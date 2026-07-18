# Codess — session record store

Codess discovers locally retained Claude Code, Codex, and Cursor sessions,
normalizes them into per-Project SQLite stores, and supports cross-session and
cross-vendor investigation.

## Documentation

This README is the user and customer guide. For the other authoritative views:

- **[Product specification](Codess.md):** goals, requirements, concepts, and the
  complete documentation map.
- **[Engineering guide and work plan](CoPlan.md):** repository architecture,
  configuration, CLI implementation, tests, priorities, and open decisions.
- **[Maintainer runbook](Operations.md):** validation, publication, evidence,
  relocation, storage, retention, and process recovery.

Schema contracts, vendor storage references, design rationale, and compatibility
evidence are indexed from **Codess.md**.

## Install

Codess currently runs from the repository:

```sh
pyenv exec pip install -r requirements.txt
pyenv exec python -m main --help
```

Use the repository's active pyenv environment, or omit `pyenv exec` when the
required Python environment is already active.

## Basic workflow

Vendor session stores are machine-local. `scan` reads vendor indexes and
metadata; `--dir` limits results to that path and does not recursively crawl
its descendants.

```sh
# Discover known session-bearing Projects.
pyenv exec python -m main scan --dir /path/to/work --out -

# Normalize one Project. Reference mode records source identity without copying
# the complete vendor source container.
pyenv exec python -m main ingest --dir /path/to/project

# Orient, list sessions, and open one by stable ID.
pyenv exec python -m main query --dir /path/to/project --stats
pyenv exec python -m main query --dir /path/to/project --sessions --id
pyenv exec python -m main query --dir /path/to/project \
  --session-id 'codess:session:sha256:…' --show pr tool
```

### Observing ingest

Ingest prints UTC-timestamped, content-free progress to stderr while stdout is
reserved for its final result. Interactive runs show Project, vendor, source,
raw-capture, Cursor composer, derived-correlation, snapshot, skip, and failure
phases. Large source/composer and SQLite-backup phases emit periodic
heartbeats. The final line distinguishes work processed during this invocation
from the totals stored in the selected scope.

For cron or CI that treats any stderr output as exceptional, add
`--no-progress`. This suppresses live lines but still retains the bounded
structured trace in each Project's `.codess/last-ingest-report.json`; preflight
returns it in the JSON result. Each Project report has its own `status` and
diagnostic deltas, so an earlier batch failure does not mark later successful
Projects as failed. Routine reports name the immutable `snapshot_id`; an
unchanged repeat may reuse the evidence summary only for that same snapshot.

```sh
pyenv exec python -m main ingest --dirs selected-projects.csv --source cursor
pyenv exec python -m main ingest --dirs selected-projects.csv --source cursor \
  --no-progress
```

## Data and safety

The working store is `<project>/.codess/`; accepted immutable snapshots and
the Project registry live under `~/.codess/` by default. Normalized text may
be bounded, sanitized, or redacted and should not be mistaken for an exact raw
record.

Do not discard or replace a session-bearing checkout as if it contained only
Git data. Claude, Codex, and Cursor retain sources locally, and a moved or
deleted workspace can break their association with the Project. Maintainers
should follow **[Operations.md](Operations.md)** before relocation, raw capture,
baseline publication, or retention cleanup.

## Selecting Project and vendor scope

`--dir PATH` is repeatable. `--dirs FILE` accepts either one path per line or a
CSV containing a `directory_path` column; file entries are applied first and
repeated resolved paths are removed. Query and ingest default to the current
Git root, or the current directory when it is not in a Git worktree. Scan
defaults to the current directory.

These paths are selection filters over vendor indexes and retained Project
bindings, not requests to recursively traverse every descendant. A work tree
that contains several repositories therefore needs an explicit Project list or
the Projects returned by `scan`.

Use `--source cc`, `--source codex`, or `--source cursor` to select one vendor.
Query additionally accepts comma-separated unions such as `cc,codex` and
`all`. Select the Project set before vendor, session, time, or report filters so
every result has an explicit, reproducible scope.

## Investigation and research

Investigation is the primary reason to retain and normalize sessions. Use the
CLI first for stable Project/vendor/session scope and repeatable reports; use
read-only SQLite for event-level questions that the current report surface does
not yet express. The use-case IDs below cross-reference the known-gap and
active-work registers in **CoPlan.md §§8.2–8.3**.

### Capability matrix

| Use case | Current support | Commands and export | Limits |
|----------|-----------------|---------------------|--------|
| **UC1 — list sessions for one or more Projects** | Direct for current ingested snapshots; one explicit historical snapshot is also supported | `query --dir P --sessions --id`; repeat `--dir` or use `--dirs FILE`; table, JSONL, or CSV | **L-S1**, **L-S3** |
| **UC2 — select sessions by vendor** | Direct; comma-separated union | Add `--source cc`, `codex`, `cursor`, `cc,cursor`, or `all` to sessions, stats, content, tool, lineage, audit, diagnostic, permission, and artifact reports | No model/date filter yet: **L-S2** |
| **UC3 — orient by size, activity, and time** | Basic session/event totals, session bounds, tool histogram, artifact and storage/skew reports | `--stats`; `--tool N`; `--artifacts`; `storage report`; sessions CSV/JSONL for external aggregation | Totals are minimal and elapsed span is not active time: **L-M1–L-M3** |
| **UC4 — open a known session** | Direct by list ordinal, stable global ID, or an unambiguous vendor ID | `-sess N` or `--session-id ID`; `--show prompt pr agent tool perm` | Whole-session display only; terminal excerpts: **L-S2**, **L-O1**, **L-C2** |
| **UC5 — find an exchange, Interaction, or event group** | Data exists; direct SQLite is currently required | Read-only SQL by `global_id`, `session_id`, `interaction_id`, `model_turn_id`, `sequence_no`, time, tool, status, or artifact | No first-class event/window command: **L-S2**, **L-O2** |
| **UC6 — find text, a path, error, symbol, or topic** | Bounded SQL substring search over normalized fields; artifacts have a report | SQLite `LIKE` over `content`, `tool_input`, `tool_output`, or artifact locators; `--artifacts` | No FTS/topic index; text may be excerpted: **L-C1–L-C3**, **L-E2** |
| **UC7 — investigate tools, failures, denials, or compaction** | Direct fixed reports | `--lineage`, `--audit`, `--permissions`, `--task-review`, `--tool N`; vendor scope applies | Most reports are table-only and cannot feed a next selection: **L-O1–L-O3** |
| **UC8 — correlate work across vendors/artifacts** | Direct aggregate plus read-only SQL drill-down | `--artifacts --source ...`; SQL through `event_artifacts` to sessions/events | Aggregate output omits constituent event IDs: **L-O2**, **L-P1** |
| **UC9 — export and compose** | Sessions/stats support table, versioned JSONL, and spreadsheet-safe CSV | `--output-format jsonl`; `--output-format csv > result.csv`; external `jq`, SQLite, or Python | Only sessions/stats have structured formats; no saved selection input: **L-O1–L-O3** |
| **UC10 — verify exact source evidence** | Raw/live source identities and locators exist; manual resolver needed | Inspect `sources`, `source_records`, raw manifest, then the local or captured source | No record resolver; captured containers may require streaming decode: **L-C2–L-C3** |

Operationally, UC1–UC10 may be run interactively with live progress or under
automation with `--no-progress`; both modes retain the same per-Project trace
and status evidence.

“All sessions” means all sessions currently ingested and attributed to the
selected Project snapshot. It does not mean every vendor file on the machine,
every superseded snapshot, or a union of a Project's historical versions.

### Workflow A — Project or vendor session research

1. Select one Project, repeated Projects, or a maintained `--dirs` file.
2. Optionally add `--source`; filtering happens inside each read-only store
   before cross-store ordering and aggregation.
3. List sessions with stable IDs and bounds.
4. Export JSONL for programmatic pipelines or CSV for a spreadsheet/dataframe.
5. Reopen a chosen session by `--session-id`; unlike an ordinal, its global ID
   remains stable when the Project/vendor scope changes.

```sh
python -m main query --dir ~/Work/ZK/Zero400 --source cursor \
  --sessions --id --limit 50
python -m main query --dirs selected-projects.csv --source cc,codex \
  --sessions --output-format csv > selected-sessions.csv
python -m main query --dir ~/Work/ZK/Zero400 \
  --session-id 'codess:session:sha256:…' --show pr tool
```

Parameters compose as: Project scope → optional retained snapshot → vendor
scope → report mode → report-specific limit/display → renderer. Exactly one
report mode is allowed; `--id` modifies `--sessions`, while `--show` modifies
`-sess` or `--session-id`. Unscoped current `--stats` refreshes the registry's
complete Project counts; vendor-filtered or historical stats are observational
and do not overwrite that all-source registry summary.

### Workflow B — orientation, narrowing, and phases

1. Run scoped `--stats` and `--sessions` to establish corpus size and bounds.
2. Use `--tool N`, `--artifacts`, `--audit`, and `--lineage` to identify skew,
   repeated activity, failures, or cross-vendor evidence.
3. Export sessions and bucket their millisecond timestamps externally when a
   date range is enough.
4. For an activity period or task phase, query `events` by session plus
   `sequence_no`, `event_at`, `interaction_id`, or `model_turn_id`.
5. Treat `ended_at-started_at` as elapsed span. Active duration requires a
   declared inactivity-gap rule and remains a derived measure.

### Workflow C — locate and reconstruct an exchange

1. Bound the search by Project, vendor, and preferably session/time.
2. Search prompt/response/tool fields or artifact locators read-only.
3. Record the stable event global ID, source locator, session, Interaction,
   sequence, event kind, and content-completeness evidence.
4. Fetch the entire Interaction or a sequence window around the hit.
5. Resolve the original source record when the normalized value is excerpted or
   when an exhaustive search must distinguish “absent” from “not retained.”
6. Preserve the SQL/request, snapshot identity, and evidence IDs with any
   external or LLM-produced summary.

### Structured JSONL and CSV

`query --output-format jsonl` is a versioned interface for `--sessions` and
`--stats`. Stats stream one record per Project followed by one total. Each line
is a `codess.query-row/1` envelope with report, Project scope, optional row
number, and typed data. Its contract is `schema/query-row-v1.json`, independent
of the CoSchema database version.

`query --output-format csv` covers the same two reports. CSV is intended for
spreadsheets, pandas, R, DuckDB, and shell pipelines. It uses Python CSV quoting
and protects string cells that could be interpreted as spreadsheet formulas.
Redirect stdout to a `.csv` file; diagnostics remain on stderr.

Requirements are deterministic ordering, stable global identities, explicit
scope, bounded output, and additive evolution within a row version. An
incompatible JSON row meaning requires a new row version. CSV column additions
must be documented; consumers requiring a strict contract should prefer JSONL.

## Direct read-only SQLite investigation

Direct SQL is the present event-level escape hatch and a design laboratory for
future first-class reports. Prefer retained snapshot databases: they are
immutable, versioned, hash-checked inputs. Do not edit, vacuum, reindex, attach
with write intent, or create FTS tables inside an accepted snapshot.

Resolve a Project's current retained snapshot and inspect its vendor stores:

```sh
PROJECT="$HOME/Work/ZK/Zero400"
SNAPSHOT="$(jq -r .path "$PROJECT/.codess/current.json")"
ls "$SNAPSHOT"/*.db
sqlite3 -readonly "$SNAPSHOT/sessions_cc.db"
```

Inside the SQLite shell:

```sql
PRAGMA query_only = ON;
.headers on
.mode box

-- Per-session orientation. Times and spans use Unix milliseconds.
SELECT s.source, s.global_id, count(e.id) AS events,
       count(DISTINCT e.interaction_id) AS interactions,
       sum(e.event_kind='message.prompt') AS prompts,
       sum(e.event_type='tool_call') AS tool_calls,
       sum(coalesce(e.content_len,0)) AS original_body_chars,
       sum(length(e.content)) AS stored_body_chars,
       round((s.ended_at-s.started_at)/60000.0,1) AS elapsed_minutes
FROM sessions s LEFT JOIN events e ON e.session_id=s.id
GROUP BY s.id ORDER BY events DESC;

-- Locate candidate hits, retaining stable identity and phase information.
SELECT e.global_id, s.global_id AS session_global_id, e.sequence_no,
       e.interaction_id, e.event_kind, e.tool_name,
       datetime(e.event_at/1000,'unixepoch') AS event_utc,
       substr(e.content,1,240) AS excerpt
FROM events e JOIN sessions s ON s.id=e.session_id
WHERE lower(coalesce(e.content,'')) LIKE '%python 3 fixes%'
ORDER BY e.session_id, e.sequence_no;

-- Reconstruct the selected Interaction in canonical order.
SELECT sequence_no, global_id, event_kind, subtype, tool_name,
       coalesce(content,tool_input,tool_output) AS material
FROM events
WHERE session_id=:session_id AND interaction_id=:interaction_id
ORDER BY sequence_no;

-- Daily activity for a narrowed session selection.
SELECT date(event_at/1000,'unixepoch') AS day, count(*) AS events,
       count(DISTINCT interaction_id) AS interactions
FROM events WHERE session_id=:session_id AND event_at IS NOT NULL
GROUP BY day ORDER BY day;
```

For a one-shot CSV export:

```sh
sqlite3 -readonly -header -csv "$SNAPSHOT/sessions_cursor.db" \
  "SELECT global_id,source,started_at,ended_at FROM sessions ORDER BY ended_at DESC" \
  > cursor-sessions.csv
```

Python's standard library offers the same safety boundary:

```python
import sqlite3
from pathlib import Path

path = Path(snapshot_db).resolve()
conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
conn.execute("PRAGMA query_only = ON")
rows = conn.execute("SELECT global_id, source FROM sessions").fetchall()
conn.close()
```

SQLite's documented `mode=ro` URI opens read-only. Use `immutable=1` only for a
retained snapshot that truly cannot change; SQLite warns that falsely marking a
changing file immutable can yield incorrect results. Never use it against the
live Cursor database or another WAL-backed vendor store.

Useful external exploration tools include:

- [SQLite CLI](https://sqlite.org/cli.html) for reproducible SQL, query plans,
  and CSV/JSON output;
- [sqlite-utils query](https://sqlite-utils.datasette.io/en/stable/cli-reference.html#query)
  for parameterized SQL with JSON, JSONL, CSV, or TSV output; and
- [Datasette immutable mode](https://docs.datasette.io/en/stable/cli-reference.html#datasette-serve)
  for a local browser, facets, SQL, JSON API, and CSV export over retained
  snapshots. Bind only to localhost, disable downloads if appropriate, and do
  not publish private session databases.

Generic tools expose the physical schema and do not implement Codess's
cross-store ordering, Project bindings, source compatibility, or snapshot
contract. SQL that becomes a repeated workflow is a candidate for the typed
query service rather than an indefinitely copied snippet.
