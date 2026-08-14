"""Store and state edge cases."""

import json
import os
from pathlib import Path

import pytest

from codess.fileio import open_readonly
from codess.schema_contract import column_names, store_metadata, table_names
from codess.store import (
    connect,
    drop_sessions_absent_from_source,
    ensure_source,
    ingest_state_marker,
    init_db,
    integrity_report,
    load_ingest_state,
    prune_unreferenced_source_revisions,
    replace_session_events,
    save_ingest_state,
    session_ids_for_source,
    should_ingest,
    table_counts,
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

    def test_model_turn_inherits_session_default_configuration(self, tmp_path):
        db = tmp_path / "default-model.db"
        init_db(db)
        conn = connect(db)
        replace_session_events(
            conn,
            {
                "id": "s1",
                "source": "Codex",
                "type": "Code",
                "metadata": {
                    "model_provider": "openai",
                    "model": "gpt-default",
                    "reasoning_effort": "medium",
                },
            },
            [
                {
                    "session_id": "s1",
                    "event_id": "response",
                    "event_type": "assistant_message",
                    "subtype": "response",
                    "role": "assistant",
                    "content": "autonomous response",
                },
            ],
            session_id="s1",
        )
        row = conn.execute(
            """
            SELECT mc.model_name_exact,mc.reasoning_effort
            FROM model_turns mt
            JOIN model_params mc ON mc.id=mt.model_param_id
            WHERE mt.session_id='s1'
            """
        ).fetchone()
        assert tuple(row) == ("gpt-default", "medium")
        conn.close()

    def test_model_turn_retains_inherited_configuration_provenance(
        self, tmp_path
    ):
        db = tmp_path / "inherited-configuration.db"
        init_db(db)
        conn = connect(db)
        replace_session_events(
            conn,
            {"id": "s1", "source": "Cursor", "type": "Code"},
            [
                {
                    "session_id": "s1",
                    "event_id": "selection",
                    "event_type": "user_message",
                    "subtype": "prompt",
                    "role": "user",
                    "content": "continue",
                    "source_record_locator": "bubble:user:1",
                    "metadata": {
                        "model": "composer-test",
                        "configuration_provenance": {
                            "model": {
                                "source_field": "modelInfo.modelName",
                                "source_record_locator": "bubble:user:1",
                                "source_record_type": "bubble.user",
                            },
                        },
                    },
                },
                {
                    "session_id": "s1",
                    "event_id": "response",
                    "event_type": "assistant_message",
                    "subtype": "response",
                    "role": "assistant",
                    "content": "done",
                    "source_record_locator": "bubble:assistant:2",
                },
            ],
            session_id="s1",
        )
        row = conn.execute(
            """
            SELECT e.metadata,mc.model_name_exact
            FROM events e
            JOIN model_turns mt ON mt.id=e.model_turn_id
            JOIN model_params mc ON mc.id=mt.model_param_id
            WHERE e.event_id='response'
            """
        ).fetchone()
        metadata = json.loads(row["metadata"])
        assert row["model_name_exact"] == "composer-test"
        assert metadata["configuration_provenance"]["model"][
            "source_field"
        ] == "modelInfo.modelName"
        assert metadata["configuration_provenance_scope"] == {
            "state": "inherited",
            "governing_event_id": "selection",
            "governing_source_record_locator": "bubble:user:1",
        }
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
            "SELECT source_path, source_revision, source_size, availability, "
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
        """A Session another source still contributes to must survive.

        One Cursor database can hold Sessions that another also wrote Events
        for, so removing a Session outright when one source stops carrying it
        would discard evidence that source never owned.
        """
        db = tmp_path / "s.db"
        init_db(db)
        conn = connect(db)
        for sid in ("gone", "shared"):
            replace_session_events(
                conn,
                {"id": sid, "source": "Cursor", "type": "IDE", "started_at": 1.0},
                [{"session_id": sid, "event_id": "1", "source_file": "/one.db"}],
                session_id=sid,
                prune=False,
            )
        replace_session_events(
            conn,
            {"id": "shared", "source": "Cursor", "type": "IDE", "started_at": 1.0},
            [
                {"session_id": "shared", "event_id": "1", "source_file": "/one.db"},
                {"session_id": "shared", "event_id": "2", "source_file": "/two.db"},
            ],
            session_id="shared",
            prune=False,
        )
        conn.commit()
        assert session_ids_for_source(conn, "/one.db") == {"gone", "shared"}

        # `/one.db` no longer contains either Session.
        drop_sessions_absent_from_source(
            conn, "/one.db", session_ids_for_source(conn, "/one.db"),
        )
        conn.commit()
        assert [
            row[0] for row in conn.execute("SELECT id FROM sessions ORDER BY id")
        ] == ["shared"]
        assert [
            row[0] for row in conn.execute("SELECT source_file FROM events")
        ] == ["/two.db"]
        conn.close()


class TestSharedStoreReads:
    """Reads that several modules had each written out for themselves.

    Each of these replaced two or more copies of the same statement, so the
    tests here are what keeps the single definition honest for every caller.
    """

    def test_table_names_reports_what_the_store_has(self, tmp_path):
        db = tmp_path / "s.db"
        init_db(db)
        conn = connect(db)
        try:
            names = table_names(conn)
            assert {"sessions", "events", "store_meta"} <= names
            assert "not_a_table" not in names
        finally:
            conn.close()

    def test_column_names_reports_one_table_shape(self, tmp_path):
        db = tmp_path / "s.db"
        init_db(db)
        conn = connect(db)
        try:
            columns = column_names(conn, "sessions")
            assert {"id", "entity_id", "project_id"} <= columns
        finally:
            conn.close()

    def test_counts_cover_every_table_by_default(self, tmp_path):
        """The list is derived, so it cannot drift from the schema."""
        db = tmp_path / "s.db"
        init_db(db)
        conn = connect(db)
        try:
            counts = table_counts(conn)
            assert set(counts) == table_names(conn)
            # A new store holds only its own metadata rows.
            assert counts["sessions"] == 0 and counts["events"] == 0
            assert counts["store_meta"] > 0
        finally:
            conn.close()

    def test_counts_can_be_restricted_to_named_tables(self, tmp_path):
        db = tmp_path / "s.db"
        init_db(db)
        conn = connect(db)
        try:
            assert set(table_counts(conn, ("sessions", "events"))) == {
                "sessions", "events",
            }
        finally:
            conn.close()

    def test_a_table_the_store_lacks_is_omitted_not_zero(self, tmp_path):
        """A missing table is a different fact from an empty one."""
        db = tmp_path / "s.db"
        init_db(db)
        conn = connect(db)
        try:
            assert table_counts(conn, ("sessions", "absent_table")) == {
                "sessions": 0,
            }
        finally:
            conn.close()

    def test_counts_follow_what_was_written(self, tmp_path):
        db = tmp_path / "s.db"
        init_db(db)
        conn = connect(db)
        try:
            replace_session_events(
                conn,
                {"id": "s1", "source": "Claude", "type": "Code", "started_at": 1.0},
                [{"session_id": "s1", "event_id": "e1"}],
                session_id="s1",
            )
            conn.commit()
            counts = table_counts(conn, ("sessions", "events"))
            assert counts == {"sessions": 1, "events": 1}
        finally:
            conn.close()

    def test_integrity_report_states_both_structural_checks(self, tmp_path):
        """`integrity_check` misses referential faults, so both are reported."""
        db = tmp_path / "s.db"
        init_db(db)
        conn = connect(db)
        try:
            report = integrity_report(conn)
            assert report == {"integrity_check": "ok", "foreign_key_violations": 0}
        finally:
            conn.close()

    def test_store_metadata_reads_the_key_value_table(self, tmp_path):
        db = tmp_path / "s.db"
        init_db(db)
        conn = connect(db)
        try:
            meta = store_metadata(conn)
            assert meta["format_id"] == "codess.coschema"
            assert meta["package_digest"]
        finally:
            conn.close()

    def test_a_read_only_open_refuses_writes(self, tmp_path):
        """Every hand-written read-only open now carries `query_only`."""
        import sqlite3 as sqlite

        db = tmp_path / "s.db"
        init_db(db)
        conn = open_readonly(db)
        try:
            with pytest.raises(sqlite.OperationalError):
                conn.execute("INSERT INTO store_meta(key, value) VALUES ('k','v')")
        finally:
            conn.close()

    def test_a_read_only_open_does_not_require_a_coschema_store(self, tmp_path):
        """Its callers open files precisely because the contract may not hold."""
        import sqlite3 as sqlite

        foreign = tmp_path / "foreign.db"
        setup = sqlite.connect(foreign)
        setup.execute("CREATE TABLE unrelated(id INTEGER)")
        setup.commit()
        setup.close()
        conn = open_readonly(foreign)
        try:
            assert table_names(conn) == {"unrelated"}
        finally:
            conn.close()


class TestInvocationKind:
    """What evidence an invocation rests on, rather than a constant.

    `invocation_kind` was written as `harness_capability` for every row, so
    the column that should distinguish a model's request from a
    harness-observed operation carried nothing. Codex records both --
    `patch_apply_end` and `web_search_end` are operations the harness
    performed and reported -- and 461 of one Project's invocations are the
    latter (13.4.9).
    """

    def write(self, tmp_path, events: list[dict]):
        """Write through the real path: `_record_tool` runs inside it."""
        db = tmp_path / "s.db"
        init_db(db)
        conn = connect(db)
        replace_session_events(
            conn,
            {"id": "s1", "source": "Codex", "type": "Code", "started_at": 1.0},
            events,
            session_id="s1",
            prune=False,
        )
        conn.commit()
        return conn

    def call(self, **overrides) -> dict:
        event = {
            "session_id": "s1", "event_id": "e1", "event_type": "tool_call",
            "tool_name": "Read", "metadata": json.dumps({"call_id": "c1"}),
            "timestamp": 1.0,
        }
        event.update(overrides)
        return event

    def kinds(self, conn) -> dict:
        return dict(conn.execute(
            "SELECT invocation_kind, COUNT(*) FROM tool_invocations GROUP BY 1"
        ))

    def test_a_model_request_is_recorded_as_such(self, tmp_path):
        conn = self.write(tmp_path, [self.call()])
        try:
            assert self.kinds(conn) == {"model_requested": 1}
        finally:
            conn.close()

    def test_a_result_without_a_request_is_harness_observed(self, tmp_path):
        """The harness reporting what it did, with no model call recorded."""
        conn = self.write(tmp_path, [self.call(
            event_id="r1", event_type="user_message", subtype="tool_result",
            metadata=json.dumps({"call_id": "only-result"}),
        )])
        try:
            assert self.kinds(conn) == {"harness_observed": 1}
        finally:
            conn.close()

    def test_a_request_arriving_after_its_result_promotes_the_kind(self, tmp_path):
        """Absence of evidence at one moment is not evidence of absence.

        A store can see the result before the request. The value is promoted
        when the request arrives and never demoted, so the completed pair
        reads as what it is.
        """
        result = self.call(
            event_id="r1", event_type="user_message", subtype="tool_result",
        )
        conn = self.write(tmp_path, [result])
        try:
            assert self.kinds(conn) == {"harness_observed": 1}
            # The request arrives in a later write of the same Session, as it
            # would when a source is re-read and the pair completes.
            replace_session_events(
                conn,
                {"id": "s1", "source": "Codex", "type": "Code", "started_at": 1.0},
                [result, self.call()],
                session_id="s1",
                prune=False,
            )
            conn.commit()
            assert self.kinds(conn) == {"model_requested": 1}
        finally:
            conn.close()

    def test_a_later_result_does_not_demote_a_request(self, tmp_path):
        conn = self.write(tmp_path, [
            self.call(),
            self.call(event_id="r1", event_type="user_message", subtype="tool_result"),
        ])
        try:
            assert self.kinds(conn) == {"model_requested": 1}
        finally:
            conn.close()

    def test_the_kind_agrees_with_the_evidence_it_is_derived_from(self, tmp_path):
        """The column must never disagree with `requested_event_id`."""
        conn = self.write(tmp_path, [
            self.call(),
            self.call(event_id="r2", event_type="user_message",
                      subtype="tool_result", metadata=json.dumps({"call_id": "c2"})),
        ])
        try:
            disagreeing = conn.execute("""
                SELECT COUNT(*) FROM tool_invocations
                WHERE (invocation_kind='model_requested')
                  <> (requested_event_id IS NOT NULL)
            """).fetchone()[0]
            assert disagreeing == 0
        finally:
            conn.close()


def test_harness_name_carries_no_surface():
    """`harness_name` names the program; `surface_kind` names the surface.

    The constants held `claude-code-cli`, `codex-cli`, and `cursor-ide`, so a
    Desktop or SDK Session was stored as a CLI one by a value contradicting the
    decoded column beside it.
    """
    from codess.store import SOURCE_PROFILES

    for key, profile in SOURCE_PROFILES.items():
        harness = profile["harness_name"]
        for surface in ("cli", "ide", "desktop", "api", "tui"):
            assert not harness.endswith(f"-{surface}"), f"{key}: {harness}"


class TestParentEventResolution:
    """A vendor names the parent by its own record id; the column holds the Event id."""

    def events(self, *pairs):
        out = []
        for event_id, record_uuid, parent_uuid in pairs:
            metadata = {}
            if record_uuid:
                metadata["record_uuid"] = record_uuid
            if parent_uuid:
                metadata["parent_uuid"] = parent_uuid
            out.append({
                "event_id": event_id,
                "metadata": json.dumps(metadata) if metadata else None,
            })
        return out

    def test_resolves(self):
        from codess.store import _resolve_parent_events

        events = self.events(("1", "aaa", None), ("2", "bbb", "aaa"))
        _resolve_parent_events(events)
        assert events[0].get("parent_event_id") is None
        assert events[1]["parent_event_id"] == "1"

    def test_parent_decoded_later(self):
        """A parent may be decoded after its child, which is why resolution needs
        the whole Session rather than a streaming pass."""
        from codess.store import _resolve_parent_events

        events = self.events(("1", "aaa", "bbb"), ("2", "bbb", None))
        _resolve_parent_events(events)
        assert events[0]["parent_event_id"] == "2"

    def test_unresolvable_stays_null(self):
        """A parent naming a record that produced no Event is left null rather than
        asserting a link to an Event that does not exist."""
        from codess.store import _resolve_parent_events

        events = self.events(("1", "aaa", "missing"))
        _resolve_parent_events(events)
        assert events[0].get("parent_event_id") is None

    def test_existing_value_wins(self):
        from codess.store import _resolve_parent_events

        events = self.events(("1", "aaa", None), ("2", "bbb", "aaa"))
        events[1]["parent_event_id"] = "stated"
        _resolve_parent_events(events)
        assert events[1]["parent_event_id"] == "stated"


class TestToolNamespace:
    """MCP tool names state their server; built-in names have none."""

    def test_server(self):
        from codess.store import _tool_namespace

        assert _tool_namespace("mcp__visualize__show_widget") == "visualize"
        assert _tool_namespace("mcp__codex_apps__github_search") == "codex_apps"

    def test_builtin_has_none(self):
        """A built-in tool belongs to the harness, not a server; inventing a
        namespace would make the column answer a question nobody asked."""
        from codess.store import _tool_namespace

        assert _tool_namespace("Bash") is None
        assert _tool_namespace("read_file_v2") is None

    def test_cursor_underscore_form(self):
        from codess.store import _tool_namespace

        assert _tool_namespace("mcp_Notion_search") == "Notion"

    def test_cursor_hyphen_form_needs_a_declared_server(self):
        """Single hyphens run through both halves of the name and no field states
        the server, so the boundary comes from a declared list. Splitting on the
        first hyphen would record `cursor`."""
        from codess.store import _tool_namespace

        assert _tool_namespace(
            "mcp-cursor-app-control-open_resource"
        ) == "cursor-app-control"

    def test_undeclared_hyphen_server_is_unresolved(self):
        from codess.store import _tool_namespace

        assert _tool_namespace("mcp-unknown-server-tool") is None

    def test_malformed(self):
        from codess.store import _tool_namespace

        assert _tool_namespace("mcp__only") is None
        assert _tool_namespace("mcp____tool") is None
        assert _tool_namespace("mcp--") is None
        assert _tool_namespace(None) is None
        assert _tool_namespace(42) is None


class TestBoundedOutputJson:
    """Structured tool output is retained, but not past the text column's bound."""

    def test_structure(self):
        from codess.store import _bounded_output_json

        assert json.loads(_bounded_output_json({"stdout": "x", "stderr": ""})) == {
            "stdout": "x", "stderr": "",
        }

    def test_absent(self):
        from codess.store import _bounded_output_json

        assert _bounded_output_json(None) is None

    def test_oversized_is_omitted(self):
        """Truncating JSON yields a value that is no longer JSON, so an oversized
        result is omitted rather than cut; the text projection still records it."""
        from codess.store import MAX_OUTPUT_JSON_BYTES, _bounded_output_json

        assert _bounded_output_json({"x": "y" * (MAX_OUTPUT_JSON_BYTES + 10)}) is None
