# Operations — preflight, structured output, resource bounds, and evidence

## Ingest preflight

`codess ingest --validate` runs real source discovery, vendor adapters, content
policy, CoSchema writes, mapping diagnostics, and SQLite integrity/foreign-key
checks against temporary databases. It forces parsing even when incremental
state says a source is unchanged. It does not alter the Project's `.codess`,
Project catalog, registry statistics, raw store, snapshots, or ingest state.

The `codess.ingest-preflight/1` JSON result contains source/session/event counts,
diagnostics, resource observations, limits, content-failure review records, and
temporary-store checks. This proves current records can normalize under the
current package. It does not
prove raw durability, snapshot promotion, or a two-run fixed point;
`python -m main baseline apply` is the acceptance gate for those properties;
`tools/apply_and_verify.py` is its compatibility wrapper.

## Structured query rows

`query --output-format jsonl` is a versioned prototype for `--sessions` and
`--stats`. Stats stream one bounded record per Project followed by one total.
Each line is a `codess.query-row/1` envelope with report, Project scope,
optional row number, and typed data. Its independent contract is
`schema/query-row-v1.json`, not the CoSchema database version.

Requirements are deterministic ordering, JSON-native numbers/nulls/objects,
stable global identities, explicit report and Project scope, bounded lines, no
terminal sanitization, and additive evolution within a row version. Incompatible
row meaning requires a new row version.

SQLite JSON functions, `.mode json`, Datasette, sqlite-utils, pandas, or generic
row dictionaries help exploration but are not the API: they expose physical
layout, omit cross-store report semantics, and turn DB migrations into output
breakage. JSON Schema is a lightweight boundary validator. Pydantic is not yet
needed because there is one producer emitting already typed values.

## Resource bounds and processing

Defaults are 8 GiB per source, 500,000 normalized events per source, and 250,000
per session. Override with `--max-source-bytes`,
`--max-events-per-source`, and `--max-events-per-session`, or deliberately use
`--no-resource-limits`. Equivalent environment variables use `CODESS_` names.

Routine ingest writes `.codess/last-ingest-report.json` with source bytes, event
counts, largest buffered session, peak process RSS, limits, and diagnostics.
Event counts are checked while normalized records are collected, so a configured
limit rejects before the complete oversized buffer is retained. Cursor decoding
projects envelopes to mapped fields before retaining them; completed source
buffers are explicitly deleted and garbage collection follows the transaction.
Content excerpts retain per-record limits.

A size, content-type/shape, or character-set failure is not assumed to be bad
content. Preflight and routine reports add a
`codess.ingest-content-review/1` record with the stage, vendor, exception class,
safe size/type/encoding observations, candidate causes, and recommended checks.
Review wrong source scope, wrong session boundary, container/binary content
mistaken for text, and an unmapped vendor variant before classifying the source
as malformed or overriding a limit. These records retain no content excerpts.
An override is an explicit operational decision, not automatic recovery.

One selected multi-session Cursor source is still the transaction buffer. If
real evidence approaches the event maximum, use a staging table and
composer-at-a-time writes in one transaction rather than silently raising the
defaults.

## Storage observations and retention

`python -m main storage report` records a dated
`codess.storage-observation/1` document under
`~/.codess/observations/storage/` and returns the same JSON. Each run compares
current totals with the preceding observation. `--no-record` is the read-only
inspection form; `--output` writes an additional copy.

The report covers current CoSchema database logical/allocated size, SQLite
page/freelist utilization, table counts, prompt/response/tool text counts,
largest sessions, sessions with at most two events, Cursor database size,
current and superseded snapshot allocation, and referenced/unreferenced raw
objects. It warns above 2 GiB for one CoSchema database and 10 GiB for Cursor;
use `CODESS_MAX_CODESS_DB_BYTES` and `CODESS_MAX_CURSOR_DB_BYTES` for configured
defaults or command options for one report.

CoSchema v3 deliberately does not persist token observations. The storage
report instead streams distinct current source URIs into a versioned derived
token observation grouped by month/model/source. Claude message usage is
deduplicated and labeled `local_observed`. Codex positive cumulative deltas are
labeled `local_derived_provisional` until their reset/fork/interleave behavior
is validated against the CodexBar lineage algorithm. Cursor remains explicitly
unavailable because no verified local token field is mapped. These are usage
observations, not billed cost, and are never inferred from text length.

`python -m main storage token-validate` is the Codex validation prototype. It
selects only Codex source files referenced by current stores and reports
cumulative counter drops, repeated points, timestamp regressions, model changes,
and counter points shared across files. `billing_ready` remains false whenever
those observations make attribution ambiguous. The report contains counters and
source paths, not conversation text; `--output` saves an explicit copy.

Storage locations and cleanup boundaries are:

- immutable snapshots: `~/.codess/projects/<project-id>/snapshots/`;
- current pointers: `~/.codess/projects/<project-id>/current.json` and the
  project-local `.codess/current.json`;
- content-addressed raw objects: `~/.codess/raw/codess.raw-1/objects/`;
- pre-package working archives: `<project>/.codess/working-archives/`.

The active retention policy keeps exactly the central `current.json` snapshot
for each Project and the raw objects named by those current raw manifests. It
does not retain a historical snapshot merely because it is old, reviewed, or
named as a parent. A parent snapshot ID is durable lineage information, not a
promise that the parent's bytes remain resolvable. Working archives are a
separate, explicitly selected retention class.

Project-local `working-archives` contain pre-package normalized databases, not
vendor transcripts or current source evidence. `storage prune` inventories them
but selects none by default. `--working-archives` selects only archives whose
catalogued Project has a current central snapshot; apply remains explicit and
the receipt records every removed path and reclaimed allocation. They are not
silently folded into raw-object garbage collection. The reviewed July 17 sweep
removed five such trees after validation and reclaimed 603,422,720 allocated
bytes.

Pruning is mark-and-sweep and dry-run by default:

```sh
python -m main storage prune --registry ~/.codess --output /tmp/codess-prune.json
python -m main storage prune --registry ~/.codess --apply
python -m main storage prune --registry ~/.codess --working-archives --output /tmp/codess-archives.json
python -m main storage prune --registry ~/.codess --working-archives --apply
```

The plan validates each central current pointer and manifest, every current DB
hash and SQLite quick-check, each raw-manifest hash, and retained raw-object
presence and size. It then lists every superseded snapshot and every object not
referenced by a current manifest with reclaimable allocation. `--apply`
recomputes that plan immediately, performs only the listed removals, checks the
zero-candidate postcondition, and writes a receipt below
`~/.codess/receipts/retention/` (or `--receipt`). It does not delete vendor
stores, Project working databases, unselected working archives, or observation
history.

Approved/reviewed catalogs are checked before deletion. A catalog whose
selected `snapshot_id` is superseded blocks apply: run `baseline freeze` after
the current baselines have passed validation, or explicitly remove the stale
catalog member if it is no longer approved. Never rewrite only its snapshot ID,
because its semantic digest and validation evidence describe the old build. An
old `parent_snapshot_id` is reported but does not pin storage. Active
Project-local `.codess/current.json` pointers are also checked; a stale one
blocks apply and should be repaired by a validated rebuild/relocation that
updates both central and local pointers.

### Full-scan boundaries

Routine work should begin from selected Projects and current pointers, not from
all vendor history:

- Cursor ingestion resolves workspace IDs to composer headers, then uses
  indexed key ranges for only those composers. Even an explicit all-composer
  audit uses a bounded prefix range rather than `LIKE`. A full transactional
  Cursor backup occurs only for raw capture, not querying.
- Cursor's live `composerHeaders` indexes select a workspace's composers, and
  `cursorDiskKV`'s unique key index selects `bubbleId:<composer-id>:` ranges.
  Counts and byte totals use `COUNT(*)` and `length(value)` without JSON decode;
  ingest decodes only selected rows. A logical export of selected rows can be a
  useful derived artifact, but it is not an exact raw copy of the vendor store.
  Exact `capture`/`seal` still requires one SQLite backup so WAL state is
  included. Main-file size/mtime alone cannot safely cache that backup while a
  WAL exists; any capture-reuse key must fingerprint the main file and WAL
  before and after backup and refer to a verified raw object.
- Claude resolves the selected Project's storage directory. Candidate discovery
  reads top-level session indexes only; feature audit is explicitly bounded by
  `--max-files`.
- Codex has no vendor Project index, so Codess still enumerates active/archive
  JSONL filenames once per operation. A persistent
  `~/.codess/cache/codex-session-index-v1.json` maps
  `(path, size, mtime_ns)` to session ID, cwd, timestamp, and optional record
  count. Unchanged transcripts are not reparsed, missing paths are dropped, and
  one in-memory inventory is shared by every selected root and Project during a
  scan or ingest.
- Token accounting selects only distinct source URIs referenced by current
  stores. `~/.codess/cache/token-usage-v1.json` fingerprints that complete
  current source set by path, size, and `mtime_ns`; unchanged observations reuse
  the prior monthly result without opening transcripts. A changed source
  currently causes a complete selected-set recomputation. Specialize this to
  per-file aggregates and Claude deduplication identities only if routine churn
  makes that recomputation material.
- `storage report` enumerates current stores directly. It reads only current raw
  manifests; it lists snapshot directories and raw object filenames once to
  measure reclaimable storage. `storage prune` necessarily performs the same
  one-pass mark/sweep inventory.
- Candidate Git discovery, vendor feature audits, baseline validation, and
  evidence gathering are explicit review operations. Their whole-set scans are
  kept off routine ingest/query paths and bounded by selected roots, depth, file
  limits, or current catalog membership.

### Where text actually resides

- Vendor Claude/Codex JSONL and Cursor `bubbleId:<composer>:*` values contain
  the source prompt/response text that remains in the vendor store. A captured
  or sealed raw object preserves the exact source container.
- `events.content` contains the normalized prompt or response excerpt;
  `tool_input` and `tool_output` contain normalized tool material. These fields
  may be sanitized, redacted by policy, and bounded, so they are searchable
  projections rather than exact raw text.
- `content_objects` and relation tables type/link normalized inline content or
  raw/derived objects; storage class determines whether the content itself is
  inline. A content-object row is not automatically an exact vendor record.
- `sessions`, `interactions`, and `model_turns` define identity and boundaries,
  not prompt/response bodies. `source_records` provides locators,
  classification, and parameters; it does not by itself contain the source
  body. Projects, locations, and workspace bindings likewise contain no chat
  text.

## Evidence inventory

`python -m main evidence gather` searches current catalog Projects and local vendor
metadata without retaining conversation bodies. It checks cross-vendor artifact
identity, effort/speed/service settings, direct Codex parents,
lifecycle/missing-time evidence, and Cursor tool/model shapes. Relevance-ranked
results live in `catalog/evidence-inventory.json`.

The current inventory found real Claude/Cursor shared artifact paths in Zero400
and real missing-time records. It still found no Codex parent identifier and no
effort/speed/service settings. Expand the corpus only for a high-relevance
missing shape; use approved active workspaces for maintenance evidence.

## Curated workflows

These command families use shared domain operations. Old tools and scripts
remain compatibility entry points during the removal review.

Candidate review combines production scan observations with optional maintained
CSV/catalog data and bounded local Git activity. It is read-only by default,
does not crawl repositories unless requested, and never checks remotes without
an explicit network option. Recommendations explain `consider`, `defer`, or
`exclude`; only an explicit review decision can authorize curated onboarding.

The normal curator workflow is intentionally two human actions:

1. refresh candidate observations and record decisions; and
2. onboard the `approved` selection.

Onboarding itself exposes plan, preflight, and apply in one structured receipt,
with stop points after plan or preflight. Operators and CI retain direct access
to each stage; ordinary users do not have to manually shuttle a scan CSV through
several scripts. `ingest --dirs` remains available for an explicit path list.

Baseline publication similarly composes safe stages: validate accepted member
reports, atomically replace each selected catalog with pair rollback on a
detected failure, then verify the written set.
The read-only verify operation remains separately callable for CI. Evidence
gathering runs vendor audit functions once and can emit both detailed component
reports and the aggregate inventory.

Location management distinguishes adding a second location, retiring a location
without replacement, and relocating from old to new. The historical
`retire_project.py` requires a new location and is therefore a relocation
wrapper; the explicit operations are under `catalog location` and
`catalog relocate`.

## Current compatibility baselines

The July 2026 gap pass added accepted, captured, fixed-point baselines for
`Claw/setpack`, `Code/Misses`, `Spank/spank-rs`, `ZK/insight`, `ZK/ZeroPerf`, `WP/wp`,
`WP/wpages`, and `WP/harduw`. Each current snapshot passes SQLite integrity and foreign keys,
manifest counts and hashes, global-ID checks, event ordering, JSON validation,
raw stored/content hashes, project policy, and all query-smoke modes. The only
bounded mapping diagnostics are historical Codex results without call IDs:
323 in `spank-rs`, 36 in `wpages`, 30 in `setpack`, and 9 in `harduw`.

Routine reconciliation may pass
`~/Work/Code/SWEmore/active_work_projects_since_2026-05.csv` directly to
`--dirs`. Cursor's central database is measured once per multi-root scan; its
unattributed aggregate can be displayed as `(global)` but is not a Project or a
registry entry. Project rows use only composer IDs linked by workspace headers.

Relocated projects can keep vendor-owned source data at its original local
locator. An approved `.codess/source-links.json` maps that immutable source
identity to the current Project location. `ZK/insight` uses this mechanism for
Claude transcripts retained under the former `ZK/ZKs/insight` slug; neither the
Claude store nor its source locators are rewritten.
