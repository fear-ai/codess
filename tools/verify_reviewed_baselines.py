#!/usr/bin/env python3
"""Compatibility wrapper for frozen reviewed-baseline verification."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.baseline_catalog import verify_reviewed_catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=REPO_ROOT / "catalog/reviewed-baselines.json")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(
            verify_reviewed_catalog(args.catalog, repo_root=REPO_ROOT), sort_keys=True
        ))
        return 0
    except (OSError, KeyError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"codess: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
