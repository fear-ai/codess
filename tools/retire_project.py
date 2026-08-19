#!/usr/bin/env python3
"""Compatibility wrapper for validated Project relocation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codess.catalog_operations import relocate_project
from codess.fileio import write_json_atomic
from codess.project_catalog import ensure_project_binding


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--store", dest="store_root", type=Path, required=True)
    parser.add_argument("--new-location", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        project = args.project.expanduser().resolve()
        binding = ensure_project_binding(args.store_root, project)
        receipt = relocate_project(
            args.store_root, binding["project_id"], project, args.new_location
        )
        receipt["receipt_format"] = "codess.project-retirement/1"
        if args.report:
            write_json_atomic(args.report, receipt)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (OSError, KeyError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"codess: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
