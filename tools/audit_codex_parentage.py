#!/usr/bin/env python3
"""Write a metadata-only Codex parent-session evidence report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codess.baseline_validation import write_json_atomic
from codess.codex_parent_audit import audit_parentage
from codess.evidence import codex_session_roots


def main() -> int:
    parser = argparse.ArgumentParser()
    configured = dict(codex_session_roots())
    parser.add_argument("--active", type=Path, default=configured["active"])
    parser.add_argument(
        "--archive", type=Path, default=configured.get("archive"),
        help="the archived sessions directory (default: the configured one, if any)",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    roots = [("active", args.active)]
    if args.archive is not None:
        roots.append(("archive", args.archive))
    report = audit_parentage(roots)
    if args.output:
        write_json_atomic(args.output, report)
    print(json.dumps({
        "files_with_session_meta": report["files_with_session_meta"],
        "cli_versions": len(report["cli_versions"]),
        "parent_candidate_fields": len(report["parent_candidate_fields"]),
        "resolved_parent_references": report["resolved_parent_references"],
        "support_status": report["support_status"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
