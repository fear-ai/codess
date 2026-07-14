"""Executable CoSchema package, mapping, compatibility, and v2 semantics."""

from __future__ import annotations

import copy
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from codess.schema_contract import (
    APPLICATION_ID,
    FORMAT_ID,
    FORMAT_VERSION,
    UnsupportedStoreError,
    load_contract,
    load_mapping,
    require_store,
    validate_database_contract,
    validate_mapping,
    verify_package,
)
from codess.store import connect, init_db, replace_session_events


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "schema" / "coschema" / "fixtures"
sys.path.insert(0, str(ROOT / "tools"))
from coschema_gate import compare, required  # noqa: E402


def load_fixture(kind: str, name: str) -> dict:
    return json.loads((FIXTURES / kind / name).read_text(encoding="utf-8"))


def test_released_package_and_mapping_specs_validate():
    assert len(verify_package()) == 64
    contract = load_contract()
    assert contract["format_id"] == FORMAT_ID
    assert contract["format_version"] == FORMAT_VERSION
    for name in ("claude", "codex", "cursor"):
        mapping = load_mapping(name)
        assert validate_mapping(mapping) == []
        assert mapping["rules"]
        assert mapping["hazards"]


def test_new_store_has_durable_identity_and_contract_tables(tmp_path):
    path = tmp_path / "store.db"
    init_db(path)
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        assert conn.execute("PRAGMA user_version").fetchone()[0] == FORMAT_VERSION
        assert validate_database_contract(conn) == []
        meta = dict(conn.execute("SELECT key, value FROM store_meta"))
        assert meta["format_id"] == FORMAT_ID
        assert meta["format_version"] == str(FORMAT_VERSION)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "sources", "sessions", "interactions", "model_turns", "events",
            "tool_invocations", "tool_results", "artifacts",
            "mapping_diagnostics", "correlation_assertions",
        } <= tables
        assert require_store(conn, write=False) == FORMAT_VERSION
    finally:
        conn.close()


def test_writer_refuses_legacy_store_but_reader_can_identify_it(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY)")
    conn.commit()
    assert require_store(conn, write=False, allow_legacy_read=True) == 1
    with pytest.raises(UnsupportedStoreError):
        require_store(conn, write=True)
    conn.close()
    with pytest.raises(UnsupportedStoreError):
        init_db(path)


def test_null_vendor_times_do_not_use_source_mtime(tmp_path):
    session = load_fixture("edge", "null-session-times.json")
    path = tmp_path / "store.db"
    init_db(path)
    conn = connect(path)
    replace_session_events(
        conn,
        session,
        [{"session_id": session["id"], "event_id": "1", "content": "x"}],
        session_id=session["id"],
    )
    conn.commit()
    row = conn.execute(
        "SELECT started_at, source_mtime, time_basis FROM sessions"
    ).fetchone()
    assert row["started_at"] is None
    assert row["source_mtime"] == session["source_mtime"]
    assert row["time_basis"] == "unknown"
    conn.close()


def test_event_graph_tools_and_artifacts_are_materialized(tmp_path):
    path = tmp_path / "project" / ".codess" / "store.db"
    path.parent.mkdir(parents=True)
    source = tmp_path / "source.jsonl"
    source.write_text("{}\n", encoding="utf-8")
    init_db(path)
    conn = connect(path)
    session = {
        "id": "s1", "source": "Codex", "type": "Code",
        "project_path": str(tmp_path / "project"), "started_at": None,
    }
    events = [
        {"session_id": "s1", "event_id": "1", "event_type": "user_message", "subtype": "prompt", "role": "user", "content": "read it", "source_file": str(source)},
        {"session_id": "s1", "event_id": "2", "event_type": "tool_call", "role": "assistant", "tool_name": "Read", "tool_input": '{"path":"README.md"}', "metadata": '{"call_id":"c1","status":"completed"}', "source_file": str(source)},
        {"session_id": "s1", "event_id": "3", "event_type": "user_message", "subtype": "tool_result", "role": "user", "tool_name": "Read", "content": "body", "tool_output": "body", "metadata": '{"call_id":"c1"}', "source_file": str(source)},
    ]
    replace_session_events(conn, session, events, session_id="s1")
    conn.commit()
    assert [r[0] for r in conn.execute("SELECT sequence_no FROM events ORDER BY sequence_no")] == [1, 2, 3]
    assert conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM model_turns").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM tool_invocations").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM tool_results").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM event_artifacts").fetchone()[0] == 1
    call = conn.execute("SELECT source_status, normalized_status FROM tool_invocations").fetchone()
    assert tuple(call) == ("completed", "succeeded")
    conn.close()


def test_unlinked_tool_result_is_preserved_with_diagnostic(tmp_path):
    path = tmp_path / "store.db"
    init_db(path)
    conn = connect(path)
    event = {
        "session_id": "s1", "event_id": "result", "event_type": "user_message",
        "subtype": "tool_result", "role": "user", "content": "orphan",
    }
    replace_session_events(
        conn, {"id": "s1", "source": "Cursor", "type": "Code"}, [event],
        session_id="s1",
    )
    conn.commit()
    result = conn.execute(
        "SELECT invocation_id, output_text FROM tool_results"
    ).fetchone()
    assert tuple(result) == (None, "orphan")
    diagnostic = conn.execute(
        "SELECT level, reason_code FROM mapping_diagnostics"
    ).fetchone()
    assert tuple(diagnostic) == ("field", "missing_tool_call_id")
    conn.close()


def test_negative_sequence_fixture_is_rejected_by_sqlite(tmp_path):
    bad = load_fixture("negative", "event-sequence-zero.json")
    path = tmp_path / "store.db"
    init_db(path)
    conn = connect(path)
    replace_session_events(
        conn,
        {"id": bad["session_id"], "source": "Claude", "type": "Code"},
        [],
        session_id=bad["session_id"],
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO events(session_id,event_id,sequence_no) VALUES (?,?,?)",
            (bad["session_id"], bad["event_id"], bad["sequence_no"]),
        )
    conn.close()


def test_evolution_gate_classifies_and_fails_closed():
    old = load_contract()
    additive = copy.deepcopy(old)
    additive["entities"]["sessions"]["fields"]["optional_new"] = {
        "type": "text", "nullable": True
    }
    findings = list(compare(old, additive))
    assert required(findings) == "compatible"

    breaking = copy.deepcopy(old)
    del breaking["entities"]["events"]["fields"]["event_id"]
    assert required(list(compare(old, breaking))) == "breaking"

    unknown = copy.deepcopy(old)
    unknown["future_rule"] = True
    assert required(list(compare(old, unknown))) == "manual"
