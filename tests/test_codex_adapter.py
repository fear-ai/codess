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
    event = next(iter(process_file(path, "s1", "/p", {})))
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
            # `originator` is retained as source evidence and also mapped to
            # the common column, so a reader sees both what Codex said and
            # what it was normalized to.
            "harness_name": "codex_cli_rs",
        }


class TestObservedHarness:
    """Codex reports its harness and surface; the profile constant hid them.

    `store.SOURCE_PROFILES` supplies one constant per vendor, correct for
    Claude and Cursor because neither names its harness in a Session. Codex
    does, and storing the constant recorded a Desktop or VS Code Session as
    CLI.
    """

    def _metadata(self, tmp_path, payload):
        path = tmp_path / "rollout.jsonl"
        path.write_text(json.dumps({
            "type": "session_meta",
            "payload": {"id": "a", "cwd": "/x", **payload},
        }) + "\n")
        return get_session_metadata(path)

    @pytest.mark.parametrize(
        ("originator", "source", "harness", "surface"),
        [
            ("codex_cli_rs", "cli", "codex_cli_rs", "cli"),
            ("Codex Desktop", "vscode", "Codex Desktop", "ide"),
            ("codex-tui", "cli", "codex-tui", "cli"),
            ("codex_exec", "exec", "codex_exec", "cli"),
        ],
    )
    def test_observed(self, tmp_path, originator, source, harness, surface):
        values = self._metadata(
            tmp_path, {"originator": originator, "source": source},
        )
        assert values["harness_name"] == harness
        assert values["surface_kind"] == surface

    def test_unknown_surface(self, tmp_path):
        """Unmapped surfaces stay absent; the profile default is a guess."""
        values = self._metadata(
            tmp_path, {"originator": "codex_cli_rs", "source": "hologram"},
        )
        assert "surface_kind" not in values
        assert values["harness_name"] == "codex_cli_rs"

    def test_absent(self, tmp_path):
        values = self._metadata(tmp_path, {"cli_version": "1.0"})
        assert "harness_name" not in values
        assert "surface_kind" not in values


class TestProcessFile:
    def test_explicit_compaction_preserves_bounded_encrypted_summary(
        self, tmp_path
    ):
        path = tmp_path / "rollout.jsonl"
        records = [
            {
                "timestamp": "2026-07-10T00:00:00Z",
                "type": "compacted",
                "payload": {
                    "message": "",
                    "replacement_history": [
                        {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "repeat"}],
                        },
                        {
                            "type": "compaction",
                            "encrypted_content": "encrypted-summary-body",
                            "id": "compact-1",
                        },
                    ],
                    "window_number": 3,
                    "window_id": "window-3",
                },
            },
            {
                "timestamp": "2026-07-10T00:00:00Z",
                "type": "event_msg",
                "payload": {"type": "context_compacted"},
            },
        ]
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records)
        )
        diagnostics = {}
        events = list(process_file(
            path, "s1", "/p", {
                "diagnostics": diagnostics,
                "max_context_content_chars": 10,
            },
        ))
        assert len(events) == 1
        event = events[0]
        assert event["subtype"] == "context_compaction"
        assert event["content"] == "encrypted…"
        assert event["content_len"] == len("encrypted-summary-body")
        assert event["mapping_rule"] == "codex.compaction"
        metadata = json.loads(event["metadata"])
        assert metadata["content_encoding"] == "vendor_encrypted"
        assert metadata["replacement_history_items"] == 2
        assert metadata["replacement_history_messages_not_duplicated"] == 1
        assert metadata["window_number"] == 3
        assert diagnostics["known_ignored_records"] == 1

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

    def test_user_role_is_partitioned_by_direct_submission_evidence(
        self, tmp_path
    ):
        path = tmp_path / "rollout.jsonl"
        records = [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "direct request"}
                    ],
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "user_message",
                    "message": "direct request",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "<environment_context>injected"
                                "</environment_context>"
                            ),
                        }
                    ],
                },
            },
        ]
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records)
        )
        diagnostics = {}
        events = list(process_file(
            path, "s1", "/p", {"diagnostics": diagnostics}
        ))
        assert [(event["event_kind"], event["actor_kind"]) for event in events] == [
            ("message.prompt", "human"),
            ("message.context", "harness"),
        ]
        assert json.loads(events[0]["metadata"])["actor_evidence"] == (
            "event_msg.user_message"
        )
        context_metadata = json.loads(events[1]["metadata"])
        assert context_metadata["source_role"] == "user"
        assert context_metadata["actor_evidence"] == (
            "unpaired_response_item_user_role"
        )
        assert diagnostics["direct_user_message_records"] == 1
        assert diagnostics["harness_user_role_context_records"] == 1

    def test_assistant_message_retains_source_role_and_actor_evidence(
        self, tmp_path
    ):
        path = tmp_path / "rollout.jsonl"
        path.write_text(json.dumps({
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "response"}],
            },
        }) + "\n")
        event = next(iter(process_file(path, "s1", "/p", {})))
        assert event["actor_kind"] == "model"
        metadata = json.loads(event["metadata"])
        assert metadata["source_role"] == "assistant"
        assert metadata["actor_evidence"] == (
            "response_item_assistant_role"
        )
        assert metadata["content_truncated"] is False

    def test_legacy_user_role_without_notifications_remains_human(
        self, tmp_path
    ):
        path = tmp_path / "rollout.jsonl"
        path.write_text(json.dumps({
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "legacy"}],
            },
        }) + "\n")
        event = next(iter(process_file(path, "s1", "/p", {})))
        assert event["actor_kind"] == "human"
        assert json.loads(event["metadata"])["actor_evidence"] == (
            "legacy_user_role_fallback"
        )

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

    def test_subagent_session_metadata_preserves_direct_lineage(
        self, tmp_path
    ):
        path = tmp_path / "rollout.jsonl"
        path.write_text(json.dumps({
            "type": "session_meta",
            "payload": {
                "id": "child-thread",
                "cwd": "/project",
                "source": {
                    "subagent": {
                        "thread_spawn": {
                            "parent_thread_id": "parent-thread",
                            "depth": 1,
                        }
                    }
                },
                "thread_source": "subagent",
                "parent_thread_id": "parent-thread",
                "agent_nickname": "researcher",
                "agent_role": "explorer",
                "agent_path": "1",
            },
        }) + "\n")
        metadata = get_session_metadata(path)
        assert metadata["parent_session_id"] == "parent-thread"
        assert metadata["session_relation_kind"] == "subagent"
        assert metadata["lineage_provenance"] == (
            "session_meta.parent_thread_id"
        )
        assert metadata["agent_nickname"] == "researcher"
        assert metadata["agent_role"] == "explorer"
        assert metadata["agent_path"] == "1"

    def test_forked_session_metadata_is_not_misclassified_as_subagent(
        self, tmp_path
    ):
        path = tmp_path / "rollout.jsonl"
        path.write_text(json.dumps({
            "type": "session_meta",
            "payload": {
                "id": "fork", "cwd": "/project", "source": "vscode",
                "thread_source": "user", "forked_from_id": "original",
            },
        }) + "\n")
        metadata = get_session_metadata(path)
        assert metadata["parent_session_id"] == "original"
        assert metadata["session_relation_kind"] == "fork"

    def test_collaboration_events_preserve_participants_and_prompt(
        self, tmp_path
    ):
        path = tmp_path / "rollout.jsonl"
        records = [
            {
                "type": "event_msg",
                "payload": {
                    "type": "collab_agent_spawn_begin",
                    "call_id": "spawn-1",
                    "sender_thread_id": "parent",
                    "prompt": "Investigate the parser",
                    "model": "gpt-5",
                    "reasoning_effort": "high",
                    "started_at_ms": 123,
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "collab_agent_spawn_end",
                    "call_id": "spawn-1",
                    "sender_thread_id": "parent",
                    "new_thread_id": "child",
                    "new_agent_nickname": "researcher",
                    "new_agent_role": "explorer",
                    "status": "completed",
                    "prompt": "Investigate the parser",
                    "model": "gpt-5",
                    "reasoning_effort": "high",
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "sub_agent_activity",
                    "event_id": "activity-1",
                    "agent_thread_id": "child",
                    "agent_path": "1",
                    "kind": "started",
                    "occurred_at_ms": 124,
                },
            },
        ]
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records)
        )
        begin, end, activity = list(
            process_file(path, "parent", "/project", {})
        )
        assert begin["event_kind"] == "collaboration.spawn.begin"
        assert begin["actor_kind"] == "harness"
        assert begin["content_role"] == "delegated_task"
        assert begin["content"] == "Investigate the parser"
        assert begin["mapping_rule"] == "codex.collaboration"
        end_metadata = json.loads(end["metadata"])
        assert end_metadata["new_thread_id"] == "child"
        assert end_metadata["new_agent_role"] == "explorer"
        assert activity["subtype"] == "subagent_activity"
        assert json.loads(activity["metadata"])["agent_path"] == "1"

    def test_tool_search_and_mcp_transport_are_preserved(self, tmp_path):
        path = tmp_path / "rollout.jsonl"
        records = [
            {
                "type": "response_item",
                "payload": {
                    "type": "tool_search_call",
                    "call_id": "search-1",
                    "status": "completed",
                    "execution": "server",
                    "arguments": {"query": "github issue search"},
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "tool_search_output",
                    "call_id": "search-1",
                    "status": "completed",
                    "execution": "server",
                    "tools": [{"name": "github.search_issues"}],
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "mcp_tool_call_end",
                    "call_id": "mcp-1",
                    "invocation": {
                        "server": "codex_apps",
                        "tool": "github.search_issues",
                        "arguments": {"query": "CodexBar"},
                    },
                    "connector_id": "connector-1",
                    "app_name": "GitHub",
                    "action_name": "search_issues",
                    "duration": {"secs": 2, "nanos": 500_000_000},
                    "result": {"Ok": {"content": []}},
                },
            },
        ]
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records)
        )
        events = list(process_file(path, "s1", "/p", {}))
        assert [event["event_kind"] for event in events] == [
            "tool.call", "tool.result", "tool.transport",
        ]
        assert [event["actor_kind"] for event in events] == [
            "model", "harness", "harness",
        ]
        assert json.loads(events[0]["tool_input"]) == {
            "query": "github issue search"
        }
        assert events[1]["tool_name"] == "tool_search"
        transport = events[2]
        assert transport["tool_name"] == "github.search_issues"
        metadata = json.loads(transport["metadata"])
        assert metadata["mcp_server"] == "codex_apps"
        assert metadata["connector_id"] == "connector-1"
        assert metadata["duration_ms"] == 2500.0
        assert metadata["result_status"] == "succeeded"
        assert transport["normalized_status"] == "succeeded"

    def test_mcp_transport_success_preserves_application_failure(
        self, tmp_path
    ):
        path = tmp_path / "rollout.jsonl"
        records = [
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "github.search_issues",
                    "arguments": '{"query":"bad"}',
                    "call_id": "mcp-1",
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "mcp_tool_call_end",
                    "call_id": "mcp-1",
                    "invocation": {
                        "server": "codex_apps",
                        "tool": "github.search_issues",
                    },
                    "result": {"Ok": {"content": []}},
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "mcp-1",
                    "output": json.dumps({
                        "error": "GitHub API error: Validation Failed",
                    }),
                },
            },
        ]
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records)
        )
        call, transport, result = list(
            process_file(path, "s1", "/p", {})
        )
        assert call["tool_name"] == "github.search_issues"
        assert transport["normalized_status"] == "succeeded"
        transport_metadata = json.loads(transport["metadata"])
        assert transport_metadata["transport_status"] == "succeeded"
        assert transport_metadata["application_status"] == "failed"
        assert result["subtype"] == "tool_failure"
        assert result["source_status"] == "application_error"
        assert result["normalized_status"] == "failed"

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
            diagnostics = {}
            events = list(process_file(
                path, "s1", "/p", {"diagnostics": diagnostics}
            ))
            assert len(events) == 0
            assert diagnostics["usage_records"] == 1
            assert diagnostics["known_ignored_records"] == 1
        finally:
            path.unlink()

    def test_event_msg_user_message_is_duplicate_notification(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"event_msg","payload":{"type":"user_message","info":"note"}}\n')
            path = Path(f.name)
        try:
            diagnostics = {}
            events = list(process_file(
                path, "s1", "/p", {"diagnostics": diagnostics}
            ))
            assert events == []
            assert diagnostics["duplicate_envelope_records"] == 1
        finally:
            path.unlink()

    def test_thread_rollback_is_preserved_as_context_lifecycle(self, tmp_path):
        path = tmp_path / "rollout.jsonl"
        path.write_text(json.dumps({
            "type": "event_msg",
            "payload": {
                "type": "thread_rolled_back",
                "num_turns": 2,
            },
        }) + "\n")
        event = next(iter(process_file(path, "s1", "/p", {})))
        assert event["event_kind"] == "context.rollback"
        assert event["actor_kind"] == "harness"
        assert json.loads(event["metadata"]) == {"removed_user_turns": 2}

    def test_reasoning_summary_is_retained_without_encrypted_state(
        self, tmp_path
    ):
        path = tmp_path / "session.jsonl"
        path.write_text(json.dumps({
            "type": "response_item",
            "payload": {
                "type": "reasoning",
                "summary": [
                    {"type": "summary_text", "text": "Checking the schema"},
                    {"type": "summary_text", "text": "Planning validation"},
                ],
                "encrypted_content": "opaque-private-state",
            },
        }) + "\n")
        diagnostics = {}
        events = list(process_file(
            path, "s1", "/p", {"diagnostics": diagnostics}
        ))
        assert len(events) == 1
        assert events[0]["subtype"] == "reasoning_summary"
        assert events[0]["event_kind"] == "message.reasoning_summary"
        assert events[0]["content"] == (
            "Checking the schema\nPlanning validation"
        )
        assert "opaque-private-state" not in events[0]["content"]
        assert diagnostics["reasoning_summary_records"] == 1

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
        # Codex states the tier the client requested; Claude states the tier the API
        # served. The provenance keeps Codex's exact field name either way.
        assert metadata["request_tier"] == "priority"
        assert "service_tier" not in metadata
        assert metadata["mode"] == "default"
        assert metadata["configuration_provenance"]["request_tier"] == {
            "source_record_type": "thread_settings_applied",
            "source_record_locator": "1",
            "source_field": "payload.thread_settings.service_tier",
        }
        assert metadata["configuration_provenance"]["reasoning_effort"][
            "source_record_locator"
        ] == "2"


def test_hostile_codex_fields_are_diagnosed_and_other_records_survive(tmp_path):
    path = tmp_path / "session.jsonl"
    records = [
        {"type": "response_item", "payload": ["invalid-envelope"]},
        {"type": "response_item", "payload": {
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "keep prompt"}],
        }},
        {"type": "response_item", "payload": {
            "type": "function_call", "name": "read_file",
            "call_id": "call-1", "arguments": None,
        }},
    ]
    path.write_text("".join(json.dumps(item) + "\n" for item in records))
    diagnostics = {}
    events = list(process_file(
        path, "s1", "/project", {"diagnostics": diagnostics}
    ))
    assert diagnostics["malformed_records"] == 1
    assert [event["event_type"] for event in events] == [
        "user_message", "tool_call",
    ]
    prompt_rows = events[0]["field_diagnostics"]
    assert any(
        row["source_field"] == "payload.origin"
        and row["reason_code"] == "field_absent"
        for row in prompt_rows
    )
    tool_rows = events[1]["field_diagnostics"]
    assert any(
        row["source_field"] == "payload.arguments"
        and row["reason_code"] == "field_null"
        for row in tool_rows
    )


class TestPatchedFile:
    """`apply_patch` is the only Codex call that names a file.

    Codex passes no path as a tool argument -- `exec_command` carries a shell
    string, `apply_patch` an envelope -- so `events.file_path` was null for
    every Codex Event while 4,639 real `apply_patch` calls named 5,722 file
    operations in their envelope headers.
    """

    def _call(self, tmp_path, name, arguments):
        path = tmp_path / "rollout.jsonl"
        path.write_text(json.dumps({
            "timestamp": "2026-07-10T00:00:00Z",
            "type": "response_item",
            "payload": {
                "type": "function_call", "name": name,
                "call_id": "c1", "arguments": arguments,
            },
        }) + "\n")
        calls = [
            event for event in process_file(path, "s1", "/p", {})
            if event.get("event_type") == "tool_call"
        ]
        assert len(calls) == 1
        return calls[0]

    @pytest.mark.parametrize(
        ("operation", "expected"),
        [
            ("Add File: new/module.py", "new/module.py"),
            ("Update File: src/existing.py", "src/existing.py"),
            ("Delete File: old/gone.py", "old/gone.py"),
        ],
    )
    def test_operations(self, tmp_path, operation, expected):
        patch = f"*** Begin Patch\n*** {operation}\n+body\n*** End Patch"
        event = self._call(
            tmp_path, "apply_patch", json.dumps({"input": patch}),
        )
        assert event["file_path"] == expected

    def test_first_of_several(self, tmp_path):
        """One column, so the first path; `tool_input` retains them all."""
        patch = (
            "*** Begin Patch\n*** Update File: first.py\n+a\n"
            "*** Update File: second.py\n+b\n*** End Patch"
        )
        event = self._call(
            tmp_path, "apply_patch", json.dumps({"input": patch}),
        )
        assert event["file_path"] == "first.py"
        assert "second.py" in event["tool_input"]

    def test_other_tools(self, tmp_path):
        """A shell command naming a file is not a file operation."""
        event = self._call(
            tmp_path, "exec_command",
            json.dumps({"cmd": "cat src/thing.py"}),
        )
        assert event["file_path"] is None

    def test_malformed_envelope(self, tmp_path):
        event = self._call(
            tmp_path, "apply_patch", "not json at all",
        )
        assert event["file_path"] is None


class TestExitCodeStatus:
    """Codex reports outcomes as an exit code inside the output body.

    Most `function_call_output` records carry no `status` field, so 26,917 of
    30,415 real results had neither a source nor a normalized outcome. The
    exit code is there but embedded as JSON in text, which no field read
    reaches.
    """

    def _result(self, tmp_path, output):
        path = tmp_path / "rollout.jsonl"
        path.write_text(json.dumps({
            "timestamp": "2026-07-10T00:00:00Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output", "call_id": "c1",
                "output": output,
            },
        }) + "\n")
        results = [
            event for event in process_file(path, "s1", "/p", {})
            if event.get("subtype") == "tool_result"
        ]
        assert len(results) == 1
        return results[0]

    def test_zero_exit_code(self, tmp_path):
        event = self._result(
            tmp_path, '[{"text": "{\\"exit_code\\":0,\\"output\\":\\"ok\\"}"}]',
        )
        assert event["source_status"] == "exit_code:0"

    def test_nonzero_exit_code(self, tmp_path):
        event = self._result(
            tmp_path, '[{"text": "{\\"exit_code\\":2,\\"output\\":\\"bad\\"}"}]',
        )
        assert event["source_status"] == "exit_code:2"

    def test_no_exit_code_stays_unknown(self, tmp_path):
        """Codex did not say, so neither does the store."""
        event = self._result(tmp_path, "plain output with no code")
        assert event["source_status"] is None


class TestSessionProvider:
    """Codex states provider and model on different records."""

    def decode(self, tmp_path, *records):
        path = tmp_path / "rollout.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in records))
        return list(process_file(path, "s1", "/p", {}))

    def meta(self, **payload):
        return {
            "timestamp": "2026-07-10T00:00:00Z", "type": "session_meta",
            "payload": {"id": "s1", "cwd": "/p", **payload},
        }

    def turn(self, **payload):
        return {
            "timestamp": "2026-07-10T00:00:01Z", "type": "turn_context",
            "payload": payload,
        }

    def message(self):
        return {
            "timestamp": "2026-07-10T00:00:02Z", "type": "response_item",
            "payload": {
                "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": "hello"}],
            },
        }

    def configured(self, events):
        for event in events:
            metadata = json.loads(event.get("metadata") or "{}")
            if "model" in metadata:
                return metadata
        return {}

    def test_provider_reaches_turn(self, tmp_path):
        """`model_provider` is on `session_meta` and `model` on `turn_context`, so
        reading one record at a time never saw both."""
        events = self.decode(
            tmp_path,
            self.meta(model_provider="openai"),
            self.turn(model="gpt-5.6-sol", effort="high"),
            self.message(),
        )
        metadata = self.configured(events)
        assert metadata["model"] == "gpt-5.6-sol"
        assert metadata["model_provider"] == "openai"
        assert metadata["reasoning_effort"] == "high"

    def test_provider_absent(self, tmp_path):
        """A Session stating no provider records none rather than a guess."""
        events = self.decode(
            tmp_path, self.meta(), self.turn(model="gpt-5.6-sol"),
            self.message(),
        )
        metadata = self.configured(events)
        assert metadata["model"] == "gpt-5.6-sol"
        assert "model_provider" not in metadata

    def test_turn_provider_precedence(self, tmp_path):
        """A provider stated on the turn describes that turn, so it wins over the
        Session-level one it would otherwise inherit."""
        events = self.decode(
            tmp_path,
            self.meta(model_provider="openai"),
            self.turn(model="local", model_provider="ollama"),
            self.message(),
        )
        assert self.configured(events)["model_provider"] == "ollama"


class TestDecodedOutput:
    """Codex states a header of facts before `Output:`, in several spellings."""

    def test_exit_code_spellings(self):
        """`Process exited with code N` appears on 14,795 results and
        `Exit code: N` on 1,319; both state the same fact."""
        from codess.adapters.codex import _decoded_output

        a = _decoded_output("Exit code: 0\nWall time: 0.1 seconds\nOutput:\ndb.out")
        b = _decoded_output(
            "Wall time: 0.1 seconds\nProcess exited with code 0\nOutput:\ndb.out"
        )
        assert a["exit_code"] == b["exit_code"] == 0
        assert a["output"] == b["output"] == "db.out"

    def test_all_fields(self):
        from codess.adapters.codex import _decoded_output

        decoded = _decoded_output(
            "Chunk ID: 112967\nWall time: 0.1578 seconds\n"
            "Process exited with code 0\nOriginal token count: 16\nOutput:\nx"
        )
        assert decoded == {
            "chunk_id": "112967", "wall_seconds": 0.1578,
            "exit_code": 0, "output_tokens": 16, "output": "x",
        }

    def test_script_completed(self):
        """A script that ran to completion without a stated code is not the same
        fact as `exit_code: 0`, so it is its own marker."""
        from codess.adapters.codex import _decoded_output

        decoded = _decoded_output("Script completed\nWall time 15.4 seconds\nOutput:\n")
        assert decoded["script_completed"] is True
        assert "exit_code" not in decoded

    def test_envelope_and_list_transports(self):
        """Three transports carry the same payload; one header decode serves all."""
        import json as _json

        from codess.adapters.codex import _decoded_output

        body = "Exit code: 2\nWall time: 1.5 seconds\nOutput:\nboom"
        envelope = _json.dumps({"output": body})
        blocks = [{"type": "input_text", "text": body}]
        for value in (body, envelope, blocks):
            assert _decoded_output(value)["exit_code"] == 2

    def test_no_header(self):
        from codess.adapters.codex import _decoded_output

        assert _decoded_output("exec command rejected by user") is None

    def test_output_marker_in_body_only(self):
        """An unrecognized line before the marker means it was body text, so
        nothing is claimed rather than half a header."""
        from codess.adapters.codex import _decoded_output

        assert _decoded_output("here is what I found\nOutput:\nstuff") is None


class TestBoundedContent:
    """One helper for the process/bound/process sequence (W42).

    Every content-bearing branch repeated five steps, and twenty of
    `process_file`'s branches were the two `None` guards rather than record
    dispatch -- so the function's shape said "many kinds of record" where it
    mostly said "one policy applied many times".
    """

    def test_absent_text_is_dropped(self):
        from codess.adapters.codex import _bounded_content

        assert _bounded_content(
            None, {"redact": False}, record_type="r",
            event_kind="message.response", limit=100,
        ) is None

    def test_content_within_the_limit_is_returned_whole(self):
        from codess.adapters.codex import _bounded_content

        bounded = _bounded_content(
            "short", {"redact": False}, record_type="r",
            event_kind="message.response", limit=100,
        )
        assert bounded == ("short", 5)

    def test_the_original_length_survives_truncation(self):
        """The stored length describes the source, not the stored text.

        A reader comparing `content_len` against the content sees that it was
        bounded; reporting the truncated length would hide it.
        """
        from codess.adapters.codex import _bounded_content

        content, original = _bounded_content(
            "x" * 50, {"redact": False}, record_type="r",
            event_kind="message.response", limit=10,
        )
        assert original == 50
        assert len(content) == 10
        assert content.endswith("…")

    def test_a_policy_drop_at_either_phase_skips_the_record(self, monkeypatch):
        """Both phases can refuse, and both mean the same to the caller."""
        import codess.adapters.codex as codex

        for dropped_phase in ("pre", "post"):
            monkeypatch.setattr(
                codex, "apply_processing",
                lambda text, opts, *, phase, **kw: (
                    None if phase == dropped_phase else text
                ),
            )
            assert codex._bounded_content(
                "text", {"redact": False}, record_type="r",
                event_kind="message.response", limit=100,
            ) is None, f"a drop at the {dropped_phase} phase must skip the record"
