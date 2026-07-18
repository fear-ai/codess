-- codess.coschema format 4
-- Functional meanings live in schema/coschema/contract.json and Schemas.md.
-- This file contains only the SQLite layout, constraints, and access paths.

PRAGMA application_id = 1129268293; -- 0x434F4445, "CODE"
PRAGMA user_version = 4;
PRAGMA foreign_keys = ON;

CREATE TABLE store_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  logical_name TEXT,
  root_path TEXT,
  source_cwd TEXT,
  ownership TEXT CHECK (ownership IN ('own','reference','external','mixed','unknown') OR ownership IS NULL),
  activity_state TEXT CHECK (activity_state IN ('active','dormant','archived','unknown') OR activity_state IS NULL),
  selection_state TEXT CHECK (selection_state IN ('priority','candidate','fixture','deferred','excluded','needs_review') OR selection_state IS NULL),
  metadata TEXT CHECK (metadata IS NULL OR json_valid(metadata))
);

CREATE TABLE project_locations (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  machine_id TEXT NOT NULL,
  observed_path TEXT NOT NULL,
  location_kind TEXT NOT NULL DEFAULT 'directory',
  state TEXT NOT NULL CHECK (state IN ('active','retired','missing','unknown')),
  observed_at TEXT NOT NULL,
  metadata TEXT CHECK (metadata IS NULL OR json_valid(metadata)),
  UNIQUE(machine_id, observed_path)
);

CREATE TABLE workspace_bindings (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  location_id TEXT REFERENCES project_locations(id) ON DELETE SET NULL,
  source_system_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  relation_kind TEXT NOT NULL,
  source_project_path TEXT,
  selection_state TEXT NOT NULL,
  metadata TEXT CHECK (metadata IS NULL OR json_valid(metadata)),
  UNIQUE(source_system_id, workspace_id, project_id)
);

CREATE TABLE sources (
  id INTEGER PRIMARY KEY,
  global_id TEXT NOT NULL UNIQUE DEFAULT ('codess:legacy:uuid:' || lower(hex(randomblob(16)))),
  source_system_id TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  storage_format TEXT NOT NULL,
  source_revision TEXT NOT NULL,
  source_mtime REAL,
  source_size INTEGER CHECK (source_size IS NULL OR source_size >= 0),
  observed_at TEXT NOT NULL,
  ingested_at TEXT NOT NULL,
  availability TEXT NOT NULL DEFAULT 'reference'
    CHECK (availability IN ('captured','reference','not_retained','unavailable')),
  capture_method TEXT,
  consistency TEXT,
  content_sha256 TEXT,
  metadata TEXT CHECK (metadata IS NULL OR json_valid(metadata)),
  UNIQUE(source_system_id, source_uri, source_revision)
);

CREATE TABLE model_configurations (
  id INTEGER PRIMARY KEY,
  provider TEXT,
  model_family TEXT,
  model_name_exact TEXT,
  model_revision TEXT,
  reasoning_effort TEXT,
  speed_tier TEXT,
  service_tier TEXT,
  mode TEXT,
  source_config TEXT CHECK (source_config IS NULL OR json_valid(source_config)),
  UNIQUE(provider, model_family, model_name_exact, model_revision, reasoning_effort, speed_tier, service_tier, mode)
);

CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  global_id TEXT NOT NULL UNIQUE DEFAULT ('codess:legacy:uuid:' || lower(hex(randomblob(16)))),
  observation_id TEXT NOT NULL UNIQUE DEFAULT ('codess:legacy:uuid:' || lower(hex(randomblob(16)))),
  source_system_id TEXT NOT NULL DEFAULT 'legacy.unknown',
  vendor_session_id TEXT,
  vendor_name TEXT,
  product_name TEXT,
  harness_name TEXT,
  storage_format TEXT,
  surface_kind TEXT CHECK (surface_kind IN ('cli','ide','desktop','api','agent','unknown') OR surface_kind IS NULL),
  session_purpose TEXT,
  harness_version TEXT,
  source_id INTEGER REFERENCES sources(id),
  project_id TEXT REFERENCES projects(id),
  source_cwd TEXT,
  started_at REAL,
  ended_at REAL,
  source_mtime REAL,
  observed_at TEXT,
  ingested_at TEXT,
  time_basis TEXT CHECK (time_basis IN ('event','session','source_mtime','ingested','unknown') OR time_basis IS NULL),
  parent_session_id TEXT,
  session_relation_kind TEXT CHECK (session_relation_kind IN ('subagent','fork','resume','continuation','unknown') OR session_relation_kind IS NULL),
  archive_state TEXT CHECK (archive_state IN ('active','archived','unknown') OR archive_state IS NULL),
  archive_source TEXT,
  default_model_config_id INTEGER REFERENCES model_configurations(id),
  metadata TEXT CHECK (metadata IS NULL OR json_valid(metadata)),

  -- Read compatibility for the 0.1 query surface. These are projections, not
  -- the v2 functional identity model.
  source TEXT NOT NULL DEFAULT 'Unknown',
  type TEXT NOT NULL DEFAULT 'Unknown',
  release TEXT,
  project_path TEXT,

  UNIQUE(source_system_id, vendor_session_id)
);

CREATE TABLE interactions (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  sequence_no INTEGER NOT NULL CHECK (sequence_no > 0),
  initiating_event_id TEXT,
  boundary_source TEXT NOT NULL CHECK (boundary_source IN ('vendor','mapping','inferred','manual')),
  confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  UNIQUE(session_id, sequence_no)
);

CREATE TABLE model_turns (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  sequence_no INTEGER NOT NULL CHECK (sequence_no > 0),
  source_turn_id TEXT,
  model_config_id INTEGER REFERENCES model_configurations(id),
  boundary_source TEXT NOT NULL CHECK (boundary_source IN ('vendor','mapping','inferred')),
  UNIQUE(session_id, sequence_no)
);

CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  global_id TEXT NOT NULL UNIQUE DEFAULT ('codess:legacy:uuid:' || lower(hex(randomblob(16)))),
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  source_id INTEGER REFERENCES sources(id),
  event_id TEXT NOT NULL,
  sequence_no INTEGER CHECK (sequence_no IS NULL OR sequence_no > 0),
  source_record_locator TEXT,
  source_record_type TEXT,
  source_record_subtype TEXT,
  event_kind TEXT,
  actor_kind TEXT,
  content_role TEXT,
  origin_kind TEXT,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  model_turn_id TEXT REFERENCES model_turns(id) ON DELETE SET NULL,
  parent_event_id TEXT,
  caused_by_event_id TEXT,
  content TEXT,
  content_len INTEGER CHECK (content_len IS NULL OR content_len >= 0),
  tool_name TEXT,
  tool_input TEXT CHECK (tool_input IS NULL OR json_valid(tool_input)),
  tool_output TEXT,
  event_at REAL,
  event_at_basis TEXT,
  source_status TEXT,
  normalized_status TEXT CHECK (normalized_status IN ('pending','running','succeeded','failed','denied','cancelled','incomplete','unknown') OR normalized_status IS NULL),
  source_file TEXT,
  artifact_path TEXT,
  mapping_rule TEXT,
  mapping_trace TEXT CHECK (mapping_trace IS NULL OR json_valid(mapping_trace)),
  metadata TEXT CHECK (metadata IS NULL OR json_valid(metadata)),

  -- Read compatibility for existing queries.
  event_type TEXT,
  subtype TEXT,
  role TEXT,
  timestamp REAL,
  file_path TEXT,

  UNIQUE(session_id, event_id)
);

CREATE TABLE source_records (
  id TEXT PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  source_locator TEXT NOT NULL,
  source_sequence INTEGER CHECK (source_sequence IS NULL OR source_sequence > 0),
  source_record_type TEXT,
  source_record_subtype TEXT,
  parent_locator TEXT,
  record_at REAL,
  classification TEXT,
  parameters_json TEXT CHECK (parameters_json IS NULL OR json_valid(parameters_json)),
  UNIQUE(source_id, source_locator)
);

CREATE TABLE content_objects (
  id TEXT PRIMARY KEY,
  content_sha256 TEXT NOT NULL,
  media_type TEXT,
  charset TEXT,
  byte_length INTEGER CHECK (byte_length IS NULL OR byte_length >= 0),
  character_length INTEGER CHECK (character_length IS NULL OR character_length >= 0),
  storage_class TEXT NOT NULL CHECK (storage_class IN ('inline','raw_object','derived','not_retained')),
  inline_content TEXT,
  raw_object_id TEXT,
  privacy_class TEXT,
  metadata TEXT CHECK (metadata IS NULL OR json_valid(metadata)),
  UNIQUE(content_sha256, storage_class, raw_object_id)
);

CREATE TABLE event_content (
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  content_id TEXT NOT NULL REFERENCES content_objects(id) ON DELETE CASCADE,
  relation_kind TEXT NOT NULL,
  sequence_no INTEGER NOT NULL DEFAULT 1 CHECK (sequence_no > 0),
  start_offset INTEGER CHECK (start_offset IS NULL OR start_offset >= 0),
  end_offset INTEGER CHECK (end_offset IS NULL OR end_offset >= 0),
  integrity_state TEXT NOT NULL DEFAULT 'verified',
  PRIMARY KEY(event_id, relation_kind, sequence_no)
) WITHOUT ROWID;

CREATE TABLE source_record_content (
  source_record_id TEXT NOT NULL REFERENCES source_records(id) ON DELETE CASCADE,
  content_id TEXT NOT NULL REFERENCES content_objects(id) ON DELETE CASCADE,
  relation_kind TEXT NOT NULL,
  sequence_no INTEGER NOT NULL DEFAULT 1 CHECK (sequence_no > 0),
  integrity_state TEXT NOT NULL DEFAULT 'verified',
  PRIMARY KEY(source_record_id, relation_kind, sequence_no)
) WITHOUT ROWID;

CREATE TABLE tool_result_content (
  tool_result_id INTEGER NOT NULL REFERENCES tool_results(id) ON DELETE CASCADE,
  content_id TEXT NOT NULL REFERENCES content_objects(id) ON DELETE CASCADE,
  relation_kind TEXT NOT NULL,
  sequence_no INTEGER NOT NULL DEFAULT 1 CHECK (sequence_no > 0),
  integrity_state TEXT NOT NULL DEFAULT 'verified',
  PRIMARY KEY(tool_result_id, relation_kind, sequence_no)
) WITHOUT ROWID;

CREATE TABLE artifact_content (
  artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
  content_id TEXT NOT NULL REFERENCES content_objects(id) ON DELETE CASCADE,
  relation_kind TEXT NOT NULL,
  sequence_no INTEGER NOT NULL DEFAULT 1 CHECK (sequence_no > 0),
  integrity_state TEXT NOT NULL DEFAULT 'verified',
  PRIMARY KEY(artifact_id, relation_kind, sequence_no)
) WITHOUT ROWID;

CREATE TABLE processing_runs (
  id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(id),
  policy_sha256 TEXT NOT NULL,
  processor_name TEXT NOT NULL,
  software_version TEXT NOT NULL,
  scope_json TEXT CHECK (scope_json IS NULL OR json_valid(scope_json)),
  actions_json TEXT CHECK (actions_json IS NULL OR json_valid(actions_json)),
  rejection_reason TEXT,
  started_at TEXT NOT NULL,
  completed_at TEXT NOT NULL
);

CREATE TABLE content_derivations (
  processing_run_id TEXT NOT NULL REFERENCES processing_runs(id) ON DELETE CASCADE,
  input_content_id TEXT NOT NULL REFERENCES content_objects(id),
  output_content_id TEXT REFERENCES content_objects(id),
  sequence_no INTEGER NOT NULL CHECK (sequence_no > 0),
  actions_json TEXT CHECK (actions_json IS NULL OR json_valid(actions_json)),
  rejection_reason TEXT,
  PRIMARY KEY(processing_run_id, sequence_no)
) WITHOUT ROWID;

CREATE TABLE tool_invocations (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  model_turn_id TEXT REFERENCES model_turns(id) ON DELETE SET NULL,
  requested_event_id INTEGER REFERENCES events(id) ON DELETE SET NULL,
  source_call_id TEXT,
  source_tool_name TEXT,
  canonical_tool_name TEXT,
  tool_namespace TEXT,
  invocation_kind TEXT,
  input_json TEXT CHECK (input_json IS NULL OR json_valid(input_json)),
  source_status TEXT,
  normalized_status TEXT,
  started_at REAL,
  ended_at REAL,
  UNIQUE(session_id, source_call_id)
);

CREATE TABLE tool_results (
  id INTEGER PRIMARY KEY,
  invocation_id TEXT REFERENCES tool_invocations(id) ON DELETE CASCADE,
  result_event_id INTEGER REFERENCES events(id) ON DELETE SET NULL,
  sequence_no INTEGER NOT NULL DEFAULT 1 CHECK (sequence_no > 0),
  producing_actor_kind TEXT,
  output_text TEXT,
  output_json TEXT CHECK (output_json IS NULL OR json_valid(output_json)),
  is_error INTEGER CHECK (is_error IN (0,1) OR is_error IS NULL),
  source_status TEXT,
  normalized_status TEXT,
  UNIQUE(invocation_id, sequence_no)
);

CREATE TABLE artifacts (
  id INTEGER PRIMARY KEY,
  project_id TEXT REFERENCES projects(id),
  artifact_kind TEXT NOT NULL,
  relative_path TEXT,
  observed_absolute_path TEXT,
  uri TEXT,
  repository_object_id TEXT,
  content_sha256 TEXT,
  metadata TEXT CHECK (metadata IS NULL OR json_valid(metadata)),
  UNIQUE(project_id, artifact_kind, relative_path, uri, repository_object_id, content_sha256)
);

CREATE TABLE event_artifacts (
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
  operation TEXT NOT NULL CHECK (operation IN ('read','create','modify','delete','execute','mention','unknown')),
  evidence_source TEXT,
  confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  PRIMARY KEY(event_id, artifact_id, operation)
) WITHOUT ROWID;

CREATE TABLE mapping_diagnostics (
  id INTEGER PRIMARY KEY,
  source_id INTEGER REFERENCES sources(id),
  session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
  event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
  level TEXT NOT NULL CHECK (level IN ('source','record','field')),
  reason_code TEXT NOT NULL,
  source_field TEXT,
  source_value TEXT,
  mapping_rule TEXT,
  detail TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE correlation_assertions (
  id INTEGER PRIMARY KEY,
  subject_kind TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  object_kind TEXT NOT NULL,
  object_id TEXT NOT NULL,
  relation_kind TEXT NOT NULL,
  method TEXT NOT NULL,
  evidence TEXT CHECK (evidence IS NULL OR json_valid(evidence)),
  confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  asserted_at TEXT NOT NULL,
  reviewer TEXT
);

CREATE UNIQUE INDEX idx_events_session_sequence
  ON events(session_id, sequence_no) WHERE sequence_no IS NOT NULL;
CREATE INDEX idx_events_session ON events(session_id);
CREATE INDEX idx_events_event_at ON events(event_at) WHERE event_at IS NOT NULL;
CREATE INDEX idx_events_timestamp ON events(timestamp) WHERE timestamp IS NOT NULL;
CREATE INDEX idx_events_tool_name ON events(tool_name) WHERE tool_name IS NOT NULL;
CREATE INDEX idx_events_source_record ON events(source_id, source_record_locator);
CREATE INDEX idx_events_interaction ON events(interaction_id, sequence_no);
CREATE INDEX idx_sources_uri_revision ON sources(source_uri, source_revision);
CREATE INDEX idx_sessions_project ON sessions(project_id);
CREATE INDEX idx_sessions_project_path ON sessions(project_path);
CREATE INDEX idx_sessions_parent ON sessions(parent_session_id);
CREATE INDEX idx_sessions_global ON sessions(global_id);
CREATE INDEX idx_sessions_observation ON sessions(observation_id);
CREATE INDEX idx_events_global ON events(global_id);
CREATE INDEX idx_project_locations_project ON project_locations(project_id);
CREATE INDEX idx_workspace_bindings_project ON workspace_bindings(project_id);
CREATE INDEX idx_source_records_source ON source_records(source_id, source_sequence);
CREATE INDEX idx_content_sha256 ON content_objects(content_sha256);
CREATE INDEX idx_tools_name ON tool_invocations(canonical_tool_name);
CREATE INDEX idx_artifacts_project_path ON artifacts(project_id, relative_path);
CREATE UNIQUE INDEX idx_model_configurations_identity
  ON model_configurations(
    coalesce(provider,''), coalesce(model_family,''),
    coalesce(model_name_exact,''), coalesce(model_revision,''),
    coalesce(reasoning_effort,''), coalesce(speed_tier,''),
    coalesce(service_tier,''), coalesce(mode,'')
  );
CREATE UNIQUE INDEX idx_artifacts_identity_path
  ON artifacts(project_id, artifact_kind, relative_path)
  WHERE relative_path IS NOT NULL;
CREATE UNIQUE INDEX idx_artifacts_identity_uri
  ON artifacts(project_id, artifact_kind, uri)
  WHERE uri IS NOT NULL;
CREATE UNIQUE INDEX idx_artifacts_identity_repository_object
  ON artifacts(project_id, artifact_kind, repository_object_id)
  WHERE repository_object_id IS NOT NULL;
CREATE UNIQUE INDEX idx_artifacts_identity_content
  ON artifacts(project_id, artifact_kind, content_sha256)
  WHERE content_sha256 IS NOT NULL;
CREATE INDEX idx_correlations_subject ON correlation_assertions(subject_kind, subject_id);
