"""Value-level acceptance gate (A14 / CoPlan D17).

Design and rationale: CoPlan D17/D18, Findings.md §4. Uses field_state for the
comparison outcome and criticality partition.
"""

from __future__ import annotations

from typing import Iterable

from codess import field_state

# Fields whose per-row divergence blocks promotion (identity / ordering / lineage).
CRITICAL_FIELDS = frozenset({
    "global_id", "observation_id", "event_id", "session_id",
    "sequence_no", "interaction_id", "model_turn_id",
    "parent_event_id", "caused_by_event_id", "source_call_id",
})


def compare_row(prior: dict, rebuilt: dict, fields: Iterable[str]) -> list[dict]:
    """Return one result per field: outcome (match/mismatch/vacant) + criticality."""
    results = []
    for field in fields:
        outcome = field_state.compare(prior.get(field), rebuilt.get(field))
        is_critical = field in CRITICAL_FIELDS
        if outcome == field_state.MATCH:
            crit = None
        else:
            # Both vacant and mismatch are non-present for criticality purposes.
            crit = field_state.criticality(outcome, is_critical_field=is_critical)
        results.append({
            "field": field,
            "outcome": outcome,
            "criticality": crit,
        })
    return results


def accept(rows: list[dict]) -> dict:
    """Aggregate compare_row results into an acceptance verdict.

    ``accepted`` is False iff any row is ``fatal``. Advisory outcomes (vacant or
    non-critical mismatch) are counted and reported, never blocking.
    """
    fatal = [r for r in rows if r.get("criticality") == field_state.FATAL]
    advisory = [r for r in rows if r.get("criticality") == field_state.ADVISORY]
    return {
        "accepted": not fatal,
        "fatal": fatal,
        "advisory_count": len(advisory),
        "match_count": sum(1 for r in rows if r.get("outcome") == field_state.MATCH),
    }
