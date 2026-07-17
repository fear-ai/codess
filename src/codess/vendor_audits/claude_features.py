"""Bounded structure-only audit of Claude Code JSONL source shapes."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def audit_claude_features(root: Path, *, max_files: int = 200) -> dict[str, Any]:
    if max_files < 1:
        raise ValueError("Claude audit max_files must be positive")
    files = sorted(root.expanduser().rglob("*.jsonl"))[:max_files]
    record_types: Counter[str] = Counter()
    roles: Counter[str] = Counter()
    content_block_types: Counter[str] = Counter()
    lifecycle: Counter[str] = Counter()
    versions: Counter[str] = Counter()
    parent_links = 0
    sidechains = 0
    malformed = 0
    records = 0
    for path in files:
        try:
            stream = path.open(encoding="utf-8")
        except OSError:
            malformed += 1
            continue
        with stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                if not isinstance(value, dict):
                    continue
                records += 1
                kind = str(value.get("type") or "unknown")
                record_types[kind] += 1
                if value.get("parentUuid"):
                    parent_links += 1
                if value.get("isSidechain"):
                    sidechains += 1
                version = value.get("version") or value.get("claudeCodeVersion")
                if version:
                    versions[str(version)] += 1
                subtype = value.get("subtype")
                if kind in {"system", "summary"} and subtype:
                    lifecycle[str(subtype)] += 1
                message = value.get("message")
                if isinstance(message, dict):
                    if message.get("role"):
                        roles[str(message["role"])] += 1
                    content = message.get("content")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict):
                                content_block_types[str(block.get("type") or "unknown")] += 1
    return {
        "audit_format": "codess.claude-feature-audit/1",
        "privacy_boundary": "structure and aggregate counts only; content bodies not retained",
        "root": str(root.expanduser().resolve()),
        "file_limit": max_files,
        "files_reviewed": len(files),
        "records_reviewed": records,
        "malformed_records": malformed,
        "record_types": dict(record_types),
        "message_roles": dict(roles),
        "content_block_types": dict(content_block_types),
        "lifecycle_subtypes": dict(lifecycle),
        "parent_links": parent_links,
        "sidechain_records": sidechains,
        "versions": dict(versions),
    }
