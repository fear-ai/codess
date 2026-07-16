# CoSchema v2

CoSchema is Codess's vendor-neutral logical record model and its current SQLite
store format. Functional meaning is defined by
`schema/coschema/contract.json`; the SQLite layout is defined only by
`schema/coschema/sqlite/schema.sql`. Vendor facts remain in `CCSchema.md`,
`CodexSchema.md`, and `CursorSchema.md`; executable translations are declared in
`schema/mappings/` and implemented by the adapters/store mapper.

## Package and version identity

The released package is `schema/coschema/` plus the three mapping profiles.
`schema/coschema/manifest.json` names and hashes every package file. Runtime
initialization refuses a package whose files do not match that manifest.

One monotonic integer versions the whole readable store contract:

- format ID: `codess.coschema`
- format version: `2`
- SQLite `application_id`: `0x434F4445` (`CODE`)
- SQLite `user_version`: `2`
- Codess software version: independent, currently recorded in `store_meta` and
  each snapshot manifest

We do not separately version every table, index, taxonomy, adapter, or vendor
mapping. A change advances the CoSchema format only when the stored contract or
reader requirements change. Adapter corrections normally require a new software
release and rebuilt snapshot, not a new database format.

Released packages are immutable. Unknown package or database formats fail
closed. Legacy unversioned stores may be read through the compatibility query
surface but cannot be mutated; rebuild creates v2 stores beside retained
baselines.

## Core terms

- **Source** — one observed revision of vendor evidence, identified by source
  system, locator, and revision. A source is not a session and need not be
  retained as a raw object.
- **Interaction** — one user- or environment-initiated unit that can encompass
  several model turns, tool calls/results, harness events, and requests for more
  input. Its boundary may be vendor-provided, mapped, inferred, or manual.
- **Model turn** — one bounded model execution within an interaction. It is not
  assumed to equal a displayed message or a user/assistant pair.
- **Actor** — the producer or operative principal represented by
  `actor_kind` (for example human, model, harness, tool, agent, or system).
  `content_role` separately records how content is presented, and `origin_kind`
  records where it came from. This avoids forcing all harness input into
  `user` and all model output into `assistant`.
- **Artifact** — a file, URI, repository object, or other durable object an event
  reads, creates, modifies, deletes, executes, or mentions. Observed absolute
  paths are evidence; project-relative paths are the preferred portable key.

## Functional entities

| Entity | Purpose and identity |
|---|---|
| `projects` | Stable logical project identity plus observed root/cwd, ownership, activity, and selection state |
| `sources` | Immutable observed source revision; unique by source system, URI, and revision |
| `model_configurations` | Provider/model family/exact name and independently settable effort, speed, service, and mode values |
| `sessions` | Vendor/harness container; vendor session ID is scoped by source system and may be absent |
| `interactions` | Initiating work unit, ordered within a session, with explicit boundary source/confidence |
| `model_turns` | Model execution, ordered within a session and optionally linked to an interaction |
| `events` | Ordered normalized observation with preserved vendor type/subtype and mapping trace |
| `tool_invocations` | Requested operation with source/free-text tool name, optional canonical name, input, and status |
| `tool_results` | One or more ordered results linked to an invocation when source evidence permits |
| `artifacts` / `event_artifacts` | Durable objects and evidence-backed operations on them |
| `mapping_diagnostics` | Source-, record-, or field-level loss, rejection, or ambiguity |
| `correlation_assertions` | Reviewable cross-session/project/vendor claims with method, evidence, and confidence |

The exhaustive field, nullability, reference, ordering, range, and vocabulary
definitions are machine-readable in `contract.json`; this document does not
duplicate that list. SQLite compatibility projection columns in `sessions` and
`events` preserve the existing query surface but are not the v2 identity model.

## Important field decisions

### Identity and paths

`source_system_id` identifies the source/harness namespace; a vendor session ID
alone is not globally meaningful. Product, vendor, harness, storage format, and
surface are separate because vendors reuse storage structures across IDE, CLI,
desktop, agent, and API packaging.

The CLI now displays a deterministic `codess:session:sha256:...` global ID
derived from the source-system namespace and vendor session ID. This prevents
cross-store ambiguity without changing the released SQLite layout. The current
`sessions.id` remains the vendor/local compatibility key; persisting global
entity and observation keys belongs in the next approved schema package. A
path hash or inode is not a substitute: paths identify locations and inodes do
not survive copying or cloning.

`root_path` is the normalized project anchor. `source_cwd` is what the source
actually reported. `relative_path` is preferred for artifact correlation;
`observed_absolute_path` preserves local evidence. Source locators are URIs or
absolute observed paths and are never treated as portable project identity.
An artifact resolving outside `root_path` is not assigned a misleading `../`
project-relative key. It uses a `file:` URI, retains the absolute observation,
and records `path_scope=external` plus the source spelling in metadata. This
allows later project correlation without claiming that the file belongs to the
session's selected project.

### Ordering and time

`sequence_no` is the deterministic within-session order and is required for
interactions/model turns and present for mapped events. Event sequence values
must be positive and are unique within a session. Source record locators and
vendor IDs remain alongside it for lineage.

`started_at`, `ended_at`, and `event_at` are explicit vendor/mapping timestamps
or `NULL`. Codess does not manufacture them from file modification time.
`source_mtime` is captured separately. `time_basis`/`event_at_basis` tells an
application which evidence supports a time value. SQLite stores event-oriented
numeric time as Unix milliseconds; manifests and ingest/observation times use
RFC 3339 UTC strings.

### Types, roles, and tools

Vendor record type/subtype are retained in `source_record_type` and
`source_record_subtype`. Broad common meaning is mapped into open
`event_kind`, `actor_kind`, `content_role`, and `origin_kind` values. New vendor
values therefore remain queryable even before the common vocabulary grows.

Source tool names are free text because tool registries are vendor-, harness-,
plugin-, and version-dependent. `canonical_tool_name` is an optional mapping,
not a closed enum. `input_json`, `output_json`, and `output_text` describe the
invocation boundary explicitly; a harness subprocess is not automatically
classified as a model tool call.

`source_status` preserves the vendor value. `normalized_status` is the common
taxonomy (`pending`, `running`, `succeeded`, `failed`, `denied`, `cancelled`,
`incomplete`, `unknown`). Neither silently replaces the other.

### Metadata and mapping trace

Typed, commonly queried meaning belongs in columns/relations. `metadata` is a
JSON extension object for sparse vendor evidence that has not earned a common
field. It must not duplicate canonical fields, conceal required identity, or
become an unbounded raw-record dump. `mapping_rule` and `mapping_trace` identify
the translation responsible for a normalized event. Structured mapping
diagnostics record information that could not be mapped reliably.

There is no `release_value`. Version strings remain exact source strings in the
appropriate software/harness/model fields. There is no database `source_raw`
column; raw evidence is handled by the sidecar store.

## Raw evidence and immutable snapshots

Raw retention uses `codess.raw/1`, a content-addressed store outside query
databases. JSONL sources use a stable-file read; Cursor SQLite uses SQLite's
backup API so WAL-visible committed data is captured consistently. Captured
objects are zstd-compressed and named by the SHA-256 of uncompressed content.

`--raw-mode` controls retention:

- `none`: record that the source was not retained
- `reference`: record locator, size, and modification identity (default)
- `capture`: store a content-addressed exact revision
- `seal`: capture and hard-link/copy the objects into the snapshot

Each ingest builds `<project>/.codess/snapshots/<snapshot-id>/` beside existing
snapshots, backs up its v2 databases, writes `raw-manifest.jsonl` and
`manifest.json`, verifies package/database/raw hashes and logical counts, then
atomically replaces `<project>/.codess/current.json`. Queries prefer the
validated current snapshot. Prior snapshots and their matching software/package
identity remain available as baselines.

This current placement is not durable against deletion of the project
directory. Nor does `reference` protect Claude, Codex, or Cursor evidence from
local vendor-store deletion. Before retiring a directory, operators must use
`capture` or `seal`, validate, and preserve the complete snapshot plus its raw
objects. Moving retained baselines to a stable project-ID catalog is pending as
a deliberate store-layout revision; it is not part of the present SQLite DDL.

`tools/validate_snapshot.py` verifies the current package and immutable-file
hashes, SQLite integrity and foreign keys, manifest counts, event ordering,
artifact identity/index invariants, JSON fields, raw object recovery, mapping
diagnostic allowances, source-specific minimums, and optional Cursor scoping
and turn rules. `tools/apply_and_verify.py` applies this gate to one project at
a time and can require two rebuilds with unchanged source revisions and equal
canonical logical digests. It runs read-only query smoke tests before atomically
updating `catalog/approved-baselines.json`. Policies are versioned data under
`catalog/policies/`; their contract is
`schema/validation-policy-contract.json`.

Immediate apply validation compares a reference-only locator's current size and
mtime identity to the revision just ingested, preventing promotion after source
drift. Frozen reviewed-baseline verification does not require a live mutable
locator to remain unchanged forever; it verifies retained snapshot/store/raw-
manifest identities and reports reference reproducibility as a limitation.

The logical digest deliberately excludes snapshot creation time, surrogate
row identifiers, and SQLite layout. It includes common entities, vendor/source
values, ordering, lineage, diagnostics, artifact relations, and correlation
assertions. It therefore proves repeatable normalization for the same sources;
it is not a substitute for manual semantic review or exact raw capture.

Working databases are disposable derived state. A writer refuses a store whose
recorded released-package digest differs from the current package. The guarded
apply workflow first verifies the retained current snapshot, archives the old
working databases and ingest state with hashes, then rebuilds from source. This
is a rebuild boundary, not an in-place schema or mapping migration.

Historical queries select one retained identity with `--snapshot-id`. Exact
package matching is the default. The explicit `read-compatible` package policy
checks immutable hashes and the supported SQLite contract but warns that it
does not recreate the older mapping semantics; historical stats do not update
the current registry.

## Compatibility and change procedure

`tools/coschema_gate.py OLD_CONTRACT NEW_CONTRACT` classifies a change as same,
compatible, breaking, or manual review. It checks entity/field removal,
identity/order changes, type/nullability constraints, and vocabularies; unknown
change shapes fail closed. Fixtures under `schema/coschema/fixtures/` cover
minimal, maximal, edge, negative, and compatibility cases.

For a proposed store change:

1. Change the logical contract and mapping specs first.
2. Run the compatibility gate and record the decision.
3. Change the SQLite layout without mixing application semantics into SQL.
4. Add/update fixtures and mapping/database tests.
5. Advance `format_version` only when the readable contract requires it.
6. Hash the final package into the manifest and treat it as released.
7. Rebuild, validate, and atomically promote a new snapshot; never overwrite a
   retained baseline in place.

See `Schemas.md` for rationale and compatibility-policy provenance and
`Designs.md` for the broader source, correlation, catalog, and execution design.
