"""Codex JSONL parser and normalizer."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from codess import field_state
from codess.config import TRUNCATE_PROMPT, TRUNCATE_RESPONSE, TRUNCATE_TOOL_RESULT
from codess.context_content import bound_context_content
from codess.sanitize import sanitize_value
from codess.content_processing import apply_processing
from codess.mapping import annotate_mapping

log = logging.getLogger(__name__)


def iter_codex_records(
    path: Path,
    diagnostics: dict[str, int] | None = None,
    *,
    warn: bool = True,
) -> Iterator[tuple[int, dict, str]]:
    """Stream JSONL; yield (line_num, record, raw_line). Skip empty; on JSON error log and skip."""
    with path.open(encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            raw = line
            line = line.rstrip("\n\r")
            if not line:
                continue
            try:
                record = json.loads(line)
                yield line_num, record, raw
            except json.JSONDecodeError as e:
                if diagnostics is not None:
                    diagnostics["malformed_records"] = (
                        diagnostics.get("malformed_records", 0) + 1
                    )
                if warn:
                    log.warning("JSON error at %s:%d: %s", path, line_num, e)
                continue


def get_session_meta(path: Path) -> tuple[str, str]:
    """Return (session_id, project_path) from first session_meta. Fallback to filename stem and '.'."""
    for _line_num, record, _ in iter_codex_records(path, warn=False):
        if record.get("type") == "session_meta":
            payload = record.get("payload") or {}
            sid = payload.get("id")
            cwd = payload.get("cwd")
            return (
                str(sid) if sid else path.stem,
                str(cwd) if cwd else ".",
            )
    return path.stem, "."


def get_session_metadata(path: Path) -> dict:
    """Return useful, bounded session-level metadata from session_meta."""
    for _line_num, record, _ in iter_codex_records(path, warn=False):
        if record.get("type") != "session_meta":
            continue
        payload = record.get("payload") or {}
        return {
            key: payload[key]
            for key in ("cli_version", "model_provider", "originator", "source")
            if payload.get(key) is not None
        }
    return {}


def _parse_timestamp(value) -> float | None:
    """Normalize Unix seconds/ms or ISO-8601 to Unix milliseconds."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number * 1000 if number < 1e12 else number
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() * 1000
    return None


def _extract_text_from_content(content: list) -> str:
    """Extract text from Codex content blocks (input_text, etc.)."""
    if not content:
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "input_text":
            parts.append(block.get("text", ""))
        elif "text" in block:
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def _extract_reasoning_summary(summary) -> str:
    """Extract vendor-exposed summary text, never encrypted reasoning state."""
    if not isinstance(summary, list):
        return ""
    parts = []
    for item in summary:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(part for part in parts if part)


def _build_call_map(path: Path) -> dict[str, str]:
    """Map tool call ids to names so later output records retain identity."""
    calls = {}
    for _line_num, record, _raw in iter_codex_records(path, warn=False):
        if record.get("type") != "response_item":
            continue
        payload = record.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("type") not in ("function_call", "custom_tool_call"):
            continue
        call_id = payload.get("call_id")
        name = payload.get("name")
        if call_id and name:
            calls[str(call_id)] = str(name)
    return calls


def _tool_input(payload: dict, redact_enabled: bool) -> str | None:
    """Normalize function/custom tool input to a JSON value."""
    field = "arguments" if payload.get("type") == "function_call" else "input"
    raw = payload.get(field)
    if raw is None:
        return None
    value = raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = {field: raw}
    value = sanitize_value(value, redact_enabled)
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _metadata(payload: dict) -> str | None:
    values = {
        key: payload[key]
        for key in ("call_id", "status")
        if payload.get(key) is not None
    }
    return json.dumps(values, separators=(",", ":")) if values else None


def _configuration_values(
    record_type: str,
    payload: dict,
    line_num: int,
) -> dict:
    """Extract only settings whose Codex field semantics were verified."""
    source = payload
    prefix = "payload"
    if record_type == "thread_settings_applied":
        source = payload.get("thread_settings") or {}
        prefix = "payload.thread_settings"
    if not isinstance(source, dict):
        return {}
    values = {}
    provenance = {}

    def keep(common: str, source_field: str, value) -> None:
        if value is None or isinstance(value, (dict, list)):
            return
        text = str(value).strip()
        if text:
            values[common] = text
            provenance[common] = {
                "source_record_type": record_type,
                "source_record_locator": str(line_num),
                "source_field": f"{prefix}.{source_field}",
            }

    keep("model", "model", source.get("model"))
    keep(
        "model_provider",
        "model_provider_id" if "model_provider_id" in source else "model_provider",
        source.get("model_provider_id") or source.get("model_provider"),
    )
    keep(
        "reasoning_effort",
        "reasoning_effort" if "reasoning_effort" in source else "effort",
        source.get("reasoning_effort") or source.get("effort"),
    )
    keep("service_tier", "service_tier", source.get("service_tier"))
    collaboration = source.get("collaboration_mode")
    if isinstance(collaboration, dict):
        keep("mode", "collaboration_mode.mode", collaboration.get("mode"))
        keep(
            "collaboration_mode_kind",
            "collaboration_mode.kind",
            collaboration.get("kind"),
        )
    keep("approval_policy", "approval_policy", source.get("approval_policy"))
    if source.get("turn_id") is not None:
        values["source_turn_id"] = str(source["turn_id"])
    if values:
        values["configuration_provenance"] = provenance
    return values


def _mapping_rule(event: dict) -> str:
    if event.get("subtype") == "context_compaction":
        return "codex.compaction"
    if event.get("subtype") == "context_injection":
        return "codex.context-injection"
    if event.get("subtype") in {"task_started", "task_complete"}:
        return "codex.task-lifecycle"
    if event.get("subtype") == "reasoning_summary":
        return "codex.reasoning-summary"
    if event.get("event_type") == "tool_call":
        return "codex.tool-call"
    if event.get("subtype") == "tool_result":
        return "codex.tool-result"
    if event.get("subtype") == "turn_aborted":
        return "codex.abort"
    return "codex.message"


def _annotate_source(
    event: dict, record_type: str, payload: dict, line_num: int,
) -> dict:
    event = dict(event)
    source_path = event.pop("_source_path", "$.payload")
    rule = _mapping_rule(event)
    applied = [rule]
    if event.get("metadata") and record_type == "response_item":
        applied.append("codex.configuration")
    if event.get("actor_kind") == "model" or event.get("role") == "assistant":
        metadata = event.get("metadata")
        try:
            configuration = json.loads(metadata) if metadata else {}
        except (TypeError, json.JSONDecodeError):
            configuration = {}
        model, state = field_state.get_state(configuration, "model")
        field_state.attach(
            event, field="model", state=state,
            source_field="effective_configuration.model", value=model,
        )
    if event.get("event_type") == "user_message":
        field_state.attach(
            event, field="prompt_origin", state=field_state.ABSENT,
            source_field="payload.origin",
        )
    if event.get("event_type") == "tool_call":
        input_field = (
            "arguments"
            if payload.get("type") == "function_call" else "input"
        )
        value, state = field_state.get_state(payload, input_field)
        field_state.attach(
            event, field="tool_input", state=state,
            source_field=f"payload.{input_field}", value=value,
        )
    return annotate_mapping(
        event,
        source_record_type=record_type,
        source_record_subtype=(
            str(payload["type"]) if payload.get("type") is not None else None
        ),
        source_record_locator=str(line_num),
        mapping_rule=rule,
        source_path=source_path,
        applied_rules=applied,
    )


def _update_configuration(current: dict, observed: dict) -> None:
    provenance = dict(current.get("configuration_provenance") or {})
    provenance.update(observed.get("configuration_provenance") or {})
    current.update({
        key: value for key, value in observed.items()
        if key != "configuration_provenance"
    })
    if provenance:
        current["configuration_provenance"] = provenance


def _merge_metadata(payload: dict, configuration: dict) -> str | None:
    values = json.loads(_metadata(payload) or "{}")
    values.update(configuration)
    return json.dumps(values, separators=(",", ":")) if values else None


def _failed_status(payload: dict) -> bool:
    return str(payload.get("status") or "").lower() in {
        "failed", "failure", "error", "incomplete",
    }


def _compaction_events(
    payload: dict,
    *,
    session_id: str,
    source_file: str,
    line_num: int,
    timestamp: float | None,
    source_raw: bytes | None,
    opts: dict,
) -> Iterator[dict]:
    """Map each explicit encrypted Codex compaction summary once.

    ``replacement_history`` reconstructs a context window and repeats ordinary
    transcript messages.  Only its dedicated ``type=compaction`` item is new
    compaction communication; copying the rest would multiply large messages.
    """
    history = payload.get("replacement_history")
    if not isinstance(history, list):
        history = []
    summaries = [
        (index, item)
        for index, item in enumerate(history)
        if isinstance(item, dict) and item.get("type") == "compaction"
    ]
    if not summaries:
        summaries = [(-1, {})]
    for emitted_index, (history_index, item) in enumerate(summaries):
        encrypted = item.get("encrypted_content")
        text = encrypted if isinstance(encrypted, str) else ""
        text = apply_processing(
            text,
            opts,
            vendor="Codex",
            record_type="compacted.encrypted_content",
            event_kind="context.compact",
            phase="pre",
        )
        if text is None:
            continue
        text, content_len, truncated = bound_context_content(text, opts)
        text = apply_processing(
            text,
            opts,
            vendor="Codex",
            record_type="compacted.encrypted_content",
            event_kind="context.compact",
            phase="post",
        )
        if text is None:
            continue
        text, _post_length, post_truncated = bound_context_content(text, opts)
        truncated = truncated or post_truncated
        metadata = {
            "audit_kind": "context_compaction",
            "context_kind": "compaction_summary",
            "content_encoding": (
                "vendor_encrypted" if isinstance(encrypted, str) else "absent"
            ),
            "content_truncated": truncated,
            "replacement_history_items": len(history),
            "replacement_history_messages_not_duplicated": sum(
                isinstance(entry, dict) and entry.get("type") == "message"
                for entry in history
            ),
        }
        for key in (
            "window_number", "first_window_id", "previous_window_id", "window_id"
        ):
            if payload.get(key) is not None:
                metadata[key] = payload[key]
        if item.get("id") is not None:
            metadata["compaction_item_id"] = item["id"]
        yield {
            "session_id": session_id,
            "event_id": (
                str(line_num)
                if len(summaries) == 1
                else f"{line_num}:{emitted_index}"
            ),
            "event_type": "system_event",
            "subtype": "context_compaction",
            "role": "harness",
            "content": text or None,
            "content_len": content_len if encrypted is not None else None,
            "content_ref": None,
            "tool_name": None,
            "tool_input": None,
            "tool_output": None,
            "timestamp": timestamp,
            "file_path": None,
            "source_file": source_file,
            "metadata": json.dumps(metadata, separators=(",", ":")),
            "source_raw": source_raw,
            "event_kind": "context.compact",
            "actor_kind": "harness",
            "content_role": "context",
            "origin_kind": "harness_injected",
            "_source_path": (
                "$.payload.replacement_history"
                if history_index < 0
                else f"$.payload.replacement_history[{history_index}]"
            ),
        }


def process_file(
    path: Path,
    session_id: str,
    project_path: str,
    opts: dict,
) -> Iterator[dict]:
    """Stream events from Codex JSONL. Maps session_meta, response_item to normalized events."""
    source_file = str(path.resolve())
    redact_enabled = opts.get("redact", False)
    debug = opts.get("debug", False)
    diagnostics = opts.get("diagnostics")
    call_map = _build_call_map(path)
    current_configuration: dict = {}

    for line_num, record, raw_line in iter_codex_records(path, diagnostics):
        rtype = record.get("type")
        payload = record.get("payload") or {}
        if not isinstance(payload, dict):
            if diagnostics is not None:
                diagnostics["malformed_records"] = (
                    diagnostics.get("malformed_records", 0) + 1
                )
            continue
        timestamp = _parse_timestamp(record.get("timestamp"))

        source_raw = (
            raw_line.encode("utf-8", errors="replace")[:512]
            if debug and not redact_enabled
            else None
        )

        if rtype == "session_meta":
            if diagnostics is not None:
                diagnostics["session_metadata_records"] = (
                    diagnostics.get("session_metadata_records", 0) + 1
                )
            continue

        if rtype == "compacted":
            for event in _compaction_events(
                payload,
                session_id=session_id,
                source_file=source_file,
                line_num=line_num,
                timestamp=timestamp,
                source_raw=source_raw,
                opts=opts,
            ):
                yield _annotate_source(event, rtype, payload, line_num)
            continue

        if rtype == "turn_context":
            _update_configuration(
                current_configuration,
                _configuration_values("turn_context", payload, line_num),
            )
            if diagnostics is not None:
                diagnostics["configuration_records"] = (
                    diagnostics.get("configuration_records", 0) + 1
                )
            continue

        if (
            rtype == "event_msg"
            and payload.get("type") == "thread_settings_applied"
        ):
            _update_configuration(
                current_configuration,
                _configuration_values(
                    "thread_settings_applied", payload, line_num
                ),
            )
            if diagnostics is not None:
                diagnostics["configuration_records"] = (
                    diagnostics.get("configuration_records", 0) + 1
                )
            continue

        if rtype == "response_item":
            item_type = payload.get("type", "")
            if item_type == "reasoning":
                text = _extract_reasoning_summary(payload.get("summary"))
                if not text:
                    if diagnostics is not None:
                        diagnostics["known_ignored_records"] = (
                            diagnostics.get("known_ignored_records", 0) + 1
                        )
                        diagnostics["reasoning_without_summary_records"] = (
                            diagnostics.get(
                                "reasoning_without_summary_records", 0
                            ) + 1
                        )
                    continue
                text = apply_processing(
                    text, opts, vendor="Codex",
                    record_type="reasoning_summary",
                    event_kind="message.reasoning_summary", phase="pre",
                )
                if text is None:
                    continue
                truncated, content_len = _truncate(text, TRUNCATE_RESPONSE)
                truncated = apply_processing(
                    truncated, opts, vendor="Codex",
                    record_type="reasoning_summary",
                    event_kind="message.reasoning_summary", phase="post",
                )
                if truncated is None:
                    continue
                if diagnostics is not None:
                    diagnostics["reasoning_summary_records"] = (
                        diagnostics.get("reasoning_summary_records", 0) + 1
                    )
                yield _annotate_source({
                    "session_id": session_id,
                    "event_id": str(line_num),
                    "event_type": "assistant_message",
                    "subtype": "reasoning_summary",
                    "role": "assistant",
                    "event_kind": "message.reasoning_summary",
                    "actor_kind": "model",
                    "content_role": "reasoning_summary",
                    "origin_kind": "model_generated",
                    "content": truncated,
                    "content_len": content_len,
                    "content_ref": None,
                    "tool_name": None,
                    "tool_input": None,
                    "tool_output": None,
                    "timestamp": timestamp,
                    "file_path": None,
                    "source_file": source_file,
                    "metadata": _merge_metadata(
                        payload, current_configuration
                    ),
                    "source_raw": source_raw,
                }, rtype, payload, line_num)
                continue

            if item_type == "message":
                role = payload.get("role", "")
                content = payload.get("content") or []
                text = _extract_text_from_content(content)
                message_kind = (
                    "message.prompt"
                    if role == "user"
                    else "message.context"
                    if role in {"developer", "system"}
                    else "message.response"
                )
                text = apply_processing(
                    text, opts, vendor="Codex", record_type="message",
                    event_kind=message_kind,
                    phase="pre",
                )
                if text is None:
                    continue

                if role == "user":
                    subtype = "slash_command" if text.strip().startswith("/") else "prompt"
                    truncated, content_len = _truncate(text, TRUNCATE_PROMPT)
                    truncated = apply_processing(
                        truncated, opts, vendor="Codex", record_type="message",
                        event_kind="message.prompt", phase="post",
                    )
                    if truncated is None:
                        continue
                    yield _annotate_source({
                        "session_id": session_id,
                        "event_id": str(line_num),
                        "event_type": "user_message",
                        "subtype": subtype,
                        "role": "user",
                        "content": truncated,
                        "content_len": content_len,
                        "content_ref": None,
                        "tool_name": None,
                        "tool_input": None,
                        "tool_output": None,
                        "timestamp": timestamp,
                        "file_path": None,
                        "source_file": source_file,
                        "metadata": _merge_metadata(payload, current_configuration),
                        "source_raw": source_raw,
                    }, rtype, payload, line_num)
                elif role == "assistant":
                    truncated, content_len = _truncate(text, TRUNCATE_RESPONSE)
                    truncated = apply_processing(
                        truncated, opts, vendor="Codex", record_type="message",
                        event_kind="message.response", phase="post",
                    )
                    if truncated is None:
                        continue
                    yield _annotate_source({
                        "session_id": session_id,
                        "event_id": str(line_num),
                        "event_type": "assistant_message",
                        "subtype": "response",
                        "role": "assistant",
                        "content": truncated,
                        "content_len": content_len,
                        "content_ref": None,
                        "tool_name": None,
                        "tool_input": None,
                        "tool_output": None,
                        "timestamp": timestamp,
                        "file_path": None,
                        "source_file": source_file,
                        "metadata": _merge_metadata(payload, current_configuration),
                        "source_raw": source_raw,
                    }, rtype, payload, line_num)
                elif role in {"developer", "system"}:
                    bounded, content_len, truncated = bound_context_content(
                        text, opts
                    )
                    bounded = apply_processing(
                        bounded, opts, vendor="Codex", record_type="message",
                        event_kind="message.context", phase="post",
                    )
                    if bounded is None:
                        continue
                    bounded, _post_len, post_truncated = bound_context_content(
                        bounded, opts
                    )
                    yield _annotate_source({
                        "session_id": session_id,
                        "event_id": str(line_num),
                        "event_type": "system_event",
                        "subtype": "context_injection",
                        "role": role,
                        "event_kind": "message.context",
                        "actor_kind": "harness",
                        "content_role": "context",
                        "origin_kind": "harness_injected",
                        "content": bounded,
                        "content_len": content_len,
                        "content_ref": None,
                        "tool_name": None,
                        "tool_input": None,
                        "tool_output": None,
                        "timestamp": timestamp,
                        "file_path": None,
                        "source_file": source_file,
                        "metadata": _merge_metadata(payload, {
                            **current_configuration,
                            "source_role": role,
                            "content_truncated": (
                                truncated or post_truncated
                            ),
                        }),
                        "source_raw": source_raw,
                    }, rtype, payload, line_num)
                elif diagnostics is not None:
                    diagnostics["ignored_records"] = (
                        diagnostics.get("ignored_records", 0) + 1
                    )
                continue

            if item_type in ("function_call", "custom_tool_call"):
                yield _annotate_source({
                    "session_id": session_id,
                    "event_id": str(line_num),
                    "event_type": "tool_call",
                    "subtype": "tool_failure" if _failed_status(payload) else None,
                    "role": "assistant",
                    "content": None,
                    "content_len": None,
                    "content_ref": None,
                    "tool_name": payload.get("name"),
                    "tool_input": _tool_input(payload, redact_enabled),
                    "tool_output": None,
                    "timestamp": timestamp,
                    "file_path": None,
                    "source_file": source_file,
                    "metadata": _merge_metadata(payload, current_configuration),
                    "source_raw": source_raw,
                }, rtype, payload, line_num)
                continue

            if item_type == "web_search_call":
                action = sanitize_value(
                    payload.get("action") or {}, redact_enabled
                )
                yield _annotate_source({
                    "session_id": session_id,
                    "event_id": str(line_num),
                    "event_type": "tool_call",
                    "subtype": None,
                    "role": "assistant",
                    "content": None,
                    "content_len": None,
                    "content_ref": None,
                    "tool_name": "web_search",
                    "tool_input": json.dumps(
                        action, separators=(",", ":"), ensure_ascii=False
                    ),
                    "tool_output": None,
                    "timestamp": timestamp,
                    "file_path": None,
                    "source_file": source_file,
                    "metadata": _merge_metadata(payload, current_configuration),
                    "source_raw": source_raw,
                }, rtype, payload, line_num)
                continue

            if item_type in ("function_call_output", "custom_tool_call_output"):
                call_id = payload.get("call_id")
                output = payload.get("output")
                if isinstance(output, str):
                    text = output
                else:
                    text = json.dumps(output, ensure_ascii=False)
                text = apply_processing(
                    text, opts, vendor="Codex", record_type="tool_result",
                    event_kind="tool.result", phase="pre",
                )
                if text is None:
                    continue
                truncated, content_len = _truncate(text, TRUNCATE_TOOL_RESULT)
                truncated = apply_processing(
                    truncated, opts, vendor="Codex", record_type="tool_result",
                    event_kind="tool.result", phase="post",
                )
                if truncated is None:
                    continue
                yield _annotate_source({
                    "session_id": session_id,
                    "event_id": str(line_num),
                    "event_type": "user_message",
                    "subtype": "tool_result",
                    "role": "user",
                    "content": truncated,
                    "content_len": content_len,
                    "content_ref": None,
                    "tool_name": call_map.get(str(call_id)) if call_id else None,
                    "tool_input": None,
                    "tool_output": truncated,
                    "timestamp": timestamp,
                    "file_path": None,
                    "source_file": source_file,
                    "metadata": _merge_metadata(payload, current_configuration),
                    "source_raw": source_raw,
                }, rtype, payload, line_num)
                continue

            if diagnostics is not None:
                if item_type == "ghost_snapshot":
                    diagnostics["known_ignored_records"] = (
                        diagnostics.get("known_ignored_records", 0) + 1
                    )
                    diagnostics["intermediate_state_records"] = (
                        diagnostics.get("intermediate_state_records", 0) + 1
                    )
                else:
                    diagnostics["ignored_records"] = (
                        diagnostics.get("ignored_records", 0) + 1
                    )
            continue

        elif rtype == "event_msg":
            msg_type = payload.get("type", "")
            if msg_type == "context_compacted":
                if diagnostics is not None:
                    diagnostics["known_ignored_records"] = (
                        diagnostics.get("known_ignored_records", 0) + 1
                    )
                continue
            if msg_type in {"task_started", "task_complete"}:
                is_start = msg_type == "task_started"
                metadata = {
                    key: payload.get(key)
                    for key in (
                        "turn_id", "started_at", "completed_at", "duration_ms",
                        "time_to_first_token_ms", "model_context_window",
                        "collaboration_mode_kind",
                    )
                    if payload.get(key) is not None
                }
                if isinstance(payload.get("last_agent_message"), str):
                    metadata["last_agent_message_characters"] = len(
                        payload["last_agent_message"]
                    )
                    metadata["last_agent_message_not_duplicated"] = True
                yield _annotate_source({
                    "session_id": session_id,
                    "event_id": str(line_num),
                    "event_type": "lifecycle_event",
                    "subtype": msg_type,
                    "role": "harness",
                    "event_kind": (
                        "lifecycle.start" if is_start else "lifecycle.complete"
                    ),
                    "actor_kind": "harness",
                    "content_role": "status",
                    "origin_kind": "harness_generated",
                    "content": None,
                    "content_len": None,
                    "content_ref": None,
                    "tool_name": None,
                    "tool_input": None,
                    "tool_output": None,
                    "timestamp": timestamp,
                    "file_path": None,
                    "source_file": source_file,
                    "metadata": json.dumps(metadata, separators=(",", ":")),
                    "source_raw": source_raw,
                }, rtype, payload, line_num)
                continue
            if msg_type in {"web_search_end", "patch_apply_end"}:
                call_id = payload.get("call_id")
                failed = (
                    payload.get("success") is False
                    or str(payload.get("status") or "").lower()
                    in {"failed", "failure", "error"}
                )
                metadata = {
                    "call_id": str(call_id) if call_id is not None else None,
                    "status": payload.get("status"),
                    "success": payload.get("success"),
                    "change_count": (
                        len(payload["changes"])
                        if isinstance(payload.get("changes"), dict) else None
                    ),
                    "duplicate_output_not_retained": True,
                }
                yield _annotate_source({
                    "session_id": session_id,
                    "event_id": str(line_num),
                    "event_type": "user_message",
                    "subtype": "tool_failure" if failed else "tool_result",
                    "role": "tool",
                    "event_kind": "tool.result",
                    "actor_kind": "tool",
                    "content_role": "tool_result",
                    "origin_kind": "tool_generated",
                    "content": None,
                    "content_len": None,
                    "content_ref": None,
                    "tool_name": (
                        "web_search"
                        if msg_type == "web_search_end" else "apply_patch"
                    ),
                    "tool_input": None,
                    "tool_output": None,
                    "timestamp": timestamp,
                    "file_path": None,
                    "source_file": source_file,
                    "source_status": payload.get("status"),
                    "normalized_status": "failed" if failed else "succeeded",
                    "metadata": json.dumps(
                        {key: value for key, value in metadata.items()
                         if value is not None},
                        separators=(",", ":"),
                    ),
                    "source_raw": source_raw,
                }, rtype, payload, line_num)
                continue
            if msg_type != "turn_aborted":
                if diagnostics is not None:
                    known_kind = {
                        "agent_message": "duplicate_envelope_records",
                        "user_message": "duplicate_envelope_records",
                        "agent_reasoning": "duplicate_reasoning_records",
                        "token_count": "usage_records",
                    }.get(msg_type)
                    if known_kind:
                        diagnostics["known_ignored_records"] = (
                            diagnostics.get("known_ignored_records", 0) + 1
                        )
                        diagnostics[known_kind] = (
                            diagnostics.get(known_kind, 0) + 1
                        )
                    else:
                        diagnostics["ignored_records"] = (
                            diagnostics.get("ignored_records", 0) + 1
                        )
                continue
            content = str(payload.get("reason") or payload.get("info") or "turn aborted")
            content = apply_processing(
                content, opts, vendor="Codex", record_type="turn_aborted",
                event_kind="lifecycle.abort", phase="pre",
            )
            if content is None:
                continue
            truncated, content_len = _truncate(content, 500)
            truncated = apply_processing(
                truncated, opts, vendor="Codex", record_type="turn_aborted",
                event_kind="lifecycle.abort", phase="post",
            )
            if truncated is None:
                continue
            ev = {
                "session_id": session_id,
                "event_id": str(line_num),
                "event_type": "assistant_message",
                "subtype": "turn_aborted",
                "role": "assistant",
                "content": truncated,
                "content_len": content_len,
                "content_ref": None,
                "tool_name": None,
                "tool_input": None,
                "tool_output": None,
                "timestamp": timestamp,
                "file_path": None,
                "source_file": source_file,
                "metadata": json.dumps({"event_msg_type": msg_type}) if msg_type else None,
                "source_raw": source_raw,
            }
            yield _annotate_source(ev, rtype, payload, line_num)
        elif diagnostics is not None:
            if rtype == "world_state":
                diagnostics["known_ignored_records"] = (
                    diagnostics.get("known_ignored_records", 0) + 1
                )
                diagnostics["intermediate_state_records"] = (
                    diagnostics.get("intermediate_state_records", 0) + 1
                )
            else:
                diagnostics["ignored_records"] = (
                    diagnostics.get("ignored_records", 0) + 1
                )


def _truncate(text: str, limit: int) -> tuple[str, int]:
    """Return (truncated, full_len)."""
    if text is None:
        return "", 0
    s = str(text)
    n = len(s)
    if limit <= 0:
        return "…" if n else "", n
    if n <= limit:
        return s, n
    return s[: limit - 1] + "…", n
