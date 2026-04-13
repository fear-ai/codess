"""CC adapter corner cases: record variants, bad input, tool extraction."""

from pathlib import Path

import pytest

from codess.adapters.cc import (
    extract_tool_input,
    iter_cc_records,
    normalize_assistant,
    normalize_user,
    process_file,
    should_skip,
    truncate_content,
)


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

    def test_edit(self):
        assert extract_tool_input("Edit", {"path": "x", "old_len": 5, "new_len": 10}) == {
            "path": "x", "old_len": 5, "new_len": 10
        }

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

    def test_permission_denied(self):
        rec = {"message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "denied", "is_error": True}
        ]}}
        evs = normalize_user(rec, 1, "s1", "/f", {"t1": "Edit"}, {"redact": False})
        assert evs[0]["subtype"] == "permission_denied" and evs[0]["tool_name"] == "Edit"

    def test_tool_result_content_as_list(self):
        rec = {"message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [
                {"type": "text", "text": "line1"},
                {"type": "text", "text": "line2"},
            ], "is_error": False}
        ]}}
        evs = normalize_user(rec, 1, "s1", "/f", {"t1": "Read"}, {"redact": False})
        assert "line1" in evs[0]["content"] and "line2" in evs[0]["content"]

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
        rec = {"message": {"role": "assistant", "content": [
            {"type": "text", "text": "I'll run it."},
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
        ]}}
        evs, tm = normalize_assistant(rec, 1, "s1", "/f", {"redact": False})
        assert len(evs) == 2
        assert evs[0]["subtype"] == "dialog"
        assert evs[1]["event_type"] == "tool_call" and evs[1]["tool_name"] == "Bash"
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
