#!/usr/bin/env python3
"""Fail-closed compatibility gate for machine-readable CoSchema contracts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codess.schema_evolution import RANK, compare, required  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("--declared", choices=RANK, default="same")
    args = parser.parse_args(argv)
    try:
        old = json.loads(Path(args.old).read_text(encoding="utf-8"))
        new = json.loads(Path(args.new).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    findings = list(compare(old, new))
    for level, path, message in findings:
        print(f"{level.upper():10s} {path}: {message}")
    need = required(findings)
    print(f"required: {need}; declared: {args.declared}")
    if need == "manual":
        return 1
    return 0 if RANK[args.declared] >= RANK[need] else 1


if __name__ == "__main__":
    raise SystemExit(main())
