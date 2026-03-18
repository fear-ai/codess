"""Cursor SQLite parser and normalizer. Extracts bubbleId messages from state.vscdb."""

import json
import logging
from pathlib import Path
from typing import Iterator

from config import TRUNCATE_PROMPT, TRUNCATE_RESPONSE, TRUNCATE_TOOL_RESULT
from ingest.sanitize import apply_sanitization

log = logging.getLogger(__name__)


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


def _iter_bubbles(db_path: Path) -> Iterator[tuple[str, str, dict]]:
    """Yield (composer_id, bubble_id, message_dict) from cursorDiskKV bubbleId keys."""
    import sqlite3

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.execute(
            "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'"
        )
        for key, value in cur:
            if value is None:
                continue
            parts = key.split(":")
            if len(parts) < 3:
                continue
            composer_id, bubble_id = parts[1], parts[2]
            try:
                data = json.loads(value)
            except json.JSONDecodeError:
                try:
                    import base64
                    decoded = base64.b64decode(value)
                    data = json.loads(decoded)
                except Exception:
                    continue
            if isinstance(data, dict):
                yield composer_id, bubble_id, data
    finally:
        conn.close()


def process_db(
    db_path: Path,
    project_path: str,
    opts: dict,
) -> Iterator[tuple[str, dict]]:
    """Stream (session_id, event) from Cursor state.vscdb. Groups by composerId."""
    source_file = str(db_path.resolve())
    redact_enabled = opts.get("redact", False)

    by_composer: dict[str, list[tuple[str, dict]]] = {}
    for composer_id, bubble_id, data in _iter_bubbles(db_path):
        if composer_id not in by_composer:
            by_composer[composer_id] = []
        by_composer[composer_id].append((bubble_id, data))

    for composer_id, bubbles in by_composer.items():
        bubbles.sort(
            key=lambda x: x[1].get("timingInfo", {}).get("clientStartTime", 0)
        )
        for bubble_id, data in bubbles:
            for ev in _bubble_to_events(
                composer_id, bubble_id, data, source_file, redact_enabled
            ):
                yield composer_id, ev


def _bubble_to_events(
    composer_id: str,
    bubble_id: str,
    data: dict,
    source_file: str,
    redact: bool,
) -> Iterator[dict]:
    """Convert bubble to normalized event(s). Yields 0 or more events."""
    msg_type = data.get("type", 0)
    event_id = f"{composer_id}:{bubble_id}"
    text = data.get("text") or ""
    text = apply_sanitization(text, redact)
    ts = data.get("timingInfo", {}).get("clientStartTime")
    timestamp = float(ts) if ts else None

    def base_ev(etype: str, subtype: str, role: str, content: str, content_len: int):
        return {
            "session_id": composer_id,
            "event_id": event_id,
            "event_type": etype,
            "subtype": subtype,
            "role": role,
            "content": content,
            "content_len": content_len,
            "content_ref": None,
            "tool_name": None,
            "tool_input": None,
            "tool_output": None,
            "timestamp": timestamp,
            "file_path": None,
            "source_file": source_file,
            "metadata": None,
            "source_raw": None,
        }

    if msg_type == 1:
        subtype = "slash_command" if text.strip().startswith("/") else "prompt"
        truncated, content_len = _truncate(text, TRUNCATE_PROMPT)
        yield base_ev("user_message", subtype, "user", truncated, content_len)
        return

    if msg_type == 2:
        truncated, content_len = _truncate(text, TRUNCATE_RESPONSE)
        subtype = "response" if text.strip() else "dialog"
        yield base_ev("assistant_message", subtype, "assistant", truncated, content_len)

        tool_results = data.get("toolResults") or []
        for i, tr in enumerate(tool_results):
            tname = tr.get("toolName") or "unknown"
            result = tr.get("result")
            result_str = str(result) if result is not None else ""
            result_str = apply_sanitization(result_str, redact)
            ttrunc, tlen = _truncate(result_str, TRUNCATE_TOOL_RESULT)
            ev = base_ev("user_message", "tool_result", "user", ttrunc, tlen)
            ev["event_id"] = f"{event_id}:tr{i}"
            ev["tool_name"] = tname
            ev["tool_output"] = ttrunc
            yield ev
