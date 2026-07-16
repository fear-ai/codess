#!/usr/bin/env python3
"""Verify that a frozen reviewed-baseline set still names current valid data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.baseline_validation import load_policy, validate_project  # noqa: E402
from codess.schema_contract import verify_package  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--catalog", type=Path,
        default=REPO_ROOT / "catalog/reviewed-baselines.json",
    )
    args = parser.parse_args(argv)
    try:
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        if catalog.get("catalog_format") != "codess.reviewed-baselines/1":
            raise ValueError("unsupported reviewed-baseline catalog format")
        if catalog.get("package_digest") != verify_package():
            raise ValueError("reviewed package digest differs from the current package")
        registry = Path(catalog["registry"]).expanduser().resolve()
        results = []
        for item in catalog.get("projects", []):
            project = Path(item["path"]).expanduser().resolve()
            pointer = json.loads(
                (project / ".codess/current.json").read_text(encoding="utf-8")
            )
            if pointer.get("snapshot_id") != item.get("snapshot_id"):
                raise ValueError(f"reviewed snapshot is no longer current: {project}")
            policy_path = Path(item["policy"])
            if not policy_path.is_absolute():
                policy_path = REPO_ROOT / policy_path
            report = validate_project(
                project,
                policy=load_policy(policy_path),
                raw_store_root=registry / "raw",
                verify_reference_current=False,
            )
            for field in ("snapshot_id", "semantic_digest"):
                if report.get(field) != item.get(field):
                    raise ValueError(f"reviewed {field} changed: {project}")
            if report.get("status") != item.get("validation_state"):
                raise ValueError(f"reviewed validation state changed: {project}")
            results.append(
                {
                    "project": str(project),
                    "snapshot_id": report["snapshot_id"],
                    "status": report["status"],
                }
            )
        print(json.dumps({"status": "verified", "projects": results}, sort_keys=True))
        return 0
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"codess: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
