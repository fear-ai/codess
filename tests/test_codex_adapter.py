"""Tests for Codex adapter."""

import json
import tempfile
from pathlib import Path

import pytest

from codess.adapters.codex import (
    get_session_meta,
    get_session_metadata,
    iter_codex_records,
    process_file,
)


class TestIterCodexRecords:
    """iter_codex_records edge cases."""

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        assert list(iter_codex_records(f)) == []

    def test_skips_malformed_json(self, tmp_path):
        f = tmp_path / "bad.jsonl"
        f.write_text('{"type":"session_meta"}\nnot json\n{"type":"other"}\n')
        recs = list(iter_codex_records(f))
        assert len(recs) == 2


class TestGetSessionMeta:
    def test_from_session_meta(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"session_meta","payload":{"id":"abc","cwd":"/x/y"}}\n')
            path = Path(f.name)
        try:
            sid, cwd = get_session_meta(path)
            assert sid == "abc"
            assert cwd == "/x/y"
        finally:
            path.unlink()

    def test_fallback(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"other"}\n')
            path = Path(f.name)
        try:
            sid, cwd = get_session_meta(path)
            assert sid == path.stem
            assert cwd == "."
        finally:
            path.unlink()

    def test_session_metadata_keeps_useful_identity_fields(self, tmp_path):
        path = tmp_path / "rollout.jsonl"
        path.write_text(json.dumps({
            "type": "session_meta",
            "payload": {
                "id": "abc",
                "cwd": "/x",
                "cli_version": "1.2.3",
                "model_provider": "openai",
                "originator": "codex_cli_rs",
                "instructions": "not retained",
            },
        }) + "\n")
        assert get_session_metadata(path) == {
            "cli_version": "1.2.3",
            "model_provider": "openai",
            "originator": "codex_cli_rs",
        }


class TestProcessFile:
    def test_user_and_assistant_messages_with_iso_timestamps(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"session_meta","payload":{"id":"s1","cwd":"/p"}}\n')
            f.write('{"timestamp":"2026-07-10T12:34:56.789Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Hi"}]}}\n')
            f.write('{"timestamp":"2026-07-10T12:35:00Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Hello"}]}}\n')
            path = Path(f.name)
        try:
            events = list(process_file(path, "s1", "/p", {}))
            assert len(events) == 2
            assert events[0]["event_type"] == "user_message"
            assert events[0]["content"] == "Hi"
            assert events[1]["event_type"] == "assistant_message"
            assert events[1]["content"] == "Hello"
            assert events[0]["timestamp"] == pytest.approx(1783686896789.0)
            assert events[1]["timestamp"] == pytest.approx(1783686900000.0)
        finally:
            path.unlink()

    def test_function_and_custom_tool_call_lineage(self, tmp_path):
        path = tmp_path / "rollout.jsonl"
        records = [
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "shell",
                    "arguments": '{"command":"pwd"}',
                    "call_id": "call-1",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": "/project",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "apply_patch",
                    "input": "*** patch ***",
                    "call_id": "call-2",
                    "status": "completed",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "call-2",
                    "output": "Done!",
                },
            },
        ]
        path.write_text("".join(json.dumps(record) + "\n" for record in records))
        events = list(process_file(path, "s1", "/p", {}))
        assert [event["event_type"] for event in events] == [
            "tool_call", "user_message", "tool_call", "user_message"
        ]
        assert [event["tool_name"] for event in events] == [
            "shell", "shell", "apply_patch", "apply_patch"
        ]
        assert json.loads(events[0]["tool_input"]) == {"command": "pwd"}
        assert json.loads(events[2]["tool_input"]) == {"input": "*** patch ***"}
        assert json.loads(events[3]["metadata"]) == {"call_id": "call-2"}

    def test_web_search_is_a_tool_call(self, tmp_path):
        path = tmp_path / "rollout.jsonl"
        path.write_text(json.dumps({
            "timestamp": "2026-07-10T12:35:00Z",
            "type": "response_item",
            "payload": {
                "type": "web_search_call",
                "status": "completed",
                "action": {"type": "search", "query": "Codex docs"},
            },
        }) + "\n")
        events = list(process_file(path, "s1", "/p", {}))
        assert len(events) == 1
        assert events[0]["event_type"] == "tool_call"
        assert events[0]["tool_name"] == "web_search"
        assert json.loads(events[0]["tool_input"]) == {
            "type": "search",
            "query": "Codex docs",
        }
        assert json.loads(events[0]["metadata"]) == {"status": "completed"}

    def test_skips_non_message_response_item(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"response_item","payload":{"type":"other","role":"user"}}\n')
            path = Path(f.name)
        try:
            events = list(process_file(path, "s1", "/p", {}))
            assert len(events) == 0
        finally:
            path.unlink()

    def test_event_msg_token_count_skipped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"event_msg","payload":{"type":"token_count"}}\n')
            path = Path(f.name)
        try:
            events = list(process_file(path, "s1", "/p", {}))
            assert len(events) == 0
        finally:
            path.unlink()

    def test_event_msg_user_message_is_duplicate_notification(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"event_msg","payload":{"type":"user_message","info":"note"}}\n')
            path = Path(f.name)
        try:
            events = list(process_file(path, "s1", "/p", {}))
            assert events == []
        finally:
            path.unlink()

    def test_turn_aborted_is_sanitized_and_redacted(self, tmp_path):
        path = tmp_path / "session.jsonl"
        path.write_text(
            '{"type":"event_msg","payload":{"type":"turn_aborted",'
            '"reason":"safe\\u0000 sk-abcdefghij1234567890xyz"}}\n'
        )
        events = list(process_file(path, "s1", "/p", {"redact": True}))
        assert events[0]["content"] == "safe [REDACTED]"
        assert events[0]["subtype"] == "truncated"

    def test_slash_command(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"/fix"}]}}\n')
            path = Path(f.name)
        try:
            events = list(process_file(path, "s1", "/p", {}))
            assert events[0]["subtype"] == "slash_command"
        finally:
            path.unlink()

    def test_redaction_disables_raw_debug_capture(self, tmp_path):
        path = tmp_path / "session.jsonl"
        path.write_text(
            '{"type":"response_item","payload":{"type":"message","role":"user",'
            '"content":[{"type":"input_text","text":"secret"}]}}\n'
        )
        events = list(
            process_file(path, "s1", "/p", {"debug": True, "redact": True})
        )
        assert events
        assert all(event["source_raw"] is None for event in events)
