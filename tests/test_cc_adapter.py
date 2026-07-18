"""CC adapter corner cases: record variants, bad input, tool extraction."""

import json
from pathlib import Path

import pytest

from codess.adapters.cc import (
    SourceCompatibilityError,
    extract_tool_input,
    get_session_lineage,
    iter_cc_records,
    normalize_assistant,
    normalize_user,
    process_file,
    should_skip,
    truncate_content,
)
from codess.schema_contract import validate_mapped_event


class TestShouldSkip:
    """should_skip for all skip types."""

    def test_progress(self):
        assert should_skip({"type": "progress"})

    def test_file_history_snapshot(self):
        assert should_skip({"type": "file-history-snapshot"})

    def test_queue_operation(self):
        assert should_skip({"type": "queue-operation"})

    def test_last_prompt(self):
        assert should_skip({"type": "last-prompt"})

    def test_system_empty(self):
        assert should_skip({"type": "system", "message": {}})
        assert should_skip({"type": "system", "message": {"content": []}})

    def test_system_with_content(self):
        assert not should_skip({"type": "system", "message": {"content": ["x"]}})

    def test_user_assistant_not_skipped(self):
        assert not should_skip({"type": "user"})
        assert not should_skip({"type": "assistant"})

    def test_unknown_type_not_skipped(self):
        assert not should_skip({"type": "unknown"})


def test_claude_events_carry_declared_exact_mapping_evidence(tmp_path):
    path = tmp_path / "session.jsonl"
    path.write_text(json.dumps({
        "type": "assistant", "version": "2.1.0", "message": {
            "role": "assistant", "content": [{"type": "text", "text": "hi"}],
        },
    }) + "\n", encoding="utf-8")
    event = list(process_file(path, "s1", {}))[0]
    assert event["source_record_type"] == "assistant"
    assert validate_mapped_event("claude", event) == []


class TestTruncateContent:
    """truncate_content edge cases."""

    def test_none(self):
        t, n = truncate_content(None, 10)
        assert t == "" and n == 0

    def test_empty(self):
        t, n = truncate_content("", 10)
        assert t == "" and n == 0

    def test_exact_limit(self):
        s = "x" * 10
        t, n = truncate_content(s, 10)
        assert t == s and n == 10

    def test_one_over_limit(self):
        s = "x" * 11
        t, n = truncate_content(s, 10)
        assert len(t) == 10 and t.endswith("…") and n == 11

    def test_zero_limit(self):
        t, n = truncate_content("hello", 0)
        assert t == "…" and n == 5

    def test_negative_limit(self):
        t, n = truncate_content("hi", -1)
        assert t == "…" and n == 2


class TestExtractToolInput:
    """extract_tool_input per tool type."""

    def test_bash(self):
        assert extract_tool_input("Bash", {"command": "ls -la"}) == {"command": "ls -la"}
        assert extract_tool_input("bash", {"command": "x", "other": 1}) == {"command": "x"}

    def test_read(self):
        assert extract_tool_input("Read", {"path": "a.py", "offset": 0, "limit": 100}) == {
            "path": "a.py", "offset": 0, "limit": 100
        }

    def test_read_modern_file_path(self):
        assert extract_tool_input(
            "Read", {"file_path": "a.py", "offset": 0, "limit": 100, "pages": "1"}
        ) == {"file_path": "a.py", "offset": 0, "limit": 100, "pages": "1"}

    def test_edit(self):
        assert extract_tool_input("Edit", {"path": "x", "old_len": 5, "new_len": 10}) == {
            "path": "x", "old_len": 5, "new_len": 10
        }

    def test_modern_edit_and_write_retain_path_but_only_content_lengths(self):
        assert extract_tool_input(
            "Edit",
            {"file_path": "x.py", "old_string": "old", "new_string": "newer", "replace_all": True},
        ) == {"file_path": "x.py", "replace_all": True, "old_len": 3, "new_len": 5}
        assert extract_tool_input(
            "Write", {"file_path": "x.py", "content": "secret body"}
        ) == {"file_path": "x.py", "content_len": 11}

    def test_grep_truncates_pattern(self):
        long_pat = "x" * 250
        out = extract_tool_input("Grep", {"pattern": long_pat})
        assert len(out["pattern"]) == 200 and out["pattern"].endswith("…")

    def test_agent_truncates_prompt(self):
        long_p = "y" * 2500
        out = extract_tool_input("Agent", {"prompt": long_p})
        assert len(out["prompt"]) == 2000 and out["prompt"].endswith("…")

    def test_mcp_task_extracts_description_prompt_subagent(self):
        out = extract_tool_input("mcp_task", {"description": "Research X", "prompt": "Find Y", "subagent_type": "explore"})
        assert out == {"description": "Research X", "prompt": "Find Y", "subagent_type": "explore"}

    def test_unknown_tool_passthrough(self):
        out = extract_tool_input("UnknownTool", {"foo": "bar"})
        assert out == {"foo": "bar"}

    def test_empty_input(self):
        assert extract_tool_input("Bash", {}) == {}
        assert extract_tool_input("Bash", None) == {}


class TestNormalizeUser:
    """normalize_user record variants."""

    def test_text_prompt(self):
        rec = {"message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}}
        evs = normalize_user(rec, 1, "s1", "/f", {}, {"redact": False})
        assert len(evs) == 1
        assert evs[0]["event_type"] == "user_message" and evs[0]["subtype"] == "prompt"

    def test_modern_string_prompt_preserves_human_origin(self):
        rec = {
            "uuid": "prompt-record",
            "origin": {"kind": "human"},
            "promptSource": "typed",
            "permissionMode": "acceptEdits",
            "message": {"role": "user", "content": "repair the build"},
        }
        evs = normalize_user(rec, 7, "s1", "/f", {}, {"redact": False})
        assert len(evs) == 1
        assert evs[0]["event_type"] == "user_message"
        assert evs[0]["subtype"] == "prompt"
        assert evs[0]["actor_kind"] == "human"
        assert evs[0]["origin_kind"] == "direct_user_input"
        assert evs[0]["content"] == "repair the build"
        metadata = json.loads(evs[0]["metadata"])
        assert metadata["prompt_source"] == "typed"
        assert metadata["permission_mode"] == "acceptEdits"

    def test_string_system_notification_is_not_mislabeled_human(self):
        rec = {
            "origin": {"kind": "task-notification"},
            "promptSource": "system",
            "message": {"role": "user", "content": "scheduled task completed"},
        }
        event = normalize_user(rec, 8, "s1", "/f", {}, {"redact": False})[0]
        assert event["event_type"] == "system_event"
        assert event["subtype"] == "task_notification"
        assert event["actor_kind"] == "harness"
        assert event["origin_kind"] == "harness_injected"

    def test_strict_mode_rejects_unsupported_user_content_shape(self):
        rec = {"message": {"role": "user", "content": {"unexpected": True}}}
        with pytest.raises(SourceCompatibilityError, match="user content"):
            normalize_user(
                rec, 9, "s1", "/f", {},
                {"redact": False, "strict_mapping": True},
            )

    def test_slash_command(self):
        rec = {"message": {"role": "user", "content": [{"type": "text", "text": "/fix"}]}}
        evs = normalize_user(rec, 1, "s1", "/f", {}, {"redact": False})
        assert evs[0]["subtype"] == "slash_command"

    def test_tool_result(self):
        rec = {"message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok", "is_error": False}
        ]}}
        evs = normalize_user(rec, 1, "s1", "/f", {"t1": "Bash"}, {"redact": False})
        assert len(evs) == 1 and evs[0]["subtype"] == "tool_result" and evs[0]["tool_name"] == "Bash"
        assert evs[0]["normalized_status"] == "succeeded"

    def test_permission_denied(self):
        rec = {"message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "Permission for this tool use was denied.", "is_error": True}
        ]}}
        evs = normalize_user(rec, 1, "s1", "/f", {"t1": "Edit"}, {"redact": False})
        assert evs[0]["subtype"] == "permission_denied" and evs[0]["tool_name"] == "Edit"
        assert evs[0]["normalized_status"] is None

    def test_non_permission_error_is_tool_failure(self):
        rec = {"message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "<tool_use_error>File missing.</tool_use_error>", "is_error": True}
        ]}}
        evs = normalize_user(rec, 1, "s1", "/f", {"t1": "Read"}, {"redact": False})
        assert evs[0]["subtype"] == "tool_failure"

    def test_tool_result_content_as_list(self):
        rec = {"uuid": "result-record", "parentUuid": "call-record",
               "message": {"role": "user", "content": [
            {"type": "text", "text": "context"},
            {"type": "tool_result", "tool_use_id": "t1", "content": [
                {"type": "text", "text": "line1"},
                {"type": "text", "text": "line2"},
            ], "is_error": False}
        ]}}
        evs = normalize_user(rec, 1, "s1", "/f", {"t1": "Read"}, {"redact": False})
        assert [event["event_id"] for event in evs] == ["1", "1:1"]
        assert "line1" in evs[1]["content"] and "line2" in evs[1]["content"]
        assert json.loads(evs[1]["metadata"]) == {
            "record_uuid": "result-record",
            "parent_uuid": "call-record",
            "tool_use_id": "t1",
        }

    def test_tool_result_no_pairing(self):
        rec = {"message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "unknown", "content": "x", "is_error": False}
        ]}}
        evs = normalize_user(rec, 1, "s1", "/f", {}, {"redact": False})
        assert evs[0]["tool_name"] is None


class TestNormalizeAssistant:
    """normalize_assistant record variants."""

    def test_response_no_tool_use(self):
        rec = {"message": {"role": "assistant", "content": [{"type": "text", "text": "Here you go."}]}}
        evs, _ = normalize_assistant(rec, 1, "s1", "/f", {"redact": False})
        assert len(evs) == 1 and evs[0]["subtype"] == "response"

    def test_dialog_tool_use_follows(self):
        rec = {"uuid": "assistant-record", "parentUuid": "prior-record",
               "message": {"role": "assistant", "content": [
            {"type": "text", "text": "I'll run it."},
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
        ]}}
        evs, tm = normalize_assistant(rec, 1, "s1", "/f", {"redact": False})
        assert len(evs) == 2
        assert evs[0]["subtype"] == "dialog"
        assert evs[1]["event_type"] == "tool_call" and evs[1]["tool_name"] == "Bash"
        assert [event["event_id"] for event in evs] == ["1", "1:1"]
        assert json.loads(evs[1]["metadata"]) == {
            "record_uuid": "assistant-record",
            "parent_uuid": "prior-record",
            "tool_use_id": "t1",
        }
        assert tm == {"t1": "Bash"}

    def test_truncated_stop_reason(self):
        """CC adapter reads stop_reason from message."""
        rec = {"message": {"role": "assistant", "stop_reason": "max_tokens",
               "content": [{"type": "text", "text": "x" * 500}]}}
        evs, _ = normalize_assistant(rec, 1, "s1", "/f", {"redact": False})
        assert evs[0]["subtype"] == "truncated"

    def test_tool_use_only(self):
        rec = {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"path": "a.py"}}
        ]}}
        evs, _ = normalize_assistant(rec, 1, "s1", "/f", {"redact": False})
        assert len(evs) == 1 and evs[0]["event_type"] == "tool_call"

    def test_tool_input_is_recursively_sanitized_and_redacted(self):
        rec = {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "UnknownTool",
             "input": {"nested": ["safe\u0000", "sk-abcdefghij1234567890xyz"]}}
        ]}}
        evs, _ = normalize_assistant(rec, 1, "s1", "/f", {"redact": True})
        tool_input = evs[0]["tool_input"]
        assert "\\u0000" not in tool_input
        assert "sk-" not in tool_input
        assert "[REDACTED]" in tool_input


class TestIterCcRecords:
    """iter_cc_records bad input and edge cases."""

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        assert list(iter_cc_records(f)) == []

    def test_only_blank_lines(self, tmp_path):
        f = tmp_path / "blank.jsonl"
        f.write_text("\n\n\n")
        assert list(iter_cc_records(f)) == []

    def test_truncated_json(self, tmp_path):
        f = tmp_path / "trunc.jsonl"
        f.write_text('{"type":"user","message":')
        recs = list(iter_cc_records(f))
        assert len(recs) == 0

    def test_unclosed_bracket(self, tmp_path):
        f = tmp_path / "bad.jsonl"
        f.write_text('{"type":"user"}')
        f.write_text('{"incomplete": ')  # overwrites
        f.write_text('{"type":"user"}\n{"incomplete": \n')
        recs = list(iter_cc_records(f))
        assert len(recs) == 1
        assert recs[0][1]["type"] == "user"

    def test_mixed_valid_invalid(self, tmp_path):
        f = tmp_path / "mixed.jsonl"
        f.write_text('{"type":"user"}\nnot json\n{"type":"assistant"}\n')
        recs = list(iter_cc_records(f))
        assert len(recs) == 2


class TestGetTimestamp:
    """_get_timestamp handles float and ISO 8601."""

    def test_float_timestamp(self):
        from codess.adapters.cc import _get_timestamp
        assert _get_timestamp({"timestamp": 1710000000123.0}) == 1710000000123.0
        assert _get_timestamp({"message": {"timestamp": 1710000000123.0}}) == 1710000000123.0

    def test_iso8601_timestamp(self):
        from codess.adapters.cc import _get_timestamp
        ts = _get_timestamp({"timestamp": "2026-03-07T18:01:43.313Z"})
        assert ts is not None and ts > 1e12

    def test_missing_returns_none(self):
        from codess.adapters.cc import _get_timestamp
        assert _get_timestamp({}) is None
        assert _get_timestamp({"message": {}}) is None


class TestProcessFile:
    """process_file integration with fixtures."""

    def test_slash_command_ingested(self):
        fixtures = Path(__file__).parent / "fixtures" / "slash_command.jsonl"
        if not fixtures.exists():
            pytest.skip("fixture missing")
        evs = list(process_file(fixtures, "s1", {"redact": False}))
        assert any(e.get("subtype") == "slash_command" for e in evs)

    def test_assistant_model_and_service_tier_have_source_provenance(self, tmp_path):
        path = tmp_path / "session.jsonl"
        path.write_text(json.dumps({
            "type": "assistant", "uuid": "record-1",
            "message": {
                "role": "assistant", "model": "claude-test",
                "usage": {"service_tier": "standard"},
                "content": [{"type": "text", "text": "hello"}],
            },
        }) + "\n")
        event = list(process_file(path, "s1", {}))[0]
        metadata = json.loads(event["metadata"])
        assert metadata["model"] == "claude-test"
        assert metadata["service_tier"] == "standard"
        assert metadata["configuration_provenance"]["model"] == {
            "source_record_type": "assistant",
            "source_record_locator": "record-1",
            "source_field": "message.model",
        }

    def test_lineage_fixture_contract(self):
        fixture = Path(__file__).parent / "fixtures" / "claude_lineage.jsonl"
        events = list(process_file(fixture, "lineage", {"redact": False}))
        assert [event["event_id"] for event in events] == ["1", "1:1", "2"]
        call = events[1]
        result = events[2]
        assert json.loads(call["metadata"])["tool_use_id"] == "tool-read"
        assert json.loads(result["metadata"])["tool_use_id"] == "tool-read"
        assert call["tool_name"] == result["tool_name"] == "Read"

    def test_audit_fixture_contract(self):
        fixture = Path(__file__).parent / "fixtures" / "claude_audit.jsonl"
        events = list(process_file(fixture, "audit", {"redact": False}))
        audit = {
            event["subtype"]: event
            for event in events
            if event["subtype"] in {
                "permission_denied", "tool_failure", "context_compaction"
            }
        }
        assert set(audit) == {
            "permission_denied", "tool_failure", "context_compaction"
        }
        compact = audit["context_compaction"]
        assert compact["content"] is None
        assert json.loads(compact["metadata"]) == {
            "audit_kind": "context_compaction", "trigger": "auto"
        }
        assert all("summary body" not in (event.get("content") or "") for event in events)

    def test_redaction_disables_raw_debug_capture(self, tmp_path):
        path = tmp_path / "session.jsonl"
        path.write_text(
            '{"type":"user","message":{"role":"user","content":'
            '[{"type":"text","text":"secret"}]}}\n'
        )
        events = list(process_file(path, "s1", {"debug": True, "redact": True}))
        assert events
        assert all(event["source_raw"] is None for event in events)

    def test_multiple_blocks_on_one_line_have_unique_stable_ids(self, tmp_path):
        path = tmp_path / "session.jsonl"
        path.write_text(json.dumps({
            "type": "assistant",
            "uuid": "record-1",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Running."},
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "Bash",
                        "input": {"command": "true"},
                    },
                ],
            },
        }) + "\n")
        events = list(process_file(path, "s1", {"redact": False}))
        assert [event["event_id"] for event in events] == ["1", "1:1"]
        assert len({event["event_id"] for event in events}) == len(events)

    def test_product_state_records_are_classified_with_bounded_parameters(self, tmp_path):
        path = tmp_path / "session.jsonl"
        records = [
            {"type": "mode", "mode": "normal", "sessionId": "s1"},
            {"type": "permission-mode", "permissionMode": "acceptEdits", "sessionId": "s1"},
            {"type": "system", "subtype": "turn_duration", "durationMs": 42, "messageCount": 3},
        ]
        path.write_text("".join(json.dumps(record) + "\n" for record in records))
        events = list(process_file(path, "s1", {"redact": False}))
        assert [(event["event_type"], event["subtype"]) for event in events] == [
            ("product_state", "mode"),
            ("product_state", "permission_mode"),
            ("lifecycle_event", "turn_duration"),
        ]
        assert json.loads(events[0]["metadata"])["mode"] == "normal"
        assert json.loads(events[2]["metadata"]) == {
            "duration_ms": 42,
            "message_count": 3,
        }

    def test_titles_agent_name_and_fork_reference_are_structured(self, tmp_path):
        path = tmp_path / "session.jsonl"
        records = [
            {"type": "custom-title", "customTitle": "A title", "sessionId": "s1"},
            {"type": "agent-name", "agentName": "Reviewer", "sessionId": "s1"},
            {"type": "fork-context-ref", "agentId": "agent-1",
             "parentSessionId": "parent-1", "parentLastUuid": "record-9",
             "contextLength": 42},
        ]
        path.write_text("".join(json.dumps(record) + "\n" for record in records))
        events = list(process_file(path, "s1", {}))
        assert [event["subtype"] for event in events] == [
            "custom_title", "agent_name", "fork_context_reference",
        ]
        assert events[0]["content"] == "A title"
        assert json.loads(events[2]["metadata"])["parent_session_id"] == "parent-1"
        assert get_session_lineage(path) == {
            "parent_session_id": "parent-1",
            "session_relation_kind": "fork",
            "lineage_provenance": "fork-context-ref.parentSessionId",
            "agent_id": "agent-1",
            "parent_last_uuid": "record-9",
        }

    def test_persisted_tool_result_emits_linked_external_content(self, tmp_path):
        session_dir = tmp_path / "session-id"
        sidecar = session_dir / "tool-results" / "result.txt"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text("external result body")
        transcript = tmp_path / "session-id.jsonl"
        transcript.write_text("".join([
            json.dumps({
                "type": "assistant",
                "message": {"role": "assistant", "content": [{
                    "type": "tool_use", "id": "tool-1", "name": "Bash",
                    "input": {"command": "run"},
                }]},
            }) + "\n",
            json.dumps({
                "type": "user",
                "message": {"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": "tool-1",
                    "content": "Output persisted externally", "is_error": False,
                }]},
                "toolUseResult": {
                    "persistedOutputPath": str(sidecar),
                    "persistedOutputSize": sidecar.stat().st_size,
                },
            }) + "\n",
        ]))
        external_sources = []
        events = list(process_file(
            transcript, "session-id",
            {"redact": False, "external_sources": external_sources},
        ))
        external = [e for e in events if e["event_type"] == "external_content"]
        assert len(external) == 1
        assert external[0]["subtype"] == "persisted_tool_result"
        assert external[0]["content"] == "external result body"
        assert external[0]["caused_by_event_id"] == "2"
        metadata = json.loads(external[0]["metadata"])
        assert metadata["content_sha256"]
        assert metadata["source_locator"] == str(sidecar)
        assert external_sources == [{
            "path": str(sidecar),
            "parent_source": str(transcript.resolve()),
            "relation_kind": "persisted_tool_result",
        }]

    def test_strict_mode_rejects_persisted_output_outside_session_tree(self, tmp_path):
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")
        transcript = tmp_path / "session-id.jsonl"
        transcript.write_text(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": "tool-1", "content": "x",
            }]},
            "toolUseResult": {"persistedOutputPath": str(outside)},
        }) + "\n")
        with pytest.raises(SourceCompatibilityError, match="outside session tree"):
            list(process_file(
                transcript, "session-id",
                {"redact": False, "strict_mapping": True},
            ))
