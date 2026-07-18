"""Cursor SQLite parser and normalizer. Extracts bubbleId messages from state.vscdb."""

import json
import logging
import time
from pathlib import Path
from typing import Iterator

from codess.config import TRUNCATE_PROMPT, TRUNCATE_RESPONSE, TRUNCATE_TOOL_RESULT
from codess.content_processing import apply_processing
from codess.cursor_source import (
    connect_readonly,
    iter_bubble_rows,
    parse_timestamp as _parse_timestamp,
)
from codess.mapping import annotate_mapping, structured_json

log = logging.getLogger(__name__)

_MAPPED_BUBBLE_FIELDS = frozenset({
    "type", "text", "createdAt", "timingInfo", "serverBubbleId",
    "toolFormerData", "toolResults", "modelInfo",
})
_PROGRESS_ROWS = 1000
_PROGRESS_SECONDS = 5.0


def _bubble_timestamp(data: dict) -> float | None:
    """Use event creation time, with an epoch-only legacy timing fallback."""
    timestamp = _parse_timestamp(data.get("createdAt"))
    if timestamp is not None:
        return timestamp
    timing = data.get("timingInfo") or {}
    if isinstance(timing, dict):
        return _parse_timestamp(timing.get("clientStartTime"))
    return None


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


def get_composer_data(db_path: Path) -> list[dict]:
    """Decode composerData keys from cursorDiskKV. Returns list of {composer_id, keys, has_conversation, ...}.
    Based on: legel gist, Cursor forum; composerData can be None for some entries."""
    import base64
    from contextlib import closing

    if not db_path.exists():
        return []
    out = []
    try:
        with closing(connect_readonly(db_path)) as conn:
            cur = conn.execute(
                "SELECT key, value FROM cursorDiskKV "
                "WHERE key >= 'composerData:' AND key < 'composerData;'"
            )
            for key, value in cur:
                composer_id = key.split(":", 1)[1] if ":" in key else key
                entry = {"composer_id": composer_id, "key": key, "value_null": value is None}
                if value is None:
                    out.append(entry)
                    continue
                try:
                    data = json.loads(value)
                except json.JSONDecodeError:
                    try:
                        data = json.loads(base64.b64decode(value).decode("utf-8", errors="replace"))
                    except Exception:
                        entry["decode_error"] = True
                        out.append(entry)
                        continue
                if isinstance(data, dict):
                    entry["top_keys"] = list(data.keys())
                    entry["has_conversation"] = "conversation" in data and len(data.get("conversation") or []) > 0
                    # Known/possible fields from forums, OSS: conversation, workspaceRoot?, ...
                    for k in ("workspaceRoot", "workspace", "folder", "projectPath"):
                        if k in data:
                            entry[k] = data[k]
                out.append(entry)
    except Exception as exc:
        log.warning("Cannot read Cursor composer data from %s: %s", db_path, exc)
    return out


def _iter_bubbles(
    db_path: Path,
    stats: dict[str, int] | None = None,
    composer_ids: set[str] | None = None,
) -> Iterator[tuple[str, str, dict]]:
    """Yield (composer_id, bubble_id, message_dict) from cursorDiskKV bubbleId keys."""
    if composer_ids == set():
        return
    conn = connect_readonly(db_path)
    try:
        for key, value in iter_bubble_rows(conn, composer_ids):
            if stats is not None:
                stats["rows"] = stats.get("rows", 0) + 1
            if value is None:
                if stats is not None:
                    stats["null_values"] = stats.get("null_values", 0) + 1
                continue
            parts = key.split(":", 2)
            if len(parts) < 3:
                if stats is not None:
                    stats["invalid_keys"] = stats.get("invalid_keys", 0) + 1
                continue
            composer_id, bubble_id = parts[1], parts[2]
            try:
                data = json.loads(value)
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                try:
                    import base64
                    decoded = base64.b64decode(value)
                    data = json.loads(decoded)
                except Exception:
                    if stats is not None:
                        stats["decode_errors"] = stats.get("decode_errors", 0) + 1
                    continue
            if isinstance(data, dict):
                if stats is not None:
                    stats["yielded"] = stats.get("yielded", 0) + 1
                # Large attachment/context envelopes are not mapped. Drop them
                # before composer-level ordering/deduplication retains records.
                projected = {
                    key: data[key] for key in _MAPPED_BUBBLE_FIELDS if key in data
                }
                yield composer_id, bubble_id, projected
            elif stats is not None:
                stats["non_objects"] = stats.get("non_objects", 0) + 1
    finally:
        conn.close()


def process_db(
    db_path: Path,
    project_path: str,
    opts: dict,
    *,
    composer_ids: set[str] | None = None,
    source_file: str | None = None,
) -> Iterator[tuple[str, dict]]:
    """Stream (session_id, event) from Cursor state.vscdb. Groups by composerId."""
    source_file = source_file or str(db_path.resolve())
    diagnostics = opts.get("diagnostics")
    stats: dict[str, int] = {}
    progress = opts.get("progress")

    current_composer: str | None = None
    bubbles: list[tuple[str, dict]] = []
    composer_started: float | None = None
    last_progress: float | None = None

    def emit(event: str, **fields) -> None:
        if progress is not None:
            progress(
                event, project=project_path, source=source_file,
                composer_id=current_composer, **fields,
            )

    def finish_read() -> None:
        if current_composer is None:
            return
        emit(
            "cursor.composer.read.done", bubbles=len(bubbles),
            phase_seconds=(
                round(time.monotonic() - composer_started, 3)
                if composer_started is not None else None
            ),
        )

    for composer_id, bubble_id, data in _iter_bubbles(
        db_path,
        stats,
        composer_ids,
    ):
        if current_composer is not None and composer_id != current_composer:
            finish_read()
            yield from _process_composer(
                current_composer, bubbles, source_file, opts, diagnostics
            )
            bubbles.clear()
        if composer_id != current_composer:
            current_composer = composer_id
            composer_started = last_progress = time.monotonic()
            emit("cursor.composer.read.start")
        bubbles.append((bubble_id, data))
        now = time.monotonic()
        if len(bubbles) % _PROGRESS_ROWS == 0 or (
            last_progress is not None
            and now - last_progress >= _PROGRESS_SECONDS
        ):
            emit(
                "cursor.composer.read.progress", bubbles=len(bubbles),
                phase_seconds=round(now - composer_started, 3),
            )
            last_progress = now
    if current_composer is not None:
        finish_read()
        yield from _process_composer(
            current_composer, bubbles, source_file, opts, diagnostics
        )

    skipped = sum(
        stats.get(key, 0)
        for key in ("null_values", "invalid_keys", "decode_errors", "non_objects")
    )
    if skipped:
        if diagnostics is not None:
            diagnostics["malformed_records"] = (
                diagnostics.get("malformed_records", 0) + skipped
            )
        log.warning(
            "Cursor skipped %d/%d bubble rows from %s "
            "(null=%d invalid_key=%d decode=%d non_object=%d)",
            skipped,
            stats.get("rows", 0),
            db_path,
            stats.get("null_values", 0),
            stats.get("invalid_keys", 0),
            stats.get("decode_errors", 0),
            stats.get("non_objects", 0),
        )
    elif opts.get("debug"):
        log.debug(
            "Cursor decoded %d bubble rows from %s",
            stats.get("yielded", 0),
            db_path,
        )


def _process_composer(
    composer_id: str,
    bubbles: list[tuple[str, dict]],
    source_file: str,
    opts: dict,
    diagnostics: dict[str, int] | None,
) -> Iterator[tuple[str, dict]]:
    """Order/deduplicate one composer so other composers can be released."""
    def sort_key(item: tuple[str, dict]) -> tuple[bool, float, str]:
        timestamp = _bubble_timestamp(item[1])
        return timestamp is None, timestamp or 0, item[0]

    canonical: dict[tuple[object, str], tuple[str, dict]] = {}
    without_server_identity: list[tuple[str, dict]] = []
    duplicate_count = 0
    for item in bubbles:
        server_bubble_id = item[1].get("serverBubbleId")
        if not server_bubble_id:
            without_server_identity.append(item)
            continue
        key = (item[1].get("type"), str(server_bubble_id))
        previous = canonical.get(key)
        if previous is None or sort_key(item) < sort_key(previous):
            canonical[key] = item
        if previous is not None:
            duplicate_count += 1
    if duplicate_count and diagnostics is not None:
        diagnostics["duplicate_records"] = (
            diagnostics.get("duplicate_records", 0) + duplicate_count
        )
    ordered = without_server_identity + list(canonical.values())
    ordered.sort(key=sort_key)
    for bubble_id, data in ordered:
        events = list(
            _bubble_to_events(composer_id, bubble_id, data, source_file, opts)
        )
        if not events and diagnostics is not None:
            diagnostics["ignored_records"] = (
                diagnostics.get("ignored_records", 0) + 1
            )
        for event in events:
            yield composer_id, event


def _bubble_to_events(
    composer_id: str,
    bubble_id: str,
    data: dict,
    source_file: str,
    opts: dict | bool,
) -> Iterator[dict]:
    """Convert bubble to normalized event(s). Yields 0 or more events."""
    msg_type = data.get("type", 0)
    event_id = f"{composer_id}:{bubble_id}"
    if isinstance(opts, bool):
        opts = {"redact": opts}
    text = data.get("text") or ""
    timestamp = _bubble_timestamp(data)

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

    def mapped(event: dict, rule: str, source_path: str = "$.bubble") -> dict:
        return annotate_mapping(
            event,
            source_record_type="cursorDiskKV.bubble",
            source_record_subtype=str(msg_type),
            source_record_locator=f"bubbleId:{composer_id}:{bubble_id}",
            mapping_rule=rule,
            source_path=source_path,
        )

    if msg_type == 1:
        text = apply_processing(
            text, opts, vendor="Cursor", record_type="bubble.user",
            event_kind="message.prompt", phase="pre",
        )
        if text is None:
            return
        subtype = "slash_command" if text.strip().startswith("/") else "prompt"
        truncated, content_len = _truncate(text, TRUNCATE_PROMPT)
        truncated = apply_processing(
            truncated, opts, vendor="Cursor", record_type="bubble.user",
            event_kind="message.prompt", phase="post",
        )
        if truncated is None:
            return
        event = base_ev("user_message", subtype, "user", truncated, content_len)
        model_info = data.get("modelInfo")
        if isinstance(model_info, dict):
            selection = model_info.get("modelName")
            if isinstance(selection, str) and selection.strip():
                metadata = {"model_selection": selection.strip()}
                if selection.strip().lower() != "default":
                    metadata["model"] = selection.strip()
                    metadata["configuration_provenance"] = {
                        "model": {
                            "source_record_type": "bubble.user",
                            "source_record_locator": event_id,
                            "source_field": "modelInfo.modelName",
                        }
                    }
                event["metadata"] = json.dumps(metadata, separators=(",", ":"))
        yield mapped(event, "cursor.bubble")
        return

    if msg_type == 2:
        if text.strip():
            text = apply_processing(
                text, opts, vendor="Cursor", record_type="bubble.assistant",
                event_kind="message.response", phase="pre",
            )
        if text and text.strip():
            truncated, content_len = _truncate(text, TRUNCATE_RESPONSE)
            truncated = apply_processing(
                truncated, opts, vendor="Cursor", record_type="bubble.assistant",
                event_kind="message.response", phase="post",
            )
            if truncated is None:
                return
            yield mapped(
                base_ev(
                    "assistant_message", "response", "assistant",
                    truncated, content_len,
                ),
                "cursor.bubble",
            )

        tool_former = data.get("toolFormerData")
        if isinstance(tool_former, dict):
            tool_name = tool_former.get("name")
            call_id = tool_former.get("toolCallId") or f"{event_id}:toolFormerData"
            status = str(tool_former.get("status") or "unknown")
            has_tool_evidence = any(
                tool_former.get(key) not in (None, "")
                for key in ("name", "toolCallId", "rawArgs", "params", "result", "status")
            )
            if has_tool_evidence:
                raw_input = tool_former.get("rawArgs")
                if raw_input in (None, ""):
                    raw_input = tool_former.get("params")
                input_text = "" if raw_input is None else (
                    json.dumps(raw_input, ensure_ascii=False, separators=(",", ":"))
                    if isinstance(raw_input, (dict, list)) else str(raw_input)
                )
                input_text = apply_processing(
                    input_text, opts, vendor="Cursor", record_type="tool_input",
                    event_kind="tool.call", phase="pre",
                )
                normalized = {
                    "completed": "succeeded", "complete": "succeeded",
                    "error": "failed", "failed": "failed",
                    "loading": "running", "running": "running",
                    "pending": "pending", "cancelled": "cancelled",
                }.get(status.lower(), "unknown")
                user_decision = str(tool_former.get("userDecision") or "").lower()
                if user_decision == "rejected":
                    normalized = "denied"
                metadata_values = {
                    "call_id": str(call_id),
                    "model_call_id": tool_former.get("modelCallId"),
                    "status": status,
                    "source_field": "toolFormerData",
                }
                if user_decision:
                    metadata_values.update({
                        "user_decision": user_decision,
                        "permission_provenance": "toolFormerData.userDecision",
                    })
                metadata = json.dumps(metadata_values, separators=(",", ":"))
                call = base_ev("tool_call", "tool_call", "assistant", "", 0)
                call["event_id"] = f"{event_id}:tool-call"
                call["tool_name"] = str(tool_name or "unknown")
                call["tool_input"] = structured_json(input_text)
                call["metadata"] = metadata
                call["source_status"] = status
                call["normalized_status"] = normalized
                yield mapped(
                    call,
                    "cursor.tool-former-invocation",
                    "$.bubble.toolFormerData",
                )

                result_value = tool_former.get("result")
                final_status = normalized in {"succeeded", "failed", "denied", "cancelled", "incomplete"}
                if result_value is not None or final_status:
                    result_text = "" if result_value is None else str(result_value)
                    result_text = apply_processing(
                        result_text, opts, vendor="Cursor", record_type="tool_result",
                        event_kind="tool.result", phase="pre",
                    )
                    if result_text is not None:
                        result_text, result_len = _truncate(result_text, TRUNCATE_TOOL_RESULT)
                        result_text = apply_processing(
                            result_text, opts, vendor="Cursor", record_type="tool_result",
                            event_kind="tool.result", phase="post",
                        )
                        if result_text is not None:
                            result = base_ev(
                                "user_message",
                                (
                                    "permission_denied" if normalized == "denied"
                                    else "tool_failure" if normalized == "failed"
                                    else "tool_result"
                                ),
                                "tool", result_text, result_len,
                            )
                            result["event_id"] = f"{event_id}:tool-result"
                            result["tool_name"] = str(tool_name or "unknown")
                            result["tool_output"] = result_text
                            result["metadata"] = metadata
                            result["source_status"] = status
                            result["normalized_status"] = normalized
                            yield mapped(
                                result,
                                "cursor.tool-former-result",
                                "$.bubble.toolFormerData",
                            )

        tool_results = data.get("toolResults") or []
        for i, tr in enumerate(tool_results):
            tname = tr.get("toolName") or "unknown"
            result = tr.get("result")
            result_str = str(result) if result is not None else ""
            result_str = apply_processing(
                result_str, opts, vendor="Cursor", record_type="tool_result",
                event_kind="tool.result", phase="pre",
            )
            if result_str is None:
                continue
            ttrunc, tlen = _truncate(result_str, TRUNCATE_TOOL_RESULT)
            ttrunc = apply_processing(
                ttrunc, opts, vendor="Cursor", record_type="tool_result",
                event_kind="tool.result", phase="post",
            )
            if ttrunc is None:
                continue
            ev = base_ev("user_message", "tool_result", "user", ttrunc, tlen)
            ev["event_id"] = f"{event_id}:tr{i}"
            ev["tool_name"] = tname
            ev["tool_output"] = ttrunc
            yield mapped(
                ev,
                "cursor.tool-result-legacy",
                f"$.bubble.toolResults[{i}]",
            )
