"""session-ingest CLI command."""

import json
import logging
import sys
from pathlib import Path

from config import get_state_path, get_store_path, MIN_SESSION_FILE_SIZE
from ingest.cc_adapter import process_file as process_cc_file
from ingest.codex_adapter import get_session_meta, process_file as process_codex_file
from ingest.cursor_adapter import process_db as process_cursor_db
from ingest.project import (
    get_cc_session_dir,
    get_codex_session_files,
    get_cursor_global_db,
    get_cursor_workspace_dbs,
    get_project_root,
)
from ingest.store import (
    connect,
    init_db,
    load_ingest_state,
    save_ingest_state,
    should_ingest,
    upsert_event,
    upsert_session,
)

log = logging.getLogger(__name__)


def _ingest_cc(project_root: Path, store_path: Path, state_path: Path, opts: dict, force: bool, min_size: int) -> tuple[int, int]:
    """Ingest CC. Return (sessions_added, events_added)."""
    cc_dir = get_cc_session_dir(project_root)
    if cc_dir is None:
        return 0, 0
    ingested, total_events = 0, 0
    jsonl_files = sorted(cc_dir.glob("*.jsonl"))
    for path in jsonl_files:
        try:
            st = path.stat()
            mtime = st.st_mtime
            if st.st_size < min_size:
                continue
        except OSError as e:
            log.warning("Cannot stat %s: %s", path, e)
            continue
        if not should_ingest(state_path, str(path.resolve()), mtime, force):
            continue
        session_id = path.stem
        conn = connect(store_path)
        events_list = []
        try:
            for event in process_cc_file(path, session_id, opts):
                upsert_event(conn, event)
                events_list.append(event)
                total_events += 1
            if events_list:
                timestamps = [e["timestamp"] for e in events_list if e.get("timestamp") is not None]
                started_at = min(timestamps) if timestamps else mtime * 1000
                ended_at = max(timestamps) if timestamps else mtime * 1000
                session = {
                    "id": session_id,
                    "source": "Claude",
                    "type": "Code",
                    "release": None,
                    "release_value": None,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "project_path": str(project_root),
                    "metadata": None,
                }
                upsert_session(conn, session)
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.exception("Ingest failed for %s: %s", path, e)
            raise
        finally:
            conn.close()
        state = load_ingest_state(state_path)
        state[str(path.resolve())] = mtime
        save_ingest_state(state_path, state)
        ingested += 1
    return ingested, total_events


def _ingest_codex(project_root: Path, store_path: Path, state_path: Path, opts: dict, force: bool, min_size: int) -> tuple[int, int]:
    """Ingest Codex. Return (sessions_added, events_added)."""
    files = get_codex_session_files(project_root)
    ingested, total_events = 0, 0
    for path in files:
        try:
            st = path.stat()
            mtime = st.st_mtime
            if st.st_size < min_size:
                continue
        except OSError as e:
            log.warning("Cannot stat %s: %s", path, e)
            continue
        if not should_ingest(state_path, str(path.resolve()), mtime, force):
            continue
        session_id, proj_path = get_session_meta(path)
        conn = connect(store_path)
        events_list = []
        try:
            for event in process_codex_file(path, session_id, proj_path, opts):
                upsert_event(conn, event)
                events_list.append(event)
                total_events += 1
            if events_list:
                timestamps = [e["timestamp"] for e in events_list if e.get("timestamp") is not None]
                started_at = min(timestamps) if timestamps else mtime * 1000
                ended_at = max(timestamps) if timestamps else mtime * 1000
                session = {
                    "id": session_id,
                    "source": "Codex",
                    "type": "Code",
                    "release": None,
                    "release_value": None,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "project_path": proj_path if proj_path != "." else str(project_root),
                    "metadata": None,
                }
                upsert_session(conn, session)
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.exception("Ingest failed for %s: %s", path, e)
            raise
        finally:
            conn.close()
        state = load_ingest_state(state_path)
        state[str(path.resolve())] = mtime
        save_ingest_state(state_path, state)
        ingested += 1
    return ingested, total_events


def _ingest_cursor(
    project_root: Path,
    store_path: Path,
    state_path: Path,
    opts: dict,
    force: bool,
    cursor_global: bool = False,
) -> tuple[int, int]:
    """Ingest Cursor. Return (sessions_added, events_added)."""
    proj_str = str(project_root.resolve())
    ingested, total_events = 0, 0

    if not cursor_global:
        dbs = get_cursor_workspace_dbs(project_root)
        for db_path in dbs:
            try:
                mtime = db_path.stat().st_mtime
            except OSError as e:
                log.warning("Cannot stat %s: %s", db_path, e)
                continue
            state_key = f"cursor:{db_path.resolve()}"
            if not should_ingest(state_path, state_key, mtime, force):
                continue
            conn = connect(store_path)
            sessions_events: dict[str, list[dict]] = {}
            try:
                for session_id, event in process_cursor_db(db_path, proj_str, opts):
                    upsert_event(conn, event)
                    total_events += 1
                    if session_id not in sessions_events:
                        sessions_events[session_id] = []
                    sessions_events[session_id].append(event)
                for session_id, evs in sessions_events.items():
                    timestamps = [e["timestamp"] for e in evs if e.get("timestamp") is not None]
                    ts = min(timestamps) if timestamps else mtime * 1000
                    ts_end = max(timestamps) if timestamps else mtime * 1000
                    session = {
                        "id": session_id,
                        "source": "Cursor",
                        "type": "IDE",
                        "release": None,
                        "release_value": None,
                        "started_at": ts,
                        "ended_at": ts_end,
                        "project_path": proj_str,
                        "metadata": None,
                    }
                    upsert_session(conn, session)
                conn.commit()
            except Exception as e:
                conn.rollback()
                log.exception("Ingest failed for %s: %s", db_path, e)
                raise
            finally:
                conn.close()
            state = load_ingest_state(state_path)
            state[state_key] = mtime
            save_ingest_state(state_path, state)
            ingested += len(sessions_events)

    if cursor_global or ingested == 0:
        global_db = get_cursor_global_db()
        if global_db is not None:
            try:
                mtime = global_db.stat().st_mtime
            except OSError as e:
                log.warning("Cannot stat %s: %s", global_db, e)
            else:
                state_key = f"cursor:global:{global_db.resolve()}"
                if should_ingest(state_path, state_key, mtime, force):
                    conn = connect(store_path)
                    sessions_events: dict[str, list[dict]] = {}
                    try:
                        for session_id, event in process_cursor_db(
                            global_db, "", opts
                        ):
                            upsert_event(conn, event)
                            total_events += 1
                            if session_id not in sessions_events:
                                sessions_events[session_id] = []
                            sessions_events[session_id].append(event)
                        for session_id, evs in sessions_events.items():
                            timestamps = [
                                e["timestamp"]
                                for e in evs
                                if e.get("timestamp") is not None
                            ]
                            ts = min(timestamps) if timestamps else mtime * 1000
                            ts_end = max(timestamps) if timestamps else mtime * 1000
                            session = {
                                "id": session_id,
                                "source": "Cursor",
                                "type": "IDE",
                                "release": None,
                                "release_value": None,
                                "started_at": ts,
                                "ended_at": ts_end,
                                "project_path": None,
                                "metadata": json.dumps({"storage": "global"}),
                            }
                            upsert_session(conn, session)
                        conn.commit()
                    except Exception as e:
                        conn.rollback()
                        log.exception(
                            "Ingest failed for global %s: %s", global_db, e
                        )
                        raise
                    finally:
                        conn.close()
                    state = load_ingest_state(state_path)
                    state[state_key] = mtime
                    save_ingest_state(state_path, state)
                    ingested += len(sessions_events)

    return ingested, total_events


def run(args) -> int:
    """Run session-ingest. Returns exit code."""
    project_root = Path(args.project) if args.project else get_project_root()
    project_root = project_root.resolve()

    source = getattr(args, "source", "all")
    if source == "cc":
        sources = ["cc"]
    elif source == "codex":
        sources = ["codex"]
    elif source == "cursor":
        sources = ["cursor"]
    else:
        sources = ["cc", "codex", "cursor"]

    store_path = get_store_path(project_root)
    state_path = get_state_path(project_root)
    init_db(store_path)

    opts = {
        "debug": getattr(args, "debug", False),
        "redact": getattr(args, "redact", False),
    }
    force = getattr(args, "force", False)
    min_size = getattr(args, "min_size", MIN_SESSION_FILE_SIZE)

    total_ingested = 0
    total_events = 0

    if "cc" in sources:
        cc_dir = get_cc_session_dir(project_root)
        if cc_dir is None and source == "cc":
            print(f"No CC project dir for {project_root}", file=sys.stderr)
            return 1
        if cc_dir is not None:
            n, e = _ingest_cc(project_root, store_path, state_path, opts, force, min_size)
            total_ingested += n
            total_events += e

    if "codex" in sources:
        n, e = _ingest_codex(project_root, store_path, state_path, opts, force, min_size)
        total_ingested += n
        total_events += e

    if "cursor" in sources:
        cursor_global = getattr(args, "cursor_global", False)
        n, e = _ingest_cursor(
            project_root, store_path, state_path, opts, force, cursor_global
        )
        total_ingested += n
        total_events += e

    conn = connect(store_path)
    try:
        overall_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        overall_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        conn.close()

    print(f"Ingested {total_ingested} session(s), {total_events} event(s)")
    print(f"Added: {total_ingested} sessions, {total_events} events | Overall: {overall_sessions} sessions, {overall_events} events")
    return 0
