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

from codess.timeval import (
    EPOCH_MS_FLOOR,
    EPOCH_SECONDS_FLOOR,
    epoch_ms,
)


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


# Time parsing lives in `timeval`, which is standalone by constraint. These
# names are re-exported so existing callers keep working while they migrate;
# `timeval` is the module a new caller imports.
EPOCH_MILLISECONDS_FLOOR = EPOCH_MS_FLOOR
EPOCH_SECONDS_FLOOR = EPOCH_SECONDS_FLOOR

epoch_milliseconds = epoch_ms
