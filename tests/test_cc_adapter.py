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
from codess.content_processing import ContentPolicy, ContentProcessor
from codess.schema_contract import validate_mapped_event


class TestShouldSkip:
    """should_skip for all skip types."""

    def test_progress(self):
        assert should_skip({"type": "progress"})

    def test_file_history_snapshot(self):
        assert should_skip({"type": "file-history-snapshot"})

    def test_file_history_delta(self):
        """Known product state, not an unsupported record (13.4.9)."""
        assert should_skip({"type": "file-history-delta"})

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
    event = next(iter(process_file(path, "s1", {})))
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

    @pytest.mark.parametrize(
        ("text", "event_type", "subtype", "actor_kind", "event_kind"),
        [
            (
                "<local-command-caveat>Caveat</local-command-caveat>",
                "system_event", "local_command_notice", "harness",
                "message.context",
            ),
            (
                "<command-name>/model</command-name>\n"
                "<command-message>model</command-message>",
                "user_message", "slash_command", "human", "command.invoke",
            ),
            (
                "<local-command-stdout>Set model to Opus</local-command-stdout>",
                "system_event", "local_command_output", "harness",
                "command.result",
            ),
        ],
    )
    def test_tagged_local_command_user_envelope(
        self, text, event_type, subtype, actor_kind, event_kind,
    ):
        rec = {
            "type": "user",
            "userType": "external",
            "message": {"role": "user", "content": text},
        }
        event = normalize_user(
            rec, 1, "s1", "/f", {}, {"redact": False}
        )[0]
        assert event["event_type"] == event_type
        assert event["subtype"] == subtype
        assert event["actor_kind"] == actor_kind
        assert event["event_kind"] == event_kind
        if subtype == "slash_command":
            assert json.loads(event["metadata"])["command_name"] == "/model"

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

    def test_is_error_is_kept_as_source_status(self):
        """The vendor's own flag is source evidence, not only a subtype.

        `source_status` recorded a text-pattern inference used for MCP
        results and nothing else, so it was null on all 470 Claude failure
        and denial Events while Claude states the outcome directly. `normalized_status`
        is correct either way; what is lost is the exact source value the schema retains.
        """
        record = {"message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "<tool_use_error>File missing.</tool_use_error>",
             "is_error": True},
        ]}}
        events = normalize_user(
            record, 1, "s1", "/f", {"t1": "Read"}, {"redact": False},
        )
        assert events[0]["source_status"] == "is_error"

    def test_successful_result_has_no_source_status(self):
        record = {"message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "ok", "is_error": False},
        ]}}
        events = normalize_user(
            record, 1, "s1", "/f", {"t1": "Read"}, {"redact": False},
        )
        assert events[0]["source_status"] is None

    def test_mcp_error_body_overrides_false_is_error_flag(self):
        rec = {"message": {"role": "user", "content": [
            {
                "type": "tool_result",
                "tool_use_id": "t1",
                "content": "Error: result exceeds maximum allowed tokens",
                "is_error": False,
            }
        ]}}
        evs = normalize_user(
            rec, 1, "s1", "/f",
            {"t1": "mcp__visualize__read_me"},
            {"redact": False},
        )
        assert evs[0]["subtype"] == "tool_failure"
        assert evs[0]["source_status"] == "application_error"
        assert evs[0]["normalized_status"] == "failed"
        metadata = json.loads(evs[0]["metadata"])
        assert metadata["source_is_error"] is False
        assert metadata["application_status"] == "failed"

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

    def test_subagent_text_envelope_is_harness_delegated_not_human(self):
        rec = {
            "type": "user",
            "userType": "external",
            "isSidechain": True,
            "agentId": "agent-1",
            "message": {"role": "user", "content": "Investigate this"},
        }
        event = normalize_user(
            rec, 1, "s1",
            "/tmp/session/subagents/agent-1.jsonl", {},
            {"redact": False},
        )[0]
        assert event["event_type"] == "system_event"
        assert event["subtype"] == "delegated_prompt"
        assert event["actor_kind"] == "harness"
        assert event["content_role"] == "delegated_task"
        assert event["origin_kind"] == "harness_delegated"
        metadata = json.loads(event["metadata"])
        assert set(metadata["actor_evidence"]) == {
            "record.isSidechain",
            "record.agentId",
            "source_path.subagents",
        }

    def test_subagent_list_text_envelope_is_harness_delegated(self):
        rec = {
            "type": "user",
            "userType": "external",
            "isSidechain": True,
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Continue"}],
            },
        }
        event = normalize_user(
            rec, 1, "s1", "/tmp/subagents/agent.jsonl", {},
            {"redact": False},
        )[0]
        assert event["actor_kind"] == "harness"
        assert event["origin_kind"] == "harness_delegated"

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

    def test_system_local_command_release_variant_is_preserved(self, tmp_path):
        path = tmp_path / "session.jsonl"
        path.write_text(json.dumps({
            "type": "system",
            "subtype": "local_command",
            "content": (
                "<local-command-stdout>Kept model as Sonnet</local-command-stdout>"
            ),
        }) + "\n")
        event = next(iter(process_file(path, "s1", {"redact": False})))
        assert event["event_type"] == "system_event"
        assert event["subtype"] == "local_command_output"
        assert event["actor_kind"] == "harness"
        assert event["event_kind"] == "command.result"
        assert event["mapping_rule"] == "claude.message"

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
        event = next(iter(process_file(path, "s1", {})))
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
            "audit_kind": "context_compaction",
            "trigger": "auto",
            "pre_tokens": 64000,
            "post_tokens": 8000,
            "duration_ms": 1200,
        }
        summary = next(
            event for event in events
            if event["subtype"] == "context_compaction_summary"
        )
        assert summary["content"] == "summary body is not retained"
        assert summary["content_len"] == len(summary["content"])
        assert summary["event_kind"] == "context.inject"
        assert summary["actor_kind"] == "harness"
        assert summary["mapping_rule"] == "claude.compaction-summary"
        assert json.loads(summary["metadata"])["compaction_boundary_uuid"] == (
            "compact-1"
        )

    def test_compaction_summary_uses_context_limit(self, tmp_path):
        path = tmp_path / "compact.jsonl"
        path.write_text(json.dumps({
            "type": "user",
            "isCompactSummary": True,
            "parentUuid": "boundary",
            "message": {"role": "user", "content": "0123456789abcdef"},
        }) + "\n")
        event = next(iter(process_file(
            path, "s1",
            {"redact": False, "max_context_content_chars": 8},
        )))
        assert event["content"] == "0123456…"
        assert event["content_len"] == 16
        assert json.loads(event["metadata"])["content_truncated"] is True

    def test_context_limit_is_reapplied_after_processing(self, tmp_path):
        path = tmp_path / "compact.jsonl"
        path.write_text(json.dumps({
            "type": "user",
            "isCompactSummary": True,
            "message": {"role": "user", "content": "xxxx"},
        }) + "\n")
        processor = ContentProcessor(ContentPolicy.from_mapping({
            "scopes": [{
                "when": {
                    "phase": "post",
                    "record_type": "context.compact.summary",
                },
                "privacy_patterns": [{
                    "pattern": "x", "replacement": "YYYY",
                }],
            }],
        }))
        event = next(iter(process_file(path, "s1", {
            "max_context_content_chars": 5,
            "content_processor": processor,
        })))
        assert event["content"] == "YYYY…"
        assert event["content_len"] == 4
        assert json.loads(event["metadata"])["content_truncated"] is True

    def test_redaction_disables_raw_debug_capture(self, tmp_path):
        path = tmp_path / "session.jsonl"
        path.write_text(
            '{"type":"user","message":{"role":"user","content":'
            '[{"type":"text","text":"secret"}]}}\n'
        )
        events = list(process_file(path, "s1", {"debug": True, "redact": True}))
        assert events
        assert all(event["source_raw"] is None for event in events)

    def test_nonsemantic_state_is_dropped_and_image_input_is_retained(
        self, tmp_path
    ):
        path = tmp_path / "session.jsonl"
        records = [
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": [{
                    "type": "thinking", "thinking": "",
                    "signature": "opaque",
                }]},
            },
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": [{
                    "type": "fallback", "from": "a", "to": "b",
                }]},
            },
            {
                "type": "user",
                "message": {"role": "user", "content": [{
                    "type": "image",
                    "source": {"type": "base64", "data": "AA=="},
                }]},
            },
        ]
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records)
        )
        diagnostics = {}
        events = list(process_file(path, "s1", {"diagnostics": diagnostics}))
        # The two non-semantic assistant states remain state-only: an empty
        # thinking block and a fallback notice carry no communication.
        assert diagnostics["empty_reasoning_state_records"] == 1
        assert diagnostics["fallback_state_records"] == 1
        assert diagnostics["known_ignored_records"] == 2
        assert diagnostics.get("ignored_records", 0) == 0
        # The image-only user record now decodes. It was counted unsupported
        # and emitted nothing, so a human prompt existed in the Session and
        # not in the store.
        assert diagnostics.get("unsupported_records", 0) == 0
        [event] = events
        assert event["subtype"] == "attachment"
        assert event["actor_kind"] == "human"
        assert event["content"] is None

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

    def test_product_state_splits_into_four_kinds(self, tmp_path):
        """Each product-state subtype selects on its own purpose.

        One kind spanning every subtype made a query for Session titles return
        permission settings and file diffs too, because titles, harness
        settings, attached material, and a position marker were one kind
       . The rule id tracks the kind, so the released profile and
        the decoder cannot disagree about which is which.
        """
        records = [
            {"type": "ai-title", "aiTitle": "T", "sessionId": "s1"},
            {"type": "custom-title", "customTitle": "T", "sessionId": "s1"},
            {"type": "agent-name", "agentName": "R", "sessionId": "s1"},
            {"type": "mode", "mode": "normal", "sessionId": "s1"},
            {"type": "permission-mode", "permissionMode": "acceptEdits", "sessionId": "s1"},
            {"type": "last-prompt", "lastPrompt": "p", "sessionId": "s1"},
        ]
        path = tmp_path / "session.jsonl"
        path.write_text("".join(json.dumps(record) + "\n" for record in records))
        events = list(process_file(path, "s1", {"redact": False}))
        by_subtype = {event["subtype"]: event for event in events}
        assert by_subtype["ai_title"]["event_kind"] == "session.label"
        assert by_subtype["custom_title"]["event_kind"] == "session.label"
        assert by_subtype["agent_name"]["event_kind"] == "session.label"
        assert by_subtype["mode"]["event_kind"] == "harness.setting"
        assert by_subtype["permission_mode"]["event_kind"] == "harness.setting"
        assert by_subtype["last_prompt_marker"]["event_kind"] == "session.marker"
        assert by_subtype["ai_title"]["mapping_rule"] == "claude.session-label"
        assert by_subtype["mode"]["mapping_rule"] == "claude.harness-setting"
        assert by_subtype["last_prompt_marker"]["mapping_rule"] == "claude.session-marker"
        assert not any(
            event["event_kind"] == "state.product" for event in events
        )

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
        assert metadata["content_digest"]
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


def test_get_timestamp_reports_field_state():
    """A16: malformed timestamp -> warn diagnostic; absent -> info; never raises."""
    from codess.adapters.cc import _get_timestamp

    opts = {"diagnostics": {}, "field_diagnostics": []}
    assert _get_timestamp({"timestamp": "not-a-date"}, opts) is None
    assert _get_timestamp({}, opts) is None
    assert _get_timestamp({"timestamp": 1700000000000.0}, opts) == 1700000000000.0

    assert opts["diagnostics"] == {"field_malformed": 1, "field_absent": 1}
    levels = [(r["severity"], r["reason_code"]) for r in opts["field_diagnostics"]]
    assert ("warn", "field_malformed") in levels
    assert ("info", "field_absent") in levels


def test_hostile_assistant_fields_are_diagnosed_without_losing_record(tmp_path):
    transcript = tmp_path / "hostile.jsonl"
    transcript.write_text(json.dumps({
        "type": "assistant",
        "timestamp": "not-a-date",
        "message": {
            "role": "assistant",
            "model": {"unexpected": "shape"},
            "content": [
                {"type": "text", "text": "still retained"},
                {"type": "tool_use", "id": "call-1", "name": "Read",
                 "input": ["wrong-shape"]},
            ],
        },
    }) + "\n")
    events = list(process_file(
        transcript, "session-id", {"redact": False, "diagnostics": {}}
    ))
    assert len(events) == 2
    reasons = {
        (row["source_field"], row["reason_code"], row["severity"])
        for event in events for row in event.get("field_diagnostics", [])
    }
    assert ("timestamp", "field_malformed", "warn") in reasons
    assert ("message.model", "field_malformed", "warn") in reasons
    assert (
        "message.content[].input", "field_malformed", "warn"
    ) in reasons


def test_hostile_prompt_origin_is_advisory_and_prompt_is_retained(tmp_path):
    transcript = tmp_path / "origin.jsonl"
    transcript.write_text(json.dumps({
        "type": "user", "origin": 42,
        "message": {"role": "user", "content": "keep me"},
    }) + "\n")
    event = next(iter(process_file(
        transcript, "session-id", {"redact": False, "diagnostics": {}}
    )))
    assert event["content"] == "keep me"
    assert any(
        row["source_field"] == "origin"
        and row["reason_code"] == "field_malformed"
        for row in event["field_diagnostics"]
    )


class TestFileHistoryDelta:
    """A tracked file's backup, linked to the snapshot it extends.

    Real Claude Code Sessions emit 369 of these across the observed Projects,
    and without this every one is counted as an unsupported record -- the count matched
    exactly, which is what made the gap actionable rather than a suspicion.
    """

    def record(self, **overrides) -> dict:
        value = {
            "type": "file-history-delta",
            "messageId": "msg-1",
            "snapshotMessageId": "msg-0",
            "timestamp": "2026-07-10T00:00:01.000Z",
            "trackingPath": "/projects/p/main.py",
            "backup": {
                "backupFileName": "main.py.bak",
                "backupTime": "2026-07-10T00:00:02.000Z",
                "version": 3,
            },
        }
        value.update(overrides)
        return value

    def decode(self, record: dict) -> dict:
        from codess.adapters.cc import normalize_product_state

        event = normalize_product_state(record, 1, "s1", "/sources/a.jsonl", {})
        assert event is not None, "the record decoded to nothing"
        return event

    def test_it_is_product_state_rather_than_a_message(self):
        event = self.decode(self.record())
        assert event["event_type"] == "product_state"
        assert event["subtype"] == "file_history_delta"
        assert event["role"] == "harness"

    def test_it_retains_the_vendor_identifiers_it_links_through(self):
        """The delta names the message it belongs to and the snapshot it extends."""
        import json

        event = self.decode(self.record())
        metadata = json.loads(event["metadata"])
        assert metadata["message_id"] == "msg-1"
        assert metadata["snapshot_message_id"] == "msg-0"
        assert metadata["backup_version"] == 3

    def test_it_records_the_tracked_path_as_presence_not_a_copy(self):
        """The path is an Artifact locator elsewhere; this Event is structural."""
        import json

        event = self.decode(self.record())
        metadata = json.loads(event["metadata"])
        assert metadata["has_tracking_path"] is True
        assert "/projects/p/main.py" not in event["metadata"]

    def test_a_delta_without_a_backup_still_decodes(self):
        """Vendor shapes vary; a missing sub-object is absence, not a failure.

        The absent version is omitted rather than stored as null, which is
        this module's convention: a key that is not there was not recorded.
        """
        import json

        event = self.decode(self.record(backup=None))
        metadata = json.loads(event["metadata"])
        assert metadata["has_backup"] is False
        assert "backup_version" not in metadata

    def test_a_delta_is_a_known_record_rather_than_unsupported(self):
        """Without this, 44 of these are reported unsupported.

        `should_skip` is what the record loop consults before falling through
        to the unsupported counter, so membership there is the fix.
        """
        from codess.adapters.cc import SKIP_TYPES, should_skip

        assert should_skip({"type": "file-history-delta"})
        assert "file-history-delta" in SKIP_TYPES


class TestImageOnlyPrompt:
    """A human pasting a screenshot with no accompanying text.

    Untreated these produce no Event and count as unsupported, leaving the prompt in
    the Session and not in the store -- 48 of them in one observed Project, 107 image
    blocks, 19.8 MB of base64. The payload is deliberately not retained: the `attachment`
    record's bounded treatment is this adapter's established pattern.
    """

    def record(self, blocks=None) -> dict:
        return {
            "type": "user",
            "message": {"role": "user", "content": blocks if blocks is not None else [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg", "data": "A" * 400,
                }},
            ]},
        }

    def decode(self, record: dict, opts: dict | None = None) -> list[dict]:
        from codess.adapters.cc import normalize_user

        return normalize_user(record, 1, "s1", "/sources/a.jsonl", {}, opts or {})

    def test_it_is_a_human_prompt(self):
        [event] = self.decode(self.record())
        assert event["actor_kind"] == "human"
        assert event["content_role"] == "prompt"
        assert event["origin_kind"] == "direct_user_input"
        assert event["subtype"] == "attachment"

    def test_the_payload_is_not_retained(self):
        """These average ~185 KB of base64; the store records the reference."""
        [event] = self.decode(self.record())
        assert event["content"] is None
        assert event["content_len"] == 0
        assert "A" * 400 not in (event["metadata"] or "")

    def test_it_records_what_the_attachment_was(self):
        import json

        [event] = self.decode(self.record())
        metadata = json.loads(event["metadata"])
        assert metadata["attachment_type"] == "image"
        assert metadata["media_type"] == "image/jpeg"
        assert metadata["attachment_source"] == "base64"
        assert metadata["encoded_length"] == 400

    def test_each_image_in_one_record_becomes_its_own_event(self):
        """Observed records carry up to seven images; none may be lost."""
        blocks = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "B"}}
            for _ in range(7)
        ]
        events = self.decode(self.record(blocks))
        assert len(events) == 7
        assert len({event["event_id"] for event in events}) == 7

    def test_an_image_beside_text_keeps_both(self):
        """A screenshot with a caption is two Events, not one or none."""
        blocks = [
            {"type": "text", "text": "look at this"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "C"}},
        ]
        subtypes = [event["subtype"] for event in self.decode(self.record(blocks))]
        assert "attachment" in subtypes
        assert len(subtypes) == 2

    def test_a_malformed_image_block_still_decodes(self):
        """A missing source is absence, not a decode failure."""
        import json

        [event] = self.decode(self.record([{"type": "image"}]))
        metadata = json.loads(event["metadata"])
        assert metadata["encoded_length"] == 0
        assert "media_type" not in metadata

    def test_it_is_no_longer_counted_unsupported(self):
        diagnostics: dict = {}
        events = self.decode(self.record(), {"diagnostics": diagnostics})
        assert events
        assert diagnostics.get("unsupported_records", 0) == 0
        assert diagnostics.get("attachment_only_records", 0) == 0


class TestSessionSurface:
    """`entrypoint` decoded to `surface_kind` and kept verbatim."""

    def write(self, tmp_path, *records):
        f = tmp_path / "session.jsonl"
        f.write_text("".join(json.dumps(r) + "\n" for r in records))
        return f

    def test_desktop(self, tmp_path):
        """A Desktop Session is a Desktop Session, not the profile constant."""
        from codess.adapters.cc import get_session_metadata
        facts = get_session_metadata(self.write(
            tmp_path, {"type": "user", "entrypoint": "claude-desktop"},
        ))
        assert facts["surface_kind"] == "desktop"
        assert facts["entrypoint"] == "claude-desktop"

    def test_sdk(self, tmp_path):
        """`sdk-cli` is programmatic, so `api`, though the token contains "cli"."""
        from codess.adapters.cc import get_session_metadata
        facts = get_session_metadata(self.write(
            tmp_path, {"type": "user", "entrypoint": "sdk-cli"},
        ))
        assert facts["surface_kind"] == "api"
        assert facts["entrypoint"] == "sdk-cli"

    def test_cli(self, tmp_path):
        from codess.adapters.cc import get_session_metadata
        facts = get_session_metadata(self.write(
            tmp_path, {"type": "user", "entrypoint": "cli"},
        ))
        assert facts["surface_kind"] == "cli"

    def test_unlisted(self, tmp_path):
        """An unmapped value yields no surface: a wrong one is worse than none."""
        from codess.adapters.cc import get_session_metadata
        facts = get_session_metadata(self.write(
            tmp_path, {"type": "user", "entrypoint": "future-surface"},
        ))
        assert "surface_kind" not in facts
        assert facts["entrypoint"] == "future-surface"

    def test_absent(self, tmp_path):
        from codess.adapters.cc import get_session_metadata
        facts = get_session_metadata(self.write(tmp_path, {"type": "user"}))
        assert "surface_kind" not in facts
        assert "entrypoint" not in facts

    def test_stated_late(self, tmp_path):
        """The fact is sought across the whole bounded read, not until the facts
        collected so far look complete."""
        from codess.adapters.cc import get_session_metadata
        records = [{"type": "assistant", "version": "2.1.0", "cwd": "/w"}]
        records += [{"type": "assistant"} for _ in range(40)]
        records.append({"type": "user", "entrypoint": "claude-desktop"})
        facts = get_session_metadata(self.write(tmp_path, *records))
        assert facts["surface_kind"] == "desktop"

    def test_beyond_bound(self, tmp_path):
        """Past the bound the fact is not found: the bound is a resource limit, so this
        states its cost rather than a decode rule."""
        from codess.adapters.cc import MAX_FACT_RECORDS, get_session_metadata
        records = [{"type": "assistant"} for _ in range(MAX_FACT_RECORDS + 1)]
        records.append({"type": "user", "entrypoint": "claude-desktop"})
        facts = get_session_metadata(self.write(tmp_path, *records))
        assert "surface_kind" not in facts


class TestAssistantEffort:
    """Claude states `effort` at the record top level."""

    def test_effort(self):
        """Both vendors state the effort; only Codex's was being decoded."""
        from codess.adapters.cc import _assistant_configuration
        values = _assistant_configuration({
            "type": "assistant", "uuid": "u1", "effort": "high",
            "message": {"model": "claude-opus-4-8"},
        })
        assert values["reasoning_effort"] == "high"
        assert values["model"] == "claude-opus-4-8"
        provenance = values["configuration_provenance"]["reasoning_effort"]
        assert provenance["source_field"] == "effort"

    def test_effort_without_message(self):
        """`effort` is top-level, so an absent `message` must not drop it."""
        from codess.adapters.cc import _assistant_configuration
        values = _assistant_configuration({"type": "assistant", "effort": "high"})
        assert values["reasoning_effort"] == "high"

    def test_absent(self):
        from codess.adapters.cc import _assistant_configuration
        values = _assistant_configuration({
            "type": "assistant", "message": {"model": "claude-opus-4-8"},
        })
        assert "reasoning_effort" not in values


class TestModelFallback:
    """One model asked for, another answered, both stated."""

    def record(self):
        return {
            "type": "system", "subtype": "model_consent_fallback",
            "uuid": "u1", "timestamp": "2026-07-20T07:27:25.493Z",
            "originalModel": "claude-fable-5",
            "fallbackModel": "claude-sonnet-5",
            "choice": "switch_default", "persistedAsDefault": False,
            "content": "Switched to Sonnet 5 for this session",
        }

    def test_fallback(self):
        """Without this the Session shows only the model that ran, and the
        model that was asked for is lost."""
        from codess.adapters.cc import normalize_product_state

        event = normalize_product_state(self.record(), 1, "s1", "/f", {})
        assert event["subtype"] == "model_fallback"
        metadata = json.loads(event["metadata"])
        assert metadata["requested_model"] == "claude-fable-5"
        assert metadata["fallback_model"] == "claude-sonnet-5"
        assert metadata["fallback_choice"] == "switch_default"

    def test_not_skipped(self):
        """The record has no `message.content`, so the generic system rule
        would drop it; the named branch runs first."""
        from codess.adapters.cc import normalize_product_state

        assert normalize_product_state(self.record(), 1, "s1", "/f", {}) is not None


class TestProductStatePartition:
    """The four Event kinds that replaced `state.product`.

    The table and the rule map are one decision expressed twice, so they are
    checked against each other rather than each against a copy of itself: a
    rule naming a kind the released profile does not declare would otherwise
    reach a store and fail only at conformance time.
    """

    def test_every_subtype_maps_to_one_of_the_four_kinds(self):
        from codess.adapters.cc import _PRODUCT_STATE_KINDS

        assert set(_PRODUCT_STATE_KINDS.values()) == {
            "session.label", "harness.setting",
            "content.attachment", "session.marker",
        }

    def test_the_nine_observed_subtypes_are_covered(self):
        """Every subtype the decoder emits is classified.

        Measured against real stores: these nine are the whole of the family,
        11,272 Events across the development machine's Claude stores.
        """
        from codess.adapters.cc import _PRODUCT_STATE_KINDS

        assert set(_PRODUCT_STATE_KINDS) == {
            "ai_title", "custom_title", "agent_name",
            "mode", "permission_mode",
            "context_attachment", "file_history_snapshot", "file_history_delta",
            "last_prompt_marker",
        }

    def test_a_rule_exists_for_every_kind(self):
        from codess.adapters.cc import _PRODUCT_STATE_KINDS, _PRODUCT_STATE_RULES

        assert set(_PRODUCT_STATE_RULES) == set(_PRODUCT_STATE_KINDS)
        for subtype, kind in _PRODUCT_STATE_KINDS.items():
            expected = "claude." + kind.replace(".", "-")
            assert _PRODUCT_STATE_RULES[subtype] == expected

    def test_every_rule_is_declared_in_the_released_profile(self):
        """The profile is what `validate_mapped_event` checks against.

        A rule the decoder emits but the profile does not declare is the
        failure the split could introduce, and it would surface only when a
        conformance check ran over a store rather than here.
        """
        from codess.adapters.cc import _PRODUCT_STATE_RULES
        from codess.schema_contract import load_mapping

        declared = {rule["id"] for rule in load_mapping("claude")["rules"]}
        assert set(_PRODUCT_STATE_RULES.values()) <= declared
        assert "claude.product-state" not in declared

    def test_an_unknown_subtype_keeps_the_general_kind(self):
        """A newly observed Claude record is not guessed into a partition.

        `event_kind` is a declared open vocabulary, so an unrecognized subtype
        is evidence to classify deliberately rather than to force into the
        nearest existing name.
        """
        from codess.adapters.cc import _product_state_kind

        assert _product_state_kind("a_shape_not_yet_seen") == "state.product"
        assert _product_state_kind(None) == "state.product"
        assert _product_state_kind("") == "state.product"

    def test_attachment_records_classify_as_attached_material(self, tmp_path):
        """The three attachment subtypes reach `content.attachment` end to end.

        Covered separately from the label and setting cases because these
        records travel a different decode path -- they carry bounded metadata
        about attached material rather than a single short value.
        """
        records = [
            {"type": "attachment", "attachment": {"type": "file", "content": "x"},
             "sessionId": "s1"},
            {"type": "file-history-snapshot", "snapshot": {"a": 1}, "sessionId": "s1"},
        ]
        path = tmp_path / "session.jsonl"
        path.write_text("".join(json.dumps(record) + "\n" for record in records))
        events = list(process_file(path, "s1", {"redact": False}))
        kinds = {event["subtype"]: event["event_kind"] for event in events}
        for subtype, kind in kinds.items():
            if subtype in {"context_attachment", "file_history_snapshot"}:
                assert kind == "content.attachment"
        assert kinds, "no attachment events decoded"
