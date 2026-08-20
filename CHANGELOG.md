# Changelog

Notable changes per released version. The authoritative version is
`codess.__version__`, reported by `codess --version`.

**A CoSchema format change requires a rebuild, not a migration.** Codess never
migrates a store: the store is a projection of vendor Sources, and the way to
change a projection is to recompute it. `require_store` accepts only the
current format for reading as well as writing, so after installing a version
that changes the format, run `codess ingest --force` for each Project and
republish. The cost scales with Project count rather than with the size of the
change, and is minutes of machine time for a corpus of this scale.

## 0.3.0

### CoSchema Format 7

Requires a rebuild. Stores at format 6 and earlier are unreadable by this
version.

- **Session model evidence is recorded for every vendor that supplies it.**
  `sessions.session_model_basis` states how the Session-level model was
  obtained -- `vendor` where the vendor made a Session-level statement,
  `initial_event` where the first model observed to serve a turn was recorded
  instead. `sessions.session_model_count` holds the number of distinct models
  across the Session's Model Turns, so a model-switch question is a predicate
  rather than a join.

  Claude records the model per assistant record and never as a Session header,
  so its Session-level model coverage was zero and is now complete. A derived
  value is never presented as a vendor statement: the basis column is what
  keeps the two claims distinct.

### Decode

- **Cursor reasoning is decoded and emitted as `message.reasoning_summary`**,
  the Event kind Codex already uses, so a cross-vendor reasoning query needs no
  per-vendor case. Cursor never places reasoning beside a response -- every
  bubble carrying `thinking` has empty `text` -- so the evidence previously
  produced no Event at all.
- **Cursor bubble fields mapped**: turn and client timings, recorded error
  details, terminal working directory, symbol and file links, todos, code
  blocks, the populated `context` leaves, and the request and response
  identifiers, which are kept as separate values because they name the two ends
  of a Model Turn.
- **Cursor Session times fall back to the composer header.** Where a composer's
  bubbles carry no timestamp, `created_at` and `last_updated_at` supply the
  Session span and `time_basis` records `session`, so a header-stated span
  stays distinguishable from an Event-derived one. Sessions that previously
  carried no time at any level could not be ordered or filtered by `--since`.

- **Cursor composers absent from `composerHeaders` are recovered.** The header
  table is the smallest of three indexes the vendor keeps; 107 composers held
  bubbles it does not list. Settings are now read for every known composer
  rather than only for headered ones, raising composer coverage from 66 to 164
  and Sessions carrying a stated model from 32 to 134. A recovered composer
  states no workspace, so it is never admitted under a workspace selection --
  attributing it to a Project would be an inference rather than a decode.
- **`modelConfig.selectedModels` supplies `speed_tier` and `reasoning_effort`.**
  A `fast` parameter is set on models whose name does not encode it, and an
  `effort` parameter on models whose name never does. Values are strings, so
  `"false"` is a stated value rather than an assertion.

### Correctness

- **Timestamp scale is decided once.** `units.epoch_milliseconds` normalizes
  ISO-8601 text, epoch seconds, and epoch milliseconds to the milliseconds
  CoSchema defines, and the three vendor parsers delegate to it. The Claude
  parser previously returned a seconds-scale number unchanged, which would have
  stored a 1970 instant, and accepted `True` as a number.
- **`tools/decode_audit.py` queried a column renamed in format 6**, so the
  audit the validation sequence mandates after every decode change had been
  failing at runtime.
- **`tools/gather_evidence.py` read an argument name that was never defined**,
  so it had never run.

### Checks

- **The module-level import graph is asserted acyclic.** Counting every import
  reports two components; both are closed only by imports deferred into a
  function body, which is the mechanism that keeps the layering loadable.
- **Static checks precede tests in the documented validation sequence.** An
  undefined name is reported by ruff and mypy in about a second with a file and
  line; the same defect reaching the suite surfaces as a subprocess failure
  with no location.
