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

### Two managed versions, several recorded facts

Seven independently managed version numbers would create ceremony without
useful compatibility. Maintain only these public versions:

| Managed version | Meaning | Changes when |
|---|---|---|
| `software_version` | Released Codess application, currently `0.2.0` | CLI, reader, writer, adapter, or query behavior is released |
| `store_format` | Durable package containing the common logical schema, SQLite layout/DDL, constraints, and normalized taxonomies | A stored baseline can differ in structure or defined meaning |

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

Everything else is recorded provenance, not a separately governed release:

| Recorded fact | Why retain it |
|---|---|
| `software_revision` | Exact Git/build identity, including dirty state |
| adapter implementation identity | The software release/revision and adapter name already identify shipped mapping code; add a separate adapter package version only if adapters become independently distributed |
| `source_format` and observed harness version | Upstream evidence used for support decisions; these are properties of input data, not Codess versions |
| Python, SQLite, and platform versions | Reproduction and diagnosis; the store package may declare a minimum SQLite capability, but the SQLite runtime is not another Codess release train |
| snapshot ID, policy/configuration digest, and source fingerprints | Identify the exact baseline contents without pretending they are schema versions |

For example, a corrected Codex mapping normally advances the Codess software
version and produces a new immutable snapshot, but does not advance
`store_format` if the resulting records obey the same schema and taxonomy. A
schema or taxonomy change advances the store format. This preserves the useful
distinctions without exposing seven knobs.

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
3. Repeat `format_id`, `format_version`, package digest, `created_by` software,
   and snapshot identity in `store_meta`; put the same contract plus hashes and
   provenance in the external manifest.

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

Linked Git worktrees require both identities. Record the worktree Git directory,
common Git directory, branch, HEAD, and remote observation. Two CodeSess
Projects may remain separate analysis/curation units when their vendor
workspaces and session purposes differ while still sharing one repository
identity for repository-level correlation. A shared common Git directory is
strong local evidence of that relationship, but does not by itself merge their
Project IDs or session scopes.

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

### Content processing contract

Content processing is the configurable boundary between vendor evidence and
normalized query content. Vendor record shapes remain in the vendor schema
documents; persisted content and derivation entities remain in **CoSchema.md**.
Implementation wiring is indexed from **CoPlan.md §5**.

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

Digest roles remain deliberately separate. MD5 is the approved fast,
non-authenticating routine update fingerprint; it is not used for durable raw
identity. `codess.raw/1`, snapshot manifests, and established global IDs use
SHA-256. BLAKE3 would be a good high-throughput cryptographic content digest
only through a maintained implementation such as the Rust-backed Python
package—not a local reimplementation. It is not currently installed, and
changing existing IDs or `objects/sha256/` paths would be a format/identity
migration with little threat-model benefit. Evaluate it for `codess.raw/2` or a
new measured digest role rather than silently applying it “across the board.”

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
design prose. The maintained active-work CSV may seed
`catalog/active-work-review.json`, but neither an old GitHub list nor this
document is authoritative for current paths, remotes, session counts, or
approval.

The catalog keeps observed facts, policy recommendations, and human decisions
separate. Remote state is a dated observation and missing remotes do not
invalidate local owned work. Reference collections and dormant trees remain
non-active by default unless a concrete compatibility or correlation need
changes their classification.

Current candidate review and onboarding needs enter the central registry under
**CoPlan T5**; broad discovery or corpus expansion remains governed by
**CoPlan P4**. Machine catalogs and receipts retain the actual Project set.

### Candidate review, selection, and batch onboarding

Candidate review is a **curation view over observations**, not another vendor
scanner and not ingest authorization. It consumes `run_scan()` results, an
optional maintained candidate CSV or catalog, and bounded local repository
observations. It must not duplicate Claude, Codex, or Cursor discovery.

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

The compatibility spelling is `codess candidate-review`; its primary
command-family location is `codess catalog candidates`. The interface is
read-only unless an explicit output/update option is given:

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

- identity: Project ID when known, observed path, logical name, and topic;
- vendor evidence: sources, sessions, events, bytes, time range, harness/source
  shape, mapping diagnostics, and last observation;
- local Git evidence: repository root, HEAD, last commit time, commits since
  cutoff, dirty state, configured remote URL, and observation time;
- curation: ownership, activity, selection state, review decision
  (`approved`, `deferred`, or `excluded`), reviewer, notes, and reviewed time;
  and
- policy result: `consider`, `defer`, or `exclude`, with named rules and reasons.

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
then verifies the written set before success. `baseline apply` remains the
expensive per-Project rebuild and fixed-point operation. A composed refresh, if
promoted under **CoPlan P8**, preserves every per-Project result.

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
  would remove the last reproducible source location; and
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
codess.baseline_operations    preserve/archive/apply/fixed-point orchestration
codess.baseline_catalog       catalog construction, freeze, rollback, and verification
codess.evidence               common store summaries and aggregate inventory
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

### Typed request and result contract

A first vertical `codess.query-request/1` / `codess.query-result/1` path is
implemented for sessions, overview, event rows, and bounded search. It is
independent of the physical SQLite schema. The implemented request contains:

- a stable action;
- CLI-resolved Project scope plus vendor, session, snapshot, and time scope;
- typed filters for text, event kind/ID, Interaction, Model Turn, status, exact
  model, and artifact path;
- action-appropriate row and byte limits; and
- explicit current or named-snapshot freshness.

Catalog/location/workspace selectors, actor/role/tool predicates, projection,
grouping, caller-selected ordering, saved-query names, and content-policy
selection are planned extensions, not silently accepted fields.

The target planner resolves stable Project identities, rejects ambiguous or
stale scope, pushes indexed identity/time/tool/path predicates into each
read-only store, streams bounded rows, merges deterministically, and only then
aggregates or summarizes. The prototype rejects unsupported fields and pushes
its implemented predicates into each store, but cross-store heap merge and
complete limit pushdown remain A9 work. Exact identity and bounded predicates use ordinary indexes.
Text search is first bounded by Project, time, and record kind. Any FTS
projection is a separately versioned, rebuildable derivative rather than part
of durable CoSchema.

A `codess.query-result/1` contains the normalized request, observation and
data-as-of times, selected package/store/snapshot/policy identities, bounds,
summary, typed rows with stable evidence IDs, and explicit truncation or
missing-data limitations. The existing `codess.query-row/1` JSON Lines contract
remains the legacy sessions/stats streaming form; a typed streaming projection
is added only when scale evidence defines its contract. Tables, CSV, and
Markdown are renderings rather than inputs scraped back into the system.

Saved investigations are declarative JSON requests evaluated by one runner,
not one wrapper script per question. Stable-ID result chaining, prior-membership
comparison, and stable success/change codes are implemented. Threshold
conditions and persisted derivation records remain A7 work. An LLM-produced
summary must become a derived processing record and cite the bounded rows it
received.

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

The present implementation owns steps 1–5 for the first four actions and step
7 for event evidence. Interaction windows, derivation records, and a guided UI
remain incremental work under A3/A7/A8.

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

Therefore A9 is primarily a query-execution refactor—push predicates/limits to
each SQLite store, stream and heap-merge ordered rows, and profile allocations.
External recipes consume immutable inputs or typed exports. A vendor-neutral
SQL view is promoted only after two independent consumers repeat the same row
contract; DuckDB remains optional and testable at the boundary.

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
an explicit set. Current and named-snapshot reads exist; diff, union, and broad
registry discovery remain postponed until reusable results and comparison
semantics are mature enough to preserve observation identity.

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
