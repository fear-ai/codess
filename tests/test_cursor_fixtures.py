"""The shared Cursor fixture builders are themselves covered.

Test fixtures that lie are worse than absent ones: a builder that wrote the
wrong shape would make every Cursor test agree with each other and disagree
with Cursor. These assert the shape the vendor modules actually read.
"""

from __future__ import annotations

import json
import sqlite3

from cursor_fixtures import (
    HEADER_COLUMNS,
    build_cursor_db,
    create_bubble_table,
    create_header_table,
    put_bubbles,
    put_headers,
    put_records,
)

from codess.cursor_source import get_composer_headers, has_bubble_rows


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def test_a_workspace_database_has_no_header_table(tmp_path):
    """Omitting headers is what distinguishes a workspace store from a global one."""
    path = build_cursor_db(tmp_path / "state.vscdb", bubbles=[("c1", "b1", {})])
    conn = sqlite3.connect(path)
    try:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    finally:
        conn.close()
    assert tables == {"cursorDiskKV"}


def test_supplying_headers_creates_the_header_table(tmp_path):
    path = build_cursor_db(
        tmp_path / "state.vscdb", bubbles=[], headers=[("c1", "ws-1")],
    )
    conn = sqlite3.connect(path)
    try:
        assert columns(conn, "composerHeaders") == [
            column.split()[0] for column in HEADER_COLUMNS
        ]
    finally:
        conn.close()


def test_a_header_row_is_padded_to_the_created_shape(tmp_path):
    """Most tests set only the Composer and workspace and mean null for the rest."""
    path = build_cursor_db(
        tmp_path / "state.vscdb", bubbles=[], headers=[("c1", "ws-1")],
    )
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT composerId, workspaceId, createdAt FROM composerHeaders"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("c1", "ws-1", None)


def test_bubbles_are_keyed_the_way_cursor_keys_them(tmp_path):
    """The key format is what the source module's range scans depend on."""
    path = build_cursor_db(
        tmp_path / "state.vscdb", bubbles=[("c1", "b1", {"type": 1})],
    )
    conn = sqlite3.connect(path)
    try:
        [(key,)] = conn.execute("SELECT key FROM cursorDiskKV").fetchall()
    finally:
        conn.close()
    assert key == "bubbleId:c1:b1"


def test_a_value_is_json_encoded_unless_it_is_already_a_string(tmp_path):
    """Tests supply malformed values as strings to exercise decode failures."""
    path = build_cursor_db(
        tmp_path / "state.vscdb",
        bubbles=[("c1", "b1", {"type": 1}), ("c1", "b2", "{not json")],
    )
    conn = sqlite3.connect(path)
    try:
        values = dict(conn.execute("SELECT key, value FROM cursorDiskKV"))
    finally:
        conn.close()
    assert json.loads(values["bubbleId:c1:b1"]) == {"type": 1}
    assert values["bubbleId:c1:b2"] == "{not json"


def test_records_are_written_under_their_own_keys(tmp_path):
    """Request contexts are not bubbles and carry a different key prefix."""
    path = build_cursor_db(
        tmp_path / "state.vscdb",
        records={"messageRequestContext:c1:r1": {"files": ["a.py"]}},
    )
    conn = sqlite3.connect(path)
    try:
        [(key,)] = conn.execute("SELECT key FROM cursorDiskKV").fetchall()
    finally:
        conn.close()
    assert key == "messageRequestContext:c1:r1"


def test_writing_the_same_key_twice_keeps_the_second(tmp_path):
    """A fixture that writes a key again means the new value, not an error."""
    path = tmp_path / "state.vscdb"
    conn = sqlite3.connect(path)
    try:
        create_bubble_table(conn)
        put_bubbles(conn, [("c1", "b1", {"text": "first"})])
        put_bubbles(conn, [("c1", "b1", {"text": "second"})])
        conn.commit()
        [(value,)] = conn.execute("SELECT value FROM cursorDiskKV").fetchall()
    finally:
        conn.close()
    assert json.loads(value)["text"] == "second"


def test_a_reduced_header_shape_can_be_requested(tmp_path):
    """Some tests exist precisely to cover an older or unexpected shape."""
    path = tmp_path / "state.vscdb"
    conn = sqlite3.connect(path)
    try:
        create_header_table(conn, ("composerId TEXT", "workspaceId TEXT"))
        put_headers(conn, [("c1", "ws-1")])
        conn.commit()
        assert columns(conn, "composerHeaders") == ["composerId", "workspaceId"]
    finally:
        conn.close()


def test_the_built_database_is_readable_by_the_source_module(tmp_path):
    """The builders must produce what `cursor_source` actually reads."""
    path = build_cursor_db(
        tmp_path / "state.vscdb",
        bubbles=[("c1", "b1", {"type": 1, "text": "hi"})],
        headers=[("c1", "ws-1", 1700000000000, 1700000001000, 0, 0)],
    )
    assert has_bubble_rows(path) is True
    headers = get_composer_headers(path)
    assert "c1" in headers


def test_an_empty_database_reports_no_bubbles(tmp_path):
    path = build_cursor_db(tmp_path / "state.vscdb")
    assert has_bubble_rows(path) is False


def test_put_records_rejects_nothing_and_writes_nothing(tmp_path):
    path = tmp_path / "state.vscdb"
    conn = sqlite3.connect(path)
    try:
        create_bubble_table(conn)
        put_records(conn, {})
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM cursorDiskKV").fetchone()[0] == 0
    finally:
        conn.close()


def test_building_twice_over_one_path_is_safe(tmp_path):
    """`IF NOT EXISTS` keeps a fixture that extends a database from failing."""
    path = tmp_path / "state.vscdb"
    build_cursor_db(path, bubbles=[("c1", "b1", {})])
    build_cursor_db(path, bubbles=[("c2", "b1", {})])
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM cursorDiskKV").fetchone()[0] == 2
    finally:
        conn.close()
