#!/usr/bin/env python3
"""Compatibility wrapper for verified atomic baseline catalog freezing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.baseline_catalog import (
    freeze_reviewed_catalogs,
    load_baseline_selection,
)
from codess.config import catalog_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        # `--file`, matching `codess baseline freeze`, which this mirrors.
        "--file", dest="selection", type=Path,
        default=catalog_root() / "baseline-selection.json",
        help="the baseline selection to freeze (default: the configured one)",
    )
    parser.add_argument(
        "--approved", type=Path,
        default=catalog_root() / "approved-baselines.json",
    )
    parser.add_argument(
        "--reviewed", type=Path,
        default=catalog_root() / "reviewed-baselines.json",
    )
    args = parser.parse_args(argv)
    try:
        result = freeze_reviewed_catalogs(
            load_baseline_selection(args.selection),
            approved_path=args.approved,
            reviewed_path=args.reviewed,
            catalog_base=args.selection.parent,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, KeyError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"codess: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
