# Codess — Decode Coding Tools

## Consumers

| Who | Scenario |
|-----|----------|
| Developer | Tool usage across sessions |
| Auditor | Permissions, cost review |
| Researcher | Model behavior, prompt adherence |
| Curator | Discover/prioritize projects to ingest |

---

## 1. Problem and Solution

**Problem:** Session records from Claude Code, Cursor, and Codex are valuable for assessing model behaviors, tool usage, cost estimation, and audits—but they are scattered, hard to read (large JSONL, nested structures), and harder to interpret (schema varies by source).

**Solution:** Ingest from multiple sources → normalize to a common schema → query via SQL or CLI. Separation of discovery (scan), ingestion, and querying.

**Goals:** Discover projects with session data; ingest and normalize; query tools/sessions/content; support batch or per-directory workflows.

---

## 2. Product Strategy and Requirements

### 2.1 Capabilities and Priorities

| Capability | Priority |
|------------|----------|
| Directory search / multi-rooti walk (`--dirs`, `--dir`) | P0 |
| Find projects with session data (scan) | P0 |
| Per-vendor filters | P0 |
| Ingest CC, Codex, Cursor | P0 |
| Query sessions, tool counts, content | P1 |
| Markdown export | P2 |
| FTS5 search | P3 |

### 2.2 Outcomes

- **Inclusion:** Path exists; session data present; git root with Github remote a big plus
- **Filters:** `min_size`, `min_duration` (CC/Codex); Cursor-specific filters TBD

### 2.4 Requirements summary (traceability)

| Need | Detail | Where specified |
|------|--------|-----------------|
| Multi-vendor inputs | CC projects dir, Codex `sessions`, Cursor `state.vscdb` | **CCSchema.md**, **CodexSchema.md**, **CursorSchema.md** |
| Normalized store | SQLite under `<project>/.codess/` | **CoSchema.md**, `sql/CoSchema.sql` |
| Incremental ingest | mtime + state file; idempotent upsert | §4 below; **CoPlan** modules |
| CLI | `codess scan`, `ingest`, `query` | §4 |

---

## 3. Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   SCAN          │     │   INGEST        │     │   QUERY         │
│ Discovery       │────▶│ Adapters →      │────▶│ SQL / CLI       │
│ + vendor indices│     │ .codess/        │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

- **Directory discovery** (walk) is separate from vendor adapters.
- **Vendors:** CC, Codex, Cursor: filter with `--source`.

---

## 4. Specification and operations

### 4.1 Configuration (ENV)

| Variable | Role |
|----------|------|
| `CODESS_CC_PROJECTS`, `CODESS_CODEX_SESSIONS`, `CODESS_CURSOR_DATA` | Override data roots |
| `CODESS_DAYS` | Default recent window for scan (days) |
| `CODESS_SUBAGENT` | CC: include sidechain sessions in scan counts (`1`/`true`/`yes`) |
| `CODESS_MIN_SIZE`, `CODESS_FORCE`, `CODESS_DEBUG`, `CODESS_REGISTRY` | Ingest / debug / registry |

**Validation:** `validate_config()` checks `CODESS_DAYS` ∈ [1, 3650], `MIN_SIZE` ≥ 0, and related sanity; scan prints warnings to stderr when violated.

### 4.2 Naming (CLI)

- **Roots:** `--dir` (repeatable), `--dirs FILE` (one path per line). No `..` in listed paths.
- **Subagent:** `--subagent` flag; same meaning as `CODESS_SUBAGENT`.

### 4.3 Directory list file (`--dirs`)

- One path per line; `#` starts a comment; empty lines skipped; paths containing `..` skipped.

### 4.4 Directory search (walk)

- Default roots: cwd if no `--dir`/`--dirs`.
- `--norec`: only listed roots (no tree walk).
- Built-in skip names (case-insensitive): `.git`, `.*`, `node_modules`, `__pycache__`, plus sets in config (see **CoPlan** §7).
- **`.codessignore`:** project `cwd/.codessignore` then `~/.codessignore`; one directory name per line.
- **Safeguards:** `max_depth` 16, `max_time` 100 min (walk module).
- **Planned:** scan prune when a directory already has coding-tool session data (see **CoPlan**).

### 4.5 `codess scan`

- **Input:** root dir(s); `--source cc,codex,cursor`; `--days N`; `--debug`; `--subagent`.
- **Output:** CSV default `find_codess.csv`, or `-` for stdout.
- **Columns:** `path,vendor,sess,mb,span_weeks` (debug adds `dir_path`).
- **Per-vendor definitions:** **CCSchema.md** §7, **CodexSchema.md** §6, **CursorSchema.md** §6.

### 4.6 `codess ingest` / `codess query`

- **Ingest:** `--dir` / `--dirs`, `--source`, `--min-size`, `--force`, `--redact`, `--registry`.
- **Query:** per-project store; modes per `main.py` / `query_cmd` (tools, sessions, stats, …).
- Default output paths described in CLI `--help`.

### 4.7 Filters (scan / ingest)

| Filter | Sources | ENV / flag |
|--------|---------|------------|
| min_size | CC, Codex ingest | `CODESS_MIN_SIZE` / `--min-size` |
| min_events, min_duration | Planned | TBD |
| subagent counts | CC scan | `CODESS_SUBAGENT` / `--subagent` |
| Recent sessions | CC, Codex scan | `CODESS_DAYS` / `--days` |

### 4.8 Operational tips

1. `codess scan --dir . --out -` — quick sanity check.
2. `CODESS_SUBAGENT=1` — full CC activity counts including sidechains.
3. `codess scan --dir . --days 365` — longer window; default 90 from `CODESS_DAYS`.
4. `codess scan --debug` — `[dir]` / `[scan]` trace on stderr.

### 4.9 Planned improvements (summary)

Detailed **P1/P2 backlog** (validate missing roots, `--days 0` semantics, Cursor `days_ago`, `--no-central`, `--validate`, `--source` validation) is tracked in **CoPlan.md** §10.

---

## 5. Documentation map

| Document | Role |
|----------|------|
| **Codess.md** | This file: goals, framing, architecture, CLI spec |
| **CoPlan.md** | Layout, phases, CLI flags, issues, roadmap, platform, backlog |
| **CoSchema.md** | Our SQLite store (normalized) |
| **CCSchema.md** | Claude Code on-disk layout and scan metrics |
| **CodexSchema.md** | Codex CLI session files and scan metrics |
| **CursorSchema.md** | Cursor `state.vscdb` keys and scan metrics |
| **CoSessions.md** | Pointer: vendor detail lives in `*Schema.md` |
| **sql/CoSchema.sql** | Canonical DDL |
| **docs/scan-metrics.md** | Index → schema files for metric definitions |
| **README.md** | Intro and quick start |

---

## 6. Glossary

| Term | Definition |
|------|------------|
| adapter | Source-specific parser (CC, Codex, Cursor) |
| event | Normalized record in our DB |
| session | One conversation (varies by vendor; see vendor schema) |
| slug | CC path encoding: `/Users/x/y` → `-Users-x-y` |
| scan | Discover projects with vendor session data (CSV) |
| ingest | Read source → upsert into `.codess/` |

---

## 7. References

- [Claude Code npm](https://www.npmjs.com/package/@anthropic-ai/claude-code)
- [Codex CLI](https://github.com/openai/codex)
- [Cursor forum: chat history](https://forum.cursor.com/t/chat-history-folder/7653)
- [legel: Cursor export gist](https://gist.github.com/legel/ebd0bbc012bf019a1db5212b825e7d16)
