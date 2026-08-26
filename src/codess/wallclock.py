"""The one place Codess reads the ambient wall clock.

`timeval` converts and formats instants and reads no clock at all -- a test
walks its syntax tree to assert that, because every value it produces must
depend on its arguments rather than on when the process ran. That constraint is
only worth having if the clock lives somewhere, and this is where.

Callers pass `system_clock` to the `timeval` function that needs an instant:

    from codess.timeval import now_iso
    from codess.wallclock import system_clock

    observed_when = now_iso(system_clock)

Written that way rather than as `now_iso(lambda: datetime.now(UTC))` because a
lambda at each call site spells the ambient clock 40-odd times and gives a test
nothing to replace. The injection point stays visible at the call site and the
clock has one definition.

`reporting.clock` is a different clock and stays separate: it anchors monotonic
ticks for event timing, where a backward NTP step would produce a negative
duration.
"""

from __future__ import annotations

from datetime import UTC, datetime


def system_clock() -> datetime:
    """The current instant, timezone-aware and in UTC.

    Returns an aware `datetime` rather than a naive one so a caller cannot
    silently record local time: `timeval` reads a naive stamp as UTC, which is
    right for vendor data of unstated zone and wrong for a clock Codess reads
    itself.
    """
    return datetime.now(UTC)
