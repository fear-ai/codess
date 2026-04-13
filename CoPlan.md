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
| [§8](#8-testing-strategy) | Testing Strategy |
| [§9](#9-delivery-phases) | Delivery Phases |
| [§10](#10-implementation-gaps) | Implementation Gaps |
| [§11](#11-improvement-backlog) | Improvement Backlog |
| [§12](#12-documentation-and-change-rules) | Documentation and Change Rules |
| [§13](#13-optional-splits) | Optional Splits |
| [§14](#14-open-questions-and-resolved-decisions) | Open Questions + Resolved Decisions |
| [§15](#15-consolidated-engineering-gaps-discussion-brief) | Consolidated Engineering Gaps (discussion) |

### Scope

Repository tree; architecture (call graph, data pipelines, persistence); configuration (what, why, how); CLI contract (flags, ENV, defaults); feature → module index; coding practices; test strategy; delivery phases; backlog, status, and review queue.

### Not Here

Vendor paths, filenames, DB keys, or field values — **CCSchema.md**, **CodexSchema.md**, **CursorSchema.md**; normalized columns — **CoSchema.md**.

### Documentation Boundaries

Per **Codess.md §4.1** (verbatim):

| Topic | Document |
|-------|----------|
| Why the product exists; audience; this index | **Codess.md** |
| Repository layout, layers, data flows, configuration, **CLI tables**, coding, **§8 Tests**, **§3.5–§3.6** status and verified wiring, phases, backlog **§11**, open questions **§14**, gap themes **§15** | **CoPlan.md** |
| Claude Code paths, index, JSONL fields, scan metrics | **CCSchema.md** |
| Codex session files | **CodexSchema.md** |
| Cursor `state.vscdb` keys and values | **CursorSchema.md** |
| Our normalized `sessions` / `events` columns | **CoSchema.md** |
| Executable DDL | **sql/CoSchema.sql** |

Per **Codess.md §4.2**, the **CoPlan.md** row (verbatim):

| Document | Goal | Include | Exclude |
|----------|------|---------|---------|
| **CoPlan.md** | *How* the repo implements and validates behavior | Tree, layered architecture, persistence notes, **§3.5–§3.6** status and verified wiring, **§4 configuration**, **§5 CLI**, features→modules, coding, **§8 Tests**, phases, backlog **§11**, **§14–§15** | Vendor on-disk truth (→ *Schema.md) |

Cross-cutting doc rules (ToC, no transient links from core docs, etc.): **Codess.md §4.0**.

---

## 2. Repository Layout

**Terms:** **scan** = discover projects that have vendor session data; **walk** = filesystem tree traversal (library in **`walk.py`** — **no** `walk` CLI subcommand; `CMD` is only `scan` \| `ingest` \| `query` in **`build_parser()`**).

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
│   │   └── query_cmd.py    # run(): roots[0], store/SQL; --stats → registry merge
│   └── codess/
│       ├── config.py       # ENV → Path / int / bool; defaults; no other codess imports
│       ├── helpers.py      # parse_dir_list, validate_dirs_file, write_csv, is_excluded, slug/path … ; imports config
│       ├── registry_store.py  # ingested_projects.json merge (scan / ingest / query / future walk)
│       ├── walk.py         # walk_dirs(); imports helpers only; not imported by cli/ or scan.py in current code — tests + future traversal
│       ├── sanitize.py     # text cleanup + redact; imports config
│       ├── store.py        # SQLite, DDL path, upsert*, ingest state; no codess imports
│       ├── project.py      # argparse, parse_and_run, roots, run-options, git root, vendor path helpers; imports config only — no walk, no scan
│       ├── scan.py         # run_scan(); config, helpers, project, adapters.cursor.get_db_metrics
│       ├── adapters/
│       │   ├── cc.py
│       │   ├── codex.py
│       │   └── cursor.py   # process_* + get_db_metrics (used by scan for metrics)
│       └── sanitize.py     # text cleanup + optional redact; adapters only — listed once
└── tests/                  # order mirrors src/codess + cli; full map in §8 Tests
    ├── test_config.py
    ├── test_helpers.py
    ├── test_project.py
    ├── test_store.py
    ├── test_scan.py
    ├── test_registry_store.py
    ├── test_walk.py
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

### 3.0 Walk: Launch, Processing, and Role

Filesystem traversal is the **shared primitive** we want for any future “expand this root” or “find artifacts on disk” behavior: one place for **excludes**, **depth**, **time limits**, and **no symlink follow**, so scan, ingest, and batch paths do not fork different recursion rules.

**How `walk_dirs` runs:** Call **`codess.walk.walk_dirs(roots, …)`** from Python. It resolves existing directory roots, optionally runs **`os.walk`** per root (**topdown**, **`followlinks=False`**), filters child names with **`helpers.should_skip_recurse`** and **`.codessignore`**, applies **`MAX_DEPTH`** / **`MAX_TIME_MIN`** from **`walk.py`**, and **yields** resolved directory **`Path`s**. It depends on **`helpers`** only and does **not** import **`project`** or **`scan`**.

**How it is launched today:** It is **not** invoked from **`main`**, **`parse_and_run`**, or any **`cli/*_cmd`**. The only in-repo caller is **`tests/test_walk.py`**. So the **feature exists as library code** ahead of product wiring; index-led **scan** and direct **ingest** paths do not use it yet.

**Intended next uses:** Walk-first discovery, unified multi-root expansion, and honoring **`--norec`** once passed through to whatever command owns traversal — tracked in the Improvement Backlog.

### 3.1 Call Graph and Module Roles

- **`main.py`:** Prepends `src/` → `codess.project.main()` → `parse_and_run()` → **`cli.scan_cmd.run`** \| **`cli.ingest_cmd.run`** \| **`cli.query_cmd.run`**.
- **`codess.config`:** ENV and constants; used by **`project`**, **`scan`**, **`helpers`**, **`adapters/*`**, **`sanitize`**, CLI.
- **`codess.helpers`:** Roots/CSV/excludes/slug helpers; imports **`config`**. Used by **`scan`**, **`walk`**, and resolution paths.
- **`codess.walk`:** See **§3.0** for launch, processing, and current callers.
- **`codess.sanitize`:** Used by **`adapters/*`** for text cleanup and optional redact.
- **`codess.store`:** SQLite, DDL file, upsert, ingest state. **`ingest_cmd`** and **`query_cmd`** use it; **`scan`** does not write the store.
- **`codess.project`:** **`build_parser`**, **`parse_and_run`**, **`resolve_cli_roots`**, **`build_*_run_options`**, **`get_project_root`**, vendor path helpers. Imports **`config` only** — **no** **`walk`**, **no** **`scan`**.
- **`codess.scan`:** **`run_scan()`**; imports **`config`**, **`helpers`**, **`project`**, **`adapters.cursor.get_db_metrics`**.
- **`cli/*_cmd`:** Thin **`run(args) -> int`**: roots/options, then **`run_scan`** / **`_ingest_*`** / **`store.connect`**.

**Query vs ingest vs adapters:** Ingest parses sources and upserts into **`.codess/*.db`**. Query runs **read-only SQL** on those DBs only — **no** vendor files, **no** **`adapters/*`**, so “normalize once, read many” stays clear.

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

 codess.helpers ◄──── codess.walk.walk_dirs   ← not on CLI path yet

 ingest_cmd ──► codess.adapters.* ──► store.upsert* … , ingest_state JSON
```

**Dependency sketch:** **`adapters/*`** → **`config`**, **`sanitize`**; called from **`ingest_cmd`**, and **`get_db_metrics`** from **`scan.py`**. **`scan.py`** → **`config`**, **`helpers`**, **`project`**, **`adapters.cursor`**. **`walk.py`** → **`helpers`** only; **`test_walk`** today. **`project.py`** → **`config`** only; **`cli/*`**, **`scan.py`**. **`store.py`** → no codess imports; **`ingest_cmd`**, **`query_cmd`**.

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

**`walk` vs scan**

- **`resolve_cli_roots`** returns **roots**; it does **not** call **`walk_dirs`**.
- **`run_scan`** does **not** import **`walk.py`**. Discovery stays **index-led**.
- **`walk.walk_dirs`:** Implemented and tested; **no production caller** yet. Walk-first and unified traversal are backlog items.

**Backlog**

- **Walk-first:** Traverse trees under shared **`walk`** rules to find artifacts; not implemented.
- **Scan prune:** Stop descending after a hit rule; not implemented. Unlike **`canonicalize`**, which prefers **leaf** paths over parents.

**Other**

- **`_is_agg`:** One segment below **`work_root`** in **`AGGREGATORS`** → drop as aggregator parent, not a leaf project.
- **Scan vs ingest shape:** Scan = one CSV row, **multiple** vendors possible. Ingest = **`_ingest_cc` / `_ingest_codex` / `_ingest_cursor`** per vendor, one **`--source`** selection — shared project loop, **separate** DB files and parsers.

**Long-term:** One validated **project list** from scan for ingest/query — see consolidated gap themes at end of this document.

#### Ingest

- **Purpose:** Project root → **`.codess/`** normalized **sessions** / **events**.
- **Mechanism:** **`project`** path resolution → **`adapters/*`** streams → **`store.upsert_*`** → **`ingest_state.json`** mtime keys.

#### Query

- **Purpose:** Read-only reporting on the local store.
- **Mechanism:** Open **`.codess/*.db`** — see **§3.4**. **`query_cmd`** does not write vendor trees.

### 3.4 Persistence Layout

*Layout is provisional.*

Under each **project directory**, **`STORE_DIR`** (`.codess/`) holds:

- **Per-vendor DB files** (`sessions_cc.db`, `sessions_codex.db`, `sessions_cursor.db`) and/or **legacy** `sessions.db` — **`get_store_path`**, **CoSchema.md**.

**Intent:** Split DBs reduce coupling while adapters differ. A merged DB would require coordinated **`store`**, **CoSchema**, and **test** changes.

**`ingest_state.json`:** Per-project mtimes for incremental ingest.

### 3.5 Implementation vs Validation

Last full run: **212** tests passed — re-run **`pytest tests/`** after substantive changes. **Validated** here means representative automated coverage, not every edge case.

| Area | Implemented | Validated | Gaps |
|------|-------------|-----------|------|
| Scan (index-led) | Yes | CLI + `test_scan*`, metrics | **`--norec`** / **`CODESS_NOREC`** merged into **`ScanRunOptions`** but **`scan_cmd` never reads `opts.norec`** and **`run_scan`** has no such parameter; root existence unchecked |
| Ingest | Yes | Adapters, `test_integration`, CLI | `validate_config` scan-only; partial-failure semantics thin; nested CC — **CCSchema** |
| Query | Yes | CLI, store | **`roots[0]`** only; mode UX |
| **`walk.walk_dirs`** | Yes | `test_walk` | No production caller; not unified with scan/ingest |
| **`validate_config()`** | Yes | `test_config` default | Bad env ranges under-tested; not on ingest/query |
| Store / DDL | Yes | `test_store` | — |
| Sanitize | Yes | `test_sanitize` | Policy gaps — Content and Sanitize Policy in Improvement Backlog |

**Completeness:** Main workflows work; depth, validation, Cursor, query polish, walk integration remain **incomplete** — see **§15 Consolidated Engineering Gaps**.

### 3.6 Verified wiring

Cross-checked against **`src/`** and **`tests/`** so this plan does not drift from the repo. Re-audit after large refactors.

- **`main.py`:** prepends **`src/`**, calls **`codess.project.main()`** → **`parse_and_run()`**.
- **Dispatch:** **`parse_and_run`** lazy-imports **`cli.scan_cmd` / `cli.ingest_cmd` / `cli.query_cmd`** then branches on **`args.command`**.
- **`run_scan(work_root, …)`:** parameters are **`vendor_filter`**, **`recent_days`**, **`debug`**, **`subagent`** only — **no** **`norec`**.
- **`scan_cmd`:** builds **`opts`** via **`build_scan_run_options`** but **never references `opts.norec`**; calls **`run_scan`** without recursion flags.
- **`validate_config()`:** invoked only from **`scan_cmd.run`** (stderr messages; non-fatal).
- **`query_cmd`:** resolves **`roots`** then uses **`roots[0]`** only; imports **`store`** + **`get_project_stores`**, **no** **`adapters/*`**.
- **`walk_dirs`:** **no** caller under **`src/`**; **`tests/test_walk.py`** only.
- **`scan.py`:** imports **`adapters.cursor.get_db_metrics`**; **does not** import **`walk`**.
- **`project.py` module imports:** **`codess.config`** only at top level for the public CLI surface.
- **`adapters/*`:** **no** imports of **`scan`**, **`scan_cmd`**, or **`ingest_cmd`**.
- **Central registry (`ingested_projects.json`):** **`codess.registry_store`** merges per-project records. **Scan** always upserts **`scan`** / **`last_scan`** for every discovered project path into **`resolve_registry_directory(args)`** (default **`CODESS_REGISTRY`**). **`--registry PATH`** overrides that root and, when set, **also** filters CSV to paths present in the file **before** this run + appends **`reg_*`** columns — **no** sidecar. **Ingest** merges **`sources`** / **`last_ingestion`**. **Query `--stats`** merges **`query`** / **`last_query`** into the same file (**§5**).
- **`validate_scan_source_for_cli` / scan `--source`:** invalid tokens → **stderr + exit 1** before any scan work (**global** invocation policy — **§11.6**, **§14**).
- **`store.init_db`:** executes **`sql/CoSchema.sql`** when that file exists (path resolved from **`store.py`** location).

---

## 4. Configuration

### 4.1 What Is Configurable, Why, and How

**What:** (1) **Locations** of vendor data on this machine (`CODESS_CC_PROJECTS`, …). (2) **Behavior defaults**: scan window (`CODESS_DAYS`), min ingest size (`CODESS_MIN_SIZE`), CC sidechain counts (`CODESS_SUBAGENT`), debug/redact/force/stop/verbose/norec flags (`CODESS_*` — see §4.3). (3) **Output/registry**: `CODESS_REGISTRY` for central **`ingested_projects.json`**. (4) **Walk exclusions** and truncation limits are **code constants** in **`config.py`** (not ENV) unless noted.

**Why:** Same codebase runs on **different OS paths**, **CI sandboxes**, and **user preferences** without editing Python.

**How:** **`config.py`** reads **environment variables at import time** into module-level `Path` / `int` / `bool`. **CLI** arguments are defined in **`codess.project.build_parser()`** and parsed by **`parse_and_run()`**; they may **override** scan/ingest behavior per invocation (e.g. `--days` overrides default recent window). **Precedence:** where a flag exists (e.g. `--days`, `--min-size`), it **wins** for that run; otherwise **ENV** default from **`config`** applies.

**`CODESS_MIN_SIZE` / `--min-size`:** Ingest skips a source file when **`st_size < min_size`**. **`min_size == 0`** means **no size floor** (every non-empty file passes the size check). That is **not** the same as omitting **`--min-size`**: omission uses the **`config.MIN_SIZE`** default (20 KiB unless overridden by **`CODESS_MIN_SIZE`** at import). **`validate_config`** rejects **`MIN_SIZE < 0`** only.

**`CODESS_CC_PROJECTS` must be absolute:** **`validate_config()`** requires **`CC_PROJECTS.is_absolute()`**. A relative path would be resolved from the **process cwd at import time**, which is fragile for scan/CI/daemons and can silently point at the wrong tree. Other vendor roots are also normalized to **`Path`**; treat **absolute** CC projects as the supported contract.

**`main.py` vs commands:** **`main.py`** only extends **`sys.path`** and calls **`codess.project.main()`**. **`project.build_parser()`** defines **one** **`ArgumentParser`** (no subparsers): positional **`CMD`** ∈ {**`scan`**, **`ingest`**, **`query`**} plus **all** flags. **`parse_and_run()`** parses **once**, sets logging from **`-v` / `CODESS_VERBOSE`**, then dispatches to **`scan_cmd.run` / `ingest_cmd.run` / `query_cmd.run`**. Unused flags for a given CMD are simply ignored by that command’s implementation.

**Options object (`project.py`):** ENV is **not** re-read on each line of a loop — it is read **once at import** in **`config`**. **`build_scan_run_options(args)`** / **`build_ingest_run_options(args)`** merge **`Namespace` + `config` once per invocation** into a small **frozen dataclass**; **`scan_cmd`** / **`ingest_cmd`** pass **only** the fields they need into **`run_scan`** / **`_ingest_*`**. **Query** can gain the same pattern when it grows ENV-backed toggles.

**Why global args/ENV, not per-vendor sections:**

- **Vendor-specific *paths* already exist:** `CODESS_CC_PROJECTS`, `CODESS_CODEX_SESSIONS`, `CODESS_CURSOR_DATA` — each points at that tool’s install layout on this machine.
- **Behavior knobs are intentionally *run-wide*:** One **`scan`** / **`ingest`** applies a **single policy** to every vendor selected by **`--source`** (`CODESS_DAYS`, `CODESS_MIN_SIZE`, `CODESS_DEBUG`, `CODESS_FORCE`, …). That keeps **one argv surface**, **one import-time config**, and shared loops in **`scan_cmd` / `ingest_cmd`** without a combinatorial matrix (`--min-size-cc`, `CODESS_DEBUG_CODEX`, …).
- **Vendor-only semantics** stay in **code + Schema**, not parallel ENV trees: e.g. **`CODESS_SUBAGENT`** affects **CC** scan metrics only; Cursor/Codex ignore it. Per-vendor *behavior* differences that need toggles belong in ***Schema.md** + adapter options first; new **`CODESS_*`** or flags would follow a proven need.

### 4.2 Combining `--dir` and `--dirs`

1. If **`--dirs FILE`** is passed, **`helpers.validate_dirs_file`** runs first: file **must exist**, be a **regular file**, be **readable**, and contain **≥1** non-comment path line — otherwise **stderr** message and **exit 1** (scan / ingest / query).
2. **`helpers.parse_dir_list(dirs_file, dir_args)`** builds **one ordered list** of **resolved** `Path`s.
3. If **`--dirs FILE`** validated, lines are read **first** (in file order).
4. Each **`--dir PATH`** is **appended** in argv order.
5. **Duplicates** (same resolved path) are **skipped**.
6. **User root strings** (`--dir` lines, **`--dirs`** file): **`..`** in any path **component** is **disallowed** (skipped + warning). **Relative** paths: any segment **starting with `.`** except the lone segments **`.`** and **`..`** is **disallowed** — this blocks **hidden-style** relative segments (e.g. **`.venv`**, **`.private`**) while still allowing **`.`** (cwd) and paths like **`./repo`** (the **`.`** segment is explicitly allowed). **Absolute** paths may contain segments such as **`.config`** under the home tree. **Empty** lines / empty **`--dir`** arguments are skipped. **Future — name-prefix roots only (not implemented; not general globs):** only the **final** segment of a root string may end with **`*`**. The characters before **`*`** are a **literal prefix** for matching **one** filesystem component’s **name** (e.g. **`.../lib*`** expands to siblings whose **basename** starts with **`lib`**: **`lib`**, **`libs`**, …). **No** infix **`*`**, **no** `**`, **no** multi-segment pattern — it is **trailing-asterisk on the last segment** = **directory/file name prefix match**, sometimes called a **prefix glob** on that segment only. When that ships, re-check **`..`** / hidden rules **after** expansion so expansion cannot escape the intended root.
7. **Walk recursion** (inside **`walk.walk_dirs`**): **any child directory name starting with `.`** is skipped (**`should_skip_recurse`**), independent of the root path rules above — covers **`.git`**, **`.venv`**, etc.
8. If the result is **empty**: **`scan_cmd`** uses **`Path.cwd()`**; **`ingest_cmd`** and **`query_cmd`** use **`get_project_root()`** (`git rev-parse --show-toplevel` from cwd, else cwd — see **`project.py`**).

**`DEFAULT_WORK` / `is_excluded`:** There is **no** CLI flag for **`DEFAULT_WORK`** (`~/Work`). **`is_excluded(p, work_root=None)`** uses **`DEFAULT_WORK`** only as the **`relative_to`** anchor when **`work_root`** is omitted — **`scan.run_scan`** passes the real **`work_root`** into **`canonicalize`**, so exclusion is relative to the **scan root**, not **`~/Work`** unless you omit the argument in other call sites.

### 4.3 Environment Variables

Defaults in the table are when the variable is **unset**.

| Variable | Role | Default (if unset) |
|----------|------|---------------------|
| `CODESS_CC_PROJECTS` | CC projects root | `~/.claude/projects` |
| `CODESS_CODEX_SESSIONS` | Codex sessions root | `~/.codex/sessions` |
| `CODESS_CURSOR_DATA` | Cursor User dir | OS-specific under `Cursor/User` (see `config._cursor_data`) |
| `CODESS_DAYS` | Scan default recent days | `90` |
| `CODESS_MIN_SIZE` | Ingest skip small sources (bytes) | `20480` |
| `CODESS_FORCE` | Ingest ignore mtime state | `0` → false (see **boolean ENV** below) |
| `CODESS_DEBUG` | Verbose / debug behaviors | `0` → false (see **boolean ENV** below) |
| `CODESS_REGISTRY` | Registry dir for stats JSON | `~/.codess` |
| `CODESS_SUBAGENT` | CC scan include sidechains | `0` → false (see **boolean ENV** below) |
| `CODESS_STOP` | Fail-fast: stop whole command on first error | `0` → false; combine with **`--stop`** |
| `CODESS_VERBOSE` | Python logging **DEBUG** for the process (`-v` equivalent) | `0` → false |
| `CODESS_NOREC` | Scan: merged into **`ScanRunOptions.norec`** via **`build_scan_run_options`**; **`scan_cmd` does not use the field**; **`run_scan`** has no matching parameter — **§3.6** | `0` → false |
| `CODESS_REDACT` | Ingest: enable redaction default (same patterns as **`--redact`**) | `0` → false |

**Boolean ENV (`CODESS_DEBUG`, `CODESS_FORCE`, `CODESS_SUBAGENT`, `CODESS_STOP`, `CODESS_VERBOSE`, `CODESS_NOREC`, `CODESS_REDACT`):** Implemented in **`config.py`** via **`env_bool()`**: **true** only if, after **`.lower()`**, the value is exactly **`1`**, **`true`**, or **`yes`**. **Unset** uses default **`0`** → false. Values like **`y`**, **`Y`**, **`on`**, **`2`** are **false** (not generic shell truthiness). Export e.g. `CODESS_DEBUG=1` or `CODESS_DEBUG=yes`.

**Why `CODESS_*` vs `DEBUG` / `FORCE` / `SUBAGENT`:** Shell and CI need **prefixed** names (`CODESS_DEBUG`, …) to avoid collisions with unrelated tools. **`config.py`** exposes short **Python** names (`DEBUG`, `FORCE`, `SUBAGENT`) as **bools read once at import** from those variables. Docs refer to **ENV** with the `CODESS_` name; code samples may show **`config.DEBUG`** meaning “the bool parsed from **`CODESS_DEBUG`**.”

**Boolean policy (flags + ENV):** Default is **false** unless the **CLI flag** is passed or the **`CODESS_*`** env parses **true** (see above). **`store_true`** flags: presence → **true**; omission → **false** at argparse, then OR with env where the table says so.

**Note on scan vs ingest `--debug`:** Both use **`CODESS_DEBUG` → `DEBUG`** via **`args.debug or DEBUG`**, but **effects differ**: **scan** uses it only for **discovery trace** + CSV shape; **ingest** uses it for **`source_raw`** / adapter verbosity. Same switch, different subsystems.

**CLI `store_true`:** There is **no** `-y` shorthand.

**Boolean and pseudo-boolean flags — by command**

- **Top-level `-v` / `--verbose`:** true when **`args.verbose or VERBOSE`** from **`CODESS_VERBOSE`**; **`parse_and_run`** sets **`logging.basicConfig(DEBUG)`**. Not the same as **`CODESS_DEBUG`** (vendor/session trace).
- **Scan `--debug`:** **`args.debug or DEBUG`**. **`--subagent`:** **`args.subagent or SUBAGENT`**. **`--norec`:** **`args.norec or NOREC`** in **`build_scan_run_options`** → **`ScanRunOptions.norec`**, but **`scan_cmd` never reads it** and **`run_scan`** has no **`norec`** argument — **§3.6**.
- **Ingest `--debug` / `--force` / `--redact`:** each **`args.* or`** matching **`CODESS_*`**; **`--force`** argparse default stays **`False`** so omission does not imply force.
- **Query:** mode flags only; **no** **`CODESS_*`** booleans for **`--stats`**, **`--tool`**, etc.

**Validation:** **`validate_config()`** (invoked from **`scan_cmd` only** today) checks **`CODESS_DAYS`** in **[1, 3650]**, **`MIN_SIZE` ≥ 0**, **`CC_PROJECTS`** absolute; violations → **stderr** messages (non-fatal). **Ingest** / **query** do not call it yet — **Ingest and Store** backlog rows.

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
| `--source cc,codex,cursor` | — | all three | Comma-separated vendor subset; **order does not matter**. Tokens are compared case-insensitively after trim. **`all`** clears the filter (same as omitting **`--source`**). **Invalid token** (anything other than **`cc`**, **`codex`**, **`cursor`**, or the whole value **`all`**) is a **global** error: **stderr** message listing bad tokens and **exit 1** — no partial vendor set (**§11.6**). |
| `--out PATH` | — | `codess_walk.csv` | CSV path; **`write_csv`** creates **parent directories**. |
| `--out -` | — | — | CSV to **stdout** (not **`write_csv`**). |
| `--norec` | `CODESS_NOREC` | off | Stored on **`ScanRunOptions`**; **`scan_cmd` ignores `opts.norec`**; **`run_scan`** has no parameter. **`walk_dirs`** is not used on the scan path — **§3.0**, **§3.6**, **§5.4**. |
| `--days N` | `CODESS_DAYS` | **`90`** | Recent window; omitted → **`CODESS_DAYS`**. |
| `--debug` | `CODESS_DEBUG` | off if flag omitted **and** unset ENV | Discovery trace + CSV **`dir_path`**; **`args.debug or DEBUG`** — see **§4.3**. |
| `--subagent` | `CODESS_SUBAGENT` | **`SUBAGENT`** from ENV | **`args.subagent or SUBAGENT`** — see **§4.3**. |
| `--registry PATH` | `CODESS_REGISTRY` | — | **Directory** for **`ingested_projects.json`**: default **`CODESS_REGISTRY`** (`~/.codess`); **`PATH`** overrides for this invocation. **Scan:** always **writes** merged index metrics to that directory; when **`--registry`** is **passed**, **also** restricts CSV to paths already listed **before** this run and adds **`reg_*`** columns. **Argparse requires a path** — no bare **`--registry`**. |
| `-v` / `--verbose` | `CODESS_VERBOSE` | off | Python **`logging`** level **DEBUG** (process-wide); not **`CODESS_DEBUG`**. |

**Precedence (scan):** **`--days` omitted** → **`CODESS_DAYS`**. **`--subagent`:** **`args.subagent or SUBAGENT`**. **`Registry`:** **`project.resolve_registry_directory(args)`** selects the registry **root** for **both** scan upserts and (when **`--registry PATH`** is set) filter + join columns. **Walk (`walk_dirs`):** not on the production path yet; **`registry_store.upsert_walk_seen`** exists for future wiring when walk lists projects (**§5.4**).

**Output columns:** `path,vendor,sess,mb,span_weeks` (with `dir_path` when `--debug`). With **`--registry`**, append **`reg_path`**, **`reg_updated`**, **`reg_sources`** — **§5.1** table. Metric definitions: **CCSchema** §7, **CodexSchema** §6, **CursorSchema** §6. Rows with **`path=(global)`** are **Cursor central DB** aggregates in scan output only — **ingest** / **query** stay project-root-centric until **CursorSchema** defines a first-class global project (**§14** Q3).

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
| *(multi-root)* | — | first only | **Only `roots[0]`** is queried; rest ignored until multi-query exists. |

**Modes:** **`--stats`**, **`--sessions`**, **`--tool`**, **`-sess`**, **`--show`**, **`--permissions`**, **`--task-review`**, **`--taxonomy`**, … — full list in **`python -m main query --help`**. **`--stats`** also **merges** session/event counts into **`ingested_projects.json`** at **`resolve_registry_directory(args)`** (same **`--registry PATH`** / **`CODESS_REGISTRY`** rule as ingest). **No other `CODESS_*`** wiring for query modes. Omitting all mode flags → **no report**, exit **1**.

### 5.4 `walk_dirs` and `--dirs` File Format

- **`--dirs` file:** one path per line; **`#`** starts a comment; if **`--dirs`** is passed, the file **must** have ≥1 path line — **§4.2**.
- **`walk.walk_dirs`:** When called, applies **`should_skip_recurse`**, **`.codessignore`**, **`MAX_DEPTH`**, **`MAX_TIME_MIN`**, no symlink follow — **`walk.py`**, **`config.EXCLUDE_RECURSE`**. **`cli/*`** and **`scan.py`** do **not** call it today — Improvement Backlog. When integrated, call **`registry_store.upsert_walk_seen`** with discovered project paths so the registry reflects walk output (**§11.1**).
- **`--norec`:** Intended: no directory descent where walk applies. **Today:** flag and **`CODESS_NOREC`** populate **`ScanRunOptions`** but **`scan_cmd` does not read them** — **§3.6**; Improvement Backlog.

### 5.5 Filter Wiring

Vendor-specific **meaning** of timestamps, sidechains, and sizes lives in **\*Schema.md** — this file only ties **which knob** hits **which code**.

- **Recent sessions:** `scan.py` with **`--days`** / **`CODESS_DAYS`**; timestamp semantics per vendor schema.
- **CC sidechains:** `scan.py` with **`--subagent`** / **`CODESS_SUBAGENT`**; detail in **CCSchema**.
- **Min source size:** ingest with **`--min-size`** / **`CODESS_MIN_SIZE`**; bytes on **source** files before parse.
- **`min_events` / duration filters:** not implemented — Improvement Backlog.

### 5.6 Operational quick check

`python -m main scan --dir . --out -`

**Batch errors:** By default, **scan** (per work root) and **ingest** (per file / DB / project) **log** failures and **continue**; exit code **1** if **any** part failed. **`--stop`** or **`CODESS_STOP`** → **fail-fast** (first error aborts the command).

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
| Incremental ingest | `store.should_ingest`, state JSON | mtime keys |
| Idempotent upsert | `store.upsert_*` | unique (session_id, event_id) |
| Redaction | `sanitize`, adapter opts | regex list in **config** |
| Walk safeguards | `walk.walk_dirs` | depth / time; **no** `cli` / `scan` caller — **§3.0** |
| Central registry JSON | **`registry_store`**, **`ingest_cmd._save_stats`**, **`scan_cmd`**, **`query_cmd._stats`**, **`config.get_stats_path`**, **`project.resolve_registry_directory`** | **`ingested_projects.json`** is a **merged** project registry: **scan** (index metrics), **ingest** (store **`sources`**), **query `--stats`** (counts), future **walk** (**`upsert_walk_seen`**). **`--registry PATH`** overrides **`CODESS_REGISTRY`**; **no** bare **`--registry`**. |

---

## 7. Coding Techniques

**Audience:** People changing **`adapters/*`**, **`store.py`**, or **`cli/*_cmd.py`**.

Start from the **call graph in §3.1**: ingest streams normalized events into **`store`**; query reads **`store`** only. The points below are **patterns**, not a style guide.

- **Streaming:** adapters **`yield`**; ingest commits per file or batch so large JSONL stays bounded in memory.
- **Cursor SQLite reads:** use read-only URI in the adapter so we do not take write locks on vendor DBs.
- **Errors:** log and skip bad lines where vendor format drifts; scan tolerates partial index reads. **Tradeoff:** operators may see partial data instead of a hard fail — validation backlog in **§15** themes.
- **Tolerant parsing:** **`JSONDecodeError`**, missing keys, odd lines → skip with **`try`**. **Pro:** resilient on real trees. **Con:** silent data loss risk; needs clearer surfaced warnings long-term.
- **CSV output:** **`helpers.write_csv`** for paths; **`scan_cmd`** writes stdout with **`csv.writer`** when **`--out -`** because stdout is not a path.
- **DDL:** only **`sql/CoSchema.sql`** via **`store.init_db()`** so schema is not duplicated in Python.

**Refactor candidates:** **`_ingest_codex`** and **`_ingest_cc`** share **stat → should_ingest → connect → stream → upsert → state**; could share one internal helper. **Query** might gain **`build_query_run_options`**. **Scan CSV** row building is duplicated for file vs stdout — small shared helper.

---

## 8. Tests

This section sits **after** coding practices (**§7**) because tests validate the implementation described above. **All** outstanding test work is also listed under **§11.6** so the Improvement Backlog stays the single queue.

**Goals:** Regressions in CLI, metric math, adapters, and store — without relying on a real **`~/.claude`** tree.

**Approach:** **Unit** tests use **`tmp_path`**, fake JSONL, temp SQLite. **CLI** tests use **`subprocess`** **`python -m main …`** with **`CODESS_*`** aimed at temp dirs. **Integration** flows live in **`test_integration.py`**. Prefer **temp env** per child process; do not mutate the developer’s home directory in tests.

**Module ↔ test file** — order follows **`src/codess/`** then CLI-focused tests:

- **`test_config.py`** — **`config`**, **`build_*_run_options`** in **`project`**
- **`test_helpers.py`** — **`helpers`**
- **`test_project.py`** — **`project`** paths and roots
- **`test_store.py`** — **`store`**, **`sql/CoSchema.sql`**
- **`test_scan.py`**, **`test_candidate.py`**, **`test_subagent_detail.py`** — **`scan`**, scan CLI subprocess
- **`test_registry_store.py`** — **`registry_store`** merges
- **`test_walk.py`** — **`walk`** (**only** caller of **`walk_dirs`** in repo today)
- **`test_*_adapter.py`** — **`adapters/*`**
- **`test_sanitize.py`** — **`sanitize`**
- **`test_cli.py`**, **`test_integration.py`** — **`cli/*`**, **`parse_and_run`**, end-to-end

**Coverage emphasis:** **`parse_dir_list`** and **`--dirs`**, scan CSV shape, walk depth/excludes, adapter edge cases, **`validate_config`** default path.

**When adding a feature:** extend tests in the **same PR**.

---

## 9. Delivery Phases

Phases are **historical ordering** and a **routing index** into **§11** / **§10** so nothing is “floating” without backlog rows.

| Phase | Scope | Tracked / owned in |
|-------|--------|---------------------|
| **1** | CC + Codex scan, ingest, store, CLI | **Largely complete**; regressions → **§8**, **§11** as filed |
| **2** | Walk, multi-root, walk-first, scan prune, **`norec` → `run_scan` / walk** | **§11.1** (all rows); **§3.0**, **§3.3** |
| **3** | Cursor adapter, global/workspace, scan timestamps | **§10**; **CursorSchema**; **§11.2** (Cursor timestamps); **§11.3** (`--no-central`); **§15** Cursor row |
| **4** | Query UX, optional **`queries.sql`**, multi-root query | **§11.7**; **§14** Q4; **§15** Query row; **§14.2** multi-root; **§11.3** **`validate_config`** where relevant |

**Notes:** **`scan --registry`** is **§14** Q2 (**done**) — **not** part of phase 2. Phase 2 is **discovery pipeline** only.

Keep **`sql/CoSchema.sql`** aligned with **CoSchema.md** as event shapes stabilize.

---

## 10. Implementation Gaps

Vendor-specific **known holes** are documented in schema files, not duplicated here.

- **CC slug / path ambiguity** — **CCSchema.md** §8–§9.
- **CC subagent ingest** — **CCSchema.md** §9.
- **Cursor global `project_path`** — **CursorSchema.md** §7–§8.1.
- **Cursor scan time range** — **CursorSchema.md** §8.1.

---

## 11. Improvement Backlog

**Execution order (recommended):** (1) **Spec / product** — close open themes in **§15** and schema docs where they gate behavior. (2) **Code** — implement with **§5** + parser updates in lockstep. (3) **Validation** — extend **§8** / **§11.6** in the same change set when behavior moves.

**Dependencies (high level):** **Walk-first / scan prune** depend on **§3.3** pipeline agreement and **`walk_dirs`** integration. **Nested CC / subagent ingest** depends on **CCSchema** + adapter contracts. **Content / sanitize policy** (**§11.5**) can proceed in parallel but should land before broad export/query hardening. **`validate_config` everywhere** is independent but touches all **`*_cmd`**.

Work items stay grouped by theme below. **Codess.md §4.0** requires **all** tickets to live here or in **§8** / **§14** / **§15** as specified there.

### 11.1 Scan / discovery and walk

| Item | P | Depends on | Notes |
|------|---|------------|--------|
| Validate roots exist | 1 | — | Missing **`--dir`** / path errors |
| Wire **`norec` → `run_scan` / walk** | 2 | Walk integration | **`§3.6`** — flag unused today |
| Walk-first discovery | 2 | **`walk_dirs` on CLI path** | Today index-led |
| Scan prune | 2 | Walk-first | Skip deeper traversal once hit rule — **§3.3** |
| CSV type tests | 2 | — | Partial coverage |

### 11.2 Filters, CLI, and vendors

| Item | P | Depends on | Notes |
|------|---|------------|--------|
| **`--days 0`** (all-time) | 1 | — | Scan window |
| Cursor timestamps in scan | 2 | **CursorSchema** | Aggregate bubbles / global row semantics |
| **Name-prefix roots** (final segment only: **`name*`** → basename **string-prefix** match; **§4.2**) | 3 | Spec + **`parse_dir_list`** | **Not** implemented; **not** general globs / infix **`*` |

### 11.3 Ingest and store

| Item | P | Depends on | Notes |
|------|---|------------|--------|
| Nested CC / subagent files | 2 | **CCSchema** | Ingest depth |
| **`--no-central`** | 2 | **CursorSchema** | Cursor paths |
| **`validate_config` everywhere** | 2 | — | Today scan-only |
| **`--validate`** dry run | 2 | — | Optional ingest |

### 11.4 Platform

| Choice | Decision |
|--------|----------|
| Store | SQLite |
| Location | `<project>/.codess/` |

### 11.5 Content and sanitize policy (research → spec → build)

**Purpose:** Separate **ingest storage** safety from **export / display** policy. **Today:** **`sanitize.py`** strips control chars (except tab/newline), ANSI, normalizes newlines; optional regex **redact** from **`config.REDACT_PATTERNS`**. **No** HTML strip; **no** SQL-display-specific rules.

**Research (online / prior art) — do before locking policy:**

- **Use case A — CSV / TSV export:** escaping, quoting, multiline fields, cell size limits; spreadsheet and SIEM ingest expectations.
- **Use case B — terminal / query human output:** wrapping, truncation, and whether to strip HTML-like tags from vendor payloads.
- **Use case C — retained archives:** what must never leave disk raw (secrets, tokens) vs what can stay lossless for forensics.

**Lift vs build (initial lean):**

| Area | Lift (deps) | Build (custom) |
|------|-------------|----------------|
| HTML-like tag stripping | Established HTML/text libs **if** we commit to HTML semantics | Thin tag-strip or vendor-specific rules **if** payloads are mostly markdown-like |
| Redaction | Regex lists (**today**) + optional dedicated PII scanners for enterprise | Codess-specific patterns and **adapter** hooks |
| CSV safety | **`csv` module** (**today**) + documented limits | Policy for max field length / row count |

**Spec outline:** (1) Threat model one-pager (who reads exports). (2) Normative table per **output surface** (ingest, query, CSV). (3) Test vectors in **§11.6**. (4) Implement in **`sanitize.py`** + **`query_cmd`** + docs.

**Backlog rows (unchanged intent):**

| Item | P | Notes |
|------|---|--------|
| HTML / SQL-like display | 2 | Policy + implementation after **§11.5** spec |
| Multiline / whitespace | 2 | Trim, internal newline limits |
| Docs + tests | 2 | Same PR as policy |

### 11.6 Testing and validation work

Concrete test and validation follow-ups. **`--min-size 0`** is already covered in **`test_cli`** / **`test_integration`**; add a **`build_ingest_run_options`** unit assert only if subprocess coverage is insufficient.

**Contract:** **Scan `--source`** invalid tokens and **ingest `--source`** invalid token are both **global** errors (**stderr + exit 1** for that invocation) — not per-root or per-session partial apply (**§14**).

- **`validate_config`** with monkeypatched bad **`CODESS_DAYS`** / **`CODESS_MIN_SIZE`**
- Subprocess **non-numeric `--days`**
- Ingest **invalid `--source`** — tighten stderr assertions
- **`scan --registry`** corrupt JSON, empty registry warning, path mismatch filter
- **`registry_store`** merge regressions — **`test_registry_store`**, **`test_cli.test_query_stats`**
- **`--dirs`** missing file, empty after validation, all-invalid lines
- **`--stop`** vs continue exit semantics
- **Query multi-root** “first only” contract documented in tests
- **`env_bool`** falsy strings (**`on`**, **`2`**, empty)
- Symlink roots; corrupt JSONL adapter resilience

### 11.7 Deferred until CoSchema.md revisit

| Item | Notes |
|------|--------|
| Optional **`queries.sql`** companion | **§14** — no file until schema/query library is redesigned |

---

## 12. Documentation and Change Rules

**Why these rules live in two places:** **Codess.md §4.0** is the **normative** list contributors see from the product index. **This section** repeats the **commitment** so CoPlan editors do not have to jump away while editing. **Rationale:** a single **CoPlan** + **Codess** loop is easier to enforce in review than rules scattered across README or wiki.

- **Codess.md §4.0** — full rule set: boundaries, ToC, headings, prose/list/table balance, sparse cross-links, work-item placement, gap/question writeups.
- Vendor format change → ***Schema.md** first → adapters → tests.
- New CLI flag → **`codess/project.py`** (`build_parser`), **`_*_cmd.py`**, **§5** here, **Codess.md** if user-visible.
- New DB column → **CoSchema.md** + **`sql/CoSchema.sql`** + **`store.py`**.

---

## 13. Optional Splits

Large future: **`CoPlan-cli.md`** (§5 only) or phase files; keep **Codess.md §4** pointers current.

---

## 14. Open questions and resolved decisions

**Format:** Resolved items keep a short audit trail here; **open** items use **context → options (pro/con) → recommendation + justification** for review.

### 14.1 Resolved (former Q1–Q5)

| ID | Decision | Implementation / doc |
|----|----------|------------------------|
| **Q1** | **Scan unknown `--source` tokens** → **stderr + exit 1** (fail loud; no silent empty CSV). | **Implemented:** **`validate_scan_source_for_cli`** (**`project.py`**); **`scan_cmd`** before roots; **§5.1**, **§11.6**. |
| **Q2** | Central registry: **scan** upserts index metrics **every** run; **`--registry PATH`** adds CSV filter + **`reg_*`** cols (file must exist when filtering). **Ingest** merges **`sources`**; **query `--stats`** merges **`query`**. **`PATH`** overrides **`CODESS_REGISTRY`**. **No** bare **`--registry`**. | **Done:** **`registry_store`**, **`scan_cmd`**, **`ingest_cmd`**, **`query_cmd`**, **`resolve_registry_directory`**; tests **`test_scan.py`**, **`test_registry_store.py`**, **`test_cli.py`**, **`test_config.py`**. |
| **Q3** | **Global Cursor row** (`path=(global)`): treat as **scan-only aggregate** of central/workspace DB metrics — **document** clearly; do **not** require ingest/query symmetry until **CursorSchema** defines a first-class global project. **Why:** ingest and query are **project-root-centric** by design; forcing global rows into **`.codess/`** without schema and UX agreement would fork the mental model. **Revisit** optional ingest of global history when **CursorSchema** §7–8 and store layout are updated. | **Doc stance:** **§5.1** output note; **§15** Cursor theme; **explain.md** Mail 5. |
| **Q4** | **`queries.sql` companion** → **postponed** until **CoSchema.md** (and query surface) are revisited; SQL stays embedded in **`query_cmd`** until then. | **Deferred:** **§11.7**; **§9** delivery note. |
| **Q5** | **Name-prefix roots:** **none** today. **Planned:** only the **last** segment may end with **`*`** → **basename string-prefix** match (**§4.2**). | **Verified (code):** **`helpers.parse_dir_list`** / **`user_root_string_disallowed`** have **no** `*` expansion — only **§4.2** prose. **§11.2** tracks implementation. **Independent of Q2** (registry shipped separately). |

**Q1–Q5 status:** **Q1** / **Q2** implemented in **`src/`**. **Q3** / **Q4** doc or defer. **Q5** specified only (**grep** / tests confirm **no** prefix-root code). **Follow-through:** **§11.2** when prioritized.

### 14.2 Open (for future decision rows)

Items below are **not** the former Q1–Q5; they remain genuinely open or multi-option:

- **Multi-root query:** keep **first root only** vs explicit multi-project report — needs UX + **§8** tests when chosen.
- **`--norec` / walk:** behavior once **`walk_dirs`** is on the production path (**§11.1**).
- **Enterprise redaction / PII:** whether to integrate third-party scanners vs regex-only (**§11.5**).

---

## 15. Consolidated engineering gaps (discussion brief)

**Purpose:** **§15** is for **review and prioritization**, not ticket duplication. Each theme below should be read with **open questions**, **recommendation**, and **justification**; **§11** holds the actionable rows and dependencies.

| Theme | Open questions | Recommendation (lean) | Justification |
|-------|----------------|----------------------|---------------|
| **Discovery / walk** | When to switch from index-led scan to walk-first? How does **`--norec`** interact with **`walk_dirs`**? | Spec **§3.3** pipeline first, then one **`walk`** entry point shared by scan/ingest. | Avoids divergent discovery logic and duplicate exclusion rules. |
| **Validation** | Should **`validate_config`** run for ingest/query? | Yes for **ingest** in a later PR once messages are non-noisy; query optional. | Same **CODESS_*** mistakes hurt ingest as much as scan. |
| **Cursor** | Global row vs project rows; **`--no-central`**; scan timestamps. | Follow **CursorSchema** §7–8; keep **Q3** stance until schema changes. | Prevents ad hoc store shapes. |
| **Query** | Multi-root; empty-store UX; optional **`queries.sql`**. | Defer **SQL file** (**Q4**); improve empty-store messages before multi-root. | Reduces surface area while UX is still moving. |
| **Errors / resilience** | **`--stop`** matrix; adapter partial failure visibility. | Document matrix in **§5** + tests (**§11.6**). | Operators need predictable exit codes. |
| **Processing depth** | Nested CC / subagent ingest vs strict fail. | Schema-led (**CCSchema**), tolerant parse + counters in debug. | Matches current adapter philosophy (**explain.md**). |
| **Content policy** | HTML, display SQL-like strings, CSV limits. | Complete **§11.5** research → normative table → code. | Export safety is cross-cutting. |

**Bulleted mirror (themes only):** Discovery and walk; validation parity; Cursor global/workspace; query UX and scope; errors and **`--stop`**; nested CC / subagent; content policy (**§11.5**).
