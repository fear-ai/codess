"""Unit tests for codess.fileio's hash-verified read/write primitives."""

from __future__ import annotations

import hashlib
import sqlite3

import pytest

from codess.fileio import (
    HashMismatchError,
    hash_file,
    quote_identifier,
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


class TestFileState:
    """One shared answer to "has this file changed since we read it"."""

    def test_unchanged(self, tmp_path):
        from codess.fileio import file_state, file_unchanged

        path = tmp_path / "x"
        path.write_text("hello")
        assert file_unchanged(path, file_state(path))

    def test_edited(self, tmp_path):
        from codess.fileio import file_state, file_unchanged

        path = tmp_path / "x"
        path.write_text("hello")
        state = file_state(path)
        path.write_text("hello world")
        assert not file_unchanged(path, state)

    def test_replacement_with_matching_size_and_mtime(self, tmp_path):
        """Size and mtime alone miss a file replaced by rename: the replacement
        can carry the same length and a copied timestamp. The inode catches it."""
        import os

        from codess.fileio import file_state, file_unchanged

        path = tmp_path / "x"
        path.write_text("AAAAA")
        state = file_state(path)
        other = tmp_path / "y"
        other.write_text("BBBBB")
        os.utime(other, ns=(state["mtime_ns"], state["mtime_ns"]))
        other.replace(path)
        current = file_state(path)
        assert current["size"] == state["size"]
        assert current["mtime_ns"] == state["mtime_ns"]
        assert not file_unchanged(path, state)

    def test_missing_reads_as_changed(self, tmp_path):
        """A first observation and a vanished file both read as changed, which is
        the safe direction: the caller re-reads rather than trusting a comparison
        it could not make."""
        from codess.fileio import file_state, file_unchanged

        path = tmp_path / "x"
        path.write_text("hello")
        assert file_state(tmp_path / "absent") is None
        assert not file_unchanged(tmp_path / "absent", file_state(path))
        assert not file_unchanged(path, None)

    def test_changes_names_the_field(self, tmp_path):
        """A boolean says a file changed; this says how. "size 5 to 10" and
        "same size, new inode" are different findings, and a hash comparison
        flattens both to "differs"."""
        from codess.fileio import file_changes, file_state

        path = tmp_path / "x"
        path.write_text("AAAAA")
        state = file_state(path)
        assert file_changes(path, state) is None
        path.write_text("AAAAAAAAAA")
        assert file_changes(path, state)["size"] == (5, 10)

    def test_changes_isolates_a_replacement(self, tmp_path):
        from codess.fileio import file_changes, file_state

        path = tmp_path / "x"
        path.write_text("AAAAA")
        state = file_state(path)
        other = tmp_path / "y"
        other.write_text("BBBBB")
        import os

        os.utime(other, ns=(state["mtime_ns"], state["mtime_ns"]))
        other.replace(path)
        assert list(file_changes(path, state)) == ["inode"]

    def test_changes_unknown(self, tmp_path):
        """An unreadable or unrecorded file is neither unchanged nor an
        attributable difference."""
        from codess.fileio import file_changes, file_state

        path = tmp_path / "x"
        path.write_text("x")
        assert file_changes(path, None) == {}
        assert file_changes(tmp_path / "absent", file_state(path)) == {}


class TestQuoteIdentifier:
    """One rendering for every dynamic table or column name.

    SQLite binds values through `?` but has no equivalent for an identifier,
    so a dynamic name must reach the SQL text as a string. Sites variously
    wrote `"{table}"`, a bare `{table}`, and their own `replace('"', '""')`,
    so whether an embedded quote was handled depended on which site a reader
    was in. This is the one answer.
    """

    def test_an_ordinary_name_is_quoted(self):
        assert quote_identifier("events") == '"events"'

    def test_an_embedded_quote_is_doubled(self):
        """The case the bare-interpolation sites got wrong.

        Without doubling, a name containing `"` closes the identifier early
        and the remainder is parsed as SQL.
        """
        assert quote_identifier('a"b') == '"a""b"'
        assert quote_identifier('"') == '""""'

    def test_a_name_needing_quoting_round_trips(self, tmp_path):
        """The quoted form addresses the column SQLite actually created."""
        conn = sqlite3.connect(tmp_path / "quoting.db")
        conn.execute('CREATE TABLE t ("odd ""name" TEXT)')
        conn.execute('INSERT INTO t VALUES (?)', ("value",))
        column = quote_identifier('odd "name')
        assert conn.execute(f"SELECT {column} FROM t").fetchone()[0] == "value"
        conn.close()

    def test_a_reserved_word_is_addressable(self):
        """Quoting is what lets a schema name a column `order` or `select`."""
        assert quote_identifier("order") == '"order"'

    def test_a_nul_is_refused_rather_than_quoted(self):
        """SQLite truncates at a NUL, so quoting one addresses another object.

        Refusing is the only safe answer: the quoted text would parse, and
        would silently name a different column than the caller asked for.
        """
        with pytest.raises(ValueError, match="NUL"):
            quote_identifier("ev\0ents")

    @pytest.mark.parametrize("value", ["", None, 5])
    def test_an_empty_or_non_string_name_is_refused(self, value):
        with pytest.raises(ValueError):
            quote_identifier(value)

    def test_unicode_names_pass_through(self):
        """Only the quote character is special; the rest is UTF-8 text."""
        assert quote_identifier("sessión") == '"sessión"'


class TestQuoteIdentifierRaiseReachesACaller:
    """A refused identifier surfaces where a reader can act on it.

    `quote_identifier` raises `ValueError`, which is neither `sqlite3.Error`
    nor `OSError` -- so the handlers wrapping several call sites do not catch
    it by accident. That is the intended behavior at every site except the one
    best-effort report, and it is pinned here because the distinction is
    invisible at the call site: a reader sees a `try` and cannot tell whether
    the raise escapes it.
    """

    def _store(self, tmp_path):
        from codess.store import init_db
        db = tmp_path / "sessions_cc.db"
        init_db(db)
        return db

    def test_a_nul_name_is_refused_before_it_reaches_sqlite(self, tmp_path):
        """The check runs ahead of `execute`, so no partial query is issued."""
        from codess.schema_contract import column_names
        from codess.store import connect

        conn = connect(self._store(tmp_path))
        try:
            with pytest.raises(ValueError, match="NUL"):
                column_names(conn, "ev\0ents")
        finally:
            conn.close()

    def test_validation_lets_the_refusal_escape_its_sqlite_handler(self, tmp_path):
        """`baseline_validation` gates a publication, so it must not degrade.

        Its store loop catches `sqlite3.Error`; a name it cannot render is a
        different fault, and swallowing it would let a snapshot validate on a
        check that never ran.
        """
        from unittest.mock import patch

        import codess.baseline_validation as validation

        report = {"checks": [], "errors": [], "limitations": []}
        with patch(
            "codess.baseline_validation.quote_identifier",
            side_effect=ValueError("refused identifier"),
        ), pytest.raises(ValueError, match="refused identifier"):
            validation._validate_store(self._store(tmp_path), {}, report)

    def test_the_best_effort_annotation_degrades_instead(self, tmp_path):
        """`project_annotations` records the fault and keeps going.

        It is a report row, not a gate: the read is best-effort and already
        degrades on an unreadable store, so one Project's bad name must not
        cost the annotations for every other.
        """
        from unittest.mock import patch

        import codess.project_annotations as annotations

        self._store(tmp_path)
        with patch(
            "codess.project_annotations.quote_identifier",
            side_effect=ValueError("refused identifier"),
        ):
            facts = annotations._snapshot_facts(tmp_path)
        assert "refused identifier" in facts["snapshot_read_error"]
        assert facts["sessions"] == 0

    def test_a_name_absent_from_the_store_is_dropped_not_refused(self, tmp_path):
        """`table_counts` filters against the catalog before quoting.

        Omitting an absent table is its stated contract -- a missing table is
        a different fact from an empty one -- so the name never reaches
        `quote_identifier` and no raise is involved.
        """
        from codess.store import connect, table_counts

        conn = connect(self._store(tmp_path))
        try:
            assert table_counts(conn, ["ev\0ents"]) == {}
            assert table_counts(conn, ["events"]) == {"events": 0}
        finally:
            conn.close()


class TestOpenWritable:
    """The write-side connection contract.

    SQLite applies `foreign_keys` per connection and defaults it off, so
    enforcement is a property of how a file was opened rather than of the
    file. `open_readonly` has owned the read side since 3.5.4; this is its
    counterpart.
    """

    def _store(self, tmp_path):
        from codess.store import init_db

        db = tmp_path / "sessions_cc.db"
        init_db(db)
        return db

    def test_constraints_are_enforced_by_default(self, tmp_path):
        from codess.fileio import open_writable

        conn = open_writable(self._store(tmp_path))
        try:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO events(event_entity_id, session_id, event_id) "
                    "VALUES ('x', 'no-such-session', 'e1')"
                )
        finally:
            conn.close()

    def test_rows_are_addressable_by_name(self, tmp_path):
        """`row_factory` belongs with the opener, not with each caller."""
        from codess.fileio import open_writable

        conn = open_writable(self._store(tmp_path))
        try:
            row = conn.execute("SELECT key, value FROM store_meta LIMIT 1").fetchone()
            assert row["key"]
        finally:
            conn.close()

    def test_constraints_can_be_waived_explicitly(self, tmp_path):
        """The one legitimate case: a copy populated by `backup()`.

        Row constraints do not apply while SQLite copies pages, and stating
        that at the call site is the point -- the previous shape left every
        raw connection silently unconstrained.
        """
        from codess.fileio import open_writable

        conn = open_writable(self._store(tmp_path), foreign_keys=False)
        try:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 0
        finally:
            conn.close()

    def test_a_created_store_enforces_constraints(self, tmp_path):
        """`init_db` builds the store every later writer depends on."""
        from codess.store import connect

        conn = connect(self._store(tmp_path))
        try:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        finally:
            conn.close()
