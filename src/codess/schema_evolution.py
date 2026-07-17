"""Fail-closed comparison of machine-readable CoSchema contracts."""

from __future__ import annotations

from typing import Any, Iterator


RANK = {"same": 0, "compatible": 1, "breaking": 2, "manual": 3}


def _fields(entity: dict[str, Any]) -> dict[str, Any]:
    return entity.get("fields", {})


def compare(old: dict[str, Any], new: dict[str, Any]) -> Iterator[tuple[str, str, str]]:
    known_root = {
        "format_id", "format_version", "application_id", "compatibility_policy",
        "entities", "vocabularies",
    }
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
        old_entity, new_entity = old_entities[name], new_entities[name]
        if old_entity.get("identity") != new_entity.get("identity"):
            yield "breaking", f"{path}/identity", "identity changed"
        if old_entity.get("order") != new_entity.get("order"):
            yield "breaking", f"{path}/order", "ordering contract changed"
        old_fields, new_fields = _fields(old_entity), _fields(new_entity)
        for field in sorted(set(old_fields) | set(new_fields)):
            field_path = f"{path}/fields/{field}"
            if field not in new_fields:
                yield "breaking", field_path, "field removed"
                continue
            if field not in old_fields:
                level = "compatible" if new_fields[field].get("nullable", True) else "breaking"
                yield level, field_path, "nullable field added" if level == "compatible" else "required field added"
                continue
            old_field, new_field = old_fields[field], new_fields[field]
            if old_field.get("type") != new_field.get("type"):
                yield "breaking", field_path, "field type changed"
            if old_field.get("nullable", True) and not new_field.get("nullable", True):
                yield "breaking", field_path, "field became required"
            elif not old_field.get("nullable", True) and new_field.get("nullable", True):
                yield "compatible", field_path, "field became nullable"
            known = {"type", "nullable", "target", "vocabulary", "minimum", "maximum"}
            for key in ("target", "vocabulary", "minimum", "maximum"):
                if old_field.get(key) != new_field.get(key):
                    yield "manual", f"{field_path}/{key}", f"{key} changed"
            for key in sorted((set(old_field) | set(new_field)) - known):
                if old_field.get(key) != new_field.get(key):
                    yield "manual", f"{field_path}/{key}", "unclassified field contract change"
    old_vocab, new_vocab = old.get("vocabularies", {}), new.get("vocabularies", {})
    for name in sorted(set(old_vocab) | set(new_vocab)):
        path = f"/vocabularies/{name}"
        if name not in new_vocab:
            yield "breaking", path, "vocabulary removed"
        elif name not in old_vocab:
            yield "compatible", path, "vocabulary added"
        else:
            removed = set(old_vocab[name]) - set(new_vocab[name])
            added = set(new_vocab[name]) - set(old_vocab[name])
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
