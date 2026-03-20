# Codess — Central project document

Goals, problem/solution, criteria, features, users, use cases; requirements, architecture, modules, design, roadmap; platform selection; documentation map; glossary; references. Authoritative doc list: §11.

---

## 1. Goals and Problem

**Problem:** Session records from Claude Code, Cursor, and Codex are valuable for assessing model behaviors, tool usage, cost estimation, and audits—but they are scattered, hard to read (large JSONL, nested structures), and harder to interpret (schema varies by source).

**Solution:** Ingest from multiple sources → normalize to a common schema → query via SQL or CLI. Separation of ingestion, indexing, and querying.

**Goals:**
- Discover projects with session data across vendors
- Ingest and normalize into a unified store
- Query tool counts, sessions, content
- Support find (discovery), ingest, query as batch or per-directory

---

## 2. Overall Criteria

- **Inclusion:** Path exists; session data present; git repo; not under backup/review dirs
- **Exclusion:** Path gone; slug decode artifact; backup (OLD, Save); review dirs (CodingTools, MCPs, etc.)
- **Filters:** min_size, min_events, min_duration (CC, Codex; CSCandidates). Cursor filterable fields TBD.

---

## 3. Desirable Features

| Feature | Priority |
|---------|----------|
| Find projects with session data | P0 |
| Ingest CC, Codex, Cursor | P0 |
| Query sessions, tool counts, content | P0 |
| Batch recursive find/ingest/query | P0 |
| Per-vendor filters | P1 |
| Redaction of secrets | P1 |
| FTS5 full-text search | P2 |
| Markdown export | P2 |

---

## 4. Target Users and Use Cases

| User | Use case |
|------|----------|
| Developer | Analyze tool usage across sessions |
| Researcher | Assess model behaviors, prompt adherence |
| Curator | Discover and prioritize projects for ingestion |
| Auditor | Permission and cost review |

---

## 5. Requirements (Summary)

- Ingest from CC (`~/.claude/projects/<slug>/*.jsonl`), Codex (`~/.codex/sessions/**`), Cursor (`state.vscdb`)
- Normalize to unified event model
- Project-local store: `<project>/.codess/`
- Incremental ingestion (mtime); idempotent upsert
- CLI: `codess find`, `codess ingest`, `codess query`
- Batch recursive by default; `--dirs FILE`, `--dir PATH` (additive)

---

## 6. Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   FIND          │     │   INGEST        │     │   QUERY         │
│ Directory       │────▶│ Adapters →      │────▶│ SQL / CLI       │
│ search + vendor │     │ .codess/        │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

**Directory search:** Separate from vendor/mode. Recurse from cwd or given dirs; stop at `.git` or excluded dirs; no symlinks; deduplicate.

**Vendor/mode:** CC, Codex, Cursor. Filter which vendors to consider.

---

## 7. Modules and Interactions

| Module | Role |
|--------|------|
| config | Paths, env, EXCLUDE_RECURSE, STORE_DIR |
| helpers | Path, slug, exclude, CSV, dir list (shared) |
| search | Directory recursion; exclude; dedupe; no symlinks |
| adapters | CC, Codex, Cursor parsers |
| store | SQLite init (reads CoSchema.sql), upsert, state |
| project | Slug, get_cc_dir, get_codex_files, get_cursor_dbs |
| find | Discovery, filters, CSV output |
| ingest | Per-dir ingest |
| query | Per-dir query; loads sql/queries.sql |

Layout: `src/codess/`, `src/cli/`, `tests/`, `sql/`. See CoPlan §1.

---

## 8. Spec (Find, Query, Ingest)

### Config

`CODESS_*` env vars; `CODESS_CURSOR_DATA`; `CODESS_MIN_SIZE`.

### Directory search

- Default: cwd when no dirs given; else `--dirs` / `--dir`
- `--dirs PATH`: file with dirs (one per line, full path or no `..`)
- `--dir PATH`: add dir (repeatable, additive)
- `--norec`: use cwd or listed dirs only; no recursion
- Recurse by default; stop at excluded dirs
- **Exclude** (case-insensitive, built-in): `.git`, `.*`, `node_modules`, `__pycache__`; `build`, `debug`, `release`, `test`, `tests`, `doc`, `docs`, `bin`, `lib`, `libs`, `var`, `log`, `logs`, `env`, `venv`; `OLD`, `Save`
- **Exclude file:** `cwd/.codessignore` first; if absent, `~/.codessignore`. One directory name per line. Initially no wildcards; eventually trailing `*` and full path.
- When scan notes a directory has Coding tool work, do not recurse further
- Safeguards: max_depth 16; max_time 100 min
- No symlinks; deduplicate

### scan

- Input: start dir(s); vendor filter (default: all)
- Output: CSV, one row per project+vendor. path, vendor, sess, mb, span_weeks
- `--out` default `./find_codess.csv`; `-` for stdout
- Default: run git fetch check when remote exists; `--nofetch` to skip

### query_

- Input: dir(s); vendor filter
- Output: by dir, by --show mode
- `--out` default `./query_codess.csv`

### ingest_

- Input: dir(s); vendor filter
- Output: path, vendor, sessions_added, events_added
- `--out` default `./ingest_codess.csv`

### Filters (ENV or CLI)

| Filter | Vendors | ENV |
|--------|---------|-----|
| min_size | CC, Codex | CODESS_MIN_SIZE |
| min_events | CC, Codex | CODESS_MIN_EVENTS |
| min_duration | CC, Codex | CODESS_MIN_DURATION |
| subagent | CC (scan) | CODESS_SUBAGENT |
| (Cursor) | TBD | TBD |

CODESS_DAYS: scan filter for recent sessions. CODESS_SUBAGENT / --subagent: CC scan includes subagent (default: exclude).

---

## 9. Roadmap and Implementation Order

1. **Phase 1:** CC and Codex find + ingest (known well); CoSchema; helpers
2. **Phase 2:** Search and recurse (modular); --dirs, --dir, --norec
3. **Phase 3:** Cursor read, filter, ingest; CursorSchema draft and updates
4. **Phase 4:** Query at project level and batch; externalize SQL; CoSchema review
5. Optional: max time, ^C, threads, progress

---

## 10. Platform Selection

| Choice | Decision |
|--------|----------|
| Store | SQLite |
| Location | Project-local `.codess/` |
| Project scope | Git repo root |
| FTS5 | Postponed |

---

## 11. Documentation Map

| Document | Role | Inclusion |
|----------|------|-----------|
| **Codess.md** | Central. Goals, problem, criteria, architecture, spec, roadmap. | Everything that defines *what* and *why* |
| **CoSessions.md** | Technical: sessions, LLM exchanges, tools, logs. | Deep technical detail; complements Codess |
| **CoPlan.md** | Work items, tasks, by module/feature/sequence. | Actionable items only |
| **CoSchema.md** | Our SQLite schema (doc). | Schema description |
| **coding-sessions-schema.sql** | DDL for sessions, events, indexes. | Canonical schema; store.py or init reads |
| **CursorSchema.md** | Cursor state.vscdb (emerging). | Cursor-specific only |
| **docs/scan-metrics.md** | Scan metrics, subagent vs main, Cursor central vs workspace, composerData, suggestions. | Metrics; analysis; gaps; recommendations |
| **docs/improvements.md** | Scan/filter/ingest improvements, config validation, recommendations. | Roadmap |
| **README.md** | Intro, getting started, minimal apps. | Obligatory; minimal |

---

## 12. Glossary

| Term | Definition |
|------|------------|
| adapter | Source-specific parser (CC, Codex, Cursor) |
| event | Normalized record: event_type, subtype, role, content |
| ingest | Read source, normalize, upsert into store |
| session | One conversation; one JSONL file or composer |
| slug | Path encoded for CC: `/Users/x/y` → `-Users-x-y` |
| source | Claude, Codex, Cursor |

---

## 13. References

- [Claude Code](https://www.npmjs.com/package/@anthropic-ai/claude-code)
- [Codex CLI](https://github.com/openai/codex)
- [Cursor forum: chat history](https://forum.cursor.com/t/chat-history-folder/7653)
- [legel: Cursor export](https://gist.github.com/legel/ebd0bbc012bf019a1db5212b825e7d16)
