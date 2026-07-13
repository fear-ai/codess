"""Codex JSONL parser and normalizer."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from codess.config import TRUNCATE_PROMPT, TRUNCATE_RESPONSE, TRUNCATE_TOOL_RESULT
from codess.sanitize import apply_sanitization, sanitize_value

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


def _build_call_map(path: Path) -> dict[str, str]:
    """Map tool call ids to names so later output records retain identity."""
    calls = {}
    for _line_num, record, _raw in iter_codex_records(path, warn=False):
        if record.get("type") != "response_item":
            continue
        payload = record.get("payload") or {}
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


def _failed_status(payload: dict) -> bool:
    return str(payload.get("status") or "").lower() in {
        "failed", "failure", "error", "incomplete",
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

    for line_num, record, raw_line in iter_codex_records(path, diagnostics):
        rtype = record.get("type")
        payload = record.get("payload") or {}
        timestamp = _parse_timestamp(record.get("timestamp"))

        source_raw = (
            raw_line.encode("utf-8", errors="replace")[:512]
            if debug and not redact_enabled
            else None
        )

        if rtype == "session_meta":
            if diagnostics is not None:
                diagnostics["ignored_records"] = (
                    diagnostics.get("ignored_records", 0) + 1
                )
            continue

        if rtype == "response_item":
            item_type = payload.get("type", "")
            if item_type == "message":
                role = payload.get("role", "")
                content = payload.get("content") or []
                text = _extract_text_from_content(content)
                text = apply_sanitization(text, redact_enabled)

                if role == "user":
                    subtype = "slash_command" if text.strip().startswith("/") else "prompt"
                    truncated, content_len = _truncate(text, TRUNCATE_PROMPT)
                    yield {
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
                        "metadata": None,
                        "source_raw": source_raw,
                    }
                elif role == "assistant":
                    truncated, content_len = _truncate(text, TRUNCATE_RESPONSE)
                    yield {
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
                        "metadata": None,
                        "source_raw": source_raw,
                    }
                elif diagnostics is not None:
                    diagnostics["ignored_records"] = (
                        diagnostics.get("ignored_records", 0) + 1
                    )
                continue

            if item_type in ("function_call", "custom_tool_call"):
                yield {
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
                    "metadata": _metadata(payload),
                    "source_raw": source_raw,
                }
                continue

            if item_type == "web_search_call":
                action = sanitize_value(
                    payload.get("action") or {}, redact_enabled
                )
                yield {
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
                    "metadata": _metadata(payload),
                    "source_raw": source_raw,
                }
                continue

            if item_type in ("function_call_output", "custom_tool_call_output"):
                call_id = payload.get("call_id")
                output = payload.get("output")
                if isinstance(output, str):
                    text = output
                else:
                    text = json.dumps(output, ensure_ascii=False)
                text = apply_sanitization(text, redact_enabled)
                truncated, content_len = _truncate(text, TRUNCATE_TOOL_RESULT)
                yield {
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
                    "metadata": _metadata(payload),
                    "source_raw": source_raw,
                }
                continue

            if diagnostics is not None:
                diagnostics["ignored_records"] = (
                    diagnostics.get("ignored_records", 0) + 1
                )
            continue

        elif rtype == "event_msg":
            msg_type = payload.get("type", "")
            if msg_type != "turn_aborted":
                if diagnostics is not None:
                    diagnostics["ignored_records"] = (
                        diagnostics.get("ignored_records", 0) + 1
                    )
                continue
            content = str(payload.get("reason") or payload.get("info") or "turn aborted")
            content = apply_sanitization(content, redact_enabled)
            truncated, content_len = _truncate(content, 500)
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
            yield ev
        elif diagnostics is not None:
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
