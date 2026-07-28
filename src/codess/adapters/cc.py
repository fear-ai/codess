"""CC JSONL parser and normalizer."""

import json
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from codess import field_state

from codess.config import (
    TRUNCATE_DIALOG,
    TRUNCATE_GREP_PATTERN,
    TRUNCATE_PROMPT,
    TRUNCATE_RESPONSE,
    TRUNCATE_TOOL_RESULT,
)
from codess.sanitize import apply_sanitization, sanitize_value
from codess.bounded_jsonl import iter_bounded_jsonl
from codess.context_content import bound_context_content
from codess.mapping import annotate_mapping

log = logging.getLogger(__name__)


class SourceCompatibilityError(ValueError):
    """A source record cannot be mapped without silently losing meaning."""

SKIP_TYPES = frozenset({
    "progress", "file-history-snapshot", "queue-operation", "last-prompt", "system",
})

PERMISSION_DENIAL_MARKERS = (
    "permission for this tool use was denied",
    "tool use was rejected",
    "doesn't want to proceed with this tool use",
)


def iter_cc_records(
    path: Path,
    diagnostics: dict[str, int] | None = None,
    *,
    warn: bool = True,
) -> Iterator[tuple[int, dict, str]]:
    """Stream JSONL; yield (line_num, record, raw_line). Skip empty lines; on JSON error log and skip."""
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


def get_session_metadata(path: Path) -> dict:
    """Return bounded session facts observed directly in Claude records."""
    facts = {}
    for line_num, record, _raw in iter_cc_records(path, warn=False):
        version = record.get("version") or record.get("claudeCodeVersion")
        if version is not None and "harness_version" not in facts:
            facts["harness_version"] = str(version)
        cwd = record.get("cwd")
        if isinstance(cwd, str) and cwd and "source_cwd" not in facts:
            facts["source_cwd"] = cwd
        if len(facts) == 2 or line_num >= 256:
            break
    return facts


def get_session_lineage(path: Path) -> dict:
    """Return direct Claude fork evidence without reading unbounded records."""
    try:
        for _line, record, error in iter_bounded_jsonl(path):
            if error or record is None or record.get("type") != "fork-context-ref":
                continue
            parent = record.get("parentSessionId")
            if not parent:
                continue
            return {
                "parent_session_id": str(parent),
                "session_relation_kind": "fork",
                "lineage_provenance": "fork-context-ref.parentSessionId",
                "agent_id": record.get("agentId"),
                "parent_last_uuid": record.get("parentLastUuid"),
            }
    except OSError:
        pass
    return {}


def should_skip(record: dict) -> bool:
    """Return True for progress, file-history-snapshot, queue-operation, last-prompt, system (empty)."""
    rtype = record.get("type")
    if rtype == "system":
        content = record.get("message", {}).get("content")
        if content and (not isinstance(content, list) or content):
            return False  # Include system with content
        return True
    if rtype in SKIP_TYPES:
        return True
    return False


def _is_permission_denial(text: str) -> bool:
    """Recognize explicit Claude denial text; other error results are failures."""
    lowered = text.lower()
    return any(marker in lowered for marker in PERMISSION_DENIAL_MARKERS)


def _normalize_compaction(
    record: dict,
    line_num: int,
    session_id: str,
    source_file: str,
) -> dict:
    """Retain an explicit compact boundary and its observed accounting."""
    compact = record.get("compactMetadata") or {}
    metadata = {"audit_kind": "context_compaction"}
    field_names = {
        "trigger": "trigger",
        "preTokens": "pre_tokens",
        "postTokens": "post_tokens",
        "durationMs": "duration_ms",
        "preCompactDiscoveredTools": "pre_compact_discovered_tools",
        "preservedSegment": "preserved_segment",
        "preservedMessages": "preserved_messages",
        "precomputed": "precomputed",
    }
    for source_name, common_name in field_names.items():
        if compact.get(source_name) is not None:
            metadata[common_name] = compact[source_name]
    return {
        "session_id": session_id,
        "event_id": str(line_num),
        "event_type": "system_event",
        "subtype": "context_compaction",
        "role": "system",
        "content": None,
        "content_len": None,
        "content_ref": None,
        "tool_name": None,
        "tool_input": None,
        "tool_output": None,
        "timestamp": _get_timestamp(record),
        "file_path": None,
        "source_file": source_file,
        "metadata": json.dumps(metadata, separators=(",", ":")),
        "source_raw": None,
    }


def _mapping_rule(event: dict) -> str:
    """Return the declared primary rule for one Claude-derived event."""
    event_type = event.get("event_type")
    subtype = event.get("subtype")
    if event_type == "system_event" and subtype == "context_compaction":
        return "claude.compaction"
    if event_type == "system_event" and subtype == "context_compaction_summary":
        return "claude.compaction-summary"
    if event_type == "external_content":
        return "claude.persisted-tool-result"
    if event_type == "tool_call":
        return "claude.tool-use"
    if subtype in {"tool_result", "tool_failure", "permission_denied"}:
        return "claude.tool-result"
    if event_type == "product_state":
        return "claude.product-state"
    if subtype == "fork_context_reference":
        return "claude.fork-context"
    if event_type == "lifecycle_event":
        return "claude.lifecycle"
    if event_type == "user_message" and subtype in {"prompt", "slash_command"}:
        return "claude.typed-prompt"
    return "claude.message"


def _annotate_source(event: dict, record: dict, line_num: int) -> dict:
    rule = _mapping_rule(event)
    applied = [rule]
    if record.get("parentUuid") or record.get("tool_use_id"):
        applied.append("claude.lineage")
    metadata = event.get("metadata")
    if metadata:
        try:
            if json.loads(metadata).get("configuration_provenance"):
                applied.append("claude.configuration")
        except (AttributeError, json.JSONDecodeError, TypeError):
            pass
    return annotate_mapping(
        event,
        source_record_type=str(record.get("type") or "unknown"),
        source_record_subtype=(
            str(record["subtype"]) if record.get("subtype") is not None else None
        ),
        source_record_locator=str(line_num),
        mapping_rule=rule,
        applied_rules=applied,
    )


def extract_tool_input(tool_name: str, input_obj: dict) -> dict:
    """Per-tool field selection per CSPlan §3.3 extract_tool_input."""
    if not input_obj:
        return {}
    out = {}
    name = (tool_name or "").lower()
    if name == "bash":
        for k in ("command", "description"):
            if k in input_obj:
                out[k] = input_obj[k]
    elif name == "read":
        for k in ("path", "file_path", "offset", "limit", "pages"):
            if k in input_obj:
                out[k] = input_obj[k]
    elif name in ("edit", "write"):
        for k in ("path", "file_path", "old_len", "new_len", "content_len", "replace_all"):
            if k in input_obj:
                out[k] = input_obj[k]
        if "old_string" in input_obj:
            out["old_len"] = len(str(input_obj["old_string"]))
        if "new_string" in input_obj:
            out["new_len"] = len(str(input_obj["new_string"]))
        if "content" in input_obj:
            out["content_len"] = len(str(input_obj["content"]))
    elif name == "grep":
        for k in ("pattern", "path", "output_mode", "glob"):
            if k in input_obj:
                v = input_obj[k]
                if k == "pattern" and isinstance(v, str) and len(v) > TRUNCATE_GREP_PATTERN:
                    v = v[: TRUNCATE_GREP_PATTERN - 1] + "…"
                out[k] = v
    elif name == "glob":
        for k in ("pattern", "path"):
            if k in input_obj:
                out[k] = input_obj[k]
    elif name == "agent":
        for k in ("subagent_type", "description", "model"):
            if k in input_obj:
                out[k] = input_obj[k]
        if "prompt" in input_obj:
            p = input_obj["prompt"]
            if isinstance(p, str):
                truncated, _ = truncate_content(p, TRUNCATE_PROMPT)
                out["prompt"] = truncated
            else:
                out["prompt"] = p
    elif name == "skill":
        for k in ("skill", "args"):
            if k in input_obj:
                out[k] = input_obj[k]
    elif name in ("mcp_task", "task"):
        for k in ("subagent_type", "description"):
            if k in input_obj:
                out[k] = input_obj[k]
        if "prompt" in input_obj:
            p = input_obj["prompt"]
            if isinstance(p, str):
                truncated, _ = truncate_content(p, TRUNCATE_PROMPT)
                out["prompt"] = truncated
            else:
                out["prompt"] = p
    else:
        out = dict(input_obj)
    return out


def truncate_content(text: str, limit: int) -> tuple[str, int]:
    """Return (truncated, full_len). If over limit, append …."""
    if text is None:
        return "", 0
    s = str(text)
    n = len(s)
    if limit <= 0:
        return "…" if n else "", n
    if n <= limit:
        return s, n
    return s[: limit - 1] + "…", n


def _build_tool_map(path: Path) -> dict[str, str]:
    """First pass: build tool_use_id -> tool_name from assistant records."""
    tool_map = {}
    for _line_num, record, _ in iter_cc_records(path, warn=False):
        if record.get("type") != "assistant":
            continue
        content = record.get("message", {}).get("content") or []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tid = block.get("id")
                tname = block.get("name")
                if tid and tname:
                    tool_map[tid] = tname
    return tool_map


def _parse_timestamp(ts) -> float | None:
    """Convert timestamp to Unix ms. Handles float or ISO 8601 string."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            s = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp() * 1000
        except (ValueError, TypeError):
            pass
    return None


def _get_timestamp(record: dict, opts: dict | None = None) -> float | None:
    """Extract timestamp from record or message. Returns Unix ms.

    A present-but-unparseable timestamp is reported as ``malformed`` (warn) when
    ``opts`` is given; absent/empty values stay silent. Never raises.
    """
    ts = record.get("timestamp") or record.get("message", {}).get("timestamp")
    parsed = _parse_timestamp(ts)
    if opts is not None and parsed is None:
        state = field_state.classify(ts if ts is not None else field_state._MISSING)
        if state == field_state.PRESENT:
            state = field_state.MALFORMED  # present but did not parse
        field_state.diagnose(
            opts, field="event_at", state=state, source_field="timestamp", value=ts
        )
    return parsed


def _block_event_id(line_num: int, emitted_index: int) -> str:
    """Keep the legacy first id while making additional line events unique."""
    return str(line_num) if emitted_index == 0 else f"{line_num}:{emitted_index}"


def _event_metadata(record: dict, tool_use_id=None, extra: dict | None = None) -> str | None:
    """Retain stable Claude lineage identifiers without copying the envelope."""
    metadata = {}
    if record.get("uuid") is not None:
        metadata["record_uuid"] = record["uuid"]
    if record.get("parentUuid") is not None:
        metadata["parent_uuid"] = record["parentUuid"]
    if tool_use_id is not None:
        metadata["tool_use_id"] = tool_use_id
    if extra:
        metadata.update({key: value for key, value in extra.items() if value is not None})
    return json.dumps(metadata, separators=(",", ":")) if metadata else None


def _assistant_configuration(record: dict) -> dict:
    """Retain verified Claude model settings with their exact source fields."""
    message = record.get("message") or {}
    if not isinstance(message, dict):
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
                "source_record_type": "assistant",
                "source_record_locator": str(record.get("uuid") or "line"),
                "source_field": source_field,
            }

    keep("model", "message.model", message.get("model"))
    usage = message.get("usage")
    if isinstance(usage, dict):
        keep(
            "service_tier", "message.usage.service_tier",
            usage.get("service_tier"),
        )
    if provenance:
        values["configuration_provenance"] = provenance
    return values


def _diagnostic(opts: dict, name: str, count: int = 1) -> None:
    diagnostics = opts.get("diagnostics")
    if diagnostics is not None:
        diagnostics[name] = diagnostics.get(name, 0) + count


def _process_text(text: str, opts: dict, *, phase: str, record_type: str) -> str | None:
    from codess.content_processing import apply_processing
    return apply_processing(
        text, opts, vendor="Claude", record_type=record_type, phase=phase
    )


def _base_event(
    *, session_id: str, event_id: str, event_type: str, subtype: str,
    role: str, timestamp: float | None, source_file: str,
) -> dict:
    return {
        "session_id": session_id, "event_id": event_id,
        "event_type": event_type, "subtype": subtype, "role": role,
        "content": None, "content_len": None, "content_ref": None,
        "tool_name": None, "tool_input": None, "tool_output": None,
        "timestamp": timestamp, "file_path": None,
        "source_file": source_file, "metadata": None, "source_raw": None,
    }


def _attach_timestamp_state(event: dict, record: dict, timestamp) -> None:
    if timestamp is not None:
        return
    value, state = field_state.get_state(record, "timestamp")
    if state == field_state.PRESENT:
        state = field_state.MALFORMED
    field_state.attach(
        event, field="event_at", state=state,
        source_field="timestamp", value=value,
    )


def _attach_configuration_state(event: dict, record: dict) -> None:
    message, message_state = field_state.get_state(record, "message")
    if message_state == field_state.PRESENT and not isinstance(message, dict):
        field_state.attach(
            event, field="model", state=field_state.MALFORMED,
            source_field="message", value=message,
        )
        return
    message = message if isinstance(message, dict) else {}
    model, model_state = field_state.get_state(message, "model")
    if model_state == field_state.PRESENT and isinstance(model, (dict, list)):
        model_state = field_state.MALFORMED
    field_state.attach(
        event, field="model", state=model_state,
        source_field="message.model", value=model,
    )
    usage = message.get("usage")
    if usage is None:
        return
    if not isinstance(usage, dict):
        field_state.attach(
            event, field="service_tier", state=field_state.MALFORMED,
            source_field="message.usage", value=usage,
        )
        return
    tier, tier_state = field_state.get_state(usage, "service_tier")
    if tier_state == field_state.PRESENT and isinstance(tier, (dict, list)):
        tier_state = field_state.MALFORMED
    field_state.attach(
        event, field="service_tier", state=tier_state,
        source_field="message.usage.service_tier", value=tier,
    )


def _attach_prompt_origin_state(event: dict, record: dict) -> None:
    origin, origin_state = field_state.get_state(record, "origin")
    prompt_source, prompt_state = field_state.get_state(record, "promptSource")
    if origin_state == field_state.PRESENT and not isinstance(origin, (dict, str)):
        origin_state = field_state.MALFORMED
    if (
        origin_state == field_state.ABSENT
        and prompt_state != field_state.ABSENT
    ):
        return
    field_state.attach(
        event, field="prompt_origin", state=origin_state,
        source_field="origin", value=origin,
    )
    if prompt_state == field_state.PRESENT and isinstance(
        prompt_source, (dict, list)
    ):
        field_state.attach(
            event, field="prompt_origin", state=field_state.MALFORMED,
            source_field="promptSource", value=prompt_source,
        )


def normalize_product_state(
    record: dict, line_num: int, session_id: str, source_file: str, opts: dict,
) -> dict | None:
    """Map bounded Claude product/lifecycle state without copying envelopes."""
    rtype = record.get("type")
    subtype = record.get("subtype")
    event = None
    metadata: dict = {}
    if rtype == "mode":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="product_state", subtype="mode", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        metadata["mode"] = record.get("mode")
    elif rtype == "permission-mode":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="product_state", subtype="permission_mode", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        metadata["permission_mode"] = record.get("permissionMode")
    elif rtype == "ai-title":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="product_state", subtype="ai_title", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        title = _process_text(record.get("aiTitle") or "", opts, phase="pre", record_type="ai-title")
        if title is not None:
            event["content"], event["content_len"] = truncate_content(title, 512)
    elif rtype == "custom-title":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="product_state", subtype="custom_title", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        title = _process_text(record.get("customTitle") or "", opts, phase="pre", record_type="custom-title")
        if title is not None:
            event["content"], event["content_len"] = truncate_content(title, 512)
    elif rtype == "agent-name":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="product_state", subtype="agent_name", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        name = _process_text(record.get("agentName") or "", opts, phase="pre", record_type="agent-name")
        if name is not None:
            event["content"], event["content_len"] = truncate_content(name, 512)
    elif rtype == "fork-context-ref":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="lifecycle_event", subtype="fork_context_reference", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        metadata = {
            "parent_session_id": record.get("parentSessionId"),
            "parent_last_uuid": record.get("parentLastUuid"),
            "agent_id": record.get("agentId"),
            "context_length": record.get("contextLength"),
            "lineage_provenance": "fork-context-ref.parentSessionId",
        }
    elif rtype == "attachment":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="product_state", subtype="context_attachment", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        attachment = record.get("attachment") or {}
        if isinstance(attachment, dict):
            metadata = {
                "attachment_type": attachment.get("type"),
                "item_count": attachment.get("itemCount"),
                "is_initial": attachment.get("isInitial"),
                "command_mode": attachment.get("commandMode"),
                "has_content": bool(attachment.get("content")),
            }
    elif rtype == "file-history-snapshot":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="product_state", subtype="file_history_snapshot", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        metadata["snapshot_field_count"] = len(record)
    elif rtype == "queue-operation":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="lifecycle_event", subtype="queue_operation", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        metadata["operation"] = record.get("operation")
    elif rtype == "last-prompt":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="product_state", subtype="last_prompt_marker", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        value = record.get("lastPrompt") or record.get("prompt") or ""
        metadata["content_len"] = len(str(value))
    elif rtype == "system" and subtype == "turn_duration":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="lifecycle_event", subtype="turn_duration", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        metadata = {"duration_ms": record.get("durationMs"), "message_count": record.get("messageCount")}
    elif rtype == "system" and subtype == "scheduled_task_fire":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="lifecycle_event", subtype="scheduled_task_fire", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
    if event is None:
        return None
    event.update({
        "event_kind": "state.product" if event["event_type"] == "product_state" else "lifecycle.vendor",
        "actor_kind": "harness", "content_role": "state",
        "origin_kind": "harness_generated",
        "metadata": _event_metadata(record, extra=metadata),
    })
    return event


def normalize_assistant(
    record: dict,
    line_num: int,
    session_id: str,
    source_file: str,
    opts: dict,
) -> tuple[list[dict], dict[str, str]]:
    """Extract assistant events; return (events, tool_map)."""
    events = []
    tool_map = {}
    message = record.get("message")
    message = message if isinstance(message, dict) else {}
    content = message.get("content") or []
    role = message.get("role", "assistant")
    ts = _get_timestamp(record)
    redact_enabled = opts.get("redact", False)
    model_configuration = _assistant_configuration(record)
    # Build tool_map from tool_use blocks
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tid = block.get("id")
            tname = block.get("name")
            if tid and tname:
                tool_map[tid] = tname

    stop_reason = message.get("stop_reason", "")
    emitted_index = 0

    for i, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        btype = block.get("type")

        if btype == "text":
            text = block.get("text") or ""
            text = _process_text(text, opts, phase="pre", record_type="assistant.text")
            if text is None:
                continue
            # Response: no tool_use follows in this record. Dialog: tool_use follows.
            follows_tool_use = any(
                isinstance(content[j], dict) and content[j].get("type") == "tool_use"
                for j in range(i + 1, len(content))
            )
            if follows_tool_use:
                subtype = "dialog"
                limit = TRUNCATE_DIALOG
            else:
                subtype = "truncated" if "max_tokens" in str(stop_reason) else "response"
                limit = TRUNCATE_RESPONSE
            truncated, content_len = truncate_content(text, limit)
            processed = _process_text(
                truncated, opts, phase="post", record_type="assistant.text"
            )
            if processed is None:
                continue
            truncated = processed
            events.append({
                "session_id": session_id,
                "event_id": _block_event_id(line_num, emitted_index),
                "event_type": "assistant_message",
                "subtype": subtype,
                "role": role,
                "content": truncated,
                "content_len": content_len,
                "content_ref": None,
                "tool_name": None,
                "tool_input": None,
                "tool_output": None,
                "timestamp": ts,
                "file_path": None,
                "source_file": source_file,
                "metadata": _event_metadata(record, extra=model_configuration),
                "source_raw": None,
            })
            _attach_timestamp_state(events[-1], record, ts)
            _attach_configuration_state(events[-1], record)
            emitted_index += 1

        elif btype == "tool_use":
            tname = block.get("name")
            raw_input, input_state = field_state.get_state(block, "input")
            if input_state == field_state.PRESENT and not isinstance(
                raw_input, dict
            ):
                input_state = field_state.MALFORMED
                tinput = {}
            else:
                tinput = raw_input if isinstance(raw_input, dict) else {}
            tool_input = extract_tool_input(tname or "", tinput)
            tool_input = sanitize_value(tool_input, redact_enabled)
            tool_use_id = block.get("id")
            events.append({
                "session_id": session_id,
                "event_id": _block_event_id(line_num, emitted_index),
                "event_type": "tool_call",
                "subtype": None,
                "role": role,
                "content": None,
                "content_len": None,
                "content_ref": None,
                "tool_name": tname,
                "tool_input": json.dumps(tool_input) if tool_input else None,
                "tool_output": None,
                "timestamp": ts,
                "file_path": (
                    tool_input.get("path") or tool_input.get("file_path")
                    if isinstance(tool_input, dict) else None
                ),
                "source_file": source_file,
                "metadata": _event_metadata(
                    record, tool_use_id, extra=model_configuration
                ),
                "source_raw": None,
            })
            _attach_timestamp_state(events[-1], record, ts)
            _attach_configuration_state(events[-1], record)
            field_state.attach(
                events[-1], field="tool_input", state=input_state,
                source_field="message.content[].input", value=raw_input,
            )
            emitted_index += 1

    return events, tool_map


def normalize_user(
    record: dict,
    line_num: int,
    session_id: str,
    source_file: str,
    tool_map: dict[str, str],
    opts: dict,
) -> list[dict]:
    """Extract user events."""
    events = []
    message = record.get("message")
    message = message if isinstance(message, dict) else {}
    content = message.get("content")
    role = message.get("role", "user")
    ts = _get_timestamp(record)
    emitted_index = 0

    # The post-compaction summary is harness-injected replacement context, not
    # a typed human prompt.  Preserve it as communication and link it to the
    # preceding compact boundary through parentUuid.
    if record.get("isCompactSummary"):
        if not isinstance(content, str):
            _diagnostic(opts, "unsupported_records")
            if opts.get("strict_mapping"):
                raise SourceCompatibilityError(
                    "Claude compact summary content is not text"
                )
            return []
        text = _process_text(
            content, opts, phase="pre", record_type="context.compact.summary"
        )
        if text is None:
            return []
        text, content_len, truncated = bound_context_content(text, opts)
        text = _process_text(
            text, opts, phase="post", record_type="context.compact.summary"
        )
        if text is None:
            return []
        text, _post_length, post_truncated = bound_context_content(text, opts)
        truncated = truncated or post_truncated
        event = _base_event(
            session_id=session_id,
            event_id=str(line_num),
            event_type="system_event",
            subtype="context_compaction_summary",
            role="harness",
            timestamp=ts,
            source_file=source_file,
        )
        event.update({
            "content": text,
            "content_len": content_len,
            "event_kind": "context.inject",
            "actor_kind": "harness",
            "content_role": "context",
            "origin_kind": "harness_injected",
            "metadata": _event_metadata(record, extra={
                "context_kind": "compaction_summary",
                "compaction_boundary_uuid": record.get("parentUuid"),
                "content_truncated": truncated,
            }),
        })
        _attach_timestamp_state(event, record, ts)
        return [event]

    if isinstance(content, str):
        text = _process_text(content, opts, phase="pre", record_type="user.prompt")
        if text is None:
            return []
        text = _process_text(text, opts, phase="post", record_type="user.prompt")
        if text is None:
            return []
        origin = record.get("origin") or {}
        origin_kind = origin.get("kind") if isinstance(origin, dict) else str(origin)
        prompt_source = record.get("promptSource")
        harness_generated = prompt_source == "system" or origin_kind not in {None, "human"}
        subtype = (
            "task_notification" if origin_kind == "task-notification"
            else "system_prompt" if harness_generated
            else "slash_command" if text.strip().startswith("/")
            else "prompt"
        )
        event_type = "system_event" if harness_generated else "user_message"
        actor_kind = "harness" if harness_generated else "human"
        event = _base_event(
            session_id=session_id, event_id=str(line_num), event_type=event_type,
            subtype=subtype, role="harness" if harness_generated else role,
            timestamp=ts, source_file=source_file,
        )
        event.update({
            "content": text, "content_len": len(text),
            "event_kind": "message.context" if harness_generated else "message.prompt",
            "actor_kind": actor_kind,
            "content_role": "notification" if harness_generated else "prompt",
            "origin_kind": "harness_injected" if harness_generated else "direct_user_input",
            "metadata": _event_metadata(record, extra={
                "prompt_source": prompt_source,
                "origin_kind": origin_kind,
                "permission_mode": record.get("permissionMode"),
                "user_type": record.get("userType"),
            }),
        })
        _attach_timestamp_state(event, record, ts)
        _attach_prompt_origin_state(event, record)
        return [event]
    if content is None:
        content = []
    elif not isinstance(content, list):
        _diagnostic(opts, "unsupported_records")
        if opts.get("strict_mapping"):
            raise SourceCompatibilityError(
                f"unsupported Claude user content type: {type(content).__name__}"
            )
        return []

    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")

        if btype == "text":
            text = block.get("text") or ""
            text = _process_text(text, opts, phase="pre", record_type="user.text")
            if text is None:
                continue
            text = _process_text(text, opts, phase="post", record_type="user.text")
            if text is None:
                continue
            subtype = "slash_command" if text.strip().startswith("/") else "prompt"
            events.append({
                "session_id": session_id,
                "event_id": _block_event_id(line_num, emitted_index),
                "event_type": "user_message",
                "subtype": subtype,
                "role": role,
                "content": text,
                "content_len": len(text),
                "content_ref": None,
                "tool_name": None,
                "tool_input": None,
                "tool_output": None,
                "timestamp": ts,
                "file_path": None,
                "source_file": source_file,
                "metadata": _event_metadata(record),
                "source_raw": None,
            })
            _attach_timestamp_state(events[-1], record, ts)
            _attach_prompt_origin_state(events[-1], record)
            emitted_index += 1

        elif btype == "tool_result":
            tool_use_id = block.get("tool_use_id")
            tool_name = tool_map.get(tool_use_id) if tool_use_id else None
            is_error = block.get("is_error", False)
            content_val = block.get("content")
            if isinstance(content_val, list):
                # Some tool results have content as list of blocks
                parts = []
                for c in content_val:
                    if isinstance(c, dict) and c.get("type") == "text":
                        parts.append(c.get("text", ""))
                content_val = "\n".join(parts)
            text = str(content_val) if content_val else ""
            text = _process_text(text, opts, phase="pre", record_type="tool_result")
            if text is None:
                continue
            truncated, content_len = truncate_content(text, TRUNCATE_TOOL_RESULT)
            processed = _process_text(
                truncated, opts, phase="post", record_type="tool_result"
            )
            if processed is None:
                continue
            truncated = processed
            if is_error:
                subtype = (
                    "permission_denied"
                    if _is_permission_denial(text)
                    else "tool_failure"
                )
            else:
                subtype = "tool_result"
            events.append({
                "session_id": session_id,
                "event_id": _block_event_id(line_num, emitted_index),
                "event_type": "user_message",
                "subtype": subtype,
                "role": role,
                "content": truncated,
                "content_len": content_len,
                "content_ref": None,
                "tool_name": tool_name,
                "tool_input": None,
                "tool_output": truncated,
                "normalized_status": "succeeded" if subtype == "tool_result" else None,
                "timestamp": ts,
                "file_path": None,
                "source_file": source_file,
                "metadata": _event_metadata(record, tool_use_id),
                "source_raw": None,
            })
            _attach_timestamp_state(events[-1], record, ts)
            emitted_index += 1

    persisted = record.get("toolUseResult")
    if isinstance(persisted, dict) and persisted.get("persistedOutputPath"):
        path = Path(str(persisted["persistedOutputPath"])).expanduser().resolve()
        allowed_root = Path(source_file).with_suffix("").resolve()
        result_event = next(
            (event for event in events if event.get("subtype") in {
                "tool_result", "tool_failure", "permission_denied"
            }),
            None,
        )
        try:
            if not path.is_relative_to(allowed_root):
                raise SourceCompatibilityError(
                    f"persisted tool output outside session tree: {path}"
                )
            before = path.stat()
            raw = path.read_bytes()
            after = path.stat()
            if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                raise SourceCompatibilityError(
                    f"persisted tool output changed during read: {path}"
                )
            processor = opts.get("content_processor")
            if processor is not None:
                from codess.content_processing import ContentContext
                decoded = processor.decode(raw, ContentContext(
                    vendor="Claude", record_type="external.tool_result",
                    project_path=opts.get("project_path"),
                    repo_path=opts.get("repo_path"), phase="pre",
                ))
                if not decoded.accepted:
                    _diagnostic(opts, "filtered_records")
                    return events
                full_text = decoded.content
            else:
                full_text = raw.decode("utf-8", errors="replace")
            full_text = apply_sanitization(full_text, opts.get("redact", False))
            extracted, full_len = truncate_content(full_text, TRUNCATE_TOOL_RESULT)
            extracted = _process_text(
                extracted, opts, phase="post", record_type="external.tool_result"
            )
            if extracted is None:
                return events
            expected_size = persisted.get("persistedOutputSize")
            if expected_size is not None and int(expected_size) != len(raw):
                _diagnostic(opts, "external_content_size_mismatch")
            external_id = _block_event_id(line_num, emitted_index)
            external = _base_event(
                session_id=session_id, event_id=external_id,
                event_type="external_content", subtype="persisted_tool_result",
                role="tool", timestamp=ts, source_file=source_file,
            )
            external.update({
                "content": extracted, "content_len": full_len,
                "content_ref": str(path), "file_path": str(path),
                "caused_by_event_id": result_event.get("event_id") if result_event else None,
                "tool_name": result_event.get("tool_name") if result_event else None,
                "event_kind": "content.external", "actor_kind": "tool",
                "content_role": "tool_result_detail", "origin_kind": "tool_generated",
                "metadata": _event_metadata(record, extra={
                    "source_locator": str(path),
                    "content_sha256": hashlib.sha256(raw).hexdigest(),
                    "byte_size": len(raw), "character_length": full_len,
                    "extraction": "complete" if len(extracted) == full_len else "bounded",
                    "media_type": "text/plain",
                }),
            })
            events.append(external)
            external_sources = opts.get("external_sources")
            if external_sources is not None:
                external_sources.append({
                    "path": str(path), "parent_source": source_file,
                    "relation_kind": "persisted_tool_result",
                })
            _diagnostic(opts, "external_content_records")
        except (OSError, UnicodeError, ValueError, SourceCompatibilityError) as exc:
            _diagnostic(opts, "external_content_errors")
            from codess.ingest_review import record_ingest_review
            record_ingest_review(
                opts, exc, source=path, vendor="Claude",
                stage="external_content_extraction",
                record_type="external.tool_result",
            )
            if opts.get("strict_mapping"):
                if isinstance(exc, SourceCompatibilityError):
                    raise
                raise SourceCompatibilityError(
                    f"cannot extract persisted tool output {path}: {exc}"
                ) from exc

    return events


def process_file(
    path: Path,
    session_id: str,
    opts: dict,
) -> Iterator[dict]:
    """Stream events from CC JSONL. Two-pass: build tool_map, then emit events."""
    source_file = str(path.resolve())
    tool_map = _build_tool_map(path)
    diagnostics = opts.get("diagnostics")

    for line_num, record, raw_line in iter_cc_records(path, diagnostics):
        if record.get("type") == "system" and record.get("subtype") == "compact_boundary":
            yield _annotate_source(
                _normalize_compaction(record, line_num, session_id, source_file),
                record,
                line_num,
            )
            continue
        product_state = normalize_product_state(
            record, line_num, session_id, source_file, opts
        )
        if product_state is not None:
            if opts.get("include_product_state", True):
                yield _annotate_source(product_state, record, line_num)
                _diagnostic(opts, "product_state_records")
            else:
                _diagnostic(opts, "known_ignored_records")
            continue
        if should_skip(record):
            _diagnostic(opts, "known_ignored_records")
            continue
        rtype = record.get("type")
        debug = opts.get("debug", False)
        source_raw = (
            raw_line.encode("utf-8", errors="replace")[:512]
            if debug and not opts.get("redact", False)
            else None
        )

        if rtype == "assistant":
            evs, _ = normalize_assistant(record, line_num, session_id, source_file, opts)
            if not evs and diagnostics is not None:
                blocks = (record.get("message") or {}).get("content") or []
                block_types = {
                    block.get("type") for block in blocks
                    if isinstance(block, dict)
                }
                empty_thinking = bool(blocks) and block_types == {"thinking"} and all(
                    not block.get("thinking")
                    for block in blocks if isinstance(block, dict)
                )
                if empty_thinking or block_types == {"fallback"}:
                    diagnostics["known_ignored_records"] = (
                        diagnostics.get("known_ignored_records", 0) + 1
                    )
                    reason = (
                        "empty_reasoning_state_records"
                        if empty_thinking else "fallback_state_records"
                    )
                    diagnostics[reason] = diagnostics.get(reason, 0) + 1
                else:
                    diagnostics["ignored_records"] = (
                        diagnostics.get("ignored_records", 0) + 1
                    )
            for ev in evs:
                if source_raw is not None:
                    ev["source_raw"] = source_raw
                yield _annotate_source(ev, record, line_num)
        elif rtype == "user":
            evs = normalize_user(
                record, line_num, session_id, source_file, tool_map, opts
            )
            if not evs and diagnostics is not None:
                blocks = (record.get("message") or {}).get("content") or []
                if blocks and all(
                    isinstance(block, dict) and block.get("type") == "image"
                    for block in blocks
                ):
                    diagnostics["unsupported_records"] = (
                        diagnostics.get("unsupported_records", 0) + 1
                    )
                    diagnostics["attachment_only_records"] = (
                        diagnostics.get("attachment_only_records", 0) + 1
                    )
                else:
                    diagnostics["ignored_records"] = (
                        diagnostics.get("ignored_records", 0) + 1
                    )
            for ev in evs:
                if source_raw is not None:
                    ev["source_raw"] = source_raw
                yield _annotate_source(ev, record, line_num)
        elif diagnostics is not None:
            diagnostics["unsupported_records"] = (
                diagnostics.get("unsupported_records", 0) + 1
            )
            if opts.get("strict_mapping"):
                raise SourceCompatibilityError(
                    f"unsupported Claude record type: {rtype!r} at {path}:{line_num}"
                )
