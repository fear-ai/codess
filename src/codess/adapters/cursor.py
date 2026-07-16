"""Cursor SQLite parser and normalizer. Extracts bubbleId messages from state.vscdb."""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from codess.config import TRUNCATE_PROMPT, TRUNCATE_RESPONSE, TRUNCATE_TOOL_RESULT
from codess.content_processing import apply_processing

log = logging.getLogger(__name__)


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open a URI-safe, query-only connection that can observe a live WAL."""
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    """Return lowercase -> actual column names for a fixed internal table."""
    quoted = table.replace('"', '""')
    return {
        str(row[1]).lower(): str(row[1])
        for row in conn.execute(f'PRAGMA table_info("{quoted}")')
    }


def _quoted_column(columns: dict[str, str], name: str) -> str | None:
    actual = columns.get(name.lower())
    if actual is None:
        return None
    return '"' + actual.replace('"', '""') + '"'


def _parse_timestamp(value) -> float | None:
    """Return a Cursor timestamp as Unix milliseconds.

    Bubble ``createdAt`` is normally ISO-8601. Numeric values are accepted only
    when they plausibly represent Unix seconds or milliseconds; small client
    timing values are deliberately rejected.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number >= 1e12:
            return number
        if number >= 1e9:
            return number * 1000
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            dt = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() * 1000
    return None


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
        with closing(_connect_readonly(db_path)) as conn:
            cur = conn.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'")
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


def get_composer_headers(
    db_path: Path,
    workspace_ids: set[str] | None = None,
) -> dict[str, dict]:
    """Return composer header metadata, optionally limited to workspace ids."""
    if not db_path.exists() or workspace_ids == set():
        return {}
    try:
        conn = _connect_readonly(db_path)
        try:
            columns = _table_columns(conn, "composerHeaders")
            composer_col = _quoted_column(columns, "composerId")
            workspace_col = _quoted_column(columns, "workspaceId")
            if composer_col is None or workspace_col is None:
                raise sqlite3.OperationalError(
                    "composerHeaders lacks composerId or workspaceId"
                )

            def optional(name: str) -> str:
                column = _quoted_column(columns, name)
                return f"{column} AS {name}" if column else f"NULL AS {name}"

            sql = (
                f"SELECT {composer_col} AS composerId, "
                f"{workspace_col} AS workspaceId, "
                f"{optional('createdAt')}, {optional('lastUpdatedAt')}, "
                f"{optional('isArchived')}, {optional('isSubagent')} "
                "FROM composerHeaders"
            )
            params: tuple[str, ...] = ()
            if workspace_ids is not None:
                ordered = tuple(sorted(workspace_ids))
                placeholders = ",".join("?" for _ in ordered)
                sql += f" WHERE {workspace_col} IN ({placeholders})"
                params = ordered
            rows = conn.execute(sql, params)
            return {
                str(composer_id): {
                    "workspace_id": workspace_id,
                    "created_at": created_at,
                    "last_updated_at": last_updated_at,
                    "is_archived": bool(is_archived),
                    "is_subagent": bool(is_subagent),
                }
                for (
                    composer_id,
                    workspace_id,
                    created_at,
                    last_updated_at,
                    is_archived,
                    is_subagent,
                ) in rows
                if composer_id
            }
        finally:
            conn.close()
    except Exception as exc:
        log.warning("Cannot read Cursor composer headers from %s: %s", db_path, exc)
        return {}


def get_db_metrics(db_path: Path) -> dict:
    """Return bubble counts, DB size, and header time range from state.vscdb."""
    from contextlib import closing

    if not db_path.exists():
        return {
            "count": 0,
            "events": 0,
            "size_bytes": 0,
            "invalid_keys": 0,
            "header_count": 0,
            "timed_header_count": 0,
            "min_ts": None,
            "max_ts": None,
            "error": None,
        }
    try:
        size_bytes = db_path.stat().st_size
    except OSError:
        size_bytes = 0
    try:
        with closing(_connect_readonly(db_path)) as conn:
            cur = conn.execute(
                "SELECT key FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'"
            )
            composers = set()
            events = 0
            invalid_keys = 0
            for (key,) in cur:
                parts = key.split(":")
                if len(parts) >= 3:
                    composers.add(parts[1])
                    events += 1
                else:
                    invalid_keys += 1
            min_ts = max_ts = None
            header_count = timed_header_count = 0
            try:
                columns = _table_columns(conn, "composerHeaders")
                composer_col = _quoted_column(columns, "composerId")
                created_col = _quoted_column(columns, "createdAt")
                updated_col = _quoted_column(columns, "lastUpdatedAt")
                if composer_col:
                    ordered_composers = sorted(composers)
                    for offset in range(0, len(ordered_composers), 900):
                        composer_chunk = tuple(
                            ordered_composers[offset : offset + 900]
                        )
                        placeholders = ",".join("?" for _ in composer_chunk)
                        created_expr = created_col or "NULL"
                        updated_expr = updated_col or "NULL"
                        rows = conn.execute(
                            f"SELECT {created_expr}, {updated_expr} "
                            "FROM composerHeaders "
                            f"WHERE {composer_col} IN ({placeholders})",
                            composer_chunk,
                        )
                        for created_at, updated_at in rows:
                            header_count += 1
                            parsed_min = _parse_timestamp(created_at)
                            parsed_max = _parse_timestamp(updated_at)
                            if parsed_max is None:
                                parsed_max = parsed_min
                            if parsed_min is not None or parsed_max is not None:
                                timed_header_count += 1
                            if parsed_min is not None:
                                min_ts = (
                                    parsed_min
                                    if min_ts is None
                                    else min(min_ts, parsed_min)
                                )
                            if parsed_max is not None:
                                max_ts = (
                                    parsed_max
                                    if max_ts is None
                                    else max(max_ts, parsed_max)
                                )
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc).lower():
                    log.warning("Cannot read Cursor header metrics from %s: %s", db_path, exc)
        return {
            "count": len(composers),
            "events": events,
            "size_bytes": size_bytes,
            "invalid_keys": invalid_keys,
            "header_count": header_count,
            "timed_header_count": timed_header_count,
            "min_ts": min_ts,
            "max_ts": max_ts,
            "error": None,
        }
    except Exception as exc:
        log.warning("Cannot read Cursor metrics from %s: %s", db_path, exc)
        return {
            "count": 0,
            "events": 0,
            "size_bytes": size_bytes,
            "invalid_keys": 0,
            "header_count": 0,
            "timed_header_count": 0,
            "min_ts": None,
            "max_ts": None,
            "error": str(exc),
        }


def _iter_bubbles(
    db_path: Path,
    stats: dict[str, int] | None = None,
    composer_ids: set[str] | None = None,
) -> Iterator[tuple[str, str, dict]]:
    """Yield (composer_id, bubble_id, message_dict) from cursorDiskKV bubbleId keys."""
    if composer_ids == set():
        return
    conn = _connect_readonly(db_path)
    try:
        if composer_ids is None:
            rows = conn.execute(
                "SELECT key, value FROM cursorDiskKV "
                "WHERE key LIKE 'bubbleId:%'"
            )
        else:
            rows = (
                row
                for selected_id in sorted(composer_ids)
                for row in conn.execute(
                    "SELECT key, value FROM cursorDiskKV "
                    "WHERE key >= ? AND key < ?",
                    (
                        f"bubbleId:{selected_id}:",
                        f"bubbleId:{selected_id}:\U0010ffff",
                    ),
                )
            )
        for key, value in rows:
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
                yield composer_id, bubble_id, data
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
) -> Iterator[tuple[str, dict]]:
    """Stream (session_id, event) from Cursor state.vscdb. Groups by composerId."""
    source_file = str(db_path.resolve())
    redact_enabled = opts.get("redact", False)
    diagnostics = opts.get("diagnostics")
    stats: dict[str, int] = {}

    by_composer: dict[str, list[tuple[str, dict]]] = {}
    for composer_id, bubble_id, data in _iter_bubbles(
        db_path,
        stats,
        composer_ids,
    ):
        if composer_id not in by_composer:
            by_composer[composer_id] = []
        by_composer[composer_id].append((bubble_id, data))

    for composer_id, bubbles in by_composer.items():
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
        bubbles = without_server_identity + list(canonical.values())
        bubbles.sort(key=sort_key)
        for bubble_id, data in bubbles:
            events = list(
                _bubble_to_events(
                    composer_id, bubble_id, data, source_file, opts
                )
            )
            if not events and diagnostics is not None:
                diagnostics["ignored_records"] = (
                    diagnostics.get("ignored_records", 0) + 1
                )
            for ev in events:
                yield composer_id, ev

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
        yield base_ev("user_message", subtype, "user", truncated, content_len)
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
            yield base_ev(
                "assistant_message", "response", "assistant",
                truncated, content_len,
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
            yield ev
