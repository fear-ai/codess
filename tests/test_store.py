"""Store and state edge cases."""

import json
import os
from pathlib import Path

from codess.store import (
    init_db,
    ingest_state_marker,
    load_ingest_state,
    save_ingest_state,
    should_ingest,
    connect,
    replace_session_events,
    ensure_source,
    prune_unreferenced_source_revisions,
    replace_source_sessions,
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

    def test_content_change_with_same_mtime_and_size_is_detected(self, tmp_path):
        source = tmp_path / "source.jsonl"
        source.write_text("aaaa\n", encoding="utf-8")
        original = source.stat()
        state_path = tmp_path / "state.json"
        marker = ingest_state_marker(source)
        assert marker["source_revision"].startswith("sha256-fingerprint:")
        assert marker["fingerprint_method"] == "full-sha256-fingerprint"
        save_ingest_state(state_path, {"source": marker})
        assert not should_ingest(
            state_path, "source", original.st_mtime, False, path=source
        )
        source.write_text("bbbb\n", encoding="utf-8")
        os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
        assert should_ingest(
            state_path, "source", original.st_mtime, False, path=source
        )

    def test_sqlite_wal_only_change_is_detected(self, tmp_path):
        source = tmp_path / "state.vscdb"
        source.write_bytes(b"sqlite-main")
        wal = Path(str(source) + "-wal")
        wal.write_bytes(b"wal-one")
        state_path = tmp_path / "state.json"
        marker = ingest_state_marker(source)
        assert marker["source_revision"].startswith(
            "sqlite-main-wal-sha256-fingerprint:"
        )
        assert marker["fingerprint_method"] == (
            "full-sha256-fingerprint+wal:full-sha256-fingerprint"
        )
        save_ingest_state(state_path, {"cursor": marker})
        wal.write_bytes(b"wal-two")
        assert should_ingest(
            state_path, "cursor", source.stat().st_mtime, False, path=source
        )

    def test_large_source_uses_labelled_sampled_sha256(
        self, tmp_path, monkeypatch
    ):
        source = tmp_path / "large.jsonl"
        source.write_bytes(b"0123456789")
        monkeypatch.setattr("codess.fileio.SOURCE_FULL_HASH_MAX", 4)
        marker = ingest_state_marker(source)
        assert marker["source_revision"].startswith(
            "sample-sha256-fingerprint:"
        )
        assert marker["fingerprint_method"] == (
            "bounded-sample-sha256-fingerprint"
        )


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

    def test_long_source_call_id_uses_bounded_relational_key(self, tmp_path):
        db = tmp_path / "calls.db"
        init_db(db)
        conn = connect(db)
        exact = "call-" + ("🙂" * 40) + "-vendor-tail"
        metadata = json.dumps({"call_id": exact})
        replace_session_events(
            conn,
            {"id": "s1", "source": "Codex", "type": "Code"},
            [
                {
                    "session_id": "s1", "event_id": "call",
                    "event_type": "tool_call", "subtype": "tool_call",
                    "tool_name": "example", "metadata": metadata,
                },
                {
                    "session_id": "s1", "event_id": "result",
                    "event_type": "user_message", "subtype": "tool_result",
                    "tool_name": "example", "tool_output": "ok",
                    "metadata": metadata,
                },
            ],
            session_id="s1",
        )
        row = conn.execute(
            "SELECT source_call_id FROM tool_invocations"
        ).fetchone()
        assert len(row["source_call_id"].encode("utf-8")) <= 100
        assert "~sha256:" in row["source_call_id"]
        assert conn.execute(
            "SELECT COUNT(*) FROM tool_results"
        ).fetchone()[0] == 1
        stored = conn.execute(
            "SELECT metadata FROM events WHERE event_id='call'"
        ).fetchone()
        assert json.loads(stored["metadata"])["call_id"] == exact
        conn.close()

    def test_explicit_source_observation_uses_captured_revision(self, tmp_path):
        db = tmp_path / "source.db"
        init_db(db)
        conn = connect(db)
        source_id = ensure_source(
            conn,
            source="Cursor",
            source_file="/original/Cursor/state.vscdb",
            observation={
                "source_revision_id": "sha256:captured",
                "source_mtime_ns": 1_750_000_000_000_000_000,
                "source_size": 1234,
                "capture_method": "sqlite-backup",
                "consistency": "transactional",
                "availability": "captured",
            },
        )
        row = conn.execute(
            "SELECT source_uri, source_revision, source_size, availability, "
            "capture_method, consistency FROM sources WHERE id=?",
            (source_id,),
        ).fetchone()
        assert tuple(row) == (
            "/original/Cursor/state.vscdb",
            "sha256:captured",
            1234,
            "captured",
            "sqlite-backup",
            "transactional",
        )
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

    def test_replace_session_removes_stale_events_and_rolls_back(self, tmp_path):
        db = tmp_path / "s.db"
        init_db(db)
        conn = connect(db)
        session = {
            "id": "s1", "source": "Claude", "type": "Code",
            "started_at": 1.0,
        }
        old_events = [
            {"session_id": "s1", "event_id": str(i), "content": f"old-{i}"}
            for i in (1, 2)
        ]
        replace_session_events(
            conn, session, old_events, session_id="s1"
        )
        conn.commit()

        replacement = [
            {"session_id": "s1", "event_id": "1", "content": "new"}
        ]
        replace_session_events(
            conn, session, replacement, session_id="s1"
        )
        assert [
            tuple(row)
            for row in conn.execute("SELECT event_id, content FROM events")
        ] == [("1", "new")]
        conn.rollback()
        assert [
            tuple(row)
            for row in conn.execute(
                "SELECT event_id, content FROM events ORDER BY event_id"
            )
        ] == [("1", "old-1"), ("2", "old-2")]
        conn.close()

    def test_explicit_open_semantics_do_not_create_unmapped_diagnostic(self, tmp_path):
        db = tmp_path / "s.db"
        init_db(db)
        conn = connect(db)
        replace_session_events(
            conn,
            {"id": "s1", "source": "Claude", "type": "Code"},
            [{
                "session_id": "s1", "event_id": "1",
                "event_type": "product_state", "subtype": "mode",
                "role": "harness", "event_kind": "state.product",
                "actor_kind": "harness", "content_role": "state",
                "origin_kind": "harness_generated",
            }],
            session_id="s1",
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM mapping_diagnostics"
        ).fetchone()[0] == 0
        assert tuple(conn.execute(
            "SELECT event_kind, actor_kind, content_role, origin_kind FROM events"
        ).fetchone()) == (
            "state.product", "harness", "state", "harness_generated"
        )
        conn.close()

    def test_replace_empty_session_removes_previous_session(self, tmp_path):
        db = tmp_path / "s.db"
        init_db(db)
        conn = connect(db)
        session = {
            "id": "s1", "source": "Codex", "type": "Code",
            "started_at": 1.0,
        }
        replace_session_events(
            conn,
            session,
            [{"session_id": "s1", "event_id": "1"}],
            session_id="s1",
        )
        replace_session_events(conn, None, [], session_id="s1")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        conn.close()

    def test_reingest_prunes_superseded_source_revision_records(self, tmp_path):
        db = tmp_path / "s.db"
        init_db(db)
        conn = connect(db)
        session = {"id": "s1", "source": "Cursor", "type": "IDE"}

        def replace(revision: str) -> None:
            current = {
                **session,
                "source_observation": {
                    "source_revision_id": revision,
                    "source_size": 100,
                    "capture_method": "sqlite-backup",
                    "consistency": "transactional-snapshot",
                    "availability": "captured",
                },
            }
            replace_session_events(
                conn,
                current,
                [{
                    "session_id": "s1", "event_id": "one",
                    "source_file": "/Cursor/state.vscdb",
                    "source_record_locator": "bubble:one", "content": "same",
                }],
                session_id="s1",
            )
            conn.commit()

        replace("sha256:first")
        replace("sha256:second")
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM source_records").fetchone()[0] == 1
        assert conn.execute(
            "SELECT source_revision FROM sources"
        ).fetchone()[0] == "sha256:second"
        assert prune_unreferenced_source_revisions(conn) == 0
        conn.close()

    def test_replace_source_removes_only_orphaned_sessions(self, tmp_path):
        db = tmp_path / "s.db"
        init_db(db)
        conn = connect(db)
        sessions = {
            sid: {
                "id": sid, "source": "Cursor", "type": "IDE",
                "started_at": 1.0,
            }
            for sid in ("gone", "shared")
        }
        replace_source_sessions(
            conn,
            "/one.db",
            sessions,
            [
                {"session_id": "gone", "event_id": "1", "source_file": "/one.db"},
                {"session_id": "shared", "event_id": "1", "source_file": "/one.db"},
            ],
        )
        replace_source_sessions(
            conn,
            "/two.db",
            {"shared": sessions["shared"]},
            [{"session_id": "shared", "event_id": "2", "source_file": "/two.db"}],
        )
        conn.commit()

        replace_source_sessions(conn, "/one.db", {}, [])
        conn.commit()
        assert [
            row[0] for row in conn.execute("SELECT id FROM sessions ORDER BY id")
        ] == ["shared"]
        assert [
            row[0] for row in conn.execute("SELECT source_file FROM events")
        ] == ["/two.db"]
        conn.close()
