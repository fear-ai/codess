"""Codex JSONL parser and normalizer."""

import json
import logging
from pathlib import Path
from typing import Iterator

from config import TRUNCATE_PROMPT, TRUNCATE_RESPONSE, TRUNCATE_TOOL_RESULT
from ingest.sanitize import apply_sanitization

log = logging.getLogger(__name__)


def iter_codex_records(path: Path) -> Iterator[tuple[int, dict, str]]:
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
                log.warning("JSON error at %s:%d: %s", path, line_num, e)
                continue


def get_session_meta(path: Path) -> tuple[str, str]:
    """Return (session_id, project_path) from first session_meta. Fallback to filename stem and '.'."""
    for _line_num, record, _ in iter_codex_records(path):
        if record.get("type") == "session_meta":
            payload = record.get("payload") or {}
            sid = payload.get("id")
            cwd = payload.get("cwd")
            return (
                str(sid) if sid else path.stem,
                str(cwd) if cwd else ".",
            )
    return path.stem, "."


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

    for line_num, record, raw_line in iter_codex_records(path):
        rtype = record.get("type")
        payload = record.get("payload") or {}
        ts = record.get("timestamp")
        if isinstance(ts, (int, float)):
            timestamp = float(ts) * 1000 if ts < 1e12 else float(ts)
        else:
            timestamp = None

        source_raw = raw_line.encode("utf-8", errors="replace")[:512] if debug else None

        if rtype == "session_meta":
            continue

        if rtype == "response_item":
            item_type = payload.get("type", "")
            if item_type != "message":
                continue
            role = payload.get("role", "")
            content = payload.get("content") or []
            text = _extract_text_from_content(content)
            text = apply_sanitization(text, redact_enabled)

            if role == "user":
                subtype = "slash_command" if text.strip().startswith("/") else "prompt"
                truncated, content_len = _truncate(text, TRUNCATE_PROMPT)
                ev = {
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
                yield ev
            elif role == "developer":
                truncated, content_len = _truncate(text, TRUNCATE_RESPONSE)
                ev = {
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
                yield ev

        elif rtype == "event_msg":
            msg_type = payload.get("type", "")
            if msg_type == "token_count":
                continue
            if msg_type in ("user_message", "turn_aborted"):
                pass
            content = str(payload.get("info", payload))
            truncated, content_len = _truncate(content, 500)
            ev = {
                "session_id": session_id,
                "event_id": str(line_num),
                "event_type": "assistant_message",
                "subtype": "dialog",
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
