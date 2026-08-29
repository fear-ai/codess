"""Deterministic, namespace-qualified identities for cross-store use."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from codess.hashing import codess_hash

IDENTITY_FORMAT = "codess.id/1"

IDENTITY_FORMAT_TAG = "id1"
"""The derivation scheme, as it appears in every emitted identity.

The format is an input to the digest, so two schemes cannot collide -- but a
digest alone cannot say which scheme produced it, and identities are compared
across stores rather than within one. The tag therefore travels in the value:
a reader holding `codess:session:id1:...` knows how it was derived, and a
store written under a later scheme is distinguishable rather than merely
different.
"""


def _qualified(kind: str, *components: object) -> str:
    """Derive one namespace-qualified identity.

    Composition is `codess_hash`'s component mode rather than a hand-rolled
    digest: it already prefixes a format tag and separates components with a
    NUL, which is exactly what this function needs and what it previously
    duplicated. The emitted value names the derivation scheme,
    not the algorithm -- a reader recomputes through `hashing`, which owns
    that choice, so naming it here would fix a wire format to an
    implementation detail (13.4.8).
    """
    digest = codess_hash(256, 256, [IDENTITY_FORMAT, kind, *components])
    return f"codess:{kind}:{IDENTITY_FORMAT_TAG}:{digest}"


def session_entity_id(source_system_key: str, vendor_session_id: str) -> str:
    """Identify one vendor session independently of a DB or local path."""
    if not source_system_key or not vendor_session_id:
        raise ValueError("session entity identity requires source system and vendor ID")
    return _qualified("session", source_system_key, vendor_session_id)


def event_entity_id(session_id: str, vendor_event_id: str) -> str:
    """Identify one event within a globally qualified session."""
    if not session_id or not vendor_event_id:
        raise ValueError("event entity identity requires session and event IDs")
    return _qualified("event", session_id, vendor_event_id)


def source_key(source_path: str) -> str:
    """The portable part of a Source location: its name within vendor storage.

    Vendor stores are machine-rooted -- `/Users/me/.claude/projects/...` on one
    machine, `/home/you/.claude/projects/...` on another -- so an absolute path
    cannot appear in a portable identity. The trailing two segments are what
    the vendor itself assigns (a Project slug or session directory, then the
    transcript file), and they are stable across machines.

    The name is retained rather than dropped because two Sources can hold
    byte-identical content: a Claude subagent transcript and its parent can
    share a fingerprint, and they are two Sources, not one.
    """
    parts = [part for part in PurePosixPath(str(source_path)).parts if part != "/"]
    return "/".join(parts[-2:]) if parts else ""


def source_revision_entity_id(
    source_system_key: str, source_path: str, source_revision: str
) -> str:
    """Identify one immutable state of an upstream Source.

    Derived from the source system, the vendor-assigned name within its store,
    and the revision fingerprint -- never the absolute local path. `entity_id`
    means "the same thing observed anywhere derives the same value", and an
    absolute path breaks that: the same transcript read on two machines
    produced two identities, so deduplication across stores failed silently
    for every Source row.

    The revision alone is insufficient, because it is a content fingerprint and
    two distinct Sources can share one; the vendor-assigned name is what
    separates them.
    """
    if not source_system_key or not source_revision:
        raise ValueError("source revision identity requires source system and revision")
    return _qualified(
        "source-revision", source_system_key, source_key(source_path), source_revision
    )


def source_record_entity_id(source_revision_id: str, source_locator: str) -> str:
    """Identify one record position within an observed source revision."""
    return _qualified("source-record", source_revision_id, source_locator)


def source_observation_id(
    observed_entity_id: str,
    source_system_key: str,
    source_path: str,
    source_revision: str,
    project_id: str | None = None,
) -> str:
    """Identify one extraction observation of a logical entity.

    `observed_entity_id` is the `entity_id` of whatever was observed -- a Session, an
    Event -- so the observation is named for the entity plus where and when it was
    read. Qualified because a bare `entity_id` here would read as this function's own
    return value rather than its input.

    Unlike `source_revision_entity_id`, this one takes the path deliberately: an
    observation is the act of reading a Source at a location, so two machines
    reading the same Source made two observations and should derive two
    identities. The entity they observed is shared; the observation is not.
    """
    return _qualified(
        "observation", observed_entity_id, source_system_key, source_path,
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


def workspace_binding_id(
    project_id: str, source_system_key: str, workspace_id: str
) -> str:
    """Identify one workspace binding of a Project."""
    return _qualified("workspace", project_id, source_system_key, workspace_id)


def processing_run_id(
    project_id: str | None, policy_digest: str, actions_digest: str
) -> str:
    """Identify one content-processing run by what it applied.

    `actions_digest` is a canonical digest of the applied actions, computed by
    the caller through `hashing`, so this module composes identities and does
    not also decide how a structure is serialized.
    """
    return _qualified("processing", project_id or "", policy_digest, actions_digest)


def content_object_id(content_digest: str) -> str:
    """Name a stored content object by the digest of its bytes.

    The digest is computed by the caller, which already holds the content, so
    this only applies the shared qualifier rather than re-deriving it.
    """
    return f"codess:content:{IDENTITY_FORMAT_TAG}:{content_digest}"


def observation_row_id(digest: str) -> str:
    """Name one row of a query result, from a digest of its selection."""
    return f"codess:observation:{IDENTITY_FORMAT_TAG}:{digest}"
