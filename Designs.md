# Codess design decisions

This document defines the intended normalized model and the next design steps.
It is not a description of the current `0.1.0` database. `CoSchema.md` and
`sql/CoSchema.sql` remain the description and executable DDL for that database
until a new baseline is implemented.

The immediate goal is reliable ingestion and comparison of recent, active work
from Claude Code, Codex, and Cursor. Exhaustively finding every historical
session or repository is less important than preserving evidence, mapping the
three vendors consistently, rebuilding reproducibly, and supporting mixed
queries.

## 1. Decisions and priorities

### Implement first

1. **Version every compatibility boundary independently.** Track the Codess
   software release, logical schema, physical store layout, normalization
   taxonomy, each vendor mapping, and the observed harness/source-format
   version. One number cannot describe all of these.
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

### Accepted removals and corrections

- Remove `release_value` from the next schema. Its packed integer encoding is
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

### Independent versions

| Version | Meaning | Changes when |
|---|---|---|
| `software_version` | Released Codess application, currently `0.1.0` | CLI or library behavior is released |
| `software_revision` | Exact source revision and dirty-state marker | The build input changes |
| `logical_schema_version` | Entities, fields, relationships, and their meanings | The normalized information model changes |
| `layout_version` | SQLite files, tables, columns, indexes, constraints, and encodings | Physical storage changes, even if semantics do not |
| `taxonomy_version` | Normalized event, actor, status, and operation vocabularies | Classification meanings or mappings change |
| `mapping_version[vendor]` | Claude, Codex, or Cursor adapter rules | A vendor mapping changes |
| `source_format_version` | Observed upstream record/storage format, if known | The vendor changes its format |
| `harness_version` | Exact Claude Code, Codex, Cursor, or other harness release | The producing application changes |

The versions must be independent. For example, a corrected Codex mapping may
produce different normalized events without changing the logical schema or the
Codex harness version. An added index changes the layout but not functional
meaning. The manifest may additionally record minimum and maximum compatible
reader versions, but compatibility must be tested rather than inferred from a
matching number.

Per-vendor logical schemas are not separate normalized schemas. The vendor
documents describe upstream formats and each versioned mapping into the common
logical schema. A vendor-specific staging database is permissible as a physical
implementation detail and receives its own layout/mapping identity.

### Names versus authoritative metadata

Do **not** make a database filename or directory name the authoritative version
record. Encoding every independent version in a path produces long names,
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
    └── <created>-sw<software>-ls<logical>-ly<layout>/
        ├── manifest.json
        ├── sessions_cc.db
        ├── sessions_codex.db
        ├── sessions_cursor.db
        └── raw/
```

The directory suffixes are human hints only. `manifest.json` and `store_meta`
are authoritative. Keeping vendor names in current DB filenames is reasonable
because it identifies a physical partition; putting mapping or schema versions
in every DB filename is not. A future single database can replace the
per-vendor files without changing the logical model.

### Snapshot contract

Each immutable snapshot should record:

- all versions above, build timestamp, Python and SQLite versions, and platform;
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
   logical/layout version; or
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
| Logical schema (`CoSchema.md`, next revision) | Common fields, nullability, cardinality, identity and lineage | SQLite-specific optimization |
| Physical schema (`sql/CoSchema.sql` plus a layout document) | Tables, columns, SQL types, constraints, indexes, pragmas, file partitioning | Product behavior and vendor interpretation except as comments/links |

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

The common model should contain these concepts. This is a logical model, not a
commitment to one table per item.

- **Project**: a stable work identity, independent of its current local path.
- **Project location**: a machine-local observed root, worktree, subdirectory,
  or vendor-reported working directory.
- **Source**: one upstream transcript, database, record stream, or bounded
  extraction unit, with provenance and observation facts.
- **Session**: one vendor/harness conversation identity and its lifecycle.
- **Interaction**: a user goal segment initiated by a prompt or reply and
  containing any number of events. It can remain open across tool/model cycles.
- **Model turn**: one model inference/request-response cycle when the source
  provides sufficient evidence. This is not the same as an interaction.
- **Event**: an ordered observation such as content, a tool request/result,
  lifecycle change, context operation, or audit fact.
- **Participant/actor**: the human, model, harness, tool, agent, skill, or other
  producer responsible for an event.
- **Tool invocation and result**: a request plus zero or more result fragments,
  correlated by a vendor call ID or inferred local identity.
- **Model configuration**: provider/model and configurable inference settings,
  referenced as a session default and optionally overridden per model turn.
- **Artifact**: a file, document, repository state, URL, or other resource that
  a session reads or changes.

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

## 7. Time, ordering, and observation

### Session and event time

Store `started_at` explicitly and allow it to be `NULL`. Do not substitute a
file mtime into the same field. Suggested time facts are:

| Field | Meaning |
|---|---|
| `started_at` / `ended_at` | Vendor-supported session bounds; nullable |
| `event_at` | Vendor-supported event occurrence time; nullable |
| `source_mtime` | Filesystem modification time observed for a source |
| `observed_at` | Time Codess inspected the source |
| `ingested_at` | Time the normalized baseline was built |
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

Strike `release_value`. Replace ambiguous `release` with the explicit version
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

### Roles are multivariate

The source roles `user` and `assistant` are repeatedly violated by harness
inputs, project instructions, skills, agent output, tool results, and developer
messages being serialized into message-shaped records. Use independent axes:

- `actor_kind`: `human`, `model`, `harness`, `agent`, `skill`, `tool`,
  `system`, `developer`, or `unknown`;
- `content_role`: `instruction`, `prompt`, `response`, `context`,
  `tool_request`, `tool_result`, `status`, `memory`, or `audit`;
- `origin_kind`: `direct_user_input`, `harness_injected`,
  `project_instruction`, `skill_generated`, `agent_generated`,
  `tool_generated`, `model_generated`, or `unknown`; and
- participant/actor identity when known.

Retain the exact vendor role separately. These dimensions should be nullable or
`unknown` when the source does not prove them; mapping a record labeled `user`
to a human actor without checking its origin would preserve the current error.

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

## 11. Raw evidence and sidecars

Do not put full `source_raw` blobs in the main query database. They enlarge
backups, mix sensitive evidence with normalized search data, and make retention
and redaction all-or-nothing. Raw capture should be explicit and policy-driven.

For reproducible baselines, use an immutable content-addressed sidecar, for
example `raw/sha256/<prefix>/<hash>.zst`, containing exact source bytes or
framed exact records. The snapshot manifest maps source URI, source revision,
record offset/identity, content hash, compression/encoding, and retention policy
to that object. Normalized records store only the source/record identity and
optional raw reference/hash.

Zstandard-compressed source bytes preserve reparsing fidelity and deduplicate
identical evidence. Framed JSONL is convenient for record access but should not
replace exact bytes when formatting or database pages matter. A small sidecar
index is a physical-layout option, not part of the functional model. Apply
permissions, encryption, redaction, and deletion policy separately from the
normalized store. When raw capture is disabled, the source manifest still
states what was inspected and that exact evidence was not retained.

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

Scanning updates observed facts. A review operation updates curation. Ingestion
uses an explicit saved selection policy or selection set. Tests must always use
an isolated registry; temporary test projects must never enter the personal
catalog.

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

### Current read-only review snapshot

A fresh scan of `~/Work` found **237 Git repositories** across topical trees and
**130** with a commit in the last 180 days. Large reference collections under
`Spank/sOSS`, `ZK/ZKs`, `Claw/Claws`, and similar paths demonstrate why recency
and repository count alone are noisy. Repository discovery and vendor-session
discovery are separate inventories.

| Topical tree | Git repositories |
|---|---:|
| `Biz` | 1 |
| `Claude` | 20 |
| `Claw` | 34 |
| `Code` | 34 |
| `Codex` | 1 |
| `GBP` | 1 |
| `Github` | 21 |
| `Spank` | 58 |
| `WP` | 9 |
| `ZK` | 58 |

The current vendor-index scan found 18 project paths plus the global Cursor
source. Twelve paths had meaningful session evidence and six were zero-session
Cursor traces. The strongest immediate review set is:

| Candidate | Current reason | Proposed state |
|---|---|---|
| `Code/CodeSess` | Active owned implementation; repository itself was not in the prior meaningful vendor-index result | Priority; locate/validate all three vendor sources |
| `Code/SWEmore` | Recent, meaningful session evidence | Priority candidate; classify ownership |
| `Code/Misses/petri/petri` | Recent meaningful evidence | Candidate; classify ownership and scope |
| `Spank/spank-py` | Recent meaningful evidence and existing old store | Priority candidate; rebuild rather than trust old store |
| `ZK/Zero400` | Meaningful Claude and Cursor evidence | Priority cross-vendor baseline |
| `ZK/ZeroPerf` | Recent meaningful evidence | Priority candidate |
| `WP/harduw` | Claude and Codex evidence, but currently dated | Deferred cross-vendor compatibility baseline |
| `Claw/setpack` | Meaningful evidence | Candidate; classify owned/reference and activity |
| `Code/jsonschema` | External project with recent evidence | Reference/fixture only |

The other meaningful paths (`WP/multiwp`, `WP/must-py`, `WP/wp`, and
`WP/wpages`) should remain reviewable but not inflate the first active baseline.
The six zero-session traces (`Claude/CContext`, `Github/Schema`, `Github/skip`,
`Spank/HECpoc`, `Spank/spank-rs/perf`, and `ZK/zerowalletmac/src`) are discovery
diagnostics or candidates for path-mapping repair, not ingestion successes.

The existing personal registry is not a trustworthy catalog: it is dominated
by temporary test entries and contains no useful `~/Work` project selection.
Do not publish or reuse it as the new baseline. Regenerate observed facts into
a clean review artifact after registry isolation is verified, then add explicit
ownership and selection decisions.

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

## 13. Immediate work plan

1. **Freeze the version contract.** Define the manifest and internal store
   metadata fields, compatibility rules, snapshot validation, and atomic current
   pointer. Add a reader refusal test for unknown layout/logical versions.
2. **Write logical schema v2 before DDL.** Finalize Source, Session, Interaction,
   Event, Actor, Tool Invocation/Result, Model Configuration, Artifact Link, and
   time/lineage fields. Mark every current field as keep, rename, partition,
   specialize, raw-only, or remove. `release_value` is remove.
3. **Build vendor mapping matrices.** For Claude, Codex, and Cursor, map exact
   fields and variants to the logical model, including absent/unsupported
   evidence, archive semantics, model settings, roles/origins, tool statuses,
   parent sessions, context compaction, and memory operations.
4. **Implement a new snapshot writer.** Build beside the current store, preserve
   the `0.1.0` baseline, validate counts/order/lineage/integrity, and promote only
   after success. Do not add an in-place migration path for derived events.
5. **Repair and republish the catalog.** Verify test registry isolation, move the
   polluted registry aside as evidence rather than editing it into shape, run a
   clean topical scan, classify ownership, and publish the candidate review set.
6. **Create the first compatibility corpus.** Use a small active set covering all
   three vendors and at least one cross-vendor project. Keep WP as deferred and
   `jsonschema` as reference unless a specific format case needs them.
7. **Add mixed-query acceptance tests.** Verify stable ordering, nullable true
   start times, source-mtime fallback, prompt-to-many-events relationships,
   tool call/result correlation, source and normalized status, model overrides,
   compaction versus memory, and same-artifact cross-vendor correlation.

Only after these pass should broader historical discovery, ranking refinements,
or full raw capture become the priority.
