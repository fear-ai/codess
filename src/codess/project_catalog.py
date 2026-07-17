"""Stable project identities, locations, workspace bindings, and durable roots."""

from __future__ import annotations

import json
import platform
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codess.identity import location_id
from codess.fileio import write_json_atomic


CATALOG_FORMAT = "codess.project-catalog/1"
PROJECT_BINDING_FORMAT = "codess.project-binding/1"


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
    locations[observed_location_id] = {
        "location_id": observed_location_id,
        "machine_id": machine_id,
        "path": resolved,
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
    aliases = set(entry.get("path_aliases", []))
    aliases.add(resolved)
    for link in _source_links(project_root):
        if link.get("selection_state") != "approved":
            continue
        source_system_id = link.get("source_system_id")
        identity = link.get("source_identity") or {}
        workspace_id = identity.get("workspace_id") if isinstance(identity, dict) else None
        if source_system_id and workspace_id:
            workspaces[(source_system_id, str(workspace_id))] = {
                "source_system_id": source_system_id,
                "workspace_id": str(workspace_id),
                "relation_kind": link.get("relation_kind") or "workspace_binding",
                "source_project_path": link.get("source_project_path"),
                "target_location_id": observed_location_id,
                "selection_state": "approved",
            }
        for key in ("source_project_path", "target_project_path"):
            if link.get(key):
                aliases.add(str(link[key]))
    entry["workspace_bindings"] = sorted(
        workspaces.values(), key=lambda item: (item["source_system_id"], item["workspace_id"])
    )
    entry["path_aliases"] = sorted(aliases)
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
    locations[observed_location_id] = {
        "location_id": observed_location_id,
        "machine_id": machine,
        "path": resolved,
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
