# Operations — preflight, structured output, resource bounds, and evidence

## Ingest preflight

`codess ingest --validate` runs real source discovery, vendor adapters, content
policy, CoSchema writes, mapping diagnostics, and SQLite integrity/foreign-key
checks against temporary databases. It forces parsing even when incremental
state says a source is unchanged. It does not alter the Project's `.codess`,
Project catalog, registry statistics, raw store, snapshots, or ingest state.

The `codess.ingest-preflight/1` JSON result contains source/session/event counts,
diagnostics, resource observations, limits, and temporary-store checks. This
proves current records can normalize under the current package. It does not
prove raw durability, snapshot promotion, or a two-run fixed point;
`python -m main baseline apply` is the acceptance gate for those properties;
`tools/apply_and_verify.py` is its compatibility wrapper.

## Structured query rows

`query --output-format jsonl` is a versioned prototype for `--sessions` and
`--stats`. Stats stream one bounded record per Project followed by one total.
Each line is a `codess.query-row/1` envelope with report, Project scope,
optional row number, and typed data. Its independent contract is
`schema/query-row-v1.json`, not the CoSchema database version.

Requirements are deterministic ordering, JSON-native numbers/nulls/objects,
stable global identities, explicit report and Project scope, bounded lines, no
terminal sanitization, and additive evolution within a row version. Incompatible
row meaning requires a new row version.

SQLite JSON functions, `.mode json`, Datasette, sqlite-utils, pandas, or generic
row dictionaries help exploration but are not the API: they expose physical
layout, omit cross-store report semantics, and turn DB migrations into output
breakage. JSON Schema is a lightweight boundary validator. Pydantic is not yet
needed because there is one producer emitting already typed values.

## Resource bounds and processing

Defaults are 8 GiB per source, 500,000 normalized events per source, and 250,000
per session. Override with `--max-source-bytes`,
`--max-events-per-source`, and `--max-events-per-session`, or deliberately use
`--no-resource-limits`. Equivalent environment variables use `CODESS_` names.

Routine ingest writes `.codess/last-ingest-report.json` with source bytes, event
counts, largest buffered session, peak process RSS, limits, and diagnostics.
Event counts are checked while normalized records are collected, so a configured
limit rejects before the complete oversized buffer is retained. Cursor decoding
projects envelopes to mapped fields before retaining them; completed source
buffers are explicitly deleted and garbage collection follows the transaction.
Content excerpts retain per-record limits.

One selected multi-session Cursor source is still the transaction buffer. If
real evidence approaches the event maximum, use a staging table and
composer-at-a-time writes in one transaction rather than silently raising the
defaults.

## Evidence inventory

`python -m main evidence gather` searches current catalog Projects and local vendor
metadata without retaining conversation bodies. It checks cross-vendor artifact
identity, effort/speed/service settings, direct Codex parents,
lifecycle/missing-time evidence, and Cursor tool/model shapes. Relevance-ranked
results live in `catalog/evidence-inventory.json`.

The current inventory found real Claude/Cursor shared artifact paths in Zero400
and real missing-time records. It still found no Codex parent identifier and no
effort/speed/service settings. Expand the corpus only for a high-relevance
missing shape; use approved active workspaces for maintenance evidence.

## Curated workflows

These command families use shared domain operations. Old tools and scripts
remain compatibility entry points during the removal review.

Candidate review combines production scan observations with optional maintained
CSV/catalog data and bounded local Git activity. It is read-only by default,
does not crawl repositories unless requested, and never checks remotes without
an explicit network option. Recommendations explain `consider`, `defer`, or
`exclude`; only an explicit review decision can authorize curated onboarding.

The normal curator workflow is intentionally two human actions:

1. refresh candidate observations and record decisions; and
2. onboard the `approved` selection.

Onboarding itself exposes plan, preflight, and apply in one structured receipt,
with stop points after plan or preflight. Operators and CI retain direct access
to each stage; ordinary users do not have to manually shuttle a scan CSV through
several scripts. `ingest --dirs` remains available for an explicit path list.

Baseline publication similarly composes safe stages: validate accepted member
reports, atomically replace each selected catalog with pair rollback on a
detected failure, then verify the written set.
The read-only verify operation remains separately callable for CI. Evidence
gathering runs vendor audit functions once and can emit both detailed component
reports and the aggregate inventory.

Location management distinguishes adding a second location, retiring a location
without replacement, and relocating from old to new. The historical
`retire_project.py` requires a new location and is therefore a relocation
wrapper; the explicit operations are under `catalog location` and
`catalog relocate`.
