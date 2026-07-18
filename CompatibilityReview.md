# Historical CoSchema v3 compatibility review

This records the retained format-3 baseline and is not the current format-4
acceptance report. Format-4 rebuild and freeze is tracked as **CoPlan A12**.

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
| `Spank/spank-py` | Claude | 6 / 3,958 | 6 captured objects | Accepted |
| `ZK/Zero400` | Claude, Cursor | 20 / 39,184 | 6 captured objects | Accepted |

All three passed two forced ingests with equal normalization digests. SWEmore
and spank-py also had equal source revisions and full semantic digests;
Zero400's live shared Cursor DB advanced between captures, so its policy
accepted only equal observation-independent normalization digests while each
exact source revision remained captured.
Package/store/raw hashes, SQLite integrity and foreign keys,
manifest counts, event ordering, JSON fields, artifact identity, policy limits,
and six query modes passed.

## Semantic compatibility findings

The review sampled normalized locators and mapping traces for prompts, model
responses, tool calls/results, permission denials, failures, compaction,
subagent linkage, slash commands, artifacts, and Cursor inferred turns. Prompt
and response content was not copied into this report.

The accepted mapping enforces three corrections established by review. Claude error tool results
arrive in a vendor `user` envelope, but they are tool outcomes rather than human
prompts. Denials and failures now map to `tool.result` / `tool` /
`tool_result`, populate `tool_results`, and carry `denied` or `failed` status.
The rebuilt real baselines contain 33 such error results in spank-py and 9 in
Zero400. A hazard fixture prevents regression while keeping failed Codex tool
calls classified as model invocations.

Cursor type-2 envelopes containing only whitespace message text and repeated
harness/context fields are not called model responses; tool results are still
retained when present. Cursor also copied the same
logical message up to nine times under different local keys. Within a composer,
records with the same `(type, serverBubbleId)` now retain only the earliest
observed copy. There is no cross-composer or content-similarity deduplication.
The Cursor baseline consequently contains 642 prompts and 2,582 responses
rather than 60,368 mostly non-message events. Its average interaction fell from
82.5 to 3.9 events and its maximum from 32,360 to 556. The packaged Cursor
hazard fixture covers both rules.

Current structure-only evidence shows that Cursor tool evidence lives
in populated `toolFormerData` objects, not the empty `toolResults` arrays. The
mapping now emits source-call-id-linked invocations and outcomes, preserves
`completed`/`error`/`loading`/`cancelled`, and retains `modelCallId` as evidence.
Zero400 contains 13,165 invocations and 17,014 results; 134 inferred model turns
use vendor selection `composer-2.5` and five use `grok-4.5`. Large unmapped
attachment/context fields are discarded after decoding but remain in captured
raw evidence, reducing peak ingest memory from about 6 GB to about 0.6 GB.

Artifact evidence shows that every spank-py artifact and eight Zero400
artifacts resolve outside the selected project root. These now use `file:` URIs
and explicit `path_scope=external` metadata instead of misleading `../`
project-relative identities. In-project artifacts retain normalized relative
paths.

The selected Codex baseline has 113 calls and 94 linked results. Its 19 calls
without stable call identifiers remain explicit diagnostics rather than guessed
lineage. The Claude stores have complete call/result rows after the correction:
1,063 / 1,063 in spank-py and 437 / 437 in Zero400. One real compaction and two
real subagent parent links are represented. Every selected session and event has
a source timestamp; the wider current-store inventory contains real Cursor
missing-time records while the frozen selected baseline uses its edge fixture.

Ordinary Claude results now retain the source's explicit non-error evidence as
`succeeded`: spank-py has 1,030 succeeded, 29 failed, and 4 denied outcomes;
Zero400 has 428 succeeded, 7 failed, and 2 denied. Failures are usually followed
quickly by another call to the same tool: 20/25 Bash, 9/10 Edit, 2/5 Read, and
2/2 WebFetch failures were retried within five normalized events.

The corpus contains substantial concurrent Claude/Cursor work windows in
Zero400 (approximately 784 and 516 minutes for the two main Claude sessions)
and shared normalized artifact paths across the two vendors. This supports
cross-vendor work on the same files; it does not by itself prove shared
authorship or causal handoff. External artifact
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
| Missing timestamps | Cursor records in current stores | `edge/null-session-times.json` | Covered |
| Unknown/unmapped semantics | None | rejection/diagnostic tests | Fixture-only |
| Cursor project scoping and inferred turns | Zero400 | policy invariants and adapter tests | Covered |
| Cursor non-message envelopes and stable bubble deduplication | Zero400 | `hazard/cursor-nonmessage-copies.json` | Covered |
| Cursor tool lineage and source status | Zero400 | adapter/store tests and `catalog/cursor-feature-audit.json` | Covered |
| External versus project-scoped artifact identity | spank-py, Zero400 | store/query tests | Covered |
| Same artifact across vendors | Claude/Cursor paths in Zero400 | `golden/cross-vendor-artifact.json` and evidence inventory | Covered |
| Exact model selection | Cursor `modelInfo.modelName` | model-turn configuration tests | Covered |
| Effort, speed, service settings | Local audits now show Claude model/service tier and Codex model/effort/newer service tier; Cursor shows model only; no distinct speed tier | Adapter/provenance and model-configuration tests; real baseline rebuild pending | Uneven source availability and stale normalized baselines; **CoPlan A12/E-2** |
| Exact raw recovery | SWEmore, spank-py, Zero400 | hash/decompression checks | Covered |
| Reference-only raw behavior | Non-reviewed policies/fixtures | stability checks and explicit limitations | Covered |

Reference-only apply validation requires the live locator to remain at the
ingested revision through both fixed-point runs. Captured shared databases may
legitimately advance between two reads; a policy must explicitly permit that
case, and acceptance still requires the normalized, observation-independent
digest to match. Each snapshot retains its exact captured revision. The frozen
reviewed set now has no reference-only evidence.

Coverage states above are evidence facts. Corpus expansion and evidence-gap
work are governed only by **CoPlan.md §8**, especially **T4–T5**.

## Retained snapshot access

Querying a retained snapshot requires `--snapshot-id`. The default package
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

## Maintenance ownership

This review records evidence state, not a second work queue. **CoPlan.md** owns
pending work and restart conditions. **Operations.md** owns baseline
verification, evidence refresh, and freeze procedures. The machine-readable
catalogs remain authoritative for membership and immutable snapshot identity.
