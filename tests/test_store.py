"""Store and state edge cases."""

import json
import os
import sqlite3
from pathlib import Path
from typing import ClassVar

import pytest

from codess.fileio import open_readonly
from codess.schema_contract import (
    FORMAT_VERSION,
    column_names,
    store_metadata,
    table_names,
)
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
        assert marker["source_revision"].startswith("digest-fingerprint:")
        assert marker["fingerprint_method"] == "full-digest-fingerprint"
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
            "sqlite-main-wal-digest-fingerprint:"
        )
        assert marker["fingerprint_method"] == (
            "full-digest-fingerprint+wal:full-digest-fingerprint"
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
        monkeypatch.setattr("codess.fileio.SOURCE_READ_MAX", 4)
        marker = ingest_state_marker(source)
        assert marker["source_revision"].startswith(
            "sample-digest-fingerprint:"
        )
        assert marker["fingerprint_method"] == (
            "bounded-sample-digest-fingerprint"
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
        assert "~digest:" in row["source_call_id"]
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
            assert {"id", "session_entity_id", "project_id"} <= columns
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
            assert meta["contract_digest"]
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
        from codess.tool_identity import mcp_namespace

        assert mcp_namespace("mcp__visualize__show_widget") == "visualize"
        assert mcp_namespace("mcp__codex_apps__github_search") == "codex_apps"

    def test_builtin_has_none(self):
        """A built-in tool belongs to the harness, not a server; inventing a
        namespace would make the column answer a question nobody asked."""
        from codess.tool_identity import mcp_namespace

        assert mcp_namespace("Bash") is None
        assert mcp_namespace("read_file_v2") is None

    def test_cursor_underscore_form(self):
        from codess.tool_identity import mcp_namespace

        assert mcp_namespace("mcp_Notion_search") == "Notion"

    def test_cursor_hyphen_form_needs_a_declared_server(self):
        """Single hyphens run through both halves of the name and no field states
        the server, so the boundary comes from a declared list. Splitting on the
        first hyphen would record `cursor`."""
        from codess.tool_identity import mcp_namespace

        assert mcp_namespace(
            "mcp-cursor-app-control-open_resource"
        ) == "cursor-app-control"

    def test_undeclared_hyphen_server_is_unresolved(self):
        from codess.tool_identity import mcp_namespace

        assert mcp_namespace("mcp-unknown-server-tool") is None

    def test_malformed(self):
        from codess.tool_identity import mcp_namespace

        assert mcp_namespace("mcp__only") is None
        assert mcp_namespace("mcp____tool") is None
        assert mcp_namespace("mcp--") is None
        assert mcp_namespace(None) is None
        assert mcp_namespace(42) is None


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


class TestWireFormatChanges:
    """Columns and metadata keys that CoSchema format 5 added or removed.

    Asserted against a store the writer actually produced, not a fixture: the
    defect these guard against is a write path still naming a column the DDL
    no longer declares, which a fixture built from the DDL cannot show.
    """

    def test_store_meta_records_the_contract_digest(self, tmp_path):
        """`package_digest` named the Python distribution, not what it covers.

        The value gates every write, so the name a reader sees in `store_meta`
        has to be the one the code and the documentation use.
        """
        from codess.schema_contract import contract_digest

        db = tmp_path / "meta.db"
        init_db(db)
        conn = connect(db)
        meta = store_metadata(conn)
        conn.close()
        assert meta["contract_digest"] == contract_digest()
        assert "package_digest" not in meta

    def test_removed_time_columns_are_absent(self, tmp_path):
        """Each was measured redundant or unwritten before removal."""
        db = tmp_path / "columns.db"
        init_db(db)
        conn = connect(db)
        try:
            assert "timestamp" not in column_names(conn, "events")
            assert "ingested_at" not in column_names(conn, "sources")
            assert "ingested_at" not in column_names(conn, "sessions")
            assert "ended_at" not in column_names(conn, "tool_invocations")
        finally:
            conn.close()

    def test_retained_time_columns_are_present(self, tmp_path):
        """The surviving times, including the two held for the read path.

        `sessions.started_at`/`ended_at` are derivable from Events but carry
        the indexed `--since`/`--until` predicate, so they stay materialized.
        """
        db = tmp_path / "retained.db"
        init_db(db)
        conn = connect(db)
        try:
            assert "event_at" in column_names(conn, "events")
            assert "event_at_basis" in column_names(conn, "events")
            assert "observed_at" in column_names(conn, "sources")
            assert {"started_at", "ended_at"} <= column_names(conn, "sessions")
            assert "source_started_at" in column_names(conn, "tool_invocations")
            assert "started_at" not in column_names(conn, "tool_invocations")
        finally:
            conn.close()

    def test_digest_columns_do_not_name_the_algorithm(self, tmp_path):
        """`hashing` owns the algorithm, so no column may pin it."""
        db = tmp_path / "digest.db"
        init_db(db)
        conn = connect(db)
        try:
            for table in ("sources", "content_objects", "artifacts"):
                columns = column_names(conn, table)
                assert "content_digest" in columns
                assert "content_sha256" not in columns
            assert "policy_digest" in column_names(conn, "processing_runs")
            assert "policy_sha256" not in column_names(conn, "processing_runs")
        finally:
            conn.close()

    def test_a_written_store_declares_the_current_format(self, tmp_path):
        db = tmp_path / "version.db"
        init_db(db)
        conn = connect(db)
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == FORMAT_VERSION
            assert store_metadata(conn)["format_version"] == str(FORMAT_VERSION)
        finally:
            conn.close()


class TestConnectionEnforcesConstraints:
    """`store.connect` enforces foreign keys; a raw connection does not.

    SQLite defaults `foreign_keys` to off *per connection*, so enforcement is
    a property of how a store was opened rather than of the file. These pin
    the current contract, and are the regression guard: if the write
    path is later unified, the managed behavior below must not change.
    """

    def test_the_managed_connection_enforces_foreign_keys(self, tmp_path):
        db = tmp_path / "managed.db"
        init_db(db)
        conn = connect(db)
        try:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO events(event_entity_id, session_id, event_id) "
                    "VALUES ('x', 'no-such-session', 'e1')"
                )
        finally:
            conn.close()

    def test_a_raw_connection_does_not_and_this_is_why_w56_exists(self, tmp_path):
        """Records the gap rather than asserting it is acceptable.

        No current path writes an FK-bearing table through a raw connection --
        the four raw sites write `store_meta`, which has none, or use
        `backup()`, which copies pages. This test states what would happen if
        one did, so the next writer added to such a connection is a visible
        decision rather than a silent orphan.
        """
        db = tmp_path / "raw.db"
        init_db(db)
        raw = sqlite3.connect(db)
        try:
            assert raw.execute("PRAGMA foreign_keys").fetchone()[0] == 0
            raw.execute(
                "INSERT INTO events(event_entity_id, session_id, event_id) "
                "VALUES ('y', 'no-such-session', 'e2')"
            )
            raw.commit()
            orphans = raw.execute(
                "SELECT COUNT(*) FROM events WHERE session_id='no-such-session'"
            ).fetchone()[0]
            assert orphans == 1
        finally:
            raw.close()

    def test_store_meta_has_no_foreign_keys(self, tmp_path):
        """Why the four raw write sites are safe today.

        Each writes only `store_meta` or uses `backup()`. If `store_meta` ever
        gains a reference, those writes become unchecked and this fails.
        """
        db = tmp_path / "meta.db"
        init_db(db)
        conn = connect(db)
        try:
            assert conn.execute("PRAGMA foreign_key_list(store_meta)").fetchall() == []
        finally:
            conn.close()


class TestFormatSixRemovals:
    """Columns removed in format 6, and why each removal is safe.

    Every one held a single value on every measured row across 90 real stores,
    was written by `store` from a literal, and was read by nothing but the
    fixed-point digest that enumerates all columns by construction. A test per
    group so that reintroducing one is a deliberate change with a name, rather
    than a column that quietly reappears.
    """

    def test_content_is_text_stored_inline_without_declaring_it(self, tmp_path):
        """`media_type`, `charset`, `storage_class` were one literal each."""
        db = tmp_path / "content.db"
        init_db(db)
        conn = connect(db)
        try:
            columns = column_names(conn, "content_objects")
            assert {"media_type", "charset", "storage_class"} & columns == set()
            assert {"content_digest", "inline_content"} <= columns
        finally:
            conn.close()

    def test_the_content_link_tables_key_on_owner_and_relation(self, tmp_path):
        """`sequence_no` distinguished nothing: no owner/relation pair repeated."""
        db = tmp_path / "links.db"
        init_db(db)
        conn = connect(db)
        try:
            for table in (
                "event_content", "source_record_content",
                "tool_result_content", "artifact_content",
            ):
                columns = column_names(conn, table)
                assert "sequence_no" not in columns, table
                assert "integrity_state" not in columns, table
                assert "relation_kind" in columns, table
        finally:
            conn.close()

    def test_sequence_no_is_retained_where_it_varies(self, tmp_path):
        """The removal was per column, not per name.

        `sequence_no` genuinely orders rows in these tables -- measured maxima of
        19,661 for events and 5,564 for model turns -- so dropping the name
        everywhere would have destroyed real ordering.
        """
        db = tmp_path / "seq.db"
        init_db(db)
        conn = connect(db)
        try:
            for table in ("events", "interactions", "model_turns", "tool_results"):
                assert "sequence_no" in column_names(conn, table), table
        finally:
            conn.close()

    def test_a_session_does_not_store_what_its_source_system_implies(self, tmp_path):
        """`product_name` was a pure function of `source_system_id`."""
        db = tmp_path / "sessions.db"
        init_db(db)
        conn = connect(db)
        try:
            columns = column_names(conn, "sessions")
            assert "product_name" not in columns
            assert "session_purpose" not in columns
            assert "source_system_id" in columns
        finally:
            conn.close()

    def test_a_tool_result_does_not_restate_that_a_tool_produced_it(self, tmp_path):
        db = tmp_path / "tools.db"
        init_db(db)
        conn = connect(db)
        try:
            assert "producing_actor_kind" not in column_names(conn, "tool_results")
        finally:
            conn.close()

    def test_artifact_evidence_drops_its_two_constants(self, tmp_path):
        db = tmp_path / "artifacts.db"
        init_db(db)
        conn = connect(db)
        try:
            columns = column_names(conn, "event_artifacts")
            assert {"evidence_source", "confidence"} & columns == set()
        finally:
            conn.close()


class TestDiagnosticGranularity:
    """`level` became `granularity`, because that is what it holds.

    The column carries `source`/`record`/`field` -- which part of the input a
    diagnostic is about -- while `severity` sits beside it holding how much it
    matters. Named `level` it read as an ordering, which made summing its values
    look meaningful when doing so overstates loss.
    """

    def test_the_column_names_the_granularity(self, tmp_path):
        db = tmp_path / "diag.db"
        init_db(db)
        conn = connect(db)
        try:
            columns = column_names(conn, "mapping_diagnostics")
            assert "granularity" in columns
            assert "level" not in columns
            assert "severity" in columns
        finally:
            conn.close()

    def test_field_state_emits_both_keys_under_their_own_names(self):
        """The collision: one dict carried `level` (severity) and
        `diagnostic_level` (granularity), and the store read the second into the
        column named after the first."""
        from codess.field_state import MALFORMED, diagnostic

        row = diagnostic(field="f", state=MALFORMED, source_field="src")
        assert row["severity"] == "warn"
        assert row["granularity"] == "field"
        assert "level" not in row
        assert "diagnostic_level" not in row


class TestOneVendorDescription:
    """Every vendor view derives from `config.VENDORS`.

    Discovery, ingest, publication, refresh, review, and the command layer each
    re-derived a partial view from a bare key -- three separate encodings of the
    same three vendors, plus the key tuple written out at a dozen call sites.
    """

    def test_the_store_profiles_derive_from_the_vendor_table(self):
        from codess.config import VENDORS
        from codess.store import SOURCE_PROFILES

        assert set(SOURCE_PROFILES) == {
            v["adapter_key"] for v in VENDORS.values()
        }
        for description in VENDORS.values():
            profile = SOURCE_PROFILES[description["adapter_key"]]
            assert profile["source_system_id"] == description["source_system_id"]
            assert profile["storage_format"] == description["storage_format"]

    def test_both_key_spellings_resolve_to_one_description(self):
        """`cc` and `Claude` name the same vendor; a caller need not convert."""
        from codess.config import VENDOR_KEYS, vendor

        for key in VENDOR_KEYS:
            assert vendor(key) is vendor(vendor(key)["adapter_key"])

    def test_an_unknown_vendor_is_refused_rather_than_defaulted(self):
        from codess.config import vendor

        with pytest.raises(KeyError):
            vendor("notavendor")

    def test_the_store_filename_comes_from_the_table(self, tmp_path):
        from codess.config import VENDORS, get_store_path

        for key, description in VENDORS.items():
            assert get_store_path(tmp_path, key).name == description["store_db"]
            expected = description["store_db"]
            assert get_store_path(tmp_path, description["adapter_key"]).name == expected

    def test_no_module_writes_the_vendor_key_set_out_longhand(self):
        """The duplication this item removed must not come back."""
        from pathlib import Path

        import codess.config as config_module

        root = Path(config_module.__file__).resolve().parent.parent
        offenders = []
        for path in sorted(root.rglob("*.py")):
            if path.name == "config.py":
                continue
            text = path.read_text(encoding="utf-8")
            if '"codex", "cursor"' in text or "'codex', 'cursor'" in text:
                offenders.append(path.name)
        assert offenders == []


class TestBothOpenersYieldNamedRows:
    """`row_factory` belongs to both connection contracts, not just the write one.

    It was set only by `open_writable`, and `store.connect` re-set it for every
    reader -- so a caller opening the same store through `open_readonly`
    directly got positional tuples while one going through `store.connect` got
    named rows. Removing the redundant assignment exposed that, and the fix was
    to give the read opener the same contract.
    """

    def test_the_read_opener_yields_named_rows(self, tmp_path):
        db = tmp_path / "read.db"
        init_db(db)
        conn = open_readonly(db)
        try:
            row = conn.execute("SELECT key, value FROM store_meta LIMIT 1").fetchone()
            assert row["key"]
        finally:
            conn.close()

    def test_the_write_opener_yields_named_rows(self, tmp_path):
        from codess.fileio import open_writable

        db = tmp_path / "write.db"
        init_db(db)
        conn = open_writable(db)
        try:
            row = conn.execute("SELECT key, value FROM store_meta LIMIT 1").fetchone()
            assert row["key"]
        finally:
            conn.close()

    def test_a_managed_store_yields_named_rows_read_only_and_writable(self, tmp_path):
        """The two routes to one store must agree on how a row is addressed."""
        db = tmp_path / "both.db"
        init_db(db)
        for read_only in (True, False):
            conn = connect(db, read_only=read_only)
            try:
                row = conn.execute(
                    "SELECT key, value FROM store_meta LIMIT 1"
                ).fetchone()
                assert row["key"], f"positional rows with read_only={read_only}"
            finally:
                conn.close()


class TestIsolationModelIsDeferred:
    """The isolation model is stated in `fileio` and this pins it.

    Deferred is SQLite's default, which is exactly why it needs a test: an
    opener that later sets `isolation_level` or issues `BEGIN IMMEDIATE` would
    change the model without any existing assertion noticing.
    """

    def test_no_opener_sets_an_explicit_isolation_level(self, tmp_path):
        from codess.fileio import open_writable

        db = tmp_path / "iso.db"
        init_db(db)
        for opener, kwargs in ((open_writable, {}), (open_readonly, {})):
            conn = opener(db, **kwargs)
            try:
                assert conn.isolation_level == ""
            finally:
                conn.close()

    def test_read_uncommitted_is_never_enabled(self, tmp_path):
        """A reader seeing another connection's uncommitted write would make a
        query result depend on an in-flight ingest."""
        db = tmp_path / "dirty.db"
        init_db(db)
        conn = open_readonly(db)
        try:
            assert conn.execute("PRAGMA read_uncommitted").fetchone()[0] == 0
        finally:
            conn.close()

    def test_the_isolation_model_is_stated_where_the_openers_live(self):
        """A model nobody wrote down cannot be distinguished from an omission."""
        import codess.fileio as fileio_module

        text = Path(fileio_module.__file__).read_text(encoding="utf-8")
        assert "Isolation model" in text
        assert "deferred" in text


class TestStoreErrorsDoNotLeakTheDriver:
    """A caller of a store operation catches a Codess error.

    The store layer had no error type of its own, so the CLI named
    `sqlite3.Error` to report a store it could not open -- the one handler of
    the fourteen that caught a driver exception across a layer boundary. The
    other thirteen are in modules that opened the connection themselves, where
    the exception originates locally.
    """

    def test_opening_a_file_that_is_not_a_database_raises_store_error(self, tmp_path):
        from codess.store import StoreError

        not_a_db = tmp_path / "not.db"
        not_a_db.write_bytes(b"this is not a SQLite file, it is a text file\n" * 64)
        with pytest.raises(StoreError):
            connect(not_a_db, read_only=True)

    def test_store_error_is_not_a_driver_exception(self):
        """It must not be catchable as `sqlite3.Error`, or the boundary is
        nominal rather than real."""
        from codess.store import StoreError

        assert not issubclass(StoreError, sqlite3.Error)

    def test_the_message_names_the_store(self, tmp_path):
        from codess.store import StoreError

        not_a_db = tmp_path / "broken.db"
        not_a_db.write_bytes(b"garbage" * 256)
        with pytest.raises(StoreError, match=str(not_a_db.name)):
            connect(not_a_db, read_only=True)


class TestTheOpenersOwnTheConnectionContracts:
    """A new raw `sqlite3.connect` outside the openers must fail a test.

    The contract properties SQLite applies per connection -- `query_only`,
    `foreign_keys`, `busy_timeout`, `row_factory` -- are guarantees of how a
    file was opened, not of the file. A site that connects directly gets none
    of them, silently, which is what made the read guarantee vary by call site
    before `open_readonly` existed.

    The two permitted exceptions each state their reason at the call site: the
    openers themselves, and `raw_store`'s pure `backup()` target.
    """

    ALLOWED: ClassVar[dict[str, int]] = {"fileio.py": 2, "raw_store.py": 1}

    def test_no_new_raw_connect_appears_outside_the_openers(self):
        import codess.store as store_module

        src = Path(store_module.__file__).resolve().parent.parent
        found: dict[str, int] = {}
        for path in sorted(src.rglob("*.py")):
            count = path.read_text(encoding="utf-8").count("sqlite3.connect(")
            if count:
                found[path.name] = count
        assert found == self.ALLOWED, (
            "a raw sqlite3.connect appeared outside the openers, or one was "
            "removed; each must state at its call site why it does not use "
            f"open_readonly/open_writable. Found: {found}"
        )

    def test_the_permitted_raw_connect_states_its_reason(self):
        """`backup()` copies pages, so row-level constraints never apply."""
        import codess.raw_store as raw_store_module

        text = Path(raw_store_module.__file__).read_text(encoding="utf-8")
        assert "backup()" in text
        assert "open_writable" in text


class TestRecordLevelDiagnostics:
    """A refused record is queryable with its reason and locator.

    `mapping_diagnostics.level` declares `source`, `record`, and `field`, and
    only `field` had ever been written -- 13,432 rows across real stores, none
    at the other two. So the coverage report stated zero record-level loss and
    that zero was unfalsifiable rather than measured: a reader could not tell
    "nothing was refused" from "refusals are not recorded".
    """

    def test_a_refusal_is_written_against_its_source(self, tmp_path):
        from codess.store import record_source_diagnostics

        db = tmp_path / "diag.db"
        init_db(db)
        conn = connect(db)
        try:
            written = record_source_diagnostics(
                conn, None,
                [{
                    "granularity": "record",
                    "reason_code": "unsupported_records",
                    "source_locator": "line:7",
                    "source_file": "/s/session.jsonl",
                    "source_record_type": "user",
                    "detail": "user content is dict, not a list",
                }],
            )
            conn.commit()
            assert written == 1
            row = conn.execute(
                "SELECT granularity, reason_code, source_field, source_value, detail, event_id "
                "FROM mapping_diagnostics"
            ).fetchone()
            assert row["granularity"] == "record"
            assert row["reason_code"] == "unsupported_records"
            assert row["source_field"] == "user"
            assert row["source_value"] == "/s/session.jsonl"
            assert "line:7" in row["detail"]
            assert row["event_id"] is None, (
                "a refused record produced no Event to hang the diagnostic on"
            )
        finally:
            conn.close()

    def test_the_locator_survives_into_the_stored_detail(self, tmp_path):
        """Which record was refused, not merely that one was."""
        from codess.store import record_source_diagnostics

        db = tmp_path / "locator.db"
        init_db(db)
        conn = connect(db)
        try:
            record_source_diagnostics(
                conn, None,
                [{"reason_code": "malformed_records", "source_locator": "line:42"}],
            )
            conn.commit()
            detail = conn.execute(
                "SELECT detail FROM mapping_diagnostics"
            ).fetchone()[0]
            assert "line:42" in detail
        finally:
            conn.close()

    def test_a_source_level_refusal_carries_no_session(self, tmp_path):
        """A whole Source skipped precedes any Session."""
        from codess.store import record_source_diagnostics

        db = tmp_path / "source.db"
        init_db(db)
        conn = connect(db)
        try:
            record_source_diagnostics(
                conn, None,
                [{"granularity": "source", "reason_code": "failed_sources",
                  "source_file": "/s/broken.jsonl"}],
            )
            conn.commit()
            row = conn.execute(
                "SELECT granularity, session_id FROM mapping_diagnostics"
            ).fetchone()
            assert (row["granularity"], row["session_id"]) == ("source", None)
        finally:
            conn.close()

    def test_an_adapter_refusal_reaches_the_store(self, tmp_path):
        """End to end: decode refuses, and the store can be asked about it."""
        import json as _json

        from codess.adapters.cc import process_file
        from codess.ingest_pipeline import commit_source_replacement

        source = tmp_path / "session.jsonl"
        source.write_text(_json.dumps({
            "type": "user", "uuid": "u1", "sessionId": "s1",
            "message": {"role": "user", "content": {"unexpected": True}},
        }) + "\n", encoding="utf-8")

        opts = {"redact": False, "diagnostics": {}, "record_diagnostics": []}
        assert list(process_file(source, "s1", opts)) == []
        assert opts["diagnostics"]["unsupported_records"] == 1

        db = tmp_path / "end-to-end.db"
        init_db(db)
        commit_source_replacement(
            db,
            session={"id": "s1", "source": "Claude", "type": "Code",
                     "project_path": str(tmp_path)},
            events=[{"session_id": "s1", "event_id": "e0",
                     "event_type": "user_message", "subtype": "prompt",
                     "role": "user", "content": "x", "source_file": str(source)}],
            session_id="s1",
            record_diagnostics=opts["record_diagnostics"],
        )
        conn = connect(db, read_only=True)
        try:
            levels = dict(
                conn.execute("SELECT granularity, COUNT(*) FROM mapping_diagnostics GROUP BY 1")
            )
            assert levels.get("record") == 1
        finally:
            conn.close()

class TestMappingProfileConformance:
    """A stored `mapping_rule` is one its released profile declares.

    The property held by construction -- each adapter selects a declared id
    rather than deriving one from the record -- with nothing testing it, so a
    refactor that replaced a dispatch table with a derivation would have been
    silently accepted. Stores written before the current contract show what that
    looks like: they carry ids of the form `vendor.event_type.subtype`, built
    from the record rather than chosen from the profile.
    """

    def _commit(self, tmp_path, rule, source_name):
        from codess.ingest_pipeline import commit_source_replacement

        db = tmp_path / f"conformance-{source_name}.db"
        init_db(db)
        commit_source_replacement(
            db,
            session={"id": "s1", "source": source_name, "type": "Code",
                     "project_path": str(tmp_path)},
            events=[{
                "session_id": "s1", "event_id": "e0",
                "event_type": "user_message", "subtype": "prompt",
                "role": "user", "content": "x",
                "source_record_type": "user", "source_record_locator": "l1",
                "mapping_rule": rule, "mapping_trace": '{"applied_rules": []}',
            }],
            session_id="s1",
        )
        conn = connect(db, read_only=True)
        try:
            return [
                row[0] for row in conn.execute(
                    "SELECT reason_code FROM mapping_diagnostics"
                )
            ]
        finally:
            conn.close()

    @pytest.mark.parametrize(
        ("source_name", "declared"),
        [("Claude", "claude.message"), ("Codex", "codex.message"),
         ("Cursor", "cursor.bubble")],
    )
    def test_a_declared_rule_records_no_nonconformance(
        self, tmp_path, source_name, declared
    ):
        """Every adapter's own declared id passes the shared check."""
        codes = self._commit(tmp_path, declared, source_name)
        assert "mapping_profile_nonconformance" not in codes

    @pytest.mark.parametrize(
        "source_name", ["Claude", "Codex", "Cursor"],
    )
    def test_an_undeclared_rule_is_refused_identically_per_vendor(
        self, tmp_path, source_name
    ):
        """The same non-conformance meets the same disposition in each adapter.

        A vendor that raises where another tolerates would give one conformance
        figure two meanings, which is why the check sits at one vendor-neutral
        boundary rather than in three adapters.
        """
        codes = self._commit(tmp_path, "vendor.user_message.prompt", source_name)
        assert codes.count("mapping_profile_nonconformance") == 1

    def test_an_event_without_a_rule_is_not_reported_twice(self, tmp_path):
        """No rule means no profile to measure against.

        The unmapped-semantics diagnostic already reports it, and reporting the
        same condition under two reason codes would double every count a
        coverage report derives from them.
        """
        from codess.ingest_pipeline import commit_source_replacement

        db = tmp_path / "conformance-none.db"
        init_db(db)
        commit_source_replacement(
            db,
            session={"id": "s1", "source": "Claude", "type": "Code",
                     "project_path": str(tmp_path)},
            events=[{"session_id": "s1", "event_id": "e0",
                     "event_type": "user_message", "subtype": "prompt",
                     "role": "user", "content": "x"}],
            session_id="s1",
        )
        conn = connect(db, read_only=True)
        try:
            codes = [
                row[0] for row in conn.execute(
                    "SELECT reason_code FROM mapping_diagnostics"
                )
            ]
        finally:
            conn.close()
        assert "mapping_profile_nonconformance" not in codes

