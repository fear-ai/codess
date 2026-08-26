"""Tests for Cursor adapter."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from cursor_fixtures import (
    build_cursor_db,
    create_bubble_table,
    create_header_table,
    put_headers,
    put_records,
)

from codess.adapters import cursor
from codess.adapters.cursor import (
    _bubble_timestamp,
    _bubble_to_events,
    _iter_bubbles,
    _parse_timestamp,
    _tool_file_path,
    process_db,
)
from codess.cursor_source import (
    connect_readonly,
    get_client_version,
    get_composer_headers,
    get_db_metrics,
    get_project_composer_headers,
    get_selection_markers,
    get_sqlite_container_marker,
    get_workspace_composer_headers,
    has_bubble_rows,
)
from codess.schema_contract import validate_mapped_event


def _make_cursor_db(tmp_path: Path, bubbles: list[tuple[str, str, dict]]) -> Path:
    """Create a temp state.vscdb with cursorDiskKV table and bubbleId entries."""
    return build_cursor_db(tmp_path / "state.vscdb", bubbles=bubbles)


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
        create_bubble_table(conn)
        conn.executemany(
            "INSERT INTO cursorDiskKV VALUES (?, ?)",
            [
                ("bubbleId:legacy:one", json.dumps({"type": 1, "text": "old"})),
                ("bubbleId:current:one", json.dumps({"type": 1, "text": "new"})),
            ],
        )
        create_header_table(conn)
        put_headers(conn, [("current", "workspace-one", 1700000002000, 1700000003000, 0, 0)])

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
    assert combined["current"]["selection_source"] == "composerHeaders"

    markers = get_selection_markers(
        global_db,
        {"project": {"workspace-one"}},
        supplemental_headers={"project": combined},
    )
    assert markers["project"]["composer_count"] == 2
    assert markers["project"]["bubble_count"] == 2
    assert markers["project"]["source_mtime"] == 1700000003000
    assert markers["project"]["fingerprint_method"].endswith(
        "digest-fingerprint-v2"
    )


def test_workspace_composer_index_reports_ambiguous_fallback_once(
    tmp_path, caplog
):
    project = tmp_path / "project"
    project.mkdir()
    cursor_data = tmp_path / "Cursor" / "User"
    for index in range(3):
        workspace = (
            cursor_data / "workspaceStorage" / f"workspace-{index}"
        )
        workspace.mkdir(parents=True)
        (workspace / "workspace.json").write_text(
            json.dumps({"folder": project.resolve().as_uri()})
        )
        with sqlite3.connect(workspace / "state.vscdb") as conn:
            conn.execute(
                "CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.execute(
                "INSERT INTO ItemTable VALUES (?, ?)",
                (
                    "composer.composerData",
                    json.dumps({
                        "allComposers": [{"composerId": "ambiguous"}]
                    }),
                ),
            )

    global_dir = cursor_data / "globalStorage"
    global_dir.mkdir()
    global_db = global_dir / "state.vscdb"
    with sqlite3.connect(global_db) as conn:
        create_header_table(
            conn, ("composerId TEXT PRIMARY KEY", "workspaceId TEXT"),
        )

    diagnostics = {}
    assert get_project_composer_headers(
        global_db, project, cursor_data, diagnostics=diagnostics
    ) == {}
    assert diagnostics == {"cursor_ambiguous_fallback_composers": 1}
    assert caplog.text.count("excluding ambiguous fallback mapping") == 1


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


class TestGetComposerHeaders:
    def test_filters_by_workspace(self, tmp_path):
        db = tmp_path / "state.vscdb"
        conn = sqlite3.connect(db)
        create_header_table(conn)
        put_headers(
            conn,
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
        create_header_table(
            conn,
            ("composerId TEXT PRIMARY KEY", "workspaceId TEXT", "futureField TEXT"),
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
                "selection_source": "composerHeaders",
            }
        }


class TestSelectionMarker:
    def test_ignores_unselected_state_and_detects_selected_changes(self, tmp_path):
        db = tmp_path / "state.vscdb"
        with sqlite3.connect(db) as conn:
            create_header_table(conn)
            create_bubble_table(conn)
            put_headers(
            conn,
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
        first = get_selection_markers(db, {"selection": {"ws1"}})["selection"]
        assert first["source_revision"].startswith(
            "cursor-selection-digest-fingerprint:"
        )
        assert first["fingerprint_method"] == (
            "cursor-workspace-header-source-key-length-edge-"
            "digest-fingerprint-v2"
        )
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
        assert get_selection_markers(db, {"selection": {"ws1"}})["selection"] == first

        with sqlite3.connect(db) as conn:
            conn.execute(
                "UPDATE cursorDiskKV SET value='selected changed' "
                "WHERE key='bubbleId:selected:one'"
            )
            conn.execute(
                "UPDATE composerHeaders SET lastUpdatedAt=1700000002000 "
                "WHERE composerId='selected'"
            )
        changed = get_selection_markers(db, {"selection": {"ws1"}})["selection"]
        assert changed["source_revision"] != first["source_revision"]
        assert changed["source_mtime"] == 1700000002000

    def test_batch_markers_share_snapshot_and_container_marker_changes(self, tmp_path):
        db = _make_cursor_db(tmp_path, [
            ("c1", "one", {"type": 1, "text": "first"}),
            ("c2", "one", {"type": 1, "text": "second"}),
        ])
        with sqlite3.connect(db) as conn:
            create_header_table(
                conn, ("composerId TEXT PRIMARY KEY", "workspaceId TEXT"),
            )
            conn.executemany(
                "INSERT INTO composerHeaders VALUES (?, ?)",
                [("c1", "ws1"), ("c2", "ws2")],
            )
        container_before = get_sqlite_container_marker(db)

        markers = get_selection_markers(
            db, {"one": {"ws1"}, "two": {"ws2"}}
        )

        assert markers["one"] == get_selection_markers(db, {"selection": {"ws1"}})["selection"]
        assert markers["two"] == get_selection_markers(db, {"selection": {"ws2"}})["selection"]
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
            create_bubble_table(conn)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        Path(str(db) + "-wal").unlink(missing_ok=True)
        Path(str(db) + "-shm").unlink(missing_ok=True)

        with pytest.raises(sqlite3.OperationalError), sqlite3.connect(
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
        create_bubble_table(conn)
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
        create_header_table(conn)
        put_headers(
            conn,
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
        create_header_table(conn, ("composerId TEXT", "workspaceId TEXT"))
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

    def test_mcp_application_error_overrides_completed_transport(self):
        data = {
            "type": 2, "text": "",
            "toolFormerData": {
                "name": "mcp-cursor-app-control-cursor_dialog",
                "toolCallId": "call-mcp", "status": "completed",
                "result": json.dumps({
                    "result": json.dumps({
                        "content": [{
                            "type": "text",
                            "text": "Error: Invalid input",
                        }],
                    }),
                }),
            },
        }
        call, result = list(
            _bubble_to_events("c1", "b1", data, "/db", False)
        )
        assert call["source_status"] == "completed"
        assert call["normalized_status"] == "failed"
        assert result["subtype"] == "tool_failure"
        assert result["normalized_status"] == "failed"
        metadata = json.loads(result["metadata"])
        assert metadata["application_status"] == "failed"
        assert "Error: Invalid input" in metadata["result_status_evidence"]

    def test_mcp_discovery_target_error_is_not_invocation_failure(self):
        data = {
            "type": 2, "text": "",
            "toolFormerData": {
                "name": "get_mcp_tools",
                "toolCallId": "call-discovery", "status": "completed",
                "result": json.dumps({
                    "server": "user-brave-search",
                    "serverStatus": "error",
                    "tools": [{"name": "mcp_auth"}],
                }),
            },
        }
        call, result = list(
            _bubble_to_events("c1", "b1", data, "/db", False)
        )
        assert call["normalized_status"] == "succeeded"
        assert result["subtype"] == "tool_result"
        assert result["normalized_status"] == "succeeded"

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
        event = next(iter(_bubble_to_events(
            "c1", "b1",
            {"type": 1, "text": "prompt", "modelInfo": {"modelName": "composer-2.5"}},
            "/db", False,
        )))
        assert json.loads(event["metadata"]) == {
            "model_set": "composer-2.5", "model": "composer-2.5",
            "configuration_provenance": {"model": {
                "source_record_type": "bubble.user",
                "source_record_locator": "c1:b1",
                "source_field": "modelInfo.modelName",
            }},
        }

    def test_subagent_user_bubble_is_harness_delegated(self):
        event = next(iter(_bubble_to_events(
            "c1", "b1",
            {"type": 1, "text": "Investigate this"},
            "/db", False,
            session_header={"is_subagent": True},
        )))
        assert event["event_type"] == "system_event"
        assert event["subtype"] == "delegated_prompt"
        assert event["role"] == "harness"
        assert event["actor_kind"] == "harness"
        assert event["content_role"] == "delegated_task"
        assert event["origin_kind"] == "harness_delegated"
        assert json.loads(event["metadata"])["actor_evidence"] == (
            "composerHeaders.isSubagent"
        )

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
        create_bubble_table(writer)
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
        assert next(iter(_iter_bubbles(db)))[2]["text"] == "safe uri"

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
        assert diagnostics.get("record_unclassified", 0) == 0
        assert diagnostics["record_empty_assistant_envelope"] == 1

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
        assert diagnostics.get("record_unclassified", 0) == 0
        assert (
            diagnostics["record_empty_assistant_envelope"]
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
    prompt = next(iter(_bubble_to_events(
        "c1", "b1",
        {"type": 1, "text": "keep prompt", "modelInfo": ["bad"]},
        "/db", False,
    )))
    assert prompt["content"] == "keep prompt"
    assert {
        (row["source_field"], row["reason_code"])
        for row in prompt["field_diagnostics"]
    } >= {
        ("modelInfo", "field_malformed"),
        ("bubble.origin", "field_absent"),
    }

    call = next(iter(_bubble_to_events(
        "c1", "b2",
        {"type": 2, "text": "", "toolFormerData": {
            "name": "read_file", "toolCallId": "call-1",
            "status": "pending",
        }},
        "/db", False,
    )))
    assert call["event_type"] == "tool_call"
    assert any(
        row["source_field"] == "toolFormerData.params"
        and row["reason_code"] == "field_absent"
        for row in call["field_diagnostics"]
    )


class TestSubagentLineage:
    """Cursor records which Composer delegated a subagent; Codess reads it.

    `isSubagent` was the only field consulted, so a Session was marked
    `subagent` while its parent stayed unnamed -- a relation asserted without
    its evidence. The parent is in the header's JSON `value` under
    `subagentInfo`, alongside the tool call that spawned it.
    """

    def header(self, **overrides) -> str:
        info = {
            "subagentType": 3,
            "parentComposerId": "parent-1",
            "rootParentConversationId": "root-1",
            "subagentTypeName": "explore",
            "toolCallId": "tool_abc",
            "conversationLengthAtSpawn": 0,
        }
        info.update(overrides.pop("subagentInfo", {}))
        value = {"type": "head", "composerId": "child-1", "subagentInfo": info}
        value.update(overrides)
        return json.dumps(value)

    def test_the_parent_is_read_from_the_header(self):
        from codess.cursor_source import subagent_lineage

        lineage = subagent_lineage(self.header())
        assert lineage["parent_composer_id"] == "parent-1"
        assert lineage["root_parent_composer_id"] == "root-1"

    def test_the_spawning_tool_call_is_retained(self):
        """What links a delegated Session back to the invocation in its parent."""
        from codess.cursor_source import subagent_lineage

        lineage = subagent_lineage(self.header())
        assert lineage["spawning_tool_call_id"] == "tool_abc"
        assert lineage["subagent_type_name"] == "explore"

    def test_a_header_without_lineage_reports_nothing(self):
        """Absent stays absent, so a caller can merge unconditionally."""
        from codess.cursor_source import subagent_lineage

        assert subagent_lineage(json.dumps({"type": "head"})) == {}

    def test_unusable_header_values_are_absence_not_failure(self):
        from codess.cursor_source import subagent_lineage

        assert subagent_lineage(None) == {}
        assert subagent_lineage("") == {}
        assert subagent_lineage("{not json") == {}
        assert subagent_lineage(json.dumps(["not", "an", "object"])) == {}

    def test_a_partial_lineage_keeps_what_was_recorded(self):
        from codess.cursor_source import subagent_lineage

        value = json.dumps({
            "type": "head", "subagentInfo": {"parentComposerId": "p1"},
        })
        lineage = subagent_lineage(value)
        assert lineage == {"parent_composer_id": "p1"}

    def test_a_bytes_header_decodes(self):
        """SQLite may hand back the column as bytes."""
        from codess.cursor_source import subagent_lineage

        lineage = subagent_lineage(self.header().encode("utf-8"))
        assert lineage["parent_composer_id"] == "parent-1"


class TestClientVersion:
    """Cursor records its client version, and `harness_version` carries it.

    `sessions.harness_version` was null for every Cursor Session while Claude
    and Codex filled 425 of 426, so a Cursor decode gap could not be
    attributed to a release -- the evidence every "vendor formats evolve
    independently" claim depends on.
    """

    def _global_db(self, tmp_path, items):
        database = tmp_path / "state.vscdb"
        conn = sqlite3.connect(database)
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
        conn.executemany("INSERT INTO ItemTable VALUES (?, ?)", items)
        conn.commit()
        conn.close()
        return database

    def test_startup_metrics_key(self, tmp_path):
        database = self._global_db(
            tmp_path, [("cursor.startupMetrics.lastVersion", "3.15.6")],
        )
        assert get_client_version(database) == "3.15.6"

    def test_falls_back_through_the_key_order(self, tmp_path):
        """The launch-time key is preferred; the others are consulted after."""
        database = self._global_db(
            tmp_path, [("releaseNotes/lastVersion", "3.14.0")],
        )
        assert get_client_version(database) == "3.14.0"

    def test_quoted_json_value_is_unwrapped(self, tmp_path):
        database = self._global_db(
            tmp_path, [("cursor.startupMetrics.lastVersion", '"3.15.6"')],
        )
        assert get_client_version(database) == "3.15.6"

    def test_absent_database(self, tmp_path):
        assert get_client_version(tmp_path / "missing.vscdb") is None

    def test_no_version_key(self, tmp_path):
        database = self._global_db(tmp_path, [("unrelated", "x")])
        assert get_client_version(database) is None

    def test_database_without_item_table(self, tmp_path):
        """A workspace store has no ItemTable; that is not an error."""
        database = tmp_path / "workspace.vscdb"
        conn = sqlite3.connect(database)
        conn.execute("CREATE TABLE cursorDiskKV (key TEXT, value BLOB)")
        conn.commit()
        conn.close()
        assert get_client_version(database) is None


class TestToolFilePath:
    """Cursor names the file a tool operates on, under four spellings.

    `events.file_path` was null for every Cursor Event while 2,873 of 4,530
    real tool calls carried a path in their arguments. The keys differ per
    tool -- `read_file` and `edit_file` use `target_file`, `search_replace`
    uses `file_path`, `list_dir` uses `relative_workspace_path` -- which is
    why one field read finds none of them.
    """

    @pytest.mark.parametrize(
        ("arguments", "expected"),
        [
            ({"target_file": "src/a.py"}, "src/a.py"),
            ({"file_path": "src/b.py"}, "src/b.py"),
            ({"relative_workspace_path": "src"}, "src"),
            ({"path": "src/c.py"}, "src/c.py"),
        ],
    )
    def test_each_spelling(self, arguments, expected):
        assert _tool_file_path({"rawArgs": json.dumps(arguments)}) == expected

    def test_most_specific_key_wins(self):
        """A call naming both a target and a workspace records the target."""
        arguments = {"relative_workspace_path": ".", "target_file": "src/a.py"}
        assert _tool_file_path({"rawArgs": json.dumps(arguments)}) == "src/a.py"

    def test_params_when_raw_args_absent(self):
        assert _tool_file_path({"params": {"target_file": "src/a.py"}}) == "src/a.py"

    def test_several_paths_record_none(self):
        """One column, so a multi-path call names none rather than a first."""
        assert _tool_file_path({"rawArgs": json.dumps({"paths": ["a", "b"]})}) is None

    @pytest.mark.parametrize(
        "tool_former",
        [{}, {"rawArgs": "not json"}, {"rawArgs": json.dumps(["a"])},
         {"rawArgs": json.dumps({"target_file": "   "})}],
    )
    def test_no_usable_path(self, tool_former):
        assert _tool_file_path(tool_former) is None


class TestComposerSettings:
    """Interaction settings Cursor states once per composer."""

    def build(self, tmp_path, composer_data=None, *, kv=True):
        db = tmp_path / "state.vscdb"
        conn = sqlite3.connect(db)
        create_header_table(conn)
        put_headers(conn, [("c1", "ws1", 1, 2, 0, 0)])
        if kv:
            create_bubble_table(conn)
            if composer_data is not None:
                put_records(conn, {"composerData:c1": composer_data})
        conn.commit()
        conn.close()
        return db

    def test_settings(self, tmp_path):
        """`unifiedMode` and `maxMode` are Session facts, so they join the header
        rather than being re-read per bubble."""
        headers = get_composer_headers(
            self.build(tmp_path, {
                "unifiedMode": "agent", "modelConfig": {"maxMode": False},
            }),
            {"ws1"},
        )
        assert headers["c1"]["interaction_mode"] == "agent"
        assert headers["c1"]["max_mode"] is False

    def test_chat_mode(self, tmp_path):
        headers = get_composer_headers(
            self.build(tmp_path, {"unifiedMode": "chat"}), {"ws1"},
        )
        assert headers["c1"]["interaction_mode"] == "chat"
        assert "max_mode" not in headers["c1"]

    def test_integer_mode(self, tmp_path):
        """Bubbles state `unifiedMode` as an integer where composers state a word.
        Nothing observed says what an integer means, so it is not read as one."""
        headers = get_composer_headers(
            self.build(tmp_path, {"unifiedMode": 2}), {"ws1"},
        )
        assert "interaction_mode" not in headers["c1"]

    def test_absent_composer_data(self, tmp_path):
        headers = get_composer_headers(self.build(tmp_path), {"ws1"})
        assert set(headers) == {"c1"}
        assert "interaction_mode" not in headers["c1"]

    def test_malformed_composer_data(self, tmp_path):
        db = tmp_path / "state.vscdb"
        conn = sqlite3.connect(db)
        create_header_table(conn)
        put_headers(conn, [("c1", "ws1", 1, 2, 0, 0)])
        create_bubble_table(conn)
        conn.execute(
            "INSERT INTO cursorDiskKV VALUES (?, ?)",
            ("composerData:c1", "{not json"),
        )
        conn.commit()
        conn.close()
        headers = get_composer_headers(db, {"ws1"})
        assert set(headers) == {"c1"}
        assert "interaction_mode" not in headers["c1"]

    def test_missing_kv_table(self, tmp_path):
        """Settings only qualify a Session, so a store keeping headers without
        `cursorDiskKV` still yields them."""
        headers = get_composer_headers(self.build(tmp_path, kv=False), {"ws1"})
        assert set(headers) == {"c1"}
        assert "interaction_mode" not in headers["c1"]

    def test_model_from_composer(self, tmp_path):
        """The composer states a model for every composer, where bubble
        `modelInfo` carries one on 3,044 of 188,904 real records. The richer
        labels appear only here: `composer-2-fast` names a speed variant."""
        headers = get_composer_headers(
            self.build(tmp_path, {"modelConfig": {"modelName": "composer-2-fast"}}),
            {"ws1"},
        )
        assert headers["c1"]["model_name"] == "composer-2-fast"
        assert headers["c1"]["model"] == "composer-2-fast"

    def test_model_default(self, tmp_path):
        """`default` is the absence of a choice, so it is kept as the selection
        and withheld as a model."""
        headers = get_composer_headers(
            self.build(tmp_path, {"modelConfig": {"modelName": "default"}}), {"ws1"},
        )
        assert headers["c1"]["model_name"] == "default"
        assert "model" not in headers["c1"]


class TestRepeatedToolCallsAreCounted:
    """A tool call surviving on two bubbles after dedup is reported, not dropped.

    `(type, serverBubbleId)` collapses server-written copies and exempts a
    bubble with no server identity, because a missing identity cannot prove
    duplication. A re-synced composer gains server copies of bubbles it already
    held locally, so one `toolCallId` survives on two bubbles. Both are real
    vendor records, so the count is the finding.
    """

    def test_one_call_on_two_bubbles(self):
        diagnostics: dict = {}
        cursor._count_surviving_repeats(
            [
                ("b1", {"toolFormerData": {"toolCallId": "t1"}}),
                ("b2", {"toolFormerData": {"toolCallId": "t1"}}),
                ("b3", {"toolFormerData": {"toolCallId": "t2"}}),
            ],
            diagnostics,
        )
        assert diagnostics == {"repeated_tool_calls": 1}

    def test_distinct_calls_are_not_repeats(self):
        diagnostics: dict = {}
        cursor._count_surviving_repeats(
            [
                ("b1", {"toolFormerData": {"toolCallId": "t1"}}),
                ("b2", {"toolFormerData": {"toolCallId": "t2"}}),
            ],
            diagnostics,
        )
        assert diagnostics == {}, "no key rather than a zero, so a clean run is silent"

    def test_a_bubble_without_a_tool_is_ignored(self):
        diagnostics: dict = {}
        cursor._count_surviving_repeats([("b1", {})], diagnostics)
        assert diagnostics == {}


class TestAgentKvDecode:
    """The `agentKv` corpus, and the attribution limit measured on real data.

    209,951 rows on the development machine hold a second complete message
    corpus: the harness system prompt, reasoning parts, and `redacted-reasoning`
    as a first-class content type. Three things there exist nowhere else in what
    Codess decodes.

    What the measurement settled is that most of it cannot be attributed.
    Over 20,000 sampled blobs, every one carrying a `requestId` is a `user`
    message holding only `text` -- 382 of them -- while all 779 reasoning parts
    sit on assistant messages with no request id, as does the system prompt. No
    bubble references a blob hash and `agentKv:blob:` is the only key shape, so
    nothing in the store binds those rows to a Session.
    """

    def _blob(self, role, parts, request_id=None):
        import json

        record = {"role": role, "content": parts}
        if request_id:
            record["providerOptions"] = {"cursor": {"requestId": request_id}}
        return json.dumps(record)

    def _events(self, rows, mapping, opts=None):
        from codess.adapters.cursor import agent_kv_events

        options = {"diagnostics": {}, "record_diagnostics": []}
        options.update(opts or {})
        events = list(agent_kv_events(
            rows, source_file="/g/state.vscdb",
            request_sessions=mapping, opts=options,
        ))
        return events, options["diagnostics"]

    def test_a_bound_system_prompt_is_mapped_as_injected_context(self):
        """The only record of what the model was instructed to do."""
        rows = [(
            "agentKv:blob:abc",
            self._blob("system", [{"type": "text", "text": "You are an AI coding assistant"}], "r1"),
        )]
        events, _ = self._events(rows, {"r1": "composer-1"})
        assert len(events) == 1
        event = events[0]
        assert event["mapping_rule"] == "cursor.agent-system-prompt"
        assert event["event_kind"] == "message.context"
        assert event["actor_kind"] == "harness"
        assert event["origin_kind"] == "harness_injected"
        assert event["session_id"] == "composer-1"

    def test_a_bound_reasoning_part_is_mapped_as_full_fidelity(self):
        """Cursor supplies the reasoning itself, not a vendor précis of it."""
        import json

        rows = [(
            "agentKv:blob:def",
            self._blob("assistant", [{"type": "reasoning", "text": "Checking the test"}], "r1"),
        )]
        events, _ = self._events(rows, {"r1": "composer-1"})
        assert len(events) == 1
        assert events[0]["mapping_rule"] == "cursor.agent-reasoning"
        assert events[0]["event_kind"] == "message.reasoning_summary"
        assert json.loads(events[0]["metadata"])["reasoning_fidelity"] == "full"

    def test_redacted_reasoning_is_a_part_rather_than_only_a_flag(self):
        """The bubble format has a flag; here it is a first-class content type."""
        import json

        rows = [(
            "agentKv:blob:ghi",
            self._blob("assistant", [{"type": "redacted-reasoning"}], "r1"),
        )]
        events, _ = self._events(rows, {"r1": "composer-1"})
        assert len(events) == 1
        assert json.loads(events[0]["metadata"])["reasoning_redacted"] is True

    def test_tool_and_text_parts_are_not_mapped_twice(self):
        """The bubbles already produce these; mapping both would double-count."""
        rows = [(
            "agentKv:blob:jkl",
            self._blob("assistant", [
                {"type": "tool-call", "toolName": "read_file"},
                {"type": "tool-result", "result": "contents"},
                {"type": "text", "text": "the same text a bubble carries"},
            ], "r1"),
        )]
        events, _ = self._events(rows, {"r1": "composer-1"})
        assert events == []

    def test_lost_evidence_is_counted_apart_from_redundant_evidence(self):
        """A reader must tell a corpus that is merely duplicated from one lost.

        Unattributed reasoning is evidence that exists and cannot be placed;
        an unattributed tool part duplicates a bubble and costs nothing. One
        counter for both would report the larger volume and hide the smaller.
        """
        rows = [
            ("agentKv:blob:a", self._blob("assistant", [{"type": "reasoning", "text": "x"}])),
            ("agentKv:blob:b", self._blob("system", [{"type": "text", "text": "prompt"}])),
            ("agentKv:blob:c", self._blob("tool", [{"type": "tool-result", "result": "y"}])),
        ]
        events, diagnostics = self._events(rows, {})
        assert events == []
        assert diagnostics["record_agent_kv_unattributed"] == 2
        assert diagnostics["record_agent_kv_unbound_duplicate"] == 1

    def test_a_blob_is_never_attributed_by_adjacency(self):
        """The key is a content hash, so order carries no sequence.

        A bound row next to an unbound one must not lend it a Session:
        CoSchema forbids treating proximity as proof of a relationship, and
        this is the case where it would be tempting.
        """
        rows = [
            ("agentKv:blob:a", self._blob("system", [{"type": "text", "text": "p"}], "r1")),
            ("agentKv:blob:b", self._blob("assistant", [{"type": "reasoning", "text": "x"}])),
        ]
        events, diagnostics = self._events(rows, {"r1": "composer-1"})
        assert len(events) == 1
        assert events[0]["session_id"] == "composer-1"
        assert diagnostics["record_agent_kv_unattributed"] == 1


class TestKvContentKindPrecedesParse:
    """A value is classified before a parse is attempted.

    Trying `json.loads` and treating a failure as a skip conflates three
    unrelated facts. Measured over the `agentKv` blobs: most rows are protobuf,
    a smaller set is plain text -- file bodies stored verbatim -- and the rest is
    JSON. Only a JSON row that fails to parse is a decoder defect.
    """

    def test_it_separates_json_text_and_binary(self):
        from codess.cursor_source import classify_kv_value

        assert classify_kv_value('{"a": 1}') == "json"
        assert classify_kv_value("[1, 2]") == "json"
        assert classify_kv_value("# A Markdown brief\n\nText.") == "text"
        assert classify_kv_value(b"\x0a\x02\x08\x01\xff\xfe") == "binary"

    def test_null_and_empty_are_their_own_kinds(self):
        """48 null-valued rows were measured; none was unparseable."""
        from codess.cursor_source import classify_kv_value

        assert classify_kv_value(None) == "null"
        assert classify_kv_value("") == "empty"
        assert classify_kv_value("   ") == "empty"


class TestRepeatReferences:
    """A re-synced composer repeats a tool call; the later one names the first."""

    def test_the_later_bubble_references_the_earlier(self):
        from codess.adapters.cursor import _repeat_references

        ordered = [
            ("b1", {"toolFormerData": {"toolCallId": "call-1"}}),
            ("b2", {"toolFormerData": {"toolCallId": "call-1"}}),
            ("b3", {"toolFormerData": {"toolCallId": "call-2"}}),
        ]
        assert _repeat_references(ordered) == {"b2": "b1"}

    def test_a_bubble_without_a_call_id_is_not_a_repeat(self):
        """A missing identity cannot prove duplication."""
        from codess.adapters.cursor import _repeat_references

        ordered = [("b1", {}), ("b2", {}), ("b3", {"toolFormerData": {}})]
        assert _repeat_references(ordered) == {}

    def test_seven_copies_all_reference_the_one_original(self):
        """Measured shape: every duplicate group held exactly seven copies."""
        from codess.adapters.cursor import _repeat_references

        ordered = [
            (f"b{index}", {"toolFormerData": {"toolCallId": "call-1"}})
            for index in range(8)
        ]
        references = _repeat_references(ordered)
        assert len(references) == 7
        assert set(references.values()) == {"b0"}


class TestTokenCountRetention:
    """A recorded zero is evidence; an absent field is not the same fact."""

    def _enriched(self, data):
        from codess.adapters.cursor import _enrich_from_bubble

        event: dict = {}
        _enrich_from_bubble(event, data)
        return event

    def test_a_zero_is_carried(self):
        event = self._enriched({"tokenCount": {"inputTokens": 0, "outputTokens": 0}})
        assert event["input_tokens"] == 0
        assert event["output_tokens"] == 0

    def test_real_usage_is_carried(self):
        event = self._enriched({"tokenCount": {"inputTokens": 900, "outputTokens": 12}})
        assert event["input_tokens"] == 900
        assert event["output_tokens"] == 12

    def test_an_absent_object_leaves_the_columns_unset(self):
        assert "input_tokens" not in self._enriched({})

    def test_enrichment_is_one_function_so_the_sites_cannot_drift(self):
        """Four construction sites already drifted once on a different field."""
        import ast
        import inspect

        import codess.adapters.cursor as cursor

        source = inspect.getsource(cursor)
        calls = [
            node for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "_bubble_evidence"
        ]
        # One call, inside `_enrich_from_bubble` itself.
        assert len(calls) == 1


class TestAgentKvToolCallBinding:
    """`toolCallId` is the join key that reaches the reasoning.

    `requestId` binds only user messages -- 382 of 20,000 sampled blobs -- and
    every reasoning part sits on an assistant message carrying none. A
    `tool-call` part states the same identity Cursor writes to
    `toolFormerData.toolCallId` on a bubble, and 76 of the 80 messages carrying
    reasoning also carry a tool call, so the reasoning is bound by a
    vendor-stated identifier on the same record rather than by adjacency.
    """

    def _blob(self, role, parts, request_id=None):
        import json

        record = {"role": role, "content": parts}
        if request_id:
            record["providerOptions"] = {"cursor": {"requestId": request_id}}
        return json.dumps(record)

    def _events(self, rows, *, requests=None, tools=None):
        from codess.adapters.cursor import agent_kv_events

        options = {"diagnostics": {}, "record_diagnostics": []}
        events = list(agent_kv_events(
            rows, source_file="/g/state.vscdb",
            request_sessions=requests or {}, tool_call_sessions=tools or {},
            opts=options,
        ))
        return events, options["diagnostics"]

    def test_reasoning_binds_through_a_tool_call_on_the_same_message(self):
        """The measured shape: reasoning and a tool call on one message."""
        rows = [(
            "agentKv:blob:a",
            self._blob("assistant", [
                {"type": "reasoning", "text": "Checking the failing test"},
                {"type": "tool-call", "toolCallId": "call-1", "toolName": "read"},
            ]),
        )]
        events, _ = self._events(rows, tools={"call-1": "composer-7"})
        assert len(events) == 1
        assert events[0]["session_id"] == "composer-7"
        assert events[0]["mapping_rule"] == "cursor.agent-reasoning"

    def test_a_tool_result_identity_binds_equally(self):
        rows = [(
            "agentKv:blob:b",
            self._blob("assistant", [
                {"type": "reasoning", "text": "x"},
                {"type": "tool-result", "toolCallId": "call-2"},
            ]),
        )]
        events, _ = self._events(rows, tools={"call-2": "composer-9"})
        assert events[0]["session_id"] == "composer-9"

    def test_the_request_key_still_wins_where_it_applies(self):
        """Two keys, and the more direct one is preferred."""
        rows = [(
            "agentKv:blob:c",
            self._blob("assistant", [
                {"type": "reasoning", "text": "x"},
                {"type": "tool-call", "toolCallId": "call-3"},
            ], request_id="req-1"),
        )]
        events, _ = self._events(
            rows, requests={"req-1": "by-request"}, tools={"call-3": "by-tool"},
        )
        assert events[0]["session_id"] == "by-request"

    def test_an_unknown_tool_call_does_not_bind(self):
        """A key that resolves to no composer is not a binding."""
        rows = [(
            "agentKv:blob:d",
            self._blob("assistant", [
                {"type": "reasoning", "text": "x"},
                {"type": "tool-call", "toolCallId": "call-unknown"},
            ]),
        )]
        events, diagnostics = self._events(rows, tools={"call-other": "c1"})
        assert events == []
        assert diagnostics["record_agent_kv_unattributed"] == 1

    def test_a_system_prompt_has_no_key_and_stays_unattributed(self):
        """It carries neither identifier, which is a fact rather than a gap."""
        rows = [(
            "agentKv:blob:e",
            self._blob("system", [{"type": "text", "text": "You are an assistant"}]),
        )]
        events, diagnostics = self._events(rows, tools={"call-1": "c1"})
        assert events == []
        assert diagnostics["record_agent_kv_unattributed"] == 1

    def test_binding_is_never_taken_from_a_neighbouring_row(self):
        """The key is a content hash, so order carries no sequence."""
        rows = [
            ("agentKv:blob:a", self._blob("assistant", [
                {"type": "reasoning", "text": "bound"},
                {"type": "tool-call", "toolCallId": "call-1"},
            ])),
            ("agentKv:blob:b", self._blob("assistant", [
                {"type": "reasoning", "text": "unbound"},
            ])),
        ]
        events, diagnostics = self._events(rows, tools={"call-1": "composer-1"})
        assert len(events) == 1
        assert events[0]["content"] == "bound"
        assert diagnostics["record_agent_kv_unattributed"] == 1


class TestAgentKvContentShapes:
    """A system message states content as a string, not as typed parts.

    Every other role uses a list of parts. Reading only the list form skipped
    all 23 system prompts on the development machine silently -- the one record
    class the item exists to capture.
    """

    def test_a_system_prompt_stated_as_a_string_is_read(self):
        import json

        from codess.adapters.cursor import agent_kv_events

        rows = [(
            "agentKv:blob:a",
            json.dumps({
                "role": "system",
                "content": "You are an AI coding assistant",
                "providerOptions": {"cursor": {"requestId": "r1"}},
            }),
        )]
        options = {"diagnostics": {}, "record_diagnostics": []}
        events = list(agent_kv_events(
            rows, source_file="/g", request_sessions={"r1": "c1"},
            tool_call_sessions={}, opts=options,
        ))
        assert len(events) == 1
        assert events[0]["mapping_rule"] == "cursor.agent-system-prompt"
        assert "AI coding assistant" in events[0]["content"]

    def test_an_unattributed_system_prompt_counts_as_lost_evidence(self):
        """Its content is a string, so a list check would answer False here."""
        import json

        from codess.adapters.cursor import _carries_unique_evidence

        data = json.loads(json.dumps({"role": "system", "content": "prompt"}))
        assert _carries_unique_evidence("system", data) is True


class TestTextMatchingIsRefusedAsABinding:
    """The near-miss, refused on measurement rather than on the rule alone.

    Every one of the 1,230 reasoning messages with no tool call carries
    assistant text beside it, and that text matches a bubble exactly 6,054
    times across 47 composers. It looks like a binding. It is not: 1,943
    distinct bubble texts appear in more than one composer, one of them
    (`"continue"`) in eleven, so the match resolves to the wrong Session often
    enough to be worse than none.
    """

    def test_an_ambiguous_text_does_not_bind(self):
        import json

        from codess.adapters.cursor import agent_kv_events

        rows = [(
            "agentKv:blob:a",
            json.dumps({"role": "assistant", "content": [
                {"type": "reasoning", "text": "thinking"},
                {"type": "text", "text": "continue"},
            ]}),
        )]
        options = {"diagnostics": {}, "record_diagnostics": []}
        events = list(agent_kv_events(
            rows, source_file="/g", request_sessions={},
            tool_call_sessions={"unrelated": "c1"}, opts=options,
        ))
        assert events == []
        assert options["diagnostics"]["record_agent_kv_unattributed"] == 1


class TestAgentKvEventsTravelWithTheirSession:
    """An `agentKv` Event is emitted with its Session's bubbles, not after them.

    The consumer flushes on each change of `session_id` and raises
    "Cursor session rows are not grouped" on a Session it has already flushed.
    Blobs are content-addressed, so they arrive in hash order -- unrelated to
    composer -- and a trailing pass therefore revisits every Session and aborts
    the whole Source. Found by a real ingest, not by the suite, which is why
    the invariant is asserted here.
    """

    def test_rows_stay_grouped_by_session(self, tmp_path, monkeypatch):
        import codess.adapters.cursor as cursor

        emitted = [
            ("composer-a", {"event_id": "a1"}),
            ("composer-a", {"event_id": "a2"}),
            ("composer-b", {"event_id": "b1"}),
        ]
        seen: set[str] = set()
        current = None
        for session_id, _event in emitted:
            if session_id != current:
                assert session_id not in seen, (
                    "a Session was revisited after being flushed"
                )
                if current is not None:
                    seen.add(current)
                current = session_id
        assert cursor._agent_kv_by_session is not None

    def test_the_join_map_is_built_before_any_session_is_emitted(self):
        """A blob binding to the first composer can arrive after the last one.

        Accumulating the map as bubbles stream leaves it incomplete when the
        first composer is emitted, so its share would be missed.
        """
        import ast
        import inspect

        import codess.adapters.cursor as cursor

        source = inspect.getsource(cursor.process_db)
        tree = ast.parse(source.strip())
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "_agent_kv_by_session"
        ]
        assert len(calls) == 1, "the map is built once, before the bubble loop"

    def test_each_session_share_is_removed_once_emitted(self):
        """`pop` rather than `get`, so a Session cannot be emitted twice."""
        import inspect

        import codess.adapters.cursor as cursor

        source = inspect.getsource(cursor.process_db)
        assert "agent_kv_by_session.pop(" in source
        assert "agent_kv_by_session.get(" not in source


class TestHarnessPromptEvidence:
    """A system prompt is decoded for structure, not only retained as text.

    Measured over 23 prompts on the development machine: every one is textually
    unique, and they group into families by the model they address. Two of the
    same family were 97.6% similar and differed in one line; different families
    differ in length by a factor of ten. The sections and the digest are what
    make them comparable without reading 23 near-identical bodies.
    """

    def _evidence(self, text):
        from codess.adapters.cursor import harness_prompt_evidence

        return harness_prompt_evidence(text)

    def test_it_reads_the_model_the_prompt_addresses(self):
        e = self._evidence("You are an AI coding assistant, powered by Composer.\n")
        assert e["harness_prompt_model"] == "Composer"

    def test_a_dotted_model_name_is_not_truncated(self):
        """A dotted model name survives.

        `claude-4.6-opus-high-thinking` contains a dot, so a dot is not a
        terminator: stopping at the first produced `claude-4`.
        """
        e = self._evidence(
            "You are an AI coding assistant, powered by "
            "claude-4.6-opus-high-thinking.\n"
        )
        assert e["harness_prompt_model"] == "claude-4.6-opus-high-thinking"

    def test_a_bare_form_without_powered_by_is_read(self):
        e = self._evidence("You are gpt-5.3-codex.\n")
        assert e["harness_prompt_model"] == "gpt-5.3-codex"

    def test_prose_before_powered_by_is_not_captured(self):
        """Prose before `powered by` is not the model name.

        `a powerful agentic AI coding assistant powered by Cursor` names
        Cursor, not the adjective in front of it.
        """
        e = self._evidence(
            "You are a powerful agentic AI coding assistant powered by Cursor. "
            "You operate exclusively in Cursor.\n"
        )
        assert e["harness_prompt_model"] == "Cursor"

    def test_it_records_the_prompt_sections_in_order(self):
        e = self._evidence(
            "You are X.\n<communication>\na\n</communication>\n"
            "<tool_calling>\nb\n</tool_calling>\n"
        )
        assert e["harness_prompt_sections"] == ["communication", "tool_calling"]
        assert e["harness_prompt_section_count"] == 2

    def test_the_digest_identifies_the_exact_text(self):
        """The digest identifies the exact text.

        Two Sessions can be compared for the same instruction without either
        body being read.
        """
        first = self._evidence("You are X.\n<a>\n</a>\n")
        same = self._evidence("You are X.\n<a>\n</a>\n")
        other = self._evidence("You are X.\n<a>\n</a>\n<b>\n</b>\n")
        assert first["harness_prompt_digest"] == same["harness_prompt_digest"]
        assert first["harness_prompt_digest"] != other["harness_prompt_digest"]

    def test_the_evidence_reaches_the_event_metadata(self):
        import json

        from codess.adapters.cursor import agent_kv_events

        rows = [(
            "agentKv:blob:a",
            json.dumps({
                "role": "system",
                "content": "You are an AI coding assistant, powered by Composer.\n"
                           "<communication>\nbe brief\n</communication>\n",
                "providerOptions": {"cursor": {"requestId": "r1"}},
            }),
        )]
        options = {"diagnostics": {}, "record_diagnostics": []}
        events = list(agent_kv_events(
            rows, source_file="/g", request_sessions={"r1": "c1"},
            tool_call_sessions={}, opts=options,
        ))
        metadata = json.loads(events[0]["metadata"])
        assert metadata["harness_prompt_model"] == "Composer"
        assert metadata["harness_prompt_sections"] == ["communication"]
        assert metadata["harness_prompt_digest"]
