"""Executable CoSchema package, mapping, compatibility, and v2 semantics."""

from __future__ import annotations

import copy
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from codess.processing_contract import DECODER_VERSION, VALIDATOR_VERSION
from codess.schema_contract import (
    APPLICATION_ID,
    FORMAT_ID,
    FORMAT_VERSION,
    MANIFEST_PATH,
    SchemaContractError,
    UnsupportedStoreError,
    load_contract,
    load_mapping,
    require_store,
    validate_database_contract,
    validate_mapped_event,
    validate_mapping,
    verify_package,
)
from codess.store import connect, init_db, replace_session_events

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "schema" / "coschema" / "fixtures"
sys.path.insert(0, str(ROOT / "tools"))
from coschema_gate import compare, required


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
        assert meta["decoder_version"] == DECODER_VERSION
        assert meta["validator_version"] == VALIDATOR_VERSION
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
        conn.execute("ALTER TABLE events ADD COLUMN undocumented_value TEXT")
        assert "events: uncontracted column undocumented_value" in validate_database_contract(conn)
    finally:
        conn.close()


def test_json_contract_is_enforced_by_sqlite(tmp_path):
    path = tmp_path / "store.db"
    init_db(path)
    conn = connect(path)
    replace_session_events(
        conn, {"id": "s1", "source": "Cursor"}, [], session_id="s1"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO events(session_id,event_id,tool_input) VALUES ('s1','e1','not-json')"
        )
    conn.close()


def test_event_field_diagnostics_materialize_scope_and_severity(tmp_path):
    path = tmp_path / "store.db"
    init_db(path)
    conn = connect(path)
    replace_session_events(
        conn,
        {"id": "s1", "source": "Cursor"},
        [{
            "session_id": "s1", "event_id": "e1",
            "event_type": "user_message", "role": "user",
            "field_diagnostics": [{
                "diagnostic_level": "field", "level": "info",
                "reason_code": "field_absent",
                "source_field": "modelInfo",
            }],
        }],
        session_id="s1",
    )
    row = conn.execute(
        "SELECT level,severity,reason_code,source_field "
        "FROM mapping_diagnostics"
    ).fetchone()
    assert tuple(row) == ("field", "info", "field_absent", "modelInfo")
    conn.close()


def test_mapping_event_verifier_checks_rules_provenance_and_json():
    valid = {
        "source_record_type": "response_item",
        "source_record_subtype": "function_call",
        "source_record_locator": "2",
        "mapping_rule": "codex.tool-call",
        "mapping_trace": json.dumps({"applied_rules": ["codex.tool-call"]}),
        "tool_input": '{"command":"pwd"}',
    }
    assert validate_mapped_event("codex", valid) == []
    invalid = {**valid, "mapping_rule": "codex.missing", "tool_input": "{'x': 1}"}
    assert validate_mapped_event("codex", invalid) == [
        "undeclared mapping rule codex.missing",
        "tool_input is not valid JSON",
    ]


def test_store_from_a_superseded_format_is_refused_for_read_and_write(tmp_path):
    """Only the current format is accepted; older stores are rebuilt, not read."""
    path = tmp_path / "superseded.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY)")
    conn.commit()
    for write in (False, True):
        with pytest.raises(UnsupportedStoreError):
            require_store(conn, write=write)
    conn.close()
    with pytest.raises(UnsupportedStoreError):
        init_db(path)


def test_only_the_current_format_is_readable():
    from codess.schema_contract import (
        FORMAT_VERSION,
        SUPPORTED_READ_FORMATS,
        SUPPORTED_WRITE_FORMATS,
    )

    assert SUPPORTED_READ_FORMATS == SUPPORTED_WRITE_FORMATS == {FORMAT_VERSION}


def test_writer_refuses_store_from_another_released_package(tmp_path):
    path = tmp_path / "store.db"
    init_db(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE store_meta SET value=? WHERE key='package_digest'", ("0" * 64,)
    )
    conn.commit()
    assert require_store(conn, write=False) == FORMAT_VERSION
    with pytest.raises(UnsupportedStoreError, match="rebuild"):
        require_store(conn, write=True)
    conn.close()


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


def test_cursor_prompt_model_selection_configures_following_model_turn(tmp_path):
    path = tmp_path / "store.db"
    init_db(path)
    conn = connect(path)
    session = {"id": "cursor-1", "source": "Cursor", "type": "Code"}
    replace_session_events(conn, session, [
        {
            "session_id": "cursor-1", "event_id": "prompt",
            "event_type": "user_message", "subtype": "prompt", "role": "user",
            "content": "hello",
            "metadata": json.dumps({"model_selection": "composer-2.5", "model": "composer-2.5"}),
        },
        {
            "session_id": "cursor-1", "event_id": "response",
            "event_type": "assistant_message", "subtype": "response",
            "role": "assistant", "content": "hi",
        },
    ], session_id="cursor-1")
    row = conn.execute(
        """
        SELECT c.model_name_exact
        FROM model_turns t JOIN model_configurations c ON c.id=t.model_config_id
        """
    ).fetchone()
    assert row[0] == "composer-2.5"
    replace_session_events(conn, session, [
        {
            "session_id": "cursor-1", "event_id": "prompt",
            "event_type": "user_message", "subtype": "prompt", "role": "user",
            "content": "hello", "metadata": json.dumps({"model": "composer-2.5"}),
        },
        {
            "session_id": "cursor-1", "event_id": "response",
            "event_type": "assistant_message", "subtype": "response",
            "role": "assistant", "content": "hi",
        },
    ], session_id="cursor-1")
    assert conn.execute("SELECT COUNT(*) FROM model_configurations").fetchone()[0] == 1
    conn.close()


def test_model_event_settings_override_session_or_prompt_defaults(tmp_path):
    path = tmp_path / "store.db"
    init_db(path)
    conn = connect(path)
    metadata = json.dumps({
        "model": "gpt-test", "model_provider": "openai",
        "reasoning_effort": "high", "service_tier": "priority",
        "mode": "default", "configuration_provenance": {
            "reasoning_effort": {
                "source_record_type": "turn_context",
                "source_record_locator": "2",
                "source_field": "payload.effort",
            },
        },
    })
    replace_session_events(conn, {"id": "codex-1", "source": "Codex"}, [
        {"session_id": "codex-1", "event_id": "prompt",
         "event_type": "user_message", "subtype": "prompt", "role": "user",
         "content": "hello"},
        {"session_id": "codex-1", "event_id": "response",
         "event_type": "assistant_message", "subtype": "response",
         "role": "assistant", "content": "hi", "metadata": metadata},
    ], session_id="codex-1")
    row = conn.execute(
        """
        SELECT c.model_name_exact,c.provider,c.reasoning_effort,
               c.service_tier,c.mode,c.source_config
        FROM model_turns t JOIN model_configurations c ON c.id=t.model_config_id
        """
    ).fetchone()
    assert tuple(row[:5]) == (
        "gpt-test", "openai", "high", "priority", "default"
    )
    assert json.loads(row["source_config"])["configuration_provenance"]
    conn.close()


def test_model_configuration_null_safe_identity_is_enforced(tmp_path):
    path = tmp_path / "store.db"
    init_db(path)
    conn = connect(path)
    conn.execute(
        "INSERT INTO model_configurations(model_name_exact) VALUES ('model-x')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO model_configurations(model_name_exact) VALUES ('model-x')"
        )
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
    assert conn.execute("SELECT COUNT(*) FROM source_records").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM content_objects").fetchone()[0] >= 3
    assert conn.execute("SELECT COUNT(*) FROM event_content").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM source_record_content").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM tool_result_content").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM artifact_content").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE global_id LIKE 'codess:session:sha256:%'"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM events WHERE global_id LIKE 'codess:event:sha256:%'"
    ).fetchone()[0] == 3
    call = conn.execute("SELECT source_status, normalized_status FROM tool_invocations").fetchone()
    assert tuple(call) == ("completed", "succeeded")
    replace_session_events(conn, session, events, session_id="s1")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM event_artifacts").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO artifacts(project_id, artifact_kind, relative_path)
            SELECT project_id, artifact_kind, relative_path FROM artifacts LIMIT 1
            """
        )
    conn.close()


def test_artifact_outside_project_uses_uri_and_explicit_scope(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "shared" / "README.md"
    path = tmp_path / "store.db"
    init_db(path)
    conn = connect(path)
    replace_session_events(
        conn,
        {
            "id": "s1", "source": "Claude", "type": "Code",
            "project_path": str(project),
        },
        [{
            "session_id": "s1", "event_id": "read", "event_type": "tool_call",
            "role": "assistant", "tool_name": "Read",
            "tool_input": json.dumps({"path": "../shared/README.md"}),
            "metadata": '{"call_id":"c1"}',
        }],
        session_id="s1",
    )
    conn.commit()
    artifact = conn.execute(
        "SELECT relative_path, observed_absolute_path, uri, metadata FROM artifacts"
    ).fetchone()
    assert artifact["relative_path"] is None
    assert artifact["observed_absolute_path"] == str(outside)
    assert artifact["uri"] == outside.as_uri()
    assert json.loads(artifact["metadata"]) == {
        "path_scope": "external", "source_path": "../shared/README.md"
    }
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


def test_claude_source_role_hazard_keeps_denial_as_tool_outcome(tmp_path):
    fixture = load_fixture("hazard", "claude-error-tool-results.json")
    path = tmp_path / "store.db"
    init_db(path)
    conn = connect(path)
    replace_session_events(
        conn, fixture["session"], fixture["events"],
        session_id=fixture["session"]["id"],
    )
    conn.commit()
    semantic = conn.execute(
        "SELECT event_kind, actor_kind, content_role, normalized_status "
        "FROM events WHERE event_id='denied'"
    ).fetchone()
    expected = fixture["expected_result"]
    assert tuple(semantic) == tuple(
        expected[key]
        for key in ("event_kind", "actor_kind", "content_role", "normalized_status")
    )
    result = conn.execute(
        "SELECT is_error, normalized_status FROM tool_results"
    ).fetchone()
    assert tuple(result) == (expected["is_error"], expected["normalized_status"])
    # The error tool-result in a user envelope is not a human prompt, so it opens
    # no human interaction (any interaction present is autonomous model activity).
    assert conn.execute(
        "SELECT COUNT(*) FROM interactions WHERE initiation_kind='human'"
    ).fetchone()[0] == 0
    conn.close()


def test_failed_codex_tool_call_remains_an_invocation(tmp_path):
    path = tmp_path / "store.db"
    init_db(path)
    conn = connect(path)
    replace_session_events(
        conn,
        {"id": "s1", "source": "Codex", "type": "Code"},
        [{
            "session_id": "s1", "event_id": "call", "event_type": "tool_call",
            "subtype": "tool_failure", "role": "assistant", "tool_name": "exec",
            "metadata": '{"call_id":"c1","status":"failed"}',
        }],
        session_id="s1",
    )
    conn.commit()
    semantic = conn.execute(
        "SELECT event_kind, actor_kind, content_role, normalized_status FROM events"
    ).fetchone()
    assert tuple(semantic) == ("tool.call", "model", "tool_request", "failed")
    assert conn.execute("SELECT COUNT(*) FROM tool_invocations").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM tool_results").fetchone()[0] == 0
    conn.close()


def test_cursor_turns_are_inferred_per_prompt_interaction(tmp_path):
    path = tmp_path / "store.db"
    init_db(path)
    conn = connect(path)
    events = [
        {"session_id": "c1", "event_id": "pre", "event_type": "assistant_message", "role": "assistant"},
        {"session_id": "c1", "event_id": "p1", "event_type": "user_message", "subtype": "prompt", "role": "user"},
        {"session_id": "c1", "event_id": "a1", "event_type": "assistant_message", "role": "assistant"},
        {"session_id": "c1", "event_id": "a2", "event_type": "assistant_message", "role": "assistant"},
        {"session_id": "c1", "event_id": "p2", "event_type": "user_message", "subtype": "prompt", "role": "user"},
        {"session_id": "c1", "event_id": "a3", "event_type": "assistant_message", "role": "assistant"},
    ]
    replace_session_events(
        conn, {"id": "c1", "source": "Cursor", "type": "IDE"}, events,
        session_id="c1",
    )
    conn.commit()
    turns = conn.execute(
        "SELECT interaction_id, source_turn_id, boundary_source FROM model_turns ORDER BY sequence_no"
    ).fetchall()
    # `pre` precedes the first prompt: it opens an autonomous interaction rather
    # than being dropped, then p1/p2 open human interactions.
    assert [tuple(row) for row in turns] == [
        ("c1:interaction:1", None, "inferred"),
        ("c1:interaction:2", None, "inferred"),
        ("c1:interaction:3", None, "inferred"),
    ]
    kinds = dict(
        conn.execute("SELECT id, initiation_kind FROM interactions")
    )
    assert kinds["c1:interaction:1"] == "autonomous"
    assert kinds["c1:interaction:2"] == "human"
    assert kinds["c1:interaction:3"] == "human"
    assignments = dict(
        conn.execute("SELECT event_id, model_turn_id FROM events")
    )
    assert assignments["pre"] is not None  # no longer orphaned
    assert assignments["a1"] == assignments["a2"]
    assert assignments["a3"] != assignments["a2"]
    conn.close()


def test_codex_vendor_turn_id_groups_model_events(tmp_path):
    path = tmp_path / "store.db"
    init_db(path)
    conn = connect(path)
    metadata = json.dumps({"source_turn_id": "turn-42", "model": "gpt-test"})
    events = [
        {"session_id": "c1", "event_id": "1", "event_type": "user_message",
         "subtype": "prompt", "role": "user", "content": "go"},
        {"session_id": "c1", "event_id": "2", "event_type": "assistant_message",
         "subtype": "response", "role": "assistant", "metadata": metadata},
        {"session_id": "c1", "event_id": "3", "event_type": "assistant_message",
         "subtype": "response", "role": "assistant", "metadata": metadata},
    ]
    replace_session_events(
        conn, {"id": "c1", "source": "Codex"}, events, session_id="c1"
    )
    turns = conn.execute(
        "SELECT source_turn_id,boundary_source FROM model_turns"
    ).fetchall()
    assert [tuple(row) for row in turns] == [("turn-42", "vendor")]
    conn.close()


def test_cursor_subagent_header_maps_to_common_relation(tmp_path):
    path = tmp_path / "store.db"
    init_db(path)
    conn = connect(path)
    replace_session_events(
        conn,
        {"id": "c1", "source": "Cursor", "metadata": '{"is_subagent":true}'},
        [],
        session_id="c1",
    )
    assert conn.execute(
        "SELECT session_relation_kind FROM sessions WHERE id='c1'"
    ).fetchone()[0] == "subagent"
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


# --- contract digest versus package digest -----------------------------------
#
# The write gate compares the executable contract, not the whole released set.
# Ten of the manifest's sixteen entries are validation fixtures, and editing
# one used to make every published store unwritable although its layout,
# decoder, and data were unchanged (13.4.4).

def rewrite_manifest_hash(role: str, path: Path) -> None:
    """Point the manifest at a file's current bytes, as a release would."""
    import hashlib

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["files"][role]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def clear_package_caches() -> None:
    import codess.schema_contract as module

    module.load_manifest.cache_clear()
    module.load_contract.cache_clear()
    module.contract_digest.cache_clear()
    module.verify_package.cache_clear()


@pytest.fixture
def restore_package():
    """Restore every released file this test may edit, whatever happens."""
    import codess.schema_contract as module

    originals = {
        path: path.read_text(encoding="utf-8")
        for path in (
            MANIFEST_PATH,
            module.PACKAGE_ROOT / "fixtures" / "minimal" / "session.json",
            module.DDL_PATH,
        )
    }
    clear_package_caches()
    try:
        yield originals
    finally:
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8")
        clear_package_caches()


def test_the_contract_digest_covers_only_the_runtime_files():
    """Six files determine what a store is; nothing else can change that."""
    from codess.schema_contract import CONTRACT_ROLES, load_manifest

    assert {
        "sqlite_schema", "contract", "mapping_contract",
        "mapping_claude", "mapping_codex", "mapping_cursor",
    } == CONTRACT_ROLES
    assert set(load_manifest()["files"]) >= CONTRACT_ROLES


def test_the_two_digests_are_distinct():
    """They answer different questions, so they must not be interchangeable."""
    from codess.schema_contract import contract_digest, verify_package

    assert contract_digest() != verify_package()
    assert len(contract_digest()) == 64


def test_a_new_store_records_the_contract_digest(tmp_path):
    from codess.schema_contract import contract_digest, store_metadata

    path = tmp_path / "store.db"
    init_db(path)
    conn = sqlite3.connect(path)
    try:
        assert store_metadata(conn)["package_digest"] == contract_digest()
    finally:
        conn.close()


def test_editing_a_fixture_does_not_make_a_store_unwritable(
    tmp_path, restore_package,
):
    """The defect W03 removed: a test document must not gate a store write."""
    import codess.schema_contract as module

    path = tmp_path / "store.db"
    init_db(path)
    fixture = module.PACKAGE_ROOT / "fixtures" / "minimal" / "session.json"
    fixture.write_text(
        restore_package[fixture].rstrip("\n") + "\n\n", encoding="utf-8",
    )
    rewrite_manifest_hash("fixture_minimal_session", fixture)
    clear_package_caches()

    connect(path).close()


def test_a_fixture_edit_with_a_stale_manifest_does_not_break_the_loaders(
    tmp_path, restore_package,
):
    """The sharper failure: a half-finished edit disabled the program.

    `load_ddl` and `load_contract` verified the whole manifest, so a fixture
    whose recorded hash had not yet been updated broke every path that reads
    the DDL -- including creating a store, which has nothing to do with it.
    """
    import codess.schema_contract as module

    fixture = module.PACKAGE_ROOT / "fixtures" / "minimal" / "session.json"
    fixture.write_text(
        restore_package[fixture].rstrip("\n") + "\n\n", encoding="utf-8",
    )
    clear_package_caches()

    assert module.load_ddl()
    init_db(tmp_path / "store.db")


def test_a_fixture_edit_is_still_reported_by_package_verification(
    restore_package,
):
    """Nothing is weakened: the fixtures are still verified, elsewhere."""
    import codess.schema_contract as module

    fixture = module.PACKAGE_ROOT / "fixtures" / "minimal" / "session.json"
    fixture.write_text(
        restore_package[fixture].rstrip("\n") + "\n\n", encoding="utf-8",
    )
    clear_package_caches()

    with pytest.raises(SchemaContractError, match="released CoSchema package"):
        module.verify_package()


def test_changing_the_ddl_still_refuses_the_write(tmp_path, restore_package):
    """The control: a real contract change must still stop a store write."""
    import codess.schema_contract as module

    path = tmp_path / "store.db"
    init_db(path)
    module.DDL_PATH.write_text(
        restore_package[module.DDL_PATH] + "\n-- semantic change\n",
        encoding="utf-8",
    )
    rewrite_manifest_hash("sqlite_schema", module.DDL_PATH)
    clear_package_caches()

    with pytest.raises(UnsupportedStoreError, match="rebuild"):
        connect(path)


def test_changing_a_mapping_profile_still_refuses_the_write(
    tmp_path, restore_package,
):
    """Mapping profiles are runtime files, so they gate writes as the DDL does."""
    import codess.schema_contract as module

    path = tmp_path / "store.db"
    init_db(path)
    profile = module.MAPPINGS_ROOT / "claude.json"
    original = profile.read_text(encoding="utf-8")
    try:
        profile.write_text(original.rstrip("\n") + "\n\n", encoding="utf-8")
        rewrite_manifest_hash("mapping_claude", profile)
        clear_package_caches()
        with pytest.raises(UnsupportedStoreError, match="rebuild"):
            connect(path)
    finally:
        profile.write_text(original, encoding="utf-8")
        clear_package_caches()


# --- explicit override -------------------------------------------------------
#
# Contract checking runs by default and is skippable by explicit request. Two
# situations use the skip: a test exercising a deliberately mismatched store,
# and a recovery where the released files that produced a store are no longer
# reconstructible, so refusing the write protects nothing and leaves retained
# evidence unreachable.

@pytest.fixture
def contract_override(monkeypatch):
    """Enable the override for one test, clearing the digest caches around it."""
    from codess.schema_contract import CONTRACT_OVERRIDE_ENV

    clear_package_caches()
    monkeypatch.setenv(CONTRACT_OVERRIDE_ENV, "1")
    yield
    monkeypatch.delenv(CONTRACT_OVERRIDE_ENV, raising=False)
    clear_package_caches()


def test_the_override_is_off_unless_asked_for(monkeypatch):
    from codess.schema_contract import CONTRACT_OVERRIDE_ENV, contract_check_disabled

    monkeypatch.delenv(CONTRACT_OVERRIDE_ENV, raising=False)
    assert contract_check_disabled() is False


@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), ("YES", True), (" 1 ", True),
    ("0", False), ("false", False), ("", False), ("maybe", False),
])
def test_the_override_reads_the_usual_truthy_spellings(
    monkeypatch, value, expected,
):
    from codess.schema_contract import CONTRACT_OVERRIDE_ENV, contract_check_disabled

    monkeypatch.setenv(CONTRACT_OVERRIDE_ENV, value)
    assert contract_check_disabled() is expected


def test_a_refused_write_names_the_override(tmp_path):
    """The refusal names the flag, so the escape is discoverable."""
    from codess.schema_contract import CONTRACT_OVERRIDE_ENV

    path = tmp_path / "store.db"
    init_db(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE store_meta SET value=? WHERE key='package_digest'", ("0" * 64,)
    )
    conn.commit()
    with pytest.raises(UnsupportedStoreError, match=CONTRACT_OVERRIDE_ENV):
        require_store(conn, write=True)
    conn.close()


def test_the_override_allows_writing_a_mismatched_store(
    tmp_path, contract_override,
):
    """Recovery: the contract that produced this store is gone."""
    path = tmp_path / "store.db"
    init_db(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE store_meta SET value=? WHERE key='package_digest'", ("0" * 64,)
    )
    conn.commit()
    try:
        assert require_store(conn, write=True) == FORMAT_VERSION
    finally:
        conn.close()


def test_the_override_allows_an_unverifiable_contract(
    restore_package, contract_override,
):
    """A partly restored working tree still permits work."""
    import codess.schema_contract as module

    module.DDL_PATH.write_text(
        restore_package[module.DDL_PATH] + "\n-- unrecorded\n", encoding="utf-8",
    )
    clear_package_caches()
    assert len(module.contract_digest()) == 64


def test_the_override_is_reported_when_it_is_used(
    tmp_path, contract_override, caplog,
):
    """Each bypass logs a warning."""
    import logging

    path = tmp_path / "store.db"
    init_db(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE store_meta SET value=? WHERE key='package_digest'", ("0" * 64,)
    )
    conn.commit()
    try:
        with caplog.at_level(logging.WARNING, logger="codess.schema_contract"):
            require_store(conn, write=True)
    finally:
        conn.close()
    assert any("CODESS_NO_CONTRACT_CHECK" in record.message for record in caplog.records)


def test_a_store_created_under_the_override_records_that(
    tmp_path, contract_override,
):
    """The store records that its digest was not verified."""
    from codess.schema_contract import store_metadata

    path = tmp_path / "store.db"
    init_db(path)
    conn = sqlite3.connect(path)
    try:
        assert store_metadata(conn).get("contract_override") == "1"
    finally:
        conn.close()


def test_an_ordinary_store_records_no_override(tmp_path):
    from codess.schema_contract import store_metadata

    path = tmp_path / "store.db"
    init_db(path)
    conn = sqlite3.connect(path)
    try:
        assert "contract_override" not in store_metadata(conn)
    finally:
        conn.close()
