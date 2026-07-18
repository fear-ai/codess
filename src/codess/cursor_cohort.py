"""Reusable, transactionally consistent Cursor capture cohorts."""

from __future__ import annotations

import json
import hashlib
import time
from pathlib import Path
from typing import Any, Callable

from codess.fileio import write_json_atomic
from codess.raw_store import RawCaptureError, RawStore, materialize_captured_object
from codess.store import load_ingest_state


CACHE_FORMAT = "codess.cursor-cohort-cache/1"
SELECTION_CACHE_FORMAT = "codess.cursor-selection-cache/1"


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
    canonical = json.dumps(
        [[project, markers[project]] for project in sorted(markers)],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        digest = hashlib.md5(canonical, usedforsecurity=False).hexdigest()
    except TypeError:  # pragma: no cover - older Python/OpenSSL combinations
        digest = hashlib.md5(canonical).hexdigest()
    mtimes = [
        marker.get("source_mtime") for marker in markers.values()
        if isinstance(marker.get("source_mtime"), (int, float))
    ]
    return {
        "source_revision": f"cursor-cohort-selection-md5-fingerprint:{digest}",
        "source_mtime": max(mtimes) if mtimes else None,
        "source_size": sum(
            int(marker.get("source_size") or 0) for marker in markers.values()
        ),
        "fingerprint_method": "cursor-combined-project-selection-md5-fingerprint",
        "consistency": "composed-sqlite-read-transactions",
        "project_count": len(markers),
    }


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
    materialized_path: Path,
    source_system_id: str,
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
                phase_started = time.monotonic()
                if progress is not None:
                    progress(
                        "cursor.cohort.restore.start",
                        object_id=cached.get("object_id"),
                        stored_bytes=cached.get("stored_size"),
                    )
                materialize_captured_object(object_path, materialized_path, cached)
                if progress is not None:
                    progress(
                        "cursor.cohort.restore.done",
                        object_id=cached.get("object_id"),
                        materialized_bytes=cached.get("uncompressed_size"),
                        phase_seconds=round(time.monotonic() - phase_started, 3),
                    )
                return cached, marker, "reused"
            except RawCaptureError:
                # Fall through to a fresh transactional backup.  If the
                # content-addressed object itself is corrupt, capture will also
                # reject it instead of hiding the failure.
                pass

    record = raw_store.observe(
        source,
        source_system_id=source_system_id,
        storage_format=storage_format,
        mode="capture",
        materialized_target=materialized_path,
        progress=progress,
    )
    record["change_detection"] = {
        "source_revision": marker.get("source_revision"),
        "fingerprint_method": marker.get("fingerprint_method"),
        "consistency": marker.get("consistency"),
    }
    write_json_atomic(cache_path, {
        "cache_format": CACHE_FORMAT,
        "source_locator": str(source.resolve()),
        "source_marker": marker,
        "raw_record": record,
    })
    return record, marker, "captured"
