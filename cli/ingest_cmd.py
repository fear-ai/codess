"""session-ingest CLI command."""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import get_state_path, get_stats_path, get_store_path, MIN_SESSION_SIZE
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
    # Main sessions only (top-level uuid.jsonl); exclude subagents (uuid/subagents/*.jsonl)
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
        rel = path.relative_to(cc_dir)
        session_id = str(rel.with_suffix("")).replace("/", ":")
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

    if cursor_global:
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


def _save_stats(project_root: Path, registry_root: Path, source_stats: dict) -> None:
    """Append/update project stats in ingested_projects.json."""
    stats_path = get_stats_path(registry_root)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if stats_path.exists():
        try:
            data = json.loads(stats_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    projects = data.get("projects", [])
    proj_str = str(project_root.resolve())
    now = datetime.now(timezone.utc).isoformat()
    entry = {"path": proj_str, "last_ingestion": now, "sources": source_stats}
    # Replace or append
    projects = [p for p in projects if p.get("path") != proj_str]
    projects.append(entry)
    data["projects"] = projects
    data["updated"] = now
    stats_path.write_text(json.dumps(data, indent=2))


def run(args) -> int:
    """Run session-ingest. Returns exit code."""
    project_root = Path(args.project) if args.project else get_project_root()
    project_root = project_root.resolve()
    legacy = getattr(args, "legacy", False)
    registry_root = Path(args.registry) if getattr(args, "registry", None) else project_root

    source = getattr(args, "source", "all")
    if source == "cc":
        sources = ["cc"]
    elif source == "codex":
        sources = ["codex"]
    elif source == "cursor":
        sources = ["cursor"]
    else:
        sources = ["cc", "codex", "cursor"]

    state_path = get_state_path(project_root)
    opts = {
        "debug": getattr(args, "debug", False),
        "redact": getattr(args, "redact", False),
    }
    force = getattr(args, "force", False)
    min_size = getattr(args, "min_size", MIN_SESSION_SIZE)

    total_ingested = 0
    total_events = 0
    source_stats = {}

    def _store_path(src: str) -> Path:
        if legacy:
            return get_store_path(project_root)
        return get_store_path(project_root, {"cc": "Claude", "codex": "Codex", "cursor": "Cursor"}[src])

    if legacy:
        init_db(get_store_path(project_root))

    if "cc" in sources:
        store_path = _store_path("cc")
        if not legacy:
            init_db(store_path)
        cc_dir = get_cc_session_dir(project_root)
        if cc_dir is None and source == "cc":
            print(f"No CC project dir for {project_root}", file=sys.stderr)
            return 1
        if cc_dir is not None:
            n, e = _ingest_cc(project_root, store_path, state_path, opts, force, min_size)
            total_ingested += n
            total_events += e
        if store_path.exists():
            conn = connect(store_path)
            try:
                s = conn.execute("SELECT COUNT(*) FROM sessions WHERE source='Claude'").fetchone()[0] if legacy else conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                ev = conn.execute("SELECT COUNT(*) FROM events e JOIN sessions s ON e.session_id=s.id WHERE s.source='Claude'").fetchone()[0] if legacy else conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                source_stats["Claude"] = {"sessions": s, "events": ev, "last_ingestion": datetime.now(timezone.utc).isoformat()}
            finally:
                conn.close()

    if "codex" in sources:
        store_path = _store_path("codex")
        if not legacy:
            init_db(store_path)
        n, e = _ingest_codex(project_root, store_path, state_path, opts, force, min_size)
        total_ingested += n
        total_events += e
        if store_path.exists():
            conn = connect(store_path)
            try:
                s = conn.execute("SELECT COUNT(*) FROM sessions WHERE source='Codex'").fetchone()[0] if legacy else conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                ev = conn.execute("SELECT COUNT(*) FROM events e JOIN sessions s ON e.session_id=s.id WHERE s.source='Codex'").fetchone()[0] if legacy else conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                source_stats["Codex"] = {"sessions": s, "events": ev, "last_ingestion": datetime.now(timezone.utc).isoformat()}
            finally:
                conn.close()

    if "cursor" in sources:
        store_path = _store_path("cursor")
        if not legacy:
            init_db(store_path)
        cursor_global = getattr(args, "cursor_global", False)
        n, e = _ingest_cursor(
            project_root, store_path, state_path, opts, force, cursor_global
        )
        total_ingested += n
        total_events += e
        if store_path.exists():
            conn = connect(store_path)
            try:
                s = conn.execute("SELECT COUNT(*) FROM sessions WHERE source='Cursor'").fetchone()[0] if legacy else conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                ev = conn.execute("SELECT COUNT(*) FROM events e JOIN sessions s ON e.session_id=s.id WHERE s.source='Cursor'").fetchone()[0] if legacy else conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                source_stats["Cursor"] = {"sessions": s, "events": ev, "last_ingestion": datetime.now(timezone.utc).isoformat()}
            finally:
                conn.close()

    if source_stats:
        _save_stats(project_root, registry_root, source_stats)

    overall_sessions = sum(s["sessions"] for s in source_stats.values())
    overall_events = sum(s["events"] for s in source_stats.values())

    print(f"Ingested {total_ingested} session(s), {total_events} event(s)")
    print(f"Added: {total_ingested} sessions, {total_events} events | Overall: {overall_sessions} sessions, {overall_events} events")
    return 0
