-- codess.coschema
-- Functional meanings live in schema/coschema/contract.json and Schemas.md.
-- This file contains only the SQLite layout, constraints, and access paths.
--
-- The format number is declared once, by `PRAGMA user_version` below, and is
-- read from there by `schema_contract`. It is not repeated in this comment:
-- a number a check cannot read drifts from the one it describes, which is what
-- a stale header here did while the pragma stayed correct.

PRAGMA application_id = 1129268293; -- 0x434F4445, "CODE"
PRAGMA user_version = 10;
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
  path_obsolete INTEGER NOT NULL DEFAULT 0 CHECK (path_obsolete IN (0,1)),
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
  path_obsolete INTEGER NOT NULL DEFAULT 0 CHECK (path_obsolete IN (0,1)),
  selection_state TEXT NOT NULL,
  metadata TEXT CHECK (metadata IS NULL OR json_valid(metadata)),
  UNIQUE(source_system_id, workspace_id, project_id)
);

CREATE TABLE sources (
  id INTEGER PRIMARY KEY,
  source_entity_id TEXT NOT NULL UNIQUE,
  source_system_id TEXT NOT NULL,
  source_path TEXT NOT NULL,
  storage_format TEXT NOT NULL,
  source_revision TEXT NOT NULL,
  source_mtime REAL,
  source_size INTEGER CHECK (source_size IS NULL OR source_size >= 0),
  observed_at TEXT NOT NULL,
  availability TEXT NOT NULL DEFAULT 'reference'
    CHECK (availability IN ('captured','reference','not_retained','unavailable')),
  capture_method TEXT,
  consistency TEXT,
  content_digest TEXT,
  metadata TEXT CHECK (metadata IS NULL OR json_valid(metadata)),
  UNIQUE(source_system_id, source_path, source_revision)
);

CREATE TABLE model_params (
  id INTEGER PRIMARY KEY,
  provider TEXT,
  model_line TEXT,
  model_generation TEXT,
  model_version TEXT,
  model_gradation TEXT,
  model_variant TEXT,
  model_name_exact TEXT,
  model_revision TEXT,
  reasoning_effort TEXT,
  speed_tier TEXT,
  service_tier TEXT,
  request_tier TEXT,
  mode TEXT,
  source_params TEXT CHECK (source_params IS NULL OR json_valid(source_params)),
  UNIQUE(provider, model_line, model_generation, model_version, model_gradation,
         model_variant, model_name_exact, model_revision, reasoning_effort,
         speed_tier, service_tier, request_tier, mode)
);

CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  session_entity_id TEXT NOT NULL UNIQUE,
  observation_id TEXT NOT NULL UNIQUE,
  source_system_id TEXT NOT NULL DEFAULT 'legacy.unknown',
  vendor_session_id TEXT,
  vendor_name TEXT,
  harness_name TEXT,
  storage_format TEXT,
  surface_kind TEXT CHECK (surface_kind IN ('cli','ide','desktop','api','agent','unknown') OR surface_kind IS NULL),
  harness_version TEXT,
  source_id INTEGER REFERENCES sources(id),
  project_id TEXT REFERENCES projects(id),
  -- The first working directory the Session recorded, and how many distinct
  -- ones it recorded in total. A Session is usually one directory and is not
  -- guaranteed to be: measured over 376 Claude transcripts, four record more
  -- than one and one records 21, all subdirectories of the same Project. The
  -- count says whether the single value understates the Session without
  -- storing a list the query surface has no predicate for.
  source_cwd TEXT,
  source_cwd_count INTEGER CHECK (source_cwd_count IS NULL OR source_cwd_count >= 0),
  -- The vendor's own label for the Session, and where it came from. Every
  -- vendor keeps one and none of them keeps it in the transcript: Claude
  -- writes `aiTitle` on records, Codex an operator-set `thread_name` in
  -- `session_index.jsonl`, Cursor a `title` in `conversation-search.db`. A
  -- store built from transcripts alone reports Sessions the operator cannot
  -- recognise by the name they gave them.
  --
  -- Distinct from a Codess alias, which the registry holds: one is the
  -- vendor's label and one is ours, and a reader asking "which Session was
  -- that" wants the first. `session_label_basis` says which it is.
  session_label TEXT,
  session_label_basis TEXT CHECK (
    session_label_basis IN ('vendor_generated','operator_named') OR session_label_basis IS NULL
  ),
  -- The vendor's own grouping for the Session, where it states one: a Cursor
  -- conversation branch, a Codex thread. Not a git branch and not a Project --
  -- a label the vendor groups threads by, retained verbatim.
  vendor_group TEXT,
  -- Directory identity as the filesystem states it, recorded at ingest. A path
  -- is a name and these are the thing named: an inode that persists across a
  -- rename says the directory is the same one, and an mtime bounds when it was
  -- last written. Both are POSIX values -- on Windows `st_ino` is not stable,
  -- so a reader must treat them as evidence rather than as identity.
  source_dir_inode INTEGER,
  source_dir_mtime REAL,
  path_obsolete INTEGER NOT NULL DEFAULT 0 CHECK (path_obsolete IN (0,1)),
  -- Materialized MIN/MAX(events.event_at) for the Session. Retained rather
  -- than derived: they carry the indexed `--since`/`--until` predicate and
  -- every Session listing, so deriving them would put an aggregate over the
  -- events table on the common read path.
  started_at REAL,
  ended_at REAL,
  source_mtime REAL,
  observed_at TEXT,
  time_basis TEXT CHECK (time_basis IN ('event','session','source_mtime','ingested','unknown') OR time_basis IS NULL),
  parent_session_id TEXT,
  session_relation_kind TEXT CHECK (session_relation_kind IN ('subagent','fork','resume','continuation','unknown') OR session_relation_kind IS NULL),
  archive_state TEXT CHECK (archive_state IN ('active','archived','unknown') OR archive_state IS NULL),
  archive_source TEXT,
  session_model_param_id INTEGER REFERENCES model_params(id),
  -- How `session_model_param_id` was obtained. 'vendor' is a Session-level
  -- statement the vendor made; 'initial_event' is the first model observed to
  -- serve a turn, recorded where the vendor states none. The two are different
  -- claims and a query comparing configuration must be able to exclude the
  -- second.
  session_model_basis TEXT CHECK (session_model_basis IN ('vendor','initial_event') OR session_model_basis IS NULL),
  -- Distinct models observed across the Session's Model Turns. 1 for almost
  -- every Session; greater than 1 identifies a model switch without a join,
  -- which is the population a model-comparison question is usually about.
  session_model_count INTEGER CHECK (session_model_count IS NULL OR session_model_count >= 0),
  metadata TEXT CHECK (metadata IS NULL OR json_valid(metadata)),

  -- Read compatibility for the legacy flat query surface. These are
  -- projections, not the functional identity model.
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
  initiation_kind TEXT NOT NULL DEFAULT 'human' CHECK (initiation_kind IN ('human','autonomous','unknown')),
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
  model_param_id INTEGER REFERENCES model_params(id),
  boundary_source TEXT NOT NULL CHECK (boundary_source IN ('vendor','mapping','inferred')),
  UNIQUE(session_id, sequence_no)
);

CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  event_entity_id TEXT NOT NULL UNIQUE,
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

  -- Coarser vendor-facing projection of the classification above, retained
  -- while the reports in `query_reports` still select on it. Measured against
  -- 146,158 stored Events, (event_kind, actor_kind, content_role) is a strict
  -- refinement of (event_type, role): every functional triple determines the
  -- pair, and two of seventeen determine it more precisely than the pair does.
  event_type TEXT,
  subtype TEXT,
  role TEXT,
  file_path TEXT,

  -- An advisory reference to the Event this one repeats, with the evidence
  -- that justified it in `metadata`. Both records are real vendor records: a
  -- long-lived Cursor composer is re-synced and the sync writes
  -- server-identified copies of bubbles that already exist locally, so
  -- deleting either loses evidence and would be unrecoverable. A reader
  -- wanting the raw record count ignores this column; one excluding replays
  -- selects on it.
  duplicate_of TEXT,

  -- Recorded usage, retained whenever the vendor states it -- including when it
  -- states zero. An explicitly recorded zero is evidence the vendor reported no
  -- usage, which is not the same as the field being absent, and that
  -- distinction is exactly what a usage question needs. `field_state` already
  -- separates absent from null from empty; storing the zero is what lets the
  -- distinction reach a query.
  input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
  output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),

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

-- Content is UTF-8 text stored inline. `media_type`, `charset`, and
-- `storage_class` were removed in format 6: each was written from a literal
-- ('text/plain', 'utf-8', 'inline') on all 236,535 measured rows and read by
-- nothing but the fixed-point digest. Reintroducing any of them is a real
-- change -- a non-text or externally stored object -- and should arrive with
-- the capability rather than ahead of it.
CREATE TABLE content_objects (
  id TEXT PRIMARY KEY,
  content_digest TEXT NOT NULL,
  byte_length INTEGER CHECK (byte_length IS NULL OR byte_length >= 0),
  character_length INTEGER CHECK (character_length IS NULL OR character_length >= 0),
  inline_content TEXT,
  raw_object_id TEXT,
  privacy_class TEXT,
  metadata TEXT CHECK (metadata IS NULL OR json_valid(metadata)),
  UNIQUE(content_digest, raw_object_id)
);

-- The four link tables below dropped `sequence_no` and `integrity_state` in
-- format 6. Both were constant on every measured row -- 494,384 in
-- `event_content` alone, all `sequence_no=1` and `integrity_state='verified'`
-- -- and no (owner, relation_kind) pair ever repeated, so the sequence
-- distinguished nothing. Ordered multi-part content is a real capability and
-- would restore the column as part of the key; verification state belongs with
-- a verifier that can report a state other than 'verified'.
CREATE TABLE event_content (
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  content_id TEXT NOT NULL REFERENCES content_objects(id) ON DELETE CASCADE,
  relation_kind TEXT NOT NULL,
  start_offset INTEGER CHECK (start_offset IS NULL OR start_offset >= 0),
  end_offset INTEGER CHECK (end_offset IS NULL OR end_offset >= 0),
  PRIMARY KEY(event_id, relation_kind)
) WITHOUT ROWID;

CREATE TABLE source_record_content (
  source_record_id TEXT NOT NULL REFERENCES source_records(id) ON DELETE CASCADE,
  content_id TEXT NOT NULL REFERENCES content_objects(id) ON DELETE CASCADE,
  relation_kind TEXT NOT NULL,
  PRIMARY KEY(source_record_id, relation_kind)
) WITHOUT ROWID;

CREATE TABLE tool_result_content (
  tool_result_id INTEGER NOT NULL REFERENCES tool_results(id) ON DELETE CASCADE,
  content_id TEXT NOT NULL REFERENCES content_objects(id) ON DELETE CASCADE,
  relation_kind TEXT NOT NULL,
  PRIMARY KEY(tool_result_id, relation_kind)
) WITHOUT ROWID;

CREATE TABLE artifact_content (
  artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
  content_id TEXT NOT NULL REFERENCES content_objects(id) ON DELETE CASCADE,
  relation_kind TEXT NOT NULL,
  PRIMARY KEY(artifact_id, relation_kind)
) WITHOUT ROWID;

CREATE TABLE processing_runs (
  id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(id),
  policy_digest TEXT NOT NULL,
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
  -- The instant the vendor reported for the call. `source_` marks it as a
  -- vendor-supplied time, following `source_mtime`; no vendor reports an end,
  -- so there is no matching column.
  source_started_at REAL,
  UNIQUE(session_id, source_call_id)
);

CREATE TABLE tool_results (
  id INTEGER PRIMARY KEY,
  invocation_id TEXT REFERENCES tool_invocations(id) ON DELETE CASCADE,
  result_event_id INTEGER REFERENCES events(id) ON DELETE SET NULL,
  sequence_no INTEGER NOT NULL DEFAULT 1 CHECK (sequence_no > 0),
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
  content_digest TEXT,
  metadata TEXT CHECK (metadata IS NULL OR json_valid(metadata)),
  UNIQUE(project_id, artifact_kind, relative_path, uri, repository_object_id, content_digest)
);

CREATE TABLE event_artifacts (
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
  operation TEXT NOT NULL CHECK (operation IN ('read','create','modify','delete','execute','mention','unknown')),
  PRIMARY KEY(event_id, artifact_id, operation)
) WITHOUT ROWID;

CREATE TABLE mapping_diagnostics (
  id INTEGER PRIMARY KEY,
  source_id INTEGER REFERENCES sources(id),
  session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
  event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
  -- Granularity, not severity: which *part* of the input a diagnostic is
  -- about. `severity` beside it carries how much it matters. The column was
  -- named `level` through format 5, which reads as an ordering and made
  -- summing its values look meaningful when it overstates loss.
  granularity TEXT NOT NULL CHECK (granularity IN ('source','record','field')),
  severity TEXT NOT NULL DEFAULT 'info'
    CHECK (severity IN ('info','warn','error')),
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
CREATE INDEX idx_events_tool_name ON events(tool_name) WHERE tool_name IS NOT NULL;
CREATE INDEX idx_events_source_record ON events(source_id, source_record_locator);
CREATE INDEX idx_events_interaction ON events(interaction_id, sequence_no);
CREATE INDEX idx_events_source ON events(source_id);
CREATE INDEX idx_sources_uri_revision ON sources(source_path, source_revision);
CREATE INDEX idx_sessions_project ON sessions(project_id);
CREATE INDEX idx_sessions_project_path ON sessions(project_path);
CREATE INDEX idx_sessions_parent ON sessions(parent_session_id);
CREATE INDEX idx_sessions_entity ON sessions(session_entity_id);
CREATE INDEX idx_sessions_observation ON sessions(observation_id);
CREATE INDEX idx_sessions_source ON sessions(source_id);
CREATE INDEX idx_sessions_model_param ON sessions(session_model_param_id)
  WHERE session_model_param_id IS NOT NULL;
CREATE INDEX idx_events_entity ON events(event_entity_id);
CREATE INDEX idx_model_turns_model_param ON model_turns(model_param_id)
  WHERE model_param_id IS NOT NULL;
CREATE INDEX idx_project_locations_project ON project_locations(project_id);
CREATE INDEX idx_workspace_bindings_project ON workspace_bindings(project_id);
CREATE INDEX idx_source_records_source ON source_records(source_id, source_sequence);
CREATE INDEX idx_content_digest ON content_objects(content_digest);
CREATE INDEX idx_event_content_content ON event_content(content_id);
CREATE INDEX idx_source_record_content_content ON source_record_content(content_id);
CREATE INDEX idx_tool_result_content_content ON tool_result_content(content_id);
CREATE INDEX idx_artifact_content_content ON artifact_content(content_id);
CREATE INDEX idx_tools_name ON tool_invocations(canonical_tool_name);
CREATE INDEX idx_artifacts_project_path ON artifacts(project_id, relative_path);
CREATE INDEX idx_event_artifacts_artifact ON event_artifacts(artifact_id);
CREATE UNIQUE INDEX idx_model_params_identity
  ON model_params(
    coalesce(provider,''), coalesce(model_line,''),
    coalesce(model_generation,''), coalesce(model_version,''),
    coalesce(model_gradation,''), coalesce(model_variant,''),
    coalesce(model_name_exact,''), coalesce(model_revision,''),
    coalesce(reasoning_effort,''), coalesce(speed_tier,''),
    coalesce(service_tier,''), coalesce(request_tier,''), coalesce(mode,'')
  );
CREATE INDEX idx_model_params_line ON model_params(model_line)
  WHERE model_line IS NOT NULL;
CREATE INDEX idx_model_params_gradation ON model_params(model_gradation)
  WHERE model_gradation IS NOT NULL;
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
  ON artifacts(project_id, artifact_kind, content_digest)
  WHERE content_digest IS NOT NULL;
CREATE INDEX idx_correlations_subject ON correlation_assertions(subject_kind, subject_id);
