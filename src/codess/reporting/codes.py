"""The event code table, the counter slots, and the field registry.

Three closed sets, all sized at import so the hot path allocates nothing
(Report 9). Each answers a different question and they are here together
because each is a name-to-index table the sinks read and the call sites index.

**An event code is an integer.** Codes are known at import, so an integer
compares and dispatches faster than a string and keeps the event tuple uniform
(Report 5). The dotted name lives here, consulted only when a sink renders.

**A counter is a list index.** A per-record fact answers *how many*, not
*when*, so it is `counters[i] += 1` at 66 ns with no allocation rather than an
event that has to be stored and later aggregated (Report 2.3).

**A field name is classified before it can be rendered.** The registry is an
allowlist: a name absent from it renders as `<unregistered>` under any
non-local privacy profile. A denylist fails open, and the field nobody
classified is the one that leaks (Report 15.4).
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
# Seeded from the event names `ProgressTrace` already emits, because those are
# the events that exist and must keep working when it becomes a shim (Report
# 13.1, gate G3). A code is assigned once and never renumbered: a retained
# report holds integers, so reusing one would silently relabel history.
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
    ("cursor.cohort.unchanged", DEBUG, SCOPE_INGEST),
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
    # otherwise, which is exactly what the level gate is for (W21).
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
    # bounded buffer silently becomes a lie about what happened (Report 6).
    ("report.events_dropped", WARNING, SCOPE_NONE),
    ("report.field_rejected", WARNING, SCOPE_NONE),
    # A command-boundary failure, carrying the exception family rather than a
    # rendered traceback (Report 14).
    ("command.failed", ERROR, SCOPE_NONE),
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
# Report 15.4's three classes. `open` is a count, size, duration, or vendor
# name; `located` names a filesystem position; `linking` is an identifier that
# correlates to a retained record.
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
    "budget": OPEN, "partial": OPEN, "device": OPEN, "field": OPEN,
    "records": OPEN, "bytes": OPEN, "rows": OPEN, "limit": OPEN,
    "size_mb": OPEN, "span_weeks": OPEN, "days_ago": OPEN,
    "header_count": OPEN, "timed_header_count": OPEN, "kind": OPEN,
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
