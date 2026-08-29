"""The shared Cursor fixture builders are themselves covered.

Test fixtures that lie are worse than absent ones: a builder that wrote the
wrong shape would make every Cursor test agree with each other and disagree
with Cursor. These assert the shape the vendor modules actually read.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

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


def test_the_item_table_index_qualifies_without_widening(tmp_path):
    """Cursor keeps two composer indexes; only one selects.

    `ItemTable`'s `composer.composerHeaders` is UI state over a subset of the
    same composers -- measured 39 against 66 table rows, all also in the table,
    agreeing on the workspace for every one. It carries two facts the table
    does not: `unifiedMode` (agent or chat) and the workspace **path**, where
    the table holds only the storage hash a workspace recreation would change.

    So it qualifies a selected Session and must never add one: a composer
    present only there stays out, or the index would widen a Project's
    selection through a document that does not decide membership.
    """
    path = build_cursor_db(
        tmp_path / "state.vscdb", bubbles=[], headers=[("c1", "ws-1")],
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS ItemTable(key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT OR REPLACE INTO ItemTable(key, value) VALUES (?, ?)",
            ("composer.composerHeaders", json.dumps({"allComposers": [
                {"composerId": "c1", "unifiedMode": "agent",
                 "workspaceIdentifier": {"id": "ws-1",
                                         "uri": {"fsPath": "/work/proj"}}},
                {"composerId": "absent-from-table", "unifiedMode": "chat",
                 "workspaceIdentifier": {"id": "ws-1"}},
            ]})),
        )
        conn.commit()
    finally:
        conn.close()

    headers = get_composer_headers(Path(path), {"ws-1"})
    assert set(headers) == {"c1"}, "an ItemTable-only composer must not be selected"
    assert headers["c1"]["interaction_mode"] == "agent"
    assert headers["c1"]["workspace_path"] == "/work/proj"


def test_an_absent_item_table_index_leaves_headers_usable(tmp_path):
    """The qualifier is optional; a store without it still selects."""
    path = build_cursor_db(
        tmp_path / "state.vscdb", bubbles=[], headers=[("c1", "ws-1")],
    )
    headers = get_composer_headers(Path(path), {"ws-1"})
    assert set(headers) == {"c1"}
    assert "interaction_mode" not in headers["c1"]


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


class TestHeaderlessComposerRecovery:
    """A composer with bubbles but no header row is still a Session.

    Cursor keeps three indexes of the same composers and they disagree. On the
    development machine 107 composers hold bubbles that `composerHeaders` does
    not list, and the whole of a Session reachable only from an unread index is
    lost -- not a field, the Session.
    """

    def _store(self, tmp_path, *, header_ids=(), data_ids=()):
        db = tmp_path / "state.vscdb"
        conn = sqlite3.connect(db)
        create_bubble_table(conn)
        create_header_table(conn)
        for composer_id in header_ids:
            conn.execute(
                "INSERT INTO composerHeaders"
                "(composerId, workspaceId, createdAt, lastUpdatedAt,"
                " isArchived, isSubagent) VALUES (?,?,?,?,?,?)",
                (composer_id, "ws-1", 1_700_000_000_000, 1_700_000_100_000, 0, 0),
            )
        for composer_id in data_ids:
            put_records(conn, {
                f"composerData:{composer_id}": {
                    "composerId": composer_id,
                    "createdAt": 1_700_000_200_000,
                    "unifiedMode": "agent",
                    "modelConfig": {"modelName": "composer-2.5", "maxMode": False},
                },
            })
        conn.commit()
        conn.close()
        return db

    def test_composer_data_recovery(self, tmp_path):
        """The recovered header states where it came from."""
        db = self._store(tmp_path, header_ids=("headered",), data_ids=("orphan",))
        headers = get_composer_headers(db)
        assert set(headers) == {"headered", "orphan"}
        assert headers["orphan"]["selection_source"] == "global.composerData"
        assert headers["headered"]["selection_source"] == "composerHeaders"

    def test_recovered_composer_model(self, tmp_path):
        """`modelConfig.modelName` reaches the Session it belongs to.

        Settings were previously read only for composers that had a header, so
        a recovered Session would arrive with no model even though the vendor
        recorded one.
        """
        db = self._store(tmp_path, data_ids=("orphan",))
        headers = get_composer_headers(db)
        assert headers["orphan"]["model"] == "composer-2.5"
        assert headers["orphan"]["interaction_mode"] == "agent"

    def test_selected_model_parameters(self, tmp_path):
        """`selectedModels` carries settings the model name need not state.

        Two parameter ids appear: `fast`, which the name encodes only for the
        `*-fast` aliases, and `effort`, which no Cursor model name encodes at
        all. A composer may set either on a model whose name says nothing, so
        reading the name alone loses them.
        """
        db = tmp_path / "state.vscdb"
        conn = sqlite3.connect(db)
        create_bubble_table(conn)
        create_header_table(conn)
        put_records(conn, {
            "composerData:speedy": {
                "composerId": "speedy",
                "modelConfig": {
                    "modelName": "composer-2.5",
                    "selectedModels": [
                        {"modelId": "composer-2.5",
                         "parameters": [{"id": "fast", "value": "true"}]},
                    ],
                },
            },
            "composerData:plain": {
                "composerId": "plain",
                "modelConfig": {
                    "modelName": "composer-2.5",
                    "selectedModels": [
                        {"modelId": "composer-2.5",
                         "parameters": [{"id": "fast", "value": "false"}]},
                    ],
                },
            },
            "composerData:thinker": {
                "composerId": "thinker",
                "modelConfig": {
                    "modelName": "composer-2.5",
                    "selectedModels": [
                        {"modelId": "composer-2.5",
                         "parameters": [{"id": "effort", "value": "high"}]},
                    ],
                },
            },
        })
        conn.commit()
        conn.close()
        headers = get_composer_headers(db)
        assert headers["speedy"]["speed"] == "fast"
        # `"false"` is a stated value, not an assertion: it must not set a tier.
        assert "speed" not in headers["plain"]
        assert headers["thinker"]["effort"] == "high"

    def test_header_table_wins(self, tmp_path):
        """A header is authoritative; recovery fills gaps rather than overriding."""
        db = self._store(tmp_path, header_ids=("both",), data_ids=("both",))
        headers = get_composer_headers(db)
        assert headers["both"]["selection_source"] == "composerHeaders"
        assert headers["both"]["workspace_id"] == "ws-1"

    def test_workspace_excludes_unbound(self, tmp_path):
        """A `composerData:` row states no workspace, so it cannot satisfy one.

        Admitting it under a workspace filter would widen that selection
        silently, attributing a Session to a Project on no evidence.
        """
        db = self._store(tmp_path, header_ids=("headered",), data_ids=("orphan",))
        headers = get_composer_headers(db, workspace_ids={"ws-1"})
        assert set(headers) == {"headered"}
