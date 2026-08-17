#!/usr/bin/env python3
"""Compatibility wrapper for one-project baseline apply and verification."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.baseline_operations import apply_project
from codess.fileio import write_json_atomic


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source", choices=("cc", "codex", "cursor", "all"), default="all")
    parser.add_argument("--raw-mode", choices=("none", "reference", "capture", "seal"), default="reference")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--repeat", action="store_true")
    parser.add_argument("--approve-catalog", type=Path)
    parser.add_argument("--min-size", type=int, default=0)
    parser.add_argument("--no-query-smoke", action="store_true")
    args = parser.parse_args(argv)
    project = args.project.expanduser().resolve()
    try:
        result = apply_project(
            project,
            source=args.source,
            raw_mode=args.raw_mode,
            registry=args.registry,
            policy_path=args.policy,
            repeat=args.repeat,
            approve_catalog=args.approve_catalog,
            min_size=args.min_size,
            query_smoke=not args.no_query_smoke,
            catalog_base=args.selection.parent,
            report_path=args.report,
        )
        final = result["final_validation"]
        print(json.dumps({
            "project": str(project), "snapshot_id": final.get("snapshot_id"),
            "status": final["status"], "fixed_point": result.get("fixed_point"),
        }, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        failure = {
            "report_format": "codess.apply-report/1", "project": str(project),
            "status": "rejected", "error": str(exc),
        }
        canonical = project / ".codess/validation-report.json"
        write_json_atomic(canonical, failure)
        if args.report and args.report.resolve() != canonical.resolve():
            write_json_atomic(args.report, failure)
        print(f"codess: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
