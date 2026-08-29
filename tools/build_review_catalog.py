#!/usr/bin/env python3
"""Build a clean, reviewable Codess catalog seed from a candidate CSV."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codess.catalog import CatalogError, load_candidate_csv

from codess.fileio import write_json_atomic


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_csv", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--work-root", type=Path, default=Path.home() / "Work")
    args = parser.parse_args(argv)
    try:
        catalog = load_candidate_csv(args.candidate_csv, work_root=args.work_root)
    except CatalogError as exc:
        print(f"codess: {exc}", file=sys.stderr)
        return 1
    write_json_atomic(args.output, catalog)
    print(f"Wrote {len(catalog['projects'])} candidates to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
