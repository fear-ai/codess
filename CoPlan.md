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

- **`main.py`:** Prepends `src/` → `codess.project.main()` → `parse_and_run()` → **`cli.scan_cmd.run`** \| **`cli.ingest_cmd.run`** \| **`cli.query_cmd.run`**.
- **`codess.config`:** ENV and constants; used by **`project`**, **`scan`**, **`helpers`**, **`adapters/*`**, **`sanitize`**, CLI.
- **`codess.helpers`:** Roots/CSV/excludes/slug helpers; imports **`config`**. Used by scan and root resolution.
- **`codess.sanitize`:** Shared ingest, terminal-display, tabular-output, redaction, and CSV-cell policy.
- **`codess.store`:** SQLite, DDL, upsert primitives, transactional source
  replacement, and ingest state. **`ingest_cmd`** writes it; query opens the
  resulting databases read-only.
- **`codess.project`:** CLI parsing/root resolution and Git/Claude-slug helpers; no Codex/Cursor storage layout or SQL.
- **`codess.codex_source`:** active/archive roots, session metadata, fingerprinted inventory, Project selection, and active-over-archive deduplication.
- **`codess.cursor_source`:** Cursor installation/workspace discovery, read-only connections, composer headers, indexed bubble ranges, and metrics.
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
§§8.3 and 8.6.

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

**What:** (1) **Locations** of vendor data on this machine (`CODESS_CC_PROJECTS`, …). (2) **Behavior defaults**: scan window (`CODESS_DAYS`), min ingest size (`CODESS_MIN_SIZE`), CC sidechain counts (`CODESS_SUBAGENT`), and debug/redact/force/stop/verbose flags (`CODESS_*` — see §3.3). (3) **Output/registry**: `CODESS_REGISTRY` for central **`ingested_projects.json`**. (4) Truncation limits are **code constants** in **`config.py`**.

**Why:** Same codebase runs on **different OS paths**, **CI sandboxes**, and **user preferences** without editing Python.

**How:** **`config.py`** reads **environment variables at import time** into module-level `Path` / `int` / `bool`. **CLI** arguments are defined in **`codess.project.build_parser()`** and parsed by **`parse_and_run()`**; they may **override** scan/ingest behavior per invocation (e.g. `--days` overrides default recent window). **Precedence:** where a flag exists (e.g. `--days`, `--min-size`), it **wins** for that run; otherwise **ENV** default from **`config`** applies.

**`CODESS_MIN_SIZE` / `--min-size`:** Ingest skips a source file when **`st_size < min_size`**. **`min_size == 0`** means **no size floor** (including empty files). That is **not** the same as omitting **`--min-size`**: omission uses the **`config.MIN_SIZE`** default (20 KiB unless overridden by **`CODESS_MIN_SIZE`** at import). **`validate_config`** rejects **`MIN_SIZE < 0`**.

**Vendor roots must be absolute:** **`validate_config()`** rejects relative
Claude, Codex active/archive, and Cursor roots. Resolving a vendor root from the
process cwd is fragile for scan, CI, and daemons.

**`main.py` vs commands:** **`main.py`** only extends **`sys.path`** and calls **`codess.project.main()`**. **`project.build_parser()`** defines **one** **`ArgumentParser`** (no subparsers): positional **`CMD`** ∈ {**`scan`**, **`ingest`**, **`query`**} plus **all** flags. **`parse_and_run()`** parses **once**, sets logging from **`-v` / `CODESS_VERBOSE`**, then dispatches to **`scan_cmd.run` / `ingest_cmd.run` / `query_cmd.run`**. Unused flags for a given CMD are simply ignored by that command’s implementation.

**Options object (`project.py`):** ENV is **not** re-read on each line of a loop — it is read **once at import** in **`config`**. **`build_scan_run_options(args)`** / **`build_ingest_run_options(args)`** merge **`Namespace` + `config` once per invocation** into a small **frozen dataclass**; **`scan_cmd`** / **`ingest_cmd`** pass **only** the fields they need into **`run_scan`** / **`_ingest_*`**. **Query** can gain the same pattern when it grows ENV-backed toggles.

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
| `CODESS_MAX_CODESS_DB_BYTES` | Storage-report warning threshold for one CoSchema DB | `2147483648` (2 GiB) |
| `CODESS_MAX_CURSOR_DB_BYTES` | Storage-report warning threshold for Cursor's global DB | `10737418240` (10 GiB) |

**Boolean ENV (`CODESS_DEBUG`, `CODESS_FORCE`, `CODESS_SUBAGENT`, `CODESS_STOP`, `CODESS_VERBOSE`, `CODESS_REDACT`):** Implemented in **`config.py`** via **`env_bool()`**: **true** only if, after **`.lower()`**, the value is exactly **`1`**, **`true`**, or **`yes`**. **Unset** uses default **`0`** → false. Values like **`y`**, **`Y`**, **`on`**, **`2`** are **false** (not generic shell truthiness). Export e.g. `CODESS_DEBUG=1` or `CODESS_DEBUG=yes`.

**Why `CODESS_*` vs `DEBUG` / `FORCE` / `SUBAGENT`:** Shell and CI need **prefixed** names (`CODESS_DEBUG`, …) to avoid collisions with unrelated tools. **`config.py`** exposes short **Python** names (`DEBUG`, `FORCE`, `SUBAGENT`) as **bools read once at import** from those variables. Docs refer to **ENV** with the `CODESS_` name; code samples may show **`config.DEBUG`** meaning “the bool parsed from **`CODESS_DEBUG`**.”

**Boolean policy (flags + ENV):** Default is **false** unless the **CLI flag** is passed or the **`CODESS_*`** env parses **true** (see above). **`store_true`** flags: presence → **true**; omission → **false** at argparse, then OR with env where the table says so.

**Note on scan vs ingest `--debug`:** Both use **`CODESS_DEBUG` → `DEBUG`** via **`args.debug or DEBUG`**, but **effects differ**: **scan** uses it only for **discovery trace** + CSV shape; **ingest** uses it for adapter diagnostics/verbosity. Raw retention is controlled independently by **`--raw-mode` / `CODESS_RAW_MODE`**.

**CLI `store_true`:** There is **no** `-y` shorthand.

**Boolean and pseudo-boolean flags — by command**

- **Top-level `-v` / `--verbose`:** true when **`args.verbose or VERBOSE`** from **`CODESS_VERBOSE`**; **`parse_and_run`** sets **`logging.basicConfig(DEBUG)`**. Not the same as **`CODESS_DEBUG`** (vendor/session trace).
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
| `--force` | `CODESS_FORCE` | **`FORCE`** from ENV if flag omitted | **`args.force or FORCE`**; argparse **`default=False`**. Ignores **`ingest_state.json`** mtime skips when true. |
| `--redact` | `CODESS_REDACT` | off | **`args.redact or INGEST_REDACT`**; patterns in **`config.REDACT_PATTERNS`**. |
| `--debug` | `CODESS_DEBUG` | **`DEBUG`** from ENV | **`args.debug or DEBUG`** — see **§3.3**. |
| `--registry PATH` | `CODESS_REGISTRY` | **`~/.codess`** | Central registry dir (`ingested_projects.json`). **`PATH`** overrides default. |

### 4.3 `codess query`

| Flag | ENV | Default | Explanation |
|------|-----|---------|-------------|
| `--dirs` / `--dir` | — | **`get_project_root()`** | Same merge as §3.2; empty → git root or cwd. |
| *(multiple roots)* | — | aggregated | Sessions are globally ordered across selected projects. Roots without stores warn and contribute zero; all roots without stores exit 1. |
| *(multiple vendor DBs)* | — | aggregated | Every existing legacy or per-vendor store returned by `get_project_stores` participates in one logical report. |
| `--source SPEC` | — | all | Query-side vendor scope: `cc`, `codex`, `cursor`, comma-separated union, or `all`. Applied inside stores to every data-bearing report; invalid tokens fail globally. |
| `--limit N` | — | unlimited | Globally limit rows after deterministic cross-project/vendor ordering for `--sessions`, `--permissions`, `--lineage`, and `--audit`. `0` emits no rows; negative values fail before stores are opened. |
| `--session-id ID` | — | — | Show a session by stable global ID or an unambiguous vendor session ID; preferable to recency ordinal in composed workflows. |
| `--output-format table\|jsonl\|csv` | — | table | Sessions/stats have versioned JSONL and spreadsheet-safe CSV; redirect CSV stdout to a file. Other reports currently require table output. |

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

`python -m main scan --dir . --out -`

**Batch errors:** By default, **scan** (per work root) and **ingest** (per file /
DB / project) log failures and continue; exit code 1 if any source failed. Scan
summarizes **`malformed`**, **`invalid_keys`**, **`failed_sources`**, and
**`failed_roots`**. Ingest summarizes **`malformed`**, **`ignored`**,
**`empty_sources`**, and **`failed_sources`**; the first three are nonfatal.
**`--stop`** or **`CODESS_STOP`** makes source failures fail fast.

Incomplete CLI semantics and their dispositions are registered in §8.

### 4.7 Administrative command surface

These implemented families preserve `scan`, `ingest`, and `query`. Focused
commands and orchestrators call the same domain operations:

```text
codess catalog candidates|decide|onboard
codess catalog location add|retire
codess catalog relocate
codess baseline validate|apply|freeze|verify
codess evidence gather|audit
codess schema compare
codess storage report|prune|token-validate
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
| **UC1** | `project.resolve_cli_roots`, `config.get_project_stores`, `snapshot.snapshot_store_paths`, `query_cmd._get_sessions_ordered` |
| **UC2** | `query_cmd._parse_source_tokens`, `_source_predicate`, `sessions.source_system_id` |
| **UC3** | `query_cmd._project_counts`, `_tool_table`, `_artifacts`, `storage_report`, `token_usage` |
| **UC4** | `query_cmd._session_by_identifier`, `_show_session`, canonical `events.sequence_no` ordering |
| **UC5–UC6** | CoSchema `events`, `interactions`, `model_turns`, typed tool/artifact tables, source locators, and `schema/coschema/sqlite/schema.sql` |
| **UC7** | `query_cmd` lineage/audit/permission/task/tool reports and normalized status tables |
| **UC8** | `query_cmd._artifacts`, `artifact_correlation`, `correlation_assertions`, `event_artifacts` |
| **UC9** | `query_cmd._jsonl_output`, `_csv_output`, `schema/query-row-v1.json`, `sanitize.protect_csv_row` |
| **UC10** | `raw_store`, snapshot raw manifests, `sources`, and `source_records` |

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

**When adding a feature:** extend tests in the **same PR**.

---

## 8. Central work registry

This is the sole registry for active work, known gaps, open decisions,
event-triggered maintenance, and postponed topics. Other documents own product
requirements, design rationale, vendor facts, procedures, and evidence; they
link here instead of maintaining another queue.

### 8.1 Execution rules

- Work active items in dependency order unless a production defect or source
  format change takes priority.
- Land each feature vertically: request/contract, data operation, renderer or
  interface, compatibility path, unit/scale tests, real-store smoke test, and
  the affected README capability row.
- A vendor fact or research idea becomes work only when it receives a registry
  ID here.
- Rebuild derived stores and replace accepted baselines rather than mutating
  them in place.

#### 8.1.1 Current review checkpoint

The implementation is deliberately stopped before real-store rollout. The
existing format-3 snapshots and approved-baseline pointers have not been
replaced. The format-4 package is a **candidate**, not an accepted release,
until R1 and the two parts of R3 are confirmed. R2 is decided.

Directions already established and not reopened by this checkpoint:

- preserve useful vendor- and release-specific evidence even before it has a
  common field;
- expose normalized common names for mixed-vendor queries while retaining exact
  source names, values, locators, and mapping evidence;
- support documented and automated source-to-common and common-to-external
  mappings as separate directions; and
- retain dated, versioned snapshots and detect changed sources rather than
  migrating accepted derived stores in place.

| Review ID | Small decision still required | Current recommendation | Work held until decision |
|---|---|---|---|
| **R1** | Accept CoSchema format 4 now, or defer the complete contract/JSON correction | Accept format 4: it makes already-used functional tables/fields and JSON obligations truthful and machine-verifiable; keep formats 2/3 read-only | Release designation, real-store rebuild, baseline replacement |
| **R2 — decided** | Routine source-update fingerprint | Use fast, non-authenticating MD5: full-file through 64 MiB and labeled bounded sampling above it, including SQLite WAL state. This is only a change detector. Captured raw objects retain complete SHA-256 because it is their content address and integrity check, not the routine fingerprint. | Measure scale/detection behavior; no further policy approval required |
| **R3a** | Authoritative occurrence provenance | Recommend per-event JSON provenance containing source record/locator/field path and exact source value or designation. Keep reusable model-configuration columns limited to normalized configuration values. Do not rely on one representative `source_config` as occurrence history. | Decide whether `source_config` is removed, retained only as a non-authoritative example, or narrowed to configuration-level notes |
| **R3b** | Materialized model-configuration observation table | Recommend postponing it. Add one only when direct queries need every configuration-field occurrence without JSON extraction. If approved now, it adds a row per observed field/occurrence plus event/source links and becomes part of the format-4 contract. | Final format-4 table set and query design |

R3a and R3b solve different problems. Provenance answers “which exact source
field justified this value on this event?” and is required even without a new
table. An observation table answers “show and aggregate every occurrence of a
configuration field efficiently.” The alternatives are:

- **Per-event JSON only (recommended now):** exact and naturally attached to
  the event; no additional joins or row multiplication. Queries use
  `json_extract` and repeated provenance is less compact.
- **Observation table now:** strongest relational querying and indexing, with
  explicit event/source/configuration foreign keys. It materially increases
  row counts, schema surface, ingestion work, and rules for deduplication and
  partial observations.
- **Representative `source_config` only:** compact but ambiguous when the same
  normalized configuration came from several releases or field paths. This is
  not sufficient as authoritative provenance and is not recommended.
- **Hybrid later:** keep authoritative event JSON now, then build a rebuildable
  observation projection if real queries justify it. This preserves evidence
  without committing the central schema prematurely.

Until R1 and R3a/R3b are resolved, changes may receive tests and documentation fixes but
must not promote a format-4 baseline, alter approved pointers, or claim a new
Codess release.

The format-4 package and reviewed corpus are current. SWEmore, spank-py, and
Zero400 passed policy, query-smoke, integrity, foreign-key, and repeat-ingest
fixed-point checks; approved and reviewed catalogs were frozen to those
snapshots. The retained raw set uses one shared Cursor cohort for Zero400,
zerowalletmac, and Spank/Logs. Superseded format-3/intermediate snapshots,
obsolete Cursor captures, and temporary working archives were pruned through a
validated retention receipt. Future schema changes return to the same
compare/rebuild/freeze sequence rather than mutating these stores.

ZeroPerf is the `perf-401` linked Git worktree of Zero400's repository, whose
current primary worktree is on `testfix-401`; it is not an unrelated repository.
It remains a separate CodeSess Project/session scope for now, while candidate
Git observations record the shared common Git directory so repository-level
queries and future correlation can group them explicitly.

### 8.2 Active work

| Order | ID | Work item | Completion evidence |
|------:|----|-----------|---------------------|
| 1 | **A1** | Typed selection kernel and `codess.query-request/1`: Project/catalog/vendor/session/time/event/tool/status/model/artifact scope; current and explicit historical snapshot resolution; reject ignored predicates | Cross-store tests prove identical scope across renderers and no out-of-scope rows |
| 2 | **A2** | Orientation and utilization overview: sessions, Interactions, turns, events, content volume, tools, artifacts, models, elapsed span, active days/time estimate, and time buckets | Golden reports cover empty, tiny, multi-vendor, long-idle, many-small-session, and one-huge-session stores |
| 3 | **A3** | Event and Interaction drill-down: typed event rows, stable event lookup, complete Interaction/Model Turn, sequence windows, source locators, and completeness | Known Claude, Codex, and Cursor exchanges reconstruct in canonical order |
| 4 | **A4** | Bounded search by Project/vendor/time/type with completeness warnings and product-state facets; benchmark a rebuildable FTS5 derivative only afterward | Known hits, truncated false-negative warnings, repeated-state noise tests, and bounded resource evidence |
| 5 | **A5** | Complete failure/resource validation for exact raw capture and bounded fingerprints. Transactional standalone SQLite backup, metadata-only cohort cache, all-Project marker preflight, direct fresh-backup queries, staged level-3 zstd, content-addressed reuse across valid encodings, bounded restore/verification, no-op snapshot suppression, atomic promotion, and retention apply are implemented | Add measured fresh-capture peak RSS, injected partial-failure/no-promotion cases, and documented large-source sampling false-negative bounds; measure cache restoration for a newly selected Project |
| 6 | **A6** | Exact evidence resolver from event to source record to verified live, captured, or sealed evidence | The same record resolves from live and captured evidence; changed or unavailable sources are explicit |
| 7 | **A7** | Reusable results and automation: `codess.query-result/1`, saved selections, result-set input, hashes, prior-result comparison, stable exit codes, and derivation records | A multi-step investigation replays against the same snapshots and cites every evidence row |
| 8 | **A8** | Guided investigation and optional question-to-typed-request formulation | Project → overview → search → Interaction → exact evidence → cited summary works without handwritten SQL |
| 9 | **A9** | Performance and ecosystem: predicate/limit pushdown, heap merge, profiling, justified read-only views, and Datasette/notebook/DuckDB recipes | Scale fixtures bound rows, bytes, and RSS; external recipes remain read-only |
| parallel | **A10** | Resolve Codex token counter reset/model/fork/interleave attribution, or formally limit it to non-billing evidence | The diagnostic either proves a stable attribution rule or records a permanent confidence boundary |
| maintenance | **A11** | Consolidate duplicated Claude/Codex ingest control flow and review remaining compatibility aliases/wrappers, including `retire_project.py` | Shared control flow has one tested owner; retained wrappers are thin, documented, and have an explicit keep/remove decision |

### 8.3 Known gaps

The IDs below are stable references for README use cases, vendor evidence, and
tests. A gap is not automatically active work; the **Disposition** column names
its active item or trigger.

| ID | Known gap | Disposition |
|----|-----------|-------------|
| **L-S1** | No catalog-wide current selector by Project ID, topic, ownership, or curation state | **A1** |
| **L-S2** | No common CLI selection by date/model/event/Interaction/turn/status/artifact or stable event ID | **A1–A3** |
| **L-S3** | No historical union or semantic snapshot-diff operation | Decide under **D9**, then **A1/A7** |
| **L-O1** | Structured JSONL/CSV covers sessions and stats only | **A2–A4**, then **A7** |
| **L-O2** | Aggregate reports often omit constituent stable session/event identities | **A2–A3** |
| **L-O3** | Results cannot be consumed directly as a saved or chained selection | **A7** |
| **L-M1** | Orientation is limited to shallow session/event totals | **A2** |
| **L-M2** | Elapsed span exists, but active-time semantics and gap sensitivity are unsettled | Decide under **D3**, implement in **A2** |
| **L-M3** | Utilization differs by vendor: Codex attribution is provisional, Cursor lacks verified local tokens, and quota/price facts are dated external evidence | **A10**; do not infer tokens from text |
| **L-C1** | No first-class bounded search, ranking, topic classification, or saved search | **A4**, **A7** |
| **L-C2** | Normalized content may be sanitized, filtered, redacted, or truncated; a miss does not prove raw absence | Preserve completeness in **A3–A6** |
| **L-C3** | No command resolves one normalized event to its exact available source record | **A5–A6** |
| **L-P1** | Interaction, Model Turn, phase, and cross-vendor correlation confidence varies; shared evidence is not authorship | Preserve method/confidence in **A2–A8** |
| **L-P2** | Repeated Cursor title/mode/permission/reminder state can dominate naïve text search | **A4** facets and defaults |
| **L-E1** | Cross-store reports materialize and sort selected sessions in Python | **A9** |
| **L-E2** | Repeated substring search has no rebuildable policy-aware index | Benchmark after **A4**; decide under **D4** |
| **L-E3** | Cursor selection and SQLite writes are composer-streamed, but ordering/deduplication and Interaction construction still buffer one complete composer; a real 19,661-event composer reached about 531 MiB RSS | **A9**: profile allocation owners, then make event grouping/stateful writes incremental without weakening rollback or canonical ordering |
| **L-E4** | First capture of a changed 4.78 GB Cursor DB still requires one transactional backup and streaming compression; a newly selected Project may require one verified streaming restore of an unchanged cached cohort | **A5/A9**: measure fresh-capture and cache-restore I/O/RSS; keep the unchanged all-Project path at bounded marker cost only |
| **V-CC1** | Claude slug decoding is lossy when the index lacks an explicit Project path | Prefer indexed paths; reopen mapping only with new evidence |
| **V-CC2** | Claude model/service settings, custom/AI titles, agent names, direct fork references, and bounded product state are mapped; richer runtime-context snapshots remain only partially specialized | Validate under **A12**; other context remains evidence-triggered |
| **V-CTX1** | Runtime context such as memory, skills/tool schemas, reasoning/turn context, and detailed token snapshots is not represented as a first-class common model | Evidence- and use-case-triggered; define semantics before adding entities |
| **V-CX1** | Codex supplies no direct referential parent-session identifier | Unsupported until **T4** |
| **V-CU1** | Cursor composers without usable workspace/header mapping remain unattributed | Evidence-triggered mapping maintenance under **T1** |
| **V-CU2** | Cursor scan time range is incomplete when headers lack usable timestamps | Preserve coverage diagnostics; do not decode all bubbles merely for dates |
| **V-CU3** | Cursor exposes exact `modelInfo.modelName` and accepted/rejected `toolFormerData.userDecision`, but no separate observed effort, speed, or service-tier fields | Validate model/permission provenance under **A12**; retain absent settings as NULL |
| **E-1** | Lifecycle abort is fixture-only in the reviewed corpus | Add a real shape only under **T4** |
| **E-2** | Settings are uneven: Codex records model/effort and newer service tier; Claude records model/service tier; Cursor records model only; no distinct speed-tier evidence was observed | **A12**; preserve exact values and field provenance, never derive speed from a model label |

### 8.4 Decision register

Resolve a decision immediately before its first consuming work item; do not
block unrelated work.

**State:** D4 and D10 are adopted directions; D11's normalized identity is
adopted while occurrence representation remains at R3a/R3b. D7 has an approved iterative
shape but each method still needs evaluation; D1, D2, D3, D5, D6, and D9 are
expanded recommendations awaiting acceptance; D8 remains the only unframed
open choice.

| ID | Decision | Needed by | Recommended direction |
|----|----------|-----------|-----------------------|
| **D1** | Query interface shape | **A1–A4** | **Recommend subcommands.** Use `query sessions|overview|events|search|show` because they have different result contracts and required arguments; keep Project/vendor/session/time and output flags shared. One typed request remains the implementation kernel. Existing flat report flags become documented compatibility aliases, then deprecate only after command parity. This reduces invalid flag combinations and makes help/completion usable without fragmenting query semantics. |
| **D2** | Inline and saved selection representation | **A1**, **A7** | **Recommend both over one schema.** Inline requests are the inspectable/default form. A saved selection stores the canonical request, snapshot IDs, policy/package hash, and optionally materialized stable IDs; its content hash names it. Predicates support refresh, explicit IDs support exact replay, and a saved result must state which form it contains. |
| **D3** | Derived active-time sensitivity | **A2** | **Recommend a sensitivity report, not one duration.** Always report observed elapsed span and event-bearing intervals; estimate active time with declared default gap caps of 5, 30, and 120 minutes plus configurable caps. Include the gap histogram and never call an estimate observed, billable, or charged time. |
| **D4** | Full-source search derivative | postponed | Normalized, bounded search remains **A4**. Any full-source index remains postponed indefinitely until an explicit privacy, encryption, retention, deletion, and access design is approved; raw capture alone does not authorize indexing. |
| **D5** | Exact evidence resolution precedence | **A6** | **Recommend evidence equality before location preference.** Resolve a hash-matching sealed/captured object first; accept live evidence only after its revision/hash matches; allow an explicitly selected immutable snapshot next. Report changed live files as mismatching candidates and unavailable sources as unavailable—never silently fall through to a different revision. |
| **D6** | Stable SQL views and query package boundary | **A9** | **Recommend typed application queries as owner.** Add a vendor-neutral read-only SQL view only after two independent consumers repeat the same stable row contract and compatibility tests cover it. Keep exploratory SQL in documented recipes. A standalone versioned `queries.sql` package remains **P7**, not a prerequisite for ordinary reports. |
| **D7** | Topic/phase derivation methods and composition | **A8** | **Use multiple, composed methods iteratively:** (1) deterministic lexical rules and explicit vendor events; (2) phase heuristics over ordered windows; (3) optional versioned embeddings for recall; (4) optional LLM labels only on bounded candidates; (5) an ensemble assertion that cites its inputs. Preserve every method/version/evidence/confidence separately rather than overwriting one label. Promote each stage only after a labelled evaluation set shows added value. |
| **D8** | What result provenance is mandatory? | **A1**, **A7** | Require package/query hashes, snapshot IDs, policy, source availability, truncation, and processor identity |
| **D9** | Historical snapshot semantics | **A1**, **A7** | **Recommend one immutable snapshot by default.** Historical reads require an explicit snapshot selector. Diff compares stable entity IDs, source revisions, and content/semantic hashes; union is a separate explicit operation retaining observation identity and duplicate diagnostics. Never combine “latest” rows from different snapshots implicitly. |
| **D10** | Saved-result validity across Project moves | **A7** | Treat relocation separately from extraction correctness. Bind result identity and comparison to stable Project/session/event IDs plus snapshot/query hashes; retain the observed filesystem path as time-specific provenance. A move updates location bindings, not prior evidence, and must not excuse inaccurate or inconsistent extraction. |
| **D11** | Model-configuration identity and provenance | **A2–A3**, **A12**, **R3a/R3b** | Keep provider, family, exact name, revision, effort, speed, service tier, and mode nullable and independently queryable. Use their normalized tuple as null-safe configuration identity; do not infer one setting from another. Preserve exact source values and field paths per event. R3a/R3b decide whether `source_config` remains and whether occurrences receive a relational projection. |

### 8.5 Event-triggered maintenance

| ID | Trigger | Required response |
|----|---------|-------------------|
| **T1** | Vendor storage or source-format change, or observed unmapped evidence | Update the vendor fact document and smallest representative fixture; run the bounded vendor audit and compatibility gate |
| **T2** | Package/schema/mapping change or accepted source refresh | Run preflight, fixed-point rebuild, semantic sampling, query smoke tests, and atomic baseline replacement |
| **T3** | Material ingest/rebuild or unexplained storage growth | Run storage observation and dry-run prune; apply only a reviewed selection with a receipt |
| **T4** | Direct Codex parent ID, distinct speed tier, a new lifecycle shape, or another recorded evidence gap appears | Add the minimal source shape, mapping, fixture, and compatibility assertion; update the gap disposition |
| **T5** | Project move, replacement checkout, or demonstrated cross-vendor correlation need | Update stable location/source bindings; add a corpus member only when the existing corpus cannot answer the compatibility question |
| **T6** | Every implementation change | Keep the full suite and representative candidate, onboarding, evidence, baseline, relocation, and real-store smoke workflows green |

### 8.6 Postponed topics

These are intentionally outside the active product sequence. The first table
can be composed today from Codess commands and external/system tooling; native
implementation is justified only when orchestration, portability, provenance,
or atomic failure semantics become product requirements.

#### 8.6.1 Externally orchestratable

| ID | Topic | Restart condition |
|----|-------|-------------------|
| **P1** | Enterprise PII/secret scanning beyond configured regex policy | External scanners can gate source/raw promotion now. Add native policy integration only when a deployment threat model requires uniform findings, suppression, and provenance. |
| **P2** | Periodic storage/query scheduling and notifications | Use `launchd` on macOS, systemd timers on Linux, or cron/CI to invoke stable commands and retain outputs. Add an internal scheduler only when cross-platform lifecycle and notification state are product requirements. |
| **P3** | Proactive baseline refreshes and vendor audits | An external scheduler may run dry-run/audit commands; promotion remains reviewed. Reopen native automation under **T1/T2** only if safe apply policy is defined. |
| **P6** | Natural-language query execution | An external LLM can formulate a proposed typed request after **A1–A7**; Codess must validate and display it before execution. Native formulation waits for evaluation and trust requirements. |
| **P7** | Standalone `queries.sql` package | SQLite CLI, Datasette, sqlite-utils, and notebooks can consume documented read-only recipes. Package only when **D6** has repeated external consumers and a versioned contract. |
| **P8** | Multi-Project `baseline refresh` orchestration | Shell/Make/CI can compose preflight → apply → validate → freeze per Project now. Native orchestration waits for demonstrated cross-Project rollback and partial-failure semantics. |
| **P9** | First-class Markdown report export | `jq`, templates, notebooks, or report tools can render typed JSONL/CSV. Add a native format only when a stable customer-facing Markdown contract is required. |

#### 8.6.2 Product functionality still postponed

| ID | Topic | Restart condition |
|----|-------|-------------------|
| **P4** | Broad historical discovery or additional vendors | A concrete compatibility, correlation, or active-work requirement appears; filesystem/Git discovery can propose candidates but cannot approve catalog membership. |
| **P5** | FTS5 normalized-search derivative | **A4** bounded search is measured and repeated scans justify an index. This does not authorize the full-source derivative postponed by **D4**. |

### 8.7 Completed foundation retained for follow-up

Only completed capabilities that constrain current work are retained here:

- CoSchema v4 package, two-way contract/DDL and JSON enforcement, canonical
  DDL, common/vendor mappings and event-level mapping evidence, diagnostics,
  content lineage, raw modes, immutable snapshots, and reader compatibility.
- Automated preflight, fixed-point validation, reviewed/approved catalogs,
  semantic/query gates, and the bounded three-vendor compatibility corpus.
- Stable Project/location/workspace identities, source links, candidate review,
  curated onboarding, relocation, evidence audits, and retention receipts.
- Correct vendor filtering, stable session IDs, sequence ordering, lineage,
  audit/diagnostic/artifact reports, sessions/stats JSONL and protected CSV,
  single-report validation, and pipeline-safe shutdown.
- Resource limits/telemetry, storage observations, latest-only pruning, and
  provisional derived token observations.

## 9. Change routing

Use **Codess.md §4.3** for documentation ownership:

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
