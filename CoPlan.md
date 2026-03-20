# CoPlan — Developer guidance and work plan

Coding approaches; work items, tasks, issues by module, feature, implementation sequence.

---

## 1. Module Layout

**Naming:** **scan** = discover projects with session data; **walk** = traverse directory tree.

```
src/
├── codess/
│   ├── __init__.py
│   ├── config.py           # Paths, env, EXCLUDE_RECURSE, STORE_DIR
│   ├── helpers.py          # Shared: path, slug, exclude, csv, dirlist (parse_dir_list)
│   ├── store.py            # SQLite init (reads CoSchema.sql), upsert, state
│   ├── project.py          # Slug, get_cc_dir, get_codex_files, get_cursor_dbs
│   ├── sanitize.py         # Control chars, ANSI, redaction
│   ├── walk.py             # Directory traversal; exclude; dedupe; no symlinks
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── cc.py
│   │   ├── codex.py
│   │   └── cursor.py
│   └── scan.py             # Discover projects with session data; vendor filter; CSV
├── cli/
│   ├── __init__.py
│   ├── scan_cmd.py
│   ├── ingest_cmd.py
│   └── query_cmd.py
└── main.py                 # codess scan | ingest | query

tests/
├── conftest.py             # Fixtures, temp dirs, env
├── test_helpers.py
├── test_config.py
├── test_store.py
├── test_project.py
├── test_sanitize.py
├── test_candidate.py
├── test_cc_adapter.py
├── test_codex_adapter.py
├── test_cursor_adapter.py
├── test_scan.py
├── test_walk.py            # Phase 2
├── test_cli.py
└── test_integration.py

sql/
├── CoSchema.sql            # Canonical DDL; store reads this
└── queries.sql             # Phase 4: query strings for query_cmd; named sections

scripts/                     # Plan to obsolete and delete
├── batch_ingest.py         # Replaced by codess ingest --dirs/--dir
└── find_candidate.py       # Replaced by codess scan
```

**Shared helpers:** `src/codess/helpers.py`. Used by adapters, scan, walk, cli.

**Store:** `.codess/` (new). Archive/remove `.coding-sess` as we migrate. Tests create `.codess` repeatedly; no reliance on `.coding-sess`.

---

## 2. Implementation Phases

**Order:** CC/Codex scan+ingest (known) → walk+recurse (modular) → Cursor (read, filter, ingest) → query (project + batch, incl. Cursor).

### Phase 1: CC and Codex scan + ingest

Knock off scan and ingest for Claude and Codex; we know these well.

| Step | Task | Module | Status |
|------|------|--------|--------|
| 1.1 | Config: CODESS_*, CODESS_CURSOR_DATA, CODESS_MIN_SIZE | config | — |
| 1.2 | Config: STORE_DIR = ".codess", EXCLUDE_RECURSE | config | — |
| 1.3 | CoSchema.sql: store reads file; fallback if missing | sql, store | — |
| 1.4 | helpers.py: path_to_slug, slug_to_path, is_excluded, write_csv | helpers | — |
| 1.5 | scan logic: per-dir, CC+Codex, filters, CSV | scan | — |
| 1.6 | ingest logic: per-dir, CC+Codex | cli/ingest_cmd | — |
| 1.7 | codess scan, codess ingest (CLI, single-dir first) | cli | — |
| 1.8 | Archive/remove .coding-sess; tests use .codess | — | — |
| 1.9 | Tests: conftest, test_helpers, test_config, test_scan, test_cli | tests | — |

### Phase 2: Walk and recurse

Modular directory traversal; --dirs, --dir, --norec. When no dirs given, start in cwd.

| Step | Task | Module | Status |
|------|------|--------|--------|
| 2.1 | walk.py: recurse from dirs; exclude; dedupe; no symlinks; max_depth 16, max_time 100 min | walk | — |
| 2.2 | Exclude: built-in (Codess §8) + .codessignore (cwd first, else ~/); dir names; no wildcards initially | config, helpers | — |
| 2.3 | parse_dir_list: --dirs FILE, --dir PATH (additive) | helpers | — |
| 2.4 | When scan notes dir with Coding tool work, do not recurse further | scan, walk | — |
| 2.5 | codess scan --dirs/--dir; recursive by default; --norec; CODESS_DAYS for recent sessions | cli | — |
| 2.6 | codess ingest --dirs/--dir; same; use walk when dirs given | cli | — |
| 2.7 | Tests: test_walk, integration | tests | — |

### Phase 3: Cursor

Read, filter, ingest Cursor.

| Step | Task | Module | Status |
|------|------|--------|--------|
| 3.1 | CursorSchema.md: initial draft before implementation | docs | — |
| 3.2 | Cursor adapter: min_events, min_duration filters | adapters/cursor | — |
| 3.3 | Cursor in scan (workspace + global; filter by dir when possible) | scan | — |
| 3.4 | Cursor in ingest | cli/ingest_cmd | — |
| 3.5 | codess scan/ingest --vendor cursor | cli | — |
| 3.6 | Update CursorSchema.md as we validate | docs | — |
| 3.7 | Tests: test_cursor_adapter, test_cli_cursor | tests | — |

### Phase 4: Query

Project-level and batch query, including Cursor.

| Step | Task | Module | Status |
|------|------|--------|--------|
| 4.1 | Externalize SQL: sql/queries.sql; query loads by name | sql, cli/query_cmd | — |
| 4.2 | query logic: per-dir, vendor filter | cli/query_cmd | — |
| 4.3 | codess query (project level) | cli | — |
| 4.4 | codess query --dirs/--dir (batch) | cli | — |
| 4.5 | Once CursorSchema nailed down: review our SQLite design; update CoSchema; retest | CoSchema, store | — |
| 4.6 | Tests: test_query, test_cli query, integration | tests | — |

---

## 3. CLI Flags

| Flag | Meaning |
|------|---------|
| --dirs PATH | File with dirs (one per line; full path or no ..) |
| --dir PATH | Add dir (repeatable, additive) |
| --norec | Use cwd or listed dirs only; no recursion |
| --source cc,codex,cursor | Filter sources (default: all); 1 or 2 allowed |
| --out PATH | Output file (default: find_codess.csv for scan, etc.); `-` for stdout |
| --registry PATH | Override ~/.codess for central registry |

When no --dir/--dirs given, start in cwd.

---

## 4. General Coding Approaches

- Shared helpers in `src/codess/helpers.py`
- Directory traversal in `walk.py`; separate from vendor/mode
- Per-vendor filters; one spec applies to all that recognize it
- Tests per phase; conftest for fixtures; no redundant implementations
- .codess for new work; archive/remove .coding-sess as appropriate

---

## 5. Schema Timing

| When | Action |
|------|--------|
| Phase 1 | CoSchema.sql generated; store.init_db() reads and executes |
| Before Phase 3 | CursorSchema.md initial draft |
| During Phase 3 | Update CursorSchema.md as we validate |
| After CursorSchema nailed down | Review our SQLite design; update CoSchema; retest |

---

## 6. Intermediate Lists

Keep step-level task lists in files as needed:

- `CoPlan-steps-1.md` — Phase 1 breakdown (optional)
- `CoPlan-steps-2.md` — Phase 2 breakdown (optional)

Or maintain in this file; split only if it grows unwieldy.

---

## 7. Exclude and Safeguards

**Exclude file:** `cwd/.codessignore` first; if absent, `~/.codessignore`. One directory name per line. Initially no wildcards; eventually trailing `*` and full path.

**Scan prune:** When scan notes a directory has Coding tool work, do not recurse further down.

**Walk safeguards:** max_depth 16; max_time 100 min.

**CODESS_DAYS:** Scan filter for recent sessions (ENV only).

---

## 8. Issues

- Cursor global: project_path NULL; directory filter deferred until schema confirmed
- Slug decode lossy: spank-py vs spank/py; fallback in place
- **Subagent:** Scan has `--subagent` (CC only); ingest does not support subagent files
- **Cursor central:** composerData decoded via `get_composer_data()`; workspaceRoot unverified — see docs/scan-metrics.md
