#!/usr/bin/env python3
"""Batch ingest: run find_candidate, filter worthy projects, ingest into per-vendor DBs.
Writes ingested_projects.json to CodeSess/.coding-sess/ (registry root = script dir parent).
Worthy: sess >= 2 OR size_mb >= 1 OR (sess >= 1 and has-remote)."""

import subprocess
import sys
from pathlib import Path

# CodeSess root (parent of scripts/)
CODESS_ROOT = Path(__file__).resolve().parent.parent
if str(CODESS_ROOT) not in sys.path:
    sys.path.insert(0, str(CODESS_ROOT))
from config import WORK


def main() -> int:
    # Run find_candidate, parse output
    r = subprocess.run(
        [sys.executable, str(CODESS_ROOT / "scripts" / "find_candidate.py")],
        cwd=str(CODESS_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode != 0:
        print(r.stderr or r.stdout, file=sys.stderr)
        return 1

    lines = r.stdout.splitlines()
    candidates = []
    in_candidates = False
    for line in lines:
        if line.startswith("=== CANDIDATES (metrics) ==="):
            in_candidates = True
            continue
        if in_candidates and line.startswith("==="):
            break
        if in_candidates and line.strip() and not line.startswith("-"):
            parts = line.split()
            if len(parts) >= 7:
                path_str = parts[0]
                src = parts[1] if len(parts) > 1 else ""
                sess = int(parts[5]) if parts[5].isdigit() else 0
                mb = float(parts[6]) if parts[6].replace(".", "").isdigit() else 0.0
                remote = parts[4] if len(parts) > 4 else ""
                worthy = sess >= 2 or mb >= 1 or (sess >= 1 and remote == "has-remote")
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

    # Ingest Cursor global once (v44.9+ stores all sessions in globalStorage)
    print("\nIngesting Cursor global (central store)...")
    r3 = subprocess.run(
        [
            sys.executable, "-m", "main", "ingest",
            "--project", str(CODESS_ROOT),
            "--source", "cursor",
            "--cursor-global",
            "--registry", str(CODESS_ROOT),
            "--force",
        ],
        cwd=str(CODESS_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r3.returncode == 0:
        print(r3.stdout.strip())
    else:
        print(r3.stderr or r3.stdout, file=sys.stderr)

    stats_file = CODESS_ROOT / ".coding-sess" / "ingested_projects.json"
    if stats_file.exists():
        print(f"\nStats: {stats_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
