"""Tests for Cursor adapter."""

from contextlib import closing
import json
import sqlite3
from pathlib import Path

import pytest

from codess.adapters.cursor import (
    _bubble_timestamp,
    _bubble_to_events,
    _iter_bubbles,
    _parse_timestamp,
    get_composer_data,
    process_db,
)
from codess.cursor_source import (
    connect_readonly,
    get_composer_headers,
    get_db_metrics,
    get_project_composer_headers,
    get_selection_marker,
    get_selection_markers,
    get_sqlite_container_marker,
    get_workspace_composer_headers,
    has_bubble_rows,
)
from codess.schema_contract import validate_mapped_event


def _make_cursor_db(tmp_path: Path, bubbles: list[tuple[str, str, dict]]) -> Path:
    """Create a temp state.vscdb with cursorDiskKV table and bubbleId entries."""
    db = tmp_path / "state.vscdb"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)"
    )
    for composer_id, bubble_id, data in bubbles:
        key = f"bubbleId:{composer_id}:{bubble_id}"
        conn.execute(
            "INSERT OR REPLACE INTO cursorDiskKV (key, value) VALUES (?, ?)",
            (key, json.dumps(data)),
        )
    conn.commit()
    conn.close()
    return db


def test_workspace_composer_index_recovers_missing_global_headers(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    cursor_data = tmp_path / "Cursor" / "User"
    workspace = cursor_data / "workspaceStorage" / "workspace-one"
    workspace.mkdir(parents=True)
    (workspace / "workspace.json").write_text(
        json.dumps({"folder": project.resolve().as_uri()})
    )
    with sqlite3.connect(workspace / "state.vscdb") as conn:
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            (
                "composer.composerData",
                json.dumps({
                    "allComposers": [
                        {
                            "composerId": "legacy",
                            "createdAt": 1700000000000,
                            "lastUpdatedAt": 1700000001000,
                            "isArchived": True,
                        },
                        {
                            "composerId": "current",
                            "createdAt": 1,
                            "lastUpdatedAt": 2,
                        },
                    ]
                }),
            ),
        )
    global_dir = cursor_data / "globalStorage"
    global_dir.mkdir()
    global_db = global_dir / "state.vscdb"
    with sqlite3.connect(global_db) as conn:
        conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
        conn.executemany(
            "INSERT INTO cursorDiskKV VALUES (?, ?)",
            [
                ("bubbleId:legacy:one", json.dumps({"type": 1, "text": "old"})),
                ("bubbleId:current:one", json.dumps({"type": 1, "text": "new"})),
            ],
        )
        conn.execute(
            "CREATE TABLE composerHeaders ("
            "composerId TEXT PRIMARY KEY, workspaceId TEXT, createdAt INTEGER, "
            "lastUpdatedAt INTEGER, isArchived INTEGER, isSubagent INTEGER)"
        )
        conn.execute(
            "INSERT INTO composerHeaders VALUES (?, ?, ?, ?, ?, ?)",
            ("current", "workspace-one", 1700000002000, 1700000003000, 0, 0),
        )

    fallback = get_workspace_composer_headers(project, cursor_data)
    assert fallback["legacy"] == {
        "workspace_id": "workspace-one",
        "created_at": 1700000000000,
        "last_updated_at": 1700000001000,
        "is_archived": True,
        "is_subagent": False,
        "selection_source": "workspace.composerData",
    }
    combined = get_project_composer_headers(global_db, project, cursor_data)
    assert set(combined) == {"legacy", "current"}
    assert combined["current"]["created_at"] == 1700000002000
    assert "selection_source" not in combined["current"]

    markers = get_selection_markers(
        global_db,
        {"project": {"workspace-one"}},
        supplemental_headers={"project": combined},
    )
    assert markers["project"]["composer_count"] == 2
    assert markers["project"]["bubble_count"] == 2
    assert markers["project"]["source_mtime"] == 1700000003000


def _cursor_fixture() -> list[tuple[str, str, dict]]:
    path = Path(__file__).parent / "fixtures" / "cursor_bubbles.json"
    return [tuple(item) for item in json.loads(path.read_text())]


def test_cursor_structured_tool_input_is_json_with_mapping_evidence():
    data = {
        "type": 2,
        "toolFormerData": {
            "name": "read", "toolCallId": "call-1",
            "params": {"path": "README.md"}, "status": "completed",
        },
    }
    call = next(
        event for event in _bubble_to_events("c1", "b1", data, "/db", False)
        if event["event_type"] == "tool_call"
    )
    assert json.loads(call["tool_input"]) == {"path": "README.md"}
    assert validate_mapped_event("cursor", call) == []


class TestGetComposerData:
    """get_composer_data unit tests."""

    def test_missing_db(self, tmp_path):
        out = get_composer_data(tmp_path / "nonexistent.vscdb")
        assert out == []

    def test_empty_db(self, tmp_path):
        db = tmp_path / "state.vscdb"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()
        out = get_composer_data(db)
        assert out == []

    def test_decodes_composer_data(self, tmp_path):
        db = tmp_path / "state.vscdb"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            ("composerData:c1", json.dumps({"conversation": [{"type": 1, "text": "hi"}], "workspaceRoot": "/proj"})),
        )
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            ("composerData:c2", None),
        )
        conn.commit()
        conn.close()
        out = get_composer_data(db)
        assert len(out) == 2
        c1 = next(e for e in out if e["composer_id"] == "c1")
        assert c1["has_conversation"] is True
        assert "conversation" in c1["top_keys"]
        assert c1.get("workspaceRoot") == "/proj"
        c2 = next(e for e in out if e["composer_id"] == "c2")
        assert c2["value_null"] is True


class TestGetComposerHeaders:
    def test_filters_by_workspace(self, tmp_path):
        db = tmp_path / "state.vscdb"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE composerHeaders ("
            "composerId TEXT PRIMARY KEY, workspaceId TEXT, createdAt INTEGER, "
            "lastUpdatedAt INTEGER, isArchived INTEGER, isSubagent INTEGER)"
        )
        conn.executemany(
            "INSERT INTO composerHeaders VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("c1", "ws1", 1, 2, 0, 0),
                ("c2", "ws2", 3, 4, 1, 1),
            ],
        )
        conn.commit()
        conn.close()
        headers = get_composer_headers(db, {"ws1"})
        assert set(headers) == {"c1"}
        assert headers["c1"]["workspace_id"] == "ws1"
        assert headers["c1"]["is_archived"] is False

    def test_missing_table_is_visible_and_safe(self, tmp_path, caplog):
        db = tmp_path / "state.vscdb"
        sqlite3.connect(db).close()
        assert get_composer_headers(db, {"ws1"}) == {}
        assert "Cannot read Cursor composer headers" in caplog.text

    def test_tolerates_missing_optional_columns_and_new_columns(self, tmp_path):
        db = tmp_path / "state.vscdb"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE composerHeaders ("
            "composerId TEXT PRIMARY KEY, workspaceId TEXT, futureField TEXT)"
        )
        conn.execute(
            "INSERT INTO composerHeaders VALUES (?, ?, ?)",
            ("c1", "ws1", "ignored"),
        )
        conn.commit()
        conn.close()

        headers = get_composer_headers(db, {"ws1"})
        assert headers == {
            "c1": {
                "workspace_id": "ws1",
                "created_at": None,
                "last_updated_at": None,
                "is_archived": False,
                "is_subagent": False,
            }
        }


class TestSelectionMarker:
    def test_ignores_unselected_state_and_detects_selected_changes(self, tmp_path):
        db = tmp_path / "state.vscdb"
        with sqlite3.connect(db) as conn:
            conn.execute(
                "CREATE TABLE composerHeaders ("
                "composerId TEXT PRIMARY KEY, workspaceId TEXT, createdAt INTEGER, "
                "lastUpdatedAt INTEGER, isArchived INTEGER, isSubagent INTEGER)"
            )
            conn.execute(
                "CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.executemany(
                "INSERT INTO composerHeaders VALUES (?, ?, ?, ?, ?, ?)",
                [
                    ("selected", "ws1", 1700000000000, 1700000001000, 0, 0),
                    ("other", "ws2", 1700000000000, 1700000001000, 0, 0),
                ],
            )
            conn.executemany(
                "INSERT INTO cursorDiskKV VALUES (?, ?)",
                [
                    ("bubbleId:selected:one", "selected payload"),
                    ("bubbleId:other:one", "other payload"),
                ],
            )
        first = get_selection_marker(db, {"ws1"})
        assert first["workspace_count"] == 1
        assert first["composer_count"] == 1
        assert first["bubble_count"] == 1

        with sqlite3.connect(db) as conn:
            conn.execute(
                "UPDATE cursorDiskKV SET value='other changed' "
                "WHERE key='bubbleId:other:one'"
            )
            conn.execute("CREATE TABLE unrelated(value TEXT)")
            conn.execute("INSERT INTO unrelated VALUES ('changed')")
        assert get_selection_marker(db, {"ws1"}) == first

        with sqlite3.connect(db) as conn:
            conn.execute(
                "UPDATE cursorDiskKV SET value='selected changed' "
                "WHERE key='bubbleId:selected:one'"
            )
            conn.execute(
                "UPDATE composerHeaders SET lastUpdatedAt=1700000002000 "
                "WHERE composerId='selected'"
            )
        changed = get_selection_marker(db, {"ws1"})
        assert changed["source_revision"] != first["source_revision"]
        assert changed["source_mtime"] == 1700000002000

    def test_batch_markers_share_snapshot_and_container_marker_changes(self, tmp_path):
        db = _make_cursor_db(tmp_path, [
            ("c1", "one", {"type": 1, "text": "first"}),
            ("c2", "one", {"type": 1, "text": "second"}),
        ])
        with sqlite3.connect(db) as conn:
            conn.execute(
                "CREATE TABLE composerHeaders ("
                "composerId TEXT PRIMARY KEY, workspaceId TEXT)"
            )
            conn.executemany(
                "INSERT INTO composerHeaders VALUES (?, ?)",
                [("c1", "ws1"), ("c2", "ws2")],
            )
        container_before = get_sqlite_container_marker(db)

        markers = get_selection_markers(
            db, {"one": {"ws1"}, "two": {"ws2"}}
        )

        assert markers["one"] == get_selection_marker(db, {"ws1"})
        assert markers["two"] == get_selection_marker(db, {"ws2"})
        with sqlite3.connect(db) as conn:
            conn.execute(
                "UPDATE cursorDiskKV SET value=? WHERE key=?",
                (json.dumps({"type": 1, "text": "changed"}), "bubbleId:c1:one"),
            )
        assert get_sqlite_container_marker(db) != container_before

    def test_sidecar_free_wal_workspace_uses_immutable_fallback(self, tmp_path):
        db = tmp_path / "state.vscdb"
        with sqlite3.connect(db) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        Path(str(db) + "-wal").unlink(missing_ok=True)
        Path(str(db) + "-shm").unlink(missing_ok=True)

        with pytest.raises(sqlite3.OperationalError):
            with sqlite3.connect(
                db.resolve().as_uri() + "?mode=ro", uri=True
            ) as conn:
                conn.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone()
        with closing(connect_readonly(db)) as conn:
            assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert not has_bubble_rows(db)


class TestGetDbMetrics:
    """get_db_metrics unit tests."""

    def test_missing_db(self, tmp_path):
        m = get_db_metrics(tmp_path / "nonexistent.vscdb")
        assert m["count"] == 0
        assert m["events"] == 0
        assert m["size_bytes"] == 0

    def test_empty_db(self, tmp_path):
        db = tmp_path / "state.vscdb"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()
        m = get_db_metrics(db)
        assert m["count"] == 0
        assert m["events"] == 0
        assert m["size_bytes"] > 0
        assert m["error"] is None

    def test_counts_composers_and_bubbles(self, tmp_path):
        bubbles = [
            ("c1", "b1", {"type": 1, "text": "hi"}),
            ("c1", "b2", {"type": 2, "text": "ok"}),
            ("c2", "b1", {"type": 1, "text": "bye"}),
        ]
        db = _make_cursor_db(tmp_path, bubbles)
        m = get_db_metrics(db)
        assert m["count"] == 2
        assert m["events"] == 3
        assert m["size_bytes"] > 0

    def test_filters_metrics_to_selected_composers(self, tmp_path):
        db = _make_cursor_db(tmp_path, [
            ("c1", "b1", {"type": 1, "text": "selected"}),
            ("c1", "b2", {"type": 2, "text": "selected"}),
            ("c2", "b1", {"type": 1, "text": "unrelated"}),
        ])
        selected = get_db_metrics(db, {"c1"})
        assert selected["count"] == 1
        assert selected["events"] == 2
        assert 0 < selected["size_bytes"] < db.stat().st_size

    def test_uses_composer_header_time_range(self, tmp_path):
        db = _make_cursor_db(tmp_path, [("c1", "b1", {"type": 1, "text": "hi"})])
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE composerHeaders ("
            "composerId TEXT PRIMARY KEY, workspaceId TEXT, createdAt INTEGER, "
            "lastUpdatedAt INTEGER, isArchived INTEGER, isSubagent INTEGER)"
        )
        conn.executemany(
            "INSERT INTO composerHeaders VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("c1", "ws", 1_700_000_000_000, 1_700_000_100_000, 0, 0),
                ("c2", "ws", 1_600_000_000_000, 1_800_000_000_000, 0, 0),
            ],
        )
        conn.commit()
        conn.close()
        metrics = get_db_metrics(db)
        assert metrics["min_ts"] == 1_700_000_000_000
        assert metrics["max_ts"] == 1_700_000_100_000
        assert metrics["header_count"] == 1
        assert metrics["timed_header_count"] == 1

    def test_header_coverage_survives_missing_time_columns(self, tmp_path):
        db = _make_cursor_db(
            tmp_path, [("c1", "b1", {"type": 1, "text": "hi"})]
        )
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE composerHeaders (composerId TEXT, workspaceId TEXT)"
        )
        conn.execute("INSERT INTO composerHeaders VALUES ('c1', 'ws1')")
        conn.commit()
        conn.close()

        metrics = get_db_metrics(db)
        assert metrics["header_count"] == 1
        assert metrics["timed_header_count"] == 0
        assert metrics["min_ts"] is None
        assert metrics["max_ts"] is None

    def test_metrics_reports_missing_table(self, tmp_path, caplog):
        db = tmp_path / "state.vscdb"
        sqlite3.connect(db).close()
        m = get_db_metrics(db)
        assert m["count"] == 0
        assert m["error"]
        assert "cursorDiskKV" in m["error"]
        assert "Cannot read Cursor metrics" in caplog.text


class TestBubbleToEvents:
    """_bubble_to_events unit tests."""

    def test_user_prompt(self):
        data = {"type": 1, "text": "Hello", "createdAt": "2026-07-10T12:34:56.789Z"}
        evs = list(_bubble_to_events("c1", "b1", data, "/db", False))
        assert len(evs) == 1
        assert evs[0]["event_type"] == "user_message"
        assert evs[0]["subtype"] == "prompt"
        assert evs[0]["content"] == "Hello"
        assert evs[0]["timestamp"] == pytest.approx(1783686896789.0)

    def test_user_slash_command(self):
        data = {"type": 1, "text": "/fix bug", "timingInfo": {}}
        evs = list(_bubble_to_events("c1", "b1", data, "/db", False))
        assert evs[0]["subtype"] == "slash_command"

    def test_assistant_response(self):
        data = {"type": 2, "text": "Here is the fix.", "createdAt": 1783686896789}
        evs = list(_bubble_to_events("c1", "b1", data, "/db", False))
        assert len(evs) == 1
        assert evs[0]["event_type"] == "assistant_message"
        assert evs[0]["subtype"] == "response"
        assert evs[0]["content"] == "Here is the fix."

    def test_relative_client_start_time_is_not_epoch(self):
        data = {
            "type": 1,
            "text": "Hello",
            "timingInfo": {"clientStartTime": 127196698.1},
        }
        evs = list(_bubble_to_events("c1", "b1", data, "/db", False))
        assert evs[0]["timestamp"] is None

    def test_assistant_whitespace_only_envelope_is_not_a_model_message(self):
        data = {"type": 2, "text": "", "timingInfo": {}}
        evs = list(_bubble_to_events("c1", "b1", data, "/db", False))
        assert evs == []

    def test_assistant_empty_envelope_still_emits_tool_results(self):
        data = {
            "type": 2,
            "text": "  \n",
            "toolResults": [{"toolName": "Read", "result": "contents"}],
        }
        evs = list(_bubble_to_events("c1", "b1", data, "/db", False))
        assert len(evs) == 1
        assert evs[0]["subtype"] == "tool_result"
        assert evs[0]["tool_name"] == "Read"

    def test_assistant_with_tool_results(self):
        data = {
            "type": 2,
            "text": "Running command.",
            "timingInfo": {},
            "toolResults": [
                {"toolName": "Bash", "result": "output"},
                {"toolName": "Read", "result": "file contents"},
            ],
        }
        evs = list(_bubble_to_events("c1", "b1", data, "/db", False))
        assert len(evs) == 3
        assert evs[0]["event_type"] == "assistant_message"
        assert evs[1]["event_type"] == "user_message"
        assert evs[1]["subtype"] == "tool_result"
        assert evs[1]["tool_name"] == "Bash"
        assert evs[1]["content"] == "output"
        assert evs[2]["tool_name"] == "Read"
        assert evs[2]["event_id"] == "c1:b1:tr1"

    def test_tool_former_data_emits_linked_call_and_result(self):
        data = {
            "type": 2, "text": "",
            "toolFormerData": {
                "name": "read_file_v2", "toolCallId": "call-1",
                "modelCallId": "model-1", "status": "completed",
                "rawArgs": '{"path":"README.md"}', "result": "contents",
            },
            "toolResults": [],
        }
        evs = list(_bubble_to_events("c1", "b1", data, "/db", False))
        assert [event["event_type"] for event in evs] == ["tool_call", "user_message"]
        assert [event["subtype"] for event in evs] == ["tool_call", "tool_result"]
        assert evs[0]["tool_input"] == '{"path":"README.md"}'
        assert evs[1]["tool_output"] == "contents"
        assert json.loads(evs[0]["metadata"])["call_id"] == "call-1"

    def test_tool_former_error_without_body_is_retained(self):
        data = {
            "type": 2, "text": "",
            "toolFormerData": {
                "name": "edit_file_v2", "toolCallId": "call-2", "status": "error",
            },
        }
        evs = list(_bubble_to_events("c1", "b1", data, "/db", False))
        assert len(evs) == 2
        assert evs[1]["subtype"] == "tool_failure"
        assert evs[1]["normalized_status"] == "failed"

    def test_rejected_tool_decision_is_denied_even_when_status_completed(self):
        data = {
            "type": 2, "text": "",
            "toolFormerData": {
                "name": "run_terminal_command", "toolCallId": "call-3",
                "status": "completed", "userDecision": "rejected",
            },
        }
        evs = list(_bubble_to_events("c1", "b1", data, "/db", False))
        assert len(evs) == 2
        assert evs[0]["normalized_status"] == "denied"
        assert evs[1]["subtype"] == "permission_denied"
        assert evs[1]["normalized_status"] == "denied"
        assert json.loads(evs[1]["metadata"])["permission_provenance"] == (
            "toolFormerData.userDecision"
        )

    def test_user_model_selection_is_bounded_metadata(self):
        event = list(_bubble_to_events(
            "c1", "b1",
            {"type": 1, "text": "prompt", "modelInfo": {"modelName": "composer-2.5"}},
            "/db", False,
        ))[0]
        assert json.loads(event["metadata"]) == {
            "model_selection": "composer-2.5", "model": "composer-2.5",
            "configuration_provenance": {"model": {
                "source_record_type": "bubble.user",
                "source_record_locator": "c1:b1",
                "source_field": "modelInfo.modelName",
            }},
        }

    def test_unknown_type_skipped(self):
        data = {"type": 99, "text": "x", "timingInfo": {}}
        evs = list(_bubble_to_events("c1", "b1", data, "/db", False))
        assert len(evs) == 0


class TestIterBubbles:
    """_iter_bubbles integration with real SQLite."""

    def test_iter_bubbles(self, tmp_path):
        bubbles = [
            ("composer1", "b1", {"type": 1, "text": "hi", "timingInfo": {}}),
            ("composer1", "b2", {"type": 2, "text": "ok", "timingInfo": {}}),
        ]
        db = _make_cursor_db(tmp_path, bubbles)
        out = list(_iter_bubbles(db))
        assert len(out) == 2
        assert out[0] == ("composer1", "b1", {"type": 1, "text": "hi", "timingInfo": {}})
        assert out[1] == ("composer1", "b2", {"type": 2, "text": "ok", "timingInfo": {}})

    def test_reads_uncheckpointed_wal_rows(self, tmp_path):
        db = tmp_path / "state.vscdb"
        writer = sqlite3.connect(db)
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute(
            "CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)"
        )
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute(
            "INSERT INTO cursorDiskKV VALUES (?, ?)",
            ("bubbleId:c1:b1", json.dumps({"type": 1, "text": "from wal"})),
        )
        writer.commit()
        try:
            assert (tmp_path / "state.vscdb-wal").stat().st_size > 0
            rows = list(_iter_bubbles(db))
        finally:
            writer.close()
        assert rows[0][2]["text"] == "from wal"

    def test_uri_special_characters_in_database_path(self, tmp_path):
        special = tmp_path / "with ? and #"
        special.mkdir()
        db = _make_cursor_db(
            special, [("c1", "b1", {"type": 1, "text": "safe uri"})]
        )
        assert list(_iter_bubbles(db))[0][2]["text"] == "safe uri"

    def test_skips_non_bubble_keys(self, tmp_path):
        db = _make_cursor_db(tmp_path, [])
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            ("otherKey", json.dumps({"x": 1})),
        )
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            ("bubbleId:c1:b1", json.dumps({"type": 1, "text": "hi", "timingInfo": {}})),
        )
        conn.commit()
        conn.close()
        out = list(_iter_bubbles(db))
        assert len(out) == 1
        assert out[0][2]["text"] == "hi"

    def test_skips_invalid_json(self, tmp_path):
        db = _make_cursor_db(tmp_path, [])
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            ("bubbleId:c1:b1", "not json"),
        )
        conn.commit()
        conn.close()
        out = list(_iter_bubbles(db))
        assert len(out) == 0

    def test_process_db_reports_skipped_rows(self, tmp_path, caplog):
        db = _make_cursor_db(tmp_path, [])
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            ("bubbleId:c1:null", None),
        )
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            ("bubbleId:c1:bad", "not json"),
        )
        conn.commit()
        conn.close()
        diagnostics = {}
        assert list(process_db(db, "/proj", {"diagnostics": diagnostics})) == []
        assert diagnostics == {"malformed_records": 2}
        assert "skipped 2/2 bubble rows" in caplog.text
        assert "null=1" in caplog.text
        assert "decode=1" in caplog.text


class TestProcessDb:
    """process_db full flow."""

    def test_process_db_groups_by_composer(self, tmp_path):
        bubbles = [
            ("c1", "b1", {"type": 1, "text": "prompt", "timingInfo": {"clientStartTime": 1}}),
            ("c1", "b2", {"type": 2, "text": "reply", "timingInfo": {"clientStartTime": 2}}),
            ("c2", "b1", {"type": 1, "text": "other", "timingInfo": {"clientStartTime": 3}}),
        ]
        db = _make_cursor_db(tmp_path, bubbles)
        out = list(process_db(db, "/proj", {}))
        assert len(out) == 3
        sids = [o[0] for o in out]
        assert sids.count("c1") == 2
        assert sids.count("c2") == 1

    def test_compaction_and_request_context_are_first_class_events(
        self, tmp_path
    ):
        summary = json.dumps({
            "summary": "cursor compact summary",
            "truncationLastBubbleIdInclusive": "old-last",
            "clientShouldStartSendingFromInclusiveBubbleId": "new-first",
        })
        db = _make_cursor_db(tmp_path, [
            (
                "c1", "b1",
                {
                    "type": 1,
                    "text": "prompt",
                    "createdAt": "2026-07-10T00:00:00Z",
                    "contextWindowStatusAtCreation": {
                        "tokensUsed": 100,
                        "tokenLimit": 1000,
                        "percentageRemaining": 90,
                    },
                },
            ),
            (
                "c1", "b2",
                {
                    "type": 2,
                    "text": "reply",
                    "createdAt": "2026-07-10T00:00:01Z",
                    "conversationSummary": summary,
                },
            ),
        ])
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
                (
                    "messageRequestContext:c1:b1",
                    json.dumps({
                        "cursorRules": ["rule"],
                        "terminalFiles": [],
                    }),
                ),
            )
        events = [
            event for _session, event in process_db(
                db, "/project",
                {"max_context_content_chars": 128},
            )
        ]
        assert [event["subtype"] for event in events] == [
            "prompt", "context_injection", "response", "context_compaction",
        ]
        prompt_metadata = json.loads(events[0]["metadata"])
        assert prompt_metadata["context_tokens_used"] == 100
        assert prompt_metadata["context_token_limit"] == 1000
        request_context = events[1]
        assert json.loads(request_context["content"]) == {
            "cursorRules": ["rule"], "terminalFiles": [],
        }
        assert request_context["mapping_rule"] == "cursor.request-context"
        compact = events[3]
        assert compact["content"] == "cursor compact summary"
        assert compact["mapping_rule"] == "cursor.compaction-summary"
        assert json.loads(compact["metadata"])[
            "truncationLastBubbleIdInclusive"
        ] == "old-last"

    def test_process_db_traces_composer_read_buffer(self, tmp_path, monkeypatch):
        monkeypatch.setattr("codess.adapters.cursor._PROGRESS_ROWS", 2)
        db = _make_cursor_db(tmp_path, [
            ("c1", "b1", {"type": 1, "text": "one"}),
            ("c1", "b2", {"type": 2, "text": "two"}),
            ("c2", "b1", {"type": 1, "text": "three"}),
        ])
        progress = []

        list(process_db(
            db, "/proj",
            {"progress": lambda event, **fields: progress.append((event, fields))},
        ))

        assert [event for event, _fields in progress] == [
            "cursor.composer.read.start",
            "cursor.composer.read.progress",
            "cursor.composer.read.done",
            "cursor.composer.read.start",
            "cursor.composer.read.done",
        ]
        assert progress[1][1]["bubbles"] == 2
        assert {fields["composer_id"] for _event, fields in progress} == {"c1", "c2"}

    def test_representative_fixture_contract(self, tmp_path):
        db = _make_cursor_db(tmp_path, _cursor_fixture())
        events = list(process_db(db, "/project", {}))
        assert len(events) == 4
        assert [event[0] for event in events].count("composer-main") == 3
        assert events[-1][0] == "composer-undated"
        assert events[-1][1]["timestamp"] is None
        assert not {
            "permission_denied", "tool_failure", "turn_aborted",
            "context_compaction",
        } & {event[1]["subtype"] for event in events}

    def test_process_db_sorts_by_timing(self, tmp_path):
        bubbles = [
            ("c1", "b2", {"type": 1, "text": "second", "createdAt": "2026-07-10T00:00:02Z"}),
            ("c1", "b1", {"type": 1, "text": "first", "createdAt": "2026-07-10T00:00:01Z"}),
        ]
        db = _make_cursor_db(tmp_path, bubbles)
        out = list(process_db(db, "/proj", {}))
        assert out[0][1]["content"] == "first"
        assert out[1][1]["content"] == "second"

    def test_process_db_classifies_empty_assistant_envelope_as_known_state(
        self, tmp_path,
    ):
        db = _make_cursor_db(tmp_path, [
            ("c1", "b1", {
                "type": 2, "text": "", "createdAt": 1780000000000,
                "toolResults": [],
            }),
        ])
        diagnostics = {}
        assert list(process_db(db, "/proj", {
            "diagnostics": diagnostics,
        })) == []
        assert diagnostics.get("ignored_records", 0) == 0
        assert diagnostics["known_ignored_records"] == 1
        assert diagnostics["empty_assistant_envelope_records"] == 1

    def test_process_db_deduplicates_server_identity_per_composer(self, tmp_path):
        fixture = json.loads(
            (Path(__file__).parents[1] / "schema/coschema/fixtures/hazard/"
             "cursor-nonmessage-copies.json").read_text()
        )
        diagnostics = {}
        db = _make_cursor_db(tmp_path, fixture["bubbles"])
        out = list(process_db(db, "/proj", {"diagnostics": diagnostics}))
        assert [list(item) for item in (
            (sid, event["event_id"]) for sid, event in out
        )] == fixture["expected_events"]
        assert diagnostics["duplicate_records"] == fixture["expected_duplicate_records"]
        # The released fixture's legacy key counts non-emitted envelopes. The
        # decoder now distinguishes this known state from unknown loss.
        assert diagnostics.get("ignored_records", 0) == 0
        assert (
            diagnostics["known_ignored_records"]
            == fixture["expected_ignored_records"]
        )

    def test_process_db_places_missing_timestamps_last(self, tmp_path):
        bubbles = [
            ("c1", "b2", {"type": 1, "text": "missing", "timingInfo": {"clientStartTime": 2}}),
            ("c1", "b1", {"type": 1, "text": "dated", "createdAt": "2026-07-10T00:00:01Z"}),
        ]
        db = _make_cursor_db(tmp_path, bubbles)
        out = list(process_db(db, "/proj", {}))
        assert [event[1]["content"] for event in out] == ["dated", "missing"]

    def test_process_db_filters_composers(self, tmp_path):
        bubbles = [
            ("c1", "b1", {"type": 1, "text": "keep"}),
            ("c2", "b1", {"type": 1, "text": "drop"}),
        ]
        db = _make_cursor_db(tmp_path, bubbles)
        stats = {}
        out = list(
            _iter_bubbles(db, stats=stats, composer_ids={"c1"})
        )
        assert [event[0] for event in out] == ["c1"]
        assert stats["rows"] == 1


class TestCursorTimestamps:
    def test_iso_and_numeric_epoch_values(self):
        assert _parse_timestamp("2026-07-10T12:34:56.789Z") == pytest.approx(1783686896789.0)
        assert _parse_timestamp(1783686896789) == 1783686896789.0
        assert _parse_timestamp(1783686896.789) == pytest.approx(1783686896789.0)

    @pytest.mark.parametrize("value", [None, "", "not-a-time", 0, 5208.8, 127196698.1, True])
    def test_invalid_or_relative_values(self, value):
        assert _parse_timestamp(value) is None

    def test_created_at_precedes_legacy_epoch_fallback(self):
        data = {
            "createdAt": "2026-07-10T00:00:01Z",
            "timingInfo": {"clientStartTime": 1780000000000},
        }
        assert _bubble_timestamp(data) == pytest.approx(1783641601000.0)


def test_hostile_cursor_fields_are_diagnosed_without_losing_events():
    prompt = list(_bubble_to_events(
        "c1", "b1",
        {"type": 1, "text": "keep prompt", "modelInfo": ["bad"]},
        "/db", False,
    ))[0]
    assert prompt["content"] == "keep prompt"
    assert {
        (row["source_field"], row["reason_code"])
        for row in prompt["field_diagnostics"]
    } >= {
        ("modelInfo", "field_malformed"),
        ("bubble.origin", "field_absent"),
    }

    call = list(_bubble_to_events(
        "c1", "b2",
        {"type": 2, "text": "", "toolFormerData": {
            "name": "read_file", "toolCallId": "call-1",
            "status": "pending",
        }},
        "/db", False,
    ))[0]
    assert call["event_type"] == "tool_call"
    assert any(
        row["source_field"] == "toolFormerData.params"
        and row["reason_code"] == "field_absent"
        for row in call["field_diagnostics"]
    )
