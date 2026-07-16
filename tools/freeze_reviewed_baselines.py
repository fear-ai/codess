#!/usr/bin/env python3
"""Atomically replace approved and manually reviewed baseline catalogs."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.baseline_validation import write_json_atomic  # noqa: E402
from codess.schema_contract import FORMAT_VERSION, verify_package  # noqa: E402


PROJECTS = (
    (Path("/Users/walter/Work/Code/SWEmore"), "catalog/policies/swemore.json"),
    (Path("/Users/walter/Work/Spank/spank-py"), "catalog/policies/spank-py.json"),
    (Path("/Users/walter/Work/ZK/Zero400"), "catalog/policies/zero400.json"),
)


def main() -> int:
    package_digest = verify_package()
    approved_projects = []
    reviewed_projects = []
    registries = set()
    for project, policy in PROJECTS:
        report_path = project / ".codess/validation-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        final = report.get("final_validation") or {}
        if report.get("status") != "accepted" or final.get("status") != "accepted":
            raise RuntimeError(f"project is not fully accepted: {project}")
        if final.get("package_digest") != package_digest:
            raise RuntimeError(f"project package differs from current package: {project}")
        if not (report.get("fixed_point") or {}).get("passed"):
            raise RuntimeError(f"project lacks a fixed point: {project}")
        pointer = json.loads((project / ".codess/current.json").read_text(encoding="utf-8"))
        registry = str(Path(pointer["path"]).parents[2].parent)
        registries.add(registry)
        approved_projects.append({
            "path": str(project),
            "project_id": pointer.get("project_id"),
            "snapshot_id": final["snapshot_id"],
            "parent_snapshot_id": final.get("parent_snapshot_id"),
            "selection_state": "approved",
            "validation_state": "accepted",
            "sources": final.get("counts_by_source", {}),
            "raw_records": final.get("raw_records", 0),
            "raw_mode": final.get("raw_mode"),
            "mapping_diagnostics": final.get("diagnostics", {}),
            "semantic_digest": final["semantic_digest"],
            "validation_policy": policy,
            "fixed_point": report["fixed_point"],
            "query_smoke": {
                name: value.get("passed", False)
                for name, value in final.get("query_smoke", {}).items()
            },
        })
        reviewed_projects.append({
            "path": str(project),
            "project_id": pointer.get("project_id"),
            "snapshot_id": final["snapshot_id"],
            "semantic_digest": final["semantic_digest"],
            "validation_state": "accepted",
            "policy": policy,
        })
    if len(registries) != 1:
        raise RuntimeError(f"reviewed projects use different registries: {registries}")
    registry = registries.pop()
    approved = {
        "catalog_format": "codess.approved-baselines/1",
        "coschema_format": FORMAT_VERSION,
        "package_digest": package_digest,
        "registry": registry,
        "projects": approved_projects,
    }
    reviewed = {
        "catalog_format": "codess.reviewed-baselines/1",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "review_state": "accepted_with_known_gaps",
        "package_digest": package_digest,
        "registry": registry,
        "projects": reviewed_projects,
        "known_gaps": [
            "same-artifact multi-vendor correlation is fixture-proven rather than selected-real-project evidence",
            "lifecycle abort and missing timestamp behavior remain fixture-only",
            "reasoning effort, speed tier, and service tier are absent from selected source records",
            "Codex parent-session identifiers are absent across the metadata-only local audit"
        ],
    }
    write_json_atomic(REPO_ROOT / "catalog/approved-baselines.json", approved)
    write_json_atomic(REPO_ROOT / "catalog/reviewed-baselines.json", reviewed)
    print(json.dumps({
        "status": "frozen", "package_digest": package_digest,
        "projects": len(reviewed_projects), "registry": registry,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"codess: {exc}", file=sys.stderr)
        raise SystemExit(1)
