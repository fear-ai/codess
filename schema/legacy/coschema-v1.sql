-- Codess legacy unversioned store layout (software 0.1.0).
-- Retained for read-only baseline documentation. New writers must not execute it.

CREATE TABLE sessions (
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

CREATE TABLE events (
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
  source_raw BLOB,
  UNIQUE(session_id, event_id)
);

