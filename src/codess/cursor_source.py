"""Cursor installation discovery and read-only SQLite access.

**Owns selection.** Vendor storage layout, connections, table names, key
ranges, and every selective SQL statement live here, for the ingest path and
for the feature audit alike. Callers receive selected records and counted
observations; they never open a Cursor database themselves.

Cursor needs more modules than the other vendors because it stores Sessions
in shared SQLite databases rather than per-session files, so selection,
caching, and decode are genuinely separate concerns rather than one read:

| Module | Owns |
|---|---|
| `cursor_source` | Selection: where Cursor stores data and which rows to read |
| `cursor_cohort` | Caching: a reusable, transactionally consistent capture |
| `adapters/cursor` | Decode: selected records to common Events |
| `cursor_feature_audit` | Reporting: which counted evidence an audit states |

No module holds two of these. The adapter in particular keeps no storage
dependency: it imports record accessors from here and no `sqlite3`.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

from codess.config import (
    CURSOR_DATA,
    SOURCE_LINKS_FILE,
    SOURCE_LINKS_FORMAT,
    STORE_DIR,
)
from codess.fileio import open_readonly, quote_identifier
from codess.hashing import codess_digest
from codess.helpers import local_path_from_uri
from codess.timeval import EPOCH_SECONDS_FLOOR, epoch_ms

log = logging.getLogger(__name__)

CURSOR_SELECTION_EDGE_BYTES = 512


def _fingerprint_digest() -> Any:
    """Return the SHA-256 digest used by new selected-row change markers."""
    return codess_digest()


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open a URI-safe, query-only connection that can observe a live WAL."""
    conn = open_readonly(db_path)
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
        immutable = open_readonly(db_path, immutable=True)
        immutable.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone()
        return immutable


def table_columns(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    """Map each of `table`'s columns, lowercased, to its actual spelling.

    Cursor's vendor tables are camelCase and vary by release, so a reader
    matches case-insensitively and then uses the spelling the store reports.
    """
    return {
        str(row[1]).lower(): str(row[1])
        for row in conn.execute(f"PRAGMA table_info({quote_identifier(table)})")
    }


def quoted_column(columns: dict[str, str], name: str) -> str | None:
    """The quoted spelling of `name`, or None if this store has no such column.

    None rather than a raise: an absent column is the ordinary case across
    Cursor releases, and callers project a literal in its place.
    """
    actual = columns.get(name.lower())
    return None if actual is None else quote_identifier(actual)


def parse_timestamp(value: Any) -> float | None:
    """Return a plausible Cursor timestamp as Unix milliseconds.

    Cursor bubbles carry values that are not times at all -- small counters and
    enum codes sit in fields a reader might take for stamps -- so this adds a
    plausibility floor the shared normalizer deliberately does not impose: a
    numeric value below `EPOCH_SECONDS_FLOOR` is rejected rather than scaled.
    Scaling it would manufacture a 1970s instant from a counter.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return None
        if number < EPOCH_SECONDS_FLOOR:
            return None
    return epoch_ms(value)


def open_bubble_rows(
    db_path: Path, composer_ids: set[str] | None = None,
) -> Iterator[tuple[str, object]]:
    """Yield bubble rows from `db_path`, owning the connection.

    The connection-taking iterators below suit callers that already hold one.
    This variant exists so a decoder can ask for rows by path and never touch
    SQLite, which is what keeps vendor storage access in this module.
    """
    with closing(connect_readonly(db_path)) as conn:
        yield from iter_bubble_rows(conn, composer_ids)


def open_message_request_context_rows(
    db_path: Path, composer_ids: set[str] | None = None,
) -> Iterator[tuple[str, object]]:
    """Yield request-context rows from `db_path`, owning the connection."""
    with closing(connect_readonly(db_path)) as conn:
        yield from iter_message_request_context_rows(conn, composer_ids)


def get_global_db(cursor_data: Path | None = None) -> Path | None:
    data_root = cursor_data or CURSOR_DATA
    db = data_root / "globalStorage" / "state.vscdb"
    return db if db.exists() else None


# Keys the Cursor client writes its own version under, in the order they are
# consulted. `startupMetrics.lastVersion` is written at launch and is the most
# direct statement; the other two are maintained by the update and release-notes
# paths and agree with it in every store observed.
_CLIENT_VERSION_KEYS = (
    "cursor.startupMetrics.lastVersion",
    "cursor/localLastActivityClientVersion",
    "releaseNotes/lastVersion",
)


def get_client_version(db_path: Path) -> str | None:
    """The Cursor client version recorded in the global store, or None.

    **What this attests, and what it does not.** Cursor writes its current
    version, not a per-Session one, so this is the version observed when the
    Source was read -- not proof that a given Session ran under it. A Session
    decoded today from a Composer written months ago carries today's client
    version. That is still the best available evidence for attributing a
    decode gap to a release, which is why `harness_version` records it, but a
    reader comparing versions across Sessions in one store will find them
    identical by construction.

    Claude and Codex differ here: both state a version per Session, so their
    `harness_version` is per-Session evidence. Cursor's is per-observation.
    """
    if not db_path.exists():
        return None
    try:
        with closing(connect_readonly(db_path)) as conn:
            columns = table_columns(conn, "ItemTable")
            key_column = quoted_column(columns, "key")
            value_column = quoted_column(columns, "value")
            if key_column is None or value_column is None:
                return None
            for key in _CLIENT_VERSION_KEYS:
                row = conn.execute(
                    f"SELECT {value_column} FROM ItemTable "
                    f"WHERE {key_column}=? LIMIT 1",
                    (key,),
                ).fetchone()
                if row is None or row[0] is None:
                    continue
                value = str(row[0]).strip().strip('"')
                if value:
                    return value
    except sqlite3.Error:
        return None
    return None


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

    link_path = project_path / STORE_DIR / SOURCE_LINKS_FILE
    if link_path.exists():
        try:
            links = json.loads(link_path.read_text(encoding="utf-8"))
            if links.get("format") != SOURCE_LINKS_FORMAT:
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


def subagent_lineage(header_value: object) -> dict[str, Any]:
    """Read the parent a Cursor subagent Composer records, if it names one.

    `isSubagent` says a Composer is delegated work; the identity of what
    delegated it lives in the header's JSON `value` under `subagentInfo`.
    Reading only the flag would set a `subagent` relation on a Session whose parent the
    store never named, asserting a relationship without its evidence.

    Returns an empty mapping when the header records no lineage, so a caller
    can merge it unconditionally and absent stays absent.
    """
    if isinstance(header_value, (bytes, bytearray)):
        header_value = header_value.decode("utf-8", errors="replace")
    if not isinstance(header_value, str) or not header_value:
        return {}
    try:
        head = json.loads(header_value)
    except (TypeError, ValueError):
        return {}
    info = head.get("subagentInfo") if isinstance(head, dict) else None
    if not isinstance(info, dict):
        return {}
    lineage = {
        "parent_composer_id": info.get("parentComposerId"),
        "root_parent_composer_id": info.get("rootParentConversationId"),
        "subagent_type_name": info.get("subagentTypeName"),
        # The tool call that spawned it, which is what links a delegated
        # Session back to the invocation in its parent.
        "spawning_tool_call_id": info.get("toolCallId"),
        "conversation_length_at_spawn": info.get("conversationLengthAtSpawn"),
    }
    return {key: value for key, value in lineage.items() if value is not None}


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
        f"{optional('isArchived')}, {optional('isSubagent')}, "
        f"{optional('value')} "
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
            **subagent_lineage(value),
        }
        for composer_id, workspace_id, created_at, last_updated_at,
            is_archived, is_subagent, value in conn.execute(sql, params)
        if composer_id
    }


CONVERSATION_INDEX_FILE = "conversation-search.db"


def read_conversation_labels(cursor_data: Path | None = None) -> dict[str, dict]:
    """Conversation titles and groupings, keyed by composer id.

    Cursor keeps a search index beside the composer store, holding a `title`,
    a `branches` value, and an `is_archived` flag per conversation. None of
    these appears on a bubble, so a store built from bubbles alone cannot
    report the name the operator sees in the interface -- measured on one
    machine, 57 of 87 ingested Sessions had a title the store did not hold.

    Read-only and best-effort: an absent or unreadable index yields no labels
    rather than an error, because a label qualifies a Session and its absence
    must not stop a decode.
    """
    root = cursor_data or CURSOR_DATA
    if root is None:
        return {}
    path = Path(root) / "globalStorage" / CONVERSATION_INDEX_FILE
    if not path.is_file():
        return {}
    labels: dict[str, dict] = {}
    try:
        with closing(connect_readonly(path)) as conn:
            rows = conn.execute(
                "SELECT id, title, branches, is_archived FROM conversations"
            ).fetchall()
    except sqlite3.Error:
        return {}
    for identity, title, branches, archived in rows:
        if not isinstance(identity, str) or not identity:
            continue
        entry: dict[str, object] = {}
        if isinstance(title, str) and title.strip():
            entry["session_label"] = title.strip()
        if isinstance(branches, str) and branches.strip():
            entry["vendor_group"] = branches.strip()
        if archived:
            entry["is_archived"] = True
        if entry:
            labels[identity] = entry
    return labels


def _headerless_composers(conn: sqlite3.Connection) -> dict[str, dict]:
    """Composers holding bubbles that `composerHeaders` does not list.

    Cursor keeps three indexes of the same composers and they do not agree.
    `composerHeaders` is the smallest; global `composerData:` rows outnumber it,
    and the workspace `composer.composerData` index covers a third set. A
    Session reachable only from an index nothing reads is not decoded at all --
    measured on the development machine, 107 composers hold bubbles without a
    header, and the workspace fallback recovers 75 of them.

    This recovers the remainder from the global `composerData:` row, which
    states `composerId`, `createdAt`, and the composer's own settings. It states
    no `workspaceId`, so a Project binding has to come from elsewhere; that is
    why these are returned separately rather than merged into the header read,
    and why `selection_source` records where each came from.
    """
    if not table_columns(conn, "cursorDiskKV"):
        return {}
    recovered: dict[str, dict] = {}
    for key, value in conn.execute(
        "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'"
    ):
        composer_id = str(key).split(":", 1)[1] if ":" in str(key) else None
        if not composer_id or value is None:
            continue
        try:
            data = json.loads(value)
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        recovered[composer_id] = {
            "workspace_id": None,
            "created_at": data.get("createdAt"),
            "last_updated_at": data.get("lastUpdatedAt"),
            "is_archived": bool(data.get("isArchived")),
            "is_subagent": bool(data.get("isSubagent")),
            "selection_source": "global.composerData",
        }
    return recovered


def _composer_settings(conn: sqlite3.Connection, composer_ids: set[str]) -> dict[str, dict]:
    """Interaction settings each named composer states in `composerData`.

    Cursor records these once per composer rather than per bubble, so they are read here
    rather than during bubble decode. `unifiedMode` also appears on bubbles, but as an
    integer where the composer states a word (`agent`, `chat`); across 3,984 real bubbles
    the integer co-occurred with `agent` alone, so nothing establishes what another value
    would mean and only the composer's spelling is read.
    """
    if not composer_ids or not table_columns(conn, "cursorDiskKV"):
        # Supplementary evidence: a store keeping headers without `cursorDiskKV` still has
        # usable Sessions, so an absent table yields no settings rather than an error.
        return {}
    settings: dict[str, dict] = {}
    for composer_id in sorted(composer_ids):
        row = conn.execute(
            "SELECT value FROM cursorDiskKV WHERE key=? LIMIT 1",
            (f"composerData:{composer_id}",),
        ).fetchone()
        if row is None or row[0] is None:
            continue
        try:
            data = json.loads(row[0])
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        observed: dict[str, object] = {}
        mode = data.get("unifiedMode")
        if isinstance(mode, str) and mode.strip():
            observed["interaction_mode"] = mode.strip()
        model_config = data.get("modelConfig")
        if isinstance(model_config, dict):
            max_mode = model_config.get("maxMode")
            if isinstance(max_mode, bool):
                observed["max_mode"] = max_mode
            # The composer states the model for every composer, where the bubble
            # `modelInfo` the adapter reads carries one on 3,044 of 188,904 records. The
            # richer labels appear only here: `composer-2-fast` and
            # `cursor-grok-4.5-high-fast` name a speed variant no bubble records.
            name = model_config.get("modelName")
            if isinstance(name, str) and name.strip():
                # `model_name` is the composer's current setting, not the model a given
                # message ran under: across 38 composers stating both, 15 disagree --
                # one records `claude-4.6-opus-high-thinking` while every bubble records
                # `composer-1.5`. Last-write-wins for the Session; the per-turn evidence
                # is the bubble's `model_set`.
                observed["model_name"] = name.strip()
                # `default` records the absence of an explicit choice, which is not an
                # unknown model, so it is retained as the selection and withheld as one.
                if name.strip().casefold() != "default":
                    observed["model"] = name.strip()
            # `selectedModels` states parameters beside the model id. A speed
            # parameter is the one the name does not always carry: `composer-2`
            # and `composer-2-fast` are distinct names, but a composer may set
            # `fast` on a model whose name does not say so, and reading only the
            # name would lose it.
            selected = model_config.get("selectedModels")
            if isinstance(selected, list):
                for entry in selected:
                    if not isinstance(entry, dict):
                        continue
                    parameters = entry.get("parameters")
                    if not isinstance(parameters, list):
                        continue
                    for parameter in parameters:
                        if not isinstance(parameter, dict):
                            continue
                        identifier = parameter.get("id")
                        value = parameter.get("value")
                        # The vendor writes the value as a string, so `"true"`
                        # is the assertion and anything else is not: `false`
                        # appears and must not set the tier.
                        if identifier == "fast" and str(value).casefold() == "true":
                            observed["speed"] = "fast"
                        # `store` already reads `effort` into
                        # `reasoning_effort`, and the name does not always
                        # carry it: only the `*-high-*` aliases encode a
                        # strength, while a composer may set one on any model.
                        elif identifier == "effort" and isinstance(value, str) and value.strip():
                            observed["effort"] = value.strip()
        if observed:
            settings[composer_id] = observed
    return settings


def get_composer_headers(
    db_path: Path, workspace_ids: set[str] | None = None,
) -> dict[str, dict]:
    """Return composer header metadata, optionally limited to workspace ids."""
    if not db_path.exists() or workspace_ids == set():
        return {}
    try:
        with closing(connect_readonly(db_path)) as conn:
            headers = _composer_headers(conn, workspace_ids)
            if workspace_ids is None:
                # Only when the caller asked for every composer: a
                # `composerData:` row states no workspace, so it cannot be
                # filtered by one and including it under a workspace selection
                # would widen that selection silently.
                for composer_id, recovered in _headerless_composers(conn).items():
                    headers.setdefault(composer_id, recovered)
            try:
                settings = _composer_settings(conn, set(headers))
            except sqlite3.Error as exc:
                # Settings only qualify the headers, so a failure narrows what is known
                # rather than discarding Sessions the store does contain.
                log.warning("Cannot read Cursor composer settings from %s: %s", db_path, exc)
                settings = {}
            for composer_id, observed in settings.items():
                headers[composer_id].update(observed)
            return headers
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


def _fingerprint_value(digest: Any, value: Any) -> None:
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
            f"cursor-selection-digest-fingerprint:{digest.hexdigest()}"
        ),
        "source_mtime": latest_timestamp,
        "source_size": selected_bytes,
        "fingerprint_method": (
            "cursor-workspace-header-source-key-length-edge-digest-fingerprint-v2"
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
    """Fingerprint several Project selections in one SQLite read snapshot.

    The explicit transaction is one of the two places Codess needs more than the
    deferred default stated in `fileio`. Cursor's database is written by its own
    running application, and a read transaction's snapshot ends with the
    transaction, so fingerprinting several selections across separate
    transactions could read each against a different state of the container and
    produce markers that never described one moment. One `BEGIN` holds one
    snapshot across all of them; the `rollback` ends it without writing.
    """
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


_BUBBLE_ROWS = "key LIKE 'bubbleId:%' AND json_valid(value)"
_BUBBLE_ROWS_JOINED = "kv.key LIKE 'bubbleId:%' AND json_valid(kv.value)"
_REQUEST_CONTEXT_ROWS = (
    "key >= 'messageRequestContext:' AND key < 'messageRequestContext;' "
    "AND json_valid(value)"
)


def _count(conn: sqlite3.Connection, predicate: str) -> int:
    return conn.execute(
        f"SELECT COUNT(*) FROM cursorDiskKV WHERE {predicate}"
    ).fetchone()[0]


def _shape_rows(conn: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(query)]


def read_feature_evidence(db_path: Path) -> dict[str, Any]:
    """Count Cursor tool, model, and context evidence without reading values.

    Structure only: every query counts records or reports field names and JSON
    types, so no message, argument, result, or attachment text is read. That
    boundary is what lets the audit run over a personal store, and it is
    enforced here rather than restated by each caller.

    Lives with source access rather than beside the audit because these are
    vendor table names and key ranges, which this module owns. The audit
    composes the report; deciding how to open the database and which rows
    exist is selection.
    """
    with closing(connect_readonly(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        if not table_columns(conn, "composerHeaders"):
            # Workspace databases hold bubbles but no Composer headers, so
            # the per-workspace grouping below has nothing to join against.
            # Reject by name rather than letting SQLite report a missing
            # table: the audit is scoped to the global store, and the caller
            # chose the file.
            raise ValueError(
                f"not a Cursor global store (no composerHeaders table): {db_path}"
            )
        evidence: dict[str, Any] = {
            "bubble_records": _count(conn, _BUBBLE_ROWS),
            "tool_former_records": _count(
                conn,
                f"{_BUBBLE_ROWS} "
                "AND json_type(value,'$.toolFormerData')='object' "
                "AND COALESCE(json_extract(value,'$.toolFormerData.name'), "
                "json_extract(value,'$.toolFormerData.toolCallId'), "
                "json_extract(value,'$.toolFormerData.status'), "
                "json_extract(value,'$.toolFormerData.rawArgs'), "
                "json_extract(value,'$.toolFormerData.params'), "
                "json_extract(value,'$.toolFormerData.result')) IS NOT NULL",
            ),
            "tool_results_records": _count(
                conn,
                f"{_BUBBLE_ROWS} AND json_type(value,'$.toolResults')='array' "
                "AND json_array_length(json_extract(value,'$.toolResults'))>0",
            ),
            "model_name_records": _count(
                conn,
                f"{_BUBBLE_ROWS} "
                "AND json_type(value,'$.modelInfo.modelName')='text'",
            ),
            "conversation_summary_records": _count(
                conn,
                f"{_BUBBLE_ROWS} "
                "AND json_type(value,'$.conversationSummary')='text'",
            ),
            "context_window_records": _count(
                conn,
                f"{_BUBBLE_ROWS} "
                "AND json_type(value,'$.contextWindowStatusAtCreation')='object'",
            ),
            "request_context_records": _count(conn, _REQUEST_CONTEXT_ROWS),
            "request_context_bytes": conn.execute(
                "SELECT COALESCE(SUM(length(value)),0) FROM cursorDiskKV "
                f"WHERE {_REQUEST_CONTEXT_ROWS}"
            ).fetchone()[0],
        }
        evidence["conversation_summary_stats"] = dict(conn.execute(
            "SELECT "
            "COALESCE(SUM(length(json_extract("
            "json_extract(value,'$.conversationSummary'),'$.summary'))),0) "
            "AS summary_characters, "
            "COALESCE(MAX(length(json_extract("
            "json_extract(value,'$.conversationSummary'),'$.summary'))),0) "
            "AS maximum_summary_characters, "
            "SUM(CASE WHEN json_type(json_extract("
            "value,'$.conversationSummary'),"
            "'$.truncationLastBubbleIdInclusive') IS NOT NULL "
            "THEN 1 ELSE 0 END) AS truncation_boundary_records, "
            "SUM(CASE WHEN json_type(json_extract("
            "value,'$.conversationSummary'),"
            "'$.clientShouldStartSendingFromInclusiveBubbleId') IS NOT NULL "
            "THEN 1 ELSE 0 END) AS restart_boundary_records "
            f"FROM cursorDiskKV WHERE {_BUBBLE_ROWS} "
            "AND json_type(value,'$.conversationSummary')='text' "
            "AND json_valid(json_extract(value,'$.conversationSummary'))"
        ).fetchone())
        evidence["context_window_ranges"] = dict(conn.execute(
            "SELECT "
            "MIN(json_extract(value,'$.contextWindowStatusAtCreation.tokensUsed')) "
            "AS minimum_tokens_used, "
            "MAX(json_extract(value,'$.contextWindowStatusAtCreation.tokensUsed')) "
            "AS maximum_tokens_used, "
            "MIN(json_extract(value,'$.contextWindowStatusAtCreation.tokenLimit')) "
            "AS minimum_token_limit, "
            "MAX(json_extract(value,'$.contextWindowStatusAtCreation.tokenLimit')) "
            "AS maximum_token_limit "
            f"FROM cursorDiskKV WHERE {_BUBBLE_ROWS} "
            "AND json_type(value,'$.contextWindowStatusAtCreation')='object'"
        ).fetchone())
        evidence["request_context_field_shapes"] = _shape_rows(conn, """
            SELECT fields.key AS field, fields.type AS value_type,
                   COUNT(*) AS observations
            FROM cursorDiskKV kv, json_each(kv.value) fields
            WHERE kv.key >= 'messageRequestContext:'
              AND kv.key < 'messageRequestContext;'
              AND json_valid(kv.value)
            GROUP BY fields.key, fields.type
            ORDER BY fields.key, fields.type
        """)
        evidence["workspace_evidence"] = _shape_rows(conn, f"""
            SELECT h.workspaceId AS workspace_id,
              SUM(CASE WHEN json_type(kv.value,'$.toolFormerData')='object'
                AND COALESCE(json_extract(kv.value,'$.toolFormerData.name'),
                  json_extract(kv.value,'$.toolFormerData.toolCallId'),
                  json_extract(kv.value,'$.toolFormerData.status')) IS NOT NULL
                THEN 1 ELSE 0 END) AS tool_former_records,
              SUM(CASE WHEN json_type(kv.value,'$.toolResults')='array'
                AND json_array_length(json_extract(kv.value,'$.toolResults'))>0
                THEN 1 ELSE 0 END) AS nonempty_tool_results_records,
              SUM(CASE WHEN json_type(kv.value,'$.modelInfo.modelName')='text'
                THEN 1 ELSE 0 END) AS model_name_records,
              COUNT(DISTINCT h.composerId) AS composers
            FROM cursorDiskKV kv JOIN composerHeaders h
              ON h.composerId=substr(kv.key,10,instr(substr(kv.key,10),':')-1)
            WHERE {_BUBBLE_ROWS_JOINED}
            GROUP BY h.workspaceId
            HAVING tool_former_records>0 OR model_name_records>0
            ORDER BY tool_former_records DESC, model_name_records DESC
        """)
        evidence["tool_names"] = _shape_rows(conn, f"""
            SELECT json_extract(value,'$.toolFormerData.name') AS tool_name,
                   COUNT(*) AS observations
            FROM cursorDiskKV WHERE {_BUBBLE_ROWS}
              AND json_type(value,'$.toolFormerData')='object'
              AND json_type(value,'$.toolFormerData.name')='text'
            GROUP BY json_extract(value,'$.toolFormerData.name')
            ORDER BY observations DESC, tool_name LIMIT 50
        """)
        evidence["tool_statuses"] = _shape_rows(conn, f"""
            SELECT COALESCE(json_extract(value,'$.toolFormerData.status'),'[absent]')
                     AS source_status,
                   COUNT(*) AS observations
            FROM cursorDiskKV WHERE {_BUBBLE_ROWS}
              AND json_type(value,'$.toolFormerData')='object'
            GROUP BY COALESCE(json_extract(value,'$.toolFormerData.status'),'[absent]')
            ORDER BY observations DESC, source_status
        """)
        evidence["tool_user_decisions"] = _shape_rows(conn, f"""
            SELECT json_extract(value,'$.toolFormerData.userDecision') AS decision,
                   json_extract(value,'$.toolFormerData.status') AS source_status,
                   COUNT(*) AS observations
            FROM cursorDiskKV WHERE {_BUBBLE_ROWS}
              AND json_type(value,'$.toolFormerData.userDecision')='text'
            GROUP BY decision, source_status
            ORDER BY observations DESC, decision, source_status
        """)
        evidence["model_name_values"] = _shape_rows(conn, f"""
            SELECT json_extract(value,'$.modelInfo.modelName') AS model_selection,
                   COUNT(*) AS observations
            FROM cursorDiskKV WHERE {_BUBBLE_ROWS}
              AND json_type(value,'$.modelInfo.modelName')='text'
            GROUP BY json_extract(value,'$.modelInfo.modelName')
            ORDER BY observations DESC, model_selection
        """)
        evidence["model_field_shapes"] = _shape_rows(conn, f"""
            SELECT fields.key AS field, fields.type AS value_type,
                   COUNT(*) AS observations
            FROM cursorDiskKV kv, json_each(kv.value,'$.modelInfo') fields
            WHERE {_BUBBLE_ROWS_JOINED}
              AND json_type(kv.value,'$.modelInfo')='object'
            GROUP BY fields.key, fields.type ORDER BY fields.key, fields.type
        """)
        evidence["tool_field_shapes"] = _shape_rows(conn, f"""
            SELECT fields.key AS field, fields.type AS value_type,
                   COUNT(*) AS observations
            FROM cursorDiskKV kv, json_each(kv.value,'$.toolFormerData') fields
            WHERE {_BUBBLE_ROWS_JOINED}
              AND json_type(kv.value,'$.toolFormerData')='object'
            GROUP BY fields.key, fields.type ORDER BY fields.key, fields.type
        """)
    return evidence


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
