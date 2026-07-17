"""Reusable project baseline preservation, apply, and fixed-point workflow."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codess.baseline_catalog import update_approved_catalog
from codess.baseline_validation import (
    load_policy, run_query_smoke, validate_project,
)
from codess.fileio import hash_file, read_json, write_json_atomic
from codess.schema_contract import FORMAT_VERSION, has_legacy_schema, verify_package
from codess.snapshot import current_store_paths, snapshot_store_paths


def preserve_legacy(project: Path, enabled: bool) -> Path | None:
    base = project / ".codess"
    legacy: list[Path] = []
    for path in sorted(base.glob("*.db")):
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            if has_legacy_schema(conn):
                legacy.append(path)
        finally:
            conn.close()
    if not legacy:
        return None
    if (base / "current.json").exists():
        raise RuntimeError("legacy working databases coexist with current.json; review manually")
    if not enabled:
        raise RuntimeError("legacy stores found; rerun with --preserve-legacy")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = base / "legacy" / f"pre-coschema{FORMAT_VERSION}-{stamp}"
    destination.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, Any] = {
        "baseline_kind": "legacy-unversioned-codess",
        "preserved_at": datetime.now(timezone.utc).isoformat(),
        "files": {},
    }
    for source in legacy:
        conn = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            counts = {}
            for table in ("sessions", "events"):
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                if exists:
                    counts[table] = int(
                        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    )
        finally:
            conn.close()
        manifest["files"][source.name] = {
            "sha256": hash_file(source), "size": source.stat().st_size,
            "integrity_check": integrity, **counts,
        }
        shutil.move(str(source), destination / source.name)
    state = base / "ingest_state.json"
    if state.exists():
        manifest["files"][state.name] = {
            "sha256": hash_file(state), "size": state.stat().st_size,
        }
        shutil.move(str(state), destination / state.name)
    write_json_atomic(destination / "baseline.json", manifest)
    return destination


def archive_stale_working_stores(project: Path) -> Path | None:
    base = project / ".codess"
    databases = sorted(base.glob("*.db"))
    if not databases:
        return None
    current_digest = verify_package()
    package_digests: set[str | None] = set()
    for path in databases:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            if not has_legacy_schema(conn):
                package_digests.add(
                    dict(conn.execute("SELECT key, value FROM store_meta")).get(
                        "package_digest"
                    )
                )
        finally:
            conn.close()
    if package_digests == {current_digest} or not package_digests:
        return None
    pointer_path = base / "current.json"
    if not pointer_path.exists():
        raise RuntimeError(
            "working stores use another package and no retained current snapshot exists"
        )
    pointer = read_json(pointer_path)
    snapshot_store_paths(project, pointer["snapshot_id"], allow_package_mismatch=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    old_label = "-".join(sorted((value or "unknown")[:12] for value in package_digests))
    destination = base / "working-archives" / f"pre-package-{old_label}-{stamp}"
    destination.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, Any] = {
        "archive_format": "codess.working-archive/1",
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "reason": "released-package-change-requires-source-rebuild",
        "prior_package_digests": sorted(value or "unknown" for value in package_digests),
        "replacement_package_digest": current_digest,
        "retained_snapshot_id": pointer["snapshot_id"],
        "files": {},
    }
    for source in databases:
        conn = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
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
    state = base / "ingest_state.json"
    if state.exists():
        manifest["files"][state.name] = {
            "sha256": hash_file(state), "size": state.stat().st_size,
        }
        shutil.move(str(state), destination / state.name)
    write_json_atomic(destination / "archive.json", manifest)
    return destination


def reset_rebuildable_working_stores(project: Path) -> list[str]:
    """Discard derived working stores only after verifying a retained snapshot."""
    base = project / ".codess"
    databases = sorted(base.glob("*.db"))
    if not databases:
        return []
    if not (base / "current.json").exists() or not current_store_paths(project):
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
    (base / "ingest_state.json").unlink(missing_ok=True)
    return removed


def run_ingest(
    project: Path,
    *,
    source: str,
    raw_mode: str,
    registry: Path,
    min_size: int,
    repo_root: Path,
) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    command = [
        sys.executable, "-m", "main", "ingest", "--dir", str(project),
        "--source", source, "--force", "--min-size", str(min_size),
        "--raw-mode", raw_mode, "--registry", str(registry),
    ]
    result = subprocess.run(
        command, cwd=repo_root, env=env, capture_output=True,
        text=True, timeout=3600,
    )
    return {
        "command": command, "returncode": result.returncode,
        "stdout": result.stdout, "stderr": result.stderr,
    }


def apply_project(
    project: Path,
    *,
    source: str,
    raw_mode: str,
    registry: Path,
    policy_path: Path | None,
    repeat: bool,
    preserve_legacy_stores: bool,
    approve_catalog: Path | None,
    min_size: int,
    query_smoke: bool,
    repo_root: Path,
    report_path: Path | None = None,
) -> dict[str, Any]:
    project = project.expanduser().resolve()
    registry = registry.expanduser().resolve()
    policy = load_policy(policy_path)
    if policy.get("require_fixed_point") and not repeat:
        raise RuntimeError("policy requires --repeat")
    legacy = preserve_legacy(project, preserve_legacy_stores)
    working_archive = archive_stale_working_stores(project)
    first_reset = reset_rebuildable_working_stores(project)
    first_ingest = run_ingest(
        project, source=source, raw_mode=raw_mode, registry=registry,
        min_size=min_size, repo_root=repo_root,
    )
    if first_ingest["returncode"] != 0:
        raise RuntimeError("ingest failed: " + first_ingest["stderr"].strip())
    raw_root = registry / "raw"
    first = validate_project(project, policy=policy, raw_store_root=raw_root)
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
        )
        if second_ingest["returncode"] != 0:
            raise RuntimeError("repeat ingest failed: " + second_ingest["stderr"].strip())
        second = validate_project(project, policy=policy, raw_store_root=raw_root)
        fixed_point = {
            "source_revisions_match": first.get("source_revisions") == second.get("source_revisions"),
            "semantic_digest_match": first.get("semantic_digest") == second.get("semantic_digest"),
            "normalization_digest_match": first.get("normalization_digest") == second.get("normalization_digest"),
        }
        source_stable = fixed_point["source_revisions_match"]
        if policy.get("allow_source_revision_drift"):
            source_stable = fixed_point["normalization_digest_match"]
        fixed_point["passed"] = bool(
            source_stable and fixed_point["normalization_digest_match"]
            and second["status"] != "rejected"
        )
        if not fixed_point["passed"]:
            raise RuntimeError("fixed-point validation failed")
    final = second or first
    if query_smoke:
        smoke = run_query_smoke(project)
        final["query_smoke"] = smoke
        failures = [name for name, item in smoke.items() if not item["passed"]]
        if failures:
            raise RuntimeError("query smoke failed: " + ", ".join(failures))
    result = {
        "report_format": "codess.apply-report/1",
        "project": str(project), "status": final["status"],
        "legacy_preserved": str(legacy) if legacy else None,
        "working_stores_archived": str(working_archive) if working_archive else None,
        "working_stores_reset": {
            "before_first": first_reset,
            "before_repeat": repeat_reset if repeat else [],
        },
        "first_ingest": first_ingest, "first_validation": first,
        "repeat_ingest": second_ingest, "repeat_validation": second,
        "fixed_point": fixed_point, "final_validation": final,
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
