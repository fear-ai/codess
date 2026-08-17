"""Codex transcript roots, metadata, fingerprinted inventory, and selection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codess.config import CODEX_ARCHIVED_SESSIONS, CODEX_SESSIONS
from codess.fileio import read_json, write_json_atomic

CODEX_INDEX_FORMAT = "codess.codex-session-index/1"


def get_session_roots() -> list[Path]:
    """Return configured active and archived transcript roots, deduplicated."""
    roots = [CODEX_SESSIONS]
    if CODEX_ARCHIVED_SESSIONS is not None:
        roots.append(CODEX_ARCHIVED_SESSIONS)
    return list(dict.fromkeys(path.resolve() for path in roots))


def unrolled_history_sessions(
    *, history_path: Path | None = None, sample: int | None = None,
) -> dict[str, Any]:
    """Sessions Codex retained a human side for and no rollout.

    `~/.codex/history.jsonl` records human prompts keyed by `session_id`,
    beside the rollout tree. It is usually redundant -- a Session with a
    rollout has its prompts there too -- but the two are written
    independently, so a Session can appear in history with no rollout at all.
    Measured on one machine: 19 Sessions in history, 18 with rollouts, and
    one without, carrying 2 prompts. An earlier count of three
    read only the active tree; two of those had archived rollouts, which is
    why this consults `get_session_roots()` rather than one directory.

    **This reports; it does not decode.** Admitting a history-only Session
    would mean a Session with prompts and no Model Turns, which changes what
    a Session is and is a mapping decision under 6.5. Reporting that evidence
    exists which Codess cannot decode is a coverage statement, and is what the
    record-level diagnostics are for -- the cheap, honest middle
    path between silence and a new mapping.

    Returns counts and Session identifiers only. No prompt text is read into
    the result, so the report can be published beside a store.
    """
    history = history_path or (CODEX_SESSIONS.parent / "history.jsonl")
    observed: dict[str, int] = {}
    if history.is_file():
        try:
            with history.open(encoding="utf-8", errors="replace") as stream:
                for index, line in enumerate(stream):
                    if sample is not None and index >= sample:
                        break
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    identifier = record.get("session_id")
                    if isinstance(identifier, str) and identifier:
                        observed[identifier] = observed.get(identifier, 0) + 1
        except OSError:
            return {"available": False, "history_path": str(history)}

    rolled: set[str] = set()
    for root in get_session_roots():
        if not root.is_dir():
            continue
        for rollout in root.rglob("*.jsonl"):
            rolled.add(rollout.stem.split("-")[-1])

    # Rollout filenames carry a suffix of the identifier rather than the whole
    # of it, so membership is tested on that suffix rather than on equality.
    unrolled = {
        identifier: count for identifier, count in observed.items()
        if identifier[-12:] not in rolled
    }
    return {
        "available": history.is_file(),
        "history_path": str(history),
        "history_sessions": len(observed),
        "with_rollout": len(observed) - len(unrolled),
        "without_rollout": len(unrolled),
        "unrolled_prompt_counts": dict(sorted(unrolled.items())),
    }


def session_archive_evidence(path: Path) -> tuple[str, str]:
    """Classify archive state solely from the configured source root."""
    resolved = path.resolve()
    archived = CODEX_ARCHIVED_SESSIONS
    if archived is not None and resolved.is_relative_to(archived.resolve()):
        return "archived", "configured-archive-root"
    return "active", "configured-active-root"


def build_session_index(
    *, cache_path: Path | None = None, include_record_counts: bool = False,
) -> list[dict[str, Any]]:
    """Index metadata while rereading only new or fingerprint-changed files."""
    roots = get_session_roots()
    root_names = [str(root) for root in roots]
    cached: dict[str, dict[str, Any]] = {}
    if cache_path and cache_path.exists():
        try:
            value = read_json(cache_path)
            if (
                value.get("format") == CODEX_INDEX_FORMAT
                and value.get("roots") == root_names
            ):
                cached = {
                    str(item["path"]): item for item in value.get("files", [])
                    if isinstance(item, dict) and item.get("path")
                }
        except (OSError, ValueError, json.JSONDecodeError):
            cached = {}

    indexed: list[dict[str, Any]] = []
    for root_index, root in enumerate(roots):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.jsonl")):
            try:
                stat = path.stat()
            except OSError:
                continue
            key = str(path.resolve())
            old = cached.get(key)
            fingerprint_matches = bool(
                old
                and old.get("size") == stat.st_size
                and old.get("mtime_ns") == stat.st_mtime_ns
                and old.get("root_index") == root_index
            )
            needs_count = include_record_counts and (
                not old or not isinstance(old.get("record_count"), int)
            )
            if fingerprint_matches and not needs_count:
                indexed.append(dict(old))
                continue

            meta = None
            record_count = 0
            try:
                with path.open(encoding="utf-8", errors="replace") as stream:
                    for line in stream:
                        if not line.strip():
                            continue
                        if include_record_counts:
                            record_count += 1
                        if meta is not None:
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if record.get("type") == "session_meta":
                            meta = record
                            if not include_record_counts:
                                break
            except OSError:
                continue
            payload = (meta or {}).get("payload") or {}
            item: dict[str, Any] = {
                "path": key,
                "root_index": root_index,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "session_id": str(payload.get("id") or path.stem),
                "cwd": str(payload.get("cwd") or ""),
                "timestamp": (meta or {}).get("timestamp"),
            }
            if include_record_counts:
                item["record_count"] = record_count
            elif old and isinstance(old.get("record_count"), int):
                item["record_count"] = old["record_count"]
            indexed.append(item)

    if cache_path:
        write_json_atomic(cache_path, {
            "format": CODEX_INDEX_FORMAT,
            "roots": root_names,
            "files": indexed,
        })
    return indexed


def get_session_files(
    project_path: Path,
    *,
    index: list[dict[str, Any]] | None = None,
    cache_path: Path | None = None,
) -> list[Path]:
    """Return deduplicated transcripts whose indexed cwd is within Project."""
    project_str = str(project_path.resolve())
    selected: dict[str, tuple[tuple[int, float, str], Path]] = {}
    entries = index if index is not None else build_session_index(cache_path=cache_path)
    for item in entries:
        cwd = str(item.get("cwd") or "")
        if not cwd or not (cwd == project_str or cwd.startswith(project_str + "/")):
            continue
        path = Path(str(item["path"]))
        session_id = str(item.get("session_id") or path.stem)
        rank = (
            int(item.get("root_index", 0)),
            -float(item.get("mtime_ns", 0)),
            str(path),
        )
        current = selected.get(session_id)
        if current is None or rank < current[0]:
            selected[session_id] = (rank, path)
    return sorted((item[1] for item in selected.values()), key=str)
