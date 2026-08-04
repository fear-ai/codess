#!/usr/bin/env python3
"""Compatibility wrapper for verified atomic baseline catalog freezing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.baseline_catalog import (  # noqa: E402
    freeze_reviewed_catalogs, load_baseline_selection,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--selection", type=Path,
        default=REPO_ROOT / "catalog/baseline-selection.json",
    )
    parser.add_argument(
        "--approved", type=Path,
        default=REPO_ROOT / "catalog/approved-baselines.json",
    )
    parser.add_argument(
        "--reviewed", type=Path,
        default=REPO_ROOT / "catalog/reviewed-baselines.json",
    )
    args = parser.parse_args(argv)
    try:
        result = freeze_reviewed_catalogs(
            load_baseline_selection(args.selection),
            approved_path=args.approved,
            reviewed_path=args.reviewed,
            repo_root=REPO_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, KeyError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"codess: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
