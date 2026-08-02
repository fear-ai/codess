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
| Find projects with session data (scan) | Critical |
| Ingest CC, Codex, Cursor | Critical |
| Query sessions, orientation, events, and bounded normalized content | Critical |
| Catalog-wide and filtered cross-Project analytical Assemblies | High |
| Save/replay typed requests, chain stable result IDs, and verify exact evidence | High |
| Batch / multi-root (`--dirs`, `--dir`) | Critical |
| Review candidates using session, local Git, activity, ownership, and topic evidence | High |
| Execute an explicit reviewed selection without a hidden “worthy” heuristic | High |
| Per-source filters (`--source`) | High |
| Redaction | High |

**Out of scope:** raw-source search over authorized vendor fields and messages,
alternative indexed retrieval without measured need, and Markdown export.
Bounded normalized substring search is implemented. Raw retention does not make
raw vendor evidence searchable. The remaining
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
| **CoPlan.md** | Modules/components, entity composition, data/configuration flows, code boundaries, runtime/CLI contract, tests, active work, decisions, and gaps |
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

Maintained documents describe the present system, the reasons for its design,
and unresolved work. Git history and generated reports retain change history;
the documentation does not narrate incremental fixes after their consequences
have been incorporated.

Introduce a subject in prose before using a list or table. Use tables only for
short, repeated fields that readers genuinely compare. A qualification that
needs several sentences belongs in a prose subsection, with a terse registry
entry pointing to it. Lists group parallel items; they do not replace an
explanation of relationships or tradeoffs.

Define a specialized term or abbreviation at first use and retain its agreed
spelling in the glossary. Status, task, and cross-reference entries use familiar
or glossary-defined terms, state one disposition, and name the authoritative
location without repeating its argument.

## 5. Glossary

| Term | Definition |
|------|------------|
| adapter | Parser/mapper for one source-system storage family |
| Assembly | Reproducible cross-Project selection over explicitly named Project snapshots, filters, and selected fields; it may be queried directly or exported |
| analysis dataset | Reusable rows selected for an investigation, with their Project/snapshot/source provenance and limitations |
| Assembly export | An analysis dataset encoded for a consumer as JSONL, Parquet, DuckDB, merged SQLite, or another declared format; it is a derived workproduct, not source authority |
| directory / path | Machine-local location string; never a durable work identity |
| event | One ordered normalized observation within a Session |
| extraction | Informal operation/result name; use **Project snapshot** for the durable dated normalized Project object, **analysis dataset** for selected reusable rows, and **Assembly export** for an encoded cross-Project output |
| raw-source search | A future bounded search over policy-authorized fields in exact vendor Source revisions, including evidence not projected into normalized content; raw capture alone is not such a search feature. Earlier documents called this full-source search, but encrypted, binary, unavailable, or unauthorized values prevent a truthful completeness claim |
| harness / surface | Runtime or interface producing evidence, such as CLI, desktop, IDE extension, or agent runner |
| ingest | Read selected Source revisions, normalize them, and atomically publish a new Project snapshot |
| model | Model configuration used by a Model Turn; it is not a vendor, actor role, Session, or harness |
| Project | Minted stable identity for one continuing body of work. For Git-backed work, exactly one Codess Project represents the repository; its clones, linked worktrees, workspace directories, and branches are locations, bindings, or observations under that Project |
| Project location | Observed directory/worktree/subdirectory bound to a Project on one machine |
| Project snapshot | Immutable dated normalized observation of one Project under recorded source revisions, package, decoder, validator, and policy |
| repository | Version-control identity and the Project boundary for Git-backed work; one repository maps to one Codess Project, while non-Git work still has a Project without a repository |
| scan | Discover candidate Project locations from source-system indexes without normalizing content |
| Session | One source-system conversation/thread identity and lifecycle; globally namespaced by `source_system_id` |
| Session name | Mutable human-readable key such as `slash_model` that maps to one `global_session_id`; unique within one Project and never itself an identity or provenance key. A source-system title remains separate upstream metadata |
| Source / Source revision | Vendor/harness evidence container, and one observed byte/database revision of it; one Source can yield one or many Sessions |
| source system | Namespace and storage family that makes upstream Session/record IDs meaningful, such as `anthropic.claude-code`, `openai.codex`, or `cursor.composer` |
| provenance check | Bounded test with exact source records and expected Codess rows; it checks identity, order, relationships, values, source-specific evidence, diagnostics, query behavior, and evidence lookup for a claimed use case |
| search report | Bounded, deterministic display of search matches and their result/provenance information. A future evaluation may compare report ordering without deleting matches or changing stored meaning |
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

### 5.1 Vocabulary governance

This glossary is the controlled terminology for documentation, public
interfaces, and work-item names. The executable CoSchema contract separately
owns closed stored-value vocabularies such as `normalized_status` and
`location_state`; vendor Schema documents own exact upstream designations and
their mappings. Open source-system values remain namespaced rather than being
forced into a misleading common enum.

Four loose phrases are retired:

- **materialization** becomes **analysis dataset** for the selected rows and
  **Assembly export** for a JSONL/Parquet/SQLite/DuckDB encoding; the
  logical-versus-physical distinction adds nothing useful here;
- **semantic golden** becomes the expected rows inside a **provenance
  check**; it does not assert that different source systems express identical
  meaning;
- **source-system evidence-preservation case** becomes **provenance check**;
  preservation remains an acceptance property rather than part of the name;
  and
- **investigation result-order evaluation** becomes **search report**: first
  establish the investigation scope, then present its bounded matches and
  provenance in the requested order. It carries no evaluation claim.

---

## 6. References

- [Claude Code npm](https://www.npmjs.com/package/@anthropic-ai/claude-code)
- [Codex CLI](https://github.com/openai/codex)
- [Cursor forum: chat history](https://forum.cursor.com/t/chat-history-folder/7653)
- [legel: Cursor export gist](https://gist.github.com/legel/ebd0bbc012bf019a1db5212b825e7d16)
