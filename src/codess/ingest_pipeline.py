"""Vendor-neutral source admission and completion for transcript ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codess.resources import ResourceLimitError, check_source
from codess.store import (
    ingest_state_marker, load_ingest_state, save_ingest_state, should_ingest,
)


@dataclass(frozen=True)
class SourceAdmission:
    path: Path
    stat: object | None = None
    error: Exception | None = None
    skip_reason: str | None = None


def inspect_sources(
    paths,
    *,
    state_path: Path,
    force: bool,
    min_size: int,
    max_source_bytes: int | None,
):
    """Yield one explicit admission result; no validation failure is hidden."""
    for value in paths:
        path = value[0] if isinstance(value, tuple) else value
        try:
            stat = path.stat()
            if stat.st_size < min_size:
                yield SourceAdmission(path, stat=stat, skip_reason="below_minimum_size")
                continue
            check_source(path, max_source_bytes)
        except (OSError, ResourceLimitError) as exc:
            yield SourceAdmission(path, error=exc)
            continue
        if not should_ingest(
            state_path, str(path.resolve()), stat.st_mtime, force, path=path
        ):
            yield SourceAdmission(path, stat=stat, skip_reason="unchanged")
            continue
        yield SourceAdmission(path, stat=stat)


def mark_source_complete(state_path: Path, path: Path) -> None:
    """Advance incremental state only after the normalized transaction commits."""
    state = load_ingest_state(state_path)
    state[str(path.resolve())] = ingest_state_marker(path)
    save_ingest_state(state_path, state)
