#!/usr/bin/env python3
"""Extract human/model exchanges as a flat dataset for downstream analysis.

Step one of two: this reads stores and writes a plain format -- JSONL, CSV, or a
labelled dialog transcript. Analysis and visualization read that file and never
open a store, so a measure can be re-derived, diffed, or handed to another tool
without SQL.

**What an exchange is.** One human prompt and the model replies that follow it,
up to the next human prompt. That is the unit a reader thinks in, and it is not
a CoSchema entity: an Interaction is the vendor's own boundary where one is
recorded, and a Model Turn is one evidenced model execution. This derives the
pairing from Session sequence and marks it as derived, because sequence is
evidence and adjacency is not proof.

**What is excluded, and why each is a separate decision.**

- *Harness traffic wearing a user envelope.* A Claude `user` record can carry a
  tool result, a context injection, or a task notification. `actor_kind` and
  `origin_kind` already distinguish these, so the filter is a predicate over
  classification rather than a guess about content.
- *Scripted runs.* `surface_kind='api'` on Claude means `entrypoint: sdk-cli`,
  which is a programmatic invocation. Measured: 328 of 1,167 Claude prompts are
  scripted and 839 are typed at a terminal. Excluded by default and admitted by
  `--surface any`, because a study of harness behaviour wants them.
- *Status-only prompts.* `continue`, `go`, `ls` carry no task. They are real
  human input and they are not a request, so they are excluded from the default
  dataset and counted, never silently dropped.

**Bouts, not Sessions.** A Session can span days; the work inside it happens in
bursts. Measured over 4,905 consecutive human prompts, the median gap is 5
minutes and 90% fall under an hour, so a gap longer than `--bout-gap` starts a
new bout. That is a derived boundary and every row states which bout it belongs
to, so an analysis can use Sessions instead by ignoring the column.

    python tools/dialog_extract.py --out dialog.jsonl
    python tools/dialog_extract.py --format csv --out dialog.csv
    python tools/dialog_extract.py --format dialog --out dialog.txt --since 30d
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.config import STORE_ROOT  # noqa: E402

# A gap longer than this starts a new bout. Measured over 4,905 consecutive
# human prompts: p50 is 5 minutes, p75 is 16, p90 is 63, and the tail runs to
# days. One hour sits just past the knee, so a bout is a sitting rather than a
# calendar Session.
DEFAULT_BOUT_GAP_MS = 3_600_000

# Prompts that are real human input and are not a request: they resume work
# rather than state any. Excluded from the default dataset and counted, because
# "the operator said continue" is a different observation from "no prompt".
STATUS_ONLY = frozenset({
    "continue", "go", "y", "yes", "n", "no", "ok", "okay", "next", "more",
    "status", "ls", "stop", "wait", "resume", "proceed", "again", "retry",
})

# A prompt shorter than this states no task even when it is not a known status
# word. Deliberately small: 40 characters was tried and is the 25th percentile
# of real prompts, so it removed ordinary work.
MIN_TASK_CHARS = 12

_DURATION = re.compile(r"^(\d+)([dhw])$")
_UNIT_MS = {"h": 3_600_000, "d": 86_400_000, "w": 604_800_000}


def parse_since(value: str | None) -> int | None:
    """Turn `30d` into milliseconds before now, or None for all time.

    A relative window rather than a date because the question is almost always
    "recent work", and a date in a saved command goes stale silently.
    """
    if not value:
        return None
    match = _DURATION.match(value.strip().lower())
    if not match:
        raise ValueError(f"--since must look like 30d, 12h, or 2w; got {value!r}")
    return int(match.group(1)) * _UNIT_MS[match.group(2)]


def _is_status_only(text: str) -> bool:
    stripped = text.strip().strip(".!?").casefold()
    return stripped in STATUS_ONLY or len(text.strip()) < MIN_TASK_CHARS


def published_stores(store_root: Path) -> list[tuple[str, Path]]:
    """Every current store, as `(project_id, path)`."""
    found: list[tuple[str, Path]] = []
    for pointer in sorted((store_root / "projects").glob("*/current.json")):
        try:
            snapshot = json.loads(pointer.read_text(encoding="utf-8")).get("path")
        except (OSError, ValueError):
            continue
        if not snapshot or not Path(snapshot).is_dir():
            continue
        found.extend(
            (pointer.parent.name, database)
            for database in sorted(Path(snapshot).glob("*.db"))
        )
    return found


def _session_rows(
    conn: sqlite3.Connection, surface: str, cutoff: int | None,
) -> list[sqlite3.Row]:
    """Every classified message Event, in Session order.

    Selects on the common classification rather than on the vendor's envelope:
    a `user` record carrying a tool result is not a prompt, and `actor_kind`
    is the column that already says so.
    """
    clause = ["e.event_kind IN ('message.prompt', 'message.response')"]
    parameters: list[Any] = []
    if surface != "any":
        clause.append("(s.surface_kind = ? OR s.surface_kind IS NULL)")
        parameters.append(surface)
    if cutoff is not None:
        clause.append("e.event_at >= ?")
        parameters.append(cutoff)
    # The clause is assembled from the fixed literals above and every value is
    # a bound parameter; nothing here interpolates caller input.
    return list(conn.execute(
        "SELECT e.session_id, e.sequence_no, e.event_at, e.event_kind, "  # noqa: S608
        "  e.actor_kind, e.content, e.content_len, "
        "  s.source_system_id, s.surface_kind "
        "FROM events e JOIN sessions s ON s.id = e.session_id "
        f"WHERE {' AND '.join(clause)} "
        "ORDER BY e.session_id, e.sequence_no",
        parameters,
    ))


def extract(
    store_root: Path,
    *,
    surface: str = "cli",
    since_ms: int | None = None,
    bout_gap_ms: int = DEFAULT_BOUT_GAP_MS,
    keep_status_only: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return `(exchanges, counts)`; counts explain every exclusion."""
    import time

    cutoff = int(time.time() * 1000) - since_ms if since_ms else None
    exchanges: list[dict[str, Any]] = []
    counts = {
        "prompts_seen": 0, "excluded_status_only": 0,
        "excluded_not_human": 0, "sessions": 0, "bouts": 0,
    }

    for project_id, database in published_stores(store_root):
        conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = _session_rows(conn, surface, cutoff)
        except sqlite3.Error:
            continue
        finally:
            conn.close()

        session_id = None
        bout = 0
        last_at: int | None = None
        pending: dict[str, Any] | None = None
        for row in rows:
            if row["session_id"] != session_id:
                if pending:
                    exchanges.append(pending)
                pending = None
                session_id = row["session_id"]
                bout = 0
                last_at = None
                counts["sessions"] += 1
                counts["bouts"] += 1

            if row["event_kind"] == "message.prompt":
                counts["prompts_seen"] += 1
                if row["actor_kind"] != "human":
                    # A harness-generated prompt: a context injection or a task
                    # notification wearing a `user` envelope.
                    counts["excluded_not_human"] += 1
                    continue
                text = str(row["content"] or "")
                if not keep_status_only and _is_status_only(text):
                    counts["excluded_status_only"] += 1
                    continue
                at = row["event_at"]
                if (
                    at is not None and last_at is not None
                    and at - last_at > bout_gap_ms
                ):
                    bout += 1
                    counts["bouts"] += 1
                if at is not None:
                    last_at = at
                if pending:
                    exchanges.append(pending)
                pending = {
                    "project_id": project_id,
                    "vendor": row["source_system_id"],
                    "surface": row["surface_kind"],
                    "session_id": row["session_id"],
                    "bout": bout,
                    "sequence_no": row["sequence_no"],
                    "prompt_at": at,
                    "prompt": text,
                    "prompt_chars": row["content_len"] or len(text),
                    "reply_chars": 0,
                    "replies": 0,
                    "reply": "",
                    # Stated on every row: the pairing follows Session sequence,
                    # which is evidence of order and not proof of causality.
                    "pairing": "derived_from_sequence",
                }
            elif pending is not None and row["actor_kind"] == "model":
                pending["replies"] += 1
                pending["reply_chars"] += row["content_len"] or len(
                    str(row["content"] or ""),
                )
                if not pending["reply"]:
                    pending["reply"] = str(row["content"] or "")
                if row["event_at"] is not None:
                    last_at = row["event_at"]
        if pending:
            exchanges.append(pending)
    return exchanges, counts


def _write_jsonl(rows: list[dict[str, Any]], out: Path, counts: dict[str, Any]) -> None:
    with out.open("w", encoding="utf-8") as stream:
        # A header record, so the file states its own provenance and filters.
        stream.write(json.dumps({"record": "header", **counts}) + "\n")
        for row in rows:
            stream.write(json.dumps({"record": "exchange", **row}) + "\n")


_CSV_FIELDS = (
    "project_id", "vendor", "surface", "session_id", "bout", "sequence_no",
    "prompt_at", "prompt_chars", "replies", "reply_chars", "pairing", "prompt",
)


def _write_csv(rows: list[dict[str, Any]], out: Path, counts: dict[str, Any]) -> None:
    with out.open("w", encoding="utf-8", newline="") as stream:
        stream.write(f"# {json.dumps(counts)}\n")
        writer = csv.DictWriter(
            stream, fieldnames=_CSV_FIELDS, extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **row,
                # One line per row: an embedded newline turns one record into
                # several for every reader that splits on them first.
                "prompt": " ".join(str(row["prompt"]).split())[:400],
            })


def _write_dialog(rows: list[dict[str, Any]], out: Path, counts: dict[str, Any]) -> None:
    """Labelled, newline-delimited transcript with a header."""
    lines = [
        "# Codess dialog extract",
        f"# {json.dumps(counts)}",
        "# HUMAN and MODEL lines are paired by Session sequence, which is",
        "# evidence of order rather than proof of causality.",
        "",
    ]
    current: tuple[str, int] | None = None
    for row in rows:
        marker = (row["session_id"], row["bout"])
        if marker != current:
            current = marker
            lines.append(
                f"=== session {row['session_id'][:12]} bout {row['bout']} "
                f"({row['vendor']}) ===",
            )
        lines.append(f"HUMAN: {' '.join(str(row['prompt']).split())}")
        if row["reply"]:
            lines.append(f"MODEL: {' '.join(str(row['reply']).split())}")
        lines.append("")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--store", dest="store_root", type=Path, default=STORE_ROOT,
        help="the machine's durable store (default: %(default)s)",
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="where to write the dataset",
    )
    parser.add_argument(
        "--format", choices=("jsonl", "csv", "dialog"), default="jsonl",
        help="output format (default: %(default)s)",
    )
    parser.add_argument(
        "--surface", choices=("cli", "ide", "api", "any"), default="cli",
        help="which invocation surface to admit; `api` is scripted "
             "(default: %(default)s)",
    )
    parser.add_argument(
        "--since", help="a relative window such as 30d, 12h, or 2w",
    )
    parser.add_argument(
        "--bout-gap-minutes", type=int, default=60,
        help="a longer gap between prompts starts a new bout "
             "(default: %(default)s)",
    )
    parser.add_argument(
        "--keep-status-only", action="store_true",
        help="admit `continue`, `go`, and other resume words",
    )
    args = parser.parse_args(argv)

    try:
        since_ms = parse_since(args.since)
    except ValueError as error:
        print(f"codess: {error}", file=sys.stderr)
        return 1

    rows, counts = extract(
        args.store_root.expanduser(),
        surface=args.surface,
        since_ms=since_ms,
        bout_gap_ms=args.bout_gap_minutes * 60_000,
        keep_status_only=args.keep_status_only,
    )
    counts = {
        **counts, "exchanges": len(rows), "surface": args.surface,
        "since": args.since or "all", "bout_gap_minutes": args.bout_gap_minutes,
    }
    writer = {
        "jsonl": _write_jsonl, "csv": _write_csv, "dialog": _write_dialog,
    }[args.format]
    writer(rows, args.out, counts)
    print(json.dumps(counts, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
