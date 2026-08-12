"""Mutable human-readable aliases for stable Sessions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from codess.fileio import open_readonly, write_json_atomic
from codess.identity import global_session_id
from codess.project_catalog import resolve_project_query_scopes
from codess.snapshot import snapshot_store_paths_from_base


SESSION_NAMES_FORMAT = "codess.session-names/1"


def _path(registry: Path) -> Path:
    return registry.expanduser().resolve() / "session-names.json"


def load_session_names(registry: Path) -> dict[str, Any]:
    path = _path(registry)
    if not path.exists():
        return {"format": SESSION_NAMES_FORMAT, "names": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("format") != SESSION_NAMES_FORMAT:
        raise ValueError("unsupported Session-name registry format")
    if not isinstance(value.get("names"), list):
        raise ValueError("Session-name registry names must be a list")
    seen_names: set[tuple[str, str]] = set()
    seen_sessions: set[tuple[str, str]] = set()
    required = {"project_id", "global_session_id", "name", "source"}
    for item in value["names"]:
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError(
                "each Session-name mapping must contain exactly project_id, "
                "global_session_id, name, and source"
            )
        project_id = str(item["project_id"])
        session_id = str(item["global_session_id"])
        name = _validated_name(str(item["name"]))
        if not project_id.startswith("codess:project:"):
            raise ValueError("Session-name project_id is not a Codess Project ID")
        if not session_id.startswith("codess:session:"):
            raise ValueError(
                "Session-name global_session_id is not a Codess Session ID"
            )
        if item["source"] != "user_alias":
            raise ValueError("Session-name source must be 'user_alias'")
        name_key = (project_id, name.casefold())
        session_key = (project_id, session_id)
        if name_key in seen_names or session_key in seen_sessions:
            raise ValueError("duplicate Session-name mapping")
        seen_names.add(name_key)
        seen_sessions.add(session_key)
    return value


def alias_index(registry: Path) -> dict[tuple[str, str], str]:
    value = load_session_names(registry)
    return {
        (
            str(item["project_id"]),
            str(item["global_session_id"]),
        ): str(item["name"])
        for item in value["names"]
        if (
            isinstance(item, dict)
            and item.get("project_id")
            and item.get("global_session_id")
            and item.get("name")
        )
    }


def _validated_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise ValueError("Session name must not be empty")
    if len(value) > 80:
        raise ValueError("Session name must be at most 80 characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("Session name must not contain control characters")
    return value


def resolve_session_id(
    registry: Path,
    project_id: str,
    identifier: str,
) -> str:
    """Resolve an exact ID or unambiguous ID prefix in the current snapshot."""
    selection = resolve_project_query_scopes(registry, [project_id])[0]
    paths = snapshot_store_paths_from_base(
        Path(selection["snapshot_base"]),
        selection["snapshot_id"],
        allow_package_mismatch=True,
    )
    matches: set[str] = set()
    for path in paths:
        conn = open_readonly(path)
        conn.row_factory = sqlite3.Row
        try:
            for row in conn.execute(
                "SELECT id, global_id, source_system_id, vendor_session_id "
                "FROM sessions"
            ):
                stable = row["global_id"] or global_session_id(
                    row["source_system_id"], row["vendor_session_id"] or row["id"]
                )
                candidates = (stable, str(row["id"]), str(row["vendor_session_id"]))
                if identifier in candidates or any(
                    candidate.startswith(identifier) for candidate in candidates
                ):
                    matches.add(str(stable))
        finally:
            conn.close()
    if not matches:
        raise ValueError(
            f"no current Session in {project_id} matches {identifier!r}"
        )
    if len(matches) > 1:
        raise ValueError(
            f"Session identifier {identifier!r} is ambiguous in {project_id}"
        )
    return matches.pop()


def set_session_name(
    registry: Path,
    project_id: str,
    session_identifier: str,
    name: str,
) -> dict[str, str]:
    value = load_session_names(registry)
    stable_id = resolve_session_id(registry, project_id, session_identifier)
    alias = _validated_name(name)
    for item in value["names"]:
        if (
            isinstance(item, dict)
            and item.get("project_id") == project_id
            and str(item.get("name", "")).casefold() == alias.casefold()
            and item.get("global_session_id") != stable_id
        ):
            raise ValueError(
                f"Session name {alias!r} is already used in {project_id}"
            )
    retained = [
        item for item in value["names"]
        if not (
            isinstance(item, dict)
            and item.get("project_id") == project_id
            and item.get("global_session_id") == stable_id
        )
    ]
    entry = {
        "project_id": project_id,
        "name": alias,
        "global_session_id": stable_id,
        "source": "user_alias",
    }
    value["names"] = sorted(
        [*retained, entry],
        key=lambda item: (item["project_id"], item["name"].casefold()),
    )
    write_json_atomic(_path(registry), value)
    return entry


def remove_session_name(
    registry: Path,
    project_id: str,
    session_identifier: str,
) -> dict[str, str]:
    value = load_session_names(registry)
    stable_id = resolve_session_id(registry, project_id, session_identifier)
    before = len(value["names"])
    value["names"] = [
        item for item in value["names"]
        if not (
            isinstance(item, dict)
            and item.get("project_id") == project_id
            and item.get("global_session_id") == stable_id
        )
    ]
    if len(value["names"]) == before:
        raise ValueError(f"Session {stable_id} has no human-readable name")
    write_json_atomic(_path(registry), value)
    return {"project_id": project_id, "global_session_id": stable_id}
