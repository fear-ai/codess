-- Coding Sessions Store Schema
-- Project-local: <project>/.coding-sess/sessions.db
-- FTS5 postponed

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  type TEXT NOT NULL,
  release TEXT,
  release_value INTEGER,
  started_at REAL NOT NULL,
  ended_at REAL,
  project_path TEXT,
  metadata TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  event_id TEXT NOT NULL,
  event_type TEXT,
  subtype TEXT,
  role TEXT,
  content TEXT,
  content_len INTEGER,
  content_ref TEXT,
  tool_name TEXT,
  tool_input TEXT,
  tool_output TEXT,
  timestamp REAL,
  file_path TEXT,
  source_file TEXT,
  metadata TEXT,
  source_raw BLOB,  -- decoder debug: first 512 bytes; no string ops until sanitized
  UNIQUE(session_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_tool_name ON events(tool_name);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_path);
