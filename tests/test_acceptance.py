"""A14 / D17: value-level acceptance gate."""

from __future__ import annotations

from codess import acceptance, field_state
from codess.store import connect, init_db, replace_session_events


def test_matching_rows_accept():
    prior = {"entity_id": "g1", "content": "hello", "tool_name": "Bash"}
    rebuilt = dict(prior)
    rows = acceptance.compare_row(prior, rebuilt, prior)
    verdict = acceptance.accept(rows)
    assert verdict["accepted"]
    assert verdict["match_count"] == 3


def test_non_critical_mismatch_is_advisory_not_fatal():
    prior = {"entity_id": "g1", "tool_name": "Bash"}
    rebuilt = {"entity_id": "g1", "tool_name": "Shell"}  # non-critical differs
    rows = acceptance.compare_row(prior, rebuilt, prior)
    verdict = acceptance.accept(rows)
    assert verdict["accepted"]  # tool_name is not a critical field
    assert verdict["advisory_count"] == 1


def test_critical_mismatch_is_fatal():
    prior = {"entity_id": "g1", "sequence_no": 5}
    rebuilt = {"entity_id": "g1", "sequence_no": 6}  # ordering differs
    rows = acceptance.compare_row(prior, rebuilt, prior)
    verdict = acceptance.accept(rows)
    assert not verdict["accepted"]
    assert verdict["fatal"][0]["field"] == "sequence_no"


def test_vacant_side_is_advisory_on_noncritical_field():
    prior = {"entity_id": "g1", "tool_name": "Bash"}
    rebuilt = {"entity_id": "g1", "tool_name": None}  # rebuilt vacant
    rows = acceptance.compare_row(prior, rebuilt, prior)
    verdict = acceptance.accept(rows)
    row = next(r for r in rows if r["field"] == "tool_name")
    assert row["outcome"] == field_state.VACANT
    assert verdict["accepted"]  # non-critical vacancy does not block


def test_vacant_critical_field_is_fatal():
    prior = {"entity_id": "g1"}
    rebuilt = {"entity_id": None}  # identity went vacant
    rows = acceptance.compare_row(prior, rebuilt, ["entity_id"])
    verdict = acceptance.accept(rows)
    assert not verdict["accepted"]
    assert verdict["fatal"][0]["outcome"] == field_state.VACANT


def test_vacant_precedence_over_mismatch_at_gate():
    # A vacant side reports `vacant`, not `mismatch`, even though values differ.
    prior = {"content": "real"}
    rebuilt = {"content": ""}  # empty -> vacant
    rows = acceptance.compare_row(prior, rebuilt, ["content"])
    assert rows[0]["outcome"] == field_state.VACANT


def _snapshot_store(path, *, sequence_no=1):
    init_db(path)
    conn = connect(path)
    replace_session_events(
        conn,
        {
            "id": "s1", "source": "Codex",
            "project_id": "codess:project:fixture",
            "project_path": "/fixture",
        },
        [{
            "session_id": "s1", "event_id": "e1",
            "sequence_no": sequence_no,
            "event_type": "user_message", "role": "user",
            "content": "hello",
        }],
        session_id="s1",
    )
    if sequence_no != 1:
        conn.execute(
            "UPDATE events SET sequence_no=? WHERE session_id='s1'",
            (sequence_no,),
        )
    conn.commit()
    conn.close()


def test_snapshot_value_gate_streams_canonical_rows(tmp_path):
    prior = tmp_path / "prior" / "sessions_codex.db"
    rebuilt = tmp_path / "rebuilt" / "sessions_codex.db"
    _snapshot_store(prior)
    _snapshot_store(rebuilt)
    verdict = acceptance.compare_snapshots([prior], [rebuilt])
    assert verdict["accepted"]
    assert verdict["fatal_count"] == 0


def test_snapshot_value_gate_rejects_critical_order_change(tmp_path):
    prior = tmp_path / "prior" / "sessions_codex.db"
    rebuilt = tmp_path / "rebuilt" / "sessions_codex.db"
    _snapshot_store(prior, sequence_no=1)
    _snapshot_store(rebuilt, sequence_no=2)
    verdict = acceptance.compare_snapshots([prior], [rebuilt])
    assert not verdict["accepted"]
    assert any(row["field"] == "sequence_no" for row in verdict["fatal"])
