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

# Diagnostic levels, ordered by what a reader does about them. `source` and
# `record` mean something was not mapped; `field` means a record was mapped
# with a value missing. Conflating the two overstates loss, which is why the
# report separates them rather than summing.
_LOSS_LEVELS = ("source", "record")


def _counts_by(conn: sqlite3.Connection, column: str, where: str = "") -> dict[str, int]:
    """Count `mapping_diagnostics` rows grouped by one column.

    The column is resolved against the live store before it reaches the SQL,
    so a rename fails here naming the column rather than returning an empty
    report from a query that no longer matches anything (CoPlan W52 step 2).
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

    Split by diagnostic level rather than summed: a source or record
    diagnostic means something did not become an Event, while a field
    diagnostic means an Event exists with a value missing. Adding them would
    report a Project as lossier than it is.
    """
    if "mapping_diagnostics" not in table_names(conn):
        return {"available": False}
    by_level = _counts_by(conn, "level")
    return {
        "available": True,
        "by_level": by_level,
        "unmapped_records": {
            level: by_level.get(level, 0) for level in _LOSS_LEVELS
        },
        # A zero here currently means "not recorded", not "did not happen": nothing
        # writes a source or record diagnostic yet, so record-level loss is unmeasured
        # rather than absent. Stated so a reader does not take the zero as evidence.
        "record_loss_recorded": any(
            by_level.get(level, 0) for level in _LOSS_LEVELS
        ),
        "by_reason": _counts_by(conn, "reason_code"),
        "record_level_reasons": _counts_by(
            conn, "reason_code",
            where="level IN ('source', 'record')",
        ),
    }


def store_coverage(conn: sqlite3.Connection) -> dict[str, Any]:
    """Coverage, shapes, and loss for one vendor store."""
    return {
        "coverage": mapped_coverage(conn),
        "shapes": source_record_shapes(conn),
        "loss": loss(conn),
    }
