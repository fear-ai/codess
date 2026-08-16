#!/usr/bin/env python3
"""Recompute the released CoSchema manifest hashes from the files on disk.

The manifest records a SHA-256 per released file, and `contract_digest` folds
the executable ones into the value every store records. Editing the DDL, the
logical contract, or a mapping profile therefore invalidates the manifest, and
until it is refreshed every loader raises -- which is the intended gate, but it
has to be releasable by a command rather than by editing hashes by hand.

Run after any deliberate change to a released file, and review the reported
digest change the way any wire-format change is reviewed. `--check` reports
whether a refresh is needed without writing, for use in a verification run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codess.fileio import hash_file  # noqa: E402

MANIFEST_PATH = ROOT / "schema/coschema/manifest.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="report stale entries and exit nonzero without writing",
    )
    args = parser.parse_args(argv)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    files = manifest.get("files", {})
    stale: list[str] = []
    for role, entry in sorted(files.items()):
        path = ROOT / entry["path"]
        if not path.is_file():
            print(f"missing: {role} -> {entry['path']}", file=sys.stderr)
            return 2
        actual = hash_file(path)
        if actual != entry.get("sha256"):
            stale.append(role)
            print(f"{'stale' if args.check else 'updated'}: {role} ({entry['path']})")
            entry["sha256"] = actual

    if not stale:
        print("manifest is current")
        return 0
    if args.check:
        print(f"{len(stale)} stale entr{'y' if len(stale) == 1 else 'ies'}")
        return 1

    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"refreshed {len(stale)} entr{'y' if len(stale) == 1 else 'ies'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
