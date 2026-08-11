# Code Review Notes

Running record of implementation-review sessions: what was checked, how, what
was found, and — as important as the findings themselves — which flagged
issues were verified as false positives and why. This is a working log, not a
decision register; accepted conclusions that change behavior or policy belong
in CoPlan.md (Section 10.4 Secure Coding, Section 13 Code Review, Section 14
Work Registry), not here. This file exists so a later review does not
re-derive the same verification from scratch, and so a lint tool's raw
finding count is never mistaken for a defect count without the read-through
that separates the two.

## 1. Full Implementation Review

Scope: `src/codess/` (36 modules), `src/cli/` (4 modules),
`src/codess/adapters/` (3 vendor decoders), 46 test files. Full findings are
recorded in the conversation that produced this session's CoPlan.md Section
10.4 addition and the code changes below; this entry summarizes method and
numbers so they don't need re-deriving.

### 1.1 Tooling Baseline

No `[tool.ruff]` or `[tool.mypy]` section exists in `pyproject.toml`. Every
run in this session used explicit flags rather than project defaults:

```bash
ruff check src/ tests/ tools/ --select ALL --statistics   # broad triage
ruff check src/ --select <RULE> --output-format concise   # isolated verification
mypy src/ --ignore-missing-imports --no-error-summary
pytest -q --cov=codess --cov=cli --cov-branch --cov-report=term-missing
```

**Methodology correction, discovered mid-session:** a broad `--select ALL
--statistics` summary is a triage instrument, not a citable count. Checked
against an isolated `ruff check --select <RULE>` run for two rules this
session, the broad summary's per-rule figures came out several times larger
than the isolated, actually-verified count for both -- large enough that a
report citing the broad number without isolating it would have overstated
the true finding count by roughly an order of magnitude, in both directions
checked. `S608` happened not to show this drift (broad and isolated agreed),
which is itself the trap: a rule showing no drift on first check does not
license skipping the isolated re-run on every other rule, since drift was
present for two of the three rules actually compared and absent was only
confirmed, not predictable in advance.

The generalizable rule, independent of which specific numbers were involved
this session (and they should not be treated as durable facts about this
codebase -- both counts will drift as the code changes): **before reporting
or acting on any lint/static-analysis finding count, re-derive it with the
narrowest command that isolates exactly that rule, and treat the broad
run's number as an upper-bound triage signal only.** This generalizes past
ruff -- any tool that reports aggregated statistics across a combined
run (a combined `--select`, a merged report across multiple linters, a
coverage tool summing over parallel workers) is a candidate for the same
check. The actionable follow-up is in the harness/tooling layer, not in this
codebase: search or review commands built on top of a static-analysis tool
should default to isolating the rule/check being reported on, or should
flag when a summary count and an isolated re-run were not both taken, so
this class of overstatement doesn't require a human to remember to check
for it each time.

### 1.2 Ruff Categories Fully Verified (Zero Real Defects)

Every hit in each category below was read at the source line, not accepted
or dismissed from the rule name. None produced a behavior change beyond what
is noted.

| Rule | Verdict | Note |
|---|---|---|
| `S608` (possible SQL injection) | All false positives | Three recurring safe shapes; see CoPlan.md 10.4 for the patterns and rewrite-vs-suppress criteria. Some sites (`evidence.py`, `storage_report.py`, `baseline_operations.py`, part of `baseline_validation.py`) were rewritten to eliminate the warning entirely; most carry `# noqa: S608` with a module-docstring justification, since most sites do not fit a warning-free rewrite (10.4.2 explains why by pattern). Run `tools/report_sql_suppressions.py` for the current count and file list, and to confirm no site is unsuppressed (unreviewed). |
| `B023` (loop-variable closure capture) | All false positives | Every flagged closure is invoked synchronously within the same loop iteration (e.g. as an `after_replace` callback executed before the next iteration), not stored for deferred execution. Confirmed by reading the calling function (`commit_source_replacement`), not just the closure site. |
| `PLW1510` (subprocess without `check=`) | All false positives | Every site inspects `result.returncode` explicitly and returns it as structured pass/fail data; `check=True` would force a try/except at every call site for no benefit, since the caller already handles non-zero exit as data. |
| `PLW2901` (redefined loop name) | All false positives | Each reassigns the loop variable to a normalized form of itself (`project_root = project_root.resolve()`, `line = line.rstrip(...)`) for use within the same iteration only; no closure or deferred reference captures the pre-reassignment value. |

Run `ruff check src/ --select <RULE>` for the current count and locations
of any rule above; none is recorded here, including in this sentence,
because every prior attempt to keep a hand-maintained count in this file
went stale or was simply wrong within the same session that wrote it (see
1.1's methodology correction below) -- the fix was to stop writing counts
at all, not to try to write them more carefully.

**On closures and late binding (why B023 needed a synchronous-call proof, not
a pattern match):** Python closures — `def`-nested functions and `lambda`
alike — capture the enclosing scope's variable by reference to its cell, not
by value at definition time; the closure body resolves the name when
*called*, not when defined. A loop that creates closures across iterations
but calls them only after the loop advances will see every closure read
whatever the shared loop-variable cell holds *last*, not what it held when
that particular closure was created — the standard `[lambda: i for i in
range(3)]`-prints-`2,2,2` failure. Every B023 site here avoided this because
the closure is invoked synchronously, inside the same iteration, before the
loop advances (verified by reading the function the closure is passed into,
e.g. `commit_source_replacement` calling `after_replace(conn)` before
returning) — the hazard requires the closure to be *stored and invoked
later*; none of these are. This is also why ruff's static check cannot
resolve the question itself: proving "never escapes this iteration" needs
call-graph reasoning past what a linter typically performs. Preferred fix
where a rewrite is wanted, ranked above the default-argument-capture idiom
(`lambda i=i: ...`, which works only because default argument values really
are evaluated at definition time — a narrow, easily-forgotten exception to
otherwise-uniform late binding, not a pattern to build on): eliminate the
closure's dependency on the outer scope by passing the current value as an
explicit parameter, or by binding it eagerly with `functools.partial`, which
is not a closure at all and requires no late-binding reasoning to verify —
`ingest_cmd.py:547`'s `lambda conn: _record_raw(opts, path, "Codex", conn)`
is the one lambda-shaped site among the five and the clearest candidate for
that rewrite, purely to remove the need for a future reader to re-derive the
synchronous-call proof rather than because current behavior is wrong.

### 1.3 Ruff Categories Explicitly Left Open

Not cleared, not flagged as defects — genuinely unexamined at the
per-site level this session. Do not cite these as "reviewed and safe."

- `S603` / `S607` (subprocess call / partial executable path) — a narrower
  spot check (confirming `subprocess.run` calls use argument lists, never
  `shell=True`) did not surface a concern, but this is not the same
  site-by-site read `S608` received. Recorded as open in CoPlan.md 10.4.4.
- `S105` (hardcoded-password-string) — same status; not read site-by-site.
- `ANN*` (missing type annotations) — real signal exists (see mypy findings,
  151 errors, concentrated in `ingest_cmd.py` and the three adapters) but
  ruff's `ANN*` rules duplicate what mypy already reports more precisely;
  treating both as separate action items double-counts the same gap.
- `D1xx` (missing docstrings) — deliberately not a target. CLAUDE.md's own
  style guidance ("no comments unless the WHY is non-obvious") argues against
  enforcing `D1xx`, not for it.
- `PLR0912` / `PLR0915` / `PLR0911` / `PLR0913` (complexity/size/arg-count) —
  not false-positive-checked in the same sense as the injection/closure
  rules above, because these don't have a "safe pattern" to verify against;
  see Section 2 below for the classification these actually needed.

### 1.4 Code Changes Made This Session

1. `configuration_audit.py` — replaced `configuration_params = params + params`
   with `turn_branch_params`/`default_branch_params`, named after the two
   `EXISTS` branches each copy binds. Behavior unchanged; makes the
   params-count-must-match-predicate-occurrence-count pairing explicit so a
   future edit to one branch doesn't silently break the other's binding.
2. `evidence.py::summarize_store_evidence` — replaced an f-string table-name
   interpolation (`f"SELECT COUNT(*) FROM {key}"` inside a loop over a fixed
   4-entry tuple) with a literal `_TOTAL_COUNT_QUERIES` dict of complete,
   pre-written query strings. Confirmed empirically that this eliminates the
   `S608` warning entirely (ruff does not flag a bare dict-value passed to
   `execute()`), unlike a dict *comprehension* over the same tuple, which
   still triggers the rule because the f-string itself is still evaluated
   somewhere in the source, comprehension or not.
3. `storage_report.py` — same rewrite for an 11-table count loop
   (`_TABLE_COUNT_QUERIES`), written as fully literal dict entries rather
   than a comprehension for the same reason.
4. `query_api.py` — added `sanitize_free_text_filter()` and wired it into
   `validate_request()`'s existing `filters.text` / `filters.artifact` type
   check. Bounds free-text filter values (originating from `--text`
   / `--artifact` CLI arguments, i.e. user input, not stored session
   content) to 512 characters, excludes control/formatting characters
   (matching `sanitize.py::CONTROL_CHARS_RE`, deliberately *not* restricting
   to ASCII — searched content is Unicode per CoPlan.md 7.3, and an earlier
   draft of this check incorrectly used an ASCII-only allowlist that would
   have broken legitimate non-English search terms; caught before landing
   by cross-checking against CoPlan's own "Bounded UTF-8 text" language),
   and screens for a short list of injection/markup-shaped patterns
   (`<script`, generic HTML tags, `UNION SELECT`, SQL comment markers,
   destructive-statement keywords following `;`). Three dispositions:
   `reject` (default, raises `QueryContractError`), `strip`, `blank`. This
   is explicitly a size/legibility/defense-in-depth boundary, not the
   mechanism preventing SQL injection — `filters.text`/`filters.artifact`
   were already verified safe as bound `LIKE` parameters before this change
   (see `_like_literal`, `query_api.py`); the new check bounds and screens
   the value before it reaches that already-safe path, independent of
   whether SQL injection was ever reachable through it.
5. Ten new tests added to `tests/test_query_api.py` covering the new
   function's accept/reject/strip/blank paths and its wiring into
   `validate_request`.

Deferred, not built this session: a small internal SQL `Clause`/`Predicate`
helper (pairing an SQL fragment with its bound params so concatenation can't
drift the two out of sync, the general fix for the bug class item 1 above
was a narrow instance of) — documented as a future-phase item in CoPlan.md
10.4.2 rather than implemented, per explicit direction.

### 1.5 Verification Discipline Used

For every "is this actually safe" question this session, the standard was:
read the source at the flagged line, trace the value back to its origin
(literal, parameter, schema introspection, or genuinely external input), and
where a fix was tested, run the specific affected test file plus the full
suite before considering it done. `python3 -m pytest -q` was run after every
substantive code edit in this session; it stayed green throughout except for
one self-caught test-authoring bug (a `pytest.raises` block that didn't
actually wrap the call which raised, fixed immediately by moving the
assertion to wrap `make_request()` instead of the redundant explicit
`validate_request()` call after it).

## 2. Complexity-Metric Classification

Ruff's McCabe check (`C901`, threshold 10) flags a function count large
enough (dozens) that a flat list has no interpretive value. What matters is
*why* each function is complex, because the fix differs by cause: some need
decomposition, some need a standard-library replacement for hand-rolled
logic, some are irreducibly complex validation and should be left alone.
Every function below was read at the source, not classified from the
complexity number or function name alone.

Functional grouping follows CoPlan.md 3.2's component table (Interface,
Vendor decode, Storage services, Query engine, Project catalog, Operational
services, Evidence audits) rather than physical directory, since directory
alone does not separate these concerns in this codebase (Section 2 of
CoPlan.md).

### 2.1 Root-Cause Categories

**A — Too much action in one function (multiple responsibilities that don't
share state, glued together rather than composed).** The function does two
or more things a reader would describe with different verbs, and the things
don't need to share the function's local scope to work.
- `scan.py::run_scan` — per-vendor path discovery (three near-duplicate
  blocks for cc/codex/cursor) followed by a distinct second phase
  (Git-root project-boundary attribution via a nested `project_boundary`
  closure). These are two composable steps, not one.
- `ingest_cmd.py::run` — config validation, source resolution, per-vendor
  dispatch, transaction/publication orchestration, and raw-capture handling
  in one function; see CoPlan.md 13.4.1 (W06) for the existing finding this
  confirms with a specific location.
- `cli/query_cmd.py::run` — hand-built mutual-exclusion checking across
  eleven independent boolean "mode" flags via manual list slicing, instead
  of per-mode dispatch (contrast with `admin_cmd.py`, which already uses a
  clean per-handler pattern in the same codebase — see 2.4).
- `cursor.py::process_db` — bubble-stream iteration, composer-boundary
  detection, progress-event emission, and per-composer dispatch together;
  overlaps with Category B below (see `itertools.groupby`).

**B — Missing standard-library use for a routine task.** The function
hand-rolls logic the standard library already expresses more directly and
more testably.
- `cursor.py::process_db` and `store.py::_prepare_event_groups` — both
  manually track "current group key changed" state across a loop
  (`current_composer`/`current_interaction`) with mutable outer-scope
  variables and inner closures reading/writing them, reimplementing what
  `itertools.groupby` (grouping a stream by a changing key) is for.
- `codex.py::_build_record_maps` — returns a bare 4-tuple of same-shaped
  collections (`dict[str,str], Counter[str], set[str], dict[str,str]`) with
  no names; a `typing.NamedTuple` (standard library, zero new dependency)
  would remove the positional-order burden from every call site without
  reducing the branch count, which is a real but separate complaint from
  complexity itself.
- `load_policy`, `load_project_set`, `_load_project_references`,
  `_validate_raw`, `_validate_current`, `_local_pointer_references` — six
  functions, four different files, independently hand-roll the same
  "read file, `json.loads`, check it's a dict, check a format/schema
  marker, raise a specific `ValueError` per violation" sequence. Not a
  standard-library gap (there is no stdlib "load and validate a versioned
  JSON document" helper) but a missing *internal* shared utility — this
  codebase already has the concept (`schema_contract.py`, `field_state.py`)
  and could extract a `load_versioned_json(path, format_field, expected)`
  helper other than duplicating the pattern six times.

**C — Genuinely flat, not decomposable without relocating the same
complexity.** The branch count is real but each branch is small,
independent, and self-contained; splitting the function would move the
lines into several sibling functions without reducing what a reader has to
hold in mind, because the checks don't share meaningful sub-groupings.
- `query_api.py::validate_request` — a flat sequence of independent field
  checks, each raising its own `QueryContractError`. Already assessed this
  way in the original review; re-confirmed here as Category C rather than
  A or B specifically because no sub-grouping of these checks shares
  state or would be independently reusable.
- `config.py::validate_config` — same shape, smaller (a bounds check per
  environment-derived constant).
- `adapters/cc.py::extract_tool_input` is the boundary case between C and B:
  it reads as "one branch per tool name," which looks like Category C, but
  the per-tool bodies are almost all "copy these N fields if present" —
  close enough to uniform that a `{tool_name: field_list}` dict plus a
  handful of named exceptions (the `edit`/`write`/`grep`/`agent` branches
  that derive fields rather than copy them) would remove most, not all, of
  the branch count. Classified as B (missing table-driven dispatch) because
  the uniform majority outweighs the genuine exceptions.

**D — Parameter-list size correlates with branch count, not a separate
defect but a contributing signal.** Several C901 hits carry 6–14
parameters, frequently with a long keyword-only section:
`_ingest_cc`/`_ingest_cursor` (ingest_cmd.py), `apply_project`
(baseline_operations.py), `refresh_candidates` (candidate_review.py),
`resolve_refresh_selection`/`refresh_projects` (refresh_operations.py). A
function threading this many independent caller-supplied knobs through its
signature is structurally likely to branch on several of them
independently — the parameter count and the branch count are two
symptoms of the same "too many independent concerns in one call" shape as
Category A, not two unrelated findings. Where these functions are also
Category A (most are), the fix is the same: split by concern, and each
smaller function naturally sheds several of the original parameters along
with its share of the branches.

**E — Excessive comments contributing to apparent size.** Checked for and
not found as a meaningful contributor. Functions in this codebase are long
because of branch count and parameter count, not because of comment
density; the flagged functions are, if anything, comment-sparse relative to
their length, consistent with CLAUDE.md's own "no comments unless the WHY
is non-obvious" convention already holding in practice (see 1.3 on `D1xx`).
Not a category with findings here — recorded so a future pass doesn't
re-ask the question without an answer on file.

### 2.2 By Functional Area

| Area (CoPlan.md 3.2 component) | Files with C901 hits | Dominant category |
|---|---|---|
| Interface layer | `cli/ingest_cmd.py`, `cli/query_cmd.py`, `cli/scan_cmd.py`, `cli/admin_cmd.py` | A (multiple responsibilities per command function); `admin_cmd.py` is the outlier — its one C901 hit (`_catalog_candidates`, 11) is mild Category C, the rest of the file already uses per-handler decomposition well |
| Vendor decode | `adapters/cc.py`, `adapters/codex.py`, `adapters/cursor.py` | Mixed A/B — `cc.py::normalize_user` and `codex.py::process_file` lean C (linear, self-contained branches per envelope/record subtype, matching the adapter contract's own "handle every case independently" requirement); `extract_tool_input`, `_bubble_to_events`, `process_db`, `_build_record_maps` lean B (missing dispatch table / groupby / NamedTuple) |
| Storage services | `store.py`, `schema_contract.py`, `snapshot.py`, `raw_store.py` | B for `_prepare_event_groups` (groupby); C for `validate_database_contract`, `snapshot_store_paths_from_base`, `RawStore.observe` (flat validation/observation sequences) |
| Query engine | `query_api.py` | C for `validate_request`; A/B mixed for `_overview`, `_event_rows`, `compare_results` (each accumulates several independent metrics in one pass — could split by metric group, moderate priority) |
| Project catalog | `project_catalog.py`, `project_annotations.py` | A — `ensure_project_binding` and `build_project_annotations` each merge several catalog sub-structures (locations, workspace bindings, aliases) in one function; genuinely related data but currently one function per merge-everything pass rather than one per sub-structure |
| Operational services | `refresh_operations.py`, `retention.py`, `baseline_*.py`, `token_usage.py`, `candidate_review.py`, `codex_source.py`, `cursor_source.py`, `scan.py`, `tool_result_status.py`, `schema_evolution.py`, `evidence_resolver.py`, `config.py` | Mixed — B for the six load/validate-JSON functions (2.1); D (parameter bloat) for `apply_project`, `refresh_candidates`, `resolve_refresh_selection`, `refresh_projects`; C for `validate_config`, `_validate_current`, `_local_pointer_references` |
| Evidence audits | `vendor_audits/claude_features.py`, `vendor_audits/codex_features.py`, `mcp_audit.py`, `orientation_audit.py`, `configuration_audit.py` | C — each is a flat "count this, count that, cross-check the counts" pass appropriate to what an audit is; not flagged as needing decomposition, since splitting an audit's independent tallies into separate functions would not make any one of them easier to verify against its stated question (13.4.6-adjacent: audits are deliberately narrow single-question measurements) |

### 2.3 Priority Reading

Category A + D together (too much action, often also too many parameters)
is the largest and highest-value group: `ingest_cmd.py::run`,
`scan.py::run_scan`, `query_cmd.py::run`, and the catalog-merge functions in
`project_catalog.py` account for most of the highest individual complexity
scores and are the ones where splitting genuinely reduces what a reader
holds in mind, not just where the lines live. Category B is smaller but
cheap to fix and removes a class of future bugs along with the complexity
number (the `groupby` sites are exactly the shape that produces the same
kind of stateful-accumulation bug this session already found and fixed
once, in `store.py`). Category C should not be worked — decomposing
`validate_request` or the evidence audits would satisfy the linter and cost
readability, trading a metric for the thing the metric is a proxy for.

### 2.4 One Cross-File Observation

`admin_cmd.py` and `query_cmd.py`/`ingest_cmd.py` sit in the same directory,
serve the same CLI layer, and are held to the same dependency rules — but
`admin_cmd.py` already does per-subcommand dispatch well (one small
`_xxx(args) -> int` handler per subcommand, wired through
`argparse.set_defaults(handler=...)`), while the other two hand-roll
mode-flag bookkeeping and accumulate workflow logic directly in `run()`.
This means the fix for the Interface-layer Category A functions is not a
new pattern to invent — it is applying a pattern that already exists,
already works, and already ships in this codebase, to the two files that
did not follow it.
