"""Read-only verification and semantic validation for CoSchema snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from codess.raw_store import RawStore
from codess.schema_contract import FORMAT_VERSION, require_store, verify_package
from codess.snapshot import SnapshotError, current_store_paths


REPORT_FORMAT = "codess.validation-report/1"
POLICY_FORMAT = "codess.validation-policy/1"
POLICY_FIELDS = {
    "policy_format", "project", "required_sources", "minimum_sessions",
    "minimum_events", "raw_mode", "allowed_diagnostics",
    "cursor_turn_policy", "expected_cursor_workspace_ids",
    "expected_raw_records", "require_fixed_point",
}
REQUIRED_ARTIFACT_INDEXES = {
    "idx_artifacts_identity_path",
    "idx_artifacts_identity_uri",
    "idx_artifacts_identity_repository_object",
    "idx_artifacts_identity_content",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_policy(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load validation policy {path}: {exc}") from exc
    if not isinstance(policy, dict):
        raise ValueError("validation policy must be a JSON object")
    if policy.get("policy_format") != POLICY_FORMAT:
        raise ValueError(f"validation policy must declare {POLICY_FORMAT}")
    unknown = sorted(set(policy) - POLICY_FIELDS)
    if unknown:
        raise ValueError("validation policy has unknown fields: " + ", ".join(unknown))
    if "project" in policy and not isinstance(policy["project"], str):
        raise ValueError("validation policy project must be a string")
    if "required_sources" in policy and not (
        isinstance(policy["required_sources"], list)
        and all(isinstance(value, str) and value for value in policy["required_sources"])
    ):
        raise ValueError("validation policy required_sources must be a string array")
    for field in ("minimum_sessions", "minimum_events"):
        value = policy.get(field, {})
        if not isinstance(value, dict) or not all(
            isinstance(key, str)
            and isinstance(count, int) and not isinstance(count, bool)
            and count >= 0
            for key, count in value.items()
        ):
            raise ValueError(f"validation policy {field} must map sources to nonnegative integers")
    if policy.get("raw_mode") not in {None, "none", "reference", "capture", "seal"}:
        raise ValueError("validation policy raw_mode is invalid")
    diagnostics = policy.get("allowed_diagnostics", {})
    if not isinstance(diagnostics, dict):
        raise ValueError("validation policy allowed_diagnostics must be an object")
    for reason, specification in diagnostics.items():
        valid = (
            isinstance(reason, str)
            and (
                isinstance(specification, int) and not isinstance(specification, bool)
                and specification >= 0
                or isinstance(specification, dict)
                and set(specification) == {"max"}
                and isinstance(specification["max"], int)
                and not isinstance(specification["max"], bool)
                and specification["max"] >= 0
            )
        )
        if not valid:
            raise ValueError(
                "validation policy diagnostic allowances must be nonnegative "
                "integers or objects containing only a nonnegative max"
            )
    cursor_policy = policy.get("cursor_turn_policy")
    if cursor_policy not in {None, "inferred-per-user-interaction"}:
        raise ValueError("validation policy cursor_turn_policy is invalid")
    workspace_ids = policy.get("expected_cursor_workspace_ids")
    if workspace_ids is not None and not (
        isinstance(workspace_ids, list)
        and all(isinstance(value, str) and value for value in workspace_ids)
    ):
        raise ValueError(
            "validation policy expected_cursor_workspace_ids must be a string array"
        )
    raw_records = policy.get("expected_raw_records")
    if raw_records is not None and not (
        isinstance(raw_records, int) and not isinstance(raw_records, bool)
        and raw_records >= 0
    ):
        raise ValueError("validation policy expected_raw_records must be nonnegative")
    if "require_fixed_point" in policy and not isinstance(
        policy["require_fixed_point"], bool
    ):
        raise ValueError("validation policy require_fixed_point must be boolean")
    return policy


def _canonical_rows(conn: sqlite3.Connection) -> Iterable[tuple[str, Iterable[sqlite3.Row]]]:
    """Yield stable logical rows; exclude build timestamps and surrogate keys."""
    queries = {
        "projects": """
            SELECT id, logical_name, root_path, source_cwd, ownership,
                   activity_state, selection_state, metadata
            FROM projects ORDER BY id
        """,
        "sources": """
            SELECT source_system_id, source_uri, storage_format, source_revision,
                   source_mtime, source_size, availability, capture_method,
                   consistency, content_sha256, metadata
            FROM sources ORDER BY source_system_id, source_uri, source_revision
        """,
        "sessions": """
            SELECT id, source_system_id, vendor_session_id, vendor_name,
                   product_name, harness_name, storage_format, surface_kind,
                   session_purpose, harness_version, source_cwd, started_at,
                   ended_at, source_mtime, time_basis, parent_session_id,
                   session_relation_kind, archive_state, archive_source,
                   metadata, source, type, release, project_path
            FROM sessions ORDER BY id
        """,
        "interactions": """
            SELECT id, session_id, sequence_no, initiating_event_id,
                   boundary_source, confidence
            FROM interactions ORDER BY session_id, sequence_no
        """,
        "model_turns": """
            SELECT id, session_id, interaction_id, sequence_no, source_turn_id,
                   boundary_source
            FROM model_turns ORDER BY session_id, sequence_no
        """,
        "events": """
            SELECT session_id, event_id, sequence_no, source_record_locator,
                   source_record_type, source_record_subtype, event_kind,
                   actor_kind, content_role, origin_kind, interaction_id,
                   model_turn_id, parent_event_id, caused_by_event_id, content,
                   content_len, tool_name, tool_input, tool_output, event_at,
                   event_at_basis, source_status, normalized_status,
                   artifact_path, mapping_rule, mapping_trace, metadata,
                   file_path
            FROM events ORDER BY session_id, sequence_no, event_id
        """,
        "tool_invocations": """
            SELECT id, session_id, interaction_id, model_turn_id, source_call_id,
                   source_tool_name, canonical_tool_name, tool_namespace,
                   invocation_kind, input_json, source_status, normalized_status,
                   started_at, ended_at
            FROM tool_invocations ORDER BY id
        """,
        "tool_results": """
            SELECT COALESCE(invocation_id, ''), sequence_no,
                   producing_actor_kind, output_text, output_json, is_error,
                   source_status, normalized_status
            FROM tool_results
            ORDER BY COALESCE(invocation_id, ''), sequence_no, id
        """,
        "artifacts": """
            SELECT project_id, artifact_kind, relative_path,
                   observed_absolute_path, uri, repository_object_id,
                   content_sha256, metadata
            FROM artifacts
            ORDER BY project_id, artifact_kind, relative_path, uri,
                     repository_object_id, content_sha256
        """,
        "event_artifacts": """
            SELECT e.session_id, e.event_id, a.project_id, a.artifact_kind,
                   a.relative_path, a.uri, a.repository_object_id,
                   a.content_sha256, ea.operation, ea.evidence_source,
                   ea.confidence
            FROM event_artifacts ea
            JOIN events e ON e.id=ea.event_id
            JOIN artifacts a ON a.id=ea.artifact_id
            ORDER BY e.session_id, e.event_id, a.artifact_kind,
                     a.relative_path, a.uri, ea.operation
        """,
        "mapping_diagnostics": """
            SELECT d.session_id, e.event_id, d.level, d.reason_code,
                   d.source_field, d.source_value, d.mapping_rule, d.detail
            FROM mapping_diagnostics d
            LEFT JOIN events e ON e.id=d.event_id
            ORDER BY d.session_id, e.event_id, d.level, d.reason_code,
                     d.source_field
        """,
        "correlation_assertions": """
            SELECT subject_kind, subject_id, object_kind, object_id,
                   relation_kind, method, evidence, confidence, reviewer
            FROM correlation_assertions
            ORDER BY subject_kind, subject_id, object_kind, object_id,
                     relation_kind, method
        """,
    }
    for name, query in queries.items():
        yield name, conn.execute(query)


def semantic_digest(store_paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(store_paths, key=lambda item: item.name):
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            require_store(conn, write=False)
            for table, rows in _canonical_rows(conn):
                digest.update(f"{path.name}\0{table}\n".encode("utf-8"))
                for row in rows:
                    digest.update(
                        json.dumps(
                            tuple(row), ensure_ascii=False, separators=(",", ":")
                        ).encode("utf-8")
                    )
                    digest.update(b"\n")
        finally:
            conn.close()
    return digest.hexdigest()


def _add_check(report: dict[str, Any], name: str, passed: bool, detail: Any = None) -> None:
    report["checks"].append({"name": name, "passed": bool(passed), "detail": detail})
    if not passed:
        report["errors"].append(f"{name}: {detail or 'failed'}")


def _validate_store(
    path: Path,
    expected: dict[str, Any],
    report: dict[str, Any],
) -> tuple[dict[str, int], dict[str, int]]:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    counts: dict[str, int] = {}
    diagnostic_counts: dict[str, int] = {}
    prefix = path.name
    try:
        try:
            version = require_store(conn, write=False)
            _add_check(report, f"{prefix}.format", version == FORMAT_VERSION, version)
        except Exception as exc:
            _add_check(report, f"{prefix}.format", False, str(exc))
            return counts, diagnostic_counts
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        _add_check(report, f"{prefix}.integrity", integrity == "ok", integrity)
        fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        _add_check(report, f"{prefix}.foreign_keys", not fk_rows, len(fk_rows))

        tables = (
            "sources", "sessions", "interactions", "model_turns", "events",
            "tool_invocations", "tool_results", "artifacts", "event_artifacts",
            "mapping_diagnostics", "correlation_assertions",
        )
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }
        manifest_counts = expected.get("counts", {})
        _add_check(
            report,
            f"{prefix}.manifest_counts",
            all(counts.get(key) == value for key, value in manifest_counts.items()),
            {"manifest": manifest_counts, "actual": counts},
        )

        sequence_failures = conn.execute(
            """
            SELECT session_id FROM events GROUP BY session_id
            HAVING COUNT(*)>0 AND (
              MIN(sequence_no)!=1 OR MAX(sequence_no)!=COUNT(*) OR
              COUNT(DISTINCT sequence_no)!=COUNT(*) OR
              SUM(sequence_no IS NULL)>0)
            """
        ).fetchall()
        _add_check(
            report, f"{prefix}.event_sequence", not sequence_failures,
            [row[0] for row in sequence_failures[:10]],
        )
        indexes = {row[1] for row in conn.execute("PRAGMA index_list('artifacts')")}
        missing_indexes = sorted(REQUIRED_ARTIFACT_INDEXES - indexes)
        _add_check(
            report, f"{prefix}.artifact_indexes", not missing_indexes,
            missing_indexes,
        )
        duplicates = 0
        for column in ("relative_path", "uri", "repository_object_id", "content_sha256"):
            duplicates += int(
                conn.execute(
                    f"""
                    SELECT COUNT(*) FROM (
                      SELECT project_id, artifact_kind, {column}, COUNT(*) n
                      FROM artifacts WHERE {column} IS NOT NULL
                      GROUP BY project_id, artifact_kind, {column} HAVING n>1
                    )
                    """
                ).fetchone()[0]
            )
        orphan_artifacts = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM artifacts a
                WHERE NOT EXISTS (
                  SELECT 1 FROM event_artifacts ea WHERE ea.artifact_id=a.id
                )
                """
            ).fetchone()[0]
        )
        _add_check(
            report, f"{prefix}.artifact_identity",
            duplicates == 0 and orphan_artifacts == 0,
            {"duplicate_groups": duplicates, "orphan_artifacts": orphan_artifacts},
        )
        invalid_json = 0
        for table, column in (
            ("events", "tool_input"), ("events", "mapping_trace"),
            ("tool_invocations", "input_json"), ("tool_results", "output_json"),
        ):
            invalid_json += int(
                conn.execute(
                    f"SELECT COUNT(*) FROM {table} "
                    f"WHERE {column} IS NOT NULL AND NOT json_valid({column})"
                ).fetchone()[0]
            )
        _add_check(report, f"{prefix}.json_fields", invalid_json == 0, invalid_json)
        diagnostic_counts = {
            row[0]: int(row[1])
            for row in conn.execute(
                "SELECT reason_code, COUNT(*) FROM mapping_diagnostics GROUP BY reason_code"
            )
        }
    except sqlite3.Error as exc:
        _add_check(report, f"{prefix}.sqlite", False, str(exc))
    finally:
        conn.close()
    return counts, diagnostic_counts


def _validate_raw(
    snapshot: Path,
    manifest: dict[str, Any],
    raw_store_root: Path | None,
    report: dict[str, Any],
    *,
    verify_reference_current: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    revisions: list[str] = []
    try:
        lines = (snapshot / "raw-manifest.jsonl").read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
        _add_check(report, "raw.header", header.get("raw_format") == "codess.raw/1", header)
        records = [json.loads(line) for line in lines[1:] if line.strip()]
    except (OSError, IndexError, json.JSONDecodeError) as exc:
        _add_check(report, "raw.manifest", False, str(exc))
        return records, revisions

    raw_store = RawStore(raw_store_root) if raw_store_root is not None else None
    for index, record in enumerate(records):
        revisions.append(
            "\0".join(
                str(record.get(key) or "")
                for key in (
                    "source_system_id", "source_locator", "source_revision_id"
                )
            )
        )
        availability = record.get("availability")
        label = f"raw.record[{index}]"
        if availability == "captured":
            if manifest.get("sealed"):
                object_path = snapshot / "raw" / record["object_relpath"]
            elif raw_store is not None:
                object_path = raw_store.resolve(record)
            else:
                report["limitations"].append(
                    f"{label}: captured object not reverified; supply --raw-store-root"
                )
                continue
            try:
                stored = object_path.read_bytes()
                stored_ok = hashlib.sha256(stored).hexdigest() == record.get("stored_sha256")
                _add_check(report, f"{label}.stored_hash", stored_ok, str(object_path))
                if stored_ok:
                    try:
                        import zstandard

                        raw = zstandard.ZstdDecompressor().decompress(stored)
                        content_ok = (
                            "sha256:" + hashlib.sha256(raw).hexdigest()
                            == record.get("object_id")
                        )
                        _add_check(report, f"{label}.content_hash", content_ok, len(raw))
                    except Exception as exc:
                        _add_check(report, f"{label}.decompress", False, str(exc))
            except (OSError, KeyError) as exc:
                _add_check(report, f"{label}.object", False, str(exc))
        elif availability == "reference":
            report["limitations"].append(
                f"{label}: reference-only source is not independently reproducible"
            )
            locator = record.get("source_locator")
            if locator and verify_reference_current:
                try:
                    stat = Path(locator).stat()
                    matches = (
                        stat.st_mtime_ns == record.get("source_mtime_ns")
                        and stat.st_size == record.get("source_size")
                    )
                    _add_check(report, f"{label}.current_reference", matches, locator)
                except OSError as exc:
                    report["limitations"].append(f"{label}: source unavailable: {exc}")
            elif locator:
                report["limitations"].append(
                    f"{label}: current locator was not compared with the retained revision"
                )
        elif availability in {"not_retained", "unavailable"}:
            report["limitations"].append(f"{label}: raw source {availability}")
        else:
            _add_check(report, f"{label}.availability", False, availability)
    return records, revisions


def _validate_policy(
    project_root: Path,
    policy: dict[str, Any],
    report: dict[str, Any],
    counts_by_source: dict[str, dict[str, int]],
    diagnostics: dict[str, int],
    raw_mode: str | None,
    stores: dict[str, Path],
) -> None:
    configured_project = policy.get("project")
    if configured_project:
        _add_check(
            report, "policy.project",
            Path(configured_project).expanduser().resolve() == project_root,
            configured_project,
        )
    for source in policy.get("required_sources", []):
        actual = counts_by_source.get(source, {}).get("sessions", 0)
        _add_check(report, f"policy.required_source.{source}", actual > 0, actual)
    for source, minimum in policy.get("minimum_sessions", {}).items():
        actual = counts_by_source.get(source, {}).get("sessions", 0)
        _add_check(report, f"policy.minimum_sessions.{source}", actual >= int(minimum), actual)
    for source, minimum in policy.get("minimum_events", {}).items():
        actual = counts_by_source.get(source, {}).get("events", 0)
        _add_check(report, f"policy.minimum_events.{source}", actual >= int(minimum), actual)
    expected_raw = policy.get("raw_mode")
    if expected_raw:
        _add_check(report, "policy.raw_mode", raw_mode == expected_raw, raw_mode)
    if "expected_raw_records" in policy:
        _add_check(
            report, "policy.raw_records",
            report.get("raw_records") == int(policy["expected_raw_records"]),
            report.get("raw_records"),
        )

    expected_workspace_ids = policy.get("expected_cursor_workspace_ids")
    if expected_workspace_ids is not None:
        from codess.project import get_cursor_workspace_ids

        actual_workspace_ids = get_cursor_workspace_ids(project_root)
        _add_check(
            report, "policy.cursor_workspace_ids",
            sorted(expected_workspace_ids) == actual_workspace_ids,
            actual_workspace_ids,
        )

    allowed = policy.get("allowed_diagnostics", {})
    unknown = sorted(set(diagnostics) - set(allowed))
    _add_check(report, "policy.diagnostics.known", not unknown, unknown)
    for reason, count in diagnostics.items():
        specification = allowed.get(reason, {})
        maximum = specification if isinstance(specification, int) else specification.get("max", 0)
        _add_check(
            report, f"policy.diagnostics.{reason}", count <= int(maximum),
            {"actual": count, "maximum": maximum},
        )

    if policy.get("cursor_turn_policy") == "inferred-per-user-interaction":
        cursor_path = stores.get("sessions_cursor.db")
        if cursor_path is None:
            _add_check(report, "policy.cursor_turns", False, "Cursor store missing")
        else:
            conn = sqlite3.connect(cursor_path.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                invalid = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) FROM model_turns mt
                        JOIN sessions s ON s.id=mt.session_id
                        WHERE s.source='Cursor' AND (
                          mt.boundary_source!='inferred' OR mt.interaction_id IS NULL
                          OR mt.source_turn_id IS NOT NULL)
                        """
                    ).fetchone()[0]
                )
                duplicate = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) FROM (
                          SELECT mt.interaction_id, COUNT(*) n
                          FROM model_turns mt JOIN sessions s ON s.id=mt.session_id
                          WHERE s.source='Cursor'
                          GROUP BY mt.interaction_id HAVING n>1
                        )
                        """
                    ).fetchone()[0]
                )
                _add_check(
                    report, "policy.cursor_turns", invalid == 0 and duplicate == 0,
                    {"invalid": invalid, "duplicate_interactions": duplicate},
                )
            finally:
                conn.close()


def validate_project(
    project_root: Path,
    *,
    policy: dict[str, Any] | None = None,
    raw_store_root: Path | None = None,
    verify_reference_current: bool = True,
) -> dict[str, Any]:
    """Validate the current immutable baseline without mutating project state."""
    project_root = project_root.expanduser().resolve()
    policy = policy or {}
    report: dict[str, Any] = {
        "report_format": REPORT_FORMAT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": str(project_root),
        "status": "rejected",
        "errors": [],
        "limitations": [],
        "checks": [],
        "stores": {},
        "counts_by_source": {},
        "diagnostics": {},
    }
    try:
        paths = current_store_paths(project_root)
        if not paths:
            raise SnapshotError("no current snapshot")
        current = json.loads((project_root / ".codess" / "current.json").read_text())
        snapshot = project_root / ".codess" / current["path"]
        manifest = json.loads((snapshot / "manifest.json").read_text())
    except (OSError, KeyError, json.JSONDecodeError, SnapshotError) as exc:
        report["errors"].append(f"snapshot: {exc}")
        return report

    report.update(
        {
            "snapshot_id": manifest.get("snapshot_id"),
            "parent_snapshot_id": manifest.get("parent_snapshot_id"),
            "package_digest": manifest.get("package_digest"),
            "software_version": manifest.get("software_version"),
            "software_revision": manifest.get("software_revision"),
            "raw_mode": manifest.get("build_policy", {}).get("raw_mode"),
        }
    )
    _add_check(
        report, "package_digest",
        manifest.get("package_digest") == verify_package(),
        manifest.get("package_digest"),
    )

    counts_by_source: dict[str, dict[str, int]] = {}
    diagnostics: dict[str, int] = {}
    stores = {path.name: path for path in paths}
    for path in paths:
        counts, diagnostic_counts = _validate_store(
            path, manifest.get("stores", {}).get(path.name, {}), report
        )
        report["stores"][path.name] = counts
        for reason, count in diagnostic_counts.items():
            diagnostics[reason] = diagnostics.get(reason, 0) + count
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            for source, sessions, events in conn.execute(
                """
                SELECT s.source, COUNT(DISTINCT s.id), COUNT(e.id)
                FROM sessions s LEFT JOIN events e ON e.session_id=s.id
                GROUP BY s.source
                """
            ):
                entry = counts_by_source.setdefault(source, {"sessions": 0, "events": 0})
                entry["sessions"] += int(sessions)
                entry["events"] += int(events)
        finally:
            conn.close()
    report["counts_by_source"] = counts_by_source
    report["diagnostics"] = diagnostics

    raw_records, revisions = _validate_raw(
        snapshot, manifest, raw_store_root, report,
        verify_reference_current=verify_reference_current,
    )
    report["raw_records"] = len(raw_records)
    report["source_revisions"] = sorted(revisions)
    report["semantic_digest"] = semantic_digest(paths)
    _validate_policy(
        project_root, policy, report, counts_by_source, diagnostics,
        report.get("raw_mode"), stores,
    )
    if report["errors"]:
        report["status"] = "rejected"
    elif report["limitations"]:
        report["status"] = "accepted_with_limitations"
    else:
        report["status"] = "accepted"
    return report


def run_query_smoke(project_root: Path) -> dict[str, Any]:
    """Exercise version-aware CLI read paths with an isolated temporary registry."""
    repo_root = Path(__file__).resolve().parents[2]
    modes = (
        ("stats", ["--stats"]),
        ("sessions", ["--sessions", "--limit", "1"]),
        ("lineage", ["--lineage", "--limit", "1"]),
        ("audit", ["--audit", "--limit", "1"]),
        ("diagnostics", ["--diagnostics", "--limit", "1"]),
        ("artifacts", ["--artifacts", "--limit", "1"]),
    )
    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="codess-query-smoke-") as registry:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        for name, flags in modes:
            command = [
                sys.executable, "-m", "main", "query", "--dir",
                str(project_root), "--registry", registry, *flags,
            ]
            result = subprocess.run(
                command, cwd=repo_root, env=env, capture_output=True,
                text=True, timeout=120,
            )
            results[name] = {
                "passed": result.returncode == 0,
                "returncode": result.returncode,
                "stderr": result.stderr.strip(),
                "stdout_lines": len(result.stdout.splitlines()),
            }
    return results


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)
