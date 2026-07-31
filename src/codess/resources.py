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


def searchable_event_payload(event: dict[str, Any]) -> tuple[int, int]:
    """Measure retained searchable text without double-counting aliases.

    Tool-result adapters commonly place the same value in both ``content`` and
    ``tool_output`` so ordinary text search and structured tool queries can
    share one Event.  That physical projection is one logical payload value.
    Other equal-valued fields remain distinct because they have distinct
    semantics.
    """
    values: list[str] = []
    content = event.get("content")
    if isinstance(content, str):
        values.append(content)
    tool_input = event.get("tool_input")
    if isinstance(tool_input, str):
        values.append(tool_input)
    tool_output = event.get("tool_output")
    if isinstance(tool_output, str) and tool_output != content:
        values.append(tool_output)
    artifact_path = event.get("artifact_path")
    if isinstance(artifact_path, str):
        values.append(artifact_path)
    return (
        sum(len(value) for value in values),
        sum(len(value.encode("utf-8")) for value in values),
    )


def summarize_event_payload(
    sessions_events: dict[str, list[dict[str, Any]]],
) -> tuple[int, int]:
    """Return retained searchable characters and UTF-8 bytes."""
    characters = utf8_bytes = 0
    for events in sessions_events.values():
        for event in events:
            event_characters, event_bytes = searchable_event_payload(event)
            characters += event_characters
            utf8_bytes += event_bytes
    return characters, utf8_bytes


def summarize_resource_observations(
    observations: Iterable[dict[str, Any]],
) -> dict[str, int | None]:
    """Reconcile additive and non-additive ingest resource observations."""
    items = list(observations)
    unique_containers: dict[str, int] = {}
    emitted_events = 0
    retained_characters = 0
    retained_utf8_bytes = 0
    largest_session = 0
    peak_rss: int | None = None
    for item in items:
        size = int(item.get("source_bytes") or 0)
        container = str(item.get("container") or item.get("source") or "")
        if container:
            unique_containers[container] = max(
                unique_containers.get(container, 0), size
            )
        emitted_events += int(item.get("events") or 0)
        retained_characters += int(
            item.get("retained_searchable_characters") or 0
        )
        retained_utf8_bytes += int(
            item.get("retained_searchable_utf8_bytes") or 0
        )
        largest_session = max(
            largest_session, int(item.get("largest_session_events") or 0)
        )
        observed_rss = item.get("peak_rss_bytes")
        if observed_rss is not None:
            peak_rss = max(peak_rss or 0, int(observed_rss))
    return {
        "observations": len(items),
        "unique_source_containers": len(unique_containers),
        "unique_source_container_bytes": sum(unique_containers.values()),
        "emitted_events": emitted_events,
        "retained_searchable_characters": retained_characters,
        "retained_searchable_utf8_bytes": retained_utf8_bytes,
        "largest_session_events": largest_session,
        # Process RSS is a high-water mark and is never additive.
        "peak_rss_bytes": peak_rss,
    }


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
