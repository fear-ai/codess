"""session-ingest CLI command."""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from codess.config import get_state_path, get_store_path, validate_config
from codess.adapters.cc import process_file as process_cc_file
from codess.adapters.codex import (
    get_session_meta,
    get_session_metadata,
    process_file as process_codex_file,
)
from codess.adapters.cursor import get_composer_headers, process_db as process_cursor_db
from codess.project import RootsWhenEmpty, build_ingest_run_options, resolve_cli_roots
from codess.project import (
    get_cc_session_dir,
    get_codex_session_files,
    get_cursor_global_db,
    get_cursor_workspace_dbs,
    get_cursor_workspace_ids,
)
from codess.store import (
    connect,
    init_db,
    load_ingest_state,
    save_ingest_state,
    should_ingest,
    upsert_event,
    upsert_session,
)

log = logging.getLogger(__name__)


def _cc_session_files(cc_dir: Path) -> list[tuple[Path, str | None]]:
    """Return main and nested subagent transcripts with their parent session id."""
    main = [(path, None) for path in cc_dir.glob("*.jsonl")]
    nested = []
    for path in cc_dir.glob("*/subagents/**/*.jsonl"):
        rel = path.relative_to(cc_dir)
        nested.append((path, rel.parts[0]))
    return sorted(main + nested, key=lambda item: str(item[0]))


def _ingest_cc(
    project_root: Path,
    store_path: Path,
    state_path: Path,
    opts: dict,
    force: bool,
    min_size: int,
    *,
    stop_on_error: bool,
) -> tuple[int, int, int]:
    """Ingest CC. Return (sessions_added, events_added, failed_sources)."""
    cc_dir = get_cc_session_dir(project_root)
    if cc_dir is None:
        return 0, 0, 0
    ingested, total_events, failures = 0, 0, 0
    for path, parent_session_id in _cc_session_files(cc_dir):
        try:
            st = path.stat()
            mtime = st.st_mtime
            if st.st_size < min_size:
                continue
        except OSError as e:
            log.warning("Cannot stat %s: %s", path, e)
            failures += 1
            continue
        if not should_ingest(state_path, str(path.resolve()), mtime, force):
            continue
        rel = path.relative_to(cc_dir)
        session_id = path.stem
        conn = connect(store_path)
        events_list = []
        try:
            for event in process_cc_file(path, session_id, opts):
                upsert_event(conn, event)
                events_list.append(event)
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
                    "metadata": (
                        json.dumps(
                            {
                                "is_sidechain": True,
                                "parent_session_id": parent_session_id,
                                "source_relpath": str(rel),
                            }
                        )
                        if parent_session_id is not None
                        else None
                    ),
                }
                upsert_session(conn, session)
            conn.commit()
            total_events += len(events_list)
        except Exception as e:
            conn.rollback()
            log.exception("Ingest failed for %s: %s", path, e)
            failures += 1
            if stop_on_error:
                raise
            continue
        finally:
            conn.close()
        state = load_ingest_state(state_path)
        state[str(path.resolve())] = mtime
        save_ingest_state(state_path, state)
        ingested += 1
    return ingested, total_events, failures


def _ingest_codex(
    project_root: Path,
    store_path: Path,
    state_path: Path,
    opts: dict,
    force: bool,
    min_size: int,
    *,
    stop_on_error: bool,
) -> tuple[int, int, int]:
    """Ingest Codex. Return (sessions_added, events_added, failed_sources)."""
    files = get_codex_session_files(project_root)
    ingested, total_events, failures = 0, 0, 0
    for path in files:
        try:
            st = path.stat()
            mtime = st.st_mtime
            if st.st_size < min_size:
                continue
        except OSError as e:
            log.warning("Cannot stat %s: %s", path, e)
            failures += 1
            continue
        if not should_ingest(state_path, str(path.resolve()), mtime, force):
            continue
        session_id, proj_path = get_session_meta(path)
        session_metadata = get_session_metadata(path)
        conn = connect(store_path)
        events_list = []
        try:
            for event in process_codex_file(path, session_id, proj_path, opts):
                upsert_event(conn, event)
                events_list.append(event)
            if events_list:
                timestamps = [e["timestamp"] for e in events_list if e.get("timestamp") is not None]
                started_at = min(timestamps) if timestamps else mtime * 1000
                ended_at = max(timestamps) if timestamps else mtime * 1000
                session = {
                    "id": session_id,
                    "source": "Codex",
                    "type": "Code",
                    "release": session_metadata.get("cli_version"),
                    "release_value": None,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "project_path": proj_path if proj_path != "." else str(project_root),
                    "metadata": (
                        json.dumps(session_metadata, separators=(",", ":"))
                        if session_metadata
                        else None
                    ),
                }
                upsert_session(conn, session)
            conn.commit()
            total_events += len(events_list)
        except Exception as e:
            conn.rollback()
            log.exception("Ingest failed for %s: %s", path, e)
            failures += 1
            if stop_on_error:
                raise
            continue
        finally:
            conn.close()
        state = load_ingest_state(state_path)
        state[str(path.resolve())] = mtime
        save_ingest_state(state_path, state)
        ingested += 1
    return ingested, total_events, failures


def _ingest_cursor(
    project_root: Path,
    store_path: Path,
    state_path: Path,
    opts: dict,
    force: bool,
    *,
    stop_on_error: bool,
) -> tuple[int, int, int]:
    """Ingest Cursor. Return (sessions_added, events_added, failed_sources)."""
    proj_str = str(project_root.resolve())
    ingested, total_events, failures = 0, 0, 0

    dbs = get_cursor_workspace_dbs(project_root)
    for db_path in dbs:
        try:
            mtime = db_path.stat().st_mtime
        except OSError as e:
            log.warning("Cannot stat %s: %s", db_path, e)
            failures += 1
            continue
        state_key = f"cursor:{db_path.resolve()}"
        if not should_ingest(state_path, state_key, mtime, force):
            continue
        conn = connect(store_path)
        sessions_events: dict[str, list[dict]] = {}
        try:
            for session_id, event in process_cursor_db(db_path, proj_str, opts):
                upsert_event(conn, event)
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
            total_events += sum(len(events) for events in sessions_events.values())
        except Exception as e:
            conn.rollback()
            log.exception("Ingest failed for %s: %s", db_path, e)
            failures += 1
            if stop_on_error:
                raise
            continue
        finally:
            conn.close()
        state = load_ingest_state(state_path)
        state[state_key] = mtime
        save_ingest_state(state_path, state)
        ingested += len(sessions_events)

    global_db = get_cursor_global_db()
    if global_db is not None:
        workspace_ids = set(get_cursor_workspace_ids(project_root))
        headers = get_composer_headers(global_db, workspace_ids)
        if not headers:
            if opts.get("debug"):
                log.debug(
                    "No global Cursor composers mapped to %s via workspace ids %s",
                    project_root,
                    sorted(workspace_ids),
                )
            return ingested, total_events, failures
        try:
            mtime = global_db.stat().st_mtime
        except OSError as e:
            log.warning("Cannot stat %s: %s", global_db, e)
            failures += 1
        else:
            state_key = f"cursor:global:{global_db.resolve()}"
            if should_ingest(state_path, state_key, mtime, force):
                conn = connect(store_path)
                sessions_events: dict[str, list[dict]] = {}
                try:
                    for session_id, event in process_cursor_db(
                        global_db,
                        proj_str,
                        opts,
                        composer_ids=set(headers),
                    ):
                        upsert_event(conn, event)
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
                            "project_path": proj_str,
                            "metadata": json.dumps(
                                {
                                    "storage": "global",
                                    **headers[session_id],
                                }
                            ),
                        }
                        upsert_session(conn, session)
                    conn.commit()
                    total_events += sum(
                        len(events) for events in sessions_events.values()
                    )
                except Exception as e:
                    conn.rollback()
                    log.exception(
                        "Ingest failed for global %s: %s", global_db, e
                    )
                    failures += 1
                    if stop_on_error:
                        raise
                else:
                    state = load_ingest_state(state_path)
                    state[state_key] = mtime
                    save_ingest_state(state_path, state)
                    ingested += len(sessions_events)
                finally:
                    conn.close()

    return ingested, total_events, failures


def _save_stats(project_root: Path, registry_root: Path, source_stats: dict) -> None:
    """Merge ingest store stats into registry (preserves ``scan`` / ``query`` / etc.)."""
    from codess.registry_store import merge_ingest_sources, update_project_entry

    proj_str = str(project_root.resolve())

    def mut(e: dict) -> None:
        merge_ingest_sources(e, source_stats)

    update_project_entry(registry_root, proj_str, mut)


def run(args) -> int:
    """Run session-ingest. Returns exit code."""
    config_errors = validate_config()
    for msg in config_errors:
        print(f"codess: {msg}", file=sys.stderr)
    if config_errors:
        return 1

    roots, err = resolve_cli_roots(args, when_empty=RootsWhenEmpty.PROJECT_ROOT)
    if err:
        print(err, file=sys.stderr)
        return 1

    from codess.project import resolve_registry_directory

    registry_root = resolve_registry_directory(args)

    raw_src = getattr(args, "source", None) or "all"
    if "," in raw_src:
        print(
            "codess: ingest --source must be one token: cc | codex | cursor | all (not a comma list)",
            file=sys.stderr,
        )
        return 1
    source = raw_src.strip().lower()
    if source not in ("cc", "codex", "cursor", "all"):
        print(f"codess: invalid ingest --source: {raw_src!r}", file=sys.stderr)
        return 1
    if source == "cc":
        sources = ["cc"]
    elif source == "codex":
        sources = ["codex"]
    elif source == "cursor":
        sources = ["cursor"]
    else:
        sources = ["cc", "codex", "cursor"]

    iopt = build_ingest_run_options(args)
    diagnostics: dict[str, int] = {}
    opts = {
        "debug": iopt.debug,
        "redact": iopt.redact,
        "diagnostics": diagnostics,
    }
    force = iopt.force
    min_size = iopt.min_size

    total_ingested = 0
    total_events = 0
    source_stats = {}
    had_error = False

    def _store_path(proj: Path, src: str) -> Path:
        return get_store_path(proj, {"cc": "Claude", "codex": "Codex", "cursor": "Cursor"}[src])

    for project_root in roots:
        try:
            project_root = project_root.resolve()
            state_path = get_state_path(project_root)
            proj_stats = {}

            if "cc" in sources:
                store_path = _store_path(project_root, "cc")
                init_db(store_path)
                cc_dir = get_cc_session_dir(project_root)
                if cc_dir is None and source == "cc":
                    print(f"No CC project dir for {project_root}", file=sys.stderr)
                    had_error = True
                    if iopt.stop_on_error:
                        return 1
                if cc_dir is not None:
                    n, e, failed = _ingest_cc(
                        project_root,
                        store_path,
                        state_path,
                        opts,
                        force,
                        min_size,
                        stop_on_error=iopt.stop_on_error,
                    )
                    total_ingested += n
                    total_events += e
                    if failed:
                        diagnostics["failed_sources"] = (
                            diagnostics.get("failed_sources", 0) + failed
                        )
                        had_error = True
                if store_path.exists():
                    conn = connect(store_path)
                    try:
                        s = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                        ev = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                        proj_stats["Claude"] = {
                            "sessions": s,
                            "events": ev,
                            "last_ingestion": datetime.now(timezone.utc).isoformat(),
                        }
                    finally:
                        conn.close()

            if "codex" in sources:
                store_path = _store_path(project_root, "codex")
                init_db(store_path)
                n, e, failed = _ingest_codex(
                    project_root,
                    store_path,
                    state_path,
                    opts,
                    force,
                    min_size,
                    stop_on_error=iopt.stop_on_error,
                )
                total_ingested += n
                total_events += e
                if failed:
                    diagnostics["failed_sources"] = (
                        diagnostics.get("failed_sources", 0) + failed
                    )
                    had_error = True
                if store_path.exists():
                    conn = connect(store_path)
                    try:
                        s = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                        ev = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                        proj_stats["Codex"] = {
                            "sessions": s,
                            "events": ev,
                            "last_ingestion": datetime.now(timezone.utc).isoformat(),
                        }
                    finally:
                        conn.close()

            if "cursor" in sources:
                store_path = _store_path(project_root, "cursor")
                init_db(store_path)
                n, e, failed = _ingest_cursor(
                    project_root,
                    store_path,
                    state_path,
                    opts,
                    force,
                    stop_on_error=iopt.stop_on_error,
                )
                total_ingested += n
                total_events += e
                if failed:
                    diagnostics["failed_sources"] = (
                        diagnostics.get("failed_sources", 0) + failed
                    )
                    had_error = True
                if store_path.exists():
                    conn = connect(store_path)
                    try:
                        s = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                        ev = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                        proj_stats["Cursor"] = {
                            "sessions": s,
                            "events": ev,
                            "last_ingestion": datetime.now(timezone.utc).isoformat(),
                        }
                    finally:
                        conn.close()

            if proj_stats:
                _save_stats(project_root, registry_root, proj_stats)
                for k, v in proj_stats.items():
                    if k not in source_stats:
                        source_stats[k] = {"sessions": 0, "events": 0}
                    source_stats[k]["sessions"] += v["sessions"]
                    source_stats[k]["events"] += v["events"]
        except Exception:
            log.exception("Ingest failed for project root %s", project_root)
            had_error = True
            if iopt.stop_on_error:
                return 1

    overall_sessions = sum(s["sessions"] for s in source_stats.values())
    overall_events = sum(s["events"] for s in source_stats.values())

    print(f"Ingested {total_ingested} session(s), {total_events} event(s)")
    print(f"Added: {total_ingested} sessions, {total_events} events | Overall: {overall_sessions} sessions, {overall_events} events")
    if any(diagnostics.values()):
        print(
            "codess: ingest diagnostics: "
            f"malformed={diagnostics.get('malformed_records', 0)} "
            f"ignored={diagnostics.get('ignored_records', 0)} "
            f"failed_sources={diagnostics.get('failed_sources', 0)}",
            file=sys.stderr,
        )
    return 1 if had_error else 0
