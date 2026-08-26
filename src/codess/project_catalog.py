"""Stable project identities, locations, workspace bindings, and durable roots."""

from __future__ import annotations

import json
import logging
import platform
import uuid
from pathlib import Path
from typing import Any

from codess.config import (
    PROJECT_FILE,
    SOURCE_LINKS_FILE,
    SOURCE_LINKS_FORMAT,
    STORE_DIR,
    STORE_ROOT,
)
from codess.fileio import write_json_atomic
from codess.hashing import codess_canonical_hash
from codess.helpers import ephemeral_project_location_reason
from codess.identity import location_id
from codess.timeval import now_iso
from codess.wallclock import system_clock

log = logging.getLogger(__name__)

CATALOG_FORMAT = "codess.project-catalog/1"
PROJECT_BINDING_FORMAT = "codess.project-binding/1"
PROJECT_SET_FORMAT = "codess.project-set/1"
PROJECT_SELECTION_STATES = frozenset({
    "priority", "candidate", "deferred", "excluded", "needs_review",
    # Transitional catalog state for a duplicate Project identity that is
    # actually a linked worktree of the related repository-level Project.
    "worktree",
})


def _catalog_path(store_root: Path) -> Path:
    return store_root / "projects.json"


def _binding_path(project_path: Path) -> Path:
    return project_path / STORE_DIR / PROJECT_FILE


def _save_catalog_entry(
    store_root: Path, catalog: dict[str, Any], entry: dict[str, Any],
) -> None:
    """Stamp `entry` and `catalog` as updated now, then persist `catalog`.

    Four call sites shared this exact two-timestamp-then-write sequence
    (mutate one project's entry, mutate the catalog it belongs to, write the
    catalog back) with nothing else in common between them; extracted so a
    future site can't stamp only one of the two by omission.
    """
    stamped = now_iso(system_clock)
    entry["updated_at"] = stamped
    catalog["updated_at"] = stamped
    write_json_atomic(_catalog_path(store_root), catalog)


def _machine_id(store_root: Path) -> str:
    path = store_root / "machine-id"
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


def load_catalog(store_root: Path) -> dict[str, Any]:
    path = _catalog_path(store_root)
    if not path.exists():
        return {"catalog_format": CATALOG_FORMAT, "projects": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("catalog_format") != CATALOG_FORMAT:
        raise ValueError("unsupported project catalog format")
    if not isinstance(value.get("projects"), list):
        raise ValueError("project catalog projects must be a list")
    return value


def _source_links(project_path: Path) -> list[dict[str, Any]]:
    path = project_path / STORE_DIR / SOURCE_LINKS_FILE
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("format") != SOURCE_LINKS_FORMAT:
        raise ValueError("unsupported source-link format")
    return [item for item in value.get("links", []) if isinstance(item, dict)]


def _read_existing_binding(binding_path: Path) -> dict[str, Any] | None:
    """Read a Project's retained binding, refusing an unsupported format.

    A binding written under a different format is rejected rather than
    ignored: silently discarding it would mint a second identity for a
    Project that already has one, which is the failure this file prevents.
    """
    if not binding_path.exists():
        return None
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    if binding.get("binding_format") != PROJECT_BINDING_FORMAT:
        raise ValueError("unsupported project binding format")
    return binding


def _resolve_project_id(
    binding: dict[str, Any] | None,
    entries_by_id: dict[str, dict[str, Any]],
    resolved_path: str,
) -> str:
    """Find this Project's stable identity, or mint one.

    Three sources in falling order of authority: the Project's own retained
    binding, a catalog entry already claiming this exact location, and
    finally a new identity. The catalog search matters when a binding file
    was deleted but the catalog still records the Project -- reminting there
    would split one Project's history across two identities.

    **A minted identity is reported.** The binding lives inside the Project
    directory, so it is lost whenever that directory is cleaned, re-cloned, or
    restored from a copy predating it -- and a lost binding is
    indistinguishable from a Project never ingested. Minting then produces a
    second Project for one path, which is silent in every list and carries none
    of the review the first entry may have accumulated. Nine such duplicates
    were created on this machine in one session before anything said so.
    """
    project_id = binding.get("project_id") if binding else None
    claimants = [
        str(entry["project_id"])
        for entry in entries_by_id.values()
        if any(
            location.get("path") == resolved_path
            for location in entry.get("locations", [])
        )
    ]
    if project_id:
        others = [claimed for claimed in claimants if claimed != str(project_id)]
        if others:
            log.warning(
                "project binding names %s while the catalog records %s for %s: "
                "one path now has several Projects",
                project_id, ", ".join(sorted(others)), resolved_path,
            )
        return str(project_id)
    if claimants:
        return claimants[0]
    minted = f"codess:project:{uuid.uuid4()}"
    log.warning(
        "no retained binding and no catalog entry for %s: minting %s. If this "
        "Project was ingested before, its binding was lost and its history "
        "will split across two identities",
        resolved_path, minted,
    )
    return minted


def _merged_locations(
    entry: dict[str, Any],
    observed_location_id: str,
    *,
    machine_id: str,
    resolved_path: str,
    observed_at: str,
) -> list[dict[str, Any]]:
    """Record this observation among the Project's known locations.

    Retained locations keep their state; only the one just observed is
    rewritten. `path_obsolete` is defaulted rather than assumed false, since
    a retired or missing location is obsolete by definition and older entries
    predate the field.

    **Keyed by `(machine_id, path)`, not by `location_id`.** A location's
    identity is the physical place, and `location_id` is derived from it -- so
    keying on the derived value means a change in the derivation produces a
    second entry for one directory. That happened: the format-5 identity change
    re-derived every `location_id` from `sha256:` to `id1:`, and a registry
    written across both carried two entries per location. `project_locations`
    declares `UNIQUE(machine_id, observed_path)`, so the second insert failed
    and every re-ingest of an affected Project aborted.

    Deduplicating here rather than at the insert is deliberate: the catalog is
    the operator-visible record, and leaving a duplicate in it to be filtered on
    the way into SQL would mean two documents disagreeing about how many
    locations a Project has.
    """
    locations: dict[tuple[str | None, str | None], dict[str, Any]] = {}
    for item in entry.get("locations", []):
        if not isinstance(item, dict) or not item.get("location_id"):
            continue
        location = dict(item)
        location.setdefault(
            "path_obsolete", location.get("state") in {"retired", "missing"}
        )
        key = (location.get("machine_id"), location.get("path"))
        existing = locations.get(key)
        # A later observation of the same place supersedes an earlier one; among
        # equals prefer the entry whose id matches the current derivation, so
        # repeated runs converge on one spelling rather than alternating.
        if existing is None or (
            str(location.get("observed_at") or ""),
            location.get("location_id") == observed_location_id,
        ) >= (
            str(existing.get("observed_at") or ""),
            existing.get("location_id") == observed_location_id,
        ):
            locations[key] = location
    locations[(machine_id, resolved_path)] = {
        "location_id": observed_location_id,
        "machine_id": machine_id,
        "path": resolved_path,
        "path_obsolete": False,
        "state": "active",
        "observed_at": observed_at,
        "platform": platform.system().lower(),
    }
    return sorted(locations.values(), key=lambda item: item["location_id"])


def _repointed_bindings(
    bindings: list[dict[str, Any]], locations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Re-point a binding whose target location no longer exists.

    `workspace_bindings.location_id` is a foreign key into `project_locations`,
    so a binding naming a location that is not in the catalog makes the Project
    unwritable -- the insert fails with `FOREIGN KEY constraint failed` partway
    through and aborts the ingest.

    That is reachable because a location's identity is derived from its path: the
    format-5 identity change re-derived every `location_id`, and a binding
    written beforehand still names the previous value. Deduplicating locations by
    physical place then removes the row it referred to. Resolving by path is what
    makes the repair correct rather than a guess -- the binding and the location
    describe the same directory, so the current identity for that path is the
    answer.

    A binding whose path matches no known location is left as it is. It is
    dangling either way, and inventing a target would attach a workspace to a
    directory no evidence connects it to.
    """
    by_path = {
        item.get("path"): item.get("location_id")
        for item in locations
        if item.get("path") and item.get("location_id")
    }
    live = {item.get("location_id") for item in locations}
    repointed = []
    for binding in bindings:
        target = binding.get("target_location_id")
        if target in live:
            repointed.append(binding)
            continue
        resolved = by_path.get(binding.get("source_project_path"))
        if resolved is None:
            repointed.append(binding)
            continue
        repointed.append({**binding, "target_location_id": resolved})
    return repointed


def _apply_source_links(
    entry: dict[str, Any],
    project_path: Path,
    observed_location_id: str,
    resolved_path: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fold approved source links into workspace bindings and path aliases.

    Only approved links are read: a proposed or rejected link is evidence of
    a selection decision, not authority to bind a workspace. A link whose
    source path differs from the observed one marks that path obsolete, which
    is how a moved or renamed Project stops claiming its former location
    while keeping the alias history that identifies it.

    Returns the sorted workspace bindings and path aliases.
    """
    workspaces = {
        (item.get("source_system_id"), item.get("workspace_id")): dict(item)
        for item in entry.get("workspace_bindings", [])
        if isinstance(item, dict)
        and item.get("source_system_id")
        and item.get("workspace_id")
    }
    for workspace in workspaces.values():
        workspace.setdefault("path_obsolete", False)
    aliases = set(entry.get("path_aliases", []))
    aliases.add(resolved_path)
    obsolete_paths: set[str] = set()
    for link in _source_links(project_path):
        if link.get("selection_state") != "approved":
            continue
        source_system_id = link.get("source_system_id")
        identity = link.get("source_identity") or {}
        workspace_id = (
            identity.get("workspace_id") if isinstance(identity, dict) else None
        )
        if source_system_id and workspace_id:
            source_project_path = link.get("source_project_path")
            path_obsolete = bool(link.get("path_obsolete"))
            if source_project_path and source_project_path != resolved_path:
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
            link.get("path_obsolete") or str(source_path) != resolved_path
        ):
            obsolete_paths.add(str(source_path))
        target_path = link.get("target_project_path")
        if target_path:
            aliases.add(str(target_path))
    return (
        sorted(
            workspaces.values(),
            key=lambda item: (item["source_system_id"], item["workspace_id"]),
        ),
        sorted(aliases - obsolete_paths),
    )


def read_project_binding(project_path: Path) -> dict[str, Any] | None:
    """Return a Project's retained binding without creating or rewriting one.

    `ensure_project_binding` resolves an identity and persists it, which is
    right when a caller needs a Project to have one. A caller that only wants
    to *check* the identity it is already working under must not write:
    verifying by calling `ensure_*` would rewrite the catalog as a side
    effect of the check.

    Returns None when the Project has no binding yet.
    """
    return _read_existing_binding(_binding_path(project_path))


def ensure_project_binding(store_root: Path, project_path: Path) -> dict[str, Any]:
    """Return and persist one stable project identity for an observed location.

    Four steps, each a named function above: read any retained binding,
    resolve the identity, rebuild the entry from this observation, and write
    the catalog and binding together. They are extracted within this module
    rather than into another because catalog identity, locations, and
    readiness are one concern (3.5.5).
    """
    store_root = store_root.expanduser().resolve()
    project_path = project_path.expanduser().resolve()
    if store_root == STORE_ROOT.resolve():
        reason = ephemeral_project_location_reason(project_path)
        if reason:
            raise ValueError(reason)
    binding_path = _binding_path(project_path)
    binding = _read_existing_binding(binding_path)

    catalog = load_catalog(store_root)
    resolved = str(project_path)
    by_id = {
        item.get("project_id"): item
        for item in catalog["projects"]
        if isinstance(item, dict) and item.get("project_id")
    }
    project_id = _resolve_project_id(binding, by_id, resolved)

    # One observation, one timestamp. These were three separate `now()` calls,
    # so a single logical event could be stamped at three different instants.
    observed_at = now_iso(system_clock)
    machine_id = _machine_id(store_root)
    observed_location_id = location_id(machine_id, project_path)

    entry = dict(by_id.get(project_id) or {})
    entry.update({
        "project_id": project_id,
        "logical_name": entry.get("logical_name") or project_path.name,
        "updated_at": observed_at,
    })
    entry["locations"] = _merged_locations(
        entry, observed_location_id,
        machine_id=machine_id, resolved_path=resolved, observed_at=observed_at,
    )
    entry["workspace_bindings"], entry["path_aliases"] = _apply_source_links(
        entry, project_path, observed_location_id, resolved,
    )
    entry["workspace_bindings"] = _repointed_bindings(
        entry["workspace_bindings"], entry["locations"],
    )

    by_id[project_id] = entry
    catalog["projects"] = sorted(by_id.values(), key=lambda item: item["project_id"])
    catalog["updated_at"] = observed_at
    write_json_atomic(_catalog_path(store_root), catalog)
    binding = {
        "binding_format": PROJECT_BINDING_FORMAT,
        "project_id": project_id,
        "location_id": observed_location_id,
        "store_root": str(store_root),
    }
    write_json_atomic(binding_path, binding)
    return binding


def durable_project_root(store_root: Path, project_id: str) -> Path:
    """Return the central baseline root for one stable project identity."""
    safe = project_id.removeprefix("codess:project:")
    if not safe or any(part in safe for part in ("/", "\\", "..")):
        raise ValueError("invalid project identity")
    return store_root.expanduser().resolve() / "projects" / safe


def get_project_entry(store_root: Path, project_id: str) -> dict[str, Any]:
    """Return one catalog entry by stable ID."""
    for item in load_catalog(store_root).get("projects", []):
        if item.get("project_id") == project_id:
            return dict(item)
    raise ValueError(f"project is absent from catalog: {project_id}")


def set_project_selection_state(
    store_root: Path,
    project_id: str,
    state: str,
    *,
    related_project_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Set an explicit catalog disposition without rewriting retained evidence."""
    if state not in PROJECT_SELECTION_STATES:
        raise ValueError(f"unsupported Project selection state: {state}")
    catalog = load_catalog(store_root)
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
    # The state it is leaving, kept beside the state it enters. Without it a
    # reader cannot tell an initial setting from a transition -- "excluded,
    # always was" and "excluded on this date, previously active" are different
    # facts, and only the second raises the question of what changed.
    previous = (entry.get("catalog_disposition") or {}).get("state")
    entry["selection_state"] = state
    disposition = {
        "state": state,
        "updated_at": now_iso(system_clock),
    }
    if previous and previous != state:
        disposition["previous_state"] = previous
    if related_project_id:
        disposition["related_project_id"] = related_project_id
        disposition["relation_kind"] = (
            "worktree_of" if state == "worktree" else "related_project"
        )
    if note:
        disposition["note"] = note
    entry["catalog_disposition"] = disposition
    _save_catalog_entry(store_root, catalog, entry)
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
    canonical["selection_sha256"] = codess_canonical_hash(256, 256, canonical)
    canonical["path"] = str(path.expanduser().resolve())
    return canonical


def _current_snapshot_id(snapshot_base: Path) -> str | None:
    """Return the current snapshot's verified snapshot_id, or None if unset.

    Delegates to `snapshot.current_snapshot` for the pointer read and
    manifest_sha256 check rather than re-reading current.json directly, so a
    tampered or stale pointer raises SnapshotError here exactly as it would
    anywhere else in the module that consumes the current snapshot.
    """
    from codess.snapshot import current_snapshot

    resolved = current_snapshot(snapshot_base)
    if resolved is None:
        return None
    _snapshot_path, pointer = resolved
    snapshot_id = pointer.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError(f"current snapshot pointer lacks snapshot_id: {snapshot_base}")
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


def _assess_query_status(
    store_root: Path, project_id: str, *, eligible: bool,
) -> tuple[str, str | None, str | None]:
    """Decide whether one Project can be queried, and why not if it cannot.

    Returns the status, the current snapshot identity, and a detail string
    for the failing cases. A Project that was never selected is reported as
    `not_selected` rather than as a failure: it has no published snapshot
    because none was asked for, which is not the same as a broken one.

    `contract_mismatch` is separated from `snapshot_fail` because they call
    for different actions -- regenerating the store versus investigating a
    damaged snapshot -- and a caller cannot tell them apart from a message.
    """
    from codess.snapshot import (
        SnapshotContractMismatchError,
        SnapshotError,
        snapshot_store_paths_from_base,
    )

    if not eligible:
        return "not_selected", None, None
    base = durable_project_root(store_root, project_id)
    try:
        current_id = _current_snapshot_id(base)
        if current_id is None:
            return "missing_current_snapshot", None, None
        snapshot_store_paths_from_base(base, current_id)
        return "query_ready", current_id, None
    except (OSError, ValueError, SnapshotError) as exc:
        # Classified by exception type rather than by message text: the
        # wording is operator-facing and changes, and matching on it made the
        # message a silent interface that reclassified the status when edited.
        status = (
            "contract_mismatch"
            if isinstance(exc, SnapshotContractMismatchError)
            else "snapshot_fail"
        )
        return status, None, str(exc)


def _readiness_row(
    entry: dict[str, Any],
    *,
    query_status: str,
    current_snapshot_id: str | None,
    detail: str | None,
    eligible: bool,
    refresh_observation: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compose one Project's readiness record.

    Selection and activity state each have two possible homes -- the entry
    itself or its `curation` block -- because curation was added later and
    older entries carry the values at the top level. Reading both here keeps
    that compatibility in one place.
    """
    curation = entry.get("curation")
    active_locations = [
        str(item["path"])
        for item in entry.get("locations", [])
        if (
            isinstance(item, dict)
            and item.get("state") == "active"
            and item.get("path")
        )
    ]
    return {
        "project_id": str(entry["project_id"]),
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
        "current_snapshot_id": current_snapshot_id,
        "query_status": query_status,
        "detail": detail,
        # This is a receipt-backed operation result, not a freshness
        # inference from a pointer, Git status, or vendor-store mtime.
        "source_refresh_status": (
            refresh_observation["status"]
            if refresh_observation is not None else "not_assessed"
        ),
        "refresh_observation": refresh_observation,
    }


def _readiness_summary(projects: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize readiness over the assessed Projects.

    Coverage counts only eligible Projects, since an unselected one is not a
    Project that failed to become ready. Refresh coverage counts all of them,
    because a receipt can exist for a Project no longer selected.
    """
    eligible_projects = [item for item in projects if item["selection_eligible"]]
    ready = sum(
        item["query_status"] == "query_ready" for item in eligible_projects
    )
    total = len(eligible_projects)
    assessed = sum(
        item["source_refresh_status"] != "not_assessed" for item in projects
    )
    return {
        "eligible_projects": total,
        "query_ready_projects": ready,
        "not_query_ready_projects": total - ready,
        "query_ready_coverage": f"{ready}/{total}",
        "all_eligible_query_ready": bool(total and ready == total),
        "source_refresh_assessed_projects": assessed,
        "source_refresh_coverage": f"{assessed}/{len(projects)}",
    }


def catalog_readiness(store_root: Path) -> dict[str, Any]:
    """Report per-Project query readiness without claiming source freshness.

    Three steps, each a named function above: assess whether a Project can be
    queried, compose its record, and summarize the set.
    """
    from codess.refresh_receipts import latest_refresh_observations

    store_root = store_root.expanduser().resolve()
    refresh_observations = latest_refresh_observations(store_root)
    projects = []
    for entry in sorted(
        load_catalog(store_root).get("projects", []),
        key=lambda item: str(item.get("logical_name") or item.get("project_id") or ""),
    ):
        if not isinstance(entry, dict) or not entry.get("project_id"):
            continue
        project_id = str(entry["project_id"])
        eligible = _entry_is_query_eligible(entry)
        status, current_id, detail = _assess_query_status(
            store_root, project_id, eligible=eligible,
        )
        projects.append(_readiness_row(
            entry,
            query_status=status,
            current_snapshot_id=current_id,
            detail=detail,
            eligible=eligible,
            refresh_observation=refresh_observations.get(project_id),
        ))
    return {
        "format": "codess.catalog-readiness/1",
        "generated_at": now_iso(system_clock),
        "summary": _readiness_summary(projects),
        "projects": projects,
    }


def resolve_project_query_scopes(
    store_root: Path,
    project_ids: list[str] | None = None,
    *,
    project_set: Path | None = None,
    all_current: bool = False,
    allow_contract_mismatch: bool = False,
) -> list[dict[str, Any]]:
    """Resolve one exact, saved, or all-current Project scope without mutation."""
    store_root = store_root.expanduser().resolve()
    catalog = load_catalog(store_root)
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
            base = durable_project_root(store_root, project_id)
            try:
                snapshot_id = _current_snapshot_id(base)
                if snapshot_id is None:
                    return None
                snapshot_store_paths_from_base(
                    base,
                    snapshot_id,
                    allow_contract_mismatch=allow_contract_mismatch,
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
        central = durable_project_root(store_root, project_id)
        snapshot_id = requested_snapshot_id or _current_snapshot_id(central)
        if snapshot_id is None:
            raise ValueError(
                f"Project has no central current snapshot: {project_id}"
            )
        scopes.append({
            "project_id": project_id,
            "logical_name": entry.get("logical_name"),
            "snapshot_id": snapshot_id,
            "project_path": (
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
    resolved_sha256 = codess_canonical_hash(256, 256, [
        {"project_id": item["project_id"], "snapshot_id": item["snapshot_id"]}
        for item in scopes
    ])
    for item in scopes:
        item["resolved_selection_sha256"] = resolved_sha256
    return scopes


def add_project_location(
    store_root: Path, project_id: str, project_path: Path,
) -> dict[str, Any]:
    """Explicitly bind an existing directory to a known Project identity."""
    store_root = store_root.expanduser().resolve()
    project_path = project_path.expanduser().resolve()
    if not project_path.is_dir():
        raise ValueError(f"location is not a directory: {project_path}")
    catalog = load_catalog(store_root)
    resolved = str(project_path)
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
    machine = _machine_id(store_root)
    observed_location_id = location_id(machine, project_path)
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
        "observed_at": now_iso(system_clock),
        "platform": platform.system().lower(),
    }
    entry["locations"] = sorted(
        locations.values(), key=lambda item: item["location_id"]
    )
    entry["path_aliases"] = sorted(set(entry.get("path_aliases", [])) | {resolved})
    _save_catalog_entry(store_root, catalog, entry)
    binding = {
        "binding_format": PROJECT_BINDING_FORMAT,
        "project_id": project_id,
        "location_id": observed_location_id,
        "store_root": str(store_root),
    }
    write_json_atomic(_binding_path(project_path), binding)
    return {**binding, "path": resolved, "state": "active"}


def retire_project_location(
    store_root: Path,
    project_id: str,
    project_path: Path,
    *,
    allow_last_active: bool = False,
) -> dict[str, Any]:
    """Retire one known Project location without requiring a replacement."""
    store_root = store_root.expanduser().resolve()
    resolved = str(project_path.expanduser().resolve())
    catalog = load_catalog(store_root)
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
    target["retired_at"] = now_iso(system_clock)
    _save_catalog_entry(store_root, catalog, entry)
    return {"project_id": project_id, "path": resolved, "state": "retired"}


def register_workspace_bindings(
    store_root: Path,
    project_id: str,
    location_id_value: str,
    workspace_ids: list[str] | set[str],
    *,
    source_project_path: str,
) -> dict[str, Any]:
    """Persist local Cursor workspace-to-Project evidence discovered by ingest."""
    catalog = load_catalog(store_root)
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
    _save_catalog_entry(store_root, catalog, entry)
    return dict(entry)


