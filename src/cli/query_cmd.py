"""Read-only, cross-store session query CLI command.
"""

import csv
import json
import logging
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from codess.config import (
    DEFAULT_QUERY_BYTE_LIMIT, get_project_stores, validate_config,
)
from codess.identity import global_session_id
from codess.project import RootsWhenEmpty, resolve_cli_roots, resolve_registry_directory
from codess.project_catalog import resolve_project_query_scopes
from codess.registry_store import merge_query_stats, update_project_entry
from codess.sanitize import (
    protect_csv_row, sanitize_for_display, sanitize_tabular, sanitize_text,
)
from codess.schema_contract import SchemaContractError
from codess.session_names import alias_index
from codess.snapshot import (
    SnapshotError,
    current_store_paths_from_base,
    snapshot_store_paths,
    snapshot_store_paths_from_base,
)
from codess.store import connect as connect_store
from codess.configuration_audit import audit as audit_configurations
from codess.evidence_resolver import resolve_event
from codess.investigation import build_investigation
from codess.query_api import (
    REQUEST_FORMAT, RESULT_FORMAT, QueryContractError,
    compare_results, content_hash, execute as execute_typed_query, load_document,
    make_request, merge_selection, save_document, selection_from_result,
    selected_project_ids, selected_project_snapshots, validate_request,
)
log = logging.getLogger(__name__)

# Standard (built-in) tools for grouping; others are "loaded"
STANDARD_TOOLS = frozenset({
    "Bash", "Read", "Edit", "Write", "Grep", "Glob", "TodoWrite",
    "LS", "AskUserQuestion", "Skill", "Agent", "Task",
    "TaskCreate", "TaskUpdate", "TaskStop", "TaskList", "TaskOutput",
})

QUERY_SOURCE_FILTERS = {
    "cc": ("anthropic.claude-code", "claude"),
    "codex": ("openai.codex", "codex"),
    "cursor": ("cursor.composer", "cursor"),
}


class QueryScope:
    """Read-only stores selected for one logical query."""

    def __init__(self, source_tokens: set[str] | None = None) -> None:
        self.stores: list[dict] = []
        self.source_tokens = source_tokens
        self.session_names: dict[tuple[str, str], str] = {}

    def close(self) -> None:
        for store in self.stores:
            store["conn"].close()


def _open_readable_store(path):
    """Open one store read-only, confirming its core tables are queryable.

    The probe distinguishes a store that exists from one that can actually be
    read, so a caller does not discover a truncated or foreign file midway
    through a query. The connection is closed before the error propagates,
    since a failed open must not leak a handle.
    """
    conn = connect_store(path, read_only=True)
    try:
        conn.execute("SELECT 1 FROM sessions LIMIT 1")
        conn.execute("SELECT 1 FROM events LIMIT 1")
    except Exception:
        conn.close()
        raise
    return conn


def _open_query_scope(
    roots: list[Path],
    *,
    snapshot_id: str | None = None,
    allow_package_mismatch: bool = False,
    source_tokens: set[str] | None = None,
) -> tuple[QueryScope, list[Path]]:
    """Open every existing project store read-only without an attachment limit."""
    scope = QueryScope(source_tokens)
    roots_without_stores = []
    try:
        for root in roots:
            resolved_root = root.resolve()
            stores = (
                snapshot_store_paths(
                    resolved_root, snapshot_id,
                    allow_package_mismatch=allow_package_mismatch,
                )
                if snapshot_id
                else get_project_stores(resolved_root)
            )
            if not stores:
                roots_without_stores.append(resolved_root)
                continue
            for path in stores:
                conn = _open_readable_store(path)
                scope.stores.append(
                    {"conn": conn, "path": path, "project_path": resolved_root}
                )
        return scope, roots_without_stores
    except Exception:
        scope.close()
        raise


def _open_project_id_query_scope(
    project_scopes: list[dict],
    *,
    snapshot_id: str | None = None,
    allow_package_mismatch: bool = False,
    source_tokens: set[str] | None = None,
) -> tuple[QueryScope, list[Path]]:
    """Open central snapshots selected by exact Project identity."""
    scope = QueryScope(source_tokens)
    missing: list[Path] = []
    try:
        for selection in project_scopes:
            base = Path(selection["snapshot_base"])
            selected_snapshot_id = snapshot_id or selection.get("snapshot_id")
            try:
                stores = (
                    snapshot_store_paths_from_base(
                        base,
                        selected_snapshot_id,
                        allow_package_mismatch=allow_package_mismatch,
                    )
                    if selected_snapshot_id
                    else current_store_paths_from_base(base)
                )
            except SnapshotError as exc:
                label = selection.get("logical_name")
                project_label = (
                    f"{label} ({selection['project_id']})"
                    if label
                    else selection["project_id"]
                )
                raise SnapshotError(
                    "Project "
                    f"{project_label} snapshot "
                    f"{selected_snapshot_id or '<current>'} cannot be opened "
                    "under the selected snapshot policy: "
                    f"{exc}"
                ) from exc
            if not stores:
                missing.append(base)
                continue
            for path in stores:
                conn = _open_readable_store(path)
                scope.stores.append({
                    "conn": conn,
                    "path": path,
                    "project_path": Path(selection["project_path"]),
                    "project_id": selection["project_id"],
                    "snapshot_id": selected_snapshot_id,
                    "snapshot_base": base,
                    "selection_kind": selection.get("selection_kind"),
                    "selection_sha256": selection.get("selection_sha256"),
                    "resolved_selection_sha256": selection.get(
                        "resolved_selection_sha256"
                    ),
                })
        return scope, missing
    except Exception:
        scope.close()
        raise


def _source_predicate(scope: QueryScope, alias: str = "s") -> tuple[str, tuple[str, ...]]:
    """Return a compatibility-aware session-source predicate and parameters."""
    if not scope.source_tokens:
        return "1", ()
    clauses = []
    params: list[str] = []
    for token in sorted(scope.source_tokens):
        source_system_id, legacy_label = QUERY_SOURCE_FILTERS[token]
        clauses.append(
            f"({alias}.source_system_id=? OR "
            f"({alias}.source_system_id='legacy.unknown' "
            f"AND lower({alias}.source)=?))"
        )
        params.extend((source_system_id, legacy_label))
    return "(" + " OR ".join(clauses) + ")", tuple(params)


def _timestamp_last_sort_key(
    timestamp: Any, project: str, store_index: int, session_id: str, tail: str,
) -> tuple:
    """Shared row-ordering key: malformed/missing timestamp sorts last.

    `_lineage` and `_audit` build differently-shaped row dicts (their own
    field names for `project` and the trailing tie-break field) but order
    rows identically; this takes the already-extracted values so neither
    caller needs to conform its dict shape to the other's.
    """
    try:
        ordered_time = float(timestamp)
    except (TypeError, ValueError):
        ordered_time = float("inf")
    return (ordered_time, project, store_index, session_id, tail)


def _parse_source_tokens(value: str | None) -> tuple[set[str] | None, str | None]:
    if value is None or not value.strip() or value.strip().lower() == "all":
        return None, None
    tokens = {item.strip().lower() for item in value.split(",") if item.strip()}
    bad = sorted(tokens - set(QUERY_SOURCE_FILTERS))
    if bad:
        return None, (
            "codess: invalid --source token(s) for query: "
            + ", ".join(repr(item) for item in bad)
            + " (allowed: cc, codex, cursor, all; comma-separated)"
        )
    return tokens or None, None


def _session_recency_sort_key(session: dict) -> tuple:
    timestamp = session["ended_at"]
    if timestamp is None:
        timestamp = session["started_at"]
    try:
        recency = float(timestamp) if timestamp is not None else float("-inf")
    except (TypeError, ValueError):
        recency = float("-inf")
    return (
        -recency,
        session["query_project"],
        session["source"],
        session["id"],
    )


def _get_sessions_ordered(scope: QueryScope, limit: int | None = None) -> list[dict]:
    """Return sessions across stores, globally ordered by recency."""
    sessions = []
    for store_index, store in enumerate(scope.stores):
        session_columns = {
            row[1] for row in store["conn"].execute("PRAGMA table_info(sessions)")
        }
        global_projection = "global_id," if "global_id" in session_columns else "NULL AS global_id,"
        project_projection = (
            "project_id," if "project_id" in session_columns
            else "NULL AS project_id,"
        )
        predicate, params = _source_predicate(scope)
        rows = store["conn"].execute(
            f"""
            SELECT id, {global_projection} {project_projection} source_system_id, vendor_session_id, source, release, started_at, ended_at,
                   project_path, metadata
            FROM sessions s
            WHERE {predicate}
            """,
            params,
        )
        for row in rows:
            source_system_id = row["source_system_id"]
            if not source_system_id or source_system_id == "legacy.unknown":
                # Pre-provenance stores did not persist a source namespace.  Keep
                # their IDs globally distinct by deriving a compatibility
                # namespace from the recorded vendor label.
                source_system_id = f"legacy.vendor:{str(row['source']).casefold()}"
            stable_id = (
                row["global_id"]
                if row["global_id"] and not row["global_id"].startswith("codess:legacy:")
                else global_session_id(
                    source_system_id, row["vendor_session_id"] or row["id"]
                )
            )
            project_id = row["project_id"] or store.get("project_id")
            sessions.append(
                {
                    "id": row["id"],
                    "global_id": stable_id,
                    "name": scope.session_names.get(
                        (str(project_id), stable_id)
                    ) if project_id else None,
                    "query_id": (store_index, row["id"]),
                    "source": row["source"],
                    "release": row["release"],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "project_path": row["project_path"],
                    "metadata": row["metadata"],
                    "query_project": str(store["project_path"]),
                    "conn": store["conn"],
                }
            )

    sessions.sort(key=_session_recency_sort_key)
    if limit is not None:
        return sessions[:limit]
    return sessions


def _limited(rows: list[dict], limit: int | None) -> list[dict]:
    return rows if limit is None else rows[:limit]


def _session_by_number(scope: QueryScope, n: int) -> dict | None:
    """Return the 1-based globally ordered session reference."""
    rows = _get_sessions_ordered(scope, limit=n)
    if n < 1 or n > len(rows):
        return None
    return rows[n - 1]


def _session_by_identifier(scope: QueryScope, identifier: str) -> dict | None:
    folded = identifier.casefold()
    matches = [
        row for row in _get_sessions_ordered(scope)
        if (
            row["global_id"] == identifier
            or row["id"] == identifier
            or (
                row.get("name") is not None
                and str(row["name"]).casefold() == folded
            )
        )
    ]
    if len(matches) > 1:
        raise ValueError(
            f"Session identifier {identifier!r} is ambiguous across selected "
            "stores; use the global session ID"
        )
    return matches[0] if matches else None


def run(args) -> int:
    """Run session-query. Returns exit code."""
    config_errors = validate_config()
    for msg in config_errors:
        print(f"codess: {msg}", file=sys.stderr)
    if config_errors:
        return 1

    limit = getattr(args, "limit", None)
    if limit is not None and limit < 0:
        print("codess: --limit must be >= 0", file=sys.stderr)
        return 1
    source_tokens, source_error = _parse_source_tokens(
        getattr(args, "source", None)
    )
    if source_error:
        print(source_error, file=sys.stderr)
        return 1
    if getattr(args, "sess", None) is not None and getattr(
        args, "session_identifier", None
    ):
        print("codess: -sess and --session-id are mutually exclusive", file=sys.stderr)
        return 1
    primary_modes = [
        getattr(args, "tool", None) is not None,
        bool(getattr(args, "sessions", False)),
        getattr(args, "sess", None) is not None
        or bool(getattr(args, "session_identifier", None)),
        bool(getattr(args, "permissions", False)),
        bool(getattr(args, "task_review", False)),
        bool(getattr(args, "lineage", False)),
        bool(getattr(args, "audit", False)),
        bool(getattr(args, "diagnostics", False)),
        bool(getattr(args, "artifacts", False)),
        bool(getattr(args, "stats", False)),
        bool(getattr(args, "taxonomy", False)),
    ]
    if getattr(args, "query_action", None):
        # A stable session ID is a typed predicate.  Other legacy report modes
        # would make the requested result contract ambiguous.
        legacy_without_session_filter = primary_modes[:2] + primary_modes[3:]
        if any(legacy_without_session_filter) or getattr(args, "sess", None) is not None:
            print("codess: typed query actions cannot be combined with legacy report modes", file=sys.stderr)
            return 1
        primary_modes = [True]
    if sum(primary_modes) > 1:
        print("codess: select exactly one query report mode", file=sys.stderr)
        return 1
    if getattr(args, "show", None) is not None and not (
        getattr(args, "sess", None) is not None
        or getattr(args, "session_identifier", None)
    ):
        print("codess: --show requires -sess or --session-id", file=sys.stderr)
        return 1
    if getattr(args, "sess_id", False) and not getattr(args, "sessions", False):
        print("codess: --id requires --sessions", file=sys.stderr)
        return 1

    registry = resolve_registry_directory(args)
    requested_project_ids = list(getattr(args, "project_ids", None) or [])
    project_set = getattr(args, "project_set", None)
    all_current = bool(getattr(args, "all_current", False))
    package_policy = getattr(args, "snapshot_package_policy", "exact")
    explicit_paths = bool(getattr(args, "dirs", None)) or bool(
        getattr(args, "dir_list", None)
    )
    selector_count = (
        int(bool(requested_project_ids))
        + int(project_set is not None)
        + int(all_current)
        + int(explicit_paths)
    )
    if selector_count > 1:
        print(
            "codess: select exactly one of --project-id, --project-set, "
            "--all-current, or --dir/--dirs",
            file=sys.stderr,
        )
        return 1
    catalog_selection = bool(requested_project_ids) or project_set is not None or all_current
    if catalog_selection:
        try:
            project_scopes = resolve_project_query_scopes(
                registry,
                requested_project_ids or None,
                project_set=project_set,
                all_current=all_current,
                allow_package_mismatch=package_policy == "read-compatible",
            )
        except (OSError, ValueError, json.JSONDecodeError, SnapshotError) as exc:
            print(f"codess: cannot resolve Project scope: {exc}", file=sys.stderr)
            return 1
        resolved_roots = [
            Path(selection["project_path"]) for selection in project_scopes
        ]
    else:
        roots, err = resolve_cli_roots(
            args, when_empty=RootsWhenEmpty.PROJECT_ROOT
        )
        if err:
            print(err, file=sys.stderr)
            return 1
        resolved_roots = [root.resolve() for root in roots]
        project_scopes = []
    snapshot_id = getattr(args, "snapshot_id", None)
    if snapshot_id and (project_set is not None or all_current):
        print(
            "codess: --snapshot-id cannot be combined with --project-set or "
            "--all-current; put expected snapshots in the Project set",
            file=sys.stderr,
        )
        return 1
    if snapshot_id and len(resolved_roots) != 1:
        print("codess: --snapshot-id requires exactly one project root", file=sys.stderr)
        return 1
    try:
        if catalog_selection:
            scope, missing_roots = _open_project_id_query_scope(
                project_scopes,
                snapshot_id=snapshot_id,
                allow_package_mismatch=package_policy == "read-compatible",
                source_tokens=source_tokens,
            )
        else:
            scope, missing_roots = _open_query_scope(
                resolved_roots,
                snapshot_id=snapshot_id,
                allow_package_mismatch=package_policy == "read-compatible",
                source_tokens=source_tokens,
            )
    except (sqlite3.Error, SchemaContractError, SnapshotError) as exc:
        print(f"codess: cannot open query stores: {exc}", file=sys.stderr)
        return 1
    if not scope.stores:
        print("No store found. Run session-ingest first.", file=sys.stderr)
        return 1
    scope.session_names = alias_index(registry)
    for root in missing_roots:
        print(
            f"codess: warning: no store found for {sanitize_tabular(root)}",
            file=sys.stderr,
        )
    if snapshot_id and package_policy == "read-compatible":
        print(
            "codess: warning: historical snapshot package differs or was not "
            "required to match; hashes and format were verified, mapping parity was not",
            file=sys.stderr,
        )

    try:
        if getattr(args, "query_action", None):
            return _typed_output(scope, args, snapshot_id=snapshot_id)
        if getattr(args, "output_format", "table") == "jsonl":
            return _jsonl_output(
                scope, args, resolved_roots, limit,
                resolve_registry_directory(args),
                update_registry=not bool(snapshot_id) and not bool(source_tokens),
            )
        if getattr(args, "output_format", "table") == "csv":
            return _csv_output(
                scope, args, resolved_roots, limit,
                resolve_registry_directory(args),
                update_registry=not bool(snapshot_id) and not bool(source_tokens),
            )
        if getattr(args, "stats", False):
            return _stats(
                scope, resolved_roots, resolve_registry_directory(args),
                update_registry=not bool(snapshot_id) and not bool(source_tokens),
            )
        if getattr(args, "taxonomy", False):
            return _taxonomy(scope)
        if getattr(args, "tool", None) is not None:
            return _tool_table(scope, args.tool)
        if args.sessions:
            return _sessions(scope, getattr(args, "sess_id", False), limit)
        if getattr(args, "sess", None) is not None:
            return _show_session(scope, args.sess, getattr(args, "show", None))
        if getattr(args, "session_identifier", None):
            return _show_session(
                scope, None, getattr(args, "show", None),
                session_identifier=args.session_identifier,
            )
        if args.permissions:
            return _permissions(scope, limit)
        if args.task_review:
            return _task_review(scope)
        if getattr(args, "lineage", False):
            return _lineage(scope, limit)
        if getattr(args, "audit", False):
            return _audit(scope, limit)
        if getattr(args, "diagnostics", False):
            return _diagnostics(scope, limit)
        if getattr(args, "artifacts", False):
            return _artifacts(scope, limit)
        print(
            "Specify --tool, --sessions, -sess, --session-id, --permissions, --task-review, "
            "--lineage, --audit, --diagnostics, --artifacts, --stats, or --taxonomy",
            file=sys.stderr,
        )
        return 1
    finally:
        scope.close()


def _typed_filters(args, source_tokens: set[str] | None) -> dict:
    filters = {}
    values = {
        "event_ids": getattr(args, "event_ids", None),
        "interaction_ids": getattr(args, "interaction_ids", None),
        "model_turn_ids": getattr(args, "model_turn_ids", None),
        "event_kinds": getattr(args, "event_kinds", None),
        "statuses": getattr(args, "query_statuses", None),
        "models": getattr(args, "query_models", None),
        "model_providers": getattr(args, "query_model_providers", None),
        "model_families": getattr(args, "query_model_families", None),
        "model_revisions": getattr(args, "query_model_revisions", None),
        "reasoning_efforts": getattr(args, "query_reasoning_efforts", None),
        "speed_tiers": getattr(args, "query_speed_tiers", None),
        "service_tiers": getattr(args, "query_service_tiers", None),
        "model_modes": getattr(args, "query_model_modes", None),
        "tool_names": getattr(args, "query_tool_names", None),
        "actor_kinds": getattr(args, "query_actor_kinds", None),
        "content_roles": getattr(args, "query_content_roles", None),
        "origin_kinds": getattr(args, "query_origin_kinds", None),
        "parent_session_ids": getattr(args, "parent_session_ids", None),
        "session_relation_kinds": getattr(
            args, "session_relation_kinds", None
        ),
        "initiation_kinds": getattr(args, "initiation_kinds", None),
        "artifact": getattr(args, "query_artifact", None),
        "text": getattr(args, "query_text", None),
        "since": getattr(args, "since", None),
        "until": getattr(args, "until", None),
    }
    for key, value in values.items():
        if value is not None:
            filters[key] = value
    if getattr(args, "session_identifier", None):
        filters["session_ids"] = [args.session_identifier]
    if source_tokens:
        filters["source_system_ids"] = [QUERY_SOURCE_FILTERS[token][0] for token in sorted(source_tokens)]
    return filters


def _typed_output(scope: QueryScope, args, *, snapshot_id: str | None) -> int:
    """Execute the typed interface and retain exact replay/provenance contracts."""
    action = args.query_action
    if action == "cite":
        if not getattr(args, "result_input", None):
            print(
                "codess: query cite requires --result-input",
                file=sys.stderr,
            )
            return 1
        if not getattr(args, "summary_file", None):
            print(
                "codess: query cite requires --summary-file",
                file=sys.stderr,
            )
            return 1
        if not getattr(args, "processor_id", None):
            print(
                "codess: query cite requires --processor-id",
                file=sys.stderr,
            )
            return 1
        try:
            prior = load_document(Path(args.result_input), RESULT_FORMAT)
            selected_snapshots = selected_project_snapshots(scope.stores)
            expected_snapshots = (
                prior.get("request") or {}
            ).get("project_snapshots", [])
            if expected_snapshots and expected_snapshots != selected_snapshots:
                raise QueryContractError(
                    "cited result Project snapshots do not match the selected scope"
                )
            summary = Path(args.summary_file).read_text(encoding="utf-8")
            record = build_investigation(
                prior,
                summary=summary,
                processor_id=args.processor_id,
                event_ids=getattr(args, "event_ids", None) or (),
            )
            if getattr(args, "save_investigation", None):
                save_document(Path(args.save_investigation), record)
        except (OSError, UnicodeError, QueryContractError) as exc:
            print(f"codess: cited investigation rejected: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0
    if action == "evidence":
        event_ids = getattr(args, "event_ids", None) or []
        if len(event_ids) != 1:
            print("codess: query evidence requires exactly one --event-id", file=sys.stderr)
            return 1
        matches = []
        for store in scope.stores:
            try:
                matches.append(resolve_event(store, event_ids[0]))
            except LookupError as exc:
                if "ambiguous" in str(exc):
                    print(f"codess: {exc}", file=sys.stderr)
                    return 1
        if len(matches) != 1:
            print(f"codess: event {event_ids[0]!r} resolved in {len(matches)} stores; use a globally unique ID", file=sys.stderr)
            return 1
        allowed = (
            {QUERY_SOURCE_FILTERS[token][0] for token in scope.source_tokens}
            if scope.source_tokens else None
        )
        if allowed and matches[0]["source"]["source_system_id"] not in allowed:
            print("codess: event is outside the selected vendor scope", file=sys.stderr)
            return 1
        print(json.dumps(matches[0], indent=2, sort_keys=True))
        return 0 if matches[0]["selected"] else 2
    if action == "configurations":
        allowed = (
            {QUERY_SOURCE_FILTERS[token][0] for token in scope.source_tokens}
            if scope.source_tokens else None
        )
        audit_stores = scope.stores
        session_ids = None
        if getattr(args, "session_identifier", None):
            try:
                selected_session = _session_by_identifier(
                    scope, args.session_identifier
                )
            except ValueError as exc:
                print(f"codess: {exc}", file=sys.stderr)
                return 1
            if selected_session is None:
                print(
                    f"codess: no Session matches {args.session_identifier!r}",
                    file=sys.stderr,
                )
                return 1
            audit_stores = [
                store
                for store in scope.stores
                if store["conn"] is selected_session["conn"]
            ]
            session_ids = {selected_session["id"]}
        print(json.dumps(audit_configurations(
            audit_stores,
            source_system_ids=allowed,
            session_ids=session_ids,
        ), indent=2, sort_keys=True))
        return 0
    source_tokens, error = _parse_source_tokens(getattr(args, "source", None))
    if error:
        print(error, file=sys.stderr)
        return 1
    try:
        derivations = []
        selected = None
        if getattr(args, "result_input", None):
            prior_selection = load_document(
                Path(args.result_input), RESULT_FORMAT
            )
            selected = selection_from_result(prior_selection)
            derivation = {
                "kind": "stable_id_selection",
                "input_result_hash": prior_selection.get("result_hash"),
                "input_request_hash": prior_selection.get("request_hash"),
                "selected_session_ids": selected.get("session_ids", []),
                "selected_event_ids": selected.get("event_ids", []),
            }
            derivation["derivation_id"] = content_hash(derivation)
            derivations.append(derivation)
        if getattr(args, "query_request", None):
            request = load_document(Path(args.query_request), REQUEST_FORMAT)
            validate_request(request)
            if request["action"] != action:
                raise QueryContractError(
                    f"request action {request['action']!r} does not match query action {action!r}"
                )
            cli_filters = _typed_filters(args, source_tokens)
            if (
                cli_filters or getattr(args, "limit", None) is not None
                or getattr(args, "byte_limit", None) is not None
                or getattr(args, "active_gap_caps", None)
                or getattr(args, "expand", None)
                or getattr(args, "before", 0)
                or getattr(args, "after", 0)
                or getattr(args, "group_repetitions", False)
                or getattr(args, "facet_limit", 50) != 50
            ):
                raise QueryContractError(
                    "a saved request cannot be combined with CLI predicates or limits"
                )
            if request.get("snapshot_id") != snapshot_id:
                raise QueryContractError(
                    "saved request snapshot_id must match the explicit --snapshot-id scope"
                )
            if request.get("project_ids") != selected_project_ids(scope.stores):
                raise QueryContractError(
                    "saved request project_ids do not match the selected Project scope"
                )
            if request.get("project_snapshots") and (
                request["project_snapshots"]
                != selected_project_snapshots(scope.stores)
            ):
                raise QueryContractError(
                    "saved request project_snapshots do not match the selected "
                    "Project observations"
                )
            if selected:
                request = merge_selection(request, selected)
        else:
            if action == "overview" and (
                getattr(args, "limit", None) is not None
                or getattr(args, "byte_limit", None) is not None
            ):
                raise QueryContractError("overview does not accept --limit or --byte-limit")
            filters = _typed_filters(args, source_tokens)
            if selected:
                for key, values in selected.items():
                    current = set(filters.get(key) or [])
                    filters[key] = (
                        sorted(current & set(values))
                        if current else sorted(set(values))
                    )
            request = make_request(
                action,
                project_ids=selected_project_ids(scope.stores),
                project_snapshots=selected_project_snapshots(scope.stores),
                filters=filters,
                limit=getattr(args, "limit", None),
                byte_limit=(
                    (getattr(args, "byte_limit", None) if getattr(args, "byte_limit", None) is not None else DEFAULT_QUERY_BYTE_LIMIT)
                    if action in {"events", "search"} else None
                ),
                snapshot_id=snapshot_id,
                active_gap_caps_minutes=getattr(args, "active_gap_caps", None) or (5, 30, 120),
                expand=(
                    str(args.expand).replace("-", "_")
                    if getattr(args, "expand", None)
                    else None
                ),
                sequence_before=getattr(args, "before", 0),
                sequence_after=getattr(args, "after", 0),
                group_repetitions=bool(
                    getattr(args, "group_repetitions", False)
                ),
                facet_limit=getattr(args, "facet_limit", 50),
            )
        if getattr(args, "save_request", None):
            save_document(Path(args.save_request), request)
        result = execute_typed_query(
            scope.stores, request, derivations=derivations
        )
        changed = False
        if getattr(args, "compare_result", None):
            prior = load_document(Path(args.compare_result), RESULT_FORMAT)
            result["comparison"] = compare_results(prior, result)
            if not result["comparison"]["comparable"]:
                raise QueryContractError(
                    "comparison inputs are not semantically comparable: "
                    + "; ".join(result["comparison"]["comparison_issues"])
                )
            changed = bool(
                result["comparison"]["added_ids"]
                or result["comparison"]["removed_ids"]
                or result["comparison"]["changed_ids"]
                or result["comparison"]["summary_changed"]
                or result["comparison"]["provenance_changed"]
            )
        if getattr(args, "save_result", None):
            save_document(Path(args.save_result), result)
    except (QueryContractError, OSError) as exc:
        print(f"codess: typed query rejected: {exc}", file=sys.stderr)
        return 1
    output_format = getattr(args, "output_format", "table")
    if output_format == "csv":
        print("codess: typed results are JSON documents; use jq/sqlite/notebooks for tabular projection", file=sys.stderr)
        return 1
    if output_format == "jsonl":
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 3 if changed else 0


def _emit_jsonl(report: str, data: dict, *, project_path: str | None = None, row_number: int | None = None) -> None:
    envelope = {
        "schema": "codess.query-row/1",
        "report": report,
        "project_path": project_path,
        "row_number": row_number,
        "data": data,
    }
    print(json.dumps(envelope, sort_keys=True, separators=(",", ":")))


def _project_counts(scope: QueryScope, roots: list[Path]) -> dict[str, dict[str, int]]:
    counts = {str(root.resolve()): {"sessions": 0, "events": 0} for root in roots}
    for store in scope.stores:
        project = str(store["project_path"])
        predicate, params = _source_predicate(scope)
        counts[project]["sessions"] += store["conn"].execute(
            f"SELECT COUNT(*) FROM sessions s WHERE {predicate}", params
        ).fetchone()[0]
        counts[project]["events"] += store["conn"].execute(
            f"SELECT COUNT(*) FROM events e JOIN sessions s ON s.id=e.session_id "
            f"WHERE {predicate}", params
        ).fetchone()[0]
    return counts


def _merge_stats_into_registry(
    counts: dict[str, dict[str, int]], roots: list[Path], registry_root: Path,
) -> None:
    for project_path in roots:
        project = str(project_path.resolve())

        def mut(e: dict, values: dict = counts[project]) -> None:
            merge_query_stats(e, values["sessions"], values["events"])

        try:
            update_project_entry(registry_root, project, mut)
        except OSError as exc:
            log.warning("Registry update failed for %s: %s", project, exc)


def _jsonl_output(
    scope: QueryScope,
    args,
    roots: list[Path],
    limit: int | None,
    registry_root: Path,
    *,
    update_registry: bool,
) -> int:
    """Versioned typed prototype for reports with settled row semantics."""
    if args.sessions:
        for number, row in enumerate(_get_sessions_ordered(scope, limit), 1):
            _emit_jsonl("sessions", {
                "session_id": row["id"], "global_session_id": row["global_id"],
                "source": row["source"], "release": row["release"],
                "started_at": row["started_at"], "ended_at": row["ended_at"],
                "source_project_path": row["project_path"],
                "metadata": _json_metadata(row["metadata"]),
            }, project_path=row["query_project"], row_number=number)
        return 0
    if getattr(args, "stats", False):
        counts = _project_counts(scope, roots)
        for number, root in enumerate(roots, 1):
            project = str(root.resolve())
            _emit_jsonl(
                "stats.project", counts[project],
                project_path=project, row_number=number,
            )
        _emit_jsonl("stats.total", {
            "projects": len(counts),
            "sessions": sum(item["sessions"] for item in counts.values()),
            "events": sum(item["events"] for item in counts.values()),
        })
        if update_registry:
            _merge_stats_into_registry(counts, roots, registry_root)
        return 0
    print("codess: JSON Lines prototype currently supports --sessions and --stats", file=sys.stderr)
    return 1


def _csv_output(
    scope: QueryScope,
    args,
    roots: list[Path],
    limit: int | None,
    registry_root: Path,
    *,
    update_registry: bool,
) -> int:
    """Emit spreadsheet-safe CSV for settled sessions and stats reports."""
    writer = csv.writer(sys.stdout, lineterminator="\n")
    if args.sessions:
        writer.writerow([
            "session_id", "global_session_id", "row_number", "source",
            "release", "started_at", "ended_at", "source_project_path",
            "query_project_path", "metadata_json",
        ])
        for number, row in enumerate(_get_sessions_ordered(scope, limit), 1):
            writer.writerow(protect_csv_row([
                row["id"], row["global_id"], number, row["source"],
                row["release"], row["started_at"], row["ended_at"],
                row["project_path"], row["query_project"],
                json.dumps(_json_metadata(row["metadata"]), sort_keys=True),
            ]))
        return 0
    if getattr(args, "stats", False):
        writer.writerow([
            "report", "project_path", "row_number", "projects", "sessions",
            "events",
        ])
        counts = _project_counts(scope, roots)
        for number, root in enumerate(roots, 1):
            project = str(root.resolve())
            writer.writerow(protect_csv_row([
                "stats.project", project, number, "",
                counts[project]["sessions"], counts[project]["events"],
            ]))
        writer.writerow(protect_csv_row([
            "stats.total", "", "", len(counts),
            sum(item["sessions"] for item in counts.values()),
            sum(item["events"] for item in counts.values()),
        ]))
        if update_registry:
            _merge_stats_into_registry(counts, roots, registry_root)
        return 0
    print("codess: CSV currently supports --sessions and --stats", file=sys.stderr)
    return 1


def _stats(
    scope: QueryScope,
    project_roots: list[Path],
    registry_root: Path,
    *,
    update_registry: bool = True,
) -> int:
    """Print aggregate stats and merge per-project counts into the registry."""
    counts = _project_counts(scope, project_roots)
    sessions = sum(item["sessions"] for item in counts.values())
    events = sum(item["events"] for item in counts.values())
    print(f"Sessions: {sessions}")
    print(f"Events: {events}")
    if not update_registry:
        return 0
    _merge_stats_into_registry(counts, project_roots, registry_root)
    return 0


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _diagnostics(scope: QueryScope, limit: int | None = None) -> int:
    """Print structured mapping loss/ambiguity without hiding source values."""
    rows: list[dict] = []
    for store_index, store in enumerate(scope.stores):
        conn = store["conn"]
        if not _has_table(conn, "mapping_diagnostics"):
            continue
        diagnostic_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(mapping_diagnostics)")
        }
        severity_projection = (
            "d.severity" if "severity" in diagnostic_columns
            else "'warn' AS severity"
        )
        where = ""
        params: tuple[str, ...] = ()
        if scope.source_tokens:
            session_predicate, session_params = _source_predicate(scope)
            source_ids = tuple(
                QUERY_SOURCE_FILTERS[token][0]
                for token in sorted(scope.source_tokens)
            )
            placeholders = ",".join("?" for _ in source_ids)
            where = (
                f"WHERE ({session_predicate} OR "
                f"src.source_system_id IN ({placeholders}))"
            )
            params = (*session_params, *source_ids)
        for row in conn.execute(
            f"""
            SELECT d.level, {severity_projection}, d.reason_code,
                   d.source_field, d.source_value,
                   d.mapping_rule, d.detail, d.created_at, d.session_id,
                   e.event_id
            FROM mapping_diagnostics d
            LEFT JOIN events e ON e.id = d.event_id
            LEFT JOIN sessions s ON s.id = COALESCE(d.session_id, e.session_id)
            LEFT JOIN sources src ON src.id = d.source_id
            {where}
            """,
            params,
        ):
            item = dict(row)
            item["project_path"] = str(store["project_path"])
            item["store_index"] = store_index
            rows.append(item)
    rows.sort(key=lambda row: (
        row["created_at"], row["project_path"], row["store_index"],
        row["session_id"] or "", row["event_id"] or "",
    ))
    rows = _limited(rows, limit)
    if not rows:
        return 0
    print("project_path\tsession_id\tevent_id\tlevel\tseverity\treason_code\tsource_field\tsource_value\tmapping_rule\tdetail")
    for row in rows:
        print("\t".join(sanitize_tabular(row.get(key)) for key in (
            "project_path", "session_id", "event_id", "level", "severity", "reason_code",
            "source_field", "source_value", "mapping_rule", "detail",
        )))
    return 0


def _artifacts(scope: QueryScope, limit: int | None = None) -> int:
    """Aggregate evidence for artifacts touched by one or more coding systems."""
    grouped: dict[tuple[str, str, str], dict] = {}
    for store in scope.stores:
        conn = store["conn"]
        if not _has_table(conn, "artifacts") or not _has_table(conn, "event_artifacts"):
            continue
        correlations = {}
        if _has_table(conn, "correlation_assertions"):
            for assertion in conn.execute(
                "SELECT object_id, relation_kind, evidence, confidence FROM correlation_assertions "
                "WHERE subject_kind='artifact' AND object_kind='project'"
            ):
                evidence = _json_metadata(assertion["evidence"])
                uri = evidence.get("artifact_uri")
                if uri:
                    correlations.setdefault(uri, []).append(
                        (assertion["object_id"], assertion["relation_kind"], assertion["confidence"])
                    )
        predicate, params = _source_predicate(scope)
        rows = conn.execute(
            f"""
            SELECT a.artifact_kind,
                   COALESCE(a.relative_path, a.uri, a.observed_absolute_path) AS locator,
                   ea.operation, s.source, e.session_id
            FROM artifacts a
            JOIN event_artifacts ea ON ea.artifact_id = a.id
            JOIN events e ON e.id = ea.event_id
            JOIN sessions s ON s.id = e.session_id
            WHERE COALESCE(a.relative_path, a.uri, a.observed_absolute_path) IS NOT NULL
              AND {predicate}
            """,
            params,
        )
        project = str(store["project_path"])
        for row in rows:
            key = (project, row["artifact_kind"], row["locator"])
            item = grouped.setdefault(key, {"sources": set(), "operations": set(), "sessions": set(), "evidence": 0, "correlations": set()})
            item["sources"].add(row["source"])
            item["operations"].add(row["operation"])
            item["sessions"].add(row["session_id"])
            item["evidence"] += 1
            item["correlations"].update(correlations.get(row["locator"], []))
    rows = []
    for (project, kind, locator), item in grouped.items():
        rows.append({
            "project_path": project, "kind": kind, "locator": locator,
            "sources": ",".join(sorted(item["sources"])),
            "source_count": len(item["sources"]),
            "operations": ",".join(sorted(item["operations"])),
            "session_count": len(item["sessions"]), "evidence": item["evidence"],
            "correlations": ",".join(
                f"{project_id}|{relation}|{confidence:g}"
                for project_id, relation, confidence in sorted(item["correlations"])
            ),
        })
    rows.sort(key=lambda row: (-row["source_count"], -row["evidence"], row["project_path"], row["locator"]))
    rows = _limited(rows, limit)
    if not rows:
        return 0
    print("project_path\tartifact_kind\tlocator\tsources\tsource_count\toperations\tsession_count\tevidence_count\tproject_correlations")
    for row in rows:
        print(
            f"{sanitize_tabular(row['project_path'])}\t{sanitize_tabular(row['kind'])}\t"
            f"{sanitize_tabular(row['locator'])}\t{sanitize_tabular(row['sources'])}\t"
            f"{row['source_count']}\t{sanitize_tabular(row['operations'])}\t"
            f"{row['session_count']}\t{row['evidence']}\t{sanitize_tabular(row['correlations'])}"
        )
    return 0


def _taxonomy(_scope: QueryScope) -> int:
    """Event types and subtypes, vertical list."""
    print("tool_call")
    print("user_message")
    print("  prompt")
    print("  slash_command")
    print("  tool_result")
    print("  permission_denied")
    print("  tool_failure")
    print("assistant_message")
    print("  response")
    print("  dialog")
    print("  truncated")
    print("  turn_aborted")
    print("system_event")
    print("  context_compaction")
    print("  context_compaction_summary")
    print("  context_injection")
    return 0


def _tool_table(scope: QueryScope, recent: int) -> int:
    """Tool histogram: rows=tools (standard first, then loaded), cols=sessions. recent=0 all, 1=most recent."""
    limit = None if recent == 0 else recent
    sessions = _get_sessions_ordered(scope, limit=limit)
    if not sessions:
        return 0

    # Per-session tool counts: {session_id: {tool_name: count}}
    sess_ids = [r["query_id"] for r in sessions]
    sess_counts = {}
    for session in sessions:
        sid = session["query_id"]
        cur = session["conn"].execute(
            """
            SELECT tool_name, COUNT(*) as cnt
            FROM events
            WHERE event_type = 'tool_call' AND tool_name IS NOT NULL AND session_id = ?
            GROUP BY tool_name
            """,
            (session["id"],),
        )
        sess_counts[sid] = {row["tool_name"]: row["cnt"] for row in cur}

    # All tools, totals, sorted by total desc
    all_tools = {}
    for sid in sess_ids:
        for t, c in sess_counts[sid].items():
            all_tools[t] = all_tools.get(t, 0) + c
    tools_sorted = sorted(all_tools.keys(), key=lambda t: -all_tools[t])

    # Group: standard first (alphabetical), then loaded (alphabetical)
    standard = sorted([t for t in tools_sorted if t in STANDARD_TOOLS])
    loaded = sorted([t for t in tools_sorted if t not in STANDARD_TOOLS])
    tools_ordered = standard + loaded

    # Header: Sess 1 2 3 Total
    n = len(sessions)
    header = ["", "Sess"] + [str(i + 1) for i in range(n)] + ["Total"]
    print("  ".join(header))

    max_w = max(len(t) for t in tools_ordered) if tools_ordered else 10
    for tool in tools_ordered:
        row = [tool]
        for i, sid in enumerate(sess_ids):
            row.append(str(sess_counts[sid].get(tool, 0)))
        row.append(str(all_tools[tool]))
        print("  ".join([sanitize_tabular(row[0]).ljust(max_w)] + row[1:]))
    return 0


def _normalize_prompt(s: str) -> str:
    """Code fence, collapse whitespace."""
    if not s:
        return ""
    s = sanitize_text(s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _normalize_response(s: str) -> str:
    """Remove empty lines, trailing whitespace."""
    if not s:
        return ""
    lines = [ln.rstrip() for ln in sanitize_text(s).splitlines() if ln.strip()]
    return "\n".join(lines)


def _show_session(
    scope: QueryScope,
    sess_num: int | None,
    show_modes: list | None,
    *,
    session_identifier: str | None = None,
) -> int:
    """Show session content by ordinal or stable global/vendor identifier."""
    try:
        session = (
            _session_by_identifier(scope, session_identifier)
            if session_identifier is not None
            else _session_by_number(scope, int(sess_num))
        )
    except ValueError as exc:
        print(f"codess: {exc}", file=sys.stderr)
        return 1
    if not session:
        display = session_identifier if session_identifier is not None else sess_num
        print(f"No session {display}", file=sys.stderr)
        return 1

    modes = show_modes if show_modes else ["prompt", "pr", "agent", "tool", "perm"]
    show_prompt = "prompt" in modes or "pr" in modes
    show_pr = "pr" in modes
    show_agent = "agent" in modes
    show_tool = "tool" in modes
    show_perm = "perm" in modes

    cur = session["conn"].execute(
        """
        SELECT event_type, subtype, role, content, tool_name, tool_input
        FROM events
        WHERE session_id = ?
        ORDER BY CASE WHEN sequence_no IS NULL THEN 1 ELSE 0 END,
                 sequence_no, COALESCE(event_at, timestamp), id
        """,
        (session["id"],),
    )
    for row in cur:
        etype, subtype, _role, content, tool_name, tool_input = (
            row["event_type"], row["subtype"], row["role"],
            row["content"], row["tool_name"], row["tool_input"],
        )
        if etype == "user_message":
            if subtype in ("prompt", "slash_command"):
                if show_prompt:
                    text = _normalize_prompt(content or "")
                    print("## User")
                    print("```")
                    print(text)
                    print("```")
                    print()
            elif subtype in ("tool_result", "tool_failure"):
                if show_tool:
                    print(f"[{subtype}] {sanitize_tabular(tool_name)}")
                    print(sanitize_for_display(content or "", 500))
                    print()
            elif subtype == "permission_denied":
                if show_perm:
                    print(f"[permission_denied] {sanitize_tabular(tool_name)}")
                    print()
        elif etype == "assistant_message":
            # Skip dialog (short pre-tool chatter); keep response and truncated only
            if subtype in ("response", "truncated") and show_pr:
                text = _normalize_response(content or "")
                if text:
                    print("## Model")
                    print(text)
                    print()
        elif etype == "tool_call":
            is_agent = tool_name and ("Task" in tool_name or tool_name in ("mcp_task", "Task", "Agent"))
            if is_agent and show_agent:
                inp = {}
                if tool_input:
                    try:
                        inp = json.loads(tool_input)
                    except json.JSONDecodeError:
                        pass
                print(f"[agent] {sanitize_tabular(tool_name)}")
                print(f"  desc: {sanitize_for_display(inp.get('description', ''), 80)}")
                print(f"  prompt: {sanitize_for_display(inp.get('prompt', ''), 80)}")
                print()
            elif show_tool and not is_agent:
                print(f"[tool] {sanitize_tabular(tool_name)}")
                if tool_input:
                    print(f"  {sanitize_for_display(str(tool_input), 120)}")
                print()
    return 0


def _sessions(scope: QueryScope, with_id: bool, limit: int | None = None) -> int:
    """List sessions. with_id: number them (1=most recent)."""
    rows = _get_sessions_ordered(scope, limit=limit)
    if not rows:
        return 0
    if with_id:
        print("id\tglobal_id\tnum\tsource\tname\trelease\tdetails\tstarted_at\tended_at\tproject_path")
        for i, row in enumerate(rows, 1):
            project = row["project_path"] or row["query_project"]
            details = _session_details(row["metadata"])
            print(
                f"{sanitize_tabular(row['id'])}\t{row['global_id']}\t{i}\t"
                f"{sanitize_tabular(row['source'])}\t"
                f"{sanitize_tabular(row['name'])}\t"
                f"{sanitize_tabular(row['release'])}\t{details}\t"
                f"{row['started_at']}\t"
                f"{row['ended_at']}\t{sanitize_tabular(project)}"
            )
    else:
        print("id\tglobal_id\tsource\tname\trelease\tdetails\tstarted_at\tended_at\tproject_path")
        for row in rows:
            project = row["project_path"] or row["query_project"]
            details = _session_details(row["metadata"])
            print(
                f"{sanitize_tabular(row['id'])}\t{row['global_id']}\t"
                f"{sanitize_tabular(row['source'])}\t"
                f"{sanitize_tabular(row['name'])}\t"
                f"{sanitize_tabular(row['release'])}\t{details}\t"
                f"{row['started_at']}\t{row['ended_at']}\t{sanitize_tabular(project)}"
            )
    return 0


def _json_metadata(raw) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _session_details(raw) -> str:
    metadata = _json_metadata(raw)
    details = []
    for key in ("originator", "source", "storage", "parent_session_id"):
        if metadata.get(key) is not None:
            details.append(f"{key}={metadata[key]}")
    if metadata.get("is_sidechain"):
        details.append("sidechain=true")
    return sanitize_tabular(",".join(details))


def _lineage_id(raw) -> str:
    metadata = _json_metadata(raw)
    return str(metadata.get("call_id") or metadata.get("tool_use_id") or "")


def _lineage(scope: QueryScope, limit: int | None = None) -> int:
    """Print tool calls joined to results using vendor lineage identifiers."""
    rows = []
    for store_index, store in enumerate(scope.stores):
        predicate, params = _source_predicate(scope)
        events = [
            dict(row)
            for row in store["conn"].execute(
                f"""
                SELECT e.session_id, e.event_id, e.event_type, e.subtype,
                       e.tool_name, e.content_len, e.timestamp, e.metadata
                FROM events e JOIN sessions s ON s.id=e.session_id
                WHERE (e.event_type = 'tool_call'
                   OR e.subtype IN ('tool_result', 'permission_denied', 'tool_failure'))
                  AND {predicate}
                ORDER BY e.timestamp, e.id
                """,
                params,
            )
        ]
        results: dict[tuple[str, str], list[dict]] = {}
        unlinked_results = []
        calls = []
        for event in events:
            lineage_id = _lineage_id(event["metadata"])
            event["lineage_id"] = lineage_id
            if event["event_type"] == "tool_call":
                calls.append(event)
            elif lineage_id:
                results.setdefault(
                    (event["session_id"], lineage_id), []
                ).append(event)
            else:
                unlinked_results.append(event)

        for call in calls:
            key = (call["session_id"], call["lineage_id"])
            matched = results.get(key, []) if call["lineage_id"] else []
            result = matched.pop(0) if matched else None
            call_metadata = _json_metadata(call["metadata"])
            if result is None:
                outcome = (
                    "missing_result" if call["lineage_id"] else "unlinked_call"
                )
                result_len = ""
            else:
                outcome = {
                    "permission_denied": "permission_denied",
                    "tool_failure": "tool_failure",
                }.get(result["subtype"], "result")
                result_len = result["content_len"] or 0
            rows.append({
                "store_index": store_index,
                "project_path": str(store["project_path"]),
                "session_id": call["session_id"],
                "timestamp": call["timestamp"],
                "tool_name": call["tool_name"] or (
                    result["tool_name"] if result else ""
                ),
                "lineage_id": call["lineage_id"],
                "status": call_metadata.get("status", ""),
                "outcome": outcome,
                "result_len": result_len,
            })

        for remaining in results.values():
            unlinked_results.extend(remaining)
        for result in unlinked_results:
            rows.append({
                "store_index": store_index,
                "project_path": str(store["project_path"]),
                "session_id": result["session_id"],
                "timestamp": result["timestamp"],
                "tool_name": result["tool_name"] or "",
                "lineage_id": result.get("lineage_id", ""),
                "status": "",
                "outcome": {
                    "permission_denied": "permission_denied",
                    "tool_failure": "tool_failure",
                }.get(result["subtype"], "unlinked_result"),
                "result_len": result["content_len"] or 0,
            })

    rows.sort(key=lambda row: _timestamp_last_sort_key(
        row["timestamp"], row["project_path"], row["store_index"],
        row["session_id"], row["lineage_id"],
    ))
    rows = _limited(rows, limit)
    if not rows:
        return 0
    print(
        "project_path\tsession_id\ttimestamp\ttool_name\tlineage_id\t"
        "status\toutcome\tresult_len"
    )
    for row in rows:
        print(
            f"{sanitize_tabular(row['project_path'])}\t"
            f"{sanitize_tabular(row['session_id'])}\t{row['timestamp']}\t"
            f"{sanitize_tabular(row['tool_name'])}\t"
            f"{sanitize_tabular(row['lineage_id'])}\t"
            f"{sanitize_tabular(row['status'])}\t{row['outcome']}\t"
            f"{row['result_len']}"
        )
    return 0


def _task_review(scope: QueryScope) -> int:
    """Review Task and Web* tool invocations: counts, descriptions, outcomes."""
    # Tool counts by category
    all_tools = {}
    for store in scope.stores:
        predicate, params = _source_predicate(scope)
        cur = store["conn"].execute(
            f"""
            SELECT e.tool_name, COUNT(*) as cnt
            FROM events e JOIN sessions s ON s.id=e.session_id
            WHERE e.event_type = 'tool_call' AND e.tool_name IS NOT NULL
              AND {predicate}
            GROUP BY e.tool_name
            """,
            params,
        )
        for row in cur:
            all_tools[row["tool_name"]] = (
                all_tools.get(row["tool_name"], 0) + row["cnt"]
            )

    task_tools = {k: v for k, v in all_tools.items() if k and ("Task" in k or k in ("mcp_task", "Task"))}
    web_tools = {k: v for k, v in all_tools.items() if k and ("Web" in k or "web" in k.lower())}

    print("=== Tool counts ===")
    for name, cnt in sorted(all_tools.items(), key=lambda x: -x[1]):
        print(f"  {sanitize_tabular(name)}\t{cnt}")

    print("\n=== Task tools ===")
    for name, cnt in sorted(task_tools.items(), key=lambda x: -x[1]):
        print(f"  {sanitize_tabular(name)}\t{cnt}")

    print("\n=== Web* tools ===")
    for name, cnt in sorted(web_tools.items(), key=lambda x: -x[1]):
        print(f"  {sanitize_tabular(name)}\t{cnt}")

    # Task/Agent invocations: description, prompt, outcome
    task_calls = []
    for store in scope.stores:
        predicate, params = _source_predicate(scope)
        cur = store["conn"].execute(
            f"""
            SELECT e.session_id, e.event_id, e.tool_name, e.tool_input, e.timestamp
            FROM events e JOIN sessions s ON s.id=e.session_id
            WHERE e.event_type = 'tool_call'
              AND (e.tool_name LIKE '%Task%' OR e.tool_name IN ('mcp_task', 'Task'))
              AND {predicate}
            """,
            params,
        )
        task_calls.extend(dict(row) for row in cur)
    task_calls.sort(
        key=lambda row: (
            float(row["timestamp"]) if row["timestamp"] is not None else float("inf"),
            row["session_id"],
            row["event_id"],
        )
    )

    if task_calls:
        print("\n=== Task/Agent invocations (description, prompt) ===")
        for row in task_calls:
            inp = {}
            if row["tool_input"]:
                try:
                    inp = json.loads(row["tool_input"])
                except json.JSONDecodeError:
                    pass
            desc = sanitize_for_display(inp.get("description", ""), 80)
            prompt = sanitize_for_display(inp.get("prompt", ""), 80)
            sub = sanitize_tabular(inp.get("subagent_type", ""))
            parts = [f"[{sanitize_tabular(row['tool_name'])}]"]
            if desc:
                parts.append(f"desc: {sanitize_tabular(desc)}")
            if prompt:
                parts.append(f"prompt: {sanitize_tabular(prompt)}")
            if sub:
                parts.append(f"subagent: {sub}")
            print("  " + " | ".join(parts))

    # Tool results (outcomes): match by session + tool_name, infer outcome from content
    results = []
    for store in scope.stores:
        predicate, params = _source_predicate(scope)
        cur = store["conn"].execute(
            f"""
            SELECT e.session_id, e.tool_name, e.content, e.content_len
            FROM events e JOIN sessions s ON s.id=e.session_id
            WHERE e.event_type = 'user_message' AND e.subtype = 'tool_result'
              AND e.tool_name IS NOT NULL
              AND (e.tool_name LIKE '%Task%' OR e.tool_name IN ('mcp_task', 'Task'))
              AND {predicate}
            ORDER BY e.session_id, e.id
            """,
            params,
        )
        results.extend(dict(row) for row in cur)
    if results:
        outcomes = {}
        for row in results:
            c = (row["content"] or "").lower()
            if "timeout" in c:
                outcomes["timeout"] = outcomes.get("timeout", 0) + 1
            elif "not_ready" in c or "not ready" in c:
                outcomes["not_ready"] = outcomes.get("not_ready", 0) + 1
            elif "success" in c or "completed" in c:
                outcomes["success"] = outcomes.get("success", 0) + 1
            else:
                outcomes["unknown"] = outcomes.get("unknown", 0) + 1
        print("\n=== Task tool result outcomes (inferred from content) ===")
        for k, v in sorted(outcomes.items(), key=lambda x: -x[1]):
            print(f"  {k}\t{v}")

    return 0


def _permissions(scope: QueryScope, limit: int | None = None) -> int:
    """Print permission_denied events."""
    rows = []
    for store in scope.stores:
        predicate, params = _source_predicate(scope)
        cur = store["conn"].execute(
            f"""
            SELECT e.session_id, e.timestamp, e.tool_name
            FROM events e JOIN sessions s ON s.id=e.session_id
            WHERE e.subtype = 'permission_denied' AND {predicate}
            """,
            params,
        )
        for row in cur:
            item = dict(row)
            item["project_path"] = str(store["project_path"])
            rows.append(item)
    rows.sort(
        key=lambda row: (
            float(row["timestamp"]) if row["timestamp"] is not None else float("inf"),
            row["project_path"],
            row["session_id"],
            row["tool_name"] or "",
        )
    )
    rows = _limited(rows, limit)
    if not rows:
        return 0
    print("session_id\tproject_path\ttimestamp\ttool_name")
    for row in rows:
        print(
            f"{sanitize_tabular(row['session_id'])}\t"
            f"{sanitize_tabular(row['project_path'])}\t"
            f"{row['timestamp']}\t{sanitize_tabular(row['tool_name'])}"
        )
    return 0


def _audit(scope: QueryScope, limit: int | None = None) -> int:
    """Print only normalized, evidence-backed audit events."""
    rows = []
    supported = (
        "permission_denied",
        "tool_failure",
        "turn_aborted",
        "context_compaction",
        "context_compaction_summary",
    )
    placeholders = ",".join("?" for _ in supported)
    for store_index, store in enumerate(scope.stores):
        predicate, source_params = _source_predicate(scope)
        cur = store["conn"].execute(
            f"""
            SELECT e.session_id, e.event_id, e.timestamp, e.subtype,
                   e.tool_name, e.content_len, e.metadata, s.source
            FROM events e
            JOIN sessions s ON s.id = e.session_id
            WHERE e.subtype IN ({placeholders}) AND {predicate}
            """,
            (*supported, *source_params),
        )
        for row in cur:
            item = dict(row)
            item["project_path"] = str(store["project_path"])
            item["store_index"] = store_index
            rows.append(item)

    rows.sort(key=lambda row: _timestamp_last_sort_key(
        row["timestamp"], row["project_path"], row["store_index"],
        row["session_id"], row["event_id"],
    ))
    rows = _limited(rows, limit)
    if not rows:
        return 0
    print(
        "project_path\tsession_id\tsource\ttimestamp\taudit_kind\t"
        "tool_name\tdetail"
    )
    for row in rows:
        metadata = _json_metadata(row["metadata"])
        detail = ""
        if row["subtype"] == "context_compaction":
            detail = f"trigger={metadata.get('trigger', 'unknown')}"
        elif row["subtype"] == "context_compaction_summary":
            detail = (
                f"characters={row['content_len'] or 0},"
                f"truncated={str(bool(metadata.get('content_truncated'))).lower()}"
            )
        elif metadata.get("status") is not None:
            detail = f"status={metadata['status']}"
        print(
            f"{sanitize_tabular(row['project_path'])}\t"
            f"{sanitize_tabular(row['session_id'])}\t"
            f"{sanitize_tabular(row['source'])}\t{row['timestamp']}\t"
            f"{row['subtype']}\t{sanitize_tabular(row['tool_name'])}\t"
            f"{sanitize_tabular(detail)}"
        )
    return 0
