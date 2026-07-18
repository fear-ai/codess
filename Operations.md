# Operations — maintainer runbook

**Audience:** corpus curators, release maintainers, evidence maintainers, and
operators responsible for accepted baselines and retained storage.

Daily user investigation belongs in **README.md**. This runbook covers
non-mutating preflight, processing limits, storage and retention, bounded source
access, evidence refresh, curation, and compatibility baselines.

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

## Resource bounds and processing

Defaults are 8 GiB per source, 500,000 normalized events per source, and 250,000
per session. Override with `--max-source-bytes`,
`--max-events-per-source`, and `--max-events-per-session`, or deliberately use
`--no-resource-limits`. Equivalent environment variables use `CODESS_` names.

Ingest emits `codess: progress` lines to stderr without waiting for Python
DEBUG logging. Stdout remains the final human/structured result. Each line has
a UTC timestamp, elapsed time, a stable phase name, and content-free fields such as
Project/source/composer identity, counts, byte sizes, and phase duration. Cursor
traces selection-marker computation, cohort restore or capture, periodic SQLite
backup progress, compression/object verification, composer read-buffer
heartbeats, composer writes, and unchanged skips. All vendors expose Project,
vendor, snapshot, completion, and failure boundaries. A long operation should
therefore show its current phase; `-v/--verbose` remains separate DEBUG logging.

Routine ingest writes `.codess/last-ingest-report.json` with
`progress_format: codess.progress/1`, the same bounded `progress_events`, source
bytes, event counts, largest buffered session, peak process RSS, limits, and
diagnostics. Preflight includes the trace in its JSON result. Progress records
never contain prompt, response, tool, attachment, or raw-source bodies. The
trace retains at most 5,000 events and explicitly reports any dropped count.
Cursor runs add `cursor_cohort.status` (`unchanged`, `reused`, or `captured`),
bounded-marker/capture elapsed time, source/materialized/stored byte counts when
available, and the process RSS high-water mark.
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

CoSchema v4 deliberately does not persist token observations. The storage
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
silently folded into raw-object garbage collection. Cleanup receipts retain the
selected paths, validation result, and reclaimed allocation; the runbook does
not preserve dated cleanup chronology.

Pruning is mark-and-sweep and dry-run by default:

```sh
python -m main storage prune --registry ~/.codess --output /tmp/codess-prune.json
python -m main storage prune --registry ~/.codess --apply
python -m main storage prune --registry ~/.codess --working-archives --output /tmp/codess-archives.json
python -m main storage prune --registry ~/.codess --working-archives --apply
```

The default plan also rejects multiple current, distinct revisions of the same
logical raw source when each revision is at least 1 GiB. This prevents several
Project snapshots from silently pinning near-copies of a mutable global Cursor
database. Use `--keep-comparison-revisions` only when those revisions are
intentional comparison evidence. Otherwise capture one deliberate Cursor
source cohort, rebuild the affected current Project snapshots against it, and
run the dry-run/apply sequence; do not remove an object while an immutable
current manifest still names it.

For a multi-Project Cursor capture, a **cohort** is one transactionally
consistent backup of the mutable global Cursor SQLite database, not a Project
classification. Before any backup, ingest calculates a bounded marker for each
Project's selected workspace headers and composer bubble-key ranges, then
compares those markers with Project ingest state. If all markers are current,
it neither backs up nor materializes the global DB and
does not create no-op snapshots. Otherwise it captures once and applies indexed
workspace/composer queries for every selected Project. A fresh capture is
queried directly from its temporary standalone backup; it is not immediately
decompressed from the raw object again. Each successful Project manifest
therefore names the same content-addressed object and original live source
locator.

`~/.codess/cache/cursor-cohort-v1.json` is a replaceable metadata-only cache; it
does not contain a second database copy. When another Project needs the same
unchanged cohort, ingest verifies and streams the retained raw object into one
temporary query database. `--force` bypasses cache reuse. Cache deletion affects
performance only. The pre-capture selection marker is deliberately retained as
the state guard: if selected header or bubble evidence changes after the marker
was read, the next invocation revisits that Project instead of treating the
backup as current.

SQLite backups are normalized to `journal_mode=DELETE` before capture so the
standalone object remains queryable through a strict read-only connection
without live WAL sidecars.

Raw object identity is the decompressed source digest. A valid existing zstd
encoding is reused after streaming verification even if a different compressor
version or level would produce different stored bytes; the manifest records the
stored digest and size of the encoding actually retained. Incremental rebuilds
also remove normalized Source revisions no longer referenced by any current
session/event, preventing stale `source_records` from accumulating while raw
snapshot history remains governed by retention.

The plan validates each central current pointer and manifest, every current DB
hash and SQLite quick-check, each raw-manifest hash, and retained raw-object
presence and size. Full raw verification separately reads the compressed
representation and the decompressed source in fixed 1 MiB chunks, so a multi-
gigabyte Cursor backup is never materialized in memory. It then lists every
superseded snapshot and every object not
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
  Exact `capture`/`seal` still requires one SQLite backup when the bounded
  selection marker changes or a selected Project lacks captured evidence, so
  WAL state is included. Main-file size/mtime is both too coarse and incomplete
  in WAL mode. Routine Cursor change detection reads one SQLite snapshot and
  hashes exact selected header fields plus every selected bubble key/length and
  the first/last 512 value bytes. This deliberately ignores unrelated Cursor
  workbench/global state. A retained/reused cohort remains a
  fully SHA-256-addressed raw backup and cache restoration verifies both its
  compressed and decompressed identities; the selection MD5 is never an
  authenticity or retained-object integrity claim. A same-length change wholly
  inside a large bubble could evade the edge sample only if Cursor also failed
  to update its selected composer header; use `--force` when investigating that
  vendor-behavior boundary.
  Selected bubble rows are ordered by indexed key range, normalized one
  composer at a time, and written within one rollback-capable transaction. This
  bounds multi-composer accumulation, but the largest composer is still the
  unit needed for timestamp ordering, duplicate suppression, and Interaction
  construction. The measured high-water result and remaining within-composer
  streaming work are tracked as **CoPlan L-E3/A9**.
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

The current source audits find Claude exact model/service tier, Codex exact
model/effort and newer service tier, Cursor exact model selections, and Cursor
accepted/rejected tool decisions. No distinct speed tier or direct Codex parent
identifier has been observed. `available` in the inventory distinguishes raw
source evidence from normalized-store counts so an old baseline cannot make a
source capability look absent. Evidence-gap and corpus-expansion actions are
governed by **CoPlan A12/T4–T5**, not by this procedure.

Useful bounded component audits are:

```text
python -m main evidence audit claude-features --max-record-bytes 65536
python -m main evidence audit codex-features --max-record-bytes 65536
python -m main evidence audit cursor-features
```

The JSONL audits never retain message, reasoning, instruction, argument, or
result bodies. Records above the configured ceiling are drained and counted as
oversize rather than allocated or parsed.

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

## Baseline inventories

Three different records must not be conflated:

- `catalog/reviewed-baselines.json` is the frozen, bounded compatibility set
  described in **CompatibilityReview.md**.
- `catalog/approved-baselines.json` is the explicitly published operational
  selection.
- `~/.codess/projects/*/current.json` points to every Project's current central
  snapshot, including snapshots that are not members of either catalog.

The JSON catalogs and current pointers are authoritative; this runbook does not
copy their Project lists or snapshot IDs. Run `python -m main baseline verify`
to check the published set against package identity, policy, hashes, SQLite
integrity, global IDs, ordering, raw evidence, and query-smoke requirements.

Routine reconciliation may pass
`~/Work/Code/SWEmore/active_work_projects_since_2026-05.csv` to `--dirs`.
Cursor's central database is measured once per multi-root scan; its unattributed
aggregate may appear as `(global)`, but is not a Project or registry member.
Project rows use only composer IDs linked by workspace headers.

A relocated Project can retain vendor-owned evidence at its original local
locator. An approved `.codess/source-links.json` maps that immutable source
identity to the current Project location. `ZK/insight`, for example, retains
Claude evidence under its prior storage slug; neither the vendor store nor
source locators are rewritten.

## Claude background process recovery

This appendix covers hung tests and Claude-managed background commands. It is
an operating procedure, not a project work queue; current work remains in
**CoPlan.md §8**.

Claude's task view and the operating-system process list track different state.

| State | Inspect | Stop or update |
|---|---|---|
| Shell process | `jobs`, `ps` | `kill`, or a timeout around the command |
| Claude-managed background command or agent | `/tasks` | Task controls in Claude Code or `TaskStop` |
| Claude task-list item | `~/.claude/tasks/<session>/` | Update task status; it is metadata, not a process |

Stopping one layer does not prove that the others changed. Files under
`~/.claude/tasks/` contain task descriptions and statuses, not live PIDs.

### Bound commands that may hang

Use the project's pyenv environment. Add GNU `gtimeout` when a command needs a
hard deadline:

```bash
pyenv exec pytest tests/
gtimeout --kill-after=5s 180s pyenv exec pytest tests/
```

After 180 seconds `gtimeout` sends `TERM`; five seconds later it sends `KILL` if
the command is still alive. Do not add `--foreground` when children must also be
timed out. Exit status `124` means the deadline expired; `137` indicates `KILL`.

Claude Code may move a long Bash call into the background. The environment
variables `BASH_DEFAULT_TIMEOUT_MS` and `BASH_MAX_TIMEOUT_MS` control Bash tool
timing, but neither proves that an external process exited.

### Inspect before killing

```bash
jobs -l
ps -o pid=,ppid=,pgid=,state=,etime=,command= -p <pid>
ps ax -o pid=,ppid=,pgid=,etime=,command= | rg '[p]ytest|[p]ython.*specific_script'
```

Match a distinctive script, test path, or argument. Counts such as
`pgrep -c python3` include unrelated work and are not safe cleanup criteria.

Stop only a confirmed process:

```bash
kill -TERM <pid>
ps -p <pid>
kill -KILL <pid>  # only if the same process remains
```

Before signaling a process group, compare its PGID with the current shell:

```bash
ps -o pid=,ppid=,pgid=,command= -p <pid>
ps -o pgid= -p $$
```

Use `kill -TERM -- -<pgid>` only when the target group is confirmed to be
separate from the shell. Never use blanket commands such as `pkill python3`, and
never reuse PIDs copied from an old log.

### Reconcile Claude-managed work

Use `/tasks` to inspect work known to the current Claude session. Stop the
selected command or agent through Claude Code, then check `ps` if it launched
external workers or detached a daemon. Deleting `~/.claude/tasks/` files does
not stop an OS process.

Tests that create child processes should own teardown in a fixture or `finally`
block. The project does not need a general-purpose reaper.
