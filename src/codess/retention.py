"""Latest-snapshot retention planning and explicit, validated pruning."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codess.fileio import hash_file, write_json_atomic


PLAN_FORMAT = "codess.retention-plan/1"
RECEIPT_FORMAT = "codess.retention-receipt/1"


def _usage(paths: list[Path]) -> dict[str, int]:
    logical = allocated = files = 0
    for root in paths:
        candidates = [root] if root.is_file() else root.rglob("*")
        for path in candidates:
            if not path.is_file():
                continue
            stat = path.stat()
            files += 1
            logical += stat.st_size
            allocated += int(getattr(stat, "st_blocks", 0) * 512 or stat.st_size)
    return {"files": files, "logical_bytes": logical, "allocated_bytes": allocated}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _raw_records(snapshot: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with (snapshot / "raw-manifest.jsonl").open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid raw manifest {snapshot}:{number}: {exc}") from exc
            if isinstance(value, dict) and value.get("record_type") != "header":
                records.append(value)
    return records


def _validate_current(project_root: Path, pointer: dict[str, Any], raw_root: Path) -> tuple[Path, set[str]]:
    snapshot_id = pointer.get("snapshot_id")
    path_value = pointer.get("path")
    if not isinstance(snapshot_id, str) or not isinstance(path_value, str):
        raise RuntimeError(f"invalid current pointer: {project_root / 'current.json'}")
    snapshot = Path(path_value)
    if not snapshot.is_absolute():
        snapshot = project_root / snapshot
    expected_root = project_root / "snapshots"
    if snapshot.name != snapshot_id or not _inside(snapshot, expected_root) or not snapshot.is_dir():
        raise RuntimeError(f"current snapshot escapes or is absent: {snapshot}")
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("snapshot_id") != snapshot_id:
        raise RuntimeError(f"manifest identity mismatch: {snapshot}")
    if hash_file(manifest_path) != pointer.get("manifest_sha256"):
        raise RuntimeError(f"current manifest hash mismatch: {snapshot}")
    raw_manifest = snapshot / "raw-manifest.jsonl"
    if hash_file(raw_manifest) != manifest.get("raw_manifest_sha256"):
        raise RuntimeError(f"raw manifest hash mismatch: {snapshot}")
    for name, entry in manifest.get("stores", {}).items():
        store = snapshot / name
        if not _inside(store, snapshot) or hash_file(store) != entry.get("sha256"):
            raise RuntimeError(f"snapshot store hash mismatch: {store}")
        conn = sqlite3.connect(store.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            result = conn.execute("PRAGMA quick_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"snapshot SQLite quick_check failed: {store}: {result}")
        finally:
            conn.close()
    raw_references: set[str] = set()
    for record in _raw_records(snapshot):
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
    return snapshot.resolve(), raw_references


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
            pointer_path = Path(str(location.get("path") or "")) / ".codess" / "current.json"
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


def build_retention_plan(registry: Path, *, reference_catalogs: list[Path] | None = None) -> dict[str, Any]:
    """Plan keeping exactly each central current snapshot and its raw objects."""
    registry = registry.expanduser().resolve()
    projects_root = registry / "projects"
    raw_root = registry / "raw" / "codess.raw-1"
    current: list[Path] = []
    current_by_project: dict[str, str] = {}
    raw_keep: set[str] = set()
    errors: list[str] = []
    for project_root in sorted(path for path in projects_root.iterdir() if path.is_dir()) if projects_root.exists() else []:
        pointer_path = project_root / "current.json"
        if not pointer_path.exists():
            errors.append(f"project has no current pointer: {project_root}")
            continue
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            snapshot, references = _validate_current(project_root, pointer, raw_root)
            current.append(snapshot)
            current_by_project[project_root.name] = snapshot.name
            raw_keep.update(references)
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
    if references["blocking"]:
        errors.append("a reference catalog selects a superseded snapshot; refreeze or drop that catalog entry before pruning")
    if references["local_pointers"]["blocking"]:
        errors.append("an active Project location points to a superseded snapshot; rebuild or synchronize that validated current pointer before pruning")
    identity = {
        "current": [str(path) for path in current],
        "delete_snapshots": [str(path) for path in delete_snapshots],
        "raw_keep": sorted(raw_keep),
        "delete_objects": [str(path) for path in delete_objects],
    }
    plan_sha256 = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "format": PLAN_FORMAT,
        "policy": "latest-current-per-project",
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
            "snapshots_usage": _usage(delete_snapshots),
            "raw_objects_usage": _usage(delete_objects),
        },
        "references": references,
    }


def apply_retention_plan(registry: Path, *, reference_catalogs: list[Path] | None = None, receipt_path: Path | None = None) -> dict[str, Any]:
    """Re-plan immediately, then delete only the validated latest-only candidates."""
    plan = build_retention_plan(registry, reference_catalogs=reference_catalogs)
    if not plan["safe_to_apply"]:
        raise RuntimeError("retention plan rejected: " + "; ".join(plan["errors"]))
    deleted_snapshots: list[str] = []
    deleted_objects: list[str] = []
    for value in plan["delete"]["snapshot_paths"]:
        path = Path(value)
        shutil.rmtree(path)
        deleted_snapshots.append(value)
    for value in plan["delete"]["raw_object_paths"]:
        path = Path(value)
        path.unlink()
        deleted_objects.append(value)
    raw_objects_root = Path(plan["registry"]) / "raw" / "codess.raw-1" / "objects"
    if raw_objects_root.exists():
        for root, dirs, files in os.walk(raw_objects_root, topdown=False):
            if not dirs and not files:
                Path(root).rmdir()
    after = build_retention_plan(registry, reference_catalogs=reference_catalogs)
    if after["delete"]["snapshots"] or after["delete"]["raw_objects"] or not after["safe_to_apply"]:
        raise RuntimeError("retention postcondition failed; inspect the receipt and registry")
    receipt = {
        "format": RECEIPT_FORMAT,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "registry": plan["registry"],
        "policy": plan["policy"],
        "plan_sha256": plan["plan_sha256"],
        "deleted": {"snapshot_paths": deleted_snapshots, "raw_object_paths": deleted_objects},
        "reclaimed": {
            "snapshot_allocated_bytes": plan["delete"]["snapshots_usage"]["allocated_bytes"],
            "raw_allocated_bytes": plan["delete"]["raw_objects_usage"]["allocated_bytes"],
        },
        "postcondition": {"safe_to_apply": True, "remaining_candidates": 0},
    }
    target = receipt_path or Path(plan["registry"]) / "receipts" / "retention" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}.json"
    write_json_atomic(target, receipt)
    receipt["receipt_path"] = str(target)
    return receipt
