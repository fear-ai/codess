"""Reusable project baseline preservation, apply, and fixed-point workflow."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codess.acceptance import compare_snapshots
from codess.baseline_catalog import update_approved_catalog
from codess.baseline_validation import (
    load_policy,
    run_query_smoke,
    validate_project,
)
from codess.config import (
    CURRENT_POINTER_FILE,
    LAST_INGEST_REPORT_FILE,
    STATE_FILE,
    STORE_DIR,
    WORKING_ARCHIVES_DIR,
)
from codess.fileio import hash_file, open_readonly, read_json, write_json_atomic
from codess.schema_contract import contract_digest, store_metadata
from codess.snapshot import (
    current_stores,
    publish_snapshot,
    snapshot_store_paths,
    snapshot_store_paths_from_base,
)


def archive_stale_working_stores(project: Path) -> Path | None:
    base = project / STORE_DIR
    databases = sorted(base.glob("*.db"))
    if not databases:
        return None
    current_digest = contract_digest()
    package_digests: set[str | None] = set()
    for path in databases:
        conn = open_readonly(path)
        try:
            package_digests.add(store_metadata(conn).get("package_digest"))
        finally:
            conn.close()
    if package_digests == {current_digest} or not package_digests:
        return None
    pointer_path = base / CURRENT_POINTER_FILE
    if not pointer_path.exists():
        raise RuntimeError(
            "working stores use another package and no retained current snapshot exists"
        )
    pointer = read_json(pointer_path)
    snapshot_store_paths(project, pointer["snapshot_id"], allow_package_mismatch=True)
    # One archival event, one instant. The directory name and the manifest's
    # `archived_at` are two renderings of the same moment, so reading the clock
    # twice would let a directory claim a different second than the manifest
    # inside it -- and the directory name is what an operator sorts by.
    archived_at = datetime.now(UTC)
    stamp = archived_at.strftime("%Y%m%dT%H%M%SZ")
    old_label = "-".join(sorted((value or "unknown")[:12] for value in package_digests))
    destination = base / WORKING_ARCHIVES_DIR / f"pre-package-{old_label}-{stamp}"
    destination.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, Any] = {
        "archive_format": "codess.working-archive/1",
        "archived_at": archived_at.isoformat(),
        "reason": "released-package-change-requires-source-rebuild",
        "prior_package_digests": sorted(value or "unknown" for value in package_digests),
        "replacement_package_digest": current_digest,
        "retained_snapshot_id": pointer["snapshot_id"],
        "files": {},
    }
    for source in databases:
        conn = open_readonly(source)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
        if integrity != "ok":
            raise RuntimeError(f"refusing to archive corrupt working store: {source}")
        manifest["files"][source.name] = {
            "sha256": hash_file(source), "size": source.stat().st_size,
            "integrity_check": integrity,
        }
        shutil.move(str(source), destination / source.name)
    state = base / STATE_FILE
    if state.exists():
        manifest["files"][state.name] = {
            "sha256": hash_file(state), "size": state.stat().st_size,
        }
        shutil.move(str(state), destination / state.name)
    write_json_atomic(destination / "archive.json", manifest)
    return destination


def reset_rebuildable_working_stores(project: Path) -> list[str]:
    """Discard derived working stores only after verifying a retained snapshot."""
    base = project / STORE_DIR
    databases = sorted(base.glob("*.db"))
    if not databases:
        return []
    if not (base / CURRENT_POINTER_FILE).exists() or not current_stores(project):
        raise RuntimeError(
            "refusing to rebuild working stores without a readable retained snapshot"
        )
    removed = []
    for database in databases:
        removed.append(database.name)
        for path in (
            database,
            Path(str(database) + "-journal"),
            Path(str(database) + "-wal"),
            Path(str(database) + "-shm"),
        ):
            path.unlink(missing_ok=True)
    (base / STATE_FILE).unlink(missing_ok=True)
    return removed


def run_ingest(
    project: Path,
    *,
    source: str,
    raw_mode: str,
    registry: Path,
    min_size: int,
    repo_root: Path,
    resource_policy: Path | None = None,
    candidate_snapshot: bool = False,
) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    command = [
        sys.executable, "-m", "main", "ingest", "--dir", str(project),
        "--source", source, "--force", "--min-size", str(min_size),
        "--raw-mode", raw_mode, "--registry", str(registry),
    ]
    if candidate_snapshot:
        command.append("--candidate-snapshot")
    if resource_policy is not None:
        command.extend(["--resource-policy", str(resource_policy)])
    result = subprocess.run(
        command, cwd=repo_root, env=env, capture_output=True,
        text=True, timeout=3600,
    )
    runtime_report = {}
    runtime_path = project / STORE_DIR / LAST_INGEST_REPORT_FILE
    if result.returncode == 0 and runtime_path.exists():
        runtime_report = read_json(runtime_path)
    return {
        "command": command, "returncode": result.returncode,
        "stdout": result.stdout, "stderr": result.stderr,
        "snapshot_id": runtime_report.get("snapshot_id"),
        "candidate_snapshot_path": runtime_report.get(
            "candidate_snapshot_path"
        ),
    }


def apply_project(
    project: Path,
    *,
    source: str,
    raw_mode: str,
    registry: Path,
    policy_path: Path | None,
    repeat: bool,
    approve_catalog: Path | None,
    min_size: int,
    query_smoke: bool,
    repo_root: Path,
    report_path: Path | None = None,
    resource_policy: Path | None = None,
) -> dict[str, Any]:
    project = project.expanduser().resolve()
    registry = registry.expanduser().resolve()
    policy = load_policy(policy_path)
    if policy.get("require_fixed_point") and not repeat:
        raise RuntimeError("policy requires --repeat")
    working_archive = archive_stale_working_stores(project)
    first_reset = reset_rebuildable_working_stores(project)
    first_ingest = run_ingest(
        project, source=source, raw_mode=raw_mode, registry=registry,
        min_size=min_size, repo_root=repo_root,
        resource_policy=resource_policy,
        candidate_snapshot=True,
    )
    if first_ingest["returncode"] != 0:
        raise RuntimeError("ingest failed: " + first_ingest["stderr"].strip())
    first_candidate = first_ingest.get("candidate_snapshot_path")
    if not isinstance(first_candidate, str) or not first_candidate:
        raise RuntimeError("ingest did not report a candidate snapshot")
    first_snapshot = Path(first_candidate).resolve()
    raw_root = registry / "raw"
    verify_reference_current = not bool(
        policy.get("allow_source_revision_drift")
    )
    first = validate_project(
        project,
        policy=policy,
        raw_store_root=raw_root,
        verify_reference_current=verify_reference_current,
        snapshot_path=first_snapshot,
    )
    if first["status"] == "rejected":
        raise RuntimeError("first validation rejected: " + "; ".join(first["errors"]))
    second = None
    second_ingest = None
    fixed_point = None
    if repeat:
        repeat_reset = reset_rebuildable_working_stores(project)
        second_ingest = run_ingest(
            project, source=source, raw_mode=raw_mode, registry=registry,
            min_size=min_size, repo_root=repo_root,
            resource_policy=resource_policy,
            candidate_snapshot=True,
        )
        if second_ingest["returncode"] != 0:
            raise RuntimeError("repeat ingest failed: " + second_ingest["stderr"].strip())
        second_candidate = second_ingest.get("candidate_snapshot_path")
        if not isinstance(second_candidate, str) or not second_candidate:
            raise RuntimeError("repeat ingest did not report a candidate snapshot")
        second_snapshot = Path(second_candidate).resolve()
        second = validate_project(
            project,
            policy=policy,
            raw_store_root=raw_root,
            verify_reference_current=verify_reference_current,
            snapshot_path=second_snapshot,
        )
        fixed_point = {
            "source_revisions_match": first.get("source_revisions") == second.get("source_revisions"),
            "semantic_digest_match": first.get("semantic_digest") == second.get("semantic_digest"),
            "normalization_digest_match": first.get("normalization_digest") == second.get("normalization_digest"),
        }
        prior_paths = snapshot_store_paths_from_base(
            first_snapshot.parent.parent,
            first["snapshot_id"],
            allow_package_mismatch=False,
        )
        rebuilt_paths = snapshot_store_paths_from_base(
            second_snapshot.parent.parent,
            second["snapshot_id"],
            allow_package_mismatch=False,
        )
        value_acceptance = compare_snapshots(
            prior_paths,
            rebuilt_paths,
            allow_source_revision_drift=bool(
                policy.get("allow_source_revision_drift")
            ),
        )
        fixed_point["value_acceptance"] = value_acceptance
        source_stable = fixed_point["source_revisions_match"]
        if policy.get("allow_source_revision_drift"):
            source_stable = fixed_point["normalization_digest_match"]
        fixed_point["passed"] = bool(
            source_stable and fixed_point["normalization_digest_match"]
            and value_acceptance["accepted"]
            and second["status"] != "rejected"
        )
        if not fixed_point["passed"]:
            raise RuntimeError("fixed-point validation failed")
    final = second or first
    final_snapshot = second_snapshot if second is not None else first_snapshot
    if query_smoke:
        smoke = run_query_smoke(
            project,
            snapshot_id=final["snapshot_id"],
            snapshot_path=final_snapshot,
        )
        final["query_smoke"] = smoke
        failures = [name for name, item in smoke.items() if not item["passed"]]
        if failures:
            raise RuntimeError("query smoke failed: " + ", ".join(failures))
    published = publish_snapshot(
        project,
        final_snapshot,
        registry_root=registry,
        project_id=final.get("project_id"),
    )
    result = {
        "report_format": "codess.apply-report/1",
        "project": str(project), "status": final["status"],
        "working_stores_archived": str(working_archive) if working_archive else None,
        "working_stores_reset": {
            "before_first": first_reset,
            "before_repeat": repeat_reset if repeat else [],
        },
        "first_ingest": first_ingest, "first_validation": first,
        "repeat_ingest": second_ingest, "repeat_validation": second,
        "fixed_point": fixed_point, "final_validation": final,
        "publication": {
            "status": "published",
            "snapshot_id": published["snapshot_id"],
            "project_pointer": str(project / ".codess/current.json"),
        },
    }
    if approve_catalog:
        update_approved_catalog(
            approve_catalog, final, policy_path=policy_path, fixed_point=fixed_point
        )
    canonical = project / ".codess/validation-report.json"
    write_json_atomic(canonical, result)
    if report_path and report_path.resolve() != canonical.resolve():
        write_json_atomic(report_path, result)
    return result
