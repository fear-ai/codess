# CoPlan — Codess Implementation Plan and Engineering Guide

**Scope:** Repository layout, **architecture**, **features** (what the code does), **coding techniques**, CLI/runtime contract, phases, backlog, and tests.

**Out of scope here:** Vendor paths, files, DB keys, field names, and on-disk values.
Those live only in **CCSchema.md**, **CodexSchema.md**, **CursorSchema.md**.
Normalized store documented in **CoSchema.md** / **sql/CoSchema.sql**.

**Operator spec:** §6 (CLI, ENV, walk rules).

---

## 1. Purpose and document boundaries

| Topic | Document |
|-------|----------|
| Why the product exists, doc map | **Codess.md** |
| Claude Code layout & fields | **CCSchema.md** |
| Codex session files | **CodexSchema.md** |
| Cursor `state.vscdb` | **CursorSchema.md** |
| Our SQLite tables/columns | **CoSchema.md** |
| This file | How code is structured, built, and extended |

---

## 2. Repository layout

```
src/codess/     config, helpers, store, project, sanitize, walk, scan, adapters/{cc,codex,cursor}
src/cli/        scan_cmd, ingest_cmd, query_cmd
main.py         Entrypoint: codess scan | ingest | query
tests/          Per-module and integration tests
sql/            CoSchema.sql (+ future queries.sql)
```
**Naming:**
  **scan** = discover projects with session data
  **walk** = directory tree traversal (shared infra, not vendor-specific).

---

## 3. System architecture

### 3.1 Layers (dependency direction)

```
CLI (argparse)
  → helpers (paths, dir lists, CSV, excludes)
  → scan | ingest_cmd | query_cmd
        → scan.py          # index-based discovery, CSV rows
        → walk.py          # optional recursion; excludes; time/depth caps
        → project.py       # resolve vendor roots → project paths / DB paths
        → adapters/*       # parse vendor → normalized events (streaming)
        → store.py         # SQLite init, upsert, ingest state
```

- **Vendor logic** is isolated in `adapters/` + vendor-specific helpers in `project.py` / `scan.py` calls.
- **No adapter imports scan**; scan may call `project` and `get_db_metrics`-style helpers.

### 3.2 Major data flows

| Flow | Mechanism |
|------|-----------|
| Discovery | Read vendor indices or filesystem hints → canonicalize project paths → CSV |
| Ingest | For each project root, resolve sources → adapter iterators → `upsert_*` → `ingest_state.json` mtime keys |
| Query | Open per-vendor or legacy DB under `.codess/` → SQL / CLI presenters |

### 3.3 Configuration surface

Single module **`config.py`**: env-backed paths, `EXCLUDE_RECURSE`, store filenames, truncation limits, `validate_config()`. CLI flags override or complement env for scan/ingest.

---

## 4. Feature → implementation map

| Feature | Primary modules | Notes |
|---------|-----------------|--------|
| Multi-root discovery | `helpers.parse_dir_list`, CLI | Dedupe resolved paths; no `..` |
| Vendor filter | `scan`, `ingest_cmd`, argparse `--source` | String list → frozenset |
| Recent-session window | `scan`, `config.CODESS_DAYS` | Cutoff ms; debug mode may bypass |
| CC sidechain counts | `scan._session_metrics_cc`, `CODESS_SUBAGENT` / `--subagent` | Semantics: **CCSchema.md** |
| Cursor workspace + global | `scan`, `project.get_cursor_*`, `adapters/cursor` | Two storage modes; **CursorSchema.md** |
| Incremental ingest | `store.should_ingest`, `ingest_state.json` | Per-file or per-DB mtime |
| Idempotent upsert | `store.upsert_session`, `upsert_event` | Unique (session_id, event_id) |
| Redaction | `sanitize.py`, adapter opts | Pattern-based before persist |
| Walk safeguards | `walk.walk_dirs` | `MAX_DEPTH`, `MAX_TIME_MIN`; skip symlinks |

---

## 5. Coding techniques

- **Streaming:** Adapters yield events; ingest batches commits per file/DB, not load-all.
- **SQLite read-only:** Cursor reads use `file:…?mode=ro` URI where possible.
- **Tests:** Pytest per module; temp dirs + `CODESS_*` overrides for isolation; subprocess CLI tests for `main.py`.
- **Errors:** Log and skip bad lines/rows in adapters; scan tolerates missing index fields.
- **CSV output:** `csv.writer` / `write_csv`; stable column order for scan.
- **Single source for DDL:** `sql/CoSchema.sql` executed by `store.init_db()` — no duplicated CREATE strings in Python.

---

## 6. CLI and runtime contract

Canonical flags, environment variables, walk rules, and command behavior. **Per-vendor meaning of counts and filters** → vendor Schema (**§ scan metrics** / ingest sections).

### 6.0 Quick flag reference

| Flag | Meaning |
|------|---------|
| --dirs PATH | File with dirs (one per line; no `..`) |
| --dir PATH | Add dir (repeatable) |
| --norec | Roots only; no recursion |
| --source cc,codex,cursor | Filter sources |
| --out PATH | Output file; `-` stdout |
| --registry PATH | Override `~/.codess` |
| --subagent | CC scan: include sidechain session counts |
| --days N | Scan recent window (days) |

### 6.1 Configuration (ENV)

| Variable | Role |
|----------|------|
| `CODESS_CC_PROJECTS`, `CODESS_CODEX_SESSIONS`, `CODESS_CURSOR_DATA` | Override vendor data roots (paths only; semantics → *Schema.md) |
| `CODESS_DAYS` | Default scan recency |
| `CODESS_SUBAGENT` | CC scan sidechain inclusion |
| `CODESS_MIN_SIZE`, `CODESS_FORCE`, `CODESS_DEBUG`, `CODESS_REGISTRY` | Ingest / debug / registry |

`validate_config()` (scan entry): range checks; stderr warnings.

### 6.2 Roots and `--dirs` file format

- `--dir` repeatable; `--dirs` one path per line; `#` comments; empty/`..` skipped.

### 6.3 Walk behavior

- Default roots: cwd if no dirs given.
- `--norec`: yield roots only.
- Skip rules: `should_skip_recurse` + `load_codessignore`; exact sets in **`config.EXCLUDE_RECURSE`** (not duplicated here).
- Caps: `walk.MAX_DEPTH`, `walk.MAX_TIME_MIN`.
- **Planned:** prune when directory already has session data (feature hook; vendor detection TBD).

### 6.4 Commands

- **scan:** CSV columns `path,vendor,sess,mb,span_weeks` (+ `dir_path` in debug). Metric definitions: **CCSchema.md** §7, **CodexSchema.md** §6, **CursorSchema.md** §6.
- **ingest / query:** See `main.py` / `*_cmd.py` and `--help`.

### 6.5 Filters (wiring only)

| Mechanism | Wired in | Semantics |
|-----------|----------|-----------|
| min_size | ingest, `CODESS_MIN_SIZE` | Skip small **source** files (CC/Codex); thresholds are bytes, not vendor records |
| subagent | scan | CC index flag; **CCSchema.md** |
| recent | scan | CC/Codex timestamps; **CCSchema.md**, **CodexSchema.md** |
| min_events / min_duration | — | Planned; **§9** |

### 6.6 Operational tips

See **Codess.md** or run `codess scan --help`. Quick check: `codess scan --dir . --out -`.

### 6.7 Planned spec work

Backlog: **§9** (e.g. `--days 0`, `--validate`, `--source` validation).

---

## 7. Delivery phases

| Phase | Goal | Code focus |
|-------|------|------------|
| 1 | CC + Codex scan & ingest stable | adapters/cc, codex; scan; store; CLI |
| 2 | Walk integrated with multi-root workflows | walk.py; parse_dir_list; prune (planned) |
| 3 | Cursor read + ingest + scan rows | adapters/cursor; project; global + workspace |
| 4 | Query batch + external SQL | queries.sql; query_cmd |

**DDL / store:** Keep **CoSchema.sql** aligned with **CoSchema.md** after Cursor event shapes stabilize.

---

## 8. Implementation gaps (track in code; detail in Schema)

Short list; **data/model truth** in vendor Schema **§ quirks / open gaps**.

| Area | Pointer |
|------|---------|
| CC slug / path decode | **CCSchema.md** §8–§9 |
| CC subagent ingest | **CCSchema.md** §9 |
| Cursor global `project_path` | **CursorSchema.md** §7–§8.1 |
| Cursor scan time range | **CursorSchema.md** §8.1 |

---

## 9. Improvement backlog

### 9.1 Scan / discovery

| Item | P | Notes |
|------|---|--------|
| Validate roots exist | 1 | Warn missing `--dir` |
| Walk + scan integration | 2 | Today index-led; walk for discovery |
| Scan prune | 2 | Stop recursing after session hit |
| CSV assertions | 2 | Header + types (partial) |

### 9.2 Filters / CLI

| Item | P | Notes |
|------|---|--------|
| `--days 0` semantics | 1 | All-time vs cutoff |
| Cursor scan timestamps | 2 | Aggregate in scan |
| `--source` validation | 2 | Reject unknown tokens |

### 9.3 Ingest / store

| Item | P | Notes |
|------|---|--------|
| Subagent / nested sources | 2 | Feature; **CCSchema.md** |
| Skip Cursor global | 2 | `--no-central` |
| MIN_SIZE warnings | 2 | Sanity |
| `validate_config` on all subcommands | 2 | Today: scan |
| `--validate` | 2 | Exit 0 after checks |

### 9.4 Platform / runtime

| Choice | Decision |
|--------|----------|
| Store | SQLite |
| Location | `<project>/.codess/` |
| Project anchor | Git root (typical) |
| FTS5 | Postponed |

Optional: timeouts, ^C, threads, progress.

---

## 10. Test ↔ implementation

| Test area | Validates |
|-----------|-----------|
| `test_scan_*` | scan CLI, `_session_metrics_*`, CSV, mixed `--dirs`/`--dir` |
| `test_subagent_detail` | CC fixture vs scan flags |
| `test_walk` | Recursion, excludes, depth, prune set |
| `test_*_adapter` | Normalization and edge records |
| `test_store`, `test_config` | DDL path, env, `validate_config` |

---

## 11. Dependencies and documentation rule

- **Upstream format changes:** Update **vendor Schema first**, then adapters, then tests.
- **New CLI flag:** **CoPlan §6**, `main.py`, relevant `_cmd.py`, and **Codess.md** if user-facing.
- **New normalized column:** **CoSchema.md** + **sql/CoSchema.sql** + `store.py` upserts.

---

## 12. Optional splits

If this file grows: `CoPlan-cli.md` (§6 only) or phase files `CoPlan-phase-N.md`; keep §1 boundaries in each derivative.
