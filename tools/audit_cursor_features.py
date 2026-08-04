#!/usr/bin/env python3
"""Write a structure-only Cursor tool/model evidence report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.baseline_validation import write_json_atomic  # noqa: E402
from codess.cursor_feature_audit import audit_cursor_features  # noqa: E402
from codess.project_catalog import load_catalog  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db", type=Path,
        default=Path.home() / "Library/Application Support/Cursor/User/globalStorage/state.vscdb",
    )
    parser.add_argument("--registry", type=Path, default=Path.home() / ".codess")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_cursor_features(args.db, load_catalog(args.registry))
    if args.output:
        write_json_atomic(args.output, report)
    print(json.dumps({
        "bubble_records": report["bubble_records"],
        **report["evidence"],
        "workspaces_with_evidence": len(report["workspace_evidence"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
