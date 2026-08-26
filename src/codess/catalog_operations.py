"""Reviewed batch onboarding and explicit Project-location lifecycle operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codess.baseline_validation import validate_project
from codess.child_invocation import ChildInvocation, RunPolicy
from codess.config import CURRENT_POINTER_FILE, RAW_MANIFEST_FILE, SNAPSHOTS_DIR
from codess.fileio import read_json, write_json_atomic
from codess.hashing import codess_bytes_hash, codess_canonical_hash
from codess.project_catalog import (
    add_project_location,
    durable_project_root,
    get_project_entry,
    retire_project_location,
)
from codess.schema_contract import contract_digest
from codess.snapshot import current_stores
from codess.timeval import now_iso
from codess.wallclock import system_clock

ONBOARD_RECEIPT_FORMAT = "codess.catalog-onboard/1"


def resolve_reviewed_selection(
    catalog_path: Path, *, decision: str = "approved", source: str = "all",
) -> dict[str, Any]:
    catalog = read_json(catalog_path)
    projects = []
    for item in catalog.get("projects", []):
        if (item.get("review") or {}).get("decision") != decision:
            continue
        path = Path(item["path"]).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"selected Project path is unavailable: {path}")
        projects.append({
            "project_id": item.get("project_id"), "path": str(path),
            "source": source,
        })
    projects.sort(key=lambda item: (item.get("project_id") or "", item["path"]))
    if not projects:
        raise ValueError(f"catalog has no projects with review decision {decision!r}")
    return {
        "catalog": str(catalog_path.resolve()),
        "catalog_sha256": codess_bytes_hash(256, 256, catalog_path.read_bytes()),
        "selection_sha256": codess_canonical_hash(256, 256, projects),
        "contract_digest": contract_digest(),
        "review_decision": decision,
        "projects": projects,
    }


def _run_ingest_stage(
    plan: dict[str, Any], run: RunPolicy, *, validate: bool, source: str,
) -> dict[str, Any]:
    invocation = ChildInvocation(
        policy=run,
        projects=tuple(Path(item["path"]) for item in plan["projects"]),
        vendor_selector=source, validate=validate,
    )
    command = invocation.command()
    result = invocation.run()
    parsed = None
    if validate and result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            parsed = None
    return {
        "command": command, "returncode": result.returncode,
        "stdout": None if parsed is not None else result.stdout,
        "stderr": result.stderr,
        "report": parsed,
    }


def onboard_catalog(
    catalog_path: Path,
    run: RunPolicy,
    *,
    decision: str = "approved",
    source: str = "all",
    apply: bool = False,
    stop_after: str | None = None,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Plan, preflight, and optionally apply an ingest for a reviewed catalog.

    `run` rather than its four fields: `registry`, `repo_root`, `raw_mode`, and
    `resource_policy` reached only the `_run_ingest_stage` calls below.
    """
    plan = resolve_reviewed_selection(
        catalog_path, decision=decision, source=source
    )
    plan["raw_mode"] = run.raw_mode
    receipt: dict[str, Any] = {
        "receipt_format": ONBOARD_RECEIPT_FORMAT,
        "created_at": now_iso(system_clock), "status": "planned", "plan": plan,
        "preflight": None, "apply": None,
    }
    if stop_after != "plan":
        preflight = _run_ingest_stage(
            plan, run, validate=True, source=source,
        )
        receipt["preflight"] = preflight
        if preflight["returncode"] != 0:
            receipt["status"] = "preflight_rejected"
        elif stop_after == "preflight" or not apply:
            receipt["status"] = "preflight_accepted"
        else:
            current = resolve_reviewed_selection(
                catalog_path, decision=decision, source=source
            )
            if current["selection_sha256"] != plan["selection_sha256"]:
                raise RuntimeError("reviewed selection changed between preflight and apply")
            if current["contract_digest"] != plan["contract_digest"]:
                raise RuntimeError("CoSchema package changed between preflight and apply")
            applied = _run_ingest_stage(
                plan, run, validate=False, source=source,
            )
            receipt["apply"] = applied
            receipt["status"] = "applied" if applied["returncode"] == 0 else "apply_failed"
    if receipt_path:
        write_json_atomic(receipt_path, receipt)
    return receipt


def _captured_current(registry: Path, project_id: str) -> bool:
    durable = durable_project_root(registry, project_id)
    pointer = durable / CURRENT_POINTER_FILE
    if not pointer.exists():
        return False
    value = read_json(pointer)
    snapshot = durable / SNAPSHOTS_DIR / value["snapshot_id"]
    raw_manifest = snapshot / RAW_MANIFEST_FILE
    if not raw_manifest.exists():
        return False
    records = [
        json.loads(line) for line in raw_manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    sources = [item for item in records if item.get("record_type") != "header"]
    return bool(sources) and all(item.get("availability") == "captured" for item in sources)


def retire_location(registry: Path, project_id: str, path: Path) -> dict[str, Any]:
    entry = get_project_entry(registry, project_id)
    excluded = entry.get("selection_state") == "excluded"
    return retire_project_location(
        registry, project_id, path,
        allow_last_active=excluded or _captured_current(registry, project_id),
    )


def relocate_project(
    registry: Path,
    project_id: str,
    old_path: Path,
    new_path: Path,
) -> dict[str, Any]:
    old_path = old_path.expanduser().resolve()
    new_path = new_path.expanduser().resolve()
    validation = validate_project(old_path, raw_store_root=registry / "raw")
    if validation["status"] != "accepted":
        raise RuntimeError(
            "relocation requires a fully reproducible accepted baseline: "
            + "; ".join(validation.get("errors", []) + validation.get("limitations", []))
        )
    if not _captured_current(registry, project_id):
        raise RuntimeError("relocation requires every raw source revision to be captured")
    source_pointer = old_path / ".codess/current.json"
    if not source_pointer.exists():
        raise RuntimeError("old location has no current snapshot pointer")
    catalog_path = registry / "projects.json"
    prior_catalog = catalog_path.read_bytes() if catalog_path.exists() else None
    pointer_path = new_path / ".codess/current.json"
    prior_pointer = pointer_path.read_bytes() if pointer_path.exists() else None
    new_path.mkdir(parents=True, exist_ok=True)
    try:
        binding = add_project_location(registry, project_id, new_path)
        write_json_atomic(pointer_path, read_json(source_pointer))
        if not current_stores(new_path):
            raise RuntimeError("new location cannot read the durable snapshot")
        retired = retire_project_location(
            registry, project_id, old_path, allow_last_active=False
        )
    except Exception:
        if prior_catalog is None:
            catalog_path.unlink(missing_ok=True)
        else:
            rollback = catalog_path.with_name(f".{catalog_path.name}.rollback")
            rollback.write_bytes(prior_catalog)
            rollback.replace(catalog_path)
        if prior_pointer is None:
            pointer_path.unlink(missing_ok=True)
        else:
            rollback = pointer_path.with_name(f".{pointer_path.name}.rollback")
            rollback.write_bytes(prior_pointer)
            rollback.replace(pointer_path)
        raise
    return {
        "project_id": project_id, "old_location": retired,
        "new_location": binding, "verified": True,
        "snapshot_id": validation.get("snapshot_id"),
        "semantic_digest": validation.get("semantic_digest"),
    }
