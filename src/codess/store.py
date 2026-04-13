"""SQLite store: init, upsert, incremental state."""

import json
import sqlite3
from pathlib import Path

# Schema at project root sql/CoSchema.sql (store.py is in src/codess/)
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "sql" / "CoSchema.sql"


def _load_schema() -> str:
    """Load schema from sql/CoSchema.sql."""
    if _SCHEMA_PATH.exists():
        return _SCHEMA_PATH.read_text(encoding="utf-8")
    # Fallback if file missing
    return """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, source TEXT NOT NULL, type TEXT NOT NULL,
  release TEXT, release_value INTEGER, started_at REAL NOT NULL, ended_at REAL,
  project_path TEXT, metadata TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), event_id TEXT NOT NULL,
  event_type TEXT, subtype TEXT, role TEXT, content TEXT, content_len INTEGER, content_ref TEXT,
  tool_name TEXT, tool_input TEXT, tool_output TEXT, timestamp REAL, file_path TEXT, source_file TEXT,
  metadata TEXT, source_raw BLOB, UNIQUE(session_id, event_id)
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_tool_name ON events(tool_name);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_path);
"""


def init_db(db_path: Path) -> None:
    """Create parent dir if needed; execute schema from sql/CoSchema.sql."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_load_schema())
        conn.commit()
    finally:
        conn.close()


def connect(db_path: Path) -> sqlite3.Connection:
    """Open connection; set row_factory=sqlite3.Row."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def upsert_session(conn: sqlite3.Connection, session: dict) -> None:
    """INSERT OR REPLACE into sessions."""
    conn.execute(
        """
        INSERT OR REPLACE INTO sessions
        (id, source, type, release, release_value, started_at, ended_at, project_path, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session.get("id"),
            session.get("source", "Claude"),
            session.get("type", "Code"),
            session.get("release"),
            session.get("release_value"),
            session.get("started_at"),
            session.get("ended_at"),
            session.get("project_path"),
            session.get("metadata"),
        ),
    )


def upsert_event(conn: sqlite3.Connection, event: dict) -> None:
    """INSERT OR REPLACE into events (conflict on session_id, event_id)."""
    conn.execute(
        """
        INSERT OR REPLACE INTO events
        (session_id, event_id, event_type, subtype, role, content, content_len,
         content_ref, tool_name, tool_input, tool_output, timestamp, file_path,
         source_file, metadata, source_raw)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.get("session_id"),
            event.get("event_id"),
            event.get("event_type"),
            event.get("subtype"),
            event.get("role"),
            event.get("content"),
            event.get("content_len"),
            event.get("content_ref"),
            event.get("tool_name"),
            event.get("tool_input"),
            event.get("tool_output"),
            event.get("timestamp"),
            event.get("file_path"),
            event.get("source_file"),
            event.get("metadata"),
            event.get("source_raw"),
        ),
    )


def load_ingest_state(state_path: Path) -> dict[str, float]:
    """Read ingest_state.json; return {} if missing/invalid."""
    if not state_path.exists():
        return {}
    try:
        data = state_path.read_text(encoding="utf-8")
        return json.loads(data)
    except (json.JSONDecodeError, OSError):
        return {}


def save_ingest_state(state_path: Path, state: dict[str, float]) -> None:
    """Write ingest_state.json."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=0), encoding="utf-8")


def should_ingest(
    state_path: Path,
    source_file: str,
    mtime: float,
    force: bool,
) -> bool:
    """Return True if file should be ingested (force or mtime changed)."""
    if force:
        return True
    state = load_ingest_state(state_path)
    return state.get(source_file) != mtime
