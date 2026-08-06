"""Bounded JSONL iteration shared by structure-only vendor audits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from codess.config import MAX_RECORD_BYTES as DEFAULT_MAX_RECORD_BYTES


def iter_bounded_jsonl(
    path: Path,
    *,
    max_record_bytes: int = DEFAULT_MAX_RECORD_BYTES,
) -> Iterator[tuple[int, dict[str, Any] | None, str | None]]:
    """Yield bounded JSON objects; oversize/malformed records are diagnostics."""
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
            try:
                value = json.loads(chunk)
            except (json.JSONDecodeError, UnicodeDecodeError):
                yield line_number, None, "malformed"
                continue
            if not isinstance(value, dict):
                yield line_number, None, "non_object"
                continue
            yield line_number, value, None
