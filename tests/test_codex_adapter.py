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
from codess.schema_contract import validate_mapped_event


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


def test_codex_events_carry_declared_exact_mapping_evidence(tmp_path):
    path = tmp_path / "session.jsonl"
    path.write_text(json.dumps({
        "type": "response_item", "payload": {
            "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "hi"}],
        },
    }) + "\n", encoding="utf-8")
    event = list(process_file(path, "s1", "/p", {}))[0]
    assert event["source_record_type"] == "response_item"
    assert event["source_record_subtype"] == "message"
    assert validate_mapped_event("codex", event) == []


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
    def test_modern_fixture_contract(self, tmp_path):
        fixture = Path(__file__).parent / "fixtures" / "codex_modern.jsonl"
        project = tmp_path / "project"
        project.mkdir()
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            fixture.read_text().replace("__PROJECT__", str(project))
        )
        session_id, cwd = get_session_meta(path)
        events = list(process_file(path, session_id, cwd, {}))
        assert session_id == "codex-modern"
        assert len(events) == 8
        assert [event["event_type"] for event in events].count("tool_call") == 3
        assert [event["subtype"] for event in events].count("tool_result") == 2
        assert {event["tool_name"] for event in events if event["tool_name"]} == {
            "shell", "apply_patch", "web_search"
        }
        assert all(event["timestamp"] is not None for event in events)

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
        assert events[0]["subtype"] == "turn_aborted"

    def test_audit_fixture_contract(self, tmp_path):
        fixture = Path(__file__).parent / "fixtures" / "codex_audit.jsonl"
        project = tmp_path / "project"
        project.mkdir()
        path = tmp_path / "rollout.jsonl"
        path.write_text(fixture.read_text().replace("__PROJECT__", str(project)))
        events = list(process_file(path, "codex-audit", str(project), {}))
        assert [event["subtype"] for event in events] == [
            "tool_failure", "turn_aborted"
        ]
        assert json.loads(events[0]["metadata"])["status"] == "failed"

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

    def test_turn_settings_are_attached_with_field_provenance(self, tmp_path):
        path = tmp_path / "session.jsonl"
        records = [
            {"type": "event_msg", "payload": {
                "type": "thread_settings_applied", "thread_settings": {
                    "model": "gpt-test", "model_provider_id": "openai",
                    "reasoning_effort": "medium", "service_tier": "priority",
                    "approval_policy": "on-request",
                    "collaboration_mode": {"mode": "default"},
                },
            }},
            {"type": "turn_context", "payload": {
                "model": "gpt-test", "effort": "high",
            }},
            {"type": "response_item", "payload": {
                "type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            }},
            {"type": "response_item", "payload": {
                "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": "hi"}],
            }},
        ]
        path.write_text("".join(json.dumps(item) + "\n" for item in records))
        diagnostics = {}
        events = list(process_file(
            path, "s1", "/p", {"diagnostics": diagnostics}
        ))
        metadata = json.loads(events[0]["metadata"])
        assert diagnostics["configuration_records"] == 2
        assert metadata["model"] == "gpt-test"
        assert metadata["reasoning_effort"] == "high"
        assert metadata["service_tier"] == "priority"
        assert metadata["mode"] == "default"
        assert metadata["configuration_provenance"]["service_tier"] == {
            "source_record_type": "thread_settings_applied",
            "source_record_locator": "1",
            "source_field": "payload.thread_settings.service_tier",
        }
        assert metadata["configuration_provenance"]["reasoning_effort"][
            "source_record_locator"
        ] == "2"
