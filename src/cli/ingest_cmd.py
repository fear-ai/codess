"""session-ingest CLI command."""

import json
import logging
import sys
import gc
import hashlib
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from codess.config import get_state_path, get_store_path, validate_config
from codess.content_processing import ContentPolicy, ContentProcessor
from codess.adapters.cc import process_file as process_cc_file
from codess.adapters.cc import get_session_lineage as get_cc_session_lineage
from codess.adapters.cc import get_session_metadata as get_cc_session_metadata
from codess.adapters.codex import (
    get_session_meta,
    get_session_metadata,
    process_file as process_codex_file,
)
from codess.adapters.cursor import process_db as process_cursor_db
from codess.cursor_source import (
    get_composer_headers,
    get_global_db as get_cursor_global_db,
    get_workspace_dbs as get_cursor_workspace_dbs,
    get_workspace_ids as get_cursor_workspace_ids,
)
from codess.cursor_cohort import (
    cohort_needed,
    cohort_state_key,
    prepare_cursor_cohort,
)
from codess.project import (
    RootsWhenEmpty,
    build_ingest_run_options,
    get_cc_session_dir,
    resolve_cli_roots,
)
from codess.codex_source import build_session_index as build_codex_session_index
from codess.codex_source import get_session_files as get_codex_session_files
from codess.codex_source import session_archive_evidence as get_codex_archive_evidence
from codess.store import (
    SOURCE_PROFILES,
    connect,
    init_db,
    ingest_state_marker,
    load_ingest_state,
    replace_session_events,
    save_ingest_state,
    should_ingest,
)
from codess.raw_store import RawStore
from codess.project_catalog import ensure_project_binding, get_project_entry
from codess.project_catalog import load_catalog, register_workspace_bindings
from codess.artifact_correlation import correlate_external_artifacts
from codess.snapshot import create_snapshot, current_raw_records
from codess.store import record_processing_run, sync_project_catalog
from codess.resources import ResourceLimitError, check_events, check_source, peak_rss_bytes
from codess.evidence import summarize_store_evidence
from codess.ingest_review import record_ingest_review

log = logging.getLogger(__name__)


def _raw_record_key(record: dict) -> tuple:
    """Identify one logical raw source/relation independent of its revision."""
    return (
        record.get("record_type"),
        record.get("source_system_id"),
        record.get("source_locator"),
        record.get("parent_source_locator"),
        record.get("relation_kind"),
    )


def _merge_raw_record(records: list[dict], record: dict) -> bool:
    """Replace a prior observation of the same logical source in place."""
    key = _raw_record_key(record)
    previous = next(
        (existing for existing in records if _raw_record_key(existing) == key),
        None,
    )
    changed = previous is None or (
        previous.get("source_revision_id") != record.get("source_revision_id")
        or previous.get("object_id") != record.get("object_id")
    )
    records[:] = [existing for existing in records if _raw_record_key(existing) != key]
    records.append(record)
    return changed


def _record_raw(
    opts: dict, path: Path, source: str, conn=None, *,
    record_override: dict | None = None, source_uri: str | None = None,
) -> None:
    """Observe/capture one successfully parsed source for the pending snapshot."""
    recorder = opts.get("raw_store")
    records = opts.get("raw_records")
    if recorder is None or records is None:
        return
    profile = SOURCE_PROFILES[source]
    record = dict(record_override) if record_override is not None else recorder.observe(
        path,
        source_system_id=profile["source_system_id"],
        storage_format=profile["storage_format"],
        mode=opts.get("raw_mode", "reference"),
        source_locator=source_uri,
    )
    if _merge_raw_record(records, record):
        opts["raw_records_changed"] = True
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
                profile["source_system_id"], source_uri or str(path),
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
            f"source produced more than {source_max} events; maximum is {source_max}",
            limit_kind="source_events", observed=source_total, maximum=source_max,
        )
    if session_max is not None and len(session_events) >= session_max:
        raise ResourceLimitError(
            f"session produced more than {session_max} events; maximum is {session_max}",
            limit_kind="session_events", observed=len(session_events) + 1,
            maximum=session_max,
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
    record = recorder.observe_related(
        path,
        source_system_id=profile["source_system_id"],
        storage_format="text/plain",
        mode=opts.get("raw_mode", "reference"),
        parent_source_locator=parent_source_locator,
        relation_kind=relation_kind,
    )
    if _merge_raw_record(records, record):
        opts["raw_records_changed"] = True


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
        except (OSError, ResourceLimitError) as e:
            log.warning("Source validation failed for %s: %s", path, e)
            record_ingest_review(
                opts, e, source=path, vendor="Claude", stage="source_validation"
            )
            failures += 1
            if stop_on_error:
                raise
            continue
        if not should_ingest(
            state_path, str(path.resolve()), mtime, force, path=path
        ):
            continue
        rel = path.relative_to(cc_dir)
        session_id = path.stem
        direct_lineage = get_cc_session_lineage(path)
        if direct_lineage.get("parent_session_id"):
            parent_session_id = direct_lineage["parent_session_id"]
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
                session_metadata = None
                if parent_session_id is not None:
                    metadata_values = {
                        "is_sidechain": True,
                        "parent_session_id": parent_session_id,
                        "source_relpath": str(rel),
                    }
                    if direct_lineage:
                        metadata_values.update({
                            key: value for key, value in direct_lineage.items()
                            if key not in {
                                "parent_session_id", "session_relation_kind"
                            } and value is not None
                        })
                    session_metadata = json.dumps(metadata_values)
                session_facts = get_cc_session_metadata(path)
                session = {
                    "id": session_id,
                    "source": "Claude",
                    "type": "Code",
                    "release": session_facts.get("harness_version"),
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "source_mtime": mtime * 1000,
                    "time_basis": "event" if timestamps else "unknown",
                    "project_path": str(project_root),
                    "project_id": opts.get("project_id"),
                    "parent_session_id": parent_session_id,
                    "session_relation_kind": (
                        direct_lineage.get("session_relation_kind")
                        or ("subagent" if parent_session_id else None)
                    ),
                    "metadata": session_metadata,
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
            record_ingest_review(
                opts, e, source=path, vendor="Claude", stage="record_mapping"
            )
            failures += 1
            if stop_on_error:
                raise
            continue
        finally:
            conn.close()
        state = load_ingest_state(state_path)
        state[str(path.resolve())] = ingest_state_marker(path)
        save_ingest_state(state_path, state)
        if events_list:
            kind = "subagent" if parent_session_id else "main"
            kinds = opts.setdefault("claude_session_kinds", {"main": 0, "subagent": 0})
            kinds[kind] += 1
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
    files = get_codex_session_files(
        project_root, index=opts.get("codex_session_index")
    )
    ingested, total_events, failures = 0, 0, 0
    for path in files:
        try:
            st = path.stat()
            mtime = st.st_mtime
            if st.st_size < min_size:
                continue
            check_source(path, opts.get("max_source_bytes"))
        except (OSError, ResourceLimitError) as e:
            log.warning("Source validation failed for %s: %s", path, e)
            record_ingest_review(
                opts, e, source=path, vendor="Codex", stage="source_validation"
            )
            failures += 1
            if stop_on_error:
                raise
            continue
        if not should_ingest(
            state_path, str(path.resolve()), mtime, force, path=path
        ):
            continue
        session_id, proj_path = get_session_meta(path)
        session_metadata = get_session_metadata(path)
        archive_state, archive_source = get_codex_archive_evidence(path)
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
                    "archive_state": archive_state,
                    "archive_source": archive_source,
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
            record_ingest_review(
                opts, e, source=path, vendor="Codex", stage="record_mapping"
            )
            failures += 1
            if stop_on_error:
                raise
            continue
        finally:
            conn.close()
        state = load_ingest_state(state_path)
        state[str(path.resolve())] = ingest_state_marker(path)
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

    def ingest_db_stream(
        conn,
        db_path: Path,
        mtime: float,
        *,
        composer_ids: set[str] | None = None,
        headers: dict[str, dict] | None = None,
        source_file: str | None = None,
        source_observation: dict | None = None,
    ) -> tuple[int, int]:
        """Replace one Cursor source while retaining only one session buffer."""
        source_file = source_file or str(db_path.resolve())
        old_session_ids = {
            row[0] for row in conn.execute(
                "SELECT DISTINCT session_id FROM events WHERE source_file=?",
                (source_file,),
            )
        }
        seen: set[str] = set()
        current_id: str | None = None
        current_events: list[dict] = []
        source_total = largest = 0

        def flush() -> None:
            nonlocal current_events, largest
            if current_id is None:
                return
            timestamps = [
                event["timestamp"] for event in current_events
                if event.get("timestamp") is not None
            ]
            metadata = None
            if headers is not None:
                metadata = json.dumps({
                    "storage": "global", **headers[current_id],
                })
            session = {
                "id": current_id, "source": "Cursor", "type": "IDE",
                "release": None,
                "started_at": min(timestamps) if timestamps else None,
                "ended_at": max(timestamps) if timestamps else None,
                "source_mtime": mtime * 1000,
                "time_basis": "event" if timestamps else "unknown",
                "project_path": proj_str,
                "project_id": opts.get("project_id"),
                "metadata": metadata,
                "source_observation": source_observation,
            }
            replace_session_events(
                conn, session, current_events, session_id=current_id
            )
            seen.add(current_id)
            largest = max(largest, len(current_events))
            current_events = []

        for session_id, event in process_cursor_db(
            db_path, proj_str, opts, composer_ids=composer_ids,
            source_file=source_file,
        ):
            if current_id is not None and session_id != current_id:
                flush()
                if session_id in seen:
                    raise RuntimeError(
                        f"Cursor session rows are not grouped: {session_id}"
                    )
            current_id = session_id
            source_total += 1
            source_max = opts.get("max_events_per_source")
            session_max = opts.get("max_events_per_session")
            if source_max is not None and source_total > source_max:
                raise ResourceLimitError(
                    f"source produced more than {source_max} events; maximum is {source_max}",
                    limit_kind="source_events", observed=source_total,
                    maximum=source_max,
                )
            if session_max is not None and len(current_events) >= session_max:
                raise ResourceLimitError(
                    f"session produced more than {session_max} events; maximum is {session_max}",
                    limit_kind="session_events", observed=len(current_events) + 1,
                    maximum=session_max,
                )
            current_events.append(event)
        flush()
        for session_id in old_session_ids - seen:
            conn.execute(
                "DELETE FROM events WHERE session_id=? AND source_file=?",
                (session_id, source_file),
            )
            if conn.execute(
                "SELECT 1 FROM events WHERE session_id=? LIMIT 1", (session_id,)
            ).fetchone() is None:
                conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        opts["resource_observations"].append({
            "source": source_file, "source_bytes": db_path.stat().st_size,
            "events": source_total, "largest_session_events": largest,
            "peak_rss_bytes": peak_rss_bytes(),
        })
        return len(seen), source_total

    dbs = get_cursor_workspace_dbs(project_root)
    for db_path in dbs:
        try:
            mtime = db_path.stat().st_mtime
            check_source(db_path, opts.get("max_source_bytes"))
        except (OSError, ResourceLimitError) as e:
            log.warning("Source validation failed for %s: %s", db_path, e)
            record_ingest_review(
                opts, e, source=db_path, vendor="Cursor", stage="source_validation"
            )
            failures += 1
            if stop_on_error:
                raise
            continue
        state_key = f"cursor:{db_path.resolve()}"
        if not should_ingest(
            state_path, state_key, mtime, force, path=db_path
        ):
            continue
        conn = connect(store_path)
        try:
            db_sessions, db_events = ingest_db_stream(conn, db_path, mtime)
            _record_raw(opts, db_path, "Cursor", conn)
            conn.commit()
            total_events += db_events
        except Exception as e:
            conn.rollback()
            log.exception("Ingest failed for %s: %s", db_path, e)
            record_ingest_review(
                opts, e, source=db_path, vendor="Cursor", stage="record_mapping"
            )
            failures += 1
            if stop_on_error:
                raise
            continue
        finally:
            conn.close()
        state = load_ingest_state(state_path)
        state[state_key] = ingest_state_marker(db_path)
        save_ingest_state(state_path, state)
        ingested += db_sessions
        gc.collect()

    live_global_db = get_cursor_global_db()
    global_db = opts.get("cursor_cohort_db") or live_global_db
    if global_db is not None:
        global_db = Path(global_db)
        global_source = Path(opts.get("cursor_cohort_source") or global_db)
        cohort_record = opts.get("cursor_cohort_record")
        state_key = cohort_state_key(global_source)
        detection_marker = (
            opts.get("cursor_cohort_marker")
            or ingest_state_marker(global_source)
        )
        needs_captured_evidence = proj_str in opts.get(
            "cursor_cohort_evidence_projects", set()
        )
        if (
            not force
            and not needs_captured_evidence
            and load_ingest_state(state_path).get(state_key) == detection_marker
        ):
            return ingested, total_events, failures
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
            marker_mtime = detection_marker.get("source_mtime")
            mtime = (
                float(marker_mtime) / 1000
                if isinstance(marker_mtime, (int, float))
                else global_db.stat().st_mtime
            )
            check_source(global_db, opts.get("max_source_bytes"))
        except (OSError, ResourceLimitError) as e:
            log.warning("Source validation failed for %s: %s", global_db, e)
            record_ingest_review(
                opts, e, source=global_db, vendor="Cursor", stage="source_validation"
            )
            failures += 1
            if stop_on_error:
                raise
        else:
            if (
                force
                or needs_captured_evidence
                or load_ingest_state(state_path).get(state_key) != detection_marker
            ):
                conn = connect(store_path)
                try:
                    db_sessions, db_events = ingest_db_stream(
                        conn, global_db, mtime,
                        composer_ids=set(headers), headers=headers,
                        source_file=str(global_source),
                        source_observation=cohort_record,
                    )
                    _record_raw(
                        opts, global_db, "Cursor", conn,
                        record_override=cohort_record,
                        source_uri=str(global_source),
                    )
                    conn.commit()
                    total_events += db_events
                except Exception as e:
                    conn.rollback()
                    log.exception(
                        "Ingest failed for global %s: %s", global_db, e
                    )
                    record_ingest_review(
                        opts, e, source=global_db, vendor="Cursor",
                        stage="projected_record_mapping",
                    )
                    failures += 1
                    if stop_on_error:
                        raise
                else:
                    state = load_ingest_state(state_path)
                    state[state_key] = detection_marker
                    save_ingest_state(state_path, state)
                    ingested += db_sessions
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
    return summarize_store_evidence(paths)


def _current_snapshot_is_sealed(project_root: Path) -> bool:
    """Return whether the verified current snapshot already embeds raw objects."""
    pointer_path = project_root / ".codess" / "current.json"
    if not pointer_path.exists():
        return False
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        snapshot_path = Path(pointer["path"])
        if not snapshot_path.is_absolute():
            snapshot_path = pointer_path.parent / snapshot_path
        manifest = json.loads(
            (snapshot_path / "manifest.json").read_text(encoding="utf-8")
        )
        return manifest.get("sealed") is True
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return False


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
        "content_failure_reviews": [],
        "claude_session_kinds": {"main": 0, "subagent": 0},
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
    if "codex" in sources:
        opts["codex_session_index"] = build_codex_session_index(
            cache_path=(
                None if iopt.validate_only else
                registry_root / "cache" / "codex-session-index-v1.json"
            )
        )

    cursor_cohort_temp = None

    def cleanup_cursor_cohort() -> None:
        nonlocal cursor_cohort_temp
        if cursor_cohort_temp is not None:
            cursor_cohort_temp.cleanup()
            cursor_cohort_temp = None

    cursor_roots = (
        [root.resolve() for root in roots if get_cursor_workspace_ids(root)]
        if "cursor" in sources else []
    )
    if cursor_roots and not iopt.validate_only:
        live_global = get_cursor_global_db()
        if live_global is not None:
            try:
                marker_started = time.monotonic()
                marker = ingest_state_marker(live_global)
                marker_elapsed = round(time.monotonic() - marker_started, 6)
                opts.update({
                    "cursor_cohort_source": live_global,
                    "cursor_cohort_marker": marker,
                })
                if (
                    iopt.raw_mode in {"capture", "seal"}
                ):
                    # Keep timing out of diagnostics: that map contains only
                    # integer counters consumed by existing reports.
                    opts["cursor_cohort"] = {
                        "status": "unchanged",
                        "fingerprint_method": marker.get("fingerprint_method"),
                        "marker_seconds": marker_elapsed,
                        "source_bytes": marker.get("source_size"),
                        "peak_rss_bytes": peak_rss_bytes(),
                    }
                    cohort_store = RawStore(registry_root / "raw")
                    state_needs_cohort = cohort_needed(
                        live_global,
                        [get_state_path(root) for root in cursor_roots],
                        marker,
                        force=force,
                    )
                    evidence_projects = {
                        str(root)
                        for root in cursor_roots
                        if not any(
                            record.get("source_locator")
                            == str(live_global.resolve())
                            and record.get("availability") == "captured"
                            and (
                                (object_path := cohort_store.resolve(record))
                                is not None
                            )
                            and object_path.is_file()
                            for record in current_raw_records(root)
                        )
                    }
                    opts["cursor_cohort_evidence_projects"] = evidence_projects
                    evidence_needs_cohort = bool(evidence_projects)
                else:
                    state_needs_cohort = False
                    evidence_needs_cohort = False
                if state_needs_cohort or evidence_needs_cohort:
                    cohort_started = time.monotonic()
                    cursor_cohort_temp = tempfile.TemporaryDirectory(
                        prefix="codess-cursor-cohort-"
                    )
                    cohort_db = Path(cursor_cohort_temp.name) / "state.vscdb"
                    cohort_record, marker, status = prepare_cursor_cohort(
                        live_global,
                        raw_store=cohort_store,
                        cache_path=(
                            registry_root / "cache" / "cursor-cohort-v1.json"
                        ),
                        materialized_path=cohort_db,
                        source_system_id=(
                            SOURCE_PROFILES["Cursor"]["source_system_id"]
                        ),
                        storage_format=SOURCE_PROFILES["Cursor"]["storage_format"],
                        marker=marker,
                        force=force,
                    )
                    opts.update({
                        "cursor_cohort_db": cohort_db,
                        "cursor_cohort_record": cohort_record,
                        "cursor_cohort_marker": marker,
                        "cursor_cohort": {
                            "status": status,
                            "object_id": cohort_record.get("object_id"),
                            "source_revision": cohort_record.get(
                                "source_revision_id"
                            ),
                            "fingerprint_method": marker.get(
                                "fingerprint_method"
                            ),
                            "marker_seconds": marker_elapsed,
                            "cohort_seconds": round(
                                time.monotonic() - cohort_started, 6
                            ),
                            "source_bytes": marker.get("source_size"),
                            "stored_bytes": cohort_record.get("stored_size"),
                            "materialized_bytes": cohort_record.get(
                                "uncompressed_size"
                            ),
                            "peak_rss_bytes": peak_rss_bytes(),
                        },
                    })
            except Exception as exc:
                cleanup_cursor_cohort()
                print(f"codess: Cursor cohort capture failed: {exc}", file=sys.stderr)
                return 1

    for project_index, project_root in enumerate(roots):
        try:
            resource_start = len(opts["resource_observations"])
            review_start = len(opts["content_failure_reviews"])
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
            project_raw_records: list[dict] = (
                [] if iopt.validate_only else current_raw_records(project_root)
            )
            raw_store = RawStore((staging_root / "raw") if staging_root else registry_root / "raw")
            opts["raw_records"] = project_raw_records
            opts["raw_store"] = None if iopt.validate_only else raw_store
            opts["raw_records_changed"] = False
            opts["external_sources"] = []
            project_ingested = 0
            seal_upgrade = (
                iopt.raw_mode == "seal"
                and not _current_snapshot_is_sealed(project_root)
            )

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
                        cleanup_cursor_cohort()
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
                    project_ingested += n
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
                project_ingested += n
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
                project_ingested += n
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
                if (
                    project_raw_records
                    and not iopt.validate_only
                    and (
                        project_ingested
                        or opts["raw_records_changed"]
                        or seal_upgrade
                    )
                ):
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
                        "content_failure_reviews": opts["content_failure_reviews"][review_start:],
                        "resource_observations": opts["resource_observations"][resource_start:],
                        "cursor_cohort": opts.get("cursor_cohort"),
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
                cleanup_cursor_cohort()
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
            "content_failure_reviews": opts["content_failure_reviews"],
            "resource_observations": opts["resource_observations"],
            "session_kinds": {"Claude": opts["claude_session_kinds"]},
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
    cleanup_cursor_cohort()
    if opts.get("cursor_cohort"):
        cohort = opts["cursor_cohort"]
        elapsed = cohort.get("cohort_seconds", cohort.get("marker_seconds", 0))
        print(f"Cursor cohort: {cohort['status']} ({elapsed:.3f}s)")
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
            f"external_errors={diagnostics.get('external_content_errors', 0)} "
            f"reviewable_content_failures={diagnostics.get('reviewable_content_failures', 0)}",
            file=sys.stderr,
        )
    return 1 if had_error else 0
