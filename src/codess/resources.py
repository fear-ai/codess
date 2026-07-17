"""Bounded-ingest checks and low-overhead process resource observations."""

from __future__ import annotations

import platform
from collections.abc import Iterable
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # Windows has no resource module.
    resource = None


class ResourceLimitError(RuntimeError):
    """A bounded-ingest limit failure with machine-readable observations."""

    def __init__(
        self,
        message: str,
        *,
        limit_kind: str | None = None,
        observed: int | None = None,
        maximum: int | None = None,
    ) -> None:
        super().__init__(message)
        self.limit_kind = limit_kind
        self.observed = observed
        self.maximum = maximum


def peak_rss_bytes() -> int | None:
    if resource is None:
        return None
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if platform.system() == "Darwin" else value * 1024


def check_source(path: Path, maximum: int | None) -> int:
    size = path.stat().st_size
    if maximum is not None and size > maximum:
        raise ResourceLimitError(
            f"source size {size} exceeds maximum {maximum}: {path}",
            limit_kind="source_bytes", observed=size, maximum=maximum,
        )
    return size


def check_events(
    sessions_events: dict[str, list[dict[str, Any]]],
    *, max_source: int | None, max_session: int | None,
) -> tuple[int, int]:
    total = sum(len(events) for events in sessions_events.values())
    largest = max((len(events) for events in sessions_events.values()), default=0)
    if max_source is not None and total > max_source:
        raise ResourceLimitError(
            f"source produced {total} events; maximum is {max_source}",
            limit_kind="source_events", observed=total, maximum=max_source,
        )
    if max_session is not None and largest > max_session:
        raise ResourceLimitError(
            f"session produced {largest} events; maximum is {max_session}",
            limit_kind="session_events", observed=largest, maximum=max_session,
        )
    return total, largest


USAGE_KEYS = (
    "files", "logical_bytes", "allocated_bytes", "unique_allocated_bytes",
)


def allocated_bytes(path: Path) -> int:
    """Return filesystem allocation where available, else logical size."""
    stat = path.stat()
    return int(getattr(stat, "st_blocks", 0) * 512 or stat.st_size)


def storage_usage(
    paths: Iterable[Path], *, recurse_directories: bool = True,
) -> dict[str, int]:
    """Measure files with consistent hard-link-aware allocation semantics."""
    files = logical = allocated = unique_allocated = 0
    inodes: set[tuple[int, int]] = set()
    for root in paths:
        candidates = (
            root.rglob("*")
            if recurse_directories and root.is_dir()
            else (root,)
        )
        for path in candidates:
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            disk = int(getattr(stat, "st_blocks", 0) * 512 or stat.st_size)
            files += 1
            logical += stat.st_size
            allocated += disk
            inode = (stat.st_dev, stat.st_ino)
            if inode not in inodes:
                inodes.add(inode)
                unique_allocated += disk
    return {
        "files": files,
        "logical_bytes": logical,
        "allocated_bytes": allocated,
        "unique_allocated_bytes": unique_allocated,
    }


def tree_usage(root: Path) -> dict[str, int]:
    return storage_usage((root,)) if root.exists() else dict.fromkeys(USAGE_KEYS, 0)


def file_usage(paths: Iterable[Path]) -> dict[str, int]:
    return storage_usage(paths, recurse_directories=False)
