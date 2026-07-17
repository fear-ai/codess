from pathlib import Path

import pytest

from codess.resources import ResourceLimitError, check_events, check_source, peak_rss_bytes


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
