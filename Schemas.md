# Schema compatibility, evolution, and translation

This document records findings from the local project at
`~/Work/Github/Schema` and applies them to Codess. It complements
`Designs.md`: that document defines the broader system direction; this one
governs the CoSchema contract, vendor translation, compatibility decisions,
and conformance model.

The source review covered `Schema.md`, the conformance and mapping documents,
decision records, contract fixtures, vendor mapping specifications, schema
manifest and registry checker, evolution gate and tests, mapping engine and
round-trip tests, and transform-language experiment. These are local source
artifacts. Their repository URLs or continued publication must not be assumed
from an old list.

## 1. Conclusions

The most useful lesson is not “use JSON Schema.” It is to make a canonical
contract executable and surround it with disciplined translation and evidence:

1. Maintain one common CoSchema model and map every vendor into it. Do not
   create Claude-to-Codex, Cursor-to-Claude, or other point-to-point mappings.
2. Package the logical contract, SQLite layout, taxonomies, and conformance
   fixtures as `codess.coschema`.
3. Keep only the two managed versions already selected: Codess software and
   the monotonic CoSchema store format. Treat adapter, harness, SQLite, source,
   and snapshot identities as recorded provenance rather than release trains.
4. Make compatibility an executable gate. Known changes receive a declared
   classification and action; unknown changes fail closed for review.
5. Treat vendor mappings as executable specifications with exact fixtures,
   named transforms, mapping traces, explicit loss, and structured diagnostics.
6. Preserve source identity and exact source values. Never guess a normalized
   value, silently turn failure into `null`, or merge cross-vendor identities.
7. Rebuild derived session stores from source or captured raw evidence. Reserve
   explicit schema-to-schema translation for irreproducible curated data.

## 2. Findings from the Schema project

### 2.1 One canonical model, many mappings

The source project treats its canonical Person and Company profiles as the hub
and gives every external system a mapping to or from that hub. It rejects the
combinatorial growth and inconsistent semantics of point-to-point mappings.

This directly applies to Codess. Claude, Codex, and Cursor should each map into
one CoSchema contract. Vendor source types and values remain available as
evidence, but vendor structures do not become parallel common schemas.

The source project also argues that adapters are more operationally important
than an elegant canonical profile. That is especially true here: CoSchema is
valuable only if the three adapters preserve ordering, source provenance,
roles/origins, tool correlation, model settings, and vendor exceptions
accurately.

### 2.2 Conformance is executable

The project uses several complementary test layers:

- maximal fixtures with all optional data;
- minimal fixtures with only required data;
- edge fixtures that must pass;
- negative fixtures named for the rule they violate;
- mutation tests that prove declared constraints reject bad variants;
- parity tests that expose validator implementation differences; and
- an evolution gate that compares old and new contracts.

CoSchema should adopt the fixture and mutation discipline. Cross-language JSON
Schema parity is not inherently valuable for a SQLite store, but the underlying
principle is: if two layers claim to enforce the same invariant, run identical
fixtures through both and treat disagreement as a contract defect. Relevant
pairs include application validation versus SQLite constraints and supported
SQLite runtime versions.

### 2.3 Stable names, local resolution, and content hashes

The source project separates a schema's stable `$id` from its current file
location. A committed manifest maps identity to file and SHA-256 hash; consumers
resolve through the manifest rather than the network. A registry checker verifies
that identities are unique, files exist, hashes match, and schemas are valid.

This strongly supports the existing Codess direction:

- fixed format identity: `codess.coschema`;
- fixed SQLite `application_id` for the database family;
- monotonic `user_version` for the CoSchema store format;
- `store_meta` inside a detached database;
- a package manifest mapping contract components to hashes; and
- a snapshot manifest mapping sources, stores, raw objects, policy, and software
  provenance to hashes.

Codess should be stricter about released immutability. A released CoSchema
format's content hashes must never be regenerated under the same format
identity. Corrections that alter the contract create a new format. Pre-release
generation may update a candidate manifest, but release freezes it.

### 2.4 Evolution classification and fail-closed review

The source evolution gate classifies additive or relaxing JSON Schema changes
as minor and removing, narrowing, or tightening changes as major. Unknown
changed keywords are considered breaking until reviewed.

The mechanism applies, but profile SemVer and the JSON-keyword rules do not.
Codess needs a relational and semantic classifier over a machine-readable
CoSchema contract. The result should say whether the existing format remains
valid, whether readers can remain compatible, whether the format integer must
advance, and whether stored data must be rebuilt. These are change properties,
not more managed versions.

Descriptions and taxonomy definitions may carry functional meaning, so a
semantic text change cannot always be dismissed as an annotation-only patch.
The gate should require explicit review for changes it cannot classify.

### 2.5 Extension points and strict stable structures

The source project keeps top-level documents open to additive fields but closes
small leaf objects to catch misspellings. This makes additive evolution possible
without accepting arbitrary corruption everywhere.

The exact JSON-object rule does not transfer to SQLite. The useful policy is:

- stable common entities, keys, relationships, and typed payloads are strict;
- namespaced vendor extension JSON remains open;
- exact upstream fields remain available through raw evidence and mapping
  traces;
- an unknown normalized field or vocabulary value is not silently accepted;
  it is retained as source evidence, mapped to an explicit unknown/extension
  representation where the contract permits, or diagnosed; and
- extension data cannot override or contradict a common field.

### 2.6 Mapping specifications, named transforms, and hazards

Current source mappings are package-hashed JSON rule registries implemented by
named adapter transforms. Each rule identifies its source selector, target,
operation, retention, and direction; emitted events are automatically checked
for exact source identity, a declared primary/applied rule, structured trace,
and JSON tool arguments. Vendor hazards are encoded in the profile and fixtures
rather than left as institutional memory. A general interpreted mapping engine
is a possible later implementation, not a claim about the current code.

The current grammar implements `from`, `from_any`, `from_each`, `const`, target,
retention, hazards, and direction. Candidate extensions, to add only with an
executable consumer and fixtures, include:

- `from`: one exact source path or record selector;
- `from_any`: ordered alternatives for source-format variants, recording which
  path matched;
- `from_each`: fan-out for arrays or source blocks;
- `to`: one common field or specialized relation;
- `when`: an evidence-based guard;
- `transform`: a named host function;
- `const`: allowed only when the value is truly implied by the matched source
  structure, never as a substitute for missing evidence;
- `retention`: `core`, `specialized`, `extension`, `raw_only`, or `discard`;
- `loss`: an explicit reason when information is not recoverable; and
- `notes` and hazard identifiers linked to fixtures.

Keep named Python transforms initially. The source project's jq/JSONata/JMESPath
experiment found that an expression language did not remove host functions and
added another failure surface. Codess has no demonstrated need for user-authored
mapping expressions yet.

### 2.7 Loud failures and dead-letter discipline

The source engine refuses unmappable values rather than guessing and returns
structured dead letters. Controlled vocabularies are external artifacts, and a
miss does not automatically become `other`.

Codess should adapt this into three diagnostic levels:

| Level | Use |
|---|---|
| Source quarantine | The source is unreadable, inconsistent, unsupported, or cannot be captured safely. No normalized records from that revision are promoted. |
| Record rejection | A source record cannot satisfy core identity, ordering, or structural invariants. Other valid source records may proceed. |
| Field diagnostic | An optional value cannot be normalized. Preserve the source value/trace and omit or extend only according to declared policy. |

Every diagnostic should include source revision, record locator, vendor/source
field, exact reason code, mapping rule, and bounded safe detail. A partially
normalized event must never appear complete when a required core fact failed.

### 2.8 Structural aliases, vocabularies, and reconciliation

The source project separates three problems that are often conflated:

1. Structural aliases reconcile different field names.
2. Vocabulary mappings reconcile different values.
3. Registries/reconciliation assert that separately identified entities refer
   to the same thing.

For Codess these become:

- source-format aliases for fields and record variants;
- mappings for roles, event kinds, statuses, commands, model modes, and tool
  categories; and
- evidence-graded links between projects, sessions, actors, or artifacts across
  vendors.

Alias or vocabulary matching records the exact matched surface value and rule.
Fuzzy matching is not a default mapping mechanism. A cross-vendor link is a
separate assertion with method, evidence, confidence, reviewer/policy, and time;
it never rewrites the original identities. Incorrect links then remain
reversible and do not corrupt source lineage.

### 2.9 Fixed points, round trips, and declared loss

The source project tests vendor-to-canonical-to-vendor fixed points and declares
known lossy fields. Codess currently has no vendor publishing requirement, so a
literal round trip would create unnecessary scope.

Adopt these equivalents instead:

- ingesting the same Source revision under the same software, mapping policy,
  and CoSchema format produces identical normalized logical records;
- rebuilding the same snapshot produces the same logical content hashes, while
  allowing documented physical SQLite differences that do not affect meaning;
- event order and generated internal/source keys remain stable;
- raw `capture` or `seal` modes reproduce the exact captured source bytes;
- every discarded, truncated, generalized, or noninvertible value appears in a
  mapping loss report; and
- any future export mapping is directional and receives its own fixtures and
  fixed-point test.

A canonical fixed point proves normalization stability, not losslessness of the
original source. Exact raw preservation and the loss report prove the latter.

### 2.10 Full snapshots and deferred deltas

The source project chose complete entity snapshots over patch events because
full payloads make the declared schema honest and keep consumers simple.

Codess should retain the analogous choice already made in `Designs.md`: build
complete immutable database snapshots, validate them, and atomically promote
them. Do not make a chain of migration deltas the authoritative history. Deltas,
incremental copies, or page-level optimization may be introduced internally
only when measured corpus size justifies them; the logical baseline remains a
complete snapshot.

### 2.11 Decision records and evidence-triggered scope

The source project records alternatives, consequences, and explicit triggers
for deferred work. Its experiments graduate into decisions rather than becoming
permanent parallel prototypes.

Codess should use short decision records for choices that constrain later work,
including the CoSchema package/version policy, snapshot-over-migration rule,
raw-store format, interaction/turn distinction, mapping failure policy, and
cross-vendor identity assertions. Each deferral should name the evidence that
would reopen it.

## 3. Applicability decisions

### Adopt

- One canonical model with vendor adapters.
- Stable format identity decoupled from file location.
- Hash manifest and released-package immutability.
- Executable compatibility gate that fails closed.
- Minimal, maximal, edge, negative, hazard, and golden fixtures.
- Mutation tests for claimed constraints.
- Declarative mapping tables backed by named transforms.
- Exact mapping traces, diagnostics, and loss declarations.
- Controlled vocabularies as reviewed artifacts.
- Separate evidence-graded identity/correlation assertions.
- Full immutable baselines and evidence-triggered decision records.

### Adapt

- Replace JSON-profile SemVer with the monotonic CoSchema format integer and a
  compatibility classification.
- Replace JSON open-root/closed-leaf rules with strict common structures plus
  namespaced extension data.
- Replace vendor publish round trips with deterministic re-ingestion and snapshot
  fixed-point tests until export is required.
- Replace field-only dead letters with source, record, and field diagnostic
  levels appropriate to transcripts.
- Replace cross-validator JSON parity with parity between any layers that claim
  the same CoSchema invariant and a supported SQLite runtime matrix.

### Defer

- Vendor export/publish mappings.
- A hosted registry or runtime network schema resolution.
- An embedded mapping expression language.
- Fuzzy or automated cross-vendor identity resolution.
- Delta snapshots and in-place derived-data migration.
- Additional vendors until the three-vendor compatibility corpus passes.

### Reject

- Point-to-point vendor translations.
- JSON Schema as the sole authority for relational storage and functional
  semantics.
- Multiple independent schema/layout/taxonomy/adapter release trains.
- Silent `null`, guessed values, or fallback-to-`other` on every mapping miss.
- Editing a released contract under the same format identity.
- Treating normalized fixed-point equality as proof that raw input was lossless.

## 4. CoSchema compatibility contract

### 4.1 Package contents

A proposed source layout is:

```text
schema/coschema/
├── manifest.json
├── contract.json                 # logical entities, fields, relationships
├── sqlite/
│   └── schema.sql                # canonical DDL, indexes, pragmas
├── taxonomy/
│   ├── actors.yaml
│   ├── events.yaml
│   ├── operations.yaml
│   └── statuses.yaml
├── mapping-contract.json         # grammar for adapter mapping specs
└── fixtures/
    ├── minimal/
    ├── maximal/
    ├── edge/
    ├── negative/
    └── compatibility/
```

This is a design direction, not a requirement to move the current files before
the v2 contract is settled. Per-vendor mapping specifications and hazard
fixtures ship with Codess software under adapter directories; their output must
validate against this package. They do not receive separate public versions
while they ship as part of Codess.

The package manifest records:

- `format_id = codess.coschema` and monotonic `format_version`;
- fixed SQLite application ID and required SQLite capabilities;
- file paths, SHA-256 hashes, media types, and roles;
- contract/package creation software and source revision;
- reader compatibility declarations;
- released/candidate state; and
- fixture set and validation command identity.

### 4.2 Change classification

| Change | Format action | Data action | Reader consequence |
|---|---|---|---|
| Documentation or fixture correction with no semantic effect | Keep format; new package digest/software release | None or retest | Existing readers remain valid |
| Operational index tuning with unchanged query contract | Keep format; new package digest/software release | Optional physical rebuild | Existing readers remain valid |
| Adapter mapping correction within the same common contract | Keep format; new Codess release | Rebuild affected snapshots | Store readers remain valid |
| Add nullable field/relation or widen an explicitly tolerant taxonomy | Advance format | Rebuild snapshot | Gate may declare older reader read-compatible |
| Add required data, tighten nullability/constraint, remove or rename a field | Advance format; breaking | Rebuild from raw/source | Old reader/writer must refuse unless explicitly supported |
| Change identity, ordering, lineage, time, role, status, or other field meaning | Advance format; breaking | Rebuild from raw/source | Old semantic interpretation is invalid |
| Change raw capture without changing `codess.raw/1` semantics | Keep CoSchema format if normalized contract is unchanged | Revalidate raw objects/manifests | Raw reader compatibility must be tested |
| Unknown or unclassified difference | No release | Stop for manual review | Fail closed |

The gate must compare the logical contract and package hashes, not infer
semantics from a textual SQL diff alone. It should confirm that DDL implements
the declared contract and that the declared format action covers the most severe
finding.

### 4.3 Reader and writer rules

- A reader checks SQLite `application_id`, `user_version`, `store_meta`, package
  identity/digest, and snapshot manifest agreement before querying.
- A reader may support an explicit set or range of CoSchema formats, verified by
  compatibility fixtures.
- A writer creates only its declared current format and never silently upgrades
  a store.
- Unsupported writers/readers fail without mutation and point to the matching
  software/snapshot information.
- Released packages and snapshots are immutable. A new build occurs beside the
  old baseline and is promoted only after validation.

## 5. Vendor translation contract

Each adapter must declare:

- vendor, product, harness/source system, and supported storage families;
- source record selectors and source-format variants;
- common targets and specialized relation targets;
- named transforms and controlled vocabularies;
- exact source type/value retention;
- stable source record and ordering locators;
- guards and fan-out behavior;
- missing/unsupported/invalid/redacted handling;
- diagnostic level and reason code;
- deliberate losses and raw-only fields;
- vendor hazards and their fixture names; and
- mapping trace fields needed for explanation and rebuild comparison.

Translation stages are:

```text
exact Source revision
  -> source reader and structural validation
  -> vendor mapping and named transforms
  -> common-domain validation and diagnostics
  -> CoSchema snapshot writer
  -> snapshot/package integrity validation
```

Do not let SQLite column names become the mapping contract. Vendor adapters map
to domain fields/entities; the SQLite writer maps the domain representation to
physical storage.

## 6. Conformance model

### Contract fixtures

A conforming package represents every common entity or relationship with:

- minimal valid instance;
- maximal representative instance;
- edge cases that must pass, including null/unknown and extension behavior;
- one negative fixture per invariant;
- ordering and lineage fixtures; and
- old-format compatibility fixtures for every supported reader path.

A conforming vendor/source profile includes:

- realistic golden source plus expected normalized output;
- malformed and unsupported source records;
- every documented vendor hazard;
- multi-block/fan-out cases;
- unmapped vocabulary and alias cases;
- source/record/field diagnostic cases;
- deterministic repeated-ingestion comparison; and
- explicit loss-report comparison.

### Mutation tests

Mutate the contract or DDL one rule at a time: remove required constraints,
weaken foreign keys, alter uniqueness/order keys, admit invalid taxonomy values,
drop source lineage, or bypass nullability. A surviving mutant indicates that a
claimed invariant is not enforced by the test suite.

### Compatibility gate

The small gate compares `contract.json` revisions. Classification coverage includes:

- entity/field/relation addition and removal;
- nullability and type changes;
- primary, unique, and foreign-key changes;
- identity/order key changes;
- taxonomy additions, removals, and meaning changes;
- extension-policy changes;
- DDL/contract disagreement; and
- unknown changes that require manual review.

Do not attempt to parse every possible SQL expression initially. Compare a
canonical machine-readable contract, validate the DDL behavior with fixtures,
and fail closed when the gate lacks a rule.

## 7. Package design implications

- The durable store contract includes a manifest, immutable hashes,
  machine-readable contract, evolution gate, and conformance fixtures.
- Common structures and extension points are defined before physical DDL.
- Vendor mappings are executable specifications with named transforms, traces,
  diagnostic levels, hazards, and declared loss.
- Immutable snapshots, fixed-point normalization, and exact raw hashes replace
  migration chains and assumed round trips.
- Project/source identities remain stable; remote and cross-vendor equivalence
  is a dated evidence-bearing assertion.
- Compatibility evidence uses minimal, maximal, edge, negative, hazard, and
  golden fixtures around the bounded corpus.
- Mixed queries expose common values together with source values, mapping
  provenance, loss diagnostics, and correlation confidence.

## 8. Schema research direction

The schema programme treats compatibility as a versioned package of logical
contract, physical layout, vendor mappings, fixtures, transform identities,
and executable gates. Its long-term research direction is to improve:

- semantic change classification beyond surface JSON or SQL diffs;
- mutation evidence that every claimed invariant is enforced;
- declared-loss and round-trip analysis for vendor translations;
- vocabulary/alias reconciliation without weakening stable common structures;
- fixed-point and cross-version comparison of immutable snapshots; and
- content-addressed schema and mapping resolution across older readers.

The governing principle remains: the evolution gate follows a settled contract
rather than automating uncertainty. These are offered research directions, not
a work queue. Current work, known gaps, open decisions, event triggers, and
postponed topics are registered only in **CoPlan.md §8**.
