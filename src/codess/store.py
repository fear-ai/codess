"""Versioned CoSchema v4 SQLite store and incremental ingest state."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codess import __version__
from codess.fileio import source_fingerprint
from codess.identity import (
    global_event_id,
    global_session_id,
    global_source_record_id,
    global_source_revision_id,
    source_observation_id,
)
from codess.schema_contract import (
    APPLICATION_ID,
    FORMAT_ID,
    FORMAT_VERSION,
    UnsupportedStoreError,
    has_legacy_schema,
    load_ddl,
    require_store,
    verify_package,
)
from codess.tool_identity import bounded_source_call_id
from codess.mapping import canonical_json, structured_json
from codess.processing_contract import DECODER_VERSION, VALIDATOR_VERSION


SOURCE_PROFILES = {
    "Claude": {
        "source_system_id": "anthropic.claude-code",
        "vendor_name": "anthropic",
        "product_name": "claude-code",
        "harness_name": "claude-code-cli",
        "storage_format": "claude-jsonl",
        "surface_kind": "cli",
        "mapping": "claude",
    },
    "Codex": {
        "source_system_id": "openai.codex",
        "vendor_name": "openai",
        "product_name": "codex",
        "harness_name": "codex-cli",
        "storage_format": "codex-jsonl",
        "surface_kind": "cli",
        "mapping": "codex",
    },
    "Cursor": {
        "source_system_id": "cursor.composer",
        "vendor_name": "cursor",
        "product_name": "cursor-composer",
        "harness_name": "cursor-ide",
        "storage_format": "cursor-sqlite",
        "surface_kind": "ide",
        "mapping": "cursor",
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _profile(source: str | None) -> dict[str, str]:
    return SOURCE_PROFILES.get(
        str(source or ""),
        {
            "source_system_id": "legacy.unknown",
            "vendor_name": "unknown",
            "product_name": str(source or "unknown").lower(),
            "harness_name": "unknown",
            "storage_format": "unknown",
            "surface_kind": "unknown",
            "mapping": "unknown",
        },
    )


def _existing_project_id(
    conn: sqlite3.Connection, path: str | None,
) -> str | None:
    if not path:
        return None
    normalized = os.path.normcase(os.path.realpath(os.path.expanduser(path)))
    for row in conn.execute("SELECT id, root_path FROM projects"):
        root = row["root_path"]
        if root and os.path.normcase(os.path.realpath(os.path.expanduser(root))) == normalized:
            return str(row["id"])
    return None


def _path_is_obsolete(
    conn: sqlite3.Connection, project_id: str | None, path: str | None,
) -> bool:
    """Return whether a vendor path is outside every registered active location."""
    if not project_id or not path or not os.path.isabs(path):
        return False
    roots = [
        row["observed_path"]
        for row in conn.execute(
            """
            SELECT observed_path
            FROM project_locations
            WHERE project_id=? AND state='active' AND path_obsolete=0
            """,
            (project_id,),
        )
        if row["observed_path"]
    ]
    project = conn.execute(
        "SELECT root_path FROM projects WHERE id=?", (project_id,)
    ).fetchone()
    if project is not None and project["root_path"]:
        roots.append(project["root_path"])
    if not roots:
        return False
    source = Path(os.path.realpath(os.path.expanduser(path)))
    for value in roots:
        root = Path(os.path.realpath(os.path.expanduser(value)))
        try:
            source.relative_to(root)
            return False
        except ValueError:
            pass
    return True


def init_db(db_path: Path) -> None:
    """Create a new CoSchema v4 store; refuse mutation of legacy/unknown stores."""
    verify_package()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        has_tables = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1"
        ).fetchone()
        if has_tables:
            if has_legacy_schema(conn):
                raise UnsupportedStoreError(
                    f"{db_path} is a legacy store; preserve it and rebuild CoSchema v4"
                )
            require_store(conn, write=True)
            return
        conn.executescript(load_ddl())
        package_digest = verify_package()
        meta = {
            "format_id": FORMAT_ID,
            "format_version": str(FORMAT_VERSION),
            "application_id": str(APPLICATION_ID),
            "package_digest": package_digest,
            "decoder_version": DECODER_VERSION,
            "validator_version": VALIDATOR_VERSION,
            "created_by": __version__,
            "created_at": _now(),
        }
        conn.executemany(
            "INSERT INTO store_meta(key, value) VALUES (?, ?)", meta.items()
        )
        conn.commit()
        require_store(conn, write=True)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def connect(db_path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open and validate a CoSchema store."""
    if read_only:
        conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        require_store(conn, write=not read_only, allow_legacy_read=read_only)
    except Exception:
        conn.close()
        raise
    return conn


def _ensure_project(conn: sqlite3.Connection, session: dict[str, Any]) -> str | None:
    path = session.get("project_path")
    project_id = (
        session.get("project_id")
        or _existing_project_id(conn, path)
        or f"codess:project:{uuid.uuid4()}"
    )
    if not project_id:
        return None
    conn.execute(
        """
        INSERT INTO projects(id, logical_name, root_path, source_cwd, ownership,
                             activity_state, selection_state, metadata)
        VALUES (?, ?, ?, ?, 'unknown', 'unknown', 'needs_review', NULL)
        ON CONFLICT(id) DO NOTHING
        """,
        (
            project_id,
            Path(path).name if path else None,
            path,
            session.get("source_cwd") or path,
        ),
    )
    return project_id


def sync_project_catalog(
    conn: sqlite3.Connection,
    project: dict[str, Any],
) -> bool:
    """Project catalog identity and bindings projected into one vendor store.

    Return whether any row changed.  Null-safe conflict predicates avoid
    rewriting identical catalog projections on every incremental ingest.
    """
    changes_before = conn.total_changes
    project_id = project["project_id"]
    active = next(
        (item for item in project.get("locations", []) if item.get("state") == "active"),
        None,
    )
    path_observations = [
        {
            "path": item.get("path"),
            "path_obsolete": bool(item.get("path_obsolete")),
            "source": "project_location",
        }
        for item in project.get("locations", [])
        if item.get("path")
    ]
    path_observations.extend(
        {
            "path": item.get("source_project_path"),
            "path_obsolete": bool(item.get("path_obsolete")),
            "source": item.get("source_system_id"),
        }
        for item in project.get("workspace_bindings", [])
        if item.get("source_project_path")
    )
    conn.execute(
        """
        INSERT INTO projects(id, logical_name, root_path, source_cwd, ownership,
                             activity_state, selection_state, metadata)
        VALUES (?, ?, ?, ?, 'unknown', 'active', 'priority', ?)
        ON CONFLICT(id) DO UPDATE SET
          logical_name=excluded.logical_name,
          root_path=excluded.root_path,
          source_cwd=excluded.source_cwd,
          activity_state=excluded.activity_state,
          metadata=excluded.metadata
        WHERE projects.logical_name IS NOT excluded.logical_name
           OR projects.root_path IS NOT excluded.root_path
           OR projects.source_cwd IS NOT excluded.source_cwd
           OR projects.activity_state IS NOT excluded.activity_state
           OR projects.metadata IS NOT excluded.metadata
        """,
        (
            project_id, project.get("logical_name"),
            active.get("path") if active else None,
            active.get("path") if active else None,
            json.dumps(
                {
                    "path_aliases": project.get("path_aliases", []),
                    "path_observations": path_observations,
                },
                separators=(",", ":"),
            ),
        ),
    )
    for location in project.get("locations", []):
        conn.execute(
            """
            INSERT INTO project_locations(
              id, project_id, machine_id, observed_path, path_obsolete,
              location_kind, state, observed_at, metadata)
            VALUES (?, ?, ?, ?, ?, 'directory', ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET state=excluded.state,
              path_obsolete=excluded.path_obsolete,
              metadata=excluded.metadata
            WHERE project_locations.state IS NOT excluded.state
               OR project_locations.path_obsolete IS NOT excluded.path_obsolete
               OR project_locations.metadata IS NOT excluded.metadata
            """,
            (
                location["location_id"], project_id, location["machine_id"],
                location["path"], int(bool(location.get("path_obsolete"))),
                location.get("state", "unknown"),
                location.get("observed_at") or _now(),
                json.dumps({"platform": location.get("platform")}, separators=(",", ":")),
            ),
        )
    for workspace in project.get("workspace_bindings", []):
        workspace_key = "\0".join((
            project_id, workspace["source_system_id"], workspace["workspace_id"]
        ))
        binding_id = "codess:workspace:sha256:" + hashlib.sha256(
            workspace_key.encode("utf-8")
        ).hexdigest()
        conn.execute(
            """
            INSERT INTO workspace_bindings(
              id, project_id, location_id, source_system_id, workspace_id,
              relation_kind, source_project_path, path_obsolete,
              selection_state, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(id) DO UPDATE SET
              location_id=excluded.location_id,
              source_project_path=excluded.source_project_path,
              path_obsolete=excluded.path_obsolete,
              selection_state=excluded.selection_state
            WHERE workspace_bindings.location_id IS NOT excluded.location_id
               OR workspace_bindings.source_project_path
                  IS NOT excluded.source_project_path
               OR workspace_bindings.path_obsolete IS NOT excluded.path_obsolete
               OR workspace_bindings.selection_state
                  IS NOT excluded.selection_state
            """,
            (
                binding_id, project_id, workspace.get("target_location_id"),
                workspace["source_system_id"], workspace["workspace_id"],
                workspace.get("relation_kind") or "workspace_binding",
                workspace.get("source_project_path"),
                int(bool(workspace.get("path_obsolete"))),
                workspace.get("selection_state") or "approved",
            ),
        )
    return conn.total_changes != changes_before


def _source_revision(
    path: Path,
) -> tuple[str, float | None, int | None, str, str]:
    return source_fingerprint(path)


def ensure_source(
    conn: sqlite3.Connection,
    *,
    source: str,
    source_file: str | None,
    availability: str = "reference",
    observation: dict[str, Any] | None = None,
) -> int | None:
    """Create/locate one observed Source revision for a transcript/database."""
    if not source_file:
        return None
    profile = _profile(source)
    if observation is None:
        path = Path(source_file)
        revision, mtime, size, capture_method, consistency = _source_revision(path)
    else:
        revision = str(
            observation.get("source_revision")
            or observation.get("source_revision_id")
            or ""
        )
        if not revision:
            raise ValueError("source observation lacks a revision identity")
        mtime_ns = observation.get("source_mtime_ns")
        mtime = (
            float(mtime_ns) / 1_000_000
            if isinstance(mtime_ns, int) else observation.get("source_mtime")
        )
        size = observation.get("source_size")
        capture_method = str(observation.get("capture_method") or "observed")
        consistency = str(observation.get("consistency") or "observed")
        availability = str(observation.get("availability") or availability)
    global_id = global_source_revision_id(
        profile["source_system_id"], source_file, revision
    )
    now = _now()
    conn.execute(
        """
        INSERT INTO sources(
          global_id, source_system_id, source_uri, storage_format, source_revision,
          source_mtime, source_size, observed_at, ingested_at, availability,
          capture_method, consistency)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_system_id, source_uri, source_revision) DO UPDATE SET
          observed_at=excluded.observed_at,
          ingested_at=excluded.ingested_at,
          availability=excluded.availability
        """,
        (
            global_id,
            profile["source_system_id"],
            source_file,
            profile["storage_format"],
            revision,
            mtime,
            size,
            now,
            now,
            availability,
            capture_method,
            consistency,
        ),
    )
    row = conn.execute(
        """
        SELECT id FROM sources
        WHERE source_system_id=? AND source_uri=? AND source_revision=?
        """,
        (profile["source_system_id"], source_file, revision),
    ).fetchone()
    return int(row[0])


def _ensure_model_configuration(
    conn: sqlite3.Connection, metadata: dict[str, Any]
) -> int | None:
    exact = metadata.get("model") or metadata.get("model_name")
    provider = metadata.get("model_provider")
    family = metadata.get("model_family")
    effort = metadata.get("reasoning_effort") or metadata.get("effort")
    speed = metadata.get("speed") or metadata.get("speed_tier")
    service = metadata.get("service_tier")
    mode = metadata.get("mode")
    if not any((exact, provider, family, effort, speed, service, mode)):
        return None
    existing = conn.execute(
        """
        SELECT id FROM model_configurations
        WHERE provider IS ? AND model_name_exact IS ? AND model_revision IS ?
          AND model_family IS ?
          AND reasoning_effort IS ? AND speed_tier IS ? AND service_tier IS ?
          AND mode IS ?
        ORDER BY id LIMIT 1
        """,
        (
            provider, exact, metadata.get("model_revision"), family,
            effort, speed, service, mode,
        ),
    ).fetchone()
    if existing is not None:
        return int(existing[0])
    conn.execute(
        """
        INSERT OR IGNORE INTO model_configurations(
          provider, model_family, model_name_exact, model_revision,
          reasoning_effort, speed_tier, service_tier, mode, source_config)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            provider,
            family,
            exact,
            metadata.get("model_revision"),
            effort,
            speed,
            service,
            mode,
            canonical_json(metadata) if metadata else None,
        ),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def upsert_session(conn: sqlite3.Connection, session: dict[str, Any]) -> None:
    """Upsert a common session while retaining the legacy query projection."""
    source = str(session.get("source") or "Unknown")
    profile = _profile(source)
    raw_metadata = session.get("metadata")
    metadata = _json_dict(raw_metadata)
    stored_metadata = (
        canonical_json(raw_metadata)
        if isinstance(raw_metadata, dict)
        else raw_metadata
    )
    project_id = _ensure_project(conn, session)
    model_config_id = _ensure_model_configuration(conn, metadata)
    parent = session.get("parent_session_id") or metadata.get("parent_session_id")
    relation = session.get("session_relation_kind")
    if relation is None and (
        metadata.get("is_sidechain") or metadata.get("is_subagent")
    ):
        relation = "subagent"
    archive_state = session.get("archive_state")
    archive_source = session.get("archive_source")
    if archive_state is None and metadata.get("is_archived") is not None:
        archive_state = "archived" if metadata.get("is_archived") else "active"
        archive_source = "vendor"
    started_at = session.get("started_at")
    time_basis = session.get("time_basis") or ("event" if started_at is not None else "unknown")
    now = _now()
    source_system_id = session.get("source_system_id") or profile["source_system_id"]
    vendor_session_id = session.get("vendor_session_id") or session.get("id")
    session_global_id = global_session_id(source_system_id, vendor_session_id)
    source_row = conn.execute(
        "SELECT global_id, source_uri, source_revision FROM sources WHERE id IS ?",
        (session.get("source_id"),),
    ).fetchone()
    observation_id = source_observation_id(
        session_global_id,
        source_system_id,
        source_row["source_uri"] if source_row else "unobserved",
        source_row["source_revision"] if source_row else "unobserved",
        project_id,
    )
    source_cwd = session.get("source_cwd") or session.get("project_path")
    path_obsolete = session.get("path_obsolete")
    if path_obsolete is None:
        path_obsolete = _path_is_obsolete(conn, project_id, source_cwd)
    values = (
        session.get("id"),
        session_global_id,
        observation_id,
        source_system_id,
        vendor_session_id,
        session.get("vendor_name") or profile["vendor_name"],
        session.get("product_name") or profile["product_name"],
        session.get("harness_name") or profile["harness_name"],
        session.get("storage_format") or profile["storage_format"],
        session.get("surface_kind") or profile["surface_kind"],
        session.get("session_purpose") or "coding",
        session.get("harness_version") or session.get("release"),
        session.get("source_id"),
        project_id,
        source_cwd,
        int(bool(path_obsolete)),
        started_at,
        session.get("ended_at"),
        session.get("source_mtime"),
        session.get("observed_at") or now,
        session.get("ingested_at") or now,
        time_basis,
        parent,
        relation,
        archive_state or "unknown",
        archive_source,
        model_config_id,
        stored_metadata,
        source,
        session.get("type", "Code"),
        session.get("release"),
        session.get("project_path"),
    )
    conn.execute(
        """
        INSERT INTO sessions(
          id, global_id, observation_id, source_system_id, vendor_session_id, vendor_name, product_name,
          harness_name, storage_format, surface_kind, session_purpose,
          harness_version, source_id, project_id, source_cwd, path_obsolete,
          started_at, ended_at, source_mtime, observed_at, ingested_at, time_basis,
          parent_session_id, session_relation_kind, archive_state, archive_source,
          default_model_config_id, metadata, source, type, release, project_path)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          global_id=excluded.global_id,
          observation_id=excluded.observation_id,
          source_system_id=excluded.source_system_id,
          vendor_session_id=excluded.vendor_session_id,
          vendor_name=excluded.vendor_name,
          product_name=excluded.product_name,
          harness_name=excluded.harness_name,
          storage_format=excluded.storage_format,
          surface_kind=excluded.surface_kind,
          session_purpose=excluded.session_purpose,
          harness_version=excluded.harness_version,
          source_id=COALESCE(excluded.source_id, sessions.source_id),
          project_id=COALESCE(excluded.project_id, sessions.project_id),
          source_cwd=excluded.source_cwd,
          path_obsolete=excluded.path_obsolete,
          started_at=excluded.started_at,
          ended_at=excluded.ended_at,
          source_mtime=excluded.source_mtime,
          observed_at=excluded.observed_at,
          ingested_at=excluded.ingested_at,
          time_basis=excluded.time_basis,
          parent_session_id=excluded.parent_session_id,
          session_relation_kind=excluded.session_relation_kind,
          archive_state=excluded.archive_state,
          archive_source=excluded.archive_source,
          default_model_config_id=excluded.default_model_config_id,
          metadata=excluded.metadata,
          source=excluded.source,
          type=excluded.type,
          release=excluded.release,
          project_path=excluded.project_path
        """,
        values,
    )


def _event_semantics(event: dict[str, Any]) -> dict[str, str | None]:
    etype, subtype, role = event.get("event_type"), event.get("subtype"), event.get("role")
    if etype != "tool_call" and subtype in {
        "tool_result", "tool_failure", "permission_denied"
    }:
        return {"event_kind": "tool.result", "actor_kind": "tool", "content_role": "tool_result", "origin_kind": "tool_generated"}
    if etype == "tool_call":
        return {"event_kind": "tool.call", "actor_kind": "model", "content_role": "tool_request", "origin_kind": "model_generated"}
    if subtype in {"context_compaction", "context_compaction_summary"}:
        return {"event_kind": "context.compact", "actor_kind": "harness", "content_role": "context", "origin_kind": "harness_injected"}
    if subtype == "context_injection":
        return {"event_kind": "context.inject", "actor_kind": "harness", "content_role": "context", "origin_kind": "harness_injected"}
    if subtype == "turn_aborted":
        return {"event_kind": "lifecycle.abort", "actor_kind": "harness", "content_role": "status", "origin_kind": "harness_injected"}
    if etype == "user_message":
        return {"event_kind": "message.prompt", "actor_kind": "human", "content_role": "prompt", "origin_kind": "direct_user_input"}
    if etype == "assistant_message":
        return {"event_kind": "message.response", "actor_kind": "model", "content_role": "response", "origin_kind": "model_generated"}
    if role == "system":
        return {"event_kind": "message.context", "actor_kind": "harness", "content_role": "context", "origin_kind": "harness_injected"}
    return {"event_kind": "unknown", "actor_kind": "unknown", "content_role": "status", "origin_kind": "unknown"}


def _resolved_event_semantics(event: dict[str, Any]) -> dict[str, str | None]:
    """Prefer explicit adapter mappings, filling only absent common dimensions."""
    inferred = _event_semantics(event)
    return {
        key: event.get(key) or inferred[key]
        for key in ("event_kind", "actor_kind", "content_role", "origin_kind")
    }


def _normalized_status(event: dict[str, Any], metadata: dict[str, Any]) -> tuple[str | None, str | None]:
    source_status = event.get("source_status") or metadata.get("status")
    value = str(source_status or "").lower()
    if event.get("subtype") == "permission_denied":
        return source_status, "denied"
    if event.get("subtype") == "turn_aborted":
        return source_status, "cancelled"
    if event.get("subtype") == "tool_failure" or value in {"failed", "failure", "error"}:
        return source_status, "failed"
    if value == "incomplete":
        return source_status, "incomplete"
    if value in {"completed", "complete", "success", "succeeded"}:
        return source_status, "succeeded"
    return source_status, event.get("normalized_status")


def upsert_event(conn: sqlite3.Connection, event: dict[str, Any]) -> int:
    """Upsert one event with common semantics and return its surrogate id."""
    session = conn.execute(
        "SELECT source, source_system_id, project_id, global_id FROM sessions WHERE id=?",
        (event.get("session_id"),),
    ).fetchone()
    semantics = _resolved_event_semantics(event)
    raw_metadata = event.get("metadata")
    metadata = _json_dict(raw_metadata)
    stored_metadata = (
        canonical_json(raw_metadata)
        if isinstance(raw_metadata, dict)
        else raw_metadata
    )
    source_status, normalized_status = _normalized_status(event, metadata)
    mapping_rule = event.get("mapping_rule")
    mapping_trace = event.get("mapping_trace")
    if mapping_trace is None:
        mapping_trace = canonical_json({
            "mapping_status": "source-provenance-unavailable",
            "normalized_input": {
                "event_type": event.get("event_type"),
                "role": event.get("role"),
                "subtype": event.get("subtype"),
            },
        })
    elif not isinstance(mapping_trace, str):
        mapping_trace = canonical_json(mapping_trace)
    else:
        try:
            json.loads(mapping_trace)
        except json.JSONDecodeError as exc:
            raise ValueError("mapping_trace must be valid JSON") from exc
    tool_input = structured_json(event.get("tool_input"))
    event["tool_input"] = tool_input
    event["mapping_trace"] = mapping_trace
    event_global_id = global_event_id(
        session["global_id"], str(event.get("event_id"))
    )
    values = (
        event_global_id, event.get("session_id"), event.get("source_id"), event.get("event_id"),
        event.get("sequence_no"), event.get("source_record_locator") or event.get("event_id"),
        event.get("source_record_type"),
        event.get("source_record_subtype"),
        event.get("event_kind") or semantics["event_kind"],
        event.get("actor_kind") or semantics["actor_kind"],
        event.get("content_role") or semantics["content_role"],
        event.get("origin_kind") or semantics["origin_kind"],
        event.get("interaction_id"), event.get("model_turn_id"),
        event.get("parent_event_id"), event.get("caused_by_event_id"),
        event.get("content"), event.get("content_len"), event.get("tool_name"),
        tool_input, event.get("tool_output"),
        event.get("event_at", event.get("timestamp")), event.get("event_at_basis") or "vendor",
        source_status, normalized_status, event.get("source_file"),
        event.get("artifact_path") or event.get("file_path"), mapping_rule,
        mapping_trace,
        stored_metadata, event.get("event_type"), event.get("subtype"),
        event.get("role"), event.get("timestamp"), event.get("file_path"),
    )
    conn.execute(
        """
        INSERT INTO events(
          global_id, session_id, source_id, event_id, sequence_no, source_record_locator,
          source_record_type, source_record_subtype, event_kind, actor_kind,
          content_role, origin_kind, interaction_id, model_turn_id,
          parent_event_id, caused_by_event_id, content, content_len, tool_name,
          tool_input, tool_output, event_at, event_at_basis, source_status,
          normalized_status, source_file, artifact_path, mapping_rule,
          mapping_trace, metadata, event_type, subtype, role, timestamp, file_path)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(session_id, event_id) DO UPDATE SET
          global_id=excluded.global_id, source_id=excluded.source_id, sequence_no=excluded.sequence_no,
          source_record_locator=excluded.source_record_locator,
          source_record_type=excluded.source_record_type,
          source_record_subtype=excluded.source_record_subtype,
          event_kind=excluded.event_kind, actor_kind=excluded.actor_kind,
          content_role=excluded.content_role, origin_kind=excluded.origin_kind,
          interaction_id=excluded.interaction_id, model_turn_id=excluded.model_turn_id,
          parent_event_id=excluded.parent_event_id, caused_by_event_id=excluded.caused_by_event_id,
          content=excluded.content, content_len=excluded.content_len,
          tool_name=excluded.tool_name, tool_input=excluded.tool_input,
          tool_output=excluded.tool_output, event_at=excluded.event_at,
          event_at_basis=excluded.event_at_basis, source_status=excluded.source_status,
          normalized_status=excluded.normalized_status, source_file=excluded.source_file,
          artifact_path=excluded.artifact_path, mapping_rule=excluded.mapping_rule,
          mapping_trace=excluded.mapping_trace, metadata=excluded.metadata,
          event_type=excluded.event_type, subtype=excluded.subtype,
          role=excluded.role, timestamp=excluded.timestamp, file_path=excluded.file_path
        """,
        values,
    )
    return int(conn.execute(
        "SELECT id FROM events WHERE session_id=? AND event_id=?",
        (event.get("session_id"), event.get("event_id")),
    ).fetchone()[0])


def _ensure_content_object(
    conn: sqlite3.Connection,
    value: str,
    *,
    storage_class: str = "inline",
    privacy_class: str | None = None,
) -> str:
    encoded = value.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    content_id = f"codess:content:sha256:{digest}"
    conn.execute(
        """
        INSERT INTO content_objects(
          id, content_sha256, media_type, charset, byte_length,
          character_length, storage_class, inline_content, privacy_class)
        VALUES (?, ?, 'text/plain', 'utf-8', ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          byte_length=excluded.byte_length,
          character_length=excluded.character_length,
          inline_content=COALESCE(content_objects.inline_content, excluded.inline_content),
          privacy_class=COALESCE(content_objects.privacy_class, excluded.privacy_class)
        """,
        (
            content_id, digest, len(encoded), len(value), storage_class,
            value if storage_class in {"inline", "derived"} else None,
            privacy_class,
        ),
    )
    return content_id


def _record_source_and_content(
    conn: sqlite3.Connection,
    event: dict[str, Any],
    row_id: int,
) -> None:
    source_id = event.get("source_id")
    locator = str(event.get("source_record_locator") or event.get("event_id"))
    source_record_id = None
    if source_id is not None:
        source = conn.execute(
            "SELECT global_id FROM sources WHERE id=?", (source_id,)
        ).fetchone()
        if source is not None:
            source_record_id = global_source_record_id(source["global_id"], locator)
            conn.execute(
                """
                INSERT INTO source_records(
                  id, source_id, source_locator, source_sequence,
                  source_record_type, source_record_subtype, parent_locator,
                  record_at, classification, parameters_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  source_sequence=excluded.source_sequence,
                  classification=excluded.classification,
                  parameters_json=excluded.parameters_json
                """,
                (
                    source_record_id, source_id, locator, event.get("sequence_no"),
                    event.get("source_record_type"),
                    event.get("source_record_subtype"),
                    event.get("parent_event_id"),
                    event.get("event_at", event.get("timestamp")),
                    event.get("event_kind"), event.get("mapping_trace"),
                ),
            )
    payloads = (
        ("body", event.get("content")),
        ("tool.input", event.get("tool_input")),
        ("tool.output", event.get("tool_output")),
    )
    for relation_kind, value in payloads:
        if value is None:
            continue
        text = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
        content_id = _ensure_content_object(conn, text)
        conn.execute(
            """
            INSERT OR REPLACE INTO event_content(
              event_id, content_id, relation_kind, sequence_no, integrity_state)
            VALUES (?, ?, ?, 1, 'verified')
            """,
            (row_id, content_id, relation_kind),
        )
        if source_record_id is not None:
            conn.execute(
                """
                INSERT OR REPLACE INTO source_record_content(
                  source_record_id, content_id, relation_kind, sequence_no,
                  integrity_state)
                VALUES (?, ?, ?, 1, 'verified')
                """,
                (source_record_id, content_id, relation_kind),
            )


def prune_unreferenced_source_revisions(conn: sqlite3.Connection) -> int:
    """Remove superseded normalized Source revisions and their orphan content.

    Raw manifests retain immutable source history.  A mutable normalized store
    represents its current projection, so a revision no longer referenced by a
    session or event must not leave duplicate source records behind.
    """
    stale = [
        int(row[0]) for row in conn.execute(
            """
            SELECT s.id FROM sources s
            WHERE NOT EXISTS (SELECT 1 FROM sessions x WHERE x.source_id=s.id)
              AND NOT EXISTS (SELECT 1 FROM events e WHERE e.source_id=s.id)
            """
        )
    ]
    if not stale:
        return 0
    placeholders = ",".join("?" for _ in stale)
    conn.execute(
        f"DELETE FROM mapping_diagnostics WHERE source_id IN ({placeholders})",
        stale,
    )
    conn.execute(f"DELETE FROM sources WHERE id IN ({placeholders})", stale)
    conn.execute(
        """
        DELETE FROM content_objects
        WHERE NOT EXISTS (
          SELECT 1 FROM event_content x WHERE x.content_id=content_objects.id
        ) AND NOT EXISTS (
          SELECT 1 FROM source_record_content x WHERE x.content_id=content_objects.id
        ) AND NOT EXISTS (
          SELECT 1 FROM tool_result_content x WHERE x.content_id=content_objects.id
        ) AND NOT EXISTS (
          SELECT 1 FROM artifact_content x WHERE x.content_id=content_objects.id
        )
        """
    )
    return len(stale)


def _link_specialized_content(conn: sqlite3.Connection, row_id: int) -> None:
    """Project event content into typed tool-result and artifact link tables."""
    output = conn.execute(
        """
        SELECT content_id FROM event_content
        WHERE event_id=? AND relation_kind IN ('tool.output','body')
        ORDER BY CASE relation_kind WHEN 'tool.output' THEN 0 ELSE 1 END
        LIMIT 1
        """,
        (row_id,),
    ).fetchone()
    if output is not None:
        for result in conn.execute(
            "SELECT id FROM tool_results WHERE result_event_id=?", (row_id,)
        ):
            conn.execute(
                """
                INSERT OR REPLACE INTO tool_result_content(
                  tool_result_id, content_id, relation_kind, sequence_no,
                  integrity_state)
                VALUES (?, ?, 'output', 1, 'verified')
                """,
                (result[0], output[0]),
            )
    parameters = conn.execute(
        """
        SELECT content_id FROM event_content
        WHERE event_id=? AND relation_kind IN ('tool.input','body')
        ORDER BY CASE relation_kind WHEN 'tool.input' THEN 0 ELSE 1 END
        LIMIT 1
        """,
        (row_id,),
    ).fetchone()
    if parameters is not None:
        for artifact in conn.execute(
            "SELECT artifact_id FROM event_artifacts WHERE event_id=?", (row_id,)
        ):
            conn.execute(
                """
                INSERT OR REPLACE INTO artifact_content(
                  artifact_id, content_id, relation_kind, sequence_no,
                  integrity_state)
                VALUES (?, ?, 'operation.parameters', 1, 'verified')
                """,
                (artifact[0], parameters[0]),
            )


def record_processing_run(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    policy: dict[str, Any],
    actions: list[dict[str, Any]],
) -> str:
    """Persist one scoped content-processing run and its derivation identities."""
    policy_text = json.dumps(policy, sort_keys=True, separators=(",", ":"))
    policy_sha = hashlib.sha256(policy_text.encode("utf-8")).hexdigest()
    now = _now()
    identity_text = json.dumps(
        {"project_id": project_id, "policy_sha256": policy_sha, "actions": actions},
        sort_keys=True, separators=(",", ":"),
    )
    run_id = "codess:processing:sha256:" + hashlib.sha256(
        identity_text.encode("utf-8")
    ).hexdigest()
    rejection = next(
        (str(item.get("reason")) for item in actions if not item.get("accepted", True)),
        None,
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO processing_runs(
          id, project_id, policy_sha256, processor_name, software_version,
          scope_json, actions_json, rejection_reason, started_at, completed_at)
        VALUES (?, ?, ?, 'codess.content_processing', ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id, project_id, policy_sha, __version__,
            json.dumps({"project_id": project_id}, separators=(",", ":")),
            json.dumps(actions, separators=(",", ":")), rejection, now, now,
        ),
    )
    for sequence, action in enumerate(actions, 1):
        input_hash = action.get("input_sha256")
        if not input_hash:
            continue
        input_id = f"codess:content:sha256:{input_hash}"
        conn.execute(
            """
            INSERT OR IGNORE INTO content_objects(
              id, content_sha256, storage_class, character_length, privacy_class)
            VALUES (?, ?, 'not_retained', ?, ?)
            """,
            (input_id, input_hash, action.get("original_length"), "policy_input"),
        )
        output_id = None
        output_hash = action.get("output_sha256")
        if output_hash:
            output_id = f"codess:content:sha256:{output_hash}"
            conn.execute(
                """
                INSERT OR IGNORE INTO content_objects(
                  id, content_sha256, storage_class, character_length, privacy_class)
                VALUES (?, ?, 'not_retained', ?, ?)
                """,
                (output_id, output_hash, action.get("output_length"), "policy_output"),
            )
        conn.execute(
            """
            INSERT OR REPLACE INTO content_derivations(
              processing_run_id, input_content_id, output_content_id,
              sequence_no, actions_json, rejection_reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, input_id, output_id, sequence,
                json.dumps(action.get("actions", []), separators=(",", ":")),
                action.get("reason"),
            ),
        )
    return run_id


def _lineage_id(event: dict[str, Any]) -> str | None:
    metadata = _json_dict(event.get("metadata"))
    value = metadata.get("call_id") or metadata.get("tool_use_id")
    return bounded_source_call_id(value) if value is not None else None


def _record_diagnostic(
    conn: sqlite3.Connection,
    event: dict[str, Any],
    row_id: int,
    *,
    reason_code: str,
    source_field: str | None = None,
    source_value: Any = None,
    detail: str | None = None,
    level: str = "field",
    severity: str = "warn",
) -> None:
    mapping_rule = event.get("mapping_rule")
    if mapping_rule is None:
        row = conn.execute(
            "SELECT mapping_rule FROM events WHERE id=?", (row_id,)
        ).fetchone()
        mapping_rule = row[0] if row else None
    conn.execute(
        """
        INSERT INTO mapping_diagnostics(
          source_id, session_id, event_id, level, severity, reason_code, source_field,
          source_value, mapping_rule, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.get("source_id"), event.get("session_id"), row_id, level,
            severity,
            reason_code, source_field,
            None if source_value is None else str(source_value),
            mapping_rule, detail, _now(),
        ),
    )


def _record_tool(conn: sqlite3.Connection, event: dict[str, Any], row_id: int) -> None:
    subtype = event.get("subtype")
    result_subtypes = {"tool_result", "tool_failure", "permission_denied"}
    is_result = event.get("event_type") != "tool_call" and subtype in result_subtypes
    if event.get("event_type") != "tool_call" and not is_result:
        return
    session_id = str(event["session_id"])
    metadata = _json_dict(event.get("metadata"))
    source_status, normalized_status = _normalized_status(event, metadata)
    call_id = _lineage_id(event)
    if call_id is None:
        _record_diagnostic(
            conn, event, row_id,
            reason_code="missing_tool_call_id",
            source_field="call_id",
            detail="tool invocation/result cannot be correlated by a source identifier",
        )
        if is_result:
            conn.execute(
                """
                INSERT INTO tool_results(
                  invocation_id, result_event_id, sequence_no,
                  producing_actor_kind, output_text, is_error,
                  source_status, normalized_status)
                VALUES (NULL, ?, 1, 'tool', ?, ?, ?, ?)
                """,
                (
                    row_id, event.get("tool_output") or event.get("content"),
                    1 if normalized_status in {"failed", "denied", "incomplete"} else 0,
                    source_status, normalized_status,
                ),
            )
            return
    invocation_id = f"{session_id}:call:{call_id or event['event_id']}"
    conn.execute(
        """
        INSERT INTO tool_invocations(
          id, session_id, interaction_id, model_turn_id, requested_event_id,
          source_call_id, source_tool_name, canonical_tool_name, invocation_kind,
          input_json, source_status, normalized_status, started_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          requested_event_id=COALESCE(excluded.requested_event_id, tool_invocations.requested_event_id),
          source_tool_name=COALESCE(excluded.source_tool_name, tool_invocations.source_tool_name),
          canonical_tool_name=COALESCE(excluded.canonical_tool_name, tool_invocations.canonical_tool_name),
          input_json=COALESCE(excluded.input_json, tool_invocations.input_json),
          source_status=COALESCE(excluded.source_status, tool_invocations.source_status),
          normalized_status=COALESCE(excluded.normalized_status, tool_invocations.normalized_status)
        """,
        (
            invocation_id, session_id, event.get("interaction_id"), event.get("model_turn_id"),
            row_id if event.get("event_type") == "tool_call" else None, call_id,
            event.get("tool_name"), event.get("tool_name"), "harness_capability",
            event.get("tool_input"), source_status, normalized_status,
            event.get("timestamp") if event.get("event_type") == "tool_call" else None,
        ),
    )
    if is_result:
        next_seq = conn.execute(
            "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM tool_results WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT OR REPLACE INTO tool_results(
              invocation_id, result_event_id, sequence_no, producing_actor_kind,
              output_text, is_error, source_status, normalized_status)
            VALUES (?, ?, ?, 'tool', ?, ?, ?, ?)
            """,
            (
                invocation_id, row_id, next_seq, event.get("tool_output") or event.get("content"),
                1 if normalized_status in {"failed", "denied", "incomplete"} else 0,
                source_status, normalized_status,
            ),
        )


def _artifact_path(event: dict[str, Any]) -> str | None:
    if event.get("file_path"):
        return str(event["file_path"])
    raw = event.get("tool_input")
    if not raw:
        return None
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return None
    if isinstance(value, dict):
        path = value.get("path") or value.get("file_path")
        return str(path) if path else None
    return None


def _record_artifact(conn: sqlite3.Connection, event: dict[str, Any], row_id: int) -> None:
    path = _artifact_path(event)
    if not path:
        return
    session = conn.execute(
        "SELECT project_id, project_path FROM sessions WHERE id=?", (event["session_id"],)
    ).fetchone()
    project_id = session["project_id"] if session else None
    project_path = session["project_path"] if session else None
    absolute = os.path.realpath(os.path.expanduser(path)) if os.path.isabs(path) else (
        os.path.realpath(os.path.join(project_path, path)) if project_path else None
    )
    relative = path
    uri = None
    artifact_metadata = None
    if absolute and project_path:
        try:
            relative = os.path.relpath(absolute, project_path)
        except ValueError:
            pass
        if relative == os.pardir or relative.startswith(os.pardir + os.sep):
            uri = Path(absolute).as_uri()
            relative = None
            artifact_metadata = json.dumps(
                {"path_scope": "external", "source_path": path},
                sort_keys=True, separators=(",", ":"),
            )
    elif absolute:
        uri = Path(absolute).as_uri()
        relative = None
        artifact_metadata = json.dumps(
            {"path_scope": "external", "source_path": path},
            sort_keys=True, separators=(",", ":"),
        )
    artifact = conn.execute(
        """
        SELECT id FROM artifacts WHERE project_id IS ? AND artifact_kind='file'
          AND relative_path IS ? AND uri IS ? AND repository_object_id IS NULL
          AND content_sha256 IS NULL
        """,
        (project_id, relative, uri),
    ).fetchone()
    if artifact is None:
        cursor = conn.execute(
            """
            INSERT INTO artifacts(
              project_id, artifact_kind, relative_path, observed_absolute_path,
              uri, metadata)
            VALUES (?, 'file', ?, ?, ?, ?)
            """,
            (project_id, relative, absolute, uri, artifact_metadata),
        )
        artifact_id = int(cursor.lastrowid)
    else:
        artifact_id = int(artifact[0])
    tool = str(event.get("tool_name") or "").lower()
    operation = "read" if tool in {"read", "grep", "glob"} else (
        "modify" if tool in {"edit", "write"} else "mention"
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO event_artifacts(
          event_id, artifact_id, operation, evidence_source, confidence)
        VALUES (?, ?, ?, 'tool_input', 1.0)
        """,
        (row_id, artifact_id, operation),
    )


def _prepare_event_groups(
    conn: sqlite3.Connection,
    session_id: str,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    session_row = conn.execute(
        "SELECT source,default_model_config_id FROM sessions WHERE id=?",
        (session_id,),
    ).fetchone()
    session_source = session_row[0] if session_row else "Unknown"
    interaction_counter = 0
    model_turn_counter = 0
    current_interaction: str | None = None
    current_model_config_id: int | None = (
        session_row["default_model_config_id"] if session_row else None
    )
    current_configuration_provenance: dict[str, Any] | None = None
    current_configuration_anchor: dict[str, Any] | None = None
    turn_by_record: dict[str, str] = {}
    for sequence, original in enumerate(events, 1):
        event = dict(original)
        event["sequence_no"] = sequence
        semantics = _resolved_event_semantics(event)
        is_prompt = (
            semantics["actor_kind"] == "human"
            and event.get("subtype") not in {"tool_result"}
        )
        if is_prompt:
            interaction_counter += 1
            current_interaction = f"{session_id}:interaction:{interaction_counter}"
            conn.execute(
                """
                INSERT INTO interactions(
                  id, session_id, sequence_no, initiating_event_id,
                  initiation_kind, boundary_source, confidence)
                VALUES (?, ?, ?, ?, 'human', 'mapping', 0.8)
                """,
                (current_interaction, session_id, interaction_counter, event.get("event_id")),
            )
            prompt_metadata = _json_dict(event.get("metadata"))
            prompt_model_config_id = _ensure_model_configuration(
                conn, prompt_metadata
            )
            if prompt_model_config_id is not None:
                current_model_config_id = prompt_model_config_id
                prompt_provenance = prompt_metadata.get(
                    "configuration_provenance"
                )
                current_configuration_provenance = (
                    json.loads(canonical_json(prompt_provenance))
                    if isinstance(prompt_provenance, dict)
                    else None
                )
                current_configuration_anchor = {
                    "governing_event_id": event.get("event_id"),
                    "governing_source_record_locator": event.get(
                        "source_record_locator"
                    ),
                }
        if semantics["actor_kind"] == "model":
            event_metadata = _json_dict(event.get("metadata"))
            observed_model_config_id = _ensure_model_configuration(
                conn, event_metadata
            )
            if observed_model_config_id is not None:
                observed_provenance = event_metadata.get(
                    "configuration_provenance"
                )
                if isinstance(observed_provenance, dict):
                    current_configuration_provenance = json.loads(
                        canonical_json(observed_provenance)
                    )
                    current_configuration_anchor = {
                        "governing_event_id": event.get("event_id"),
                        "governing_source_record_locator": event.get(
                            "source_record_locator"
                        ),
                    }
                elif observed_model_config_id != current_model_config_id:
                    current_configuration_provenance = None
                    current_configuration_anchor = None
                current_model_config_id = observed_model_config_id
            if (
                current_model_config_id is not None
                and current_configuration_provenance is not None
                and not isinstance(
                    event_metadata.get("configuration_provenance"), dict
                )
            ):
                event_metadata["configuration_provenance"] = json.loads(
                    canonical_json(current_configuration_provenance)
                )
                event_metadata["configuration_provenance_scope"] = {
                    "state": "inherited",
                    **(current_configuration_anchor or {}),
                }
                event["metadata"] = canonical_json(event_metadata)
            if current_interaction is None:
                # Model activity with no preceding human prompt (e.g. /loop or a
                # scheduled/timer fire). Open an inferred autonomous interaction so
                # the turn is attributed rather than orphaned.
                interaction_counter += 1
                current_interaction = f"{session_id}:interaction:{interaction_counter}"
                conn.execute(
                    """
                    INSERT INTO interactions(
                      id, session_id, sequence_no, initiating_event_id,
                      initiation_kind, boundary_source, confidence)
                    VALUES (?, ?, ?, ?, 'autonomous', 'inferred', 0.5)
                    """,
                    (current_interaction, session_id, interaction_counter,
                     event.get("event_id")),
                )
            if session_source == "Cursor":
                record_key = current_interaction
                boundary_source = "inferred"
            else:
                event_metadata = _json_dict(event.get("metadata"))
                source_turn_id = event_metadata.get("source_turn_id")
                record_key = (
                    str(source_turn_id)
                    if source_turn_id is not None
                    else str(event.get("event_id") or sequence).split(":", 1)[0]
                )
                boundary_source = "vendor" if source_turn_id is not None else "mapping"
            turn_id = turn_by_record.get(record_key)
            if turn_id is None:
                model_turn_counter += 1
                turn_id = f"{session_id}:turn:{model_turn_counter}"
                turn_by_record[record_key] = turn_id
                conn.execute(
                    """
                    INSERT INTO model_turns(
                      id, session_id, interaction_id, sequence_no, source_turn_id,
                      model_config_id, boundary_source)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        turn_id, session_id, current_interaction,
                        model_turn_counter,
                        None if session_source == "Cursor" else record_key,
                        current_model_config_id,
                        boundary_source,
                    ),
                )
            event["model_turn_id"] = turn_id
        event["interaction_id"] = current_interaction
        prepared.append(event)
    return prepared


def replace_session_events(
    conn: sqlite3.Connection,
    session: dict[str, Any] | None,
    events: list[dict[str, Any]],
    *,
    session_id: str,
    prune: bool = True,
) -> None:
    """Replace one transcript-backed session inside the caller's transaction."""
    conn.execute("DELETE FROM events WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM tool_invocations WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM model_turns WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM interactions WHERE session_id=?", (session_id,))
    if session is None:
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        if prune:
            prune_unreferenced_records(conn)
        return
    source_file = next((e.get("source_file") for e in events if e.get("source_file")), None)
    source_id = ensure_source(
        conn, source=str(session.get("source") or "Unknown"),
        source_file=source_file,
        observation=session.get("source_observation"),
    )
    enriched_session = dict(session)
    enriched_session["source_id"] = source_id
    upsert_session(conn, enriched_session)
    for event in _prepare_event_groups(conn, session_id, events):
        event["source_id"] = source_id
        row_id = upsert_event(conn, event)
        _record_source_and_content(conn, event, row_id)
        for diagnostic in event.get("field_diagnostics") or ():
            if not isinstance(diagnostic, dict):
                continue
            _record_diagnostic(
                conn, event, row_id,
                reason_code=str(
                    diagnostic.get("reason_code") or "field_malformed"
                ),
                source_field=diagnostic.get("source_field"),
                source_value=diagnostic.get("source_value"),
                detail=diagnostic.get("detail"),
                level=str(diagnostic.get("diagnostic_level") or "field"),
                severity=str(diagnostic.get("level") or "warn"),
            )
        if _resolved_event_semantics(event)["event_kind"] == "unknown":
            _record_diagnostic(
                conn, event, row_id,
                reason_code="unmapped_event_semantics",
                source_field="event_type/subtype/role",
                source_value="/".join(str(event.get(key) or "") for key in ("event_type", "subtype", "role")),
                detail="source record retained with open common values set to unknown",
            )
        _record_tool(conn, event, row_id)
        _record_artifact(conn, event, row_id)
        _link_specialized_content(conn, row_id)
    if prune:
        prune_unreferenced_records(conn)


def prune_unreferenced_records(conn: sqlite3.Connection) -> None:
    """Prune store-wide orphans once after a replacement batch.

    These statements intentionally cover the whole normalized store. Running
    them after every composer makes a multi-session Cursor replacement roughly
    quadratic in store size, so batch callers defer them until their last row.
    """
    conn.execute(
        "DELETE FROM artifacts WHERE NOT EXISTS "
        "(SELECT 1 FROM event_artifacts WHERE event_artifacts.artifact_id=artifacts.id)"
    )
    conn.execute(
        """
        DELETE FROM model_configurations
        WHERE NOT EXISTS (
          SELECT 1 FROM model_turns WHERE model_turns.model_config_id=model_configurations.id
        ) AND NOT EXISTS (
          SELECT 1 FROM sessions WHERE sessions.default_model_config_id=model_configurations.id
        )
        """
    )
    prune_unreferenced_source_revisions(conn)


def replace_source_sessions(
    conn: sqlite3.Connection,
    source_file: str,
    sessions: dict[str, dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    """Replace events owned by one multi-session source such as a Cursor DB."""
    old_session_ids = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT session_id FROM events WHERE source_file=?", (source_file,)
        )
    }
    grouped: dict[str, list[dict[str, Any]]] = {sid: [] for sid in sessions}
    for event in events:
        grouped.setdefault(str(event["session_id"]), []).append(event)
    for session_id, session in sessions.items():
        replace_session_events(
            conn, session, grouped.get(session_id, []), session_id=session_id,
            prune=False,
        )
    for session_id in old_session_ids - set(sessions):
        conn.execute("DELETE FROM events WHERE session_id=? AND source_file=?", (session_id, source_file))
        remaining = conn.execute(
            "SELECT 1 FROM events WHERE session_id=? LIMIT 1", (session_id,)
        ).fetchone()
        if remaining is None:
            conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    prune_unreferenced_records(conn)


def load_ingest_state(state_path: Path) -> dict[str, Any]:
    """Read ingest_state.json; return {} if missing/invalid."""
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_ingest_state(state_path: Path, state: dict[str, Any]) -> None:
    """Atomically write incremental state."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_name(f".{state_path.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(state, indent=0), encoding="utf-8")
    os.replace(tmp, state_path)


def should_ingest(
    state_path: Path,
    source_file: str,
    mtime: float,
    force: bool,
    *,
    path: Path | None = None,
) -> bool:
    if force:
        return True
    previous = load_ingest_state(state_path).get(source_file)
    if path is None:
        return previous != mtime
    current = ingest_state_marker(path)
    return previous != current


def ingest_state_marker(path: Path) -> dict[str, Any]:
    """Return a dated, versioned marker used to detect source updates."""
    revision, mtime, size, method, consistency = _source_revision(path)
    return {
        "source_revision": revision,
        "source_mtime": mtime,
        "source_size": size,
        "fingerprint_method": method,
        "consistency": consistency,
    }
