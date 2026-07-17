"""Derived monthly token observations from current local vendor sources."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from codess.fileio import read_json, write_json_atomic

TOKEN_OBSERVATION_FORMAT = "codess.token-observation/1"
TOKEN_CACHE_FORMAT = "codess.token-source-set-cache/1"
MAX_TOKEN_LINE_BYTES = 8 * 1024**2


def _month(value: Any) -> str:
    if isinstance(value, str) and len(value) >= 7:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return value[:7]
        except ValueError:
            pass
    return "unknown"


def _integer(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _new_bucket() -> dict[str, int]:
    return {
        "input_tokens": 0, "cached_input_tokens": 0,
        "cache_creation_input_tokens": 0, "output_tokens": 0,
        "reasoning_output_tokens": 0, "total_tokens": 0,
        "usage_records": 0,
    }


def _add(bucket: dict[str, int], values: dict[str, int]) -> None:
    for key in bucket:
        if key != "usage_records":
            bucket[key] += int(values.get(key, 0))
    bucket["usage_records"] += 1


def _rows(buckets: dict[tuple[str, str], dict[str, int]]) -> list[dict[str, Any]]:
    return [
        {"month": month, "model": model, **values}
        for (month, model), values in sorted(buckets.items())
    ]


def _claude(paths: Iterable[Path]) -> dict[str, Any]:
    buckets: dict[tuple[str, str], dict[str, int]] = defaultdict(_new_bucket)
    seen: set[str] = set()
    files = malformed = oversized = 0
    for path in sorted(set(paths)):
        try:
            stream = path.open("rb")
        except OSError:
            continue
        files += 1
        with stream:
            for line_number, raw in enumerate(stream, 1):
                if len(raw) > MAX_TOKEN_LINE_BYTES:
                    oversized += 1
                    continue
                try:
                    record = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    malformed += 1
                    continue
                message = record.get("message") or {}
                usage = message.get("usage") if isinstance(message, dict) else None
                if not isinstance(usage, dict):
                    continue
                message_id = message.get("id")
                request_id = record.get("requestId") or record.get("request_id")
                identity = (
                    f"{message_id}:{request_id}" if message_id and request_id
                    else f"{path.resolve()}:{line_number}"
                )
                if identity in seen:
                    continue
                seen.add(identity)
                values = {
                    "input_tokens": _integer(usage.get("input_tokens")),
                    "cached_input_tokens": _integer(usage.get("cache_read_input_tokens")),
                    "cache_creation_input_tokens": _integer(usage.get("cache_creation_input_tokens")),
                    "output_tokens": _integer(usage.get("output_tokens")),
                }
                values["total_tokens"] = sum(values.values())
                _add(
                    buckets[(_month(record.get("timestamp")), str(message.get("model") or "unknown"))],
                    values,
                )
    return {
        "source_system_id": "anthropic.claude-code",
        "method": "deduplicated_message_usage_sum_v1",
        "confidence": "local_observed",
        "files": files, "malformed_lines": malformed,
        "oversized_lines": oversized, "monthly": _rows(buckets),
    }


def _codex(paths: Iterable[Path]) -> dict[str, Any]:
    buckets: dict[tuple[str, str], dict[str, int]] = defaultdict(_new_bucket)
    files = malformed = oversized = counter_resets = 0
    for path in sorted(set(paths)):
        previous = _new_bucket()
        model = "unknown"
        try:
            stream = path.open("rb")
        except OSError:
            continue
        files += 1
        with stream:
            for raw in stream:
                if len(raw) > MAX_TOKEN_LINE_BYTES:
                    oversized += 1
                    continue
                try:
                    record = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    malformed += 1
                    continue
                payload = record.get("payload") or {}
                if record.get("type") == "turn_context" and payload.get("model"):
                    model = str(payload["model"])
                if not (
                    record.get("type") == "event_msg"
                    and payload.get("type") == "token_count"
                ):
                    continue
                total = (payload.get("info") or {}).get("total_token_usage")
                if not isinstance(total, dict):
                    continue
                current = {
                    "input_tokens": _integer(total.get("input_tokens")),
                    "cached_input_tokens": _integer(total.get("cached_input_tokens")),
                    "cache_creation_input_tokens": 0,
                    "output_tokens": _integer(total.get("output_tokens")),
                    "reasoning_output_tokens": _integer(total.get("reasoning_output_tokens")),
                    "total_tokens": _integer(total.get("total_tokens")),
                }
                keys = tuple(current)
                if all(current[key] == previous.get(key, 0) for key in keys):
                    continue
                monotonic = all(current[key] >= previous.get(key, 0) for key in keys)
                if monotonic:
                    delta = {key: current[key] - previous.get(key, 0) for key in keys}
                else:
                    counter_resets += 1
                    delta = current
                if any(delta.values()):
                    _add(
                        buckets[(_month(record.get("timestamp")), model)], delta
                    )
                previous = {**previous, **current}
    return {
        "source_system_id": "openai.codex",
        "method": "cumulative_positive_delta_v1",
        "confidence": "local_derived_provisional",
        "limitations": (
            "counter drops are treated as resets; fork/interleave attribution "
            "must be validated against the CodexBar lineage algorithm"
        ),
        "files": files, "malformed_lines": malformed,
        "oversized_lines": oversized, "counter_resets": counter_resets,
        "monthly": _rows(buckets),
    }


def collect_token_usage(
    store_paths: Iterable[Path], *, cache_path: Path | None = None,
) -> dict[str, Any]:
    """Collect token observations, reusing an unchanged current-source set."""
    sources: dict[str, set[Path]] = defaultdict(set)
    for store in store_paths:
        try:
            import sqlite3
            conn = sqlite3.connect(store.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                for system, uri in conn.execute(
                    "SELECT source_system_id, source_uri FROM sources"
                ):
                    path = Path(str(uri))
                    if path.is_file():
                        sources[str(system)].add(path)
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            continue
    fingerprints = []
    for system, paths in sorted(sources.items()):
        for path in sorted(paths):
            try:
                stat = path.stat()
            except OSError:
                continue
            fingerprints.append({
                "source_system_id": system,
                "path": str(path.resolve()),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            })
    if cache_path and cache_path.exists():
        try:
            cached = read_json(cache_path)
            if (
                cached.get("format") == TOKEN_CACHE_FORMAT
                and cached.get("fingerprints") == fingerprints
                and isinstance(cached.get("result"), dict)
            ):
                return {
                    **cached["result"],
                    "cache": {"status": "hit", "files": len(fingerprints)},
                }
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    claude = _claude(sources["anthropic.claude-code"])
    codex = _codex(sources["openai.codex"])
    result = {
        "format": TOKEN_OBSERVATION_FORMAT,
        "vendors": [
            claude,
            codex,
            {
                "source_system_id": "cursor.composer",
                "method": None,
                "confidence": "unknown",
                "availability": "unavailable",
                "reason": "no verified local Cursor token field is mapped",
                "monthly": [],
            },
        ],
    }
    if cache_path:
        write_json_atomic(cache_path, {
            "format": TOKEN_CACHE_FORMAT,
            "fingerprints": fingerprints,
            "result": result,
        })
    return {
        **result,
        "cache": {"status": "miss", "files": len(fingerprints)},
    }
