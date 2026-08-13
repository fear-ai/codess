"""Value-level acceptance gate (A14 / CoPlan D17).

Design and rationale: CoPlan D17/D18, Findings.md §4. Uses field_state for the
comparison outcome and criticality partition.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import ExitStack
from itertools import zip_longest
from pathlib import Path

from codess import field_state
from codess.baseline_validation import canonical_rows
from codess.fileio import open_readonly
from codess.schema_contract import require_store

# Fields whose per-row divergence blocks promotion (identity / ordering / lineage).
CRITICAL_FIELDS = frozenset({
    "global_id", "observation_id", "event_id", "session_id",
    "sequence_no", "interaction_id", "model_turn_id",
    "parent_event_id", "caused_by_event_id", "source_call_id",
    "row_identity",
})


def compare_row(
    prior: dict,
    rebuilt: dict,
    fields: Iterable[str],
    *,
    context: dict | None = None,
) -> list[dict]:
    """Return one result per field: outcome (match/mismatch/vacant) + criticality."""
    results = []
    for field in fields:
        # Equal vacancy is stable, not a regression. ``field_state.compare``
        # deliberately reports vacancy whenever either side is absent; the
        # two-snapshot gate refines that rule so only one-sided vacancy blocks.
        outcome = (
            field_state.MATCH
            if prior.get(field) == rebuilt.get(field)
            else field_state.compare(prior.get(field), rebuilt.get(field))
        )
        is_critical = field in CRITICAL_FIELDS
        if outcome == field_state.MATCH:
            crit = None
        else:
            # Both vacant and mismatch are non-present for criticality purposes.
            crit = field_state.criticality(outcome, is_critical_field=is_critical)
        result = {
            "field": field,
            "outcome": outcome,
            "criticality": crit,
        }
        if context:
            result.update(context)
        results.append(result)
    return results


def accept(rows: Iterable[dict], *, example_limit: int = 100) -> dict:
    """Aggregate compare_row results into an acceptance verdict.

    ``accepted`` is False iff any row is ``fatal``. Advisory outcomes (vacant or
    non-critical mismatch) are counted and reported, never blocking.
    """
    fatal = []
    advisory = []
    fatal_count = advisory_count = match_count = 0
    for row in rows:
        if row.get("criticality") == field_state.FATAL:
            fatal_count += 1
            if len(fatal) < example_limit:
                fatal.append(row)
        elif row.get("criticality") == field_state.ADVISORY:
            advisory_count += 1
            if len(advisory) < example_limit:
                advisory.append(row)
        if row.get("outcome") == field_state.MATCH:
            match_count += 1
    return {
        "accepted": fatal_count == 0,
        "fatal": fatal,
        "fatal_count": fatal_count,
        "advisory": advisory,
        "advisory_count": advisory_count,
        "match_count": match_count,
        "examples_truncated": (
            fatal_count > len(fatal) or advisory_count > len(advisory)
        ),
    }


_OBSERVATION_TABLES = frozenset({
    "sources", "source_records", "source_record_content",
})
_NORMALIZED_SESSION_FIELDS = frozenset({"observation_id", "ended_at"})


def _open_tables(path: Path, stack: ExitStack) -> dict[str, Iterable[sqlite3.Row]]:
    conn = open_readonly(path)
    stack.callback(conn.close)
    conn.row_factory = sqlite3.Row
    require_store(conn, write=False)
    return dict(canonical_rows(conn))


def compare_snapshot_rows(
    prior_paths: Iterable[Path],
    rebuilt_paths: Iterable[Path],
    *,
    allow_source_revision_drift: bool = False,
) -> Iterator[dict]:
    """Yield bounded-memory field comparisons for two normalized snapshots.

    Store/table/row ordering comes from the same canonical projection used by
    semantic digests. When a policy permits source revision drift, raw source
    observation tables and the same volatile Session fields excluded from the
    normalization digest do not participate in this value gate.
    """
    prior = {path.name: path for path in prior_paths}
    rebuilt = {path.name: path for path in rebuilt_paths}
    for store_name in sorted(set(prior) | set(rebuilt)):
        with ExitStack() as stack:
            prior_tables = (
                _open_tables(prior[store_name], stack)
                if store_name in prior else {}
            )
            rebuilt_tables = (
                _open_tables(rebuilt[store_name], stack)
                if store_name in rebuilt else {}
            )
            for table in sorted(set(prior_tables) | set(rebuilt_tables)):
                if allow_source_revision_drift and table in _OBSERVATION_TABLES:
                    continue
                old_rows = prior_tables.get(table, ())
                new_rows = rebuilt_tables.get(table, ())
                for index, pair in enumerate(
                    zip_longest(old_rows, new_rows, fillvalue=None), 1
                ):
                    old, new = pair
                    old = {} if old is None else dict(old)
                    new = {} if new is None else dict(new)
                    context = {
                        "store": store_name,
                        "table": table,
                        "row": index,
                    }
                    # Missing rows are an identity vacancy even in tables
                    # without a column literally named global_id.
                    old_identity = (
                        f"{store_name}:{table}:{index}" if old else None
                    )
                    new_identity = (
                        f"{store_name}:{table}:{index}" if new else None
                    )
                    yield from compare_row(
                        {"row_identity": old_identity},
                        {"row_identity": new_identity},
                        ("row_identity",),
                        context=context,
                    )
                    fields = sorted(set(old) | set(new))
                    if allow_source_revision_drift and table == "sessions":
                        fields = [
                            field for field in fields
                            if field not in _NORMALIZED_SESSION_FIELDS
                        ]
                    yield from compare_row(old, new, fields, context=context)


def compare_snapshots(
    prior_paths: Iterable[Path],
    rebuilt_paths: Iterable[Path],
    *,
    allow_source_revision_drift: bool = False,
) -> dict:
    """Return the D17 verdict for two immutable snapshot store sets."""
    return accept(
        compare_snapshot_rows(
            prior_paths,
            rebuilt_paths,
            allow_source_revision_drift=allow_source_revision_drift,
        )
    )
