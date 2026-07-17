# Codess design decisions

This document records the design decisions behind the implemented CoSchema v3
foundation and the remaining corpus/catalog/query work. `CoSchema.md`,
`schema/coschema/contract.json`, and `schema/coschema/sqlite/schema.sql` are the
authoritative logical description and executable layout.

The immediate goal is reliable ingestion and comparison of recent, active work
from Claude Code, Codex, and Cursor. Exhaustively finding every historical
session or repository is less important than preserving evidence, mapping the
three vendors consistently, rebuilding reproducibly, and supporting mixed
queries.

## 1. Decisions and priorities

### Implemented foundation

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

### Remaining concepts

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

## 11. Raw evidence and sidecars

Do not put full `source_raw` blobs in the main query database. They enlarge
backups, mix sensitive evidence with normalized search data, and make retention
and redaction all-or-nothing. Raw capture should be explicit and policy-driven.

The older local `SessionRec.md` proposed a useful hybrid—normalized SQLite plus
raw sidecar JSONL. Retain the hybrid architecture, but do not make converted
JSONL the raw format: it cannot preserve a Cursor SQLite source byte-for-byte
and may discard unknown fields, ordering, encoding, or database structure.

### Proposed `codess.raw/1` format

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

Exact backup reuse is safe only when a revision guard covers the main database
and WAL before and after backup and resolves to an already verified raw object.
The main file's mtime/size is insufficient in WAL mode. Content addressing
currently deduplicates stored bytes after backup; it does not avoid the backup
or whole-buffer compression cost, which is why streaming remains pending.

Large raw capture is the next resource-boundary change. The current capture
implementation reads an ordinary source or completed Cursor SQLite backup into
one byte string and produces another full compressed byte string. Replace that
with a chunked pipeline: SQLite backup or stable source file → incremental
content hash → streaming zstd writer → incremental stored hash → atomic
content-addressed rename. The temporary output must live on the destination
filesystem, be removed on every failure, and publish only after source-stability
and stored-size/hash checks. Peak memory should be approximately the configured
chunk/buffer sizes, not source size.

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

### Review catalog seed

Repository counts and commit-recency totals are deliberately not retained here;
they age quickly and overrepresent reference collections. Repository discovery
and vendor-session discovery remain separate observations. Use
`~/Work/Code/SWEmore/active_work_projects_since_2026-05.csv` as the maintained
active-work candidate input, not Git-repository recency or an old GitHub list.
Its rows seed this review queue, which must be refreshed with current vendor
observations before selection:

| Local candidate | Evidence and current disposition |
|---|---|
| `ZK/Zero400` | Priority: active-work list plus meaningful Claude/Cursor evidence |
| `ZK/zerowalletmac` | Imported compatibility candidate: one current Claude session plus two Cursor sessions linked explicitly from the former `zerowallet400` workspace; direct root/`src` Cursor traces still have no headers |
| `Code/Misses` | Accepted Claude stress baseline: 18 main plus 105 subagent sessions, 26,658 events, 373 external artifacts, and 123 captured source revisions; root identity is the repository root |
| `Code/CodeSess` | Priority: active implementation and `.codess`; locate/validate current sources from all three vendors |
| `Spank/spank-py` | Priority: active-work list, harness markers, meaningful source evidence, and an old store that should be rebuilt |
| `Spank/spank-rs` | Accepted Codex baseline: four sessions and 31,046 events; the nested `perf` Cursor workspace maps to the repository root but contains no attributable composer sessions |
| `Claude/CContext` | Candidate/path-mapping case: active-work list, weak marker, and current zero-session trace |
| `Claw/setpack` | Accepted large-single-session Codex baseline: 8,473 normalized events from one 18,223-record source despite no repository marker |
| `Spank/HECpoc` | Candidate/path-mapping case: substantial local work but current zero-session trace and no marker |
| `ZK/Zebro` | Local active candidate with no harness marker yet; current configured GitHub remote was unavailable, which does not invalidate the local repository |
| `ZK/Requihash` | Local active candidate with no harness marker yet; current configured GitHub remote was unavailable, which does not invalidate the local repository |
| `Codex` | Candidate: recent local work but no harness marker; verify relevant session evidence before inclusion |
| `Github/Schema` | Needs explicit review: present in the CSV, but `Work/Github` is dormant by default and its current zero-session trace is not an ingestion success |

The CSV remains a list of **local active-work candidates**, not a promise that
any recorded remote still exists. The generated catalog therefore marks every
remote `unchecked`; remote availability is updated only by a new, dated
observation and never inferred from an old list.

Supplement the CSV with evidence-driven candidates it does not currently list:
`Code/SWEmore` itself remains a priority baseline. `ZK/ZeroPerf` is now an
accepted Claude baseline with eight sessions, 7,398 events, 71 artifacts, and
nine raw revisions including one external tool-result file. Dormant `WP/wp`,
`WP/wpages`, and `WP/harduw` are accepted compatibility baselines; their former
working stores were preserved where present. `WP/multiwp` and `WP/must-py` were
stale Claude-index observations and are not current candidates. `Code/jsonschema`
is an external/reference fixture only.

`Code/CodingTools`, including the upstream Codex checkout whose Rust workspace
is `codex/codex-rs`, is third-party reference source. Git recency or local LLM
sessions there may justify compatibility inspection, but do not make it owned
work or authorize corpus onboarding.

The remaining zero-session traces (`Github/skip` and any unresolved paths
above) are discovery diagnostics or path-mapping work, not evidence of usable
session ingestion.

`ZK/ZKs/insight` was relocated to `ZK/insight`. Its Claude store deliberately
retains the historical slug and is joined to the current checkout through an
approved source link. The accepted baseline contains 14 sessions, 8,644 events,
80 artifacts, four external tool-result sources, and 18 captured raw revisions.

The old personal registry is not reused as catalog truth. The maintained CSV is
now transformed into `catalog/active-work-review.json`, with observed CSV facts,
local availability, remote status `unchecked`, path-derived conservative
curation, and an empty human-review decision kept in separate objects. Refresh
it with `tools/build_review_catalog.py`; then merge current vendor scan evidence
and explicit review decisions without overwriting observations.

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
then verifies the written set before success. `baseline apply` remains the expensive per-Project rebuild
and fixed-point operation. A future `baseline refresh` may compose apply for
each selected Project followed by freeze, but must expose every Project result.

Evidence audits are capability-specific rather than symmetrical wrappers for
their own sake. Cursor currently has a broad structural feature audit; Codex
has a bounded parentage audit. A Claude wrapper is justified when it answers a
maintained question such as raw role/source shapes, tool outcome and permission
fields, compaction, sidechain parentage, model fields, or harness-version drift.
Implement it as `evidence audit claude-features` over reusable
`audit_claude_features()`, retaining counts and field population but no
conversation bodies. `evidence gather` calls vendor audits once and may emit
their full component reports plus the aggregate inventory; sequential wrapper
runs are not the normal refresh procedure.

Project-location lifecycle needs explicit complementary operations:

- `catalog location add --project-id ID --path PATH` associates an additional
  location after identity and conflict checks;
- `catalog location retire --project-id ID --path PATH` retires a location
  without inventing a replacement, requiring captured durable evidence when it
  would remove the last reproducible source location; and
- `catalog relocate --project-id ID --from OLD --to NEW` composes add, pointer
  installation, retained-snapshot read verification, and retirement.

Current ingest can ensure a binding for its path, while `retire_project.py`
actually performs relocation because `--new-location` is required. Neither is
a safe explicit “add this second location to the known Project” command. The
public catalog operations now provide add, retire, and relocation; retain the
old script as a compatibility wrapper through the removal checkpoint.

### Code partition for operations and wrappers

Partition by semantic ownership and reuse, not command count:

- `src/codess/`: domain operations returning typed dictionaries/dataclasses;
  no argument parsing or terminal rendering;
- `src/cli/`: parsing, dispatch, rendering, exit-code mapping, and composition;
- `tools/`: temporary developer entry points and compatibility wrappers only;
  no unique business rules or SQL;
- `scripts/`: deprecated compatibility surface, removed only after replacement
  commands pass tests and documented workflows are updated;
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

## 13. Seven key directions and execution order

The numbered directions below are also the intended execution order. Each step
establishes the contract or evidence needed by the next; avoid broad historical
ingestion until this path works on a small, representative corpus.

### 1. Establish a durable store contract — implemented

Package the logical schema, SQLite layout/DDL, constraints, required indexes,
taxonomies, validation rules, and fixtures as `codess.coschema`. Define the
manifest and `store_meta`, assign the SQLite application ID, encode the CoSchema
format in `user_version`, declare reader compatibility, and reject unsupported
formats. A detached database must be self-identifying and safely readable by a
known Codess release.

### 2. Finalize CoSchema v3 — implemented

Define Source and Source Revision, Session, Interaction, Model Turn, Event,
Actor, Tool Invocation/Result, Model Configuration, Artifact, and Artifact Link,
including identities, relationships, ordering, time provenance, nullability,
and lineage. Disposition every current field as keep, rename, partition,
specialize, raw-only, or remove. `release_value` is removed and fabricated
fallback values and overloaded fields before writing the new DDL.

### 3. Produce explicit vendor mappings — implemented with evidence gaps

Create field-by-field Claude, Codex, and Cursor mapping matrices. Preserve exact
source types, roles, statuses, model settings, and tool names alongside common
values. Document absent, unsupported, inferred, invalid, redacted, and discarded
evidence. Cover parent/subagent relationships, archive semantics, commands,
skills, tool call/results, context compaction, and memory. Every normalized fact
must be traceable to source evidence and a tested mapping rule.

### 4. Build immutable snapshots and raw capture — implemented

Implement a writer that builds beside the current store, validates the result,
and atomically promotes it without modifying the prior baseline. Implement
`codess.raw/1` for exact JSONL capture and transactionally consistent Cursor
backup, with `none`, `reference`, `capture`, and `seal` modes. Hash sources, raw
objects, stores, and manifests; preserve the matching software identity. Rebuild
derived data by default rather than migrating it in place.

For a clean worktree, software revision is the Git commit. For a dirty
worktree, snapshot identity also includes a SHA-256 over status, the binary Git
diff, and every untracked file's path and bytes; `commit+dirty` alone is not a
reproducible software identity.

### 5. Repair project discovery and cataloging — catalog seed implemented

Permanently isolate test registries and retire the polluted personal registry
as evidence. Seed the clean review catalog from
`active_work_projects_since_2026-05.csv`, then add vendor-session observations.
Separate scan facts from human curation; record topic, ownership, activity,
selection state, mapping quality, and dated remote observations. Treat reference
collections and `Work/Github` as non-active by default, without allowing missing
remotes to invalidate local work.

### 6. Create a small compatibility corpus — implemented with known gaps

The frozen SWEmore, spank-py, and Zero400 set covers Claude, Codex, Cursor, tool
cycles for Claude/Codex, subagents, compaction, mixed-vendor project timing, and
current mapping hazards. Golden fixtures cover same-artifact multi-vendor
queries and shapes absent from the frozen corpus. Current real evidence contains
Cursor `toolFormerData` call/result lineage, `modelInfo.modelName` selections,
and Claude/Cursor references to the same normalized artifact paths in an
approved workspace. This is evidence of shared files, not authorship.

### 7. Deliver useful mixed queries — implemented

Implement and test cross-vendor session/event queries, deterministic ordering,
Interaction and evidenced Model Turn grouping, tool call/result correlation,
source versus normalized status, model configuration, and artifact correlation.
Queries may report that multiple coding systems touched the same project or
artifact, with evidence and confidence, but must not assert unsupported
authorship.

### Common questions and a query workflow

Prioritize questions that recur in corpus review and operations, plus the
usage/reset/burn-rate views proven useful by
[CodexBar](https://github.com/steipete/CodexBar) and
[Claude Code Usage Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor).
Do not build a generic natural-language-to-SQL surface first.

| Priority | Question | Current method | Missing method |
|----------|----------|----------------|----------------|
| 1 | What changed since the preceding scan, ingest, or usage observation? | Registry observations and storage-report deltas | Versioned entity-level new/changed/removed result |
| 2 | Which Projects or sessions need review? | Preflight, diagnostics, audit, candidate review, resource/skew reports | One health summary with reasons and evidence IDs |
| 3 | What is the current vendor usage, reset horizon, pace, and likely monthly total/cost? | Monthly Claude/Codex observations; Codex diagnostic | Verified quota/reset and price sources; confidence-aware forecast |
| 4 | What consumes storage and what is safely reclaimable? | `storage report` and dry-run `storage prune` | Saved threshold comparison only when routine automation resumes |
| 5 | Which recent sessions exist for a Project/vendor/model, and how large/long are they? | Sessions, stats, taxonomy, direct SQL | Typed filters and duration/content-size projections |
| 6 | Where did a prompt, response, error, path, symbol, or topic occur? | Bounded session display and direct SQL | Scoped content search; optional rebuildable FTS index |
| 7 | Which vendors touched the same Project or artifact, and what is the evidence? | Artifact and correlation reports | Typed correlation result with confidence and source locators |
| 8 | What happened around a user request, tool call/result, denial, compaction, or abort? | Session, lineage, permissions, and audit reports | One ordered interaction/turn window |
| 9 | Which tool/command outcomes failed, were orphaned, or lack mappings? | Lineage, audit, diagnostics | Composable status/tool/source filters |
| 10 | What intent, decisions, and unresolved work can be summarized from selected evidence? | Manual bounded review | Optional derived summary that cites event/source IDs and records its processor |

Every formulated query should become a versioned request independent of the
physical SQLite schema. A `codess.query-request/1` contains:

- a stable `question_kind` and optional saved-query name;
- scope by Project/location/workspace, vendor, session, and time interval;
- typed filters for text, event/record kind, actor/role, tool, status, model,
  artifact, and diagnostic reason;
- projection, grouping, ordering, row/byte limits, and content policy; and
- requested freshness: current retained snapshots by default, or an explicit
  historical snapshot.

The planner resolves durable Project identities to current store paths, rejects
ambiguous or stale scope, pushes indexed identity/time/tool/path predicates into
each read-only SQLite store, streams bounded rows, merges deterministically, and
only then aggregates or summarizes. Exact IDs, time, tool, status, and artifact
queries use B-tree indexes. Text search must first be bounded by Project/time/
record kind. Current `events.content`, `tool_input`, and `tool_output` have no FTS
index, so ad hoc substring search is an explicit bounded scan. If repeated use
justifies it, add a separately versioned, rebuildable FTS5 projection after
content filtering; do not make FTS tables part of the durable CoSchema contract.

A `codess.query-result/1` response contains the normalized request, observation
and data-as-of times, selected store/snapshot identities, summary, typed rows and
aggregates, evidence references, confidence, and explicit truncation or missing-
data limitations. Stream large row sets as `codess.query-row/1` JSON Lines;
write one JSON result for bounded aggregates; derive a table or Markdown view
from the same typed result rather than scraping terminal output.

Saved queries should be declarative JSON/YAML definitions invoking one runner,
not one wrapper script per question. Manual and post-ingest execution come
first. A saved query can compare with its prior result, set threshold conditions,
and return stable exit codes without sending notifications or mutating external
systems. Periodic scheduling is postponed; when resumed, record the query
definition hash, input snapshot IDs, result path, duration, rows/bytes examined,
peak memory, and whether output was truncated. Any LLM-generated summary is a
derived processing record and must cite the bounded rows it saw.

### Remaining maintenance sequence

1. Implement bounded streaming for exact raw capture without changing routine
   selective Cursor access.
2. Continue Codex counter-attribution experiments until the token result can be
   accepted or permanently limited as non-billing evidence.
3. Prototype the query request/result planner with the first five operational
   questions before adding content FTS or natural-language formulation.

Proactive baseline maintenance, periodic storage/query automation, and vendor-
mapping audits are postponed. Existing gates still run when code changes.
Restart the respective work only for a package/source-format change,
unexplained growth, or observed unmapped vendor evidence. Codex parentage stays
unsupported until a direct referential field appears. Broad historical
discovery and additional vendors likewise require a concrete compatibility or
correlation gap.
