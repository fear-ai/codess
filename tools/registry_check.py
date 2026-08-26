#!/usr/bin/env python3
"""Check the registry's record of Projects against the filesystem.

Three records describe what Codess knows about a Project and they can
disagree: `projects_state.json` records what scan saw, `projects.json` is
the catalog of what ingest published, and `projects/<id>/` holds the stores.
Nothing reconciles them, so a Project can be scanned and never ingested,
catalogued and its directory removed, or published twice for one path.

This reports the disagreements. It changes nothing, so it is safe to run at
any time -- periodically, or whenever a count looks wrong.

Findings are graded so a long list stays readable:

  ERROR    the registry contradicts itself or the filesystem
  WARN     a condition that is legitimate but usually unintended
  NOTE     an observation worth seeing, not a defect

A finding names the command that resolves it where one exists, because the
conditions here are ones where the wrong choice is expensive: retiring a
location that moved is not the same as retiring one that was copied.

    python tools/registry_check.py            # every finding
    python tools/registry_check.py --errors   # exit nonzero on ERROR only
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from project_inventory import inventory  # noqa: E402

from codess.config import CC_PROJECTS, STORE_ROOT  # noqa: E402
from codess.helpers import (  # noqa: E402
    EXCLUDE_PATHS,
    INCLUDE_PATHS,
    is_excluded,
    resolve_slug,
    slug_to_path,
)


@dataclass(frozen=True, slots=True)
class Finding:
    """One disagreement, and the command that resolves it.

    `remedy` is `None` where the condition is ambiguous by nature -- a copy and
    a restore present identically, and only the operator knows which occurred.
    Printing a command there would direct them to guess.
    """

    severity: str
    subject: str
    detail: str
    remedy: str | None = None


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


def _claude_slug_splits(catalog_paths: dict[str, list[dict]]) -> list[Finding]:
    """Pair a slug whose path is gone with a live Project of the same name.

    Claude's slug encodes the absolute path, so a move splits one Project's
    history across two slug directories and no vendor field joins them. The
    catalog's `path_aliases` is the existing mechanism for stating that two
    paths are one Project; nothing populates it from a slug.

    The match is by trailing directory name because that is what a move
    preserves. It is a *proposal*, never an automatic join: a same-named
    directory under a different parent is as likely to be an unrelated Project,
    and only the operator can tell those apart.
    """
    if not CC_PROJECTS.is_dir():
        return []
    live_by_name: dict[str, list[str]] = defaultdict(list)
    for path in catalog_paths:
        if Path(path).is_dir():
            live_by_name[Path(path).name].append(path)

    findings: list[Finding] = []
    for slug_dir in sorted(CC_PROJECTS.iterdir()):
        if not slug_dir.is_dir() or resolve_slug(slug_dir.name) is not None:
            continue
        stale = slug_to_path(slug_dir.name)
        candidates = [
            live for live in live_by_name.get(stale.name, [])
            if Path(live) != stale
        ]
        if len(candidates) != 1:
            continue
        identities = {
            str(entry["project_id"]) for entry in catalog_paths[candidates[0]]
        }
        remedy = (
            f"codess catalog relocate --project-id {identities.pop()} "
            f"--from {stale} --to {candidates[0]}"
            if len(identities) == 1 else None
        )
        findings.append(Finding(
            "WARN", str(stale),
            f"Claude holds Sessions under a slug whose path is gone, and "
            f"{candidates[0]} is a live Project of the same name: one "
            f"Project's history may be split across two slugs",
            remedy,
        ))
    return findings


def _vanished_source_findings(store_root: Path) -> list[Finding]:
    """Report a store whose vendor Sources no longer exist.

    Severity follows what is at stake rather than what is unusual. A purged
    store is the only remaining record of its Sessions, so deleting it is
    unrecoverable and it is an ERROR that any destructive operation must see; a
    partial one is the same condition part-way and is a WARN.
    """
    findings: list[Finding] = []
    for row in inventory(store_root):
        vanished = row.get("sources_vanished")
        if not isinstance(vanished, int) or vanished <= 0:
            continue
        name = str(row.get("logical_name") or row.get("project_id") or "")
        total = row.get("sources_total")
        findings.append(Finding(
            "ERROR" if row.get("coverage") == "purged" else "WARN",
            name,
            f"{vanished} of {total} recorded Sources no longer exist: this "
            f"store is the only remaining record of those Sessions, so a "
            f"prune, a rebuild, or a superseded-store cleanup destroys them",
            "python tools/project_inventory.py   # before any deletion",
        ))
    return findings


def check(store_root: Path) -> list[Finding]:
    """Return one `Finding` per disagreement found.

    Each carries the command that resolves it where one exists. A report that
    names a condition and stops leaves the operator to work out which of
    several catalog operations applies, and the conditions are precisely the
    ones where guessing wrong is expensive -- retiring a location that moved is
    not the same as retiring one that was copied.
    """
    findings: list[Finding] = []
    scanned = _load(store_root / "projects_state.json").get("projects", [])
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
            findings.append(Finding(
                "WARN", path,
                f"scanned {(record.get('last_scan') or '?')[:10]} and never ingested",
                f"codess ingest --dir {path}",
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
            findings.append(Finding(
                "NOTE", path,
                f"{len(entries)} Projects, {len(explained)} with a recorded "
                f"disposition: {ids}",
            ))
        else:
            # No remedy: which identity is the Project is the operator's to
            # state. Retiring the wrong one discards the reviewed entry.
            findings.append(Finding(
                "ERROR", path, f"claimed by {len(entries)} Projects: {ids}",
            ))

    # 3. Catalogued directories that no longer exist.
    for path in sorted(catalog_paths):
        if Path(path).is_dir():
            continue
        identities = {e["project_id"] for e in catalog_paths[path]}
        remedy = (
            f"codess catalog location retire --project-id {identities.pop()} "
            f"--directory {path}"
            if len(identities) == 1 else None
        )
        findings.append(Finding(
            "NOTE", path, "catalogued directory is absent from disk", remedy,
        ))

    # 4. A Project inside an excluded tree. Sessions land in directories the
    #    operator never meant to develop in, and an exclusion added later does
    #    not retract a Project already published from one.
    for path in sorted(catalog_paths):
        candidate = Path(path)
        if is_excluded(candidate):
            findings.append(Finding(
                "WARN", path, "catalogued although the path is excluded",
            ))
        findings.extend(
            Finding(
                "WARN", path, f"catalogued under the excluded tree {entry!r}",
            )
            for entry in EXCLUDE_PATHS
            if candidate == Path(entry) or candidate.is_relative_to(Path(entry))
        )

    # 5. A Project nested inside another Project. Legitimate for a monorepo and
    #    usually accidental: a harness run from a subdirectory publishes it as
    #    its own Project, which then double-counts the parent's work.
    ordered = sorted(catalog_paths)
    findings.extend(
        Finding("WARN", path, f"nested inside the catalogued Project {other}")
        for path in ordered
        for other in ordered
        if path != other and Path(path).is_relative_to(Path(other))
    )

    # 6. A Project that *is* an excluded tree rather than sitting inside one.
    #    Reported separately from check 4 because the answer differs: a Project
    #    under an excluded tree is usually a clone the operator did not mean to
    #    catalogue, while the tree itself being catalogued means the exclusion
    #    was added after the Project was published.
    findings.extend(
        Finding(
            "NOTE", path,
            f"the catalogued Project is the excluded tree {entry!r} itself",
        )
        for path in ordered
        for entry in EXCLUDE_PATHS
        if Path(path) == Path(entry)
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
            findings.append(Finding(
                "WARN" if state == "UNRELATED" else "NOTE",
                common,
                f"one repository holds {len(members)} catalogued Projects "
                f"({state}): {', '.join(members)}",
                None if state != "UNRELATED" else (
                    "codess catalog decide --project <id> --relation worktree_of "
                    "--related-project <id>"
                ),
            ))

    # 8. A Claude slug split. Claude's storage slug *encodes the absolute path*,
    #    so moving a Project leaves its history under the old slug and writes
    #    new Sessions under a new one, with nothing joining them. Two slugs
    #    whose decoded paths differ, where one path is absent and the other is
    #    live, are one Project's history seen either side of a move.
    #
    #    `resolve_slug` returns None precisely when a slug's path is no longer
    #    on disk, which is the absent half of the pair; it is matched against a
    #    live catalogued path by the trailing directory name, since that is
    #    what a move preserves and the parent is what it changes.
    findings.extend(_claude_slug_splits(catalog_paths))

    # 9. Vendor Sources that no longer exist. A store whose Sources are gone is
    #    the only remaining record of those Sessions, so this decides whether a
    #    prune, a rebuild, or a superseded-store cleanup may touch it -- and
    #    getting that wrong is unrecoverable. Computed by `project_inventory`
    #    and, until now, reported by no command.
    findings.extend(_vanished_source_findings(store_root))

    # 10. Store-level coherence: a pointer must name a live snapshot.
    projects_dir = store_root / "projects"
    if projects_dir.is_dir():
        for project in sorted(projects_dir.iterdir()):
            pointer = project / "current.json"
            if not pointer.is_file():
                findings.append(Finding(
                    "NOTE", project.name[-12:], "no current.json; no published store",
                ))
                continue
            target = _load(pointer).get("path")
            if not target or not Path(target).is_dir():
                findings.append(Finding(
                    "ERROR", project.name[-12:],
                    f"current.json names a missing snapshot: {target}",
                ))
            elif "/archive/" in str(target):
                findings.append(Finding(
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
    for finding in sorted(
        findings, key=lambda f: (order[f.severity], f.subject),
    ):
        print(f"{finding.severity:<6} {finding.subject}\n       {finding.detail}")
        if finding.remedy:
            print(f"       run: {finding.remedy}")

    counts = {
        level: sum(1 for f in findings if f.severity == level) for level in order
    }
    print(
        f"\n{counts['ERROR']} error(s), {counts['WARN']} warning(s), "
        f"{counts['NOTE']} note(s)"
    )
    # A skipped check currently reads as a passing one: with no path settings
    # configured the layout checks do not run and the totals report zero, which
    # is indistinguishable from clean. Name the checks that did not run and the
    # setting that enables them. Not an error -- that would break a first run on
    # a clean checkout, which is the early-access path.
    if not (EXCLUDE_PATHS or INCLUDE_PATHS):
        print(
            "\nnot checked: 2 layout checks (a Project directly under a "
            "grouping directory, and a Project under a reference tree) did not "
            "run because no path settings are configured, so the totals above "
            "are not a clean result for them.\n"
            "  set: CODESS_EXCLUDE_PATHS, or run "
            "`python tools/setup_discovery.py --propose`",
            file=sys.stderr,
        )
    if counts["ERROR"]:
        return 1
    return 0 if args.errors else (1 if counts["WARN"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())
