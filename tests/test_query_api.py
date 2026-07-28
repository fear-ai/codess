"""Typed query, reusable-result, evidence, and configuration contracts."""

import json
from pathlib import Path

import pytest

from codess.configuration_audit import audit
from codess.evidence_resolver import resolve_event
from codess.query_api import (
    QueryContractError, execute, load_document, make_request, merge_selection,
    save_document, selection_from_result,
)
from codess.raw_store import RawStore
from codess.snapshot import create_snapshot, snapshot_store_paths
from codess.store import connect, init_db, replace_session_events


def _store(tmp_path):
    project = tmp_path / "project"
    source = tmp_path / "session.jsonl"
    source.write_text('{"message":"source evidence"}\n', encoding="utf-8")
    store = project / ".codess" / "sessions_codex.db"
    init_db(store)
    conn = connect(store)
    replace_session_events(conn, {
        "id": "s1", "source": "Codex", "type": "Code",
        "project_path": str(project), "started_at": 1_000.0, "ended_at": 4_000.0,
    }, [
        {"session_id": "s1", "event_id": "e1", "event_type": "user_message",
         "subtype": "prompt", "role": "user", "content": "alpha request",
         "timestamp": 1_000.0, "source_file": str(source), "source_record_locator": "line:1"},
        {"session_id": "s1", "event_id": "e2", "event_type": "assistant_message",
         "subtype": "response", "role": "assistant", "content": "beta response",
         "timestamp": 4_000.0, "source_file": str(source), "source_record_locator": "line:1"},
    ], session_id="s1")
    conn.commit()
    conn.close()
    return project, store, source


def _scope(project, store):
    return {"conn": connect(store, read_only=True), "path": store, "project_root": project}


def test_typed_overview_events_search_and_saved_selection(tmp_path):
    project, store, _source = _store(tmp_path)
    opened = _scope(project, store)
    try:
        overview = execute([opened], make_request("overview"))
        assert overview["summary"]["sessions"] == 1
        assert overview["summary"]["events"] == 2
        assert overview["summary"]["active_time_estimates_ms_by_gap_cap_minutes"]["5"] == 3000

        search = execute([opened], make_request("search", filters={"text": "beta"}, limit=10))
        assert [row["event_id"] for row in search["rows"]] == ["e2"]
        selected = selection_from_result(search)
        events = execute([opened], merge_selection(make_request("events"), selected))
        assert [row["global_event_id"] for row in events["rows"]] == selected["event_ids"]

        saved = tmp_path / "result.json"
        save_document(saved, search)
        assert load_document(saved, "codess.query-result/1")["result_hash"] == search["result_hash"]
    finally:
        opened["conn"].close()


def test_query_rejects_unknown_or_missing_search_predicates():
    with pytest.raises(QueryContractError, match="unsupported filter"):
        make_request("events", filters={"silently_ignored": "bad"})
    with pytest.raises(QueryContractError, match="requires"):
        make_request("search")
    request = make_request("events")
    request["silently_ignored"] = True
    with pytest.raises(QueryContractError, match="request field"):
        execute([], request)


def test_request_project_scope_cannot_be_replayed_against_other_stores(tmp_path):
    project, store, _source = _store(tmp_path)
    opened = _scope(project, store)
    try:
        with pytest.raises(QueryContractError, match="project_ids"):
            execute([opened], make_request("sessions", project_ids=["wrong-project"]))
    finally:
        opened["conn"].close()


def test_sessions_exposes_vendor_path_and_obsolete_marker(tmp_path):
    project, store, _source = _store(tmp_path)
    obsolete = tmp_path / "old-project"
    conn = connect(store)
    conn.execute(
        "UPDATE sessions SET source_cwd=?,path_obsolete=1 WHERE id='s1'",
        (str(obsolete),),
    )
    conn.commit()
    conn.close()
    opened = _scope(project, store)
    try:
        row = execute([opened], make_request("sessions"))["rows"][0]
        assert row["project_path"] == str(project)
        assert row["source_project_path"] == str(obsolete)
        assert row["path_obsolete"] == 1
        assert "source_cwd" not in row
    finally:
        opened["conn"].close()


def test_search_byte_limit_bounds_tool_fields_not_only_content(tmp_path):
    project, store, _source = _store(tmp_path)
    conn = connect(store)
    conn.execute(
        "UPDATE events SET tool_input=? WHERE event_id='e1'",
        (json.dumps({"payload": "x" * 4096}),),
    )
    conn.commit()
    conn.close()
    opened = _scope(project, store)
    try:
        result = execute([opened], make_request(
            "search", filters={"text": "payload"}, byte_limit=128,
        ))
        assert result["rows"] == []
        assert result["summary"]["truncated"]
        assert result["summary"]["truncation_reasons"] == ["byte_limit"]
    finally:
        opened["conn"].close()


def test_exact_evidence_prefers_verified_sealed_object_over_changed_live(tmp_path):
    project, store, source = _store(tmp_path)
    raw = RawStore(tmp_path / "raw")
    record = raw.observe(
        source, source_system_id="openai.codex", storage_format="codex-jsonl",
        mode="capture",
    )
    conn = connect(store)
    conn.execute(
        "UPDATE sources SET availability='captured',content_sha256=?",
        (record["object_id"].removeprefix("sha256:"),),
    )
    event_id = conn.execute("SELECT global_id FROM events WHERE event_id='e1'").fetchone()[0]
    conn.commit()
    conn.close()
    snapshot = create_snapshot(project, [store], [record], raw_store=raw, seal=True)
    source.write_text("changed live evidence\n", encoding="utf-8")
    snapshot_store = snapshot_store_paths(project, snapshot.name)[0]
    opened = _scope(project, snapshot_store)
    try:
        result = resolve_event(opened, event_id)
        assert result["selected"]["kind"] == "sealed"
        assert result["selected"]["equality"] == "exact"
        assert next(c for c in result["candidates"] if c["kind"] == "live")["equality"] == "mismatch"
    finally:
        opened["conn"].close()


def test_configuration_audit_keeps_nullable_settings_independent(tmp_path):
    project, store, _source = _store(tmp_path)
    conn = connect(store)
    conn.execute("""
        INSERT INTO model_configurations(provider,model_name_exact,reasoning_effort,source_config)
        VALUES ('openai','gpt-test','high',?)
    """, (json.dumps({"model": {"field": "payload.model", "value": "gpt-test"}}),))
    conn.commit()
    conn.close()
    opened = _scope(project, store)
    try:
        report = audit([opened])
        config = report["configurations"][0]
        assert config["model_name_exact"] == "gpt-test"
        assert config["speed_tier"] is None
        assert config["provenance_state"] == "recorded"
    finally:
        opened["conn"].close()
