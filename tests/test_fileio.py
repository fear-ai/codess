"""Unit tests for codess.fileio's hash-verified read/write primitives."""

from __future__ import annotations

import hashlib

import pytest

from codess.fileio import (
    HashMismatchError,
    hash_file,
    read_hash,
    rewrite_hash,
    verify_hash,
    write_hash,
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_read_hash_returns_content_without_expected_hash(tmp_path):
    path = tmp_path / "value.txt"
    path.write_bytes(b"hello")
    assert read_hash(path) == b"hello"


def test_read_hash_accepts_matching_hash(tmp_path):
    path = tmp_path / "value.txt"
    path.write_bytes(b"hello")
    assert read_hash(path, expected_hash=_digest(b"hello")) == b"hello"


def test_read_hash_rejects_mismatched_hash(tmp_path):
    path = tmp_path / "value.txt"
    path.write_bytes(b"hello")
    with pytest.raises(HashMismatchError, match="hash mismatch"):
        read_hash(path, expected_hash=_digest(b"different"))


def test_read_hash_missing_file_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        read_hash(tmp_path / "missing.txt", expected_hash=_digest(b"x"))


def test_write_hash_writes_content_and_returns_matching_hash(tmp_path):
    path = tmp_path / "out.txt"
    digest = write_hash(path, b"payload")
    assert path.read_bytes() == b"payload"
    assert digest == _digest(b"payload")


def test_write_hash_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "out.txt"
    write_hash(path, b"payload")
    assert path.read_bytes() == b"payload"


def test_write_hash_leaves_no_temp_file_behind(tmp_path):
    path = tmp_path / "out.txt"
    write_hash(path, b"payload")
    leftovers = [p for p in tmp_path.iterdir() if p.name != "out.txt"]
    assert leftovers == []


def test_verify_hash_accepts_matching_hash(tmp_path):
    path = tmp_path / "value.txt"
    path.write_bytes(b"hello")
    verify_hash(path, _digest(b"hello"))  # does not raise


def test_verify_hash_rejects_mismatched_hash(tmp_path):
    path = tmp_path / "value.txt"
    path.write_bytes(b"hello")
    with pytest.raises(HashMismatchError, match="hash mismatch"):
        verify_hash(path, _digest(b"different"))


def test_verify_hash_matches_hash_file_for_large_content(tmp_path):
    path = tmp_path / "big.bin"
    content = b"x" * (2 * 1024 * 1024 + 17)  # spans multiple hash_file chunks
    path.write_bytes(content)
    verify_hash(path, hash_file(path))  # does not raise


def test_rewrite_hash_transforms_content_and_returns_new_hash(tmp_path):
    path = tmp_path / "doc.txt"
    old_hash = write_hash(path, b"old")
    new_hash = rewrite_hash(path, old_hash, lambda content: content.upper())
    assert path.read_bytes() == b"OLD"
    assert new_hash == _digest(b"OLD")


def test_rewrite_hash_refuses_stale_old_hash(tmp_path):
    path = tmp_path / "doc.txt"
    write_hash(path, b"old")
    with pytest.raises(HashMismatchError):
        rewrite_hash(path, _digest(b"not-the-real-old-content"), lambda c: c)
    assert path.read_bytes() == b"old"  # untouched


def test_no_hash_env_var_skips_read_hash_mismatch(tmp_path, monkeypatch):
    path = tmp_path / "value.txt"
    path.write_bytes(b"hello")
    monkeypatch.setenv("CODESS_NO_HASH", "1")
    assert read_hash(path, expected_hash=_digest(b"wrong")) == b"hello"


def test_no_hash_env_var_skips_verify_hash_mismatch(tmp_path, monkeypatch):
    path = tmp_path / "value.txt"
    path.write_bytes(b"hello")
    monkeypatch.setenv("CODESS_NO_HASH", "1")
    verify_hash(path, _digest(b"wrong"))  # does not raise


def test_no_hash_env_var_skips_rewrite_hash_old_check(tmp_path, monkeypatch):
    path = tmp_path / "doc.txt"
    write_hash(path, b"old")
    monkeypatch.setenv("CODESS_NO_HASH", "1")
    new_hash = rewrite_hash(
        path, _digest(b"not-the-real-old-content"), lambda c: c.upper()
    )
    assert path.read_bytes() == b"OLD"
    assert new_hash == _digest(b"OLD")


def test_no_hash_env_var_false_values_still_verify(tmp_path, monkeypatch):
    path = tmp_path / "value.txt"
    path.write_bytes(b"hello")
    monkeypatch.setenv("CODESS_NO_HASH", "0")
    with pytest.raises(HashMismatchError):
        read_hash(path, expected_hash=_digest(b"wrong"))


def test_read_exactly_stops_at_the_announced_size():
    """A file that grows during a read must not extend the read."""
    import io

    from codess.fileio import read_exactly

    stream = io.BytesIO(b"abcdefghij")
    assert b"".join(read_exactly(stream, 4, 2)) == b"abcd"

    short = io.BytesIO(b"abc")
    assert b"".join(read_exactly(short, 10, 2)) == b"abc"


# --- stat consistency -------------------------------------------------------
#
# One guard serves fingerprinting, which records the answer, and raw capture,
# which rejects on it. The classification is tested here; the two dispositions
# are tested at their own call sites.

def _stat_for(path, data: bytes, mtime_ns: int):
    """Write `data` and stamp a chosen modification time, then stat it."""
    import os

    path.write_bytes(data)
    os.utime(path, ns=(mtime_ns, mtime_ns))
    return path.stat()


def test_an_untouched_file_is_stable(tmp_path):
    from codess.fileio import stat_consistency

    before = _stat_for(tmp_path / "a", b"hello", 1_000_000_000)
    after = (tmp_path / "a").stat()
    assert stat_consistency(before, after) == "stable"


def test_a_file_that_only_grew_is_appended(tmp_path):
    """An appending session file is ordinary, not a fault."""
    from codess.fileio import stat_consistency

    path = tmp_path / "a"
    before = _stat_for(path, b"hello", 1_000_000_000)
    after = _stat_for(path, b"hello world", 2_000_000_000)
    assert stat_consistency(before, after) == "appended"


def test_a_file_that_shrank_is_rewritten(tmp_path):
    from codess.fileio import stat_consistency

    path = tmp_path / "a"
    before = _stat_for(path, b"hello world", 1_000_000_000)
    after = _stat_for(path, b"hi", 2_000_000_000)
    assert stat_consistency(before, after) == "rewritten"


def test_a_same_size_change_is_rewritten(tmp_path):
    """Equal size with a new mtime is a replacement, not an append."""
    from codess.fileio import stat_consistency

    path = tmp_path / "a"
    before = _stat_for(path, b"aaaaa", 1_000_000_000)
    after = _stat_for(path, b"bbbbb", 2_000_000_000)
    assert stat_consistency(before, after) == "rewritten"


def test_a_restored_stat_reads_as_stable(tmp_path):
    """The known limit: this guard cannot see a rewrite that restores both.

    Capture therefore also compares the bytes it read against the size it was
    promised; this test records that the cheap check alone is not sufficient.
    """
    from codess.fileio import stat_consistency

    path = tmp_path / "a"
    before = _stat_for(path, b"aaaaa", 1_000_000_000)
    after = _stat_for(path, b"bbbbb", 1_000_000_000)
    assert stat_consistency(before, after) == "stable"
