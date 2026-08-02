# Codess design decisions

This document records the functional design and research direction behind
CoSchema v4 and cross-vendor investigation. `CoSchema.md`,
`schema/coschema/contract.json`, and `schema/coschema/sqlite/schema.sql` are the
authoritative logical description and executable layout.

The immediate goal is reliable ingestion and comparison of recent, active work
from Claude Code, Codex, and Cursor. Exhaustively finding every historical
session or repository is less important than preserving evidence, mapping the
three vendors consistently, rebuilding reproducibly, and supporting mixed
queries.

## 1. Decisions and priorities

### Current design foundation

1. **Keep two public compatibility versions.** Version the Codess software and
   a durable CoSchema store-format package. Record implementation and upstream
   versions as provenance, but do not operate seven release trains.
2. **Build immutable baselines rather than migrating derived data in place.**
   Build a new snapshot, validate it, then atomically make it current. Preserve
   the previous snapshot and the exact Codess software identity that reads it.
3. **Separate source evidence, normalized entities, and SQLite layout.** Vendor
   records and mappings belong in vendor documents; functional meanings belong
   here; SQLite tables, indexes, types, and SQL belong in the physical schema
   document and DDL.
4. **Add source, ordering, time-provenance, and lineage concepts.** A session ID
   and timestamp are not sufficient to explain where a row came from or how its
   events should be ordered.
5. **Model an interaction as a graph of events.** One user request can produce
   several model turns, tool calls and results, harness messages, subagents,
   user-input requests, and replies. Do not force that into alternating
   `user`/`assistant` messages.
6. **Prioritize active, owned projects and cross-vendor evidence.** Topical
   directory, ownership, meaningful source records, activity, and mapping value
   all matter. Repository recency alone is a poor selector.

### Engineering and evidence principles

This section is the central statement of how Codess is designed and how design
choices become implementation. Detailed entity, storage, operational, and
research rules remain in their respective sections below.

| Principle | Present application | Continued enforcement |
|---|---|---|
| Preserve source designations and add normalized classifications | Events retain source system, record type/subtype, locator, source status, and mapping trace alongside common Event, actor, role, origin, and status values | Every new vendor field or record shape requires a named mapping or an explicit diagnostic; normalization never erases the source value |
| Keep classification, filtering, search, validation, and authorization distinct | Adapters classify; selectors and content policy filter; typed search matches normalized projections; preflight and acceptance validate; explicit mutation commands authorize writes | Interfaces and reports name which operation occurred and never use a recommendation, search miss, or validation result as implicit authorization |
| Select scope explicitly and reproducibly | Project locations and source systems are selected before Session, time, Event, or content predicates; saved results retain canonical requests and snapshot/package/policy identity | Stable Project-ID/catalog selectors replace path-only setup while preserving paths as observed provenance |
| Separate durable identity from location | Projects use UUID identities; Sessions, Events, Sources, and records use namespaced stable IDs; paths/worktrees/workspaces remain locations or bindings | Relocation and repository/worktree consolidation update bindings without rewriting historical evidence |
| Treat evidence, normalized storage, and analytical derivatives as separate authorities | Vendor Sources and raw objects remain evidence; immutable per-Project CoSchema snapshots are normalized authority; exports, DuckDB, Parquet, notebooks, and search indexes are derivatives | Derived formats carry Project, snapshot, source, observation, processor, and limitation provenance and never become a second vendor decoder |
| Preserve occurrence and interaction structure | Ordered human, harness, model, agent, subagent, tool, MCP, lifecycle, and context Events remain distinct and are grouped into Interactions and Model Turns | Grouping, repetition analysis, and correlation retain constituent stable IDs and support lossless expansion |
| Make loss explicit and bounded | Sanitization, redaction, suppression, truncation, and externalization record policy, original length, completeness, and derivation evidence | A normalized search miss never proves source absence; exact evidence resolution is a separate operation |
| Prefer observation to inference and grade unavoidable inference | Exact vendor values remain nullable; inferred Interaction boundaries and correlations record method, confidence, and diagnostics | New inferences require a versioned method, evidence references, evaluation data, and no identity rewrite |
| Build immutable snapshots and rebuild derived data | Ingest builds and validates a new snapshot before atomic promotion; schema/mapping changes rebuild rather than mutate accepted rows | Copy-forward is reserved for non-regenerable curation and must still produce a new snapshot with explicit lineage |
| Bound resources and stream large evidence | Source/Event/content ceilings, JSONL streaming, paged SQLite backup, zstd streaming, row/byte query limits, and progress/RSS observations are implemented | Lower bounds remain optional selection heuristics; upper bounds remain default safety controls with explicit reviewed overrides |
| Build domain interpretation and reuse mature primitives | Codess owns vendor decoding, mapping, identity, provenance, and typed research behavior; it reuses SQLite, JSON, CSV, Git, zstd, Unicode, regex, and maintained digest implementations | Add a runtime dependency only for a measured missing primitive or two implemented workflows sharing a stable boundary |
| Keep one authority per concern | Designs owns functional rationale, vendor documents own upstream facts, CoSchema owns logical records, DDL owns SQLite layout, CoPlan owns work and gaps, and Operations owns procedures | Repartition or link duplicated material instead of creating another overlapping document, schema model, registry, or wrapper |
| Validate boundaries in proportion to consequence | Field-state diagnostics preserve usable malformed records; preflight checks decoding and temporary writes; acceptance checks fixed-point values; exact evidence checks revision equality | Tests include hostile shapes, large/skewed data, cross-vendor fixtures, multi-store scope parity, atomic failure, and representative real snapshots |
| Measure before optimizing or adding infrastructure | Cursor selection markers, progress phases, storage allocation, RSS, query limitations, and coverage are measured | Alternative indexes, SQLite bindings, graph/search services, dataframe engines, and new hashes enter the core only after a benchmark and lifecycle analysis |

### Accepted removals and corrections

- `release_value` is removed from v2. Its packed integer encoding was
  not a general ordering for SemVer, vendor build identifiers, dates, channels,
  or nonnumeric releases. Retain exact version text and parse into a
  version-specific structure only where a comparison is needed.
- Do not use `Code` versus `IDE` as the meaning of session `type`. Products now
  share storage and code across CLI, IDE, desktop, API, and agent packaging, and
  sessions may concern research, documentation, operations, or review rather
  than code. Use separate product, surface, and purpose dimensions.
- Do not interpret an archive flag as completion. Archive is a vendor lifecycle
  or storage state with vendor-specific semantics.
- Do not treat `assistant` as a model identifier. It is at most a source-format
  content role; the actor and model configuration are separate.
- Do not classify every skill invocation as a slash command. Preserve how the
  invocation was represented and normalize command and skill concepts
  independently.

## 2. Versioning and immutable baselines

### Two release versions and two processing profiles

Seven independently managed component releases would create ceremony without
useful compatibility. Maintain two public release versions and record two
small processing-profile versions with each build:

| Managed version | Meaning | Changes when |
|---|---|---|
| `software_version` | Released Codess application, currently `0.2.3` | CLI, reader, writer, adapter, or query behavior is released |
| `store_format` | Durable package containing the common logical schema, SQLite layout/DDL, constraints, and normalized taxonomies | A stored baseline can differ in structure or defined meaning |
| `decoder_version` | Normalization/filter profile, currently `0.2` | The same supported source records would be selected, classified, or decoded differently |
| `validator_version` | Acceptance interpretation, currently `0.2` | Checks, severity, or policy semantics change even though stored rows do not |

Use a lasting format identifier such as `codess.coschema` plus a small monotonic
`format_version`. The complete format package contains the logical field
definitions, canonical DDL, taxonomies/lookup values, required indexes, and
validation fixtures. Its files should have a reproducible package digest. A
reader declares the store-format versions it supports; compatibility is tested
against fixtures rather than inferred from Codess release numbers.

The package can change in a disciplined manner without inventing another
public version for each layer:

- a meaning, required field, relationship, taxonomy, or incompatible layout
  change advances `format_version`;
- a purely operational SQLite index change can update the package digest and
  software release without making old data unreadable; advance the format only
  if exact physical reproducibility or reader assumptions require it; and
- a taxonomy is part of the store contract. If a future taxonomy must evolve
  independently at high frequency, store its vocabulary ID in the data then,
  rather than paying that complexity now.

The decoder and validator values are compact behavior dates, not independently
distributed packages. They are repeated in store metadata, snapshots, reports,
and validation policy requirements. Everything else is recorded provenance,
not a separately governed release:

| Recorded fact | Why retain it |
|---|---|
| `software_revision` | Exact Git/build identity, including dirty state |
| adapter implementation identity | The software release/revision and adapter name already identify shipped mapping code; add a separate adapter package version only if adapters become independently distributed |
| `source_format` and observed harness version | Upstream evidence used for support decisions; these are properties of input data, not Codess versions |
| Python, SQLite, and platform versions | Reproduction and diagnosis; the store package may declare a minimum SQLite capability, but the SQLite runtime is not another Codess release train |
| snapshot ID, policy/configuration digest, and source fingerprints | Identify the exact baseline contents without pretending they are schema versions |

For example, decoder 0.2 retains Codex reasoning summaries and classifies
duplicate UI envelopes separately from unknown ignored records. It produces a
new immutable snapshot without requiring a new CoSchema number: the rows still
obey format 4. A schema or incompatible taxonomy change advances the store
format. This preserves the useful distinctions without exposing seven release
trains.

Per-vendor logical schemas are not separate common schemas. Vendor documents
describe upstream formats and mappings into CoSchema. A vendor-specific staging
database remains a physical implementation detail. If a vendor adapter later
ships independently, its package may acquire one version then; do not design
that release process prematurely.

### Durable encoding

Encode the store contract at three deliberate levels:

1. Codess SQLite files use fixed `PRAGMA application_id = 0x434F4445`. This permanently marks
   the file family and lets readers reject unrelated SQLite databases quickly.
2. Put the integer CoSchema `format_version` in `PRAGMA user_version`. This is
   the fast physical compatibility check and remains readable from the SQLite
   file header.
3. Repeat `format_id`, `format_version`, package digest, decoder/validator
   versions, `created_by` software, and snapshot identity in `store_meta`; put
   the same contract plus hashes and provenance in the external manifest.

The repetition is intentional: SQLite header fields survive detachment,
`store_meta` is descriptive and queryable, and the manifest can be inspected
without opening any database. Validation must require them to agree. The fixed
application ID and monotonic format integer are the lasting encoding; the
package digest identifies the exact DDL/taxonomy/fixture revision without
creating another human-managed version number.

### Names versus authoritative metadata

Do **not** make a database filename or directory name the authoritative version
record. Encoding every version and provenance fact in a path produces long names,
rename churn, and false confidence when a file is copied. Keep a stable current
location and store authoritative values in both:

- a snapshot manifest, readable without opening SQLite; and
- a small `store_meta` relation inside every database, so a detached file is
  self-describing.

A useful physical layout is:

```text
<project>/.codess/
├── current.json                    # points to one immutable snapshot
└── snapshots/
    └── <created>-coschema<format>/
        ├── manifest.json
        ├── sessions_cc.db
        ├── sessions_codex.db
        ├── sessions_cursor.db
        └── raw/
```

The directory suffix is a human hint only. `manifest.json` and `store_meta`
are authoritative. Keeping vendor names in current DB filenames is reasonable
because it identifies a physical partition; putting mapping or schema versions
in every DB filename is not. A future single database can replace the
per-vendor files without changing the logical model.

### Snapshot contract

Each immutable snapshot should record:

- `software_version`, `store_format`, package digest, software revision, build
  timestamp, Python and SQLite versions, and platform;
- the exact configuration and filtering policy that affects inclusion;
- source identities, sizes, mtimes, content hashes where captured, and adapter
  results or rejection reasons;
- database and sidecar hashes, counts, integrity-check results, and validation
  diagnostics;
- the parent baseline, if any, as lineage rather than as an instruction to
  mutate it; and
- the exact command or reproducible recipe used to build it.

Build into a new temporary directory, close all databases, run integrity and
mapping checks, finalize hashes, make the directory immutable by policy, and
atomically replace `current.json`. Never partially update the current baseline.

### Rebuild versus migration

Normalized transcripts are derived data, so **rebuild is the default**. An
in-place migration can preserve old mapping mistakes, lose raw distinctions,
and make rollback ambiguous. Rebuild from source or a captured raw sidecar when
the logical schema, mapping, or taxonomy changes.

Migration is justified only for information that cannot be regenerated, such
as manual curation, review decisions, annotations, or stable project identity.
Keep that information in a small separately versioned catalog and import it
into a new baseline. For an unusually large corpus, an explicit copy-forward
operation may be implemented, but it must create a new snapshot, retain the old
one, and identify every transformed source row.

Prior baselines remain accessible in one of two ways:

1. the current reader advertises and tests read-only compatibility with that
   store format; or
2. the manifest identifies the Git revision, lockfile, release artifact, or
   environment needed to run the matching older reader.

The writer must refuse an unsupported current store rather than silently
opening or upgrading it.

## 3. Documentation and code boundaries

Keep four layers distinct:

| Layer | Contains | Does not contain |
|---|---|---|
| Functional model (`Designs.md`) | Entity meanings, relationships, invariants, vocabularies, selection policy | SQLite types, index names, SQL |
| Vendor documents (`CCSchema.md`, `CodexSchema.md`, `CursorSchema.md`) | Upstream records, evidence, vendor semantics, mapping and limitations | Claims that a vendor field is universally meaningful |
| Logical schema (`CoSchema.md` and `schema/coschema/contract.json`) | Common fields, nullability, cardinality, identity and lineage | SQLite-specific optimization |
| Physical schema (`schema/coschema/sqlite/schema.sql` plus a layout document) | Tables, columns, SQL types, constraints, indexes, pragmas, file partitioning | Product behavior and vendor interpretation except as comments/links |

Code should mirror this boundary: vendor readers and mapping profiles, common
domain records and validation, then a `storage/sqlite` implementation. SQL
column names such as `session_pk` should not leak into application concepts
such as “session identity.” Query code should target a storage interface or
versioned read model, not repeat vendor mapping rules.

Indexes are physical access paths, not functional fields. After the logical
schema and representative mixed queries are fixed, the layout should normally
enforce/index these lookup shapes:

- unique source-system plus vendor-session identity;
- unique session plus `sequence_no`, and source plus record/block position;
- event lookup by session order and by non-null occurrence time;
- source lookup by normalized URI/path and source revision/fingerprint;
- tool invocation lookup by session/source call ID and normalized tool name;
- artifact lookup by project plus relative path or content identity; and
- parent/causation, interaction, model-turn, and parent-session foreign keys.

Do not add indexes for every JSON key or speculative filter. Record actual query
plans and corpus cardinality in the physical-layout review. Repeating a full
`source_file` string on every event is neither a substitute for a Source entity
nor a good indexing strategy.

## 4. Core entities and relationships

These are logical concepts, not a commitment to one table per item.

### Source

A **Source** is a bounded unit of upstream evidence inspected by Codess: for
example one Claude or Codex JSONL transcript, one Cursor SQLite database, or one
API export. It answers “what evidence did this normalized record come from?”

A Source is not a vendor, project, session, or code file merely mentioned in a
chat. One source may contain one session, as transcript files commonly do, or
many sessions, as a Cursor database does. A session may also be reconstructed
from several source revisions or files.

Source identity has two levels:

- a logical source identity: source system plus URI/path or upstream identity;
- an observed source revision: size, mtime, content fingerprint where captured,
  observation time, and extraction status.

If a file changes, it remains the same logical source but yields a new observed
revision. Normalized records link to the revision and source record position so
their lineage is reproducible. A missing source value means no normalized
source link was established; diagnostics must say whether evidence was absent,
unsupported, invalid, redacted, or not retained.

### Interaction versus turn

An **Interaction** is a user-intent grouping inside a session. It starts with a
direct user request or another evidenced initiating input and contains the
events performed to pursue that request: model output, tool calls/results,
harness actions, subagent work, clarification requests, and clarification
replies. It answers “which user goal was this work serving?”

An interaction is broader than a model call. It can contain many model calls
and tool cycles. A harness request for more input and the user's answer normally
remain in the same interaction. A later independent request starts another.
Where a vendor does not expose boundaries, the grouping is nullable or marked
as inferred with method/confidence; it must not be presented as upstream fact.

**Turn** is too overloaded to use unqualified. Vendors may call a whole
user-to-assistant cycle, one inference, or a tool loop a “turn.” In the common
model use **Model Turn** (or eventually **Inference**) narrowly: one evidenced
request to a model and its emitted response/requested actions. A tool result may
lead to another Model Turn within the same Interaction. Preserve any vendor
`turn_id` and vendor meaning separately. If the source does not expose model
invocation boundaries, do not manufacture Model Turns merely by alternating
message roles.

Example:

```text
Interaction: "Fix the failing parser test"
  Model Turn 1: proposes inspection and requests file/test tools
  Tool calls/results: reads files and runs the test
  Model Turn 2: proposes and requests an edit
  Tool call/result: applies the edit
  Model Turn 3: reports verification
```

### Actor

An **Actor** is the identifiable producer or requester responsible for an
event. It answers “who or what originated this event?” Actor is independent of
the serialized message role and of content purpose.

Actor kinds include human, model, harness, agent/subagent, skill, tool, system,
and developer. An actor can be a durable participant (the human user), a scoped
runtime instance (a subagent), or a configured service identity (a particular
model configuration). `assistant` is not an actor identity; it is an upstream
role label that may have been used for model, harness, or agent-generated
content. When the true actor is not supported by evidence, use unknown rather
than interpreting a source role literally.

Do not create actors merely because a label exists. A skill is an actor only
when evidence treats a scoped skill component as producing or requesting the
event; otherwise it is an origin or invoked resource. Likewise, `system` and
`developer` may be source content roles whose actual actor is the harness or an
unknown configuration author.

Actor, content role, and origin stay separate. For example, a harness actor can
inject instruction content with `harness_injected` origin; a model actor can
request a tool; and a tool actor can return result content.

### Artifact

An **Artifact** is a stable referent that work reads, creates, changes, or
mentions: a project-relative file, document, repository/commit state, URL,
notebook, image, generated patch, or similar object. It answers “what subject or
output did this work affect?”

Artifact identity is separate from an observation/version of its content. A
path can move, a file can change hash, and two paths can refer to the same
repository object. Record the strongest available identity and evidence:
project plus relative path, URI, repository plus commit/object ID, content hash,
or vendor object ID. Link events or tool invocations to artifacts with an
operation such as read, create, modify, delete, execute, or mention and a
confidence/source.

A transcript file can occupy two roles without conflation: it is a Source when
Codess ingests it as evidence, and an Artifact if a session itself edited or
discussed that file. A tool result body is event payload, not automatically an
Artifact; it becomes one when it identifies or creates a durable referent.

### Additional concepts

- **Project**: a stable work identity, independent of its current local path.
- **Project location**: a machine-local observed root, worktree, subdirectory,
  or vendor-reported working directory.
- **Session**: one vendor/harness conversation identity and its lifecycle.
- **Event**: an ordered observation such as content, a tool request/result,
  lifecycle change, context operation, or audit fact.
- **Tool invocation and result**: a request plus zero or more result fragments,
  correlated by a vendor call ID or inferred local identity.
- **Model configuration**: provider/model and configurable inference settings,
  referenced as a session default and optionally overridden per model turn.

Important cardinalities and lineage rules:

- A project can have many locations and sources; a source can yield many
  sessions, as Cursor databases do.
- A session has one source-system identity but may receive records from more
  than one source file or revision. Source ownership must be explicit.
- One interaction can contain many user replies, model turns, tool calls,
  results, subagent actions, and harness events. A request for more user input
  and a structured-choice reply are linked events, not evidence that the first
  interaction ended.
- Events have an authoritative per-session order and may additionally reference
  `parent_event`, `caused_by_event`, `interaction`, `model_turn`, and tool-call
  identities. These links form a graph; they are not all parent/child nesting.
- A session may reference a parent session with `session_relation_kind` such as
  `subagent`, `fork`, `resume`, or `unknown`, plus source and confidence. The
  link is nullable. Claude sidechain evidence supports some parent links;
  current Codex evidence does not justify inventing one.

## 5. Identity, vendor, product, and harness

`session_id` should never stand alone as the global identity. Several products
from one vendor can share code or storage, and the same upstream identifier can
be meaningful only within a source system.

Recommended identity dimensions are:

| Field | Purpose |
|---|---|
| `session_pk` | Internal stable key with no vendor meaning |
| `vendor_name` | Organization or ecosystem, for example `anthropic`, `openai`, `cursor` |
| `product_name` | User-facing product, for example `claude-code`, `codex`, `cursor-composer` |
| `harness_name` | Producing runtime/surface, such as CLI, desktop app, IDE extension, or agent runner |
| `storage_format` | Transcript/database family actually parsed |
| `vendor_session_id` | Exact upstream identifier |
| `source_system_id` | Namespace that makes the upstream identifier unique |

Uniqueness should be based on `(source_system_id, vendor_session_id)`, not
`(vendor, session_id)`. “Harness” is useful but can change packaging; the
source-system identity should be defined by evidence from the storage format.

### Global IDs and operational units

Cross-database IDs must not depend on a database filename, row number, inode,
or current project path. Inodes change on copy and fresh clone; paths change on
rename; both identify an observation location, not the work or conversation.
Use a versioned, domain-separated SHA-256 over the source namespace and exact
vendor ID for a session. Derive event IDs from that global session ID plus the
vendor event ID. This preserves one identity when the same vendor session is
copied or re-extracted while preventing identical vendor strings from
colliding across Claude, Codex, and Cursor. Legacy rows lacking a source-system
namespace use an explicit compatibility namespace derived from their recorded
vendor label.

Keep a separate **observation ID** for one extraction of that entity from a
specific source revision and project/workspace binding. Thus a copied session
can remain the same logical session while two extractions retain distinct
lineage. A machine ID plus canonical path may define a **location ID**, but
must never become the logical project ID. Project IDs should be minted catalog
identities with path, workspace, and repository aliases recorded as evidence.

The operation hierarchy is:

1. **Project** is the durable curation, baseline, and mixed-query unit: one
   continuing body of work, even across checkout replacement or rename.
2. **Workspace binding** attributes a vendor project/workspace identity and an
   observed local or remote location to that project.
3. **Source revision** is the atomic ingest unit: one consistent transcript,
   database snapshot, or export, yielding one or many sessions.
4. **Session**, interaction, and event are analysis/query units below ingest.

A Git repository is useful artifact and correlation evidence but is not the
universal operation unit: work may be non-Git, span repositories, or use a
monorepo subdirectory. A local directory is a mutable location. A vendor
workspace is an attribution binding. None alone replaces Project.

Replace the current `type = Code|IDE` with independent open dimensions:

- `surface_kind`: `cli`, `ide`, `desktop`, `api`, `agent`, or `unknown`;
- `session_purpose`: `coding`, `review`, `research`, `documentation`,
  `operations`, `general`, or `unknown`; and
- optional product capabilities, inferred only when evidence supports them.

These should be controlled open vocabularies: common values are documented and
validated, but unknown vendor values remain representable.

## 6. Paths, sources, and files

### Project paths

An absolute `project_path` is useful for locating a live checkout and joining
local vendor indexes. It is also machine-specific, private, unstable after a
move, sensitive to symlinks and case normalization, and ambiguous for
worktrees, monorepo subdirectories, and sessions started outside a repository.

Partition it into:

- `project_id`: stable catalog identity;
- `source_cwd`: exact vendor-provided string, if present;
- `resolved_project_root`: observed canonical root on this machine;
- `project_relative_cwd`: portable path below that root;
- `location_uri` or machine-local location record rather than a universal
  absolute path;
- `path_match_method`: `exact`, `vendor_index`, `git_root`, `ancestor`,
  `manual`, or `unknown`; and
- `path_match_confidence`, without converting uncertainty into false identity.

Git remote identity, repository UUID, or content/commit evidence can help
correlate moved checkouts, but none should automatically merge forks or
uncommitted worktrees.

For Git-backed work, repository identity is the Codess Project boundary:
exactly one Project per repository. Record every clone or linked worktree as a
Project location, including its worktree Git directory, common Git directory,
branch, HEAD, remote observation, and observation time. Vendor workspaces with
their own directories remain workspace bindings and locations under the same
Project. Their independent directories, session purposes, activity, or branches
do not justify additional Project IDs. A common Git directory is definitive
local evidence that linked worktrees belong to the same Project; other clone or
remote correlations retain their evidence and confidence.

### File meanings

The current names `file_path` and `source_file` conflate different resources.
Use distinct concepts:

- `source_uri`/`source_path`: transcript or vendor database read by Codess;
- `storage_relpath`: source path relative to its configured vendor root;
- `cwd_path`: working directory reported for a session or event;
- `artifact_path`: code or document referenced by an event/tool;
- `artifact_relpath`: preferred portable path relative to a project root; and
- `observed_absolute_path`: optional local evidence when it adds value.

An event may reference multiple artifacts, so artifact relationships should
eventually be rows rather than one `file_path` column. Preserve the source path
at Source level and link events to the source record/offset instead of repeating
the same unindexed string on every event.

### Missing source and file evidence

Missing is not a single condition. Record whether a value was absent upstream,
not supported by the adapter, rejected as invalid, redacted, unresolved, or not
captured by policy. Prefer a compact diagnostic/status on the source or mapping
result rather than sentinel strings in functional fields. `NULL` means no
normalized value; the mapping diagnostic explains why when that distinction is
important.

### Validity, value, attribution, and currency

One status cannot answer every question about a discovered record. Assess these
dimensions independently before deciding what to ingest or investigate:

| Question | Suggested descriptions | Consequence |
|---|---|---|
| Is it a supported source object? | supported, malformed, unsupported, not a Session | Controls decoding and diagnostics |
| What kind of content is present? | substantive conversation, operational command/configuration, informational state, empty/noise, oversized-suspect | Controls orientation and review priority, not source existence |
| Which Project does it concern? | confirmed, probable, mixed, ambiguous, unattributed | Controls Project binding or review; storage directory alone is evidence, not proof |
| Is the Source observation closed? | stable, open-ended, truncated, unknown | Describes the observed evidence; an unanswered final prompt or recent mtime does not prove a running process |
| What was the observed runtime state? | active, idle, not loaded, system error, unknown | Requires runtime evidence and an observation time; transcript or Git recency alone is insufficient |
| Is the Project snapshot caught up? | source unchanged, source newer, repository-only change, changed global container without selected change, unknown | Controls re-ingest assessment |
| Is it useful in the current selection? | include, de-emphasize, historical-only, defer, exclude | Controls a query/cohort; it must not erase retained evidence |

Examples therefore react differently: a command-only `/model` Session is a
supported operational micro-session, not malformed drivel; a huge build log
inside a message is a supported Session with suspect/misclassified payload; a
Claude file stored under one Project but operating in another directory is
valid source evidence with ambiguous or corrected Project attribution; and a
deleted temporary directory with no snapshot is a catalog artifact to exclude,
not an invalid vendor message.

## 7. Time, ordering, and observation

### Session and event time

Store `started_at` explicitly and allow it to be `NULL`. Do not substitute a
file mtime into the same field. Suggested time facts are:

| Field | Meaning |
|---|---|
| `started_at` / `ended_at` | Vendor-supported session bounds; nullable |
| `event_at` | Vendor-supported event occurrence time; nullable |
| `source_mtime` | Filesystem modification time observed for a source |
| `file_mtime` | Filesystem modification time observed for a Project work file; Git does not store it |
| `observed_at` | Time Codess inspected the source |
| `ingested_at` | Time the normalized baseline was built |
| `commit_author_at` / `commit_at` | Git author and committer times stored in the commit object |
| `ref_observed_at` | Time Codess observed a local/upstream ref and its commit; not the time that ref moved |
| `effective_at` | Optional derived application fallback for display/filtering |
| `effective_at_basis` | `event`, `session`, `source_mtime`, `ingested`, or `unknown` |

Where needed, retain `timestamp_raw`, precision, timezone/basis, and source
field. A generic column named only `timestamp` hides whether it is occurrence,
observation, or filesystem time. Source mtime is valuable for incremental scan
and a fallback UI sort, but it is not evidence that a session started then.

### Ordering

`sequence_no` is required and is authoritative within a session/source
revision. Timestamps can be missing, equal, rounded, delayed, or emitted out of
order; they are unsuitable as the only order key. Preserve source record
position and emitted block position so one source record that normalizes into
several events remains deterministic. A useful ordering tuple is
`(source_order, record_order, block_order)`, exposed as a dense session
`sequence_no` after mapping.

Cross-session chronology remains probabilistic. Correlation queries should use
time plus uncertainty, project/artifact evidence, and source provenance rather
than manufacture a global sequence.

Manual work is a separate observation stream. A file edited after a Session
can be observed through its mtime and Git dirty/index state, but neither proves
who edited it. Git commits preserve author and committer dates, not working-file
mtimes. Local reflogs may preserve when a local ref changed. A normal Git commit
object does not record push time; Codess can only record when it observed an
upstream ref, or optionally retain a dated hosting-provider event/audit result.

Compare tool-linked Artifact operations with repository observations:
tool-linked changes are attributed to that invocation; remaining dirty/staged,
committed, or upstream changes are **Project activity**. They may be manual,
another tool, an IDE, a hook, or a background process. Record the facts and
time bases without converting them into conversation Events or guessing
authorship.

## 8. Core fields, specialized data, JSON, and “not recorded”

JSON is appropriate for sparse, evolving, namespaced vendor attributes and for
configuration whose exact keys must survive mapping. It avoids a schema change
for every rare upstream field. It is poor for stable query predicates because
key names drift, types are weak, constraints and indexes are harder to manage,
and unrelated meanings accumulate in one object.

Use four retention tiers:

1. **Core field** — common, stable, semantically defined, and regularly queried.
2. **Specialized relation** — repeated, multivalued, independently identified,
   or important to one domain such as model configuration, tool calls, artifact
   links, context operations, or status transitions.
3. **Namespaced extension JSON** — sparse vendor facts retained for future use,
   with `extension_namespace`, `extension_schema`, and version. Values must have
   documented types and must not silently override core fields.
4. **Raw-only or not retained** — exact evidence remains in the raw source or
   sidecar, but is intentionally absent from the normalized store.

“Not recorded” must therefore be precise. It can mean `not provided`,
`unsupported`, `not captured`, `redacted`, `invalid`, `derivable`, `duplicate`,
or `discarded by policy`. Vendor mapping documents should maintain a field
disposition table with source field, type, example shape, target tier/field,
mapping version, and reason. This is more useful than an unqualified “not
recorded.”

Alternatives to JSON are typed columns, child relations, a document store, or
entity-attribute-value rows. Prefer typed columns for core facts and child
relations for repeated values. EAV should not be the common escape hatch: it
moves schema problems into runtime strings and makes validation and queries
harder. JSON Schema may validate an extension document, but the external
`jsonschema` repository is only a reference/example project; it is not a reason
to make JSON Schema central to Codess.

## 9. Session lifecycle, status, and models

### Releases

`release_value` is removed. Replace ambiguous `release` with the explicit version
fields in section 2. Preserve an exact harness version string even when it
cannot be ordered. If comparisons are required, use a parser declared for that
specific vendor/version scheme and retain the original string.

### Archive and lifecycle

Use `archive_state = active|archived|unknown` plus `archive_source` and the
observed source location. Known meanings differ:

- Cursor supplies `isArchived`, an explicit product/session classification.
- Codex uses active and archived session directories. Location supplies a
  storage/lifecycle observation; active currently wins on a duplicate ID. It
  does not prove completion or deletion.
- Current Claude ingestion has no equivalent common archive evidence.

Keep normalized completion/status separate. For statuses generally, retain
both `source_status` (exact vendor value) and `normalized_status` from a small
taxonomy such as `pending`, `running`, `succeeded`, `failed`, `denied`,
`cancelled`, `incomplete`, or `unknown`, with the mapping version. This applies
to tool calls and lifecycle operations; one generic session `status` should not
collapse all of them.

### Parent sessions

A nullable parent-session link is useful for subagents, forks, resumptions, and
continuations, but these are different relationships. Store the relation kind,
source evidence, and confidence. Do not infer parentage solely from time,
similar text, archive location, or a shared project. Unresolved upstream parent
IDs may be retained as external references until their session is ingested.

### Model configuration

Model identity can change within a session. Store a session default and allow a
model-turn override. Candidate fields are:

- `provider`, `model_family`, `model_name_exact`, and optional model revision;
- reasoning/effort setting;
- speed, service, priority, or latency tier where configurable;
- interaction mode or agent mode;
- sampling parameters where actually exposed;
- context-window or capability declarations only when sourced, not guessed;
- exact source configuration in a namespaced extension.

`assistant` does not mean a model. A model is an actor with a model
configuration. A harness or agent can emit assistant-shaped records without
those records being direct model output.

Treat the candidate list as independently nullable facts, not one “model
settings” JSON object:

| Field | Meaning and maintenance | Current vendor evidence | Impact |
|---|---|---|---|
| `provider` | Exact service/provider namespace when supplied; store with reusable configuration plus occurrence provenance | Codex supplies provider in session/turn/settings records; Claude supplies service evidence in reviewed assistant usage; Cursor lacks a separate mapped provider | High for cross-provider scope |
| `model_name_exact` | Exact selected/reported string, never normalized away | All three vendors provide it in at least some mapped records | Critical for filtering/comparison |
| `model_family` | Rebuildable grouping derived from exact name under a versioned alias table | Potentially all vendors; not a source fact unless explicitly supplied | Useful, not urgent |
| `model_revision` | Exact immutable revision/deployment identifier only when the source distinguishes it | No general reviewed evidence; a model-name suffix is not automatically a revision | Leave NULL; evidence-triggered |
| `reasoning_effort` | Exact user/harness-selectable effort | Codex turn/settings records; not separately observed in current Claude/Cursor mappings | High where available; A12 |
| `speed_tier` | Exact selectable speed/latency value, separate from model name | No distinct reviewed three-vendor evidence | Leave NULL; T4 |
| `service_tier` | Exact service/priority tier supplied separately | Newer Codex settings and Claude usage evidence; not Cursor | High; retain source field/release |
| `mode` | Exact collaboration/agent/interaction mode from an identified field; never reuse sandbox or truncation “mode” | Codex collaboration mode; Cursor product mode and Claude agent/permission concepts require separate mappings | High only for demonstrated queries |
| sampling/capability/context declarations | Exact configuration or declaration, never inferred from text or model marketing | Uneven and mostly outside current local mappings | Later/evidence-triggered |

The common columns normalize formats but never erase the exact source value or
field path. `source_config` is one bounded representative configuration
observation and vendor extension, not occurrence history and not a dumping
ground for unrelated product state. Event `configuration_provenance` plus its
Source revision and record locator is the occurrence evidence. Promote a new
common field only after A12 shows exact evidence, repeatable meaning, and a
concrete query or validation need.

#### A12 configuration-provenance programme

A12 supports features rather than collecting settings for their own sake:

- **UC1/UC2:** locate Sessions and Events by source system, exact model, effort,
  or service configuration;
- **UC3:** partition engagement and volume by observed model/configuration
  without confusing a setting with utilization, cost, or capability;
- **UC5/UC7:** reconstruct which configuration governed a particular model
  response, tool decision, retry, or harness transition;
- **UC8:** compare work on the same Project across vendors while retaining
  vendor-only distinctions; and
- **UC9/UC10:** cite the exact configuration occurrence and resolve it back to
  the vendor Source record.

The implementation unit is a source-backed **configuration occurrence**, not
one Session-wide JSON blob and not an inferred “current model.” Each occurrence
records: nullable normalized fields; exact vendor values; source system,
release/profile, Source revision, record locator and field path; applicable
Session/Event/turn identity and sequence/time range; mapping profile/version;
and a field state of `observed`, `derived`, `ambiguous`, `absent`, or
`unsupported`. `derived` is initially allowed only for a rebuildable
`model_family` alias mapping. It is never used for effort, speed, service tier,
revision, or mode.

The completed current-evidence contract and maintenance triggers are:

| State | Vendor slice | Evidence and outcome |
|---|---|---|
| **complete** | Exact model occurrence on Claude, Codex, Cursor | Real Source records pass adapter, store, typed filter, and exact-evidence resolution with exact field/value and observed overrides |
| **complete** | Codex effort and service tier | Session defaults, turn overrides, and harness/runtime settings remain distinct; absent values remain NULL |
| **complete** | Claude service/model evidence | Assistant usage/model evidence is distinct from harness configuration and `assistant` role |
| **complete** | Release/harness version | Vendor tool release remains independent from model configuration and decoder support |
| **observed scope complete** | Mode | Exact observed values remain queryable without claiming cross-vendor equivalence |
| **evidence-triggered** | Family, revision, speed, sampling, context/capability declarations | Add only from direct evidence and a demonstrated query/validation requirement |

Development proceeds vertically, one field/source case at a time:

1. inventory exact local occurrences and adjacent records, including release
   boundaries and overrides;
2. state whether the value is Session default, turn/Event occurrence, harness
   setting, provider response field, or derived alias;
3. preserve the raw value/path in mapping provenance and map a normalized
   nullable value only when meaning is established;
4. add a focused adapter fixture plus one real-source assertion;
5. verify storage, query filtering, result identity, and exact-evidence
   resolution;
6. compare prior/current snapshots for `match`, `mismatch`, or `vacant`
   without making an absent optional value fatal; and
7. update the vendor schema document and supported release/profile evidence.

The first delivery order is exact model for all three vendors, Codex effort,
Codex/Claude service tier, then release provenance. Mode/family work follows
only if those core filters reveal a user need. This order maximizes UC2/UC5/
UC10 value and prevents a broad schema migration before occurrence semantics
are proven.

The implemented first vertical slice exposes all eight nullable configuration
dimensions as typed Session/Event predicates and Event result/facet fields;
overview reports their observed Event distributions. `query configurations`
uses set-based SQL to report configuration/default/turn counts plus at most
three Source-backed occurrence examples per tuple. A Model Turn inherits a
recorded Session default until an occurrence overrides it. When a vendor such
as Cursor records a model selection on the governing human bubble rather than
on later model bubbles, the writer carries that exact provenance to governed
model Events with `configuration_provenance_scope.state=inherited` and the
governing Event/locator. Direct Claude/Codex evidence has no inherited marker.

Current real-store validation found direct occurrence provenance for reviewed
Claude and Codex snapshots. A forced staged Zero400 rebuild verified inherited
Cursor selection provenance for every configured Model Turn; turns with no
governing selection remain unconfigured. No separate Claude/Cursor effort or
speed value is synthesized from model names.

Forced ingestion rebuilds selected vendor stores in a Project-local temporary
directory, runs mapping and derived correlation there, then atomically replaces
the selected working database and state before immutable snapshot publication.
This avoids delete/upsert amplification against an old indexed database. A
failed staged rebuild retains an existing working store; first-ingest partial
success and `--stop` compatibility remain tested. On Zero400 this changed the
forced apply from a 600-second timeout to an 83.7-second successful apply; the
separate mandatory preflight remained about 90 seconds.

## 10. Events, roles, commands, tools, context, and memory

### Vendor and normalized event types

Retain both `source_record_type`/`source_record_subtype` and a normalized,
versioned classification. The common taxonomy should cover the large majority
of behavior; vendor-only variants remain extensions or explicitly unmapped
diagnostics rather than forcing every upstream spelling into the common enum.

A hierarchical vocabulary is clearer than the current cross-product of
`event_type` and `subtype`. Initial families should include:

- `message.prompt`, `message.response`, `message.context`, `message.instruction`;
- `tool.call`, `tool.result`, and `tool.status`;
- `interaction.user_input_request`, `interaction.user_input_reply`, and
  `interaction.structured_choice`;
- `lifecycle.abort`, `lifecycle.archive`, and `audit.permission_decision`;
- `context.compact`, `context.inject`, and `context.remove`; and
- `memory.read`, `memory.write`, `memory.update`, `memory.delete`, and
  `memory.load`.

Compaction is a **context operation**, not automatically a memory operation.
It may produce a summary used as future context, while memory has a scope and
lifecycle beyond shrinking a context window. Model memory operations separately
with scope (`session`, `project`, `user`, or vendor-defined), target/reference,
and source evidence. Do not claim a definitive memory write when the source
only exposes a compact boundary.

When a vendor stores the compact representation, preserve its body as
communication between harness and model under the same bounded-content policy
used for other context exchanges. Keep the full source character count,
truncation state, encoding, boundary/window identifiers, and direct lineage.
Do not copy repeated replacement history into new normalized events, and do
not treat an encrypted body as absent merely because Codess cannot decode it.

### Roles are multivariate

The source roles `user` and `assistant` are repeatedly violated by harness
inputs, project instructions, skills, agent output, tool results, and developer
messages being serialized into message-shaped records. The current Codex
rollout provides a concrete discriminator: direct UI submissions have paired
`event_msg.user_message` records, while additional environment/plugin context
can be sent to the model as `response_item.message role=user` without that
pair. The envelope role is therefore evidence, not an actor assignment.

Use independent axes:

- `source_role`: the exact vendor role, retained even when it disagrees with
  the normalized actor;
- `actor_kind`: the immediate observed producer, with the core values `human`,
  `model`, `harness`, and `tool`; use `agent` only when the source exposes a
  distinct runtime participant rather than merely another model Session;
- `content_role`: `instruction`, `prompt`, `response`, `context`,
  `tool_request`, `tool_result`, `status`, `memory`, or `audit`;
- `origin_kind`: `direct_user_input`, `harness_injected`,
  `harness_delegated`, `project_instruction`, `skill_generated`,
  `agent_generated`,
  `tool_generated`, `model_generated`, or `unknown`; and
- participant/runtime identity when known;
- Interaction `initiation_kind`, independently indicating whether the
  Interaction began from direct human input, autonomous harness work,
  delegation, or unknown evidence; and
- Session relation plus parent/caused-by links for subagents, forks,
  resumptions, and delegated prompts.

These dimensions should be nullable or `unknown` when the source does not
prove them. A subagent's `user`-role task can be harness-carried and
model-authored; it must not become human merely because the receiving model API
uses `user`. Conversely, Session relation alone does not prove who authored
every Event in that Session.

No new common column is approved merely by this vocabulary. A27 first tests
whether exact `source_role` and actor evidence remain adequate in mapping
trace/metadata, which initiation values are repeatedly required, and which
runtime identities require relational projection. Only demonstrated
cross-source query predicates justify a CoSchema layout change.

The current A27 implementation applies the conservative rule at the record
boundary: Claude sidechain/agent-path and Cursor `isSubagent` user envelopes
become harness-delegated prompts while their exact vendor role remains
evidence. Current Codex protocol parent/fork/thread-source and collaboration
fields are mapped directly, but their reviewed local occurrence is still
absent and therefore fixture-backed. Missing parent evidence remains NULL.

#### Actor, activity, and configuration field programme

The proposed fields are not one schema migration. They fall into four
implementation classes:

| Concept | Source or derivation | Current representation | Next treatment | Priority |
|---|---|---|---|---:|
| Exact source role and actor evidence | Vendor record/envelope and paired-record evidence | Mapping trace or Event metadata | Audit each supported release; correct actor/origin mapping before changing layout | Critical |
| `actor_kind`, `content_role`, `origin_kind` | Normalized from exact source evidence | Common Event columns | Keep separately queryable; never derive human solely from `role=user` | Critical |
| Interaction initiation | Direct prompt, harness start, or delegation evidence | Common Interaction value, sometimes `unknown` | Refine only where the source proves delegation/autonomy | High |
| Session relation and parent | Vendor parent/fork/subagent fields | Session columns plus metadata | Map direct Codex protocol evidence and validate Claude/Cursor differences | High |
| Runtime participant ID/name/role/path | Vendor collaboration/subagent records | Vendor metadata where observed | Promote relationally only after repeated lineage queries require it | High |
| Exact tool name and namespace | Source call/invocation | Free-text tool name plus metadata | Preserve exact value; add a versioned alias/classification registry, not an enum replacement | High |
| MCP server/tool, connector, app, action, plugin, duration, result status | Codex transport event; vendor-qualified tool records elsewhere | Tool/Event metadata and transport status Event | Validate occurrence linkage; promote only frequently filtered fields | High |
| Planning, delegation, and automation class | Derived from exact tool/lifecycle shapes | Not a source fact; exact tool names remain queryable | Add a versioned derived classifier after a reviewed cross-vendor rule set | Later |
| Provider, model family/exact name/revision, effort, speed, service tier, mode | Exact vendor configuration fields; family may be normalized from exact name | Nullable independent configuration fields plus source provenance | Maintain A12 vendor/release fixtures; absence stays NULL and ambiguity stays diagnostic | High |
| Event/content/input/output lengths and truncation | Store-time observation | Common lengths plus policy/metadata, uneven for older mappings | Make truncation disposition explicit before using lengths for completeness claims | High |
| Daily/monthly counts, characters, distinct Sessions/Interactions, spans, latencies, tool totals | SQL/query derivation over selected snapshots | Typed overview result | Return the observed numbers; displays may derive ratios and percentages | High |

The test for a common stored field is repeated source availability plus a
demonstrated filter, join, ordering, or completeness need. Otherwise retain the
exact value in namespaced metadata and offer a rebuildable projection. Derived
activity facts require exact cohort, snapshot, UTC/time basis, and algorithm
identity; they are not copied into every Event row.

#### MCP evidence and outcome model

MCP support is not one boolean. Keep these evidence layers distinct:

1. **configuration** — a user file, CLI registry, installed plugin, or app
   connector says a server is available;
2. **discovery** — a harness asks for tools/resources and may learn that the
   target is empty, unavailable, or authentication-only;
3. **invocation** — a named operation with a source call ID and arguments;
4. **transport** — the harness received an MCP response or transport error;
5. **application result** — the returned body says the requested operation
   succeeded, failed, was cancelled, or is ambiguous; and
6. **use assessment** — evidence-backed description such as visualization,
   session administration, workspace control, or availability diagnostic.

Only layers 1–5 are source facts. Usefulness is a review classification and
must cite the actual operation/result. A successful transport never overrides
an explicit application error. A successful discovery never proves a target
operation occurred. Vendor copies of one source call ID across Sessions remain
separate stored occurrences but one distinct source operation for audit
counts.

#### Utilization without reading conversation meaning

Orientation queries may read byte/character lengths already stored with the
Events, but do not classify the topic or meaning of prompt/response bodies.
The primary output is the actual observation: counts, character lengths,
distinct Session/Interaction identities, timestamps/spans, tool names and
call/result totals. Ratios and percentages are display calculations over those
facts, not additional authoritative measures.

Human-inclusive daily/weekly views answer engagement questions. Vendor,
model, Project, Session, relation, tool, and monthly totals answer system
activity questions and remain meaningful without a human denominator. The two
response intervals are deliberately different: last human prompt to the last
later model output in that same Interaction approximates the tail response
window, while first prompt to that output spans the day's observed human/model
exchange window. Neither is a request latency when an Interaction contains
multiple model/tool cycles.

#### Harness telemetry and controlled transport capture

Local transcripts are the required historical source for current Codess
ingest. Harness-native telemetry is the first addition for prospective
experiments because it can label requests, turns, tools, MCP operations,
durations, and errors without retaining content by default. Codex's opt-in
OpenTelemetry and hooks provide that path.

A router/proxy can capture exact outbound request envelopes and streamed model
transport only for traffic deliberately sent through it. That is useful for
studies of request assembly, retries, stream timing, and transcript omissions,
but it is not required for the current session/investigation use cases. It
still cannot reveal server-hidden reasoning and does not observe local tool
execution unless combined with harness instrumentation. Any experiment must
state provider endpoint/configuration, capture interval, software versions,
content-retention/redaction policy, credential boundary, and mapping from
transport IDs to the local Session. Full content capture is opt-in; metric-only
telemetry is the default.

### Commands and skills

Classify input representation independently:

- `natural_language`, `slash_command`, `command_palette`, `skill_invocation`,
  `structured_choice`, `user_reply`, or `harness_instruction`;
- parsed `command_namespace` and `command_name` when syntax proves them; and
- exact invocation text in content/raw evidence.

Claude Code skills may be invoked through slash-like text or a `Skill` tool,
but a skill is not always a slash command. Codex and Cursor have their own
command or mode mechanisms. Normalize the semantic skill invocation when
known, retain its source representation, and do not infer one from a leading
slash alone if the harness treats the text as ordinary content.

### Tool names and call/result data

Tool names must remain free text because MCP servers, plugins, skills, and
vendor releases create names dynamically. A closed enum would reject real
data. Add an optional registry/alias layer with canonical name, namespace,
provider, category, and version; retain `source_tool_name` exactly. Common tools
can be seeded and validated without making the seed list exhaustive.

`tool_input` and `tool_output` are unclear when several components participate
or when a harness calls subprocess execution “tool calling.” Prefer a Tool
Invocation concept with:

- source call ID, canonical/source tool identity, requesting actor/event, and
  optional parent invocation;
- exact structured request arguments (`input_json`) plus bounded display text;
- start/end times and source/normalized status;
- zero or more Tool Result records, each with sequence, producing component,
  text/JSON/artifact reference, error evidence, and status; and
- an invocation subtype such as `harness_capability`, `mcp`, `process`,
  `subagent`, or `unknown` when supported.

The harness-mediated capability is the tool call. An OS process started by that
capability is a child execution fact, not necessarily a second tool call.
Avoid duplicating result content in both generic `content` and `tool_output`;
define one canonical payload with typed projections for display and query.

`source_call_id` is vendor free text, not a global identity. Codess preserves
the exact source value in Event metadata/raw evidence and uses a bounded
100-byte relational key. Values within the ceiling remain unchanged; longer
values retain a UTF-8-safe prefix plus the full SHA-256 digest so truncation
does not practically merge equal-prefix calls. The functional identity remains
qualified by source system and Session; the bounded call key alone is never
treated as globally unique or authenticating.

Normalization is not permission to collapse the interaction graph. Preserve
the strongest structure each source provides even when it is vendor-specific:
agent and subagent identity and lineage; harness-to-model context exchanges;
tool request, approval, status, and ordered result fragments; MCP server,
method, request, response, notification, resource, and error identities; and
child process or nested invocation relationships. A common event or invocation
type is an additional mapping over that evidence.

The minimum acceptable degradation is explicit and reviewable: retain the
source record and source classification, map the supported portion, leave
unsupported normalized fields NULL, and emit a mapping diagnostic describing
the missing specialization. Never turn an unsupported subagent, MCP, or tool
record into an undifferentiated assistant message merely to fit the common
model. Content limits may externalize or truncate a payload, but must retain
its identity, original size, media/encoding information, lineage, and
truncation or externalization state.

### Provenance checks

“Semantic goldens” was too broad: it could imply identical vendor meaning or a
Cartesian fixture matrix. “Mapping conformance” was also too narrow because
the required result includes namespaced evidence that does not map to a common
field. A **provenance check** is the plainer unit: exact source records, the
expected Codess rows, and the assertions connecting them. A *golden* is only
that checked expected output; it does not claim cross-vendor equivalence.

The active **A3** scope is deliberately smaller than everything the vendor
stores may expose. It proves only four producer classes—`human`, `harness`,
`tool`, and `model`—and the ordered exchange among them. Agent/subagent, MCP,
and context/compaction structures remain preserved where current adapters
already support them, but they are not A3 acceptance gates and do not block
UC5 or the narrowed UC7.

Conformance is prioritized by use case:

| Tier | Required cases | Use cases and exit |
|---|---|---|
| 0 | Source, Session, Event identity; order; Source locator; unsupported-shape diagnostic | Foundation for every use case; one case per source system must pass |
| 1 | Human request → harness mediation → model response/tool request → tool result → harness/model response, including absent direct links | UC5; one representative complete exchange per source system with all observed core actors |
| 2 | Tool status, ordered result fragments, permission/denial, failure, and abort evidence produced by the four scoped actors | UC7; one representative case for each behavior currently claimed for a source system |
| Later evidence-triggered work | Runtime-component lineage, context operations, release variants, malformed/ambiguous fields, attachments, and rare lifecycle shapes | Separate promotion under T1/T4 only when a recorded use case needs it; not an A3 completion condition |

Do not multiply every record type by every source system. Absence can be a
documented source-system difference rather than a missing fixture. Common
fields must agree on their normalized contract; source-specific fields and
structures must remain exact and queryable without pretending equivalence.

Each mapping check follows one reviewable path:

1. name the use-case question and exact retained Source revision/record range;
2. inventory the source entities, ordering, identifiers, and relationships;
3. write the smallest expected mapping worksheet, including intentional NULLs,
   vendor-specific retention, and diagnostics;
4. derive a privacy-safe minimal fixture without losing the structural shape;
5. compare adapter output and stored CoSchema entities to the worksheet;
6. execute the relevant standard typed query and compare ordered result rows;
7. resolve at least one result back to exact fixture/retained evidence; and
8. rebuild twice when identity or ordering behavior changed.

The A3 executable contract is now complete in
`tests/test_provenance_checks.py`. Its Claude, Codex, and Cursor cases each
start at an actual vendor storage shape, run the production adapter and store
mapping, expand one status-bearing Event through the typed query API, prove all
four scoped actors occur in the Interaction, inspect retained mapping
locators/traces, and resolve the selected Event to exact live source evidence.
The cases deliberately cover both denial and failure. Broader agent, MCP, and
context variants continue under evidence-triggered mapping maintenance; they
do not reopen A3 by themselves.

The expected rows conform to these specific properties:

1. **Source identity:** exact source-system, Source revision, record locator,
   and captured/live availability are retained.
2. **Entity identity:** Session, Interaction, Model Turn, Event, tool, agent,
   and Artifact IDs are namespaced, deterministic, and never path-only aliases.
3. **Order:** source record/block order and normalized `sequence_no` reproduce
   the exchange without timestamp-based invention.
4. **Boundaries:** Session, Interaction, turn, compaction, and lifecycle
   boundaries use direct vendor evidence where available and label inference.
5. **Actors and origins:** human, model, harness, agent, tool, MCP, command, and
   injected-context contributions remain distinguishable.
6. **Relationships:** parent/child Session, call/result, permission, tool/MCP
   request/response, artifact, and multi-fragment result links survive.
7. **Values and states:** content, model/settings, status, time basis, NULL,
   empty, malformed, truncated, externalized, and unavailable states preserve
   their declared meaning.
8. **Common and source-specific fields:** common fields follow CoSchema while
   useful upstream designations and structures remain namespaced and
   queryable; a common NULL is not permission to discard source evidence.
9. **Diagnostics:** unsupported, lossy, ambiguous, and inferred mappings are
   explicit at source/record/field scope.
10. **Query behavior:** the standard use-case query returns the expected rows,
    stable IDs, ordering, completeness, and bounds.
11. **Evidence lookup:** representative result IDs resolve back to the exact
    asserted source values or clearly report changed/unavailable evidence.
12. **Repeatability:** unchanged source revision, decoder, mapping, policy, and
    schema produce the same identities and values on a second build.

### Content processing contract

Content processing is the configurable boundary between vendor evidence and
normalized query content. Vendor record shapes remain in the vendor schema
documents; persisted content and derivation entities remain in **CoSchema.md**.
Implementation wiring is indexed from **CoPlan.md §5**.

#### Source admission bounds

Minimum and maximum sizes serve different purposes, but one byte limit cannot
describe every ingestion unit:

- the minimum is an optional selection heuristic intended to avoid parsing
  historical noise; it is not a validity or safety control and can hide valid
  short records such as `y`, `1`, `go`, or `no`;
- a zero-byte Source is an empty observation, not a Session or Event. It may
  trigger stale-source replacement and an informational diagnostic, but does
  not produce an empty prompt, statement, or response;
- a textual message Event requires nonempty decoded text. Whitespace-only text
  is empty for this purpose;
- a structured Event may have no text body when its useful payload is a tool
  name/input/output, choice identifier or label, status transition, model/mode
  setting, compaction evidence, attachment identity, or another explicitly
  mapped field. Size accounting must include the canonical representation of
  those semantic fields rather than treating the Event as zero-content;
- upper bounds separately control a transcript/container file, one source
  record, one normalized payload, selected bytes for one Session or Project,
  and an exact raw capture. Cursor's machine-wide SQLite database is a vendor
  container observation, not a Project or Session payload.

The current ordinary ingest default of 20 KiB is too strong for a general
compatibility system. Curated onboarding already uses zero. The target is a
zero selection floor plus structural admission: parse tiny supported Sources,
classify zero-byte and parsed-empty outcomes without creating empty Sessions or
message Events, retain valid tiny records, and let an explicit discovery policy
request a nonzero floor.

Software 0.2.3 removes the generic 8 GiB guard from active defaults. One
versioned `codess.resource-policy/1` file now owns the implemented maximums:
256 MiB per Claude/Codex transcript, 10 GiB per Cursor SQLite container,
200,000 Events per Source, 100,000 Events per Session, and 250,000 characters
per context or compaction body. Built-ins apply when no file is supplied; a
partial file may override or disable individual limits. Environment and CLI
overrides remain compatible. Runtime and preflight reports retain effective
values and per-value provenance.

This completes the approved configuration and transcript/container separation.
Runtime and preflight reports also provide a reconciled
`resource_summary`: repeated observations of one container are counted once
for container bytes, emitted Events are additive, the largest Session is a
maximum, and process RSS is a non-additive high-water mark. The remaining
implemented boundary is:

1. report selected decoder-input bytes and measurement coverage separately
   from full container bytes; a whole selected JSONL transcript contributes
   its file bytes, while a selective Cursor observation contributes the
   serialized values selected for that Project. A missing measure is explicit
   and makes the sum incomplete rather than becoming zero;
2. report normalized SQLite-file usage and unique referenced raw-object usage
   as logical, allocated, and unique-allocated bytes. These are physical
   retained allocations, not semantic text;
3. do not estimate source-semantic pre-truncation or query-result serialization
   from retained text; neither is a current required measure;
4. add no record, Event-payload, Project-run, or raw-capture ceiling without a
   newly reviewed measured unit and failure mode;
5. classify an over-limit observation before deciding its disposition; a
   source/container admission guard stops ingest and creates a review item,
   while a legitimate oversized textual field may retain a bounded searchable
   projection plus original length/truncation/link evidence, and an external
   object may retain only an excerpt and reference;
6. keep approved boundary, override, streaming-abort, and pre-commit tests
   green.

Do not sum repeated source-observation container sizes as retained or selected
Project data. Report physical retained allocation, distinct source revisions,
and selected semantic payload as separate quantities.

Exceeding a byte limit is not synonymous with discarding content. The
implemented source/container guard runs before parsing, leaves the source
untouched, records the observed/maximum unit and likely
misclassification/legitimate-oversize alternatives, and does not advance
ingest state or partially commit a replacement. Field bounding is different:
the searchable projection may be truncated only after type/classification
review, with full source length, truncation state, and recoverable source or
sidecar reference. Query byte limits truncate only returned inline content,
not stored Events. The remaining gap is to make ordinary prompt/response/tool
field truncation metadata as explicit and uniform as current context bounding;
Any demonstrated completeness defect belongs to **CoPlan A6/A9**.

#### Measurement and assessment method

Resource work uses a common measurement vocabulary so an investigation cannot compare
container allocation with semantic text or count one Cursor database once per
Project:

| Unit | Measurement method | Attribution and reconciliation |
|---|---|---|
| Source container bytes | Filesystem `st_size`; for SQLite also main/WAL/SHM and backup output separately | One physical revision/object observation; never multiply by selected Projects |
| Selected decoder-input bytes | Whole-file bytes for a selected JSONL transcript; selected serialized value bytes for a Cursor Project selection; unknown for a source shape without a streaming counter | Source observation → mapped Session/Project candidates. Report measured/total observation coverage and never equate an incomplete sum with zero |
| Source semantic payload | UTF-8 bytes and characters of authorized source values before truncation, with raw type and field path | Record/field; do not add container overhead |
| Retained Event payload | UTF-8 bytes and characters per distinct searchable field: content, tool input, tool output, artifact/attachment excerpt, and specialized context | Event → Session → Project run; a value copied into two physical columns is counted once by a declared logical-field rule |
| Result payload | Canonical serialized row/result bytes plus separately reported retained inline-content bytes | Query request/result; distinguishes network/file output from searchable content |
| Raw retained allocation | Unique content-addressed object sizes grouped by object ID plus manifest allocation | Count one object once even when referenced by many snapshots |
| SQLite allocation | `page_size * page_count`, freelist bytes, table/index bytes through `dbstat` when available, and logical payload totals | Store and snapshot; do not infer semantic payload from allocated pages |
| Working memory | `resource.getrusage` process RSS high-water mark for routine evidence; `tracemalloc` for Python attribution; Memray only for focused native/Python profiles | Phase, Source, composer, Session, and Project run; RSS is a high-water observation, not deallocation proof |

Existing tests and observations already cover useful pieces:

- `tests/test_resource_policy.py` checks configured maximum resolution,
  precedence, disabling, and file SHA-256;
- `tests/test_snapshot_raw.py` checks streamed capture, compressed-object sizes,
  verification, and manifest/store allocation identities;
- `tests/test_cursor_cohort.py` and Cursor adapter tests check selected markers,
  cache boundaries, backup/capture behavior, and bounded selection;
- `tests/test_scale.py` checks ordered bounded queries across 60 independent
  stores without attaching or materializing the corpus; and
- baseline reports and progress phases retain per-Source/Event counts, source
  bytes, phase time, and the observed 19,661-Event composer/approximately
  531-MiB RSS case.

They do not yet attribute allocations inside composer construction, distinguish
Python/native/SQLite memory, measure selected/pre-truncation source payload,
or measure result-serialization amplification. Runtime/preflight reports now
measure retained searchable Event characters and UTF-8 bytes while treating an
identical `content`/`tool_output` tool-result projection as one logical value.
If performance work is resumed, the profiling sequence is:

1. add content-free per-phase counters and RSS sampling to existing progress
   boundaries;
2. use `tracemalloc` on synthetic fixture cases to attribute Python objects;
3. use SQLite `dbstat`, page/freelist totals, and query plans for physical
   allocation and read amplification;
4. use one retained real large composer and one large typed result for focused
   Memray profiles only after the routine counters identify a phase; and
5. compare before/after code changes with identical snapshots, requests, and
   bounds.

Deeper real-corpus profiles are approved only when routine counters identify a
specific phase or outlier. Ordinary rebuilds are not repurposed as uncontrolled
profiling experiments, and no additional resource limit is promoted without
the staged evidence below.

Routine measurement is streaming. Histograms use fixed, versioned logarithmic
or domain buckets and bounded top-N outliers; an explicit corpus-analysis run
may compute exact sorted percentiles in SQLite/DuckDB. Every distribution
records the selected Project/snapshot set, source systems, decoder/validator/
policy versions, count of NULL/empty/nonempty/malformed values, units, and
observation time.

Assessment always follows an outlier back to exact evidence before proposing a
limit. Review in this order:

1. wrong Project/Source scope or a global Cursor container attributed as
   Project content;
2. binary/base64/archive/database content misclassified as conversation text;
3. one vendor record incorrectly treated as a Session or one field duplicated
   across normalized columns;
4. genuine large prompt, response, context, tool input/output, attachment, or
   log;
5. repeated but individually valid records; and
6. implementation buffering or serialization amplification.

The resulting classification is `expected`, `large_but_valid`,
`mapping_defect`, `source_misclassification`, `duplicate_accounting`,
`resource_amplification`, or `needs_review`, with evidence identity and notes.
A percentile alone never promotes a ceiling.

#### Resource measurement, admission, and limit architecture

**Measurement precedes limits.** Versioned observations and counters belong at
Source admission, vendor-record selection, normalized Event emission,
transaction commit, raw capture, snapshot creation, query serialization, and
process-phase completion. Counters flow forward in small aggregates; content
bodies do not enter telemetry. Reconciliation checks prove child units sum to
their parent where definitions permit and explicitly label non-additive
container/RSS observations.

**P15 decides semantic admission independently of size.** A textual
prompt/response/statement/context requires at least one meaningful decoded
character after the declared normalization policy. Tiny values remain valid.
Bodyless structured tool, status, permission, lifecycle, mode, and attachment
records may be valid when their canonical structured payload is nonempty.
Missing preferred fields, irregular numbering, or alternate record shapes are
informational mapping/compliance facts, not automatic rejection. Rejected
message emission still retains Source-record identity and a reason.

**Only evidence-backed ceilings are eligible.** The approved Source/Event/
Session/context defaults and their overrides are implemented and tested. No
additional warning, opt-in, or built-in limit programme is pending. A new
candidate begins with an observed failure mode, exact unit, recovery path, and
boundary tests in a newly scoped A item.

#### Cursor architecture and performance programme

Implementation and benchmarking under this programme are currently postponed
as **CoPlan P22**. The design remains the restart point after a measured
user-facing latency/RSS defect or the next changed large capture; routine work
must not optimize from the historical high-water observation alone.

Current understanding separates five components that must not be timed as one
opaque “Cursor ingest”:

1. **cheap assessment:** catalog and Project activity, selected workspace/
   composer markers, source-container metadata, and prior accepted revision;
2. **consistent access:** an online SQLite backup only when selected evidence
   changed or a forced run requires it;
3. **selective decode:** SQL reads for the selected workspace/composer keys and
   their required bubbles, not a decode of every record in the machine-wide
   database;
4. **normalization:** per-composer ordering, identity/deduplication, Event,
   Interaction, and Model-Turn construction; and
5. **write/finalize:** transactional replacement, deferred once-per-Source
   orphan pruning, indexes, diagnostics, resource reconciliation, and snapshot
   validation.

Selection and SQLite writes are streamed, and once-per-Source pruning removed
a repeated full-store scan. The remaining dominant risk is that normalization
still materializes a complete composer while establishing canonical order,
deduplication, and Interaction membership. A large real composer has already
shown that the resulting RSS can greatly exceed retained payload size.

Measure load across orthogonal ranges rather than selecting one “large
Project”:

| Axis | Required range |
|---|---|
| Cursor container | small fixture; ordinary current store; large global store with a small selected cohort |
| Selected cohort | zero, one, several, and many composers/workspaces |
| Composer shape | many small; one very large; tool-heavy; repeated-state-heavy; sparse/partially mapped |
| Change shape | no change; append-only; changed existing bubbles; removed composer; forced full selection |
| Payload shape | short text; bounded tool results; large-but-valid text; rejected oversized/misclassified record |
| Output state | empty target; replacement of an existing Source; repeat fixed-point rebuild; rollback/failure injection |

Every benchmark records exact input revision and selection marker, software/
schema/decoder/policy versions, selected row/key/byte counts, emitted and
retained Events/characters/bytes, phase wall and CPU time, peak RSS, SQLite page
and write changes, cache/backup decisions, and final identity/count
reconciliation. Medians and dispersion over repeated warm and cold runs matter
more than a single fastest time. No benchmark includes transcript bodies in its
telemetry.

The review and experiment order is:

1. confirm call graph, ownership, transaction boundaries, and which phase still
   owns a complete composer;
2. add/verify counters at the five boundaries above and reproduce the retained
   large-composer case plus diverse small/multi-composer cases;
3. inspect query plans and allocation profiles only in the measured dominant
   phases;
4. try one change at a time: incremental ordered grouping, bounded
   deduplication state, stateful Interaction construction, removal of duplicate
   payload representations, and write-batch sizing;
5. compare each attempt against the identical snapshot/selection and reject it
   if canonical order, stable IDs, rollback, diagnostics, or fixed-point output
   changes; and
6. retain the change only when it lowers the targeted resource measure without
   shifting an unexplained cost to backup, serialization, SQLite, or a later
   phase.

Outcome review uses a compact table per experiment: hypothesis, exact input,
before/after phase measures, correctness checks, unexpected effects, decision,
and follow-up. The immediate goal is bounded memory proportional to the
incremental grouping state rather than total composer Event count. Deeper
allocation work remains evidence-triggered; it does not block ordinary
correctness fixes or the already approved streaming path.

#### Observed text-length distribution

A read-only 2026-07-29 inventory covered 40 current per-source-system working
stores, 199 Session entities, and 182,479 Events from active catalog locations.
It measured characters and UTF-8 bytes without copying content. A subsequent
fixed-point rebuild and retention pass brought current supported-format
normalized Source revisions to SHA-256. Four deliberately unrebuilt CoSchema-3
catalog pointers contain older revision labels and are ineligible for exact
current-package queries. The size distribution below remains a dated content
measurement; its hash inventory does not describe current supported-format
state.

| Retained field | Nonempty occurrences | p50 characters | p99 characters | p99.9 characters | Maximum characters |
|---|---:|---:|---:|---:|---:|
| Event body | 94,698 | 237 | 2,000 | 2,443 | 148,780 |
| Tool input | 66,427 | 193 | 5,582 | 18,847 | 72,875 |
| Tool output | 58,218 | 480 | 2,000 | 2,000 | 2,000 |

The source-length view explains why retained and source sizes must remain
distinct:

| Event kind | Source p99 characters | Source p99.9 characters | Source maximum | Retained maximum |
|---|---:|---:|---:|---:|
| Prompt | 1,920 | 8,971 | 148,780 | 148,780 |
| Response | 6,112 | 12,943 | 31,609 | 2,000 |
| Tool result | 40,070 | 208,864 | 1,160,389 | 2,000 |
| Context or compaction | below 44,866 | below 44,866 | 44,866 | 44,866 |

No zero-length normalized prompt, response, statement, or context body was
observed when selected by normalized `event_kind`. Fifty-four prompts and two
responses contained one through four characters, confirming that semantic
nonemptiness—not an arbitrary byte minimum—is the useful lower bound. Some
legacy compatibility `event_type` values call tool results `user_message`;
those must not be counted as empty prompts.

#### Resource-bound status

The transcript and context rows are implemented through the resource policy.
The other rows are design examples, not approved defaults or pending tasks:

| Unit | Candidate | Status and handling |
|---|---:|---|
| Textual prompt, response, or statement | at least one non-whitespace decoded character | Do not emit an empty message Event; retain an informational Source-record diagnostic |
| One decoded vendor record | 4 MiB | Recognized binary/attachment/external content goes directly to raw or sidecar handling; otherwise stop before an unbounded JSON/text allocation |
| Injected context or compaction body retained for search | 250,000 characters | **Implemented default.** Retain bounded searchable text plus full character length and truncation state |
| Tool input retained for search | 128 KiB | Preserve structured identity and parameters; externalize an oversized body |
| Tool output or external/log excerpt retained for search | 32 KiB | Prefer a bounded head and tail rather than indexing a multi-megabyte listing |
| All searchable fields in one Event | 512 KiB | Prevent several individually valid fields from defeating the Event bound |
| One transcript file | 256 MiB | **Implemented default.** Stream records; Cursor's machine-wide SQLite container has its own 10 GiB guard and bounded selection queries |
| Retained searchable payload in one Session | 64 MiB warning | Orient and investigate before increasing; do not allocate the Session as one in-memory object |
| Retained searchable payload added by one Project run | 256 MiB warning | Require reviewed override or narrower scope; cumulative Project storage remains a separate physical-allocation report |

The current largest retained Session is approximately 20 million characters;
the largest Project is approximately 72 million. The candidates therefore
provide headroom while making accidental binary ingestion, giant terminal
listings, and component-sized context dumps conspicuous. They do not authorize
raising the current 2,000-character adapter excerpts; a ceiling is not a target.

#### Policy entry points and order

Ingest accepts `--content-policy JSON` and `--strict-mapping`.
`--strict-mapping` fails a source on unsupported or lossy source mappings; it
is independent of content transformation.

A content policy may act during byte decoding, before normalization, and after
normalization. Rules apply in this order:

1. global policy;
2. every matching scope in declaration order; and
3. built-in adapter storage bounds.

Scopes can match `vendor`, `record_type`, `event_kind`, `phase`,
`project_path`, and `repo_path` by exact value or shell-style wildcard.
The machine-readable example is
`schema/content-policy.example.json`; it demonstrates syntax and is not a
recommended privacy policy.

#### Supported transformations

A policy can declare:

- character encoding, decode-error behavior, and Unicode normalization;
- minimum and maximum character bounds;
- suppression expressions for known hostile content;
- privacy expressions with configurable replacement;
- vocabulary blanking; and
- topical include or exclude expressions.

Every applied action contributes to a processing trace. The normalized store
can identify policy and processor versions, input/output content identities,
actions, rejection reasons, and derivation links without copying transformed
bodies into general metadata.

#### Evidence and safety contract

Suppression, redaction, blanking, topical filtering, and truncation are lossy.
Normalized content must therefore expose completeness and processing evidence;
a query miss against a bounded projection does not prove absence from the
source.

Exact raw capture is governed separately and occurs before transformation.
External content references are accepted only through vendor-specific validated
locators. A retained hash, length, or `storage_class=not_retained` record is
evidence about an input, not the input body itself.

The common event vocabulary remains extensible, while `source_records`,
`content_objects`, typed link tables, and `processing_runs` preserve durable
identity and lineage. Structured artifact updates are source records with typed
operation/target parameters and optional before, after, patch, or diagnostic
content links. See **CoSchema.md** for their cardinality and persistence
semantics.

### Operational progress contract

Operational progress is distinct from content-processing lineage and Python
DEBUG logging. Long-running ingest stages emit `codess.progress/1` events to
stderr as they happen and retain the same bounded, content-free events in the
runtime or preflight report. Events name start, periodic progress, completion,
skip, and failure boundaries; fields are restricted to identifiers, phase
durations, counts, sizes, status, and exception class. They must not carry
transcript or raw-source content.

Interactive progress is enabled by default. `--no-progress` suppresses the
stderr renderer without disabling collection, so automation can reserve stderr
for exceptional conditions while retaining the same structured evidence.
Retention is a rolling bounded window, not a first-events buffer: failures and
the latest Project remain diagnosable in large batches. Project reports isolate
status and diagnostic deltas, and processed counts are named separately from
stored totals. Runtime evidence summaries are explicitly bound to a snapshot
ID and may be reused only for an unchanged matching snapshot.

Cursor needs finer boundaries because a selected composer is read, decoded,
ordered, and deduplicated before its normalized events are written. The trace
therefore distinguishes selection-marker work, raw SQLite backup/restore and
compression, composer read-buffer heartbeats, composer writes, and snapshot
promotion. This makes a slow but advancing run distinguishable from a stopped
one without making DEBUG logging mandatory. The bounded event list is evidence
for performance diagnosis, not authoritative source or normalization lineage.
Routine no-op ingest does not refresh derived artifact assertions or rewrite
identical catalog projections. Derived processing is triggered by normalized
vendor changes or material catalog-binding changes and participates in the
same snapshot decision.

## 11. Raw evidence and sidecars

Do not put full `source_raw` blobs in the main query database. They enlarge
backups, mix sensitive evidence with normalized search data, and make retention
and redaction all-or-nothing. Raw capture should be explicit and policy-driven.

The architecture is a hybrid: normalized SQLite plus a raw sidecar. Converted
JSONL is not the raw format — it cannot preserve a Cursor SQLite source
byte-for-byte and may discard unknown fields, ordering, encoding, or database
structure.

### `codess.raw/1` format

Treat this as part of the CoSchema store package, not another regularly managed
release train. `codess.raw/1` is a fixed format namespace; create `/2` only if a
future reader cannot understand the layout.

```text
~/.codess/raw/codess.raw-1/
├── objects/
│   └── sha256/ab/<uncompressed-content-sha256>.zst
└── locks/                         # writer coordination; not snapshot content

<snapshot>/
├── manifest.json
├── raw-manifest.jsonl             # references objects used by this snapshot
└── raw/objects/...                # present only in a sealed export
```

An object contains the exact bytes of one consistently observed source
revision, compressed with Zstandard. Its identity is the SHA-256 of the
**uncompressed** bytes. The raw manifest also records the stored-object hash,
compression, sizes, and media/storage format so corruption can be distinguished
from a changed source. Never use the original filename as the object path.

Each `raw-manifest.jsonl` begins with one header record, followed by one record
per observed Source revision. A representative source record is:

```json
{
  "record_type": "source_revision",
  "source_revision_id": "srcv_...",
  "source_system": "cursor-composer",
  "storage_format": "sqlite",
  "source_locator": "cursor-user-global/state.vscdb",
  "observed_at": "2026-07-13T22:00:00Z",
  "source_mtime_ns": null,
  "source_size": 42819584,
  "availability": "captured",
  "capture_method": "sqlite-backup",
  "consistency": "transactional-snapshot",
  "object_id": "sha256:<uncompressed-content-sha256>",
  "stored_sha256": "<compressed-object-sha256>",
  "compression": "zstd",
  "uncompressed_size": 42819584,
  "stored_size": 7182640,
  "redaction": "none"
}
```

Numeric values above illustrate JSON types, not defaults. Omit or use `null` for
an unknown fact; never write a fabricated mtime or size. Define the JSONL record
schema and allowed values in the CoSchema package. Keep machine-sensitive
absolute paths in a private location mapping where possible; the portable
locator should be relative to a configured source root.

`object_id` is location-independent. A resolver finds it first in a sealed
snapshot and then in the configured central raw store; the manifest does not
hard-code a machine path.

Capture rules differ by storage format:

- Claude/Codex JSONL and exports: capture the exact file bytes after a stable
  size/mtime check or open-file snapshot; record whether the source changed
  during capture.
- Cursor SQLite: use the SQLite backup API or a vendor-safe read transaction so
  WAL contents are included consistently. Copying only the live main DB file is
  not a valid raw snapshot.
- API/stream sources: preserve the exact received body or framed records plus
  transport metadata needed to interpret them; do not claim byte identity with
  server-side data that was never received.

The normalized Source revision stores record locators such as JSONL line/byte
position or Cursor table/key identity. Whole-file Zstandard objects are enough
initially because ordinary queries use normalized SQLite; reparsing can stream
the raw object. Add chunking or a seek index only after measured random-access
need.

### Capture and portability modes

- `none`: normalized data only; manifest records that raw evidence was not
  retained.
- `reference`: record source identity/fingerprint and external location without
  copying bytes. Useful locally but not independently reproducible.
- `capture`: place exact bytes in the central content-addressed store and pin
  them from the snapshot manifest.
- `seal`: hardlink, reflink, or copy all pinned objects into an exported
  snapshot so it is self-contained; verify every hash afterward.

The central object store deduplicates a global Cursor database and identical
transcripts instead of copying them into every project store. Garbage
collection may remove only objects unreferenced by retained manifests. Apply
permissions, encryption, retention, and deletion policy to raw objects
separately. A redacted derivative is a different object/class and must never be
labeled exact raw evidence.

### Local evidence threat model

The trust boundary is the local user account and its storage. A raw zstd object,
its JSONL manifest, and a normalized SQLite store are all ordinary mutable local
files. Corrupting a raw object is therefore not intrinsically harder than
changing the SQLite database. Their different roles determine which invariants
can be checked, but not their resistance to a local writer: raw verification
checks exact stored and decompressed bytes, while SQLite verification adds
structural, relational, package, and semantic invariants.

The model covers accidental truncation/bit rot, interrupted writes, stale or
mislinked revisions, importer defects, hostile source bytes, unauthorized local
reading, and post-capture modification. It does not claim protection against a
process with the same account authority that can rewrite an object, its
manifest, the SQLite store, and every expected digest. A digest checked only
against metadata stored beside the file detects inconsistency, not authorship.
Authentication against that adversary would require a separately protected or
signed manifest, and confidentiality requires permissions and/or encryption.

| Risk | Current control | Remaining boundary |
|---|---|---|
| Accidental raw-object corruption | Complete stored SHA-256, complete uncompressed content SHA-256, sizes, zstd decoding, and bounded two-pass verification | These checks establish consistency with the adjacent manifest, not who wrote either file |
| SQLite corruption or unintended mutation | Immutable snapshot hash, package/policy hashes, `quick_check`/integrity and foreign-key checks, semantic digest, and rebuild comparison | A same-authority writer can alter the DB and its adjacent manifest together |
| Source changes during capture | Stable-stat JSONL read or transactional SQLite backup including committed WAL state | A reference-only source can later disappear; sampled routine fingerprints can miss adversarial changes |
| Malicious collision input | SHA-256 content addressing for complete retained bytes | Hashing neither sanitizes hostile content nor authenticates its producer |
| Unauthorized disclosure | Separate raw/query storage and configurable retention | Digests provide no secrecy; installations must restrict directory/file modes or encrypt at rest |
| Unbounded allocation | Streaming capture and verification in fixed chunks; SQLite backup is paged | SQLite itself and temporary backup allocation still require disk-space monitoring |

Recoverability, archival value, and whether another copy exists are retention
and backup-policy questions, not differences in the local corruption threat.
They must not be used to imply that one of these file types is tamper-resistant
or to postpone removal of redundant current captures.

Digest roles remain deliberately separate even though current Codess digests
use one algorithm. Software 0.2.1 and later use SHA-256 for routine update
fingerprints,
durable raw identity, `codess.raw/1`, snapshot manifests, and established
global IDs. A full-file update fingerprint reads all bytes; a bounded sampled
fingerprint still does not become complete content identity merely because its
algorithm is SHA-256. The transition verifier was removed after all current
supported-format normalized Source revisions were rebuilt under SHA-256. Four
unrebuilt CoSchema-3 catalog pointers retain older mtime/size revision labels
and fail the current package contract before live-reference verification.
Unsupported historical digest labels require a rebuild, not silent acceptance.

BLAKE3 would be a good high-throughput cryptographic content digest
only through a maintained implementation such as the Rust-backed Python
package—not a local reimplementation. The maintained `blake3` 1.0.9 package is
installed in the current development pyenv but is not a declared Codess
dependency and is not used by the implementation.

Applying BLAKE3 everywhere is rejected. Existing global IDs, content-object
IDs, `content_sha256` columns, raw object paths, manifests, package digests,
accepted baselines, and saved result identities explicitly use SHA-256.
Replacing those would require a new format or multi-digest compatibility
model, would invalidate stable IDs and deduplication paths, and would force a
complete rebuild or long-lived dual lookup. Small canonical JSON and identity
hashes have no material throughput problem.

A targeted BLAKE3 experiment remains reasonable only for a future new
large-byte role. Actual Source and raw-object work may be disk-, SQLite-,
compression-, or memory-bandwidth-bound, and automatic threading increases CPU
contention.
The implemented disposition is:

1. generate algorithm-labelled SHA-256 revisions for complete, sampled,
   main-plus-WAL, Cursor selected-row, and combined-cohort fingerprints;
2. invalidate the Cursor selected-marker cache at its format boundary and
   rebuild every current supported-format normalized Source revision under
   SHA-256;
3. reject unsupported digest-labelled live-reference comparisons instead of
   retaining permanent compatibility algorithms;
4. do not compute BLAKE3 in addition to mandatory SHA-256 unless a second
   consumer needs it, because dual hashing adds work without removing the
   existing identity pass; and
5. introduce `codess.raw/2` or a new digest field only if measured large-object
   savings justify a durable compatibility change.

The default retention invariant is one retained revision of a shared logical
source when an uncompressed revision is at least 1 GiB. Multiple such current
revisions require the explicit `--keep-comparison-revisions` selection and are
reported with their source locator, snapshots, sizes, and revision IDs.
Content-addressing removes byte-identical copies but cannot deduplicate SQLite
backups that genuinely differ. Because current snapshots are immutable, an
existing conflict must be resolved by rebuilding the affected Projects against
one deliberately captured source cohort and then applying validated pruning;
deleting an object still named by a current manifest would falsify that
snapshot.

Routine storage accounting is a derived observation, not part of CoSchema.
Each invocation records database allocation/utilization, entity counts,
content/session skew, snapshot/raw allocation, thresholds, and a delta from the
preceding observation. Retention selection precedes garbage collection. The
current operating policy uses one mark per Project: the central `current.json`
snapshot. Current raw manifests form the object mark set; every other snapshot
and unmarked raw object is reclaimable. Reviewed catalogs validate current
selections rather than pin old bytes. A stale selected catalog or active local
pointer blocks pruning; historical parent IDs remain lineage labels without
retaining storage. Vendor source stores and current Project working databases
are never cleanup targets. Obsolete pre-package `working-archives` are a
separate opt-in class and may be removed only after a current central replacement
validates.

Vendor discovery indexes are operational caches, not source evidence or
CoSchema entities. The Codex cache records only transcript location,
fingerprint, session identity, cwd, timestamp, and optional line count. Its
root-list signature prevents reuse across a different active/archive setup;
each refresh enumerates names, reuses unchanged entries, reparses changed/new
files, and drops missing ones. Scan and ingest share the refreshed inventory in
memory so Project count does not multiply vendor-tree traversal. Deleting the
cache changes performance only and must never affect results.

Token observation caching follows the same replaceable-cache rule but starts at
the complete selected-source-set boundary. Exact path/size/mtime fingerprints
guard reuse of a previously derived monthly result. Any membership or
fingerprint change recomputes all selected sources, preserving Claude's
cross-file message deduplication without persisting a second detailed token
record model. Per-file cached records are justified only if measurements show
that source churn makes this simpler invalidation policy too expensive.

Cursor does not require a whole-database decode for routine operations. Resolve
workspace IDs from bindings, select composer headers through the
`(workspaceId,isSubagent,isArchived,recency)` index, and select each composer's
`bubbleId:<composer-id>:` half-open key range through the unique key index.
Compute row and byte inventories in SQL with `COUNT(*)` and `length(value)`;
decode JSON values only for selected ingest or content inspection. This supports
one workspace, session, or composer even when another composer is very large.

Keep two distinct portability products:

- an exact raw Cursor source is one transactionally consistent SQLite backup,
  including live WAL state, stored once by content identity and referenced by
  any number of Project snapshots; and
- a selective logical export contains identified headers and chosen key/value
  rows. It is smaller and reparsable for that selection but is a derived export,
  not byte-identical vendor evidence.

Exact backup reuse is safe only when a functional revision guard covers the
workspace headers and composer bubble ranges actually consumed by ingestion
and resolves to an already verified raw object. Each Project marker is read in
one SQLite transaction, including committed WAL state, and hashes exact header
fields, all selected keys and lengths, and bounded 512-byte value edges. The
marker is captured before backup and saved as the Project state guard: a
selected change during or after capture therefore causes a later mismatch and
conservative recapture. Main-file mtime/size is both insufficient in WAL mode
and too sensitive to unrelated Cursor state. Content addressing deduplicates
stored bytes after backup, while the metadata-only cohort cache avoids backup
entirely when the combined selected marker is already represented. The
selected-marker cache is a narrower prefilter: it may reuse the last markers
only for the identical Project/workspace selection when main and WAL inode,
size, and nanosecond mtime remain stable across the cache check. A difference,
unstable observation, cache miss, or `--force` returns to one shared SQLite read
transaction and the complete bounded header/key/length/edge scan. Neither cache
is evidence or a second source copy. The bounded capture design is a chunked
pipeline: SQLite backup or stable source file → incremental content hash →
streaming zstd writer → incremental stored hash → atomic content-addressed
rename. Temporary output lives on the destination filesystem, is removed on
failure, and is published only after source-stability and size/hash checks.
Peak memory is governed by configured buffers rather than source size. The
fresh standalone SQLite backup is also the query input, avoiding an immediate
decompression pass. The actionable implementation and acceptance evidence are
**CoPlan A5**.

### Retiring or replacing a local directory

Claude Code and Codex transcripts live in machine-local vendor stores, and
Cursor workspace/global databases are also local evidence. Normalized working
databases remain below the selected project's `.codess/`, but retained format-3
snapshots now live in the stable central Project catalog. A Git clone restores
neither vendor sources nor its local binding/cache. Deleting or pruning a
vendor store still makes every reference-only baseline unreproducible.

Before removing, renaming, or replacing a directory:

1. ingest with `capture` or `seal`, never only `reference`;
2. validate the new snapshot, its raw objects, and a repeated semantic fixed
   point under the recorded software/package identity;
3. register the replacement location and any vendor workspace/path alias
   against the same stable project identity;
4. copy or promote the validated baseline to the durable project catalog; and
5. verify query access through the new binding before deleting the old tree.

Format 3 implements step 4 at
`~/.codess/projects/<project-id>/snapshots/<snapshot-id>/`, with project-local
`.codess/` reduced to working cache, pointer, and bindings. The retirement tool
enforces captured evidence and replacement-location read verification; it does
not remove the old tree.

## 12. Project inventory and selection policy

### What the inventory is

The central registry should be a reviewable **catalog**, not an accidental log
of every scan/test path and not proof that a project deserves ingestion. Keep
these dimensions separately:

- `topic`: the first controlled grouping such as `Code`, `Claude`, `Spank`,
  `WP`, or `ZK`, derived initially from the `~/Work` subtree but editable;
- `ownership`: `own`, `reference`, `external`, `mixed`, or `unknown`;
- `activity_state`: `active`, `dormant`, `archived`, or `unknown`;
- `selection_state`: `priority`, `candidate`, `fixture`, `deferred`,
  `excluded`, or `needs_review`;
- source evidence per vendor, meaningful session counts, last observed event,
  last source change, and mapping diagnostics;
- repository evidence such as Git root, last commit, worktree state, and remote,
  without assuming a recent upstream commit means recent personal work; and
- explicit review notes and decisions, kept separately from reproducible scan
  facts.

Local project identity and remote repository identity are separate. For each
remote, store a dated observation: configured URL, checked time, result
(`available`, `not_found`, `access_denied`, `redirected`, or `unchecked`),
observed canonical URL, visibility/archive facts when available, and checking
credential/profile identity without secrets. A 404 may mean deletion, rename,
transfer, or inaccessible private data. It must never delete or disqualify a
local project automatically. Old lists of repositories in the `wkarshat`,
`fear-ai`, `tearodactyl`, or `zerocurrencycoin` accounts/organizations are
candidate evidence only until checked again.

Scanning updates observed facts. A review operation updates curation. Ingestion
uses an explicit saved selection policy or selection set. Tests must always use
an isolated registry; temporary test projects must never enter the personal
catalog.

`~/.codess/projects.json` is authoritative for stable Project identity,
locations and their lifecycle state, path aliases, curation, and vendor
workspace bindings. Project-local `.codess/project.json` binds the checkout to
that identity; `.codess/source-links.json` records explicitly approved
historical vendor identities after moves. `ingested_projects.json` remains an
operational path-keyed summary of recent scan/ingest/query observations, not a
second identity catalog. Each retained CoSchema snapshot projects the relevant
Project, location, and workspace-binding facts so it remains interpretable on
its own.

The user-facing Project listing should join, rather than denormalize, these
authorities: Project identity/location from `projects.json`, current and
retained extraction metadata from verified snapshot manifests/pointers, and
reverse Assembly membership from `assemblies.json`. This gives “show all
extractions for this Project” without copying changing snapshot or Assembly
arrays into the identity record. It also makes stale operational telemetry
prunable independently. The first A19 catalog command must provide
machine-readable Project ID, name, location state, curation, current snapshot,
available vendors/source systems, and Assembly count/filter fields.

### Catalog-wide Project selection

Catalog-wide selection must resolve stable Project identities before opening
stores. Five interface shapes are useful, but they are not equivalent:

| Alternative | Use | Disposition |
|---|---|---|
| Repeated `--project-id ID` | Exact, scriptable, unambiguous selection | Implement first as the primitive selector |
| `--project-set FILE` | Reviewed or generated saved list of Project IDs plus optional expected snapshot IDs | Implement second; canonicalize and hash the resolved set |
| Catalog predicates such as topic, ownership, activity, selection state, and source availability | Dynamic cohorts for orientation and Assembly construction | Implement through a typed selector object; display the resolved Projects before mutation |
| `--all-current` | Compatibility spelling for an eligible broad catalog cohort | Query convenience only; inspect `catalog status` first. Never means source-fresh, every scan-history path, or every historical snapshot |
| Repeated `--dir` and `--dirs` | Location-oriented compatibility and ad hoc local work | Retain as aliases that resolve through Project bindings; warn on ambiguity |

Do not use `ingested_projects.json` as an `all` selector and do not create a
mutable global Event database merely to select Projects. The path telemetry
contains missing, obsolete, scan-only, and temporary locations; a global Event
copy would conflate selection with storage authority.

Implementation proceeds through one shared resolver:

1. use the implemented read-only `catalog status` result joining catalog
   identity, current compatibility, active locations, and curation; source
   refresh stays a separate observed status;
2. use the implemented resolver for exact IDs, `codess.project-set/1`, and the
   compatibility broad-cohort selector, returning canonical Project/snapshot
   inputs;
3. add typed catalog predicates and compatibility-path resolution without
   weakening the stable-ID result;
4. require mutation-oriented ingest/onboarding to display and hash the resolved
   set, pass preflight, and re-resolve it unchanged immediately before apply;
5. make A19 Assemblies consume the same resolver and persist the resolved
   `(project_id, snapshot_id)` inputs rather than reimplementing catalog logic.

Vendor discovery evidence stays vendor-specific: Claude supplies project paths
through `sessions-index.json` and project storage slugs; Codex supplies `cwd`
in `session_meta` under active/archive roots; Cursor joins
`workspaceStorage/*/workspace.json` to `composerHeaders.workspaceId` and then
selects the corresponding composer key ranges. None of those vendor locators
alone authorizes curation or proves repository identity.

### Reference collections and topical defaults

Most known OSS/reference collections are below path segments `sOSS`, `Claws`,
and `ZKs`. Current code already excludes the exact prefixes `Spank/sOSS`,
`Claw/Claws`, and `ZK/ZKs` from ordinary candidate discovery (and also has
other review/reference exclusions). Preserve those defaults, generalize the
catalog classification to recognizable collection segments, and allow an
explicit per-project override. A path inside a reference collection is not
owned/active merely because its upstream repository committed recently.

Treat `~/Work/Github` as dormant/reference by default: its local collection is
currently dated by months. A project there requires an explicit review override
to enter the active corpus even if copied or maintenance commits make Git dates
look recent. Continue reporting reference-collection counts separately so they
remain available for fixtures and additional candidates without dominating
rankings.

### Selection order

Rank candidates in this order:

1. owned, active projects with recent meaningful sessions from Claude, Codex,
   or Cursor;
2. projects with evidence from two or more vendors, because they directly test
   schema mapping and mixed queries;
3. recent sources that exercise unsupported records, new harness versions, or
   mapping regressions;
4. compact fixtures selected to cover a vendor feature or source format;
5. dormant owned projects retained for compatibility; then
6. external/reference repositories only when they add a concrete format or
   cross-vendor test.

Filters should include minimum supported harness version **per vendor**, event
recency, source mtime/change size, session/event volume, mapping success,
ownership, topic, and selection state. Apply equivalent filters during scan,
ingest, and query, but retain the raw observed values so policy can change.
Set a vendor minimum only from tested format/capability evidence, not by making
version strings numerically comparable. An unknown version should be flagged
for review and attempted safely; it should not be silently treated as either
supported or obsolete.
WP projects are currently dormant/deferred, not permanently abandoned.
`Code/jsonschema` is external/reference and should be considered only as a
small compatibility/example case, not a priority corpus.

### Review catalog authority

Candidate membership, observations, and review dispositions are live data, not
design prose. The maintained active-work CSV may seed an on-demand candidate
review, but the dated July 14 checked-in JSON was deleted. Neither an old
GitHub list nor this document is authoritative for current paths, remotes,
session counts, or approval.

The catalog keeps observed facts, policy recommendations, and human decisions
separate. Remote state is a dated observation and missing remotes do not
invalidate local owned work. Reference collections and dormant trees remain
non-active by default unless a concrete compatibility or correlation need
changes their classification.

Current candidate review and onboarding needs enter the central registry under
**CoPlan T5**. Broad discovery is not a standing programme; a concrete missing
cohort or vendor receives a focused A item. Machine catalogs and receipts
retain the actual Project set.

### Candidate review, selection, and batch onboarding

Candidate review is a **curation view over observations**, not another vendor
scanner and not ingest authorization. It consumes `run_scan()` results, an
optional maintained candidate CSV or catalog, and bounded local repository
observations. It must not duplicate Claude, Codex, or Cursor discovery.

Authorization has four separate levels:

1. scan, candidate refresh, recommendation, and preflight are read-only and
   authorize no persistent ingest;
2. a direct `ingest --dir/--dirs` without `--validate` is an explicit operator
   authorization to mutate only the named Project locations, selected source
   systems, and declared policy; it does not mark the Project curated or
   approved for the compatibility corpus;
3. curated onboarding requires a saved explicit review decision, successful
   preflight, an unchanged selection/package check, and the separate
   `catalog onboard --apply` action; the review decision makes the Project
   eligible, while `--apply` authorizes the mutation; and
4. acceptance and publication are separate: `baseline apply`, `freeze`, and
   reviewed catalog replacement authorize promotion only after their
   validation gates.

Automation receives no broader authority from a recommendation, `consider`
outcome, successful preflight, or prior approval. It must invoke the explicit
mutation action over a canonical resolved selection.

Recursive repository discovery prunes dependency, build-output, cache,
environment, and VCS-internal descendants (`build`, `debug`, `dist`, `out`,
`target`, `node_modules`, `.cache`, `.ccache`, `.pyenv`, `.git`, and comparable
standard directories). Metadata-derived vendor paths beneath those descendants
are excluded by the same shared policy. An explicitly supplied root remains
eligible, permitting intentional inspection without making incidental nested
artifacts candidates.

Discovery defaults to the current directory, not the filesystem root or the
entire home directory. Broad system roots such as `/`, `/var`, `/usr`,
`/System`, `/Library`, `/Users`, and `/Volumes` are rejected. A deliberately
scoped descendant (including a real project under `/var` or `/opt`) remains
eligible.

The compatibility action is `candidate-review`; its primary command-family
location is `catalog candidates`. From the source tree, invoke both through
`codess`. The source-tree compatibility spelling is `python -m main`. The
interface is read-only unless an explicit output/update
option is given:

```text
codess catalog candidates \
  [--dir ROOT ... | --dirs ROOTS_FILE] \
  [--candidate-csv FILE] [--catalog FILE] \
  [--source cc,codex,cursor] [--days N] \
  [--git none|local] [--since DATE] \
  [--discover-git --max-depth N] [--check-remotes] \
  [--policy FILE] [--selection STATE] \
  [--ownership VALUE] [--topic VALUE] \
  [--format table|jsonl|catalog] [--out FILE] \
  [--update-catalog FILE]
```

Defaults are `--git local`, no recursive Git discovery, no network remote
check, table output to stdout, and no catalog mutation. `--discover-git` is a
bounded, explicit search for repositories with no vendor-session evidence; it
stops descending a branch as soon as it finds a repository boundary, so nested
vendored repositories and workspaces are not promoted as peer Projects. It
never changes the index-led semantics of `scan`. `--check-remotes` records a
dated network observation including configured and observed URLs, result, and
credential/profile identity without secrets. A missing or inaccessible remote
never excludes a local Project.

Each candidate keeps facts and decisions separate:

- identity: an actual UUID Project ID only after catalog binding; otherwise a
  reproducible `candidate_key`, observed path, logical name, and topic. A
  candidate path fingerprint never masquerades as a Project ID;
- vendor evidence: sources, sessions, events, bytes, time range, harness/source
  shape, mapping diagnostics, and last observation;
- local Git evidence: repository root, HEAD, last commit time, commits since
  cutoff, dirty state, configured remote URL, and observation time;
- curation: ownership, activity, selection state, review decision
  (`approved`, `deferred`, or `excluded`), reviewer, notes, and reviewed time;
  and
- policy result: `consider`, `defer`, or `exclude`, with named rules and reasons.

The established catalog receives a separate computed annotation view rather
than another identity list. Labels are non-exclusive and evidence-backed:
selection eligibility (`included`/`not_selected`), reviewed compatibility
membership (`core`), current package readability
(`query_ready`/`incomplete`), measured size (`large`), raw-evidence mode
(`limited`), direct inconsistency/review evidence (`suspect`), and current
source-system plurality (`multi_vendor`). Each label carries its reason.
Thresholds and definitions are part of the dated report; derived counts are
not written back into the identity catalog.

Policy results are recommendations. They never overwrite a human decision or
become equivalent to `approved`. This replaces the opaque historical
`worthy = sessions >= 2 or MiB >= 1` rule with a versioned policy whose inputs,
outcome, and rationale are inspectable. A default policy should prioritize
owned active work, meaningful recent sessions, cross-vendor evidence, mapping
coverage, and explicit compatibility gaps. Size alone is insufficient.

Git/activity review is worth retaining because vendor-session recency and code
activity answer different questions. It can reveal an active owned repository
whose session path is missing or misattributed, distinguish a dormant corpus
member from current work, and expose code changes after the last captured
session. It cannot prove model involvement, ownership, remote existence, or
suitability for ingestion. It therefore belongs in candidate review, not
`scan`, the normalized database, or the ingest acceptance gate.

Dropping the old automatic worthy filter prevents unreviewed size-based bulk
ingest but loses a one-command heuristic. Preserve the useful convenience by
making recommendations reproducible and decisions explicit, then consume the
decision directly:

```text
codess catalog onboard --catalog FILE --review-decision approved \
  [--validate-only | --apply] [--source all] [--raw-mode MODE] \
  [--stop-after plan|preflight]
```

`onboard` resolves entries with the saved review decision, emits the exact Project/path/source
plan, runs non-mutating preflight, and, only with `--apply`, ingests that same
resolved plan. Its receipt contains the catalog digest, selected Project IDs
and locations, preflight results, package identity, and apply results. The
selection is not re-evaluated between preflight and apply. Existing
`ingest --dirs` remains the simple explicit-path mechanism and escape hatch;
catalog onboarding is the curated mechanism.

This reduces normal catalog onboarding to two human actions—review/decide,
then onboard—while retaining direct access to discovery, plan, preflight, and
apply for troubleshooting, CI, and audit. A first-time curator may seed a
catalog from CSV; ordinary refreshes do not rebuild that seed.

### Users, command families, and composition

Keep `scan`, `ingest`, and `query` as short daily data commands. Cluster
administrative commands by the object and decision they manage:

| User / purpose | Command family | Normal operation |
|---|---|---|
| Developer or analyst | `scan`, `query`, `candidate-review` alias | Explore without changing curation |
| Project operator | `ingest`; `catalog location ...` | Preflight/apply one Project; manage locations |
| Project operator | `refresh` | Stage a routine explicit-set or annotated-cohort refresh |
| Corpus curator | `catalog candidates|decide|onboard` | Refresh observations, decide, onboard a set |
| Release maintainer | `baseline validate|apply|freeze|verify` | Rebuild and publish a verified reviewed set |
| Evidence maintainer | `evidence gather|audit` | Refresh aggregate and vendor structural evidence |
| Schema developer | `schema compare` | Classify a proposed contract change |
| CI | `baseline verify`, preflight, versioned JSON | Run read-only or explicitly staged gates |

Users need visibility into each stage but should not have to invoke every stage
separately. Orchestrators call public operations and return one structured
report containing per-stage results; focused commands expose the same stages.

Baseline freeze and verification follow this rule. Keep `baseline verify` as a
read-only CI and diagnostic command. `baseline freeze --selection FILE`
verifies proposed members and package/policy identities before writing,
atomically replaces each catalog, rolls the pair back on a detected failure,
then verifies the written set before success. Later verification resolves each
reviewed member by exact Project ID and retained snapshot ID; it does not
silently substitute, or require equality with, the mutable current pointer.
`baseline apply` remains the expensive per-Project rebuild and fixed-point
operation. Routine `refresh` is a separate native composition: resolve an
explicit list or one annotation designator, preflight every Project, verify
unchanged selection/catalog/package fingerprints, and apply each Project
independently. It deliberately has no cross-Project rollback; its checkpointed
receipt preserves every per-Project result. Reviewed baseline publication
remains an explicit operator composition, not a pending native cross-Project
rollback feature.

`catalog status` consumes those receipts as bounded operational observations.
It scans only versioned `refresh-*.json` receipts in the registry reports
directory, ignores plan-only/malformed records, and chooses the newest
completed per-Project preflight or apply result by recorded UTC completion
time. The Project row exposes the result stage/status, receipt identity,
requested Source selection, raw mode, and resulting snapshot when reported.
The normalized status is deliberately narrow:

- `not_assessed` — no usable completed result;
- `preflight_passed` or `preflight_failed` — temporary-store validation only;
- `refresh_applied` — that Project's apply subprocess succeeded; and
- `refresh_failed` — that Project's apply subprocess failed.

These labels answer “when did Codess last attempt this Project, and what
happened?” They do not answer whether every upstream vendor store is currently
unchanged, whether Git/file activity is attributable to a harness, or whether
the Project is research-current. Those broader inferences are intentionally
not claimed. A failed newer observation supersedes an older success in status
reporting without invalidating the older immutable snapshot.

Evidence audits are capability-specific rather than symmetrical wrappers for
their own sake. Cursor feature, Codex parentage, and Claude feature evidence use
reusable audit operations that retain counts and field population but no
conversation bodies. `evidence gather` calls them once and may emit detailed
component reports plus the aggregate inventory; sequential wrapper runs are not
the normal refresh procedure.

Project-location lifecycle needs explicit complementary operations:

- `catalog location add --project-id ID --path PATH` associates an additional
  location after identity and conflict checks;
- `catalog location retire --project-id ID --path PATH` retires a location
  without inventing a replacement, requiring captured durable evidence when it
  would remove the last reproducible source location of a selectable Project.
  An explicitly excluded Project may retire its final stale location while
  retaining the Project ID and catalog disposition; and
- `catalog relocate --project-id ID --from OLD --to NEW` composes add, pointer
  installation, retained-snapshot read verification, and retirement.

Current ingest can ensure a binding for its path. The public catalog operations
provide explicit add, retire, and relocation; `retire_project.py` is a legacy
relocation wrapper because `--new-location` is required. Its disposition is
centralized in **CoPlan A11**.

### Code partition for operations and wrappers

Partition by semantic ownership and reuse, not command count:

- `src/codess/`: domain operations returning typed dictionaries/dataclasses;
  no argument parsing or terminal rendering;
- `src/cli/`: parsing, dispatch, rendering, exit-code mapping, and composition;
- `tools/`: temporary developer entry points and compatibility wrappers only;
  no unique business rules or SQL;
- `scripts/`: no unique business rules; retired compatibility entry points do
  not return here;
- `catalog/`: versioned policy, selection, review, and accepted-baseline data;
  never Python policy hidden in a script; and
- `schema/`: machine-readable contracts for those data formats.

Prefer cohesive modules over a generic `utils` bucket:

```text
codess.candidate_review       scan composition, Git observations, policy reasons
codess.catalog_operations     decisions, selection, locations, onboard receipts
codess.project_annotations    computed reason-bearing catalog review labels
codess.refresh_operations     staged routine Project refresh and durable receipts
codess.baseline_operations    preserve/archive/apply/fixed-point orchestration
codess.baseline_catalog       catalog construction, freeze, rollback, and verification
codess.evidence               common store summaries and aggregate inventory
codess.orientation_audit      independent typed-overview/SQLite reconciliation
codess.mcp_audit              occurrence and outcome audit for MCP-qualified tools
codess.vendor_audits.*        capability-specific Claude/Codex/Cursor audits
codess.schema_evolution       contract comparison and declared-change gate
codess.fileio                 file hashing and atomic versioned JSON writes
```

Adapters continue to own vendor parsing; candidate review calls `scan` rather
than adapters. Catalog operations may call baseline validation but never parse
vendor sources. CLI layers may compose operations but contain no SQL, catalog
policy, hashing, or snapshot semantics. Compatibility wrappers import one
public operation and should normally remain below roughly 50 lines.

### Cross-vendor work on the same code or document

Project-level overlap is only the first signal. To identify code or documents
worked on by more than one coding system, capture artifact relationships:

- project/repository identity and Git commit/tree before and after a session;
- artifact path relative to the project, content hash when safely available,
  and observed operation (`read`, `create`, `modify`, `delete`, `mention`);
- event/session/vendor links and time intervals; and
- confidence and evidence source, avoiding unsupported authorship claims.

Queries can then find the same project, file identity, commit range, or content
hash touched by multiple vendors. Git and tool evidence are stronger than
matching prompt text. Uncommitted changes and concurrent sessions require
explicit uncertainty; Codess should report correlation, not claim which model
authored a line without evidence.

## 13. Investigation and research direction

Codess is useful only when normalized evidence supports actual investigation.
The design therefore favors a typed, reproducible research path over a generic
natural-language-to-SQL surface. Active implementation, gaps, decisions, and
postponed work are registered only in **CoPlan.md §8**.

### Research questions the system is intended to support

| Priority | Question | Desired research result |
|----------|----------|-------------------------|
| 1 | What changed since the preceding scan, ingest, snapshot, or usage observation? | Versioned new/changed/removed entities with input and observation identities |
| 2 | Which Projects or sessions merit review? | A health/orientation summary with reasons and evidence IDs |
| 3 | What is vendor usage, reset horizon, pace, and plausible monthly total or cost? | Confidence-labelled observations separated from quota, price, and billing claims |
| 4 | What consumes storage and what is safely reclaimable? | Allocation/retention results tied to verified current manifests and dry-run selections |
| 5 | Which sessions exist for a Project, vendor, model, or period, and how large or active are they? | Typed facets and timelines with explicit elapsed-versus-derived-active duration |
| 6 | Where did a prompt, response, error, path, symbol, or topic occur? | Bounded search with content-completeness and source-availability evidence |
| 7 | Which vendors touched the same Project or artifact? | Correlation rows with stable identities, locators, confidence, and no unsupported authorship claim |
| 8 | What happened around a request, tool cycle, denial, compaction, or abort? | One canonical Interaction/Model Turn or sequence window |
| 9 | Which outcomes failed, were orphaned, or lack mappings? | Composable source/tool/status/diagnostic evidence |
| 10 | What intent, decisions, and unresolved work can be summarized? | A derived summary that cites the exact bounded evidence and processor identity |

Usage/reset/burn-rate views in
[CodexBar](https://github.com/steipete/CodexBar) and
[Claude Code Usage Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor)
are useful precedents, but Codess keeps observed counters, derived estimates,
external quota/price facts, and billed cost distinct.

### A2 precedent review: usage and activity time series

CodexBar is a useful current implementation precedent because it collects two
different families of history and does not pretend they are the same:

1. **Quota-window samples.** Each sample is an observation time, used percent,
   and optional reset boundary, grouped by provider, account identity, named
   window, and window duration. Sampling is at most hourly, histories are
   bounded to 17,520 samples per series, and provider files are atomically
   persisted as versioned JSON. Account/window identity and reset-boundary
   reconciliation prevent an apparent discontinuity from being silently
   treated as one stable series.
2. **Token and cost reconstruction.** Provider APIs supply some histories;
   Codex and Claude can also be reconstructed from known local JSONL
   locations. The local scanner caches per-file mtime, size, parsed offset,
   parser/pricing identity, normalized rows, and daily/model aggregates. It
   resumes append-only files, invalidates changed dependencies, processes
   newest files first, and applies per-file and per-refresh byte budgets.

The display layer then derives daily spend/tokens, recent totals, model and
Project breakdowns, quota history, pace, expected usage, reset countdown, and
run-out estimates. The same data can be shown in the menu, widgets, a persistent
spend dashboard, or structured CLI/dashboard JSON. “Reported” versus
“estimated” cost and selected-account ownership are material parts of the
meaning, not presentation footnotes.

A targeted review of open/closed issues and pull requests found these recurring
requirements:

- **scope and attribution:** workspace/project spend, the actual model rather
  than only the calling harness, multi-account separation, and provider-specific
  windows ([#1995](https://github.com/steipete/CodexBar/issues/1995),
  [#2350](https://github.com/steipete/CodexBar/issues/2350),
  [#2393](https://github.com/steipete/CodexBar/issues/2393));
- **time-series interpretation:** visible scoped weekly pace, restored pace
  percentage, stable reset/run-out projections, and daily/monthly history
  ([#2360](https://github.com/steipete/CodexBar/issues/2360),
  [#2348](https://github.com/steipete/CodexBar/issues/2348),
  [#2182](https://github.com/steipete/CodexBar/pull/2182),
  [#2296](https://github.com/steipete/CodexBar/pull/2296));
- **freshness and reproducibility:** stale automatic refreshes, menu-open forced
  refresh with measured scan duration, history-identity migration, and a
  versioned redacted one-shot snapshot
  ([#2089](https://github.com/steipete/CodexBar/issues/2089),
  [#2388](https://github.com/steipete/CodexBar/pull/2388),
  [#2373](https://github.com/steipete/CodexBar/issues/2373),
  [#2497](https://github.com/steipete/CodexBar/issues/2497)); and
- **bounded operation:** runaway CLI memory, refresh latency, background write
  volume, cache invalidation, and bounded retention
  ([#1999](https://github.com/steipete/CodexBar/issues/1999),
  [#2117](https://github.com/steipete/CodexBar/issues/2117),
  [#2369](https://github.com/steipete/CodexBar/issues/2369),
  [#2457](https://github.com/steipete/CodexBar/pull/2457)).

Comparable systems sharpen the boundary:

| System | Collection and organization | Display/query | Lesson for Codess |
|---|---|---|---|
| [ccusage](https://github.com/ryoppippi/ccusage) | Reads known local stores for many coding harnesses; groups usage by day, week, month, Session, Project/instance, model, and Claude billing block | Responsive terminal tables, live/status-line modes, date/source/Project filters, model breakdown, JSON | Reuse the intuitive cohort/time buckets and machine-readable output; retain Codess provenance and completeness rather than importing its report schema |
| [Claude Code Usage Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) | Reads Claude history into current-window, daily, and monthly measures; computes burn rate, cost, percentile-derived limits, and depletion forecasts | Real-time Rich terminal view, daily/monthly tables, warnings, saved view/timezone/refresh settings, optional logs | Useful experiment design for declared-versus-learned limits and prediction uncertainty; its plan constants and inferred limits are external hypotheses, not vendor or Codess facts |
| [CodeBurn](https://github.com/getagentseal/codeburn) | Reads local files/SQLite across coding products, deduplicates source-specifically, marks estimates, and attributes by tool/model/Project/task | TUI, text overview, web/menu surfaces, JSON/CSV, per-day charts, cache/call/session ratios and heuristic “waste” findings | Strong precedent for one local collector feeding several views and for separating exact versus estimated measures; its behavioral classifications are hypotheses, not Codess facts |
| [Langfuse](https://langfuse.com/docs/observability/features/token-and-cost-tracking) | Instrumented generation/trace/session observations; ingested usage/cost outranks inference; arbitrary non-overlapping usage buckets and model/pricing definitions | Metrics API and dashboards by time, user, Session, model, prompt version, tags, cost, latency, volume, and scores | Useful downstream analytical shape. Codess imports vendor evidence after the fact, so it must retain source/observation identity and cannot assume live instrumentation completeness |
| [LiteLLM](https://docs.litellm.ai/) | Gateway/library observes calls and tracks spend and budgets per key, user, team, or Project | Administrative dashboard, budgets, rate limits, callbacks | Applicable when Codess later consumes gateway evidence; not a substitute for local historical extraction |
| [OpenTelemetry GenAI conventions](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/) | Standard trace/event attributes for provider, conversation, model, input/output/cache/reasoning tokens, tools, and errors | Existing telemetry backends and time-series systems | Candidate names and interchange mapping, with caution: conventions are evolving, sensitive content is opt-in, and inclusive token definitions can differ from vendor billing buckets |
| [QuotaMeter](https://www.quotameter.app/) | Reads website/API quota and cost observations locally and synchronizes its own app surfaces | Unified quota dashboard, reset timers, model breakdown, alerts, browser/menu/editor surfaces | Confirms user demand for immediate limits and reset orientation; offers less evidence about durable local-session provenance |

Codess should borrow the following, in order:

1. define every statistic as an **observation** with cohort, time basis,
   source/snapshot identity, measure name, unit, exact/derived/estimated state,
   and algorithm/pricing identity when applicable;
2. expose daily/weekly/monthly and Session/Project/source/model breakdowns only
   as reproducible queries over exact observations;
3. preserve reset-window samples separately from token/cost/activity measures;
4. use incremental source markers and bounded refresh work, with an explicit
   forced-rebuild path and visible freshness; and
5. add displays only after the typed result can reproduce the underlying
   series and reconcile it to read-only SQL.

Do not copy CodexBar's two-year/hourly constants or any other product limit
into Codess. First collect distributions from Codess's own dated invocations,
then choose retention and resolution per measure. Do not infer billed cost from
text, merge quota percentage with reconstructed tokens, or relabel a harness
attribution as model attribution.

#### Implemented daily exchange activity

The immediate A2 tranche uses Codess's distinctive normalized exchange
evidence rather than reproducing vendor billing dashboards. `query overview`
now returns `daily_exchange_activity_utc`, limited to the most recent
`facet_limit` observed days and accompanied by total-day, limit, and truncation
fields. Events without an observed timestamp remain in overall totals but
cannot enter a dated bucket.

Each day records Event and retained-character volume; distinct Sessions and
Interactions; human-prompt and model-response counts and characters; the first
and last observed Event; the first and last human prompt; and the prompt span.
For the day's last prompt it also reports the final later model response in the
same normalized Interaction, plus last-prompt→response and
first-prompt→response spans. A NULL endpoint means the selected evidence cannot
establish that response. The Interaction link is stronger than timestamp
proximity but is still a normalized grouping, not a causal or attentional
claim.

`actor_activity` gives per-day counts, characters, distinct Sessions and
Interactions, first/last observations, and observed span for every actor found,
while always exposing zero-valued human, harness, tool, model, and agent
entries. `combined_harness_model_agent_activity` provides raw union
Session/Interaction counts without double-counting the union. Ratios and
percentages remain display-layer calculations. `subagent_session_activity`
separately counts Events, characters,
Sessions, Interactions, and actor Events inside Sessions explicitly classified
`subagent`; Events inside such a Session retain their source-mapped normalized
actor. Claude sidechain and Cursor `isSubagent` user envelopes are specifically
mapped as harness-delegated prompts rather than humans. Distinct counts are
scoped to selected store
observations so an explicit historical union cannot cross-link two snapshots.
Agent is intentionally present here as an A2 observation even though it is
outside A3's narrowed provenance gate.

These are **engagement observations**, not model utilization in a billing,
capacity, availability, or active-work sense. Observed spans may include idle
gaps. For now Codess does not add price, quota utilization, token burn,
timeouts, cost, or run-out projections: established COTS/FOSS tools already
serve those views, and Codess's higher-value contribution is evidence-rich
human/harness/model/agent/tool exchange analysis.

### Typed request and result contract

A first vertical `codess.query-request/1` / `codess.query-result/1` path is
implemented for sessions, overview, event rows, and bounded search. It is
independent of the physical SQLite schema. The implemented request contains:

- a stable action;
- CLI-resolved path or exact stable Project-ID scope plus source-system,
  Session, snapshot, and time scope;
- typed filters for text, event kind/ID, Interaction, Model Turn, status, exact
  model, tool, actor, content role, origin, parent/relation, initiation, and
  artifact path;
- optional complete Interaction/Model-Turn expansion, same-Session sequence
  windows, and lossless exact repetition grouping;
- action-appropriate row and byte limits; and
- explicit current or named-snapshot freshness.

Saved Project sets and a fail-closed broad catalog-cohort selector (currently
spelled `--all-current` for compatibility) are implemented. `catalog status`
reports each Project and `N/N` query readiness without claiming source
freshness. Catalog-attribute selectors remain possible A1 extensions.
Caller-selected fields/order, a layered version-2 carrier, and named query
packages are postponed together under CoPlan P17, not silently accepted fields.

#### Query-specification layers

The table below is a **P17 research decomposition**, not an approved
version-2 contract or current implementation plan. If that phase restarts, the
public specification must not serialize SQL or expose table, column, join, or
index choices, and it should evaluate these layers distinctly:

| Layer | Purpose | Values supplied by |
|---|---|---|
| Scope selector | Resolve Projects and current or named snapshots | Caller or a saved Project set |
| Parameters | Bind reusable values such as source system, date, text, status, or limit | Caller, defaults, or a named package |
| Filter | Decide which typed entities qualify | Bound predicates over common or explicitly namespaced source-specific fields |
| Expansion | Follow an Interaction, Model Turn, sequence window, or declared relation | Query specification |
| Derivation or aggregate | Compute declared counts, buckets, facets, or correlation rows | Named core operation with versioned semantics |
| Projection | Choose returned fields from the qualifying/derived entities | Caller or named package |
| Ordering and bounds | Define deterministic presentation order and stopping conditions | Query specification plus resource policy |
| Renderer | Present the same result contract as JSON, table, chart, or another supported view | Caller or named package |

Projection therefore does **not** list fields used internally by a filter and
does not make a template useful without parameter values. A reusable query
package declares its parameter schema, binds those parameters into filters,
then declares output projection and renderer. Some predicates require internal
identity/order/lineage fields that are not returned. Conversely, a projected
field need not participate in filtering.

Every result retains a non-removable identity envelope: Project and snapshot,
entity kind and stable/observation IDs, request/specification identity, Source
availability and content-completeness state, row/byte limits, and truncation or
limitation reasons. Caller projection controls the payload, not the evidence
needed to interpret it.

Projection is also separate from developer execution reporting. Requested
result fields describe the investigation product. SQL plans, phase timings,
rows examined, allocation counters, cache behavior, and RSS describe one
execution and belong in bounded maintainer observations under A9. They may
refer to the request/result identity, but are neither projected domain fields
nor part of stable result meaning.

#### Filter planning and execution

The filter is declarative. Its JSON member order is not execution order. The
planner may reorder conjunctive predicates and push eligible work into each
read-only SQLite store when doing so preserves the specified meaning. Initial
classes are:

1. identity, equality, range, membership, and indexed relation predicates,
   which are normally safe to push down;
2. literal substring and artifact-path predicates, which are pushable with
   Codess-defined escaping and case semantics;
3. Interaction/turn expansion, global k-way ordering, cross-store limits, and
   returned-byte bounds, which remain core executor stages; and
4. evidence resolution, raw-source access, or derived interpretation, which
   require separately named operations and cannot be disguised as SQL
   predicates.

An explain result should show resolved inputs, normalized predicates, chosen
pushdowns, retained core stages, estimated/read row counts, and bounds without
exposing conversation content. Static optimization can use available indexes,
declared cardinality, and measured selectivity. It must not change the request
or make correctness depend on one backend.

SQL equivalence is proved at the public operation boundary, not assumed
globally. Current A9 coverage uses contract/unit tests, fixture-sized functional
tests, composed CLI workflow tests, source→adapter→store→query integration
tests, independent SQL reconciliation for selected orientation/count results,
and the immutable-candidate system validation ladder. The exact levels and
test owners are cataloged in `CoPlan.md §8.2.6`.

A separate backend-neutral executor and `EXPLAIN QUERY PLAN` assertions are
candidate debugging mechanisms, not current acceptance requirements. Build the
smallest one only after a reproduced qualification, NULL/literal, ordering,
bounds, completeness, or required-access-path defect. Reduce the mismatch to a
deterministic fixture first. Diverse immutable Projects—including small
single-vendor stores before Cursor-heavy Zero400—then provide system
reconciliation and scale evidence; they do not replace deterministic tests.

#### JSON carrier evaluation (postponed P17)

JSON is a candidate because current requests/results already use JSON Schema,
external programs can create and validate it without linking SQLite, and it
can preserve a typed AST better than command-line strings. The exact
version-2 shape and need are not approved. A later focused external-composition
prototype must compare:

| Candidate | Useful precedent | Boundary |
|---|---|---|
| Codess-specific JSON AST | Small, intuitive, preserves current v1 concepts and exact domain types | Codess owns validation, tooling, and documentation |
| CQL2 JSON-style operator tree | Standardized boolean/comparison expression structure | Geospatial property assumptions and broader surface are unnecessary |
| JSON Logic or MongoDB-style predicates | Familiar nested operators and broad implementation experience | Weak typing or backend-specific NULL/array semantics must not leak into Codess |
| GraphQL selection concepts | Clear field selection and mature client tooling | Projection is strong, but snapshot resolution, bounded execution, and JSON carriage need separate conventions |
| SQL | Excellent expert escape hatch and optimization oracle | Physical-schema coupling makes it unsuitable as the public query specification |

The prototype should bind the same intuitive UC1, UC3, UC5, UC6, and UC7
queries through at least one shell/JQ workflow, one Python client, and one
generic JSON-Schema-aware tool. Selection, filter, projection, execution, and
result hashes must match the direct CLI path. Adopt borrowed syntax only where
its NULL, array, comparison, and escaping semantics can be stated exactly.

#### Query packages and governance (postponed P17)

A candidate `codess.query-package/1` wraps one parameterized query
specification with:

- stable package name/version, title, use cases, maturity, and visibility;
- parameter JSON Schema, defaults, examples, and invalid cases;
- selector/filter/expansion/derivation/projection/order/bounds;
- supported renderers and visualization field requirements;
- expected completeness limitations and evidence behavior; and
- fixture, real-corpus, performance, and privacy validation records.

One executor and one core operation registry serve every package. A specialized
need that cannot use them should first be proposed as a generally useful typed
operation. If it remains proprietary or domain-specific, it is isolated as an
extension/fork rather than implemented as an untracked side channel.

Package classes are separate:

| Class | Location and distribution | Required state |
|---|---|---|
| Standard | Versioned with Codess and intended for public distribution | Reviewed, documented, stable parameter/result contract, representative fixtures, renderer checks |
| User or Project internal | User/Project registry outside the public package | Same schema/executor; explicit private visibility and owner |
| Ad hoc | Supplied for one invocation or saved investigation | Same validator; no stability promise |
| Experimental | Separate registry or extension namespace | Explicit experimental maturity, version, limitations, and no shadowing of a standard package |

If package work restarts, the candidates should remain use-case driven:
Project/Session inventory (UC1–UC2), Project orientation (UC3), known Session
display (UC4), Interaction context window (UC5/UC7), bounded literal finding
(UC6), tool failure/permission review (UC7), artifact cross-source evidence
(UC8), and exact-evidence/citation export (UC9–UC10). UC11 Assembly export waits
for the Assembly investigation.

The first-tranche scenarios are retained for requirements and acceptance
mapping, not scheduled as package implementations:

| Candidate package | Primary inputs | Stable result/display |
|---|---|---|
| `project-session-inventory` | exact/saved Project scope; optional source system and date range | bounded Session rows plus counts; table/CSV |
| `project-orientation` | same scope; declared activity-gap caps | volume, time, relation, and initiation summary; table/timeline-ready JSON |
| `exchange-window` | one Event, Interaction, or Model-Turn identity; sequence bounds | canonical complete exchange/window; transcript table |
| `normalized-findings` | scope plus literal text/path and typed predicates | occurrence-preserving Event rows, facets, and completeness; table |
| `tool-outcome-review` | scope plus tool/status/permission predicates | calls, results, lineage, failures, and denials; table/status chart |

These scenarios map to A1/A2/A3/A4/A7 as recorded in CoPlan §8.2.3; P17 owns
only a future wrapper/carrier/renderer investigation. They are not separate
query engines. A missing behavior enters the shared typed operation registry
only when its meaning, bounds, provenance, and cross-source behavior can be
specified.

#### Result identity and completeness

Use four related identities rather than one overloaded “current result” label:

1. `query_package_id` identifies a named versioned template;
2. `request_id` identifies the bound canonical selector, parameters, filters,
   projection, ordering, and bounds;
3. `result_id` identifies the resolved Project/snapshot inputs plus the
   canonical result meaning/content; and
4. a dated execution observation records when, with which software/package/
   decoder/validator/schema versions, the request ran and what it returned.

The compatibility `--all-current` spelling is only a transient selector.
Resolution produces an exact dated
cohort record naming Projects, snapshots, filter, algorithm/package versions,
CoSchema release, outcomes, and limitations. Research and publications cite
that record/result identity, not the word `current`. A later execution may
again request a broad catalog cohort and legitimately resolve differently.

Completeness is multidimensional rather than one Boolean:

- cohort completeness: every requested Project resolved or the request failed;
- source availability: captured, sealed, exact live, reference-only,
  unavailable, or changed;
- mapping coverage: mapped, vendor-specific retained, diagnosed unsupported,
  or rejected;
- content coverage: complete, policy-transformed, truncated, external, opaque,
  or absent; and
- result coverage: complete within scope or stopped by row/byte/time/other
  declared bound.

An incompatible current snapshot is never skipped. It means the pointer/store
cannot satisfy the requested CoSchema/package/query contract—for example,
required format-4 columns are absent. Omitting that Project would make the
requested cohort falsely appear complete, so the entire resolution fails and
names the Project, snapshot, and incompatibility. The caller may then rebuild
it, choose an explicit compatible snapshot, or deliberately exclude it in a
new request.

Common fields require stable normalized meaning, not identical vendor storage.
That does not forbid vendor-specific information. A query may explicitly
project namespaced source fields or retained source-record classifications;
other source systems report `not_applicable` or absent according to the field
contract. Common and source-specific projections must be clearly separated so
an Assembly never claims that the common subset exhausts vendor evidence.

Cross-Project execution of one homogeneous query is implemented by ordered
virtual composition. Sequentially feeding one saved result into another query
is also implemented. Union/intersection of homogeneous entity results,
heterogeneous joins, and merging outputs of several queries across Projects
and source systems are larger typed-composition requirements; they need
explicit key, conflict, ordering, completeness, and provenance contracts and
must not be inferred from “projection” or ordinary row concatenation.

`text` and `artifact` in `codess.query-request/1` mean literal substring, not
SQL pattern. The SQLite implementation escapes backslash, `%`, and `_`, then
uses `LIKE ? ESCAPE '\\'`; callers never need to know the physical escape
syntax. If wildcard matching becomes a demonstrated use case, add a separately
named `text_pattern` or operator-bearing predicate with explicit syntax,
escape, case, and normalization semantics. Do not overload `text` or pass raw
user input into `LIKE`, regular expressions, or another backend whose
metacharacters change the request meaning.

### Raw-source search versus normalized search

The postponed feature previously called **full-source search** is more
precisely **raw-source search**. “Full” incorrectly suggests complete semantic
coverage: encrypted values, unavailable reference Sources, binary attachments,
and unknown encodings may remain unsearchable. Raw-source search means a
bounded search over authorized fields in exact vendor Source revisions,
including values that were not projected into CoSchema. It is not raw capture,
exact-evidence lookup, or a fallback performed after normalized search misses.

| Architectural aspect | Normalized schema-compliant search | Raw-source search |
|---|---|---|
| Authority | CoSchema Event and typed relation rows | Exact Source revision plus raw record/field locator |
| Storage read | Immutable per-Project CoSchema SQLite stores | Snapshot raw manifest followed by sealed, captured, or exact live Source |
| Organization | Project → Session → Interaction/turn → Event | Source system → container/record → field path; Session association may be mapped, absent, or ambiguous |
| Value meaning | Mapped event kind, actor, role, origin, status, tool, model, artifact, and bounded content | Vendor field name/path, raw JSON/SQLite type, encoding, record kind/subtype, and unmodified or explicitly decoded value |
| Searchable values | Retained normalized content, tool input/output, artifact paths, and typed predicates | Only policy-authorized scalar/text fields; encrypted, opaque, binary, secret-suppressed, or undecodable values remain identified but unsearched |
| Matching | Literal substring with `%`, `_`, and backslash treated literally | Start with identical literal semantics; regular expression, JSONPath, or backend patterns require separate named operators |
| Bounds | Project/snapshot/source/session/time/type predicates plus row and returned-content byte limits | Add Source, raw-record, decoded-byte, field-count, match-count, excerpt, and total-read bounds before opening large content |
| Provenance | Stable Event/Session IDs, snapshot, Source locator, completeness and policy | Project/snapshot, Source ID/revision/object ID, availability/equality, record locator/type/subtype, field path/type, decoder, and match offsets |
| Missing result | Qualified by normalized completeness, filters, policy, and truncation | Also qualified by Source availability, authorization, encrypted/opaque fields, decoding failures, and unvisited records |
| Lifecycle | Rebuilt with the Project snapshot | Any derivative index is revision- and policy-bound, rebuildable, deletion-aware, and never authoritative |

The first implementation should use a distinct `query raw-search` action with
the existing Project selector, source-system scope, `--text`, `--limit`, and
`--byte-limit` conventions. Raw-specific predicates are additive:
`source_id`, `source_record_type`, `source_record_subtype`, and literal
`field_path`. Its result is `codess.raw-search-result/1`, not an overloaded
Event result. Every match carries an exact Source/record/field locator and a
bounded excerpt; it does not synthesize an Event or imply that an unmapped
field belongs to the user, model, or harness.

Initial execution is index-free and storage-aware:

1. resolve exact Project snapshots through the common Project-set resolver;
2. read each verified raw manifest and apply source-system, availability,
   revision, and storage-format predicates before content access;
3. stream Claude and Codex JSONL record-by-record while retaining byte/line
   locators and raw JSON field paths;
4. query a captured Cursor SQLite revision by selected workspace/composer/
   Session keys and bounded key ranges—never decode or copy the entire
   machine-wide database merely to search one Project;
5. treat external text sidecars as separately linked Sources; retain attachment
   IDs, media type, size, and relationship without searching binary/base64 by
   default;
6. decode through the existing character-set/content-policy entry points,
   record original type/length and decoder actions, then apply literal matching
   to authorized scalar/text values; and
7. stream bounded matches and completeness counters without retaining the
   complete Source or all matches in memory.

An optional content-derived index is distant work permitted only after repeated
index-free queries fail measured requirements. It would be keyed by Source
revision, field-authorization policy, decoder version, and index schema, with
dry-run deletion propagation and size reporting. Alternative normalized
retrieval under **P5** remains distinct from raw-source indexing and never
authorizes it.

Integration proceeds through reusable boundaries rather than a second parser
stack: the Project/snapshot resolver, raw manifest and evidence resolver,
vendor Source readers, content decoding/policy, progress/resource reporting,
canonical hashing, and atomic result persistence. Adapter mapping remains the
only path that creates CoSchema entities.

Acceptance requires:

- fixtures for Claude JSONL, Codex JSONL, Cursor SQLite, external text, unknown
  records, invalid UTF-8, opaque/encrypted values, and unavailable references;
- parity tests proving literal `%`, `_`, and backslash semantics match
  normalized search;
- exact match locators that re-resolve to the same Source revision and field;
- no implicit access to raw Sources when ordinary `query search` misses;
- record/read/match/excerpt/returned-byte boundaries tested at below, equal,
  and above values with visible truncation reasons;
- bounded-memory tests on one large JSONL Source and a large Cursor container;
- privacy/secret suppression and deletion/retention tests; and
- real-source validation on one approved recent Project per source system
  before any persistent index or default enablement.

The executable task registry is **CoPlan P13.1–P13.8**. The feature remains
postponed until an operator explicitly reopens that sequence.

A `codess.query-result/1` contains the normalized request, observation and
data-as-of times, selected package/store/snapshot/policy identities, bounds,
summary, typed rows with stable evidence IDs, persisted derivation edges, and
explicit truncation or missing-data limitations. Event/search summaries contain
facets over returned bounded rows. Optional repetition groups use only nonempty
complete retained content plus compatible semantic dimensions, retain all
occurrence IDs and time spans, and never assert redundancy. The existing
`codess.query-row/1` JSON Lines contract remains the legacy sessions/stats
streaming form; a typed streaming projection is added only when scale evidence
defines its contract. Tables, CSV, and Markdown are renderings rather than
inputs scraped back into the system.

Saved investigations are declarative JSON requests evaluated by one runner,
not one wrapper script per question. Stable-ID result chaining persists its
input result/request hashes and selected stable IDs as a derivation edge.
Comparison reports added, removed, and content-changed stable rows plus
summary/provenance changes. It rejects different logical requests,
heterogeneous row kinds, invalid row shapes, and repeated logical identities
from historical unions. Historical union is explicit and observation
preserving; replay across changed named snapshots is tested. Repetition groups
retain constituent Event IDs that can be cited directly. Request/result writes
are atomic and failure-tested. These properties complete A7's current
homogeneous typed-composition contract. Threshold conditions and named
investigation graphs require a demonstrated consumer rather than silently
expanding A7. An LLM-produced summary must become a derived processing record
and cite the bounded rows it received.

### Guided investigation behavior

Guidance is an orchestration of inspectable typed operations, not a second
query engine. Its expected sequence is:

1. resolve an explicit Project/vendor/current-or-named-snapshot scope;
2. orient with volume, time, vendor, model, tool, artifact, and completeness
   evidence before reading large bodies;
3. formulate and display a typed request, rejecting unknown or ignored
   predicates before any scan;
4. run a bounded search or facet query with predicate/limit pushdown;
5. branch by saving stable result IDs and feeding them into a narrower request;
6. reconstruct the complete Interaction or Model Turn, or a declared sequence
   window, in canonical order;
7. resolve material claims to an exact matching sealed, captured, or live
   source revision;
8. produce a cited summary whose processor, inputs, limitations, and evidence
   IDs are recorded; and
9. replay against the same snapshots, or explicitly compare a later result.

At every stage “no hit” is qualified by source availability, normalized-content
completeness, policy, and truncation. A changed live source is shown as a
mismatch, not silently substituted. Row and byte limits stop the operation
with a visible truncation reason. Optional natural-language formulation may
propose a request only after this deterministic path is stable; it must show the
request for validation and cannot bypass scope or evidence rules.

The present implementation owns the deterministic CLI operations in steps 1–9,
including exact Project-ID scope, global ordered merge, bounded facets,
stable-ID derivation, complete exchange/window reconstruction, exact Event
evidence, typed cited-summary records, and historical replay/diff. Native
summary generation and an optional guided UI remain incremental work under A8.

### Human-readable Session briefs

An organized Session summary should read like a compact research note, not a
JSON rendering or a table of transient counts. Use a six-line **Session brief**:

```text
SESSION <short ID> · <source system> · <Project>
When   <conversation range>; source touched <mtime when materially different>
Aim    <what the user was trying to accomplish>
Work   <main investigation, tools, files, or exchanges>
Result <decisions, edits, findings, failures, or unresolved work>
State  runtime <active/idle/unknown>; source <stable/open-ended/truncated>; Project snapshot <caught-up/behind/unknown>
Keep   <why this Session is useful, operational only, or safely de-emphasized>
```

`When` separates vendor Event time from Source mtime. `Work` describes kinds of
activity rather than dumping tool counts. `State` keeps runtime observation,
Source closure, and Project-snapshot currency separate. A recently modified
Source with no following response is open-ended; it is not called active
unless a runtime interface observed that state. `Keep` is an investigation-selection
recommendation, never an ingest rejection. Stable Session/Source IDs remain
attached in structured data or a citation line when the brief is published.

### Search reports

Introduce the postponed question progressively:

1. A search finds matching Events within an explicit Project/Session/source
   scope.
2. Codess must display those matches in some deterministic order.
3. Today it uses canonical Project, Session, and Event ordering so results are
   stable, reproducible, and occurrence-preserving.
4. A real investigation may benefit from seeing some matches earlier—for
   example, exact errors before broad mentions, or complete exchanges before
   isolated fragments.
5. A **search report** starts with a small set of actual investigation
   questions and reviewed useful matches. It can compare canonical
   order with one specified alternative using measures such as first useful
   match position, useful matches in the first N rows, and analyst corrections.
6. The study changes presentation only. Every occurrence, stable ID, source
   order, and saved-result identity remains available.

Do not implement ranking from the abstract desire for a “better order.” Reopen
this work only when a recorded investigation shows that canonical presentation
made a useful result materially harder to find.

### SQLite authority and optional analytical consumers

Adding DuckDB does **not** justify restructuring durable storage. Per-Project
CoSchema SQLite snapshots remain authoritative because they are embedded,
transactional, easily shipped, directly integrity-checked, and already encode
the accepted store contract. Typed application queries are the compatibility
boundary above those files.

DuckDB is useful as an optional read-only analytical consumer when an
investigation needs columnar aggregation across exported result documents,
Parquet, or several immutable SQLite snapshots. It must not write accepted
snapshots, become required for ingest, or introduce a second authoritative
catalog. Compared with alternatives:

- SQLite views are best for stable single-store joins, but do not remove the
  attachment limit or provide a cross-project analytical workspace;
- Python iterators and heap merge remain the portable application path for
  bounded interactive results;
- pandas is convenient for modest in-memory results but has a less explicit
  memory boundary;
- Datasette and sqlite-utils provide inspection and presentation over SQLite,
  not a replacement execution/store model; and
- DuckDB earns a recipe when columnar scans, Parquet interchange, or broad
  aggregates materially outperform typed pushdown plus streaming merge.

### Applicable tooling and dependency boundaries

Codess deliberately keeps ingestion and authoritative CoSchema snapshots on
Python's standard library SQLite plus zstandard. Applicable tools should first
be external consumers, development dependencies, or versioned derived-analysis
components. Promote one into the runtime only when two implemented workflows
need the same stable boundary.

| Candidate | Best fit | Related use cases/work | Recommended role |
|---|---|---|---|
| [DuckDB](https://duckdb.org/docs/stable/) | Broad aggregation across immutable SQLite inputs and future Parquet partitions | **UC3, UC8, UC9, UC11; A19** | First analytical prototype. Use a separate workspace or scans over immutable inputs; never let its SQLite extension write accepted snapshots |
| [Apache Arrow/PyArrow Dataset and Parquet](https://arrow.apache.org/docs/python/dataset.html) | Typed, partitioned, columnar interchange with projection and predicate pushdown | **UC9, UC11; A19** | Preferred Assembly export substrate and schema-validation boundary, not another authority |
| [Polars lazy API](https://docs.pola.rs/user-guide/concepts/lazy-api/) | Streaming/lazy dataframe transforms over JSONL/Parquet without requiring pandas-sized materialization | **UC3, UC6, UC8, UC9, UC11** | Optional research and export consumer after the common projection exists |
| JupyterLab or another notebook frontend | Iterative quantitative orientation, plots, sampled evidence review, and reproducible research narratives | **UC3, UC5, UC6, UC8, UC9, UC11** | Consumer of immutable snapshots or typed exports; notebooks must record input snapshot/result IDs and are not ingestion code |
| [NetworkX](https://networkx.org/documentation/stable/reference/introduction.html) | Directed/multi-edge traversal of Event, caused-by, parent, tool, Session, artifact, and correlation relations | **UC5, UC7, UC8; A3/A8** | Prototype lineage/path algorithms on bounded selected subgraphs; keep SQLite IDs and evidence as authority |
| [RapidFuzz](https://rapidfuzz.github.io/RapidFuzz/) | Edit/token similarity for copy-paste variants and near-duplicate prompts or responses | **UC6; A4/L-P2** | First derived near-duplicate experiment after exact grouping; record preprocessing, scorer, threshold, score, and constituent Event IDs |
| [Sentence Transformers](https://www.sbert.net/examples/sentence_transformer/applications/semantic-search/README.html) | Semantic retrieval and topic/phase candidate generation | **UC6; A8/D7** | Later evaluated stage only, after lexical and near-duplicate baselines; store model/revision, chunking, score, and evidence IDs |
| [Hypothesis](https://hypothesis.readthedocs.io/en/latest/) | Generated malformed, missing, reordered, oversized, and vendor-extension shapes | **A6/A16 and evidence-triggered mapping maintenance** | High-value development dependency for adapter, mapping, identity, ordering, limit, and fixed-point properties |
| [coverage.py branch coverage](https://coverage.readthedocs.io/) | Reveal unexercised error, fallback, and vendor-shape branches that a passing test count cannot show | **T6 and all adapter/query work** | Development/CI evidence; establish a measured baseline before setting a gate |
| [Memray](https://bloomberg.github.io/memray/) | Python and native allocation attribution and peak-memory reports | **A9/L-E3** | Profile the real 19,661-Event Cursor composer and forced replacements; keep captures outside snapshots and retention-managed |
| JSON Schema validator implementation | Validate query, result, Assembly, policy, and mapping JSON at process/tool boundaries | **A7, A19** | Use the checked-in JSON Schema as authority; add a library only where current structural checks do not cover an external boundary |

Several plausible packages should remain out of the core for now:

- **SQLAlchemy and Alembic:** Codess owns explicit SQLite DDL, read SQL, and
  immutable rebuilds rather than ORM identity or in-place migration.
- **Pydantic/dataclass schema duplication:** generated runtime models may become
  useful, but separately maintained models would compete with the existing
  JSON Schema and CoSchema contracts.
- **APSW:** Python `sqlite3` already supplies the online backup, read-only URI,
  progress handler, and transactional behavior currently required. Reconsider
  only for a measured missing SQLite primitive.
- **pandas:** useful in small notebooks, but Polars/Arrow/DuckDB have clearer
  bounded or lazy paths for Assembly-scale work.
- **graph databases:** SQL plus bounded NetworkX projections are sufficient
  until repeated graph traversals demonstrate a durable graph read model.
- **Elasticsearch/OpenSearch, vector databases, and general search servers:**
  they introduce another sensitive index and lifecycle. Alternative indexed
  retrieval is distant, evidence-triggered work; raw-vendor indexing remains
  postponed under **P13**.
- **Spark, Dask, Ray, and dbt:** no present corpus size, distributed execution,
  or transformation-deployment requirement justifies their operational model.
- **ijson/orjson and alternate serializers:** existing JSONL paths are bounded
  and streamed; benchmark a demonstrated parser/serialization bottleneck
  before changing canonical JSON behavior.

Therefore A9 is primarily a query-execution refactor—push predicates/limits to
each SQLite store, stream and heap-merge ordered rows, and profile allocations.
External recipes consume immutable inputs or typed exports. A vendor-neutral
SQL view is promoted only after two independent consumers repeat the same row
contract; DuckDB remains optional and testable at the boundary.

### Cross-Project analytical assemblies

A single mutable global database should **not** replace per-Project immutable
snapshots. It would mix source refresh, decoder changes, Project selection,
retention, and analytical indexing into one high-churn authority. It would also
make “all” ambiguous: all discovered paths, all curated Projects, every
historical snapshot, or only current accepted observations.

Use a first-class **Assembly** instead. An Assembly is a reproducible selection
of explicitly resolved Project snapshots plus filters and a projection. It can
remain a saved/queryable selection or produce any number of **Assembly
exports**. The compatibility broad-cohort selector can supply inputs at
resolution time, but the Assembly records the exact Projects/snapshots and
never claims every path, every superseded snapshot, or source freshness.

#### Assembly investigation before implementation

No bulk Assembly export format is authorized yet. First compare requirements
in both directions.

The top-down list starts with intended products:

1. a dated, reproducible Project/Session inventory;
2. a publication cohort with exact methods and limitations;
3. cross-source-system artifact or Interaction research;
4. utilization/time/volume analysis over a selected cohort;
5. an ML/data-science table with declared labels or features; and
6. a portable subset for another investigator or tool.

The bottom-up list starts with available structures:

- Project/snapshot/Source observations and availability;
- Sessions, Interactions, Model Turns, and Events;
- actors, model configurations, tools/results, artifacts, and diagnostics;
- common normalized fields plus namespaced vendor/source-record evidence;
- correlation assertions and content/evidence identities; and
- typed query results, derivation edges, bounds, and completeness dimensions.

For each top-down product, identify the smallest bottom-up entities and fields
that satisfy it, required joins/keys, expected cardinality and content volume,
vendor-specific columns, update semantics, renderer/consumer, and whether a
virtual saved result is already sufficient. Conversely, every proposed common
export column must name at least one product that needs it. This prevents an
imagined “all records” table from becoming the de facto schema.

The first prototype is a manifest plus virtual execution of one current
version-1 saved typed request over two Projects and two source systems, using a
fixed named Assembly projection. It must compare its rows to the direct query
results before any bulk format is selected. This does not require or authorize
P17 query-package infrastructure or general caller-selected projection. A
second prototype exercises a fixed vendor-specific projection so format design
does not erase non-common evidence. Only then choose JSONL, Parquet, DuckDB, or
merged SQLite for measured consumers.

The assembly pipeline is vendor-independent:

1. select curated `project_id` values or an explicit saved Project set;
2. resolve each to exactly one current or named immutable `snapshot_id`;
3. record package/decoder/validator/policy and source-availability facts;
4. apply common Project/session/vendor/model/time/event/content filters;
5. project the normalized read model using stable global and observation IDs;
6. optionally write the analysis dataset in one or more export formats; and
7. register the Assembly and its inputs only after counts, identities, hashes,
   and referential checks pass.

Selectors may begin from the compatibility broad cohort, explicit Project IDs,
catalog attributes such as ownership/topic/curation state, named snapshots, or
stable IDs from a saved query result. The manifest always records the resolved
set, canonicalized by `(project_id, snapshot_id)`. If the
same logical Session appears through more than one Project observation, the
default is observation-preserving: retain each `observation_id` and Project
lineage. Logical deduplication is a separate declared policy, never an
accidental unique constraint.

“All records” means the complete normalized common projection from each
selected snapshot, including diagnostics and lineage, subject to the
snapshot's recorded content-processing policy. It does not silently copy raw
vendor databases, truncated source bodies, or external attachments into every
export. Source IDs, availability, content lengths, truncation state,
and exact-evidence resolvers remain available so an analytical row can be
traced back without multiplying multi-gigabyte source objects.

Every Assembly has one small JSON manifest, regardless of export:

- `assembly_format`, `assembly_id`, creation time, creating software, and
  semantic/content digest;
- the canonical selector/request, filters, projection, limits, and their hash;
- one input row per Project snapshot with `project_id`, `snapshot_id`, package
  digest, semantic digest, data-as-of time, source availability, and selected
  vendor/source-system stores;
- export records with format, schema/profile identity, path, row/byte
  counts, content hash, partitions, and validation status; and
- limitations, truncation, deduplication policy, and processing derivations.

The initial shape should be deliberately small and value-oriented:

```json
{
  "assembly_format": "codess.assembly/1",
  "assembly_id": "codess:assembly:<content-identity>",
  "selector": {"kind": "resolved-project-set", "source": "catalog-cohort"},
  "request_hash": "<canonical-selector-and-projection-hash>",
  "inputs": [{
    "project_id": "codess:project:<uuid>",
    "snapshot_id": "<immutable-snapshot-id>",
    "package_digest": "<CoSchema-package-digest>",
    "semantic_digest": "<snapshot-semantic-digest>"
  }],
  "projection": {"name": "codess.normalized-observations", "version": 1},
  "exports": [{
    "format": "parquet",
    "path": "exports/parquet/",
    "content_hash": "<export-hash>",
    "rows": 0,
    "validation_state": "accepted"
  }]
}
```

`assembly_id` identifies the resolved input set, selector, and projection, not
the filesystem path or preferred output format. Exporting identical content in
another format adds an export record; changing selected
snapshots or filters creates a different Assembly identity. The digest is an
integrity/content identity under the existing local-writer threat model, not
authentication.

Each exported entity row carries or joins losslessly to `assembly_id`,
`project_id`, `snapshot_id`, entity kind, stable entity `global_id`,
`observation_id` where applicable, and source/source-record identity. This
supports both directions:

- Assembly → exact Project snapshots, sources, and entity observations; and
- Project → every registered Assembly whose input relation names that
  `project_id`.

Do not copy an ever-growing `assemblies` list into every Project record.
`~/.codess/projects.json` remains the Project identity catalog;
`~/.codess/assemblies.json` is the Assembly catalog and its input relation is
the authoritative reverse lookup. A `by_project` index may be regenerated
inside that catalog for speed. Assembly files live under
`~/.codess/assemblies/<assembly-id>/`; retention removes exports only
through a dry-run plan and never removes their input Project snapshots.

Analysis dataset export formats have different roles:

| Format | Role |
|---|---|
| JSON manifest | Mandatory identity, selection, provenance, and validation record; not bulk event storage |
| JSONL | Streamable, inspectable normalized interchange and pipeline boundary |
| Parquet | Candidate columnar analysis dataset, partitioned by entity kind and optionally Project/time; suitable for pandas, Polars, Arrow, Spark, and ML pipelines |
| DuckDB | Optional analytical workspace/catalog over Parquet or normalized projections; a `.duckdb` file may cache tables/views but is not authoritative |
| SQLite | Optional portable merged read model for modest assemblies and existing SQL tools; it is not a naïve copy of CoSchema tables because local surrogate keys collide |

The assembly read/export schema uses stable global/observation keys rather than
the source SQLite row IDs. Partitioned Parquet with a DuckDB view layer is a
hypothesis for large analytical consumers, not yet a default. The
bottom-up/top-down prototypes must compare it with streaming JSONL and optional
merged SQLite. Duplicating every content body into more than one format always
requires an explicit export request. Refresh creates a new Assembly revision
or a new export bound to a newly resolved input set; it never
edits the provenance of an existing one.

### Broad historical semantics

Historical scope is explicit and has five distinct operations:

1. **current** resolves each selected Project's verified current pointer;
2. **snapshot** reads one named immutable Project snapshot and records package
   compatibility policy;
3. **diff** compares exactly two named observations by stable entity identity,
   source revision, content/semantic hash, and mapping/package identity;
4. **union** reads an explicitly enumerated snapshot set, retains observation
   identity on every row, and reports duplicate/revision conflicts; and
5. **discovery** lists snapshot metadata and coverage without treating every
   old filesystem object as approved query scope.

There is no implicit “latest per row” merge and no default union of every
historical snapshot. Broad discovery should first query the maintained Project
registry and verified manifests, metadata-only, then allow an operator to save
an explicit set. Current/named reads and explicit saved-set union now exist.
Union rows retain snapshot-bound observation IDs and duplicate-logical-ID
diagnostics. Two saved results from the same logical request compare stable
IDs/content while reporting snapshot/provenance changes. Broad registry/
manifest discovery and a single shortcut that executes both sides of a diff
remain postponed.

### Research venues

- **Guided personal research:** branchable drill-downs, annotations, decisions,
  and unresolved questions tied to immutable evidence.
- **Comparative harness studies:** vendor/model/tool/permission/compaction
  behavior over the same Project, artifact, or task period.
- **Activity and cost modelling:** active-time estimators, token/cost
  confidence, quota/reset observations, and per-Interaction resource profiles.
- **Topic and phase discovery:** lexical facets, embeddings, clustering,
  change-point detection, and LLM labelling as rebuildable derived processing
  with method and confidence.
- **Research workbenches:** read-only Datasette, Jupyter/pandas, sqlite-utils,
  or DuckDB over exports and immutable snapshots.
- **Cross-snapshot analysis:** semantic diffs of sessions/events, source
  revisions, mapping changes, and investigation replay across package versions.

These are research directions, not an implementation queue. Promotion to work,
including its priority, decision dependencies, and restart conditions, occurs
only in **CoPlan.md §8**.
