#!/usr/bin/env python3
"""Verify one current CoSchema snapshot and emit a machine-readable report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codess.baseline_validation import (
    load_policy,
    run_query_smoke,
    validate_project,
    write_json_atomic,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--directory", type=Path, required=True,
        help="the Project directory to operate on",
    )
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--raw-store-root", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--query-smoke", action="store_true")
    parser.add_argument(
        "--strict-limitations", action="store_true",
        help="Return failure for accepted_with_limitations",
    )
    args = parser.parse_args(argv)
    try:
        report = validate_project(
            args.directory,
            policy=load_policy(args.policy),
            raw_store_root=args.raw_store_root,
        )
        if args.query_smoke and report["status"] != "rejected":
            smoke = run_query_smoke(args.directory.resolve())
            report["query_smoke"] = smoke
            failures = [name for name, item in smoke.items() if not item["passed"]]
            if failures:
                report["errors"].append(
                    "query_smoke: " + ", ".join(failures)
                )
                report["status"] = "rejected"
    except ValueError as exc:
        print(f"codess: {exc}", file=sys.stderr)
        return 2
    if args.report:
        write_json_atomic(args.report, report)
    print(
        json.dumps(
            {
                "project": report["project"],
                "snapshot_id": report.get("snapshot_id"),
                "status": report["status"],
                "errors": len(report["errors"]),
                "limitations": len(report["limitations"]),
                "semantic_digest": report.get("semantic_digest"),
            },
            sort_keys=True,
        )
    )
    if report["status"] == "rejected":
        return 1
    if args.strict_limitations and report["limitations"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
