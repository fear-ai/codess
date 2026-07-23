# Experiment record: JSON transform DSL for Codess mappings

**Status: POSTPONED (not adopted).** This is the full lifecycle record for the
question "should Codess mapping rules use an embedded JSON transform expression
language instead of named Python transforms?" The verdict is *postpone with a
defined trigger*, so this document lives in `experiments/`, not in the findings
or decision registers. It exists so that when the trigger fires, the evaluation
starts from a settled method and a ready acceptance test rather than from
scratch.

Scope note: Codess is a **data pipeline** — session ingestion → normalization →
immutable snapshot → DB query/analysis. Its value is the correctness and
resilience of *every* step, not of the mapping step alone. A transform DSL would
touch only the normalization step; this record is deliberately narrow.

## 1. Use case

Codess mapping profiles (`schema/mappings/{claude,codex,cursor}.json`) declare
rules whose fields may name a transform. Today those transforms are named Python
functions in `src/codess/adapters/`. The recurring question is whether the
`transform:` position should become an embedded expression language (jq /
JSONata / JMESPath / JSLT) so that a rule author could express field surgery
without shipping Python.

## 2. Desired functionality

A candidate language would have to express the transform classes our three
adapters actually perform, without weakening the pipeline's guarantees:
- field renaming and object shaping;
- conditional emission (skip a field when its source is absent/empty);
- string surgery (split multi-line tool output, trim, normalize timestamps);
- table lookup (status/role/event-kind vocabularies; tool-name canonicalization);
- **loud failure on unmappable input** — never a silent null (the never-guess
  rule, `Schemas.md §2.7`);
- and it must not force us to abandon host functions we already require
  (deterministic global-ID hashing, JSON canonicalization, bounded redaction).

## 3. Derived requirements (from existing pipeline contracts, not invented)

The evaluation criteria are read off Codess's non-negotiable contracts so the
result is authoritative rather than a matter of taste:
- **Never-guess / dead-letter** (`Schemas.md §2.7`): a miss is a diagnostic, not
  a guessed value or a silent null.
- **Never crash on input** (see §9): no record, however malformed, may abort the
  program; the pipeline reports and continues.
- **Exact provenance** (`CoSchema.md`): every emitted value keeps
  `mapping_rule` + `mapping_trace`; a DSL must preserve which rule/path produced
  a value.
- **Deterministic ordering and stable IDs**: transforms must be pure and
  reproducible so re-ingestion yields identical logical digests.
- **Bounded output**: no transform may materialize an unbounded source object.

## 4. Evaluation criteria and candidate vetting

Candidates: only real JSON→JSON transform languages a Python/JS runtime can
embed — **jq, JSONata, JMESPath**. Excluded on stated grounds: **JSLT**
(JVM-only, no Python runtime), **VTL** (targets statistical cubes, not JSON
documents).

Decisive, disqualifying criterion: **failure semantics.** On unmappable input a
candidate must *raise* (dead-letter compatible); a *silent null* is an automatic
elimination regardless of expressiveness, because it violates never-guess.

Known floor established up front: our global-ID hashing and JSON canonicalization
are not expressible in any candidate, so a DSL can only *supplement*, never
*replace*, the host transform registry. This caps the maximum possible benefit
before any test runs.

## 5. Test automation (methodology, borrowed from the Schema project's shootout)

The method — build the real mapping in each candidate, grade against one shared
golden fixture, probe failure behavior — is adopted from the source project at
`~/Work/Github/Schema` (its decision 004; see §11). Adapted to Codess:
- **Workload:** a real adapter mapping (e.g. a Cursor `toolFormerData` →
  `tool_invocations`/`tool_results` rule, or a Claude `user`-envelope →
  prompt-vs-context classification), not a toy.
- **Ground truth:** the *same* fixture the adapter's own tests already assert
  against, so all implementations grade against one truth.
- **Conformance measurement:** field-by-field exact/wrong/missing.
- **Failure measurement:** feed an unmappable value (bad status, malformed
  timestamp) and record raise vs. silent null.
- **Native execution:** each candidate in its real embedding, skipping cleanly
  when its runtime is absent.

**Conformance-only, no performance timing — deliberate.** The decision hinges on
expressiveness + failure semantics; a candidate that fails the dead-letter test
is out regardless of speed. If a future revisit is latency-bound, add a timing
stage to the same harness; measure the axis that actually decides.

## 6. Evaluating results and crafting the recommendation

The reference run of this method (Schema project, on an equivalent
Salesforce mapping) produced: JMESPath eliminated (silent nulls, no
split/regex/lookup); jq and JSONata tied at full expressiveness and both fail
loudly; no language removed the host-function need. Codess has **not** re-run the
harness against a Codess adapter mapping because the trigger (below) has not
fired; the reference result is sufficient to justify postponement, and the
Codess run is itself the acceptance test when the trigger fires.

Recommendation: **postpone.** An expression language would add a dependency and a
second failure surface to the normalization step without removing host functions,
and Codess has no rule-authors-without-Python bottleneck. If revisited, **JSONata
is the designated candidate** (native embedding, `$error()` → dead-letter, Python
ports).

## 7. Adoption and deployment (only if the trigger fires)

Not applicable now. If adopted later: JSONata would sit *beside* the host
transform registry, host functions registered for ID/canonicalization/redaction;
every DSL-produced value still carries `mapping_rule`/`mapping_trace`; the change
advances no CoSchema format (it is an adapter-internal detail) but requires a
rebuild of affected snapshots and the §5 harness green as the acceptance gate.

## 8. Post-development review

Deferred until adoption. When/if the DSL is adopted, this section records whether
the predicted benefit (non-Python authorship) materialized and whether the added
failure surface was worth it — the honest retrospective the Schema project's
decision 004 anticipates by naming its own acceptance test.

## 9. Trigger to reopen

Reopen only when rule authors who cannot ship Python become a demonstrated
bottleneck for adding or correcting a vendor mapping. Absent that, named Python
transforms remain. This trigger is registered in `CoPlan §8` as the reopen
condition for the mapping-DSL deferral.

## 10. Relationship to universal field resilience

This DSL question is separate from — but shares the never-guess/never-crash
contracts with — the field-resilience requirement (`CoPlan` D18): whatever
executes transforms (host functions today, a DSL never) must treat every field
state (absent / empty / null / sentinel / malformed) as a warn/info diagnostic
and never abort. The resilience requirement is mainline; the DSL is postponed.

## 11. Provenance of the method

The shootout methodology is borrowed from `~/Work/Github/Schema`
(`docs/decisions/004-transform-language.md`, `experiments/transform-languages/`).
That is a *separate project* (same author) targeting CRM vendors
(Salesforce/HubSpot/Shopify/MS Graph/Stripe); Codess targets AI coding harnesses
(Claude/Codex/Cursor) and borrows only the evaluation discipline, not the
"adapters are the product" framing, which is the Schema project's thesis and does
**not** describe Codess's pipeline.
