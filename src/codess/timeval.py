"""Time parsing, conversion, and formatting, as a standalone set.

Standalone is a constraint rather than a description: this module imports
`datetime` and `typing` and nothing from Codess. It holds no schema knowledge,
no vendor knowledge, and no configuration, so it can be read, tested, and
reasoned about without the rest of the package -- and nothing here can acquire
a dependency that makes a caller import half of Codess to parse a timestamp.

CoSchema fixes two representations and this module converts between them:

    _at    Unix milliseconds, `REAL`, nullable -- a vendor or filesystem
           reported the instant
    _when  RFC 3339 UTC, `TEXT`, not null    -- Codess recorded the instant

The suffix states the representation, so a reader needs neither the DDL nor a
convention memo to know which a column holds. `epoch_ms` reads the first from
whatever a vendor wrote; `to_iso` writes the second; `iso_to_ms` converts a
`_when` value for comparison against an `_at` value, which is done at query time
rather than by storing a numeric copy -- a stored copy is a duplicate column
that can drift, and three such duplicates have already been removed from the
schema for exactly that reason.

The clock is injected. `now_ms` takes the callable that reads it rather than
calling `datetime.now` itself, because an ambient clock makes a receipt's
timestamp depend on when a test ran, and every value this module produces is
either derived from an argument or from that callable.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

# Below this, a numeric epoch value is read as seconds and scaled; at or above
# it, as milliseconds. As milliseconds the boundary is 2001-09-09; as seconds it
# is the year 33658, which no vendor record reaches. Written in full rather than
# as `1e12` so the thousand-fold gap from a seconds-scale value is legible.
EPOCH_MS_FLOOR = 1_000_000_000_000

# The smallest numeric value a caller may treat as an epoch instant: as seconds
# this is 2001-09-09, and below it a value is more likely a counter or an enum
# than a time. Applied by callers that read fields where both appear, not by
# `epoch_ms`, which converts what it is given.
EPOCH_SECONDS_FLOOR = 1_000_000_000

# The window a reported instant must fall in to be treated as a measurement.
# The floor is a date before which no coding-assistant session exists; the
# ceiling allows for a clock ahead of this one without admitting a value that
# is a counter rather than a time. Cursor's `timingInfo.clientStartTime` is the
# case this exists for: it holds milliseconds since process start, so read as an
# epoch it lands in 1970 and is rejected here rather than stored as a 1970
# instant.
SANITY_FLOOR_MS = 1_577_836_800_000  # 2020-01-01T00:00:00Z
SANITY_CEILING_SLACK_MS = 24 * 60 * 60 * 1000


def epoch_ms(value: Any) -> float | None:
    """A reported instant as Unix milliseconds, or `None`.

    Accepts ISO-8601 text, epoch seconds, and epoch milliseconds, because all
    three appear across the vendors and the scale is not stated in the field.

    What this does not do is the caller's: which field to read is vendor
    knowledge, what a failure means needs the expected type, and which basis was
    used is a mapping decision. Nothing here infers a time from ordering,
    adjacency, or file position -- an absent time stays absent.

    Unparseable input returns `None` and never raises, because a caller pairs
    the result with a field state and one bad field must not abort a decode.
    """
    if value is None or isinstance(value, bool):
        # `True` is an `int` in Python, so a flag misread as a time would
        # otherwise return 1970-01-01T00:00:00.001.
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return None
        return number * 1000 if number < EPOCH_MS_FLOOR else number
    if isinstance(value, str):
        # Surrounding whitespace is stripped for every vendor rather than for
        # the one whose parser happened to do it, so a padded value does not
        # parse from one Source and fail from another.
        stripped = value.strip()
        if not stripped:
            return None
        parsed = parse_iso(stripped)
        if parsed is not None:
            return parsed.timestamp() * 1000
        # A numeric string is a stated epoch value, not text Codess failed to
        # read, so it takes the numeric path rather than being rejected for its
        # quoting.
        try:
            return epoch_ms(float(stripped))
        except ValueError:
            return None
    return None


def parse_iso(text: Any) -> datetime | None:
    """An ISO-8601 or RFC 3339 string as a timezone-aware `datetime`, or `None`.

    A naive stamp is read as UTC. Stated here because the assumption is
    invisible in the result: read as local time instead, the value shifts by the
    reader's offset with nothing recording why.
    """
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped:
        return None
    try:
        parsed = datetime.fromisoformat(stripped)
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def iso_to_ms(text: Any) -> float | None:
    """A `_when` value as Unix milliseconds, for comparison against an `_at`.

    The conversion is here rather than in a stored column so that comparing two
    differently measured clocks is visible at the point of use. SQLite's
    `strftime('%s', ...)` is the equivalent for a direct-SQL reader.
    """
    parsed = parse_iso(text)
    return None if parsed is None else parsed.timestamp() * 1000


def to_iso(value: Any) -> str | None:
    """A `_when` value: RFC 3339 UTC text, or `None` where there is no instant.

    Accepts what `epoch_ms` accepts, so a caller holding either representation
    writes the same call.
    """
    milliseconds = epoch_ms(value)
    if milliseconds is None:
        return None
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC).isoformat()


def month_key(text: Any) -> str:
    """The `YYYY-MM` bucket a stamp falls in, or `unknown`.

    Validates by parsing rather than by slicing: `2026-13` has the shape of a
    month and is not one.
    """
    parsed = parse_iso(text)
    return "unknown" if parsed is None else f"{parsed.year:04d}-{parsed.month:02d}"


def is_sane(milliseconds: Any, *, now_milliseconds: float) -> bool:
    """Whether a converted instant is plausible enough to copy into `_derived`.

    The gate is what separates a reported time from a counter that parsed. It is
    applied to the converted value, so a seconds-scale field that would have
    stored a 1970 instant fails here rather than reaching the store.
    """
    if not isinstance(milliseconds, (int, float)) or isinstance(milliseconds, bool):
        return False
    number = float(milliseconds)
    if number != number or number in (float("inf"), float("-inf")):
        return False
    return SANITY_FLOOR_MS <= number <= now_milliseconds + SANITY_CEILING_SLACK_MS


def now_ms(clock: Callable[[], datetime]) -> float:
    """The current instant as Unix milliseconds, from an injected clock.

    The clock is a parameter so a caller can supply a fixed one. A module-level
    `datetime.now` would make every derived value depend on when the process
    ran, which is untestable and puts wall-clock time into a receipt that is
    supposed to record what a run observed.
    """
    return clock().timestamp() * 1000
