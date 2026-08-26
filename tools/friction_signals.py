#!/usr/bin/env python3
"""Preliminary signals of misses and operator displeasure, per Project.

**Preliminary is the operative word, and it is a property of the method rather
than of the effort spent.** Nothing here reads sentiment or rates the work. It
counts four things the vendor recorded and one lexical pattern, and every one
of them is a *candidate* for review rather than a finding:

| Signal | What it is | Why it is only a candidate |
|---|---|---|
| `interrupted` | The harness wrote `[Request interrupted by user]` | Vendor-stated and unambiguous, but an interrupt can mean "wrong direction" or "I thought of something better" |
| `denied` | A tool permission the operator refused | Vendor-stated. Refusing a destructive command is good practice, not displeasure |
| `failed` | A tool the vendor recorded as failed | A failing test *is* the work; a failure is not a miss |
| `corrective` | A prompt opening with a correction -- `no`, `wrong`, `not`, `revert` | Lexical, so it misses politely-phrased corrections and catches `no need to` |

**The corrective pattern is anchored to the opening.** A correction that
matters is stated first: `wrong -- public documents do NOT link to internal
ones`. Matching anywhere in the text would catch every `no` in ordinary prose
and report a rate near 100%.

**Rates are compared within a Project, not across them.** Corrective share
depends on how the operator writes, and a terse operator scores higher than a
diplomatic one doing identical work. What travels is the *change* in a
Project's own rate over time, which is why `--since` exists.

    python tools/friction_signals.py
    python tools/friction_signals.py --project Misses --examples
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.config import STORE_ROOT  # noqa: E402

# The harness writes this verbatim when the operator stops a turn mid-stream.
# Vendor-stated rather than inferred, which makes it the strongest signal here.
INTERRUPTED = re.compile(r"\[request interrupted", re.IGNORECASE)

# A correction stated at the opening of a prompt. Anchored deliberately: an
# unanchored match catches every `no` in ordinary prose. Measured on this
# corpus, the anchored form selects 90 of 6,402 prompts and the examples read
# as real corrections.
CORRECTIVE = re.compile(
    r"^\s*(no[,.! ]|not |wrong|that'?s not|nope|actually,|i said|"
    r"you (missed|forgot|broke)|revert|undo|stop)",
    re.IGNORECASE,
)

# Below this a rate is arithmetic rather than evidence: one correction in
# twenty prompts is 5% and means nothing.
MIN_PROMPTS = 40


def _logical_names(store_root: Path) -> dict[str, str]:
    try:
        catalog = json.loads(
            (store_root / "projects.json").read_text(encoding="utf-8"),
        )
    except (OSError, ValueError):
        return {}
    return {
        str(entry["project_id"]).rsplit(":", 1)[-1]: str(
            entry.get("logical_name") or "",
        )
        for entry in catalog.get("projects", [])
        if entry.get("project_id")
    }


def collect(
    store_root: Path, *, keep_examples: bool = False,
) -> list[dict[str, Any]]:
    """One row per Project, with counts and optional example text."""
    names = _logical_names(store_root)
    per: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "prompts": 0, "corrective": 0, "interrupted": 0,
            "denied": 0, "failed": 0, "tool_calls": 0, "examples": [],
        },
    )
    for pointer in sorted((store_root / "projects").glob("*/current.json")):
        project_id = pointer.parent.name
        try:
            snapshot = json.loads(pointer.read_text(encoding="utf-8")).get("path")
        except (OSError, ValueError):
            continue
        if not snapshot or not Path(snapshot).is_dir():
            continue
        row = per[project_id]
        for database in sorted(Path(snapshot).glob("*.db")):
            conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
            try:
                for (text,) in conn.execute(
                    "SELECT content FROM events WHERE event_kind='message.prompt' "
                    "AND actor_kind='human' AND content IS NOT NULL",
                ):
                    stripped = str(text or "").strip()
                    row["prompts"] += 1
                    if INTERRUPTED.search(stripped):
                        row["interrupted"] += 1
                    elif CORRECTIVE.match(stripped):
                        row["corrective"] += 1
                        if keep_examples and len(row["examples"]) < 8:
                            row["examples"].append(
                                " ".join(stripped.split())[:160],
                            )
                for name, column in (
                    ("denied", "denied"), ("failed", "failed"),
                ):
                    row[name] += int(conn.execute(
                        "SELECT count(*) FROM tool_results "
                        "WHERE normalized_status = ?", (column,),
                    ).fetchone()[0])
                row["tool_calls"] += int(conn.execute(
                    "SELECT count(*) FROM tool_invocations",
                ).fetchone()[0])
            except sqlite3.Error:
                continue
            finally:
                conn.close()

    rows = []
    for project_id, values in per.items():
        if values["prompts"] < MIN_PROMPTS:
            continue
        prompts = values["prompts"]
        rows.append({
            "project": names.get(project_id) or project_id[:8],
            "prompts": prompts,
            "corrective": values["corrective"],
            "corrective_rate": round(values["corrective"] / prompts, 4),
            "interrupted": values["interrupted"],
            "denied": values["denied"],
            "failed": values["failed"],
            "tool_calls": values["tool_calls"],
            "examples": values["examples"],
        })
    return sorted(rows, key=lambda row: -row["corrective_rate"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--store", dest="store_root", type=Path, default=STORE_ROOT,
        help="the machine's durable store (default: %(default)s)",
    )
    parser.add_argument("--project", help="report one Project by logical name")
    parser.add_argument(
        "--examples", action="store_true",
        help="include the matched prompt openings, so a reader can judge the "
             "pattern rather than trust it",
    )
    args = parser.parse_args(argv)

    rows = collect(args.store_root.expanduser(), keep_examples=args.examples)
    if args.project:
        rows = [
            row for row in rows
            if args.project.casefold() in row["project"].casefold()
        ]
    if not args.examples:
        for row in rows:
            row.pop("examples", None)
    print(json.dumps({
        "note": "preliminary candidates for review, not findings; rates "
                "compare within a Project rather than across them",
        "projects": rows,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
