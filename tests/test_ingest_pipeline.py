"""Shared Claude/Codex source admission advances state only after commit."""

import pytest

from codess.ingest_pipeline import (
    commit_source_replacement,
    inspect_sources,
    mark_source_complete,
)
from codess.store import connect, init_db


def test_source_admission_distinguishes_small_changed_and_unchanged(tmp_path):
    small = tmp_path / "small.jsonl"
    small.write_bytes(b"x")
    source = tmp_path / "source.jsonl"
    source.write_bytes(b"payload")
    state = tmp_path / "state.json"

    first = list(inspect_sources(
        [small, source], state_path=state, force=False, min_size=2,
        max_source_bytes=1024,
    ))
    assert first[0].skip_reason == "below_minimum_size"
    assert first[1].skip_reason is None and first[1].error is None

    mark_source_complete(state, source)
    second = list(inspect_sources(
        [source], state_path=state, force=False, min_size=0,
        max_source_bytes=1024,
    ))
    assert second[0].skip_reason == "unchanged"


def test_source_admission_returns_typed_limit_error(tmp_path):
    source = tmp_path / "source.jsonl"
    source.write_bytes(b"too large")
    result = next(inspect_sources(
        [source], state_path=tmp_path / "state.json", force=False, min_size=0,
        max_source_bytes=2,
    ))
    assert result.error is not None
    assert result.skip_reason is None


def test_shared_source_replacement_rolls_back_related_failure(tmp_path):
    store = tmp_path / "sessions.db"
    init_db(store)

    def fail_after_replace(_conn):
        raise RuntimeError("related observation failed")

    with pytest.raises(RuntimeError, match="related observation"):
        commit_source_replacement(
            store,
            session={
                "id": "s1", "source": "Codex", "type": "Code",
                "project_path": str(tmp_path),
            },
            events=[{
                "session_id": "s1", "event_id": "e1",
                "event_type": "user_message", "subtype": "prompt",
                "role": "user", "content": "must roll back",
            }],
            session_id="s1",
            after_replace=fail_after_replace,
        )

    with connect(store, read_only=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
