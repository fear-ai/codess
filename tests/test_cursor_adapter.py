"""Tests for Cursor adapter."""

import json
import sqlite3
from pathlib import Path

import pytest

from codess.adapters.cursor import _bubble_to_events, _iter_bubbles, get_db_metrics, process_db


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


class TestBubbleToEvents:
    """_bubble_to_events unit tests."""

    def test_user_prompt(self):
        data = {"type": 1, "text": "Hello", "timingInfo": {"clientStartTime": 1000}}
        evs = list(_bubble_to_events("c1", "b1", data, "/db", False))
        assert len(evs) == 1
        assert evs[0]["event_type"] == "user_message"
        assert evs[0]["subtype"] == "prompt"
        assert evs[0]["content"] == "Hello"

    def test_user_slash_command(self):
        data = {"type": 1, "text": "/fix bug", "timingInfo": {}}
        evs = list(_bubble_to_events("c1", "b1", data, "/db", False))
        assert evs[0]["subtype"] == "slash_command"

    def test_assistant_response(self):
        data = {"type": 2, "text": "Here is the fix.", "timingInfo": {"clientStartTime": 2000}}
        evs = list(_bubble_to_events("c1", "b1", data, "/db", False))
        assert len(evs) == 1
        assert evs[0]["event_type"] == "assistant_message"
        assert evs[0]["subtype"] == "response"
        assert evs[0]["content"] == "Here is the fix."

    def test_assistant_dialog_empty_text(self):
        data = {"type": 2, "text": "", "timingInfo": {}}
        evs = list(_bubble_to_events("c1", "b1", data, "/db", False))
        assert evs[0]["subtype"] == "dialog"

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

    def test_process_db_sorts_by_timing(self, tmp_path):
        bubbles = [
            ("c1", "b2", {"type": 1, "text": "second", "timingInfo": {"clientStartTime": 2}}),
            ("c1", "b1", {"type": 1, "text": "first", "timingInfo": {"clientStartTime": 1}}),
        ]
        db = _make_cursor_db(tmp_path, bubbles)
        out = list(process_db(db, "/proj", {}))
        assert out[0][1]["content"] == "first"
        assert out[1][1]["content"] == "second"
