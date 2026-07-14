#!/usr/bin/env python3
"""Fail-closed compatibility gate for machine-readable CoSchema contracts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator


RANK = {"same": 0, "compatible": 1, "breaking": 2, "manual": 3}


def _fields(entity: dict[str, Any]) -> dict[str, Any]:
    return entity.get("fields", {})


def compare(old: dict[str, Any], new: dict[str, Any]) -> Iterator[tuple[str, str, str]]:
    """Yield (classification, path, explanation) for meaningful differences."""
    known_root = {"format_id", "format_version", "application_id", "compatibility_policy", "entities", "vocabularies"}
    if old.get("format_id") != new.get("format_id"):
        yield "breaking", "/format_id", "format identity changed"
    if old.get("application_id") != new.get("application_id"):
        yield "breaking", "/application_id", "SQLite application identity changed"

    old_entities, new_entities = old.get("entities", {}), new.get("entities", {})
    for name in sorted(set(old_entities) | set(new_entities)):
        path = f"/entities/{name}"
        if name not in new_entities:
            yield "breaking", path, "entity removed"
            continue
        if name not in old_entities:
            yield "compatible", path, "entity added"
            continue
        oe, ne = old_entities[name], new_entities[name]
        if oe.get("identity") != ne.get("identity"):
            yield "breaking", f"{path}/identity", "identity changed"
        if oe.get("order") != ne.get("order"):
            yield "breaking", f"{path}/order", "ordering contract changed"
        of, nf = _fields(oe), _fields(ne)
        for field in sorted(set(of) | set(nf)):
            fpath = f"{path}/fields/{field}"
            if field not in nf:
                yield "breaking", fpath, "field removed"
                continue
            if field not in of:
                level = "compatible" if nf[field].get("nullable", True) else "breaking"
                yield level, fpath, "nullable field added" if level == "compatible" else "required field added"
                continue
            old_field, new_field = of[field], nf[field]
            if old_field.get("type") != new_field.get("type"):
                yield "breaking", fpath, "field type changed"
            if old_field.get("nullable", True) and not new_field.get("nullable", True):
                yield "breaking", fpath, "field became required"
            elif not old_field.get("nullable", True) and new_field.get("nullable", True):
                yield "compatible", fpath, "field became nullable"
            for semantic_key in ("target", "vocabulary", "minimum", "maximum"):
                if old_field.get(semantic_key) != new_field.get(semantic_key):
                    yield "manual", f"{fpath}/{semantic_key}", f"{semantic_key} changed"
            unknown = (set(old_field) | set(new_field)) - {
                "type", "nullable", "target", "vocabulary", "minimum", "maximum"
            }
            for key in sorted(unknown):
                if old_field.get(key) != new_field.get(key):
                    yield "manual", f"{fpath}/{key}", "unclassified field contract change"

    ov, nv = old.get("vocabularies", {}), new.get("vocabularies", {})
    for name in sorted(set(ov) | set(nv)):
        path = f"/vocabularies/{name}"
        if name not in nv:
            yield "breaking", path, "vocabulary removed"
        elif name not in ov:
            yield "compatible", path, "vocabulary added"
        else:
            removed = set(ov[name]) - set(nv[name])
            added = set(nv[name]) - set(ov[name])
            if removed:
                yield "breaking", path, f"values removed: {sorted(removed)}"
            if added:
                yield "compatible", path, f"values added: {sorted(added)}"

    for key in sorted((set(old) | set(new)) - known_root):
        if old.get(key) != new.get(key):
            yield "manual", f"/{key}", "unknown root contract change"
    if old.get("compatibility_policy") != new.get("compatibility_policy"):
        yield "manual", "/compatibility_policy", "compatibility policy changed"


def required(findings: list[tuple[str, str, str]]) -> str:
    return max((item[0] for item in findings), key=RANK.get, default="same")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("--declared", choices=RANK, default="same")
    args = parser.parse_args(argv)
    try:
        old = json.loads(Path(args.old).read_text(encoding="utf-8"))
        new = json.loads(Path(args.new).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    findings = list(compare(old, new))
    for level, path, message in findings:
        print(f"{level.upper():10s} {path}: {message}")
    need = required(findings)
    print(f"required: {need}; declared: {args.declared}")
    if need == "manual":
        return 1
    return 0 if RANK[args.declared] >= RANK[need] else 1


if __name__ == "__main__":
    raise SystemExit(main())
