"""CC JSONL parser and normalizer."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from codess.config import (
    TRUNCATE_DIALOG,
    TRUNCATE_GREP_PATTERN,
    TRUNCATE_RESPONSE,
    TRUNCATE_TOOL_RESULT,
)
from codess.sanitize import apply_sanitization

log = logging.getLogger(__name__)

SKIP_TYPES = frozenset({
    "progress", "file-history-snapshot", "queue-operation", "last-prompt", "system",
})


def iter_cc_records(path: Path) -> Iterator[tuple[int, dict, str]]:
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
                log.warning("JSON error at %s:%d: %s", path, line_num, e)
                continue


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


def extract_tool_input(tool_name: str, input_obj: dict) -> dict:
    """Per-tool field selection per CSPlan §3.3 extract_tool_input."""
    if not input_obj:
        return {}
    out = {}
    name = (tool_name or "").lower()
    if name == "bash":
        if "command" in input_obj:
            out["command"] = input_obj["command"]
    elif name == "read":
        for k in ("path", "offset", "limit"):
            if k in input_obj:
                out[k] = input_obj[k]
    elif name in ("edit", "write"):
        for k in ("path", "old_len", "new_len", "content_len"):
            if k in input_obj:
                out[k] = input_obj[k]
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
        for k in ("subagent_type", "description"):
            if k in input_obj:
                out[k] = input_obj[k]
        if "prompt" in input_obj:
            p = input_obj["prompt"]
            if isinstance(p, str) and len(p) > 200:
                out["prompt"] = p[:199] + "…"
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
            if isinstance(p, str) and len(p) > 200:
                out["prompt"] = p[:199] + "…"
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
    for _line_num, record, _ in iter_cc_records(path):
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


def _get_timestamp(record: dict) -> float | None:
    """Extract timestamp from record or message. Returns Unix ms."""
    ts = record.get("timestamp") or record.get("message", {}).get("timestamp")
    return _parse_timestamp(ts)


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
    content = record.get("message", {}).get("content") or []
    role = record.get("message", {}).get("role", "assistant")
    ts = _get_timestamp(record)
    redact_enabled = opts.get("redact", False)

    # Build tool_map from tool_use blocks
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tid = block.get("id")
            tname = block.get("name")
            if tid and tname:
                tool_map[tid] = tname

    # Check for tool_use in content (for dialog vs response)
    has_tool_use = any(
        isinstance(b, dict) and b.get("type") == "tool_use" for b in content
    )
    stop_reason = record.get("message", {}).get("stop_reason", "")

    for i, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        btype = block.get("type")

        if btype == "text":
            text = block.get("text") or ""
            text = apply_sanitization(text, redact_enabled)
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
            events.append({
                "session_id": session_id,
                "event_id": str(line_num),
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
                "metadata": None,
                "source_raw": None,
            })

        elif btype == "tool_use":
            tname = block.get("name")
            tinput = block.get("input") or {}
            tool_input = extract_tool_input(tname or "", tinput)
            events.append({
                "session_id": session_id,
                "event_id": str(line_num),
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
                "file_path": tool_input.get("path") if isinstance(tool_input, dict) else None,
                "source_file": source_file,
                "metadata": None,
                "source_raw": None,
            })

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
    content = record.get("message", {}).get("content") or []
    role = record.get("message", {}).get("role", "user")
    ts = _get_timestamp(record)
    redact_enabled = opts.get("redact", False)

    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")

        if btype == "text":
            text = block.get("text") or ""
            text = apply_sanitization(text, redact_enabled)
            subtype = "slash_command" if text.strip().startswith("/") else "prompt"
            events.append({
                "session_id": session_id,
                "event_id": str(line_num),
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
                "metadata": None,
                "source_raw": None,
            })

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
            text = apply_sanitization(text, redact_enabled)
            truncated, content_len = truncate_content(text, TRUNCATE_TOOL_RESULT)
            subtype = "permission_denied" if is_error else "tool_result"
            events.append({
                "session_id": session_id,
                "event_id": str(line_num),
                "event_type": "user_message",
                "subtype": subtype,
                "role": role,
                "content": truncated,
                "content_len": content_len,
                "content_ref": None,
                "tool_name": tool_name,
                "tool_input": None,
                "tool_output": truncated,
                "timestamp": ts,
                "file_path": None,
                "source_file": source_file,
                "metadata": None,
                "source_raw": None,
            })

    return events


def process_file(
    path: Path,
    session_id: str,
    opts: dict,
) -> Iterator[dict]:
    """Stream events from CC JSONL. Two-pass: build tool_map, then emit events."""
    source_file = str(path.resolve())
    tool_map = _build_tool_map(path)

    for line_num, record, raw_line in iter_cc_records(path):
        if should_skip(record):
            continue
        rtype = record.get("type")
        debug = opts.get("debug", False)
        source_raw = raw_line.encode("utf-8", errors="replace")[:512] if debug else None

        if rtype == "assistant":
            evs, _ = normalize_assistant(record, line_num, session_id, source_file, opts)
            for ev in evs:
                if source_raw is not None:
                    ev["source_raw"] = source_raw
                yield ev
        elif rtype == "user":
            evs = normalize_user(
                record, line_num, session_id, source_file, tool_map, opts
            )
            for ev in evs:
                if source_raw is not None:
                    ev["source_raw"] = source_raw
                yield ev
