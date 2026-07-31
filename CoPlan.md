# CoPlan — engineering guide and work plan

**Audience:** contributors and maintainers changing Codess or deciding what to
do next.

This document owns repository architecture, configuration, CLI/runtime
contracts, implementation mapping, coding and test guidance, delivery order,
the actionable work queue, and engineering decisions. Product requirements
belong in **Codess.md**; user workflows in **README.md**; design rationale in
**Designs.md** and **Schemas.md**; operating procedures in **Operations.md**.

## Contents

1. [Repository layout](#1-repository-layout)
2. [System architecture](#2-system-architecture)
3. [Configuration](#3-configuration)
4. [CLI and runtime contract](#4-cli-and-runtime-contract)
5. [Feature to implementation map](#5-feature--implementation-map)
6. [Coding techniques](#6-coding-techniques)
7. [Tests](#7-tests)
8. [Central work registry](#8-central-work-registry)
9. [Change routing](#9-change-routing)

## 1. Repository Layout

**Scan** means index-led discovery of Projects that have vendor session data.
Daily commands are `scan`, `ingest`, and `query`; administrative command
families are summarized in §4.7.

```
CodeSess/
├── main.py                  # repository entry point
├── README.md                # user/customer landing page
├── Codess.md                # product specification and document map
├── CoPlan.md                # engineering guide and work plan
├── Operations.md            # maintainer runbook
├── Designs.md / Schemas.md  # rationale and schema-evolution design
├── *Schema.md               # common and vendor data contracts
├── src/cli/                 # argument adaptation, rendering, exit codes
├── src/codess/              # domain operations, adapters, persistence
├── schema/                  # machine-readable contracts and fixtures
│   └── coschema/sqlite/schema.sql
├── catalog/                 # policies, reviewed evidence, accepted baselines
├── tests/                   # unit, contract, workflow, and scale tests
└── tools/                   # compatibility and developer entry points
```

## 2. System Architecture

### 2.0 Discovery contract

Discovery is index-led. Claude, Codex, and Cursor keep session data outside the
project tree and record project paths in their own indexes or session metadata.
`--dir` and `--dirs` therefore define validated path filters; they do not request
a filesystem crawl. There is no recursion flag or general walk subsystem.

### 2.1 Call Graph and Module Roles

- **`main.py`:** Prepends `src/` → `codess.project.console_main()` → `parse_and_run()` → **`cli.scan_cmd.run`** \| **`cli.ingest_cmd.run`** \| **`cli.query_cmd.run`**. The installed `codess` entry point starts at the same `console_main()`.
- **`codess.config`:** ENV and constants; used by **`project`**, **`scan`**, **`helpers`**, **`adapters/*`**, **`sanitize`**, CLI.
- **`codess.resource_policy`:** built-in ingest maximums, strict
  `codess.resource-policy/1` loading, override validation, and effective-policy
  provenance; it has no vendor parser or CLI dependency.
- **`codess.helpers`:** Roots/CSV/excludes/slug helpers; imports **`config`**. Used by scan and root resolution.
- **`codess.sanitize`:** Shared ingest, terminal-display, tabular-output, redaction, and CSV-cell policy.
- **`codess.store`:** SQLite, DDL, upsert primitives, transactional source
  replacement, and ingest state. **`ingest_cmd`** writes it; query opens the
  resulting databases read-only.
- **`codess.ingest_pipeline`:** Shared Claude/Codex incremental admission and
  rollback-capable normalized replacement transaction; related Source writes
  commit in the same transaction and ingest state advances afterward.
- **`codess.project`:** CLI parsing/root resolution and Git/Claude-slug helpers; no Codex/Cursor storage layout or SQL.
- **`codess.project_catalog`:** Stable Project identity/location/workspace
  bindings plus exact Project-ID query-scope resolution.
- **`codess.codex_source`:** active/archive roots, session metadata, fingerprinted inventory, Project selection, and active-over-archive deduplication.
- **`codess.cursor_source`:** Cursor installation/workspace discovery, read-only connections, composer headers, indexed bubble ranges, and metrics.
- **`codess.progress`:** bounded rolling operational trace plus the live stderr renderer; no transcript content or logging-level ownership.
- **`codess.query_api`:** Typed request/result contracts, semantic predicates,
  global cross-store ordering, bounded facets/repetition summaries, saved
  selection derivation, and comparison.
- **`codess.scan`:** **`run_scan()`**; shares one `codex_source` inventory and uses selective `cursor_source` metrics.
- **`codess.storage_report`:** dated read-only CoSchema/Cursor utilization, skew, retention inventory, thresholds, and deltas.
- **`cli/*_cmd`:** Thin **`run(args) -> int`**: roots/options, then **`run_scan`** / **`_ingest_*`** / **`store.connect`**.

**Query vs ingest vs adapters:** Ingest parses sources and transactionally
replaces their normalized rows in **`.codess/*.db`**. Query runs read-only SQL
on those DBs only—no vendor files or adapters.

**§3 vs §4:** §3 documents **ENV** and **`config.py`**. §4 documents **CLI flags** and **`build_*_run_options`**, which merge **`Namespace`** with those defaults per run.

```
                         main.py
                    codess.project.parse_and_run
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
 cli.scan_cmd.run          cli.ingest_cmd.run           cli.query_cmd.run
        │                           │                           │
        ▼                           ▼                           ▼
 codess.scan.run_scan      _ingest_cc / _ingest_codex /   store.connect + SQL
        │                  _ingest_cursor                    init_db if needed
        │
        ├──► codess.codex_source
        ├──► codess.cursor_source
        ▼
 codess.config   codess.helpers   codess.project  (path helpers for scan)

 ingest_cmd ──► codess.adapters.* ──► store.replace_* … , ingest_state JSON
```

**Dependency sketch:** Codex filesystem callers use **`codex_source`** and
Cursor layout/SQL callers use **`cursor_source`**;
**`adapters.cursor`** consumes selected raw rows and normalizes them. **`scan.py`**
uses vendor source modules, not adapters. **`project.py`** owns common CLI,
Git-root, and Claude-slug helpers. **`store.py`** remains independent of vendor access.

### 2.2 Discouraged Imports

This subsection is **normative policy**, not a full import graph. It answers: *where must we not put parsing or store logic so layers stay thin?* A short checklist here is **not** “every allowed edge” — see **§2.1** for who calls whom.

- **`cli/*_cmd`:** do not parse vendor JSONL/SQLite inline; ingest goes through **`adapters/*`**.
- **`adapters/cc.py`, `adapters/codex.py`:** do not import **`scan`**, **`scan_cmd`**, or **`ingest_cmd`**.
- **`query_cmd`:** do not import **`adapters/*`**.
- **Cursor callers:** do not duplicate `state.vscdb`, workspaceStorage, table,
  or key-range knowledge; use **`cursor_source`**.
- **Codex callers:** do not duplicate active/archive traversal, metadata reads,
  or active-over-archive selection; use **`codex_source`**.

### 2.3 Data Movement — Three Pipelines

#### Discovery — Scan

- **Purpose:** Under a **work root**, which **project dirs** have session data, **which vendors**, rough **counts/sizes**.
- **Mechanism:** **Index-led** — vendor registries/listings under **`config`** roots, not a full-disk crawl. Maps paths, filters, dedupes, **`canonicalize`**, recency, **`--source`**, CSV out. File opens for metrics are **read-only**, not ingest.
- **Indices:** CC / Codex / Cursor on-disk detail → **CCSchema**, **CodexSchema**, **CursorSchema**.

**Root semantics**

- **`resolve_cli_roots`** validates and returns path filters.
- **`run_scan`** maps vendor-owned records into those roots; it does not crawl project trees.
- **`canonicalize`** prefers leaf project paths and removes configured aggregator parents.

**Other**

- **`_is_agg`:** One segment below **`work_root`** in **`AGGREGATORS`** → drop as aggregator parent, not a leaf project.
- **Scan vs ingest shape:** Scan = one CSV row, **multiple** vendors possible. Ingest = **`_ingest_cc` / `_ingest_codex` / `_ingest_cursor`** per vendor, one **`--source`** selection — shared project loop, **separate** DB files and parsers.

**Long-term:** A scan-produced project list can feed batch ingest/query through `--dirs`; no separate crawler is required.

#### Ingest

- **Purpose:** Project root → **`.codess/`** normalized **sessions** / **events**.
- **Mechanism:** **`project`** path resolution → **`adapters/*`**
  normalization → transactional **`store.replace_*`** →
  **`ingest_state.json`** mtime keys after commit.

#### Query

- **Purpose:** Read-only reporting on the local store.
- **Mechanism:** Open **`.codess/*.db`** — see **§2.4**. **`query_cmd`** does not write vendor trees.

### 2.4 Persistence Layout

The Project-local `.codess/` directory holds the local current-snapshot pointer,
incremental `ingest_state.json`, the last ingest report, and compatibility
working stores when present. Current query resolution follows the retained
snapshot pointer first and falls back to legacy working paths only when no
current snapshot is installed.

Accepted immutable snapshots live below
`~/.codess/projects/<project-id>/snapshots/` by default. Each snapshot contains
per-vendor databases such as `sessions_cc.db`, `sessions_codex.db`, and
`sessions_cursor.db`; the central and Project-local `current.json` pointers are
promoted atomically. **CoSchema.md** owns store semantics and **Operations.md**
owns retention and recovery procedures.

Changed or forced Claude and Codex transcripts replace one normalized session
transactionally. Cursor refresh replaces records owned by the selected source
database. Empty valid transcripts remove stale normalized sessions and add the
nonfatal `empty_sources` diagnostic before ingest state advances.

### 2.5 Implementation vs Validation

Verification baseline is the full **`pytest tests/`** suite. **Validated** here means representative automated coverage, not every edge case.

| Area | Implemented | Validated | Registry reference |
|------|-------------|-----------|--------------------|
| Scan (index-led) | Yes | CLI + `test_scan*`, metrics | **V-CU2** |
| Ingest | Yes | Adapters, replacement/store integration, CLI | Transactional replacement, empty sources, active/archive deduplication, continue/fail-fast handling, and scoped global Cursor ingest are covered |
| Query | Yes | CLI, store, scale tests | Read-only aggregation, global numbering, session origin details, lineage, evidence-backed audit rows, and globally bounded reports across project/vendor stores |
| **`validate_config()`** | Yes | Unit and subprocess CLI tests | Applied consistently to scan, ingest, and query |
| Store / DDL | Yes | `test_store` | — |
| Sanitize | Yes | Sanitizer, adapter, helper, and CLI tests | **P1** |

**Completeness:** Main workflows, configuration validation, source replacement,
cross-store query aggregation, lineage, audit normalization/reporting, and
bounded row reports are covered. Preflight and versioned session/stat output
are implemented. All incomplete coverage and deferred scope is classified in
§8 (known gaps and postponed topics).

### 2.6 Verified wiring

Cross-checked against **`src/`** and **`tests/`** so this plan does not drift from the repo. Re-audit after large refactors.

- **`main.py`:** prepends **`src/`**, calls **`codess.project.main()`** → **`parse_and_run()`**.
- **Dispatch:** **`parse_and_run`** lazy-imports **`cli.scan_cmd` / `cli.ingest_cmd` / `cli.query_cmd`** then branches on **`args.command`**.
- **`run_scan(work_root, …)`:** parameters are **`vendor_filter`**, **`recent_days`**, **`debug`**, and **`subagent`**. Scan is index-led and exposes no recursion option.
- **`validate_config()`:** invoked before work by scan, ingest, and query; errors are printed to stderr and return exit 1.
- **`query_cmd`:** opens every selected project store read-only and aggregates report rows in Python, avoiding SQLite's attached-database limit and preserving duplicate vendor session IDs internally. It imports **`get_project_stores`**, **no** **`adapters/*`**.
- **`scan.py`:** imports **`codex_source`** and **`cursor_source`** for vendor discovery/metrics; **does not** import adapters or **`walk`**.
- **`project.py` module imports:** contain no Codex/Cursor storage-layout or SQLite details.
- **`adapters/*`:** **no** imports of **`scan`**, **`scan_cmd`**, or **`ingest_cmd`**.
- **Central registry (`ingested_projects.json`):** **`codess.registry_store`** merges per-project records. **Scan** always upserts **`scan`** / **`last_scan`** for every discovered project path into **`resolve_registry_directory(args)`** (default **`CODESS_REGISTRY`**). **`--registry PATH`** overrides that root and, when set, **also** filters CSV to paths present in the file **before** this run + appends **`reg_*`** columns — **no** sidecar. **Ingest** merges **`sources`** / **`last_ingestion`**. **Query `--stats`** merges **`query`** / **`last_query`** into the same file (**§4**).
- **`validate_scan_source_for_cli` / scan `--source`:** invalid tokens → **stderr + exit 1** before any scan work; this is the global invocation contract in §4.1.
- **`store.init_db`:** executes **`schema/coschema/sqlite/schema.sql`** when that file exists (path resolved from **`store.py`** location).

---

## 3. Configuration

### 3.1 What Is Configurable, Why, and How

**What:** (1) **Locations** of vendor data on this machine (`CODESS_CC_PROJECTS`, …). (2) **Behavior defaults**: scan window (`CODESS_DAYS`), min ingest size (`CODESS_MIN_SIZE`), CC sidechain counts (`CODESS_SUBAGENT`), and debug/redact/force/stop/verbose flags (`CODESS_*` — see §3.3). (3) **Output/registry**: `CODESS_REGISTRY` for central **`ingested_projects.json`**. (4) Ingest resource maximums are resolved by **`resource_policy.py`** from built-ins, a versioned partial file, individual environment overrides, and CLI overrides. Adapter excerpt lengths remain code constants in **`config.py`**.

**Why:** Same codebase runs on **different OS paths**, **CI sandboxes**, and **user preferences** without editing Python.

**How:** **`config.py`** reads **environment variables at import time** into module-level `Path` / `int` / `bool`. **CLI** arguments are defined in **`codess.project.build_parser()`** and parsed by **`parse_and_run()`**; they may **override** scan/ingest behavior per invocation. Ordinary settings use CLI over ENV. Resource maximums use built-in → `codess.resource-policy/1` file → individual ENV → individual CLI; `--no-resource-limits` disables all maximums last.

**`CODESS_MIN_SIZE` / `--min-size`:** Ingest skips a source file when **`st_size < min_size`**. **`min_size == 0`** means **no size floor** (including empty files). That is **not** the same as omitting **`--min-size`**: omission currently uses the legacy **`config.MIN_SIZE`** default of 20 KiB unless overridden by **`CODESS_MIN_SIZE`** at import. This is an optional noise heuristic, not a resource guard, and can hide valid tiny Sessions. Curated onboarding already passes zero. The ordinary zero-default and structural classification of empty/tiny Sources are postponed under **P15**, not ingest-code consolidation **A11**. **`validate_config`** rejects **`MIN_SIZE < 0`**.

**Vendor roots must be absolute:** **`validate_config()`** rejects relative
Claude, Codex active/archive, and Cursor roots. Resolving a vendor root from the
process cwd is fragile for scan, CI, and daemons.

**`main.py` vs commands:** **`main.py`** only extends **`sys.path`** and calls **`codess.project.main()`**. **`project.build_parser()`** defines **one** **`ArgumentParser`** (no subparsers): positional **`CMD`** ∈ {**`scan`**, **`ingest`**, **`query`**} plus **all** flags. **`parse_and_run()`** parses **once**, sets logging from **`-v` / `CODESS_VERBOSE`**, then dispatches to **`scan_cmd.run` / `ingest_cmd.run` / `query_cmd.run`**. Unused flags for a given CMD are simply ignored by that command’s implementation.

**Options object (`project.py`):** Ordinary ENV is read **once at import** in
**`config`**. **`build_scan_run_options(args)`** /
**`build_ingest_run_options(args)`** resolve each invocation into a small
**frozen dataclass**. Resource maximums additionally inspect only their six
explicit environment names once during that resolution so a policy file can be
layered below them and each effective origin can be reported. No ENV is read
inside source/Event loops. **`scan_cmd`** / **`ingest_cmd`** pass **only** the
fields they need into **`run_scan`** / **`_ingest_*`**. **Query** can gain the
same pattern when it grows ENV-backed toggles.

**Why global args/ENV, not per-vendor sections:**

- **Vendor-specific *paths* already exist:** `CODESS_CC_PROJECTS`,
  `CODESS_CODEX_SESSIONS`, `CODESS_CODEX_ARCHIVED_SESSIONS`, and
  `CODESS_CURSOR_DATA` point at tool-owned storage on this machine.
- **Behavior knobs are intentionally *run-wide*:** One **`scan`** / **`ingest`** applies a **single policy** to every vendor selected by **`--source`** (`CODESS_DAYS`, `CODESS_MIN_SIZE`, `CODESS_DEBUG`, `CODESS_FORCE`, …). That keeps **one argv surface**, **one import-time config**, and shared loops in **`scan_cmd` / `ingest_cmd`** without a combinatorial matrix (`--min-size-cc`, `CODESS_DEBUG_CODEX`, …).
- **Vendor-only semantics** stay in **code + Schema**, not parallel ENV trees: e.g. **`CODESS_SUBAGENT`** affects **CC** scan metrics only; Cursor/Codex ignore it. Per-vendor *behavior* differences that need toggles belong in ***Schema.md** + adapter options first; new **`CODESS_*`** or flags would follow a proven need.

### 3.2 Combining `--dir` and `--dirs`

1. If **`--dirs FILE`** is passed, **`helpers.validate_dirs_file`** runs first: file **must exist**, be a **regular file**, be **readable**, and contain **≥1** usable root — otherwise **stderr** message and **exit 1** (scan / ingest / query). The file may be a plain one-path-per-line list or a candidate CSV with a **`directory_path`** column; this permits direct use of the maintained active-work CSV.
2. **`helpers.parse_dir_list(dirs_file, dir_args)`** builds **one ordered list** of **resolved** `Path`s.
3. If **`--dirs FILE`** validated, plain lines or CSV **`directory_path`** values are read **first** (in file order).
4. Each **`--dir PATH`** is **appended** in argv order.
5. **Duplicates** (same resolved path) are **skipped**.
6. **User root strings** (`--dir` lines, **`--dirs`** file): **`..`** in any path **component** is **disallowed** (skipped + warning). **Relative** paths: any segment **starting with `.`** except the lone segments **`.`** and **`..`** is **disallowed** — this blocks **hidden-style** relative segments (e.g. **`.venv`**, **`.private`**) while still allowing **`.`** (cwd) and paths like **`./repo`** (the **`.`** segment is explicitly allowed). **Absolute** paths may contain segments such as **`.config`** under the home tree. **Empty** lines / empty **`--dir`** arguments are skipped. Root strings are paths, not glob patterns.
7. If the result is **empty**: **`scan_cmd`** uses **`Path.cwd()`**; **`ingest_cmd`** and **`query_cmd`** use **`get_project_root()`** (`git rev-parse --show-toplevel` from cwd, else cwd — see **`project.py`**).

**`DEFAULT_WORK` / `is_excluded`:** There is **no** CLI flag for **`DEFAULT_WORK`** (`~/Work`). **`is_excluded(p, work_root=None)`** uses **`DEFAULT_WORK`** only as the **`relative_to`** anchor when **`work_root`** is omitted — **`scan.run_scan`** passes the real **`work_root`** into **`canonicalize`**, so exclusion is relative to the **scan root**, not **`~/Work`** unless you omit the argument in other call sites.

### 3.3 Environment Variables

Defaults in the table are when the variable is **unset**.

| Variable | Role | Default (if unset) |
|----------|------|---------------------|
| `CODESS_CC_PROJECTS` | CC projects root | `~/.claude/projects` |
| `CODESS_CODEX_SESSIONS` | Codex sessions root | `~/.codex/sessions` |
| `CODESS_CODEX_ARCHIVED_SESSIONS` | Codex archive root; set explicitly with an overridden active root | `~/.codex/archived_sessions` when the active root is default |
| `CODESS_CURSOR_DATA` | Cursor User dir | OS-specific under `Cursor/User` (see `config._cursor_data`) |
| `CODESS_DAYS` | Scan default recent days | `90` |
| `CODESS_MIN_SIZE` | Ingest skip small sources (bytes) | `20480` |
| `CODESS_FORCE` | Ingest ignore mtime state | `0` → false (see **boolean ENV** below) |
| `CODESS_DEBUG` | Verbose / debug behaviors | `0` → false (see **boolean ENV** below) |
| `CODESS_REGISTRY` | Registry dir for stats JSON | `~/.codess` |
| `CODESS_SUBAGENT` | CC scan include sidechains | `0` → false (see **boolean ENV** below) |
| `CODESS_STOP` | Fail-fast: stop whole command on first error | `0` → false; combine with **`--stop`** |
| `CODESS_VERBOSE` | Python logging **DEBUG** for the process (`-v` equivalent) | `0` → false |
| `CODESS_REDACT` | Ingest: enable redaction default (same patterns as **`--redact`**) | `0` → false |
| `CODESS_RAW_MODE` | Ingest raw evidence policy: `none`, `reference`, `capture`, or `seal` | `reference` |
| `CODESS_RESOURCE_POLICY` | Partial `codess.resource-policy/1` JSON file | no file; built-ins apply |
| `CODESS_MAX_TRANSCRIPT_BYTES` | One Claude/Codex transcript maximum | `268435456` |
| `CODESS_MAX_SOURCE_BYTES` | Compatibility alias for transcript maximum | transcript built-in |
| `CODESS_MAX_CURSOR_CONTAINER_BYTES` | One Cursor SQLite container maximum | `10737418240` |
| `CODESS_MAX_EVENTS_PER_SOURCE` | Normalized Events from one Source | `200000` |
| `CODESS_MAX_EVENTS_PER_SESSION` | Normalized Events in one Session | `100000` |
| `CODESS_MAX_CONTEXT_CONTENT_CHARS` | One context or compaction body | `250000` |
| `CODESS_MAX_CODESS_DB_BYTES` | Storage-report warning threshold for one CoSchema DB | `2147483648` (2 GiB) |
| `CODESS_MAX_CURSOR_DB_BYTES` | Storage-report warning threshold for Cursor's global DB | `10737418240` (10 GiB) |

**Boolean ENV (`CODESS_DEBUG`, `CODESS_FORCE`, `CODESS_SUBAGENT`, `CODESS_STOP`, `CODESS_VERBOSE`, `CODESS_REDACT`):** Implemented in **`config.py`** via **`env_bool()`**: **true** only if, after **`.lower()`**, the value is exactly **`1`**, **`true`**, or **`yes`**. **Unset** uses default **`0`** → false. Values like **`y`**, **`Y`**, **`on`**, **`2`** are **false** (not generic shell truthiness). Export e.g. `CODESS_DEBUG=1` or `CODESS_DEBUG=yes`.

**Why `CODESS_*` vs `DEBUG` / `FORCE` / `SUBAGENT`:** Shell and CI need **prefixed** names (`CODESS_DEBUG`, …) to avoid collisions with unrelated tools. **`config.py`** exposes short **Python** names (`DEBUG`, `FORCE`, `SUBAGENT`) as **bools read once at import** from those variables. Docs refer to **ENV** with the `CODESS_` name; code samples may show **`config.DEBUG`** meaning “the bool parsed from **`CODESS_DEBUG`**.”

**Boolean policy (flags + ENV):** Default is **false** unless the **CLI flag** is passed or the **`CODESS_*`** env parses **true** (see above). **`store_true`** flags: presence → **true**; omission → **false** at argparse, then OR with env where the table says so.

**Note on scan vs ingest `--debug`:** Both use **`CODESS_DEBUG` → `DEBUG`** via **`args.debug or DEBUG`**, but **effects differ**: **scan** uses it only for **discovery trace** + CSV shape; **ingest** uses it for adapter diagnostics/verbosity. Raw retention is controlled independently by **`--raw-mode` / `CODESS_RAW_MODE`**.

**CLI `store_true`:** There is **no** `-y` shorthand.

**Boolean and pseudo-boolean flags — by command**

- **Top-level `-v` / `--verbose`:** true when **`args.verbose or VERBOSE`** from **`CODESS_VERBOSE`**; **`parse_and_run`** sets **`logging.basicConfig(DEBUG)`**. Not the same as **`CODESS_DEBUG`** (vendor/session diagnostics) or the always-on, content-free ingest progress stream documented in **Operations.md**.
- **Scan `--debug`:** **`args.debug or DEBUG`**. **`--subagent`:** **`args.subagent or SUBAGENT`**.
- **Ingest `--debug` / `--force` / `--redact`:** each **`args.* or`** matching **`CODESS_*`**; **`--force`** argparse default stays **`False`** so omission does not imply force.
- **Query:** mode flags only; **no** **`CODESS_*`** booleans for **`--stats`**, **`--tool`**, etc.

**Validation:** **`validate_config()`** checks **`CODESS_DAYS`** in
**[0, 3650]**, **`MIN_SIZE` ≥ 0**, and every configured vendor root is
absolute. Malformed values are reported without an import traceback; every
command exits 1 before doing work.

---

## 4. CLI and Runtime Contract

**Purpose:** Operator-facing **flags**, **ENV**, and **defaults**. Vendor metric semantics → ***Schema.md**.

**Table columns:** **Flag** | **ENV** (variable name, or **—**) | **Default** (when flag omitted / ENV unset as applicable) | **Explanation**.

### 4.1 `codess scan`

| Flag | ENV | Default | Explanation |
|------|-----|---------|-------------|
| `--dirs PATH` | — | — | Plain path list or candidate CSV with `directory_path` (§3.2). |
| `--dir PATH` | — | — | Append root; repeatable. |
| *(no dirs after merge)* | — | **`Path.cwd()`** | **Scan** only; see §3.2. |
| `--source cc,codex,cursor` | — | all three | Comma-separated vendor subset; **order does not matter**. Tokens are compared case-insensitively after trim. **`all`** clears the filter (same as omitting **`--source`**). **Invalid token** (anything other than **`cc`**, **`codex`**, **`cursor`**, or the whole value **`all`**) is a **global** error: **stderr** message listing bad tokens and **exit 1** — no partial vendor set. |
| `--out PATH` | — | `codess_walk.csv` | CSV path; **`write_csv`** creates **parent directories**. |
| `--out -` | — | — | CSV to **stdout** (not **`write_csv`**). |
| `--days N` | `CODESS_DAYS` | **`90`** | Recent window; omitted → **`CODESS_DAYS`**. |
| `--debug` | `CODESS_DEBUG` | off if flag omitted **and** unset ENV | Discovery trace + CSV **`dir_path`**; **`args.debug or DEBUG`** — see **§3.3**. |
| `--subagent` | `CODESS_SUBAGENT` | **`SUBAGENT`** from ENV | **`args.subagent or SUBAGENT`** — see **§3.3**. |
| `--registry PATH` | `CODESS_REGISTRY` | — | **Directory** for **`ingested_projects.json`**: default **`CODESS_REGISTRY`** (`~/.codess`); **`PATH`** overrides for this invocation. **Scan:** always **writes** merged index metrics to that directory; when **`--registry`** is **passed**, **also** restricts CSV to paths already listed **before** this run and adds **`reg_*`** columns. **Argparse requires a path** — no bare **`--registry`**. |
| `-v` / `--verbose` | `CODESS_VERBOSE` | off | Python **`logging`** level **DEBUG** (process-wide); not **`CODESS_DEBUG`**. |

**Precedence (scan):** **`--days` omitted** → **`CODESS_DAYS`**. **`--subagent`:** **`args.subagent or SUBAGENT`**. **`Registry`:** **`project.resolve_registry_directory(args)`** selects the registry **root** for **both** scan upserts and (when **`--registry PATH`** is set) filter + join columns.

**Output columns:** `path,vendor,sess,mb,span_weeks` (with `dir_path` when `--debug`). With **`--registry`**, append **`reg_path`**, **`reg_updated`**, **`reg_sources`** — **§4.1** table. Metric definitions: **CCSchema** §7, **CodexSchema** §6, **CursorSchema** §5. Rows with **`path=(global)`** are unscoped Cursor central-DB scan aggregates, emitted at most once in a multi-root run and never registered as Projects. Project metrics and ingest use only global composers whose header workspace maps to that Project.

### 4.2 `codess ingest`

| Flag | ENV | Default | Explanation |
|------|-----|---------|-------------|
| `--dirs` / `--dir` | — | **`get_project_root()`** | Same merge as scan (§3.2); empty list → git root or cwd. |
| `--source` | — | **`all`** | `cc` \| `codex` \| `cursor` \| `all`. |
| `--min-size BYTES` | `CODESS_MIN_SIZE` | **`20480`** | Skip sources smaller than N bytes. |
| `--candidate-snapshot` | — | off | Maintainer path: build an immutable candidate without changing local or central current pointers. Baseline apply owns validation and promotion. |
| `--resource-policy JSON` | `CODESS_RESOURCE_POLICY` | built-in maximums | Load a partial, versioned maximum policy; contract in `schema/resource-policy-contract.json`. |
| `--max-source-bytes N` | `CODESS_MAX_TRANSCRIPT_BYTES`; legacy `CODESS_MAX_SOURCE_BYTES` | 256 MiB | Override the Claude/Codex transcript maximum. |
| `--max-cursor-container-bytes N` | `CODESS_MAX_CURSOR_CONTAINER_BYTES` | 10 GiB | Override the Cursor SQLite container maximum. |
| `--max-events-per-source N` | `CODESS_MAX_EVENTS_PER_SOURCE` | 200,000 | Override the normalized Event maximum for one Source. |
| `--max-events-per-session N` | `CODESS_MAX_EVENTS_PER_SESSION` | 100,000 | Override the normalized Event maximum for one Session. |
| `--max-context-content-chars N` | `CODESS_MAX_CONTEXT_CONTENT_CHARS` | 250,000 characters | Override the normalized context/compaction body maximum. |
| `--no-resource-limits` | — | off | Disable all maximums after file, ENV, and CLI resolution; reports retain this origin. |
| `--force` | `CODESS_FORCE` | **`FORCE`** from ENV if flag omitted | **`args.force or FORCE`**; argparse **`default=False`**. Ignores **`ingest_state.json`** mtime skips when true. |
| `--redact` | `CODESS_REDACT` | off | **`args.redact or INGEST_REDACT`**; patterns in **`config.REDACT_PATTERNS`**. |
| `--debug` | `CODESS_DEBUG` | **`DEBUG`** from ENV | **`args.debug or DEBUG`** — see **§3.3**. |
| `--no-progress` | — | live progress on | Suppress timestamped ingest progress on stderr while retaining `codess.progress/1` events in runtime/preflight reports. |
| `--registry PATH` | `CODESS_REGISTRY` | **`~/.codess`** | Central registry dir (`ingested_projects.json`). **`PATH`** overrides default. |

### 4.3 `codess query`

| Flag | ENV | Default | Explanation |
|------|-----|---------|-------------|
| `--dirs` / `--dir` | — | **`get_project_root()`** | Same merge as §3.2; empty → git root or cwd. |
| `--project-id ID` | — | — | Typed query only: repeat exact catalog Project IDs and resolve their durable central current snapshots. Mutually exclusive with path selectors. |
| `--project-set FILE` | — | — | Typed query: resolve canonical `codess.project-set/1` inputs; each Project may name a snapshot or resolve current. Enables explicit cross-Project/historical union. |
| `--all-current` | — | — | Compatibility spelling for a transient eligible catalog cohort. Run `catalog status` first; this selector is not a freshness or publication label. |
| *(multiple roots)* | — | aggregated | Sessions are globally ordered across selected projects. Roots without stores warn and contribute zero; all roots without stores exit 1. |
| *(multiple vendor DBs)* | — | aggregated | Every existing legacy or per-vendor store returned by `get_project_stores` participates in one logical report. |
| `--source SPEC` | — | all | Query-side vendor scope: `cc`, `codex`, `cursor`, comma-separated union, or `all`. Applied inside stores to every data-bearing report; invalid tokens fail globally. |
| `--limit N` | — | unlimited | Globally limit rows after deterministic cross-project/vendor ordering for `--sessions`, `--permissions`, `--lineage`, and `--audit`. `0` emits no rows; negative values fail before stores are opened. |
| `--session-id ID` | — | — | Show a session by stable global ID or an unambiguous vendor session ID; preferable to recency ordinal in composed workflows. |
| `--output-format table\|jsonl\|csv` | — | table | Sessions/stats have versioned JSONL and spreadsheet-safe CSV; redirect CSV stdout to a file. Other reports currently require table output. |
| `query sessions\|overview\|events\|search` | — | — | Typed actions producing `codess.query-result/1`; the legacy flag modes below remain compatibility paths. |
| `--event-id`, `--interaction-id`, `--model-turn-id` | — | — | Repeatable stable drill-down predicates for typed event/search actions. |
| `--event-kind`, `--status`, `--model`, `--tool-name`, `--actor-kind`, `--content-role`, `--origin-kind`, `--parent-session-id`, `--session-relation`, `--initiation-kind`, `--artifact`, `--text`, `--since`, `--until` | — | — | Typed normalized predicates; unknown request fields are rejected rather than ignored. Timestamps are Unix milliseconds. |
| `--expand interaction\|model-turn`, `--before N`, `--after N` | — | no expansion/window | Expand selected Event IDs to a complete Interaction or Model Turn and union a same-Session sequence window. |
| `--group-repetitions`, `--facet-limit N` | — | false, 50 | Return bounded facets and exact compatible repetition groups while preserving every occurrence. |
| `--byte-limit N` | — | 16 MiB | Maximum returned inline content bytes for typed event/search results. |
| `--save-request`, `--save-result`, `--result-input`, `--compare-result` | — | — | Atomic persistence, derivation-bearing stable-ID chaining, and prior comparison. Comparison exits 3 for added/removed/changed rows or summary/provenance change. |
| `query evidence --event-id ID` | — | — | Resolve a normalized event to source-record and verified sealed/captured/live evidence. Exit 2 means no exact candidate is available. |
| `query cite --result-input RESULT --summary-file FILE --processor-id ID` | — | — | Build `codess.investigation/1` from a supplied summary and exact bounded Event citations; Codess records but does not generate the interpretation. |
| `query configurations` | — | — | Audit normalized model/settings coverage and exact `source_config` provenance without inferring missing settings. |

**Modes:** **`--stats`**, **`--sessions`**, **`--tool`**, **`-sess`**,
**`--session-id`**,
**`--permissions`**, **`--task-review`**, **`--lineage`**, **`--audit`**,
**`--diagnostics`**, **`--artifacts`**, and **`--taxonomy`**. Exactly one report
mode is accepted; **`--show`** modifies `-sess` or `--session-id`. Session
numbers form one global recency order with
deterministic project/source/id tie-breakers; duplicate original IDs remain
distinct internally. Session rows include release and concise
origin/storage/parent details. **`--lineage`** joins Claude tool-use ids and
Codex call ids to results, and reports missing, orphaned, unlinked, or denied
outcomes. **`--stats`** prints aggregate totals. Current all-source stats merge
each Project's complete counts into **`ingested_projects.json`**;
vendor-filtered or historical stats do not overwrite that registry summary.
**`--audit`** reports only the
evidence-backed contract in **CoSchema.md**; unsupported vendor/state pairs are
not inferred. Omitting all mode flags exits 1.

### 4.4 `--dirs` File Format

- **`--dirs` file:** plain path lines (where **`#`** starts a comment) or a candidate CSV with **`directory_path`**; if **`--dirs`** is passed, it must contain ≥1 usable root — **§3.2**.
- Paths are validated directories and act as exact project roots or scan path filters; they are not recursively expanded.
- Explicit candidate Git discovery is the exception: it is depth-bounded and
  prunes a branch immediately after finding its first repository. Index-led
  vendor observations below a repository map to the nearest enclosing Git root.

### 4.5 Filter Wiring

Vendor-specific **meaning** of timestamps, sidechains, and sizes lives in **\*Schema.md** — this file only ties **which knob** hits **which code**.

- **Recent sessions:** `scan.py` with **`--days`** / **`CODESS_DAYS`**; timestamp semantics per vendor schema.
- **CC sidechains:** `scan.py` with **`--subagent`** / **`CODESS_SUBAGENT`**; detail in **CCSchema**.
- **Min source size:** ingest with **`--min-size`** / **`CODESS_MIN_SIZE`**; bytes on **source** files before parse.

### 4.6 Operational quick check

`codess scan --dir . --out -`

**Batch errors:** By default, **scan** (per work root) and **ingest** (per file /
DB / project) log failures and continue; exit code 1 if any source failed. Scan
summarizes **`malformed`**, **`invalid_keys`**, **`failed_sources`**, and
**`failed_roots`**. Ingest summarizes **`malformed`**, **`ignored`**,
**`empty_sources`**, and **`failed_sources`**; the first three are nonfatal.
**`--stop`** or **`CODESS_STOP`** makes source failures fail fast.

Incomplete CLI semantics and their dispositions are registered in §8.

### 4.7 Administrative command surface

These implemented families preserve `scan`, `ingest`, and `query`. An editable
install from `pyproject.toml` exposes `codess`; `python -m main` remains the
source-tree compatibility entry point. Focused commands and orchestrators call
the same domain operations:

```text
codess catalog candidates …
codess catalog status …
codess catalog state …
codess catalog decide …
codess catalog onboard …
codess catalog location add …
codess catalog location retire …
codess catalog relocate
codess baseline validate …
codess baseline apply …
codess baseline freeze …
codess baseline verify …
codess evidence gather …
codess evidence audit …
codess schema compare …
codess storage report …
codess storage prune …
codess storage token-validate …
```

`codess candidate-review` may remain as a discoverable alias for
`catalog candidates`. Candidate output is read-only by default and combines
production scan results with optional catalog/CSV and bounded local Git
observations. Git recursion and remote network checks require explicit flags.
Recommendations are `consider|defer|exclude`; only an explicit catalog decision
may be selected for curated ingest.

`catalog onboard` is the normal curated batch interface. It resolves entries
with one saved review decision, prints and records the plan, runs
`ingest --validate`, and applies
only when explicitly requested. `--stop-after plan|preflight` exposes stages;
the receipt preserves every stage. `ingest --dirs` remains the direct explicit
path interface.

`baseline freeze` must reuse read-only reviewed-set verification before and
after atomic catalog replacement. `baseline verify` remains separately
callable for CI and diagnosis. `evidence gather` invokes capability-specific
vendor audit functions once and may emit their detailed component reports;
vendor wrappers are focused aliases, not separate implementations.

Full semantics, user types, Git/activity justification, location lifecycle,
and code boundaries are in **Designs.md §12**.

---

## 5. Feature → Implementation Map

**Purpose:** Index of **where** features live in code (not a second copy of **§2**).

| Feature | Primary modules | Notes |
|---------|-----------------|--------|
| Multi-root roots | `helpers.parse_dir_list`, `*_cmd` | Combining `--dir` and `--dirs` |
| Vendor filter | `scan`, `ingest_cmd`, argparse | `frozenset` of names |
| Recent window | `scan`, `config.CODESS_DAYS` | ms cutoff |
| CC sidechain counts | `scan._session_metrics_cc` | **CCSchema** |
| Cursor workspace + global | `scan`, `project`, `adapters/cursor` | **CursorSchema** |
| Incremental ingest | `store.should_ingest`, state JSON | mtime keys updated after commit |
| Source replacement | `store.replace_session_events`, `replace_source_sessions` | removes stale transcript/DB-owned events transactionally |
| Tool lineage report | `query_cmd._lineage` | joins Claude/Codex ids; shows missing/orphan results |
| Audit report | `query_cmd._audit` | direct denial/failure/abort/compaction evidence per CoSchema support matrix |
| Redaction | `sanitize`, adapter opts | regex list in **config** |
| Central registry JSON | **`registry_store`**, **`ingest_cmd._save_stats`**, **`scan_cmd`**, **`query_cmd._stats`**, **`config.get_stats_path`**, **`project.resolve_registry_directory`** | **`ingested_projects.json`** is a **merged** project registry: **scan** (index metrics), **ingest** (store **`sources`**), and **query `--stats`** (counts). **`--registry PATH`** overrides **`CODESS_REGISTRY`**; **no** bare **`--registry`**. |

### Investigation capability implementation

The user-facing capability IDs are defined in **README.md**. Their code and
data owners are kept here so user workflows do not expose internal module
names.

| Use cases | Main implementation and contracts |
|-----------|-----------------------------------|
| **UC1** | `project.resolve_cli_roots`, `project_catalog.load_project_set` / `resolve_project_query_scopes`, `schema/project-set-v1.json`, `snapshot.*_store_paths_from_base`, `query_cmd.QueryScope` |
| **UC2** | `query_cmd._parse_source_tokens`, `_typed_filters`, `query_api._event_predicate`, normalized actor/role/origin/relation fields |
| **UC3** | `query_api._overview` (including bounded daily exchange/actor engagement), `query_cmd._project_counts`, `_tool_table`, `_artifacts`, `storage_report`, `token_usage` |
| **UC4** | `query_cmd._session_by_identifier`, `_show_session`, canonical `events.sequence_no` ordering |
| **UC5–UC6** | `query_api._expanded_event_predicate`, `_event_rows`, global heap merge, facets/repetition summaries, CoSchema `events`, `interactions`, and `model_turns` |
| **UC7** | `query_cmd` lineage/audit/permission/task/tool reports plus `query_api` actor/tool/status Event predicates; `tests/test_provenance_checks.py` owns the completed human/harness/tool/model source proof |
| **UC8** | `query_cmd._artifacts`, `artifact_correlation`, `correlation_assertions`, `event_artifacts` |
| **UC9** | `query_api` request/result/observation/derivation/comparison contracts, `investigation.build_investigation`, `query_cmd._typed_output`, and query/investigation JSON Schemas |
| **UC10** | `raw_store`, snapshot raw manifests, `sources`, and `source_records` |

The typed vertical path is owned by `codess.query_api`, with JSON contracts in
`schema/query-request-v1.json` and `schema/query-result-v1.json`.
`codess.evidence_resolver` owns exact event evidence precedence, and
`codess.configuration_audit` owns nullable model-setting/provenance coverage.
Legacy table/row renderers remain in `cli.query_cmd`; they do not define the
new request semantics.

### Content processing implementation

`codess.content_processing` implements byte decoding, pre-normalization, and
post-normalization hooks from the functional contract in
**Designs.md §10**. Claude, Codex, and Cursor message/result adapters call
the shared pre/post path; Claude external sidecars also use the byte decoder.
Keep action traces connected to mapping diagnostics and `processing_runs`.
Built-in adapter bounds remain the final layer after global and matching scoped
policy rules.

---

## 6. Coding Techniques

**Audience:** People changing **`adapters/*`**, **`store.py`**, or **`cli/*_cmd.py`**.

Start from the **call graph in §2.1**: ingest normalizes and replaces one source
transactionally; query reads **`store`** only.

- **Transaction boundary:** adapters yield normalized records; ingest buffers one
  transcript or one selected Cursor database result so delete/replace/insert is
  atomic, then commits before updating ingest state.
- **Cursor SQLite reads:** use read-only URI in the adapter so we do not take write locks on vendor DBs.
- **Errors:** log and skip bad lines where vendor format drifts; scan tolerates
  partial index reads. Ingest diagnostics count malformed, ignored, empty, and
  failed sources so partial data is visible without making every drift a hard
  failure.
- **Tolerant parsing:** **`JSONDecodeError`**, missing keys, and unknown records
  are skipped intentionally. Keep diagnostics and representative vendor
  fixtures current whenever a supported format changes.
- **CSV output:** **`helpers.write_csv`** for paths; **`scan_cmd`** writes stdout with **`csv.writer`** when **`--out -`** because stdout is not a path.
- **DDL:** only **`schema/coschema/sqlite/schema.sql`** via **`store.init_db()`** so schema is not duplicated in Python.
- **Host status:** prefer bounded invocations of established host tools (`git`,
  `stat`, `find`, and, when needed, `ps`, `vm_stat`/`free`, `df`, `lsof`, or
  `netstat`/`ss`) from a small shell workflow. Add Python OS/process/network
  APIs only when Codess needs a versioned machine-readable contract,
  cross-platform normalization, timeout/error semantics, or reuse inside core
  selection. Never infer source-system authorship from generic host activity.

The remaining ingest/wrapper consolidation is registered as **A11** rather than
maintained as an informal refactor list here.

---

## 7. Tests

This section sits **after** coding practices (**§6**) because tests validate
the implementation described above. Add backlog rows only for a specific
uncovered contract or reproduced defect; generic calls for “more tests” do not
qualify for a central registry row.

**Goals:** Regressions in CLI, metric math, adapters, and store — without relying on a real **`~/.claude`** tree.

**Approach:** **Unit** tests use **`tmp_path`**, fake JSONL, temp SQLite. **CLI** tests use **`subprocess`** **`python -m main …`** with **`CODESS_*`** aimed at temp dirs. **Integration** flows live in **`test_integration.py`**. Prefer **temp env** per child process; do not mutate the developer’s home directory in tests.

**Module ↔ test file** — order follows **`src/codess/`** then CLI-focused tests:

- **`test_config.py`** — **`config`**, **`build_*_run_options`** in **`project`**
- **`test_helpers.py`** — **`helpers`**
- **`test_project.py`** — shared CLI/Project paths, roots, and Claude slugs
- **`test_codex_source.py`** — Codex active/archive inventory, cache invalidation, selection, and deduplication
- **`test_store.py`** — **`store`**, **`schema/coschema/sqlite/schema.sql`**
- **`test_scan.py`**, **`test_candidate.py`**, **`test_subagent_detail.py`** — **`scan`**, scan CLI subprocess
- **`test_registry_store.py`** — **`registry_store`** merges
- **`test_*_adapter.py`** — **`adapters/*`**
- **`test_sanitize.py`** — **`sanitize`**
- **`test_cli.py`**, **`test_integration.py`** — **`cli/*`**, **`parse_and_run`**, replacement and end-to-end
- **`test_scale.py`** — bounded Cursor header/prefix-query and Codex active/archive scale checks
- **`test_storage_report.py`** — page utilization, text/session skew, thresholds, dated history, and deltas
- **`test_token_usage.py`** — Claude deduplication, Codex cumulative deltas, and explicit Cursor unavailability

**Coverage emphasis:** **`parse_dir_list`** and **`--dirs`**, scan CSV shape, adapter edge cases, and configuration validation.

### 7.1 Coverage evidence

Obtain current counts from `pytest --collect-only -q` and current outcomes from
`pytest`; do not copy those transient totals into this plan. The suite layers
are:

- **Unit/contract:** direct adapters, identity, schema, store, mapping,
  processing, query-kernel, acceptance, resource, and retention tests using
  generated records and temporary SQLite databases.
- **Functional:** CLI tests run the actual entry point in subprocesses;
  integration tests exercise ingest/replacement/query flows across Claude,
  Codex, and Cursor temporary source layouts.
- **System/real data:** approved immutable baselines run fixed-point value
  acceptance, policy, query smoke, integrity, and foreign-key checks outside
  the ordinary pytest fixtures. Zero400 additionally supplies the large Cursor
  performance and changing-live-source evidence.

Coverage measurement must enable coverage.py's subprocess patch; an ordinary
single-process run omits CLI child execution and materially understates
`query_cmd.py`. Coverage is an on-demand dated observation, not a checked-in
threshold or project-status label. Establish one reproducible
subprocess-aware command/configuration and retain its machine-readable output
before setting a gate.

Coverage percentage does not establish functional completeness. The CLI suite
includes an end-to-end bounded search → saved result → stable-ID derivation →
complete Interaction/sequence window → exact evidence workflow. A3 and A7 add
focused source-provenance and reusable-result contracts. Broader
action/renderer parity and scale/skew cases remain under A1, A2, A4, and A9.

**When adding a feature:** extend tests in the **same PR**.

---

## 8. Central work registry

This is the sole registry for active work, known gaps, open decisions,
event-triggered maintenance, and postponed topics. Other documents own product
requirements, design rationale, vendor facts, procedures, and evidence; they
link here instead of maintaining another queue.

### 8.1 Execution rules

#### 8.1.0 Designator scheme

To keep planning IDs legible, this registry uses a small fixed set. Do not mint
new prefix families; add to an existing register.

- **A** — work items (§8.2). The single register for actionable work. An item's
  lifecycle state (postponed/active/triggered/done) is a property of the item,
  not a separate ID space; `P` (§8.4 postponed) and the completed set (§8.6) are
  presentation groupings of the same work, and `T` (§8.4.3) triggers are
  conditions that *promote* work into A, not a parallel queue.
- **D** — decisions (§8.3). A resolved choice that constrains work; not itself a task.
- **Gaps** (§8.5) — known limitations. The prefixes `L-*`, `V-*`, `E-*` are
  **category facets** of one gaps register (scope/measurement/output/content/
  evidence, and vendor `CC/CU/CX/CTX`), not separate registers.
- **UC** — user-facing use cases (README capability matrix).
- **R** — settled review checkpoints (§8.1.1).

There is no durable "PR-n" designator. A proposed change is tracked as an **A**
item.

- Work active items in dependency order unless a production defect or source
  format change takes priority.
- Land each feature vertically: request/contract, data operation, renderer or
  interface, compatibility path, unit/scale tests, real-store smoke test, and
  the affected README capability row.
- A vendor fact or research idea becomes work only when it receives a registry
  ID here.
- Rebuild derived stores and replace accepted baselines rather than mutating
  them in place.

#### 8.1.1 Current decisions

- **R1:** CoSchema format 4 is accepted and current. Formats 2 and 3 remain
  read-only compatibility inputs; derived stores are rebuilt, not migrated.
- **R2:** routine fingerprints are fast, labelled, and non-authenticating.
  Software 0.2.1 writes SHA-256 for full ordinary files through 64 MiB,
  bounded sampling above it, main-plus-WAL composition, and Cursor's
  transactionally read selected headers plus bubble key/length/512-byte edges.
  Exact retained objects use complete SHA-256. Unsupported historical digest
  labels do not satisfy current live-reference validation and follow the
  generic mismatch/rebuild path.
- **R3a:** authoritative occurrence provenance remains per-event JSON with the
  source record/locator/field and exact designation. Normalized configuration
  columns are not occurrence history.
- **R3b:** a materialized configuration-observation table is postponed until a
  demonstrated query requires it. A rebuildable projection is preferred over
  prematurely expanding the central format.

Preserve useful vendor/release evidence, normalized common mappings, exact
source designations, and dated immutable snapshots. `--force` remains the
escape hatch for suspected fingerprint sampling or vendor-timestamp gaps.

#### 8.1.2 Review backlog disposition

This is the single disposition for the former long numbered review. A row is
either active under one owner, postponed under one restart condition, or
dismissed; its feature list is not itself another task list.

| Former item | Precise name | Disposition and unpacking method |
|---:|---|---|
| 1 | Typed query-kernel hardening | **A1/A9.** Keep the implemented version-1 typed request/executor. Test only use-case-required predicates, bounds, and execution equivalence now |
| 2 | Reusable investigation packages | **P17.** Package infrastructure is later-phase research; the first-tranche scenarios below remain acceptance cases for existing A-items |
| 3 | External query-specification composition | **P17.** Compare carriers and client tooling only when the later phase starts; no version-2 JSON shape is approved |
| 4 | Resolved-cohort identity and readiness | **A25 completed.** `catalog status` reports each Project and `N/N` query-ready coverage. Exact results retain resolved Project/snapshot identities. Source refresh remains separately assessed |
| 5 | Result-field selection and result identity | **A7** owns mandatory result identity and constituent IDs. Caller-selected field projection moves to **P17**. It is not developer telemetry |
| 6 | Typed result composition | **A7** owns homogeneous result/replay operations; **A19** investigates cross-Project analytical products. Heterogeneous joins are not implied |
| 7 | Provenance checks | **A3 completed** for the four-actor core; **A12** applies the same source-specific method to model/configuration facts. A check begins with a claimed behavior and exact source evidence, not a combinatorial matrix |
| 8 | Search report | **P18**, further phase. Preserve canonical order and all occurrences now; restart only from a recorded investigation in which useful matches were materially hard to find |
| 9 | Allocation and execution measurement | Existing bounded execution remains **A9**; deeper measurement and limit promotion remain **P14–P16** |
| 10 | Analysis datasets and exports | **A19** may investigate a manifest and direct query. SQLite/JSONL/Parquet/DuckDB Assembly exports are **P19** and follow requirements comparison |
| 11 | Source-specific preservation | The completed **A3-Claude/Codex/Cursor** contract covers the core exchange; configuration provenance continues under **A12**. Common mappings never erase namespaced source evidence |
| 12 | Read-only SQL equivalence and diagnostics | **A9.** Add fixture differential tests, direct SQL reconciliation, query-plan inspection, and representative real-snapshot smoke tests in that order |
| 13 | Raw-source search | **P13**, further phase. Normalized search and exact evidence resolution remain the current supported paths |
| 14 | Capability requirements | UC1–UC11 below are the requirements index. Each remaining behavior must name inputs, output/evidence, bounds, failure/completeness semantics, and a validation case before entering an A-item |
| 15 | Developer execution reporting | **A9/P14.** Phase timing, row/allocation counters, SQL plans, and RSS are maintainer evidence and remain outside caller result projection |

Newly discovered work is handled in this order: reproduce against an existing
UC; decide whether it is a defect, missing requirement, or research idea;
attach it to an existing A/P item when the owner and exit criterion match;
otherwise add one compact gap row with a restart trigger. Duplicated feature
lists are deleted. Speculative variants without a demonstrated use case are
dismissed or left in the relevant design discussion, not promoted into tasks.

Layered JSON query design can therefore be set aside safely. The current
version-1 typed request/result contract, CLI bindings, saved requests/results,
and SQL-backed executor remain supported. **P17** will restart from a carrier
comparison and requirements review rather than treating the current proposed
layers as an approved implementation plan.

Current status is derived rather than copied into this plan:

```sh
codess catalog status --registry ~/.codess
tools/project_status.sh /path/to/project ~/.codess
codess scan --dir /path/to/project --source cc,codex,cursor --out -
```

The first command reports each selected Project and `N/N` query readiness; the
second reports Git, pointers, ingest receipts, exact-path Claude sources, and
Project-local tool-state markers; the third performs Project-limited
source-system index assessment. Session/Event/raw-record totals and test counts
belong in dated command output, manifests, and comparison reports. They are not
copied into durable project documentation or used as progress metrics.

Real-Project validation policies retain structural expectations:
`required_sources` means that a reviewed compatibility baseline must exercise
the named adapter, not that the Project or Codess requires that product.
`raw_mode`, allowed diagnostics, decoder/validator versions, fixed-point
behavior, and source-specific rules remain meaningful. Transient
`minimum_sessions`, `minimum_events`, and exact `expected_raw_records` gates
have been removed from living Project policies; the deterministic CI fixture
retains them to test the policy mechanism. Immutable snapshot manifests and
reviewed catalogs already record the actual observed counts for comparison.

`package_mismatch` has one precise meaning: an immutable Project snapshot's
CoSchema package digest differs from the exact package selected for the
current query policy. Setpack, wp, and harduw currently point at retained
CoSchema-3 snapshots and therefore fail the default exact-package selector;
they are not corrupt and may be inspected only under an explicit compatible
historical-read policy or rebuilt. This is not “mapping is obsolete”: the
immutable observation remains valid under its recorded package. It simply
does not claim exact current-package behavior. Unsupported read layouts and
hash failures report separately. Personal-catalog binding now rejects macOS
and Unix temporary-system locations such as `/private/var/folders` and `/tmp`;
tests use isolated registries instead of creating durable catalog entries.

ZeroPerf is a linked worktree of the Zero400 repository. Its duplicate legacy
Project entry is retained for historical evidence but marked with the
catalog-only `worktree` disposition, related to the Zero400 Project, and
excluded from broad Project selection. The next evidence refresh is a normal
Zero400 source assessment and re-ingest, not a bespoke row/ID migration.
ZeroPerf-specific historical snapshots remain explicitly addressable until
ordinary retention removes them; any source records that a current adapter can
attribute to the repository/worktree enter the new Zero400 snapshot through
the normal path.

**A26 Extraction Validity immediate work** covers the low-cost status path,
removal of transient count gates, test-registry isolation, worktree catalog
disposition, and the rule “assess selected observations before large Cursor
extraction.” Git is a strong primary signal, but vendor source/index mtimes,
`.claude`/`.codess` state, and exact source revision markers are independent
signals. Build outputs, logs, and generated artifacts are conservatively
treated as activity hints unless a retained invocation links them to a source
system.

The larger **P20 Extraction Validity model** is postponed. It owns a formal
multi-signal freshness state, per-source update observations, evidence
confidence for tool-state/artifact changes, repository/worktree-aware
attribution, reasoned re-ingest selection, and a first-class status result
contract. It must extend the current cheap shell/index workflow from measured
failures; it does not gate current query, mapping, or validation work.

### 8.2 Implementation review and active work

#### 8.2.1 Use-case implementation review

This table is the concise review surface for system status. **Implemented**
means the primary use case works end to end on current Project snapshots.
**Partial** means a useful path is coded and validated but the named
investigation step still needs CLI/query work. **Designed** means only a
workaround or lower-level composition exists. Detailed requirements and
commands remain in **README UC1–UC11**; the work and gap IDs below own the next
implementation.

All use cases depend on the implemented CoSchema-4 ingestion, immutable
snapshot, provenance, resource-bound, diagnostic, raw-evidence, and validation
foundation. Current suite and baseline outcomes are reported by the validation
commands above; passing them does not imply that every query workflow below is
complete.

| Use case | State | What is coded and validated now | Most direct next work |
|---|---|---|---|
| **UC1 — find Sessions for Projects** | **Partial, broadly usable** | Exact Project IDs, saved current/named-snapshot sets, explicit directories, per-Project catalog readiness with `N/N` coverage, and explicit historical diff/union | **A1:** add catalog-attribute selection only after concrete predicates are specified. **P12:** repository-level Zero400/ZeroPerf catalog migration is postponed |
| **UC2 — select by source system** | **Partial, broadly usable** | Claude/Codex/Cursor unions plus Session, time, model, event-kind, status, artifact, tool, actor, role, origin, relation, and initiation scope | **A1:** missing normalized predicates/action parity. Caller-selected fields are P17 |
| **UC3 — orient by volume and time** | **Implemented core; measured extensions remain** | Session relation and Interaction-initiation partitions; UTC months; bounded UTC daily human/model exchange and actor engagement; daily/monthly raw tool call/result/input/output metrics; Event-gap histogram; Session/Interaction/turn/Event/text/tool/artifact/model volume, elapsed span, event days, and active-time sensitivity. `evidence audit orientation` independently reconciles the core observations to read-only SQL across current query-ready Projects | **A2/A9:** retain empty/tiny/skew fixtures and add only measured high-cardinality distributions or performance work |
| **UC4 — open a known Session** | **Implemented for whole Sessions and bounded typed Event windows** | Select by ordinal, stable global ID, or unambiguous vendor ID and display chosen content classes; typed sequence/window results can feed the next operation | Terminal presentation remains separate from typed result composition |
| **UC5 — find and reconstruct an exchange or event group** | **Implemented for the scoped core exchange** | Stable Event, Interaction, and Model-Turn selection in global canonical order; complete Interaction/turn expansion and sequence windows; end-to-end Claude/Codex/Cursor provenance checks across human, harness, tool, and model evidence. Claude and Cursor delegated prompts and current Codex protocol subagent/collaboration shapes are mapped; current Codex tool-search/MCP-transport/rollback records are retained | Add new vendor shapes only when direct evidence appears; local Codex subagent/collaboration occurrence remains a T4 evidence trigger, not a blocker |
| **UC6 — search text, paths, errors, symbols, or topics** | **Partial, broadly usable** | Bounded normalized substring search over content, tool input/output, and artifact paths with scope/completeness warnings, returned-row facets, and lossless exact repetition groups | **A4:** maintain current semantics. **P18:** alternative result order is further-phase. **P13:** raw-source search is further-phase. Alternative indexed retrieval is distant |
| **UC7 — investigate tool operations, outcomes, failures, or denials** | **Partial, scoped typed path validated** | Tool lineage, audit, permission, task-review, tool histogram, typed actor/tool/status filtering, and tested denial/failure expansion across Claude/Codex/Cursor | Fixed legacy reports remain table-oriented; broader runtime-component and context analysis is evidence-triggered |
| **UC8 — correlate work across vendors or artifacts** | **Partial** | Artifact extraction, event links, confidence-bearing correlation assertions, aggregate reports, and SQL drill-down | **A2/A19:** expose constituent stable IDs where a demonstrated typed aggregate requires them. **P12:** repository/worktree catalog consolidation remains postponed |
| **UC9 — export and compose investigations** | **Implemented for homogeneous typed results** | Typed JSON results, failure-tested atomic saves, stable-ID derivations, guarded changed-snapshot comparison, explicit historical union, constituent-ID repetition groups, and cited summaries. Mandatory result identity is separate from maintainer timing/allocation/SQL reporting | **P17:** optional caller field selection/package presentation. **A9/P14:** developer execution evidence. Heterogeneous analytical products remain A19/P19 |
| **UC10 — verify exact source evidence** | **Implemented** | Event → source record → exact sealed/captured/live resolver with mismatch and unavailability reporting; exercised on Claude, Codex, and Cursor evidence | Maintenance only under **T1/T2/T6** when vendor shapes, mappings, or code change |
| **UC11 — assemble cross-Project analytical data** | **Designed; basic virtual composition works** | Repeated `--dir`/`--dirs`, typed saved results, and external SQLite/DuckDB/pandas composition | **A19:** compare top-down workproducts with bottom-up fields and prototype a manifest plus current virtual query. **P19/P17:** Assembly export formats/optional fields |

The most obvious implementation sequence by user value is:

1. **UC1–UC3:** finish scope and orientation so every later investigation starts
   from an accurate Project/source/Session cohort.
2. **UC4–UC7:** finish windows, lineage predicates, repetition facets, and typed
   human/harness/tool/model evidence so a researcher can locate and inspect the
   actual exchange and tool outcome.
3. **UC9:** make the selected evidence reproducibly composable and citable.
4. **UC8/UC11:** generalize the same operations across Projects and analysis
   datasets/exports.

Capability cases are promoted from this use-case table, not invented from
vendor record inventories. Each case must specify: UC and investigation
question; exact Project/snapshot/Source/record evidence; input selector and
bounds; expected common and namespaced source fields; stable identities,
relations, and order; completeness/unsupported diagnostics; and fixture plus
real-snapshot assertions.

The current validation sequence is:

1. keep UC1/UC3 scope, count, and readiness regressions green across the six
   reviewed Projects;
2. keep the completed A3 Claude/Codex/Cursor core checks as adapter-change
   gates; their actor proof set is human, harness, tool, and model;
3. next add A12 model/effort/service provenance assertions beside the matching
   source case, never as a separate combinatorial sweep;
4. keep the completed A7 changed-snapshot, constituent-citation, atomic-save,
   incompatible-shape, and result-composition cases green; and
5. leave field projection, search-report refinement, raw search, and
   Assembly exports to P17/P18/P13/P19 respectively.

#### 8.2.2 Query and investigation completion checklist

| Work item | Remaining functional behavior | Required validation before completion |
| **A27 — actor/origin and runtime lineage** | **Core mapping complete for current evidence.** Claude sidechain/agent-path and Cursor `isSubagent` user envelopes map as harness-delegated prompts. Current Codex OSS parent/fork/thread-source and collaboration shapes map to Session lineage and harness Events, with fixture validation because no reviewed local rollout contains them. Direct-user, unpaired harness context, assistant role, MCP transport/application outcome, and rollback mappings remain covered. MCP repeated source-call IDs are duplicate candidates, not presumed global identities | Keep focused fixtures and real-snapshot assertions green; retain NULL instead of inferred parentage; add a local Codex occurrence only under T4. Ordinary field truncation disposition remains A6/P16 rather than blocking actor mapping |
| **A1 — typed query-kernel hardening** | Exact IDs, saved Project/snapshot sets, typed row predicates, global ordering, bounds, and limit pushdown are implemented. Add only demonstrated catalog predicates or missing normalized predicates | Predicate/NULL/obsolete-location tests and read-only SQL reconciliation; version-2 layered JSON and caller field projection are postponed under P17 |
| **A2 — orientation** | **Core implementation and real-store reconciliation complete.** Relation/initiation partitions, UTC months, Event-gap histogram, active-time sensitivity, bounded daily exchange/actor/subagent engagement, labelled response anchors, and daily/monthly raw tool observations are implemented. Monthly tool Interaction counts are distinct across day boundaries. `evidence audit orientation` independently reconciles current query-ready Projects to SQLite. Displays may calculate ratios/percentages; cost/quota/token-burn/timeout remain out of scope | Retain the SQL audit plus empty/tiny/long-idle/skew fixtures. Add distributions only from a demonstrated investigation or measured performance need under A9 |
| **A3 — core exchange provenance checks** | **Complete for the approved scope.** Claude, Codex, and Cursor each pass source→adapter→store→typed Interaction→exact live-evidence tests with human, harness, tool, and model actors plus real denial/failure status evidence | `tests/test_provenance_checks.py` is the contract. Agent/subagent, MCP, and context variants remain preserved and evidence-triggered but do not reopen A3 |
| **A4 — bounded normalized finding** | Literal escaping, returned-row facets, and lossless exact-repetition grouping are implemented. Retain measured repeated-shape coverage and canonical ordering | Exact matches, bounds, completeness, and occurrence preservation remain regression-tested. Search-report refinement is postponed under P18 |
| **A7 — reusable results and typed composition** | **Complete for homogeneous typed results.** Stable-ID derivation, explicit observation-preserving historical union, guarded changed-snapshot comparison, cited investigation records, saved tool-result → complete four-actor Interaction expansion, repetition-group constituent citations, failure-tested atomic saves, and incompatible-shape rejection are implemented | Current query/investigation regressions are the contract. Heterogeneous joins/analytical products remain A19/P19; optional package presentation remains P17 |
| **P17 — query language and package research** | Further phase: reevaluate layered JSON, caller-selected fields, public/private package registries, and external clients as one design programme | Restart with use-case requirements and carrier comparison; no current interface is deprecated merely to begin the prototype |

These items do not include raw-source search (**P13**),
repository-level ZeroPerf migration (**P12**), or cross-Project Assembly
exports (**P19**).

#### 8.2.3 First investigation-package tranche mapping

The five names in Designs are scenarios, not five new engines or work-item
trees. Their current and deferred owners are:

| Scenario | Existing core owner | Remaining work owner |
|---|---|---|
| `project-session-inventory` | UC1–UC2, A1 typed Sessions and source scope | A1 concrete catalog predicates; P17 package wrapper/field selection |
| `project-orientation` | UC3, A2 overview, activity sensitivity, and daily exchange engagement | A2 diverse-real-store reconciliation and only measured distributions; P17 renderer/package metadata |
| `exchange-window` | UC5/UC7, completed A3 expansion/provenance and A7 result composition | P17 wrapper only if a repeated consumer warrants it |
| `normalized-findings` | UC6, A4 bounded literal finding/facets | A4 presentation-order questions only if promoted from P18; P17 wrapper |
| `tool-outcome-review` | UC7, completed A3 tool/permission provenance and A7 composable rows | P17 wrapper only if a repeated consumer warrants it |

This tranche does not authorize the later JSON carrier. Each scenario is first
validated through the current CLI/request/executor on diverse Projects; P17
may package only behavior already defined in the core.

#### 8.2.4 Prioritized current and pending work

Priority reflects importance and urgency; dependencies control execution order.
Complexity is relative (`S`, `M`, `L`) and is not a time estimate.

##### Group 0 — correctness gates

| Priority | ID | State | Dependencies | Complexity | Next outcome |
|---:|---|---|---|:---:|---|
| **P0** | **A27** | Core current-evidence mapping complete; evidence-triggered maintenance | A3 four-actor core | S | Keep Claude/Cursor real assertions and Codex protocol fixtures green; add a local Codex collaboration occurrence under T4; leave general field-truncation disposition to A6/P16 |
| **P2** | **A12** | Active | A3 core source checks completed | M | Extend the same source-evidence method to release/model/effort/service occurrence provenance without inferring absent values |

##### Group 1 — query specification and reusable workflows

| Priority | ID | State | Dependencies | Complexity | Next outcome |
|---:|---|---|---|:---:|---|
| **P1** | **A1** | Active | A22 completed | M | Harden the current typed kernel and add only demonstrated catalog/normalized predicates; layered JSON and caller projection are P17 |
| **P2** | **A2** | Core complete and reconciled | A1 scope/bounds; A27 actor corrections | S | Maintain `evidence audit orientation` and skew fixtures; promote only measured follow-up distributions or A9 performance work |
| **P3** | **P18** | Postponed further phase | Measured UC6 investigation failures | M | If promoted, refine one search report using a small reviewed question set and one deterministic order; preserve all occurrences and keep judgments outside CoSchema |

##### Group 2 — investigation automation

| Priority | ID | State | Dependencies | Complexity | Next outcome |
|---:|---|---|---|:---:|---|
| **P2** | **A8** | Active cited-result workflow | A7 | M | Exercise one supplied-summary/citation workflow using the current result contract; native language generation and P17 packaging remain postponed |
| **P2** | **A20** | Parallel | Public contract changes | M | Apply the glossary incrementally to new public fields while preserving compatible CLI/result spellings |

##### Group 3 — execution, storage, and profiling

| Priority | ID | State | Dependencies | Complexity | Next outcome |
|---:|---|---|---|:---:|---|
| **P2** | **A9** | Core planner/SQL validation active; Cursor programme specified in Designs §10 | A1 typed operations | L | Review the five-phase Cursor call graph, measure the documented load-shape matrix, inspect plans/allocations only in dominant phases, attempt one bounded-state change at a time, and retain fixes only with identical ordering/identity/rollback/fixed-point outcomes |
| **P1** | **P14** | Active, approved | Existing runtime observations | M | Reconcile selected, emitted, retained, and allocated units without turning transient corpus totals into maintained status |
| **P1** | **P16** | Active, approved | P14 unit definitions and existing admission behavior | M | Ship the approved defaults, exact boundary/override tests, and pre-commit failure checks; do not invent additional ceilings |
| **P3** | **A5** | Event-triggered | Next changed large capture | M | Measure cache restore I/O/RSS when naturally exercised; retain current bounded-marker caveats |

##### Group 4 — analytical Assemblies

| Priority | ID | State | Dependencies | Complexity | Next outcome |
|---:|---|---|---|:---:|---|
| **P3** | **A19** | Investigation only | A1/A7; P12 before Zero400/ZeroPerf input | L | Compare desired analysis workproducts with bottom-up entities/fields; prototype one manifest plus virtual query. Assembly exports and optional field selection remain P19/P17 |

### 8.3 Decision register

Resolve a decision immediately before its first consuming work item; do not
block unrelated work.

**State:** **D1–D21 are resolved.** D4 postpones; D7's composition is adopted but
each method still requires evaluation; D11 adopts normalized identity while
occurrence representation stays at R3a/R3b. Reopen a decision only with contrary
implementation or vendor evidence.

| ID | Decision | Needed by | Resolution and justification |
|----|----------|-----------|-----------------------|
| **D1** | Query interface shape | **A1–A4**, **P17** | **Adopted now:** action subcommands and version-1 typed requests share one kernel. A later layered JSON/package interface is unapproved P17 research and cannot deprecate the current path without parity and compatibility evidence. |
| **D2** | Inline and saved selection representation | **A1**, **A7**, **P17** | **Adopted: retain both selectors and resolved stable IDs.** A broad catalog selector supports deliberate refresh; the dated result records exact Project/snapshot inputs, filters, algorithm/package/schema versions, outcomes, and limitations. “Current” alone is never a durable research identity. |
| **D3** | Derived active-time sensitivity | **A2** | **Adopted: sensitivity, not one duration.** Report observed elapsed span separately and estimate active time with declared 5, 30, and 120-minute gap caps plus configurable values. Never label the estimate observed, billable, or charged; add the gap histogram next. |
| **D4** | Raw-source search over authorized vendor fields and messages | **P13** | **Adopted: postpone as a feature.** The earlier “full-source” name overclaimed completeness. Raw-source search covers policy-authorized searchable values in exact vendor revisions, including evidence not projected into normalized content. It is not raw capture, exact-evidence resolution, or normalized search; retaining a raw Source never authorizes indexing it. |
| **D5** | Exact evidence resolution precedence | **A6** | **Adopted: equality before location.** Resolve a verified exact sealed/captured object first and exact live evidence next. Report changed live files as mismatches and unavailable sources as unavailable—never silently substitute a different revision. |
| **D6** | SQL and query-package boundary | **A1**, **A9**, **P17** | **Adopted: typed application specifications own behavior; SQL is one optimized backend and expert escape hatch.** Prove pushable operations against a backend-neutral reference executor; keep non-equivalent expansion, cross-store ordering, byte bounds, evidence, and raw access in core stages. Add a stable SQL view only after two independent consumers repeat a row contract. |
| **D7** | Topic/phase derivation methods and composition | **A8** | **Adopted: multiple composed methods, iteratively:** (1) deterministic lexical rules and explicit vendor events; (2) phase heuristics over ordered windows; (3) optional versioned embeddings for recall; (4) optional LLM labels only on bounded candidates; (5) an ensemble assertion that cites its inputs. Preserve every method/version/evidence/confidence separately and promote a stage only after a labelled evaluation set shows added value. |
| **D8** | What result provenance is mandatory? | **A1**, **A7**, **P17** | **Adopted:** optional future package identity; canonical bound request and hash; result identity; dated execution observation; processor, Project/store/snapshot/package/decoder/validator identities; policy hashes; multidimensional completeness; limits/truncation; limitations; and constituent stable IDs. Observation time identifies the run but remains outside stable result meaning/content identity. |
| **D9** | Historical snapshot semantics | **A1**, **A7** | **Adopted:** one verified current or explicitly named immutable snapshot by default. Diff compares two named observations by stable IDs, source revisions, semantic/content and package hashes. Union is separately explicit and retains observation identity plus duplicate diagnostics. Discovery is metadata-first from the maintained registry/manifests. Never combine per-row “latest” observations implicitly; see **Designs.md §13**. |
| **D10** | Saved-result validity across Project moves | **A7** | **Adopted:** treat relocation separately from extraction correctness. Bind result identity/comparison to stable entity IDs and snapshot/query hashes; retain filesystem paths only as time-specific provenance. A move updates location bindings, not prior evidence. |
| **D11** | Model-configuration identity and provenance | **A2–A3**, **A12**, **R3a/R3b** | **Adopted:** keep provider, family, exact name, revision, effort, speed, service tier, and mode nullable and independently queryable. Use the normalized tuple as null-safe identity; never infer one setting from another. Preserve exact source values/field paths. R3a/R3b retain occurrence JSON now and postpone a relational projection until demonstrated. |
| **D12** | Supported provenance window | **A12**, D13 | **Adopted:** model change, harness change, or any other readable/deducible parameter can define the minimum acceptable level for a given Codess release. The cutoff is rooted in major breaking format incompatibilities, never model capability. Below the window → source-quarantine diagnostic, not silent best-effort. Model choice stays evidence (`model_configurations`), never a support gate. |
| **D13** | Vendor vs session behavior | D12, D17 | **Adopted:** behavior seen across *all* sessions at a given model/harness provenance is vendor-specific; only behaviors explicitly declared `unsupported` (→ diagnostic), `ignored` (→ `retention: discard`), or `adjusted/mapped` (→ named rule + `mapping_trace`) are exceptions. One-session variance never drives a mapping rule. |
| **D14** | Cross-vendor renditions are separate artifacts | **T5**, `correlation_assertions` | **Adopted:** resolve each vendor → common (N mappings). Do **not** require every vendor combination → each other (N² resolution is an explicit non-goal). Cross-vendor linkage is an optional additive search/process step via `correlation_assertions` + shared `relative_path`; it never rewrites identities. Intra-session model attribution beyond `model_turn_id` coverage is a separate confidence-graded inference, not a normalization requirement. |
| **D15** | Compaction is evidence-graded | **A18**, **T4** | **Adopted and implemented:** map only a direct vendor record. Claude supplies a boundary plus a linked plaintext summary; Codex supplies a `compacted` envelope with a dedicated encrypted `compaction` item; Cursor supplies a plaintext `conversationSummary` with boundary IDs. Preserve the body even when encrypted, but classify by the containing record rather than by field spelling. Repeated history and notification records are provenance, not duplicate Events. An unsupported shape remains `indeterminate`, never inferred from error-looking prose. |
| **D16** | Capture consistency and optional quiesce | **A6** | **Adopted:** rely on the SQLite online-backup-over-live-WAL primitive plus a capture-verify-recapture stability loop that records `consistency=source_advanced` when a write lands mid-capture. Orderly harness shutdown is an **opt-in hint only** (detect running harness, suggest closing, prefer idle windows); never a forced kill. |
| **D17** | Acceptance-gate outcomes (with D18) | **A12**, D13, D16, D18 | **Adopted:** the value-level gate compares rebuilt vs. prior store per field/row and reports `match` / `mismatch` / `vacant` (`field_state.compare`), where `vacant` (a non-present side) takes precedence over `mismatch` (both present, differing). A `mismatch` or `vacant` on an identity/order/lineage field is `fatal`; else `advisory`. The structural contract gate (`validate_database_contract`) is unaffected. Prerequisite for v4 promotion. |
| **D18** | Field-state resilience | **A16**, D13, D17 | **Adopted:** every adapter field is classified `present`/`absent`/`empty`/`null`/`sentinel`/`malformed` (umbrella `vacant` = absent-family, excludes `malformed`). Non-present states emit `info` (or `warn` for `malformed`) diagnostics; **no input ever crashes the program** — a bad field is dropped with a diagnostic and the record still lands; only an unreadable source quarantines. Shares the `vacant` token and `fatal`/`advisory` scale with D17. Impl: `field_state.py`. |
| **D19** | Decoder/validator dating and path identity | **A12**, D10, D17 | **Adopted:** CoSchema continues to version readable stored meaning/layout; independent decoder and validator profiles begin at `0.2` for the current capability/filter update and are recorded in stores, manifests, reports, and policy requirements. Logical Projects use generated UUIDv4 IDs as cross-store keys. Path hashes remain only for machine-local location identity and idempotent evidence identities. Vendor-observed historical paths remain provenance and carry explicit `path_obsolete`; they never replace the active Project root. |
| **D20** | Global database versus reproducible analytical Assemblies | **A1**, **A7**, **A9**, **A19**, **P19** | **Adopted direction:** retain immutable per-Project snapshots as authority and use explicit Assemblies above them. Before selecting a default Assembly export, compare desired analysis workproducts with bottom-up common and namespaced source-specific fields through a manifest plus virtual-query prototype. Candidate JSONL/Parquet/DuckDB/SQLite outputs are derivatives, never vendor parsers or second authorities; the input relation supports both Assembly→Project and Project→Assembly lookup. |
| **D21** | Git repository versus worktree/workspace Project identity | **P12** | **Adopted: exactly one Codess Project per Git repository.** Clones, linked worktrees, workspace directories, branches, and vendor workspace IDs are Project locations, bindings, or dated observations under that Project, even when substantial independent work occurs in them. They never mint additional Project IDs. Non-Git work may still have a Project. A discovered duplicate worktree Project is marked non-selected and related to the repository Project; ordinary re-ingest refreshes the repository Project while historical duplicate snapshots remain addressable until retention. Do not rewrite normalized identities merely to consolidate the catalog. |

### 8.4 Postponed topics

Intentionally outside the active sequence. The externally orchestratable table
can be composed today from Codess commands and system tooling; native
implementation is justified only when orchestration, portability, provenance,
or atomic failure semantics become product requirements. Event triggers
(§8.4.4) name the conditions that promote a postponed or gap item into Active.

#### 8.4.1 Externally orchestratable

| ID | Topic | Restart condition |
|----|-------|-------------------|
| **P1** | Enterprise PII/secret scanning beyond configured regex policy | External scanners can gate source/raw promotion now. Add native policy integration only when a deployment threat model requires uniform findings, suppression, and provenance. |
| **P2** | Periodic storage/query scheduling and notifications | Use `launchd` on macOS, systemd timers on Linux, or cron/CI to invoke stable commands and retain outputs. Add an internal scheduler only when cross-platform lifecycle and notification state are product requirements. |
| **P3** | Proactive baseline refreshes and vendor audits | An external scheduler may run dry-run/audit commands; promotion remains reviewed. Reopen native automation under **T1/T2** only if safe apply policy is defined. |
| **P6** | Natural-language query execution | An external LLM can formulate a proposed typed request after **A1–A7**; Codess must validate and display it before execution. Native formulation waits for evaluation and trust requirements. |
| **P7** | Standalone `queries.sql` package | SQLite CLI, Datasette, sqlite-utils, and notebooks can consume documented read-only recipes. Package only when **D6** has repeated external consumers and a versioned contract. |
| **P8** | Multi-Project reviewed-`baseline refresh` orchestration | Native routine `codess refresh` now resolves explicit lists or annotation cohorts, gates all apply on complete preflight, checks unchanged inputs, and records partial per-Project outcomes. It intentionally does not approve/freeze baselines or provide cross-Project rollback. The stricter preflight → fixed-point apply → validate → freeze composition remains postponed until reviewed-publication rollback semantics are required. |
| **P9** | First-class Markdown report export | `jq`, templates, notebooks, or report tools can render typed JSONL/CSV. Add a native format only when a stable customer-facing Markdown contract is required. |

#### 8.4.2 Product functionality still postponed

| ID | Topic | Restart condition |
|----|-------|-------------------|
| **P4** | Broad historical discovery implementation or additional vendors | Current, named-snapshot, saved-set union, and result comparison now preserve observation versus logical identity. Broad metadata discovery and any additional vendors remain postponed. Filesystem/Git discovery may propose but cannot approve scope. |
| **P5** | Alternative indexed retrieval | Distant future only. Reopen after a standard query repeatedly fails measured latency/resource requirements and A1 planner improvements cannot resolve it. Any derivative remains rebuildable and does not authorize raw-source indexing under **P13/D4**. |
| **P10** | Misses assessment-store integration | Keep Misses inputs as a companion consumer of saved Codess selections/results. Reopen merged or aligned assessment storage only when a concrete assessment workflow proves which extra entities must persist. |
| **P11** | Full planning-designator reconciliation | **Problem:** `A`/`P`/`T`/done are lifecycle stages of one work register but use separate ID spaces, and `L-*`/`V-*`/`E-*` are three prefixes over one gaps register. **Resolution:** keep IDs as strings; treat `A`/`P`/`triggered`/`done` as a `state` on one register (Postponed and Completed become filtered views of Active), and `L-*`/`V-*`/`E-*` as facets of one gaps register; keep `D` and `UC` distinct. **Restart:** when a planning-doc reorganization is already underway. |
| **P12** | Complete repository-level Project identity after the Zero400/ZeroPerf transitional disposition | ZeroPerf is now non-selected `worktree` catalog evidence related to Zero400. The next refresh assesses and re-ingests Zero400 normally; no specialized normalized-row migration is planned. Resume generic discovery/onboarding enforcement only when a second duplicate-worktree case appears or before A19 requires repository-identity invariants. Preserve historical snapshots/IDs and let explicit retention handle them. |
| **P13** | Raw-source search over authorized vendor fields and messages | This is a distinct future feature, not a synonym for raw retention or exact-evidence lookup. The architecture and normalized-search comparison are now specified in **Designs.md §13**. Reopen only through P13.1–P13.8; any result must identify the exact Source revision and record/field locator. |
| **P15** | Semantic admission of empty, tiny, and structured Events | **Work item C, postponed.** Empty textual statements/prompts/responses do not become message Events. Preserve meaningful tiny text and bodyless structured Events whose canonical mapped payload is nonempty; keep source-record diagnostics and distinguish semantic from provenance metadata. |
| **P17** | Layered JSON query language, caller-selected fields, and investigation-package infrastructure | Further phase. Reevaluate requirements and existing version-1 sufficiency first; then compare carriers, parameter binding, projection, package governance, external clients, and compatibility as a hierarchy. Do not implement the earlier flat feature list |
| **P18** | Search report | Further phase. Reopen only when a recorded UC6 investigation shows useful matches were materially hard to find in canonical order; refine one report without removing occurrences |
| **P19** | Analysis datasets and Assembly exports | Further phase after A19's top-down/bottom-up requirements and saved-selection/query prototype. Compare SQLite, JSONL, Parquet, and DuckDB against actual workproducts, provenance, reverse lookup, update, and scale requirements before selecting any default |
| **P20** | Formal Extraction Validity and freshness model | The cheap A26 workflow is sufficient now. Reopen only when Project status or re-ingest selection is wrong/ambiguous in a recorded case. Then define per-source observations, multi-signal freshness states, evidence confidence, repository/worktree attribution, reasoned selection, and a typed status contract without treating Git, mtimes, build products, or global Cursor DB change as exclusive proof. |

#### 8.4.3 Follow-up implementation decomposition

P13 and P15 remain postponed specifications. P14 and P16 are approved and
active for the bounded measurement/default/boundary tranche recorded above;
approval does not invent other ceilings or authorize unrelated raw search.

The four `.0` reviews are complete. P14/P16 authorize only the bounded active
tranche above; P13/P15 authorize no `.1+` work:

| Review | Outcome | Recommendation |
|---|---|---|
| **P13.0 raw-search need** | The retained `c9d1` Source used a Claude `user` envelope for three tagged local-command blocks. The old mapper treated envelope role as actor and emitted three human prompts. Exact evidence lookup exposed the tags; normalized search found the retained values. The adapter now maps caveat → harness context, command name → human command, and stdout → harness result | This was a provenance-mapping defect, not a missing raw-field query. Keep P13 postponed until one investigation cannot be answered by normalized rows plus exact evidence |
| **P14.0 measure use** | Keep effective limit/origin, selected/mapped/stored/truncated, result-byte, SQLite/raw-allocation, warning, and diagnostic measures. Keep phase timing/RSS debugging-only. Do not promote transient corpus totals into maintained documentation. Clarify container size versus selected/retained content | **Approved:** implement reconciliation and only decision-bearing missing measures |
| **P15.0 admission sample** | The command-only correction is source-shape-specific. Current adapters still perform parts of admission independently; there is no single cross-vendor candidate/outcome contract for empty text, bodyless structure, attachments/external content, oversized logs, and unsupported-but-retained records | Keep P15 postponed. The present design can fix known mappings and enforce bounds, but cannot yet promise identical `admitted`/informational/unsupported/rejected decisions across all three source systems |
| **P16.0 limit need** | Existing maximums map to concrete binary/database/log or runaway-event accidents, are configurable, and retain overrides. Approved defaults are 200,000 Events per Source, 100,000 per Session, and 250,000 characters per context body | **Approved:** implement defaults and boundary/override/pre-commit validation; add no other ceilings |

| ID | Stage | Work and output | Validation or exit criterion |
|---|---|---|---|
| **P13.1** | Investigation | Inventory authorized raw fields/record types, unavailable/opaque/encrypted cases, privacy classes, and representative current Source revisions per source system | Reviewed inventory identifies searchable, metadata-only, suppressed, and unsupported values without conversation-body publication |
| **P13.2** | Contract design | Define `codess.raw-search-request/1` and result contract with exact Project/snapshot/Source/revision/record/field identity, literal semantics, bounds, completeness, and authorization-policy hash | JSON examples validate; every result locator can name one exact value without inventing a CoSchema Event |
| **P13.3** | Source readers | Add bounded JSONL field streaming for Claude/Codex, selected-key/row SQLite queries for Cursor, and linked external-text handling; binary/base64 remains metadata-only | Vendor fixtures prove stable locators, type/encoding preservation, and no whole-Cursor-database decode |
| **P13.4** | Execution | Reuse Project-set resolution, raw manifests, evidence availability/equality, decoding/content policy, progress, and bounded result streaming | Below/equal/above record/read/match/excerpt/result limits stop before unbounded allocation and report exact truncation reasons |
| **P13.5** | Privacy and lifecycle | Specify explicit enablement, field allow/deny policy, secret suppression, result retention, raw deletion propagation, and audit evidence | Ordinary normalized search never opens raw Sources; removed Sources invalidate/delete derivatives and stale matches cannot resolve silently |
| **P13.6** | Optional index | Benchmark index-free queries; only if justified, prototype a revision/policy/decoder-bound rebuildable derivative with allocation reporting | Index and streaming results are semantically equivalent on fixtures; rebuild/removal is deterministic and the index is not authoritative |
| **P13.7** | Integration tests | Cross-check literal `%`/`_`/backslash behavior, unavailable references, invalid UTF-8, unknown fields, external content, and exact evidence re-resolution | Complete fixture matrix passes with bounded memory and no unsupported value treated as searched |
| **P13.8** | Real validation | Run explicitly approved bounded searches on one recent Project per source system, inspect every outlier/failure, and compare normalized versus raw recall | Review shows useful additional evidence, acceptable allocation/privacy behavior, and no unexplained locator or completeness mismatch |

| ID | Stage | Work and output | Validation or exit criterion |
|---|---|---|---|
| **P14.1** | Investigation and definitions | Freeze the unit dictionary in Designs: container, selected record, source semantic payload, retained logical Event payload, result serialization, raw allocation, SQLite allocation, and RSS | Each unit has one owner, byte/character definition, attribution path, additivity rule, and explicit non-equivalences |
| **P14.2** | Instrumentation design | Place streaming counters at admission, vendor selection, Event emission, commit, capture, snapshot, query serialization, and phase completion; define versioned histograms/top-N observations | Design proves counters do not retain bodies or require a second pass over a global Cursor container |
| **P14.3** | Implementation | **Partial:** runtime/preflight reports now add retained searchable Event characters and UTF-8 bytes to container/Event/RSS totals, with an explicit `content`/`tool_output` alias rule. Next add only decision-bearing selected/source-semantic, result, and allocation measures | NULL/empty/multibyte/double-projected unit tests pass; reports remain bounded and backward-compatible |
| **P14.4** | Reconciliation | Add checks for selected→mapped→retained counts/bytes, unique raw-object allocation, SQLite page/table totals, and non-additive container/RSS labels | Synthetic fixtures reconcile exactly; deliberate duplicate accounting and omitted units fail visibly |
| **P14.5** | Corpus measurement | Run current approved recent Projects per source system plus large/skew cohorts; record fixed histograms, percentiles, top outliers, allocation, and phase RSS | Every top outlier resolves to exact evidence and receives an assessment classification |
| **P14.6** | Analysis | Separate valid large content, mapping/source defects, duplicate accounting, repetition, and buffering/serialization amplification; recommend no ceilings yet | Reviewed report explains all material tails and identifies code defects to fix before P16 |
| **P15.1** | Investigation | Build an admission matrix for textual messages/context and bodyless structured tool/status/permission/lifecycle/mode/attachment records | Matrix identifies required canonical payload, meaningful tiny examples, empty cases, and vendor-specific ambiguity |
| **P15.2** | Design | Define `admitted`, `informational_non_event`, `unsupported`, and `rejected` outcomes with reason, compliance descriptors, Source-record identity, and severity | Missing preferred fields or irregular format is informational unless semantic meaning is unavailable or unsafe |
| **P15.3** | Shared implementation | Add one semantic-admission function after decoding/policy and before Event emission; adapters provide typed candidate fields rather than independent size rules | Identical canonical candidates receive identical outcomes across adapters; no path/min-size heuristic decides Event meaning |
| **P15.4** | Adapter integration | Apply to Claude, Codex, and Cursor while preserving structured payloads, external links, and mapping diagnostics | Tiny meaningful text and valid bodyless structured Events survive; empty textual message Events do not |
| **P15.5** | Corpus review | Reclassify current empty/tiny/irregular records and inspect all behavior changes against exact evidence | No reasonable relevant record is rejected for preferred-format noncompliance; changed counts are explained |
| **P15.6** | Fixed-point validation | Rebuild representative three-vendor and irregular/large baselines twice under the same policy | Semantic identities/counts are stable; rejected/non-Event records retain source provenance and deterministic diagnostics |
| **P16.1** | Candidate analysis | Derive warning/rejection candidates only from P14 distributions plus P15 classes and threat goal—binary/database/log accidents, not arbitrary percentile clipping | Each candidate names protected failure mode, affected unit, corpus headroom, override, and recovery |
| **P16.2** | Boundary tests | Test disabled, below, equal, one-above, multi-field aggregate, multibyte, streaming-abort, and override behavior for every candidate | Rejection occurs before unbounded allocation; no silent truncation or partial commit/state advancement |
| **P16.3** | Report-only rollout | Ship candidate warnings and classifications without changing admission | Current corpus produces reviewed, explainable warnings with acceptable volume and no hidden false negatives |
| **P16.4** | Opt-in enforcement | Add explicit policy values and preflight rejection for selected candidates | Preflight errors include unit, observed/maximum, Source/Event identity, remediation, and reviewed override path |
| **P16.5** | Real acceptance | Run recent active Projects, large/skew cohorts, hostile/misclassified fixtures, and repeated clean builds | No unexplained outlier, silent loss, unstable identity/count, or excessive allocation remains |
| **P16.6** | Promotion decision | Review evidence and promote only accepted candidates to built-ins; retain others as warnings or explicit policies | Documentation, examples, schemas, tests, release/version record, and prior-policy access all agree |

#### 8.4.4 Event-triggered maintenance

Conditions that promote a postponed or gap item into Active work.

| ID | Trigger | Required response |
|----|---------|-------------------|
| **T1** | Vendor storage or source-format change, or observed unmapped evidence | Update the vendor fact document and smallest representative fixture; run the bounded vendor audit and compatibility gate |
| **T2** | Package/schema/mapping change or accepted source refresh | Run preflight, fixed-point rebuild, semantic sampling, query smoke tests, and atomic baseline replacement |
| **T3** | Material ingest/rebuild or unexplained storage growth | Run storage observation and dry-run prune; apply only a reviewed selection with a receipt |
| **T4** | Representative local Codex subagent/collaboration records, distinct speed tier, direct usage/billing attribution evidence, a new lifecycle shape, or another recorded evidence gap appears | Add the minimal source shape, mapping, fixture, and compatibility assertion; update the gap disposition |
| **T5** | Project move, replacement checkout, or demonstrated cross-vendor correlation need | Update stable location/source bindings; add a corpus member only when the existing corpus cannot answer the compatibility question |
| **T6** | Every implementation change | Keep the full suite and representative candidate, onboarding, evidence, baseline, relocation, and real-store smoke workflows green |
| **T7** | Rule authors who cannot ship Python become a bottleneck for a vendor mapping | Reopen the transform-DSL question per `experiments/JsonDSL.md`; JSONata is the designated candidate |

### 8.5 Known gaps

The IDs below are stable references for README use cases, vendor evidence, and
tests. A gap is not automatically active work; the **Disposition** column names
its active item or trigger.

| ID | Known gap | Disposition |
|----|-----------|-------------|
| **L-S1** | Exact IDs, saved Project sets, per-Project readiness, and the compatibility broad-cohort selector resolve durable central snapshots. Typed catalog-attribute predicates remain; path selectors remain compatibility bindings rather than stable identities | **A1/A19** |
| **L-S2** | Typed selection covers date/model/Event/Interaction/turn/status/artifact/tool/actor/role/origin/initiation/parent/relation scope, complete exchange expansion, sequence windows, and completed three-source core provenance checks. Broader action parity remains; layered JSON/field selection is postponed | **A1/P17** |
| **L-S3** | Explicit saved-set historical union and guarded changed-snapshot comparison are implemented. Broad snapshot discovery and a single shortcut command for creating both sides of a diff remain | **P4**; composition is authoritative until a shortcut proves useful |
| **L-O1** | Typed actions emit one structured reusable JSON result; nested-result CSV projection and streaming row envelopes remain external/legacy-only | **A9/P17**; add only with a demonstrated consumer |
| **L-O2** | Aggregate reports outside the demonstrated repetition-group path often omit constituent stable Session/Event identities | **A2/A19**; add IDs only when the aggregate must feed a subsequent typed investigation |
| **L-O3** | Stable result derivations, observation-preserving historical union, changed-snapshot replay/compare, atomic persistence, aggregate constituent citation, and cited investigation records are implemented. A named branching investigation graph and native summary generation are not | **A8/P6**; add only after a repeated consumer/evaluation |
| **L-M1** | Typed orientation includes UTC months, bounded UTC daily exchange/actor engagement, raw daily/monthly tool call/result/input/output metrics, labelled response anchors, and a fixed Event-gap histogram. Ratios and percentages are display derivations. Independent read-only SQL reconciliation passes across the current query-ready catalog; measured high-cardinality needs and deeper scale/skew profiling remain | Maintain under **A2**; new performance work belongs to **A9** |
| **L-M2** | D3 active-time sensitivity is implemented for 5/30/120-minute caps alongside a fixed Event-gap histogram. Daily first/last prompt and same-Interaction response spans are separately labelled observed endpoints; neither is active or billable time | **A2** |
| **L-M3** | Utilization differs by vendor: Codex cumulative attribution is permanently non-billing evidence, Cursor lacks verified local tokens, and quota/price facts are dated external evidence | Preserve the A10 boundary; reopen only under **T4**; never infer tokens from text |
| **L-M4** | Overview partitions related Session entities and typed Session rows expose/filter `parent_session_id` and `session_relation_kind`. Relation is not authorship. Known Claude sidechain and Cursor `isSubagent` user envelopes now map as harness-delegated prompts, while absent parent IDs remain NULL. Claude scan still excludes subagents by default while ingest preserves them, so scan headline and normalized entity totals answer different questions | Mapping is covered by **A27** and orientation by **A2**; maintain per vendor/release under T1/T4 |
| **L-C1** | Bounded literal-substring search, returned-row facets, exact complete-content repetition groups, and saved results exist. An explicit wildcard-pattern operator, evaluated deterministic result ordering, topic classification, near-duplicate analysis, and a package catalog do not | **P18/P17/A8**; add pattern syntax only from a demonstrated use case |
| **L-C2** | Normalized content may be sanitized, filtered, redacted, bounded, or externally referenced; a miss does not prove raw absence. Source/container oversize stops admission for classification and review rather than silently discarding the source. Context bounds retain original length/truncation, but ordinary prompt/response/tool fields do not yet expose disposition uniformly | Preserve completeness under **A6/A27/P16** and evidence-triggered mapping maintenance |
| **L-P1** | Interaction, Model Turn, phase, actor, origin, and cross-vendor correlation confidence varies; source role and shared evidence are not authorship | Preserve exact evidence/method/confidence in **A27/A2–A8** |
| **L-P2** | Cursor repetition has three shapes: duplicate storage copies of one logical bubble, distinct repeated operational/state events, and repeated retained content. Exact compatible complete-content grouping is now a lossless presentation summary with occurrence IDs/time span; it does not prove duplicate evidence. In the current Zero400 baseline, 22,921 nonempty event rows share content with another row, while tool-heavy records account for 34,291 calls and 34,291 results. Truncation-prefix equality, near duplicates, and semantically repetitive model output remain separate derived-analysis questions | **A4**: measure the implemented facets/groups on current Cursor data, test diverse repeated shapes, and evaluate ranking. Any future near-duplicate or semantic grouping is versioned/confidence-bearing and never removes source occurrences |
| **L-E1** | Cross-store reports materialize and sort selected sessions in Python | **A9** |
| **L-E2** | Repeated substring search has no rebuildable policy-aware index | Benchmark after **A4**; decide under **D4** |
| **L-E3** | Cursor selection and SQLite writes are composer-streamed, but ordering/deduplication and Interaction construction still buffer one complete composer; a real 19,661-event composer reached about 531 MiB RSS. Store-wide orphan pruning is now deferred to once per source transaction instead of once per composer, eliminating a repeated full-store scan; phase tracing separates read-buffer and write work | **A9**, using **Designs §10 “Cursor architecture and performance programme”**: measure the batch-pruning improvement and make grouping/stateful writes incremental without weakening rollback, canonical ordering, stable identity, diagnostics, or fixed-point output |
| **L-E4** | First capture of changed selected Cursor evidence still requires one transactional backup and streaming compression; a newly selected Project may require one verified streaming restore of an unchanged cached cohort. Real exact revisions `368bb3…` and `ae3c23…` differed while all three selected markers and normalization digests matched, proving whole-DB invalidation was too coarse | **A5/A9**: selected markers are implemented; measure cache-restore I/O/RSS and keep `--force` for suspected vendor timestamp/edge-sampling gaps |
| **L-E5** | Exact/saved/broad-cohort Project snapshot selection plus Event/Session `project_id`, `snapshot_id`, and `observation_id` are implemented. No cataloged Assembly manifest, streaming common export, Parquet/DuckDB workspace, merged SQLite model, reverse lookup, or complete Source-record projection exists | **A19/P19**, in the documented remaining stages |
| **L-E6** | The transcript and Cursor-container guards are separate and configurable. Runtime/preflight `resource_summary` deduplicates observed containers, sums emitted Events and retained searchable Event characters/UTF-8 bytes, takes the largest Session, and treats RSS as non-additive. Selected/pre-truncation source-semantic payload and physical allocation remain distinct missing units | **P14/P16/A9**, active bounded tranche: add only decision-bearing missing measures and retain distinct units |
| **V-CC1** | Claude slug decoding is lossy when the index lacks an explicit Project path | Prefer indexed paths; reopen mapping only with new evidence |
| **V-CC2** | Claude model/service settings, custom/AI titles, agent names, direct fork/subagent references, bounded product state, and structural delegated-prompt origin are mapped. `userType=external` is not treated as human evidence. Richer runtime-context snapshots remain partially specialized | Validate settings under **A12**; actor/origin mapping is maintained under **A27/T1**; other context remains evidence-triggered |
| **V-CC3** | Decoder 0.2 classifies signature-only empty thinking and fallback markers as known raw state, but image-only user records are still unsupported attachment evidence (8 records/52 image blocks in the current Misses source set) | Add bounded attachment identities/content links without copying base64 bodies; validate on Misses before allowing the diagnostic in policy |
| **V-CC4** | Claude product surfaces can provide MCP-qualified visualization, browser, and session-administration tools even when the current CLI has no user-configured MCP server. Historical names therefore do not establish present configuration; repeated large `read_me` results can also consume or exceed result bounds | Keep configuration inventory separate from occurrence evidence; use **A27** MCP audit classifications and cache/version tool instructions rather than repeatedly retaining oversized bodies |
| **V-CTX1** | Compaction summaries and selected Cursor request-context/context-window observations are represented as bounded context operations, but memory, skills/tool schemas, arbitrary attachment/context selections, reasoning state, and detailed token snapshots are not a complete first-class common model | Continue evidence- and use-case-triggered specialization; do not collapse semantically different context into one JSON dump |
| **V-CX1** | The earlier and current reviewed local Codex cohort supplies no direct parent/collaboration occurrence. Current OSS protocol fields for parent, fork, structured subagent source, participant identity, and collaboration spawn/interaction/wait/close/resume/activity are mapped and fixture-tested | **T4:** add the smallest real occurrence when one appears; never infer from time/path/content |
| **V-CX2** | Codex app/plugin connectors can be MCP-backed without a manual `mcp_servers` entry. Current rollout evidence includes useful connector results, malformed/overbroad searches, and application errors inside successful MCP transports | Preserve connector/plugin/server provenance and transport/application status separately; use smaller valid queries and **A27** audit before calling the connector reliable |
| **V-CU1** | Cursor's current header list is incomplete for historical sessions. Workspace `composer.composerData` fallback recovery is implemented and current headers take precedence; composers absent from both indexes or ambiguously bound remain unattributed | Validate fallback provenance across releases; evidence-triggered mapping maintenance under **T1** |
| **V-CU2** | Cursor scan time range is incomplete when headers lack usable timestamps | Preserve coverage diagnostics; do not decode all bubbles merely for dates |
| **V-CU3** | Cursor exposes exact `modelInfo.modelName` and accepted/rejected `toolFormerData.userDecision`, but no separate observed effort, speed, or service-tier fields | Validate model/permission provenance under **A12**; retain absent settings as NULL |
| **V-CU4** | Cursor subagent Sessions and their delegated user-shaped prompts are classified, but reviewed Zero400 records do not yield parent composer/session IDs; two ZeroPerf-referencing subagents therefore have NULL parent lineage. Cursor tool-derived ZeroPerf artifacts/event links are preserved, while repository-object identity is not populated | Maintain the NULL lineage under **A27/T1** unless a direct parent field appears. Repository/worktree identity remains P12 |
| **V-CU5** | Cursor mixes built-in app-control operations, dynamic MCP discovery, and user server registrations. Discovery may succeed while the target server is unavailable; repeated source call IDs are only duplicate candidates; completed envelopes can contain application failures. The unintended local `~/.cursor/mcp.json` Brave registration, its known-server index entry, and its migration markers have been removed; historical interaction records remain evidence | Retain bounded exact call IDs, candidate grouping, discovery target status, and explicit nested failures under **A27**. Provider-side key revocation and Cursor restart/reload are external operational actions |
| **E-1** | Lifecycle abort is fixture-only in the reviewed corpus | Add a real shape only under **T4** |
| **E-2** | Settings are uneven: Codex records model/effort and newer service tier; Claude records model/service tier; Cursor records model only; no distinct speed-tier evidence was observed | **A12**; preserve exact values and field provenance, never derive speed from a model label |

### 8.6 Completed foundation retained for follow-up

Only completed capabilities that constrain current work are retained here:

- CoSchema v4 package, two-way contract/DDL and JSON enforcement, canonical
  DDL, common/vendor mappings and event-level mapping evidence, diagnostics,
  content lineage, raw modes, immutable snapshots, and reader compatibility.
- Automated preflight, fixed-point validation, reviewed/approved catalogs,
  exact retained-snapshot verification independent of mutable current pointers,
  semantic/query gates, and the bounded three-vendor compatibility corpus.
- **A3/A7 scoped query foundation:** all three source adapters pass the
  human/harness/tool/model provenance path through exact evidence; homogeneous
  saved-result derivation, explicit historical union, changed-snapshot
  comparison, aggregate citation, atomic persistence failure, and incompatible
  row-shape behavior are regression-tested.
- Stable Project/location/workspace identities, source links, candidate review,
  curated onboarding, relocation, evidence audits, and retention receipts.
- Correct vendor filtering, stable session IDs, sequence ordering, lineage,
  audit/diagnostic/artifact reports, sessions/stats JSONL and protected CSV,
  user-assigned Session names that map to rather than replace stable IDs,
  single-report validation, and pipeline-safe shutdown.
- Resource limits/telemetry, storage observations, latest-only pruning, and
  derived token observations with a permanent non-billing confidence boundary.
- **A13 doc truth-sync:** `CoSchema.md` states v4 is written and in use with an
  honest promotion gate; `CompatibilityReview.md` is scoped to the historical v3
  baseline; vendor docs state the Codex/Cursor compaction shapes.
- **A15 capture stability loop:** `cursor_cohort.prepare_cursor_cohort` stamps
  `change_detection.capture_stability` (`stable_during_capture` / `source_advanced`
  + `post_capture_revision`) and emits `cursor.cohort.source_advanced` on drift,
  without failing the capture; two fixtures cover both cases.
- **A6 exact evidence resolution:** event/source-record lineage, streamed exact
  verification, sealed/central-captured/live precedence, and real Claude,
  Codex, and Cursor checks including a changed live Cursor database.
- **A10 token-attribution feasibility:** per-file reset/interleave/model/time
  classification and explicit `utilization_ready` versus always-false
  `billing_ready`; new direct vendor evidence reopens it under T4.
- **A11/A14/A16:** thin vendor wrappers, centralized admission, contract
  acceptance, and non-crashing field-state diagnostics now share the common
  ingest path.
- **A17/A18:** initiation lineage and evidence-graded Claude/Codex/Cursor
  context/compaction mappings are implemented without inferring absent
  relationships or plaintext.
- **A21 SHA transition:** current code and normalized Source revisions use
  labelled SHA-256 fingerprints; superseded transition snapshots and raw
  copies were pruned with receipts, and unsupported historical digest labels
  now follow the generic mismatch path.
- **A22 candidate publication:** baseline apply builds immutable candidates
  without changing either current pointer, validates the exact candidates,
  compares repeat builds, runs query smoke against the accepted candidate, and
  only then replaces the central/Project pointer pair. Injected policy and
  second-pointer failures preserve prior pointer bytes; candidates remain
  retention-visible.
- **A25 catalog readiness:** `catalog status` reports every Project's selection,
  active-location, current-snapshot compatibility, and `N/N` query-ready
  coverage. `catalog annotations` adds a reason-bearing, filterable
  included/core/query-ready/incomplete/large/limited/suspect/multi-vendor view
  without mutating curation. Neither command infers source refresh from
  pointers or Git activity.
- **A25 routine refresh composition:** `codess refresh` accepts repeated
  Project references, a maintained Project-list file, or one distinctive
  annotation designator. Read-only plan is the default; all-Project preflight,
  unchanged-input gating, per-Project apply isolation, timeouts, checkpointed
  receipts, and explicit partial-failure status are implemented. Reviewed
  baseline publication remains P8.
- **A26 Extraction Validity immediate tranche:** editable packaging exposes the
  direct `codess` command; `tools/project_status.sh` combines bounded Git and
  filesystem observations before a Project-limited source scan; living
  baseline policies no longer freeze corpus counts; tests isolate the personal
  registry; catalog dispositions exclude duplicate worktree/test entries
  without deleting historical evidence; an excluded Project may retire its
  final stale location while retaining its stable identity and disposition.
  Formal freshness semantics are P20.

### 8.7 Elicitation checklist

Behaviors to confirm against real records. The operator supplies (or notes) the
interaction just prior; Codess checks the corresponding session/event/tool rows.
Answers feed **T1** and remaining attribution/context-specialization work.

- **Codex:** `/archive` then `codex resume --last` (archive state, resume
  lineage); `codex fork` (fork lineage); mid-session model/effort/service change
  via `thread_settings_applied` (does it update `model_configurations`);
  compare older/newer `compacted` window-ID shapes without interpreting the
  encrypted summary.
- **Claude:** `/compact` (boundary, accounting, and linked summary retained);
  slash command vs task-notification vs typed prompt (the four-way
  `direct_user_input`/`harness_injected`/`task_notification`/`slash_command`
  split); subagent or `--fork` (`parent_session_id`, `session_relation_kind`).
- **Cursor:** compare auto-summary and manual `/compress`
  `conversationSummary`/boundary shapes across releases; mid-session model
  switch (per-turn `modelInfo.modelName`, surrounding-event attribution);
  accept/reject a tool permission (`toolFormerData.userDecision` →
  `normalized_status`).
- **Cross-vendor:** same file in two vendors (shared `relative_path` +
  `correlation_assertions`, not a normalization requirement).

## 9. Change routing

Documentation ownership is in **Codess.md §4**:

- User-visible investigation behavior → **README.md** and the relevant **A/L/D**
  registry rows.
- Vendor source fact → the matching vendor schema; actionable status → §8.
- Functional or research rationale → **Designs.md**; schema
  compatibility/evolution rationale → **Schemas.md**.
- New database shape → **CoSchema.md**,
  `schema/coschema/sqlite/schema.sql`, mappings, store code, and fixtures.
- Maintainer procedure → **Operations.md**; evidence result →
  **CompatibilityReview.md** or its machine-readable catalog.
- Every implementation change updates its registry disposition and acceptance
  evidence without creating a second task list.
