"""A14 / D17: value-level acceptance gate."""

from __future__ import annotations

from codess import acceptance, field_state


def test_matching_rows_accept():
    prior = {"global_id": "g1", "content": "hello", "tool_name": "Bash"}
    rebuilt = dict(prior)
    rows = acceptance.compare_row(prior, rebuilt, prior)
    verdict = acceptance.accept(rows)
    assert verdict["accepted"]
    assert verdict["match_count"] == 3


def test_non_critical_mismatch_is_advisory_not_fatal():
    prior = {"global_id": "g1", "tool_name": "Bash"}
    rebuilt = {"global_id": "g1", "tool_name": "Shell"}  # non-critical differs
    rows = acceptance.compare_row(prior, rebuilt, prior)
    verdict = acceptance.accept(rows)
    assert verdict["accepted"]  # tool_name is not a critical field
    assert verdict["advisory_count"] == 1


def test_critical_mismatch_is_fatal():
    prior = {"global_id": "g1", "sequence_no": 5}
    rebuilt = {"global_id": "g1", "sequence_no": 6}  # ordering differs
    rows = acceptance.compare_row(prior, rebuilt, prior)
    verdict = acceptance.accept(rows)
    assert not verdict["accepted"]
    assert verdict["fatal"][0]["field"] == "sequence_no"


def test_vacant_side_is_advisory_on_noncritical_field():
    prior = {"global_id": "g1", "tool_name": "Bash"}
    rebuilt = {"global_id": "g1", "tool_name": None}  # rebuilt vacant
    rows = acceptance.compare_row(prior, rebuilt, prior)
    verdict = acceptance.accept(rows)
    row = next(r for r in rows if r["field"] == "tool_name")
    assert row["outcome"] == field_state.VACANT
    assert verdict["accepted"]  # non-critical vacancy does not block


def test_vacant_critical_field_is_fatal():
    prior = {"global_id": "g1"}
    rebuilt = {"global_id": None}  # identity went vacant
    rows = acceptance.compare_row(prior, rebuilt, ["global_id"])
    verdict = acceptance.accept(rows)
    assert not verdict["accepted"]
    assert verdict["fatal"][0]["outcome"] == field_state.VACANT


def test_vacant_precedence_over_mismatch_at_gate():
    # A vacant side reports `vacant`, not `mismatch`, even though values differ.
    prior = {"content": "real"}
    rebuilt = {"content": ""}  # empty -> vacant
    rows = acceptance.compare_row(prior, rebuilt, ["content"])
    assert rows[0]["outcome"] == field_state.VACANT
