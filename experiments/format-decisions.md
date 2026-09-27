# Format Decisions: Fields, Formats, and Bounds

Working record for the next wire-format change. Each decision states what it
changes, the measurement that decided it, and what closes it. Decisions move
into [CoSchema](../CoSchema.md), [CoNames](../CoNames.md), and
[CoTasks](../CoTasks.md) as they are applied; this file is the staging record so
the reasoning is not re-derived between sessions.

Measurements are read from the operator's own corpus and vendor stores. Each
states its basis, and each is re-derivable.

## Table of Contents

- [1. Time Column Naming](#1-time-column-naming)
- [2. Bounded Text Fields](#2-bounded-text-fields)
- [3. Token Fields](#3-token-fields)
- [4. Fields to Read](#4-fields-to-read)
- [5. Fields to Ignore](#5-fields-to-ignore)
- [6. Cursor agentKv](#6-cursor-agentkv)
- [7. Codex Protocol Findings](#7-codex-protocol-findings)

## 1. Time Column Naming

### 1.1 The Rule

A time column's suffix states its representation:

| Suffix | Representation | Type | Who observed the instant |
|---|---|---|---|
| `_at` | Unix milliseconds | `REAL`, nullable | The vendor, or the filesystem |
| `_when` | RFC 3339 UTC | `TEXT`, `NOT NULL` | Codess |

[CoSchema](../CoSchema.md#time-column-naming) already establishes that the two
representations are both correct and that the name is what is wrong. This is the
resolution it stops short of: name the group in the column rather than force one
type on both.

### 1.2 What the Rule Fixes

One name currently denotes two representations. `started_at` is `REAL` Unix
milliseconds in `sessions` and `tool_invocations`, and `TEXT` RFC 3339 in
`processing_runs`. Code reading both must know which table it is in, and a query
joining them cannot compare the values without conversion. No other name is
ambiguous, which is what makes the rule cheap: it renames a small set and
removes the one collision.

### 1.3 Columns Renamed

Read from the DDL. Every column below is Codess-recorded, so each takes `_when`:

| Table | Current | Becomes |
|---|---|---|
| `sources` | `observed_at` | `observed_when` |
| `sessions` | `observed_at` | `observed_when` |
| `project_locations` | `observed_at` | `observed_when` |
| `processing_runs` | `started_at` | `started_when` |
| `processing_runs` | `completed_at` | `completed_when` |
| `mapping_diagnostics` | `created_at` | `created_when` |
| `correlation_assertions` | `asserted_at` | `asserted_when` |

Unchanged, because each is source-reported or filesystem-observed and already
carries the correct suffix: `sessions.started_at`, `sessions.ended_at`,
`events.event_at`, `source_records.record_at`,
`tool_invocations.source_started_at`, `sources.source_mtime`,
`sessions.source_mtime`, `sessions.source_dir_mtime`.

`processing_runs.started_at` moving to `started_when` is what removes the
collision: `started_at` then means Unix milliseconds everywhere it appears.

### 1.4 Comparison Across the Two Representations

A comparison between an `_at` and a `_when` value needs one of them converted.
The question is where.

**Decision: convert during query processing, not in the database.**

The reasoning is what the two groups are for. A `_when` value is a provenance
statement -- read by a person auditing what ran, never aggregated, carrying its
own offset so the record is unambiguous outside this database. An `_at` value is
a reported measurement, compared and aggregated across hundreds of thousands of
Events. Adding a stored numeric copy of a `_when` column would:

- reintroduce exactly the duplicate-column class that three measured pairs were
  removed for -- `events.timestamp`, `sources.ingested_at`, and
  `sessions.ingested_at` were each byte-identical to another column and are gone;
- widen every bookkeeping table for a comparison that is rare, since the common
  predicates (`--since`, `--until`, Session ordering) read `_at` columns only; and
- create a second value that can disagree with the first after any edit, with
  nothing asserting they match.

Query-time conversion has none of those costs and one real benefit: the
conversion is visible at the point of use, so a reader sees that two differently
measured clocks are being compared rather than finding two numeric columns that
look directly comparable and are not.

**Where the conversion lives.** In the standalone time module
(section 4.4 of this file's companion work), as `to_epoch_ms(rfc3339) -> float`.
SQLite's own `strftime('%s', ...)` is available for direct-SQL users and is
documented as the equivalent, but Codess code uses the module so the parse rules
are stated once.

**The exception, if one appears.** If a measured query pattern joins
`processing_runs` to Event time frequently enough to matter, the answer is an
expression index on the converted value rather than a stored column -- it cannot
drift, because SQLite recomputes it. No such pattern is measured today.

## 2. Bounded Text Fields

### 2.1 Policy

Open-ended text fields have bounded maximum sizes, expressed in KiB. A bound is
applied at decode, and the original length is retained in `content_len` so a
truncated value is visibly truncated rather than silently short. Truncation is
recorded as a mapping diagnostic; a bound applied silently would make a
completeness claim false.

Bounds are set from measured distributions rather than chosen round numbers, and
each states what proportion of observed values it retains intact.

### 2.2 Bounds

| Field | Bound | Median | p99 | Max observed |
|---|---|---|---|---|
| `block_text` | 32 KiB | 362 | 5,619 | 35,379 |
| `block_tool_args` | 32 KiB | 112 | 3,355 | 25,877 |
| `block_reasoning` | 32 KiB | 734 | 12,829 | 12,829 |
| `block_tool_result` | 64 KiB | 465 | 15,672 | 94,460 |
| `text_blob` | 1,024 KiB | 4,864 | 337,554 | 8,388,608 |
| `json_msg_total` | 1,024 KiB | 1,996 | 158,457 | 11,274,060 |
| Codex `instructions` | 16 KiB | -- | -- | 7,459 |

Basis: 60,000 `agentKv` rows from the Cursor global store; Codex `instructions`
from `session_meta` payloads across the sessions tree.

Three of the bounds retain every observed value intact -- `block_reasoning`
(max 12,829 against 32 KiB) and Codex `instructions` (max 7,459 against 16 KiB)
truncate nothing today. They are set anyway, because an unbounded field is a
resource question rather than a size observation: the bound exists so a changed
vendor format cannot introduce an unbounded body without the bound reporting it.

`text_blob` and `json_msg_total` at 1,024 KiB sit above p99 and cap tails that
reach 8 MiB and 11 MB. The 8,388,608 maximum is exactly 8 MiB, which is a vendor
cap rather than a natural size -- evidence that the vendor bounds this field too.

### 2.3 Corroboration

Codex's own source sets comparable caps, read from openai/codex at `c9b19de`:

| Constant | Value |
|---|---|
| `DEFAULT_OUTPUT_BYTES_CAP` | 1 MiB |
| `MAX_TOOL_SEARCH_SOURCE_DESCRIPTION_BYTES` | 4 KiB |
| `MAX_RENDERED_FRAGMENT_BYTES` | 4 KiB |
| `TELEMETRY_PREVIEW_MAX_BYTES` | 2 KiB |

Our bounds sit in the same range as the vendor's own preview and fragment caps,
which is the right neighbourhood for retained evidence: Codess stores for search,
not for replay.

## 3. Token Fields

### 3.1 Layout

Codex's layout generalizes because it is the superset: it is the only vendor that
states both a cumulative and a per-turn measurement. Field names follow
`TokenUsage` in `codex-rs/protocol/src/protocol.rs`.

```sql
total_input_tokens              INTEGER,
total_cached_input_tokens       INTEGER,
total_cache_write_input_tokens  INTEGER,
total_output_tokens             INTEGER,
total_reasoning_output_tokens   INTEGER,
total_tokens                    INTEGER,
last_input_tokens               INTEGER,
last_cached_input_tokens        INTEGER,
last_cache_write_input_tokens   INTEGER,
last_output_tokens              INTEGER,
last_reasoning_output_tokens    INTEGER,
last_tokens                     INTEGER,
model_context_window            INTEGER,
token_basis TEXT CHECK (token_basis IN
  ('vendor_cumulative','vendor_turn','vendor_both','vendor_zero','absent'))
```

`cache_write_input_tokens` carries `#[serde(default)]` in the protocol, so it is
absent from older rollouts and did not appear in the corpus scan. It is included
because the vendor declares it, not because it was observed.

### 3.2 Vendor Fit

| Vendor | Source field | Records | Fills | Basis |
|---|---|---|---|---|
| Codex | `total_token_usage` + `last_token_usage` | 16,370 each | both | `vendor_both` |
| Claude | `message.usage` | 22,637 | `last_*` | `vendor_turn` |
| Cursor | `tokenCount` | 627 of 210,109 | `last_*` | `vendor_turn` |

### 3.3 The Cursor Zero

Cursor's `tokenCount` is present on 210,109 bubbles and **populated on 627 --
0.3%**. It is nonzero only on assistant bubbles; all 5,592 user bubbles are zero.
Shape is `{inputTokens, outputTokens}` with no observed variants.

A Cursor zero must not be stored as a measurement. 209,482 rows of `{0,0}` are
the vendor writing a default into a field it did not measure; treating them as
measurements would report Cursor as having consumed approximately zero tokens
across 200,000 bubbles. `token_basis='vendor_zero'` records "the field was
present and stated zero", distinct from `absent` (no field) and from a measured
zero. **Only `vendor_turn` and `vendor_cumulative` rows are summable.**

This follows the `session_model_basis` precedent: a derived or defaulted value is
never presented as a vendor statement.

## 4. Fields to Read

Each is populated in the corpus and unread by any adapter.

| Vendor | Field | Occurrences | Destination |
|---|---|---|---|
| Claude | `promptId` | 12,421 | `interactions.boundary_source='vendor'` |
| Claude | `slug` | 3,808 | `session_label` with basis |
| Claude | `snapshot.timestamp` | 744 + 506 | `event_at` for `file-history-snapshot` and `-delta` |
| Cursor | `richText` | 390 of 4,984 | `mention` nodes only |
| Cursor | `isAgentic` | 390 | Actor evidence |
| Cursor | `checkpointId`, `afterCheckpointId` | 1,230 / 763 | `session.resume` |
| Cursor | `unifiedMode` | all | Session attribute via ingest lookup |
| Codex | `instructions` | -- | Bounded at 16 KiB |
| Codex | `forked_from_id`, `parent_thread_id` | -- | Session relation |
| Codex | `agent_nickname`, `agent_role`, `agent_path` | -- | Sub-agent identity |
| Codex | `thread_source` | -- | `User`/`Subagent`/`Feature`/`MemoryConsolidation` |
| Codex | `RolloutLine.ordinal` | -- | Explicit sequence |

`promptId` is the notable gain: it groups records belonging to one prompt, which
is the Interaction boundary CoSchema currently derives by other means.
`interactions.boundary_source` can record `vendor` where it now records `mapping`
or `inferred`.

### 4.1 The `file-history-snapshot` Defect

`adapters/cc.py` builds the Event with `_get_timestamp(record)`, which reads the
top level. These records carry no top-level `timestamp`; it is nested one level
down:

```
record:   {isSnapshotUpdate, messageId, snapshot, type}
snapshot: {messageId, trackedFileBackups, timestamp: "2026-08-17T07:40:53.597Z"}
```

744 `file-history-snapshot` and 506 `file-history-delta` records decode as
untimed while the vendor stated a time. These records carry neither `sessionId`
nor `session_id`, so Session attribution goes through `messageId`.

## 5. Fields to Ignore

| Field | Reason |
|---|---|
| Claude `session_id` | Duplicate of `sessionId`. Never appears alone in any version or date range; zero value mismatches over 200,000 records. Read `sessionId` |
| Claude `userType` | Constant `external` on all 31,821 records carrying it. Retained in metadata, not promoted |
| Cursor `timingInfo.clientStartTime` | **Not an epoch.** Values are milliseconds since process start (`98813.09`, `173267.10`). Read `clientRpcSendTime` for wall time |
| Cursor `composerVirtualRowHeights` | UI layout state |

`events.timestamp`, `sources.ingested_at`, and `sessions.ingested_at` were each
byte-identical duplicates and are already removed from the DDL and from every
published store.

### 5.1 The Uptime Trap

`clientStartTime` interpreted as epoch milliseconds yields 1970-01-02. Two
sampled bubbles are 74,454 ms apart in `clientStartTime` and 272,288 ms apart in
`clientRpcSendTime`, so it is not even a fixed offset from wall time -- the
bubbles come from different process lifetimes. It is usable only as a
within-process relative duration, and nothing records which bubbles share a
process.

The sanity gate rejects it, which is the case that justifies having a gate:
a value is copied from `_at` to `_derived` only if it falls within
`[2020-01-01, now + 24h]` after scale conversion.

## 6. Cursor agentKv

209,951 rows under `agentKv:blob:<hash>`, the largest undecoded Cursor key space
and roughly half of all 432,855 `cursorDiskKV` rows.

### 6.1 Composition

| Kind | Share |
|---|---|
| Binary | 57% |
| JSON | 37% |
| UTF-8 text | 6% |

### 6.2 The JSON Half Is Conversation Records

29,973 of 30,001 parsed JSON blobs are `{role, content, id, providerOptions}` --
four key sets covering 99.9%. Roles: `tool` 17,420, `assistant` 10,751,
`user` 1,821, `system` 8.

Content blocks are typed: `assistant:tool-call` 17,437, `tool:tool-result`
17,420, `assistant:text` 10,280, `user:text` 3,453, `assistant:reasoning` 80.

```
assistant:tool-call
  toolCallId  "tool_aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeee"
  toolName    "read_file"
  args        {"target_file": "/home/user/project/NOTES.md"}

assistant:reasoning
  providerOptions {"cursor": {"modelName": "claude-4.6-opus-high-thinking"}}
```

`providerOptions.cursor.modelName` supplies an exact model name with gradation
and thinking mode -- materially better model evidence than the 0.3%-populated
`tokenCount`.

Tool names, 111,000+ invocations: `Read` 28,746, `StrReplace` 21,981,
`Grep` 16,968, `Shell` 16,306, `Glob` 2,520, `TodoWrite` 1,913, `Write` 1,288,
`WebSearch` 1,208, `mcp_web_fetch` 806. Two naming generations coexist
(`Read`/`read_file`, `Grep`/`grep`), which is what `source_tool_name` and
`canonical_tool_name` exist to hold.

### 6.3 Attribution

8,360 bubbles join to `agentKv` blobs through `toolFormerData.toolCallId`, and
the bubble key carries the composer:

```
bubbleId:11111111-2222-4333-8444-555555555555:7843
         |__ composerId ____________________|
  toolCallId "tool_aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeee"
                    joins
agentKv:blob:<hash>  content[].toolCallId
```

Composer to workspace to Project attribution then follows the existing path.
`agentKv` identifiers also appear in `checkpointId` (45) and `inlineDiff` (1).

### 6.4 Decode Tiers

| Tier | Content | Action |
|---|---|---|
| 1 | JSON conversation records | Full decode to Events, tool invocations, results, model params |
| 2 | UTF-8 text blobs | Retain as content with digest, bounded at 1,024 KiB, no structural claim |
| 3 | Binary blobs | Extract path and digest only as Artifact references; remainder stays opaque |

Binary blobs are protobuf-consistent -- leading `0a 20` is field 1 with a 32-byte
digest -- and readable as (absolute path, content digest) pairs without a schema:

```
0a 20 1a 9d c0 73 4f c3 e2 30 5b 6b c7 41 7d ef   |. ...sO..0[k.A}.|
cc 17 4c 1b 10 4c 49 a3 15 aa 88 d0 e4 00 0a 52   |..L..LI........R|
65 8f 2a 00 7a 41 0a 1b 2f 68 6f 6d 65 2f 75 73   |e.*.zA../home/us|
65 72 2f 70 72 6f 6a 65 63 74 2f 4e 4f 54 45 53   |er/project/NOTES|
2e 6d 64 12 22 12 20 ef eb 91 6d e6 56 b1 84 23   |.md.". ...m.V..#|
```

### 6.5 Two Constraints

**Volume.** 532 MB across 40,000 sampled rows extrapolates to roughly 2.8 GB over
all 209,951 -- larger than the entire published corpus. Selective access by
composer is mandatory; a full scan is never correct. With the section 2 bounds
applied, the JSON half yields roughly 38 MB of retained text against a 1.9 GB
corpus.

**Privacy.** These blobs carry absolute paths and complete file contents from
unrelated projects, including at least one credential-bearing file
(`/var/www/html/<site>/wp-config.php`). Tier-1 decode is scoped to attributed
composers, which the `toolCallId` join supplies. Unattributed blobs stay unread.

## 7. Codex Protocol Findings

Read from openai/codex at `c9b19de`,
`codex-rs/protocol/src/protocol.rs`. Codex is open source, so its structures are
authoritative rather than inferred -- which settles several questions the corpus
alone left open.

### 7.1 Session Parentage Is Declared

`SessionMeta` declares `forked_from_id`, `parent_thread_id`, `agent_nickname`,
`agent_role` (alias `agent_type`), and `agent_path`. `ThreadSource` distinguishes
`User`, `Subagent`, `Feature(String)`, and `MemoryConsolidation`.

This changes W73's Codex parentage group from "measure field availability before
writing code" to "decode declared fields": the vendor states subagent identity
directly. The measurement question the item posed is answered by the source.

### 7.2 `instructions` Moved

The `SessionMeta` doc comment records that `instructions` was removed and
user instructions now live on `TurnContext`; `base_instructions` holds the
session default. Codess reads `instructions` from `session_meta`, which means it
is reading the older shape. Newer rollouts place it elsewhere -- a decode gap.

### 7.3 Unhandled Rollout Variants

`RolloutItem` declares three variants Codess does not handle:
`InterAgentCommunication`, `InterAgentCommunicationMetadata { trigger_turn }`,
and `WorldState(WorldStateItem { full, state })`. `RolloutLine` also carries
`ordinal: Option<u64>`, an explicit sequence number that would strengthen
ordering beyond file position.

### 7.4 Surface Detail

`SessionSource` includes `SubAgent(SubAgentSource)` and
`Internal(InternalSessionSource)` beyond the `Cli`, `VSCode`, `Exec`, and `Mcp`
variants currently mapped. Codex states more surface detail than Claude's
`entrypoint`, which bears on W93's finding that `surface_kind` is derived from
three different fields and is not comparable across vendors.
