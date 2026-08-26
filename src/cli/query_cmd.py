"""Read-only, cross-store session query CLI command.
"""

import argparse
import contextlib
import csv
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

from cli.failure import fail, fail_configuration, warn
from codess import reporting
from codess.config import (
    DEFAULT_QUERY_BYTE_LIMIT,
    get_project_stores,
)
from codess.configuration_audit import audit as audit_configurations
from codess.coverage_report import store_coverage
from codess.investigation import build_investigation
from codess.project import RootsWhenEmpty, resolve_cli_roots, resolve_store_root
from codess.project_catalog import resolve_project_query_scopes
from codess.query_api import (
    REQUEST_FORMAT,
    RESULT_FORMAT,
    QueryContractError,
    compare_results,
    content_hash,
    load_document,
    make_request,
    merge_selection,
    save_document,
    selected_project_ids,
    selected_project_snapshots,
    selection_from_result,
    validate_request,
)
from codess.query_api import (
    execute as execute_typed_query,
)
from codess.query_reports import (
    artifact_evidence,
    audit_events,
    mapping_diagnostics,
    permission_denials,
    selected_sessions,
    session_events,
    store_counts,
    task_invocations,
    task_results,
    tool_counts_by_session,
    tool_lineage,
    tool_totals,
)
from codess.registry_store import merge_query_stats, update_project_entry
from codess.sanitize import (
    protect_csv_row,
    sanitize_for_display,
    sanitize_tabular,
    sanitize_text,
    tabular_row,
)
from codess.schema_contract import SchemaContractError
from codess.session_names import alias_index
from codess.snapshot import (
    SnapshotError,
    current_store_paths_from_base,
    snapshot_store_paths,
    snapshot_store_paths_from_base,
)
from codess.source_verification import verify_event_source
from codess.store import StoreError, connect_readable

log = logging.getLogger(__name__)

# Standard (built-in) tools for grouping; others are "loaded"
STANDARD_TOOLS = frozenset({
    "Bash", "Read", "Edit", "Write", "Grep", "Glob", "TodoWrite",
    "LS", "AskUserQuestion", "Skill", "Agent", "Task",
    "TaskCreate", "TaskUpdate", "TaskStop", "TaskList", "TaskOutput",
})

QUERY_SOURCE_FILTERS = {
    "cc": "anthropic.claude-code",
    "codex": "openai.codex",
    "cursor": "cursor.composer",
}
"""CLI source selector to the CoSchema source-system namespace it selects."""


class QueryScope:
    """Read-only stores selected for one logical query.

    Also supplies the source predicate the reports in `codess.query_reports`
    filter by, so a report receives the scope rather than reaching back into
    this module for a helper.
    """

    def __init__(self, source_tokens: set[str] | None = None) -> None:
        self.stores: list[dict] = []
        self.source_tokens = source_tokens
        self.session_names: dict[tuple[str, str], str] = {}

    def close(self) -> None:
        for store in self.stores:
            store["conn"].close()

    @property
    def selected_source_ids(self) -> tuple[str, ...]:
        """The CoSchema source systems this selection names, in stable order.

        One derivation for every predicate below: the tokens are a CLI
        vocabulary and the source-system identifiers are the stored one, and
        translating between them is a single decision rather than one per
        predicate shape.
        """
        return tuple(
            QUERY_SOURCE_FILTERS[token] for token in sorted(self.source_tokens or ())
        )

    def source_predicate(self, alias: str = "s") -> tuple[str, tuple[str, ...]]:
        """A source predicate over one alias, and its parameters.

        Returns a bare predicate rather than a clause so callers can compose
        it with their own conditions; `1` stands for an unfiltered selection
        because every caller substitutes it into an existing `WHERE`.
        """
        source_ids = self.selected_source_ids
        if not source_ids:
            return "1", ()
        placeholders = ", ".join("?" for _ in source_ids)
        return f"{alias}.source_system_id IN ({placeholders})", source_ids

    def diagnostics_predicate(self) -> tuple[str, tuple[str, ...]]:
        """The same selection for mapping diagnostics, which join two ways.

        A diagnostic can reach a source system through its Session or through
        the Source it was recorded against, and either is sufficient evidence
        that it belongs to the selection -- a record-level diagnostic often
        has no Session at all. Both aliases are therefore filtered, which is
        why this returns a whole clause: an empty selection has no `WHERE` at
        all rather than a true predicate, since the query it lands in has no
        other condition to attach to.
        """
        if not self.source_tokens:
            return "", ()
        session_predicate, session_params = self.source_predicate("s")
        source_predicate, source_params = self.source_predicate("src")
        return (
            f"WHERE ({session_predicate} OR {source_predicate})",
            (*session_params, *source_params),
        )


def _open_query_scope(
    roots: list[Path],
    *,
    snapshot_id: str | None = None,
    allow_contract_mismatch: bool = False,
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
                    allow_contract_mismatch=allow_contract_mismatch,
                )
                if snapshot_id
                else get_project_stores(resolved_root)
            )
            if not stores:
                roots_without_stores.append(resolved_root)
                continue
            for path in stores:
                conn = connect_readable(path)
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
    allow_contract_mismatch: bool = False,
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
                        allow_contract_mismatch=allow_contract_mismatch,
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
                conn = connect_readable(path)
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
    """Sessions across stores by recency, with any human name applied.

    The name is looked up here rather than in the query: it is a display
    label the operator assigned, held in the scope, not something the store
    records about the Session.
    """
    sessions = selected_sessions(scope, _session_recency_sort_key, limit)
    for session in sessions:
        project_id = session["project_id"]
        session["name"] = (
            scope.session_names.get((str(project_id), session["session_entity_id"]))
            if project_id else None
        )
    return sessions


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
            row["session_entity_id"] == identifier
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


def run(args: argparse.Namespace) -> int:
    """Run session-query, flushing whatever it reported.

    A thin wrapper around `_run` because that function returns from a dozen
    places: a flush at each is a dozen chances to omit one, and an unflushed
    batch is a report that silently ends early. The buffer holds 256 events and
    a query rarely fills it, so without this most runs would emit nothing at all.
    """
    reporting.configure(
        getattr(args, "report_profile", None),
        privacy=getattr(args, "report_privacy", None),
        redaction_roots={"home": Path.home(), "store": resolve_store_root(args)},
    )
    action = getattr(args, "action", None)
    reporting.event(reporting.code("query.start"), action=action)
    try:
        code = _run(args)
        reporting.event(
            reporting.code("query.done"), action=action, exit_code=code,
        )
        return code
    finally:
        reporting.flush()


def _run(args: argparse.Namespace) -> int:
    """Run session-query. Returns exit code."""
    if fail_configuration():
        return 1

    limit = getattr(args, "limit", None)
    if limit is not None and limit < 0:
        return fail('codess: --limit must be >= 0')
    source_tokens, source_error = _parse_source_tokens(
        getattr(args, "source", None)
    )
    if source_error:
        return fail(source_error)
    if getattr(args, "sess", None) is not None and getattr(
        args, "session_identifier", None
    ):
        return fail('codess: -sess and --session-id are mutually exclusive')
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
        # A stable session ID is a typed predicate.  Other report modes
        # would make the requested result contract ambiguous.
        report_modes_without_session_filter = primary_modes[:2] + primary_modes[3:]
        if any(report_modes_without_session_filter) or getattr(args, "sess", None) is not None:
            return fail('codess: typed query actions cannot be combined with report modes')
        primary_modes = [True]
    if sum(primary_modes) > 1:
        return fail('codess: select exactly one query report mode')
    if getattr(args, "show", None) is not None and not (
        getattr(args, "sess", None) is not None
        or getattr(args, "session_identifier", None)
    ):
        return fail('codess: --show requires -sess or --session-id')
    if getattr(args, "sess_id", False) and not getattr(args, "sessions", False):
        return fail('codess: --id requires --sessions')

    registry = resolve_store_root(args)
    requested_project_ids = list(getattr(args, "project_ids", None) or [])
    project_set = getattr(args, "project_set", None)
    all_current = bool(getattr(args, "all_current", False))
    contract_policy = getattr(args, "snapshot_policy", "exact")
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
        return fail('codess: select exactly one of --project-id, --project-set, --all-current, or --dir/--dirs')
    catalog_selection = bool(requested_project_ids) or project_set is not None or all_current
    if catalog_selection:
        try:
            project_scopes = resolve_project_query_scopes(
                registry,
                requested_project_ids or None,
                project_set=project_set,
                all_current=all_current,
                allow_contract_mismatch=contract_policy == "read-compatible",
            )
        except (OSError, ValueError, json.JSONDecodeError, SnapshotError) as exc:
            return fail(f'codess: cannot resolve Project scope: {exc}')
        resolved_roots = [
            Path(selection["project_path"]) for selection in project_scopes
        ]
    else:
        roots, err = resolve_cli_roots(
            args, when_empty=RootsWhenEmpty.PROJECT_ROOT
        )
        if err or roots is None:
            return fail(err or "no roots resolved")
        resolved_roots = [root.resolve() for root in roots]
        project_scopes = []
    snapshot_id = getattr(args, "snapshot_id", None)
    if snapshot_id and (project_set is not None or all_current):
        return fail('codess: --snapshot-id cannot be combined with --project-set or --all-current; put expected snapshots in the Project set')
    if snapshot_id and len(resolved_roots) != 1:
        return fail('codess: --snapshot-id requires exactly one project root')
    try:
        if catalog_selection:
            scope, missing_roots = _open_project_id_query_scope(
                project_scopes,
                snapshot_id=snapshot_id,
                allow_contract_mismatch=contract_policy == "read-compatible",
                source_tokens=source_tokens,
            )
        else:
            scope, missing_roots = _open_query_scope(
                resolved_roots,
                snapshot_id=snapshot_id,
                allow_contract_mismatch=contract_policy == "read-compatible",
                source_tokens=source_tokens,
            )
    except (StoreError, SchemaContractError, SnapshotError) as exc:
        return fail(f'codess: cannot open query stores: {exc}')
    if not scope.stores:
        return fail('No store found. Run session-ingest first.')
    scope.session_names = alias_index(registry)
    for root in missing_roots:
        warn(f'codess: warning: no store found for {sanitize_tabular(root)}')
    if snapshot_id and contract_policy == "read-compatible":
        warn('codess: warning: historical snapshot package differs or was not required to match; hashes and format were verified, mapping parity was not')

    try:
        if getattr(args, "query_action", None):
            return _typed_output(scope, args, snapshot_id=snapshot_id)
        if getattr(args, "output_format", "table") == "jsonl":
            return _jsonl_output(
                scope, args, resolved_roots, limit,
                resolve_store_root(args),
                update_registry=not bool(snapshot_id) and not bool(source_tokens),
            )
        if getattr(args, "output_format", "table") == "csv":
            return _csv_output(
                scope, args, resolved_roots, limit,
                resolve_store_root(args),
                update_registry=not bool(snapshot_id) and not bool(source_tokens),
            )
        if getattr(args, "stats", False):
            return _stats(
                scope, resolved_roots, resolve_store_root(args),
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
        if getattr(args, "coverage", False):
            return _coverage(scope)
        return fail('Specify --tool, --sessions, -sess, --session-id, --permissions, --task-review, --lineage, --audit, --diagnostics, --artifacts, --coverage, --stats, or --taxonomy')
    finally:
        scope.close()



def _coverage(scope: QueryScope) -> int:
    """Print what each selected store mapped, missed, and could not name.

    One block per store rather than a merged total: coverage is a property of
    a vendor's records under one released profile, and averaging Claude with
    Cursor would hide the vendor whose decode is weaker, which is the
    question this report exists to answer.
    """
    for store in scope.stores:
        report = store_coverage(store["conn"])
        coverage = report["coverage"]
        print(tabular_row(store["path"].name, store["project_path"]))
        ratio = coverage["classified_ratio"]
        print(
            f"  events={coverage['admitted_events']} "
            f"classified={coverage['classified_events']} "
            f"unclassified={coverage['unclassified_events']} "
            f"ratio={'n/a' if ratio is None else format(ratio, '.6f')}"
        )
        losses = report["loss"]
        if losses.get("available"):
            unmapped = losses["unmapped_records"]
            qualifier = "" if losses.get("record_loss_recorded") else " (not recorded)"
            print(
                f"  not mapped: source={unmapped['source']} "
                f"record={unmapped['record']}{qualifier} "
                f"| fields incomplete={losses['by_granularity'].get('field', 0)}"
            )
            for reason, count in list(losses["by_reason"].items())[:5]:
                print("    " + tabular_row(reason, count))
        # Evidence no adapter admits, measured from the vendor container rather
        # than the store: a store cannot report what was never written to it, so
        # without this the report's zero was true by construction.
        undecoded = report["undecoded"]
        if undecoded.get("available") and undecoded["undecodable_sessions"]:
            print(
                f"  not decoded: {undecoded['container']} "
                f"sessions={undecoded['undecodable_sessions']} "
                f"prompts={undecoded['undecodable_prompts']} "
                f"({undecoded['disposition']})"
            )
        shapes = report["shapes"]["by_source_record_type"]
        named = ", ".join(
            f"{name}={count}" for name, count in list(shapes.items())[:6]
        )
        print(f"  record shapes ({len(shapes)}): {named}")
    return 0


def _typed_filters(args: argparse.Namespace, source_tokens: set[str] | None) -> dict:
    filters = {}
    values = {
        "event_ids": getattr(args, "event_ids", None),
        "interaction_ids": getattr(args, "interaction_ids", None),
        "model_turn_ids": getattr(args, "model_turn_ids", None),
        "event_kinds": getattr(args, "event_kinds", None),
        "statuses": getattr(args, "query_statuses", None),
        "models": getattr(args, "query_models", None),
        "model_providers": getattr(args, "query_model_providers", None),
        "model_lines": getattr(args, "query_model_lines", None),
        "model_generations": getattr(args, "query_model_generations", None),
        "model_versions": getattr(args, "query_model_versions", None),
        "model_gradations": getattr(args, "query_model_gradations", None),
        "model_variants": getattr(args, "query_model_variants", None),
        "model_revisions": getattr(args, "query_model_revisions", None),
        "reasoning_efforts": getattr(args, "query_reasoning_efforts", None),
        "speed_tiers": getattr(args, "query_speed_tiers", None),
        "service_tiers": getattr(args, "query_service_tiers", None),
        "request_tiers": getattr(args, "query_request_tiers", None),
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
    filters.update(
        {key: value for key, value in values.items() if value is not None}
    )
    if getattr(args, "session_identifier", None):
        filters["session_ids"] = [args.session_identifier]
    if source_tokens:
        filters["source_system_ids"] = [QUERY_SOURCE_FILTERS[token] for token in sorted(source_tokens)]
    return filters


def _typed_output(
    scope: QueryScope, args: argparse.Namespace, *, snapshot_id: str | None,
) -> int:
    """Execute the typed interface and retain exact replay/provenance contracts."""
    action = args.query_action
    if action == "cite":
        if not getattr(args, "result_input", None):
            return fail('codess: query cite requires --result-input')
        if not getattr(args, "summary_file", None):
            return fail('codess: query cite requires --summary-file')
        if not getattr(args, "processor_id", None):
            return fail('codess: query cite requires --processor-id')
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
            return fail(f'codess: cited investigation rejected: {exc}')
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0
    if action == "evidence":
        event_ids = getattr(args, "event_ids", None) or []
        if len(event_ids) != 1:
            return fail('codess: query evidence requires exactly one --event-id')
        matches = []
        for store in scope.stores:
            try:
                matches.append(verify_event_source(store, event_ids[0]))
            except LookupError as exc:
                if "ambiguous" in str(exc):
                    return fail(f'codess: {exc}')
        if len(matches) != 1:
            return fail(f'codess: event {event_ids[0]!r} resolved in {len(matches)} stores; use a globally unique ID')
        allowed = (
            {QUERY_SOURCE_FILTERS[token] for token in scope.source_tokens}
            if scope.source_tokens else None
        )
        if allowed and matches[0]["source"]["source_system_id"] not in allowed:
            return fail('codess: event is outside the selected vendor scope')
        print(json.dumps(matches[0], indent=2, sort_keys=True))
        return 0 if matches[0]["selected"] else 2
    if action == "configurations":
        allowed = (
            {QUERY_SOURCE_FILTERS[token] for token in scope.source_tokens}
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
                return fail(f'codess: {exc}')
            if selected_session is None:
                return fail(f'codess: no Session matches {args.session_identifier!r}')
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
        return fail(error)
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
        return fail(f'codess: typed query rejected: {exc}')
    output_format = getattr(args, "output_format", "table")
    if output_format == "csv":
        return fail('codess: typed results are JSON documents; use jq/sqlite/notebooks for tabular projection')
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
    """Per-Project counts, including a zero row for each root with no store.

    The domain query reports only the stores it opened; a root the user named
    that has no readable store is still part of what was asked for, so it
    appears here as zero rather than being omitted.
    """
    counts = {str(root.resolve()): {"sessions": 0, "events": 0} for root in roots}
    for project, totals in store_counts(scope).items():
        counts[project]["sessions"] += totals["sessions"]
        counts[project]["events"] += totals["events"]
    return counts


def _merge_stats_into_registry(
    counts: dict[str, dict[str, int]], roots: list[Path], store_root: Path,
) -> None:
    for project_path in roots:
        project = str(project_path.resolve())

        def mut(e: dict, values: dict = counts[project]) -> None:
            merge_query_stats(e, values["sessions"], values["events"])

        try:
            update_project_entry(store_root, project, mut)
        except OSError as exc:
            log.warning("Registry update failed for %s: %s", project, exc)


def _jsonl_output(
    scope: QueryScope,
    args: argparse.Namespace,
    roots: list[Path],
    limit: int | None,
    store_root: Path,
    *,
    update_registry: bool,
) -> int:
    """Versioned typed prototype for reports with settled row semantics."""
    if args.sessions:
        for number, row in enumerate(_get_sessions_ordered(scope, limit), 1):
            _emit_jsonl("sessions", {
                "session_id": row["id"], "session_entity_id": row["session_entity_id"],
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
            _merge_stats_into_registry(counts, roots, store_root)
        return 0
    return fail('codess: JSON Lines prototype currently supports --sessions and --stats')


def _csv_output(
    scope: QueryScope,
    args: argparse.Namespace,
    roots: list[Path],
    limit: int | None,
    store_root: Path,
    *,
    update_registry: bool,
) -> int:
    """Emit spreadsheet-safe CSV for settled sessions and stats reports."""
    writer = csv.writer(sys.stdout, lineterminator="\n")
    if args.sessions:
        writer.writerow([
            "session_id", "session_entity_id", "row_number", "source",
            "release", "started_at", "ended_at", "source_project_path",
            "query_project_path", "metadata_json",
        ])
        for number, row in enumerate(_get_sessions_ordered(scope, limit), 1):
            writer.writerow(protect_csv_row([
                row["id"], row["session_entity_id"], number, row["source"],
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
            _merge_stats_into_registry(counts, roots, store_root)
        return 0
    return fail('codess: CSV currently supports --sessions and --stats')


def _stats(
    scope: QueryScope,
    project_roots: list[Path],
    store_root: Path,
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
    _merge_stats_into_registry(counts, project_roots, store_root)
    return 0


def _diagnostics(scope: QueryScope, limit: int | None = None) -> int:
    """Print structured mapping loss/ambiguity without hiding source values."""
    rows = mapping_diagnostics(scope, limit)
    if not rows:
        return 0
    # Header and rows read one key list, so a renamed column cannot leave the
    # header naming one that no longer exists -- which is what `level` did after
    # it became `granularity` which is this drift seen in its own output.
    columns = (
        "project_path", "session_id", "event_id", "granularity", "severity",
        "reason_code", "source_field", "source_value", "mapping_rule", "detail",
    )
    print(tabular_row(*columns))
    for row in rows:
        print(tabular_row(*(row.get(key) for key in columns)))
    return 0


def _artifacts(scope: QueryScope, limit: int | None = None) -> int:
    """Aggregate evidence for artifacts touched by one or more coding systems."""
    rows = artifact_evidence(scope, limit)
    if not rows:
        return 0
    print("project_path\tartifact_kind\tlocator\tsources\tsource_count\toperations\tsession_count\tevidence_count\tproject_correlations")
    for row in rows:
        print(tabular_row(
            row["project_path"], row["kind"], row["locator"], row["sources"],
            row["source_count"], row["operations"], row["session_count"],
            row["evidence"], row["correlations"],
        ))
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
    sess_counts = tool_counts_by_session(sessions)

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
        for _i, sid in enumerate(sess_ids):
            row.append(str(sess_counts[sid].get(tool, 0)))
        row.append(str(all_tools[tool]))
        print("  ".join([sanitize_tabular(row[0]).ljust(max_w), *row[1:]]))
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
        return fail(f'codess: {exc}')
    if not session:
        display = session_identifier if session_identifier is not None else sess_num
        return fail(f'No session {display}')

    modes = show_modes or ["prompt", "pr", "agent", "tool", "perm"]
    show_prompt = "prompt" in modes or "pr" in modes
    show_pr = "pr" in modes
    show_agent = "agent" in modes
    show_tool = "tool" in modes
    show_perm = "perm" in modes

    for row in session_events(session):
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
            elif subtype == "permission_denied" and show_perm:
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
                    with contextlib.suppress(json.JSONDecodeError):
                        inp = json.loads(tool_input)
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
        print("id\tsession_entity_id\tnum\tsource\tname\trelease\tdetails\tstarted_at\tended_at\tproject_path")
        for i, row in enumerate(rows, 1):
            project = row["project_path"] or row["query_project"]
            details = _session_details(row["metadata"])
            print(tabular_row(
                row["id"], row["session_entity_id"], i, row["source"],
                row["name"], row["release"], details, row["started_at"],
                row["ended_at"], project,
            ))
    else:
        print("id\tsession_entity_id\tsource\tname\trelease\tdetails\tstarted_at\tended_at\tproject_path")
        for row in rows:
            project = row["project_path"] or row["query_project"]
            details = _session_details(row["metadata"])
            print(tabular_row(
                row["id"], row["session_entity_id"], row["source"], row["name"],
                row["release"], details, row["started_at"], row["ended_at"],
                project,
            ))
    return 0


def _json_metadata(raw: Any) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _session_details(raw: Any) -> str:
    metadata = _json_metadata(raw)
    details = [
        f"{key}={metadata[key]}"
        for key in ("originator", "source", "storage", "parent_session_id")
        if metadata.get(key) is not None
    ]
    if metadata.get("is_sidechain"):
        details.append("sidechain=true")
    return sanitize_tabular(",".join(details))


def _lineage_id(raw: Any) -> str:
    metadata = _json_metadata(raw)
    return str(metadata.get("call_id") or metadata.get("tool_use_id") or "")


def _lineage(scope: QueryScope, limit: int | None = None) -> int:
    """Print tool calls joined to results using vendor lineage identifiers."""
    rows = tool_lineage(scope, _lineage_id, _timestamp_last_sort_key, limit)
    if not rows:
        return 0
    print(
        "project_path\tsession_id\ttimestamp\ttool_name\tlineage_id\t"
        "status\toutcome\tresult_len"
    )
    for row in rows:
        print(tabular_row(
            row["project_path"], row["session_id"], row["timestamp"],
            row["tool_name"], row["lineage_id"], row["status"], row["outcome"],
            row["result_len"],
        ))
    return 0


def _task_review(scope: QueryScope) -> int:
    """Review Task and Web* tool invocations: counts, descriptions, outcomes."""
    all_tools = tool_totals(scope)

    task_tools = {k: v for k, v in all_tools.items() if k and ("Task" in k or k in ("mcp_task", "Task"))}
    web_tools = {k: v for k, v in all_tools.items() if k and ("Web" in k or "web" in k.lower())}

    print("=== Tool counts ===")
    for name, cnt in sorted(all_tools.items(), key=lambda x: -x[1]):
        print("  " + tabular_row(name, cnt))

    print("\n=== Task tools ===")
    for name, cnt in sorted(task_tools.items(), key=lambda x: -x[1]):
        print("  " + tabular_row(name, cnt))

    print("\n=== Web* tools ===")
    for name, cnt in sorted(web_tools.items(), key=lambda x: -x[1]):
        print("  " + tabular_row(name, cnt))

    # Task/Agent invocations: description, prompt, outcome
    task_calls = task_invocations(scope)

    if task_calls:
        print("\n=== Task/Agent invocations (description, prompt) ===")
        for row in task_calls:
            inp = {}
            if row["tool_input"]:
                with contextlib.suppress(json.JSONDecodeError):
                    inp = json.loads(row["tool_input"])
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
    results = task_results(scope)
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
            print("  " + tabular_row(k, v))

    return 0


def _permissions(scope: QueryScope, limit: int | None = None) -> int:
    """Print permission_denied events."""
    rows = permission_denials(scope, limit)
    if not rows:
        return 0
    print("session_id\tproject_path\ttimestamp\ttool_name")
    for row in rows:
        print(tabular_row(
            row["session_id"], row["project_path"], row["event_at"],
            row["tool_name"],
        ))
    return 0


def _audit(scope: QueryScope, limit: int | None = None) -> int:
    """Print only normalized, evidence-backed audit events."""
    rows = audit_events(scope, _timestamp_last_sort_key, limit)
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
        print(tabular_row(
            row["project_path"], row["session_id"], row["source"],
            row["event_at"], row["subtype"], row["tool_name"], detail,
        ))
    return 0
