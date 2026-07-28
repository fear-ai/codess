# Codess

---

## 1. Goals and problem

**Problem:** Session records from Claude Code, Cursor, and Codex are valuable for assessing model behaviors, tool usage, cost estimation, and audits—but they are scattered, hard to read (large JSONL, nested structures), and harder to interpret (schema varies by source).

**Solution:** Ingest from multiple sources → normalize to immutable per-Project
snapshots → query directly or assemble explicit cross-Project analytical
datasets. Discovery, source decoding, normalized storage, assembly, and
investigation remain separate operations.

**Goals:** Discover projects with session data; ingest and normalize; query tools/sessions/content; support batch or per-directory workflows.

---

## 2. Product framing (strategy → requirements)

### 2.1 Outcomes and constraints

- **Inclusion:** Path exists; session data present or explicit curator interest;
  typically a Git root; not under backup/review dirs. Candidate observations
  recommend consideration but never authorize ingest by themselves.
- **Exclusion:** Invalid paths; slug-decode ambiguity; backup trees (`OLD`, `Save`); reference/review trees (`Code/CodingTools`, `MCP/MCPs`, `Spank/sOSS`, etc.). Third-party source may be inspected explicitly but is not promoted as owned work.
- **Filters:** Scan supports source and recency filters. Ingest supports source
  selection and a run-wide minimum source-file size; it does not define
  vendor-specific event-count or duration thresholds.

### 2.2 Capabilities and priorities

| Capability | Priority |
|------------|----------|
| Find projects with session data (scan) | P0 |
| Ingest CC, Codex, Cursor | P0 |
| Query sessions, orientation, events, and bounded normalized content | P0 |
| Catalog-wide and filtered cross-Project analytical Assemblies | P1 |
| Save/replay typed requests, chain stable result IDs, and verify exact evidence | P1 |
| Batch / multi-root (`--dirs`, `--dir`) | P0 |
| Review candidates using session, local Git, activity, ownership, and topic evidence | P1 |
| Execute an explicit reviewed selection without a hidden “worthy” heuristic | P1 |
| Per-source filters (`--source`) | P1 |
| Redaction | P1 |

**Out of scope:** an FTS5 derivative and Markdown export. Bounded normalized
substring search is implemented. The remaining
dispositions are centralized in **CoPlan §8**.

### 2.3 People and scenarios

| Who | Scenario |
|-----|----------|
| Developer | Tool usage across sessions |
| Researcher | Model behavior, prompt adherence |
| Project operator | Safely ingest, capture, relocate, or retire one owned Project |
| Curator | Discover, compare, decide, and onboard a reviewed Project set |
| Release maintainer | Rebuild, freeze, and verify accepted baselines |
| Schema developer | Compare contracts and investigate vendor-format drift |
| Auditor | Permissions, evidence coverage, and reproducibility review |
| Automation / CI | Run noninteractive preflight and verification with versioned reports |

---

## 3. Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   SCAN          │     │   INGEST        │     │   QUERY         │
│ Discovery       │────▶│ Adapters →      │────▶│ SQL / CLI       │
│ + source indices│     │ Project snapshot│     │ or ASSEMBLE     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

- **Project discovery** is index-led and separate from event normalization in vendor adapters.
- **Source systems:** Claude Code, Codex, and Cursor Composer — filter with
  `--source`. Vendor, product, harness/surface, storage format, and source
  system are related but not interchangeable.

---

## 4. Documentation map

### 4.1 Documents and authority

Each document is the single authority for its subject; others link to it rather
than restating it.

| Document | Authoritative for |
|----------|-------------------|
| **README.md** | Installation, Project/vendor selection, investigation workflows, query composition, exports, read-only SQL |
| **Codess.md** | Product goals, requirements, high-level architecture, glossary, and this map |
| **Designs.md** | Functional design rationale, content-processing policy, and alternatives |
| **Schemas.md** | Schema compatibility, evolution, and vendor-translation policy |
| **CoSchema.md** | Logical normalized data, store semantics, and the format contract |
| **CCSchema.md**, **CodexSchema.md**, **CursorSchema.md** | Vendor-owned storage, observed fields, mapping evidence, and access |
| **CoPlan.md** | Code boundaries, runtime/CLI contract, configuration, tests, active work, decisions, and gaps |
| **Operations.md** | Maintainer procedures, safety gates, evidence, storage, retained baselines |
| **CompatibilityReview.md** | Evidence of the reviewed compatibility corpus |
| **experiments/** | Self-contained evaluations that graduate into decisions |
| **schema/** | Executable and machine-readable contracts |

### 4.2 Maintenance rules

Keep one authority for each fact; update the owning document when behavior
diverges from prose. Vendor facts belong only in the matching vendor schema;
executable DDL belongs in `schema/coschema/sqlite/schema.sql`. Do not add dated
chronology, copied command catalogs, or duplicate backlogs to the durable set.
Project-local manifests, receipts, and validation reports are operational
records, not documentation.

## 5. Glossary

| Term | Definition |
|------|------------|
| adapter | Parser/mapper for one source-system storage family |
| assembly | Reproducible cross-Project selection over explicitly named Project snapshots and filters; it may be virtual or have several materializations |
| directory / path | Machine-local location string; never a durable work identity |
| event | One ordered normalized observation within a Session |
| extraction | Informal name for normalized output; use **Project snapshot** for the durable dated object and **assembly materialization** for a derived cross-Project file |
| harness / surface | Runtime or interface producing evidence, such as CLI, desktop, IDE extension, or agent runner |
| ingest | Read selected Source revisions, normalize them, and atomically publish a new Project snapshot |
| materialization | One physical representation of an Assembly, such as SQLite, JSONL, Parquet, or DuckDB |
| model | Model configuration used by a Model Turn; it is not a vendor, actor role, Session, or harness |
| Project | Minted stable identity for one continuing body of work, independent of paths, worktrees, or repository layout |
| Project location | Observed directory/worktree/subdirectory bound to a Project on one machine |
| Project snapshot | Immutable dated normalized observation of one Project under recorded source revisions, package, decoder, validator, and policy |
| repository | Version-control identity and correlation evidence; it may contain several Projects, and a Project may span or lack repositories |
| scan | Discover candidate Project locations from source-system indexes without normalizing content |
| Session | One source-system conversation/thread identity and lifecycle; globally namespaced by `source_system_id` |
| Source / Source revision | Vendor/harness evidence container, and one observed byte/database revision of it; one Source can yield one or many Sessions |
| source system | Namespace and storage family that makes upstream Session/record IDs meaningful, such as `anthropic.claude-code`, `openai.codex`, or `cursor.composer` |
| vendor | Organization or ecosystem, such as Anthropic, OpenAI, or Cursor |
| workspace | Source-system grouping attributed to a Project through an evidence-backed Workspace binding; not a synonym for Project or directory |

Use the capitalized entity names Project, Project snapshot, Assembly, Source,
Session, Interaction, Model Turn, Event, and Artifact when referring to Codess
entities. Use lowercase words only for generic or exact upstream concepts. Do
not shorten Project to repository, directory, workspace, or checkout; qualify
those as Project locations, repository observations, or Workspace bindings.
In code and new interfaces, use `source_system` for adapter/store selection,
`vendor` for the organization/ecosystem, and `model` only for model
configuration. Existing `--source` and legacy `vendor_filter` spellings remain
compatibility surfaces until changed with aliases and migration tests.

---

## 6. References

- [Claude Code npm](https://www.npmjs.com/package/@anthropic-ai/claude-code)
- [Codex CLI](https://github.com/openai/codex)
- [Cursor forum: chat history](https://forum.cursor.com/t/chat-history-folder/7653)
- [legel: Cursor export gist](https://gist.github.com/legel/ebd0bbc012bf019a1db5212b825e7d16)
