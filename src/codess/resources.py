"""Bounded-ingest checks and low-overhead process resource observations."""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # Windows has no resource module.
    resource = None


class ResourceLimitError(RuntimeError):
    pass


def peak_rss_bytes() -> int | None:
    if resource is None:
        return None
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if platform.system() == "Darwin" else value * 1024


def check_source(path: Path, maximum: int | None) -> int:
    size = path.stat().st_size
    if maximum is not None and size > maximum:
        raise ResourceLimitError(
            f"source size {size} exceeds maximum {maximum}: {path}"
        )
    return size


def check_events(
    sessions_events: dict[str, list[dict[str, Any]]],
    *, max_source: int | None, max_session: int | None,
) -> tuple[int, int]:
    total = sum(len(events) for events in sessions_events.values())
    largest = max((len(events) for events in sessions_events.values()), default=0)
    if max_source is not None and total > max_source:
        raise ResourceLimitError(f"source produced {total} events; maximum is {max_source}")
    if max_session is not None and largest > max_session:
        raise ResourceLimitError(f"session produced {largest} events; maximum is {max_session}")
    return total, largest
