"""Gates, limits, and the two profiles that set them together.

Report 6 specifies three gates applied cheapest-first, and Report 11 and 15.5
specify that volume and privacy are each chosen once per run rather than per
call site. Both live here because a gate reads a limit and a limit comes from a
profile.

The gates, in the order a call pays them, with the cost measured on this
implementation rather than on Report 2's prototypes:

  (a) compile-time   a literal `False` build constant folds the site away   16 ns
  (b) import-time    below MIN_LEVEL, checked after the sink table         86 ns
  (c) run-time       no sink attached, checked before any construction     76 ns

(c) must precede construction, which is the defect Report 6 records in the
current facility: it builds the record and then decides not to emit it.

(b) and (c) cost more than Report 3 estimated, because `**fields` packs a dict
before the function body runs and no in-body gate can precede that -- the
reasoning is on `api.event`. (a) is the only gate that reaches a per-call cost
low enough for a site inside a decode loop, which is why it exists separately.
"""

from __future__ import annotations

import os

from codess.reporting.codes import DEBUG, ERROR, INFO, LEVEL_BY_NAME, WARNING

# --- Compile-time gate -------------------------------------------------------
#
# Read from the environment at import so it is a module constant by the time any
# call site is compiled. A site written as `if REPORT_TRACE:` around a per-record
# trace point costs nothing when this is False, because CPython folds a branch on
# a literal-bound constant (Report 2.4). It is deliberately separate from the
# level gate: a trace point inside the decode loop should not exist in a
# deployment build at all, which is a stronger statement than "not emitted".
REPORT_TRACE = os.environ.get("CODESS_REPORT_TRACE", "0").strip().lower() in (
    "1", "true", "yes",
)

# --- Limits ------------------------------------------------------------------
MAX_FIELD_BYTES = 4 * 1024
"""Report 6. A scalar longer than this is truncated with a marker.

Truncation is visible rather than silent: an unexpectedly large value is
evidence about the caller, and hiding it would remove the signal.
"""

MAX_FIELDS = 24
"""Report 6. Fields past this are dropped and counted, never raised (R10)."""


class Profile:
    """One named run configuration: what to emit, where, and how much to reveal.

    Volume and privacy are one object because they answer the same question --
    what is this run for -- and separating them produced the combination nobody
    wanted: a debug-volume run redacting the paths the operator was debugging.
    """

    __slots__ = ("flush_events", "min_level", "name", "privacy", "sinks")

    def __init__(
        self, name: str, *, min_level: int, sinks: tuple[str, ...],
        flush_events: int, privacy: str,
    ) -> None:
        self.name = name
        self.min_level = min_level
        self.sinks = sinks
        self.flush_events = flush_events
        self.privacy = privacy

    def __repr__(self) -> str:
        return (
            f"Profile({self.name!r}, min_level={self.min_level}, "
            f"sinks={self.sinks}, privacy={self.privacy!r})"
        )


# Report 11's table. `deployment` is the default because an ordinary run should
# report what an operator must act on and nothing else.
PROFILES: dict[str, Profile] = {
    "debug": Profile(
        "debug", min_level=DEBUG, sinks=("human",), flush_events=32,
        privacy="local",
    ),
    "validation": Profile(
        "validation", min_level=INFO, sinks=("collector", "human"),
        flush_events=256, privacy="local",
    ),
    "deployment": Profile(
        "deployment", min_level=WARNING, sinks=("human",), flush_events=256,
        privacy="local",
    ),
    "benchmark": Profile(
        "benchmark", min_level=ERROR, sinks=(), flush_events=1,
        privacy="local",
    ),
}

# Report 15.5. `local` is the default deliberately: Codess reads a developer's
# own data on their own machine, so redacting by default would make the ordinary
# case harder to read against a risk the ordinary case does not carry. The
# profile exists so that *sharing* is a choice with a mechanism.
PRIVACY_PROFILES = ("local", "shared", "strict")

DEFAULT_PROFILE = "deployment"


def resolve(name: str | None = None, privacy: str | None = None) -> Profile:
    """Select a profile by name, with an optional privacy override.

    Resolution order is argument, then environment, then the default. An unknown
    name raises: a mistyped profile silently falling back to the default would
    mean a run intended to redact does not, which is the failure this cannot
    afford to make quietly.
    """
    selected = name or os.environ.get("CODESS_REPORT_PROFILE") or DEFAULT_PROFILE
    try:
        profile = PROFILES[selected]
    except KeyError:
        raise ValueError(
            f"unknown reporting profile {selected!r}; "
            f"expected one of {', '.join(sorted(PROFILES))}"
        ) from None
    chosen_privacy = privacy or os.environ.get("CODESS_REPORT_PRIVACY")
    if chosen_privacy is None:
        return profile
    if chosen_privacy not in PRIVACY_PROFILES:
        raise ValueError(
            f"unknown privacy profile {chosen_privacy!r}; "
            f"expected one of {', '.join(PRIVACY_PROFILES)}"
        )
    return Profile(
        profile.name, min_level=profile.min_level, sinks=profile.sinks,
        flush_events=profile.flush_events, privacy=chosen_privacy,
    )


def level_from_name(name: str) -> int:
    """Resolve a level name for a CLI or environment value."""
    try:
        return LEVEL_BY_NAME[name]
    except KeyError:
        raise ValueError(
            f"unknown level {name!r}; expected one of "
            f"{', '.join(sorted(LEVEL_BY_NAME))}"
        ) from None
