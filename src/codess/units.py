"""Byte-size and duration conversion, as symmetric sets.

Six converters in three pairs: `KB`/`MB`/`GB` render a human quantity as
bytes, and `BKB`/`BMB`/`BGB` render bytes back. They live here rather than in
`config` because they are representation, not configuration -- `config`
*uses* them to express a limit, and so does any module reporting a size, but
neither owns the conversion.

The set is kept complete even though the reverse converters are used
unevenly. They are the inverse of a function that is used, they are two lines
each, and an incomplete set invites the next caller to write the division
inline -- which is how a conversion acquires several spellings. Deleting the
unused half would optimize for a line count at the cost of the property that
makes the set readable.

All six are binary units: a kibibyte is 1024 bytes, not 1000. Codess reports
storage that operating systems and SQLite report the same way, so the binary
reading is the one that matches what a reader sees elsewhere.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def KB(count: float) -> int:
    """`count` kibibytes as bytes (`count * 1024`)."""
    return int(count * 1024)


def MB(count: float) -> int:
    """`count` mebibytes as bytes (`count * 1024**2`)."""
    return int(count * 1024**2)


def GB(count: float) -> int:
    """`count` gibibytes as bytes (`count * 1024**3`)."""
    return int(count * 1024**3)


def BKB(count: float) -> float:
    """`count` bytes as kibibytes (`count / 1024`); inverse of `KB`."""
    return count / 1024


def BMB(count: float) -> float:
    """`count` bytes as mebibytes (`count / 1024**2`); inverse of `MB`."""
    return count / 1024**2


def BGB(count: float) -> float:
    """`count` bytes as gibibytes (`count / 1024**3`); inverse of `GB`."""
    return count / 1024**3


# --- Durations ---------------------------------------------------------------
#
# Named because the alternative was unlabeled arithmetic whose unit could only
# be inferred from the expression around it. `walk_sessions` alone mixed three
# conventions: days as `/(24 * 3600 * 1000)`, weeks as `/(7 * 24 * 3600 * 1000)`
# repeated at every span calculation, and a cutoff computed in seconds via
# `* 86400` before a separate conversion to milliseconds. A
# milliseconds-versus-seconds error reads as plausible code in that form.
#
# These live beside the byte converters because both are representation rather
# than configuration, and for the same reason the byte set is kept complete: an
# incomplete set invites the next caller to write the arithmetic inline, which is
# how a conversion acquires several spellings.
#
# Vendor timestamps are milliseconds, so the millisecond forms are the ones the
# call sites need and the boundary where the current code was most confusing.
MINUTE_SECONDS = 60
HOUR_SECONDS = 60 * MINUTE_SECONDS
DAY_SECONDS = 24 * HOUR_SECONDS
WEEK_SECONDS = 7 * DAY_SECONDS

SECOND_MS = 1_000
MINUTE_MS = MINUTE_SECONDS * SECOND_MS
HOUR_MS = HOUR_SECONDS * SECOND_MS
DAY_MS = DAY_SECONDS * SECOND_MS
WEEK_MS = WEEK_SECONDS * SECOND_MS


def seconds_to_ms(seconds: float) -> float:
    """Seconds as milliseconds, for comparison against a vendor timestamp."""
    return seconds * SECOND_MS


def ms_to_seconds(milliseconds: float) -> float:
    """Milliseconds as seconds, the inverse of `seconds_to_ms`."""
    return milliseconds / SECOND_MS


# Below this, a numeric epoch value is read as seconds and scaled; at or above
# it, as milliseconds. As milliseconds the boundary is 2001-09-09; as seconds
# it is the year 33658, which no vendor record reaches. Written in full rather
# than as `1e12` so the thousand-fold gap from a seconds-scale value is legible.
EPOCH_MILLISECONDS_FLOOR = 1_000_000_000_000


# The smallest numeric value a caller may treat as an epoch instant: as seconds
# this is 2001-09-09, and below it a value is more likely a counter or an enum
# than a time. Applied by callers that read fields where both appear, not by
# `epoch_milliseconds`, which converts what it is given.
EPOCH_SECONDS_FLOOR = 1_000_000_000


def epoch_milliseconds(value: Any) -> float | None:
    """A vendor-reported instant as Unix milliseconds, or `None`.

    CoSchema fixes the unit: a source-reported numeric time is `REAL`
    milliseconds, so that is the return unit rather than a choice each caller
    makes. Accepts ISO-8601 text, epoch seconds, and epoch milliseconds.

    What this does not do is the caller's: which field to read is vendor
    knowledge, what a failure means needs the expected type, and which basis
    was used is a mapping decision. Nothing here infers a time from ordering,
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
        return number * 1000 if number < EPOCH_MILLISECONDS_FLOOR else number
    if isinstance(value, str):
        # Surrounding whitespace is stripped for every vendor rather than for
        # the one whose parser happened to do it, so a padded value does not
        # parse from one Source and fail from another.
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = datetime.fromisoformat(stripped)
        except (TypeError, ValueError):
            # A numeric string is a stated epoch value, not text Codess
            # failed to read, so it takes the numeric path rather than being
            # rejected for its quoting.
            try:
                return epoch_milliseconds(float(stripped))
            except ValueError:
                return None
        if parsed.tzinfo is None:
            # A naive stamp is read as UTC. Stated here because the assumption
            # is invisible in the result: read as local time instead, the value
            # shifts by the reader's offset with nothing recording why.
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp() * 1000
    return None
