# CoTasks

CoTasks is the sole list of open Codess engineering work. It contains only
incomplete items: a completed item is removed and its outcome recorded in
[CoReview](CoReview.md), so this document states what is left rather than what
happened.

Identifiers are assigned once and never reused or renumbered. A gap in the
sequence means an item closed; a retained report or a code comment naming an
identifier that is absent here is naming closed work.

## 1. Status Vocabulary

| Status | Meaning |
|---|---|
| **Planned** | Accepted, unblocked, and ordered in [3. Queue](#3-queue). |
| **TODO** | Accepted but unscheduled: no dependency blocks it and nothing waits on it. |
| **Needs decision** | Blocked on a judgment, not on effort. The unanswered question is named on the item. Doing the work first would encode the wrong answer. |
| **Postponed** | Deliberately outside the current phase. The reason is recorded on the item. |
| **Withdrawn** | Examined and rejected. Retained so the reasoning is not rediscovered. |

Priority states how much an item matters. It does not say when the work happens
or what blocks it; [3. Queue](#3-queue) says that.

## 2. Open Items

Fifteen items. Ordered by identifier, which is stable; read
[3. Queue](#3-queue) for what to do next.

| ID | Priority | Status | Work | Completion evidence |
|---|---|---|---|---|
| W04 | High | Planned | Define the shared candidate-record contract and enforce released mapping profiles at the runtime decode boundary. | All three adapters satisfy the typed and runtime candidate contract, pass the same post-decode conformance check, and share strict/diagnostic semantics. |
| W05 | High | Planned | Run named real investigations against the query surface, and produce the worked examples they yield. **A closed item asking for better search reports and query examples is merged in.** The two asked one question from opposite ends: this item wanted predicates "reviewed against actual investigations" without naming an investigation or a reviewer, and the other wanted "improved search reports and structured-query examples" without saying what was inadequate about the eight `codess query` examples README and Operations already carry. Neither could be finished or failed as written. Running the investigations resolves both: it is what produces a worked example, and a predicate the investigations cannot express is exactly the report gap the merged item meant. The check cannot use fixtures, which contain the answer by construction -- it needs three to five questions of the kind 5.1 describes, asked before the data is examined: locate where an instruction first appeared, decide whether a short prompt was human or harness-generated, connect a tool result to its invocation, recover what preceded a failure. Run them against a real Project; each becomes a documented example, and each failure is a finding with evidence rather than a review opinion. | Named investigations run end to end against a real Project; each is documented as a worked example; a predicate or facet they cannot express is recorded as a finding rather than asserted to be adequate. |
| W13 | Normal | TODO | Mechanically enforce architecture and contract paths and make coverage observe child-process execution. Adopting a validation library for query requests is Postponed under 13.4.2, which also records the retained schema files' status in one place. | Import and SQL ownership checks enforce declared layers; scan and ingest execution contributes usable coverage evidence. |
| W14 | Normal | TODO | Require or explicitly mark Project identity for direct library writes. | Separate vendor stores cannot silently create unrelated Project identities for one repository. |
| W16 | Normal | TODO | Evaluate, design, and plan the external investigation interfaces described in Section 9.7; this backlog item does not authorize implementation. | A written decision maps existing capabilities and gaps, selects or rejects data and code integration paths, specifies any proposed contracts, and defines staged work with licensing, privacy, security, and validation criteria. |
| W17 | Normal | **Deferred to a stable baseline** | Expand cross-Project analysis inputs. Cross-Project search is an accepted advanced feature set rather than a hypothetical, so this is no longer waiting for a requester -- it is waiting for the baseline it would be specified against. Reopen when Baseline 2 is met, so the entities, fields, and grain are chosen against a decode that is enforced (W04) and results that state what they missed, rather than against a surface still changing underneath them. | Baseline 2 is met; a consumer then identifies entities, fields, selection, transformation, and output checks. |
| W35 | Low | Postponed | Resolve the validation-fixture inventory. Ten of the sixteen released manifest entries are fixtures; two are read by tests, by direct path rather than through the manifest, and the remaining eight are referenced by nothing but the manifest itself. They therefore cannot fail a test, because no test reads them. They were removed from the write gate, so they no longer gate anything a store does, which is why this is Low rather than Critical: it is now a question about what the released set should contain, not about whether stores can be written. Either wire each fixture into a test that reads it through the manifest, or remove it from the released set; carrying a released file no consumer reads is a claim the repository cannot check. | Every entry in the released manifest has a named consumer, or is removed; a test fails if an entry acquires none. |
| W43 | Low | **Withdrawn on inspection** | The table was proposed from the complexity score before reading the function, and the function already is one where it can be. Five `for key in (...)` loops apply a shared rule to **30 fields using 10 branches**; the remaining **28 branches are each a distinct rule** -- format, action, sortedness, cross-field agreement between `project_snapshots` and `project_ids`, `since <= until`. A table over those would need a per-entry predicate and message, which is the code that exists with a dictionary wrapped round it. Kept as a note: `resource_policy` raises 8 field errors with no loop and is the better candidate if this pattern is pursued. |
| W50 | Normal | **Partly landed; `source` and plurality remain** | Reconcile schema names with the terminology Codess.md 7 defines. **Landed in format 6**: `mapping_diagnostics.level` became `granularity`, which was the one defect of the four that made a reader draw a wrong conclusion -- summing a granularity overstates loss -- and the `level`/`diagnostic_level` collision it named is resolved with it (13.4.12). **Remaining**: `source` still carries three meanings across 26 columns (a transcript file, a vendor, an adapter key), and the four `*_content` link tables still disagree with `event_artifacts` on plurality. Both are wire-format, so they batch with W51 rather than landing alone. | Every term in a table or column name is either defined in Codess.md 7 or is a plain English word carrying no Codess meaning; `source` names one thing; plurality has one rule and one stated exception. |
| W51 | Normal | Planned | Resolve the source-identity naming, measured against peer projects rather than against our own v1. **v1 is not evidence**: `schema/legacy/coschema-v1.sql` has two tables, was generated, and was never reviewed or approved, so it cannot settle a convention. **The rule, surveyed across four peer SQLite schemas holding 56 tables**: 11 are singular and **every one is a mass noun** -- `metadata`, `evidence`, `coverage`, `usage`, `provenance`, `audit`, `store_meta`. Countable-entity tables are plural without exception. The survey itself is developer context (`experiments/peer-project-references.md`); the rule is what applies here and is checkable against CoSchema alone. **That settles CoSchema's four `*_content` tables**: `event_content` averages 1.27 rows per Event, so it is a countable set and should be `event_contents` -- or, better, renamed to what it holds. `store_meta` is correctly singular by the same rule. **`_id` carries four incompatible formats**, which is the sharper defect: `sessions.id` is a vendor UUID, `sessions.entity_id` a `codess:session:sha256:` derivation, `sources.id` a bare SQLite rowid, `sessions.source_system_id` a dotted literal `anthropic.claude-code`. A reader cannot tell from the suffix whether a value is derived, assigned, or borrowed. **`source_system_id` is not an identifier under that reading** -- it is `vendor + "." + product` composed in the mapping profile, so `source_system` or `source_system_key` says what it is. **Superseded in part**: `vendor_name` is not merely a redundant tag but the wrong fact for a harness running another provider's model, so [CoNames](CoNames.md) owns its disposition rather than this item. **`product` is required by `mapping-contract.json` and defined nowhere**: no vocabulary, no examples, no CoSchema entry, and `sessions.product_name` holds only the three literals the profiles supply. Either define it or drop it: `sessions.product_name` was removed in format 6 for being a pure function of `source_system_id`, and the contract's `product` is that value under another name. **`sessions.source` is the `SOURCE_PROFILES` dict key** -- `Claude`, `Codex`, `Cursor`, confirmed across 601 real Sessions -- so `adapter_key` names it honestly and frees `source` for the Source entity the glossary defines. Wire-format; batch with the regeneration. | One suffix rule states whether a value is derived, assigned, or borrowed; `source` names the Source entity only; every contract-required field has a definition and examples; plurality follows the mass-noun rule the peer schemas already use. |
| W55 | Normal | Planned | Unify text and record parsing across the decode layer. **Measured**: 98 `json.loads`, 42 SQLite `json_extract`, 38 `startswith`, 31 `re`, 20 `split`, 4 `removeprefix`, 7 `fromisoformat`, 8 `urllib.parse` -- spread over 38, 6, 17, 9, 15, 4, 6, and 4 modules. The ordering is sound (a parser first, a regular expression last) but the spread is not: 17 modules classify a prefix by hand where 4 use `removeprefix`, and 15 split on a separator with no shared helper. **Three specific candidates.** (1) The `mcp__`/`mcp_`/`mcp-` server split is implemented twice, in `store._tool_namespace` and `mcp_audit._mcp_candidate`, against the same three vendor spellings. (2) Timestamp parsing appears in all three adapters with slightly different fallbacks, where one bounded parser would serve. (3) The Codex output header is the only free-text regex that carries decoded fields; it should stay regex but its field table belongs beside the other vendor vocabularies rather than inside the adapter. **Also assess whether a library replaces hand-rolled work** -- `email.parser` or `dateutil` for the timestamp fallbacks, and whether SQLite's own JSON functions can replace materializing rows Python then re-parses, which is the 98-against-42 imbalance. Correctness-neutral, so it batches with no regeneration. | One helper per parsing concern; no vendor spelling is matched in two modules; a new adapter reaches for the same tools in the same order. |
| W64 | Normal | Planned | **Decide the codebase-wide typing posture, and enforce it.** Annotations are complete: every function has a return type and every argument has one -- `argparse.Namespace` for a CLI entry point, a real type where determinable, an explicit `Any` where the value is genuinely unconstrained. `--disallow-untyped-defs` now adds **10** errors where it added 85. The count fell from **190 to 107** by fixing what was there rather than reclassifying it, and `refresh_operations` reached zero. **What remains is decisions.** (1) *Which strict flags to enable.* `disallow_untyped_defs` is within reach; `strict_optional` and `warn_return_any` were deferred to W04 on the grounds that errors concentrate at the decode boundary, which is measurably false -- of 107, **40 are at the decode boundary and 67 are not**. (2) *Where `Any` is honest.* One explicit `Any` on the heterogeneous env-value table removed **50** spurious errors; the rule wants stating -- `Any` at a deliberately heterogeneous boundary is documentation, `Any` threaded onward is an escape. (3) *Where a `TypedDict` pays.* It typed `refresh_operations`' kwargs bag to zero errors at **no runtime cost**, because an annotated literal is a plain dict at 47 ns while the `TypedDict(...)` constructor form costs 120 ns -- so the annotation is free and the constructor is not. The remaining `arg-type` and `assignment` errors concentrate in the `opts` and `settings` bags threaded through ingest, where the same measurement applies. | The enabled flag set is recorded with the reasoning for each; `Any` appears only where a stated rule permits it; the type count falls rather than being reclassified; `tools/quality_report.py` gates on the baseline. |
| W65 | Normal | Planned | **Consolidate the relay parameter groups that remain.** Measured over 787 functions: 80 take five or more parameters and 18 take eight or more. Separating them by use gives two populations -- **builders**, whose parameters become a returned literal and are correct as they stand (`codex._base_event` places all 19 into its dict, `query_api.make_request` 12 of 13), and **relays**, whose parameters are forwarded to another call and are the struct candidates: `review_project.refresh_candidates` forwards 10 of 14, `baseline_operations.apply_project` 10 of 12, `ingest_cmd._ingest_project` 10 of 10. **The run-invocation cluster is done** -- `ChildInvocation` replaced three hand-built argv lists and three `PYTHONPATH` setups (CoReview 4.18). **Two remain.** The *record-context* group (`session_id`, `source_file`, `line_num`, `opts`) appears in seven adapter functions and is the identity of the record being decoded; it belongs with W04, because doing it separately rewrites the same adapter signatures twice. The *catalog-refresh* relay chain (`refresh_candidates` -> `apply_project` -> `onboard_catalog`) threads ten values through three layers and owns no other item. **Note what consolidation does and does not buy**: `ChildInvocation` removed three specifications of one command line and collapsed a test from two patch points to one, while leaving every caller's parameter count unchanged -- the callers still receive those values to build the object. A signature shortens only where a relay can take the object instead of its fields. | Each recurring parameter group is either one named object or recorded as a builder whose parameter list is its subject; no argv or environment is constructed in two places; a test fails when a second builder appears. |
| W66 | High | Planned | **Unify configuration into one subsystem.** Measured: **172 argparse flags**, **94 of them carrying a default**, **83 `CODESS_*` variables** in `config`'s table, **8 `os.environ` reads outside `config`**, and **39 flag or variable names spelled in more than one module**. A value's default is currently decided in up to four places -- a compiled constant in `config`, an `env_*` reader, an argparse `default=`, and a `getattr(args, ..., None) or CONSTANT` fallback at the use site -- and nothing states which wins. `--registry` and `--dir` each appear in four modules; `--source`, `--raw-mode`, `--min-size`, `--force`, and `--resource-policy` in three. **The precedence is real and undocumented**: `project._settings` resolves `int(MIN_SIZE if raw is None else raw)` while `schema_contract` and `fileio` read their environment variables directly *because* `config`'s constants have already resolved by the time a flag is parsed -- a genuine ordering constraint that three modules work around individually. **Scope**: one component owning declaration, default, precedence, and validation for every setting, so a new option is one table row rather than four edits; the ordering constraint stated once rather than worked around; and a config file admitted as a source, which no current path supports. `ChildInvocation` is the shape for the argv half and is done (CoReview 4.18). | One declaration per setting names its flag, variable, default, and type; precedence is stated and tested; no module reads `os.environ` for a declared setting; a flag name appears in exactly one module. |
| W67 | Normal | Planned | **Move relay fields into the objects that carry them.** `run_ingest` went from **8 parameters to 1** by taking `ChildInvocation` rather than its fields, which also exposed that its two callers built the same invocation twice -- the repeat run exists to prove the first is reproducible, so the two must not be able to differ. **Remaining relays**, measured by parameters forwarded rather than used: `review_project.refresh_candidates` (10 of 14), `baseline_operations.apply_project` (10 of 12), `ingest_cmd._ingest_project` (10 of 10), `catalog_operations.onboard_catalog` (8 of 10), `ingest_publication.publish_snapshot` (6 of 10). Each threads a group that already has, or wants, a name. **Do not convert a builder.** `codex._base_event` takes 19 parameters and places all 19 into its returned dict; the list *is* the record's shape, and an object would name the same fields twice. The distinction is measurable -- parameters reaching a literal against parameters reaching another call -- and is the rule to apply. | Every relay of five or more parameters takes an object or is recorded as a builder; a call site cannot mis-order same-typed arguments; no invocation is constructed twice where one would do. |

## 3. Queue

One ordering. Section 14 previously carried three -- a grouping by what an item
changes, a ranking of those groups, and a batching by shared cost -- and they
drifted apart: an item landed while two of the three still listed it as open.
This is the single order, and the reason for each position is a dependency or a
stated cost, not a preference.

| Rank | Item | Why here |
|---|---|---|
| 1 | **W05** | The only item whose output is evidence about whether the query surface answers real questions rather than machinery that supports them. Cheapest of the three and cheaper than when written: format-6 stores exist, rebuilt and audited, so the work does not start by rebuilding anything. |
| 2 | **W04** | Structural, and coverage reporting states loss against exactly the profiles it enforces -- a report built against unenforced profiles attests to nothing. Baseline 2's substance. |
| 3 | **W50 + W51** | The naming resolutions format 6 did not carry. Both are wire-format, so they land together as one rebuild or they cost two. |
| 4 | **W67** | Immediate and mechanical: each relay already has an object to take, and the measurement that separates a relay from a builder is written down. Ranked above the configuration work because it is the smaller half of the same problem and does not wait on it. |
| 5 | **W66** | The largest structural item on the list, and the one whose absence keeps producing the defects above: 39 names in more than one module is how a flag rename reaches two of three call sites. Below W67 only because `ChildInvocation` already proved the shape on the argv half. |
| 6 | **W64 + W65** | Ranked after W04 rather than before it, because W04 changes the decode boundary where 41 of the 144 type errors sit -- deciding the strict-flag set first would decide it against a boundary about to move. The errors *outside* that boundary are the part W04 will not touch. W65 sits here for the same reason: its record-context cluster is adapter signatures, so consolidating before W04 rewrites them twice. |

**Ranks 4 and 5 are complete.** The performance workloads, the bounds that needed
them, and the reporting subsystem all landed;
[CoReview 4.14](CoReview.md#414-measured-workloads-and-the-bounds-that-needed-them)
and [4.15](CoReview.md#415-eliminating-the-progress-shim) record what each
established, including two defects the measurement found that inspection had not.

**Not scheduled**, and each for a stated reason rather than for lack of room:

| Item | Why not queued |
|---|---|
| **W13** | Its mechanical checks are cheaper after the items that would otherwise fix their targets in place. The SQL-ownership rule it would enforce is already true, so the check locks it in rather than forcing a migration. W64's strict-flag decision is the typing half of the same question. |
| **W14** | Small and independent. Fits any gap; nothing waits on it. |
| **W16** | Postponed: no consumer has asked for external interfaces, and an item nobody is waiting for does not belong in an ordered queue. |
| **W17** | Deferred to Baseline 2 by decision. Specifying a cross-Project surface against a decode W04 has not yet enforced would fix it against a surface still changing underneath. |
| **W35** | Postponed. No longer gates anything a store does; it is now a question about what the released set should contain. |
| **W43** | Withdrawn on inspection. Retained so the analysis is not repeated. |
| **W55** | Correctness-neutral parsing consolidation, so it batches with anything and blocks nothing. |

### 3.1 The One Cross-Item Constraint

**W50 and W51 must land together.** Both rename stored columns, and each alone
owes a full rebuild of every Project from vendor Sources -- Codess never migrates
a store, because the store is a projection and the way to change a projection is
to recompute it. Landing them separately costs two rebuilds for one result.

This is the constraint format 6 was assembled to respect and then did not fully:
its measured removals were ready and W51's naming questions were not, so W51 was
left out and now owes the rebuild the batch existed to avoid. That was a
deliberate trade, and it is the reason these two are ranked together rather than
individually.

### 3.2 What a Rebuild Costs

A wire-format change is not an `ALTER TABLE`. `require_store` accepts only the
current format, for reading as well as writing, so every `.codess` store on a
machine is unreadable by the new code until its Project is reingested. Concretely:
install the new contract, `codess ingest --force` every Project, republish.

Format 6 cost 22 Project rebuilds. That figure is the argument for batching: it
is paid once per format regardless of how many columns change, so a change that
is ready should not wait, and a change that is not ready should not force the
batch to wait for it.

### 3.3 Getting Back to Solid Ground

This session changed 92 files across several kinds of work at once -- a wire
format, a reporting subsystem, a documentation split, a naming convention, and a
type-annotation sweep. Each is complete and validated on its own, but "complete"
is only checkable if the boundaries are stated. This section states them, so the
next session starts from a known position rather than reconstructing one.

#### 3.3.1 What Is Complete and Validated

Each of these is finished, exercised against real data, and guarded by a test
that fails if it regresses. None has a remaining part.

| Change | Validated by |
|---|---|
| **CoSchema format 6** -- nine constant columns removed, `level` renamed to `granularity`, one vendor table | 22 Projects rebuilt from vendor Sources; all 22 query successfully |
| **Reporting subsystem** (`codess.reporting`) | Gates G1-G5; real ingest at 32 sessions / 76,750 events; stdout byte-identical across profiles |
| **`ProgressTrace` removed** | The class is gone; 38 event names registered; per-Project retention moved to `CollectorSink` |
| **Bounded discovery traversal** | 727 directories measured against a 200,000 default; a 500 bound stops at 501 and still returns 159 Projects |
| **Ancillary read bounds** | Persisted output refused above 8 MB *before* reading; manifest streamed; worktree digest bounded |
| **Measured workloads** (`codess.workload`) | Found and fixed a 1.9x `overview` regression with results verified equal |
| **`ChildInvocation`** | Three argv builders and three `PYTHONPATH` setups became one; real child run verified |
| **Documentation split** | CoPlan / CoTasks / CoReview / CoNotes; zero broken anchors across all documents |
| **Quality baseline gate** | `tools/quality_report.py` fails on a rise; verified by injecting a type error |

#### 3.3.2 What Is Deliberately Set Aside

Named so it is visibly *not* forgotten. None of these is partly done -- each is
either untouched or has a stated stopping point.

| Set aside | Stopping point | Item |
|---|---|---|
| Naming convention applied codebase-wide | The rules are written and enforced for the two mechanical cases (parameter over module function, parameter rebind). Applying the subject-word and general-word rules to existing names is **not** started, deliberately: it is a wide diff with no behavioural content. | W64 |
| Relay parameter consolidation | `run_ingest` converted (8 parameters to 1) as the worked example. Five further relays identified and untouched. | W67 |
| Configuration unification | Measured (172 flags, 83 variables, 39 duplicated names) and not begun. | W66 |
| mypy strict flags | Count reduced 190 to 107 by repair. Which flags to enable is undecided. | W64 |
| Record-context parameter group | Identified; blocked behind W04 because it changes adapter signatures. | W65 |
| Nine orphaned catalog entries | Every affected path has a working format-6 store, so nothing is unqueryable. Pruning is operator data maintenance. | 3.3.3 below |

#### 3.3.3 Operator Data, Not Code

Nine Project paths carry two `project_id` entries each, one holding a current
format-6 store and one a stale format-3 or format-4 snapshot. They are residue
from before the location-identity fix, when a re-derived `location_id` produced a
second catalog entry for one directory.

**Nothing is broken by this**: all 22 live Projects query successfully, and each
duplicated path has a working store under one of its two identities. The stale
entries cost disk and make `storage registry-prune` report more than it should.
Pruning them is a reviewed maintenance operation on the operator's own registry,
not a code change, and is deliberately left to the operator.

#### 3.3.4 The Order to Resume In

One kind of change at a time, each validated before the next begins. The queue in
[3. Queue](#3-queue) gives the ranking; this gives the discipline:

1. **Commit the current state first.** 92 files across several kinds is already
   more than one reviewable change; adding to it makes the next bisection harder.
   The split by kind is in 3.3.1, and each row is a defensible commit boundary.
2. **Finish a kind before starting another.** The recurring defect this session
   was a change of one kind exposing an unrelated one and both being pursued at
   once -- which is how a rename reached a call site it should not have.
3. **Run `tools/quality_report.py` before declaring a kind complete.** It gates on
   ruff and mypy against recorded ceilings, and it caught two regressions this
   session that the test suite did not.

## 4. Maintenance Directions

Ongoing obligations rather than items. Each is work that recurs or has no
completion condition, so numbering it would produce an identifier that never
closes.

- Fix publication, catalog, raw, refresh, or retention behavior when it
  threatens correctness, bounded storage, or normal operation.
- Add resource controls for observed accidental or pathological input.
- Maintain Session names and utilization observations without displacing source
  decode, mapping, or search work.
- Reduce the recorded lint and type-error counts. `tools/quality_report.py`
  reports both against a baseline, so a change can be compared rather than
  asserted clean. The type errors concentrate at the decode boundary W04 will
  change, which is why they are not a tracked item of their own.

### 4.1 Terminology Debt

This document's own vocabulary was audited and found to overload seven terms:
Registry (3 senses), Catalog (4+), Source (the formal CoSchema entity diluted by
lowercase compositional use), Investigation, Pointer, Store (`legacy`/`working`
compounds), and Contract (5 scoped meanings never enumerated). Snapshot carries a
vendor-product false friend. `Audit` is the model case, disambiguated in text at
its point of use.

Findings, line numbers, and a suggested definition per sense are in
`experiments/vocabulary-audit-findings.md`. `matching set` is the settled term for
the released file set a store is written under.

The schema half of this is **W50**; the prose half is ongoing, because a document
does not finish being consistent.

### 4.2 Hash Derivation

Whether hash derivation is worth segregating into one module with no `hashlib`
reference permitted elsewhere is **a question, not a conclusion**. A single module
enforces consistency structurally rather than by convention, but the call sites
have little in common beyond calling SHA-256.

Three groupings are candidates and should be judged separately: file and stream
digests (`fileio`, `snapshot`, `raw_store`, `schema_contract`), canonical-document
digests over serialized JSON (`query_api`, `project_catalog`,
`catalog_operations`, `retention`), and identity or key derivation (`identity`,
`path_label`, `tool_identity`, `store`). Only the last is clearly one concern.

The argument in favour is that no single place states which algorithm Codess
uses, so an algorithm change is a wide edit whose wire-format consequences spread
across as many field names and value prefixes. The argument against is that
`identity.py`, `fileio.py`, and `content_processing.py` legitimately decide
encoding, chunking, truncation, and output prefix differently.

## 5. Deferred Directions

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
  machine-local location by decision, so a reviewed candidate that moves loses
  its reference. Reopening needs a portable input that exists *before* approval,
  which is the point at which a candidate acquires a real Project identity today.
