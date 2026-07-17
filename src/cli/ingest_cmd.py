"""session-ingest CLI command."""

import json
import logging
import sys
import gc
import hashlib
import tempfile
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
from codess.project_catalog import ensure_project_binding, get_project_entry
from codess.project_catalog import load_catalog, register_workspace_bindings
from codess.artifact_correlation import correlate_external_artifacts
from codess.snapshot import create_snapshot
from codess.store import record_processing_run, sync_project_catalog
from codess.resources import ResourceLimitError, check_events, check_source, peak_rss_bytes

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


def _observe_resource(opts: dict, path: Path, sessions_events: dict[str, list[dict]]) -> None:
    total, largest = check_events(
        sessions_events, max_source=opts.get("max_events_per_source"),
        max_session=opts.get("max_events_per_session"),
    )
    opts["resource_observations"].append({
        "source": str(path), "source_bytes": path.stat().st_size,
        "events": total, "largest_session_events": largest,
        "peak_rss_bytes": peak_rss_bytes(),
    })


def _append_bounded_event(
    opts: dict,
    sessions_events: dict[str, list[dict]],
    session_id: str,
    event: dict,
    source_total: int,
) -> int:
    """Append one event, rejecting before a configured buffer is exceeded."""
    source_total += 1
    source_max = opts.get("max_events_per_source")
    session_max = opts.get("max_events_per_session")
    session_events = sessions_events.setdefault(session_id, [])
    if source_max is not None and source_total > source_max:
        raise ResourceLimitError(
            f"source produced more than {source_max} events; maximum is {source_max}"
        )
    if session_max is not None and len(session_events) >= session_max:
        raise ResourceLimitError(
            f"session produced more than {session_max} events; maximum is {session_max}"
        )
    session_events.append(event)
    return source_total


def _collect_bounded_events(opts: dict, events, session_id: str) -> list[dict]:
    sessions_events: dict[str, list[dict]] = {}
    total = 0
    for event in events:
        total = _append_bounded_event(
            opts, sessions_events, session_id, event, total
        )
    return sessions_events.get(session_id, [])


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
            check_source(path, opts.get("max_source_bytes"))
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
            events_list = _collect_bounded_events(
                opts, process_cc_file(path, session_id, source_opts), session_id,
            )
            _observe_resource(opts, path, {session_id: events_list})
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
                    "project_id": opts.get("project_id"),
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
        del events_list
        gc.collect()
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
            check_source(path, opts.get("max_source_bytes"))
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
            events_list = _collect_bounded_events(
                opts, process_codex_file(path, session_id, proj_path, opts), session_id,
            )
            _observe_resource(opts, path, {session_id: events_list})
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
                    "project_id": opts.get("project_id"),
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
        del events_list
        gc.collect()
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

    workspace_ids = set(get_cursor_workspace_ids(project_root))
    if workspace_ids and opts.get("registry_root") and opts.get("project_id") and not opts.get("validate_only"):
        register_workspace_bindings(
            Path(opts["registry_root"]), str(opts["project_id"]),
            str(opts["location_id"]), workspace_ids,
            source_project_path=proj_str,
        )

    dbs = get_cursor_workspace_dbs(project_root)
    for db_path in dbs:
        try:
            mtime = db_path.stat().st_mtime
            check_source(db_path, opts.get("max_source_bytes"))
        except OSError as e:
            log.warning("Cannot stat %s: %s", db_path, e)
            failures += 1
            continue
        state_key = f"cursor:{db_path.resolve()}"
        if not should_ingest(state_path, state_key, mtime, force):
            continue
        conn = connect(store_path)
        sessions_events: dict[str, list[dict]] = {}
        source_total = 0
        try:
            for session_id, event in process_cursor_db(db_path, proj_str, opts):
                source_total = _append_bounded_event(
                    opts, sessions_events, session_id, event, source_total
                )
            _observe_resource(opts, db_path, sessions_events)
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
                    "project_id": opts.get("project_id"),
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
        del sessions_events
        gc.collect()

    global_db = get_cursor_global_db()
    if global_db is not None:
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
            check_source(global_db, opts.get("max_source_bytes"))
        except OSError as e:
            log.warning("Cannot stat %s: %s", global_db, e)
            failures += 1
        else:
            state_key = f"cursor:global:{global_db.resolve()}"
            if should_ingest(state_path, state_key, mtime, force):
                conn = connect(store_path)
                sessions_events: dict[str, list[dict]] = {}
                source_total = 0
                try:
                    for session_id, event in process_cursor_db(
                        global_db,
                        proj_str,
                        opts,
                        composer_ids=set(headers),
                    ):
                        source_total = _append_bounded_event(
                            opts, sessions_events, session_id, event, source_total
                        )
                    _observe_resource(opts, global_db, sessions_events)
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
                            "project_id": opts.get("project_id"),
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
                    del sessions_events
                    gc.collect()
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


def _write_runtime_report(project_root: Path, report: dict) -> None:
    path = project_root / ".codess" / "last-ingest-report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _evidence_summary(paths: list[Path]) -> dict:
    artifact_sources: dict[str, set[str]] = {}
    totals = {"tool_invocations": 0, "tool_results": 0, "model_configurations": 0, "events_missing_time": 0, "correlation_assertions": 0}
    settings = {"reasoning_effort": 0, "speed_tier": 0, "service_tier": 0}
    for path in paths:
        if not path.exists():
            continue
        conn = connect(path, read_only=True)
        try:
            for key in ("tool_invocations", "tool_results", "model_configurations", "correlation_assertions"):
                totals[key] += conn.execute(f"SELECT COUNT(*) FROM {key}").fetchone()[0]
            totals["events_missing_time"] += conn.execute("SELECT COUNT(*) FROM events WHERE event_at IS NULL").fetchone()[0]
            for row in conn.execute("SELECT reasoning_effort,speed_tier,service_tier FROM model_configurations"):
                for key in settings:
                    settings[key] += int(row[key] is not None)
            for row in conn.execute("""
                SELECT COALESCE(a.relative_path,a.uri,a.observed_absolute_path) locator,s.source
                FROM artifacts a JOIN event_artifacts ea ON ea.artifact_id=a.id
                JOIN events e ON e.id=ea.event_id JOIN sessions s ON s.id=e.session_id
                WHERE COALESCE(a.relative_path,a.uri,a.observed_absolute_path) IS NOT NULL
            """):
                artifact_sources.setdefault(row["locator"], set()).add(row["source"])
        finally:
            conn.close()
    shared = sorted(locator for locator, sources in artifact_sources.items() if len(sources) > 1)
    return {**totals, "model_setting_counts": settings, "cross_vendor_artifact_count": len(shared), "cross_vendor_artifact_examples": shared[:20]}


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
    for name, value in (
        ("--max-source-bytes", iopt.max_source_bytes),
        ("--max-events-per-source", iopt.max_events_per_source),
        ("--max-events-per-session", iopt.max_events_per_session),
    ):
        if value is not None and value <= 0:
            print(f"codess: {name} must be > 0", file=sys.stderr)
            return 1
    diagnostics: dict[str, int] = {}
    opts = {
        "debug": iopt.debug,
        "redact": iopt.redact,
        "diagnostics": diagnostics,
        "raw_mode": iopt.raw_mode,
        "strict_mapping": iopt.strict_mapping,
        "validate_only": iopt.validate_only,
        "max_source_bytes": iopt.max_source_bytes,
        "max_events_per_source": iopt.max_events_per_source,
        "max_events_per_session": iopt.max_events_per_session,
        "resource_observations": [],
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
            opts["content_policy_data"] = policy_data
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"codess: invalid content policy {policy_path}: {exc}", file=sys.stderr)
            return 1
    force = True if iopt.validate_only else iopt.force
    min_size = iopt.min_size

    total_ingested = 0
    total_events = 0
    source_stats = {}
    had_error = False

    def _store_path(proj: Path, src: str) -> Path:
        if iopt.validate_only:
            key = hashlib.sha256(str(proj).encode()).hexdigest()[:16]
            proj = staging_root / key
        return get_store_path(proj, {"cc": "Claude", "codex": "Codex", "cursor": "Cursor"}[src])

    temporary = tempfile.TemporaryDirectory(prefix="codess-preflight-") if iopt.validate_only else None
    staging_root = Path(temporary.name) if temporary else None
    if iopt.validate_only:
        opts["raw_mode"] = "none"

    for project_index, project_root in enumerate(roots):
        try:
            resource_start = len(opts["resource_observations"])
            project_root = project_root.resolve()
            if iopt.validate_only:
                digest = hashlib.sha256(str(project_root).encode()).hexdigest()[:24]
                binding = {"project_id": f"codess:preflight-project:{digest}", "location_id": f"preflight:{digest}"}
                project_entry = {
                    "project_id": binding["project_id"], "logical_name": project_root.name,
                    "locations": [{"location_id": binding["location_id"], "machine_id": "preflight", "path": str(project_root), "state": "active", "platform": sys.platform}],
                    "workspace_bindings": [], "path_aliases": [str(project_root)],
                }
            else:
                binding = ensure_project_binding(registry_root, project_root)
                project_entry = get_project_entry(registry_root, binding["project_id"])
            opts["project_id"] = binding["project_id"]
            opts["location_id"] = binding["location_id"]
            opts["registry_root"] = str(registry_root)
            opts["content_actions"] = []
            work_root = (staging_root / str(project_index)) if staging_root else project_root
            state_path = get_state_path(work_root)
            proj_stats = {}
            project_raw_records: list[dict] = []
            raw_store = RawStore((staging_root / "raw") if staging_root else registry_root / "raw")
            opts["raw_records"] = project_raw_records
            opts["raw_store"] = None if iopt.validate_only else raw_store
            opts["external_sources"] = []

            if "cc" in sources:
                store_path = _store_path(project_root, "cc")
                init_db(store_path)
                conn = connect(store_path)
                try:
                    sync_project_catalog(conn, project_entry)
                    conn.commit()
                finally:
                    conn.close()
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
                conn = connect(store_path)
                try:
                    sync_project_catalog(conn, project_entry)
                    conn.commit()
                finally:
                    conn.close()
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
                conn = connect(store_path)
                try:
                    sync_project_catalog(conn, project_entry)
                    conn.commit()
                finally:
                    conn.close()
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
                catalog = load_catalog(registry_root)
                if not iopt.validate_only:
                    project_entry = get_project_entry(registry_root, binding["project_id"])
                for vendor in ("Claude", "Codex", "Cursor"):
                    source_key = {"Claude": "cc", "Codex": "codex", "Cursor": "cursor"}[vendor]
                    path = _store_path(project_root, source_key)
                    if not path.exists():
                        continue
                    conn = connect(path)
                    try:
                        sync_project_catalog(conn, project_entry)
                        outcome = correlate_external_artifacts(conn, catalog)
                        conn.commit()
                    finally:
                        conn.close()
                    for key, value in outcome.items():
                        diagnostics[f"artifact_correlation_{key}"] = (
                            diagnostics.get(f"artifact_correlation_{key}", 0) + value
                        )
                if opts.get("content_policy_data"):
                    for vendor in ("Claude", "Codex", "Cursor"):
                        source_key = {
                            "Claude": "cc", "Codex": "codex", "Cursor": "cursor"
                        }[vendor]
                        path = _store_path(project_root, source_key)
                        if not path.exists():
                            continue
                        conn = connect(path)
                        try:
                            record_processing_run(
                                conn,
                                project_id=binding["project_id"],
                                policy=opts["content_policy_data"],
                                actions=opts.get("content_actions", []),
                            )
                            conn.commit()
                        finally:
                            conn.close()
                if project_raw_records and not iopt.validate_only:
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
                        registry_root=registry_root,
                        project_id=binding["project_id"],
                    )
                if not iopt.validate_only:
                    _save_stats(project_root, registry_root, proj_stats)
                    evidence_paths = [_store_path(project_root, key) for key in ("cc", "codex", "cursor")]
                    _write_runtime_report(project_root, {
                        "report_format": "codess.ingest-runtime/1",
                        "project": str(project_root), "sources": proj_stats,
                        "diagnostics": diagnostics,
                        "resource_observations": opts["resource_observations"][resource_start:],
                        "evidence_summary": _evidence_summary(evidence_paths),
                        "limits": {
                            "max_source_bytes": iopt.max_source_bytes,
                            "max_events_per_source": iopt.max_events_per_source,
                            "max_events_per_session": iopt.max_events_per_session,
                        },
                    })
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

    if iopt.validate_only:
        store_checks = []
        for path in sorted(staging_root.rglob("*.db")):
            conn = connect(path, read_only=True)
            try:
                store_checks.append({
                    "store": path.name,
                    "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
                    "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
                    "sessions": conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
                    "events": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                })
            finally:
                conn.close()
        report = {
            "report_format": "codess.ingest-preflight/1",
            "status": "rejected" if had_error else "accepted",
            "projects": [str(root.resolve()) for root in roots],
            "sources": source_stats,
            "sessions": total_ingested,
            "events": total_events,
            "diagnostics": diagnostics,
            "resource_observations": opts["resource_observations"],
            "store_checks": store_checks,
            "evidence_summary": _evidence_summary(sorted(staging_root.rglob("*.db"))),
            "limits": {
                "max_source_bytes": iopt.max_source_bytes,
                "max_events_per_source": iopt.max_events_per_source,
                "max_events_per_session": iopt.max_events_per_session,
            },
            "mutation_boundary": "temporary stores only; project, registry, raw store, snapshots, and ingest state unchanged",
        }
        print(json.dumps(report, sort_keys=True))
        if temporary:
            temporary.cleanup()
        return 1 if had_error else 0
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
