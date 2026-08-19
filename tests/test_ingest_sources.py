"""Direct tests for the vendor ingest coordinators and their shared helpers.

`codess/ingest_sources.py` holds the three per-vendor coordinators. Reachable only by
running a whole ingest, a failure in one of them would surface as a changed session count
several layers away. These call the module directly:
the helpers with explicit parameters, and each coordinator against a Project
fixture carrying one Session for its vendor.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cursor_fixtures import build_cursor_db

from codess.config import get_state_path, get_store_path
from codess.ingest_sources import (
    _cc_session_files,
    _collect_bounded_events,
    _ingest_cc,
    _ingest_codex,
    _ingest_cursor,
    _merge_raw_record,
    _observe_resource,
    _progress,
    _raw_record_key,
    _record_raw,
)
from codess.project import path_to_slug
from codess.project_catalog import ensure_project_binding
from codess.raw_store import RawStore
from codess.resources import ResourceLimitError
from codess.store import connect, init_db, sync_project_catalog

FIXTURES = Path(__file__).parent / "fixtures"


# --- shared option and store construction -----------------------------------

def decoder_options(**overrides) -> dict:
    """The decoder options a coordinator reads, with no per-Project state set.

    Mirrors the run-wide portion `ingest_cmd.run` builds. Kept here rather than
    imported so a change to the command module's dict shows up as a failure in
    these tests rather than passing silently through a shared constructor.
    """
    options = {
        "debug": False,
        "redact": False,
        "diagnostics": {},
        "raw_mode": "reference",
        "strict_mapping": False,
        "validate_only": False,
        "max_source_bytes": None,
        "max_cursor_container_bytes": None,
        "max_events_per_source": None,
        "max_events_per_session": None,
        "max_context_content_chars": None,
        "resource_observations": [],
        "content_failure_reviews": [],
        "claude_session_kinds": {"main": 0, "subagent": 0},
        # Per-Project state, as `_begin_project` would set it.
        "project_id": "codess:project:test",
        "location_id": "codess:location:test",
        "content_actions": [],
        "raw_records": [],
        "raw_store": None,
        "raw_records_changed": False,
        "external_sources": [],
    }
    options.update(overrides)
    return options


def project_entry(project_path: Path) -> dict:
    """The Project entry a store is created against.

    Built through `ensure_project_binding` rather than by hand so these tests
    exercise the same identity and location record the command layer supplies;
    a hand-written entry would drift from the catalog contract unnoticed.
    """
    store_root = project_path.parent / "_registry"
    store_root.mkdir(parents=True, exist_ok=True)
    return ensure_project_binding(store_root, project_path)


def make_store(project_path: Path, display: str) -> Path:
    """Create one vendor's store the way `VendorStore.create` does."""
    store_path = get_store_path(project_path, display)
    init_db(store_path)
    conn = connect(store_path)
    try:
        sync_project_catalog(conn, project_entry(project_path))
        conn.commit()
    finally:
        conn.close()
    return store_path


def store_counts(store_path: Path) -> tuple[int, int]:
    conn = connect(store_path, read_only=True)
    try:
        sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        conn.close()
    return sessions, events


# --- progress emission ------------------------------------------------------

def test_progress_is_silent_without_a_callback():
    """Every coordinator emits progress; none may require a consumer."""
    _progress(decoder_options(), "source.start", project="p")


def test_progress_forwards_event_and_fields():
    seen: list[tuple] = []
    opts = decoder_options(progress=lambda event, **fields: seen.append((event, fields)))
    _progress(opts, "source.done", vendor="Claude", events=7)
    assert seen == [("source.done", {"vendor": "Claude", "events": 7})]


# --- raw-record identity and merge ------------------------------------------

def raw_record(**overrides) -> dict:
    record = {
        "record_type": "source_revision",
        "source_system_id": "anthropic.claude-code",
        "source_locator": "/sources/a.jsonl",
        "parent_source_locator": None,
        "relation_kind": None,
        "source_revision_id": "rev-1",
        "object_id": "sha256:aaa",
    }
    record.update(overrides)
    return record


def test_raw_record_key_ignores_the_revision():
    """A key names a logical source, so two revisions of it must collide."""
    first = _raw_record_key(raw_record(source_revision_id="rev-1"))
    second = _raw_record_key(raw_record(source_revision_id="rev-2"))
    assert first == second


def test_raw_record_key_separates_distinct_locators():
    assert _raw_record_key(raw_record()) != _raw_record_key(
        raw_record(source_locator="/sources/b.jsonl")
    )


def test_raw_record_key_separates_a_relation_from_its_parent():
    """A related capture is a different logical record than its parent source."""
    assert _raw_record_key(raw_record()) != _raw_record_key(
        raw_record(parent_source_locator="/sources/a.jsonl", relation_kind="external")
    )


def test_merging_a_new_source_reports_a_change():
    records: list[dict] = []
    assert _merge_raw_record(records, raw_record()) is True
    assert len(records) == 1


def test_merging_an_unchanged_revision_reports_no_change():
    """Re-observing the same revision must not mark the snapshot stale."""
    records = [raw_record()]
    assert _merge_raw_record(records, raw_record()) is False
    assert len(records) == 1


def test_merging_a_new_revision_replaces_in_place():
    records = [raw_record()]
    assert _merge_raw_record(records, raw_record(source_revision_id="rev-2")) is True
    assert len(records) == 1
    assert records[0]["source_revision_id"] == "rev-2"


def test_merging_a_new_object_reports_a_change():
    """Capture can change the stored object while the revision id is stable."""
    records = [raw_record()]
    assert _merge_raw_record(records, raw_record(object_id="sha256:bbb")) is True
    assert records[0]["object_id"] == "sha256:bbb"


def test_merging_keeps_unrelated_records():
    records = [raw_record(source_locator="/sources/b.jsonl")]
    _merge_raw_record(records, raw_record())
    assert len(records) == 2


# --- raw observation --------------------------------------------------------

def test_record_raw_without_a_store_is_a_no_op():
    """Preflight runs with no raw store and must not fail on that account."""
    opts = decoder_options(raw_store=None)
    _record_raw(opts, Path("/nonexistent"), "Claude")
    assert opts["raw_records"] == []
    assert opts["raw_records_changed"] is False


def test_record_raw_observes_a_source_and_marks_the_change(tmp_path):
    source = tmp_path / "session.jsonl"
    source.write_text('{"type":"user"}\n', encoding="utf-8")
    opts = decoder_options(raw_store=RawStore(tmp_path / "raw"))
    _record_raw(opts, source, "Claude")
    assert opts["raw_records_changed"] is True
    [record] = opts["raw_records"]
    assert record["source_system_id"] == "anthropic.claude-code"
    assert record["source_locator"] == str(source.resolve())


def test_record_raw_twice_reports_one_change(tmp_path):
    """An unchanged source re-observed must not trigger a new snapshot."""
    source = tmp_path / "session.jsonl"
    source.write_text('{"type":"user"}\n', encoding="utf-8")
    opts = decoder_options(raw_store=RawStore(tmp_path / "raw"))
    _record_raw(opts, source, "Claude")
    opts["raw_records_changed"] = False
    _record_raw(opts, source, "Claude")
    assert opts["raw_records_changed"] is False
    assert len(opts["raw_records"]) == 1


def test_record_raw_writes_source_availability_into_the_store(tmp_path):
    """The `sources` row carries the capture evidence the record established."""
    project = tmp_path / "project"
    project.mkdir()
    store_path = make_store(project, "Claude")
    source = tmp_path / "session.jsonl"
    source.write_text('{"type":"user"}\n', encoding="utf-8")
    conn = connect(store_path)
    try:
        conn.execute(
            """
            INSERT INTO sources(
              source_entity_id, source_system_id, source_path, storage_format,
              source_revision, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "codess:source_revision:test", "anthropic.claude-code", str(source),
                "claude-jsonl", "rev-1", "2026-01-01T00:00:00+00:00",
            ),
        )
        opts = decoder_options(raw_store=RawStore(tmp_path / "raw"))
        _record_raw(opts, source, "Claude", conn, source_path=str(source))
        conn.commit()
        availability, method = conn.execute(
            "SELECT availability, capture_method FROM sources"
        ).fetchone()
    finally:
        conn.close()
    assert availability == "reference"
    assert method


# --- bounded event collection -----------------------------------------------

def events(count: int, session_id: str = "s1"):
    for index in range(count):
        yield {"session_id": session_id, "sequence_no": index, "timestamp": index}


def collect(opts, produced, session_id="s1"):
    return _collect_bounded_events(
        opts, produced, session_id,
        project="/projects/p", vendor="Claude", source="/sources/a.jsonl",
    )


def test_collection_buckets_every_event_under_the_named_session():
    """The session identity is the caller's, not each event's.

    Collection is called once per source with the session that source belongs
    to, so events are attributed to that session rather than to a per-event
    field. A caller that passed the wrong identity would silently reattribute
    a whole source, which is why the contract is stated here.
    """
    produced = [{"sequence_no": 0}, {"sequence_no": 1}]
    assert len(collect(decoder_options(), iter(produced), "s1")) == 2


def test_collection_returns_every_event_when_unbounded():
    assert len(collect(decoder_options(), events(2500))) == 2500


def test_collection_rejects_a_source_over_its_event_bound():
    """The bound is a rejection, not a truncation: partial data is not stored."""
    opts = decoder_options(max_events_per_source=10)
    with pytest.raises(ResourceLimitError) as excinfo:
        collect(opts, events(11))
    assert excinfo.value.limit_kind == "source_events"


def test_collection_rejects_a_session_over_its_event_bound():
    opts = decoder_options(max_events_per_session=5)
    with pytest.raises(ResourceLimitError) as excinfo:
        collect(opts, events(6))
    assert excinfo.value.limit_kind == "session_events"


def test_collection_accepts_a_source_exactly_at_its_bound():
    """Off-by-one at the limit would reject valid sources."""
    opts = decoder_options(max_events_per_source=10)
    assert len(collect(opts, events(10))) == 10


def test_collection_reports_progress_while_reading():
    seen: list[dict] = []
    opts = decoder_options(
        progress=lambda event, **fields: seen.append({"event": event, **fields}),
    )
    collect(opts, events(2000))
    mapped = [record for record in seen if record["event"] == "source.map.progress"]
    assert mapped, "a long source must report progress before it completes"
    assert mapped[0]["vendor"] == "Claude"


# --- resource observation ---------------------------------------------------

def test_resource_observation_records_the_source_and_its_events(tmp_path):
    source = tmp_path / "session.jsonl"
    source.write_text("x" * 64, encoding="utf-8")
    opts = decoder_options()
    _observe_resource(opts, source, {"s1": [{"content": "hello"}, {"content": "hi"}]})
    [observation] = opts["resource_observations"]
    assert observation["source"] == str(source)
    assert observation["source_bytes"] == 64
    assert observation["events"] == 2
    assert observation["largest_session_events"] == 2


def test_resource_observation_rejects_events_over_the_bound(tmp_path):
    """Observation applies the same bounds as collection, on the whole source."""
    source = tmp_path / "session.jsonl"
    source.write_text("x", encoding="utf-8")
    opts = decoder_options(max_events_per_source=1)
    with pytest.raises(ResourceLimitError):
        _observe_resource(opts, source, {"s1": [{}, {}]})


# --- Claude Code source selection -------------------------------------------

def test_cc_session_files_finds_main_transcripts(tmp_path):
    (tmp_path / "a.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "b.jsonl").write_text("", encoding="utf-8")
    assert [parent for _path, parent in _cc_session_files(tmp_path)] == [None, None]


def test_cc_session_files_attributes_nested_subagents_to_their_parent(tmp_path):
    nested = tmp_path / "main-session" / "subagents" / "agent-1"
    nested.mkdir(parents=True)
    (nested / "sub.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "main-session.jsonl").write_text("", encoding="utf-8")
    parents = {
        path.name: parent for path, parent in _cc_session_files(tmp_path)
    }
    assert parents["main-session.jsonl"] is None
    assert parents["sub.jsonl"] == "main-session"


def test_cc_session_files_are_ordered_deterministically(tmp_path):
    for name in ("c.jsonl", "a.jsonl", "b.jsonl"):
        (tmp_path / name).write_text("", encoding="utf-8")
    names = [path.name for path, _parent in _cc_session_files(tmp_path)]
    assert names == sorted(names)


def test_cc_session_files_ignores_unrelated_files(tmp_path):
    (tmp_path / "a.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    assert len(_cc_session_files(tmp_path)) == 1


# --- coordinator: Claude Code -----------------------------------------------

@pytest.fixture
def cc_project(tmp_path, monkeypatch):
    """A Project with one Claude Code transcript in a private projects tree.

    The source-location constants are read at import, so the binding in each
    consuming module is replaced rather than the environment variable that
    produced it; setting the variable after import would have no effect.
    """
    project = tmp_path / "myproj"
    project.mkdir()
    projects_dir = tmp_path / "cc_projects"
    session_dir = projects_dir / path_to_slug(project.resolve())
    session_dir.mkdir(parents=True)
    source = session_dir / "test-session.jsonl"
    source.write_text(
        (FIXTURES / "sample.jsonl").read_text(encoding="utf-8"), encoding="utf-8",
    )
    monkeypatch.setattr("codess.project.CC_PROJECTS", projects_dir)
    return project, source


def run_cc(project, opts, *, force=True, min_size=0, stop_on_error=False):
    store_path = make_store(project, "Claude")
    result = _ingest_cc(
        project, store_path, get_state_path(project), opts, force, min_size,
        stop_on_error=stop_on_error,
    )
    return result, store_path


def test_cc_coordinator_reports_what_it_stored(cc_project):
    project, _source = cc_project
    (ingested, events_processed, failures, changed), store_path = run_cc(
        project, decoder_options(),
    )
    assert (ingested, failures, changed) == (1, 0, True)
    assert events_processed > 0
    assert store_counts(store_path) == (1, events_processed)


def test_cc_coordinator_without_a_session_directory_does_nothing(tmp_path, monkeypatch):
    """A Project with no Claude Code sources is not an error."""
    monkeypatch.setattr("codess.project.CC_PROJECTS", tmp_path / "empty")
    project = tmp_path / "myproj"
    project.mkdir()
    store_path = make_store(project, "Claude")
    assert _ingest_cc(
        project, store_path, get_state_path(project), decoder_options(), True, 0,
        stop_on_error=False,
    ) == (0, 0, 0, False)


def test_cc_coordinator_records_the_source_as_raw_evidence(cc_project, tmp_path):
    project, source = cc_project
    opts = decoder_options(raw_store=RawStore(tmp_path / "raw"))
    run_cc(project, opts)
    locators = {record["source_locator"] for record in opts["raw_records"]}
    assert str(source.resolve()) in locators
    assert opts["raw_records_changed"] is True


def test_cc_coordinator_counts_the_session_kind(cc_project):
    """Main and subagent transcripts are counted separately for the report."""
    project, _source = cc_project
    opts = decoder_options()
    run_cc(project, opts)
    assert opts["claude_session_kinds"]["main"] == 1
    assert opts["claude_session_kinds"]["subagent"] == 0


def test_cc_coordinator_skips_an_unchanged_source_without_force(cc_project):
    """Incremental state is what makes a second ingest cheap."""
    project, _source = cc_project
    store_path = make_store(project, "Claude")
    state_path = get_state_path(project)
    first = _ingest_cc(
        project, store_path, state_path, decoder_options(), True, 0,
        stop_on_error=False,
    )
    second = _ingest_cc(
        project, store_path, state_path, decoder_options(), False, 0,
        stop_on_error=False,
    )
    assert first[0] == 1
    assert second == (0, 0, 0, False)


def test_cc_coordinator_counts_a_rejected_source_as_a_failure(cc_project):
    """Without stop_on_error a rejection is counted and the run continues."""
    project, _source = cc_project
    opts = decoder_options(max_events_per_source=1)
    (ingested, _events, failures, _changed), store_path = run_cc(project, opts)
    assert (ingested, failures) == (0, 1)
    assert store_counts(store_path) == (0, 0)


def test_cc_coordinator_raises_on_a_rejected_source_when_told_to_stop(cc_project):
    """stop_on_error is the difference between a report and a halt."""
    project, _source = cc_project
    opts = decoder_options(max_events_per_source=1)
    with pytest.raises(ResourceLimitError):
        run_cc(project, opts, stop_on_error=True)


def test_cc_coordinator_observes_resources_for_each_source(cc_project):
    project, source = cc_project
    opts = decoder_options()
    run_cc(project, opts)
    observed = {record["source"] for record in opts["resource_observations"]}
    assert str(source) in observed


# --- coordinator: Codex -----------------------------------------------------

@pytest.fixture
def codex_project(tmp_path, monkeypatch):
    """A Project with one Codex rollout naming it as the session cwd."""
    project = tmp_path / "myproj"
    project.mkdir()
    sessions_root = tmp_path / "codex" / "sessions"
    day = sessions_root / "2026" / "01" / "02"
    day.mkdir(parents=True)
    source = day / "rollout-abc.jsonl"
    source.write_text(
        json.dumps({
            "type": "session_meta",
            "payload": {"id": "s1", "cwd": str(project.resolve())},
        }) + "\n"
        + json.dumps({
            "type": "response_item",
            "payload": {
                "type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "Hi"}],
            },
        }) + "\n"
        + json.dumps({
            "type": "response_item",
            "payload": {
                "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": "Hello"}],
            },
        }) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("codess.codex_source.CODEX_SESSIONS", sessions_root)
    monkeypatch.setattr(
        "codess.codex_source.CODEX_ARCHIVED_SESSIONS", sessions_root / "archived",
    )
    return project, source


def run_codex(project, opts, *, force=True, min_size=0, stop_on_error=False):
    store_path = make_store(project, "Codex")
    result = _ingest_codex(
        project, store_path, get_state_path(project), opts, force, min_size,
        stop_on_error=stop_on_error,
    )
    return result, store_path


def test_codex_coordinator_reports_what_it_stored(codex_project):
    project, _source = codex_project
    (ingested, events_processed, failures, changed), store_path = run_codex(
        project, decoder_options(),
    )
    assert (ingested, failures, changed) == (1, 0, True)
    assert events_processed == 2
    assert store_counts(store_path) == (1, 2)


def test_codex_coordinator_without_sources_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("codess.codex_source.CODEX_SESSIONS", tmp_path / "empty")
    monkeypatch.setattr(
        "codess.codex_source.CODEX_ARCHIVED_SESSIONS", tmp_path / "empty-archived",
    )
    project = tmp_path / "myproj"
    project.mkdir()
    store_path = make_store(project, "Codex")
    assert _ingest_codex(
        project, store_path, get_state_path(project), decoder_options(), True, 0,
        stop_on_error=False,
    ) == (0, 0, 0, False)


def test_codex_coordinator_records_the_source_as_raw_evidence(codex_project, tmp_path):
    project, source = codex_project
    opts = decoder_options(raw_store=RawStore(tmp_path / "raw"))
    run_codex(project, opts)
    locators = {record["source_locator"] for record in opts["raw_records"]}
    assert str(source.resolve()) in locators


def test_codex_coordinator_skips_an_unchanged_source_without_force(codex_project):
    project, _source = codex_project
    store_path = make_store(project, "Codex")
    state_path = get_state_path(project)
    _ingest_codex(
        project, store_path, state_path, decoder_options(), True, 0,
        stop_on_error=False,
    )
    assert _ingest_codex(
        project, store_path, state_path, decoder_options(), False, 0,
        stop_on_error=False,
    ) == (0, 0, 0, False)


def test_codex_coordinator_rejects_a_source_over_its_event_bound(codex_project):
    project, _source = codex_project
    opts = decoder_options(max_events_per_source=1)
    with pytest.raises(ResourceLimitError):
        run_codex(project, opts, stop_on_error=True)


def test_codex_coordinator_counts_a_rejected_source_as_a_failure(codex_project):
    """Without stop_on_error a rejection is reported rather than raised."""
    project, _source = codex_project
    opts = decoder_options(max_events_per_source=1)
    (ingested, _events, failures, _changed), store_path = run_codex(project, opts)
    assert ingested == 0
    assert failures == 1
    assert store_counts(store_path) == (0, 0)


# --- coordinator: Cursor ----------------------------------------------------

@pytest.fixture
def cursor_project(tmp_path, monkeypatch):
    """A Project with one Cursor workspace database holding one composer."""
    project = tmp_path / "myproj"
    project.mkdir()
    cursor_base = tmp_path / "cursor" / "User"
    workspace = cursor_base / "workspaceStorage" / "abc123"
    workspace.mkdir(parents=True)
    (workspace / "workspace.json").write_text(
        json.dumps({"folder": {"path": str(project)}}), encoding="utf-8",
    )
    database = build_cursor_db(
        workspace / "state.vscdb",
        bubbles=[
            ("c1", "b1", {"type": 1, "text": "hi", "createdAt": "2026-07-10T00:00:01Z"}),
            ("c1", "b2", {"type": 2, "text": "ok", "createdAt": "2026-07-10T00:00:02Z"}),
        ],
    )
    monkeypatch.setattr("codess.cursor_source.CURSOR_DATA", cursor_base)
    return project, database


def run_cursor(project, opts, *, force=True, stop_on_error=False):
    store_path = make_store(project, "Cursor")
    result = _ingest_cursor(
        project, store_path, get_state_path(project), opts, force,
        stop_on_error=stop_on_error,
    )
    return result, store_path


def test_cursor_coordinator_reports_what_it_stored(cursor_project):
    project, _database = cursor_project
    (ingested, events_processed, failures, changed), store_path = run_cursor(
        project, decoder_options(),
    )
    assert (ingested, failures, changed) == (1, 0, True)
    assert events_processed == 2
    assert store_counts(store_path) == (1, 2)


def test_cursor_coordinator_without_a_workspace_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("codess.cursor_source.CURSOR_DATA", tmp_path / "empty")
    project = tmp_path / "myproj"
    project.mkdir()
    store_path = make_store(project, "Cursor")
    assert _ingest_cursor(
        project, store_path, get_state_path(project), decoder_options(), True,
        stop_on_error=False,
    ) == (0, 0, 0, False)


def test_cursor_coordinator_records_the_container_as_raw_evidence(
    cursor_project, tmp_path,
):
    project, database = cursor_project
    opts = decoder_options(raw_store=RawStore(tmp_path / "raw"))
    run_cursor(project, opts)
    locators = {record["source_locator"] for record in opts["raw_records"]}
    assert str(database.resolve()) in locators


def test_cursor_coordinator_rejects_a_source_over_its_event_bound(cursor_project):
    project, _database = cursor_project
    opts = decoder_options(max_events_per_source=1)
    with pytest.raises(ResourceLimitError):
        run_cursor(project, opts, stop_on_error=True)


def test_cursor_coordinator_attributes_events_to_the_project(cursor_project):
    project, _database = cursor_project
    _result, store_path = run_cursor(project, decoder_options())
    conn = connect(store_path, read_only=True)
    try:
        paths = {row[0] for row in conn.execute("SELECT project_path FROM sessions")}
    finally:
        conn.close()
    assert paths == {str(project.resolve())}


# --- module boundary --------------------------------------------------------

def test_coordinators_do_not_import_the_command_layer():
    """The domain module must not depend on the layer that calls it."""
    import codess.ingest_sources as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "from cli" not in source
    assert "import cli" not in source
