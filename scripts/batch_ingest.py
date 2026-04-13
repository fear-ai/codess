#!/usr/bin/env python3
"""Batch ingest: run find_candidate, filter worthy projects, ingest into per-vendor DBs.
Writes ingested_projects.json to CodeSess/.codess/ (registry root = script dir parent).
Worthy: sess >= 2 OR size_mb >= 1 OR (sess >= 1 and has-remote)."""

import csv
import subprocess
import sys
from pathlib import Path

# CodeSess root (parent of scripts/)
CODESS_ROOT = Path(__file__).resolve().parent.parent
_src = CODESS_ROOT / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))
from codess.config import WORK


def main() -> int:
    # Run codess scan, parse output
    r = subprocess.run(
        [sys.executable, "-m", "main", "scan", "--out", "-"],
        cwd=str(CODESS_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode != 0:
        print(r.stderr or r.stdout, file=sys.stderr)
        return 1

    reader = csv.reader(r.stdout.strip().splitlines())
    rows = list(reader)
    if not rows or rows[0][0] != "path":
        print("No projects found")
        return 0
    candidates = []
    for parts in rows[1:]:
        if len(parts) < 4:
            continue
        path_str, src = parts[0], parts[1] if len(parts) > 1 else ""
        try:
            sess = int(parts[2])
            mb = float(parts[3])
        except (ValueError, IndexError):
            continue
        worthy = sess >= 2 or mb >= 1
        candidates.append((path_str, src, sess, mb, worthy))

    worthy_projects = [(p, s, sess, mb) for p, s, sess, mb, w in candidates if w]
    print(f"Worthy candidates: {len(worthy_projects)}")
    for path_str, src, sess, mb in worthy_projects:
        print(f"  {path_str}  {src}  sess={sess}  mb={mb}")

    for path_str, src, sess, mb in worthy_projects:
        proj_path = (WORK / path_str).resolve()
        if not proj_path.exists():
            print(f"Skipping (path not found): {path_str}", file=sys.stderr)
            continue
        print(f"\nIngesting {proj_path}...")
        r2 = subprocess.run(
            [
                sys.executable, "-m", "main", "ingest",
                "--project", str(proj_path),
                "--registry", str(CODESS_ROOT),
                "--force",
            ],
            cwd=str(CODESS_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r2.returncode != 0:
            print(r2.stderr or r2.stdout, file=sys.stderr)
        else:
            print(r2.stdout.strip())

    from codess.config import get_stats_path, REGISTRY
    stats_file = get_stats_path(REGISTRY)
    if stats_file.exists():
        print(f"\nStats: {stats_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
