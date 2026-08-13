"""Administrative command families for catalog, Sessions, evidence, and schema."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from codess.baseline_catalog import (
    freeze_reviewed_catalogs,
    load_baseline_selection,
    verify_reviewed_catalog,
)
from codess.baseline_operations import apply_project
from codess.baseline_validation import load_policy, run_query_smoke, validate_project
from codess.catalog_operations import onboard_catalog, relocate_project, retire_location
from codess.codex_parent_audit import audit_parentage
from codess.config import (
    CC_PROJECTS,
    CODEX_ARCHIVED_SESSIONS,
    CODEX_SESSIONS,
    CURSOR_DATA,
    GB,
    LARGE_EVENT_COUNT,
    LARGE_STORE_BYTES,
    MAX_RECORD_BYTES,
    RAW_MODE_CHOICES,
    REGISTRY,
)
from codess.cursor_feature_audit import audit_cursor_features
from codess.evidence import build_evidence_inventory
from codess.fileio import read_json, write_json_atomic
from codess.helpers import parse_dir_list, unsafe_traversal_root_reason
from codess.mcp_audit import audit_mcp_interactions
from codess.orientation_audit import audit_orientation
from codess.project_annotations import build_project_annotations
from codess.project_catalog import (
    add_project_location,
    catalog_readiness,
    load_catalog,
    set_project_selection_state,
)
from codess.refresh_operations import (
    REFRESH_DESIGNATORS,
    refresh_projects,
)
from codess.retention import apply_retention_plan, build_retention_plan
from codess.review_project import record_decision, refresh_candidates, validate_policy
from codess.schema_evolution import RANK, compare, required
from codess.session_names import (
    load_session_names,
    remove_session_name,
    set_session_name,
)
from codess.storage_report import all_store_paths, build_storage_report
from codess.token_usage import source_paths, validate_codex_token_usage
from codess.vendor_audits.claude_features import audit_claude_features
from codess.vendor_audits.codex_features import audit_codex_features

REPO_ROOT = Path(__file__).resolve().parents[2]


def _json(value) -> None:
    print(json.dumps(value, sort_keys=True))


def _candidate_parser(subparsers) -> None:
    parser = subparsers.add_parser("candidates")
    parser.add_argument("--dir", action="append", dest="dirs", default=[])
    parser.add_argument("--dirs", dest="dirs_file", type=Path)
    parser.add_argument("--candidate-csv", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--source", default="cc,codex,cursor")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--git", choices=("none", "local"), default="local")
    parser.add_argument("--since")
    parser.add_argument("--discover-git", action="store_true")
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--check-remotes", action="store_true")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--selection")
    parser.add_argument("--ownership")
    parser.add_argument("--topic")
    parser.add_argument("--format", choices=("table", "jsonl", "catalog"), default="table")
    parser.add_argument("--out", default="-")
    parser.add_argument("--update-catalog", type=Path)
    parser.set_defaults(handler=_catalog_candidates)


def _refresh(args) -> int:
    receipt = args.receipt
    if receipt is None and args.stage != "plan":
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        receipt = (
            args.registry.expanduser().resolve()
            / "reports" / f"refresh-{stamp}.json"
        )
    result = refresh_projects(
        args.registry,
        repo_root=REPO_ROOT,
        stage=args.stage,
        project_references=args.projects,
        project_list=args.project_list,
        designator=args.designator,
        source=args.source,
        raw_mode=args.raw_mode,
        baseline_selection=args.baseline_selection,
        reviewed_catalog=args.reviewed,
        large_event_count=args.large_events,
        large_store_bytes=args.large_bytes,
        min_size=args.min_size,
        force=args.force,
        resource_policy=args.resource_policy,
        timeout_seconds=args.timeout_seconds,
        receipt_path=receipt,
    )
    _json(result)
    return 0 if result["status"] in {
        "planned", "preflight_accepted", "applied"
    } else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codess")
    families = parser.add_subparsers(dest="family", required=True)

    refresh = families.add_parser("refresh")
    refresh_selector = refresh.add_mutually_exclusive_group(required=True)
    refresh_selector.add_argument(
        "--project", action="append", dest="projects",
        help="known Project ID, unique name, or active catalog path; repeatable",
    )
    refresh_selector.add_argument(
        "--project-list", type=Path,
        help="JSON, CSV, or line-oriented file of known Project references",
    )
    refresh_selector.add_argument(
        "--designator", choices=sorted(REFRESH_DESIGNATORS),
        help="one computed catalog-annotation cohort",
    )
    refresh.add_argument(
        "--stage", choices=("plan", "preflight", "apply"), default="plan",
        help="plan is read-only; apply first preflights every selected Project",
    )
    refresh.add_argument(
        "--registry", type=Path, default=REGISTRY
    )
    refresh.add_argument(
        "--source", choices=("all", "cc", "codex", "cursor"), default="all"
    )
    refresh.add_argument(
        "--raw-mode",
        choices=("auto", *RAW_MODE_CHOICES),
        default="auto",
    )
    refresh.add_argument(
        "--baseline-selection", type=Path,
        default=REPO_ROOT / "catalog/baseline-selection.json",
    )
    refresh.add_argument(
        "--reviewed", type=Path,
        default=REPO_ROOT / "catalog/reviewed-baselines.json",
    )
    refresh.add_argument("--large-events", type=int, default=LARGE_EVENT_COUNT)
    refresh.add_argument(
        "--large-bytes", type=int, default=LARGE_STORE_BYTES
    )
    refresh.add_argument("--min-size", type=int, default=0)
    refresh.add_argument("--force", action="store_true")
    refresh.add_argument("--resource-policy", type=Path)
    refresh.add_argument("--timeout-seconds", type=int, default=3_600)
    refresh.add_argument(
        "--receipt", type=Path,
        help="checkpointed JSON receipt (automatic for preflight/apply)",
    )
    refresh.set_defaults(handler=_refresh)

    catalog = families.add_parser("catalog")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    _candidate_parser(catalog_commands)
    status = catalog_commands.add_parser("status")
    status.add_argument(
        "--registry", type=Path, default=REGISTRY
    )
    status.set_defaults(handler=_catalog_status)
    annotations = catalog_commands.add_parser("annotations")
    annotations.add_argument(
        "--registry", type=Path, default=REGISTRY
    )
    annotations.add_argument(
        "--baseline-selection", type=Path,
        default=REPO_ROOT / "catalog/baseline-selection.json",
    )
    annotations.add_argument(
        "--reviewed", type=Path,
        default=REPO_ROOT / "catalog/reviewed-baselines.json",
    )
    annotations.add_argument(
        "--large-events", type=int, default=LARGE_EVENT_COUNT
    )
    annotations.add_argument(
        "--large-bytes", type=int, default=LARGE_STORE_BYTES
    )
    annotations.add_argument("--label", action="append", default=[])
    annotations.add_argument(
        "--format", choices=("table", "json", "csv"), default="table"
    )
    annotations.add_argument("--output", type=Path)
    annotations.set_defaults(handler=_catalog_annotations)
    state = catalog_commands.add_parser("state")
    state.add_argument("--registry", type=Path, default=REGISTRY)
    state.add_argument("--project-id", required=True)
    state.add_argument(
        "--state",
        choices=(
            "priority", "candidate", "deferred", "excluded", "needs_review",
            "worktree",
        ),
        required=True,
    )
    state.add_argument("--related-project-id")
    state.add_argument("--note")
    state.set_defaults(handler=_catalog_state)
    decide = catalog_commands.add_parser("decide")
    decide.add_argument("--catalog", type=Path, required=True)
    decide.add_argument("--project", required=True)
    decide.add_argument("--decision", choices=("approved", "deferred", "excluded"), required=True)
    decide.add_argument("--reviewer")
    decide.add_argument("--notes")
    decide.set_defaults(handler=_catalog_decide)
    onboard = catalog_commands.add_parser("onboard")
    onboard.add_argument("--catalog", type=Path, required=True)
    onboard.add_argument("--registry", type=Path, default=REGISTRY)
    onboard.add_argument("--review-decision", default="approved")
    onboard.add_argument("--source", choices=("cc", "codex", "cursor", "all"), default="all")
    onboard.add_argument("--raw-mode", choices=RAW_MODE_CHOICES, default="reference")
    onboard_mode = onboard.add_mutually_exclusive_group()
    onboard_mode.add_argument("--validate-only", action="store_true")
    onboard_mode.add_argument("--apply", action="store_true")
    onboard.add_argument("--stop-after", choices=("plan", "preflight"))
    onboard.add_argument("--receipt", type=Path)
    onboard.add_argument(
        "--resource-policy",
        type=Path,
        help="apply one ingest resource-policy file to preflight and apply",
    )
    onboard.set_defaults(handler=_catalog_onboard)
    location = catalog_commands.add_parser("location")
    location_commands = location.add_subparsers(dest="location_command", required=True)
    for name, handler in (("add", _location_add), ("retire", _location_retire)):
        command = location_commands.add_parser(name)
        command.add_argument("--registry", type=Path, default=REGISTRY)
        command.add_argument("--project-id", required=True)
        command.add_argument("--path", type=Path, required=True)
        command.set_defaults(handler=handler)
    relocate = catalog_commands.add_parser("relocate")
    relocate.add_argument("--registry", type=Path, default=REGISTRY)
    relocate.add_argument("--project-id", required=True)
    relocate.add_argument("--from", dest="old_path", type=Path, required=True)
    relocate.add_argument("--to", dest="new_path", type=Path, required=True)
    relocate.set_defaults(handler=_catalog_relocate)

    baseline = families.add_parser("baseline")
    baseline_commands = baseline.add_subparsers(dest="baseline_command", required=True)
    validate = baseline_commands.add_parser("validate")
    validate.add_argument("--project", type=Path, required=True)
    validate.add_argument("--policy", type=Path)
    validate.add_argument("--raw-store-root", type=Path)
    validate.add_argument("--query-smoke", action="store_true")
    validate.add_argument("--report", type=Path)
    validate.set_defaults(handler=_baseline_validate)
    apply_parser = baseline_commands.add_parser("apply")
    _apply_arguments(apply_parser)
    apply_parser.set_defaults(handler=_baseline_apply)
    freeze = baseline_commands.add_parser("freeze")
    freeze.add_argument("--selection", type=Path, default=REPO_ROOT / "catalog/baseline-selection.json")
    freeze.add_argument("--approved", type=Path, default=REPO_ROOT / "catalog/approved-baselines.json")
    freeze.add_argument("--reviewed", type=Path, default=REPO_ROOT / "catalog/reviewed-baselines.json")
    freeze.set_defaults(handler=_baseline_freeze)
    verify = baseline_commands.add_parser("verify")
    verify.add_argument("--catalog", type=Path, default=REPO_ROOT / "catalog/reviewed-baselines.json")
    verify.set_defaults(handler=_baseline_verify)

    package = families.add_parser("package")
    package_commands = package.add_subparsers(dest="package_command", required=True)
    package_verify = package_commands.add_parser("verify")
    package_verify.set_defaults(handler=_package_verify)

    evidence = families.add_parser("evidence")
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    gather = evidence_commands.add_parser("gather")
    gather.add_argument("--registry", type=Path, default=REGISTRY)
    gather.add_argument("--cursor-db", type=Path, default=CURSOR_DATA / "globalStorage" / "state.vscdb")
    gather.add_argument("--claude-root", type=Path, default=CC_PROJECTS)
    gather.add_argument("--claude-max-files", type=int, default=200)
    gather.add_argument("--component-dir", type=Path)
    gather.add_argument("--output", type=Path)
    gather.set_defaults(handler=_evidence_gather)
    audit = evidence_commands.add_parser("audit")
    audits = audit.add_subparsers(dest="audit_kind", required=True)
    claude = audits.add_parser("claude-features")
    claude.add_argument("--root", type=Path, default=CC_PROJECTS)
    claude.add_argument("--max-files", type=int, default=200)
    claude.add_argument("--max-record-bytes", type=int, default=MAX_RECORD_BYTES)
    claude.add_argument("--output", type=Path)
    claude.set_defaults(handler=_audit_claude)
    codex = audits.add_parser("codex-parentage")
    codex.add_argument("--active", type=Path, default=CODEX_SESSIONS)
    codex.add_argument("--archive", type=Path, default=CODEX_ARCHIVED_SESSIONS)
    codex.add_argument("--output", type=Path)
    codex.set_defaults(handler=_audit_codex)
    codex_features = audits.add_parser("codex-features")
    codex_features.add_argument("--active", type=Path, default=CODEX_SESSIONS)
    codex_features.add_argument("--archive", type=Path, default=CODEX_ARCHIVED_SESSIONS)
    codex_features.add_argument("--max-files", type=int, default=200)
    codex_features.add_argument("--max-record-bytes", type=int, default=MAX_RECORD_BYTES)
    codex_features.add_argument("--output", type=Path)
    codex_features.set_defaults(handler=_audit_codex_features)
    cursor = audits.add_parser("cursor-features")
    cursor.add_argument("--db", type=Path, default=CURSOR_DATA / "globalStorage" / "state.vscdb")
    cursor.add_argument("--registry", type=Path, default=REGISTRY)
    cursor.add_argument("--output", type=Path)
    cursor.set_defaults(handler=_audit_cursor)
    mcp = audits.add_parser("mcp-interactions")
    mcp.add_argument(
        "--registry", type=Path, default=REGISTRY
    )
    mcp.add_argument("--codex-rollout", type=Path, action="append", default=[])
    mcp.add_argument("--include-excerpts", action="store_true")
    mcp.add_argument("--output", type=Path)
    mcp.set_defaults(handler=_audit_mcp)
    orientation = audits.add_parser("orientation")
    orientation.add_argument(
        "--registry", type=Path, default=REGISTRY
    )
    orientation.add_argument(
        "--project-id", action="append", default=[]
    )
    orientation.add_argument("--output", type=Path)
    orientation.set_defaults(handler=_audit_orientation)

    schema = families.add_parser("schema")
    schema_commands = schema.add_subparsers(dest="schema_command", required=True)
    compare_parser = schema_commands.add_parser("compare")
    compare_parser.add_argument("old", type=Path)
    compare_parser.add_argument("new", type=Path)
    compare_parser.add_argument("--declared", choices=RANK, default="same")
    compare_parser.set_defaults(handler=_schema_compare)

    session = families.add_parser("session")
    session_commands = session.add_subparsers(
        dest="session_command", required=True
    )
    name = session_commands.add_parser("name")
    name.add_argument("--registry", type=Path, default=REGISTRY)
    name.add_argument("--project-id", required=True)
    name.add_argument("--session-id", required=True)
    name.add_argument("--name", required=True)
    name.set_defaults(handler=_session_name)
    unname = session_commands.add_parser("unname")
    unname.add_argument("--registry", type=Path, default=REGISTRY)
    unname.add_argument("--project-id", required=True)
    unname.add_argument("--session-id", required=True)
    unname.set_defaults(handler=_session_unname)
    names = session_commands.add_parser("names")
    names.add_argument("--registry", type=Path, default=REGISTRY)
    names.add_argument("--project-id")
    names.set_defaults(handler=_session_names)

    storage = families.add_parser("storage")
    storage_commands = storage.add_subparsers(dest="storage_command", required=True)
    report = storage_commands.add_parser("report")
    report.add_argument("--registry", type=Path, default=REGISTRY)
    report.add_argument(
        "--cursor-db", type=Path,
        default=CURSOR_DATA / "globalStorage" / "state.vscdb",
    )
    report.add_argument("--history-dir", type=Path)
    report.add_argument("--no-record", action="store_true")
    report.add_argument("--codess-limit-gb", type=float, default=2.0)
    report.add_argument("--cursor-limit-gb", type=float, default=10.0)
    report.add_argument("--output", type=Path)
    report.set_defaults(handler=_storage_report)
    prune = storage_commands.add_parser("prune")
    prune.add_argument("--registry", type=Path, default=REGISTRY)
    prune.add_argument("--reference-catalog", type=Path, action="append", default=[])
    prune.add_argument("--apply", action="store_true")
    prune.add_argument("--working-archives", action="store_true")
    prune.add_argument(
        "--keep-comparison-revisions", action="store_true",
        help="explicitly retain multiple >=1 GiB revisions of one logical source",
    )
    prune.add_argument("--receipt", type=Path)
    prune.add_argument("--output", type=Path)
    prune.set_defaults(handler=_storage_prune)
    token_validate = storage_commands.add_parser("token-validate")
    token_validate.add_argument("--registry", type=Path, default=REGISTRY)
    token_validate.add_argument("--output", type=Path)
    token_validate.set_defaults(handler=_storage_token_validate)
    return parser


def _apply_arguments(parser) -> None:
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source", choices=("cc", "codex", "cursor", "all"), default="all")
    parser.add_argument("--raw-mode", choices=RAW_MODE_CHOICES, default="reference")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--repeat", action="store_true")
    parser.add_argument("--approve-catalog", type=Path)
    parser.add_argument("--min-size", type=int, default=0)
    parser.add_argument("--no-query-smoke", action="store_true")
    parser.add_argument(
        "--resource-policy",
        type=Path,
        help="apply one ingest resource-policy file to both rebuilds",
    )


def _roots(args) -> list[Path]:
    return parse_dir_list(args.dirs_file, args.dirs) or [Path.cwd()]


def _catalog_candidates(args) -> int:
    policy = read_json(args.policy) if args.policy else None
    if policy:
        validate_policy(policy)
    roots = _roots(args)
    for root in roots:
        reason = unsafe_traversal_root_reason(root)
        if reason:
            print(
                f"codess: {reason}; select a project, workspace, or home subtree",
                file=sys.stderr,
            )
            return 1
    report = refresh_candidates(
        roots, vendor_filter=[item.strip() for item in args.source.split(",")],
        recent_days=args.days, candidate_csv=args.candidate_csv,
        catalog_path=args.catalog, include_git=args.git == "local",
        discover_git=args.discover_git, max_depth=args.max_depth,
        check_remotes=args.check_remotes, since=args.since, policy=policy,
    )
    if args.update_catalog:
        write_json_atomic(args.update_catalog, report)
    rows = [item for item in report["projects"] if (
        (not args.selection or item.get("curation", {}).get("selection_state") == args.selection)
        and (not args.ownership or item.get("curation", {}).get("ownership") == args.ownership)
        and (not args.topic or item.get("curation", {}).get("topic") == args.topic)
    )]
    output_report = {**report, "projects": rows}
    if args.out != "-":
        output_path = Path(args.out)
        if args.format == "jsonl":
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "".join(json.dumps(item, sort_keys=True) + "\n" for item in rows),
                encoding="utf-8",
            )
        else:
            write_json_atomic(output_path, output_report)
    elif args.format == "catalog":
        print(json.dumps(output_report, indent=2, sort_keys=True))
    elif args.format == "jsonl":
        for item in rows:
            _json(item)
    else:
        print("path\tvendors\tsessions\tgit_last_commit\trecommendation\tdecision")
        for item in rows:
            observations = item.get("observations", {})
            print("\t".join(str(value or "") for value in (
                item["path"], ",".join(observations.get("vendors", {})),
                observations.get("session_count"),
                observations.get("git", {}).get("last_commit_at"),
                item.get("recommendation", {}).get("outcome"),
                item.get("review", {}).get("decision"),
            )))
    return 0


def _catalog_decide(args) -> int:
    _json(record_decision(
        args.catalog, project_ref=args.project, decision=args.decision,
        reviewer=args.reviewer, notes=args.notes,
    ))
    return 0


def _catalog_status(args) -> int:
    report = catalog_readiness(args.registry)
    _json(report)
    return 0 if report["summary"]["not_query_ready_projects"] == 0 else 1


def _catalog_annotations(args) -> int:
    report = build_project_annotations(
        args.registry,
        baseline_selection=args.baseline_selection,
        reviewed_catalog=args.reviewed,
        large_event_count=args.large_events,
        large_store_bytes=args.large_bytes,
    )
    required_labels = set(args.label)
    if required_labels:
        report = {
            **report,
            "projects": [
                item for item in report["projects"]
                if required_labels <= set(item["labels"])
            ],
        }
        report["summary"] = {
            **report["summary"],
            "filtered_projects": len(report["projects"]),
            "required_labels": sorted(required_labels),
        }
    if args.format == "json":
        if args.output:
            write_json_atomic(args.output, report)
        else:
            print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    rows = [{
        "name": item.get("name") or "",
        "labels": ",".join(item["labels"]),
        "query_status": item["query_status"],
        "sources": ",".join(item["source_systems"]),
        "sessions": item["sessions"],
        "events": item["events"],
        "store_bytes": item["normalized_store_bytes"],
        "workspaces": item["workspace_bindings"],
        "path": item.get("path") or "",
        "project_id": item["project_id"],
        "note": item.get("note") or "",
    } for item in report["projects"]]
    fields = (
        "name", "labels", "query_status", "sources", "sessions", "events",
        "store_bytes", "workspaces", "path", "project_id", "note",
    )
    output = io.StringIO()
    if args.format == "csv":
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    else:
        output.write("\t".join(fields) + "\n")
        for row in rows:
            output.write("\t".join(
                str(row[field]).replace("\t", " ").replace("\n", " ")
                for field in fields
            ) + "\n")
    text = output.getvalue()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


def _catalog_state(args) -> int:
    _json(set_project_selection_state(
        args.registry,
        args.project_id,
        args.state,
        related_project_id=args.related_project_id,
        note=args.note,
    ))
    return 0


def _catalog_onboard(args) -> int:
    result = onboard_catalog(
        args.catalog, registry=args.registry, repo_root=REPO_ROOT,
        decision=args.review_decision, source=args.source, raw_mode=args.raw_mode,
        apply=args.apply, stop_after=args.stop_after, receipt_path=args.receipt,
        resource_policy=args.resource_policy,
    )
    _json(result)
    return 0 if result["status"] not in {"preflight_rejected", "apply_failed"} else 1


def _location_add(args) -> int:
    _json(add_project_location(args.registry, args.project_id, args.path))
    return 0


def _location_retire(args) -> int:
    _json(retire_location(args.registry, args.project_id, args.path))
    return 0


def _catalog_relocate(args) -> int:
    _json(relocate_project(args.registry, args.project_id, args.old_path, args.new_path))
    return 0


def _baseline_validate(args) -> int:
    report = validate_project(
        args.project, policy=load_policy(args.policy), raw_store_root=args.raw_store_root
    )
    if args.query_smoke and report["status"] != "rejected":
        smoke = run_query_smoke(args.project.resolve())
        report["query_smoke"] = smoke
        failures = [name for name, item in smoke.items() if not item["passed"]]
        if failures:
            report["errors"].append("query_smoke: " + ", ".join(failures))
            report["status"] = "rejected"
    _write_optional(args.report, report)
    return 1 if report["status"] == "rejected" else 0


def _baseline_apply(args) -> int:
    result = apply_project(
        args.project, source=args.source, raw_mode=args.raw_mode,
        registry=args.registry, policy_path=args.policy, repeat=args.repeat,
        approve_catalog=args.approve_catalog, min_size=args.min_size,
        query_smoke=not args.no_query_smoke, repo_root=REPO_ROOT,
        report_path=args.report,
        resource_policy=args.resource_policy,
    )
    _json(result)
    return 0


def _baseline_freeze(args) -> int:
    _json(freeze_reviewed_catalogs(
        load_baseline_selection(args.selection), approved_path=args.approved,
        reviewed_path=args.reviewed, repo_root=REPO_ROOT,
    ))
    return 0


def _baseline_verify(args) -> int:
    _json(verify_reviewed_catalog(args.catalog, repo_root=REPO_ROOT))
    return 0


def _package_verify(args) -> int:
    """Verify every released file and report both digests.

    This is where exact package verification lives now that the write gate
    consults only the executable contract: it answers "is this working tree
    the reviewed one", which covers the validation fixtures, and it is a
    release and diagnostic question rather than one a store write asks.

    Reports both values because they answer different questions and an
    operator diagnosing a refused write needs to see which one moved.
    """
    from codess.schema_contract import (
        CONTRACT_ROLES,
        contract_digest,
        load_manifest,
        verify_package,
    )

    roles = sorted(load_manifest().get("files", {}))
    _json({
        "format": "codess.package-verification/1",
        "package_digest": verify_package(),
        "contract_digest": contract_digest(),
        "contract_files": sorted(CONTRACT_ROLES),
        "other_files": [role for role in roles if role not in CONTRACT_ROLES],
        "gate": (
            "store writes compare contract_digest; package_digest covers the "
            "released set including validation fixtures"
        ),
    })
    return 0


def _evidence_gather(args) -> int:
    components = {}
    report = build_evidence_inventory(
        args.registry, cursor_db=args.cursor_db, claude_root=args.claude_root,
        claude_max_files=args.claude_max_files, component_reports=components,
    )
    if args.output:
        write_json_atomic(args.output, report)
    if args.component_dir:
        for name, component in components.items():
            write_json_atomic(args.component_dir / f"{name}.json", component)
    _json(report)
    return 0


def _write_optional(path: Path | None, report: dict) -> None:
    if path:
        write_json_atomic(path, report)
    _json(report)


def _audit_claude(args) -> int:
    _write_optional(args.output, audit_claude_features(
        args.root, max_files=args.max_files,
        max_record_bytes=args.max_record_bytes,
    ))
    return 0


def _audit_codex(args) -> int:
    _write_optional(args.output, audit_parentage([("active", args.active), ("archive", args.archive)]))
    return 0


def _audit_codex_features(args) -> int:
    _write_optional(args.output, audit_codex_features(
        [("active", args.active), ("archive", args.archive)],
        max_files=args.max_files,
        max_record_bytes=args.max_record_bytes,
    ))
    return 0


def _audit_cursor(args) -> int:
    _write_optional(args.output, audit_cursor_features(args.db, load_catalog(args.registry)))
    return 0


def _audit_mcp(args) -> int:
    _write_optional(args.output, audit_mcp_interactions(
        args.registry,
        codex_rollouts=args.codex_rollout,
        include_excerpts=args.include_excerpts,
    ))
    return 0


def _audit_orientation(args) -> int:
    report = audit_orientation(
        args.registry, project_ids=args.project_id,
    )
    _write_optional(args.output, report)
    return 1 if report["summary"]["projects_failed"] else 0


def _schema_compare(args) -> int:
    findings = list(compare(read_json(args.old), read_json(args.new)))
    need = required(findings)
    _json({"required": need, "declared": args.declared, "findings": [
        {"classification": level, "path": path, "message": message}
        for level, path, message in findings
    ]})
    return 1 if need == "manual" or RANK[args.declared] < RANK[need] else 0


def _session_name(args) -> int:
    _json(set_session_name(
        args.registry, args.project_id, args.session_id, args.name
    ))
    return 0


def _session_unname(args) -> int:
    _json(remove_session_name(
        args.registry, args.project_id, args.session_id
    ))
    return 0


def _session_names(args) -> int:
    value = load_session_names(args.registry)
    if args.project_id:
        value = {
            **value,
            "names": [
                item for item in value["names"]
                if item.get("project_id") == args.project_id
            ],
        }
    _json(value)
    return 0


def _storage_report(args) -> int:
    if args.codess_limit_gb <= 0 or args.cursor_limit_gb <= 0:
        raise ValueError("storage size limits must be positive")
    report = build_storage_report(
        args.registry,
        cursor_db=args.cursor_db,
        history_dir=args.history_dir,
        record=not args.no_record,
        codess_limit=GB(args.codess_limit_gb),
        cursor_limit=GB(args.cursor_limit_gb),
    )
    _write_optional(args.output, report)
    return 0


def _storage_prune(args) -> int:
    catalogs = args.reference_catalog or [
        REPO_ROOT / "catalog/approved-baselines.json",
        REPO_ROOT / "catalog/reviewed-baselines.json",
    ]
    result = (
        apply_retention_plan(
            args.registry, reference_catalogs=catalogs,
            receipt_path=args.receipt,
            include_working_archives=args.working_archives,
            allow_large_comparison_revisions=args.keep_comparison_revisions,
        )
        if args.apply else
        build_retention_plan(
            args.registry, reference_catalogs=catalogs,
            include_working_archives=args.working_archives,
            allow_large_comparison_revisions=args.keep_comparison_revisions,
        )
    )
    _write_optional(args.output, result)
    return 0 if args.apply or result["safe_to_apply"] else 1


def _storage_token_validate(args) -> int:
    stores, _ = all_store_paths(args.registry.expanduser().resolve())
    paths = source_paths(stores, "openai.codex")
    result = validate_codex_token_usage(paths)
    _write_optional(args.output, result)
    return 0


def run(argv: list[str]) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return args.handler(args)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"codess: {exc}", file=sys.stderr)
        return 1
