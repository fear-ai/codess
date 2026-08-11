from pathlib import Path

import pytest

from codess.ingest_sources import _append_bounded_event
from codess.context_content import bound_context_content
from codess.resources import (
    ResourceLimitError, check_events, check_source, file_usage,
    peak_rss_bytes, searchable_event_payload, storage_usage,
    summarize_event_payload, summarize_project_resources,
    summarize_resource_observations, tree_usage,
)


def test_source_and_event_limits_are_enforced(tmp_path: Path):
    source = tmp_path / "source"
    source.write_bytes(b"1234")
    assert check_source(source, 4) == 4
    with pytest.raises(ResourceLimitError, match="source size"):
        check_source(source, 3)
    try:
        check_source(source, 3)
    except ResourceLimitError as exc:
        assert (exc.limit_kind, exc.observed, exc.maximum) == ("source_bytes", 4, 3)
    assert check_events({"s": [{}, {}]}, max_source=2, max_session=2) == (2, 2)
    with pytest.raises(ResourceLimitError) as source_error:
        check_events(
            {"s1": [{}, {}], "s2": [{}]},
            max_source=2, max_session=2,
        )
    assert (
        source_error.value.limit_kind,
        source_error.value.observed,
        source_error.value.maximum,
    ) == ("source_events", 3, 2)
    with pytest.raises(ResourceLimitError, match="session produced"):
        check_events({"s": [{}, {}]}, max_source=3, max_session=1)
    peak = peak_rss_bytes()
    assert peak is None or peak > 0


def test_streaming_event_limit_rejects_before_buffer_growth():
    sessions: dict[str, list[dict]] = {}
    opts = {
        "max_events_per_source": 2,
        "max_events_per_session": 2,
    }
    total = _append_bounded_event(opts, sessions, "s", {"n": 1}, 0)
    total = _append_bounded_event(opts, sessions, "s", {"n": 2}, total)
    assert total == 2
    assert len(sessions["s"]) == 2

    with pytest.raises(ResourceLimitError) as error:
        _append_bounded_event(opts, sessions, "s", {"n": 3}, total)
    assert error.value.observed == 3
    assert len(sessions["s"]) == 2

    unlimited: dict[str, list[dict]] = {}
    assert _append_bounded_event(
        {
            "max_events_per_source": None,
            "max_events_per_session": None,
        },
        unlimited,
        "s",
        {},
        0,
    ) == 1


def test_context_character_boundary_and_override_are_exact():
    exact = "x" * 250_000
    assert bound_context_content(exact, {}) == (exact, 250_000, False)

    bounded, full_length, truncated = bound_context_content(exact + "x", {})
    assert len(bounded) == 250_000
    assert bounded.endswith("…")
    assert (full_length, truncated) == (250_001, True)

    # The unit is Unicode characters, not UTF-8 bytes.
    assert bound_context_content("ééé", {
        "max_context_content_chars": 2,
    }) == ("é…", 3, True)
    assert bound_context_content("unbounded", {
        "max_context_content_chars": None,
    }) == ("unbounded", 9, False)


def test_storage_usage_is_shared_and_hardlink_aware(tmp_path: Path):
    first = tmp_path / "first.bin"
    linked = tmp_path / "linked.bin"
    first.write_bytes(b"1234")
    linked.hardlink_to(first)

    measured = tree_usage(tmp_path)
    assert measured["files"] == 2
    assert measured["logical_bytes"] == 8
    assert measured["allocated_bytes"] >= measured["unique_allocated_bytes"]
    assert measured["unique_allocated_bytes"] > 0
    assert storage_usage([tmp_path]) == measured
    assert file_usage([first])["files"] == 1


def test_resource_summary_deduplicates_containers_and_never_sums_rss():
    summary = summarize_resource_observations([
        {
            "source": "cursor:a", "container": "/state.vscdb",
            "source_bytes": 100, "events": 3,
            "selected_input_bytes": 10,
            "retained_searchable_characters": 7,
            "retained_searchable_utf8_bytes": 8,
            "largest_session_events": 2, "peak_rss_bytes": 40,
        },
        {
            "source": "cursor:b", "container": "/state.vscdb",
            "source_bytes": 110, "events": 5,
            "selected_input_bytes": 20,
            "retained_searchable_characters": 11,
            "retained_searchable_utf8_bytes": 12,
            "largest_session_events": 4, "peak_rss_bytes": 60,
        },
        {
            "source": "claude:c", "container": "/c.jsonl",
            "source_bytes": 20, "events": 1,
            "retained_searchable_characters": 13,
            "retained_searchable_utf8_bytes": 14,
            "largest_session_events": 1, "peak_rss_bytes": 50,
        },
    ])
    assert summary == {
        "measurement_format": "codess.ingest-resource-summary/1",
        "observations": 3,
        "unique_source_containers": 2,
        "unique_source_container_bytes": 130,
        "selected_input_observations": 2,
        "unmeasured_selected_input_observations": 1,
        "selected_input_bytes": 30,
        "selected_input_complete": False,
        "emitted_events": 9,
        "retained_searchable_characters": 31,
        "retained_searchable_utf8_bytes": 34,
        "largest_session_events": 4,
        "peak_rss_bytes": 60,
    }


def test_project_resource_summary_separates_and_deduplicates_allocations(
    tmp_path: Path,
):
    store = tmp_path / "store.db"
    raw = tmp_path / "raw.zst"
    store.write_bytes(b"store")
    raw.write_bytes(b"raw")

    summary = summarize_project_resources(
        [{"selected_input_bytes": 0}],
        normalized_store_paths=[store],
        raw_object_paths=[raw, raw],
    )

    assert summary["selected_input_complete"] is True
    assert summary["selected_input_bytes"] == 0
    assert summary["normalized_store_usage"]["files"] == 1
    assert summary["normalized_store_usage"]["logical_bytes"] == 5
    assert summary["raw_object_usage"]["files"] == 1
    assert summary["raw_object_usage"]["logical_bytes"] == 3


def test_searchable_payload_distinguishes_characters_bytes_and_aliases():
    event = {
        "content": "é",
        "tool_input": "{}",
        "tool_output": "é",
        "artifact_path": "a",
        "metadata": "not searchable payload",
    }
    assert searchable_event_payload(event) == (4, 5)
    assert summarize_event_payload({
        "s1": [event, {"content": None, "tool_output": ""}],
        "s2": [{}],
    }) == (4, 5)


def test_equal_distinct_searchable_fields_are_not_treated_as_aliases():
    assert searchable_event_payload({
        "content": "x", "tool_input": "x", "artifact_path": "x",
    }) == (3, 3)
