# Content processing and schema proposal

## Implemented processing entry points

Ingest accepts `--content-policy <json>` and `--strict-mapping`. The policy is
optional; without one, existing sanitization and truncation behavior remains in
effect. Strict mapping is independent: it fails a source rather than silently
discarding an unsupported prompt shape or unsafe external-content reference.

`codess.content_processing` provides pre-normalization, post-normalization, and
byte-decoding hooks. Claude, Codex, and Cursor message/result adapters call the
shared pre/post entry point; Claude external sidecars also use byte decoding.
Rules layer in this order:

1. global policy;
2. each matching scope in declaration order;
3. built-in storage bounds that remain part of the vendor adapter.

Scope predicates support `vendor`, `record_type`, `event_kind`, `phase`,
`project_path`, and `repo_path`. Values use exact or shell-style wildcard
matching. The prototype supports:

- declared character encoding, decode error behavior, and Unicode
  normalization;
- minimum and maximum character bounds;
- explicit suppression expressions for known hostile content;
- privacy expressions with configurable replacements;
- vocabulary blanking;
- topical include and exclude expressions; and
- an action trace suitable for mapping diagnostics or a future processing-run
  entity.

The example at `schema/content-policy.example.json` is illustrative, not a
recommended privacy policy. Suppression and topical filtering can destroy
evidence. Exact raw capture must remain separately governed and must never be
described as exact after transformation.

## Implemented vendor-compatible records

No CoSchema layout change is required for the current additions because common
event kinds are open vocabularies and the event table already has metadata and
lineage fields.

Claude now maps:

| Source shape | Common representation |
|---|---|
| String prompt with human/typed origin | `message.prompt`, human actor |
| System or task-notification input in a user envelope | harness context/notification, not human |
| Mode, permission mode, title, attachment, and file-history markers | bounded `product_state` event |
| Queue, duration, and scheduled-task records | bounded `lifecycle_event` |
| `persistedOutputPath` | bounded `content.external` event linked to its tool result |

External content is accepted only from the transcript session subtree. The
normalized record contains a stable event ID, source locator, content hash,
byte and character lengths, bounded text for query processing, and a causal
link to the tool-result event. Raw manifests can contain a
`related_content_revision` record with its own relationship ID, parent source
locator, relation kind, and exact content object/reference.

Cursor renamed and remote workspaces are never equated from path resemblance.
An explicit `.codess/source-links.json` record with an approved selection state
is required when direct `workspaceStorage` mapping is insufficient.

## Central schema — implemented in CoSchema 3

The approved source-record/content-object design is implemented in
`contract.json` and SQLite. The event-plus-metadata projection remains for
compatibility, while typed entities carry durable content and processing
identity.

### Source records plus content objects

CoSchema 3 adds four central concepts:

- `source_records`: source revision, locator, vendor record type/subtype,
  source sequence, parent locator, timestamp, classification, and bounded
  parameters JSON;
- `content_objects`: content hash, media type, charset, byte/character length,
  storage class, inline bounded content or raw object ID, privacy class, and
  metadata;
- typed link tables from events, tool results, artifacts, and source records to
  content objects, each with relation kind, sequence, extraction range, and
  integrity state; and
- `processing_runs` plus derivation links: policy digest, processor/software
  version, scope, input/output content IDs, actions, rejection reason, and time.

Structured updates then become source records classified as
`artifact.update`, with operation and target in parameters and optional before,
after, patch, or diagnostic content links. Vendor payloads remain traceable
without forcing every evolving field into the common event table.

Advantages: normalized facts, raw evidence, and transformed derivatives have
separate identities; external content is deduplicated; processing is auditable;
and structured updates can specialize incrementally. Cost: four concepts and
several link tables must be added together to preserve referential integrity.

### Rejected alternatives

Events/metadata-only and vendor extension databases were rejected as the
central model. Compatibility projections remain, but accepted and rejected
processing inputs receive content identities; rejected values use
`storage_class=not_retained` with hash/length and no body. Event and source
record links are populated now. Tool-result output and artifact operation
parameter links are projected from their owning events without duplicating the
content body.
