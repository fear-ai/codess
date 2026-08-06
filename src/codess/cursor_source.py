"""Cursor installation discovery and read-only SQLite access.

This module owns vendor storage layout and selective SQL.  The Cursor adapter
owns decoding and normalization; project/scan code should not contain Cursor
paths, table names, or key-range details.

# ruff S608 exemption: CoPlan.md 10.4.2.3
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from codess.config import CURSOR_DATA
from codess.helpers import local_path_from_uri

log = logging.getLogger(__name__)

CURSOR_SELECTION_EDGE_BYTES = 512


def _fingerprint_digest():
    """Return the SHA-256 digest used by new selected-row change markers."""
    return hashlib.sha256()


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open a URI-safe, query-only connection that can observe a live WAL."""
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        conn.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone()
        return conn
    except sqlite3.OperationalError:
        conn.close()
        # Some Cursor workspace DBs are standalone, contain no Composer rows,
        # and cannot be opened in ordinary read-only mode despite having no WAL
        # sidecars. Immutable mode is safe only for that sidecar-free shape.
        if Path(str(db_path) + "-wal").exists() or Path(str(db_path) + "-shm").exists():
            raise
        immutable = sqlite3.connect(
            db_path.resolve().as_uri() + "?mode=ro&immutable=1",
            uri=True,
            timeout=5,
        )
        immutable.execute("PRAGMA query_only = ON")
        immutable.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone()
        return immutable


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
    project_path: Path, cursor_data: Path | None = None,
) -> list[str]:
    """Return local Cursor workspace ids mapped under ``project_path``."""
    project_path = project_path.resolve()
    project_str = str(project_path)
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

    link_path = project_path / ".codess" / "source-links.json"
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
    project_path: Path, cursor_data: Path | None = None,
) -> list[Path]:
    data_root = cursor_data or CURSOR_DATA
    ws_dir = data_root / "workspaceStorage"
    return [
        ws_dir / workspace_id / "state.vscdb"
        for workspace_id in get_workspace_ids(project_path, data_root)
        if (ws_dir / workspace_id / "state.vscdb").exists()
    ]


def _composer_headers(
    conn: sqlite3.Connection, workspace_ids: set[str] | None,
) -> dict[str, dict]:
    """Read selected headers through an existing SQLite snapshot."""
    if workspace_ids == set():
        return {}
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
            "selection_source": "composerHeaders",
        }
        for composer_id, workspace_id, created_at, last_updated_at,
            is_archived, is_subagent in conn.execute(sql, params)
        if composer_id
    }


def get_composer_headers(
    db_path: Path, workspace_ids: set[str] | None = None,
) -> dict[str, dict]:
    """Return composer header metadata, optionally limited to workspace ids."""
    if not db_path.exists() or workspace_ids == set():
        return {}
    try:
        with closing(connect_readonly(db_path)) as conn:
            return _composer_headers(conn, workspace_ids)
    except Exception as exc:
        log.warning("Cannot read Cursor composer headers from %s: %s", db_path, exc)
        return {}


def get_workspace_composer_headers(
    project_path: Path, cursor_data: Path | None = None,
    *,
    diagnostics: dict[str, int] | None = None,
) -> dict[str, dict]:
    """Recover workspace-bound composers absent from global composerHeaders.

    Older Cursor state can retain ``composer.composerData`` in the workspace
    database after removing the corresponding global header.  This is vendor
    workspace evidence, not a path/content inference.  Current global headers
    remain authoritative when the two indexes overlap.
    """
    data_root = cursor_data or CURSOR_DATA
    workspace_root = data_root / "workspaceStorage"
    recovered: dict[str, dict] = {}
    for workspace_id in get_workspace_ids(project_path, data_root):
        db_path = workspace_root / workspace_id / "state.vscdb"
        if not db_path.exists():
            continue
        try:
            with closing(connect_readonly(db_path)) as conn:
                columns = table_columns(conn, "ItemTable")
                key_column = quoted_column(columns, "key")
                value_column = quoted_column(columns, "value")
                if key_column is None or value_column is None:
                    continue
                row = conn.execute(
                    f"SELECT {value_column} FROM ItemTable "
                    f"WHERE {key_column}='composer.composerData' LIMIT 1"
                ).fetchone()
                if row is None or row[0] is None:
                    continue
                value = json.loads(row[0])
                composers = value.get("allComposers", []) if isinstance(value, dict) else []
                if not isinstance(composers, list):
                    continue
                for item in composers:
                    if not isinstance(item, dict) or not item.get("composerId"):
                        continue
                    composer_id = str(item["composerId"])
                    header = {
                        "workspace_id": workspace_id,
                        "created_at": item.get("createdAt"),
                        "last_updated_at": item.get("lastUpdatedAt"),
                        "is_archived": bool(item.get("isArchived")),
                        "is_subagent": bool(item.get("isSubagent")),
                        "selection_source": "workspace.composerData",
                    }
                    previous = recovered.get(composer_id)
                    if previous is not None and previous.get("ambiguous"):
                        continue
                    if (
                        previous is not None
                        and previous.get("workspace_id") != workspace_id
                    ):
                        log.warning(
                            "Cursor composer %s occurs in multiple selected workspace indexes; "
                            "excluding ambiguous fallback mapping",
                            composer_id,
                        )
                        recovered[composer_id] = {"ambiguous": True}
                        if diagnostics is not None:
                            key = "cursor_ambiguous_fallback_composers"
                            diagnostics[key] = diagnostics.get(key, 0) + 1
                    elif previous is None:
                        recovered[composer_id] = header
        except (OSError, sqlite3.Error, json.JSONDecodeError, TypeError) as exc:
            log.warning(
                "Cannot read Cursor workspace composer index from %s: %s",
                db_path,
                exc,
            )
    return {
        composer_id: header
        for composer_id, header in recovered.items()
        if not header.get("ambiguous")
    }


def get_project_composer_headers(
    global_db: Path, project_path: Path, cursor_data: Path | None = None,
    *,
    diagnostics: dict[str, int] | None = None,
) -> dict[str, dict]:
    """Combine current global headers with workspace-index fallbacks."""
    workspace_ids = set(get_workspace_ids(project_path, cursor_data))
    fallback = get_workspace_composer_headers(
        project_path, cursor_data, diagnostics=diagnostics
    )
    current = get_composer_headers(global_db, workspace_ids)
    fallback.update(current)
    return fallback


def _fingerprint_value(digest, value: Any) -> None:
    """Add one typed, length-delimited SQLite value to a digest."""
    if value is None:
        kind, encoded = b"null", b""
    elif isinstance(value, bytes):
        kind, encoded = b"bytes", value
    elif isinstance(value, str):
        kind = b"text"
        encoded = value.encode("utf-8", errors="surrogatepass")
    else:
        kind = type(value).__name__.encode("ascii", errors="replace")
        encoded = str(value).encode("utf-8")
    digest.update(kind + b":" + str(len(encoded)).encode("ascii") + b":")
    digest.update(encoded)
    digest.update(b"\0")


def get_sqlite_container_marker(db_path: Path) -> dict[str, Any]:
    """Return a cheap non-authenticating main/WAL change prefilter."""
    files = []
    for role, path in (("main", db_path), ("wal", Path(str(db_path) + "-wal"))):
        try:
            stat = path.stat()
        except FileNotFoundError:
            files.append({"role": role, "exists": False})
            continue
        files.append({
            "role": role,
            "exists": True,
            "inode": stat.st_ino,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        })
    return {
        "method": "sqlite-main-wal-inode-size-mtime-ns",
        "files": files,
    }


def _selection_marker(
    conn: sqlite3.Connection,
    workspace_ids: set[str],
    *,
    all_headers: dict[str, dict] | None = None,
    selected_headers: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """Fingerprint one Project selection inside an existing transaction."""
    headers = (
        selected_headers
        if selected_headers is not None
        else _composer_headers(conn, workspace_ids)
        if all_headers is None
        else {
            composer_id: header
            for composer_id, header in all_headers.items()
            if header.get("workspace_id") in workspace_ids
        }
    )

    digest = _fingerprint_digest()
    selected_bytes = bubble_count = request_context_count = 0
    latest_timestamp: float | None = None
    for workspace_id in sorted(workspace_ids):
        _fingerprint_value(digest, "workspace")
        _fingerprint_value(digest, workspace_id)
    for composer_id in sorted(headers):
        header = headers[composer_id]
        _fingerprint_value(digest, "header")
        _fingerprint_value(digest, composer_id)
        for name in (
            "workspace_id", "created_at", "last_updated_at",
            "is_archived", "is_subagent", "selection_source",
        ):
            _fingerprint_value(digest, name)
            _fingerprint_value(digest, header.get(name))
        for candidate in (
            parse_timestamp(header.get("created_at")),
            parse_timestamp(header.get("last_updated_at")),
        ):
            if candidate is not None:
                latest_timestamp = (
                    candidate if latest_timestamp is None
                    else max(latest_timestamp, candidate)
                )
        lower = f"bubbleId:{composer_id}:"
        upper = f"bubbleId:{composer_id}:\U0010ffff"
        rows = conn.execute(
            "SELECT key, length(value), "
            "CAST(substr(value, 1, ?) AS BLOB), "
            "CAST(substr(value, -?) AS BLOB) "
            "FROM cursorDiskKV WHERE key >= ? AND key < ? ORDER BY key",
            (
                CURSOR_SELECTION_EDGE_BYTES, CURSOR_SELECTION_EDGE_BYTES,
                lower, upper,
            ),
        )
        for key, value_size, leading, trailing in rows:
            bubble_count += 1
            selected_bytes += int(value_size or 0)
            _fingerprint_value(digest, "bubble")
            _fingerprint_value(digest, key)
            _fingerprint_value(digest, value_size)
            _fingerprint_value(digest, leading)
            _fingerprint_value(digest, trailing)
        context_lower = f"messageRequestContext:{composer_id}:"
        context_upper = (
            f"messageRequestContext:{composer_id}:\U0010ffff"
        )
        context_rows = conn.execute(
            "SELECT key, length(value), "
            "CAST(substr(value, 1, ?) AS BLOB), "
            "CAST(substr(value, -?) AS BLOB) "
            "FROM cursorDiskKV WHERE key >= ? AND key < ? ORDER BY key",
            (
                CURSOR_SELECTION_EDGE_BYTES, CURSOR_SELECTION_EDGE_BYTES,
                context_lower, context_upper,
            ),
        )
        for key, value_size, leading, trailing in context_rows:
            request_context_count += 1
            selected_bytes += int(value_size or 0)
            _fingerprint_value(digest, "message_request_context")
            _fingerprint_value(digest, key)
            _fingerprint_value(digest, value_size)
            _fingerprint_value(digest, leading)
            _fingerprint_value(digest, trailing)
    return {
        "source_revision": (
            f"cursor-selection-sha256-fingerprint:{digest.hexdigest()}"
        ),
        "source_mtime": latest_timestamp,
        "source_size": selected_bytes,
        "fingerprint_method": (
            "cursor-workspace-header-source-key-length-edge-sha256-fingerprint-v2"
        ),
        "consistency": "sqlite-read-transaction",
        "workspace_count": len(workspace_ids),
        "composer_count": len(headers),
        "bubble_count": bubble_count,
        "message_request_context_count": request_context_count,
        "edge_bytes": CURSOR_SELECTION_EDGE_BYTES,
    }


def get_selection_markers(
    db_path: Path,
    selections: dict[str, set[str]],
    *,
    supplemental_headers: dict[str, dict[str, dict]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Fingerprint several Project selections in one SQLite read snapshot."""
    if not selections:
        return {}
    with closing(connect_readonly(db_path)) as conn:
        conn.execute("BEGIN")
        all_headers = _composer_headers(
            conn, set().union(*selections.values())
        )
        try:
            return {
                project: _selection_marker(
                    conn,
                    workspace_ids,
                    all_headers=all_headers,
                    selected_headers={
                        **(supplemental_headers or {}).get(project, {}),
                        **{
                            composer_id: header
                            for composer_id, header in all_headers.items()
                            if header.get("workspace_id") in workspace_ids
                        },
                    },
                )
                for project, workspace_ids in selections.items()
            }
        finally:
            conn.rollback()


def get_selection_marker(
    db_path: Path, workspace_ids: set[str],
) -> dict[str, Any]:
    """Fingerprint only Cursor rows consumed by one Project ingest.

    Header fields are hashed exactly. Every selected bubble contributes its
    key, byte length, and bounded leading/trailing value bytes. This is a fast
    non-authenticating invalidation guard, not raw-object integrity evidence.
    All fields come from one SQLite read transaction, including live WAL state.
    """
    return get_selection_markers(
        db_path, {"selection": workspace_ids}
    )["selection"]


def iter_bubble_rows(
    conn: sqlite3.Connection, composer_ids: set[str] | None = None,
) -> Iterator[tuple[str, object]]:
    """Yield raw bubble key/value rows using indexed ranges when scoped."""
    if composer_ids == set():
        return
    if composer_ids is None:
        yield from conn.execute(
            "SELECT key, value FROM cursorDiskKV "
            "WHERE key >= 'bubbleId:' AND key < 'bubbleId;' ORDER BY key"
        )
        return
    for composer_id in sorted(composer_ids):
        yield from conn.execute(
            "SELECT key, value FROM cursorDiskKV "
            "WHERE key >= ? AND key < ? ORDER BY key",
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


def iter_message_request_context_rows(
    conn: sqlite3.Connection, composer_ids: set[str] | None = None,
) -> Iterator[tuple[str, object]]:
    """Yield Cursor's separately stored per-message request-context records."""
    if composer_ids == set():
        return
    if composer_ids is None:
        yield from conn.execute(
            "SELECT key, value FROM cursorDiskKV "
            "WHERE key >= 'messageRequestContext:' "
            "AND key < 'messageRequestContext;' ORDER BY key"
        )
        return
    for composer_id in sorted(composer_ids):
        yield from conn.execute(
            "SELECT key, value FROM cursorDiskKV "
            "WHERE key >= ? AND key < ? ORDER BY key",
            (
                f"messageRequestContext:{composer_id}:",
                f"messageRequestContext:{composer_id}:\U0010ffff",
            ),
        )


def has_bubble_rows(db_path: Path) -> bool:
    """Return whether a workspace DB has any Composer bubble record."""
    with closing(connect_readonly(db_path)) as conn:
        return conn.execute(
            "SELECT 1 FROM cursorDiskKV "
            "WHERE key >= 'bubbleId:' AND key < 'bubbleId;' LIMIT 1"
        ).fetchone() is not None


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
