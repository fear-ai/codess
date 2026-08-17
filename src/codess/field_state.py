"""Field-state classification and two-value comparison for adapters.

A decoder that reports only "missing" loses the distinction between a field
the source omitted, one it sent empty, and one it sent unreadably. Those want
different dispositions, so the state is named and carried rather than
collapsed at the point of discovery.

Public API:
- Field states: ``PRESENT``, ``ABSENT``, ``EMPTY``, ``NULL``, ``SENTINEL``,
  ``MALFORMED``; ``VACANT`` and ``VACANT_STATES`` are the absent-family umbrella.
- Comparison outcomes: ``MATCH``, ``MISMATCH``, ``VACANT``.
- Criticality: ``FATAL``, ``ADVISORY``.
- ``classify(value)`` -> state; ``get_state(record, key)`` -> ``(value, state)``.
- ``severity(state)`` -> ``info``/``warn``/None.
- ``criticality(state, is_critical_field)`` -> ``fatal``/``advisory``/None.
- ``compare(prior, rebuilt)`` -> comparison outcome.
- ``diagnose(opts, ...)`` records a field diagnostic; never raises.

``SENTINEL_VALUES`` lists the trimmed, casefolded strings treated as ``sentinel``.
"""

from __future__ import annotations

from typing import Any

# Field states.
PRESENT = "present"
ABSENT = "absent"
EMPTY = "empty"
NULL = "null"
SENTINEL = "sentinel"
MALFORMED = "malformed"

# Absent-family umbrella (excludes MALFORMED).
VACANT = "vacant"
VACANT_STATES = frozenset({ABSENT, EMPTY, NULL, SENTINEL})


# Comparison outcomes.
MATCH = "match"
MISMATCH = "mismatch"
# VACANT (above) is the third comparison outcome.

# Criticality scale.
FATAL = "fatal"
ADVISORY = "advisory"

_INFO_STATES = frozenset({ABSENT, EMPTY, NULL, SENTINEL})
_WARN_STATES = frozenset({MALFORMED})

# Strings treated as SENTINEL, matched after trim + casefold.
SENTINEL_VALUES = frozenset({
    "n/a", "na", "none", "null", "nil", "unknown", "undefined",
    "not specified", "not set", "-", "--",
})

_MISSING = object()


def classify(value: Any) -> str:
    """Classify a value into a field state. Pass ``_MISSING`` for a missing key
    to get ``absent``. Never raises; ``malformed`` is set by parsing callers."""
    if value is _MISSING:
        return ABSENT
    if value is None:
        return NULL
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return EMPTY
        if stripped.casefold() in SENTINEL_VALUES:
            return SENTINEL
        return PRESENT
    if isinstance(value, (list, dict, tuple, set)):
        return EMPTY if len(value) == 0 else PRESENT
    return PRESENT


def get_state(record: dict, key: str) -> tuple[Any, str]:
    """Return ``(value, state)`` for ``record[key]``, distinguishing absent."""
    value = record.get(key, _MISSING)
    state = classify(value)
    return (None if value is _MISSING else value), state


def severity(state: str) -> str | None:
    """Return ``"info"``, ``"warn"``, or ``None`` (present) for a state.

    Named for what it returns. It was `diagnostic_level`, which read as the
    granularity column beside it in `mapping_diagnostics` and produced exactly
    that confusion: the emitted dict carried `level` meaning severity and
    `diagnostic_level` meaning granularity, and the store read the second into
    the column named after the first (CoPlan W50).
    """
    if state in _WARN_STATES:
        return "warn"
    if state in _INFO_STATES:
        return "info"
    return None


def criticality(state: str, *, is_critical_field: bool) -> str | None:
    """Return ``fatal``/``advisory``/None for a state on a (critical?) field.
    ``present`` -> None; non-present -> ``fatal`` if critical else ``advisory``."""
    if state == PRESENT:
        return None
    return FATAL if is_critical_field else ADVISORY


def compare(prior: Any, rebuilt: Any) -> str:
    """Return ``match``/``mismatch``/``vacant`` for two values. ``vacant`` if
    either side is non-present; else ``match`` if equal, ``mismatch`` if not.
    Never raises."""
    prior_present = classify(prior) == PRESENT
    rebuilt_present = classify(rebuilt) == PRESENT
    if not (prior_present and rebuilt_present):
        return VACANT
    return MATCH if prior == rebuilt else MISMATCH


def diagnose(opts: dict, *, field: str, state: str, source_field: str,
             value: Any = None, mapping_rule: str | None = None) -> None:
    """Record a field diagnostic into ``opts['diagnostics']`` (name->count) and
    ``opts['field_diagnostics']`` (rows); no-op for ``present``. Never raises."""
    if severity(state) is None:
        return
    diagnostics = opts.get("diagnostics")
    if diagnostics is None:
        return
    reason = f"field_{state}"
    diagnostics[reason] = diagnostics.get(reason, 0) + 1
    rows = opts.get("field_diagnostics")
    if rows is not None:
        rows.append(diagnostic(
            field=field, state=state, source_field=source_field,
            value=value, mapping_rule=mapping_rule,
        ))


def diagnostic(
    *,
    field: str,
    state: str,
    source_field: str,
    value: Any = None,
    mapping_rule: str | None = None,
) -> dict | None:
    """Build one bounded field diagnostic suitable for an Event attachment.

    `severity` is how much it matters; `granularity` is which part of the input
    it is about. Both keys name their own column in `mapping_diagnostics`.
    """
    field_severity = severity(state)
    if field_severity is None:
        return None
    return {
        "severity": field_severity,
        "granularity": "field",
        "reason_code": f"field_{state}",
        "field": field,
        "source_field": source_field,
        "source_value": None if state == MALFORMED else _bounded(value),
        "mapping_rule": mapping_rule,
        "detail": None,
    }


def attach(
    event: dict,
    *,
    field: str,
    state: str,
    source_field: str,
    value: Any = None,
    mapping_rule: str | None = None,
) -> None:
    """Attach a non-present field diagnostic to its normalized Event."""
    row = diagnostic(
        field=field, state=state, source_field=source_field,
        value=value, mapping_rule=mapping_rule,
    )
    if row is not None:
        event.setdefault("field_diagnostics", []).append(row)


def _bounded(value: Any, limit: int = 64) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"
