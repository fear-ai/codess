"""Byte-size conversion, as one symmetric set.

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
