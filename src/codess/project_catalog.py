"""Stable project identities, locations, workspace bindings, and durable roots."""

from __future__ import annotations

import json
import platform
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codess.identity import location_id
from codess.fileio import write_json_atomic
from codess.helpers import ephemeral_project_location_reason


CATALOG_FORMAT = "codess.project-catalog/1"
PROJECT_BINDING_FORMAT = "codess.project-binding/1"
PROJECT_SET_FORMAT = "codess.project-set/1"
PROJECT_SELECTION_STATES = frozenset({
    "priority", "candidate", "deferred", "excluded", "needs_review",
    # Transitional catalog state for a duplicate Project identity that is
    # actually a linked worktree of the related repository-level Project.
    "worktree",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_write_json_atomic = write_json_atomic


def _catalog_path(registry_root: Path) -> Path:
    return registry_root / "projects.json"


def _binding_path(project_root: Path) -> Path:
    return project_root / ".codess" / "project.json"


def _machine_id(registry_root: Path) -> str:
    path = registry_root / "machine-id"
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = f"machine:{uuid.uuid4()}"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_text(value + "\n", encoding="utf-8")
    temporary.replace(path)
    return value


def load_catalog(registry_root: Path) -> dict[str, Any]:
    path = _catalog_path(registry_root)
    if not path.exists():
        return {"catalog_format": CATALOG_FORMAT, "projects": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("catalog_format") != CATALOG_FORMAT:
        raise ValueError("unsupported project catalog format")
    if not isinstance(value.get("projects"), list):
        raise ValueError("project catalog projects must be a list")
    return value


def _source_links(project_root: Path) -> list[dict[str, Any]]:
    path = project_root / ".codess" / "source-links.json"
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("format") != "codess.source-links/1":
        raise ValueError("unsupported source-link format")
    return [item for item in value.get("links", []) if isinstance(item, dict)]


def ensure_project_binding(registry_root: Path, project_root: Path) -> dict[str, Any]:
    """Return and persist one stable project identity for an observed location."""
    registry_root = registry_root.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    if registry_root == (Path.home() / ".codess").resolve():
        reason = ephemeral_project_location_reason(project_root)
        if reason:
            raise ValueError(reason)
    binding_path = _binding_path(project_root)
    binding: dict[str, Any] | None = None
    if binding_path.exists():
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        if binding.get("binding_format") != PROJECT_BINDING_FORMAT:
            raise ValueError("unsupported project binding format")
    catalog = load_catalog(registry_root)
    resolved = str(project_root)
    by_id = {
        item.get("project_id"): item
        for item in catalog["projects"]
        if isinstance(item, dict) and item.get("project_id")
    }
    project_id = binding.get("project_id") if binding else None
    if not project_id:
        for item in by_id.values():
            if any(loc.get("path") == resolved for loc in item.get("locations", [])):
                project_id = item["project_id"]
                break
    if not project_id:
        project_id = f"codess:project:{uuid.uuid4()}"
    entry = dict(by_id.get(project_id) or {})
    entry.update({
        "project_id": project_id,
        "logical_name": entry.get("logical_name") or project_root.name,
        "updated_at": _now(),
    })
    machine_id = _machine_id(registry_root)
    observed_location_id = location_id(machine_id, project_root)
    locations = {
        item.get("location_id"): dict(item)
        for item in entry.get("locations", [])
        if isinstance(item, dict) and item.get("location_id")
    }
    for location in locations.values():
        location.setdefault(
            "path_obsolete", location.get("state") in {"retired", "missing"}
        )
    locations[observed_location_id] = {
        "location_id": observed_location_id,
        "machine_id": machine_id,
        "path": resolved,
        "path_obsolete": False,
        "state": "active",
        "observed_at": _now(),
        "platform": platform.system().lower(),
    }
    entry["locations"] = sorted(locations.values(), key=lambda item: item["location_id"])
    workspaces = {
        (item.get("source_system_id"), item.get("workspace_id")): dict(item)
        for item in entry.get("workspace_bindings", [])
        if isinstance(item, dict) and item.get("source_system_id") and item.get("workspace_id")
    }
    for workspace in workspaces.values():
        workspace.setdefault("path_obsolete", False)
    aliases = set(entry.get("path_aliases", []))
    aliases.add(resolved)
    obsolete_paths: set[str] = set()
    for link in _source_links(project_root):
        if link.get("selection_state") != "approved":
            continue
        source_system_id = link.get("source_system_id")
        identity = link.get("source_identity") or {}
        workspace_id = identity.get("workspace_id") if isinstance(identity, dict) else None
        if source_system_id and workspace_id:
            source_project_path = link.get("source_project_path")
            path_obsolete = bool(link.get("path_obsolete"))
            if source_project_path and source_project_path != resolved:
                path_obsolete = True
            workspaces[(source_system_id, str(workspace_id))] = {
                "source_system_id": source_system_id,
                "workspace_id": str(workspace_id),
                "relation_kind": link.get("relation_kind") or "workspace_binding",
                "source_project_path": source_project_path,
                "path_obsolete": path_obsolete,
                "target_location_id": observed_location_id,
                "selection_state": "approved",
            }
        source_path = link.get("source_project_path")
        if source_path and (
            link.get("path_obsolete") or str(source_path) != resolved
        ):
            obsolete_paths.add(str(source_path))
        target_path = link.get("target_project_path")
        if target_path:
            aliases.add(str(target_path))
    entry["workspace_bindings"] = sorted(
        workspaces.values(), key=lambda item: (item["source_system_id"], item["workspace_id"])
    )
    entry["path_aliases"] = sorted(aliases - obsolete_paths)
    by_id[project_id] = entry
    catalog["projects"] = sorted(by_id.values(), key=lambda item: item["project_id"])
    catalog["updated_at"] = _now()
    _write_json_atomic(_catalog_path(registry_root), catalog)
    binding = {
        "binding_format": PROJECT_BINDING_FORMAT,
        "project_id": project_id,
        "location_id": observed_location_id,
        "registry_root": str(registry_root),
    }
    _write_json_atomic(binding_path, binding)
    return binding


def durable_project_root(registry_root: Path, project_id: str) -> Path:
    """Return the central baseline root for one stable project identity."""
    safe = project_id.removeprefix("codess:project:")
    if not safe or any(part in safe for part in ("/", "\\", "..")):
        raise ValueError("invalid project identity")
    return registry_root.expanduser().resolve() / "projects" / safe


def get_project_entry(registry_root: Path, project_id: str) -> dict[str, Any]:
    """Return one catalog entry by stable ID."""
    for item in load_catalog(registry_root).get("projects", []):
        if item.get("project_id") == project_id:
            return dict(item)
    raise ValueError(f"project is absent from catalog: {project_id}")


def set_project_selection_state(
    registry_root: Path,
    project_id: str,
    state: str,
    *,
    related_project_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Set an explicit catalog disposition without rewriting retained evidence."""
    if state not in PROJECT_SELECTION_STATES:
        raise ValueError(f"unsupported Project selection state: {state}")
    catalog = load_catalog(registry_root)
    by_id = {
        item.get("project_id"): item
        for item in catalog["projects"]
        if isinstance(item, dict) and item.get("project_id")
    }
    entry = by_id.get(project_id)
    if entry is None:
        raise ValueError(f"project is absent from catalog: {project_id}")
    if state == "worktree":
        if not related_project_id:
            raise ValueError("worktree state requires --related-project-id")
        if related_project_id == project_id:
            raise ValueError("worktree Project cannot relate to itself")
        if related_project_id not in by_id:
            raise ValueError(
                f"related Project is absent from catalog: {related_project_id}"
            )
    entry["selection_state"] = state
    disposition = {
        "state": state,
        "updated_at": _now(),
    }
    if related_project_id:
        disposition["related_project_id"] = related_project_id
        disposition["relation_kind"] = (
            "worktree_of" if state == "worktree" else "related_project"
        )
    if note:
        disposition["note"] = note
    entry["catalog_disposition"] = disposition
    entry["updated_at"] = _now()
    catalog["updated_at"] = _now()
    _write_json_atomic(_catalog_path(registry_root), catalog)
    return {
        "project_id": project_id,
        "selection_state": state,
        "catalog_disposition": disposition,
    }


def load_project_set(path: Path) -> dict[str, Any]:
    """Load and validate one canonical saved Project selection."""
    try:
        value = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read Project set {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("format") != PROJECT_SET_FORMAT:
        raise ValueError(f"Project set must have format {PROJECT_SET_FORMAT}")
    unknown = set(value) - {"format", "name", "projects"}
    if unknown:
        raise ValueError(
            "unsupported Project-set field(s): " + ", ".join(sorted(unknown))
        )
    projects = value.get("projects")
    if not isinstance(projects, list) or not projects:
        raise ValueError("Project set projects must be a non-empty array")
    normalized = []
    seen: set[tuple[str, str | None]] = set()
    for index, item in enumerate(projects):
        if not isinstance(item, dict):
            raise ValueError(f"Project set projects[{index}] must be an object")
        item_unknown = set(item) - {"project_id", "snapshot_id"}
        if item_unknown:
            raise ValueError(
                f"unsupported projects[{index}] field(s): "
                + ", ".join(sorted(item_unknown))
            )
        project_id = item.get("project_id")
        snapshot_id = item.get("snapshot_id")
        if not isinstance(project_id, str) or not project_id:
            raise ValueError(
                f"Project set projects[{index}].project_id must be non-empty"
            )
        if snapshot_id is not None and (
            not isinstance(snapshot_id, str) or not snapshot_id
        ):
            raise ValueError(
                f"Project set projects[{index}].snapshot_id must be non-empty or null"
            )
        key = (project_id, snapshot_id)
        if key in seen:
            raise ValueError(
                f"Project set repeats Project/snapshot input: {project_id}, "
                f"{snapshot_id or 'current'}"
            )
        seen.add(key)
        normalized.append({
            "project_id": project_id,
            "snapshot_id": snapshot_id,
        })
    normalized.sort(key=lambda item: (
        item["project_id"], item["snapshot_id"] or "",
    ))
    canonical = {
        "format": PROJECT_SET_FORMAT,
        "name": value.get("name"),
        "projects": normalized,
    }
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    canonical["selection_sha256"] = hashlib.sha256(encoded).hexdigest()
    canonical["path"] = str(path.expanduser().resolve())
    return canonical


def _current_snapshot_id(snapshot_base: Path) -> str | None:
    pointer = snapshot_base / "current.json"
    if not pointer.is_file():
        return None
    try:
        value = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read current snapshot pointer {pointer}: {exc}") from exc
    snapshot_id = value.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError(f"current snapshot pointer lacks snapshot_id: {pointer}")
    return snapshot_id


def _entry_is_query_eligible(entry: dict[str, Any]) -> bool:
    """Honor explicit exclusion/defer states while accepting legacy catalog rows."""
    curation = entry.get("curation")
    state = entry.get("selection_state")
    if state is None and isinstance(curation, dict):
        state = curation.get("selection_state")
    review = entry.get("review")
    decision = review.get("decision") if isinstance(review, dict) else None
    return state not in {"excluded", "deferred", "needs_review", "worktree"} and decision not in {
        "excluded", "deferred",
    }


def catalog_readiness(registry_root: Path) -> dict[str, Any]:
    """Report per-Project query readiness without claiming source freshness."""
    from codess.refresh_receipts import latest_refresh_observations
    from codess.snapshot import SnapshotError, snapshot_store_paths_from_base

    registry_root = registry_root.expanduser().resolve()
    refresh_observations = latest_refresh_observations(registry_root)
    projects = []
    for entry in sorted(
        load_catalog(registry_root).get("projects", []),
        key=lambda item: str(item.get("logical_name") or item.get("project_id") or ""),
    ):
        if not isinstance(entry, dict) or not entry.get("project_id"):
            continue
        project_id = str(entry["project_id"])
        eligible = _entry_is_query_eligible(entry)
        active_locations = [
            str(item["path"])
            for item in entry.get("locations", [])
            if (
                isinstance(item, dict)
                and item.get("state") == "active"
                and item.get("path")
            )
        ]
        current_id = None
        detail = None
        if not eligible:
            status = "not_selected"
        else:
            base = durable_project_root(registry_root, project_id)
            try:
                current_id = _current_snapshot_id(base)
                if current_id is None:
                    status = "missing_current_snapshot"
                else:
                    snapshot_store_paths_from_base(base, current_id)
                    status = "query_ready"
            except (OSError, ValueError, SnapshotError) as exc:
                detail = str(exc)
                status = (
                    "package_mismatch"
                    if "package digest mismatch" in detail
                    else "snapshot_fail"
                )
        curation = entry.get("curation")
        refresh_observation = refresh_observations.get(project_id)
        projects.append({
            "project_id": project_id,
            "logical_name": entry.get("logical_name"),
            "selection_state": (
                entry.get("selection_state")
                or (
                    curation.get("selection_state")
                    if isinstance(curation, dict)
                    else None
                )
            ),
            "catalog_disposition": entry.get("catalog_disposition"),
            "selection_eligible": eligible,
            "activity_state": (
                curation.get("activity_state")
                if isinstance(curation, dict)
                else entry.get("activity_state")
            ),
            "active_location_count": len(active_locations),
            "existing_active_location_count": sum(
                Path(path).expanduser().is_dir() for path in active_locations
            ),
            "current_snapshot_id": current_id,
            "query_status": status,
            "detail": detail,
            # This is a receipt-backed operation result, not a freshness
            # inference from a pointer, Git status, or vendor-store mtime.
            "source_refresh_status": (
                refresh_observation["status"]
                if refresh_observation is not None else "not_assessed"
            ),
            "refresh_observation": refresh_observation,
        })
    eligible_projects = [
        item for item in projects if item["selection_eligible"]
    ]
    ready = sum(
        item["query_status"] == "query_ready" for item in eligible_projects
    )
    total = len(eligible_projects)
    assessed = sum(
        item["source_refresh_status"] != "not_assessed" for item in projects
    )
    return {
        "format": "codess.catalog-readiness/1",
        "generated_at": _now(),
        "summary": {
            "eligible_projects": total,
            "query_ready_projects": ready,
            "not_query_ready_projects": total - ready,
            "query_ready_coverage": f"{ready}/{total}",
            "all_eligible_query_ready": bool(total and ready == total),
            "source_refresh_assessed_projects": assessed,
            "source_refresh_coverage": f"{assessed}/{len(projects)}",
        },
        "projects": projects,
    }


def resolve_project_query_scopes(
    registry_root: Path,
    project_ids: list[str] | None = None,
    *,
    project_set: Path | None = None,
    all_current: bool = False,
    allow_package_mismatch: bool = False,
) -> list[dict[str, Any]]:
    """Resolve one exact, saved, or all-current Project scope without mutation."""
    registry_root = registry_root.expanduser().resolve()
    catalog = load_catalog(registry_root)
    by_id = {
        item.get("project_id"): item
        for item in catalog.get("projects", [])
        if isinstance(item, dict) and item.get("project_id")
    }
    selector_count = int(bool(project_ids)) + int(project_set is not None) + int(
        all_current
    )
    if selector_count != 1:
        raise ValueError(
            "select exactly one of Project IDs, a Project set, or all-current"
        )
    selection_kind = "project_ids"
    selection_sha256 = None
    if project_set is not None:
        saved = load_project_set(project_set)
        requested = saved["projects"]
        selection_kind = "project_set"
        selection_sha256 = saved["selection_sha256"]
    elif all_current:
        # A broad selector must be usable as resolved.  In exact mode, omit
        # retained snapshots that the current package cannot open rather than
        # admitting them here and failing the entire multi-Project query later.
        # The explicit read-compatible policy deliberately widens this set.
        from codess.snapshot import SnapshotError, snapshot_store_paths_from_base

        def selectable_current(project_id: str, entry: dict[str, Any]) -> str | None:
            if not _entry_is_query_eligible(entry):
                return None
            base = durable_project_root(registry_root, project_id)
            snapshot_id = _current_snapshot_id(base)
            if snapshot_id is None:
                return None
            try:
                snapshot_store_paths_from_base(
                    base,
                    snapshot_id,
                    allow_package_mismatch=allow_package_mismatch,
                )
            except (OSError, ValueError, SnapshotError):
                return None
            return snapshot_id

        requested = [
            {"project_id": project_id, "snapshot_id": snapshot_id}
            for project_id, entry in sorted(by_id.items())
            if (snapshot_id := selectable_current(project_id, entry)) is not None
        ]
        selection_kind = "all_current"
        if not requested:
            raise ValueError(
                "catalog has no eligible Projects with a central current snapshot"
            )
    else:
        requested = [
            {"project_id": value, "snapshot_id": None}
            for value in (project_ids or [])
        ]
    scopes: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for requested_item in requested:
        project_id = requested_item["project_id"]
        requested_snapshot_id = requested_item.get("snapshot_id")
        key = (project_id, requested_snapshot_id)
        if key in seen:
            continue
        seen.add(key)
        entry = by_id.get(project_id)
        if entry is None:
            raise ValueError(f"project is absent from catalog: {project_id}")
        active = sorted(
            (
                Path(str(location["path"])).expanduser()
                for location in entry.get("locations", [])
                if (
                    isinstance(location, dict)
                    and location.get("state") == "active"
                    and location.get("path")
                )
            ),
            key=lambda path: str(path),
        )
        existing = [path.resolve() for path in active if path.is_dir()]
        central = durable_project_root(registry_root, project_id)
        snapshot_id = requested_snapshot_id or _current_snapshot_id(central)
        if snapshot_id is None:
            raise ValueError(
                f"Project has no central current snapshot: {project_id}"
            )
        scopes.append({
            "project_id": project_id,
            "logical_name": entry.get("logical_name"),
            "snapshot_id": snapshot_id,
            "project_root": (
                existing[0]
                if existing
                else (active[0].resolve() if active else central)
            ),
            "snapshot_base": central,
            "active_location_count": len(active),
            "existing_active_location_count": len(existing),
            "selection_kind": selection_kind,
            "selection_sha256": selection_sha256,
        })
    scopes = sorted(
        scopes,
        key=lambda item: (item["project_id"], item["snapshot_id"]),
    )
    resolved_bytes = json.dumps(
        [
            {
                "project_id": item["project_id"],
                "snapshot_id": item["snapshot_id"],
            }
            for item in scopes
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    resolved_sha256 = hashlib.sha256(resolved_bytes).hexdigest()
    for item in scopes:
        item["resolved_selection_sha256"] = resolved_sha256
    return scopes


def add_project_location(
    registry_root: Path, project_id: str, project_root: Path,
) -> dict[str, Any]:
    """Explicitly bind an existing directory to a known Project identity."""
    registry_root = registry_root.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    if not project_root.is_dir():
        raise ValueError(f"location is not a directory: {project_root}")
    catalog = load_catalog(registry_root)
    resolved = str(project_root)
    entry = next(
        (item for item in catalog["projects"] if item.get("project_id") == project_id),
        None,
    )
    if entry is None:
        raise ValueError(f"project is absent from catalog: {project_id}")
    for other in catalog["projects"]:
        if other.get("project_id") != project_id and any(
            location.get("path") == resolved
            for location in other.get("locations", [])
        ):
            raise ValueError(
                f"location is already bound to another Project: {resolved}"
            )
    machine = _machine_id(registry_root)
    observed_location_id = location_id(machine, project_root)
    locations = {
        item.get("location_id"): dict(item)
        for item in entry.get("locations", [])
        if item.get("location_id")
    }
    for location in locations.values():
        location.setdefault(
            "path_obsolete", location.get("state") in {"retired", "missing"}
        )
    locations[observed_location_id] = {
        "location_id": observed_location_id,
        "machine_id": machine,
        "path": resolved,
        "path_obsolete": False,
        "state": "active",
        "observed_at": _now(),
        "platform": platform.system().lower(),
    }
    entry["locations"] = sorted(
        locations.values(), key=lambda item: item["location_id"]
    )
    entry["path_aliases"] = sorted(set(entry.get("path_aliases", [])) | {resolved})
    entry["updated_at"] = _now()
    catalog["updated_at"] = _now()
    _write_json_atomic(_catalog_path(registry_root), catalog)
    binding = {
        "binding_format": PROJECT_BINDING_FORMAT,
        "project_id": project_id,
        "location_id": observed_location_id,
        "registry_root": str(registry_root),
    }
    _write_json_atomic(_binding_path(project_root), binding)
    return {**binding, "path": resolved, "state": "active"}


def retire_project_location(
    registry_root: Path,
    project_id: str,
    project_root: Path,
    *,
    allow_last_active: bool = False,
) -> dict[str, Any]:
    """Retire one known Project location without requiring a replacement."""
    registry_root = registry_root.expanduser().resolve()
    resolved = str(project_root.expanduser().resolve())
    catalog = load_catalog(registry_root)
    entry = next(
        (item for item in catalog["projects"] if item.get("project_id") == project_id),
        None,
    )
    if entry is None:
        raise ValueError(f"project is absent from catalog: {project_id}")
    target = next(
        (item for item in entry.get("locations", []) if item.get("path") == resolved),
        None,
    )
    if target is None:
        raise ValueError(f"location is absent from Project: {resolved}")
    active = [item for item in entry.get("locations", []) if item.get("state") == "active"]
    if target.get("state") == "active" and len(active) == 1 and not allow_last_active:
        raise ValueError("refusing to retire the last active location")
    target["state"] = "retired"
    target["path_obsolete"] = True
    target["retired_at"] = _now()
    entry["updated_at"] = _now()
    catalog["updated_at"] = _now()
    _write_json_atomic(_catalog_path(registry_root), catalog)
    return {"project_id": project_id, "path": resolved, "state": "retired"}


def register_workspace_bindings(
    registry_root: Path,
    project_id: str,
    location_id_value: str,
    workspace_ids: list[str] | set[str],
    *,
    source_project_path: str,
) -> dict[str, Any]:
    """Persist local Cursor workspace-to-Project evidence discovered by ingest."""
    catalog = load_catalog(registry_root)
    entry = next(
        (item for item in catalog["projects"] if item.get("project_id") == project_id),
        None,
    )
    if entry is None:
        raise ValueError(f"project is absent from catalog: {project_id}")
    bindings = {
        (item.get("source_system_id"), item.get("workspace_id")): dict(item)
        for item in entry.get("workspace_bindings", [])
        if isinstance(item, dict) and item.get("source_system_id") and item.get("workspace_id")
    }
    for workspace_id in sorted(str(value) for value in workspace_ids if value):
        key = ("cursor.composer", workspace_id)
        if key not in bindings:
            bindings[key] = {
                "source_system_id": "cursor.composer",
                "workspace_id": workspace_id,
                "relation_kind": "local_workspace_path_binding",
                "source_project_path": source_project_path,
                "path_obsolete": False,
                "target_location_id": location_id_value,
                "selection_state": "approved",
            }
    entry["workspace_bindings"] = sorted(
        bindings.values(), key=lambda item: (item["source_system_id"], item["workspace_id"])
    )
    entry["updated_at"] = _now()
    catalog["updated_at"] = _now()
    _write_json_atomic(_catalog_path(registry_root), catalog)
    return dict(entry)


def register_relocation(
    registry_root: Path,
    project_id: str,
    old_root: Path,
    new_root: Path | None,
) -> dict[str, Any]:
    """Retire an observed location and optionally bind a replacement location."""
    catalog = load_catalog(registry_root)
    entry = next(
        (item for item in catalog["projects"] if item.get("project_id") == project_id),
        None,
    )
    if entry is None:
        raise ValueError(f"project is absent from catalog: {project_id}")
    old_path = str(old_root.expanduser().resolve())
    for location in entry.get("locations", []):
        if location.get("path") == old_path:
            location["state"] = "retired"
            location["path_obsolete"] = True
            location["retired_at"] = _now()
    catalog["updated_at"] = _now()
    _write_json_atomic(_catalog_path(registry_root), catalog)
    if new_root is None:
        return {"project_id": project_id, "old_path": old_path, "new_path": None}
    new_root = new_root.expanduser().resolve()
    new_root.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(_binding_path(new_root), {
        "binding_format": PROJECT_BINDING_FORMAT,
        "project_id": project_id,
        "location_id": location_id(_machine_id(registry_root), new_root),
        "registry_root": str(registry_root.expanduser().resolve()),
    })
    ensure_project_binding(registry_root, new_root)
    return {"project_id": project_id, "old_path": old_path, "new_path": str(new_root)}
