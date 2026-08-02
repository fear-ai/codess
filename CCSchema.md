# CCSchema — Claude Code session storage

Vendor-specific structure for **Claude Code** (`@anthropic-ai/claude-code`). Normalized ingest: `src/codess/adapters/cc.py`. Scan: `src/codess/scan.py` (`_session_metrics_cc`).

**Version note:** Claude Code is distributed as a compiled npm package; on-disk formats evolve. Field names below match current Codess parsing and common installs.

---

## 1. Document metadata

| Field | Value |
|-------|--------|
| **Vendor** | Anthropic Claude Code |
| **Primary paths** | `~/.claude/projects/` (override: `CODESS_CC_PROJECTS`) |
| **Encoding** | UTF-8 JSONL |
| **Time basis** | `fileMtime` (ms) in index; record `timestamp` in JSONL (ISO or ms) |

---

## 2. Storage layout

| Path pattern | Role |
|--------------|------|
| `projects/<slug>/` | One directory per project; **slug** = absolute project path with `/` → `-`, prefixed `-` when absolute |
| `projects/<slug>/sessions-index.json` | Session catalog (preferred for scan) |
| `projects/<slug>/<sessionId>.jsonl` | Main session transcript (ingest: top-level `*.jsonl` only) |
| `projects/<slug>/<sessionId>/` | Session subtree; may contain `**/*.jsonl` (subagents, fragments) |

**Slug quirk:** Decode is lossy (`spank-py` vs `spank/py`); Codess uses resolved `projectPath` from the index when present.

---

## 3. Recommended access

| Method | Use |
|--------|-----|
| **Codess scan** | `codess scan --dir <work>`; `--subagent` / `CODESS_SUBAGENT` for sidechain counts |
| **Codess ingest** | `codess ingest --dir <project>`; reads top-level `*.jsonl` per project slug |
| **Direct read** | Parse `sessions-index.json` + `fullPath` or glob `*.jsonl` |

---

## 4. sessions-index.json

Array under `entries` (typical fields used by Codess):

| Field | Type | Notes |
|-------|------|--------|
| `projectPath` | string | Resolved path must match scan project |
| `sessionId` | string | Directory / file stem |
| `fileMtime` | number | Unix **ms**; drives `--days` / recency |
| `messageCount` | number | Approx. messages (user + assistant); scan “events” |
| `isSidechain` | boolean | **true** = subagent session; excluded from scan unless `--subagent` |
| `fullPath` | string | Optional path to primary JSONL; size metric when present |

**Observed ranges:** `fileMtime` large ms since epoch; `messageCount` ≥ 0.

---

## 5. JSONL records and runtime context

Line-delimited JSON contains both transcript content and Claude Code product
state. Persisted records are not a verbatim copy of the model's runtime context.

Runtime context can include system/project instructions, a conversation working
set or compacted summary, a memory index, skill descriptions, loaded tool
schemas, deferred tool names, attachments, and tool results. Exact contents are
assembled dynamically and are not recoverable from normalized message events.

| Pattern | Notes |
|---------|--------|
| **Main session** | `user` / `assistant`; typed user content may be a string while assistant and tool content commonly use blocks (`text`, `tool_use`, `tool_result`) |
| **Subagent** | Messages may carry `isSidechain: true`, `agentId`; linking to parent session not always in file (see GitHub CC issues on `parentSessionId`) |
| **Product state** | Records can include `system`, `mode`, `permission-mode`, `attachment`, `file-history-snapshot`, `queue-operation`, AI/custom titles, agent names, fork context, and `last-prompt` |

Common record-envelope fields include `sessionId`, `uuid`, `parentUuid`,
`timestamp`, `cwd`, `gitBranch`, `version`, and `isSidechain`. Field presence
varies by record type.

AI/custom title records are source-system name evidence, not Session identity
and not an automatic Codess user alias. Claude transcript recency, `last-prompt`,
or an unanswered final record can show that the observed Source is open-ended;
none proves a currently running Claude process. Runtime state remains unknown
unless a separate dated runtime observation supplies it.

The current adapter emits conversation events from `user` and `assistant`
records, distinguishes typed human prompts from harness/system inputs carried
in user envelopes, and emits bounded product-state and lifecycle events. It
recognizes Claude's tagged local-command trio in either observed release
envelope: `<local-command-caveat>` is harness context,
`<command-name>/…</command-name>` is a human-initiated command, and
`<local-command-stdout>` is a harness-produced command result. Some releases
store these as `user.message.content`; others use `system/local_command`.
Their source envelope role therefore never decides the normalized actor.
Command-only Sessions remain valid operational evidence, but Session
orientation should de-emphasize them relative to substantive conversations.
The adapter
maps a `system` `compact_boundary` to `context.compact` and preserves its
trigger, pre/post token counts, duration, preserved-segment/message counts, and
other observed compact metadata. The paired `user` record marked
`isCompactSummary` becomes a distinct `context.inject` event whose summary body
is retained subject to the context-content limit. The boundary UUID and the
summary's `parentUuid` preserve their direct relationship. Error tool
results are split into explicit
`permission_denied` evidence and other `tool_failure` results. Each emitted
content block has a distinct stable event id. Event metadata retains `uuid` /
`parentUuid`; tool calls and their results also retain the shared tool-use id,
making record and call/result lineage queryable without copying the full
envelope. Task-list metadata under
`~/.claude/tasks/` is separate from transcript JSONL and from live background
processes.

Decoder 0.2 distinguishes unsupported content from non-semantic state:
signature-only `thinking` blocks with empty plaintext and model-fallback
markers are known retained-raw state, not missing conversation text.
Image-only user records are reported as `attachment_only_records` and
`unsupported_records`; their bytes remain in source evidence until the
attachment/content-link mapper is implemented.

Large tool results may be externalized below
`<sessionId>/tool-results/` and referenced by
`toolUseResult.persistedOutputPath`. Codess accepts only references within that
session subtree, emits a bounded linked external-content event for query use,
and exposes the exact file as a related raw revision.

Re-ingesting a changed or forced transcript transactionally replaces its
normalized session events. If the transcript remains valid but yields no
supported events, Codess removes the prior normalized session and reports an
`empty_sources` diagnostic.

**Timestamps:** `timestamp` on record or nested in `message`; ISO 8601 strings or numeric ms.

---

## 6. Subagent vs main (scan & ingest)

| Aspect | Main | Subagent (sidechain) |
|--------|------|----------------------|
| **Index** | `isSidechain: false` | `isSidechain: true` |
| **Typical files** | Top-level `{sessionId}.jsonl` | Often under `{parent}/subagents/` or dedicated `sessionId` dir |
| **Scan default** | Counted | Excluded |
| **Scan + `--subagent`** | Counted | Counted |
| **Ingest** | Top-level `*.jsonl` | Ingested from `{parent}/subagents/**/*.jsonl` |
| **Stored linkage** | No extra session metadata | `is_sidechain`, `parent_session_id`, and `source_relpath` in session metadata |
| **Size fallback** | `fullPath` or `{sessionId}/**/*.jsonl` | Fallback rglob may include subagent bytes if main path missing |

Consequently, default scan counts and stored Session-entity counts are not
directly comparable: scan excludes subagents unless requested, while ingest
preserves them for lineage. User-facing orientation must partition top-level
and related Sessions instead of presenting the flattened total as independent
work Sessions.

Claude's directory and record fields provide strong subagent-Session evidence,
including parent linkage in the observed layouts. `userType=external` occurs
on both top-level and subagent records and is not evidence of human authorship.
For a record with `isSidechain=true`, an `agentId`, or a source path below
`subagents/`, Codess maps a `user`-role task as a harness-carried
`delegated_prompt` with `origin_kind=harness_delegated`; it does not contribute
to human-prompt metrics. The exact source role and the structural evidence are
retained in metadata. Main-session records without a delegated/harness marker
remain human prompts; direct `origin.kind` and typed/queued prompt evidence are
stronger than that fallback.

---

## 7. Scan metrics (Codess)

| Metric | Definition |
|--------|------------|
| **Sessions** | Index entries for project (or top-level `*.jsonl` if no index); respects `isSidechain` unless `subagent` |
| **Events** | Sum of `messageCount` from counted entries |
| **Size (mb)** | Sum of `stat()` on `fullPath` targets; else rglob under `sessionId` |
| **days_ago** | `(now_ms - max fileMtime)` / 1 day |
| **span_weeks** | `(max_ts - min_ts)` / 7 days among counted entries |

---

## 8. Quirks & limitations

- Index may omit `fullPath` → size uses directory rglob (may mix subagent files).
- Ingest deliberately recurses only below `{parent}/subagents/`; unrelated nested JSONL fragments are not treated as sessions.
- Top-level `version` or `claudeCodeVersion` is present on observed releases but
  is not guaranteed on every record. Ingest retains the first observed exact
  value as `sessions.harness_version`; absence remains `NULL` rather than being
  replaced with the currently installed Claude version.
- **Slug decode (implementation impact):** `slug_to_path` is lossy (e.g. hyphen vs path segment). Discovery prefers `projectPath` from `sessions-index.json` when present; `project.py` / scan fall back to slug-derived paths.

## 9. Codess mapping boundaries

Mode, permission, attachment, snapshot, AI/custom title, agent name, queue,
duration, scheduled-task, and direct `fork-context-ref` facts have bounded
common events. A direct `parentSessionId` overrides directory-inferred
parentage and records its source field. Assistant `message.model` and
`message.usage.service_tier` configure model turns with exact field
provenance. A bounded audit found model values on 35,724 reviewed assistant
records and `service_tier=standard` on 35,565; no Claude effort or speed tier
was inferred.

The typed configuration query has also been exercised against a current Misses
snapshot: exact model/service filters resolve Model Turns to direct assistant
record provenance, Source revision, and record locator. These observed counts
are operational output, not a fixed schema claim.

Timestamp, model, service-tier, prompt-origin, and tool-input reads use the
common field-state decoder. Malformed optional fields produce field-scoped
diagnostics and are omitted without rejecting an otherwise usable record.

Every emitted event retains its exact Claude record type/subtype and line
locator. The scalar `mapping_rule` names the primary rule in
`schema/mappings/claude.json`; JSON `mapping_trace` records the source path and
additional lineage/configuration rules. Common event/configuration names are
the cross-vendor query surface, while original Claude names and values remain
available for release-specific investigation.

Tool names such as `Agent`, `TaskCreate`, `TaskUpdate`, `TaskGet`, `TaskList`,
and MCP-qualified operations are preserved as source tool evidence. A
versioned derived classifier may summarize them as planning, delegation, or
automation for reports, but those categories are not substituted for the
exact name and do not by themselves prove a distinct runtime actor.
Likewise, a historical MCP-qualified name does not prove a current
user-configured Claude CLI server. Claude product integrations can expose
session administration, visualization, or desktop/browser capabilities in a
particular surface. Codess treats each invocation and linked result as the
evidence: rendered visualization and successful chapter/task operations are
real outcomes; an empty browser list is a useful availability diagnostic; an
oversize instruction result is a real but inefficient failure. Current
configuration must be inventoried separately with the harness configuration
command.

Richer product state remains raw or metadata. Compaction boundaries and
summaries are specialized context-operation events, not a generic memory
event. Memory, skills, tool schemas, arbitrary instructions, and detailed
token snapshots are still not represented as one generic audit event because
they have different runtime semantics. The authoritative gap classifications
and dispositions are CoPlan rows **V-CC2**, **V-CTX1**, and **E-2**.

---

## 10. Cross-reference

| Topic | Document |
|-------|----------|
| Unified DB columns | **CoSchema.md** |
| Cursor storage | **CursorSchema.md** |
| Codex storage | **CodexSchema.md** |
| Implementation, tests, and work queue | **CoPlan.md** |
