# CrReview

Independent reading of Codess 0.2.0 at CoSchema format 12. It records what
the tree does, where the released documents disagree with the tree and with
each other, and the order in which the remaining defects change an
investigation.

[CoReview](CoReview.md) is the evidence layer under settled rules: why a
bound, a column, or a rejected approach is what it is. [CoTasks](CoTasks.md)
is the only list of open work. [CoPlan](CoPlan.md) describes intended
structure. This document does not add items, close items, or restate those
rules. Where a finding already has an item, the item is named so the work
has one owner. A count written here is either a property of the source or a
figure already recorded in CoTasks; the corpus was not re-counted for this
reading.

## Table of Contents

- [1. Evaluation Basis](#1-evaluation-basis)
- [2. Project State](#2-project-state)
- [3. Direction](#3-direction)
- [4. Register Divergence](#4-register-divergence)
- [5. Silent Session Loss](#5-silent-session-loss)
- [6. Misclassified Outcomes](#6-misclassified-outcomes)
- [7. Common Unit Correspondence](#7-common-unit-correspondence)
- [8. Attribution and Identity](#8-attribution-and-identity)
- [9. Format Policy and Unreadable Archives](#9-format-policy-and-unreadable-archives)
- [10. Packaging and Verification Gaps](#10-packaging-and-verification-gaps)
- [11. Documentation Load](#11-documentation-load)
- [12. Comparison with CoReview](#12-comparison-with-coreview)
- [13. Suggested Order](#13-suggested-order)

## 1. Evaluation Basis

### 1.1 What Was Read

The reading covered the product boundary in [Codess](Codess.md), the
implementation status in [CoPlan](CoPlan.md) section 12, the open register
in [CoTasks](CoTasks.md), the functional rules in [Designs](Designs.md),
the format notes in [CHANGELOG](CHANGELOG.md), and the source that
implements selection, decode, storage, and query. [CoReview](CoReview.md)
was read after that, so its compliance table was a comparison point and
was not the source of the findings in sections 5 through 10.

### 1.2 What Was Checked in Code

These claims were checked against the tree, not against a status paragraph:

| Claim | Where it holds |
|---|---|
| Package version is 0.2.0 | `codess.__version__` |
| Store format is 12, and only 12 is readable or writable | `PRAGMA user_version = 12` in `schema/coschema/sqlite/schema.sql`; `FORMAT_VERSION` and `SUPPORTED_READ_FORMATS` in `schema_contract.py` |
| Mapping conformance runs on the write path | `store._check_mapping_conformance` calls `validate_mapped_event` from `replace_session_events` |
| Incremental skip does not look at the store | `store.should_ingest` compares the vendor fingerprint with `ingest_state.json` |
| An empty decode deletes the stored Session | `replace_session_events` deletes the Session when `session is None` |
| One Codex file is kept per Session id | `codex_source.get_session_files` |
| A Codex suffix outside the gradation vocabulary becomes a resolved variant | `model_names._tokenize` for vendor `Codex` |
| Cursor tool status is `toolFormerData.status` | `adapters/cursor.py`; the file does not mention `additionalData` or `exitCode` |
| Codex `task_complete` is stored as completion | `adapters/codex.py`; the copied payload keys do not include `error` |
| Schema files are found by walking up from the module | `schema_contract.REPO_ROOT = Path(__file__).resolve().parents[2]` |
| Three loss paths are expected failures | `tests/test_hostile_project.py`, `xfail(strict=True)` |

### 1.3 What Was Not Re-measured

No ingest, refresh, or `tools/quality_report.py` run was part of this
reading. Corpus sizes, vanished-Source counts, and per-field tallies are
the ones written in CoTasks, and those sections do not agree with each
other. None of them is treated here as the current corpus. The mechanisms
are properties of the code and survive a change in those counts.

## 2. Project State

### 2.1 What Holds

Codess is a local investigation system with a real pipeline. Three vendors
are selected, decoded, and published as separate SQLite stores. Publication
is transactional. `require_store` accepts only the current format for
reading and for writing, because a store is a projection of vendor Sources
and a format change is a rebuild. Decode is strict about meaning — Actor,
relationship, time, and status are not invented to fill a column — and
tolerant about shape, with the crash-site classes and the mitigation in
[Designs](Designs.md#decode-resilience). Hashing is confined to one module.
The query executor returns bounded, ordered, multi-store results with
provenance. Mapping profiles are enforced at the store boundary for every
Event that carries a `mapping_rule`, in one mode for all three vendors.

The product boundary in Codess is the right one. Codess reads locally
retained harness evidence and exposes a provenance-preserving projection.
It does not estimate prices, recover traffic a vendor never wrote, or
treat a `user` envelope as a human. The unified store in the product
diagram is a query-time merge of Project store sets, which is the physical
layout the code implements. Baseline 1 in CoPlan section 12.3.1 — one
Project, answers that match the vendor record or say they cannot — is
close for the records a decoder is handed and classifies.

### 2.2 What the Product Claim Still Requires

The claim an investigation depends on is stronger than "the decoder does
not crash and does not invent an Actor." It is that a stored row is a
complete and correctly classified projection of what the vendor retained,
that a missing Session is reported, and that a cross-vendor count is the
same unit. That claim is not met. Sections 5 through 7 are the gap.
Baseline 2 — a result a second reader can re-derive and challenge — still
needs the named investigations in CoTasks (W05) and a correspondence
statement for Interaction and Model Turn (W129). External consumption
stays undefined, for the reason CoPlan section 12.3.3 gives: no consumer
has asked for it.

## 3. Direction

The structural program CoReview records — import and SQL boundaries,
publication, hashing, the reporting channel, type-checker adoption — is
largely in the tree. Another round of renames, flag inventories, and
mechanical gates has less effect on an investigation than the defects
below. The useful direction is evidence fidelity, in an order set by what
a wrong or missing row does to a later question.

1. Make omission and deletion visible before the next rebuild. A format
   bump recomputes every store from live vendor files and then refuses the
   previous format. Claude removes records on a retention window. Cursor
   removes index entries while the conversations remain. A rebuild that
   does not record the difference either destroys the only remaining
   record or looks like a successful refresh.
2. Open every file that belongs to a selected Session, and say when a file
   was not opened. Coverage diagnostics describe records a decoder
   received. A rollout segment, an unbound composer, a grouping-directory
   Session, and a Cursor CLI transcript never become
   `unsupported_records`.
3. State what an Interaction and a Model Turn count, with fixtures, before
   any cross-vendor comparison treats them as equivalent executions.
4. Run the named investigations against a live Project after the known
   misclassifications are fixed, so the investigations find the next gap
   and do not spend themselves rediscovering a failed command stored as
   success.

Leave external investigation interfaces (W16) deferred. An interface with
no requester becomes a surface that has to be kept current through every
format bump.

## 4. Register Divergence

### 4.1 Contradictions Inside CoTasks

CoTasks is the sole work list, and it currently describes more than one
project. Which section a reader starts from decides what they will build.

| Section | What it states |
|---|---|
| Active Work | Format 12 is published. W04, W66, and W71 are closed. A hand-written rebuild loop was the wrong tool; `codess refresh` is the operation. |
| Queue | The corpus is at format 12. W05 is unblocked. |
| Open Items | W04, W66, and W71 are planned or postponed. The table still carries closed rows whose blockers are empty, which the document's own removal rule forbids. |
| Corpus Baseline | Format 9, with Session and Event totals that match neither the Active Work narrative nor format 12. The rebuild cost is priced from that table. |
| Stopping Points | Mapping conformance is still described as unequal across vendors. Cursor is described as having no Event-record builder. Configuration unification is described as not begun. |
| Next Two Sprints | Sprint 1 and Sprint 2 are specified as future work. Recently Closed records both as landed, including format 11 and format 12. |
| Resuming | Steps for W96 are listed as the next edits. Recently Closed records those steps as landed. |

The introduction of CoTasks says a figure appears only where it bounds
work, and that a count which only reports a moment is read from a tool
because a number written down is wrong by the next change. The corpus
baseline and the session narratives violate that rule, and they are the
sections a reader uses to decide whether a rebuild is safe.

### 4.2 Documents That Lag the Tree

| Document statement | Tree |
|---|---|
| CoPlan 7.1 and 7.5: runtime mapping conformance is not enforced | `replace_session_events` calls `validate_mapped_event` for every ruled Event. Strict mode raises; diagnostic mode records `mapping_profile_nonconformance`. The comment on the function states that both modes mean the same thing for all three vendors. |
| CoPlan 12.2: the command layer still writes status through roughly sixty direct `sys.stderr` calls | Direct `sys.stderr` use in `src/` is the failure channel, help, and the reporting sinks. |
| CoReview compliance: mapping is partially compliant because conformance is not uniform | Same call as the CoPlan row. The open-findings table still names W04. |
| CoReview derived-values row: an algorithm name in a stored value remains open | Format 12 stores `digest` for the nested manifest key and the emitted value prefix. `hashlib.sha256` remains the spelling of the function, which is the rule CoNames states. |
| CoReview configuration summary says compliant, and the open-findings table says W66 is open | The two rows disagree with each other. `settings` exists and states a precedence. Help text on administrative flags may still be thin; that is a smaller fact than "a default is decided in four places." |

A reader who implements CoPlan 7.1, CoPlan 12.2, or the CoReview open row
for W04 will redo work the write path already does. The remedy is to make
one section in each document the current statement and to delete the
paragraphs that describe the previous boundary. CoTasks's removal rule —
a closed row stays only while an open item depends on it — applied to
Active Work, Stopping Points, Next Two Sprints, and Resuming would remove
most of the contradiction. The corpus baseline should be regenerated from
the registry or removed; a stale format number is worse than no number,
because it prices a rebuild against the wrong contract.

## 5. Silent Session Loss

These paths succeed, or skip, without a Source failure. They are the
defects that can remove the only copy of a Session.

### 5.1 Store Truncation and Incremental Skip

`inspect_sources` calls `should_ingest`. That function returns false when
the vendor file's revision marker matches `ingest_state.json` and `force`
is not set. It does not open the Codess store. A working store truncated
to zero bytes is therefore rebuilt empty, every unchanged Source is
skipped, and the run exits 0.

`tests/test_hostile_project.py::test_emptied_store_is_repopulated` is
`xfail(strict=True)` with that reason. The fix is to validate the store
against its recorded state before honouring the skip: a missing, empty,
or unreadable store is a reason to decode, and the skip reason
`unchanged` is reserved for a store that still holds the Session the
marker describes. W120 step 1. No format change.

### 5.2 Empty Decode as Deletion

`replace_session_events` deletes Events, tool invocations, Model Turns,
and Interactions for the Session, then deletes the Session row when
`session is None`. A Source rewritten to zero decodable records — empty,
or no line that yields a Session — commits that deletion and exits 0.
The run can count `empty_sources` or `malformed_records` and still
publish the loss.

`test_stored_session_survives_source_losing_every_record` is
`xfail(strict=True)` for both an empty body and a non-JSON body. A Source
that previously yielded Sessions and now yields none is a failure, not a
deletion, until an operator accepts the loss. That acceptance is the same
decision as W112: record Sessions and Events gained, lost, and changed,
with the lost identities and the reason, and proceed only under an
explicit policy. Doing the deletion guard without the loss record leaves
the operator unable to tell a vendor prune from a decoder regression.
W120 step 2, closed together with the first slice of W112.

### 5.3 Claude Slug Collision

`path_to_slug` maps the path separator to `-`. `work/a/b` and `work/a-b`
produce one slug. `test_slug_separator_collision_does_not_misattribute_sessions`
is `xfail(strict=True)`: ingesting one Project stores the other's Session
although every record's working directory names the other. Disambiguate
by the working directory inside the records, and refuse the Source when
two live directories share a slug and the records do not agree. W120
step 3. No format change.

This is the same family as the discovery rule already stated for linked
worktrees: the vendor's own path is the attribution, and a derived key
that collides is reported rather than trusted.

### 5.4 Codex Multi-File Threads

A Codex thread can be a base rollout plus segment files that share one
`session_meta.id`. `get_session_files` keeps a single path per id. The
rank is `(root_index, -mtime_ns, path)`, and the lower rank wins.
`get_session_roots` lists the active root first and the archive root
second, so an active file always beats an archive file, and within one
root the newer file wins. The survivor is the newest file in the earliest
root. It is not the newest file of the thread, and every other file is
never read.

CoTasks records the measurement as 3 of 46 threads spanning 2, 2, and 3
files, with 4 files dropped (W116). That count was not re-measured here.
The selection rule is independent of the count: any thread stored as more
than one file loses the files that lose the rank.

Treat the files of one id as one Session. Order segments by the sequence
the vendor states, decode each as a Source of that Session, and
deduplicate records repeated across segments. A fixture thread split
across files is the close condition, plus a re-ingest of the threads that
were measured. No format change. Until that lands, a Codex Event count is
a count of the winning file.

### 5.5 Records the Decoder Is Never Handed

`unsupported_records` and mapping diagnostics describe records the adapter
saw. The following are absent from that report because selection never
opens them. Each is already an item. Together they are one omission class:
a Project can look empty, or a Session can look complete, because the
reader stopped at an index.

| Omission | What the code does | Item |
|---|---|---|
| Codex history with no rollout | `unrolled_history_sessions` counts Session ids and does not decode. The docstring is right that admitting prompts with no Model Turns is a mapping decision. The coverage statement has to reach a report the operator sees, or the Sessions stay invisible. | The audit path in CoPlan 6.7 |
| Cursor composers absent from both indexes | `coverage_report.unbound_composers` counts them. An operator binding is the only way to attribute one. CoPlan 6.4 records 164 composers, 66 with a header and 98 without, as one machine's measurement. | W85 |
| `agentKv` blobs no Session claims | Counted under their own reason. CoTasks records that a `requestId` does not attach them to a composer. | Closed as a mapping decision; the blobs remain unattributed by design |
| Sessions started in a grouping directory | Attributed to the directory the harness started in, which Codess treats as a container, so they reach no store. | W125 |
| Work performed in a sibling Project | Stays on the launch Project. Tool paths are already extracted as Artifacts, which is the evidence a touches-relation would use. | W125 |
| Cursor CLI `agent-transcripts` | Not a Source kind. | W119 |
| Remote-host harness stores | Local vendor roots only. Cursor remote-SSH keeps the conversation locally and the workspace path on the remote host, which is a second shape. | W126 |

W125 steps 1 through 3 need a relation, not a copy of the Events. Keep the
Session on the Project where it started, and record reads, edits, and
commands against each other catalogued Project by longest-prefix match on
locations and aliases. Report container-rooted Sessions in scan and
coverage. Duplicating Events into the sibling store would invent a Session
the vendor did not record.

### 5.6 Hostile Paths Still Expected to Fail

`tests/test_hostile_sources.py` and `tests/test_hostile_project.py` mark
further sites `xfail(strict=True)`. They are an inventory, and a passing
suite does not mean they are fixed. The ones that hide or drop Sessions,
beyond section 5.1 through 5.3:

| Expected failure | Blast radius |
|---|---|
| `get_cc_session_lineage` raises `RecursionError` outside the per-Source handler | The Project fails, including a healthy sibling Source |
| `Path.glob` swallows `PermissionError` on an unreadable Claude Source directory | Ingest reports accepted with `failed_sources=0` |
| Malformed `sessions-index.json` raises outside the narrow catch | The work root fails and every Project under it is dropped from scan |
| `build_session_index` calls `record.get` on a non-dict, and `json.loads` catches only `JSONDecodeError` | One hostile rollout fails the index before the Project loop |
| Unreadable Codex rollouts are skipped with `continue` | The Session is invisible and the run succeeds |
| A FIFO named `rollout-*.jsonl` is opened with no regular-file check | Scan and ingest block |
| A Cursor workspace with a corrupt `workspace.json` is skipped | Exit 0, no diagnostic; scan counts the same file as malformed |

W103 asks for a rescan of the five crash-site classes beyond the fuzzed
adapters. The adapter fuzz is in place. These rows are the source-access
layer the item names, and they are already located. Clearing the strict
failures that drop a sibling Project or block on `open` is the rescan.
A new generative fuzz of the same adapters will not find the slug
collision or the empty-store skip; those are selection and publication
defects, and the tests that name them are the close condition.

`--no-progress` detaching the sink that also carries warnings, so a failed
run exits 1 with no reason, is an operator-channel defect in the same
suite. It does not delete Sessions. It does make the deletion paths harder
to see when they stop being silent.

## 6. Misclassified Outcomes

The query surface will return these rows with a status and an Actor. An
investigation of failures, denials, model output, or token use is wrong
by them, and nothing in the result says the classification was narrowed.

### 6.1 Cursor Tool Status

`adapters/cursor.py` reads `toolFormerData.status`. The map sends
`completed` and `complete` to `succeeded`, `error` and `failed` to
`failed`, and `userDecision == rejected` to `denied`. Names that start
with `mcp-` or `mcp__` get a second check, `application_failure_evidence`
on the result body. A terminal tool result whose failure lives in
`additionalData.status` and `exitCode` stays `succeeded`, because those
fields are not read. CoTasks records 133 such results on one machine
(W119). The asymmetry is inside an otherwise careful mapper: the MCP
path already accepts that a completed transport can carry a failed
application.

Derive the common status from the exit evidence when it is present. A
non-zero exit code is `failed`. Keep the vendor status string in
`source_status`, which the code already does, so the correction does not
discard what Cursor wrote. No format change. The close condition is a
fixture whose `toolFormerData.status` is `completed` and whose exit code
is non-zero, stored as `failed`.

### 6.2 Cursor Token Counts

`tokenCount` of `{0, 0}` is the value Cursor writes when it did not
measure usage. Storing it as a measured zero makes a sum unable to
distinguish "the vendor measured nothing" from "the vendor recorded no
usage field." CoTasks records that shape on 99.7% of bubbles in one
sample (W119). Store an all-zero count as absent. A recorded zero that
a vendor measured on purpose is a different fact and stays zero; Claude
and Codex already have that case, which is why format 10 kept a recorded
zero. The Cursor bubble count is the absent case. W93, which asks what a
utilization report includes, should wait until this column means one
thing. A policy on top of a zero that is usually missing will report a
precise and wrong total.

### 6.3 Claude API Errors and Denials

`isApiErrorMessage`, `apiErrorStatus`, and `error` are not mapped, so an
API error reply is stored as model output. CoTasks records 68 such
records on one machine (W118). Permission denials are matched by text
rather than `toolDenialKind`. `interrupted` is retained and does not
become a status. The record kinds `relocated`, `content-replacement`,
`forkedFrom`, and `history-suppression` have no mapping.

Map the error fields to a status or a kind that a `--status failed` query
selects, and map denial and interruption the same way. Add the four
record kinds to the mapping contract, or declare them ignored with a
reason the coverage report shows. An API error counted as
`message.response` corrupts the comparison Codess is for: model behaviour
across harnesses. That is a higher-severity gap than an unmapped product
state with no query consumer. The standing retention rule — decline a
mapping that has no query need — does not apply to a field that changes
the Actor or the status of a row that is already emitted.

### 6.4 Codex Task Completion

Current paginated rollouts no longer write the `*_end` records the older
branches decode. `event_msg.item_completed` carries a typed
`CommandExecution.exit_code`. `token_usage_record` carries per-response
and per-turn usage and is unread. Cache-write tokens are set to 0 where
the field exists. `task_complete` is emitted as `lifecycle.complete`.
The metadata copied from the payload lists turn id, timestamps, duration,
context window, and collaboration mode. It does not list `error`, so a
failed turn is stored as a completion (W117).

Prefer the typed exit code over the output-text pattern. Read
`token_usage_record`. Map `task_complete.error` to a failed lifecycle.
Join `item_completed` to its call once the id prefix is shown to match;
CoTasks notes an `exec-` prefix that matched no `call_id` on one machine,
so the join is a measurement before it is a mapping. No format change is
expected. The close condition is a paginated fixture, not a replay of the
old `patch_apply_end` branches.

### 6.5 Model Names

`model_names.resolve` keeps the vendor string in every case and leaves
derived fields null when the name is not recognized. That rule is stated
in the module and is the right one. Two paths weaken it.

The alias table is consulted with no vendor. The Codex and Claude
tokenizers run only when the caller passes the adapter key. A label that
appears in a log without that key stays unresolved even when a tokenizer
would have parsed it. `schema/model-aliases.json` contains `claude-opus-5`
and does not contain `gpt-6-astra`, `gpt-6-sol`, or `claude-opus-5-5`.

When the vendor is `Codex`, `_CODEX` matches `<line>-<version>[-<suffix>]`.
A suffix in `GRADATIONS` becomes the gradation. Any other suffix becomes
`variant`, and the result is `resolved=True`. `gpt-6-astra` therefore
resolves as line `gpt`, version `6`, variant `astra`, with no gradation.
The module docstring says a name that resolves to nothing is recorded
unresolved and never guessed. A free suffix stored as a variant is a
guess. `GRADATIONS` itself is `opus`, `sonnet`, `haiku`, `fable`,
`mythos`, `sol`, `terra`, and `luna`. Astra is a capability grade in the
same position as sol and is absent from that set, so the tokenizer both
accepts it and files it in the wrong slot.

W113's close condition is the right one: every label in the current
vendor logs resolves, an unknown suffix stays unresolved, and gradation
ranks are scoped per generation. New columns for tier, context window,
and platform are a format bump. Batch that bump with the loss-accounting
work in section 9, and do not bump for the columns until an unknown
suffix stops resolving. The breaking change to `--model-line` for
letter-series lines is real and belongs in the changelog of that format.

## 7. Common Unit Correspondence

### 7.1 Interaction and Model Turn

The glossary says a Model Turn is one execution where the source supports
that boundary, and it warns that the current Codex grouping must not be
counted as verified executions. `_prepare_event_groups` implements a
narrower rule than the warning suggests, and the warning is the accurate
description.

A direct human Event opens a new Interaction at confidence `0.8` with
`boundary_source = "mapping"`. Model activity with no preceding human
Event opens an autonomous Interaction at confidence `0.5` with
`boundary_source = "inferred"`. For a non-Cursor Session, Model Turns are
keyed by `metadata.source_turn_id` when present, and the same id reuses
the first turn row. The turn row is inserted with the Interaction that
was current at the first Event of that id. A later human Event inside the
same source turn opens Interaction 2. The following model Event still
carries the original `model_turn_id`, whose row points at Interaction 1.

That is the steered-input case W129 describes. Codex's own protocol
defines a turn as a collection of items and allows several sampling
requests under one turn id, including tool follow-up and steered input.
The column faithfully retains the vendor designator. It does not count
model executions. Newer `session_meta` also carries both a thread `id`
and a root `session_id`. Codess uses the thread id for the Session.
Those are different scopes.

W129's order is the right one. Specify the source unit behind Project,
Session, Interaction, Model Turn, Event, Actor, tool operation, and model
configuration. Test boundary, membership, and cardinality on fixtures
before any storage change. The first two fixtures are a Codex turn with
two sampling requests, and the same turn with a steered human Event
between them. Determine whether real adapter output reaches the mismatch
the direct-store fixture already shows. Record each correspondence as
faithful, recast, approximate, or unsupported. A relabelled contract may
need no format change. Representing model requests separately would.
This item does not authorize a rebuild or a reinterpretation of stored
rows that no longer have their source bytes.

### 7.2 Cursor Turn Key

For `session_source == "Cursor"`, the turn key is the current Interaction
and `boundary_source` is `inferred`. There is no vendor turn id on that
path. `requestId` on a user bubble and `usageUuid` on an assistant bubble
are different fields. CoPlan 6.6 records that no bubble carries both, and
that 664 of 1,505 `requestId` values in one measurement equalled a
`usageUuid` within the next five bubbles. Mapping them to one column
would erase the direction. Leaving them unjoined means a Cursor Model
Turn is "the model Events inside one Interaction," which is a Codess
grouping. Say that in the query contract so a cross-vendor turn count
names two constructions.

### 7.3 What a Cross-Vendor Count Currently Means

CoPlan 6.5's Event-kind table is evidence about the vendors for the
records that were decoded. It is not yet a comparison of equivalent
units. Messages and tool calls are present for all three vendors, and
every result the table counted linked to a call. Codex calls without
results are an aborted-turn condition. Cursor's duplicate results were
called a decode defect in that section and are also described, elsewhere
in CoTasks, as addressed by the `duplicate_of` column at format 10.
Those two statements should be reconciled against the current stores
before the table is cited. Lifecycle is a real asymmetry: Codex emits
start, complete, and abort; Claude emits a vendor lifecycle kind; Cursor
emits none. Whether Cursor records task start anywhere is still an open
decode question.

Until W129's fixtures exist, a report that ranks harnesses by Model Turn
or by human prompt is comparing `source_turn_id` reuse, an inferred
Interaction boundary, and Claude's `parentUuid` chain. The role-versus-Actor
measurement in CoPlan 6.6 should stay in force beside any such report:
about a third of one Codex store and a fifth of one Claude store carry a
`user` envelope around tool or harness content. The classifier's refusal
to copy the envelope into `actor_kind` is a strength. Queries written in
SQL against `source_role` bypass it.

## 8. Attribution and Identity

### 8.1 Launch Directory

A Session is attributed to the directory the harness started in. Two
patterns follow, both recorded as W125. A harness started in a grouping
directory records Sessions under a path Codess treats as a container.
A Session started in one Project that reads and edits a sibling is stored
on the launch Project. CoTasks records one catalogued Project with no
Sessions of its own because its work, including a Codex rollout, was done
from two siblings, and four grouping directories named in prompt history.
The signals are already in the records: Claude writes a working directory
on each record, Codex writes one per turn and per command, Cursor records
multi-root folders and tool paths.

The relation in section 5.5 is the design. Query inclusion of Sessions
that touched a Project is a later step, after the relation exists and can
be checked. Attributing a container-rooted Session to whichever Project
dominates its paths is an inference and stays optional.

### 8.2 Registry Authority

`_resolve_project_id` consults four sources, in order: the registry
binding index, the in-project `project.json`, a catalog entry that
already claims the path, and a new identity. The docstring states why the
registry is first. The registry outlives a cleaned, re-cloned, or
restored working tree. A disagreement between the in-project file and the
registry is reported, and the registry wins. A mint is reported.

CoTasks W14 says steps 1 through 5 are in the code and have not been
applied to the operator registry, as a deliberate hold. An absent index
is an empty map, so resolution falls through to the in-project file. On a
registry that has not been backfilled, a restored binding can still mint,
and a reviewed `worktree_of` disposition on the older entry is not carried
onto the new one. The code change and the operator apply are different
closes. The apply is `backfill_binding_index`, which derives the index
from catalog locations and does not overwrite a path a live entry already
claims. Run it when the operator accepts the hold, and check afterwards
that no path is claimed by two Projects.

### 8.3 Cursor Fields Read and Not Stored

`ItemTable` composer headers are read as a qualifier. `unifiedMode`
(`agent` or `chat`) and the workspace path are available there. The
composer-header table holds a storage hash where this document holds a
path. Neither field reaches a column (W106). A composer present only in
that UI document is correctly not selected. The read landed; the store
waits on a format bump. Batch the columns with whatever bump section 9
requires, so `interaction_mode` does not force a rebuild of its own.

## 9. Format Policy and Unreadable Archives

### 9.1 Single Readable Format

`SUPPORTED_READ_FORMATS` is the current format only. The comment in
`schema_contract.py` states the decision: widening the read set asserts
that an older store still answers queries correctly, which is true only
when no column a reader depends on changed meaning. That is a coherent
rule for a projection.

It is also how a store that has become the only record of pruned vendor
Sessions becomes unreachable at the next bump. CoTasks W128 records
archived stores at formats 0, 2, and 4 whose transcripts are gone. A
separate note in the same document describes one format-4 store held
aside, read-only, because a rebuild that reached it would have destroyed
the only record. Current code will not open it. The recovery path is a
read-only importer per archived format that projects Sessions and Events
into the current layout, marks them recovered with their origin store and
format, and does not overwrite a Session a live Source still supports.
The marker can be the availability state W123 has not designed yet. Raw
capture of vendor bytes is useful regardless of that decision, because a
rebuild can then re-decode one interpretation. Carrying rows forward from
the prior store mixes two decoders and is the alternative W123 correctly
disprefers.

### 9.2 Snapshot Roles

`CODESS_KEEP_SNAPSHOTS` defaults to 3 so one format migration leaves a
prior generation. Two consecutive bumps consume that span. Retention
still decides by generation count. After a format change the count says
rollback copies exist, and `require_store` refuses them. Pin protection
is inferred from catalog files at a configured location, so it lapses
when those files are elsewhere. Publication trim and `storage prune`
can return different verdicts for the same snapshot (W115).

One classifier should assign each snapshot a role: current, rollback
(the newest readable, up to the keep count), pinned, archive (one
unreadable prior per format, held until the W123 decision), sole record
(a Session present in no newer snapshot), or expendable. Only expendable
snapshots are deleted. A pinned snapshot is reported as held. This has
no format change until the sole-record mark needs a column. Build it
after W112 can say what a rebuild lost; a role called "sole record"
without that comparison is a guess.

### 9.3 Rebuild Designator

`codess refresh --designator included` is the right corpus operation for
a routine refresh. It preflights every selected Project, writes a
receipt, and honours catalog exclusions. A linked worktree annotated
`worktree_of` is correctly omitted, because refreshing it would ingest
one repository twice.

A format migration is a different operation. The worktree's published
store is format N and the new code reads only format N+1. Omitting it
strands a store (W104). The procedure in the README documents one
command. The designator that command uses does not name every published
store. Add a designator that selects every published Project store set,
including a worktree, and use it only for a format rebuild. Keep
`included` for routine refresh. No rebuild is required to add the
predicate. Document the two commands as two operations so the next
format note does not reuse the refresh designator.

W112 is the gate in front of either command. Before promotion, compare
the staged store with the one it replaces, per Source: Sessions and
Events gained, lost, and changed, with the identities of lost Sessions
and the reason (Source absent, Source shorter, decode difference).
CoTasks records, as one machine's measurement at format 12, that 377 of
380 Claude Sessions were older than the vendor's 30-day default and
survived because the operator raised the retention window, and that
several Sources of one Project had shrunk since the previous publication.
`tools/project_inventory.py` sees path existence. A path that exists and
is shorter is invisible to it, and so is a composer index that dropped
entries while the bubbles remain. The loss record is what distinguishes
those. The proceed policy is `ask`, `record`, or `refuse`, and it is
persistable. `refuse` is the default until an operator has seen one
report.

W105 is the vendor-specific half. Claude needs a cadence against its
age prune. Cursor needs the unbound set read, which depends on the W85
binding. Nothing in the current refresh measures how close a Project is
to the next Claude sweep. That is the piece that prevents loss. The
other pieces explain a loss after it happened.

## 10. Packaging and Verification Gaps

### 10.1 Schema Location

`schema_contract.REPO_ROOT` is two parents above the module file.
`model_names.ALIAS_PATH` and `helpers.DISCOVERY_POLICY_PATH` use the same
walk. An editable checkout resolves to the repository `schema/` directory.
A non-editable install does not ship that directory as package data
(`pyproject.toml` declares no package data), so contract load, model
resolution, and discovery policy fail off a wheel (W109). CoReview's
packaging row checks that the installed command dispatches through
`codess.project:console_main`. Dispatch succeeds and the contract files
are still missing. Ship `schema/` as package data, and resolve the path
from the installed package with the repository walk as a fallback for a
checkout. A test that imports from an installed tree without the
repository beside it is the close condition.

### 10.2 Previous-Format Fixture

Tests build stores under the current contract. A rename of a key that
bootstrap reads — `current.json`, a snapshot manifest, an operator
`source-links.json` — is invisible to that suite. Format 12 demonstrated
the class: renaming `manifest_sha256` on both the read side and the write
side made every published Project unrebuildable by the only release that
could rebuild them, and the failure happened while resolving the pointer,
before any store was touched. The repair was to accept both spellings on
read for the documents that bootstrap a rebuild. The suite stayed green
through the breakage because every fixture already carried the new key.

W122 asks for `MAJOR.MINOR` versioning, a change record, and a test that
builds a store at the previous version and exercises the path. The test
is the part that would have caught the digest rename. A version scheme
without a previous-format fixture repeats the class under a new numbering.
Keep one fixture store, or one `current.json`, from the previous format
in the suite, and run the rebuild read against it whenever `user_version`
or the contract digest changes. The fixture contains no Session content,
so it does not become an operator corpus.

### 10.3 Load and Fuzzing Scope

The load tier is three tests of selection and attach limits. CoTasks
records a real Project at about 90,000 Events and about 600 MiB.
`tools/workload_bench.py` times store writes and does not decode, and it
runs outside the suite (W121). The query merge holds selected stores in
process. A memory ceiling, a Cursor read under a held write lock, and a
scan across many Projects are the measurements that would tell an
operator whether the unified query surface survives the corpus they
have. They are second to the fidelity work. A fast wrong store is the
worse outcome.

Adapter fuzz covers the five crash-site classes in Designs. It does not
cover `build_session_index`, scan's index walk, or publication's
interaction with `ingest_state.json`. Section 5.6 is that list. Extend
the hostile suite there; do not lower the strictness of an `xfail` to
make the suite green.

### 10.4 Literal Search and Redaction

Search is a bounded literal match. The investigations W05 names — where
an instruction first appeared, whether a short prompt was human — fail
open when the instruction was compacted, split across tool arguments, or
removed by redaction. That is a product limit the query help can state
on the search command. It is not a reason to add fuzzy or embedding
search. Designs already refuses similarity as identity. W05 should
record each miss as a finding with the predicate that could not express
it.

`--redact` applies to stored Session content and vendor evidence in Event
metadata. Raw capture keeps Source bytes unredacted. A registry in
capture mode is not made shareable by the flag. The README states this.
It remains easy to miss because the flag's name describes the stored
projection. The raw-evidence procedure is the place an operator looks;
the capture command's own help should repeat the one sentence.

Integrity checks detect accidental mismatch. They are not a defense
against a writer who can rewrite the database and its verification
metadata. `CODESS_NO_CONTRACT_CHECK` is the deliberate bypass for a
recovery, it warns, and the store records `contract_override`. Leave
that as an operator action. Do not widen `SUPPORTED_READ_FORMATS` to
make the bypass unnecessary.

## 11. Documentation Load

CoTasks is on the order of several thousand lines. CoReview is on the
order of three thousand. Both state a retention rule: keep the rule and
the measurement that makes it checkable, drop the session narrative and
the count that only reports a moment. Both keep the narrative. CoReview's
ingest-extraction increments and its machine inventory are the review's
own examples. CoTasks's Active Work, Resuming, and Next Two Sprints are
the task list's.

The effect is operational. The open-item table, the queue, and the item
bodies in the second half of CoTasks are where a defect is actually
specified. A reader who stops at Active Work or at CoReview's compliance
summary will schedule closed work and miss sections 5 and 6. AGENTS.md
already forbids transient history in a released document. Apply that rule
to these two files as a documentation change of its own, separate from
any decode work, so the next format bump does not append another rebuild
diary.

W70 is the standing item for re-partitioning documents. The concrete cut
for the register is: one current-state section whose format number is
read from `schema_contract.FORMAT_VERSION`, an open table that contains
only open items, and item bodies that keep the condition, the work, the
close evidence, and the cost. Move the rebuild narratives that justify a
standing rule into CoReview as the rule, which is what CoReview's
introduction says it is for. The format-12 bootstrap-read rule is the
pattern: the rule belongs in CoNames and in a short CoReview entry; the
account of the failed first attempt does not need to live in three
sections of CoTasks.

Operator procedures that invoke `python tools/<script>.py` work from a
checkout and depend on import-path insertion (W114). Several scripts
duplicate a `codess admin` operation and have drifted. Split `tools/`
into operator subcommands and developer checks after the fidelity fixes,
not before. A procedure that the README tells an operator to run before
a destructive rebuild — `tools/project_inventory.py` — should stay
available as a command the installed package can run, which is the same
packaging fact as section 10.1.

## 12. Comparison with CoReview

CoReview was read after the tree. It is accurate for the system it
examined. It is not the current defect list.

### 12.1 Where the Review Still Holds

The review's method — entry points, import and SQL ownership, contract
hashes, publication, and a preflight decode of live Sources — settled
rules the tree still follows.

Vendor SQL for Cursor lives in `cursor_source`. Adapters do not open
SQLite. Derived digests go through `hashing`. Unknown records become
diagnostics rather than guessed categories. A vendor `user` envelope is
not a human, and CoPlan 6.6's measurement is the reason. Integrity checks
are described as mismatch detection. Dead code stays when it has a
consumer, or is the inverse of something with one, or is a boundary a
test exercises. The retention rules at the top of CoReview are the right
standard for both review documents. Real-source validation established
that the sampled envelopes decode and that a version skip-list would
exclude nothing in the range that was surveyed. Preserve the mechanism
that validation named: an unrecognized shape becomes `unsupported_records`.
Do not replace it with a version gate.

The open rows that are still open are source-turn correspondence (W129)
and Project identity as an operator apply (W14). Query-contract parity
tied to real investigations (W05) is still the right acceptance test for
the executor. The executor itself is built.

### 12.2 Where the Review Lags the Tree

| CoReview | Tree at format 12 |
|---|---|
| Mapping conformance is not enforced uniformly. Open finding W04. | `validate_mapped_event` runs inside `replace_session_events`. |
| Configuration fragmentation is an open finding, 172 flags and four places a default can be decided. The summary row also says configuration is compliant. | A settings table states one precedence. The summary and the open row should be rewritten from the settings module, not left as a pair. |
| An algorithm name in a stored value remains open. | Format 12 moved the stored spellings to `digest`. |
| Operational reporting fragmentation is resolved. | This row matches the code. CoPlan 12.2 does not. |
| Packaging is compliant because the console entry dispatches. | The contract, aliases, and discovery policy are repository-relative paths. |
| Test observability is resolved because child processes are measured. | True for coverage attribution. The strict expected failures in section 5.6 are a different fact: they are measured and still failing. |

Mechanical enforcement in CoReview lists mapping-profile conformance over
emitted fixtures as still owned by W04. The write-path check exists. What
remains, if anything, is conformance of fixtures the adapters emit in
tests, which is a smaller item and should be restated that way or closed.
Transaction-failure tests at each replacement and publication edge are
listed as unowned. They belong with the W120 deletion cases: a test that
the replacement rolls back is the pair of a test that an empty decode
does not delete.

### 12.3 What the Review Method Does Not See

The preflight decode asked whether classification of emitted Events was
internally inconsistent, and whether an unknown shape was counted. It did
not ask whether every file of a Session was opened, whether a successful
status was the vendor's application status, or whether a rebuild would
delete Sessions. Dropped rollout segments, unbound composers, API errors
stored as model text, and failed commands stored as succeeded do not
increment `unsupported_records`. Absence is not a diagnostic when the
reader never opens the file.

That is why sections 5 and 6 are missing from CoReview's open-findings
table. They accumulated later in CoTasks item bodies. The compliance
summary has not been updated to point at them, so a reader who treats
CoReview as the review of record will conclude that the remaining work is
conformance, flags, and investigations. The remaining work that changes a
result is selection, status, and loss accounting. Update the open-findings
table when those items close. Until then, this document is the pointer
from the structural review to the fidelity gaps.

## 13. Suggested Order

Each step leaves the suite green and does not require a format bump unless
the step says so. The queue in CoTasks ranks W103 and W05 first. The
order below uses a different criterion: a wrong or deleted Session
outranks a crash class the hostile suite has already named, and an
investigation run on known-bad status spends itself confirming this
document.

1. **Stop exit-0 deletion.** Fix the three strict failures in
   `test_hostile_project.py`: emptied store, Source that loses every
   record, slug collision. Close evidence is those tests passing without
   the `xfail`. W120. No format change.
2. **Decode every file of a Codex thread.** Change `get_session_files` so
   one id retains its segments, ordered and deduplicated. W116. No format
   change. A Codex count is incomplete until this lands, so it precedes
   any investigation that uses Codex Events.
3. **Record what a rebuild drops, and add a designator that selects every
   published store.** W112's comparison before promotion, W104's
   designator, W105's Claude cadence. Default the proceed policy to
   `refuse`. No format change for the report. Do this before the next
   contract bump, including the model-name columns.
4. **Correct status and content that are already emitted.** Cursor exit
   status and all-zero `tokenCount` (W119), Claude API errors, denials,
   and interruption (W118), Codex `task_complete.error` and typed exit
   codes (W117). Fixtures are the close. Token and status fixes change
   query results on the next ingest; say so in the changelog. Leave W93
   until a Cursor zero means absent.
5. **Write the correspondence fixtures.** W129, storage unchanged. The
   query contract states which units a row counts. Cross-vendor Model
   Turn comparisons wait on this statement.
6. **Run the named investigations.** W05, against current-format stores,
   after steps 1 through 4 so a failed command is no longer returned as
   success. Each gap becomes a finding with the predicate that could not
   express it.
7. **Apply identity, then attribute work that never reached a store.**
   Backfill the binding index (W14) when the operator ends the hold.
   Report container-rooted Sessions and sibling-Project touches (W125).
   Keep unbound composers visible and bind only on an operator statement
   (W85).
8. **Then the format bump, if steps 3 and 6 produced columns.** Model-name
   resolution that refuses an unknown suffix (W113), `interaction_mode`
   and workspace path (W106), recovered-row marker if W123 has a design
   (W128). One bump, preceded by the W112 report. The previous-format
   fixture from section 10.2 lands in the same change so the bump cannot
   repeat the digest-key failure.
9. **Clear the remaining strict hostile failures** that fail a work root,
   skip an unreadable rollout, or block on a FIFO (W103). Packaging of
   `schema/` (W109) can proceed any time; it is independent and it is
   what makes an installed command able to load the contract those tests
   check.
10. **Reconcile the register.** One current-state section, open items
    only, narratives reduced to the rule they established. W70. Do it as
    its own change so it is reviewable. Snapshot roles (W115) and load
    measurements (W121) follow the loss record and the correspondence
    statement. Split `tools/` (W114) when operator procedures no longer
    need a checkout to run the inventory that gates a rebuild.

Steps 1 through 4 are the fidelity work. Step 5 is what makes a
comparison mean a unit. Step 6 is the acceptance test the query surface
has not had. Steps 7 through 10 are real and they wait, because each of
them is safer once a rebuild can say what it deleted and a status query
returns the vendor's outcome.
