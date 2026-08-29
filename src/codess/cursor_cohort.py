"""Reusable, transactionally consistent Cursor capture cohorts.

**Owns caching.** One Cursor database backs many Projects, so capturing it
once per run and reusing that copy is what keeps a multi-Project ingest from
re-reading the same shared store. This module decides when a cached cohort is
still valid, records the selection it was captured under, and restores it;
it does not choose which rows to read, which is `cursor_source`'s concern
(see the ownership table there).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codess.fileio import write_json_atomic
from codess.hashing import codess_canonical_hash
from codess.raw_store import RawCaptureError, RawStore, restore_raw
from codess.store import ingest_state_marker, load_ingest_state

CACHE_FORMAT = "codess.cursor-cohort-cache/1"
SELECTION_CACHE_FORMAT = "codess.cursor-selection-cache/2"


@dataclass(frozen=True)
class CursorSelection:
    """Which Cursor rows one run will read, and from where.

    The four values are derived together from the Project roots and are used
    together by every step that follows -- fingerprinting, cache validation,
    and cohort capture -- so they travelled as four separate parameters
    through the whole preflight. They are one fact: the Cursor scope of this
    run.

    `global_db` is None when no root has Cursor workspaces, which is also
    when `roots` is empty; `empty` reads that as the single question callers
    actually ask.
    """

    workspace_ids: Mapping[Path, set[str]]
    global_db: Path | None
    project_headers: Mapping[str, Any]

    @property
    def roots(self) -> list[Path]:
        """Project roots with Cursor workspaces, in discovery order."""
        return list(self.workspace_ids)

    @property
    def empty(self) -> bool:
        """Whether this run reads any Cursor data at all."""
        return not self.workspace_ids or self.global_db is None

    def selections(self) -> dict[str, set[str]]:
        """Workspace IDs per Project root, keyed as the cache records them."""
        return {str(root): ids for root, ids in self.workspace_ids.items()}


def _canonical_selections(
    selections: dict[str, set[str]],
) -> dict[str, list[str]]:
    return {
        project: sorted(workspace_ids)
        for project, workspace_ids in sorted(selections.items())
    }


def load_selection_marker_cache(
    cache_path: Path,
    *,
    source: Path,
    container_marker: dict[str, Any],
    selections: dict[str, set[str]],
) -> dict[str, dict[str, Any]] | None:
    """Reuse selected markers only for the same unchanged main/WAL container."""
    try:
        value = json.loads(cache_path.read_text(encoding="utf-8"))
        markers = value["project_markers"]
        if (
            value.get("cache_format") != SELECTION_CACHE_FORMAT
            or value.get("source_locator") != str(source.resolve())
            or value.get("container_marker") != container_marker
            or value.get("selections") != _canonical_selections(selections)
            or not isinstance(markers, dict)
            or set(markers) != set(selections)
            or not all(isinstance(marker, dict) for marker in markers.values())
        ):
            return None
        return markers
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None


def save_selection_marker_cache(
    cache_path: Path,
    *,
    source: Path,
    container_marker: dict[str, Any],
    selections: dict[str, set[str]],
    project_markers: dict[str, dict[str, Any]],
) -> None:
    """Atomically retain only the latest metadata-only selected-marker set."""
    write_json_atomic(cache_path, {
        "cache_format": SELECTION_CACHE_FORMAT,
        "source_locator": str(source.resolve()),
        "container_marker": container_marker,
        "selections": _canonical_selections(selections),
        "project_markers": project_markers,
    })


def combine_selection_markers(
    markers: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return one cache key for a set of per-Project Cursor selections."""
    digest = codess_canonical_hash(
        256, 256, [[project, markers[project]] for project in sorted(markers)]
    )
    mtimes = [
        marker.get("source_mtime") for marker in markers.values()
        if isinstance(marker.get("source_mtime"), (int, float))
    ]
    return {
        "source_revision": f"cursor-cohort-selection-digest-fingerprint:{digest}",
        "source_mtime": max(mtimes) if mtimes else None,
        "source_size": sum(
            int(marker.get("source_size") or 0) for marker in markers.values()
        ),
        "fingerprint_method": "cursor-combined-project-selection-digest-fingerprint",
        "consistency": "composed-sqlite-read-transactions",
        "project_count": len(markers),
    }


@dataclass(frozen=True)
class SelectionMarkers:
    """The selection fingerprint for a run, and how it was obtained.

    `status` is evidence rather than decoration: `reused` means the cache
    answered, `scanned` means the store was read and the result cached, and
    `scanned-unstable` means Cursor wrote to its own database while the read
    was in progress, so the markers describe a state that no longer holds and
    were deliberately not cached.
    """

    per_project: dict[str, dict[str, Any]]
    combined: dict[str, Any]
    status: str


def resolve_selection_markers(
    cache_path: Path,
    *,
    source: Path,
    selections: dict[str, Any],
    supplemental_headers: Any,
    observe_containers: Callable[[], dict],
    read_markers: Callable[..., dict[str, dict[str, Any]]],
    force: bool = False,
    attempts: int = 2,
) -> SelectionMarkers:
    """Resolve the Cursor selection markers, from cache or by reading.

    **Why this decision lives here.** It is the cache question this module
    exists to answer -- may a previously computed selection be reused, and if
    not, is a freshly read one safe to keep? It ran inside the ingest command,
    where a 247-line phase decided Cursor read strategy on the wrong side of
    the layering: a command adapts arguments and renders results (5.2), and
    `cursor_cohort` already declares that it owns caching.

    **The container bracket is the correctness argument, not an optimization.**
    `read_markers` holds one read transaction, so the markers it returns are
    internally consistent -- but SQLite's snapshot ends with that transaction,
    and Cursor writes to its own store continuously. Observing the container
    before and after and requiring equality is what detects a write landing
    across the read. Caching an unstable result would persist a fingerprint
    for a state not on disk, and a later run would then skip a Project whose
    evidence had in fact changed.

    Reading is retried once on instability rather than failing: a single
    concurrent write is ordinary. A second failure returns `scanned-unstable`
    markers that are used for this run and not cached, which is the honest
    outcome -- the fingerprint describes what was read, and nothing claims it
    still holds.
    """
    container_marker = observe_containers()
    per_project: dict[str, dict[str, Any]] | None = None
    status = "scanned"

    if not force:
        per_project = load_selection_marker_cache(
            cache_path,
            source=source,
            container_marker=container_marker,
            selections=selections,
        )
        if per_project is not None:
            status = "reused"

    if per_project is None:
        for _attempt in range(attempts):
            container_before = observe_containers()
            per_project = read_markers(
                source, selections, supplemental_headers=supplemental_headers,
            )
            container_after = observe_containers()
            if container_before == container_after:
                save_selection_marker_cache(
                    cache_path,
                    source=source,
                    container_marker=container_after,
                    selections=selections,
                    project_markers=per_project,
                )
                break
        else:
            status = "scanned-unstable"

    return SelectionMarkers(
        per_project=per_project or {},
        combined=combine_selection_markers(per_project or {}),
        status=status,
    )


def cohort_state_key(source: Path) -> str:
    return f"cursor:global:{source.resolve()}"


def cohort_needed(
    source: Path,
    project_state_paths: list[Path],
    marker: dict[str, Any],
    *,
    force: bool,
) -> bool:
    """Return whether any selected Project lacks the current change marker."""
    if force:
        return True
    key = cohort_state_key(source)
    return any(load_ingest_state(path).get(key) != marker for path in project_state_paths)


def _load_cached_record(
    cache_path: Path,
    source: Path,
    marker: dict[str, Any],
    raw_store: RawStore,
) -> dict[str, Any] | None:
    try:
        value = json.loads(cache_path.read_text(encoding="utf-8"))
        record = value["raw_record"]
        if (
            value.get("cache_format") != CACHE_FORMAT
            or value.get("source_locator") != str(source.resolve())
            or value.get("source_marker") != marker
            or not isinstance(record, dict)
            or record.get("availability") != "captured"
            or record.get("source_locator") != str(source.resolve())
        ):
            return None
        object_path = raw_store.resolve(record)
        if object_path is None or not object_path.is_file():
            return None
        expected_size = record.get("stored_size")
        if isinstance(expected_size, int) and object_path.stat().st_size != expected_size:
            return None
        return record
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None


def prepare_cursor_cohort(
    source: Path,
    *,
    raw_store: RawStore,
    cache_path: Path,
    working_path: Path,
    source_system_key: str,
    storage_format: str,
    marker: dict[str, Any],
    force: bool,
    progress: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Materialize a reusable cohort, capturing only after a cache miss.

    The cache contains metadata only.  A hit still verifies the retained raw
    object while restoring it to a transient SQLite file; it never creates a
    second persistent copy of the multi-gigabyte database.
    """
    if not force:
        cached = _load_cached_record(cache_path, source, marker, raw_store)
        if cached is not None:
            object_path = raw_store.resolve(cached)
            try:
                phase_tick = time.monotonic()
                if progress is not None:
                    progress(
                        "cursor.cohort.restore.start",
                        object_id=cached.get("object_id"),
                        stored_bytes=cached.get("stored_size"),
                    )
                restore_raw(object_path, working_path, cached)
                if progress is not None:
                    progress(
                        "cursor.cohort.restore.done",
                        object_id=cached.get("object_id"),
                        working_bytes=cached.get("uncompressed_size"),
                        phase_seconds=round(time.monotonic() - phase_tick, 3),
                    )
                return cached, marker, "reused"
            except RawCaptureError:
                # Fall through to a fresh transactional backup.  If the
                # content-addressed object itself is corrupt, capture will also
                # reject it instead of hiding the failure.
                pass

    record = raw_store.observe(
        source,
        source_system_key=source_system_key,
        storage_format=storage_format,
        mode="capture",
        working_target=working_path,
        progress=progress,
    )
    # Re-read the source revision after the backup: if it moved during the
    # capture window, annotate the record rather than assume a quiescent source.
    post_marker = ingest_state_marker(source)
    source_advanced = (
        post_marker.get("source_revision") != marker.get("source_revision")
    )
    stability = "source_advanced" if source_advanced else "stable_during_capture"
    if source_advanced and progress is not None:
        progress(
            "cursor.cohort.source_advanced",
            source=str(source.resolve()),
            pre_revision=marker.get("source_revision"),
            post_revision=post_marker.get("source_revision"),
        )
    record["change_detection"] = {
        "source_revision": marker.get("source_revision"),
        "fingerprint_method": marker.get("fingerprint_method"),
        "consistency": marker.get("consistency"),
        "capture_stability": stability,
        "post_capture_revision": post_marker.get("source_revision"),
    }
    write_json_atomic(cache_path, {
        "cache_format": CACHE_FORMAT,
        "source_locator": str(source.resolve()),
        "source_marker": marker,
        "raw_record": record,
    })
    return record, marker, "captured"
