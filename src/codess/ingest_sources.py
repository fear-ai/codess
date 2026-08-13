"""Per-vendor ingest coordinators.

Each function reads one vendor's sources for one Project, writes its store
inside a transaction, and returns what it processed. They live here rather
than in the command module because they are the ingest domain: the command
adapts arguments and renders results, these do the work.

The shared helpers below travel with them. They are the pieces every
coordinator needs -- bounded event collection, raw-record recording, resource
observation, and progress emission -- and have no other consumer.
"""

from __future__ import annotations

import gc
import json
import logging
import sqlite3
import time
from functools import partial
from pathlib import Path

from codess.adapters.cc import get_session_lineage as get_cc_session_lineage
from codess.adapters.cc import get_session_metadata as get_cc_session_metadata
from codess.adapters.cc import process_file as process_cc_file
from codess.adapters.codex import get_session_meta, get_session_metadata
from codess.adapters.codex import process_file as process_codex_file
from codess.adapters.cursor import process_db as process_cursor_db
from codess.codex_source import get_session_files as get_codex_session_files
from codess.codex_source import session_archive_evidence as get_codex_archive_evidence
from codess.cursor_cohort import cohort_state_key
from codess.cursor_source import get_composer_headers
from codess.cursor_source import get_global_db as get_cursor_global_db
from codess.cursor_source import get_workspace_dbs as get_cursor_workspace_dbs
from codess.cursor_source import get_workspace_ids as get_cursor_workspace_ids
from codess.cursor_source import has_bubble_rows as cursor_has_bubble_rows
from codess.ingest_pipeline import commit_source_replacement, inspect_sources, mark_source_complete
from codess.ingest_review import record_ingest_review
from codess.project import get_cc_session_dir
from codess.project_catalog import register_workspace_bindings
from codess.resources import (
    ResourceLimitError,
    check_events,
    check_source,
    peak_rss_bytes,
    searchable_event_payload,
    summarize_event_payload,
)
from codess.store import (
    SOURCE_PROFILES,
    connect,
    drop_sessions_absent_from_source,
    ingest_state_marker,
    load_ingest_state,
    prune_unreferenced_records,
    replace_session_events,
    save_ingest_state,
    session_ids_for_source,
    should_ingest,
)

log = logging.getLogger(__name__)


def _progress(opts: dict, event: str, **fields) -> None:
    callback = opts.get("progress")
    if callback is not None:
        callback(event, **fields)


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
        progress=opts.get("progress"),
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
    retained_characters, retained_utf8_bytes = summarize_event_payload(
        sessions_events
    )
    opts["resource_observations"].append({
        "source": str(path), "container": str(path.resolve()),
        "source_bytes": path.stat().st_size,
        "selected_input_bytes": path.stat().st_size,
        "selected_input_kind": "selected_transcript_file",
        "events": total, "largest_session_events": largest,
        "retained_searchable_characters": retained_characters,
        "retained_searchable_utf8_bytes": retained_utf8_bytes,
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


def _collect_bounded_events(
    opts: dict,
    events,
    session_id: str,
    *,
    project: str,
    vendor: str,
    source: str,
) -> list[dict]:
    sessions_events: dict[str, list[dict]] = {}
    total = 0
    started = last_progress = time.monotonic()
    for event in events:
        total = _append_bounded_event(
            opts, sessions_events, session_id, event, total
        )
        now = time.monotonic()
        if total % 1000 == 0 or now - last_progress >= 5.0:
            _progress(
                opts, "source.map.progress", project=project, vendor=vendor,
                source=source, session_id=session_id, events=total,
                phase_seconds=round(now - started, 3),
            )
            last_progress = now
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
        progress=opts.get("progress"),
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


def _record_cc_source(
    opts: dict,
    path: Path,
    external_sources: list[dict],
    external_start: int,
    conn,
) -> None:
    """Record one Claude source and the external content it referenced.

    Takes its inputs explicitly rather than closing over the loop that calls
    it. The closure form read four enclosing values and rebound none, so it
    was a closure by accident of where it was written (13.4.1) -- and one a
    later deferred call would have silently bound to the wrong iteration.
    """
    _record_raw(opts, path, "Claude", conn)
    for external in external_sources[external_start:]:
        _record_related_raw(
            opts, Path(external["path"]), "Claude",
            parent_source_locator=external["parent_source"],
            relation_kind=external["relation_kind"],
        )


def _ingest_cc(
    project_path: Path,
    store_path: Path,
    state_path: Path,
    opts: dict,
    force: bool,
    min_size: int,
    *,
    stop_on_error: bool,
) -> tuple[int, int, int, bool]:
    """Return processed sessions/events, failures, and normalized-store change."""
    cc_dir = get_cc_session_dir(project_path)
    if cc_dir is None:
        return 0, 0, 0, False
    ingested, total_events, failures, changed = 0, 0, 0, False
    files = _cc_session_files(cc_dir)
    parent_by_path = dict(files)
    for admission in inspect_sources(
        files, state_path=state_path, force=force, min_size=min_size,
        max_source_bytes=opts.get("max_source_bytes"),
    ):
        path = admission.path
        parent_session_id = parent_by_path[path]
        if admission.error is not None:
            e = admission.error
            log.warning("Source validation failed for %s: %s", path, e)
            record_ingest_review(
                opts, e, source=path, vendor="Claude", stage="source_validation"
            )
            failures += 1
            if stop_on_error:
                raise e
            continue
        if admission.skip_reason:
            continue
        st = admission.stat
        mtime = st.st_mtime
        source_started = time.monotonic()
        _progress(
            opts, "source.start", project=str(project_path.resolve()),
            vendor="Claude", source=str(path.resolve()), source_bytes=st.st_size,
        )
        rel = path.relative_to(cc_dir)
        session_id = path.stem
        direct_lineage = get_cc_session_lineage(path)
        if direct_lineage.get("parent_session_id"):
            parent_session_id = direct_lineage["parent_session_id"]
        try:
            external_sources = opts.setdefault("external_sources", [])
            external_start = len(external_sources)
            source_opts = {
                **opts,
                "project_path": str(project_path),
                "repo_path": str(project_path),
            }
            events_list = _collect_bounded_events(
                opts, process_cc_file(path, session_id, source_opts), session_id,
                project=str(project_path.resolve()), vendor="Claude",
                source=str(path.resolve()),
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
                    "project_path": str(project_path),
                    "project_id": opts.get("project_id"),
                    "source_cwd": session_facts.get("source_cwd"),
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
            commit_source_replacement(
                store_path,
                session=session,
                events=events_list,
                session_id=session_id,
                after_replace=partial(
                    _record_cc_source, opts, path, external_sources, external_start,
                ),
            )
            changed = True
            total_events += len(events_list)
        except Exception as e:
            _progress(
                opts, "source.failed", project=str(project_path.resolve()),
                vendor="Claude", source=str(path.resolve()),
                error_type=type(e).__name__,
            )
            log.exception("Ingest failed for %s: %s", path, e)
            record_ingest_review(
                opts, e, source=path, vendor="Claude", stage="record_mapping"
            )
            failures += 1
            if stop_on_error:
                raise
            continue
        mark_source_complete(state_path, path)
        if events_list:
            kind = "subagent" if parent_session_id else "main"
            kinds = opts.setdefault("claude_session_kinds", {"main": 0, "subagent": 0})
            kinds[kind] += 1
        ingested += int(bool(events_list))
        _progress(
            opts, "source.done", project=str(project_path.resolve()),
            vendor="Claude", source=str(path.resolve()),
            session_id=session_id, events=len(events_list),
            phase_seconds=round(time.monotonic() - source_started, 3),
        )
        del events_list
        gc.collect()
    if changed:
        conn = connect(store_path)
        try:
            prune_unreferenced_records(conn)
            conn.commit()
        finally:
            conn.close()
    return ingested, total_events, failures, changed


def _ingest_codex(
    project_path: Path,
    store_path: Path,
    state_path: Path,
    opts: dict,
    force: bool,
    min_size: int,
    *,
    stop_on_error: bool,
) -> tuple[int, int, int, bool]:
    """Return processed sessions/events, failures, and normalized-store change."""
    files = get_codex_session_files(
        project_path, index=opts.get("codex_session_index")
    )
    ingested, total_events, failures, changed = 0, 0, 0, False
    for admission in inspect_sources(
        files, state_path=state_path, force=force, min_size=min_size,
        max_source_bytes=opts.get("max_source_bytes"),
    ):
        path = admission.path
        if admission.error is not None:
            e = admission.error
            log.warning("Source validation failed for %s: %s", path, e)
            record_ingest_review(
                opts, e, source=path, vendor="Codex", stage="source_validation"
            )
            failures += 1
            if stop_on_error:
                raise e
            continue
        if admission.skip_reason:
            continue
        st = admission.stat
        mtime = st.st_mtime
        source_started = time.monotonic()
        _progress(
            opts, "source.start", project=str(project_path.resolve()),
            vendor="Codex", source=str(path.resolve()), source_bytes=st.st_size,
        )
        session_id, proj_path = get_session_meta(path)
        session_metadata = get_session_metadata(path)
        parent_session_id = session_metadata.pop(
            "parent_session_id", None
        )
        session_relation_kind = session_metadata.pop(
            "session_relation_kind", None
        )
        archive_state, archive_source = get_codex_archive_evidence(path)
        conn = connect(store_path)
        try:
            events_list = _collect_bounded_events(
                opts, process_codex_file(path, session_id, proj_path, opts), session_id,
                project=str(project_path.resolve()), vendor="Codex",
                source=str(path.resolve()),
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
                    "project_path": proj_path if proj_path != "." else str(project_path),
                    "project_id": opts.get("project_id"),
                    "source_cwd": proj_path if proj_path != "." else str(project_path),
                    "archive_state": archive_state,
                    "archive_source": archive_source,
                    "parent_session_id": parent_session_id,
                    "session_relation_kind": session_relation_kind,
                    # Observed where Codex reports them; `store` falls back to
                    # the vendor profile constant where it does not (W40).
                    "harness_name": session_metadata.get("harness_name"),
                    "surface_kind": session_metadata.get("surface_kind"),
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
            commit_source_replacement(
                store_path,
                session=session,
                events=events_list,
                session_id=session_id,
                after_replace=partial(_record_raw, opts, path, "Codex"),
            )
            changed = True
            total_events += len(events_list)
        except Exception as e:
            _progress(
                opts, "source.failed", project=str(project_path.resolve()),
                vendor="Codex", source=str(path.resolve()),
                error_type=type(e).__name__,
            )
            log.exception("Ingest failed for %s: %s", path, e)
            record_ingest_review(
                opts, e, source=path, vendor="Codex", stage="record_mapping"
            )
            failures += 1
            if stop_on_error:
                raise
            continue
        mark_source_complete(state_path, path)
        ingested += int(bool(events_list))
        _progress(
            opts, "source.done", project=str(project_path.resolve()),
            vendor="Codex", source=str(path.resolve()),
            session_id=session_id, events=len(events_list),
            phase_seconds=round(time.monotonic() - source_started, 3),
        )
        del events_list
        gc.collect()
    if changed:
        conn = connect(store_path)
        try:
            prune_unreferenced_records(conn)
            conn.commit()
        finally:
            conn.close()
    return ingested, total_events, failures, changed


def _ingest_cursor(
    project_path: Path,
    store_path: Path,
    state_path: Path,
    opts: dict,
    force: bool,
    *,
    stop_on_error: bool,
) -> tuple[int, int, int, bool]:
    """Return processed sessions/events, failures, and normalized-store change."""
    proj_str = str(project_path.resolve())
    ingested, total_events, failures, changed = 0, 0, 0, False

    workspace_ids = set(get_cursor_workspace_ids(project_path))
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
        old_session_ids = session_ids_for_source(conn, source_file)
        seen: set[str] = set()
        current_id: str | None = None
        current_events: list[dict] = []
        source_total = largest = 0
        retained_characters = retained_utf8_bytes = 0
        source_started = time.monotonic()
        current_started: float | None = None
        _progress(
            opts, "cursor.source.start", project=proj_str,
            source=source_file,
            composer_total=(len(composer_ids) if composer_ids is not None else None),
        )

        def flush() -> None:
            nonlocal current_events, largest, current_started
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
                "source_cwd": proj_str,
                "metadata": metadata,
                "source_observation": source_observation,
            }
            if headers is not None and headers[current_id].get("is_subagent"):
                # The relation and the parent travel together: a `subagent`
                # Session whose parent the store cannot name asserts a
                # relationship without its evidence. Cursor records the
                # parent in the header's `subagentInfo` (W02, 13.4.9).
                session["session_relation_kind"] = "subagent"
                session["parent_session_id"] = headers[current_id].get(
                    "parent_composer_id"
                )
            replace_session_events(
                conn, session, current_events, session_id=current_id,
                prune=False,
            )
            seen.add(current_id)
            largest = max(largest, len(current_events))
            _progress(
                opts, "cursor.composer.write.done", project=proj_str,
                composer_id=current_id, composer_index=len(seen),
                composer_total=(len(composer_ids) if composer_ids is not None else None),
                events=len(current_events),
                phase_seconds=(
                    round(time.monotonic() - current_started, 3)
                    if current_started is not None else None
                ),
            )
            current_events = []
            current_started = None

        for session_id, event in process_cursor_db(
            db_path, proj_str, opts, composer_ids=composer_ids,
            source_file=source_file, session_headers=headers,
        ):
            event_characters, event_bytes = searchable_event_payload(event)
            retained_characters += event_characters
            retained_utf8_bytes += event_bytes
            if session_id != current_id:
                if current_id is not None:
                    flush()
                    if session_id in seen:
                        raise RuntimeError(
                            f"Cursor session rows are not grouped: {session_id}"
                        )
                current_id = session_id
                current_started = time.monotonic()
                _progress(
                    opts, "cursor.composer.write.start", project=proj_str,
                    composer_id=session_id, composer_index=len(seen) + 1,
                    composer_total=(
                        len(composer_ids) if composer_ids is not None else None
                    ),
                )
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
        drop_sessions_absent_from_source(
            conn, source_file, old_session_ids - seen,
        )
        prune_unreferenced_records(conn)
        project_marker = (
            opts.get("cursor_project_markers", {}).get(proj_str)
            if composer_ids is not None else None
        )
        selected_input_bytes = (
            project_marker.get("source_size")
            if isinstance(project_marker, dict) else None
        )
        opts["resource_observations"].append({
            "source": source_file, "container": str(db_path.resolve()),
            "source_bytes": db_path.stat().st_size,
            "selected_input_bytes": selected_input_bytes,
            "selected_input_kind": (
                "cursor_selected_values"
                if selected_input_bytes is not None else "unmeasured"
            ),
            "events": source_total, "largest_session_events": largest,
            "retained_searchable_characters": retained_characters,
            "retained_searchable_utf8_bytes": retained_utf8_bytes,
            "peak_rss_bytes": peak_rss_bytes(),
        })
        _progress(
            opts, "cursor.source.done", project=proj_str, source=source_file,
            sessions=len(seen), events=source_total,
            largest_session_events=largest,
            phase_seconds=round(time.monotonic() - source_started, 3),
        )
        return len(seen), source_total

    dbs = get_cursor_workspace_dbs(project_path)
    for db_path in dbs:
        try:
            mtime = db_path.stat().st_mtime
            check_source(db_path, opts.get("max_cursor_container_bytes"))
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
            _progress(
                opts, "cursor.workspace.skip", project=proj_str,
                source=str(db_path.resolve()), reason="unchanged",
            )
            continue
        try:
            has_bubbles = cursor_has_bubble_rows(db_path)
        except (OSError, sqlite3.Error) as e:
            log.warning("Cursor workspace probe failed for %s: %s", db_path, e)
            record_ingest_review(
                opts, e, source=db_path, vendor="Cursor",
                stage="workspace_selection",
            )
            failures += 1
            if stop_on_error:
                raise
            continue
        if not has_bubbles:
            state = load_ingest_state(state_path)
            state[state_key] = ingest_state_marker(db_path)
            save_ingest_state(state_path, state)
            _progress(
                opts, "cursor.workspace.skip", project=proj_str,
                source=str(db_path.resolve()), reason="no-bubble-rows",
            )
            continue
        conn = connect(store_path)
        try:
            db_sessions, db_events = ingest_db_stream(conn, db_path, mtime)
            _record_raw(opts, db_path, "Cursor", conn)
            conn.commit()
            changed = True
            total_events += db_events
        except Exception as e:
            conn.rollback()
            _progress(
                opts, "cursor.source.failed", project=proj_str,
                source=str(db_path.resolve()), error_type=type(e).__name__,
            )
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
            opts.get("cursor_project_markers", {}).get(proj_str)
            or opts.get("cursor_cohort_marker")
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
            _progress(
                opts, "cursor.project.unchanged", project=proj_str,
                source=str(global_source.resolve()),
            )
            return ingested, total_events, failures, changed
        headers = (
            opts.get("cursor_project_headers", {}).get(proj_str)
            or get_composer_headers(global_db, workspace_ids)
        )
        if not headers:
            if opts.get("debug"):
                log.debug(
                    "No global Cursor composers mapped to %s via workspace ids %s",
                    project_path,
                    sorted(workspace_ids),
                )
            _progress(
                opts, "cursor.project.no_composers", project=proj_str,
                workspace_ids=len(workspace_ids),
            )
            return ingested, total_events, failures, changed
        try:
            marker_mtime = detection_marker.get("source_mtime")
            mtime = (
                float(marker_mtime) / 1000
                if isinstance(marker_mtime, (int, float))
                else global_db.stat().st_mtime
            )
            check_source(global_db, opts.get("max_cursor_container_bytes"))
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
                    changed = True
                    total_events += db_events
                except Exception as e:
                    conn.rollback()
                    _progress(
                        opts, "cursor.source.failed", project=proj_str,
                        source=str(global_source.resolve()),
                        error_type=type(e).__name__,
                    )
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

    _progress(
        opts, "cursor.project.done", project=proj_str,
        processed_sessions=ingested, processed_events=total_events,
        failed_sources=failures,
    )
    return ingested, total_events, failures, changed
