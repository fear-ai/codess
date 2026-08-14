"""Typed query, reusable-result, evidence, and configuration contracts."""

import json
import shutil

import pytest

from codess.configuration_audit import audit
from codess.fileio import read_source_revision
from codess.investigation import build_investigation
from codess.orientation_audit import _compare, _sqlite_observations
from codess.query_api import (
    QueryContractError,
    compare_results,
    content_hash,
    execute,
    load_document,
    make_request,
    merge_selection,
    sanitize_free_text_filter,
    save_document,
    selected_project_ids,
    selected_project_snapshots,
    selection_from_result,
)
from codess.raw_store import RawStore
from codess.snapshot import create_snapshot, snapshot_store_paths
from codess.source_verification import verify_event_source
from codess.store import connect, init_db, replace_session_events


def _store(tmp_path):
    project = tmp_path / "project"
    source = tmp_path / "session.jsonl"
    source.write_text('{"message":"source evidence"}\n', encoding="utf-8")
    store = project / ".codess" / "sessions_codex.db"
    init_db(store)
    conn = connect(store)
    replace_session_events(conn, {
        "id": "s1", "source": "Codex", "type": "Code",
        "project_path": str(project), "started_at": 1_000.0, "ended_at": 4_000.0,
    }, [
        {"session_id": "s1", "event_id": "e1", "event_type": "user_message",
         "subtype": "prompt", "role": "user", "content": "alpha request",
         "timestamp": 1_000.0, "source_file": str(source), "source_record_locator": "line:1"},
        {"session_id": "s1", "event_id": "e2", "event_type": "assistant_message",
         "subtype": "response", "role": "assistant", "content": "beta response",
         "timestamp": 4_000.0, "source_file": str(source), "source_record_locator": "line:1"},
    ], session_id="s1")
    conn.commit()
    conn.close()
    return project, store, source


def _scope(project, store):
    return {"conn": connect(store, read_only=True), "path": store, "project_path": project}


def _timed_store(tmp_path, name, session_id, timestamps):
    project = tmp_path / name
    store = project / ".codess" / "sessions_codex.db"
    init_db(store)
    conn = connect(store)
    replace_session_events(
        conn,
        {
            "id": session_id,
            "source": "Codex",
            "type": "Code",
            "project_path": str(project),
        },
        [
            {
                "session_id": session_id,
                "event_id": f"{session_id}-e{index}",
                "event_type": (
                    "user_message" if index == 1 else "assistant_message"
                ),
                "subtype": "prompt" if index == 1 else "response",
                "role": "user" if index == 1 else "assistant",
                "content": f"{session_id} event {index}",
                "timestamp": timestamp,
            }
            for index, timestamp in enumerate(timestamps, 1)
        ],
        session_id=session_id,
    )
    conn.commit()
    conn.close()
    return project, store


def test_typed_overview_events_search_and_saved_selection(tmp_path, monkeypatch):
    project, store, _source = _store(tmp_path)
    opened = _scope(project, store)
    try:
        overview = execute([opened], make_request("overview"))
        assert overview["summary"]["sessions"] == 1
        assert overview["summary"]["events"] == 2
        assert overview["summary"]["active_time_estimates_ms_by_gap_cap_minutes"]["5"] == 3000

        search = execute([opened], make_request("search", filters={"text": "beta"}, limit=10))
        assert [row["event_id"] for row in search["rows"]] == ["e2"]
        selected = selection_from_result(search)
        events = execute([opened], merge_selection(make_request("events"), selected))
        assert [row["event_entity_id"] for row in events["rows"]] == selected["event_ids"]

        saved = tmp_path / "result.json"
        save_document(saved, search)
        assert load_document(saved, "codess.query-result/1")["result_hash"] == search["result_hash"]
        original = saved.read_bytes()
        monkeypatch.setattr(
            "codess.query_api.os.replace",
            lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
        )
        with pytest.raises(OSError, match="replace failed"):
            save_document(saved, overview)
        assert saved.read_bytes() == original
        assert list(saved.parent.glob(f".{saved.name}.*")) == []
    finally:
        opened["conn"].close()


def test_configuration_filters_and_occurrence_provenance_are_queryable(
    tmp_path,
):
    project = tmp_path / "configured-project"
    store = project / ".codess" / "sessions_codex.db"
    init_db(store)
    configuration = {
        "model_provider": "openai",
        "model_line": "gpt",
        "model_generation": "5",
        "model_version": "5.6",
        "model_gradation": "sol",
        "model": "gpt-test-2026-07",
        "model_revision": "2026-07",
        "reasoning_effort": "high",
        "speed_tier": "fast",
        "service_tier": "priority",
        "mode": "default",
    }
    occurrence = {
        **configuration,
        "configuration_provenance": {
            "model": {
                "field": "turn_context.model",
                "value": "gpt-test-2026-07",
            },
            "reasoning_effort": {
                "field": "turn_context.effort",
                "value": "high",
            },
        },
    }
    conn = connect(store)
    replace_session_events(
        conn,
        {
            "id": "configured",
            "source": "Codex",
            "type": "Code",
            "project_path": str(project),
            "metadata": configuration,
        },
        [
            {
                "session_id": "configured",
                "event_id": "prompt",
                "event_type": "user_message",
                "subtype": "prompt",
                "role": "user",
                "content": "investigate",
                "timestamp": 1_000.0,
            },
            {
                "session_id": "configured",
                "event_id": "response",
                "event_type": "assistant_message",
                "subtype": "response",
                "role": "assistant",
                "content": "result",
                "timestamp": 2_000.0,
                "metadata": occurrence,
            },
        ],
        session_id="configured",
    )
    conn.commit()
    conn.close()
    filters = {
        "models": ["gpt-test-2026-07"],
        "model_providers": ["openai"],
        "model_lines": ["gpt"],
        "model_generations": ["5"],
        "model_versions": ["5.6"],
        "model_gradations": ["sol"],
        "model_revisions": ["2026-07"],
        "reasoning_efforts": ["high"],
        "speed_tiers": ["fast"],
        "service_tiers": ["priority"],
        "model_modes": ["default"],
    }
    opened = _scope(project, store)
    try:
        events = execute(
            [opened], make_request("events", filters=filters)
        )
        assert [row["event_id"] for row in events["rows"]] == ["response"]
        row = events["rows"][0]
        assert row["model_provider"] == "openai"
        assert row["reasoning_effort"] == "high"
        assert row["configuration_provenance"]["model"]["field"] == (
            "turn_context.model"
        )
        sessions = execute(
            [opened], make_request("sessions", filters=filters)
        )
        assert [row["id"] for row in sessions["rows"]] == ["configured"]
        overview = execute(
            [opened], make_request("overview", filters=filters)
        )["summary"]
        assert overview["events"] == 1
        assert overview["model_providers_by_event"] == {"openai": 1}
        assert overview["reasoning_efforts_by_event"] == {"high": 1}
        report = audit([opened])
        observed = next(
            item for item in report["configurations"]
            if item["model_name_exact"] == "gpt-test-2026-07"
        )
        assert observed["model_turn_occurrences"] == 1
        assert observed["session_default_occurrences"] == 1
        assert observed["model_turns_with_configuration_provenance"] == 1
        assert observed["occurrence_provenance_state"] == "recorded"
        assert observed["occurrence_examples"][0][
            "configuration_provenance"
        ]["reasoning_effort"]["value"] == "high"
    finally:
        opened["conn"].close()


def test_overview_reports_bounded_daily_exchange_and_actor_activity(tmp_path):
    project = tmp_path / "daily-project"
    store = project / ".codess" / "sessions_codex.db"
    init_db(store)
    conn = connect(store)
    replace_session_events(
        conn,
        {
            "id": "daily-session",
            "source": "Codex",
            "type": "Code",
            "project_path": str(project),
            "session_relation_kind": "subagent",
        },
        [
            {
                "session_id": "daily-session",
                "event_id": "prompt-1",
                "event_type": "user_message",
                "subtype": "prompt",
                "role": "user",
                "content": "first prompt",
                "timestamp": 1_000.0,
            },
            {
                "session_id": "daily-session",
                "event_id": "response-1",
                "event_type": "assistant_message",
                "subtype": "response",
                "role": "assistant",
                "content": "first response",
                "timestamp": 2_000.0,
            },
            {
                "session_id": "daily-session",
                "event_id": "harness-1",
                "event_type": "system_event",
                "subtype": "context_injection",
                "role": "system",
                "content": "harness context",
                "timestamp": 3_000.0,
            },
            {
                "session_id": "daily-session",
                "event_id": "agent-1",
                "event_type": "agent_message",
                "subtype": "delegation",
                "role": "assistant",
                "event_kind": "message.context",
                "actor_kind": "agent",
                "content_role": "context",
                "origin_kind": "agent_generated",
                "content": "agent activity",
                "timestamp": 4_000.0,
            },
            {
                "session_id": "daily-session",
                "event_id": "tool-call-1",
                "event_type": "tool_call",
                "subtype": None,
                "role": "assistant",
                "tool_name": "inspect",
                "tool_input": '{"path":"x"}',
                "timestamp": 4_500.0,
            },
            {
                "session_id": "daily-session",
                "event_id": "tool-result-1",
                "event_type": "user_message",
                "subtype": "tool_result",
                "role": "tool",
                "tool_name": "inspect",
                "content": "ok",
                "tool_output": "ok",
                "timestamp": 4_600.0,
            },
            {
                "session_id": "daily-session",
                "event_id": "prompt-2",
                "event_type": "user_message",
                "subtype": "prompt",
                "role": "user",
                "content": "last prompt",
                "timestamp": 5_000.0,
            },
            {
                "session_id": "daily-session",
                "event_id": "response-2",
                "event_type": "assistant_message",
                "subtype": "response",
                "role": "assistant",
                "content": "next-day response",
                "timestamp": 86_405_000.0,
            },
        ],
        session_id="daily-session",
    )
    conn.commit()
    conn.close()
    opened = _scope(project, store)
    try:
        result = execute(
            [opened], make_request("overview", facet_limit=1)
        )
        summary = result["summary"]
        assert summary["daily_exchange_activity_total_days"] == 2
        assert summary["daily_exchange_activity_truncated"] is True
        assert [row["day"] for row in summary["daily_exchange_activity_utc"]] == [
            "1970-01-02"
        ]

        result = execute(
            [opened], make_request("overview", facet_limit=2)
        )
        first = result["summary"]["daily_exchange_activity_utc"][0]
        assert first["human_prompts"] == 2
        assert first["human_prompt_characters"] == len(
            "first promptlast prompt"
        )
        assert first["model_outputs"] == 1
        assert first["model_output_characters"] == len("first response")
        assert first["human_initiated_interactions"] == 2
        assert first["human_model_interactions"] == 2
        assert first["human_prompt_span_ms"] == 4_000
        assert first["final_model_output_for_last_prompt_at"] == 86_405_000
        assert first["last_prompt_to_final_model_output_ms"] == 86_400_000
        assert first["actor_activity"]["harness"]["events"] == 1
        assert first["actor_activity"]["agent"]["events"] == 1
        assert first["actor_activity"]["tool"]["events"] == 1
        combined = first["combined_harness_model_agent_activity"]
        assert combined["events"] == 4
        assert "events_per_human_prompt" not in combined
        tools = first["tool_activity"]
        assert tools == {
            "calls": 1,
            "results": 1,
            "input_characters": len('{"path":"x"}'),
            "output_characters": len("ok"),
            "call_interactions": 1,
            "result_interactions": 1,
            "calls_by_name": {"inspect": 1},
        }
        assert result["summary"]["tool_activity_by_utc_month"] == {
            "1970-01": {
                "calls": 1,
                "results": 1,
                "input_characters": len('{"path":"x"}'),
                "output_characters": len("ok"),
                "call_interactions": 1,
                "result_interactions": 1,
            }
        }
        subagent = first["subagent_session_activity"]
        assert subagent["events"] == 7
        assert subagent["sessions"] == 1
        assert subagent["actor_events"] == {
            "agent": 1,
            "harness": 1,
            "human": 2,
            "model": 2,
            "tool": 1,
        }
    finally:
        opened["conn"].close()


def test_query_rejects_unknown_or_missing_search_predicates():
    with pytest.raises(QueryContractError, match="unsupported filter"):
        make_request("events", filters={"silently_ignored": "bad"})
    with pytest.raises(QueryContractError, match="requires"):
        make_request("search")
    request = make_request("events")
    request["silently_ignored"] = True
    with pytest.raises(QueryContractError, match="request field"):
        execute([], request)


def test_request_project_scope_cannot_be_replayed_against_other_stores(tmp_path):
    project, store, _source = _store(tmp_path)
    opened = _scope(project, store)
    try:
        with pytest.raises(QueryContractError, match="project_ids"):
            execute([opened], make_request("sessions", project_ids=["wrong-project"]))
    finally:
        opened["conn"].close()


def test_sessions_exposes_vendor_path_and_obsolete_marker(tmp_path):
    project, store, _source = _store(tmp_path)
    obsolete = tmp_path / "old-project"
    conn = connect(store)
    conn.execute(
        "UPDATE sessions SET source_cwd=?,path_obsolete=1 WHERE id='s1'",
        (str(obsolete),),
    )
    conn.commit()
    conn.close()
    opened = _scope(project, store)
    try:
        row = execute([opened], make_request("sessions"))["rows"][0]
        assert row["project_path"] == str(project)
        assert row["source_project_path"] == str(obsolete)
        assert row["path_obsolete"] == 1
        assert "source_cwd" not in row
    finally:
        opened["conn"].close()


def test_search_byte_limit_bounds_tool_fields_not_only_content(tmp_path):
    project, store, _source = _store(tmp_path)
    conn = connect(store)
    conn.execute(
        "UPDATE events SET tool_input=? WHERE event_id='e1'",
        (json.dumps({"payload": "x" * 4096}),),
    )
    conn.commit()
    conn.close()
    opened = _scope(project, store)
    try:
        result = execute([opened], make_request(
            "search", filters={"text": "payload"}, byte_limit=128,
        ))
        assert result["rows"] == []
        assert result["summary"]["truncated"]
        assert result["summary"]["truncation_reasons"] == ["byte_limit"]
    finally:
        opened["conn"].close()


def test_search_and_artifact_filters_treat_like_metacharacters_literally(tmp_path):
    project, store, _source = _store(tmp_path)
    conn = connect(store)
    conn.execute(
        "UPDATE events SET content=?,artifact_path=? WHERE event_id='e1'",
        ("literal 100%_done", "reports/a%b_c.txt"),
    )
    conn.execute(
        "UPDATE events SET content=?,artifact_path=? WHERE event_id='e2'",
        ("literal 100XXdone", "reports/axbzc.txt"),
    )
    conn.commit()
    conn.close()
    opened = _scope(project, store)
    try:
        text = execute(
            [opened],
            make_request("search", filters={"text": "100%_done"}),
        )
        assert [row["event_id"] for row in text["rows"]] == ["e1"]

        artifact = execute(
            [opened],
            make_request("events", filters={"artifact": "a%b_c"}),
        )
        assert [row["event_id"] for row in artifact["rows"]] == ["e1"]
    finally:
        opened["conn"].close()


def test_sanitize_free_text_filter_accepts_ordinary_and_unicode_text():
    assert sanitize_free_text_filter(
        "permission denied", field="text"
    ) == "permission denied"
    assert sanitize_free_text_filter(
        "café münchen 日本語 emoji 🎉", field="text"
    ) == "café münchen 日本語 emoji 🎉"


@pytest.mark.parametrize(
    "value",
    [
        "x" * 513,
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "x' UNION SELECT password FROM users --",
        "bad\x00null",
        "bad\x1bescape",
    ],
)
def test_sanitize_free_text_filter_rejects_by_default(value):
    with pytest.raises(QueryContractError):
        sanitize_free_text_filter(value, field="text")


def test_sanitize_free_text_filter_strip_and_blank_modes():
    assert sanitize_free_text_filter(
        "<b>bold</b> ok text", field="text", mode="strip"
    ) == "bold ok text"
    assert sanitize_free_text_filter(
        "<script>x</script>", field="text", mode="blank"
    ) == ""


def test_sanitize_free_text_filter_rejects_unsupported_mode():
    with pytest.raises(ValueError):
        sanitize_free_text_filter("ok", field="text", mode="drop")


def test_validate_request_rejects_questionable_text_filter():
    # make_request() validates internally, so the rejection surfaces there.
    with pytest.raises(QueryContractError):
        make_request("search", filters={"text": "<script>alert(1)</script>"})


def test_multistore_events_are_globally_ordered_before_limit(tmp_path):
    first_project, first_store = _timed_store(
        tmp_path, "first", "first-session", [1000, 3000]
    )
    second_project, second_store = _timed_store(
        tmp_path, "second", "second-session", [2000, 4000]
    )
    first = _scope(first_project, first_store)
    second = _scope(second_project, second_store)
    try:
        result = execute(
            [second, first],
            make_request("events", limit=3),
        )
        assert [row["event_at"] for row in result["rows"]] == [
            1000, 2000, 3000
        ]
        assert result["summary"]["truncation_reasons"] == [
            "row_limit_reached"
        ]
    finally:
        first["conn"].close()
        second["conn"].close()


def test_relation_orientation_filters_and_exchange_windows(tmp_path):
    project, store, _source = _store(tmp_path)
    conn = connect(store)
    session = conn.execute(
        "SELECT id FROM sessions WHERE id='s1'"
    ).fetchone()[0]
    interaction = conn.execute(
        "SELECT id FROM interactions WHERE session_id=? ORDER BY sequence_no",
        (session,),
    ).fetchone()[0]
    conn.execute(
        """
        UPDATE sessions
        SET parent_session_id='parent-1',session_relation_kind='subagent'
        WHERE id='s1'
        """
    )
    conn.execute(
        "UPDATE interactions SET initiation_kind='autonomous' WHERE id=?",
        (interaction,),
    )
    conn.execute(
        """
        UPDATE events SET tool_name='Read',actor_kind='tool',
                          content_role='result',origin_kind='tool'
        WHERE event_id='e2'
        """
    )
    anchor = conn.execute(
        "SELECT event_entity_id FROM events WHERE event_id='e2'"
    ).fetchone()[0]
    conn.commit()
    conn.close()
    opened = _scope(project, store)
    try:
        sessions = execute([opened], make_request(
            "sessions",
            filters={
                "parent_session_ids": ["parent-1"],
                "session_relation_kinds": ["subagent"],
            },
        ))
        assert sessions["rows"][0]["parent_session_id"] == "parent-1"
        assert sessions["rows"][0]["session_relation_kind"] == "subagent"

        overview = execute([opened], make_request(
            "overview", filters={"initiation_kinds": ["autonomous"]},
        ))
        assert overview["summary"]["sessions_by_relation"] == {"subagent": 1}
        assert overview["summary"]["interactions_by_initiation"] == {
            "autonomous": 1
        }

        tool = execute([opened], make_request(
            "events",
            filters={
                "tool_names": ["Read"],
                "actor_kinds": ["tool"],
                "content_roles": ["result"],
                "origin_kinds": ["tool"],
            },
        ))
        assert [row["event_id"] for row in tool["rows"]] == ["e2"]

        expanded = execute([opened], make_request(
            "events",
            filters={"event_ids": [anchor]},
            expand="interaction",
        ))
        assert [row["event_id"] for row in expanded["rows"]] == ["e1", "e2"]

        window = execute([opened], make_request(
            "events",
            filters={"event_ids": [anchor]},
            sequence_before=1,
        ))
        assert [row["event_id"] for row in window["rows"]] == ["e1", "e2"]
    finally:
        opened["conn"].close()


def test_saved_tool_result_expands_to_complete_four_actor_exchange(tmp_path):
    project, store, _source = _store(tmp_path)
    conn = connect(store)
    replace_session_events(
        conn,
        {
            "id": "s1",
            "source": "Codex",
            "type": "Code",
            "project_path": str(project),
            "started_at": 1_000.0,
            "ended_at": 6_000.0,
        },
        [
            {
                "session_id": "s1",
                "event_id": "core-human",
                "event_type": "user_message",
                "subtype": "prompt",
                "role": "user",
                "content": "inspect the file",
                "timestamp": 1_000.0,
            },
            {
                "session_id": "s1",
                "event_id": "core-harness",
                "event_type": "system_message",
                "subtype": "instruction",
                "role": "system",
                "content": "workspace instructions",
                "timestamp": 2_000.0,
            },
            {
                "session_id": "s1",
                "event_id": "core-model-call",
                "event_type": "tool_call",
                "subtype": "tool_call",
                "role": "assistant",
                "content": "read request",
                "tool_name": "Read",
                "tool_input": {"path": "sample.txt"},
                "metadata": json.dumps({"call_id": "call-1"}),
                "timestamp": 3_000.0,
            },
            {
                "session_id": "s1",
                "event_id": "core-tool-result",
                "event_type": "user_message",
                "subtype": "tool_result",
                "role": "user",
                "content": "sample contents",
                "tool_name": "Read",
                "tool_output": "sample contents",
                "metadata": json.dumps(
                    {"call_id": "call-1", "status": "completed"}
                ),
                "timestamp": 4_000.0,
            },
            {
                "session_id": "s1",
                "event_id": "core-model-response",
                "event_type": "assistant_message",
                "subtype": "response",
                "role": "assistant",
                "content": "the file contains a sample",
                "timestamp": 5_000.0,
            },
        ],
        session_id="s1",
    )
    conn.commit()
    conn.close()
    opened = _scope(project, store)
    try:
        tool_result = execute(
            [opened],
            make_request(
                "events",
                filters={
                    "actor_kinds": ["tool"],
                    "event_kinds": ["tool.result"],
                    "statuses": ["succeeded"],
                },
            ),
        )
        selected = selection_from_result(tool_result)
        derivation = {
            "kind": "stable_id_selection",
            "input_result_hash": tool_result["result_hash"],
            "selected_event_ids": selected["event_ids"],
        }
        exchange = execute(
            [opened],
            make_request(
                "events",
                filters=selected,
                expand="interaction",
            ),
            derivations=[derivation],
        )
        assert [row["actor_kind"] for row in exchange["rows"]] == [
            "human",
            "harness",
            "model",
            "tool",
            "model",
        ]
        assert [row["event_id"] for row in exchange["rows"]] == [
            "core-human",
            "core-harness",
            "core-model-call",
            "core-tool-result",
            "core-model-response",
        ]
        assert all(row["interaction_id"] == "s1:interaction:1" for row in exchange["rows"])
        assert exchange["derivations"] == [derivation]
        assert selection_from_result(exchange)["event_ids"] == sorted(
            row["event_entity_id"] for row in exchange["rows"]
        )
    finally:
        opened["conn"].close()


def test_event_facets_and_exact_repetition_groups_preserve_occurrences(tmp_path):
    project, store, _source = _store(tmp_path)
    conn = connect(store)
    conn.execute(
        """
        UPDATE events
        SET content='same answer',content_len=11,event_kind='message.response',
            actor_kind='model',content_role='response',
            origin_kind='model_generated'
        """
    )
    conn.commit()
    conn.close()
    opened = _scope(project, store)
    try:
        result = execute(
            [opened],
            make_request("events", group_repetitions=True, facet_limit=10),
        )
        assert len(result["rows"]) == 2
        assert result["summary"]["facets_from_returned_rows"]["event_kind"] == [
            {"value": "message.response", "count": 2}
        ]
        groups = result["summary"][
            "repetition_groups_from_complete_returned_content"
        ]
        assert len(groups) == 1
        assert groups[0]["occurrences"] == 2
        assert groups[0]["event_entity_ids"] == sorted(
            row["event_entity_id"] for row in result["rows"]
        )
        investigation = build_investigation(
            result,
            summary="The complete-content repetition group has two occurrences.",
            processor_id="test-reviewer/1",
            event_ids=groups[0]["event_entity_ids"],
        )
        assert {
            citation["event_entity_id"]
            for citation in investigation["citations"]
        } == set(groups[0]["event_entity_ids"])
    finally:
        opened["conn"].close()


def test_saved_result_derivation_and_comparison_detect_changed_rows(tmp_path):
    project, store, _source = _store(tmp_path)
    opened = _scope(project, store)
    try:
        initial = execute(
            [opened],
            make_request("events", filters={"event_kinds": ["message.response"]}),
        )
        selected = selection_from_result(initial)
        derivation = {
            "kind": "stable_id_selection",
            "input_result_hash": initial["result_hash"],
            "selected_event_ids": selected["event_ids"],
        }
        derived = execute(
            [opened],
            merge_selection(make_request("events"), selected),
            derivations=[derivation],
        )
        assert derived["derivations"] == [derivation]
        assert [row["event_entity_id"] for row in derived["rows"]] == (
            selected["event_ids"]
        )

        changed = json.loads(json.dumps(derived))
        changed["rows"][0]["content"] = "updated normalized content"
        comparison = compare_results(derived, changed)
        assert comparison["changed_ids"] == [
            derived["rows"][0]["event_entity_id"]
        ]
        assert comparison["added_ids"] == []
        assert comparison["removed_ids"] == []
        empty = json.loads(json.dumps(derived))
        empty["rows"] = []
        removed = compare_results(derived, empty)
        assert removed["comparable"] is True
        assert removed["removed_ids"] == selected["event_ids"]
        unrelated = execute(
            [opened],
            make_request("search", filters={"text": "beta"}),
        )
        assert compare_results(derived, unrelated)["comparable"] is False
        incompatible = json.loads(json.dumps(derived))
        incompatible["rows"][0].pop("event_entity_id")
        shape_check = compare_results(derived, incompatible)
        assert shape_check["comparable"] is False
        assert any(
            issue.startswith("result row shapes differ")
            for issue in shape_check["comparison_issues"]
        )
    finally:
        opened["conn"].close()


def test_cited_investigation_binds_summary_to_exact_result_rows(tmp_path):
    project, store, _source = _store(tmp_path)
    opened = _scope(project, store)
    try:
        result = execute([opened], make_request("events"))
        event_id = result["rows"][0]["event_entity_id"]
        record = build_investigation(
            result,
            summary="The selected prompt introduced the request.",
            processor_id="test-reviewer/1",
            event_ids=[event_id],
        )
        assert record["input_result_hash"] == result["result_hash"]
        assert record["citations"][0]["event_entity_id"] == event_id
        assert record["citations"][0]["content_sha256"].startswith("sha256:")
        assert record["citations"][0]["row_sha256"] == content_hash(
            result["rows"][0]
        )
        assert record["investigation_hash"].startswith("sha256:")
        with pytest.raises(QueryContractError, match="absent"):
            build_investigation(
                result,
                summary="invalid",
                processor_id="test-reviewer/1",
                event_ids=["missing"],
            )
    finally:
        opened["conn"].close()


def test_historical_union_preserves_observations_and_diff_uses_logical_ids(
    tmp_path,
):
    project, first_store, _source = _store(tmp_path)
    second_store = project / ".codess" / "sessions_codex_second.db"
    shutil.copy2(first_store, second_store)
    for store, snapshot_id in (
        (first_store, "snapshot-one"),
        (second_store, "snapshot-two"),
    ):
        conn = connect(store)
        conn.execute(
            "INSERT OR REPLACE INTO store_meta(key,value) VALUES('snapshot_id',?)",
            (snapshot_id,),
        )
        conn.commit()
        conn.close()
    conn = connect(second_store)
    conn.execute(
        "UPDATE events SET content='changed in snapshot two' WHERE event_id='e2'"
    )
    conn.commit()
    conn.close()
    first = _scope(project, first_store)
    second = _scope(project, second_store)
    first["snapshot_id"] = "snapshot-one"
    second["snapshot_id"] = "snapshot-two"
    try:
        project_ids = selected_project_ids([first, second])
        snapshots = selected_project_snapshots([first, second])
        union = execute(
            [second, first],
            make_request(
                "events",
                project_ids=project_ids,
                project_snapshots=snapshots,
            ),
        )
        assert len(union["rows"]) == 4
        assert union["summary"]["duplicate_event_entity_id_count"] == 2
        assert len({
            row["observation_id"] for row in union["rows"]
        }) == 4

        before = execute(
            [first],
            make_request(
                "events",
                project_ids=selected_project_ids([first]),
                project_snapshots=selected_project_snapshots([first]),
            ),
        )
        after = execute(
            [second],
            make_request(
                "events",
                project_ids=selected_project_ids([second]),
                project_snapshots=selected_project_snapshots([second]),
            ),
        )
        comparison = compare_results(before, after)
        assert comparison["comparable"] is True
        expected_changed = next(
            row["event_entity_id"]
            for row in before["rows"]
            if row["event_id"] == "e2"
        )
        assert comparison["changed_ids"] == [expected_changed]
        assert comparison["provenance_changed"] is True
    finally:
        first["conn"].close()
        second["conn"].close()


def test_exact_evidence_prefers_verified_sealed_object_over_changed_live(tmp_path):
    project, store, source = _store(tmp_path)
    raw = RawStore(tmp_path / "raw")
    record = raw.observe(
        source, source_system_id="openai.codex", storage_format="codex-jsonl",
        mode="capture",
    )
    conn = connect(store)
    conn.execute(
        "UPDATE sources SET availability='captured',content_sha256=?",
        (record["object_id"].removeprefix("sha256:"),),
    )
    event_id = conn.execute("SELECT event_entity_id FROM events WHERE event_id='e1'").fetchone()[0]
    conn.commit()
    conn.close()
    snapshot = create_snapshot(project, [store], [record], raw_store=raw, seal=True)
    source.write_text("changed live evidence\n", encoding="utf-8")
    snapshot_store = snapshot_store_paths(project, snapshot.name)[0]
    opened = _scope(project, snapshot_store)
    try:
        result = verify_event_source(opened, event_id)
        assert result["selected"]["kind"] == "sealed"
        assert result["selected"]["equality"] == "exact"
        assert next(c for c in result["candidates"] if c["kind"] == "live")["equality"] == "mismatch"
    finally:
        opened["conn"].close()


def test_exact_evidence_marks_unsupported_digest_reference_incompatible(tmp_path):
    project, store, source = _store(tmp_path)
    current = read_source_revision(source)
    legacy = ("unsupported-fingerprint:" + ("0" * 32), *current[1:])
    conn = connect(store)
    conn.execute(
        """
        UPDATE sources
        SET source_revision=?,source_mtime=?,source_size=?,
            availability='reference',content_sha256=NULL
        """,
        legacy[:3],
    )
    event_id = conn.execute(
        "SELECT event_entity_id FROM events WHERE event_id='e1'"
    ).fetchone()[0]
    conn.commit()
    conn.close()
    opened = _scope(project, store)
    try:
        result = verify_event_source(opened, event_id)
        live = next(
            item for item in result["candidates"] if item["kind"] == "live"
        )
        assert live["equality"] == "mismatch"
        assert live["revision"].startswith("sha256-fingerprint:")
        assert live["verification_method"] == "full-sha256-fingerprint"
    finally:
        opened["conn"].close()


def test_configuration_audit_keeps_nullable_settings_independent(tmp_path):
    project, store, _source = _store(tmp_path)
    conn = connect(store)
    conn.execute("""
        INSERT INTO model_params(provider,model_name_exact,reasoning_effort,source_params)
        VALUES ('openai','gpt-test','high',?)
    """, (json.dumps({"model": {"field": "payload.model", "value": "gpt-test"}}),))
    conn.commit()
    conn.close()
    opened = _scope(project, store)
    try:
        report = audit([opened])
        config = report["configurations"][0]
        assert config["model_name_exact"] == "gpt-test"
        assert config["speed_tier"] is None
        assert config["provenance_state"] == "recorded"
        assert config["model_turn_occurrences"] == 0
        assert config["occurrence_examples"] == []
    finally:
        opened["conn"].close()


def test_configuration_audit_honors_native_session_scope(tmp_path):
    project = tmp_path / "configuration-scope"
    store = project / ".codess" / "sessions_codex.db"
    init_db(store)
    conn = connect(store)
    for session_id, model in (("selected", "gpt-selected"), ("other", "gpt-other")):
        configuration = {"model_provider": "openai", "model": model}
        replace_session_events(
            conn,
            {
                "id": session_id,
                "source": "Codex",
                "type": "Code",
                "project_path": str(project),
                "metadata": configuration,
            },
            [
                {
                    "session_id": session_id,
                    "event_id": f"{session_id}-prompt",
                    "event_type": "user_message",
                    "subtype": "prompt",
                    "role": "user",
                    "content": "request",
                    "timestamp": 1_000.0,
                },
                {
                    "session_id": session_id,
                    "event_id": f"{session_id}-response",
                    "event_type": "assistant_message",
                    "subtype": "response",
                    "role": "assistant",
                    "content": "result",
                    "timestamp": 2_000.0,
                    "metadata": configuration,
                },
            ],
            session_id=session_id,
        )
    conn.commit()
    conn.close()
    opened = _scope(project, store)
    try:
        report = audit([opened], session_ids={"selected"})
        assert report["totals"]["model_turns"] == 1
        assert report["totals"]["configured_model_turns"] == 1
        assert [
            row["model_name_exact"] for row in report["configurations"]
        ] == ["gpt-selected"]
        assert report["configurations"][0]["model_turn_occurrences"] == 1
        assert {
            row["session_entity_id"]
            for row in report["configurations"][0]["occurrence_examples"]
        } == {
            conn_row[0]
            for conn_row in opened["conn"].execute(
                "SELECT session_entity_id FROM sessions WHERE id='selected'"
            )
        }
    finally:
        opened["conn"].close()


def test_orientation_summary_reconciles_to_independent_sqlite_scan(tmp_path):
    project, store, _source = _store(tmp_path)
    opened = _scope(project, store)
    try:
        observed = execute(
            [opened], make_request("overview", facet_limit=1_000)
        )["summary"]
        expected = _sqlite_observations([opened])
        assert _compare(observed, expected) == []
    finally:
        opened["conn"].close()


def test_monthly_tool_interactions_are_distinct_across_days(tmp_path):
    project, store, _source = _store(tmp_path)
    conn = connect(store)
    conn.execute(
        """
        UPDATE events
        SET event_kind='tool.call',tool_name='Read',tool_input='{}'
        WHERE event_id IN ('e1','e2')
        """
    )
    conn.execute(
        "UPDATE events SET event_at=?,timestamp=? WHERE event_id='e2'",
        (86_404_000.0, 86_404_000.0),
    )
    conn.commit()
    conn.close()
    opened = _scope(project, store)
    try:
        summary = execute(
            [opened], make_request("overview", facet_limit=1_000)
        )["summary"]
        month = summary["tool_activity_by_utc_month"]["1970-01"]
        assert month["calls"] == 2
        assert month["call_interactions"] == 1
    finally:
        opened["conn"].close()
