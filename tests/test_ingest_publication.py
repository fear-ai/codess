"""Direct tests for the publication phases extracted from the Project loop.

These were the last domain transactions inside `cli.ingest_cmd.run()`: catalog
resync, Artifact correlation, content-processing records, rebuild promotion,
and snapshot creation. Each is now callable on its own, which is what makes
the failure modes below testable -- particularly the two that are otherwise
reachable only by arranging a failed rebuild over an existing store.
"""

from __future__ import annotations

import json
from pathlib import Path

from codess.config import get_state_path, get_store_path
from codess.ingest_publication import (
    VENDOR_DISPLAY_NAMES,
    VENDOR_SOURCE_KEYS,
    PublicationOutcome,
    correlate_project_artifacts,
    current_snapshot_id,
    current_snapshot_is_sealed,
    promote_rebuilt_stores,
    publish_snapshot,
    record_content_processing,
    resync_project_catalog,
)
from codess.project_catalog import ensure_project_binding
from codess.store import connect, init_db, sync_project_catalog


class Locator:
    """The minimum a publication phase needs: store paths and settings."""

    def __init__(self, root: Path, **options):
        self.root = root
        self.options = {
            "raw_mode": "reference", "candidate_snapshot": False, "redact": False,
        }
        self.options.update(options)

    def store_path(self, project_path: Path, source_key: str) -> Path:
        return get_store_path(project_path, VENDOR_DISPLAY_NAMES[source_key])

    def __getitem__(self, key):
        return self.options[key]


def entry_for(project_path: Path) -> dict:
    store_root = project_path.parent / "_registry"
    store_root.mkdir(parents=True, exist_ok=True)
    return ensure_project_binding(store_root, project_path)


def make_store(project_path: Path, source_key: str) -> Path:
    store_path = get_store_path(project_path, VENDOR_DISPLAY_NAMES[source_key])
    init_db(store_path)
    conn = connect(store_path)
    try:
        sync_project_catalog(conn, entry_for(project_path))
        conn.commit()
    finally:
        conn.close()
    return store_path


def silent(event, **fields) -> None:
    """A progress sink. Phases must emit; none may require a live trace."""


# --- vendor naming ----------------------------------------------------------

def test_vendor_names_and_keys_are_inverses():
    """Two tables that disagree would misattribute a store to a vendor."""
    assert {
        VENDOR_SOURCE_KEYS[display]: display
        for display in VENDOR_SOURCE_KEYS
    } == VENDOR_DISPLAY_NAMES


# --- catalog resync ---------------------------------------------------------

def test_resync_skips_stores_that_do_not_exist(tmp_path):
    """Resync reconciles existing stores; it must not provision new ones."""
    project = tmp_path / "project"
    project.mkdir()
    calls: list[str] = []
    changed = resync_project_catalog(
        Locator(tmp_path), project, entry_for(project),
        create_store=lambda key, item: calls.append(key) or True,
    )
    assert changed == set()
    assert calls == []


def test_resync_reports_the_vendors_whose_entry_changed(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    make_store(project, "cc")
    make_store(project, "codex")
    changed = resync_project_catalog(
        Locator(tmp_path), project, entry_for(project),
        create_store=lambda key, item: key == "cc",
    )
    assert changed == {"Claude"}


def test_resync_visits_every_existing_store(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    for source_key in ("cc", "codex", "cursor"):
        make_store(project, source_key)
    visited: list[str] = []
    resync_project_catalog(
        Locator(tmp_path), project, entry_for(project),
        create_store=lambda key, item: bool(visited.append(key)),
    )
    assert sorted(visited) == ["cc", "codex", "cursor"]


# --- Artifact correlation ---------------------------------------------------

def test_correlation_without_changed_vendors_does_nothing(tmp_path):
    """No store was written, so nothing is derived and no catalog is read."""
    project = tmp_path / "project"
    project.mkdir()
    assert correlate_project_artifacts(
        Locator(tmp_path), project, set(), tmp_path / "registry",
        diagnostics={}, progress_trace=silent,
    ) is False


def test_correlation_skips_a_vendor_whose_store_is_absent(tmp_path):
    """A vendor can be marked changed and still have no store under staging."""
    project = tmp_path / "project"
    project.mkdir()
    assert correlate_project_artifacts(
        Locator(tmp_path), project, {"Claude"}, tmp_path / "registry",
        diagnostics={}, progress_trace=silent,
    ) is False


def test_correlation_writes_and_reports_diagnostics(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    make_store(project, "cc")
    diagnostics: dict[str, int] = {}
    events: list[tuple] = []
    assert correlate_project_artifacts(
        Locator(tmp_path), project, {"Claude"}, tmp_path / "registry",
        diagnostics=diagnostics,
        progress_trace=lambda event, **fields: events.append((event, fields)),
    ) is True
    assert [event for event, _fields in events] == [
        "artifact_correlation.start", "artifact_correlation.done",
    ]
    assert all(key.startswith("artifact_correlation_") for key in diagnostics)


def test_correlation_accumulates_into_existing_diagnostics(tmp_path):
    """Counts are per run, so a second Project adds rather than replaces."""
    project = tmp_path / "project"
    project.mkdir()
    make_store(project, "cc")
    diagnostics = {"artifact_correlation_matched": 5}
    correlate_project_artifacts(
        Locator(tmp_path), project, {"Claude"}, tmp_path / "registry",
        diagnostics=diagnostics, progress_trace=silent,
    )
    assert diagnostics["artifact_correlation_matched"] >= 5


# --- content processing records ---------------------------------------------

def test_content_processing_without_vendors_writes_nothing(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    assert record_content_processing(
        Locator(tmp_path), project, set(),
        project_id="codess:project:x", policy={}, actions=[],
    ) is False


def test_content_processing_records_the_policy_for_a_changed_store(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    store_path = make_store(project, "cc")
    assert record_content_processing(
        Locator(tmp_path), project, {"Claude"},
        project_id=entry_for(project)["project_id"],
        policy={"redact": True},
        actions=[{"vendor": "Claude", "action": "redact"}],
    ) is True
    conn = connect(store_path, read_only=True)
    try:
        assert conn.execute("SELECT COUNT(*) FROM processing_runs").fetchone()[0] == 1
    finally:
        conn.close()


def test_content_processing_gives_each_store_only_its_own_actions(tmp_path):
    """An action names its vendor; another vendor's store must not record it."""
    project = tmp_path / "project"
    project.mkdir()
    codex_store = make_store(project, "codex")
    make_store(project, "cc")
    record_content_processing(
        Locator(tmp_path), project, {"Claude", "Codex"},
        project_id=entry_for(project)["project_id"],
        policy={"redact": True},
        actions=[{"vendor": "Claude", "action": "redact"}],
    )
    conn = connect(codex_store, read_only=True)
    try:
        [(actions,)] = conn.execute(
            "SELECT actions_json FROM processing_runs"
        ).fetchall()
    finally:
        conn.close()
    assert json.loads(actions) == []


# --- rebuild promotion ------------------------------------------------------

def staged_rebuild(tmp_path) -> tuple[Path, Path]:
    """A Project with existing stores and a completed staged rebuild."""
    project = tmp_path / "project"
    project.mkdir()
    staged = tmp_path / "staged"
    for source_key in ("cc", "codex", "cursor"):
        display = VENDOR_DISPLAY_NAMES[source_key]
        init_db(get_store_path(project, display))
        init_db(get_store_path(staged, display))
    get_state_path(staged).parent.mkdir(parents=True, exist_ok=True)
    get_state_path(staged).write_text(json.dumps({"sources": {}}), encoding="utf-8")
    return project, staged


def test_promotion_replaces_the_working_stores(tmp_path):
    project, staged = staged_rebuild(tmp_path)
    promoted = promote_rebuilt_stores(
        project, staged, ("cc", "codex", "cursor"), retain_prior=False,
    )
    assert sorted(promoted) == ["sessions_cc.db", "sessions_codex.db", "sessions_cursor.db"]
    assert not get_store_path(staged, "Claude").exists()
    assert get_store_path(project, "Claude").exists()


def test_promotion_moves_the_ingest_state_with_the_stores(tmp_path):
    """State and stores must advance together, or the next run re-reads sources."""
    project, staged = staged_rebuild(tmp_path)
    promote_rebuilt_stores(
        project, staged, ("cc", "codex", "cursor"), retain_prior=False,
    )
    assert get_state_path(project).exists()
    assert not get_state_path(staged).exists()


def test_promotion_covers_only_the_selected_sources(tmp_path):
    """A single-vendor run must not promote a store it did not rebuild."""
    project, staged = staged_rebuild(tmp_path)
    promoted = promote_rebuilt_stores(project, staged, ("cc",), retain_prior=False)
    assert promoted == ["sessions_cc.db"]
    assert get_store_path(staged, "Codex").exists()


def test_retaining_prior_data_promotes_nothing(tmp_path):
    """A failed rebuild over existing stores must not replace complete data."""
    project, staged = staged_rebuild(tmp_path)
    original = get_store_path(project, "Claude").read_bytes()
    assert promote_rebuilt_stores(
        project, staged, ("cc", "codex", "cursor"), retain_prior=True,
    ) == []
    assert get_store_path(project, "Claude").read_bytes() == original
    assert get_store_path(staged, "Claude").exists()


def test_promotion_removes_the_replaced_store_sidecars(tmp_path):
    """A journal or WAL of the replaced file would be read against the new one."""
    project, staged = staged_rebuild(tmp_path)
    target = get_store_path(project, "Claude")
    for suffix in ("-journal", "-wal", "-shm"):
        Path(str(target) + suffix).write_bytes(b"stale")
    promote_rebuilt_stores(project, staged, ("cc",), retain_prior=False)
    assert not any(
        Path(str(target) + suffix).exists() for suffix in ("-journal", "-wal", "-shm")
    )


def test_promotion_skips_a_staged_store_that_was_never_written(tmp_path):
    project, staged = staged_rebuild(tmp_path)
    get_store_path(staged, "Cursor").unlink()
    promoted = promote_rebuilt_stores(
        project, staged, ("cc", "codex", "cursor"), retain_prior=False,
    )
    assert "sessions_cursor.db" not in promoted


# --- snapshot publication ---------------------------------------------------

def raw_record(path: Path) -> dict:
    return {
        "record_type": "source_revision",
        "raw_format": "codess.raw/2",
        "source_system_key": "anthropic.claude-code",
        "storage_format": "claude-jsonl",
        "source_locator": str(path),
        "source_revision_id": "digest:" + "0" * 64,
        "observed_at": "2026-01-01T00:00:00+00:00",
        "availability": "reference",
        "capture_method": "stat",
        "consistency": "observed",
        "redaction": "none",
    }


def test_no_snapshot_is_made_without_raw_records(tmp_path):
    """A snapshot binds stores to source evidence and needs some to bind."""
    project = tmp_path / "project"
    project.mkdir()
    make_store(project, "cc")
    identity, candidate = publish_snapshot(
        Locator(tmp_path), project, [],
        raw_store=None, store_root=tmp_path / "registry",
        project_id="codess:project:x", sources=("cc",), minimum_source_size=0,
        required=True, progress_trace=silent,
    )
    assert (identity, candidate) == (None, None)


def test_an_unchanged_project_keeps_its_current_snapshot_identity(tmp_path):
    """Reporting None would read as "no snapshot" rather than "none was made"."""
    project = tmp_path / "project"
    project.mkdir()
    make_store(project, "cc")
    events: list[str] = []
    identity, candidate = publish_snapshot(
        Locator(tmp_path), project, [raw_record(tmp_path / "a.jsonl")],
        raw_store=None, store_root=tmp_path / "registry",
        project_id="codess:project:x", sources=("cc",), minimum_source_size=0,
        required=False,
        progress_trace=lambda event, **fields: events.append(event),
    )
    assert candidate is None
    assert identity == current_snapshot_id(project)
    assert events == ["snapshot.skip"]


def test_a_missing_snapshot_pointer_reads_as_no_identity(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    assert current_snapshot_id(project) is None
    assert current_snapshot_is_sealed(project) is False


# --- publication outcome ----------------------------------------------------

def test_outcome_reports_a_published_snapshot_as_current(tmp_path):
    assert PublicationOutcome(snapshot_id="s1").publication == "current_or_unchanged"


def test_outcome_reports_a_candidate_snapshot_as_candidate(tmp_path):
    outcome = PublicationOutcome(snapshot_id="s1", candidate_path="/snapshots/s1")
    assert outcome.publication == "candidate"


def test_outcome_starts_with_no_promoted_stores():
    """A mutable default shared between Projects would accumulate across them."""
    first, second = PublicationOutcome(), PublicationOutcome()
    first.promoted_stores.append("sessions_cc.db")
    assert second.promoted_stores == []


def test_snapshot_requirement_is_separate_from_a_derived_write():
    """The evidence summary is reused on the first, so they must not conflate."""
    outcome = PublicationOutcome(derived_changed=False, snapshot_required=True)
    assert (outcome.derived_changed, outcome.snapshot_required) == (False, True)


# --- module boundary --------------------------------------------------------

def test_publication_does_not_import_the_command_layer():
    import codess.ingest_publication as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "from cli" not in source
    assert "import cli" not in source


def test_the_command_module_no_longer_owns_publication_transactions():
    """The transactions live in the domain, not in the command."""
    source = Path("src/cli/ingest_cmd.py").read_text(encoding="utf-8")
    assert "create_snapshot(" not in source
    assert "os.replace(" not in source
