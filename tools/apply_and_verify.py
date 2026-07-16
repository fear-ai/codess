#!/usr/bin/env python3
"""Ingest exactly one project, validate it, optionally repeat and approve."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.baseline_validation import (  # noqa: E402
    load_policy,
    run_query_smoke,
    validate_project,
    write_json_atomic,
)
from codess.schema_contract import FORMAT_VERSION, has_legacy_schema, verify_package  # noqa: E402
from codess.snapshot import snapshot_store_paths  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _preserve_legacy(project: Path, enabled: bool) -> Path | None:
    base = project / ".codess"
    databases = sorted(base.glob("*.db"))
    legacy: list[Path] = []
    for path in databases:
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
            "sha256": _sha256(source),
            "size": source.stat().st_size,
            "integrity_check": integrity,
            **counts,
        }
        shutil.move(str(source), destination / source.name)
    state = base / "ingest_state.json"
    if state.exists():
        manifest["files"][state.name] = {
            "sha256": _sha256(state), "size": state.stat().st_size
        }
        shutil.move(str(state), destination / state.name)
    write_json_atomic(destination / "baseline.json", manifest)
    return destination


def _archive_stale_working_stores(project: Path) -> Path | None:
    """Archive derived working stores before a package-driven source rebuild."""
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
                meta = dict(conn.execute("SELECT key, value FROM store_meta"))
                package_digests.add(meta.get("package_digest"))
        finally:
            conn.close()
    if package_digests == {current_digest}:
        return None
    if not package_digests:
        return None
    pointer_path = base / "current.json"
    if not pointer_path.exists():
        raise RuntimeError(
            "working stores use another package and no retained current snapshot exists"
        )
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    snapshot_store_paths(
        project, pointer["snapshot_id"], allow_package_mismatch=True
    )
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
            "sha256": _sha256(source), "size": source.stat().st_size,
            "integrity_check": integrity,
        }
        shutil.move(str(source), destination / source.name)
    state = base / "ingest_state.json"
    if state.exists():
        manifest["files"][state.name] = {
            "sha256": _sha256(state), "size": state.stat().st_size,
        }
        shutil.move(str(state), destination / state.name)
    write_json_atomic(destination / "archive.json", manifest)
    return destination


def _run_ingest(
    project: Path,
    *,
    source: str,
    raw_mode: str,
    registry: Path,
    min_size: int,
) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    command = [
        sys.executable, "-m", "main", "ingest", "--dir", str(project),
        "--source", source, "--force", "--min-size", str(min_size),
        "--raw-mode", raw_mode, "--registry", str(registry),
    ]
    result = subprocess.run(
        command, cwd=REPO_ROOT, env=env, capture_output=True,
        text=True, timeout=3600,
    )
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _approve_catalog(
    path: Path,
    validation: dict[str, Any],
    policy_path: Path | None,
    fixed_point: dict[str, Any] | None,
) -> None:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {
            "catalog_format": "codess.approved-baselines/1",
            "coschema_format": FORMAT_VERSION,
            "projects": [],
        }
    by_path = {
        item["path"]: dict(item)
        for item in data.get("projects", [])
        if isinstance(item, dict) and item.get("path")
    }
    project = validation["project"]
    entry = by_path.get(project, {"path": project})
    entry.update(
        {
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
    )
    by_path[project] = entry
    data["projects"] = sorted(by_path.values(), key=lambda item: item["path"])
    data["package_digest"] = verify_package()
    write_json_atomic(path, data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source", choices=("cc", "codex", "cursor", "all"), default="all")
    parser.add_argument("--raw-mode", choices=("none", "reference", "capture", "seal"), default="reference")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--repeat", action="store_true")
    parser.add_argument("--preserve-legacy", action="store_true")
    parser.add_argument("--approve-catalog", type=Path)
    parser.add_argument("--min-size", type=int, default=0)
    parser.add_argument("--no-query-smoke", action="store_true")
    args = parser.parse_args(argv)
    project = args.project.expanduser().resolve()
    registry = args.registry.expanduser().resolve()
    try:
        policy = load_policy(args.policy)
        if policy.get("require_fixed_point") and not args.repeat:
            raise RuntimeError("policy requires --repeat")
        legacy = _preserve_legacy(project, args.preserve_legacy)
        working_archive = _archive_stale_working_stores(project)
        first_ingest = _run_ingest(
            project, source=args.source, raw_mode=args.raw_mode,
            registry=registry, min_size=args.min_size,
        )
        if first_ingest["returncode"] != 0:
            raise RuntimeError("ingest failed: " + first_ingest["stderr"].strip())
        raw_root = registry / "raw"
        first = validate_project(project, policy=policy, raw_store_root=raw_root)
        if first["status"] == "rejected":
            raise RuntimeError("first validation rejected: " + "; ".join(first["errors"]))

        second = None
        fixed_point = None
        second_ingest = None
        if args.repeat:
            second_ingest = _run_ingest(
                project, source=args.source, raw_mode=args.raw_mode,
                registry=registry, min_size=args.min_size,
            )
            if second_ingest["returncode"] != 0:
                raise RuntimeError("repeat ingest failed: " + second_ingest["stderr"].strip())
            second = validate_project(project, policy=policy, raw_store_root=raw_root)
            fixed_point = {
                "source_revisions_match": first.get("source_revisions") == second.get("source_revisions"),
                "semantic_digest_match": first.get("semantic_digest") == second.get("semantic_digest"),
                "normalization_digest_match": (
                    first.get("normalization_digest") == second.get("normalization_digest")
                ),
            }
            source_stable = fixed_point["source_revisions_match"]
            if policy.get("allow_source_revision_drift"):
                source_stable = fixed_point["normalization_digest_match"]
            fixed_point["passed"] = (
                source_stable
                and fixed_point["normalization_digest_match"]
                and second["status"] != "rejected"
            )
            if not fixed_point["passed"]:
                raise RuntimeError("fixed-point validation failed")

        final = second or first
        if not args.no_query_smoke:
            smoke = run_query_smoke(project)
            final["query_smoke"] = smoke
            failures = [name for name, item in smoke.items() if not item["passed"]]
            if failures:
                raise RuntimeError("query smoke failed: " + ", ".join(failures))
        result = {
            "report_format": "codess.apply-report/1",
            "project": str(project),
            "status": final["status"],
            "legacy_preserved": str(legacy) if legacy else None,
            "working_stores_archived": str(working_archive) if working_archive else None,
            "first_ingest": first_ingest,
            "first_validation": first,
            "repeat_ingest": second_ingest,
            "repeat_validation": second,
            "fixed_point": fixed_point,
            "final_validation": final,
        }
        if args.approve_catalog:
            _approve_catalog(args.approve_catalog, final, args.policy, fixed_point)
        canonical_report = project / ".codess" / "validation-report.json"
        write_json_atomic(canonical_report, result)
        if args.report and args.report.resolve() != canonical_report.resolve():
            write_json_atomic(args.report, result)
        print(
            json.dumps(
                {
                    "project": str(project),
                    "snapshot_id": final.get("snapshot_id"),
                    "status": final["status"],
                    "fixed_point": fixed_point,
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        failure = {
            "report_format": "codess.apply-report/1",
            "project": str(project),
            "status": "rejected",
            "error": str(exc),
        }
        canonical_report = args.project.expanduser().resolve() / ".codess" / "validation-report.json"
        write_json_atomic(canonical_report, failure)
        if args.report and args.report.resolve() != canonical_report.resolve():
            write_json_atomic(args.report, failure)
        print(f"codess: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
