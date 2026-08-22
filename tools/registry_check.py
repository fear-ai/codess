#!/usr/bin/env python3
"""Check the registry's record of Projects against the filesystem.

Three records describe what Codess knows about a Project and they can
disagree: `ingested_projects.json` records what scan saw, `projects.json` is
the catalog of what ingest published, and `projects/<id>/` holds the stores.
Nothing reconciles them, so a Project can be scanned and never ingested,
catalogued and its directory removed, or published twice for one path.

This reports the disagreements. It changes nothing, so it is safe to run at
any time -- periodically, or whenever a count looks wrong.

Findings are graded so a long list stays readable:

  ERROR    the registry contradicts itself or the filesystem
  WARN     a condition that is legitimate but usually unintended
  NOTE     an observation worth seeing, not a defect

    python tools/registry_check.py            # every finding
    python tools/registry_check.py --errors   # exit nonzero on ERROR only
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.config import AGGREGATORS, EXCLUDE_REVIEW_DIRS, STORE_ROOT  # noqa: E402
from codess.helpers import is_excluded  # noqa: E402


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _git_common_dir(path: Path) -> str | None:
    """The shared repository a directory belongs to, following a worktree."""
    if not (path / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--path-format=absolute",
             "--git-common-dir"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def check(store_root: Path) -> list[tuple[str, str, str]]:
    """Return (severity, subject, detail) for every disagreement found."""
    findings: list[tuple[str, str, str]] = []
    scanned = _load(store_root / "ingested_projects.json").get("projects", [])
    catalog = _load(store_root / "projects.json").get("projects", [])

    # A retired location is a path the operator has already accounted for --
    # typically a Project that moved, where the live path is another location
    # on the same entry. Reporting it as nested, excluded, or absent would
    # repeat a finding that has been answered.
    catalog_paths: dict[str, list[dict]] = defaultdict(list)
    retired: set[str] = set()
    for entry in catalog:
        for location in entry.get("locations") or []:
            path = location.get("path")
            if not path:
                continue
            if location.get("state") == "retired" or location.get("path_obsolete"):
                retired.add(path)
                continue
            catalog_paths[path].append(entry)

    # 1. Scanned and never ingested. The corpus silently omits these, and every
    #    list drawn from the catalog inherits the omission.
    for record in scanned:
        path = record.get("path")
        if not path:
            continue
        if not record.get("last_ingestion"):
            findings.append((
                "WARN", path,
                f"scanned {(record.get('last_scan') or '?')[:10]} and never ingested",
            ))

    # 2. One path claimed by several Projects. An entry retained deliberately --
    #    a worktree relation, or an archive holding vendor Sources that no longer
    #    exist -- is a recorded decision rather than a collision, so it is
    #    reported as a note and only unexplained pairs are errors.
    for path, entries in sorted(catalog_paths.items()):
        if len(entries) <= 1:
            continue
        ids = ", ".join(e["project_id"].rsplit(":", 1)[-1][-12:] for e in entries)
        explained = [
            e for e in entries
            if (e.get("catalog_disposition") or {}).get("state")
            or e.get("selection_state")
        ]
        if len(explained) >= len(entries) - 1:
            findings.append((
                "NOTE", path,
                f"{len(entries)} Projects, {len(explained)} with a recorded "
                f"disposition: {ids}",
            ))
        else:
            findings.append(("ERROR", path, f"claimed by {len(entries)} Projects: {ids}"))

    # 3. Catalogued directories that no longer exist.
    findings.extend(
        ("NOTE", path, "catalogued directory is absent from disk")
        for path in sorted(catalog_paths) if not Path(path).is_dir()
    )

    # 4. A Project inside an excluded tree. Sessions land in directories the
    #    operator never meant to develop in, and an exclusion added later does
    #    not retract a Project already published from one.
    for path in sorted(catalog_paths):
        candidate = Path(path)
        if is_excluded(candidate):
            findings.append(("WARN", path, "catalogued although the path is excluded"))
        for entry in EXCLUDE_REVIEW_DIRS:
            needle = tuple(entry.split("/"))
            parts = candidate.parts
            if any(parts[i:i + len(needle)] == needle
                   for i in range(len(parts) - len(needle) + 1)):
                findings.append((
                    "WARN", path,
                    f"catalogued under the excluded tree {entry!r}",
                ))

    # 5. A Project nested inside another Project. Legitimate for a monorepo and
    #    usually accidental: a harness run from a subdirectory publishes it as
    #    its own Project, which then double-counts the parent's work.
    ordered = sorted(catalog_paths)
    findings.extend(
        ("WARN", path, f"nested inside the catalogued Project {other}")
        for path in ordered
        for other in ordered
        if path != other and Path(path).is_relative_to(Path(other))
    )

    # 6. A Project directly under an aggregator, which by definition only
    #    groups Projects. Sessions recorded at that level are usually a harness
    #    started one directory too high.
    findings.extend(
        ("NOTE", path, f"the Project is the aggregator {aggregator!r} itself")
        for path in ordered
        for aggregator in AGGREGATORS
        if Path(path).parts and Path(path).parts[-1] == aggregator
    )

    # 7. Linked git worktrees, which are one repository seen twice. The catalog
    #    has a `worktree` state for this; an unrelated pair double-counts.
    repositories: dict[str, list[str]] = defaultdict(list)
    for path in ordered:
        common = _git_common_dir(Path(path))
        if common:
            repositories[common].append(path)
    for common, members in sorted(repositories.items()):
        if len(members) > 1:
            related = {
                (e.get("catalog_disposition") or {}).get("relation_kind")
                for path in members for e in catalog_paths[path]
            }
            state = "related" if "worktree_of" in related else "UNRELATED"
            findings.append((
                "WARN" if state == "UNRELATED" else "NOTE",
                common,
                f"one repository holds {len(members)} catalogued Projects "
                f"({state}): {', '.join(members)}",
            ))

    # 8. Store-level coherence: a pointer must name a live snapshot.
    projects_dir = store_root / "projects"
    if projects_dir.is_dir():
        for project in sorted(projects_dir.iterdir()):
            pointer = project / "current.json"
            if not pointer.is_file():
                findings.append((
                    "NOTE", project.name[-12:], "no current.json; no published store",
                ))
                continue
            target = _load(pointer).get("path")
            if not target or not Path(target).is_dir():
                findings.append((
                    "ERROR", project.name[-12:],
                    f"current.json names a missing snapshot: {target}",
                ))
            elif "/archive/" in str(target):
                findings.append((
                    "ERROR", project.name[-12:],
                    "current.json points into archive/, which is retained "
                    "evidence rather than a live store",
                ))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", dest="store_root", type=Path, default=STORE_ROOT)
    parser.add_argument("--errors", action="store_true",
                        help="exit nonzero only when an ERROR is found")
    args = parser.parse_args(argv)

    findings = check(args.store_root.expanduser())
    order = {"ERROR": 0, "WARN": 1, "NOTE": 2}
    for severity, subject, detail in sorted(findings, key=lambda f: (order[f[0]], f[1])):
        print(f"{severity:<6} {subject}\n       {detail}")

    counts = {level: sum(1 for f in findings if f[0] == level) for level in order}
    print(
        f"\n{counts['ERROR']} error(s), {counts['WARN']} warning(s), "
        f"{counts['NOTE']} note(s)"
    )
    if not (AGGREGATORS or EXCLUDE_REVIEW_DIRS):
        print(
            "note: no aggregator or exclusion paths are configured, so the "
            "layout checks above could not run",
            file=sys.stderr,
        )
    if counts["ERROR"]:
        return 1
    return 0 if args.errors else (1 if counts["WARN"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())
