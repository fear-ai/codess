"""Bounded JSONL reading, including records caught mid-write."""

from __future__ import annotations

import pytest

from codess.bounded_jsonl import DEFAULT_MAX_RECORD_BYTES, iter_bounded_jsonl


def write(tmp_path, content: bytes):
    path = tmp_path / "session.jsonl"
    path.write_bytes(content)
    return path


def test_complete_records_are_yielded_in_order(tmp_path):
    path = write(tmp_path, b'{"a":1}\n{"b":2}\n')
    assert list(iter_bounded_jsonl(path)) == [
        (1, {"a": 1}, None),
        (2, {"b": 2}, None),
    ]


def test_unterminated_final_record_is_incomplete_not_malformed(tmp_path):
    """A vendor appending to an open session leaves the last record partial."""
    path = write(tmp_path, b'{"a":1}\n{"b":2}\n{"c":')
    results = list(iter_bounded_jsonl(path))
    assert results[:2] == [(1, {"a": 1}, None), (2, {"b": 2}, None)]
    assert results[2] == (3, None, "incomplete")


def test_incomplete_record_ends_iteration(tmp_path):
    """Nothing can follow an unterminated line, so reading stops there."""
    path = write(tmp_path, b'{"a":1}\n{"partial"')
    assert [reason for _, _, reason in iter_bounded_jsonl(path)] == [None, "incomplete"]


def test_a_record_completed_later_is_read_normally(tmp_path):
    """The same file re-read after the writer finishes yields the record."""
    path = write(tmp_path, b'{"a":1}\n{"b":')
    assert list(iter_bounded_jsonl(path))[-1] == (2, None, "incomplete")
    path.write_bytes(b'{"a":1}\n{"b":2}\n')
    assert list(iter_bounded_jsonl(path)) == [
        (1, {"a": 1}, None),
        (2, {"b": 2}, None),
    ]


def test_corrupt_record_between_valid_ones_is_malformed(tmp_path):
    """Terminated but unparseable is a different fault from unterminated."""
    path = write(tmp_path, b'{"a":1}\n{not json}\n{"b":2}\n')
    assert [reason for _, _, reason in iter_bounded_jsonl(path)] == [
        None, "malformed", None,
    ]


def test_non_object_record_is_reported(tmp_path):
    path = write(tmp_path, b'[1,2,3]\n')
    assert list(iter_bounded_jsonl(path)) == [(1, None, "non_object")]


def test_oversize_record_is_reported_and_skipped(tmp_path):
    path = write(tmp_path, b'{"a":"' + b"x" * 4096 + b'"}\n{"b":2}\n')
    results = list(iter_bounded_jsonl(path, max_record_bytes=1024))
    assert results[0] == (1, None, "oversize")
    assert results[-1][1] == {"b": 2}


def test_blank_lines_are_skipped_without_a_diagnostic(tmp_path):
    path = write(tmp_path, b'{"a":1}\n\n\n{"b":2}\n')
    assert [record for _, record, _ in iter_bounded_jsonl(path)] == [
        {"a": 1}, {"b": 2},
    ]


def test_empty_file_yields_nothing(tmp_path):
    assert list(iter_bounded_jsonl(write(tmp_path, b""))) == []


def test_record_bound_below_the_floor_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        list(iter_bounded_jsonl(write(tmp_path, b"{}\n"), max_record_bytes=512))


def test_default_bound_is_exposed_for_callers():
    assert DEFAULT_MAX_RECORD_BYTES >= 1024


def test_incomplete_record_is_warned_not_silent(tmp_path, caplog):
    """Skipping a record must be visible, since it means data was not read."""
    path = write(tmp_path, b'{"a":1}\n{"b":')
    with caplog.at_level("WARNING"):
        list(iter_bounded_jsonl(path))
    assert "incomplete" in caplog.text
