"""Latest-snapshot retention planning and explicit, validated pruning."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codess.config import (
    CURRENT_POINTER_FILE,
    LARGE_RAW_REVISION_BYTES,
    RAW_MANIFEST_FILE,
    SNAPSHOTS_DIR,
    STORE_DIR,
    WORKING_ARCHIVES_DIR,
)
from codess.fileio import hash_file, open_readonly, write_json_atomic
from codess.hashing import codess_canonical_hash
from codess.resources import storage_usage
from codess.snapshot import SnapshotError, current_snapshot, read_manifest

PLAN_FORMAT = "codess.retention-plan/1"
RECEIPT_FORMAT = "codess.retention-receipt/1"


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _raw_records(snapshot: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with (snapshot / RAW_MANIFEST_FILE).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid raw manifest {snapshot}:{number}: {exc}") from exc
            if isinstance(value, dict) and value.get("record_type") != "header":
                records.append(value)
    return records


def _validate_current(
    project_path: Path, raw_root: Path,
) -> tuple[Path, set[str], list[dict[str, Any]]]:
    """Validate the current snapshot is safe to keep before planning deletion
    of everything else. Delegates the pointer-read and manifest_sha256 check
    to `snapshot.current_snapshot` -- the same check every other
    current-snapshot consumer relies on -- then applies retention-specific
    checks that function does not perform: the snapshot must be contained
    inside this project's own `snapshots/` directory (not an unrelated path
    the pointer happens to name), its directory name must equal its claimed
    snapshot_id, its raw manifest and every store file must hash-match the
    manifest, every store must pass a SQLite quick_check, and every raw
    object the snapshot references must exist at its recorded size.
    """
    try:
        resolved = current_snapshot(project_path)
    except SnapshotError as exc:
        raise RuntimeError(str(exc)) from exc
    if resolved is None:
        raise RuntimeError(f"invalid current pointer: {project_path / CURRENT_POINTER_FILE}")
    snapshot, resolved_pointer = resolved
    snapshot_id = resolved_pointer.get("snapshot_id")
    if not isinstance(snapshot_id, str):
        raise RuntimeError(f"invalid current pointer: {project_path / CURRENT_POINTER_FILE}")
    expected_root = project_path / SNAPSHOTS_DIR
    if snapshot.name != snapshot_id or not _inside(snapshot, expected_root) or not snapshot.is_dir():
        raise RuntimeError(f"current snapshot escapes or is absent: {snapshot}")
    manifest = read_manifest(snapshot)
    if manifest.get("snapshot_id") != snapshot_id:
        raise RuntimeError(f"manifest identity mismatch: {snapshot}")
    raw_manifest = snapshot / RAW_MANIFEST_FILE
    if hash_file(raw_manifest) != manifest.get("raw_manifest_sha256"):
        raise RuntimeError(f"raw manifest hash mismatch: {snapshot}")
    for name, entry in manifest.get("stores", {}).items():
        store = snapshot / name
        if not _inside(store, snapshot) or hash_file(store) != entry.get("sha256"):
            raise RuntimeError(f"snapshot store hash mismatch: {store}")
        conn = open_readonly(store)
        try:
            result = conn.execute("PRAGMA quick_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"snapshot SQLite quick_check failed: {store}: {result}")
        finally:
            conn.close()
    raw_references: set[str] = set()
    raw_records = _raw_records(snapshot)
    for record in raw_records:
        relpath = record.get("object_relpath")
        if not isinstance(relpath, str):
            continue
        obj = raw_root / relpath
        if not _inside(obj, raw_root) or not obj.is_file():
            raise RuntimeError(f"current snapshot raw object absent or unsafe: {obj}")
        expected_size = record.get("stored_size")
        if isinstance(expected_size, int) and obj.stat().st_size != expected_size:
            raise RuntimeError(f"current snapshot raw object size mismatch: {obj}")
        raw_references.add(relpath)
    return snapshot.resolve(), raw_references, raw_records


def _large_shared_revisions(
    records: list[tuple[Path, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Find distinct huge revisions of one logical source kept as current."""
    grouped: dict[tuple[str, str], dict[str, tuple[Path, dict[str, Any]]]] = {}
    for snapshot, record in records:
        if record.get("availability") != "captured":
            continue
        size = record.get("uncompressed_size")
        relpath = record.get("object_relpath")
        locator = record.get("source_locator")
        system = record.get("source_system_id")
        if (
            not isinstance(size, int) or size < LARGE_RAW_REVISION_BYTES
            or not all(isinstance(value, str) and value for value in (relpath, locator, system))
        ):
            continue
        grouped.setdefault((system, locator), {})[relpath] = (snapshot, record)
    conflicts: list[dict[str, Any]] = []
    for (system, locator), revisions in sorted(grouped.items()):
        if len(revisions) < 2:
            continue
        items = []
        for relpath, (snapshot, record) in sorted(
            revisions.items(), key=lambda item: str(item[1][1].get("observed_at") or "")
        ):
            items.append({
                "snapshot_id": snapshot.name,
                "observed_at": record.get("observed_at"),
                "source_revision_id": record.get("source_revision_id"),
                "object_relpath": relpath,
                "uncompressed_size": record.get("uncompressed_size"),
                "stored_size": record.get("stored_size"),
            })
        conflicts.append({
            "source_system_id": system,
            "source_locator": locator,
            "revision_count": len(items),
            "stored_bytes": sum(int(item.get("stored_size") or 0) for item in items),
            "revisions": items,
        })
    return conflicts


def _catalog_references(paths: list[Path], current_ids: set[str], delete_ids: set[str]) -> dict[str, Any]:
    result = {"catalogs": [], "blocking": [], "historical_only": []}
    for path in paths:
        if not path.exists():
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        entries = value.get("projects", []) if isinstance(value, dict) else []
        item = {"path": str(path), "current": 0, "stale": 0, "historical": 0}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            snapshot_id = entry.get("snapshot_id")
            parent_id = entry.get("parent_snapshot_id")
            if snapshot_id in current_ids:
                item["current"] += 1
            elif snapshot_id in delete_ids:
                item["stale"] += 1
                result["blocking"].append({"path": str(path), "snapshot_id": snapshot_id})
            if parent_id in delete_ids:
                item["historical"] += 1
                result["historical_only"].append({"path": str(path), "snapshot_id": parent_id})
        result["catalogs"].append(item)
    return result


def _local_pointer_references(registry: Path, current_by_project: dict[str, str], delete_ids: set[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"checked": 0, "current": 0, "missing": 0, "blocking": []}
    catalog_path = registry / "projects.json"
    if not catalog_path.exists():
        return result
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    for project in catalog.get("projects", []):
        if not isinstance(project, dict):
            continue
        project_id = str(project.get("project_id") or "")
        expected = current_by_project.get(project_id.rsplit(":", 1)[-1])
        if expected is None:
            continue
        for location in project.get("locations", []):
            if not isinstance(location, dict) or location.get("state") != "active":
                continue
            pointer_path = Path(str(location.get("path") or "")) / STORE_DIR / CURRENT_POINTER_FILE
            result["checked"] += 1
            if not pointer_path.exists():
                result["missing"] += 1
                continue
            try:
                observed = json.loads(pointer_path.read_text(encoding="utf-8")).get("snapshot_id")
            except (OSError, json.JSONDecodeError):
                observed = None
            if observed == expected:
                result["current"] += 1
            elif observed in delete_ids:
                result["blocking"].append({
                    "path": str(pointer_path), "snapshot_id": observed,
                    "expected_snapshot_id": expected,
                })
    return result


def _working_archives(
    registry: Path, current_by_project: dict[str, str],
) -> list[Path]:
    """Return pre-package archives only from active, current catalog locations."""
    catalog_path = registry / "projects.json"
    if not catalog_path.exists():
        return []
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    archives: set[Path] = set()
    for project in catalog.get("projects", []):
        if not isinstance(project, dict):
            continue
        project_key = str(project.get("project_id") or "").rsplit(":", 1)[-1]
        if project_key not in current_by_project:
            continue
        for location in project.get("locations", []):
            if not isinstance(location, dict) or location.get("state") != "active":
                continue
            root = Path(str(location.get("path") or ""))
            archive = root / STORE_DIR / WORKING_ARCHIVES_DIR
            if archive.is_dir() and _inside(archive, root / STORE_DIR):
                archives.add(archive.resolve())
    return sorted(archives)


def build_retention_plan(
    registry: Path, *, reference_catalogs: list[Path] | None = None,
    include_working_archives: bool = False,
    allow_large_comparison_revisions: bool = False,
) -> dict[str, Any]:
    """Plan current snapshots and enforce explicit retention of huge revisions."""
    registry = registry.expanduser().resolve()
    projects_root = registry / "projects"
    raw_root = registry / "raw" / "codess.raw-1"
    current: list[Path] = []
    current_by_project: dict[str, str] = {}
    raw_keep: set[str] = set()
    current_raw_records: list[tuple[Path, dict[str, Any]]] = []
    errors: list[str] = []
    for project_path in sorted(path for path in projects_root.iterdir() if path.is_dir()) if projects_root.exists() else []:
        pointer_path = project_path / CURRENT_POINTER_FILE
        if not pointer_path.exists():
            errors.append(f"project has no current pointer: {project_path}")
            continue
        try:
            snapshot, references, records = _validate_current(project_path, raw_root)
            current.append(snapshot)
            current_by_project[project_path.name] = snapshot.name
            raw_keep.update(references)
            current_raw_records.extend((snapshot, record) for record in records)
        except (OSError, ValueError, KeyError, json.JSONDecodeError, sqlite3.Error, RuntimeError) as exc:
            errors.append(str(exc))
    all_snapshots = sorted(
        path.resolve() for path in projects_root.glob("*/snapshots/*") if path.is_dir()
    ) if projects_root.exists() else []
    current_set = set(current)
    delete_snapshots = [path for path in all_snapshots if path not in current_set]
    objects_root = raw_root / "objects"
    all_objects = sorted(path for path in objects_root.rglob("*.zst") if path.is_file()) if objects_root.exists() else []
    delete_objects = [
        path for path in all_objects
        if str(path.relative_to(raw_root)) not in raw_keep
    ]
    current_ids = {path.name for path in current}
    delete_ids = {path.name for path in delete_snapshots}
    references = _catalog_references(reference_catalogs or [], current_ids, delete_ids)
    references["local_pointers"] = _local_pointer_references(
        registry, current_by_project, delete_ids
    )
    working_archives = _working_archives(registry, current_by_project)
    large_shared_revisions = _large_shared_revisions(current_raw_records)
    if references["blocking"]:
        errors.append("a reference catalog selects a superseded snapshot; refreeze or drop that catalog entry before pruning")
    if references["local_pointers"]["blocking"]:
        errors.append("an active Project location points to a superseded snapshot; rebuild or synchronize that validated current pointer before pruning")
    if large_shared_revisions and not allow_large_comparison_revisions:
        errors.append(
            "multiple current revisions of a >=1 GiB logical raw source are retained; "
            "rebuild those Projects against one capture cohort, or explicitly select "
            "--keep-comparison-revisions when the revisions are comparison evidence"
        )
    identity = {
        "current": [str(path) for path in current],
        "delete_snapshots": [str(path) for path in delete_snapshots],
        "raw_keep": sorted(raw_keep),
        "delete_objects": [str(path) for path in delete_objects],
        "delete_working_archives": (
            [str(path) for path in working_archives]
            if include_working_archives else []
        ),
        "large_shared_revisions": large_shared_revisions,
        "allow_large_comparison_revisions": allow_large_comparison_revisions,
    }
    plan_sha256 = codess_canonical_hash(256, 256, identity)
    return {
        "format": PLAN_FORMAT,
        "policy": "latest-current-per-project; one-large-revision-per-logical-source",
        "registry": str(registry),
        "safe_to_apply": not errors,
        "errors": errors,
        "plan_sha256": plan_sha256,
        "keep": {
            "snapshots": len(current), "raw_objects": len(raw_keep),
            "snapshot_ids": sorted(current_ids),
        },
        "delete": {
            "snapshots": len(delete_snapshots), "raw_objects": len(delete_objects),
            "snapshot_paths": [str(path) for path in delete_snapshots],
            "raw_object_paths": [str(path) for path in delete_objects],
            "snapshots_usage": storage_usage(delete_snapshots),
            "raw_objects_usage": storage_usage(
                delete_objects, recurse_directories=False
            ),
            "working_archives": (
                len(working_archives) if include_working_archives else 0
            ),
            "working_archive_paths": (
                [str(path) for path in working_archives]
                if include_working_archives else []
            ),
            "working_archives_usage": storage_usage(
                working_archives if include_working_archives else []
            ),
        },
        "working_archives": {
            "candidates": len(working_archives),
            "candidate_paths": [str(path) for path in working_archives],
            "usage": storage_usage(working_archives),
            "selected_for_delete": include_working_archives,
        },
        "large_revision_retention": {
            "threshold_bytes": LARGE_RAW_REVISION_BYTES,
            "comparison_retention_explicit": allow_large_comparison_revisions,
            "conflicts": large_shared_revisions,
        },
        "references": references,
    }


def apply_retention_plan(
    registry: Path, *, reference_catalogs: list[Path] | None = None,
    receipt_path: Path | None = None, include_working_archives: bool = False,
    allow_large_comparison_revisions: bool = False,
) -> dict[str, Any]:
    """Re-plan immediately, then delete only the validated latest-only candidates."""
    plan = build_retention_plan(
        registry, reference_catalogs=reference_catalogs,
        include_working_archives=include_working_archives,
        allow_large_comparison_revisions=allow_large_comparison_revisions,
    )
    if not plan["safe_to_apply"]:
        raise RuntimeError("retention plan rejected: " + "; ".join(plan["errors"]))
    deleted_snapshots: list[str] = []
    deleted_objects: list[str] = []
    deleted_working_archives: list[str] = []
    for value in plan["delete"]["snapshot_paths"]:
        path = Path(value)
        shutil.rmtree(path)
        deleted_snapshots.append(value)
    for value in plan["delete"]["raw_object_paths"]:
        path = Path(value)
        path.unlink()
        deleted_objects.append(value)
    for value in plan["delete"]["working_archive_paths"]:
        path = Path(value)
        shutil.rmtree(path)
        deleted_working_archives.append(value)
    raw_objects_root = Path(plan["registry"]) / "raw" / "codess.raw-1" / "objects"
    if raw_objects_root.exists():
        for root, dirs, files in os.walk(raw_objects_root, topdown=False):
            if not dirs and not files:
                Path(root).rmdir()
    after = build_retention_plan(
        registry, reference_catalogs=reference_catalogs,
        include_working_archives=include_working_archives,
        allow_large_comparison_revisions=allow_large_comparison_revisions,
    )
    if (
        after["delete"]["snapshots"]
        or after["delete"]["raw_objects"]
        or after["delete"]["working_archives"]
        or not after["safe_to_apply"]
    ):
        raise RuntimeError("retention postcondition failed; inspect the receipt and registry")
    # One application, one instant. The receipt's `applied_at` and the file it
    # is written to are two renderings of the same moment; reading the clock
    # twice would name the file a different instant than its own contents
    # report, which is exactly the correlation a receipt exists to support.
    applied_at = datetime.now(UTC)
    receipt = {
        "format": RECEIPT_FORMAT,
        "applied_at": applied_at.isoformat(),
        "registry": plan["registry"],
        "policy": plan["policy"],
        "plan_sha256": plan["plan_sha256"],
        "selection": {
            "keep_comparison_revisions": allow_large_comparison_revisions,
            "working_archives": include_working_archives,
        },
        "deleted": {
            "snapshot_paths": deleted_snapshots,
            "raw_object_paths": deleted_objects,
            "working_archive_paths": deleted_working_archives,
        },
        "reclaimed": {
            "snapshot_allocated_bytes": plan["delete"]["snapshots_usage"]["allocated_bytes"],
            "raw_allocated_bytes": plan["delete"]["raw_objects_usage"]["allocated_bytes"],
            "working_archive_allocated_bytes": plan["delete"]["working_archives_usage"]["allocated_bytes"],
        },
        "postcondition": {"safe_to_apply": True, "remaining_candidates": 0},
    }
    target = receipt_path or (
        Path(plan["registry"]) / "receipts" / "retention"
        / f"{applied_at.strftime('%Y%m%dT%H%M%S.%fZ')}.json"
    )
    write_json_atomic(target, receipt)
    receipt["receipt_path"] = str(target)
    return receipt
