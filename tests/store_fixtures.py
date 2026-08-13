"""Builders for stores that tests construct directly.

Production writes stores through `codess.store`, which derives every identity
from source evidence. Tests that build a store by hand still have to satisfy
the same constraints, so these helpers supply the required identity columns
rather than each fixture restating them.
"""

from __future__ import annotations

VENDOR_SOURCE_SYSTEMS = {
    "Claude": "anthropic.claude-code",
    "Codex": "openai.codex",
    "Cursor": "cursor.composer",
}


def insert_session(conn, session_id, *, source="Claude", **columns):
    """Insert one session row carrying the identities a real store requires.

    Fixtures previously wrote raw SQL naming only the columns a given test
    cared about, which worked because the schema defaulted `global_id`. It no
    longer does -- an identity is derived from evidence or the row is invalid
    -- so this builder supplies the required fields and leaves the rest to
    the caller. Using it keeps fixtures unable to construct a row that
    production could not.
    """
    row = {
        "id": session_id,
        "global_id": f"codess:session:sha256:{session_id}",
        "observation_id": f"codess:observation:sha256:{session_id}",
        "source_system_id": VENDOR_SOURCE_SYSTEMS.get(source, "anthropic.claude-code"),
        "source": source,
        "type": "Code",
    }
    row.update(columns)
    names = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    conn.execute(
        f"INSERT INTO sessions ({names}) VALUES ({placeholders})", tuple(row.values())
    )
    return row


def insert_event(conn, session_id, event_id, **columns):
    """Insert one event row carrying the identities a real store requires.

    Event identity is qualified by its Session, matching how `codess.identity`
    derives it, so two Sessions can reuse a vendor event id without colliding.
    """
    row = {
        "session_id": session_id,
        "event_id": event_id,
        "global_id": f"codess:event:sha256:{session_id}-{event_id}",
    }
    row.update(columns)
    names = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    conn.execute(
        f"INSERT INTO events ({names}) VALUES ({placeholders})", tuple(row.values())
    )
    return row
