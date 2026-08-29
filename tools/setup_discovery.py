#!/usr/bin/env python3
"""Report the effective discovery configuration, and propose exclusions.

Codess ships its grouping and exclusion lists empty, because a default drawn
from one machine's tree misclassifies directories on every other one. This is
the first step of the documented setup sequence: it states what the running
process resolved -- not what a documentation table says -- and then
proposes candidates from the operator's own tree for them to edit.

It reads directory names and vendor indexes. It does not read Session content,
write configuration, or modify anything.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.config import (  # noqa: E402
    CC_PROJECTS,
    CODEX_SESSIONS,
    CURSOR_DATA,
    DEFAULT_WORK,
    STORE_ROOT,
)
from codess.helpers import (  # noqa: E402
    DISCOVERY_POLICY_PATH,
    EXCLUDE_PATHS,
    INCLUDE_PATHS,
    TRAVERSAL_PRUNE_DIRS,
    TRAVERSED_ON_PURPOSE,
)


def _security_note() -> str:
    """The policy's own statement of why pruning is not a security control."""
    try:
        document = json.loads(DISCOVERY_POLICY_PATH.read_text(encoding="utf-8"))
        return str(document.get("security_note", ""))
    except (OSError, ValueError):
        return ""


def _origin(name: str, value: tuple[str, ...]) -> str:
    return f"{name} (set)" if os.environ.get(name) else "default (empty)" if not value else "default"


def report_configuration() -> dict:
    """What the running process resolved, with where each value came from."""
    return {
        "work_root": {
            "value": str(DEFAULT_WORK),
            "exists": DEFAULT_WORK.exists(),
            "source": "CODESS_WORK (set)" if os.environ.get("CODESS_WORK") else "default ~/Work",
        },
        "registry": {"value": str(STORE_ROOT), "exists": STORE_ROOT.exists()},
        "vendor_roots": {
            "claude": {"path": str(CC_PROJECTS), "exists": CC_PROJECTS.exists()},
            "codex": {"path": str(CODEX_SESSIONS), "exists": CODEX_SESSIONS.exists()},
            "cursor": {"path": str(CURSOR_DATA), "exists": CURSOR_DATA.exists()},
        },
        "exclude_paths": {
            "value": list(EXCLUDE_PATHS),
            "source": _origin("CODESS_EXCLUDE_PATHS", EXCLUDE_PATHS),
        },
        "include_paths": {
            "value": list(INCLUDE_PATHS),
            "source": _origin("CODESS_INCLUDE_PATHS", INCLUDE_PATHS),
        },
        "exclude_dirs": sorted(TRAVERSAL_PRUNE_DIRS),
        "traversed_on_purpose": TRAVERSED_ON_PURPOSE,
    }


def _worked_in_roots(*, codex_sample: int = 400) -> set[str]:
    """Project paths that the three vendor indexes show real work in.

    A container holding many repositories is only a *review* tree if none was
    worked in. Counting repositories alone proposed excluding a container that
    held active Projects, which would have hidden them.

    Each vendor states the working directory differently, and all three are
    read -- an earlier version read Claude alone and would have called a
    Codex- or Cursor-only container unworked:

    | Vendor | Index | Evidence |
    |---|---|---|
    | Claude | `~/.claude/projects` | The directory slug encodes the path |
    | Codex | rollout `session_meta` | `payload.cwd`, recorded directly |
    | Cursor | `workspaceStorage` | `workspace.json` names the folder |

    The Claude slug is read rather than decoded: the encoding is lossy, so a
    hyphenated directory is ambiguous, and this only needs a substring test
    against candidate names. Codex reading is bounded by `codex_sample`, since
    a rollout tree can hold thousands of files and this is a proposal rather
    than an inventory.
    """
    roots: set[str] = set()

    if CC_PROJECTS.is_dir():
        for entry in CC_PROJECTS.iterdir():
            if entry.is_dir() and entry.name.startswith("-"):
                roots.add(entry.name.replace("-", "/"))

    if CODEX_SESSIONS.is_dir():
        for index, rollout in enumerate(CODEX_SESSIONS.rglob("*.jsonl")):
            if index >= codex_sample:
                break
            try:
                with rollout.open(encoding="utf-8", errors="replace") as stream:
                    for line in stream:
                        payload = (json.loads(line).get("payload") or {})
                        if payload.get("cwd"):
                            roots.add(str(payload["cwd"]))
                            break
                        break
            except (OSError, ValueError):
                continue

    workspaces = CURSOR_DATA / "workspaceStorage"
    if workspaces.is_dir():
        for entry in workspaces.iterdir():
            marker = entry / "workspace.json"
            if not marker.is_file():
                continue
            try:
                folder = json.loads(marker.read_text(encoding="utf-8")).get("folder")
            except (OSError, ValueError):
                continue
            if isinstance(folder, str) and folder.startswith("file://"):
                roots.add(unquote(urlparse(folder).path))

    return roots


def propose(work_root: Path, *, depth: int = 2) -> dict:
    """Candidate aggregators and review trees, from the operator's own tree.

    A container is a directory whose children are repositories rather than
    itself being one. A review tree is a container holding many of them *and*
    no evidence of work. The output is a proposal to edit, never applied.
    """
    worked_in = _worked_in_roots()
    containers: list[dict] = []
    if not work_root.is_dir():
        return {"work_root": str(work_root), "exists": False, "containers": []}

    for entry in sorted(work_root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name.casefold() in TRAVERSAL_PRUNE_DIRS:
            continue
        if (entry / ".git").is_dir():
            continue  # a repository, not a container
        children = [c for c in entry.iterdir() if c.is_dir()] if depth > 1 else []
        repos = [c for c in children if (c / ".git").is_dir()]
        if repos:
            active = sum(
                1 for repo in repos
                if any(f"/{entry.name}/{repo.name}" in root for root in worked_in)
            )
            review = len(repos) >= 10 and active == 0
            containers.append({
                "path": entry.name,
                "repositories": len(repos),
                "worked_in": active,
                "suggest": "exclude" if review else "aggregator",
                "why": (
                    f"{len(repos)} repositories, none worked in: likely a review tree"
                    if review
                    else f"{len(repos)} repositories, {active} worked in: grouping directory"
                ),
            })
    return {
        "work_root": str(work_root),
        "exists": True,
        "containers": containers,
        # One list, absolute. `exclude_paths` absorbed both settings, because
        # a grouping directory and a reference tree were the same judgment
        # under two names: a tree the operator keeps rather than develops in.
        # Absolute because the setting is, and because a work-root-relative
        # segment could not name a tree outside the work root at all.
        "suggested_exclusions": [
            str((work_root / c["path"]).resolve())
            for c in containers
            if c["suggest"] in ("aggregator", "exclude")
        ],
    }


def _render(configuration: dict, proposal: dict | None) -> None:
    work = configuration["work_root"]
    print(f"work root   {work['value']}  (exists={work['exists']}, {work['source']})")
    print(f"registry    {configuration['registry']['value']}")
    print("\nvendor stores")
    for vendor, info in configuration["vendor_roots"].items():
        mark = "found" if info["exists"] else "absent"
        print(f"  {vendor:8s} {mark:7s} {info['path']}")

    for key, label in (
        ("exclude_paths", "excluded paths"),
        ("include_paths", "included paths"),
    ):
        entry = configuration[key]
        shown = ", ".join(entry["value"]) if entry["value"] else "(none)"
        print(f"\n{label}: {shown}\n  from {entry['source']}")

    print(f"\nexcluded names ({len(configuration['exclude_dirs'])}), never traversed:")
    names = configuration["exclude_dirs"]
    for index in range(0, len(names), 6):
        print("  " + "  ".join(f"{n:16s}" for n in names[index:index + 6]).rstrip())

    print("\ntraversed on purpose -- exclude by path if yours hold no work:")
    for name, why in sorted(configuration["traversed_on_purpose"].items()):
        print(f"  {name:14s} {why}")
    note = _security_note()
    if note:
        print("\n" + note)

    if proposal and proposal.get("exists"):
        print(f"\ncandidates under {proposal['work_root']}:")
        if not proposal["containers"]:
            print("  none -- every child is a repository or holds none")
        for container in proposal["containers"]:
            print(f"  {container['path']:22s} {container['why']}")
        if proposal["suggested_exclusions"]:
            print("\n  For one shell:")
            print("  export CODESS_EXCLUDE_PATHS='"
                  + ",".join(proposal["suggested_exclusions"]) + "'")
            print("\n  For this machine, which is where a durable decision"
                  " belongs -- add to")
            print(f"  {DISCOVERY_POLICY_PATH}:")
            print(json.dumps(
                {"exclude_paths": proposal["suggested_exclusions"]}, indent=2,
            ))
        print("\n  Review before applying: a container holding many repositories is a\n"
              "  reference tree only if you have not worked in it. Exclusions matter for\n"
              "  trees where you HAVE worked and do not want reported.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK)
    parser.add_argument(
        "--no-propose", action="store_true",
        help="report configuration only, without reading the work root",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    configuration = report_configuration()
    proposal = None if args.no_propose else propose(args.work_root)
    if args.json:
        print(json.dumps({"configuration": configuration, "proposal": proposal}, indent=2))
    else:
        _render(configuration, proposal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
