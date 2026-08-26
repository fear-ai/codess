"""The event code table, the counter slots, and the field registry.

Three closed sets, all sized at import so the hot path allocates nothing. Each
answers a different question, and they are here together because each is a
name-to-index table the sinks read and the call sites index.

## Why These Structures

Measured on this platform, 500,000 iterations per case. The event tuple, the
counter list, and the code table are each the cheapest structure that answers
their question, and the figures are recorded here because the reasoning is
otherwise an assertion.

    construction                       ns    vs tuple      field access     ns
    tuple literal                    16.5       1.00x      tuple[1]        17.2
    list literal                     32.3       1.95x      dict['k']       20.6
    dict literal                     63.5       3.84x      NamedTuple.k    20.3
    TypedDict annotated literal      63.0       3.81x      dataclass.k     15.5
    TypedDict constructor           149.8       9.05x      __slots__.k     15.3
    NamedTuple                      144.3       8.72x
    dataclass                        95.2       5.75x      memory        bytes
    dataclass frozen+slots          255.9      15.47x      tuple             64
    __slots__ class                  89.4       5.40x      NamedTuple        64
    plain class                      97.8       5.91x      frozen+slots      56
                                                           dict             184

Four decisions follow, and two of them are not what a reader would guess:

- **An event is a tuple** (16.5 ns) rather than a dict (63.5 ns) or a
  `NamedTuple` (144.3 ns). The `NamedTuple` result is the surprise: it reads
  best and constructs *slowest of the tuple family*, because it runs `__new__`.
  Field access is the same 20 ns either way, and the sink is where names are
  wanted -- so the positional constants in `sinks` buy readability where it is
  free and the tuple keeps the hot path cheap.
- **A counter is a list index**, not a dict key. A list slot costs 32 ns to build
  once at import and nothing per increment; a dict would pay 63 ns to build and a
  hash per access. This is why `count()` is 50 ns while `event()` is 76 ns even
  disabled.
- **A `TypedDict` annotation is free; its constructor is not.** 63.0 ns annotated
  against 149.8 ns constructed -- identical `dict` at run time. So typing an
  options bag costs nothing as long as the literal form is used, which is what
  makes `_ResolveArgs` in `refresh_operations` a pure gain.
- **`frozen` is what costs, not `slots`.** Isolated over a three-field class:
  plain 104 ns, slots-only 94 ns, frozen 291 ns, frozen+slots 271 ns -- so `slots`
  is marginally *cheaper* than plain and `frozen` is 2.8x. A frozen `__init__`
  cannot use `STORE_ATTR`, since its own `__setattr__` raises, so it emits
  `object.__setattr__` per field: 28 bytecode instructions against 14, growing with
  field count. Frozen is right for `Measurement` and `ChildInvocation`, built a few
  times per run and then read, and wrong for anything per-record.

The general rule: cost scales with how much machinery runs at construction, while
field access is ~15-20 ns for everything. A structure built per record should be a
tuple or a list slot; a structure built per phase can be whatever reads best.

**An event code is an integer.** Codes are known at import, so an integer
compares and dispatches faster than a string and keeps the event tuple
uniform. The dotted name lives here, consulted only when a sink renders.

**A counter is a list index.** A per-record fact answers *how many*, not
*when*, so it is `counters[i] += 1` at 66 ns with no allocation rather than an
event that has to be stored and later aggregated.

**A field name is classified before it can be rendered.** The registry is an
allowlist: a name absent from it renders as `<unregistered>` under any
non-local privacy profile. A denylist fails open, and the field nobody
classified is the one that leaks.
"""

from __future__ import annotations

# --- Levels ------------------------------------------------------------------
#
# Integers, ordered, so a gate is a comparison rather than a lookup. Named for
# what a reader does about the event, not for how loud it is.
DEBUG = 10
INFO = 20
WARNING = 30
ERROR = 40

LEVEL_NAMES = {DEBUG: "debug", INFO: "info", WARNING: "warning", ERROR: "error"}
LEVEL_BY_NAME = {name: value for value, name in LEVEL_NAMES.items()}

# --- Scopes ------------------------------------------------------------------
#
# Which command family produced an event. A sink filters on it without parsing
# the dotted name, and a report can separate scan from ingest without a prefix
# match on a string.
SCOPE_NONE = 0
SCOPE_SCAN = 1
SCOPE_INGEST = 2
SCOPE_QUERY = 3
SCOPE_ADMIN = 4

SCOPE_NAMES = {
    SCOPE_NONE: "", SCOPE_SCAN: "scan", SCOPE_INGEST: "ingest",
    SCOPE_QUERY: "query", SCOPE_ADMIN: "admin",
}

# --- Event codes -------------------------------------------------------------
#
# A code is assigned once and never renumbered: a retained report holds
# integers, so reusing one would silently relabel history. The set below is
# derived from the emitting call sites, and a test derives it again -- an event
# added to a call site without a code fails rather than rendering without a
# level or scope.
_EVENT_SPECS: tuple[tuple[str, int, int], ...] = (
    # Ingest lifecycle.
    ("ingest.start", INFO, SCOPE_INGEST),
    ("ingest.done", INFO, SCOPE_INGEST),
    ("project.start", INFO, SCOPE_INGEST),
    ("project.done", INFO, SCOPE_INGEST),
    ("project.failed", ERROR, SCOPE_INGEST),
    ("vendor.start", INFO, SCOPE_INGEST),
    ("vendor.done", INFO, SCOPE_INGEST),
    ("source.start", DEBUG, SCOPE_INGEST),
    ("source.done", DEBUG, SCOPE_INGEST),
    ("source.failed", WARNING, SCOPE_INGEST),
    ("source.skipped", DEBUG, SCOPE_INGEST),
    # Codex index and Cursor cohort, the two preflight phases.
    ("codex.index.start", DEBUG, SCOPE_INGEST),
    ("codex.index.done", DEBUG, SCOPE_INGEST),
    ("cursor.marker.start", DEBUG, SCOPE_INGEST),
    ("cursor.marker.done", DEBUG, SCOPE_INGEST),
    ("cursor.cohort.start", DEBUG, SCOPE_INGEST),
    ("cursor.cohort.done", DEBUG, SCOPE_INGEST),
    ("cursor.cohort.unchanged", INFO, SCOPE_INGEST),
    ("cursor.cohort.reused", DEBUG, SCOPE_INGEST),
    # Publication.
    ("snapshot.start", INFO, SCOPE_INGEST),
    ("snapshot.done", INFO, SCOPE_INGEST),
    ("publish.start", INFO, SCOPE_INGEST),
    ("publish.done", INFO, SCOPE_INGEST),
    # Raw capture.
    ("raw.capture.start", DEBUG, SCOPE_INGEST),
    ("raw.capture.done", DEBUG, SCOPE_INGEST),
    ("raw.sqlite_backup.progress", DEBUG, SCOPE_INGEST),
    # Scan.
    ("scan.start", INFO, SCOPE_SCAN),
    ("scan.done", INFO, SCOPE_SCAN),
    ("scan.directory.budget", WARNING, SCOPE_SCAN),
    ("scan.filesystem.crossed", INFO, SCOPE_SCAN),
    # Discovery diagnostics. Debug because they are one line per candidate
    # directory: useful when a Project is missing from a scan and noise
    # otherwise, which is exactly what the level gate is for.
    ("scan.source.linked", DEBUG, SCOPE_SCAN),
    ("scan.source.mapped", DEBUG, SCOPE_SCAN),
    ("scan.project.metrics", DEBUG, SCOPE_SCAN),
    # Query.
    ("query.start", DEBUG, SCOPE_QUERY),
    ("query.done", DEBUG, SCOPE_QUERY),
    # Administrative.
    ("refresh.start", INFO, SCOPE_ADMIN),
    ("refresh.done", INFO, SCOPE_ADMIN),
    ("retention.start", INFO, SCOPE_ADMIN),
    ("retention.done", INFO, SCOPE_ADMIN),
    # The facility reporting on itself. Dropped events must be visible, or a
    # bounded buffer silently becomes a lie about what happened.
    ("report.events_dropped", WARNING, SCOPE_NONE),
    ("report.field_rejected", WARNING, SCOPE_NONE),
    # A command-boundary failure, carrying the exception family rather than a
    # rendered traceback.
    ("command.failed", ERROR, SCOPE_NONE),

    # --- Derived from the call sites rather than proposed -----------------
    #
    # The table above was seeded from a reading of what ingest emits and was
    # wrong about it: 23 of the 38 names actually emitted were absent, so every
    # one of them took the shim's fallback rendering path and lost its level and
    # scope. Extracting the names from the call sites with `ast` found them; a
    # test now derives the same set, so an event added to a call site without a
    # code fails rather than silently degrading.
    ("ingest.failed", ERROR, SCOPE_INGEST),
    ("project.identity_changed", WARNING, SCOPE_INGEST),
    ("fresh_rebuild.promoted", INFO, SCOPE_INGEST),
    ("snapshot.skip", INFO, SCOPE_INGEST),
    ("snapshot.trimmed", INFO, SCOPE_INGEST),
    ("snapshot.trim_failed", WARNING, SCOPE_INGEST),
    # Cursor cohort preflight: a shared container is prepared once per run and
    # restored afterwards, so each half reports separately.
    ("cursor.cohort.prepare.start", DEBUG, SCOPE_INGEST),
    ("cursor.cohort.prepare.done", DEBUG, SCOPE_INGEST),
    ("cursor.cohort.restore.start", DEBUG, SCOPE_INGEST),
    ("cursor.cohort.restore.done", DEBUG, SCOPE_INGEST),
    ("cursor.cohort.source_advanced", WARNING, SCOPE_INGEST),
    ("cursor.cohort.failed", ERROR, SCOPE_INGEST),
    # Raw capture, which is where the large-file work happens.
    ("raw.compress.start", DEBUG, SCOPE_INGEST),
    ("raw.compress.done", DEBUG, SCOPE_INGEST),
    ("raw.object_promoted", DEBUG, SCOPE_INGEST),
    ("raw.object_verify.start", DEBUG, SCOPE_INGEST),
    ("raw.object_verify.done", DEBUG, SCOPE_INGEST),
    ("raw.sqlite_backup.start", DEBUG, SCOPE_INGEST),
    ("raw.sqlite_backup.done", DEBUG, SCOPE_INGEST),
    ("raw.working_file.written", DEBUG, SCOPE_INGEST),
    # Post-ingest derivations.
    ("artifact_correlation.start", DEBUG, SCOPE_INGEST),
    ("artifact_correlation.done", DEBUG, SCOPE_INGEST),
    ("evidence_summary.start", DEBUG, SCOPE_INGEST),
    ("evidence_summary.done", DEBUG, SCOPE_INGEST),
    # Info, not debug: it states that work was *skipped*, which is the question
    # an operator asks when a re-run finishes suspiciously fast. `start`/`done`
    # are the trace around work that happened and stay at debug.
    ("evidence_summary.reused", INFO, SCOPE_INGEST),
    # Cursor bubble decode, which reports progress because a large composer is
    # the one read that can take long enough to need it.
    ("cursor.composer.read.start", DEBUG, SCOPE_INGEST),
    ("cursor.composer.read.progress", DEBUG, SCOPE_INGEST),
    ("cursor.composer.read.done", DEBUG, SCOPE_INGEST),
    # Cursor's own ingest phases. A shared container means selection, decode, and
    # write are separate steps with separate costs, so each reports.
    ("cursor.source.start", DEBUG, SCOPE_INGEST),
    ("cursor.source.done", DEBUG, SCOPE_INGEST),
    ("cursor.source.failed", WARNING, SCOPE_INGEST),
    ("cursor.composer.write.start", DEBUG, SCOPE_INGEST),
    ("cursor.composer.write.done", DEBUG, SCOPE_INGEST),
    ("cursor.workspace.skip", DEBUG, SCOPE_INGEST),
    ("cursor.project.done", DEBUG, SCOPE_INGEST),
    ("cursor.project.unchanged", INFO, SCOPE_INGEST),
    ("cursor.project.no_composers", INFO, SCOPE_INGEST),
    ("source.map.progress", DEBUG, SCOPE_INGEST),
    # Scan-side registry maintenance. Debug because it reports a cleanup that
    # happened rather than a condition an operator acts on.
    ("registry.legacy_cursor_pruned", DEBUG, SCOPE_SCAN),
    # Every administrative subcommand, not one code per subcommand: 42 codes
    # naming what `family`/`command` already say would be a second dispatch
    # table. INFO because each of these can delete, publish, or rewrite state,
    # and "which command ran" is the first thing a later reader wants.
    ("admin.start", INFO, SCOPE_ADMIN),
    ("admin.done", INFO, SCOPE_ADMIN),
)

EVENT_NAMES: tuple[str, ...] = tuple(name for name, _level, _scope in _EVENT_SPECS)
EVENT_LEVELS: tuple[int, ...] = tuple(level for _n, level, _s in _EVENT_SPECS)
EVENT_SCOPES: tuple[int, ...] = tuple(scope for _n, _l, scope in _EVENT_SPECS)
CODE_BY_NAME: dict[str, int] = {name: index for index, name in enumerate(EVENT_NAMES)}


def code(name: str) -> int:
    """Resolve a dotted event name to its integer code.

    Raises for an unknown name rather than assigning one. The set is closed by
    design: a code invented at run time would have no level, no scope, and no
    stable meaning in a retained report.
    """
    try:
        return CODE_BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"unknown event name {name!r}; add it to codes._EVENT_SPECS"
        ) from None


# --- Counters ----------------------------------------------------------------
#
# Seeded from the diagnostic counters the adapters already produce. CoPlan
# 13.4.6 records why the printed list drifted from this set: the ingest command
# named eleven in an f-string while adapters produced twenty-one, so ten were
# counted and never reported and one reported name no longer existed. Deriving
# both the slots and the report from one table removes the second list.
COUNTER_NAMES: tuple[str, ...] = (
    "malformed",
    "ignored",
    "empty_sources",
    "failed_sources",
    "unsupported",
    "known_ignored",
    "filtered",
    "external_content",
    "external_errors",
    "reviewable_content_failures",
    "cursor_ambiguous_fallback",
    "unsupported_records",
    "refused_records",
    "field_absent",
    "field_null",
    "field_malformed",
    "field_sentinel",
    "events_dropped",
    "fields_rejected",
)
SLOT_BY_NAME: dict[str, int] = {name: i for i, name in enumerate(COUNTER_NAMES)}
COUNTER_COUNT = len(COUNTER_NAMES)


def slot(name: str) -> int:
    """Resolve a counter name to its preallocated index."""
    try:
        return SLOT_BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"unknown counter {name!r}; add it to codes.COUNTER_NAMES"
        ) from None


# --- Field registry ----------------------------------------------------------
#
# Three classes. `open` is a count, size, duration, or vendor name; `located`
# names a filesystem position; `linking` is an identifier that correlates to a
# retained record.
OPEN = "open"
LOCATED = "located"
LINKING = "linking"

FIELD_CLASSES: dict[str, str] = {
    # open -- carries no position and no correlation.
    "events": OPEN, "sessions": OPEN, "errors": OPEN, "status": OPEN,
    "vendor": OPEN, "sources": OPEN, "projects": OPEN, "count": OPEN,
    "processed_sessions": OPEN, "processed_events": OPEN,
    "stored_sessions": OPEN, "stored_events": OPEN, "failed_sources": OPEN,
    "phase_seconds": OPEN, "elapsed_seconds": OPEN, "source_bytes": OPEN,
    "pages_completed": OPEN, "pages_total": OPEN, "validate_only": OPEN,
    "raw_mode": OPEN, "project_index": OPEN, "project_total": OPEN,
    "reason": OPEN, "error_type": OPEN, "directories": OPEN,
    # Which subcommand ran. `open` because a subcommand name is a fixed
    # token from the parser, not a path and not a correlatable identifier.
    "family": OPEN, "command": OPEN, "exit_code": OPEN, "action": OPEN,
    "budget": OPEN, "partial": OPEN, "device": OPEN, "field": OPEN,
    "records": OPEN, "bytes": OPEN, "rows": OPEN, "limit": OPEN,
    "size_mb": OPEN, "span_weeks": OPEN, "days_ago": OPEN,
    "header_count": OPEN, "timed_header_count": OPEN, "kind": OPEN,
    # Counts, sizes, and flags taken from the call sites. Each carries a
    # quantity or a state, never a position or an identifier -- which is why
    # they are `open` and why the classification is checkable rather than a
    # judgement: a field naming a path or correlating to a record belongs below.
    "input_bytes": OPEN, "stored_bytes": OPEN, "backup_bytes": OPEN,
    "working_bytes": OPEN, "raw_records": OPEN, "stores": OPEN,
    "matched": OPEN, "unmatched": OPEN, "ambiguous": OPEN,
    "external_artifacts": OPEN, "retained_prior": OPEN, "sealed": OPEN,
    "stage": OPEN, "publication": OPEN, "evidence_refresh": OPEN,
    "bubbles": OPEN, "composer_index": OPEN, "composer_total": OPEN,
    "largest_session_events": OPEN,
    # A composer id names a Cursor Session and a workspace id names its
    # container, so both correlate a line to retained records.
    "composer_id": LINKING, "workspace_ids": LINKING,
    "state_refresh": OPEN, "was": OPEN, "now": OPEN,
    # A raw object is addressed by a content digest, so it correlates a report
    # line to a retained object -- `linking`, not `open`.
    "object_id": LINKING, "pre_revision": LINKING, "post_revision": LINKING,
    # located -- a path, or something that resolves to one.
    "project": LOCATED, "source": LOCATED, "path": LOCATED,
    "state_path": LOCATED, "store": LOCATED, "snapshot": LOCATED,
    "registry": LOCATED, "work_root": LOCATED, "history_path": LOCATED,
    "target": LOCATED, "workspace": LOCATED, "container": LOCATED,
    # linking -- correlates a report line to a retained record.
    "session_id": LINKING, "project_id": LINKING, "event_id": LINKING,
    "source_id": LINKING, "snapshot_id": LINKING, "workspace_id": LINKING,
}

UNREGISTERED = "<unregistered>"
"""Rendered in place of a field name absent from the registry.

Visible rather than silent: a reader sees that something was emitted and not
classified, which is a prompt to classify it. Dropping it would hide the gap
and rendering it would defeat the allowlist.
"""
