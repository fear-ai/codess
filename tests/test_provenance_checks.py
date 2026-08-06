"""End-to-end source-to-query provenance checks for the core exchange."""

import json
import sqlite3

import pytest

from codess.adapters.cc import process_file as process_claude
from codess.adapters.codex import process_file as process_codex
from codess.adapters.cursor import process_db as process_cursor
from codess.evidence_resolver import resolve_event
from codess.query_api import execute, make_request
from codess.store import connect, init_db, replace_session_events


def _write_jsonl(path, records):
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _claude_source(tmp_path):
    path = tmp_path / "claude.jsonl"
    records = [
        {
            "type": "user",
            "uuid": "user-1",
            "timestamp": "2026-07-10T12:00:00Z",
            "message": {"role": "user", "content": "Inspect the project."},
        },
        {
            "type": "user",
            "uuid": "harness-1",
            "timestamp": "2026-07-10T12:00:01Z",
            "message": {
                "role": "user",
                "content": (
                    "<local-command-stdout>Mode selected.</local-command-stdout>"
                ),
            },
        },
        {
            "type": "assistant",
            "uuid": "call-1",
            "timestamp": "2026-07-10T12:00:02Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I will inspect it."},
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "Read",
                        "input": {"path": "README.md"},
                    },
                ],
            },
        },
        {
            "type": "user",
            "uuid": "result-1",
            "parentUuid": "call-1",
            "timestamp": "2026-07-10T12:00:03Z",
            "message": {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "tool-1",
                    "content": "Permission for this tool use was denied.",
                    "is_error": True,
                }],
            },
        },
        {
            "type": "assistant",
            "uuid": "response-1",
            "timestamp": "2026-07-10T12:00:04Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "The read was denied."}],
            },
        },
    ]
    return path, list(process_claude(_write_jsonl(path, records), "claude-1", {}))


def _codex_source(tmp_path):
    path = tmp_path / "codex.jsonl"
    records = [
        {
            "timestamp": "2026-07-10T12:00:00Z",
            "type": "session_meta",
            "payload": {"id": "codex-1", "cwd": str(tmp_path)},
        },
        {
            "timestamp": "2026-07-10T12:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Run the check."}],
            },
        },
        {
            "timestamp": "2026-07-10T12:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "shell",
                "arguments": "{\"command\":\"false\"}",
                "call_id": "call-1",
                "status": "failed",
            },
        },
        {
            "timestamp": "2026-07-10T12:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "exit status 1",
            },
        },
        {
            "timestamp": "2026-07-10T12:00:04Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "The check failed."}],
            },
        },
        {
            "timestamp": "2026-07-10T12:00:05Z",
            "type": "event_msg",
            "payload": {"type": "turn_aborted", "reason": "user interrupted"},
        },
    ]
    path = _write_jsonl(path, records)
    return path, list(process_codex(path, "codex-1", str(tmp_path), {}))


def _cursor_source(tmp_path):
    path = tmp_path / "cursor.vscdb"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)"
        )
        rows = [
            (
                "bubbleId:cursor-1:user-1",
                {
                    "type": 1,
                    "text": "Inspect the project.",
                    "createdAt": "2026-07-10T12:00:00Z",
                },
            ),
            (
                "messageRequestContext:cursor-1:user-1",
                {"cursorRules": ["keep evidence"]},
            ),
            (
                "bubbleId:cursor-1:assistant-1",
                {
                    "type": 2,
                    "text": "The edit was denied.",
                    "createdAt": "2026-07-10T12:00:01Z",
                    "toolFormerData": {
                        "name": "edit",
                        "toolCallId": "call-1",
                        "params": {"path": "README.md"},
                        "result": "Rejected by user",
                        "status": "completed",
                        "userDecision": "rejected",
                    },
                },
            ),
        ]
        conn.executemany(
            "INSERT INTO cursorDiskKV VALUES (?, ?)",
            [(key, json.dumps(value)) for key, value in rows],
        )
    events = [
        event for _session_id, event in process_cursor(
            path, str(tmp_path), {}, composer_ids={"cursor-1"}
        )
    ]
    return path, events


@pytest.mark.parametrize(
    ("source_name", "builder", "session_id", "status", "status_actor"),
    [
        ("Claude", _claude_source, "claude-1", "denied", "tool"),
        ("Codex", _codex_source, "codex-1", "failed", "model"),
        ("Cursor", _cursor_source, "cursor-1", "denied", "tool"),
    ],
)
def test_core_exchange_retains_exact_vendor_evidence_through_query(
    tmp_path, source_name, builder, session_id, status, status_actor,
):
    project = tmp_path / source_name.lower()
    project.mkdir()
    source, events = builder(project)
    store = project / ".codess" / f"sessions_{source_name.lower()}.db"
    init_db(store)
    conn = connect(store)
    replace_session_events(
        conn,
        {
            "id": session_id,
            "source": source_name,
            "type": "Code",
            "project_path": str(project),
        },
        events,
        session_id=session_id,
    )
    conn.commit()

    mapped = list(conn.execute(
        """
        SELECT global_id,mapping_rule,mapping_trace,source_record_locator
        FROM events ORDER BY sequence_no
        """
    ))
    assert mapped
    assert all(row["mapping_rule"] for row in mapped)
    assert all(row["source_record_locator"] for row in mapped)
    assert all(json.loads(row["mapping_trace"]) for row in mapped)
    status_row = conn.execute(
        """
        SELECT global_id,actor_kind FROM events
        WHERE normalized_status=? ORDER BY sequence_no LIMIT 1
        """,
        (status,),
    ).fetchone()
    assert status_row is not None
    assert status_row["actor_kind"] == status_actor
    status_event_id = status_row["global_id"]
    conn.close()

    opened = {
        "conn": connect(store, read_only=True),
        "path": store,
        "project_path": project,
    }
    try:
        expanded = execute(
            [opened],
            make_request(
                "events",
                filters={"event_ids": [status_event_id]},
                expand="interaction",
            ),
        )
        assert {"human", "harness", "tool", "model"} <= {
            row["actor_kind"] for row in expanded["rows"]
        }
        assert any(
            row["status"] == status
            and row["actor_kind"] == status_actor
            for row in expanded["rows"]
        )
        assert all(row["source_record_locator"] for row in expanded["rows"])
        evidence = resolve_event(opened, status_event_id)
        assert evidence["selected"]["kind"] == "live"
        assert evidence["selected"]["equality"] == "exact"
        if source_name == "Cursor":
            with sqlite3.connect(source) as source_conn:
                assert source_conn.execute(
                    """
                    SELECT COUNT(*) FROM cursorDiskKV
                    WHERE key LIKE 'bubbleId:cursor-1:%'
                    """
                ).fetchone()[0] == 2
        else:
            assert source.read_text(encoding="utf-8").count("\n") >= 5
    finally:
        opened["conn"].close()
