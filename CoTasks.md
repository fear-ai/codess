# CoTasks

CoTasks is the sole list of open Codess engineering work. It contains only
incomplete items: a completed item is removed and its outcome recorded in
[CoReview](CoReview.md), so this document states what is left rather than what
happened.

Identifiers are assigned once and never reused or renumbered. A gap in the
sequence means an item closed; a retained report or a code comment naming an
identifier that is absent here is naming closed work.

Each item states the same four things: what the work is, what evidence closes
it, what blocks it, and what it costs. Analysis that justified an item belongs
in [CoReview](CoReview.md); what an item needs to be built and checked belongs
here.

**A count here bounds work.** A figure appears only where it
bounds the work -- which functions a change touches, how many call sites a rule
must reach -- so it can be re-derived from the code and used to tell a finished
item from an unfinished one. Each states how it was obtained. Figures that only
report a moment, such as a current error total, are not recorded here: they are
read from `tools/quality_report.py` when needed, because a number written down
is wrong by the next change and cannot close an item. No item carries a duration
or an effort estimate; ordering is by dependency and by rebuild cost, both of
which are checkable.

## Table of Contents

- [Status Vocabulary](#status-vocabulary)
- [Open Items](#open-items)
- [Queue](#queue)
- [Dependencies and Batching](#dependencies-and-batching)
- [Item Detail](#item-detail)
- [Maintenance Directions](#maintenance-directions)
- [Deferred Directions](#deferred-directions)

## Status Vocabulary

| Status | Meaning |
|---|---|
| **Planned** | Accepted, unblocked, and ordered in the queue. |
| **TODO** | Accepted but unscheduled: no dependency blocks it and nothing waits on it. |
| **Needs decision** | Blocked on a judgment, not on effort. The unanswered question is named on the item. Doing the work first would encode the wrong answer. |
| **Postponed** | Deliberately outside the current phase. The reason is recorded on the item. |
| **Withdrawn** | Examined and rejected. Retained so the reasoning is not rediscovered. |

Priority states how much an item matters. It does not say when the work happens
or what blocks it; the queue says that.

## Open Items

Ordered by identifier, which is stable. Read the queue for what to do next and
[Item Detail](#item-detail) for scope and evidence.

| ID | Priority | Status | Work | Blocked by |
|---|---|---|---|---|
| W04 | High | Planned | Shared candidate-record contract, enforced at the decode boundary | -- |
| W05 | High | Planned | Run named real investigations against the query surface | -- |
| W14 | Normal | TODO | Require or mark Project identity for direct library writes | -- |
| W16 | Normal | Postponed | Evaluate external investigation interfaces | No consumer |
| W17 | Normal | Postponed | Expand cross-Project analysis inputs | Baseline 2 |
| W35 | Low | Postponed | Resolve the validation-fixture inventory | -- |
| W43 | Low | Withdrawn | Table-drive request validation | -- |
| W50 | Normal | Planned | Reconcile schema names with defined terminology | Batches with W51 |
| W51 | Normal | Planned | Resolve source-identity naming and suffix rules | Batches with W50 |
| W55 | Normal | Planned | Unify text and record parsing across the decode layer | -- |
| W64 | Normal | Planned | Decide and enforce the typing posture | -- |
| W65 | Normal | Planned | Consolidate remaining relay parameter groups | W04 (partly) |
| W66 | High | Planned | Unify configuration into one subsystem | -- |
| W67 | Normal | Planned | Move relay fields into the objects that carry them | -- |
| W70 | Normal | Planned | Re-partition documentation; remove cross-document redundancy | -- |
| W72 | Normal | Planned | One Event-record builder per adapter; Cursor has none | -- |
| W71 | Normal | Planned | Adopt the reporting facility in the command layer | -- |

## Queue

One ordering. The reason for each position is a dependency or a stated cost,
not a preference.

| Rank | Item | Why here |
|---|---|---|
| 1 | **W05** | The only item whose output is evidence about whether the query surface answers real questions rather than machinery that supports them. Needs no rebuild: format-6 stores exist and are audited, so the work starts against current data. |
| 2 | **W04** | Structural, and coverage reporting states loss against exactly the profiles it enforces -- a report built against unenforced profiles attests to nothing. Baseline 2's substance. |
| 3 | **W50 + W51** | The naming resolutions format 6 did not carry. Both are wire-format, so they land together as one rebuild or they cost two. |
| 4 | **W66** | The largest structural item, and now the prerequisite rather than the sequel: W67's objects are built at the command adapter from values a setting declaration owns, so declaring each setting once must come first or the object's constructor encodes the current duplication. |
| 5 | **W67** | Follows W66 directly and is mechanical once it lands: each relay already has an object to take, the measurement separating a relay from a builder is written down, and the five shared parameters are the same subset `ChildInvocation` carries. |
| 6 | **W64 + W65** | W65's record-context cluster is adapter signatures, so consolidating before W04 rewrites them twice. W64 no longer waits on W04 -- what remains after the naming pass is dominated by optional-narrowing, which is what `strict_optional` decides -- but it is cheapest once the signatures have settled. |

**Not queued**, each for a stated reason rather than for lack of room:

| Item | Why not queued |
|---|---|
| **W14** | Independent. No item blocks it and none waits on it. |
| **W16** | No consumer has asked for external interfaces, and an item nobody is waiting for does not belong in an ordered queue. |
| **W17** | Deferred to Baseline 2. Specifying a cross-Project surface against a decode W04 has not enforced would fix it against a surface still changing underneath. |
| **W35** | No longer gates anything a store does; it is now a question about what the released set should contain. |
| **W43** | Withdrawn on inspection. Retained so the analysis is not repeated. |
| **W55** | Correctness-neutral, so it batches with anything and blocks nothing. |
| **W70** | Documentation only, and continuous enough that queuing it would imply an end date it does not have. Do it alongside whatever item touches a document. |

## Dependencies and Batching

**W50 and W51 must land together.** Both rename stored columns, and each alone
owes a full rebuild of every Project from vendor Sources -- Codess never migrates
a store, because the store is a projection and the way to change a projection is
to recompute it. Landing them separately costs two rebuilds for one result.

**What a rebuild costs.** A wire-format change is not an `ALTER TABLE`.
`require_store` accepts only the current format, for reading as well as writing,
so every `.codess` store on a machine is unreadable by the new code until its
Project is reingested. Concretely: install the new contract, `codess ingest
--force` every Project, republish -- once per Project on the machine, regardless
of how many columns the format changed. That is the argument for batching: the
cost scales with the number of Projects and not with the size of the change, so a
change that is ready should not wait, and a change that is not ready should not
force the batch to wait for it.

### Corpus Baseline

The scale a rebuild is paid against, and the runtime it costs. Both are read
from the operator's own registry and refresh receipts, so both are re-derivable
and both are expected to move as work is ingested -- they are a status of the
current baseline, not a property of the system.

| Measure | Current | Source |
|---|---|---|
| Published Project store sets | 30 | `~/.codess/projects/*/current.json` |
| Sessions | 635 | `SELECT count(*) FROM sessions` across published stores |
| Events | 329,750 | `SELECT count(*) FROM events` across published stores |
| Store bytes | 2,333 MiB, largest set 560 MiB | Snapshot directory sizes |
| Ingest rate | ~900 Events/s | Refresh receipt: 76,055 Events in 83.7 s, one Project, apply stage |

**What the rate is good for.** A full-corpus rebuild is the ingest rate against
the Event count, so the current corpus is on the order of six minutes of
machine time, plus per-Project publication overhead. That is the figure to
weigh when deciding whether two wire-format changes batch: the cost is real but
small, and the reason to batch is that it is paid once per format and scales
with Project count, not that any single rebuild is expensive.

**The rate is one measurement.** It comes from one Project on
one machine at the apply stage. A Project dominated by Cursor bubbles or by very
large tool outputs will differ; re-read the receipt rather than trusting this
number if the answer matters.

**W04 precedes the typing and signature work.** W04 changes adapter signatures
and the decode boundary. W64's strict-flag decision and W65's record-context
group both target that boundary, so either one done first is done twice.

**W04 also precedes the naming sweep.** Applying the subject-word and
general-word naming rules to existing identifiers is a wide diff with no
behavioural content, so it waits for the signatures W04 rewrites rather than
touching them twice.

### Working Order

One kind of change at a time, each validated before the next begins. The queue
gives the ranking; this gives the discipline, and each rule exists because its
absence produced a defect:

1. **Commit one kind of change before starting another.** Several kinds in one
   diff is more than one reviewable change, and it makes a later bisection
   harder. Each row of the stopping-point table below is a defensible commit
   boundary.
2. **Finish a kind before starting another.** The recurring defect is a change
   of one kind exposing an unrelated one and both being pursued at once -- which
   is how a rename reached a call site it should not have.
3. **Run `tools/quality_report.py` before declaring a kind complete.** It gates
   ruff and mypy against recorded ceilings and has caught regressions the test
   suite did not.

### Stopping Points

Where partly-done work stopped, so an unfinished item is visibly unfinished
rather than mistaken for untouched. None of these is half-applied: each is
either not started or has a stated boundary.

| Work | Stopping point | Item |
|---|---|---|
| Naming convention applied codebase-wide | Enforced for the two cases a checker catches, and both now report zero: builtin shadowing (ruff `A`) and a name rebound to a different type (mypy `assignment`). The subject-word and general-word rules are **not** applied to existing names, which is a wide diff with no behavioural content. | W64 |
| Relay parameter consolidation | `run_ingest` converted as the worked example. Five further relays identified and untouched. | W67 |
| Configuration unification | Measured and not begun. | W66 |
| mypy strict flags | The count was reduced by repair rather than reclassification. Which flags to enable is undecided. | W64 |
| Record-context parameter group | Identified; blocked behind W04 because it changes adapter signatures. | W65 |
| Docstring summaries (`D205`) | The rule is selected and its 111 findings are a recorded ceiling, not zero. Four docstrings in `field_state` were rewritten as the worked example; the rest fall as files are edited. | -- |
| Command-layer help text | 74 flags in `admin_cmd` carry no help, and `project.py` documents all of its own. Two were written where a verification step was being disabled; the remaining 72 are untouched, and `parents=` would let one declaration carry one help string to every subcommand. | W66 |
| Event-record builders | `cursor` has no module-level builder and `cc`/`codex` have sites that bypass theirs. Found by `pylint R0801`, not started. | W72 |
| Deep audit adoption | `tools/deep_audit.py` runs and logs; nothing yet acts on its DESIGN tier -- 444 `PLR`, 385 `TRY`, 73 `C901`, 16 duplicate clusters are reported and unqueued. | -- |

## Item Detail

### W04 -- Candidate-Record Contract

**Work.** Define the shared candidate-record contract and enforce released
mapping profiles at the runtime decode boundary. Adapters currently exchange
`dict[str, Any]` with the domain layer, so a misspelled key, an invalid value
type, or inconsistent null handling is caught only at the store boundary, if at
all. The intended shape is a `TypedDict` family for candidate Session, Event,
tool, configuration, and diagnostic records, plus one runtime validator
post-decode.

**Scope.** All three adapters; the post-decode conformance check; strict versus
diagnostic policy for a non-conforming candidate.

**Where to start reading.** The pieces exist and are not connected:

| File | Holds |
|---|---|
| `adapters/{cc,codex,cursor}.py` | The three producers of candidate dictionaries; the shapes to be typed |
| `mapping.annotate_mapping` | Where a candidate acquires its selected rule and trace today |
| `schema_contract.validate_mapped_event` | The conformance check that exists, is exercised by four test modules, and is called from **no production path** -- wiring it in is the core of this item |
| `schema/mappings/{claude,codex,cursor}.json` | The released profiles the check validates against |
| `ingest_review` | Where a non-conforming candidate's diagnostic lands |

`validate_mapped_event` being test-only is the item in one line: the contract is
written and unenforced.

**Steps.** Ordered by what feeds what, not by size.

| Step | Work | Verified by |
|---|---|---|
| 1 | Call `validate_mapped_event` at one vendor-neutral post-decode boundary, between adapter output and `store` insertion, so every Event passes it regardless of vendor. | A deliberately non-conformant Event routed through each adapter's ingest path meets the same rejection. |
| 2 | Declare the shared candidate-record contract as a type, so the shape crossing that boundary is stated rather than implied by three adapters agreeing. | Adapters type-check against the declared candidate; mypy covers the decode boundary. |
| 3 | Give the boundary diagnostic and strict modes with the same semantics for all three vendors, replacing the Claude-only strict-mapping coverage. | Equivalent partial, malformed, unsupported, and hazard fixtures per vendor produce equivalent dispositions. |
| 4 | Record each non-conformance as a `mapping_diagnostics` row rather than only raising, so diagnostic mode is inspectable after the fact. | Diagnostic-mode ingest of hazard fixtures yields rows carrying the reason codes the profiles declare. |
| 5 | Extend `tools/decode_audit.py` with a per-vendor conformance count, so the current zero is re-measurable rather than observed once. | The audit reports conformance beside its existing invariants and exits nonzero on any failure. |

**Ordering within the item.** Steps 4 and 3 are what coverage reporting depends
on: a loss report states what was *not* mapped, and diagnostic rows are that
record -- without them the report re-derives non-conformance by re-decoding,
which is a second decode path. Step 3 makes the counts comparable, since a
vendor that raises where another tolerates gives the same figure two meanings.
Steps 1 and 2 feed nothing else and can land independently. Step 5 overlaps
coverage reporting in presentation and folds into it.

**Evidence to close.** All three adapters satisfy the typed and runtime candidate
contract, pass the same post-decode conformance check, and share strict/diagnostic
semantics; `validate_mapped_event` is reached from the ingest path and a
non-conforming candidate produces a diagnostic rather than a silent store write.

**Blocks.** W64 (typing posture), W65 (record-context group), W17.

### W05 -- Real Investigations Against the Query Surface

**Work.** Run named real investigations against the query surface and produce the
worked examples they yield. The check cannot use fixtures, which contain the
answer by construction. It needs three to five questions asked before the data is
examined:

- locate where an instruction first appeared;
- decide whether a short prompt was human or harness-generated;
- connect a tool result to its invocation;
- recover what preceded a failure or permission denial.

**Scope.** Run against a real Project. Each question becomes a documented worked
example. A predicate or facet the investigations cannot express is recorded as a
finding with evidence, not as a review opinion.

**Evidence to close.** Named investigations run end to end against a real Project;
each documented as a worked example; every gap recorded as a finding.

**Cost.** No rebuild: format-6 stores exist, so the work begins against current
data rather than regenerating it.

### W14 -- Project Identity for Direct Library Writes

**Work.** Require or explicitly mark Project identity for direct library writes.

**Evidence to close.** Separate vendor stores cannot silently create unrelated
Project identities for one repository.

**Cost.** Independent: no item blocks it and none waits on it.

### W16 -- External Investigation Interfaces

**Work.** Evaluate, design, and plan the external investigation interfaces CoPlan
describes. This item does not authorize implementation.

**Evidence to close.** A written decision maps existing capabilities and gaps,
selects or rejects data and code integration paths, specifies any proposed
contracts, and defines staged work with licensing, privacy, security, and
validation criteria.

**Status.** Postponed: no consumer has asked for external interfaces.

### W17 -- Cross-Project Analysis Inputs

**Work.** Expand cross-Project analysis inputs. Cross-Project search is an accepted
advanced feature set, so this waits on the baseline it would be specified against
rather than on a requester.

**Evidence to close.** Baseline 2 is met; a consumer then identifies entities,
fields, selection, transformation, and output checks.

**Status.** Deferred until Baseline 2. Specifying against a decode W04 has not
enforced would fix the surface while it is still changing.

### W35 -- Validation-Fixture Inventory

**Work.** Either wire each released fixture into a test that reads it through the
manifest, or remove it from the released set.

**Scope.** Ten of the sixteen released manifest entries are fixtures. Two are read
by tests, by direct path rather than through the manifest; the remaining eight are
referenced by nothing but the manifest itself, so no test can fail on them.

**Evidence to close.** Every entry in the released manifest has a named consumer,
or is removed; a test fails if an entry acquires none.

**Status.** Postponed and Low: the fixtures were removed from the write gate, so
they no longer gate anything a store does. This is now a question about what the
released set should contain.

### W43 -- Table-Driven Request Validation

**Status: Withdrawn on inspection.** The table was proposed from a complexity
score before the function was read, and the function already is one where a table
can be applied. Five `for key in (...)` loops apply a shared rule to 30 fields
using 10 branches; the remaining 28 branches are each a distinct rule -- format,
action, sortedness, cross-field agreement, range. A table over those needs a
per-entry predicate and message, which is the existing code with a dictionary
wrapped round it.

**Retained note.** `resource_policy` raises 8 field errors with no loop and is the
better candidate if this pattern is pursued.

### W50 -- Schema Names Against Defined Terminology

**Work.** Reconcile schema names with the terminology Codess defines.

**Landed in format 6.** `mapping_diagnostics.level` became `granularity` -- the
one defect of the four that made a reader draw a wrong conclusion, since summing a
granularity overstates loss. The `level`/`diagnostic_level` collision resolved
with it.

**Remaining.**

| Defect | Detail |
|---|---|
| `source` carries three meanings | A transcript file, a vendor, and an adapter key, across 26 columns |
| `*_content` plurality | The four link tables disagree with `event_artifacts` |

**Evidence to close.** Every term in a table or column name is either defined in
Codess's terminology or is a plain English word carrying no Codess meaning;
`source` names one thing; plurality has one rule and one stated exception.

**Cost.** Wire-format. Batches with W51.

### W51 -- Source-Identity Naming

**Work.** Resolve source-identity naming, measured against peer projects.

**The plurality rule**, surveyed across four peer SQLite schemas holding 56 tables:
11 are singular and every one is a mass noun. Countable-entity tables are plural
without exception. This settles CoSchema's `*_content` tables -- `event_content`
averages 1.27 rows per Event, so it is a countable set. `store_meta` is correctly
singular by the same rule.

**The suffix defect.** `_id` carries four incompatible formats, so a reader cannot
tell whether a value is derived, assigned, or borrowed:

| Column | Holds |
|---|---|
| `sessions.id` | A vendor UUID |
| `sessions.entity_id` | A `codess:session:` derivation |
| `sources.id` | A bare SQLite rowid |
| `sessions.source_system_id` | A dotted literal, `anthropic.claude-code` |

`source_system_id` is not an identifier under that reading -- it is
`vendor + "." + product` composed in the mapping profile, so `source_system_key`
says what it is.

**Two contract questions.** `product` is required by `mapping-contract.json` and
defined nowhere: no vocabulary, no examples, no CoSchema entry. Either define it or
drop it. `sessions.source` holds the `SOURCE_PROFILES` dict key, confirmed across
601 real Sessions, so `adapter_key` names it honestly and frees `source` for the
Source entity.

**Excluded.** `vendor_name` is the wrong fact for a harness running another
provider's model, so [CoNames](CoNames.md) owns its disposition rather than this
item.

**Evidence to close.** One suffix rule states whether a value is derived, assigned,
or borrowed; `source` names the Source entity only; every contract-required field
has a definition and examples; plurality follows the mass-noun rule.

**Cost.** Wire-format. Batches with W50.

### W55 -- Parsing Consolidation

**Work.** Unify text and record parsing across the decode layer. The ordering is
sound -- a parser first, a regular expression last -- but the spread is not: 17
modules classify a prefix by hand where 4 use `removeprefix`, and 15 split on a
separator with no shared helper. [CoNames](CoNames.md) holds the measured
inventory and the rule each method follows.

**Three candidates.**

| Candidate | Detail |
|---|---|
| MCP server split | Implemented twice, in `store._tool_namespace` and `mcp_audit._mcp_candidate`, against the same three vendor spellings |
| Timestamp parsing | Three parsers and three direct `fromisoformat` callers, disagreeing on three input classes -- see below |
| Codex output header | The only free-text regex carrying decoded fields; keep the regex, move its field table beside the other vendor vocabularies |

**Time is the largest instance, and it is three parsers rather than two.**
`adapters/cc._parse_timestamp`, `adapters/codex._parse_timestamp`, and
`cursor_source.parse_timestamp` -- the last imported by `adapters/cursor` --
plus three further modules calling `datetime.fromisoformat` directly
(`walk_sessions`, `token_usage`, `refresh_receipts`).

They agree on ISO-8601 and disagree on three input classes:

| Input | `cc` | `codex` | `cursor` |
|---|---|---|---|
| `"2026-01-01T00:00:00Z"` | 1767225600000.0 | 1767225600000.0 | 1767225600000.0 |
| `1700000000` (seconds-scale) | **1700000000.0** | 1700000000000.0 | 1700000000000.0 |
| `1700000000000` (ms) | 1700000000000.0 | 1700000000000.0 | 1700000000000.0 |
| `True` | **1.0** | None | None |
| `"  ...Z  "` (padded) | None | None | **1767225600000.0** |
| `"1700000000000"` (numeric string) | None | None | None |

`codex` and `cursor` scale a value below `1e12` from seconds to milliseconds and
reject `bool` before the numeric branch; `cc` does neither, so a seconds-scale
number is stored a thousand times too small and `True` becomes
1970-01-01T00:00:00.001. Only `cursor` strips surrounding whitespace. None
accepts a numeric string, which is a fourth unstated decision rather than an
agreement.

**The seconds-scale case is reachable in principle.** `fileMtime` is a
POSIX mtime, which is seconds-scale and therefore below `1e12`;
`walk_sessions` compares it against a millisecond cutoff. Whether Claude ever
writes a seconds-valued `timestamp` is not established -- what is established
is that if one arrived, `cc` would store it unscaled and the other two would
not.

**No stored data is affected today**: across 141,753 Events carrying a time in
the current stores, none falls outside 2000-2100, so no vendor has yet supplied
a shape that triggers the disagreement. The defect is that the answer depends on
which adapter read the value, and nothing records which behaviour was intended.

**Time fields are more numerous than the parsers suggest**, which is why one
shared parser is worth more here than in the other parsing clusters: `timestamp`,
`fileMtime`, `createdAt`, `lastUpdatedAt`, `clientStartTime`, `started_at`,
`completed_at`, `started_at_ms`, `completed_at_ms`, `occurred_at_ms`,
`durationMs`, `time_to_first_token_ms`, and `source_mtime` are all read from
vendor records, in seconds, milliseconds, nanoseconds, and ISO text.

#### Requirements for the Shared Time Normalizer

Each row is a decision the three parsers currently make differently or leave
unstated. A normalizer that does not answer all of them reproduces the problem
under one name.

| # | Requirement | Why, and what breaks without it |
|---|---|---|
| R1 | Accept ISO-8601 text, epoch seconds, and epoch milliseconds; return Unix milliseconds as `float` | `events.event_at` is `REAL` holding milliseconds, so the return unit is fixed by the store rather than chosen |
| R2 | A naive ISO string is read as UTC, and that assumption is recorded | All three parsers already do this. Unrecorded, a local-time stamp shifts by the reader's offset with nothing saying it was assumed |
| R3 | State the seconds/milliseconds boundary as a named constant, not an inline `1e12` | `codex` and `cursor` scale below `1e12`; `cc` does not. The threshold is a decision about which epoch range is plausible and belongs where it can be read |
| R4 | Reject `bool` before the numeric branch | `True` is an `int` in Python, so `cc` returns `1.0` -- 1970-01-01T00:00:00.001 -- for a flag misread as a time |
| R5 | Decide numeric strings explicitly | No parser accepts `"1700000000000"` today. That agreement is accidental: three independent omissions, not a stated rule |
| R6 | Decide surrounding whitespace explicitly | Only `cursor` strips it, so the same padded value parses from one vendor and not another |
| R7 | Return `None` for every unparseable input; never raise | Callers treat `None` as "no time" and pair it with a field state. An exception would abort a decode over one bad field |
| R8 | Never infer a time from another value | Codess does not derive time from ordering, adjacency, or file position; the normalizer must not become the place that starts |

**Deliberately out of scope**, because these are the caller's:

- *Which field to read.* `timestamp`, `createdAt`, `clientStartTime`, and the
  rest are vendor knowledge and stay in the adapters.
- *What a failure means.* The `field_state` upgrade from `present` to
  `malformed` needs the expected type, which only the calling parser knows.
- *Which basis was used.* `events.event_at_basis` records how a time was
  obtained; that is a mapping decision, not a parsing one.

#### Where It Applies

| Site | Today | After |
|---|---|---|
| `adapters/cc._parse_timestamp` | Own implementation, no scaling, accepts `bool` | Calls the normalizer |
| `adapters/codex._parse_timestamp` | Own implementation, scales, rejects `bool` | Calls the normalizer |
| `cursor_source.parse_timestamp` | Own implementation, scales, strips whitespace | Calls the normalizer |
| `walk_sessions` | `fromisoformat` inline on a session index | Calls the normalizer |
| `token_usage` | `fromisoformat` inline on usage records | Calls the normalizer |
| `refresh_receipts` | `fromisoformat` inline on receipt text | Calls the normalizer |

The thirteen time-bearing vendor fields -- `timestamp`, `fileMtime`,
`createdAt`, `lastUpdatedAt`, `clientStartTime`, `started_at`, `completed_at`,
`started_at_ms`, `completed_at_ms`, `occurred_at_ms`, `durationMs`,
`time_to_first_token_ms`, `source_mtime` -- are read by those six sites, so
consolidating the parsers covers all of them without touching field selection.

**One related defect is a naming problem rather than a parsing one, and stays
with W50/W51**: `sessions.started_at` is `REAL` while
`processing_runs.started_at` is `TEXT`, so one column name denotes two
representations. The normalizer does not fix that; a rename does.

#### Validation

- A table of inputs to expected outputs, one row per requirement above,
  including the three inputs the current parsers disagree on.
- A test asserting no module outside the normalizer calls `fromisoformat` or
  defines its own `_parse_timestamp`, in the shape the layer-boundary tests
  already use -- otherwise a fourth parser appears the way the third did.
- Re-ingest one Project per vendor and confirm `event_at` values are unchanged,
  since a parser change that alters stored times is a wire-format change rather
  than a consolidation.

**Nothing in this is specific to Codess**, which decides where it lives.
`_parse_timestamp` reads a value that may be ISO text, epoch seconds, or epoch
milliseconds and returns milliseconds; that is a general problem, and the five
decisions above are general decisions. The Codess-specific part is only *which
field to read* and *what a failure means* -- the `field_state` upgrade to
`malformed`, and the diagnostic that records it.

So the split is: a self-contained normalizer with no Codess import, taking a
value and a stated contract; and the existing per-adapter code that selects the
field and reports the outcome. That keeps the vendor knowledge in the adapters
and makes the normalizer testable against a table of inputs rather than against
a decoded record.

Whether it becomes a separate distribution is a later question with a higher
bar -- a published package needs a maintainer and a versioning commitment. The
first step is the internal module boundary, which is worth having regardless
and is a precondition for extraction either way.

**Time is the only candidate here with that property.** The MCP server split
matches three vendor spellings of a prefix, and the Codex output header parses
one product's free-text block; both are worth consolidating and neither means
anything outside this codebase. That difference is what makes time worth a
module rather than a helper function.

**Also assess** whether a library replaces hand-rolled work -- `email.parser` or
`dateutil` for the timestamp fallbacks -- and whether SQLite's own JSON functions
can replace materializing rows Python then re-parses.

**Evidence to close.** One helper per parsing concern; no vendor spelling matched
in two modules; a new adapter reaches for the same tools in the same order.

**Cost.** Correctness-neutral; no regeneration.

### W64 -- Typing Posture

**Work.** Decide the codebase-wide typing posture and enforce it. Annotations are
complete: every function has a return type and every argument has one.

**Three decisions.**

1. *Which strict flags to enable.* `disallow_untyped_defs` is within reach.
   `strict_optional` and `warn_return_any` were deferred to W04 on the grounds
   that errors concentrate at the decode boundary, which is measurably false --
   a majority sit outside it. What remains after the naming and annotation pass
   is dominated by optional-narrowing, which is exactly what `strict_optional`
   decides, so this item no longer waits on W04 for its evidence.
2. *Where `Any` is honest.* One explicit `Any` on the heterogeneous env-value table
   removed 50 spurious errors. The rule wants stating: `Any` at a deliberately
   heterogeneous boundary is documentation, `Any` threaded onward is an escape.
3. *Where a `TypedDict` pays.* It typed `refresh_operations`' kwargs bag to zero
   errors at no runtime cost -- an annotated literal is a plain dict, while the
   `TypedDict(...)` constructor form is not. The remaining `arg-type` and
   `assignment` errors concentrate in the `opts` and `settings` bags threaded
   through ingest.

**Evidence to close.** The enabled flag set is recorded with the reasoning for
each; `Any` appears only where a stated rule permits it; the type count falls
rather than being reclassified; `tools/quality_report.py` gates on the baseline.

**Blocked by.** W04, which moves the decode boundary a large share of the
remaining errors sit behind.

### W65 -- Recurring Parameter Groups

**Work.** Consolidate the relay parameter groups that remain. Separating functions
by use gives two populations, and only one is a candidate:

- **Builders** place their parameters into a returned literal and are correct as
  they stand. The parameter list *is* the record's shape.
- **Relays** forward their parameters to another call and are the struct
  candidates.

**Two groups remain.**

| Group | Where | Note |
|---|---|---|
| Record context (`session_id`, `source_file`, `line_num`, `opts`) | Seven adapter functions | The identity of the record being decoded; belongs with W04, which rewrites these signatures anyway |
| Catalog-refresh relay chain | `refresh_candidates` → `apply_project` → `onboard_catalog` | Threads ten values through three layers; owns no other item |

**What consolidation buys, and what it does not.** `ChildInvocation` removed three
specifications of one command line and collapsed a test from two patch points to
one, while leaving every caller's parameter count unchanged -- the callers still
receive those values to build the object. A signature shortens only where a relay
can take the object instead of its fields.

**Evidence to close.** Each recurring parameter group is either one named object or
recorded as a builder whose parameter list is its subject; no argv or environment
is constructed in two places; a test fails when a second builder appears.

**Blocked by.** W04, for the record-context group only.

### W66 -- Configuration Unification

**Work.** One component owning declaration, default, precedence, and validation for
every setting, so a new option is one table row rather than four edits.

**The defect.** A value's default is currently decided in up to four places -- a
compiled constant in `config`, an `env_*` reader, an argparse `default=`, and a
`getattr(args, ..., None) or CONSTANT` fallback at the use site -- and nothing
states which wins. `--registry` and `--dir` each appear in four modules;
`--source`, `--raw-mode`, `--min-size`, `--force`, and `--resource-policy` in
three. [CoReview](CoReview.md) holds the measured counts.

**The ordering constraint is real and undocumented.** `project._settings` resolves
`int(MIN_SIZE if raw is None else raw)` while `schema_contract` and `fileio` read
their environment variables directly *because* `config`'s constants have already
resolved by the time a flag is parsed. Three modules work around this individually;
it should be stated once.

**Also in scope.** A config file admitted as a source, which no current path
supports.

**How the duplication arose.** Not by neglect -- by the absence of a mechanism.
`admin_cmd` builds **40 subparsers** and declares **157 flags inside them**,
and nothing in the file uses argparse's own `parents=` facility for shared
options -- verified to do exactly this job: one declaration on a parent parser,
inherited by every subparser that lists it. So a new subcommand that needs `--registry` gets it the only way the
surrounding code demonstrates: by writing the line again. Sixteen subcommands
need it, so the line exists sixteen times. Each addition was locally correct and
matched its neighbours; the pattern that was being matched is the defect.

That is the same mechanism CoPlan records for the snapshot file literals: a
module needs one fact, an inline declaration is smaller than a shared-code
change, and repetition across many small additions produces the duplication
without any single change being wrong. It predicts where to look next --
wherever a construct is built dozens of times with no shared helper.

**Argument audit: nothing is obsolete, and that is the finding.** All 172
distinct destinations are read somewhere in `src/`; none is dead. But the *way*
they are read splits into two populations:

| Reads via `args.X` | Dests | What it means |
|---|---|---|
| 0 | 13 | Reached only through the `settings` bag or `flag_or_env` |
| 1 | 82 | Read at one call site and passed on |
| 2 or more | 77 | Read at several sites; the top one is read 25 times |

The thirteen -- `--debug`, `--redact`, `--strict-mapping`, `--subagent`,
`--validate-only`, `--no-hash`, `--version`, `--session-relation`, and the five
`--max-*` bounds -- each reach a real consumer, so none should be removed.

**Two options go the other way: read but never set.** `opts` is queried for
`include_product_state` and `max_external_content_bytes`, and nothing in `src/`
writes either, so one is always its `True` default and the other always `None`.
Both have correct fallbacks, so behaviour is right; both are unreachable by an
operator and invisible as inert to a reader. Declare them in the table or
delete them -- an undeclared setting that cannot be set is neither. What
they demonstrate is the cost of the bag: a reader grepping `args.debug` finds
nothing and concludes the flag is dead, when it is read as `settings["debug"]`
two layers away. The setting table fixes this as a side effect, since a declared
setting names its own consumer.

**No flag should be declared twice for the same setting.** The 25 duplicated
names are all one setting reached from several subcommands, so `parents=`
removes every one of them without changing a single `--help` line: argparse
renders an inherited option exactly as a locally declared one. The duplication
is a source-code fact, not a user-visible one, so the fix is in the declaration
and the help text is what must stay identical.

One flag previously carried two superseded spellings --
`--snapshot-contract-policy` and `--snapshot-package-policy` -- and both are
now gone in favour of `--snapshot-policy`. An alias is only worth keeping where
a caller's script would break, and neither spelling had reached that status.

**Every `--no-` flag, and what it turns off.** Seven, and they are not one
family: five disable a check or an output, two invert a default.

| Flag | Command | Disables | Stated |
|---|---|---|---|
| `--no-hash` | ingest, query | Snapshot and manifest hash verification on read | Yes, with "recovery/debugging only" |
| `--no-check` | ingest, query | The released-contract verification | Yes, with "tests and recovery" |
| `--no-resource` | ingest | Transcript, container, event, and context maximums | Yes |
| `--no-progress` | ingest | Live progress on stderr, keeping the structured trace | Yes |
| `--no-propose` | `config discovery` | Reading the work root to propose exclusions | Yes |
| `--no-record` | `storage report` | Writing the observation | Yes, added |
| `--no-smoke` | `baseline apply` | The post-apply query check | Yes, added |

Two carried no help at all, and both gate a verification step -- exactly where
an operator most needs to know what is being skipped. Both are now documented;
the first four already said what they bypass *and* that a bypass is logged,
which is the standard.

**The gap is wider than those two.** 74 flags carry no help text, and **every
one is in `admin_cmd`** -- `project.py` documents all of its own. So the
administrative surface is undocumented as a class, not by oversight in a few
places: `--registry`, `--source`, `--force`, `--min-size`, and `--raw-mode` are
among them, which is the same set the duplication concentrates in. A flag
declared sixteen times with no help is sixteen chances to write one and none
taken.

This is what makes `parents=` worth more than the deduplication itself: one
declaration carries one help string to every subcommand that inherits it, so
documenting the shared options is a single edit rather than sixteen.

**The naming, settled before the table generates anything.** Three questions,
and they resolve together.

*First: `.codess` is a depository, not a store or a registry.* It sits beside
the work it describes, exactly as `.git` does, and holds derived state a tool
owns rather than content a person edits. `depository`/`depo` parallels
`repository`/`repo` and is the honest word: a repository holds the work, a
depository holds what a tool deposited about it. `STORE_DIR = ".codess"` is
currently named for one of the things inside it -- the stores -- which is the
same part-for-whole error as calling the directory a registry.

*Second: the two `.codess` directories are not the same kind of thing, and
neither is config or state.* Measured rather than assumed: the machine-level
directory is **58 GB, of which 57 GB is `projects/`** -- published store sets,
one per Project. It is a store first and everything else second.

| | Per-Project `<project>/.codess` | Machine `~/.codess` |
|---|---|---|
| Bulk | Working stores and their snapshots | Published store sets, one per Project |
| Also holds | Current pointer, ingest state, last report | Project catalog, activity index, receipts, reports, retention, raw capture, quarantine, `machine-id` |
| Scope | One Project | One machine |
| Lifetime | Deleted with the checkout | Outlives every Project it records |

**The two are not duplicates.** A Project's `current.json` points *into* the
machine directory: the working store is beside the checkout, and the published
one the pointer selects is central. `project_catalog.durable_project_root`
already names that half "durable", which is the distinction the directory names
do not carry.

So a `config`/`state` name would misdescribe both -- neither is predominantly
either, and configuration reaches Codess through the environment and flags
rather than a file in these directories. `depo` fits the per-Project side, where
a tool deposits what it derived beside the work. For the machine side the honest
word is the one already in the code: it holds **durable stores**.

| Now | Proposed | Is |
|---|---|---|
| `STORE_DIR` (`.codess`) | `PROJECT_DEPO` | The Project depo, beside the work: working stores and a pointer |
| `REGISTRY` / `registry` / `registry_root` | `DURABLE_STORE` / `store_root` | The machine's durable store, `~/.codess` |
| `ingested_projects.json` (`STATS_FILE`) | *the activity index* | Per-Project scan/ingest/query timestamps and counts |
| `projects.json` | *the registry* | Project identity, locations, aliases, workspace bindings |
| `registry_store` (module) | `activity_index` | Reads and writes the activity index, not the registry |
| `--registry` | `--store` | Selects the machine's durable store |

**Confirming what "registry" means: central information about every Project and
its status -- yes, and the two files that hold it are separately justified.**

| File | Keyed by | Holds | Written by |
|---|---|---|---|
| `projects.json` | `project_id` | Identity: locations, logical name, path aliases, workspace bindings | Catalog operations only -- onboarding, relocation, retirement |
| `ingested_projects.json` | `path` | Status: `sources`, `last_scan`, `last_ingestion`, `last_query`, and counts | Every `scan`, `ingest`, and `query` run |

**They are not a split that should be merged.** Three measured reasons:

1. *Different keys, and the difference is the point.* The catalog is keyed by
   `project_id` and carries a `locations` list, because one Project can be
   checked out in several places. The status file has **no `project_id` field on
   any entry** -- it is keyed by path, so it cannot express that model at all.
   Merging would either force a path-keyed file to grow an identity it does not
   have, or force identity records to carry per-path activity they do not own.
2. *Different write cadence.* The status file is written by every scan, ingest,
   and query -- three commands, every run. The catalog is written only when a
   Project's identity changes. Merging puts a high-frequency append in the same
   document as the record that must not be lost, and a crash during one would
   risk the other.
3. *Different populations, already.* 32 catalog entries against 31 status
   entries, and nine paths appear in status with no catalog location --
   `~/.codex` and `~/.openclaw-repo/workspace` among them, which are directories
   holding Sessions but never onboarded as Projects. That is correct behaviour:
   activity is observable before identity is established.

Neither module reads the other's file, so the separation is real in the code and
not only on disk.

**Naming them.** `ingested_projects.json` is wrong twice over: it is written by
`scan` and `query` as well as `ingest`, so "ingested" names one of its three
writers; and its subject is what has happened to a Project, not which Projects
were ingested. `projects_state.json` fixes both -- the subject is Project state,
and no writer is privileged. Paired with `projects.json` for identity, the two
read as what they are.

| Now | Proposed | Is |
|---|---|---|
| `projects.json` | `projects.json`, unchanged | The registry: which Projects exist and where |
| `ingested_projects.json` (`STATS_FILE`) | `projects_state.json` (`PROJECT_STATE_FILE`) | Per-Project status: what was scanned, ingested, queried, and when |
| `registry_store` (module) | `project_state` | Reads and writes that file |

`STATS_FILE` is also a poor constant name: the file holds timestamps and source
lists as well as counts, so "stats" describes one column family rather than the
document.

**How the vendors name theirs, checked rather than assumed.** All three keep a
per-user home directory of the same shape -- `~/.claude`, `~/.codex`,
`~/.cursor` -- each mixing configuration, credentials, caches, and session data,
and none names it in its own documentation. Claude Code additionally supports an
optional per-directory `.claude`, but it carries *settings* only: this
repository's holds one file, `settings.local.json`. That is the inverse of the
split here, where both halves are bulk data. So there is no vendor term to
borrow, and the two-level split Codess uses is its own.

**"Primary paths" is the wrong label, and one vendor document already does
better.** CCSchema and CodexSchema head a table row with **Primary paths**,
which says neither whose paths they are nor what makes them primary -- there is
no secondary set to contrast with. CursorSchema does not use the row at all: it
has a section called **Source Scope and Locations** and a table headed **Default
base**, which name the subject and admit that the value is a default an
environment variable overrides.

| Now | Proposed | Why |
|---|---|---|
| **Primary paths** | **Source locations** | Names the subject -- these are where a vendor's Sources are found. "Source" is the defined entity, so the row inherits its meaning |
| (Cursor's) **Default base** | **Default base**, unchanged | Already correct: a base that a platform sets and configuration overrides |

Apply the same row to all three vendor documents so a reader comparing them
reads one heading, and state the override variable in the row as CCSchema
already does.

*Third: `storage registry-prune` names its object, not its subject, and the
verb collides.* Two subcommands prune:

| Subcommand | Removes | Because |
|---|---|---|
| `storage prune` | Retained snapshots under the depository | Retention policy says they are superseded |
| `storage registry-prune` | Entries in the Project index | Their Project path no longer exists |

Same verb, different objects, and neither name says which. The second is not
pruning a registry -- it is removing index entries that no longer refer to
anything, which is a *reconciliation* against the filesystem rather than a
retention decision. Proposed:

| Now | Proposed | Reads as |
|---|---|---|
| `storage prune` | `storage prune-snapshots` | Apply retention to retained snapshots |
| `storage registry-prune` | `registry reconcile` | Drop index entries whose Project is gone |

`reconcile` states the subject: the index is being made to agree with the
filesystem. It also admits the operation's other half honestly -- an entry
pointing at a moved Project is as stale as one pointing at a deleted Project,
and a verb meaning "remove" cannot describe fixing it, while a verb meaning
"agree with what is there" can.

Moving it out of `storage` and under `registry` follows from the first two
answers: `storage` is about the depository's bytes, and this operation is about
the index's accuracy.

**How to do it.** Six steps, each leaving the suite green, so the work can stop
between any two.

| Step | Work | Checked by |
|---|---|---|
| 1 | Extend `config`'s existing env table to a **setting table**: one row per setting naming its env var, flag, type, default, and which commands accept it. The table exists and is table-driven already; what it lacks is the flag half. | A test asserts every row is well-formed and no two rows share a flag |
| 2 | Emit the argparse declarations **from** the table rather than by hand, one helper per command family. | `--help` output is byte-identical before and after, per command |
| 3 | Resolve the three `--registry` variants into the one the table declares. | Below |
| 4 | Replace the `getattr(args, ..., None) or CONSTANT` sites with one accessor that applies the stated precedence. | A test covers each precedence pair: flag over env, env over built-in |
| 5 | State the import-order constraint once, and give the two flags that work around it a supported path. | The `os.environ[...] = "1"` writes in `project.parse_and_run` are gone |
| 6 | Admit a config file as a source, between built-in and environment. | A file-set value loses to both the env var and the flag |

**Step 3 is a real defect, not a tidy-up.** `--registry` is declared **16
times** across two modules in three incompatible forms:

| Form | Where | Consumed by |
|---|---|---|
| `type=Path, default=REGISTRY` | `admin_cmd`, 14 subcommands | `args.registry` directly, so it must be a `Path` |
| `type=str, default=None` | `project.py` | `resolve_registry_directory`, which accepts `str \| None` |
| `type=Path, required=True` | `admin_cmd`, one subcommand | `args.registry` directly |

A caller moving between command families gets a different type from the same
flag name. The table settles it: declare `Path` with the `REGISTRY` default and
route every consumer through `resolve_registry_directory`, which already
normalizes both.

**Step 5, stated exactly.** `config`'s constants resolve at import, which is
before a flag is parsed. Two flags therefore work around it by writing the
environment variable their reader observes -- `project.parse_and_run` sets
`CODESS_NO_CONTRACT_CHECK` and `CODESS_NO_HASH` so `schema_contract` and
`fileio` see them. Both comments say this correctly; neither is wrong. The
constraint is that a **leaf module cannot import `config`**, so it reads the
environment directly and a flag has to reach it that way. The fix is not to
remove the workaround but to make it the declared mechanism: a setting marked
as leaf-visible is written to the environment by the resolver, once, instead of
by two hand-written assignments.

**Scope check.** 257 `add_argument` calls across exactly two files; 152 distinct
flags of which **25 are declared more than once**; 133 `getattr(args, ...)`
sites. The duplication is concentrated -- `--registry` 16, `--output` 11,
`--project-id` 8, `--catalog`/`--source`/`--resource-policy`/`--project` 4 each
-- so eight names account for more than half of it.

**Evidence to close.** One declaration per setting names its flag, variable,
default, and type; precedence is stated and tested; no module reads `os.environ`
for a declared setting except through the leaf-visible mechanism step 5 defines;
a flag name appears in exactly one module.

**Precedent.** `ChildInvocation` is the shape for the argv half and is done.

### W67 -- Relay Fields Into Objects

**Work.** Move relay fields into the objects that carry them. `run_ingest` went
from 8 parameters to 1 by taking `ChildInvocation` rather than its fields, which
also exposed that its two callers built the same invocation twice -- the repeat run
exists to prove the first is reproducible, so the two must not be able to differ.

**Remaining relays**, measured by parameters forwarded rather than used:

| Function | Forwarded |
|---|---|
| `review_project.refresh_candidates` | 10 of 14 |
| `baseline_operations.apply_project` | 10 of 12 |
| `ingest_cmd._ingest_project` | 10 of 10 |
| `catalog_operations.onboard_catalog` | 8 of 10 |
| `ingest_publication.publish_snapshot` | 6 of 10 |

**Do not convert a builder.** `codex._base_event` takes 19 parameters and places
all 19 into its returned dict; an object would name the same fields twice. The
distinction is measurable -- parameters reaching a literal against parameters
reaching another call -- and is the rule to apply.

**Proposed structures.** Three, and the partition between them is by *lifetime*
-- when the value is decided and when it stops being true -- because that is the
axis the existing structures already use and the one the current dicts blur.

| Structure | Holds | Decided | Mutability | Modelled on |
|---|---|---|---|---|
| `RunPolicy` | `registry`, `repo_root`, `min_size`, `raw_mode`, `resource_policy`, `force`, `timeout_seconds`, `source` | Once, before the first Project | `frozen` | `ChildInvocation` |
| `ProjectRef` | `path`, `project_id`, `location_id`, `index`, `total` | Per loop iteration | `frozen` | `ProjectScope` |
| `DiscoveryPolicy` | `roots`, `vendor_filter`, `recent_days`, `include_git`, `discover_git`, `max_depth`, `check_remotes`, `max_directories`, `deadline_seconds`, `same_filesystem` | Once, before traversal | `frozen` | `ResourcePolicy` |

**Why these three and not one.** `RunPolicy` and `DiscoveryPolicy` are both
run-lifetime and could merge, but they have different subjects and different
consumers: discovery bounds a filesystem walk and is read only by
`review_project`, while `RunPolicy` describes what an ingest does and is read by
four modules. Merging them would put a `deadline_seconds` that bounds a walk
beside a `timeout_seconds` that bounds a child process -- two unrelated bounds
one field apart, which is the collision the naming rules exist to prevent.

**Verified against what exists, and one is already built.** `ChildInvocation`
holds `registry`, `repo_root`, `min_size`, `resource_policy`, `force`,
`raw_mode`, and `timeout_seconds` -- every field `RunPolicy` would carry.
`refresh_operations._run_project_ingest` takes eight parameters and immediately
packs seven into a `ChildInvocation`; `refresh_projects` takes seventeen and
threads them down two layers to do it. So `RunPolicy` should not be a new
class: the relays should take `ChildInvocation`, which is what `run_ingest`
already did when it went from eight parameters to one.

That leaves the partition question sharper. `ChildInvocation` currently mixes
two subjects -- a *policy* (`registry`, `repo_root`, `min_size`, `raw_mode`,
`force`, `resource_policy`, `timeout_seconds`) and a *target* (`projects`,
`vendor_selector`, `validate`). The policy half is identical across every
Project in a run; the target half changes per invocation.

**The two `_run_project_ingest` call sites are the evidence.** Both pass the
same six policy arguments verbatim, differing only in `validate` and the loop
variable:

```python
result = _run_project_ingest(
    project, validate=True, registry=registry,
    repo_root=repo_root, min_size=min_size, force=force,
    resource_policy=resource_policy, timeout_seconds=timeout_seconds,
)
```

Six of the eight arguments carry no information at either site -- they restate
what the enclosing `refresh_projects` was given seventeen parameters earlier.
With the split, both become `_run_project_ingest(project, policy,
validate=...)`. Do the split before adding callers, not after.

**Field ownership, checked against the existing structures.**

| Field | Belongs to | Not to | Because |
|---|---|---|---|
| `raw_records`, `raw_store`, `content_actions` | `ProjectScope` | `IngestConfig` | Replaced every iteration; a carried-over value attributes one Project's evidence to the next |
| `outcome`, `diagnostics` | `RunTotals` | `IngestConfig` | Mutated in place; the read-only and mutable halves are deliberately separate |
| `options`, `sources`, `registry_root` | `IngestConfig` | `RunTotals` | Decided before the first Project and unchanging |
| `store_path`, `__getitem__` | `StoreLocator` protocol | `IngestConfig` directly | Publication needs two members, so the dependency points into the domain rather than back out |
| `workspace_ids`, `global_db` | `CursorSelection` | `IngestConfig` | Vendor-specific selection, owned by the module that reads the vendor store |

Each of those five is already correct. The gap is not that the vocabulary is
wrong; it is that the relays do not use it.

**Build the structure at the origin, not at the relay.** A struct constructed
inside a relay moves the packing rather than removing it -- the caller still
passes the fields and the callee still assembles them. Traced to where each
value comes from, every one of these chains starts in the same place:

| Entry point | Sole non-test caller | Where the values come from |
|---|---|---|
| `refresh_projects` (17 params) | `admin_cmd._refresh` | `args.*` and `REPO_ROOT` |
| `onboard_catalog` (10) | `admin_cmd._catalog_onboard` | `args.*` and `REPO_ROOT` |
| `apply_project` (12) | `admin_cmd._baseline_apply` | `args.*` and `REPO_ROOT` |
| `refresh_candidates` (14) | `admin_cmd._catalog_candidates` | `args.*` |

Every value is read off `argparse.Namespace` at one command adapter and then
threaded down two or three layers unchanged. So the object belongs at that
adapter: built once from `args`, passed whole, and never unpacked until
something reads a field.

**Five parameters are shared by all three ingest-side entry points** --
`registry`, `repo_root`, `source`, `raw_mode`, `resource_policy` -- with
`min_size` in two of the three and `force`/`timeout_seconds` in one. That
subset is the object, and it is the same subset `ChildInvocation` already
carries.

**One packing function already exists and shows the shape.**
`refresh_projects` accepts nine parameters it uses exactly once each, purely to
build a `_ResolveArgs` TypedDict and splat it into
`resolve_refresh_selection`. The TypedDict is right; its construction site is
not. Built at the command adapter instead, `refresh_projects` loses nine
parameters and gains one, and the nine names stop appearing in a signature that
does not read them.

Moving it makes `_ResolveArgs` public, which is the correct consequence rather
than a cost: a shape two modules pass between them is an interface, and the
leading underscore currently says it is not. It is already used twice inside
`refresh_projects`, so the second call site keeps working unchanged.

**What moves up, and what does not.** Values decided by the operator move to
the adapter. Values *derived* during the run stay where they are derived:
`plan["projects"]`, the per-Project `project_id` and `location_id`, and the
receipt path when it is defaulted from a timestamp. The test is whether the
value exists before the operation starts -- if it does, the adapter owns it.

**This overlaps W66 and should not be done twice.** The same five names are
redeclared as argparse options per subcommand, which is what W66 measures as
39 names spelled in more than one module. One declaration producing one object
answers both: W66 owns where a setting is declared, W67 owns what carries it
onward, and the object is the seam between them. Doing W67 first with a
hand-built object would encode the current duplication into a constructor.

**Two anti-patterns to avoid, both already demonstrated here.** Do not convert a
builder: `codex._base_event` takes 19 parameters and places all 19 into its
returned dict, so an object would name the same fields twice. And do not add a
structure whose only member is another structure's fields -- `RunPolicy` was
proposed above and then withdrawn on exactly that ground.

**How to do it.** Five steps, in this order because each makes the next
mechanical. Do them after W66's setting table exists, so the object is built
from one declaration rather than from 25 duplicated ones.

| Step | Work | Checked by |
|---|---|---|
| 1 | Split `ChildInvocation` into its policy half (`registry`, `repo_root`, `min_size`, `raw_mode`, `force`, `resource_policy`, `timeout_seconds`) and its target half (`projects`, `vendor_selector`, `validate`). Keep `command()` and `environment()` taking both. | Existing `ChildInvocation` tests pass unchanged; a policy is reusable across two targets |
| 2 | Build the policy at the four command adapters from the W66 table, and pass it whole. | Each adapter constructs it exactly once |
| 3 | Convert the relays innermost-first: `_run_project_ingest`, then `refresh_projects`, then `apply_project`, `onboard_catalog`, `refresh_candidates`. | Parameter counts fall; no call site rebuilds what it was handed |
| 4 | Move `_ResolveArgs` construction to the adapter and make it public. Its nine values are read off `args` and used once each. | `refresh_projects` no longer names those nine |
| 5 | Re-run the relay census. Anything still forwarding five or more is either converted or recorded as a builder with its measurement. | The census runs as a test -- measured at 216 ms over `src/`, so it costs nothing to keep -- and a new relay fails rather than accumulating |

**Innermost-first is what keeps each step small.** `_run_project_ingest` already
packs seven of its eight parameters into a `ChildInvocation`, so converting it
first is a signature change with no body change -- and its two call sites pass
identical policy arguments, so the caller simplifies in the same edit. Working
outside-in instead means each layer is converted twice: once to take the object,
once when the layer below it changes.

**Order these by what they remove, not by size.**

| Relay | Params | Forwarded | Removed by the object |
|---|---|---|---|
| `refresh_operations._run_project_ingest` | 8 | 8 | 6 |
| `refresh_operations.refresh_projects` | 17 | -- | 9 via `_ResolveArgs`, 6 via policy |
| `baseline_operations.apply_project` | 12 | 10 | 6 |
| `catalog_operations.onboard_catalog` | 10 | 8 | 5 |
| `review_project.refresh_candidates` | 14 | 10 | 10 via `DiscoveryPolicy` |

**`refresh_candidates` is the one that needs a new structure.** The other four
are served by splitting `ChildInvocation`; its ten discovery parameters have no
existing home, which is what `DiscoveryPolicy` is for. Build it last, so the
pattern is established before a new type is introduced.

**Evidence to close.** Every relay of five or more parameters takes an object or is
recorded as a builder; a call site cannot mis-order same-typed arguments; no
invocation is constructed twice where one would do; `ChildInvocation`'s policy
and target halves are separable, or the reason they are not is recorded; the
relay census runs as a test.

### W71 -- Adopt the Reporting Facility in the Command Layer

**Work.** Route command-layer status, progress, warnings, and errors through
`codess.reporting` instead of writing them directly.

**The gap.** The facility is complete and specified; the callers were never
converted. Measured across `src/`:

| Path | Count | Location |
|---|---|---|
| `reporting.*` call sites | 8 | mixed |
| `print(file=sys.stderr)` | 43 | the four command modules |
| Direct `sys.stderr` writes | 63 | the four command modules |
| `logging` calls | 33 | mixed |

**What is already correct and must not change.** Result output on stdout stays
a plain `print()`. That is the result channel, and it is what lets
`--output-format jsonl` be piped. Only the stderr half is in scope.

**Why it matters beyond tidiness.** Every property the facility provides --
level gating, profile selection, privacy classification, bounded fields,
never raising into the operation it reports on -- applies only to calls that go
through it. A direct `sys.stderr` write has none of them, so the guarantees
currently hold by convention at each call site rather than by construction, and
a redaction profile does not reach the output an operator actually sees.

**Evidence to close.** No command module writes to `sys.stderr` directly; the
channel-separation test asserts it rather than the current convention;
`--output-format jsonl` remains byte-identical on stdout across profiles.

**Cost.** Mechanical per call site, no rebuild. Independent of W04.

### W72 -- The Event Record Shape, Spelled Out Four Times

**Work.** Route every Event construction through one builder per adapter, and
give Cursor the builder the other two have.

**Found by `pylint --enable=R0801`**, which reports near-identical line blocks
across modules -- a capability neither ruff nor the structural-duplication test
has, because the repetition is a *fragment* inside larger functions rather than
a whole function.

**The evidence.** Sixteen clusters; the sharpest is the common Event field
block, appearing in all three adapters:

| Site | Shape |
|---|---|
| `cc.py:940` | `role`, `content`, `content_len`, `content_ref`, `tool_name`, `tool_input`, `tool_output`, `timestamp` |
| `codex.py:1520` | the same eight keys, same order |
| `cursor.py:185` | the same eight keys, same order |

`cc._base_event` and `codex._base_event` exist precisely to prevent this --
`codex._base_event`'s docstring records that fifteen call sites each wrote the
same twenty keys inline, 405 lines collapsed into one builder. The clusters are
the sites that were never converted, plus a third adapter that never got a
builder: **`cursor.py` has no module-level `_base_event`**, only a nested
`base_ev` closure introduced later at line 495, so the earlier construction at
line 178 still spells the record out.

**Remaining clusters, grouped by what they say.**

| Cluster | Modules | Reading |
|---|---|---|
| Event field block | `cc`, `codex`, `cursor` | The builder exists and is not universally used |
| Metrics accumulator (`day`, `events`, `content_characters`, `sessions`, `interactions`) | `orientation_audit`, `query_api` | Two report paths accumulate the same per-day shape; a shared accumulator is the fix |
| Reporting re-export | `reporting.__init__`, `reporting.api` | The package re-exports its own API; expected and correct |
| Catalog entry fields | `project_annotations`, `project_catalog`, `refresh_operations` | Three readers of the same catalog row; a typed accessor is the fix, and it is W04's shape one level up |
| Command preamble | `ingest_cmd`, `query_cmd` | Both resolve roots and store root the same way; W67 territory |

**Evidence to close.** No adapter constructs an Event dict outside its builder;
Cursor has a module-level builder like the other two; the per-day accumulator
has one definition; `pylint --enable=R0801` reports only the re-export cluster,
which is recorded as accepted.

**Cost.** Correctness-neutral, no rebuild. Overlaps W04 (adapter signatures) and
W67 (command preamble), so it batches with whichever lands first.

### W70 -- Documentation Partition and Redundancy

**Work.** Re-partition the documentation set against its stated charters, and
remove the conceptual redundancy that has accumulated across documents.

**The evidence.** Verbatim duplication is not the problem -- exactly one
sentence appears in two documents. The problem is that a single topic is
discussed, from scratch, in many places:

| Topic | Documents discussing it |
|---|---|
| Mapping profiles | 8 |
| Snapshots | 7 |
| Raw mode and capture | 5 |
| Coverage reporting | 4 |
| `quality_report` | 4 |
| Candidate records | 3 |

Work items spread the same way. W04 was mentioned 40 times across four
documents before this item was written, including a five-step implementation
plan with verification criteria in CoReview -- forward-looking planning inside
the document whose charter is "evidence, not a plan". Moving that plan to
CoTasks cut CoReview's W04 mentions from 17 to 5.

**The rule to apply.** One topic has one authoritative location; every other
document states only what its own charter requires and links rather than
restates. Where two documents must both discuss a topic, the second states the
consequence for its own subject, not the topic.

**Method.** For each topic above, identify the charter that owns it, reduce
every other treatment to a consequence or a link, and check the result against
the documentation map. The charters exist and are stated in each document's
opening; the divergence is between them and the contents, so the charter is the
fixed point.

**Evidence to close.** Every topic in the table has one authoritative location
named in the documentation map; no document restates another's subject beyond
the consequence for its own; no work item's scope, steps, or verification
criteria appear outside CoTasks.

**Cost.** Documentation only. No rebuild, no code change.

**Why it is an item.** It has a completion condition and an enumerated scope.
The recurring alternative -- fixing repetition when it is noticed -- is what
produced the current state.

## Maintenance Directions

Ongoing obligations rather than items. Each recurs or has no completion condition,
so numbering it would produce an identifier that never closes.

- Fix publication, catalog, raw, refresh, or retention behavior when it threatens
  correctness, bounded storage, or normal operation.
- Add resource controls for observed accidental or pathological input.
- Maintain Session names and utilization observations without displacing source
  decode, mapping, or search work.
- Reduce the recorded lint and type-error counts. `tools/quality_report.py` reports
  both against a baseline, so a change can be compared rather than asserted clean.
- Prune orphaned catalog entries. Nine Project paths carry two `project_id` entries
  each, one holding a current store and one a stale earlier-format snapshot --
  residue from before the location-identity fix. Nothing is broken by this: every
  live Project queries successfully, and each duplicated path has a working store
  under one of its identities. Pruning is a reviewed maintenance operation on the
  operator's own registry, not a code change.

### Terminology Debt

This document's vocabulary was audited and found to overload seven terms: Registry
(3 senses), Catalog (4+), Source (the formal entity diluted by lowercase
compositional use), Investigation, Pointer, Store (`legacy`/`working` compounds),
and Contract (5 scoped meanings never enumerated). Snapshot carries a vendor-product
false friend. `Audit` is the model case, disambiguated in text at its point of use.

Findings, line numbers, and a suggested definition per sense are in
`experiments/vocabulary-audit-findings.md`. `matching set` is the settled term for
the released file set a store is written under.

The schema half is **W50**; the prose half is ongoing, because a document does not
finish being consistent.

### Hash Derivation

Whether hash derivation is worth segregating into one module with no `hashlib`
reference permitted elsewhere is a question, not a conclusion. A single module
enforces consistency structurally rather than by convention, but the call sites have
little in common beyond calling SHA-256.

Three groupings are candidates and should be judged separately: file and stream
digests (`fileio`, `snapshot`, `raw_store`, `schema_contract`), canonical-document
digests over serialized JSON (`query_api`, `project_catalog`, `catalog_operations`,
`retention`), and identity or key derivation (`identity`, `path_label`,
`tool_identity`, `store`). Only the last is clearly one concern.

The argument in favour is that no single place states which algorithm Codess uses,
so an algorithm change is a wide edit whose wire-format consequences spread across
as many field names and value prefixes. The argument against is that `identity.py`,
`fileio.py`, and `content_processing.py` legitimately decide encoding, chunking,
truncation, and output prefix differently.

## Deferred Directions

Postponed until a concrete consumer or a measured limitation justifies reopening.
None is a tracked item, and none should acquire one without that trigger:

- a mapping expression language;
- remote schema or mapping registries;
- fuzzy cross-vendor identity resolution;
- a built-in general search engine beyond current SQLite predicates;
- standardized Parquet, DuckDB, or merged-database products;
- automatic narrative or assessment generation;
- cost, quota, or billing analysis;
- broad raw-source search; and
- a portable Project name in the review catalog. `local_path_key` names a
  machine-local location by decision, so a reviewed candidate that moves loses its
  reference. Reopening needs a portable input that exists *before* approval, which
  is the point at which a candidate acquires a real Project identity today.
