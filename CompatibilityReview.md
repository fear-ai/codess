# CoSchema v2 compatibility review

## Decision

The first bounded Claude, Codex, and Cursor baseline set is frozen as
`accepted_with_known_gaps`. This is a reviewed compatibility baseline, not a
claim that every upstream shape is represented. The immutable identities are
in `catalog/reviewed-baselines.json`; `tools/verify_reviewed_baselines.py`
detects pointer, package, semantic-digest, policy, raw-evidence, or validation
drift.

## Reviewed baselines

| Project | Vendors | Sessions / events | Raw evidence | Result |
|---|---|---:|---|---|
| `Code/SWEmore` | Codex | 1 / 275 | 1 captured object | Accepted; 19 explicit missing-call-id diagnostics |
| `Spank/spank-py` | Claude | 6 / 2,937 | 6 captured objects | Accepted |
| `ZK/Zero400` | Claude, Cursor | 20 / 4,487 | 5 references | Accepted with five reproducibility limitations |

All three passed two forced ingests with equal source revisions and canonical
semantic digests. Package/store/raw hashes, SQLite integrity and foreign keys,
manifest counts, event ordering, JSON fields, artifact identity, policy limits,
and six query modes passed.

## Semantic review findings

The review sampled normalized locators and mapping traces for prompts, model
responses, tool calls/results, permission denials, failures, compaction,
subagent linkage, slash commands, artifacts, and Cursor inferred turns. Prompt
and response content was not copied into this report.

Three defects were found and corrected before freezing. First, Claude error tool results
arrive in a vendor `user` envelope, but they are tool outcomes rather than human
prompts. Denials and failures now map to `tool.result` / `tool` /
`tool_result`, populate `tool_results`, and carry `denied` or `failed` status.
The rebuilt real baselines contain 33 such error results in spank-py and 9 in
Zero400. A hazard fixture prevents regression while keeping failed Codex tool
calls classified as model invocations.

Second, 54,290 Cursor type-2 envelopes contained only whitespace message text
and repeated harness/context fields. They are no longer called model responses;
tool results would still be retained if present. Third, Cursor copied the same
logical message up to nine times under different local keys. Within a composer,
records with the same `(type, serverBubbleId)` now retain only the earliest
observed copy. There is no cross-composer or content-similarity deduplication.
The Cursor baseline consequently contains 642 prompts and 2,582 responses
rather than 60,368 mostly non-message events. Its average interaction fell from
82.5 to 3.9 events and its maximum from 32,360 to 556. The packaged Cursor
hazard fixture covers both rules.

Artifact review also found that every spank-py artifact and eight Zero400
artifacts resolve outside the selected project root. These now use `file:` URIs
and explicit `path_scope=external` metadata instead of misleading `../`
project-relative identities. In-project artifacts retain normalized relative
paths.

The selected Codex baseline has 113 calls and 94 linked results. Its 19 calls
without stable call identifiers remain explicit diagnostics rather than guessed
lineage. The Claude stores have complete call/result rows after the correction:
1,063 / 1,063 in spank-py and 437 / 437 in Zero400. One real compaction and two
real subagent parent links are represented. Every selected session and event has
a source timestamp; missing-time behavior remains fixture-covered.

Ordinary Claude results now retain the source's explicit non-error evidence as
`succeeded`: spank-py has 1,030 succeeded, 29 failed, and 4 denied outcomes;
Zero400 has 428 succeeded, 7 failed, and 2 denied. Failures are usually followed
quickly by another call to the same tool: 20/25 Bash, 9/10 Edit, 2/5 Read, and
2/2 WebFetch failures were retried within five normalized events.

The searches found substantial concurrent Claude/Cursor work windows in
Zero400 (approximately 784 and 516 minutes for the two main Claude sessions),
but no exact shared message text and no shared artifact identity. This is
evidence of temporal overlap, not proof of shared authorship. External artifact
evidence shows spank-py sessions working heavily on Code/Misses material and
also touching spank-rs; this is now queryable without assigning those files to
spank-py itself.

## Coverage matrix

| Requirement | Real corpus | Fixture / automated evidence | State |
|---|---|---|---|
| Claude, Codex, Cursor ingestion | All three | CI fixture policy | Covered |
| Tool calls and results | Claude and Codex | lineage tests | Covered for represented vendors |
| Permission denial / failed result actor semantics | Claude | `hazard/claude-error-tool-results.json` | Covered |
| Compaction | Claude | adapter audit fixture | Covered |
| Lifecycle abort | None | Codex audit fixture | Fixture-only |
| Subagent linkage | Claude | adapter/store tests | Covered |
| Missing timestamps | None | `edge/null-session-times.json` | Fixture-only |
| Unknown/unmapped semantics | None | rejection/diagnostic tests | Fixture-only |
| Cursor project scoping and inferred turns | Zero400 | policy invariants and adapter tests | Covered |
| Cursor non-message envelopes and stable bubble deduplication | Zero400 | `hazard/cursor-nonmessage-copies.json` | Covered |
| External versus project-scoped artifact identity | spank-py, Zero400 | store/query tests | Covered |
| Same artifact across vendors | None | `golden/cross-vendor-artifact.json` | Fixture-only |
| Exact model, effort, speed settings | Source records expose only provider in the Codex sample | model-configuration storage tests | Source-data gap |
| Exact raw recovery | SWEmore, spank-py | hash/decompression checks | Covered |
| Reference-only raw behavior | Zero400 | stability checks and explicit limitations | Covered with limitation |

Reference-only apply validation requires the live locator to remain at the
ingested revision through both fixed-point runs. Later frozen-set verification
checks retained identities without requiring that mutable vendor database to
remain unchanged; it continues to report the lack of exact retained raw bytes.

No additional real project is added now. The uncovered items are either already
bounded by fixtures or require an upstream shape that the current candidates do
not supply. Candidate expansion should be evidence-triggered, not exhaustive.

## Retained snapshot access

Querying a retained snapshot now requires `--snapshot-id`. The default package
policy is `exact`; it refuses a snapshot whose recorded CoSchema package digest
differs. `--snapshot-package-policy read-compatible` is an explicit escape hatch
for the same supported database format: it verifies snapshot, raw-manifest,
store, identity, count, and SQLite contract hashes, emits a mapping-parity
warning, and does not update current registry counts.

The retained SWEmore pre-review snapshot was tested: exact mode rejected its old
package, read-compatible mode returned 1 session and 275 events with the warning,
and exact mode read the new reviewed snapshot. Recovering old mapping semantics
still requires the recorded matching software/package; format compatibility is
not presented as semantic identity.

## Remaining execution order

1. Correlate external artifact URIs to known catalog project roots using
   evidence and confidence without changing session ownership.
2. Resolve Codex parent-session support only from direct referential fields.
3. Monitor for a bounded modern Cursor tool-call/result shape and add a fixture
   before mapping it. Current Zero400 and zerowallet400 candidates contain none.
4. Add a real same-artifact multi-vendor project only when current scoped data
   supplies one; keep the golden fixture as the contract meanwhile.
5. Capture exact model name/effort/speed only when the vendor source explicitly
   provides them.
6. Re-run the reviewed-baseline verifier after source refreshes and freeze a new
   set only after semantic sampling.
