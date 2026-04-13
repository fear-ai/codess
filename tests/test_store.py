"""Store and state edge cases."""

from pathlib import Path

import pytest

from codess.store import (
    init_db,
    load_ingest_state,
    save_ingest_state,
    should_ingest,
    connect,
    upsert_event,
    upsert_session,
)


class TestLoadIngestState:
    """load_ingest_state edge cases."""

    def test_missing_file(self, tmp_path):
        assert load_ingest_state(tmp_path / "nonexistent.json") == {}

    def test_empty_file(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text("")
        assert load_ingest_state(p) == {}

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text("{invalid")
        assert load_ingest_state(p) == {}

    def test_valid(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text('{"f1": 123.0}')
        assert load_ingest_state(p) == {"f1": 123.0}


class TestSaveIngestState:
    """save_ingest_state creates dir."""

    def test_creates_parent_dir(self, tmp_path):
        p = tmp_path / "sub" / "state.json"
        save_ingest_state(p, {"a": 1.0})
        assert p.exists()
        assert load_ingest_state(p) == {"a": 1.0}


class TestShouldIngest:
    """should_ingest logic."""

    def test_force_always_true(self, tmp_path):
        assert should_ingest(tmp_path / "x.json", "/f", 1.0, force=True)

    def test_mtime_changed(self, tmp_path):
        p = tmp_path / "state.json"
        save_ingest_state(p, {"/old": 100.0})
        assert should_ingest(p, "/new", 200.0, force=False)
        assert should_ingest(p, "/old", 99.0, force=False)

    def test_mtime_unchanged_skip(self, tmp_path):
        p = tmp_path / "state.json"
        save_ingest_state(p, {"/f": 123.0})
        assert not should_ingest(p, "/f", 123.0, force=False)


class TestInitDb:
    """init_db creates schema."""

    def test_creates_dir_and_tables(self, tmp_path):
        db = tmp_path / "sub" / "sessions.db"
        init_db(db)
        assert db.exists()
        conn = connect(db)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        assert "sessions" in tables and "events" in tables
        conn.close()


class TestUpsert:
    """upsert_session and upsert_event."""

    def test_upsert_idempotent(self, tmp_path):
        init_db(tmp_path / "s.db")
        conn = connect(tmp_path / "s.db")
        upsert_session(conn, {
            "id": "s1", "source": "Claude", "type": "Code",
            "started_at": 1.0, "ended_at": 2.0,
        })
        ev = {
            "session_id": "s1", "event_id": "1", "event_type": "user_message",
            "subtype": "prompt", "role": "user", "content": "hi",
            "content_len": 2, "source_file": "/f",
        }
        upsert_event(conn, ev)
        conn.commit()
        cur = conn.execute("SELECT COUNT(*) FROM events")
        n1 = cur.fetchone()[0]
        upsert_event(conn, ev)
        conn.commit()
        cur = conn.execute("SELECT COUNT(*) FROM events")
        n2 = cur.fetchone()[0]
        assert n1 == n2 == 1
        conn.close()
