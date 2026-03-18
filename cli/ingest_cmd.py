"""session-ingest CLI command."""

import logging
import sys
from pathlib import Path

from config import get_state_path, get_store_path, MIN_SESSION_FILE_SIZE
from ingest.cc_adapter import process_file
from ingest.project import get_cc_session_dir, get_project_root
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


def run(args) -> int:
    """Run session-ingest. Returns exit code."""
    project_root = Path(args.project) if args.project else get_project_root()
    project_root = project_root.resolve()

    cc_dir = get_cc_session_dir(project_root)
    if cc_dir is None:
        print(f"No CC project dir for {project_root}", file=sys.stderr)
        return 1

    store_path = get_store_path(project_root)
    state_path = get_state_path(project_root)
    init_db(store_path)

    opts = {
        "debug": getattr(args, "debug", False),
        "redact": getattr(args, "redact", False),
    }
    force = getattr(args, "force", False)

    jsonl_files = sorted(cc_dir.glob("*.jsonl"))
    ingested = 0
    total_events = 0

    min_size = getattr(args, "min_size", MIN_SESSION_FILE_SIZE)

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
            for event in process_file(path, session_id, opts):
                upsert_event(conn, event)
                events_list.append(event)
                total_events += 1

            if events_list:
                timestamps = [e["timestamp"] for e in events_list if e.get("timestamp") is not None]
                started_at = min(timestamps) if timestamps else mtime * 1000
                ended_at = max(timestamps) if timestamps else mtime * 1000
                slug = cc_dir.parent.name
                # Decode slug to path for project_path (simplified: use project_root)
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
            return 1
        finally:
            conn.close()

        state = load_ingest_state(state_path)
        state[str(path.resolve())] = mtime
        save_ingest_state(state_path, state)
        ingested += 1

    # Stats: added this run, overall store
    added_sessions = ingested
    conn = connect(store_path)
    try:
        overall_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        overall_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        conn.close()

    print(f"Ingested {ingested} file(s), {total_events} event(s)")
    print(f"Added: {added_sessions} sessions, {total_events} events | Overall: {overall_sessions} sessions, {overall_events} events")
    return 0
