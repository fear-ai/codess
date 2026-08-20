#!/usr/bin/env python3
"""Audit source-type, Actor, and decode coverage against ingested stores.

Decode is validated against real Sessions rather than fixtures, so the audit has to be
re-runnable over whatever a developer has locally.
This reports classification distributions, the pairings that should not
co-occur, and the coverage of tool, model, context, and compaction decode.

It reports counts, classifications, and record shapes -- never message,
prompt, argument, or result content. A finding names a source record type or
a field, so it can be acted on without reproducing what the Session said.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codess.schema_contract import table_names
from codess.store import connect, table_counts

STORE_FILES = {
    "Claude": "sessions_cc.db",
    "Codex": "sessions_codex.db",
    "Cursor": "sessions_cursor.db",
}

VOCABULARIES = ("actor_kind", "content_role", "origin_kind", "event_kind")

INCONSISTENT_PAIRINGS = (
    (
        "tool_actor_without_tool_role",
        "SELECT COUNT(*) FROM events WHERE actor_kind='tool' "
        "AND content_role NOT LIKE 'tool%'",
        "A tool Actor carries a tool request or result, never a prompt or response.",
    ),
    (
        "model_actor_with_tool_result",
        "SELECT COUNT(*) FROM events WHERE actor_kind='model' "
        "AND content_role='tool_result'",
        "A result is produced by the tool, not by the model that called it.",
    ),
    (
        "user_input_from_non_human",
        "SELECT COUNT(*) FROM events WHERE origin_kind='direct_user_input' "
        "AND actor_kind<>'human'",
        "Direct user input has a human Actor by definition.",
    ),
    (
        "model_output_from_non_model",
        "SELECT COUNT(*) FROM events WHERE origin_kind='model_generated' "
        "AND actor_kind<>'model'",
        "Model-generated content has a model Actor by definition.",
    ),
    (
        "unclassified_events",
        "SELECT COUNT(*) FROM events WHERE actor_kind IS NULL "
        "OR content_role IS NULL OR origin_kind IS NULL",
        "Every admitted Event states its Actor, role, and origin.",
    ),
    (
        "relation_without_a_parent",
        "SELECT COUNT(*) FROM sessions WHERE session_relation_kind IS NOT NULL "
        "AND parent_session_id IS NULL",
        "A Session related to another names which one; the relation and its "
        "evidence travel together.",
    ),
    (
        "parent_without_a_relation",
        "SELECT COUNT(*) FROM sessions WHERE parent_session_id IS NOT NULL "
        "AND session_relation_kind IS NULL",
        "A recorded parent states how the two Sessions relate.",
    ),
    (
        "self_parenting_session",
        "SELECT COUNT(*) FROM sessions WHERE parent_session_id = id",
        "A Session is not its own parent.",
    ),
    (
        "invocation_kind_disagrees_with_evidence",
        "SELECT COUNT(*) FROM tool_invocations WHERE "
        "(invocation_kind='model_requested') <> (requested_event_id IS NOT NULL)",
        "The kind is derived from whether a request record exists, so it "
        "cannot disagree with one.",
    ),
)


def _distribution(conn, column: str) -> dict[str, int]:
    return {
        str(row[0] if row[0] is not None else "[NULL]"): int(row[1])
        for row in conn.execute(
            f"SELECT {column}, COUNT(*) FROM events GROUP BY 1 ORDER BY 2 DESC"
        )
    }


def _relations(conn) -> dict[str, object]:
    """How Sessions relate to one another, and how completely.

    Delegated and forked Sessions are the evidence a reader follows to
    reconstruct agent work, so an unresolvable parent is a decode gap rather
    than a presentation detail.
    """
    total = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    with_parent = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE parent_session_id IS NOT NULL"
    ).fetchone()[0]
    resolvable = conn.execute(
        "SELECT COUNT(*) FROM sessions s WHERE s.parent_session_id IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM sessions p WHERE p.id = s.parent_session_id)"
    ).fetchone()[0]
    return {
        "sessions": total,
        "with_parent": with_parent,
        # A parent outside this store is ordinary -- a delegated Session can
        # live in another vendor's store set -- so this is reported rather
        # than treated as an inconsistency.
        "parent_present_in_store": resolvable,
        "parent_absent_from_store": with_parent - resolvable,
        "kinds": {
            str(row[0] or "[none]"): int(row[1])
            for row in conn.execute(
                "SELECT session_relation_kind, COUNT(*) FROM sessions "
                "GROUP BY 1 ORDER BY 2 DESC"
            )
        },
    }


def _context_events(conn) -> dict[str, int]:
    """Compaction, injection, and rollback Events, by kind.

    These are what a reader consults to explain a Session whose earlier
    content was replaced, so their absence where a vendor records them is a
    decode gap that no other count reveals.
    """
    return {
        str(row[0]): int(row[1])
        for row in conn.execute(
            "SELECT event_kind, COUNT(*) FROM events "
            "WHERE event_kind LIKE 'context%' GROUP BY 1 ORDER BY 1"
        )
    }


def _linkage(conn) -> dict[str, object]:
    """How completely tool and model evidence is joined to what produced it."""
    present = table_names(conn)
    report: dict[str, object] = {}
    if {"tool_invocations", "tool_results"} <= present:
        results = conn.execute("SELECT COUNT(*) FROM tool_results").fetchone()[0]
        linked = conn.execute(
            "SELECT COUNT(*) FROM tool_results WHERE invocation_id IS NOT NULL"
        ).fetchone()[0]
        report["tool"] = {
            "invocations": conn.execute(
                "SELECT COUNT(*) FROM tool_invocations"
            ).fetchone()[0],
            "results": results,
            "results_linked": linked,
            "results_unlinked": results - linked,
            "status": {
                str(row[0] or "[unknown]"): int(row[1])
                for row in conn.execute(
                    "SELECT normalized_status, COUNT(*) FROM tool_results "
                    "GROUP BY 1 ORDER BY 2 DESC"
                )
            },
        }
    if "model_turns" in present:
        turns = conn.execute("SELECT COUNT(*) FROM model_turns").fetchone()[0]
        configured = conn.execute(
            "SELECT COUNT(*) FROM model_turns WHERE model_param_id IS NOT NULL"
        ).fetchone()[0]
        report["model"] = {
            "turns": turns,
            "turns_with_configuration": configured,
            "turns_without_configuration": turns - configured,
            "configurations": conn.execute(
                "SELECT COUNT(*) FROM model_params"
            ).fetchone()[0],
        }
    return report


def audit_store(path: Path) -> dict[str, object]:
    """Report classification and decode coverage for one store."""
    conn = connect(path, read_only=True)
    try:
        report: dict[str, object] = {
            "store": path.name,
            "counts": table_counts(conn, ("sessions", "events")),
            "vocabularies": {
                column: _distribution(conn, column) for column in VOCABULARIES
            },
            "linkage": _linkage(conn),
            "relations": _relations(conn),
            "context": _context_events(conn),
        }
        inconsistencies = {}
        for name, query, why in INCONSISTENT_PAIRINGS:
            count = conn.execute(query).fetchone()[0]
            if count:
                inconsistencies[name] = {"count": count, "expectation": why}
        report["inconsistencies"] = inconsistencies
        if "mapping_diagnostics" in table_names(conn):
            report["diagnostics"] = {
                f"{row[0]}/{row[1]}": int(row[2])
                for row in conn.execute(
                    "SELECT reason_code, granularity, COUNT(*) FROM mapping_diagnostics "
                    "GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20"
                )
            }
        return report
    finally:
        conn.close()


def audit_project(project: Path) -> dict[str, object]:
    """Report every vendor store a Project holds."""
    base = project.expanduser().resolve() / ".codess"
    stores = [
        (vendor, base / name)
        for vendor, name in STORE_FILES.items()
        if (base / name).exists()
    ]
    return {
        "project": str(project.expanduser().resolve()),
        "stores": {vendor: audit_store(path) for vendor, path in stores},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir", action="append", dest="dirs", required=True,
        help="Project root holding a .codess store set; repeatable",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    report = {
        "format": "codess.decode-audit/1",
        "boundary": "counts, classifications, and record shapes only; no content",
        "projects": [audit_project(Path(value)) for value in args.dirs],
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    inconsistent = sum(
        len(store["inconsistencies"])
        for project in report["projects"]
        for store in project["stores"].values()
    )
    return 1 if inconsistent else 0


if __name__ == "__main__":
    raise SystemExit(main())
