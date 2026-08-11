"""Bounded JSONL iteration shared by structure-only vendor audits."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterator

from codess.config import MAX_RECORD_BYTES as DEFAULT_MAX_RECORD_BYTES


log = logging.getLogger(__name__)


def iter_bounded_jsonl(
    path: Path,
    *,
    max_record_bytes: int = DEFAULT_MAX_RECORD_BYTES,
) -> Iterator[tuple[int, dict[str, Any] | None, str | None]]:
    """Yield bounded JSON objects; unusable records become diagnostics.

    A final line with no trailing newline is reported as `incomplete` rather
    than `malformed`. Vendors append to these files while a session is open,
    so a record caught mid-write is expected and says nothing about the data;
    a later read gets the finished record. Callers should skip an incomplete
    record and warn, not reject the file.
    """
    if max_record_bytes < 1024:
        raise ValueError("max_record_bytes must be at least 1024")
    with path.open("rb") as stream:
        line_number = 0
        while True:
            chunk = stream.readline(max_record_bytes + 1)
            if not chunk:
                return
            line_number += 1
            if len(chunk) > max_record_bytes:
                while chunk and not chunk.endswith(b"\n"):
                    chunk = stream.readline(max_record_bytes + 1)
                yield line_number, None, "oversize"
                continue
            if not chunk.strip():
                continue
            if not chunk.endswith(b"\n"):
                # No terminator: the writer has not finished this record.
                # Always the last line, so the file ends here either way.
                log.warning(
                    "skipping incomplete final record (source still being "
                    "written): %s:%d", path, line_number,
                )
                yield line_number, None, "incomplete"
                return
            try:
                value = json.loads(chunk)
            except (json.JSONDecodeError, UnicodeDecodeError):
                yield line_number, None, "malformed"
                continue
            if not isinstance(value, dict):
                yield line_number, None, "non_object"
                continue
            yield line_number, value, None
