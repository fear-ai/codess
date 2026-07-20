"""Shared Claude/Codex source admission advances state only after commit."""

from codess.ingest_pipeline import inspect_sources, mark_source_complete


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
