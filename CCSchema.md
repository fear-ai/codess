# CCSchema — Claude Code Session Storage

Vendor-specific structure for **Claude Code** (`@anthropic-ai/claude-code`). Normalized ingest: `src/codess/adapters/cc.py`. Scan: `src/codess/scan.py` (`_session_metrics_cc`).

**Version note:** Claude Code is distributed as a compiled npm package; on-disk formats evolve. Field names below match current Codess parsing and common installs.

## Transcript Retention

Claude Code prunes `~/.claude/projects` on a schedule. `cleanupPeriodDays`
controls it and **defaults to 30**; `~/.claude/.last-cleanup` records when the
sweep last ran.

**Observed, and the reason this is documented rather than assumed.** A sweep on
2026-08-20 left the oldest surviving transcript dated 2026-07-20 -- exactly 30
days -- on a machine where the setting was unset. Ten of seventeen Project
directories were emptied completely, and the two evidence stores that survive
show what they held: `usage.db` records 17,541 turns for one of them, and
`history.jsonl` 1,846 prompts.

**The setting is not a guarantee.** Reported defects describe transcripts
deleted despite `cleanupPeriodDays` set to 36500, around CLI and extension
updates and restarts -- root cause unstated, several versions affected. So a
high value reduces exposure rather than removing it.

| Reference | Reports |
|---|---|
| `anthropics/claude-code` issue 62272 | Deletion despite a high setting, triggered around updates; closed as duplicate |
| Issues 41458, 38055, 38691, 48334 | The same across several versions: sessions lost after an update, silent cleanup with no warning |

**Deletion is reported to key on file mtime rather than on recorded activity
time**, which would make anything that rewrites mtime -- a sync client, a
restore from backup -- age a session artificially. **Not verified here**: on
this machine the oldest surviving transcript is 2026-07-30 by both mtime and
first-record timestamp, so the corpus cannot distinguish the two rules. Treated
as a reported hazard rather than an established one, and it matters for a tree
under sync or restored from a copy.

**The consequence for Codess is a cadence requirement, not a feature.** A store
built from vendor Sources holds only what the vendor still has, so **ingest
must run more often than the vendor prunes** or the projection silently loses
what it was built to preserve. Nothing currently measures that gap. On this
machine it was crossed: one Project's format-4 store is the only remaining
record of 122 Sessions, retained by accident rather than by policy.

## Ancillary Stores Beside the Transcripts

`~/.claude/projects/**.jsonl` is what Codess decodes. Five other locations hold
Claude evidence, and three of them **outlive the transcripts** -- which matters
because the transcript store is pruned on a schedule (see Retention below).

| Location | Size | Holds | Survives cleanup |
|---|---|---|---|
| `history.jsonl` | 2.5 MiB | Every prompt: text, project path, session id, timestamp | **Yes** |
| `aiTitle` on records | -- | A generated Session title, written into the transcript rather than a side index. Read into `sessions.session_label` with basis `vendor_generated` | With the transcript |
| `usage.db` | 7.2 MiB | Per-session and per-turn token counts, model, tool name, cwd | **Yes** |
| `file-history/<session>/<hash>@vN` | 82 MiB | Actual file content, versioned per edit | **No** -- keyed by live session |
| `projects.tgz` | 21 MiB | A tar of `projects/` at some instant | Only what existed when it was made |
| `tasks/`, `teams/`, `sessions/` | small | Per-session task and team state | Not established |

**`history.jsonl` is the most useful of these.** 4,702 prompts spanning
2026-01 to 2026-08 across 153 sessions, of which **132 have no surviving
transcript**. It carries the human side of a Session -- what was asked, in
which Project, when -- for periods where nothing else remains. It does not
carry responses, tool calls, or results.

**`usage.db` covers a disjoint window.** 54 sessions and 20,604 turns spanning
2026-01-13 to 2026-04-26, with **zero overlap** with surviving transcripts. Per
turn it records input, output, cache-read and cache-creation tokens, the model,
the tool name, and the cwd. It has not been written since 2026-04-25, so it is
not a current Claude Code feature; its `processed_files` table suggests a tool
that ingested transcripts on its own schedule.

**`file-history` has its own retention and is not transcript-keyed for
retention purposes.** The documentation states it holds snapshots for the 100
most recent checkpoints, deleting snapshot files no retained checkpoint
references, **except each file's first snapshot**. Measured here: all 19 of its
session directories correspond to live transcripts, so it did not outlive the
sweep on this machine -- but the mechanism is a checkpoint count rather than
the transcript sweep, so the two can diverge.

**Documented layout, from the vendor's own reference:**

| Path | Holds |
|---|---|
| `projects/<slug>/<session>.jsonl` | Session transcripts. Swept by `cleanupPeriodDays` |
| `history.jsonl` | Every prompt typed, with timestamp and project path; used for up-arrow recall |
| `file-history/<session>/` | Pre-edit file snapshots for checkpoint restore; retained by checkpoint count |
| `shell-snapshots/` | Shell aliases and functions captured at startup |
| `plans/` | Plan files written during plan mode |

**None of these is decoded today.** Recorded here because a completeness claim
about Claude evidence that counts only transcripts understates what the vendor
retained -- and, for the two that survive cleanup, understates what is
*recoverable* after it.

## Source Scope

| Field | Value |
|-------|--------|
| **Vendor** | Anthropic Claude Code |
| **Primary paths** | `~/.claude/projects/` (override: `CODESS_CC_PROJECTS`) |
| **Encoding** | UTF-8 JSONL |
| **Time basis** | `fileMtime` (ms) in index; record `timestamp` in JSONL (ISO or ms) |

## Storage Layout

| Path pattern | Role |
|--------------|------|
| `projects/<slug>/` | One directory per project; **slug** = absolute project path with `/` → `-`, prefixed `-` when absolute |
| `projects/<slug>/sessions-index.json` | Session catalog (preferred for scan) |
| `projects/<slug>/<sessionId>.jsonl` | Main session transcript (ingest: top-level `*.jsonl` only) |
| `projects/<slug>/<sessionId>/` | Session subtree; may contain `**/*.jsonl` (subagents, fragments) |

**Slug quirk:** Decode is lossy because hyphens can represent either path
characters or separators. Codess uses resolved `projectPath` from the index
when present.

## Selective Access

| Method | Use |
|--------|-----|
| **Codess scan** | `codess scan --dir <work>`; `--subagent` / `CODESS_SUBAGENT` for sidechain counts |
| **Codess ingest** | `codess ingest --dir <project>`; reads top-level `*.jsonl` per project slug |
| **Direct read** | Parse `sessions-index.json` + `fullPath` or glob `*.jsonl` |

## `sessions-index.json`

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

## JSONL Records and Runtime Context

Line-delimited JSON contains both transcript content and Claude Code product
state. Persisted records are not a verbatim copy of the model's runtime context.

Runtime context can include system/project instructions, a Session working
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

The current adapter emits message Events from `user` and `assistant`
records, distinguishes typed human prompts from harness/system inputs carried
in user envelopes, and emits bounded product-state and lifecycle events. It
recognizes Claude's tagged local-command trio in either observed release
envelope: `<local-command-caveat>` is harness context,
`<command-name>/…</command-name>` is a human-initiated command, and
`<local-command-stdout>` is a harness-produced command result. Some releases
store these as `user.message.content`; others use `system/local_command`.
Their source envelope role therefore never decides the normalized actor.
Command-only Sessions remain valid operational evidence, but Session
orientation should de-emphasize them relative to substantive Sessions.
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
markers are known retained-raw state, not missing Session content.
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

## Subagent and Main-Session Scope

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

## Scan Observations

| Metric | Definition |
|--------|------------|
| **Sessions** | Index entries for project (or top-level `*.jsonl` if no index); respects `isSidechain` unless `subagent` |
| **Events** | Sum of `messageCount` from counted entries |
| **Size (mb)** | Sum of `stat()` on `fullPath` targets; else rglob under `sessionId` |
| **days_ago** | `(now_ms - max fileMtime)` / 1 day |
| **span_weeks** | `(max_ts - min_ts)` / 7 days among counted entries |

## Limitations

- Index may omit `fullPath` → size uses directory rglob (may mix subagent files).
- Ingest deliberately recurses only below `{parent}/subagents/`; unrelated nested JSONL fragments are not treated as sessions.
- Top-level `version` or `claudeCodeVersion` is present on observed releases but
  is not guaranteed on every record. Ingest retains the first observed exact
  value as `sessions.harness_version`; absence remains `NULL` rather than being
  replaced with the currently installed Claude version.
- **Slug decode (implementation impact):** `slug_to_path` is lossy (e.g. hyphen vs path segment). Discovery prefers `projectPath` from `sessions-index.json` when present; `project.py` / scan fall back to slug-derived paths.

## Codess Mapping Boundaries

Mode, permission, attachment, snapshot, AI/custom title, agent name, queue,
duration, scheduled-task, and direct `fork-context-ref` facts have bounded
common events. A direct `parentSessionId` overrides directory-inferred
parentage and records its source field. Assistant `message.model` and
`message.usage.service_tier` configure model turns with exact field provenance.
Exact model and service-tier filters resolve Model Turns to direct assistant
record provenance, Source revision, and record locator. Claude effort or speed
tier remains absent without a direct source field.

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
Likewise, an MCP-qualified name does not prove a user-configured Claude CLI
server. Claude product integrations can expose
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
they have different runtime semantics.
