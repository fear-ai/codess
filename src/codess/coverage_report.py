"""What one ingest mapped, what it did not, and what it could not name.

A result a reader can challenge has to state what it *missed*, not only what
it found. This derives that from a published store rather than from run-time
counters, for two reasons.

**Counters are a report of the run; a store is a report of the evidence.**
The ingest command prints eleven diagnostic counts to stderr and discards
them. They cannot be queried later, cannot be compared between runs, and
answer questions about one process rather than about the Project. A reader
asking "what did Codess fail to map here" cannot be told to re-run ingest and
watch the terminal.

**A hand-written list drifts.** Those eleven counts were an f-string naming
each counter, while adapters produce twenty-one; ten were produced and never
reported, and one reported name no longer existed. Deriving the report from
what the store holds removes the second list that has to be kept in step.

Reports counts, reason codes, and record types -- never message, prompt,
argument, or result content, so a coverage figure can be published alongside
a result without republishing the Session.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from codess.fileio import quote_identifier
from codess.schema_contract import (
    SchemaContractError,
    column_names,
    table_names,
)

# The granularities that mean something was not mapped. `source` and `record`
# mean a whole input did not become an Event; `field` means an Event exists with
# a value missing. Conflating the two overstates loss, which is why the report
# separates them rather than summing -- and is why the column is named
# `granularity` rather than `level`, which reads as an ordering that could be
# summed.
_LOSS_GRANULARITIES = ("source", "record")


def _counts_by(conn: sqlite3.Connection, column: str, where: str = "") -> dict[str, int]:
    """Count `mapping_diagnostics` rows grouped by one column.

    The column is resolved against the live store before it reaches the SQL,
    so a rename fails here naming the column rather than returning an empty
    report from a query that no longer matches anything.
    """
    if column not in column_names(conn, "mapping_diagnostics"):
        raise SchemaContractError(
            f"mapping_diagnostics has no column {column!r}; "
            "the released DDL and this report disagree"
        )
    clause = f" WHERE {where}" if where else ""
    return {
        str(row[0] if row[0] is not None else "[none]"): int(row[1])
        for row in conn.execute(
            f"SELECT {quote_identifier(column)}, COUNT(*) FROM mapping_diagnostics{clause} "  # noqa: S608
            "GROUP BY 1 ORDER BY 2 DESC"
        )
    }


def mapped_coverage(conn: sqlite3.Connection) -> dict[str, Any]:
    """How much of what was read became a classified Event.

    `admitted` counts Events in the store. `unmapped` counts Events whose
    common classification is absent -- a record that arrived and was stored
    without Codess being able to say what it is, which is the honest
    denominator for "coverage" and is distinct from a record that was never
    admitted at all.
    """
    admitted = int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    unmapped = int(
        conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_kind IS NULL "
            "OR actor_kind IS NULL OR content_role IS NULL OR origin_kind IS NULL"
        ).fetchone()[0]
    )
    return {
        "admitted_events": admitted,
        "unclassified_events": unmapped,
        "classified_events": admitted - unmapped,
        # Reported as a ratio a reader can compare between Projects; the
        # counts are given so the ratio can be recomputed rather than trusted.
        "classified_ratio": (
            round((admitted - unmapped) / admitted, 6) if admitted else None
        ),
    }


def source_record_shapes(conn: sqlite3.Connection) -> dict[str, Any]:
    """Which vendor record types were seen, and how many of each.

    This is the shape inventory a reader consults when a vendor changes its
    format: a type appearing here that no mapping profile names is an
    unknown shape, and a type that stops appearing is evidence of a vendor
    change rather than of a decoder fault.
    """
    return {
        "by_source_record_type": {
            str(row[0] if row[0] is not None else "[none]"): int(row[1])
            for row in conn.execute(
                "SELECT source_record_type, COUNT(*) FROM events "
                "GROUP BY 1 ORDER BY 2 DESC"
            )
        },
        "by_mapping_rule": {
            str(row[0] if row[0] is not None else "[none]"): int(row[1])
            for row in conn.execute(
                "SELECT mapping_rule, COUNT(*) FROM events GROUP BY 1 ORDER BY 2 DESC"
            )
        },
    }


def loss(conn: sqlite3.Connection) -> dict[str, Any]:
    """What was read and not fully carried across, by reason.

    Split by diagnostic granularity rather than summed: a source or record
    diagnostic means something did not become an Event, while a field
    diagnostic means an Event exists with a value missing. Adding them would
    report a Project as lossier than it is.
    """
    if "mapping_diagnostics" not in table_names(conn):
        return {"available": False}
    by_granularity = _counts_by(conn, "granularity")
    return {
        "available": True,
        "by_granularity": by_granularity,
        "unmapped_records": {
            name: by_granularity.get(name, 0) for name in _LOSS_GRANULARITIES
        },
        # Adapters now write record-level diagnostics when they refuse a
        # record, so a zero here is evidence rather than silence -- but
        # only for the refusals that are routed. The flag stays so a reader
        # can tell a measured zero from a store written before that landed.
        "record_loss_recorded": any(
            by_granularity.get(name, 0) for name in _LOSS_GRANULARITIES
        ),
        "by_reason": _counts_by(conn, "reason_code"),
        "record_level_reasons": _counts_by(
            conn, "reason_code",
            where="granularity IN ('source', 'record')",
        ),
    }


def undecoded_evidence(source_system_id: str | None) -> dict[str, Any]:
    """Retained vendor evidence Codess located and deliberately did not decode.

    Loss has two shapes and the report was only carrying one. `loss()` measures
    what a decoder read and could not fully map -- a refused record, an
    incomplete field. This measures a different thing: evidence a vendor
    retained, in a container Codess knows about, that no adapter admits at all.
    A store cannot report it, because the whole point is that nothing was
    written -- so a report derived only from the store states zero by
    construction, which is the unfalsifiable zero record-level diagnostics removed elsewhere.

    Codex is the one vendor with a measured instance. `~/.codex/history.jsonl`
    records human prompts keyed by Session, and a Session can appear there with
    no rollout: measured on one machine, 19 history Sessions, 18 with rollouts,
    one without carrying 2 prompts. Admitting it would mean a Session with
    prompts and no Model Turns, which changes what a Session is and is a mapping
    decision under 6.5. Reporting it is the honest middle path.

    Keyed by `source_system_id` so a store's own report names only its vendor,
    and returns `available: False` for a vendor with nothing of this kind rather
    than omitting the key, so a reader can tell "measured, none" from
    "not measured".
    """
    if source_system_id != "openai.codex":
        return {"available": False, "reason": "no undecoded container measured"}
    from codess.codex_source import unrolled_history_sessions

    measured = unrolled_history_sessions()
    if not measured.get("available"):
        return {"available": False, "reason": "history container absent"}
    return {
        "available": True,
        "container": "history.jsonl",
        "sessions": measured["history_sessions"],
        "with_rollout": measured["with_rollout"],
        # The figure a reader wants: Sessions whose only local evidence is a
        # container no adapter decodes.
        "undecodable_sessions": measured["without_rollout"],
        "undecodable_prompts": sum(measured["unrolled_prompt_counts"].values()),
        "disposition": "reported, not admitted",
    }


def _store_source_system(conn: sqlite3.Connection) -> str | None:
    """Which vendor this store holds, from its own rows."""
    if "sessions" not in table_names(conn):
        return None
    row = conn.execute(
        "SELECT source_system_id FROM sessions LIMIT 1"
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def store_coverage(conn: sqlite3.Connection) -> dict[str, Any]:
    """Coverage, shapes, and loss for one vendor store.

    `undecoded` is measured from the vendor container rather than the store,
    which is why it is resolved here rather than inside `loss`: a store is a
    report of what was mapped, and evidence nothing mapped leaves no row.
    """
    return {
        "coverage": mapped_coverage(conn),
        "shapes": source_record_shapes(conn),
        "loss": loss(conn),
        "undecoded": undecoded_evidence(_store_source_system(conn)),
    }
