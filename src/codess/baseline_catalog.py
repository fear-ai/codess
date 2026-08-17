"""Construction, freezing, and verification of accepted baseline catalogs."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codess.baseline_validation import load_policy, validate_project
from codess.fileio import read_json, write_json_atomic
from codess.project_catalog import durable_project_root
from codess.schema_contract import FORMAT_VERSION, contract_digest

SELECTION_FORMAT = "codess.baseline-selection/1"
APPROVED_FORMAT = "codess.approved-baselines/1"
REVIEWED_FORMAT = "codess.reviewed-baselines/1"
ACCEPTED_STATES = frozenset({"accepted", "accepted_with_limitations"})


def approved_entry(
    validation: dict[str, Any],
    *,
    policy_path: Path | None,
    fixed_point: dict[str, Any] | None,
) -> dict[str, Any]:
    entry = {
        "path": validation["project"],
        "snapshot_id": validation["snapshot_id"],
        "parent_snapshot_id": validation.get("parent_snapshot_id"),
        "selection_state": "approved",
        "validation_state": validation["status"],
        "sources": validation.get("counts_by_source", {}),
        "raw_records": validation.get("raw_records", 0),
        "raw_mode": validation.get("raw_mode"),
        "mapping_diagnostics": validation.get("diagnostics", {}),
        "semantic_digest": validation.get("semantic_digest"),
        "validation_policy": str(policy_path.resolve()) if policy_path else None,
        "last_automated_validation": {
            "validated_at": validation.get("generated_at"),
            "fixed_point": fixed_point,
            "query_smoke": {
                name: result.get("passed", False)
                for name, result in validation.get("query_smoke", {}).items()
            },
        },
    }
    if validation.get("project_id") is not None:
        entry["project_id"] = validation["project_id"]
    return entry


def update_approved_catalog(
    path: Path,
    validation: dict[str, Any],
    *,
    policy_path: Path | None,
    fixed_point: dict[str, Any] | None,
) -> None:
    data = read_json(path) if path.exists() else {
        "catalog_format": APPROVED_FORMAT,
        "coschema_format": FORMAT_VERSION,
        "projects": [],
    }
    if data.get("catalog_format") != APPROVED_FORMAT:
        raise ValueError("unsupported approved-baseline catalog format")
    entries = {
        item["path"]: dict(item)
        for item in data.get("projects", [])
        if isinstance(item, dict) and item.get("path")
    }
    entry = approved_entry(
        validation, policy_path=policy_path, fixed_point=fixed_point
    )
    old = entries.get(entry["path"], {})
    old.update(entry)
    entries[entry["path"]] = old
    data["projects"] = sorted(entries.values(), key=lambda item: item["path"])
    data["contract_digest"] = contract_digest()
    write_json_atomic(path, data)


def load_baseline_selection(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if value.get("selection_format") != SELECTION_FORMAT:
        raise ValueError(f"baseline selection must declare {SELECTION_FORMAT}")
    projects = value.get("projects")
    if not isinstance(projects, list) or not projects:
        raise ValueError("baseline selection projects must be a nonempty array")
    for item in projects:
        if not isinstance(item, dict) or not item.get("path") or not item.get("policy"):
            raise ValueError("each baseline selection needs path and policy")
    return value


def _accepted_from_reports(
    projects: Iterable[dict[str, Any]], *, catalog_base: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Accept the reported Projects, resolving each one's policy path.

    `catalog_base` is the directory a relative `policy` field resolves
    against, and is the *selection document's own directory* rather than a
    global root. That is what makes a selection portable: a policy named
    `policies/x.json` beside its selection resolves wherever the pair is
    placed, so moving the catalog out of the checkout (W58) does not rewrite
    every stored path. An absolute path is used as given, unchanged.
    """
    current_digest = contract_digest()
    approved: list[dict[str, Any]] = []
    reviewed: list[dict[str, Any]] = []
    registries: set[str] = set()
    for specification in projects:
        project = Path(specification["path"]).expanduser().resolve()
        policy = Path(specification["policy"])
        if not policy.is_absolute():
            policy = catalog_base / policy
        report = read_json(project / ".codess/validation-report.json")
        final = report.get("final_validation") or {}
        if (
            report.get("status") not in ACCEPTED_STATES
            or final.get("status") not in ACCEPTED_STATES
        ):
            raise RuntimeError(f"project is not fully accepted: {project}")
        if final.get("contract_digest") != current_digest:
            raise RuntimeError(f"project contract differs from the current one: {project}")
        if not (report.get("fixed_point") or {}).get("passed"):
            raise RuntimeError(f"project lacks a fixed point: {project}")
        pointer = read_json(project / ".codess/current.json")
        registry = str(Path(pointer["path"]).parents[2].parent)
        registries.add(registry)
        current = validate_project(
            project,
            policy=load_policy(policy),
            raw_store_root=Path(registry) / "raw",
            verify_reference_current=False,
        )
        if current.get("status") not in ACCEPTED_STATES:
            raise RuntimeError(f"current baseline validation rejected: {project}")
        for field in ("snapshot_id", "semantic_digest", "contract_digest"):
            if current.get(field) != final.get(field):
                raise RuntimeError(f"accepted report {field} is stale: {project}")
        final = {**current, "query_smoke": final.get("query_smoke", {})}
        entry = approved_entry(
            final, policy_path=policy, fixed_point=report["fixed_point"]
        )
        entry["path"] = str(project)
        entry["project_id"] = pointer.get("project_id")
        approved.append(entry)
        reviewed.append({
            "path": str(project),
            "project_id": pointer.get("project_id"),
            "snapshot_id": final["snapshot_id"],
            "semantic_digest": final["semantic_digest"],
            "validation_state": final["status"],
            "policy": (
                str(policy.relative_to(catalog_base))
                if policy.is_relative_to(catalog_base) else str(policy)
            ),
        })
    if len(registries) != 1:
        raise RuntimeError(f"reviewed projects use different registries: {registries}")
    return approved, reviewed, registries.pop()


def verify_reviewed_catalog(path: Path, *, catalog_base: Path | None = None) -> dict[str, Any]:
    catalog = read_json(path)
    if catalog.get("catalog_format") != REVIEWED_FORMAT:
        raise ValueError("unsupported reviewed-baseline catalog format")
    if catalog.get("contract_digest") != contract_digest():
        raise ValueError("reviewed package digest differs from the current package")
    registry = Path(catalog["registry"]).expanduser().resolve()
    results = []
    for item in catalog.get("projects", []):
        project = Path(item["path"]).expanduser().resolve()
        project_id = item.get("project_id")
        snapshot_id = item.get("snapshot_id")
        if not isinstance(project_id, str) or not project_id:
            raise ValueError(f"reviewed Project lacks project_id: {project}")
        if not isinstance(snapshot_id, str) or not snapshot_id:
            raise ValueError(f"reviewed Project lacks snapshot_id: {project}")
        snapshot = (
            durable_project_root(registry, project_id)
            / "snapshots" / snapshot_id
        )
        policy_path = Path(item["policy"])
        if not policy_path.is_absolute():
            policy_path = (catalog_base or path.parent) / policy_path
        report = validate_project(
            project,
            policy=load_policy(policy_path),
            raw_store_root=registry / "raw",
            verify_reference_current=False,
            snapshot_path=snapshot,
        )
        for field in ("snapshot_id", "semantic_digest"):
            if report.get(field) != item.get(field):
                raise ValueError(f"reviewed {field} changed: {project}")
        if report.get("status") != item.get("validation_state"):
            raise ValueError(f"reviewed validation state changed: {project}")
        results.append({
            "project": str(project), "project_id": project_id,
            "snapshot_id": report["snapshot_id"], "status": report["status"],
        })
    return {"status": "verified", "projects": results}


def freeze_reviewed_catalogs(
    selection: dict[str, Any],
    *,
    approved_path: Path,
    reviewed_path: Path,
    catalog_base: Path,
) -> dict[str, Any]:
    """Freeze the accepted Projects into the approved and reviewed catalogs.

    `catalog_base` anchors relative policy paths, and is normally the
    directory holding the selection document. Passing it explicitly rather
    than deriving it keeps the caller in control of where a portable
    selection is rooted (W58).
    """
    approved_projects, reviewed_projects, registry = _accepted_from_reports(
        selection["projects"], catalog_base=catalog_base
    )
    current_digest = contract_digest()
    approved = {
        "catalog_format": APPROVED_FORMAT,
        "coschema_format": FORMAT_VERSION,
        "contract_digest": current_digest,
        "registry": registry,
        "projects": approved_projects,
    }
    reviewed = {
        "catalog_format": REVIEWED_FORMAT,
        "reviewed_at": datetime.now(UTC).isoformat(),
        "review_state": "accepted_with_known_gaps",
        "contract_digest": current_digest,
        "registry": registry,
        "projects": reviewed_projects,
        "known_gaps": selection.get("known_gaps", []),
    }
    previous = {
        approved_path: approved_path.read_bytes() if approved_path.exists() else None,
        reviewed_path: reviewed_path.read_bytes() if reviewed_path.exists() else None,
    }
    try:
        write_json_atomic(approved_path, approved)
        write_json_atomic(reviewed_path, reviewed)
        verification = verify_reviewed_catalog(
            reviewed_path, catalog_base=catalog_base
        )
    except Exception:
        for path, content in previous.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                temporary = path.with_name(f".{path.name}.rollback")
                temporary.write_bytes(content)
                temporary.replace(path)
        raise
    return {
        "status": "frozen",
        "contract_digest": current_digest,
        "projects": len(reviewed_projects),
        "registry": registry,
        "verification": verification,
    }
