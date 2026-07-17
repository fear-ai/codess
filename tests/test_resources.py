from pathlib import Path

import pytest

from codess.resources import (
    ResourceLimitError, check_events, check_source, file_usage,
    peak_rss_bytes, storage_usage, tree_usage,
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
    with pytest.raises(ResourceLimitError, match="session produced"):
        check_events({"s": [{}, {}]}, max_source=3, max_session=1)
    peak = peak_rss_bytes()
    assert peak is None or peak > 0


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
