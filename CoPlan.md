# CoPlan — Implementation plan and engineering guide

**Audience:** Contributors maintaining **Codess** (Python CLI + library).

**Scope:** Repository tree, **architecture** (layers and data movement), **configuration** (what/why/how), **CLI contract** (flags aligned with ENV and defaults), **feature→module map**, **coding practices**, **test strategy**, phases, backlog.

**Not here:** Vendor paths, filenames, DB keys, or field values — **CCSchema.md**, **CodexSchema.md**, **CursorSchema.md**; normalized columns — **CoSchema.md**.

**Where to start reading:** §2 (tree) → §3 (architecture) → §4 (configuration) → §5 (CLI) → §6 (features) → §7–§8 (code & tests).

**Documentation boundaries:** **Codess.md §4.1**.

---

## 2. Repository layout

**Terms:** **scan** = discover projects that have vendor session data; **walk** = filesystem tree traversal (shared infra for future/batch paths).

```
Codess/
├── main.py                 # argparse entry: scan | ingest | query
├── README.md
├── Codess.md               # product + doc map
├── CoPlan.md               # this file
├── CoSchema.md
├── CCSchema.md
├── CodexSchema.md
├── CursorSchema.md
├── sql/
│   └── CoSchema.sql        # DDL; store.init_db() executes this file
├── src/
│   ├── cli/
│   │   ├── scan_cmd.py     # CSV to stdout or --out
│   │   ├── ingest_cmd.py
│   │   └── query_cmd.py
│   └── codess/
│       ├── config.py       # ENV → Path / int / bool; defaults
│       ├── helpers.py      # parse_dir_list, write_csv, is_excluded, slug, codessignore
│       ├── store.py        # connect, init_db, upsert, ingest state
│       ├── project.py      # resolve CC/Codex/Cursor paths for a project root
│       ├── sanitize.py
│       ├── walk.py         # os.walk wrapper; depth/time caps
│       ├── scan.py         # run_scan; vendor index scans
│       └── adapters/
│           ├── cc.py
│           ├── codex.py
│           └── cursor.py
└── tests/
    ├── test_scan.py
    ├── test_helpers.py
    ├── test_walk.py
    ├── test_config.py
    ├── test_store.py
    ├── test_*_adapter.py
    ├── test_cli.py
    ├── test_integration.py
    └── …
```

Legacy **`scripts/`** (if present): obsolete vs CLI; remove when unused.

---

## 3. System architecture

Read this section **before** §4–§5 so configuration and CLI attach to a clear mental model.

### 3.1 Layers and dependency direction

**Exposition:** Treat the stack as **call direction** (who calls whom) plus **forbidden dependencies** (who must not import whom). The CLI only orchestrates; **all** vendor parsing lives under **`adapters/`** and **`project.py`** path resolution. That split is why **§4** (ENV + roots) and **§5** (flags) exist: global defaults live in **`config`**, not in parsers.

The runtime is layered so **CLI** never parses vendor JSON/SQLite directly; **adapters** never decide CSV paths or global ENV defaults.

```
                    ┌─────────────┐
                    │  main.py    │  argparse, subcommands
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  cli/*_cmd  │  orchestrate: roots, loops, CSV writers
                    └──────┬──────┘
           ┌───────────────┼───────────────┐
           │               │               │
    ┌──────▼──────┐ ┌──────▼──────┐ ┌─────▼─────┐
    │   scan.py   │ │ ingest path │ │  query    │
    └──────┬──────┘ └──────┬──────┘ └─────┬─────┘
           │               │             │
           │        ┌──────▼──────┐      │
           │        │ adapters/*  │◄─────┘ (query reads store only)
           │        └──────┬──────┘
           │               │
    ┌──────▼──────┐ ┌──────▼──────┐
    │ project.py  │ │  store.py   │
    │ walk.py     │ │  + CoSchema │
    └──────┬──────┘ └─────────────┘
           │
    ┌──────▼──────┐
    │ helpers.py  │
    │ config.py   │
    └─────────────┘
```

**Rules:**

- **`adapters/*`** expose iterators (or small helpers) that yield **normalized event dicts**; they depend on **`sanitize`**, **`config`** truncation constants, not on **`scan`**.
- **`scan.py`** discovers **candidate project paths** by reading **vendor indices** under configurable roots (`config.CC_PROJECTS`, etc. — see *Schema* for what those trees mean). It does **not** today drive discovery purely off `walk.py` over arbitrary trees; walk is available for **batch/dir expansion** scenarios and shared exclusion logic.
- **`project.py`** bridges **a git/project root** to “where are CC/Codex/Cursor artifacts for this root?” — used heavily by **ingest** and partially by **scan** (path resolution).
- **`store.py`** owns **SQLite connection**, **DDL application** from **`sql/CoSchema.sql`**, and **upsert** + **ingest_state.json** keys.

### 3.2 Data movement (three pipelines)

#### Discovery (scan)

**Purpose:** Answer “under this **work root** (or cwd), which **project directories** have session data, from which **sources**, and rough **size/count** metrics?”

**Mechanism (current):** **Index-led** means: for each enabled vendor, **scan** uses that vendor’s **existing registry or listing** (not a blind recursive crawl of the whole disk). It reads enough **metadata** to map **remote paths → local project dirs**, filters to dirs under the user’s work root, dedupes/excludes, applies **recency** and **`--source`**, then writes **CSV**. Opening occasional files for **size/session counts** is still **read-only** and not ingest.

**Where the indices live (detail → Schema, not repeated here):** CC **projects tree** and slug conventions (**CCSchema**); Codex **sessions root** layout (**CodexSchema**); Cursor **workspace** + **global** DB discovery (**CursorSchema**). This section only states the **role** of scan; field names and paths stay in those docs.

**Walk’s role today:** Supplies **multi-root** roots and shared **exclude/depth** behavior when listing from **`--dir` / `--dirs`**; **vendor discovery** inside each root remains **index-led**. **Walk-first** “find any `.jsonl` / `.vscdb` on disk” is **backlog** (**§11**).

#### Ingest

**Purpose:** For each **project root** passed to the CLI, pull **source** artifacts into **`<project>/.codess/`** as normalized **sessions** and **events**.

**Mechanism:** Resolve paths via **`project.py`** → stream through **`adapters/*`** → **`store.upsert_*`** → update **`ingest_state.json`** entry keyed by source path or DB path so **mtime** skips unchanged inputs.

#### Query

**Purpose:** Run **read-only SQL** (or formatted CLI output) against the **project-local** store.

**Mechanism:** Open the appropriate **DB file(s)** under **`.codess/`** (see §3.3). **query_cmd** does not write vendor trees.

### 3.3 Persistence layout (provisional)

**Current decision:** Under each **project directory**, **`STORE_DIR`** (`.codess/`) holds:

- **Per-vendor DB files** (`sessions_cc.db`, `sessions_codex.db`, `sessions_cursor.db`) when using split stores, and/or **legacy** `sessions.db` — see **`get_store_path`** / **CoSchema.md**.

**Intent:** **Separate files per vendor** (and optionally per project) **reduces coupling** and keeps **ingest** and **query** logic simpler while adapters diverge. This is **not** a final product constraint: a **single merged DB** or **registry-only** layout could replace it later; any change must update **`store.py`**, **CoSchema** docs, and **tests** together.

**`ingest_state.json`:** One file per project (shared across vendors in current code) records **source file mtimes** for incremental runs.

---

## 4. Configuration

### 4.1 What is configurable, why, and how

**What:** (1) **Locations** of vendor data on this machine (`CODESS_CC_PROJECTS`, …). (2) **Behavior defaults**: scan window (`CODESS_DAYS`), min ingest size (`CODESS_MIN_SIZE`), CC sidechain counts (`CODESS_SUBAGENT`), debug/redact/force flags. (3) **Output/registry**: `CODESS_REGISTRY` for central **`ingested_projects.json`**. (4) **Walk exclusions** and truncation limits are **code constants** in **`config.py`** (not ENV) unless noted.

**Why:** Same codebase runs on **different OS paths**, **CI sandboxes**, and **user preferences** without editing Python.

**How:** **`config.py`** reads **environment variables at import time** into module-level `Path` / `int` / `bool`. **CLI** arguments are parsed in **`main.py`** and may **override** scan/ingest behavior per invocation (e.g. `--days` overrides default recent window). **Precedence:** where a flag exists (e.g. `--days`, `--min-size`), it **wins** for that run; otherwise **ENV** default from **`config`** applies.

**Why global args/ENV, not per-vendor sections:**

- **Vendor-specific *paths* already exist:** `CODESS_CC_PROJECTS`, `CODESS_CODEX_SESSIONS`, `CODESS_CURSOR_DATA` — each points at that tool’s install layout on this machine.
- **Behavior knobs are intentionally *run-wide*:** One **`scan`** / **`ingest`** applies a **single policy** to every vendor selected by **`--source`** (`CODESS_DAYS`, `CODESS_MIN_SIZE`, `CODESS_DEBUG`, `CODESS_FORCE`, …). That keeps **one argv surface**, **one import-time config**, and shared loops in **`scan_cmd` / `ingest_cmd`** without a combinatorial matrix (`--min-size-cc`, `CODESS_DEBUG_CODEX`, …).
- **Vendor-only semantics** stay in **code + Schema**, not parallel ENV trees: e.g. **`CODESS_SUBAGENT`** affects **CC** scan metrics only; Cursor/Codex ignore it. Per-vendor *behavior* differences that need toggles belong in ***Schema.md** + adapter options first; new **`CODESS_*`** or flags would follow a proven need.

### 4.2 Combining `--dir` and `--dirs`

1. **`helpers.parse_dir_list(dirs_file, dir_args)`** builds **one ordered list** of **resolved** `Path`s.
2. If **`--dirs FILE`** is set, **non-empty non-comment lines** are read **first** (in file order).
3. Each **`--dir PATH`** is **appended** in argv order.
4. **Duplicates** (same resolved path) are **skipped**.
5. Lines or args containing **`..`** are **skipped** (security/consistency).
6. If the result is **empty**: **`scan_cmd`** uses **`Path.cwd()`**; **`ingest_cmd`** and **`query_cmd`** use **`get_project_root()`** (`git rev-parse --show-toplevel` from cwd, else cwd — see **`project.py`**).

### 4.3 Environment variables (defaults)

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

**Boolean ENV (`CODESS_DEBUG`, `CODESS_FORCE`, `CODESS_SUBAGENT`):** Implemented in **`config.py`** as string → **true** only if, after **`.lower()`**, the value is exactly **`1`**, **`true`**, or **`yes`**. **Unset** uses default **`0`** → false. Values like **`y`**, **`Y`**, **`on`**, **`2`** are **false** (not generic shell truthiness). Export e.g. `CODESS_DEBUG=1` or `CODESS_DEBUG=yes`.

**Why `CODESS_*` vs `DEBUG` / `FORCE` / `SUBAGENT`:** Shell and CI need **prefixed** names (`CODESS_DEBUG`, …) to avoid collisions with unrelated tools. **`config.py`** exposes short **Python** names (`DEBUG`, `FORCE`, `SUBAGENT`) as **bools read once at import** from those variables. Docs refer to **ENV** with the `CODESS_` name; code samples may show **`config.DEBUG`** meaning “the bool parsed from **`CODESS_DEBUG`**.”

**Why scan `--debug` ≠ ingest `--debug` (and `CODESS_DEBUG` only affects ingest today):** **Different semantics in code.** **Scan** `--debug` only drives **discovery tracing** (stderr per dir, extra **`dir_path`** CSV column, may disable day window) — **`scan_cmd.py`** uses **`debug = args.debug`** and **never** reads **`config.DEBUG`**. **Ingest** `--debug` enables **heavier behavior** (e.g. storing **`source_raw`**, verbose adapter paths) — **`ingest_cmd.py`** uses **`opts["debug"] = args.debug or DEBUG`**. **Rationale (as implemented):** keep **profile-level** `CODESS_DEBUG=1` from flooding **scan** with directory traces when the intent is only **ingest** diagnostics / raw capture. **Cost:** operators must pass **`scan --debug`** explicitly for CSV/trace behavior even if **`CODESS_DEBUG`** is set. Unifying (**`args.debug or DEBUG`** in **`scan_cmd`**) would be a **behavior change** (document in changelog if done).

**CLI `store_true`:** Passing the flag sets **true** for that process. There is **no** `-y` shorthand. Combining with ENV is **per row** below (not uniform across subcommands).

**Boolean and pseudo-boolean flags — confirmed behavior (source):**

| Subcommand | Flag | ENV → `config` | Effective true when |
|------------|------|------------------|---------------------|
| *(top-level)* | `-v` / `--verbose` | — | **`args.verbose`** only (**`main.py`** → logging). |
| **scan** | `--debug` | **`CODESS_DEBUG` → `DEBUG` not used** | **`args.debug`** only. |
| **scan** | `--subagent` | **`CODESS_SUBAGENT` → `SUBAGENT`** | **`args.subagent or SUBAGENT`**. |
| **scan** | `--norec` | — | **`args.norec`** only. |
| **ingest** | `--debug` | **`CODESS_DEBUG` → `DEBUG`** | **`args.debug or DEBUG`**. |
| **ingest** | `--force` | **`CODESS_FORCE` → `FORCE`** | **`args.force`**: **`store_true`** with **`default=FORCE`** — if **`FORCE`** is true, omitting **`--force`** still yields **true**; **`--force`** always **true**. |
| **ingest** | `--redact` | — | **`args.redact`** only (patterns are **code** in **`config.REDACT_PATTERNS`**). |
| **query** | `--stats`, `--taxonomy`, `--sessions`, `--permissions`, `--task-review`, `--tool-counts` | — | Each **`store_true`** / mode flag only; **no** `CODESS_*` booleans. |

**Validation:** **`validate_config()`** (invoked from **scan**) checks e.g. **`CODESS_DAYS`** in **[1, 3650]**, **`MIN_SIZE` ≥ 0**; violations → **stderr** warnings.

---

## 5. CLI and runtime contract

**Purpose of this section:** After §3–§4, this is the **operator-facing contract**: exact **flags**, matching **ENV**, and **defaults** so runs are reproducible. **Semantic meaning** of vendor metrics remains in ***Schema.md** (scan metric sections).

**Table columns:** **Flag** | **ENV** (variable name, or **—**) | **Default** (when flag omitted / ENV unset as applicable) | **Explanation**.

### 5.1 `codess scan`

| Flag | ENV | Default | Explanation |
|------|-----|---------|-------------|
| `--dirs PATH` | — | — | File of work roots (§4.2). |
| `--dir PATH` | — | — | Append root; repeatable. |
| *(no dirs after merge)* | — | **`Path.cwd()`** | **Scan** only; see §4.2. |
| `--source cc,codex,cursor` | — | all three | Comma-separated vendor subset. |
| `--out PATH` | — | `find_codess.csv` | CSV output path. |
| `--out -` | — | — | CSV to **stdout** (not **`write_csv`**). |
| `--norec` | — | off | No descent when walk applies. |
| `--days N` | `CODESS_DAYS` | **`90`** | Recent window; omitted → **`CODESS_DAYS`**. |
| `--debug` | — | off | Discovery trace + CSV **`dir_path`**; **CLI only** — see **§4.3** matrix (`scan_cmd`: no **`DEBUG`**). |
| `--subagent` | `CODESS_SUBAGENT` | **`SUBAGENT`** from ENV | **`args.subagent or SUBAGENT`** — see **§4.3**. |
| `--registry PATH` | `CODESS_REGISTRY` | — | Parsed in **`main.py`**; **ignored** by **`scan_cmd`** today — no default applies to scan output (registry → **ingest** + **`CODESS_REGISTRY`** default **`~/.codess`**). |
| `-v` / `--verbose` | — | off | Python logging level. |

**Precedence (scan):** **`--days` omitted** → **`CODESS_DAYS`**. **`--subagent`:** **`args.subagent or SUBAGENT`**. **`--registry`:** not consumed in **scan** yet (**§11**).

**Output columns:** `path,vendor,sess,mb,span_weeks` (with `dir_path` when `--debug`). Metric definitions: **CCSchema** §7, **CodexSchema** §6, **CursorSchema** §6.

### 5.2 `codess ingest`

| Flag | ENV | Default | Explanation |
|------|-----|---------|-------------|
| `--dirs` / `--dir` | — | **`get_project_root()`** | Same merge as scan (§4.2); empty list → git root or cwd. |
| `--source` | — | **`all`** | `cc` \| `codex` \| `cursor` \| `all`. |
| `--min-size BYTES` | `CODESS_MIN_SIZE` | **`20480`** | Skip sources smaller than N bytes. |
| `--force` | `CODESS_FORCE` | **`FORCE`** from ENV | **`store_true`**; argparse **`default=FORCE`** — omitting flag still uses ENV at parse time. Ignores **`ingest_state.json`** mtime skips when true. |
| `--redact` | — | off | **`store_true`** only; **no** `CODESS_*` (patterns live in **config**). |
| `--debug` | `CODESS_DEBUG` | **`DEBUG`** from ENV | **`args.debug or DEBUG`** — see **§4.3**. |
| `--registry PATH` | `CODESS_REGISTRY` | **`~/.codess`** | Central registry dir (`ingested_projects.json`). |

### 5.3 `codess query` (selected flags)

| Flag | ENV | Default | Explanation |
|------|-----|---------|-------------|
| `--dirs` / `--dir` | — | **`get_project_root()`** | Same merge as §4.2; empty → git root or cwd. |
| *(multi-root)* | — | first only | **Only `roots[0]`** is queried; rest ignored until multi-query exists. |

**Other flags** (`--stats`, `--sessions`, `--tool`, `--show`, `--permissions`, …): **no `CODESS_*` wiring** in **`main.py`** today — see **`python -m main query --help`**. Default is **no report** until at least one mode flag is passed.

### 5.4 Walk and `--dirs` file format

- **`--norec`:** only explicit roots; no descent.
- **Otherwise (when walk used):** **`walk.walk_dirs`** applies **`should_skip_recurse`** + **`.codessignore`**, **`MAX_DEPTH`**, **`MAX_TIME_MIN`**, no symlink follow — constants in **`walk.py`** / **`config.EXCLUDE_RECURSE`**.
- **`--dirs` file:** one path per line; **`#`** comment; empty skipped; **`..`** rejected.

### 5.5 Filter wiring (semantics → Schema)

| Concern | Where enforced | Meaning of values |
|---------|----------------|-------------------|
| Recent sessions | `scan.py` + `--days` / `CODESS_DAYS` | Vendor timestamps → *Schema* |
| CC sidechains | `scan.py` + `--subagent` / `CODESS_SUBAGENT` | **CCSchema** |
| Min source size | `ingest` + `--min-size` / `CODESS_MIN_SIZE` | Bytes on **source** files |
| min_events / duration | — | Planned; **§11** |

### 5.6 Operational quick check

`python -m main scan --dir . --out -`

Further backlog for CLI semantics: **§11**.

---

## 6. Feature → implementation map

**Purpose:** Navigation aid — “where is X implemented?” — not a second architecture spec. Use **§3** for data flow; this table only **indexes** modules.

| Feature | Primary modules | Notes |
|---------|-----------------|--------|
| Multi-root roots | `helpers.parse_dir_list`, `*_cmd` | §4.2 |
| Vendor filter | `scan`, `ingest_cmd`, argparse | `frozenset` of names |
| Recent window | `scan`, `config.CODESS_DAYS` | ms cutoff |
| CC sidechain counts | `scan._session_metrics_cc` | **CCSchema** |
| Cursor workspace + global | `scan`, `project`, `adapters/cursor` | **CursorSchema** |
| Incremental ingest | `store.should_ingest`, state JSON | mtime keys |
| Idempotent upsert | `store.upsert_*` | unique (session_id, event_id) |
| Redaction | `sanitize`, adapter opts | regex list in **config** |
| Walk safeguards | `walk.walk_dirs` | depth / time |

---

## 7. Coding techniques

**Who:** Maintainers editing **adapters**, **store**, or **CLI**.

| Topic | Practice | Why |
|--------|----------|-----|
| **Streaming** | Adapters **yield** events; ingest commits per file/DB batch | Keeps **memory** bounded on large JSONL / many bubbles |
| **SQLite (Cursor read)** | `file:…?mode=ro` URI in adapter | **Avoids write locks** and signals read-only intent |
| **Errors** | Log + skip bad lines in parsers; scan tolerates partial index | **Resilience** on evolving vendor exports |
| **CSV** | **`helpers.write_csv(path, rows, header)`** writes scan CSV to a **path**; **`scan_cmd`** uses **`csv.writer`** on **`sys.stdout`** when **`--out -`** | Shared helper for **files**; stdout is a **text stream** and bypasses the helper |
| **Single DDL file** | **`sql/CoSchema.sql`** is the only script **`store.init_db()`** runs | **Canonical** = one place for **`CREATE TABLE` / indexes** so Python never forks schema |
| **Tests** | See **§8** | — |

---

## 8. Testing strategy

**Goals:** Catch **regressions** in CLI, **metric math**, **adapters**, and **store** without requiring real `~/.claude` data.

**Layout:** One **`test_<module>.py`** per major package (`helpers`, `config`, `store`, `scan` via subprocess, `adapters`, `walk`, `cli`).

**Strategy:**

| Layer | Approach |
|-------|----------|
| **Unit** | Pure functions / small fixtures (`tmp_path`, fake JSONL, temp SQLite) |
| **CLI** | **`subprocess`** `python -m main …` with **`CODESS_*`** pointed at temp dirs |
| **Integration** | **`test_integration.py`** for multi-step flows where present |

**Coverage emphasis:** **`parse_dir_list`** (including **`--dirs` + `--dir`**), **scan CSV** shape, **walk** depth/excludes, **adapter** edge records, **`validate_config`**.

**When adding a feature:** Add or extend tests in the **same PR**; prefer **temp env** overrides over mutating developer home directories.

---

## 9. Delivery phases

| Phase | Goal | Code focus |
|-------|------|------------|
| 1 | CC + Codex scan & ingest | adapters/cc, codex; scan; store; CLI |
| 2 | Walk + multi-root | walk; parse_dir_list; prune (planned) |
| 3 | Cursor | adapters/cursor; global + workspace |
| 4 | Query + external SQL | queries.sql; query_cmd |

Keep **`sql/CoSchema.sql`** aligned with **CoSchema.md** as event shapes stabilize.

---

## 10. Implementation gaps (pointers)

| Area | Detail in |
|------|-----------|
| CC slug / path | **CCSchema.md** §8–§9 |
| CC subagent ingest | **CCSchema.md** §9 |
| Cursor global `project_path` | **CursorSchema.md** §7–§8.1 |
| Cursor scan time range | **CursorSchema.md** §8.1 |

---

## 11. Improvement backlog

### 11.1 Scan / discovery

| Item | P | Notes |
|------|---|--------|
| Validate roots exist | 1 | Missing `--dir` |
| Walk-first discovery | 2 | Today index-led |
| Scan prune | 2 | After session hit |
| CSV type tests | 2 | Partial |

### 11.2 Filters / CLI

| Item | P | Notes |
|------|---|--------|
| `--days 0` | 1 | All-time |
| Cursor timestamps in scan | 2 | Aggregate bubbles |
| `--source` validation | 2 | Unknown tokens |
| **`scan --registry` wired** | 2 | Flag parsed; **`scan_cmd`** ignores **`args.registry`** today |
| **`scan --debug` + `CODESS_DEBUG`** | 3 | Optional: OR with **`DEBUG`** like **ingest** (behavior change) |

### 11.3 Ingest / store

| Item | P | Notes |
|------|---|--------|
| Nested CC / subagent files | 2 | **CCSchema** |
| `--no-central` | 2 | Cursor |
| `validate_config` everywhere | 2 | Today scan-only |
| `--validate` | 2 | Dry run |

### 11.4 Platform

| Choice | Decision |
|--------|----------|
| Store | SQLite |
| Location | `<project>/.codess/` |
| FTS5 | Postponed |

---

## 12. Test ↔ implementation (quick index)

| Tests | Area |
|-------|------|
| `test_scan_*`, `test_subagent_detail` | Scan CLI + CC metrics |
| `test_walk` | Recursion / caps |
| `test_*_adapter` | Normalization |
| `test_store`, `test_config` | DDL path, env, validation |

---

## 13. Documentation and change rules

- Vendor format change → ***Schema.md** first → adapters → tests.
- New CLI flag → **`main.py`**, **`_*_cmd.py`**, **§5** here, **Codess.md** if user-visible.
- New DB column → **CoSchema.md** + **`sql/CoSchema.sql`** + **`store.py`**.

---

## 14. Optional splits

Large future: **`CoPlan-cli.md`** (§5 only) or phase files; keep **§4.1** pointer in **Codess.md**.
