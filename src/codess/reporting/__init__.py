"""Structured operational reporting: counters, events, spans, and their sinks.

The public surface is `count`, `event`, `span`, `configure`, and `counters`.
Everything else is a module a sink or a test reaches into directly.

Four facilities without a contract became one (Report 1.1): status printing,
progress tracing, logger calls, and exception rendering each decided their own
channel, format, and what to include. The event is now a structure and the
channel is a profile decision, so a call site states what happened and nothing
about where it goes.

**The leaves have no Codess dependency.** `clock`, `buffer`, and `codes` import
only the standard library, which is what lets `fileio` and the adapters report
without an import cycle (Report 4). `privacy` imports `hashing` for a truncated
digest and nothing else.

Design and measurements: [Report](../../../Report.md). Cost figures are
reproducible with `tools/reporting_bench.py`.
"""

from __future__ import annotations

from codess.reporting.api import (
    ProgressEmitter,
    code,
    collector,
    configure,
    count,
    counters,
    emit_named,
    event,
    flush,
    profile,
    reset,
    roots,
    slot,
    span,
)

__all__ = [
    "ProgressEmitter",
    "code",
    "collector",
    "configure",
    "count",
    "counters",
    "emit_named",
    "event",
    "flush",
    "profile",
    "reset",
    "roots",
    "slot",
    "span",
]
