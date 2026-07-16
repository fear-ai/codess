"""session-ingest CLI command."""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from codess.config import get_state_path, get_store_path, validate_config
from codess.content_processing import ContentPolicy, ContentProcessor
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
    SOURCE_PROFILES,
    connect,
    init_db,
    load_ingest_state,
    replace_session_events,
    replace_source_sessions,
    save_ingest_state,
    should_ingest,
)
from codess.raw_store import RawStore
from codess.snapshot import create_snapshot

log = logging.getLogger(__name__)


def _record_raw(opts: dict, path: Path, source: str, conn=None) -> None:
    """Observe/capture one successfully parsed source for the pending snapshot."""
    recorder = opts.get("raw_store")
    records = opts.get("raw_records")
    if recorder is None or records is None:
        return
    profile = SOURCE_PROFILES[source]
    record = recorder.observe(
        path,
        source_system_id=profile["source_system_id"],
        storage_format=profile["storage_format"],
        mode=opts.get("raw_mode", "reference"),
    )
    records.append(record)
    if conn is not None:
        object_id = record.get("object_id")
        content_hash = (
            object_id.removeprefix("sha256:")
            if isinstance(object_id, str) and object_id.startswith("sha256:")
            else None
        )
        conn.execute(
            """
            UPDATE sources
            SET availability=?, capture_method=?, consistency=?, content_sha256=?
            WHERE id=(
              SELECT id FROM sources
              WHERE source_system_id=? AND source_uri=?
              ORDER BY id DESC LIMIT 1
            )
            """,
            (
                record["availability"], record["capture_method"],
                record["consistency"], content_hash,
                profile["source_system_id"], str(path),
            ),
        )


def _record_related_raw(
    opts: dict,
    path: Path,
    source: str,
    *,
    parent_source_locator: str,
    relation_kind: str,
) -> None:
    """Capture/reference one externally persisted content revision."""
    recorder = opts.get("raw_store")
    records = opts.get("raw_records")
    if recorder is None or records is None:
        return
    profile = SOURCE_PROFILES[source]
    records.append(recorder.observe_related(
        path,
        source_system_id=profile["source_system_id"],
        storage_format="text/plain",
        mode=opts.get("raw_mode", "reference"),
        parent_source_locator=parent_source_locator,
        relation_kind=relation_kind,
    ))


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
        try:
            external_sources = opts.setdefault("external_sources", [])
            external_start = len(external_sources)
            source_opts = {
                **opts,
                "project_path": str(project_root),
                "repo_path": str(project_root),
            }
            events_list = list(process_cc_file(path, session_id, source_opts))
            session = None
            if events_list:
                timestamps = [e["timestamp"] for e in events_list if e.get("timestamp") is not None]
                started_at = min(timestamps) if timestamps else None
                ended_at = max(timestamps) if timestamps else None
                session = {
                    "id": session_id,
                    "source": "Claude",
                    "type": "Code",
                    "release": None,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "source_mtime": mtime * 1000,
                    "time_basis": "event" if timestamps else "unknown",
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
            else:
                diagnostics = opts.get("diagnostics")
                if diagnostics is not None:
                    diagnostics["empty_sources"] = (
                        diagnostics.get("empty_sources", 0) + 1
                    )
            replace_session_events(
                conn, session, events_list, session_id=session_id
            )
            _record_raw(opts, path, "Claude", conn)
            for external in external_sources[external_start:]:
                _record_related_raw(
                    opts, Path(external["path"]), "Claude",
                    parent_source_locator=external["parent_source"],
                    relation_kind=external["relation_kind"],
                )
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
        ingested += int(bool(events_list))
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
        try:
            events_list = list(
                process_codex_file(path, session_id, proj_path, opts)
            )
            session = None
            if events_list:
                timestamps = [e["timestamp"] for e in events_list if e.get("timestamp") is not None]
                started_at = min(timestamps) if timestamps else None
                ended_at = max(timestamps) if timestamps else None
                session = {
                    "id": session_id,
                    "source": "Codex",
                    "type": "Code",
                    "release": session_metadata.get("cli_version"),
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "source_mtime": mtime * 1000,
                    "time_basis": "event" if timestamps else "unknown",
                    "project_path": proj_path if proj_path != "." else str(project_root),
                    "metadata": (
                        json.dumps(session_metadata, separators=(",", ":"))
                        if session_metadata
                        else None
                    ),
                }
            else:
                diagnostics = opts.get("diagnostics")
                if diagnostics is not None:
                    diagnostics["empty_sources"] = (
                        diagnostics.get("empty_sources", 0) + 1
                    )
            replace_session_events(
                conn, session, events_list, session_id=session_id
            )
            _record_raw(opts, path, "Codex", conn)
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
        ingested += int(bool(events_list))
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
                if session_id not in sessions_events:
                    sessions_events[session_id] = []
                sessions_events[session_id].append(event)
            sessions = {}
            for session_id, evs in sessions_events.items():
                timestamps = [e["timestamp"] for e in evs if e.get("timestamp") is not None]
                ts = min(timestamps) if timestamps else None
                ts_end = max(timestamps) if timestamps else None
                sessions[session_id] = {
                    "id": session_id,
                    "source": "Cursor",
                    "type": "IDE",
                    "release": None,
                    "started_at": ts,
                    "ended_at": ts_end,
                    "source_mtime": mtime * 1000,
                    "time_basis": "event" if timestamps else "unknown",
                    "project_path": proj_str,
                    "metadata": None,
                }
            replace_source_sessions(
                conn,
                str(db_path.resolve()),
                sessions,
                [
                    event
                    for session_events in sessions_events.values()
                    for event in session_events
                ],
            )
            if sessions_events:
                _record_raw(opts, db_path, "Cursor", conn)
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
                        if session_id not in sessions_events:
                            sessions_events[session_id] = []
                        sessions_events[session_id].append(event)
                    sessions = {}
                    for session_id, evs in sessions_events.items():
                        timestamps = [
                            e["timestamp"]
                            for e in evs
                            if e.get("timestamp") is not None
                        ]
                        ts = min(timestamps) if timestamps else None
                        ts_end = max(timestamps) if timestamps else None
                        sessions[session_id] = {
                            "id": session_id,
                            "source": "Cursor",
                            "type": "IDE",
                            "release": None,
                            "started_at": ts,
                            "ended_at": ts_end,
                            "source_mtime": mtime * 1000,
                            "time_basis": "event" if timestamps else "unknown",
                            "project_path": proj_str,
                            "metadata": json.dumps(
                                {
                                    "storage": "global",
                                    **headers[session_id],
                                }
                            ),
                        }
                    replace_source_sessions(
                        conn,
                        str(global_db.resolve()),
                        sessions,
                        [
                            event
                            for session_events in sessions_events.values()
                            for event in session_events
                        ],
                    )
                    _record_raw(opts, global_db, "Cursor", conn)
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
        "raw_mode": iopt.raw_mode,
        "strict_mapping": iopt.strict_mapping,
    }
    if iopt.content_policy:
        policy_path = Path(iopt.content_policy).expanduser()
        try:
            policy_data = json.loads(policy_path.read_text(encoding="utf-8"))
            if not isinstance(policy_data, dict):
                raise ValueError("policy root must be a JSON object")
            opts["content_processor"] = ContentProcessor(
                ContentPolicy.from_mapping(policy_data)
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"codess: invalid content policy {policy_path}: {exc}", file=sys.stderr)
            return 1
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
            project_raw_records: list[dict] = []
            raw_store = RawStore(registry_root / "raw")
            opts["raw_records"] = project_raw_records
            opts["raw_store"] = raw_store
            opts["external_sources"] = []

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
                if project_raw_records:
                    working_stores = [
                        get_store_path(project_root, vendor)
                        for vendor in ("Claude", "Codex", "Cursor")
                    ]
                    create_snapshot(
                        project_root,
                        [path for path in working_stores if path.exists()],
                        project_raw_records,
                        raw_store=raw_store,
                        seal=iopt.raw_mode == "seal",
                        build_policy={
                            "raw_mode": iopt.raw_mode,
                            "selected_sources": list(sources),
                            "minimum_source_size": min_size,
                            "redaction_enabled": iopt.redact,
                        },
                    )
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
            f"empty_sources={diagnostics.get('empty_sources', 0)} "
            f"failed_sources={diagnostics.get('failed_sources', 0)} "
            f"unsupported={diagnostics.get('unsupported_records', 0)} "
            f"known_ignored={diagnostics.get('known_ignored_records', 0)} "
            f"filtered={diagnostics.get('filtered_records', 0)} "
            f"external_content={diagnostics.get('external_content_records', 0)} "
            f"external_errors={diagnostics.get('external_content_errors', 0)}",
            file=sys.stderr,
        )
    return 1 if had_error else 0
