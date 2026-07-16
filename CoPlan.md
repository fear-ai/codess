# CoPlan — Implementation Plan and Engineering Guide

**Audience:** Contributors maintaining **Codess** (Python CLI + library).

### Table of Contents

| § | Section |
|---|---------|
| [§2](#2-repository-layout) | Repository Layout |
| [§3](#3-system-architecture) | System Architecture — **§3.0–§3.6** |
| [§4](#4-configuration) | Configuration |
| [§5](#5-cli-and-runtime-contract) | CLI and Runtime Contract |
| [§6](#6-feature--implementation-map) | Feature → Implementation Map |
| [§7](#7-coding-techniques) | Coding Techniques |
| [§8](#8-tests) | Tests |
| [§9](#9-delivery-sequence) | Delivery Sequence |
| [§10](#10-implementation-gaps) | Implementation Gaps |
| [§11](#11-improvement-backlog) | Improvement Backlog |
| [§12](#12-change-routing) | Change Routing |
| [§13](#13-optional-splits) | Optional Splits |
| [§14](#14-decisions) | Decisions |
| [§15](#15-consolidated-engineering-gaps-discussion-brief) | Consolidated Engineering Gaps (discussion) |

### Scope

Repository tree; architecture (call graph, data pipelines, persistence); configuration (what, why, how); CLI contract (flags, ENV, defaults); feature → module index; coding practices; test strategy; delivery sequence; backlog, status, and review queue.

### Not Here

Vendor paths, filenames, DB keys, or field values — **CCSchema.md**, **CodexSchema.md**, **CursorSchema.md**; normalized columns — **CoSchema.md**.

### Documentation Boundaries

Per **Codess.md §4.1** (verbatim):

| Topic | Document |
|-------|----------|
| Why the product exists; audience; this index | **Codess.md** |
| Repository layout, layers, data flows, configuration, **CLI tables**, coding, **§8 Tests**, **§3.5–§3.6** status and verified wiring, delivery sequence, backlog **§11**, decisions **§14**, gap themes **§15** | **CoPlan.md** |
| Claude Code paths, index, JSONL fields, scan metrics | **CCSchema.md** |
| Codex session files | **CodexSchema.md** |
| Cursor `state.vscdb` keys and values | **CursorSchema.md** |
| Our normalized `sessions` / `events` columns | **CoSchema.md** |
| Executable DDL | **schema/coschema/sqlite/schema.sql** |

Per **Codess.md §4.2**, the **CoPlan.md** row (verbatim):

| Document | Goal | Include | Exclude |
|----------|------|---------|---------|
| **CoPlan.md** | *How* the repo implements and validates behavior | Tree, layered architecture, persistence notes, **§3.5–§3.6** status and verified wiring, **§4 configuration**, **§5 CLI**, features→modules, coding, **§8 Tests**, delivery sequence, backlog **§11**, **§14–§15** | Vendor on-disk truth (→ *Schema.md) |

Cross-cutting doc rules (ToC, no transient links from core docs, etc.): **Codess.md §4.0**.

---

## 2. Repository Layout

**Terms:** **scan** = discover projects that have vendor session data from vendor indexes. `CMD` is `scan` \| `ingest` \| `query` in **`build_parser()`**.

```
Codess/
├── main.py                 # sys.path + codess.project.main()
├── README.md
├── Codess.md
├── CoPlan.md
├── CoSchema.md
├── CCSchema.md
├── CodexSchema.md
├── CursorSchema.md
├── sql/
│   └── CoSchema.sql        # DDL; store.init_db() executes this file
├── src/
│   ├── cli/
│   │   ├── scan_cmd.py     # run(): roots, run_scan(), CSV; registry upsert + optional --registry filter + reg_* cols
│   │   ├── ingest_cmd.py   # run(): roots, _ingest_cc|codex|cursor; registry merge via registry_store
│   │   └── query_cmd.py    # run(): read-only multi-root/store reports; --stats → registry merge
│   └── codess/
│       ├── config.py       # ENV → Path / int / bool; defaults; no other codess imports
│       ├── helpers.py      # parse_dir_list, validate_dirs_file, write_csv, is_excluded, slug/path … ; imports config
│       ├── registry_store.py  # ingested_projects.json merge (scan / ingest / query)
│       ├── sanitize.py     # text cleanup + redact; imports config
│       ├── store.py        # SQLite, DDL, transactional replacement, ingest state
│       ├── project.py      # argparse, parse_and_run, roots, run-options, git root, vendor path helpers; imports config only — no walk, no scan
│       ├── scan.py         # run_scan(); config, helpers, project, adapters.cursor.get_db_metrics
│       ├── adapters/
│       │   ├── cc.py
│       │   ├── codex.py
│       │   └── cursor.py   # process_* + get_db_metrics (used by scan for metrics)
└── tests/                  # order mirrors src/codess + cli; full map in §8 Tests
    ├── test_config.py
    ├── test_helpers.py
    ├── test_project.py
    ├── test_store.py
    ├── test_scan.py
    ├── test_registry_store.py
    ├── test_cc_adapter.py
    ├── test_codex_adapter.py
    ├── test_cursor_adapter.py
    ├── test_sanitize.py
    ├── test_candidate.py
    ├── test_subagent_detail.py
    ├── test_cli.py
    └── test_integration.py
```

Legacy **`scripts/`** (if present): obsolete vs CLI; remove when unused.

---

## 3. System Architecture

### 3.0 Discovery contract

Discovery is index-led. Claude, Codex, and Cursor keep session data outside the
project tree and record project paths in their own indexes or session metadata.
`--dir` and `--dirs` therefore define validated path filters; they do not request
a filesystem crawl. There is no recursion flag or general walk subsystem.

### 3.1 Call Graph and Module Roles

- **`main.py`:** Prepends `src/` → `codess.project.main()` → `parse_and_run()` → **`cli.scan_cmd.run`** \| **`cli.ingest_cmd.run`** \| **`cli.query_cmd.run`**.
- **`codess.config`:** ENV and constants; used by **`project`**, **`scan`**, **`helpers`**, **`adapters/*`**, **`sanitize`**, CLI.
- **`codess.helpers`:** Roots/CSV/excludes/slug helpers; imports **`config`**. Used by scan and root resolution.
- **`codess.sanitize`:** Shared ingest, terminal-display, tabular-output, redaction, and CSV-cell policy.
- **`codess.store`:** SQLite, DDL, upsert primitives, transactional source
  replacement, and ingest state. **`ingest_cmd`** writes it; query opens the
  resulting databases read-only.
- **`codess.project`:** **`build_parser`**, **`parse_and_run`**, **`resolve_cli_roots`**, **`build_*_run_options`**, **`get_project_root`**, vendor path helpers. Imports **`config` only** — **no** **`scan`**.
- **`codess.scan`:** **`run_scan()`**; imports **`config`**, **`helpers`**, **`project`**, **`adapters.cursor.get_db_metrics`**.
- **`cli/*_cmd`:** Thin **`run(args) -> int`**: roots/options, then **`run_scan`** / **`_ingest_*`** / **`store.connect`**.

**Query vs ingest vs adapters:** Ingest parses sources and transactionally
replaces their normalized rows in **`.codess/*.db`**. Query runs read-only SQL
on those DBs only—no vendor files or adapters.

**§4 vs §5:** §4 documents **ENV** and **`config.py`**. §5 documents **CLI flags** and **`build_*_run_options`**, which merge **`Namespace`** with those defaults per run.

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
        ├──► codess.adapters.cursor.get_db_metrics   ← see Discouraged Imports / justified coupling
        ▼
 codess.config   codess.helpers   codess.project  (path helpers for scan)

 ingest_cmd ──► codess.adapters.* ──► store.replace_* … , ingest_state JSON
```

**Dependency sketch:** **`adapters/*`** → **`config`**, **`sanitize`**; called from **`ingest_cmd`**, and **`get_db_metrics`** from **`scan.py`**. **`scan.py`** → **`config`**, **`helpers`**, **`project`**, **`adapters.cursor`**. **`project.py`** → **`config`** only; **`cli/*`**, **`scan.py`**. **`store.py`** → no codess imports; **`ingest_cmd`**, **`query_cmd`**.

### 3.2 Discouraged Imports

This subsection is **normative policy**, not a full import graph. It answers: *where must we not put parsing or store logic so layers stay thin?* A short checklist here is **not** “every allowed edge” — see **§3.1** for who calls whom.

**Why it feels incomplete:** **`scan.py` → `adapters.cursor.get_db_metrics`** breaks the tidy picture “scan never touches adapters.” That is **intentional reuse** of read-only sizing SQL, documented below so we do **not** silently add more adapter imports into **`scan`**.

- **`cli/*_cmd`:** do not parse vendor JSONL/SQLite inline; ingest goes through **`adapters/*`**.
- **`adapters/cc.py`, `adapters/codex.py`:** do not import **`scan`**, **`scan_cmd`**, or **`ingest_cmd`**.
- **`query_cmd`:** do not import **`adapters/*`**.

**Justified coupling:** **`scan.py`** imports **`codess.adapters.cursor.get_db_metrics`** so scan reuses the same **read-only** Cursor DB sizing logic as elsewhere, without copying SQL or pulling in **`process_db`** event normalization.

### 3.3 Data Movement — Three Pipelines

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
- **Mechanism:** Open **`.codess/*.db`** — see **§3.4**. **`query_cmd`** does not write vendor trees.

### 3.4 Persistence Layout

*Layout is provisional.*

Under each **project directory**, **`STORE_DIR`** (`.codess/`) holds:

- **Per-vendor DB files** (`sessions_cc.db`, `sessions_codex.db`, `sessions_cursor.db`) and/or **legacy** `sessions.db` — **`get_store_path`**, **CoSchema.md**.

**Intent:** Split DBs reduce coupling while adapters differ. A merged DB would require coordinated **`store`**, **CoSchema**, and **test** changes.

**`ingest_state.json`:** Per-project source mtimes for incremental ingest.
Changed/forced Claude and Codex transcripts replace one session; Cursor refresh
replaces events owned by that database. Empty valid transcripts remove stale
normalized sessions and increment the nonfatal `empty_sources` diagnostic.

### 3.5 Implementation vs Validation

Verification baseline is the full **`pytest tests/`** suite. **Validated** here means representative automated coverage, not every edge case.

| Area | Implemented | Validated | Gaps |
|------|-------------|-----------|------|
| Scan (index-led) | Yes | CLI + `test_scan*`, metrics | Cursor time range covers header-indexed sessions only |
| Ingest | Yes | Adapters, replacement/store integration, CLI | Transactional replacement, empty sources, active/archive deduplication, continue/fail-fast handling, and scoped global Cursor ingest are covered |
| Query | Yes | CLI, store, scale tests | Read-only aggregation, global numbering, session origin details, lineage, evidence-backed audit rows, and globally bounded reports across project/vendor stores |
| **`validate_config()`** | Yes | Unit and subprocess CLI tests | Applied consistently to scan, ingest, and query |
| Store / DDL | Yes | `test_store` | — |
| Sanitize | Yes | Sanitizer, adapter, helper, and CLI tests | Regex redaction is intentionally limited; enterprise PII scanning is explicitly postponed |

**Completeness:** Main workflows, configuration validation, source replacement,
cross-store query aggregation, lineage, audit normalization/reporting, and
bounded row reports are covered. Active evidence work is limited to a modern
Cursor tool-call/result shape, catalog-backed external-artifact correlation,
and direct Codex parent-session evidence. Speculative preflight, machine output,
and PII scanning are postponed. See **§11** and **§15**.

### 3.6 Verified wiring

Cross-checked against **`src/`** and **`tests/`** so this plan does not drift from the repo. Re-audit after large refactors.

- **`main.py`:** prepends **`src/`**, calls **`codess.project.main()`** → **`parse_and_run()`**.
- **Dispatch:** **`parse_and_run`** lazy-imports **`cli.scan_cmd` / `cli.ingest_cmd` / `cli.query_cmd`** then branches on **`args.command`**.
- **`run_scan(work_root, …)`:** parameters are **`vendor_filter`**, **`recent_days`**, **`debug`**, and **`subagent`**. Scan is index-led and exposes no recursion option.
- **`validate_config()`:** invoked before work by scan, ingest, and query; errors are printed to stderr and return exit 1.
- **`query_cmd`:** opens every selected project store read-only and aggregates report rows in Python, avoiding SQLite's attached-database limit and preserving duplicate vendor session IDs internally. It imports **`get_project_stores`**, **no** **`adapters/*`**.
- **`scan.py`:** imports **`adapters.cursor.get_db_metrics`**; **does not** import **`walk`**.
- **`project.py` module imports:** **`codess.config`** only at top level for the public CLI surface.
- **`adapters/*`:** **no** imports of **`scan`**, **`scan_cmd`**, or **`ingest_cmd`**.
- **Central registry (`ingested_projects.json`):** **`codess.registry_store`** merges per-project records. **Scan** always upserts **`scan`** / **`last_scan`** for every discovered project path into **`resolve_registry_directory(args)`** (default **`CODESS_REGISTRY`**). **`--registry PATH`** overrides that root and, when set, **also** filters CSV to paths present in the file **before** this run + appends **`reg_*`** columns — **no** sidecar. **Ingest** merges **`sources`** / **`last_ingestion`**. **Query `--stats`** merges **`query`** / **`last_query`** into the same file (**§5**).
- **`validate_scan_source_for_cli` / scan `--source`:** invalid tokens → **stderr + exit 1** before any scan work (**global** invocation policy — **§11.5**, **§14**).
- **`store.init_db`:** executes **`schema/coschema/sqlite/schema.sql`** when that file exists (path resolved from **`store.py`** location).

---

## 4. Configuration

### 4.1 What Is Configurable, Why, and How

**What:** (1) **Locations** of vendor data on this machine (`CODESS_CC_PROJECTS`, …). (2) **Behavior defaults**: scan window (`CODESS_DAYS`), min ingest size (`CODESS_MIN_SIZE`), CC sidechain counts (`CODESS_SUBAGENT`), and debug/redact/force/stop/verbose flags (`CODESS_*` — see §4.3). (3) **Output/registry**: `CODESS_REGISTRY` for central **`ingested_projects.json`**. (4) Truncation limits are **code constants** in **`config.py`**.

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

### 4.2 Combining `--dir` and `--dirs`

1. If **`--dirs FILE`** is passed, **`helpers.validate_dirs_file`** runs first: file **must exist**, be a **regular file**, be **readable**, and contain **≥1** non-comment path line — otherwise **stderr** message and **exit 1** (scan / ingest / query).
2. **`helpers.parse_dir_list(dirs_file, dir_args)`** builds **one ordered list** of **resolved** `Path`s.
3. If **`--dirs FILE`** validated, lines are read **first** (in file order).
4. Each **`--dir PATH`** is **appended** in argv order.
5. **Duplicates** (same resolved path) are **skipped**.
6. **User root strings** (`--dir` lines, **`--dirs`** file): **`..`** in any path **component** is **disallowed** (skipped + warning). **Relative** paths: any segment **starting with `.`** except the lone segments **`.`** and **`..`** is **disallowed** — this blocks **hidden-style** relative segments (e.g. **`.venv`**, **`.private`**) while still allowing **`.`** (cwd) and paths like **`./repo`** (the **`.`** segment is explicitly allowed). **Absolute** paths may contain segments such as **`.config`** under the home tree. **Empty** lines / empty **`--dir`** arguments are skipped. Root strings are paths, not glob patterns.
7. If the result is **empty**: **`scan_cmd`** uses **`Path.cwd()`**; **`ingest_cmd`** and **`query_cmd`** use **`get_project_root()`** (`git rev-parse --show-toplevel` from cwd, else cwd — see **`project.py`**).

**`DEFAULT_WORK` / `is_excluded`:** There is **no** CLI flag for **`DEFAULT_WORK`** (`~/Work`). **`is_excluded(p, work_root=None)`** uses **`DEFAULT_WORK`** only as the **`relative_to`** anchor when **`work_root`** is omitted — **`scan.run_scan`** passes the real **`work_root`** into **`canonicalize`**, so exclusion is relative to the **scan root**, not **`~/Work`** unless you omit the argument in other call sites.

### 4.3 Environment Variables

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

## 5. CLI and Runtime Contract

**Purpose:** Operator-facing **flags**, **ENV**, and **defaults**. Vendor metric semantics → ***Schema.md**.

**Table columns:** **Flag** | **ENV** (variable name, or **—**) | **Default** (when flag omitted / ENV unset as applicable) | **Explanation**.

### 5.1 `codess scan`

| Flag | ENV | Default | Explanation |
|------|-----|---------|-------------|
| `--dirs PATH` | — | — | File of work roots (§4.2). |
| `--dir PATH` | — | — | Append root; repeatable. |
| *(no dirs after merge)* | — | **`Path.cwd()`** | **Scan** only; see §4.2. |
| `--source cc,codex,cursor` | — | all three | Comma-separated vendor subset; **order does not matter**. Tokens are compared case-insensitively after trim. **`all`** clears the filter (same as omitting **`--source`**). **Invalid token** (anything other than **`cc`**, **`codex`**, **`cursor`**, or the whole value **`all`**) is a **global** error: **stderr** message listing bad tokens and **exit 1** — no partial vendor set (**§11.5**). |
| `--out PATH` | — | `codess_walk.csv` | CSV path; **`write_csv`** creates **parent directories**. |
| `--out -` | — | — | CSV to **stdout** (not **`write_csv`**). |
| `--days N` | `CODESS_DAYS` | **`90`** | Recent window; omitted → **`CODESS_DAYS`**. |
| `--debug` | `CODESS_DEBUG` | off if flag omitted **and** unset ENV | Discovery trace + CSV **`dir_path`**; **`args.debug or DEBUG`** — see **§4.3**. |
| `--subagent` | `CODESS_SUBAGENT` | **`SUBAGENT`** from ENV | **`args.subagent or SUBAGENT`** — see **§4.3**. |
| `--registry PATH` | `CODESS_REGISTRY` | — | **Directory** for **`ingested_projects.json`**: default **`CODESS_REGISTRY`** (`~/.codess`); **`PATH`** overrides for this invocation. **Scan:** always **writes** merged index metrics to that directory; when **`--registry`** is **passed**, **also** restricts CSV to paths already listed **before** this run and adds **`reg_*`** columns. **Argparse requires a path** — no bare **`--registry`**. |
| `-v` / `--verbose` | `CODESS_VERBOSE` | off | Python **`logging`** level **DEBUG** (process-wide); not **`CODESS_DEBUG`**. |

**Precedence (scan):** **`--days` omitted** → **`CODESS_DAYS`**. **`--subagent`:** **`args.subagent or SUBAGENT`**. **`Registry`:** **`project.resolve_registry_directory(args)`** selects the registry **root** for **both** scan upserts and (when **`--registry PATH`** is set) filter + join columns.

**Output columns:** `path,vendor,sess,mb,span_weeks` (with `dir_path` when `--debug`). With **`--registry`**, append **`reg_path`**, **`reg_updated`**, **`reg_sources`** — **§5.1** table. Metric definitions: **CCSchema** §7, **CodexSchema** §6, **CursorSchema** §5. Rows with **`path=(global)`** are unscoped Cursor central-DB scan aggregates. Project ingest imports only global composers whose header workspace maps to that project.

### 5.2 `codess ingest`

| Flag | ENV | Default | Explanation |
|------|-----|---------|-------------|
| `--dirs` / `--dir` | — | **`get_project_root()`** | Same merge as scan (§4.2); empty list → git root or cwd. |
| `--source` | — | **`all`** | `cc` \| `codex` \| `cursor` \| `all`. |
| `--min-size BYTES` | `CODESS_MIN_SIZE` | **`20480`** | Skip sources smaller than N bytes. |
| `--force` | `CODESS_FORCE` | **`FORCE`** from ENV if flag omitted | **`args.force or FORCE`**; argparse **`default=False`**. Ignores **`ingest_state.json`** mtime skips when true. |
| `--redact` | `CODESS_REDACT` | off | **`args.redact or INGEST_REDACT`**; patterns in **`config.REDACT_PATTERNS`**. |
| `--debug` | `CODESS_DEBUG` | **`DEBUG`** from ENV | **`args.debug or DEBUG`** — see **§4.3**. |
| `--registry PATH` | `CODESS_REGISTRY` | **`~/.codess`** | Central registry dir (`ingested_projects.json`). **`PATH`** overrides default. |

### 5.3 `codess query`

| Flag | ENV | Default | Explanation |
|------|-----|---------|-------------|
| `--dirs` / `--dir` | — | **`get_project_root()`** | Same merge as §4.2; empty → git root or cwd. |
| *(multiple roots)* | — | aggregated | Sessions are globally ordered across selected projects. Roots without stores warn and contribute zero; all roots without stores exit 1. |
| *(multiple vendor DBs)* | — | aggregated | Every existing legacy or per-vendor store returned by `get_project_stores` participates in one logical report. |
| `--limit N` | — | unlimited | Globally limit rows after deterministic cross-project/vendor ordering for `--sessions`, `--permissions`, `--lineage`, and `--audit`. `0` emits no rows; negative values fail before stores are opened. |

**Modes:** **`--stats`**, **`--sessions`**, **`--tool`**, **`-sess`**,
**`--show`**, **`--permissions`**, **`--task-review`**, **`--lineage`**,
**`--audit`**, and **`--taxonomy`**. Session numbers form one global recency order with
deterministic project/source/id tie-breakers; duplicate original IDs remain
distinct internally. Session rows include release and concise
origin/storage/parent details. **`--lineage`** joins Claude tool-use ids and
Codex call ids to results, and reports missing, orphaned, unlinked, or denied
outcomes. **`--stats`** prints aggregate totals and merges each project's own
counts into **`ingested_projects.json`**. **`--audit`** reports only the
evidence-backed contract in **CoSchema.md**; unsupported vendor/state pairs are
not inferred. Omitting all mode flags exits 1.

### 5.4 `--dirs` File Format

- **`--dirs` file:** one path per line; **`#`** starts a comment; if **`--dirs`** is passed, the file **must** have ≥1 path line — **§4.2**.
- Paths are validated directories and act as exact project roots or scan path filters; they are not recursively expanded.

### 5.5 Filter Wiring

Vendor-specific **meaning** of timestamps, sidechains, and sizes lives in **\*Schema.md** — this file only ties **which knob** hits **which code**.

- **Recent sessions:** `scan.py` with **`--days`** / **`CODESS_DAYS`**; timestamp semantics per vendor schema.
- **CC sidechains:** `scan.py` with **`--subagent`** / **`CODESS_SUBAGENT`**; detail in **CCSchema**.
- **Min source size:** ingest with **`--min-size`** / **`CODESS_MIN_SIZE`**; bytes on **source** files before parse.

### 5.6 Operational quick check

`python -m main scan --dir . --out -`

**Batch errors:** By default, **scan** (per work root) and **ingest** (per file /
DB / project) log failures and continue; exit code 1 if any source failed. Scan
summarizes **`malformed`**, **`invalid_keys`**, **`failed_sources`**, and
**`failed_roots`**. Ingest summarizes **`malformed`**, **`ignored`**,
**`empty_sources`**, and **`failed_sources`**; the first three are nonfatal.
**`--stop`** or **`CODESS_STOP`** makes source failures fail fast.

Further CLI semantics → **Improvement Backlog**.

---

## 6. Feature → Implementation Map

**Purpose:** Index of **where** features live in code (not a second copy of **§3**).

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

---

## 7. Coding Techniques

**Audience:** People changing **`adapters/*`**, **`store.py`**, or **`cli/*_cmd.py`**.

Start from the **call graph in §3.1**: ingest normalizes and replaces one source
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

**Refactor candidates:** **`_ingest_codex`** and **`_ingest_cc`** share
**stat → should_ingest → normalize → replace → commit → state** and could share
one internal helper. Scan CSV row building remains duplicated for path/stdout.

---

## 8. Tests

This section sits **after** coding practices (**§7**) because tests validate
the implementation described above. Add backlog rows only for a specific
uncovered contract or reproduced defect; generic calls for “more tests” are not
work items.

**Goals:** Regressions in CLI, metric math, adapters, and store — without relying on a real **`~/.claude`** tree.

**Approach:** **Unit** tests use **`tmp_path`**, fake JSONL, temp SQLite. **CLI** tests use **`subprocess`** **`python -m main …`** with **`CODESS_*`** aimed at temp dirs. **Integration** flows live in **`test_integration.py`**. Prefer **temp env** per child process; do not mutate the developer’s home directory in tests.

**Module ↔ test file** — order follows **`src/codess/`** then CLI-focused tests:

- **`test_config.py`** — **`config`**, **`build_*_run_options`** in **`project`**
- **`test_helpers.py`** — **`helpers`**
- **`test_project.py`** — **`project`** paths and roots
- **`test_store.py`** — **`store`**, **`schema/coschema/sqlite/schema.sql`**
- **`test_scan.py`**, **`test_candidate.py`**, **`test_subagent_detail.py`** — **`scan`**, scan CLI subprocess
- **`test_registry_store.py`** — **`registry_store`** merges
- **`test_*_adapter.py`** — **`adapters/*`**
- **`test_sanitize.py`** — **`sanitize`**
- **`test_cli.py`**, **`test_integration.py`** — **`cli/*`**, **`parse_and_run`**, replacement and end-to-end
- **`test_scale.py`** — bounded Cursor header/prefix-query and Codex active/archive scale checks

**Coverage emphasis:** **`parse_dir_list`** and **`--dirs`**, scan CSV shape, adapter edge cases, and configuration validation.

**When adding a feature:** extend tests in the **same PR**.

---

## 9. Delivery Sequence

Order work by risk and dependency.

| Order | Outcome | Main work |
|---|---|---|
| **1. CoSchema v2 foundation — complete** | Versioned contract, mappings, DDL, strict readers/writers, raw capture, snapshots, diagnostics, and initial mixed queries | Maintain package hashes, fixtures, and compatibility-gate tests |
| **2. Automated baseline gate — complete** | Per-project policies make package, raw, SQLite, mapping, fixed-point, and query acceptance repeatable | Maintain `tools/validate_snapshot.py`, `tools/apply_and_verify.py`, and `catalog/policies/` |
| **3. Compatibility corpus — complete with recorded gaps** | The bounded Claude/Codex/Cursor corpus proves represented mappings and distinguishes real from fixture-only evidence | Maintain `CompatibilityReview.md` and add candidates only for demonstrated gaps |
| **4. Reviewed v2 baseline — complete** | The sampled corpus is frozen by package, snapshot, semantic digest, policy, and raw-evidence state | Run `tools/verify_reviewed_baselines.py`; replace the set rather than editing it in place |
| **5. Compatibility maintenance** | Vendor drift is detected early | Refresh the smallest real-shape fixture when an upstream format changes; rebuild rather than mutate derived data |
| **6. Postponed work** | Speculative surfaces stay out of the active queue | Restart preflight, machine output, or PII scanning only on the triggers in §11.2 |

Keep **`schema/coschema/sqlite/schema.sql`** aligned with **CoSchema.md** whenever normalized event shapes change.

---

## 10. Implementation Gaps

Vendor-specific **known holes** are documented in schema files, not duplicated here.

- **CC slug / path ambiguity** — **CCSchema.md** §8–§9.
- **Cursor event and scan time range** — **CursorSchema.md** §3, §5, and §7.

---

## 11. Improvement Backlog

**Immediate order:** protect locally held evidence before widening mappings.

1. Design and approve the stable project catalog and durable baseline location;
   project-local `.codess/` cannot survive checkout deletion.
2. Add stable project/location/workspace bindings and persist the implemented
   global session/observation identities in the next approved CoSchema package.
3. Approve or revise the proposed typed source/content/processing relations in
   `ContentProcessing.md`; keep the current DDL unchanged until then.
4. Implement a retire/relocate command or checklist that captures/seals raw
   Claude, Codex, and Cursor evidence, validates twice, registers the new
   location, and verifies historical reads before deletion.
5. Rebuild the bounded reviewed set under the current package and replace the
   frozen reviewed/approved catalogs atomically; never edit their old snapshot
   identities in place.
6. Decide whether the nested Cursor `Spank/Logs/spLogs` workspace is a child
   project or a second workspace binding under `Spank/Logs`; do not import it
   into a nested independent store meanwhile.
   Then correlate observed external artifact URIs to known catalog roots and
   run the bounded Codex parent-session investigation in §11.1.
7. Keep Cursor tool mapping, exact model settings, and further corpus expansion
   evidence-triggered. Current sampled Cursor data supplies no tool results.

The content preflight, machine-readable output, and enterprise PII scanner in
§11.2 remain intentionally postponed.

For each item: settle any product contract, change code and schema docs together,
then add representative tests in the same change set.

Work items stay grouped by theme below. **Codess.md §4.0** requires **all** tickets to live here or in **§8** / **§14** / **§15** as specified there.

### 11.0 CoSchema v2 corpus review — complete with known gaps

The automated gate, semantic sampling, coverage matrix, hazard/golden fixtures,
home-independent three-vendor CI policy, retained-snapshot read boundary, and
frozen reviewed set are implemented. See `CompatibilityReview.md` and
`catalog/reviewed-baselines.json`. Review corrected Claude failure/denial tool
actors and statuses, removed Cursor whitespace-only non-message envelopes,
deduplicated stable Cursor server-bubble identities within each composer, and
separated external file URIs from project-relative artifacts. All three
projects were rebuilt and accepted at a semantic fixed point afterward.

Remaining evidence gaps are deliberately narrow: a real modern Cursor tool
call/result shape, a real same-artifact multi-vendor project, lifecycle/missing
time shapes outside fixtures, and explicit exact model settings. These do not
justify broad project discovery. Add a candidate or mapping only when one of
those source shapes is observed.

Next maintenance actions:

1. Match external artifact `file:` URIs against known local catalog roots using
   longest-root containment; emit evidence/confidence rather than changing the
   session project or asserting authorship.
2. Execute §11.1.
3. Monitor Cursor format changes or newly active candidates for explicit tool
   invocation/result identity and status. Do not map the current empty
   `toolResults` arrays or `subagentSpawnTaskToolCallId` as tool outcomes.
4. Keep real same-artifact and exact model-setting additions
   evidence-triggered.

### 11.1 Codex parent-session evidence — next

Current verified Codex `session_meta` data has no parent id. Investigate without
changing normalized data until all acceptance checks pass:

1. Read only `session_meta` keys from a bounded sample spanning active and
   archived roots and at least two CLI releases; record field frequencies, not
   prompt/reasoning bodies.
2. List candidate direct fields such as `parent_session_id`, `parent_id`, or an
   explicit thread/fork reference. Timestamps, cwd, filenames, and content
   similarity are not candidates.
3. For each candidate, verify that child values resolve to an actual session id
   and remain stable when the same session appears in active and archived roots.
4. Add minimal parent/child and orphan fixtures from each supported shape.
5. Only then retain `parent_session_id` in bounded session metadata, display it
   through existing session details, and test active/archive deduplication plus
   missing-parent behavior.

**Exit rule:** if no direct referential identifier appears across the sample,
document Codex parentage as unsupported and stop. Reopen only when an upstream
record supplies such an identifier.

### 11.2 Postponed work

| Item | Status | Restart trigger | Contract if restarted |
|------|--------|-----------------|-----------------------|
| **`ingest --validate` preflight** | Postponed | A named operator workflow needs to answer “what would ingest change?” before mutation | Parse selected sources and report planned counts/diagnostics without creating or modifying `.codess`, ingest state, or registry. |
| **Machine-readable query rows** | Postponed | A named automation consumer accepts a versioned row schema | Prefer JSON Lines, preserve tabular default, and verify exact parity with `--limit` output. |
| **Enterprise PII/secret scanner** | Postponed | A deployment threat model shows configured regex redaction is insufficient | Choose scanner, false-positive policy, and storage/output boundaries before adding a dependency. |

### 11.3 Platform

| Choice | Decision |
|--------|----------|
| Store | SQLite |
| Current location | `<project>/.codess/`; this is disposable derived state plus retained baselines, but is vulnerable to project-directory deletion |
| Recommended durable location | `~/.codess/projects/<stable-project-id>/`; approval and a rebuild-boundary implementation are pending |
| Raw source objects | `~/.codess/raw/codess.raw-1/`; use `capture` or `seal` before any source/project retirement |
| Project-local role after relocation | Cache plus project/location/workspace binding, not the sole retained baseline |

### 11.4 Content and sanitize policy

The policy separates normalized storage from output formatting. Vendor text may
contain Markdown, HTML-like tags, source code, or SQL. Codess preserves those
strings as content; it does not guess that markup is executable or strip it.

| Surface | Current contract |
|---------|------------------|
| Ingested text | Normalize CR/LF, remove ANSI escapes and C0/C1 terminal controls except tab/newline, then apply optional configured regex redaction. |
| Claude tool input | Apply the same policy recursively to retained JSON-like values before serialization. |
| Raw source evidence | Never embed raw records in normalized SQLite. `--raw-mode` records no retention, a reference, a content-addressed exact capture, or a sealed snapshot; redacted derivatives are distinct objects. |
| Multi-line query display | Preserve useful line breaks in prompts/responses; sanitize and bound individual tool-result and tool-input displays. |
| Tabular terminal output | Remove controls and replace tabs/newlines with spaces so a stored value cannot add rows or columns. |
| CSV | Use Python's `csv.writer` for quoting/newlines and prefix risky **string** cells with a tab when the first character could trigger a spreadsheet formula (`= + - @`, full-width variants, tab, CR, or LF). Numeric values retain their type. |

The CSV prefix changes the exported string intentionally for human spreadsheet
safety; consumers needing lossless normalized values should query SQLite.
The implementation follows the threat categories in
[OWASP CSV Injection](https://owasp.org/www-community/attacks/CSV_Injection)
and the serialization behavior in the
[Python `csv` documentation](https://docs.python.org/3/library/csv.html).

Enterprise PII/secret scanning is postponed under **§11.2**. Configured regex
redaction remains the baseline until a deployment threat model provides a
restart trigger.

### 11.5 Testing and validation work

**Contract:** **Scan `--source`** invalid tokens and **ingest `--source`** invalid token are both **global** errors (**stderr + exit 1** for that invocation) — not per-root or per-session partial apply (**§14**).

Current regression coverage includes numeric/day validation, global source
validation, registry corruption/empty/filter behavior, registry merges,
missing/empty/all-invalid directory lists, environment boolean parsing,
symlink-root resolution, and Cursor header-time coverage. Add new rows here only
for a specific uncovered contract or reproduced defect.

### 11.6 Optional query companion

| Item | Notes |
|------|--------|
| Optional **`queries.sql`** companion | Add only when repeated external consumers need a stable SQL library; current version-aware reads remain in `query_cmd`. |

---

## 12. Change Routing

Use **Codess.md §4.0** for documentation rules. Code changes follow these
artifact boundaries:

- Vendor format change → ***Schema.md** first → adapters → tests.
- New CLI flag → **`codess/project.py`** (`build_parser`), **`_*_cmd.py`**, **§5** here, **Codess.md** if user-visible.
- New DB column → **CoSchema.md** + **`schema/coschema/sqlite/schema.sql`** + **`store.py`**.

---

## 13. Optional Splits

If this guide becomes hard to navigate, split the CLI contract into
**`CoPlan-cli.md`** and keep **Codess.md §4** pointers current.

---

## 14. Decisions

Implemented decisions state the current contract. Open decisions include
context, viable options, and a recommendation when one is available.

### 14.1 Current decisions

| Topic | Current decision | Implementation / owner |
|---|---|---|
| Scan source validation | Unknown `--source` tokens fail the invocation with stderr and exit 1. | `validate_scan_source_for_cli`, `scan_cmd`, §5.1, §11.5 |
| Central registry | Scan always upserts index metrics. Explicit `--registry PATH` also filters output to paths already present and adds `reg_*` columns. Ingest merges sources; query stats merges query data. | `registry_store`, command modules, registry tests |
| Query SQL | Keep version-aware SQL embedded in `query_cmd` until repeated external consumers justify a stable companion library. | §11.6 |
| Global Cursor ingest | Import only composers whose `composerHeaders.workspaceId` maps to the selected project. Preserve archived and subagent flags as metadata. Exclude unmapped composers. | Cursor adapter, project helpers, ingest integration tests |
| Cursor scan timestamps | Use header timestamps and report header/time coverage in debug output. Do not decode large bubble payloads during index-led scan merely to fill missing dates. | Cursor adapter, scan debug output, CursorSchema §5–§7 |
| Discovery | Keep scan index-led. `--dir` / `--dirs` are path filters, not traversal requests; there is no recursion CLI. | `scan`, root resolution, §3.0–§3.3 |
| Query aggregation | Open each store read-only; merge report rows in Python. Session numbering is globally recency-ordered; stats are aggregate on stdout and project-local in the registry. | `query_cmd`, CLI aggregation tests |
| Tool lineage | Join Claude tool-use ids and Codex call ids in a read-only report; retain unlinked Cursor results explicitly instead of guessing a call. | `query --lineage`, adapter metadata, CLI tests |
| Source replacement | A changed or forced Claude/Codex transcript replaces its normalized session atomically; a Cursor database refresh replaces only events owned by that database. | `store`, ingest adapters, replacement tests |
| Empty sources | A valid empty transcript removes its stale normalized session and records a nonfatal `empty_sources` diagnostic. | `ingest_cmd`, replacement tests |
| Codex duplicate sources | When the same session exists in active and archived trees, ingest one canonical source rather than duplicating the session. | Codex discovery/ingest tests |
| Report formats | Human-readable tabular output remains the default. Machine-readable output is not a contract until a consumer and stable row schema are defined. | §11.2 |
| Audit events | Normalize only direct evidence in the CoSchema support matrix. Claude supplies explicit denials/failures and compact boundaries; Codex supplies failed call status and turn aborts; current Cursor shapes supply none. | adapters, `query --audit`, vendor fixtures |
| Query row limit | Apply `--limit` after deterministic global ordering for sessions, permissions, lineage, and audit reports. Zero emits no rows; negative values fail before store access. | `query_cmd`, CLI tests |

### 14.2 Open decisions

The reviewed corpus is accepted and frozen. Active evidence decisions are a
modern Cursor tool shape, external-artifact/project correlation, and Codex
parent-session support (**§11.0–§11.1**). Preflight validation,
machine-readable output, and enterprise PII scanning are postponed with
explicit restart triggers in **§11.2**.

---

## 15. Consolidated engineering gaps (discussion brief)

**Purpose:** **§15** is for **review and prioritization**, not ticket duplication. Each theme below should be read with **open questions**, **recommendation**, and **justification**; **§11** holds the actionable rows and dependencies.

| Theme | Open questions | Recommendation (lean) | Justification |
|-------|----------------|----------------------|---------------|
| **Compatibility maintenance** | Does current evidence supply Cursor tool identity/status, catalog-resolvable external artifacts, or a real cross-vendor artifact? | Add only the bounded source shape or correlation asserted by evidence; then replace the reviewed set after fixed-point validation. | Keeps the accepted corpus useful without turning historical discovery into the critical path. |
| **Codex parentage** | Does a modern transcript expose a direct, referential parent-session id across releases and active/archive storage? | Run the bounded §11.1 inventory; implement only if every acceptance check passes. | Prevents plausible-looking but false parent links based on time, path, or content. |
| **Postponed surfaces** | Has a named operator, automation consumer, or deployment threat model triggered validation, JSON Lines, or PII scanning? | Keep all three postponed until their documented trigger exists. | Avoids speculative CLI/schema/dependency commitments. |
