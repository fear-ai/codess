"""Post-ingest publication for one Project.

After a Project's vendor stores are written, four things decide what becomes
current: the catalog entries are re-synced, external Artifacts are correlated,
a fresh rebuild's staged stores are promoted over the working ones, and a
snapshot is created when anything actually changed. These transactions belong to the
ingest domain rather than to the command that adapts arguments and renders reports.

Each phase takes what it needs and returns what the caller records; none
mutates a caller's local. `promote_rebuilt_stores` and `publish_snapshot`
return their results -- promoted store names, and the published snapshot
identity -- so the command layer writes its runtime report from returned
values rather than from state a callee reached into.

The phases are ordered by dependency, not by convenience: promotion must
precede the snapshot, because a snapshot taken before promotion would record
the stores the rebuild replaced.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from codess.artifact_correlation import correlate_external_artifacts
from codess.config import (
    ADAPTER_KEYS,
    STORE_DIR,
    VENDOR_KEY_BY_ADAPTER,
    VENDOR_KEYS,
    VENDORS,
    get_state_path,
    get_store_path,
)
from codess.project_catalog import load_catalog
from codess.snapshot import create_snapshot, current_snapshot, read_manifest
from codess.store import connect, record_processing_run

log = logging.getLogger(__name__)

# Projections of `config.VENDORS`, kept as names because both directions are
# used at call sites that read better with a mapping than with a lookup.
VENDOR_DISPLAY_NAMES = {
    key: description["adapter_key"] for key, description in VENDORS.items()
}
"""Vendor key to the name used in catalogs, reports, and store filenames."""

VENDOR_SOURCE_KEYS = VENDOR_KEY_BY_ADAPTER


class StoreLocator(Protocol):
    """What publication needs from the run configuration.

    Publication locates stores and reads a handful of settings; it does not
    need the rest of `IngestConfig`. Stating that as a protocol keeps the
    dependency pointing from the command layer into the domain rather than
    back out of it.
    """

    def store_path(self, project_path: Path, source_key: str) -> Path: ...

    def __getitem__(self, key: str) -> Any: ...


@dataclass
class PublicationOutcome:
    """What publication produced for one Project.

    `snapshot_id` is the current snapshot after publication, which is the
    prior one when nothing changed -- the runtime report records what is
    current, not only what this run wrote. `candidate_path` is set only when
    the snapshot was created for review rather than published.
    """

    snapshot_id: str | None = None
    candidate_path: str | None = None
    promoted_stores: list[str] = None  # type: ignore[assignment]
    derived_changed: bool = False
    snapshot_required: bool = False
    """Whether anything changed that a new snapshot must record.

    Distinct from `derived_changed`, which reports only that a store was
    written during correlation or content processing. The evidence summary is
    reused across runs when this is false, so conflating the two would reuse a
    summary for a Project whose stores had in fact changed.
    """

    def __post_init__(self) -> None:
        if self.promoted_stores is None:
            self.promoted_stores = []

    @property
    def publication(self) -> str:
        """How the snapshot was published, as the runtime report states it."""
        return "candidate" if self.candidate_path is not None else "current_or_unchanged"


def current_snapshot_id(project_path: Path) -> str | None:
    """The verified current snapshot's identity, or None if there is none."""
    resolved = current_snapshot(project_path / STORE_DIR)
    if resolved is None:
        return None
    _snapshot_path, pointer = resolved
    snapshot_id = pointer.get("snapshot_id")
    return str(snapshot_id) if snapshot_id else None


def current_snapshot_is_sealed(project_path: Path) -> bool:
    """Whether the verified current snapshot already embeds raw objects."""
    resolved = current_snapshot(project_path / STORE_DIR)
    if resolved is None:
        return False
    snapshot_path, _pointer = resolved
    return read_manifest(snapshot_path).get("sealed") is True


def resync_project_catalog(
    config: StoreLocator,
    project_path: Path,
    project_entry: dict,
    *,
    create_store: Callable[[str, dict], bool],
) -> set[str]:
    """Re-sync every existing vendor store's catalog entry after ingest.

    The Project entry can change while sources are read -- a new location, a
    renamed workspace -- so each store is brought back into agreement before
    publication decides what to republish. Stores that do not exist are
    skipped rather than created: this reconciles, it does not provision.

    Returns the display names whose catalog entry changed.
    """
    changed: set[str] = set()
    for source_key, display in VENDOR_DISPLAY_NAMES.items():
        if not config.store_path(project_path, source_key).exists():
            continue
        if create_store(source_key, project_entry):
            changed.add(display)
    return changed


def correlate_project_artifacts(
    config: StoreLocator,
    project_path: Path,
    vendors: set[str],
    store_root: Path,
    *,
    diagnostics: dict[str, int],
    progress_trace,
) -> bool:
    """Correlate external Artifacts in every store this run touched.

    Runs only for vendors whose store or catalog entry changed, since
    correlation is derived from content that did not move otherwise. Returns
    whether any store was written, which publication uses to decide if a new
    snapshot is warranted.
    """
    derived_changed = False
    catalog = load_catalog(store_root) if vendors else None
    for vendor in sorted(vendors):
        path = config.store_path(project_path, VENDOR_SOURCE_KEYS[vendor])
        if not path.exists():
            continue
        correlation_started = time.monotonic()
        progress_trace(
            "artifact_correlation.start", project=str(project_path), vendor=vendor,
        )
        conn = connect(path)
        try:
            correlation_counts = correlate_external_artifacts(conn, catalog)
            conn.commit()
            derived_changed = True
        finally:
            conn.close()
        for key, value in correlation_counts.items():
            diagnostics[f"artifact_correlation_{key}"] = (
                diagnostics.get(f"artifact_correlation_{key}", 0) + value
            )
        progress_trace(
            "artifact_correlation.done", project=str(project_path), vendor=vendor,
            external_artifacts=correlation_counts.get("external_artifacts", 0),
            matched=correlation_counts.get("matched", 0),
            ambiguous=correlation_counts.get("ambiguous", 0),
            unmatched=correlation_counts.get("unmatched", 0),
            phase_seconds=round(time.monotonic() - correlation_started, 3),
        )
    return derived_changed


def record_content_processing(
    config: StoreLocator,
    project_path: Path,
    vendors: set[str],
    *,
    project_id: str,
    policy: dict,
    actions: list[dict],
) -> bool:
    """Record the content policy each changed store was written under.

    Returns whether any store was written, so publication counts this as a
    reason to snapshot: the processing run is stored evidence, and a snapshot
    taken without it would not describe the store it names.
    """
    written = False
    for vendor in sorted(vendors):
        path = config.store_path(project_path, VENDOR_SOURCE_KEYS[vendor])
        if not path.exists():
            continue
        conn = connect(path)
        try:
            record_processing_run(
                conn,
                project_id=project_id,
                policy=policy,
                actions=[
                    action for action in actions if action.get("vendor") == vendor
                ],
            )
            conn.commit()
            written = True
        finally:
            conn.close()
    return written


def promote_rebuilt_stores(
    project_path: Path,
    staged_project: Path,
    sources: list[str] | tuple[str, ...],
    *,
    retain_prior: bool,
) -> list[str]:
    """Replace the working stores with a completed rebuild's staged ones.

    `retain_prior` is what makes a failed rebuild non-destructive: when a
    rebuild fails and the Project already had stores, the staged tree is
    discarded and the existing stores stay current, so a partial rebuild
    cannot replace complete data. Returns the promoted store filenames.

    The journal, WAL, and shared-memory sidecars of the replaced store are
    removed rather than left behind: they describe the file that was replaced,
    and SQLite would otherwise read them against the new one.
    """
    if retain_prior:
        return []
    promoted: list[str] = []
    for source_key in VENDOR_KEYS:
        if source_key not in sources:
            continue
        vendor = VENDOR_DISPLAY_NAMES[source_key]
        staged_path = get_store_path(staged_project, vendor)
        if not staged_path.exists():
            continue
        target = get_store_path(project_path, vendor)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged_path, target)
        for suffix in ("-journal", "-wal", "-shm"):
            Path(str(target) + suffix).unlink(missing_ok=True)
        promoted.append(target.name)
    staged_state = get_state_path(staged_project)
    if staged_state.exists():
        target_state = get_state_path(project_path)
        target_state.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged_state, target_state)
    return promoted


def publish_snapshot(
    config: StoreLocator,
    project_path: Path,
    raw_records: list[dict],
    *,
    raw_store,
    store_root: Path,
    project_id: str,
    sources: list[str] | tuple[str, ...],
    minimum_source_size: int,
    required: bool,
    progress_trace,
) -> tuple[str | None, str | None]:
    """Create a snapshot over the Project's working stores when one is due.

    Returns the current snapshot identity and, when the snapshot was created
    for review rather than published, its path. An unchanged Project keeps the
    identity it already had: the caller records what is current, so reporting
    None here would read as "no snapshot exists" rather than "none was made".

    Nothing is created when the Project retains no raw records, since a
    snapshot binds stores to the source evidence they were derived from and
    would have nothing to bind.
    """
    snapshot_id = current_snapshot_id(project_path)
    if not raw_records:
        return snapshot_id, None
    if not required:
        progress_trace(
            "snapshot.skip", project=str(project_path), reason="unchanged",
        )
        return snapshot_id, None

    working_stores = [
        get_store_path(project_path, adapter_key) for adapter_key in ADAPTER_KEYS
    ]
    present = [path for path in working_stores if path.exists()]
    sealing = config["raw_mode"] == "seal"
    candidate = bool(config["candidate_snapshot"])
    snapshot_started = time.monotonic()
    progress_trace(
        "snapshot.start", project=str(project_path), stores=len(present),
        raw_records=len(raw_records), sealed=sealing,
    )
    snapshot_path = create_snapshot(
        project_path,
        present,
        raw_records,
        raw_store=raw_store,
        seal=sealing,
        build_policy={
            "raw_mode": config["raw_mode"],
            "selected_sources": list(sources),
            "minimum_source_size": minimum_source_size,
            "redaction_enabled": config["redact"],
        },
        store_root=store_root,
        project_id=project_id,
        publish=not candidate,
    )
    progress_trace(
        "snapshot.done", project=str(project_path), snapshot_id=snapshot_path.name,
        publication="candidate" if candidate else "current",
        phase_seconds=round(time.monotonic() - snapshot_started, 3),
    )
    return snapshot_path.name, (str(snapshot_path) if candidate else None)
