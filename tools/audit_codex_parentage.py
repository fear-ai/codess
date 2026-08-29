#!/usr/bin/env python3
"""Write a metadata-only Codex parent-session evidence report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.baseline_validation import write_json_atomic
from codess.codex_parent_audit import audit_parentage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active", type=Path, default=Path.home() / ".codex/sessions")
    parser.add_argument("--archive", type=Path, default=Path.home() / ".codex/archived_sessions")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_parentage([("active", args.active), ("archive", args.archive)])
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
