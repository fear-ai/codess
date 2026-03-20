# CoPlan — Developer guidance and work plan

Coding approaches; work items, tasks, issues by module, feature, implementation sequence.

---

## 1. Module layout

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
├── test_walk.py
├── test_cli.py
├── test_subagent_detail.py
└── test_integration.py

sql/
├── CoSchema.sql            # Canonical DDL; store reads this
└── queries.sql             # Phase 4: query strings for query_cmd; named sections

scripts/                     # Plan to obsolete and delete
├── batch_ingest.py         # Replaced by codess ingest --dirs/--dir
└── find_candidate.py       # Replaced by codess scan
```

**Shared helpers:** `src/codess/helpers.py`. Used by adapters, scan, walk, cli.

**Store:** `.codess/` (new). Archive/remove `.coding-sess` as we migrate.

---

## 2. Modules and interactions (reference)

| Module | Role |
|--------|------|
| config | Paths, env, EXCLUDE_RECURSE, STORE_DIR |
| helpers | Path, slug, exclude, CSV, dir list (shared) |
| walk | Directory traversal; exclude; dedupe; no symlinks |
| adapters | CC, Codex, Cursor parsers |
| store | SQLite init (CoSchema.sql), upsert, state |
| project | Slug, get_cc_dir, get_codex_files, get_cursor_dbs |
| scan | Discovery, filters, CSV output |
| ingest / query | CLI commands |

Layout: `src/codess/`, `src/cli/`, `tests/`, `sql/`. Vendor storage detail: **CCSchema.md**, **CodexSchema.md**, **CursorSchema.md**.

---

## 3. Implementation phases

**Order:** CC/Codex scan+ingest → walk+recurse → Cursor → query (project + batch).

### Phase 1: CC and Codex scan + ingest

| Step | Task | Module |
|------|------|--------|
| 1.1–1.9 | Config, CoSchema, helpers, scan, ingest, CLI, tests | config, scan, cli, tests |

### Phase 2: Walk and recurse

| Step | Task | Module |
|------|------|--------|
| 2.1–2.7 | walk.py, .codessignore, parse_dir_list, scan prune, CLI, tests | walk, scan, cli |

### Phase 3: Cursor

| Step | Task | Module |
|------|------|--------|
| 3.1–3.7 | **CursorSchema.md**, adapter filters, scan+ingest global+workspace, tests | adapters/cursor, scan, ingest |

### Phase 4: Query

| Step | Task | Module |
|------|------|--------|
| 4.1–4.6 | queries.sql, query_cmd, batch, CoSchema review | sql, cli |

---

## 4. CLI flags (summary)

| Flag | Meaning |
|------|---------|
| --dirs PATH | File with dirs (one per line; no `..`) |
| --dir PATH | Add dir (repeatable) |
| --norec | Roots only; no recursion |
| --source cc,codex,cursor | Filter sources |
| --out PATH | Output file; `-` stdout |
| --registry PATH | Override `~/.codess` |
| --subagent | CC scan: include sidechain sessions |
| --days N | Scan recent window |

Full spec: **Codess.md** §4.

---

## 5. General coding approaches

- Shared helpers in `src/codess/helpers.py`
- Directory traversal in `walk.py`; separate from vendor logic
- Per-vendor behavior documented in `*Schema.md`
- Tests per area; conftest for fixtures
- `.codess` for project stores

---

## 6. Schema timing

| When | Action |
|------|--------|
| Phase 1 | CoSchema.sql + store.init_db() |
| Before/during Cursor | **CursorSchema.md** kept in sync |
| After Cursor stable | Review CoSchema vs normalized events |

---

## 7. Exclude and safeguards

**Exclude file:** `cwd/.codessignore` first; else `~/.codessignore`. One directory name per line; `#` comments.

**Scan prune:** When scan notes a directory has Coding tool work, do not recurse further (planned).

**Walk:** `max_depth` 16; `max_time` 100 min.

**CODESS_DAYS:** Default scan recency (see config).

---

## 8. Issues

- Cursor global: `project_path` NULL in store; directory filter deferred
- Slug decode lossy (CC): hyphen vs slash segments
- **Subagent:** scan supports `--subagent` / `CODESS_SUBAGENT`; ingest does not read nested CC subagent files
- **Cursor central:** `composerData` often null; `workspaceRoot` unverified — see **CursorSchema.md**
- **Cursor DB bloat:** large `state.vscdb` reported in forums; read-only tooling recommended

---

## 9. Roadmap and platform selection

### 9.1 Roadmap (implementation order)

1. Phase 1: CC + Codex scan + ingest; CoSchema; helpers
2. Phase 2: Search/recurse; `--dirs`, `--dir`, `--norec`
3. Phase 3: Cursor read, filter, ingest; **CursorSchema.md**
4. Phase 4: Query project + batch; external SQL; CoSchema review
5. Optional: timeouts, ^C, threads, progress

### 9.2 Platform selection

| Choice | Decision |
|--------|----------|
| Store | SQLite |
| Location | Project-local `.codess/` |
| Project scope | Git repo root (typical) |
| FTS5 | Postponed |

---

## 10. Improvement backlog (from former docs/improvements.md)

### 10.1 Scan

| Item | Priority | Notes |
|------|----------|--------|
| Validate roots exist | P1 | Warn if `--dir` missing |
| Walk + scan integration | P2 | Indices today; walk for discovery later |
| Scan prune | P2 | Stop recursing when session data found |
| CSV tests | P2 | Header + numeric columns (partially done) |

### 10.2 Filter

| Item | Priority | Notes |
|------|----------|--------|
| `--days 0` = all time | P1 | Define semantics vs current cutoff |
| Cursor `days_ago` in scan | P2 | From bubble timestamps |
| `--source` validation | P2 | Reject unknown vendors |

### 10.3 Ingest

| Item | Priority | Notes |
|------|----------|--------|
| CC subagent file ingest | P2 | Nested JSONL |
| `--no-central` | P2 | Skip Cursor global DB |
| MIN_SIZE sanity warning | P2 | If absurdly large |
| Store parent writable check | P2 | |

### 10.4 Config / CLI

| Item | Priority | Notes |
|------|----------|--------|
| `validate_config()` on ingest/query | P2 | Today: scan only |
| `--validate` | P2 | Check config and exit |

---

## 11. Test ↔ implementation (scan)

| Test | Behavior verified |
|------|-------------------|
| `test_scan_cc_subagent` | `_session_metrics_cc` + `--subagent` / `CODESS_SUBAGENT` |
| `test_cc_subagent_vs_main_detailed` | Fixture layout + scan counts |
| `test_scan_cursor_central_db` | Global row `(global)` |
| `test_scan_debug_dir_label` | `[dir]` / `[scan]` labels |
| `test_scan_days_ago_in_debug` | `days_ago` in stderr |
| `test_scan_mixed_dir_dirs` | `--dirs` + `--dir` dedupe |
| `test_scan_csv_format` | CSV header and numeric columns |
| `test_walk` | Recursion, excludes, max_depth, prune |

---

## 12. Development sequences (dependencies)

- **Subagent ingest:** After CC metadata links parent/child (e.g. GitHub CC issues on `parentSessionId`).
- **Cursor central improvements:** `get_composer_data()` probes; optional `--storage` filter for query.
- **Docs:** Vendor edits go to **CCSchema.md** / **CodexSchema.md** / **CursorSchema.md** only; **Codess.md** stays high-level.

---

## 13. Intermediate lists

Optional: `CoPlan-steps-1.md`, `CoPlan-steps-2.md` for long step lists; or keep all in this file.
