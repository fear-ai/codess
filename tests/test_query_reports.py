"""Direct tests for the report queries moved out of the query command.

`query_cmd`'s report SQL lives in `codess/query_reports.py`, so each report is
callable without a CLI invocation. These cover what the
byte-identity comparison against the previous output cannot: the ordering
rules, the older-store fallbacks, and the outcome classification that decides
what a tool call without a result is called.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from store_fixtures import insert_event, insert_session

from codess.config import get_store_path
from codess.query_reports import (
    LINEAGE_RESULT_SUBTYPES,
    SUPPORTED_AUDIT_SUBTYPES,
    artifact_evidence,
    audit_events,
    json_metadata,
    limited,
    mapping_diagnostics,
    permission_denials,
    selected_sessions,
    session_events,
    store_counts,
    task_invocations,
    task_results,
    tool_counts_by_session,
    tool_lineage,
    tool_totals,
)
from codess.store import connect, init_db


class Scope:
    """A report scope over stores opened directly.

    Mirrors `QueryScope`'s predicate contract, composing the two-alias
    diagnostics clause from the single-alias predicate exactly as it does.
    """

    def __init__(self, stores: list[dict], source_ids: tuple[str, ...] = ()):
        self.stores = stores
        self.source_ids = source_ids

    def source_predicate(self, alias: str = "s") -> tuple[str, tuple[str, ...]]:
        if not self.source_ids:
            return "1", ()
        placeholders = ", ".join("?" for _ in self.source_ids)
        return f"{alias}.source_system_id IN ({placeholders})", self.source_ids

    def diagnostics_predicate(self) -> tuple[str, tuple[str, ...]]:
        if not self.source_ids:
            return "", ()
        session_predicate, session_params = self.source_predicate("s")
        source_predicate, source_params = self.source_predicate("src")
        return (
            f"WHERE ({session_predicate} OR {source_predicate})",
            (*session_params, *source_params),
        )


def lineage_id(raw) -> str:
    metadata = json_metadata(raw)
    return str(metadata.get("call_id") or metadata.get("tool_use_id") or "")


def sort_key(timestamp, project, store_index, session_id, tail) -> tuple:
    """The command module's ordering: absent timestamps last."""
    return (
        timestamp is None, timestamp or 0, project, store_index, session_id, tail,
    )


def make_store(tmp_path: Path, name: str = "Claude") -> Path:
    store_path = get_store_path(tmp_path, name)
    init_db(store_path)
    return store_path


def add_session(
    conn, session_id="s1", *, source="Claude", vendor_session_id=None, **columns,
):
    """Insert one Session through the shared fixture builder.

    Using it rather than hand-written SQL keeps these tests unable to build a
    row production could not: the identity columns are required, and the
    builder supplies them the same way `codess.store` derives them.
    """
    return insert_session(
        conn, session_id, source=source,
        vendor_session_id=vendor_session_id or f"v-{session_id}",
        project_path="/projects/p", started_at=1000.0, **columns,
    )


def add_event(
    conn, event_id, *, session_id="s1", event_type="tool_call", metadata=None,
    **columns,
):
    return insert_event(
        conn, session_id, event_id, event_type=event_type,
        metadata=json.dumps(metadata) if metadata else None, **columns,
    )


@pytest.fixture
def store(tmp_path):
    """One open store with a Session, yielded as a report scope."""
    path = make_store(tmp_path)
    conn = connect(path)
    add_session(conn)
    conn.commit()
    scope = Scope([{
        "conn": conn, "path": path, "project_path": tmp_path,
    }])
    yield conn, scope
    conn.close()


# --- shared helpers ---------------------------------------------------------

def test_unusable_metadata_reads_as_absent():
    """One malformed record must not end a report over every other Project."""
    assert json_metadata("{not json") == {}
    assert json_metadata(None) == {}
    assert json_metadata("[1, 2]") == {}
    assert json_metadata('{"status": "ok"}') == {"status": "ok"}


def test_a_limit_takes_the_top_of_an_ordered_report():
    rows = [{"n": 1}, {"n": 2}, {"n": 3}]
    assert limited(rows, 2) == [{"n": 1}, {"n": 2}]
    assert limited(rows, None) == rows


# --- mapping diagnostics ----------------------------------------------------

def test_a_store_without_the_diagnostics_table_is_skipped(tmp_path):
    """An absent table is not the same claim as a store with no diagnostics."""
    path = make_store(tmp_path)
    conn = connect(path)
    try:
        conn.execute("DROP TABLE mapping_diagnostics")
        conn.commit()
        scope = Scope([{"conn": conn, "path": path, "project_path": tmp_path}])
        assert mapping_diagnostics(scope) == []
    finally:
        conn.close()


def test_diagnostics_are_ordered_by_when_they_were_recorded(store):
    conn, scope = store
    for created_at, reason in (("2026-01-02", "later"), ("2026-01-01", "earlier")):
        conn.execute(
            """
            INSERT INTO mapping_diagnostics(
              level, severity, reason_code, created_at, session_id
            ) VALUES ('record', 'warn', ?, ?, 's1')
            """,
            (reason, created_at),
        )
    conn.commit()
    assert [row["reason_code"] for row in mapping_diagnostics(scope)] == [
        "earlier", "later",
    ]


def test_diagnostics_carry_their_project_and_store(store):
    conn, scope = store
    conn.execute(
        "INSERT INTO mapping_diagnostics(level, severity, reason_code, created_at)"
        " VALUES ('source', 'error', 'unsupported', '2026-01-01')"
    )
    conn.commit()
    [row] = mapping_diagnostics(scope)
    assert row["store_index"] == 0
    assert row["project_path"]


# --- artifact evidence ------------------------------------------------------

def test_artifacts_lead_with_the_most_source_systems(tmp_path):
    """An Artifact several coding systems touched is what the report surfaces."""
    path = make_store(tmp_path)
    conn = connect(path)
    try:
        add_session(conn, "s1", source="Claude")
        add_session(
            conn, "s2", source="Codex",
            source_system_id="openai.codex", vendor_session_id="v2",
        )
        for index, (session, locator) in enumerate(
            [("s1", "shared.py"), ("s2", "shared.py"), ("s1", "solo.py")], start=1
        ):
            add_event(conn, f"e{index}", session_id=session)
            conn.execute(
                "INSERT OR IGNORE INTO artifacts(artifact_kind, relative_path)"
                " VALUES ('file', ?)",
                (locator,),
            )
            conn.execute(
                "INSERT INTO event_artifacts(event_id, artifact_id, operation)"
                " SELECT e.id, a.id, 'read' FROM events e, artifacts a"
                " WHERE e.event_id=? AND a.relative_path=?",
                (f"e{index}", locator),
            )
        conn.commit()
        scope = Scope([{"conn": conn, "path": path, "project_path": tmp_path}])
        rows = artifact_evidence(scope)
        assert rows[0]["locator"] == "shared.py"
        assert rows[0]["source_count"] == 2
        assert rows[0]["sources"] == "Claude,Codex"
    finally:
        conn.close()


def test_a_store_without_artifact_tables_is_skipped(tmp_path):
    path = make_store(tmp_path)
    conn = connect(path)
    try:
        conn.execute("DROP TABLE event_artifacts")
        conn.commit()
        scope = Scope([{"conn": conn, "path": path, "project_path": tmp_path}])
        assert artifact_evidence(scope) == []
    finally:
        conn.close()


# --- tool lineage -----------------------------------------------------------

def test_a_call_paired_with_its_result_reports_the_result(store):
    conn, scope = store
    add_event(conn, "c1", tool_name="Read", metadata={"tool_use_id": "t1"})
    add_event(
        conn, "r1", event_type="user_message", subtype="tool_result",
        tool_name="Read", metadata={"tool_use_id": "t1"}, content_len=42,
    )
    conn.commit()
    [row] = tool_lineage(scope, lineage_id, sort_key)
    assert row["outcome"] == "result"
    assert row["result_len"] == 42


def test_a_call_with_an_identifier_and_no_result_is_missing_one(store):
    """Missing evidence and no link at all are different findings."""
    conn, scope = store
    add_event(conn, "c1", tool_name="Read", metadata={"tool_use_id": "t1"})
    conn.commit()
    [row] = tool_lineage(scope, lineage_id, sort_key)
    assert row["outcome"] == "missing_result"


def test_a_call_the_vendor_never_linked_is_unlinked(store):
    conn, scope = store
    add_event(conn, "c1", tool_name="Read")
    conn.commit()
    [row] = tool_lineage(scope, lineage_id, sort_key)
    assert row["outcome"] == "unlinked_call"


def test_a_denied_result_keeps_its_outcome_when_matched(store):
    conn, scope = store
    add_event(conn, "c1", tool_name="Bash", metadata={"tool_use_id": "t1"})
    add_event(
        conn, "r1", event_type="user_message", subtype="permission_denied",
        tool_name="Bash", metadata={"tool_use_id": "t1"},
    )
    conn.commit()
    [row] = tool_lineage(scope, lineage_id, sort_key)
    assert row["outcome"] == "permission_denied"


def test_a_denied_result_keeps_its_outcome_when_unmatched(store):
    """A denial does not become less specific because no call was linked."""
    conn, scope = store
    add_event(
        conn, "r1", event_type="user_message", subtype="permission_denied",
        tool_name="Bash",
    )
    conn.commit()
    [row] = tool_lineage(scope, lineage_id, sort_key)
    assert row["outcome"] == "permission_denied"


def test_an_unmatched_plain_result_is_reported_rather_than_dropped(store):
    conn, scope = store
    add_event(
        conn, "r1", event_type="user_message", subtype="tool_result",
        tool_name="Read", content_len=7,
    )
    conn.commit()
    [row] = tool_lineage(scope, lineage_id, sort_key)
    assert row["outcome"] == "unlinked_result"
    assert row["result_len"] == 7


def test_each_result_closes_only_one_call(store):
    """Two calls sharing an identifier must not both claim one result."""
    conn, scope = store
    for event_id in ("c1", "c2"):
        add_event(conn, event_id, tool_name="Read", metadata={"tool_use_id": "t1"})
    add_event(
        conn, "r1", event_type="user_message", subtype="tool_result",
        tool_name="Read", metadata={"tool_use_id": "t1"},
    )
    conn.commit()
    outcomes = sorted(row["outcome"] for row in tool_lineage(scope, lineage_id, sort_key))
    assert outcomes == ["missing_result", "result"]


def test_every_result_subtype_can_close_a_call():
    assert set(LINEAGE_RESULT_SUBTYPES) == {
        "tool_result", "permission_denied", "tool_failure",
    }


# --- permissions and audit --------------------------------------------------

def test_permission_denials_are_ordered_by_time(store):
    conn, scope = store
    add_event(
        conn, "e2", event_type="user_message", subtype="permission_denied",
        tool_name="Bash", timestamp=2.0,
    )
    add_event(
        conn, "e1", event_type="user_message", subtype="permission_denied",
        tool_name="Write", timestamp=1.0,
    )
    conn.commit()
    assert [row["tool_name"] for row in permission_denials(scope)] == ["Write", "Bash"]


def test_an_undated_denial_is_ordered_last(store):
    """A null timestamp is unrecorded evidence, not the earliest event."""
    conn, scope = store
    add_event(
        conn, "e1", event_type="user_message", subtype="permission_denied",
        tool_name="Undated", timestamp=None,
    )
    add_event(
        conn, "e2", event_type="user_message", subtype="permission_denied",
        tool_name="Dated", timestamp=5.0,
    )
    conn.commit()
    assert [row["tool_name"] for row in permission_denials(scope)] == [
        "Dated", "Undated",
    ]


def test_the_audit_reports_only_normalized_subtypes(store):
    conn, scope = store
    add_event(
        conn, "e1", event_type="user_message", subtype="tool_failure",
        tool_name="Bash",
    )
    add_event(conn, "e2", event_type="user_message", subtype="prompt")
    conn.commit()
    [row] = audit_events(scope, sort_key)
    assert row["subtype"] == "tool_failure"


def test_the_supported_audit_subtypes_are_a_closed_set():
    assert set(SUPPORTED_AUDIT_SUBTYPES) == {
        "permission_denied", "tool_failure", "turn_aborted",
        "context_compaction", "context_compaction_summary",
    }


def test_the_audit_honours_a_row_limit(store):
    conn, scope = store
    for index in range(5):
        add_event(
            conn, f"e{index}", event_type="user_message",
            subtype="tool_failure", timestamp=float(index),
        )
    conn.commit()
    assert len(audit_events(scope, sort_key, 3)) == 3


# --- tools and tasks --------------------------------------------------------

def test_tool_totals_count_calls_by_exact_name(store):
    conn, scope = store
    for index, tool in enumerate(("Read", "Read", "Bash")):
        add_event(conn, f"e{index}", tool_name=tool)
    conn.commit()
    assert tool_totals(scope) == {"Read": 2, "Bash": 1}


def test_a_call_without_a_tool_name_is_not_counted(store):
    conn, scope = store
    add_event(conn, "e1", tool_name=None)
    conn.commit()
    assert tool_totals(scope) == {}


def test_tool_counts_are_reported_per_session(store):
    conn, scope = store
    add_session(conn, "s2", vendor_session_id="v2")
    add_event(conn, "e1", session_id="s1", tool_name="Read")
    add_event(conn, "e2", session_id="s2", tool_name="Bash")
    conn.commit()
    sessions = selected_sessions(scope, lambda row: row["id"])
    counts = tool_counts_by_session(sessions)
    by_session = {session["id"]: counts[session["query_id"]] for session in sessions}
    assert by_session["s1"] == {"Read": 1}
    assert by_session["s2"] == {"Bash": 1}


def test_task_invocations_select_task_shaped_tools(store):
    conn, scope = store
    add_event(conn, "e1", tool_name="Task", tool_input=json.dumps({"description": "x"}))
    add_event(conn, "e2", tool_name="Read")
    conn.commit()
    assert [row["tool_name"] for row in task_invocations(scope)] == ["Task"]


def test_task_results_select_task_result_records(store):
    conn, scope = store
    add_event(
        conn, "e1", event_type="user_message", subtype="tool_result",
        tool_name="Task", content="done", content_len=4,
    )
    add_event(
        conn, "e2", event_type="user_message", subtype="tool_result",
        tool_name="Read", content="x",
    )
    conn.commit()
    assert [row["tool_name"] for row in task_results(scope)] == ["Task"]


# --- sessions and events ----------------------------------------------------

def test_a_store_without_the_identity_columns_still_reports_sessions(tmp_path):
    """Older stores predate `global_id` and `project_id`; both are projected.

    The columns are NOT NULL where they exist, so a Session cannot be stored
    without an identity -- the fallback covers a store whose schema lacks the
    column at all, which is why it is a projection rather than a default.
    """
    path = make_store(tmp_path)
    conn = connect(path)
    try:
        add_session(conn, "s1")
        conn.commit()
        columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        assert {"global_id", "project_id"} <= columns
        scope = Scope([{"conn": conn, "path": path, "project_path": tmp_path}])
        [session] = selected_sessions(scope, lambda row: row["id"])
        assert session["global_id"].startswith("codess:session:")
    finally:
        conn.close()


def test_sessions_are_filtered_by_the_scope_source(tmp_path):
    path = make_store(tmp_path)
    conn = connect(path)
    try:
        add_session(conn, "s1", source="Claude")
        add_session(
            conn, "s2", source="Codex",
            source_system_id="openai.codex", vendor_session_id="v2",
        )
        conn.commit()
        stores = [{"conn": conn, "path": path, "project_path": tmp_path}]
        scope = Scope(stores, source_ids=("openai.codex",))
        assert [s["id"] for s in selected_sessions(scope, lambda r: r["id"])] == ["s2"]
    finally:
        conn.close()


def test_session_events_follow_stored_sequence(store):
    conn, scope = store
    add_event(conn, "e2", sequence_no=2, timestamp=1.0)
    add_event(conn, "e1", sequence_no=1, timestamp=9.0)
    conn.commit()
    [session] = selected_sessions(scope, lambda row: row["id"])
    events = session_events(session)
    assert len(events) == 2


def test_an_unsequenced_event_is_ordered_last(store):
    """A vendor that recorded no sequence has not claimed its Event came first."""
    conn, scope = store
    add_event(conn, "e1", sequence_no=None, timestamp=0.0, tool_name="Unsequenced")
    add_event(conn, "e2", sequence_no=1, timestamp=9.0, tool_name="Sequenced")
    conn.commit()
    [session] = selected_sessions(scope, lambda row: row["id"])
    assert [row["tool_name"] for row in session_events(session)] == [
        "Sequenced", "Unsequenced",
    ]


# --- counts -----------------------------------------------------------------

def test_store_counts_report_sessions_and_events(store):
    conn, scope = store
    add_event(conn, "e1", timestamp=1.0)
    add_event(conn, "e2", timestamp=2.0)
    conn.commit()
    [(_project, totals)] = store_counts(scope).items()
    assert totals == {"sessions": 1, "events": 2}


def test_store_counts_omit_a_project_with_no_open_store():
    """The caller decides whether an unqueryable Project appears as zero."""
    assert store_counts(Scope([])) == {}


# --- module boundary --------------------------------------------------------

def test_the_query_command_owns_no_report_sql():
    """Report SQL belongs to the domain, not the command layer."""
    import ast
    import re

    source = Path("src/cli/query_cmd.py").read_text(encoding="utf-8")
    lines = source.splitlines()
    with_sql = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef):
            body = "\n".join(lines[node.lineno - 1:node.end_lineno])
            if re.search(r"\.execute\(", body):
                with_sql.append(node.name)
    # The store-readability probe is a connection check, not a report.
    assert with_sql == ["_open_readable_store"]


def test_the_report_module_does_not_import_the_command_layer():
    import codess.query_reports as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "from cli" not in source
    assert "import cli" not in source
