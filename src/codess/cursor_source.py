"""Cursor installation discovery and read-only SQLite access.

This module owns vendor storage layout and selective SQL.  The Cursor adapter
owns decoding and normalization; project/scan code should not contain Cursor
paths, table names, or key-range details.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from codess.config import CURSOR_DATA
from codess.helpers import local_path_from_uri

log = logging.getLogger(__name__)


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open a URI-safe, query-only connection that can observe a live WAL."""
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    quoted = table.replace('"', '""')
    return {
        str(row[1]).lower(): str(row[1])
        for row in conn.execute(f'PRAGMA table_info("{quoted}")')
    }


def quoted_column(columns: dict[str, str], name: str) -> str | None:
    actual = columns.get(name.lower())
    return None if actual is None else '"' + actual.replace('"', '""') + '"'


def parse_timestamp(value) -> float | None:
    """Return a plausible Cursor timestamp as Unix milliseconds."""
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


def get_global_db(cursor_data: Path | None = None) -> Path | None:
    data_root = cursor_data or CURSOR_DATA
    db = data_root / "globalStorage" / "state.vscdb"
    return db if db.exists() else None


def get_workspace_ids(
    project_root: Path, cursor_data: Path | None = None,
) -> list[str]:
    """Return local Cursor workspace ids mapped under ``project_root``."""
    project_root = project_root.resolve()
    project_str = str(project_root)
    ws_dir = (cursor_data or CURSOR_DATA) / "workspaceStorage"
    workspace_ids: list[str] = []
    if ws_dir.exists():
        for hash_dir in ws_dir.iterdir():
            if not hash_dir.is_dir():
                continue
            ws_json = hash_dir / "workspace.json"
            if not ws_json.exists():
                continue
            try:
                data = json.loads(ws_json.read_text(encoding="utf-8"))
                local_folder = local_path_from_uri(data.get("folder"))
                folder = str(local_folder) if local_folder else ""
                if folder and (
                    folder == project_str or folder.startswith(project_str + "/")
                ):
                    workspace_ids.append(hash_dir.name)
            except (json.JSONDecodeError, OSError):
                continue

    link_path = project_root / ".codess" / "source-links.json"
    if link_path.exists():
        try:
            links = json.loads(link_path.read_text(encoding="utf-8"))
            if links.get("format") != "codess.source-links/1":
                raise ValueError("unsupported source-link format")
            for link in links.get("links") or []:
                if not isinstance(link, dict):
                    continue
                identity = link.get("source_identity") or {}
                workspace_id = (
                    identity.get("workspace_id")
                    if isinstance(identity, dict) else None
                )
                if (
                    link.get("source_system_id") == "cursor.composer"
                    and link.get("selection_state") == "approved"
                    and workspace_id
                ):
                    workspace_ids.append(str(workspace_id))
        except (OSError, json.JSONDecodeError, ValueError, AttributeError) as exc:
            log.warning("Cannot read Cursor source links from %s: %s", link_path, exc)
    return sorted(set(workspace_ids))


def get_workspace_dbs(
    project_root: Path, cursor_data: Path | None = None,
) -> list[Path]:
    data_root = cursor_data or CURSOR_DATA
    ws_dir = data_root / "workspaceStorage"
    return [
        ws_dir / workspace_id / "state.vscdb"
        for workspace_id in get_workspace_ids(project_root, data_root)
        if (ws_dir / workspace_id / "state.vscdb").exists()
    ]


def get_composer_headers(
    db_path: Path, workspace_ids: set[str] | None = None,
) -> dict[str, dict]:
    """Return composer header metadata, optionally limited to workspace ids."""
    if not db_path.exists() or workspace_ids == set():
        return {}
    try:
        with closing(connect_readonly(db_path)) as conn:
            columns = table_columns(conn, "composerHeaders")
            composer_col = quoted_column(columns, "composerId")
            workspace_col = quoted_column(columns, "workspaceId")
            if composer_col is None or workspace_col is None:
                raise sqlite3.OperationalError(
                    "composerHeaders lacks composerId or workspaceId"
                )

            def optional(name: str) -> str:
                column = quoted_column(columns, name)
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
            return {
                str(composer_id): {
                    "workspace_id": workspace_id,
                    "created_at": created_at,
                    "last_updated_at": last_updated_at,
                    "is_archived": bool(is_archived),
                    "is_subagent": bool(is_subagent),
                }
                for composer_id, workspace_id, created_at, last_updated_at,
                    is_archived, is_subagent in conn.execute(sql, params)
                if composer_id
            }
    except Exception as exc:
        log.warning("Cannot read Cursor composer headers from %s: %s", db_path, exc)
        return {}


def iter_bubble_rows(
    conn: sqlite3.Connection, composer_ids: set[str] | None = None,
) -> Iterator[tuple[str, object]]:
    """Yield raw bubble key/value rows using indexed ranges when scoped."""
    if composer_ids == set():
        return
    if composer_ids is None:
        yield from conn.execute(
            "SELECT key, value FROM cursorDiskKV "
            "WHERE key >= 'bubbleId:' AND key < 'bubbleId;'"
        )
        return
    for composer_id in sorted(composer_ids):
        yield from conn.execute(
            "SELECT key, value FROM cursorDiskKV WHERE key >= ? AND key < ?",
            (f"bubbleId:{composer_id}:", f"bubbleId:{composer_id}:\U0010ffff"),
        )


def iter_bubble_size_rows(
    conn: sqlite3.Connection, composer_ids: set[str] | None = None,
) -> Iterator[tuple[str, int | None]]:
    """Yield bubble key/value sizes without scanning unrelated composers."""
    if composer_ids == set():
        return
    if composer_ids is None:
        yield from conn.execute(
            "SELECT key, length(value) FROM cursorDiskKV "
            "WHERE key >= 'bubbleId:' AND key < 'bubbleId;'"
        )
        return
    for composer_id in sorted(composer_ids):
        yield from conn.execute(
            "SELECT key, length(value) FROM cursorDiskKV WHERE key >= ? AND key < ?",
            (f"bubbleId:{composer_id}:", f"bubbleId:{composer_id}:\U0010ffff"),
        )


def get_db_metrics(db_path: Path, composer_ids: set[str] | None = None) -> dict:
    """Return bubble metrics, selectively when composer ids are supplied."""
    empty = {
        "count": 0, "events": 0, "size_bytes": 0, "invalid_keys": 0,
        "header_count": 0, "timed_header_count": 0, "min_ts": None,
        "max_ts": None, "error": None,
    }
    if not db_path.exists():
        return empty
    try:
        size_bytes = db_path.stat().st_size
    except OSError:
        size_bytes = 0
    try:
        with closing(connect_readonly(db_path)) as conn:
            composers: set[str] = set()
            events = invalid_keys = selected_bytes = 0
            for key, value_size in iter_bubble_size_rows(conn, composer_ids):
                parts = str(key).split(":", 2)
                if len(parts) < 3:
                    invalid_keys += 1
                    continue
                composers.add(parts[1])
                events += 1
                selected_bytes += int(value_size or 0)
            if composer_ids is not None:
                size_bytes = selected_bytes

            min_ts = max_ts = None
            header_count = timed_header_count = 0
            columns = table_columns(conn, "composerHeaders")
            composer_col = quoted_column(columns, "composerId")
            created_col = quoted_column(columns, "createdAt")
            updated_col = quoted_column(columns, "lastUpdatedAt")
            if composer_col and composers:
                ordered = sorted(composers)
                for offset in range(0, len(ordered), 900):
                    chunk = tuple(ordered[offset:offset + 900])
                    placeholders = ",".join("?" for _ in chunk)
                    rows = conn.execute(
                        f"SELECT {created_col or 'NULL'}, {updated_col or 'NULL'} "
                        f"FROM composerHeaders WHERE {composer_col} IN ({placeholders})",
                        chunk,
                    )
                    for created_at, updated_at in rows:
                        header_count += 1
                        parsed_min = parse_timestamp(created_at)
                        parsed_max = parse_timestamp(updated_at) or parsed_min
                        if parsed_min is not None or parsed_max is not None:
                            timed_header_count += 1
                        if parsed_min is not None:
                            min_ts = parsed_min if min_ts is None else min(min_ts, parsed_min)
                        if parsed_max is not None:
                            max_ts = parsed_max if max_ts is None else max(max_ts, parsed_max)
            return {
                "count": len(composers), "events": events,
                "size_bytes": size_bytes, "invalid_keys": invalid_keys,
                "header_count": header_count,
                "timed_header_count": timed_header_count,
                "min_ts": min_ts, "max_ts": max_ts, "error": None,
            }
    except Exception as exc:
        log.warning("Cannot read Cursor metrics from %s: %s", db_path, exc)
        return {**empty, "size_bytes": size_bytes, "error": str(exc)}
