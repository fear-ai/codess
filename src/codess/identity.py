"""Deterministic, namespace-qualified identities for cross-store use."""

from __future__ import annotations

import os
from pathlib import Path

from codess.hashing import codess_digest

IDENTITY_FORMAT = "codess.id/1"


def _qualified(kind: str, *components: object) -> str:
    digest = codess_digest()
    digest.update(IDENTITY_FORMAT.encode("ascii"))
    digest.update(b"\0")
    digest.update(kind.encode("ascii"))
    for component in components:
        digest.update(b"\0")
        digest.update(str(component).encode("utf-8"))
    return f"codess:{kind}:sha256:{digest.hexdigest()}"


def global_session_id(source_system_id: str, vendor_session_id: str) -> str:
    """Identify one vendor session independently of a DB or local path."""
    if not source_system_id or not vendor_session_id:
        raise ValueError("global session identity requires source system and vendor ID")
    return _qualified("session", source_system_id, vendor_session_id)


def global_event_id(session_id: str, vendor_event_id: str) -> str:
    """Identify one event within a globally qualified session."""
    if not session_id or not vendor_event_id:
        raise ValueError("global event identity requires session and event IDs")
    return _qualified("event", session_id, vendor_event_id)


def global_source_revision_id(
    source_system_id: str, source_uri: str, source_revision: str
) -> str:
    """Identify one immutable observation of an upstream source."""
    return _qualified("source-revision", source_system_id, source_uri, source_revision)


def global_source_record_id(source_revision_id: str, source_locator: str) -> str:
    """Identify one record position within an observed source revision."""
    return _qualified("source-record", source_revision_id, source_locator)


def source_observation_id(
    global_entity_id: str,
    source_system_id: str,
    source_uri: str,
    source_revision: str,
    project_id: str | None = None,
) -> str:
    """Identify one extraction observation of a logical entity."""
    return _qualified(
        "observation", global_entity_id, source_system_id, source_uri,
        source_revision, project_id or "",
    )


def location_id(machine_id: str, path: Path | str) -> str:
    """Identify a machine-local observed location, never a logical project."""
    normalized = os.path.normcase(os.path.realpath(os.path.expanduser(str(path))))
    return _qualified("location", machine_id, normalized)


def artifact_uri_id(uri: str) -> str:
    """Identify an artifact locator consistently across project databases."""
    if not uri:
        raise ValueError("artifact identity requires a URI")
    return _qualified("artifact", uri)
