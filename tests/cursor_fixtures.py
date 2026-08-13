"""Builders for the Cursor vendor databases that tests construct directly.

Cursor stores Sessions in shared SQLite databases, so almost every Cursor test
needs one built by hand. The DDL and inserts were written out across five test
modules -- the `cursorDiskKV` table more than twenty times, its insert in three
different spellings -- which made a vendor-shape change a search-and-replace
and let the fixtures drift from each other.

These build the two tables Codess reads. They deliberately do not wrap the
whole fixture: a test that needs an unusual shape (a missing column, a legacy
table, a WAL sidecar) still writes it, because that shape is the subject of
the test rather than boilerplate around it.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

BUBBLE_TABLE = "cursorDiskKV"
HEADER_TABLE = "composerHeaders"

HEADER_COLUMNS = (
    "composerId TEXT PRIMARY KEY",
    "workspaceId TEXT",
    "createdAt INTEGER",
    "lastUpdatedAt INTEGER",
    "isArchived INTEGER",
    "isSubagent INTEGER",
)
"""The header columns Codess reads. A workspace database has no header table."""


def create_bubble_table(conn: sqlite3.Connection) -> None:
    """Create the key/value table holding bubbles and request contexts."""
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {BUBBLE_TABLE} "
        "(key TEXT PRIMARY KEY, value TEXT)"
    )


def create_header_table(
    conn: sqlite3.Connection, columns: Iterable[str] = HEADER_COLUMNS,
) -> None:
    """Create the Composer header table, optionally with a reduced shape.

    `columns` exists for the tests whose subject is an older or unexpected
    header shape; every other caller takes the default.
    """
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {HEADER_TABLE} ({', '.join(columns)})"
    )


def put_records(conn: sqlite3.Connection, records: Mapping[str, Any]) -> None:
    """Write key/value records, JSON-encoding any value that is not a string.

    Three spellings of this insert were in use -- with and without a column
    list, and an OR REPLACE variant. Replacing is the useful default for a
    fixture, since a test that writes the same key twice means the second.
    """
    conn.executemany(
        f"INSERT OR REPLACE INTO {BUBBLE_TABLE} (key, value) VALUES (?, ?)",
        [
            (key, value if isinstance(value, str) else json.dumps(value))
            for key, value in records.items()
        ],
    )


def put_bubbles(
    conn: sqlite3.Connection, bubbles: Iterable[tuple[str, str, Any]],
) -> None:
    """Write bubbles given as (composer_id, bubble_id, value) triples."""
    put_records(conn, {
        f"bubbleId:{composer}:{bubble}": value
        for composer, bubble, value in bubbles
    })


def put_headers(
    conn: sqlite3.Connection, headers: Iterable[tuple],
) -> None:
    """Write Composer header rows as positional tuples.

    Rows are padded to the created shape so a caller can supply only the
    leading columns it cares about -- most tests set the Composer and its
    workspace and have no interest in the archive flags.
    """
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({HEADER_TABLE})")]
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f"INSERT OR REPLACE INTO {HEADER_TABLE} VALUES ({placeholders})",
        [tuple(row) + (None,) * (len(columns) - len(row)) for row in headers],
    )


def build_cursor_db(
    path: Path,
    *,
    bubbles: Iterable[tuple[str, str, Any]] = (),
    headers: Iterable[tuple] | None = None,
    records: Mapping[str, Any] | None = None,
) -> Path:
    """Create one Cursor database with the tables its contents imply.

    The header table is created only when headers are supplied, which is what
    distinguishes a global store from a workspace one: a workspace database
    holds bubbles and no Composer headers, and several behaviors depend on
    that difference.
    """
    conn = sqlite3.connect(path)
    try:
        create_bubble_table(conn)
        put_bubbles(conn, bubbles)
        if records:
            put_records(conn, records)
        if headers is not None:
            create_header_table(conn)
            put_headers(conn, headers)
        conn.commit()
    finally:
        conn.close()
    return path
