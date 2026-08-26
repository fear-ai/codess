"""Administrative command families for catalog, Sessions, evidence, and schema."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any

from cli.failure import fail, fail_configuration
from codess import reporting
from codess.baseline_catalog import (
    freeze_reviewed_catalogs,
    load_baseline_selection,
    verify_reviewed_catalog,
)
from codess.baseline_operations import apply_project
from codess.baseline_validation import load_policy, run_query_smoke, validate_project
from codess.catalog_operations import onboard_catalog, relocate_project, retire_location
from codess.child_invocation import RunPolicy
from codess.codex_parent_audit import audit_parentage
from codess.config import (
    CC_PROJECTS,
    CODEX_ARCHIVED_SESSIONS,
    CODEX_SESSIONS,
    CURSOR_DATA,
    GB,
    LARGE_EVENT_COUNT,
    LARGE_STORE_BYTES,
    MANIFEST_FILE,
    MAX_RECORD_BYTES,
    RAW_MODE_CHOICES,
    SOURCE_CHOICES,
    STORE_ROOT,
    canonical_raw_mode,
    catalog_root,
)
from codess.cursor_feature_audit import audit_cursor_features
from codess.evidence import build_evidence_inventory
from codess.fileio import read_json, write_json_atomic
from codess.helpers import parse_dir_list, unsafe_traversal_root_reason
from codess.mcp_audit import audit_mcp_interactions
from codess.orientation_audit import audit_orientation
from codess.project import resolve_store_root
from codess.project_annotations import build_project_annotations
from codess.project_catalog import (
    add_project_location,
    catalog_readiness,
    load_catalog,
    set_project_selection_state,
)
from codess.refresh_operations import (
    REFRESH_DESIGNATORS,
    ResolveArgs,
    refresh_projects,
)
from codess.registry_store import PROJECT_LIFECYCLE_STATES, project_lifecycle
from codess.retention import apply_retention_plan, build_retention_plan
from codess.review_project import DiscoveryPolicy, record_decision, refresh_candidates, validate_policy
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
from codess.wallclock import system_clock

REPO_ROOT = Path(__file__).resolve().parents[2]


def _json(value: Any) -> None:
    print(json.dumps(value, sort_keys=True))


def _candidate_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("candidates", parents=[_shared("policy")])
    parser.add_argument("--dir", action="append", dest="dirs", default=[],
        help="a Project directory to include; repeatable",
    )
    parser.add_argument("--dirs", dest="dirs_file", type=Path,
        help="a file listing Project directories, one per line or as candidate CSV",
    )
    parser.add_argument("--candidate-csv", type=Path,
        help="candidate rows to read instead of discovering them",
    )
    parser.add_argument("--catalog", type=Path,
        help="the reviewed-catalog file this command reads or writes",
    )
    parser.add_argument("--source", default="cc,codex,cursor",
        help="restrict to these source systems, comma-separated",
    )
    parser.add_argument("--days", type=int, default=90,
        help="only consider work newer than this many days; 0 for all time",
    )
    parser.add_argument("--git", choices=("none", "local"), default="local",
        help="how far to inspect git: none, or local repository state",
    )
    parser.add_argument("--since",
        help="only count commits after this git date expression",
    )
    parser.add_argument("--discover-git", action="store_true",
        help="treat a git repository found during traversal as a candidate",
    )
    parser.add_argument("--max-depth", type=int, default=2,
        help="how many directory levels below a root to traverse",
    )
    parser.add_argument(
        "--max-directories", type=int, default=None,
        help="stop the scan after this many directories, reporting a partial "
             "result [CODESS_MAX_SCAN_DIRECTORIES]; 0 disables",
    )
    parser.add_argument(
        "--scan-timeout", type=int, default=None,
        help="stop the scan after this long [CODESS_SCAN_TIMEOUT]; "
             "0 disables",
    )
    parser.add_argument(
        "--same-filesystem", action="store_true",
        help="do not descend past a filesystem boundary; by default a crossing "
             "is reported and traversed",
    )
    parser.add_argument("--check-remotes", action="store_true",
        help="read each repository's configured remotes",
    )
    parser.add_argument(
        "--select", dest="selection_state",
        help="keep only Projects whose reviewed selection state is this",
    )
    parser.add_argument("--ownership",
        help="keep only candidates whose recorded ownership is this",
    )
    parser.add_argument("--topic",
        help="keep only candidates carrying this topic annotation",
    )
    parser.add_argument("--format", choices=("table", "jsonl", "catalog"), default="table",
        help="how to render the result",
    )
    parser.add_argument("--out", default="-",
        help="write the result here; - for stdout",
    )
    parser.add_argument("--update-catalog", type=Path,
        help="write the result into this catalog file",
    )
    parser.set_defaults(handler=_catalog_candidates)


def _refresh(args: argparse.Namespace) -> int:
    receipt = args.receipt
    if receipt is None and args.stage != "plan":
        stamp = system_clock().strftime("%Y%m%dT%H%M%S.%fZ")
        receipt = (
            resolve_store_root(args)
            / "reports" / f"refresh-{stamp}.json"
        )
    # Both structures are built here, from `args`, which is what lets
    # `refresh_projects` take four parameters instead of seventeen: every value
    # it needed was read off the namespace at this one adapter and threaded down
    # unchanged.
    result = refresh_projects(
        RunPolicy(
            registry=resolve_store_root(args), repo_root=REPO_ROOT,
            raw_mode=args.raw_mode, min_size=args.min_size, force=args.force,
            resource_policy=args.resource_policy,
            policy_timeout=args.policy_timeout,
        ),
        ResolveArgs(
            project_references=args.projects,
            project_list=args.project_list,
            designator=args.designator,
            source=args.source,
            raw_mode=args.raw_mode,
            baseline_selection=args.baseline_selection,
            reviewed_catalog=args.reviewed,
            large_event_count=args.large_events,
            large_store_bytes=args.large_bytes,
        ),
        stage=args.stage,
        receipt_path=receipt,
    )
    _json(result)
    return 0 if result["status"] in {
        "planned", "preflight_accepted", "applied"
    } else 1


# --- Shared options -----------------------------------------------------------
#
# argparse's own mechanism for an option many subcommands take: declared once on
# a parent parser, inherited by every subparser listing it. `--store` was written
# out 19 times identically, `--output` 11 times, and a twentieth subcommand
# needing one got it the only way the surrounding code demonstrated -- by writing
# the line again.
#
# `add_help=False` on a parent is required: the child adds its own `-h`, and two
# would collide. Inheritance is otherwise invisible to a caller, because argparse
# renders an inherited option exactly as a locally declared one -- which is what
# lets this land without changing a single `--help` line.
#
# A subcommand whose form genuinely differs still declares its own. `--store` is
# `required=True` for one command and repeatable for one `--project-id`, and
# those keep their local declarations rather than bending the shared one.


def _shared(*options: str) -> argparse.ArgumentParser:
    """A parent parser carrying the named shared options.

    Built per call rather than cached because argparse binds a parent's actions
    into each child at construction, and a parser is built once per process.
    """
    parent = argparse.ArgumentParser(add_help=False)
    if "store" in options:
        parent.add_argument(
            "--store", dest="store_root", type=Path, default=STORE_ROOT,
            help="the machine's durable store, holding published Project store "
                 "sets and the registry (default: the configured one)",
        )
    if "output" in options:
        parent.add_argument(
            "--output", type=Path,
            help="write the report to this path instead of stdout",
        )
    if "project-id" in options:
        parent.add_argument(
            "--project-id", required=True,
            help="the Project's stable identifier, as the catalog records it",
        )
    if "source" in options:
        parent.add_argument(
            "--source", choices=SOURCE_CHOICES, default="all",
            help="restrict to one source system (default: all three)",
        )
    if "policy" in options:
        parent.add_argument(
            "--policy", type=Path,
            help="path to the policy file governing this operation",
        )
    if "reviewed" in options:
        parent.add_argument(
            "--reviewed", type=Path, default=catalog_root() / "reviewed-baselines.json",
            help="the reviewed-baselines catalog (default: the configured one)",
        )
    if "directory" in options:
        # `--directory` rather than `--project`, which named three subjects at
        # once: a Project reference under `catalog decide`, a repeatable
        # reference list under `refresh`, and this -- a directory on disk. The
        # flag now says which, and `--project` keeps the two that are references.
        parent.add_argument(
            "--directory", type=Path, required=True,
            help="the Project directory to operate on",
        )
    return parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codess")
    families = parser.add_subparsers(dest="family", required=True)

    refresh = families.add_parser(
        "refresh", parents=[_shared("reviewed", "source", "store")],
    )
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
        "--raw-mode",
        type=canonical_raw_mode,
        choices=("auto", *RAW_MODE_CHOICES),
        default="auto",
        help="how much vendor evidence to retain for each Source",
    )
    refresh.add_argument(
        "--baseline-selection", type=Path,
        default=catalog_root() / "baseline-selection.json",
        help="the reviewed baseline selection to read",
    )
    refresh.add_argument("--large-events", type=int, default=LARGE_EVENT_COUNT,
        help="the Event count above which a Project counts as large",
    )
    refresh.add_argument(
        "--large-bytes", type=int, default=LARGE_STORE_BYTES,
        help="the store size in bytes above which a Project counts as large",
    )
    refresh.add_argument("--min-size", type=int, default=0,
        help="ignore a Source smaller than this many bytes",
    )
    refresh.add_argument("--force", action="store_true",
        help="re-decode every Source, ignoring recorded incremental state",
    )
    refresh.add_argument("--resource-policy", type=Path,
        help="a policy file bounding Source size, Event counts, and content",
    )
    refresh.add_argument("--policy-timeout", type=int, default=3_600,
        help="abandon one Project's ingest after this long",
    )
    refresh.add_argument(
        "--receipt", type=Path,
        help="checkpointed JSON receipt (automatic for preflight/apply)",
    )
    refresh.set_defaults(handler=_refresh)

    catalog = families.add_parser("catalog")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    _candidate_parser(catalog_commands)
    status = catalog_commands.add_parser("status", parents=[_shared("store")])
    status.set_defaults(handler=_catalog_status)
    lifecycle = catalog_commands.add_parser(
        "lifecycle",
        help="every Project this machine has known, with what happened and when",
    )
    lifecycle.add_argument(
        "--store", dest="store_root", type=Path, default=STORE_ROOT,
        help="registry root to read (default: the configured one)",
    )
    lifecycle.add_argument(
        "--state", action="append", default=[],
        choices=PROJECT_LIFECYCLE_STATES,
        help="report only these states; repeatable (default: all)",
    )
    lifecycle.set_defaults(handler=_catalog_lifecycle)
    annotations = catalog_commands.add_parser(
        "annotations", parents=[_shared("output", "reviewed", "store")],
    )
    annotations.add_argument(
        "--baseline-selection", type=Path,
        default=catalog_root() / "baseline-selection.json",
        help="the reviewed baseline selection to read",
    )
    annotations.add_argument(
        "--large-events", type=int, default=LARGE_EVENT_COUNT,
        help="the Event count above which a Project counts as large",
    )
    annotations.add_argument(
        "--large-bytes", type=int, default=LARGE_STORE_BYTES,
        help="the store size in bytes above which a Project counts as large",
    )
    annotations.add_argument("--label", action="append", default=[],
        help="keep only Projects carrying this label; repeatable",
    )
    annotations.add_argument(
        "--format", choices=("table", "json", "csv"), default="table",
        help="how to render the result",
    )
    annotations.set_defaults(handler=_catalog_annotations)
    state = catalog_commands.add_parser("state", parents=[_shared("project-id", "store")])
    state.add_argument(
        "--state",
        choices=(
            "priority", "candidate", "deferred", "excluded", "needs_review",
            "worktree",
        ),
        required=True,
        help="the reviewed selection state to record",
    )
    state.add_argument("--related-project-id",
        help="the Project this one relates to",
    )
    state.add_argument("--note",
        help="free text recorded with the decision",
    )
    state.set_defaults(handler=_catalog_state)
    decide = catalog_commands.add_parser("decide")
    decide.add_argument("--catalog", type=Path, required=True,
        help="the reviewed-catalog file this command reads or writes",
    )
    decide.add_argument("--project", required=True,
        help="a known Project: its identifier, unique name, or catalogued path",
    )
    decide.add_argument("--decision", choices=("approved", "deferred", "excluded"), required=True,
        help="the review outcome to record",
    )
    decide.add_argument("--reviewer",
        help="who made the decision",
    )
    decide.add_argument("--notes",
        help="free text recorded with the decision",
    )
    decide.set_defaults(handler=_catalog_decide)
    onboard = catalog_commands.add_parser(
        "onboard", parents=[_shared("source", "store")],
    )
    onboard.add_argument("--catalog", type=Path, required=True,
        help="the reviewed-catalog file this command reads or writes",
    )
    onboard.add_argument("--review-decision", default="approved",
        help="the review state a newly catalogued Project takes",
    )
    onboard.add_argument(
        "--raw-mode", type=canonical_raw_mode, choices=RAW_MODE_CHOICES,
        default="reference",
        help="how much vendor evidence to retain for each Source",
    )
    onboard_mode = onboard.add_mutually_exclusive_group()
    onboard_mode.add_argument("--validate-only", action="store_true",
        help="run the checks and report, without publishing",
    )
    onboard_mode.add_argument("--apply", action="store_true",
        help="perform the reported operation; without it the run only reports",
    )
    onboard.add_argument("--stop-after", choices=("plan", "preflight"),
        help="end the run after this stage",
    )
    onboard.add_argument("--receipt", type=Path,
        help="write the run receipt here",
    )
    onboard.add_argument(
        "--resource-policy",
        type=Path,
        help="apply one ingest resource-policy file to preflight and apply",
    )
    onboard.set_defaults(handler=_catalog_onboard)
    location = catalog_commands.add_parser("location")
    location_commands = location.add_subparsers(dest="location_command", required=True)
    for name, handler in (("add", _location_add), ("retire", _location_retire)):
        command = location_commands.add_parser(
            name, parents=[_shared("project-id", "store")],
        )
        # A Project location is a directory, so it takes the name every
        # other directory-valued flag takes. `--path` said only that the
        # value is a path, which every `type=Path` flag already says.
        command.add_argument(
            "--directory", type=Path, required=True,
            help="the Project location on this machine",
        )
        command.set_defaults(handler=handler)
    relocate = catalog_commands.add_parser("relocate", parents=[_shared("project-id", "store")])
    relocate.add_argument("--from", dest="old_path", type=Path, required=True,
        help="the location the Project is moving from",
    )
    relocate.add_argument("--to", dest="new_path", type=Path, required=True,
        help="the location the Project is moving to",
    )
    relocate.set_defaults(handler=_catalog_relocate)

    baseline = families.add_parser("baseline")
    baseline_commands = baseline.add_subparsers(dest="baseline_command", required=True)
    validate = baseline_commands.add_parser(
        "validate", parents=[_shared("directory", "policy")],
    )
    validate.add_argument("--raw-store-root", type=Path,
        help="the raw-capture store to verify against",
    )
    validate.add_argument("--query-smoke", action="store_true",
        help="run a query against the result before accepting it",
    )
    validate.add_argument("--report", type=Path,
        help="write the report here",
    )
    validate.set_defaults(handler=_baseline_validate)
    apply_parser = baseline_commands.add_parser(
        "apply", parents=[_shared("directory", "policy", "source")],
    )
    _apply_arguments(apply_parser)
    apply_parser.set_defaults(handler=_baseline_apply)
    freeze = baseline_commands.add_parser("freeze", parents=[_shared("reviewed")])
    # `--file` rather than `--selection`: the subcommand is `baseline freeze`,
    # so the selection is its subject and the flag names which part of it --
    # the file to read. `--selection` also named a state under `catalog candidates`.
    freeze.add_argument(
        "--file", dest="selection", type=Path,
        default=catalog_root() / "baseline-selection.json",
        help="the baseline selection to freeze (default: the configured one)",
    )
    freeze.add_argument("--approved", type=Path, default=catalog_root() / "approved-baselines.json",
        help="the approved-baselines catalog to read or write",
    )
    freeze.set_defaults(handler=_baseline_freeze)
    recover_pointer = baseline_commands.add_parser(
        "recover-pointer", parents=[_shared("directory", "store")],
    )
    recover_pointer.add_argument("--project-id",
        help="a Project's stable identifier",
    )
    recover_pointer.set_defaults(handler=_baseline_recover_pointer)
    recover_manifest = baseline_commands.add_parser("recover-manifest")
    recover_manifest.add_argument("--snapshot", type=Path, required=True,
        help="the snapshot directory to operate on",
    )
    recover_manifest.add_argument(
        "--apply", action="store_true",
        help="write the reconstructed manifest; without it the run only reports",
    )
    recover_manifest.set_defaults(handler=_baseline_recover_manifest)
    verify = baseline_commands.add_parser("verify")
    verify.add_argument("--catalog", type=Path, default=catalog_root() / "reviewed-baselines.json",
        help="the reviewed-catalog file this command reads or writes",
    )
    verify.set_defaults(handler=_baseline_verify)

    package = families.add_parser("package")
    package_commands = package.add_subparsers(dest="package_command", required=True)
    package_verify = package_commands.add_parser("verify")
    package_verify.set_defaults(handler=_package_verify)

    evidence = families.add_parser("evidence")
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    gather = evidence_commands.add_parser("gather", parents=[_shared("output", "store")])
    gather.add_argument("--cursor-db", type=Path, default=CURSOR_DATA / "globalStorage" / "state.vscdb",
        help="the Cursor state database to read",
    )
    gather.add_argument("--claude-root", type=Path, default=CC_PROJECTS,
        help="the Claude Code projects directory to read",
    )
    gather.add_argument("--claude-max-files", type=int, default=200,
        help="stop after reading this many Claude transcripts",
    )
    gather.add_argument("--component-dir", type=Path,
        help="write per-component output here",
    )
    gather.set_defaults(handler=_evidence_gather)
    audit = evidence_commands.add_parser("audit")
    audits = audit.add_subparsers(dest="audit_kind", required=True)
    claude = audits.add_parser("claude-features", parents=[_shared("output")])
    claude.add_argument("--root", type=Path, default=CC_PROJECTS,
        help="the directory to read Sources from",
    )
    claude.add_argument("--max-files", type=int, default=200,
        help="stop after reading this many files",
    )
    claude.add_argument("--max-record-bytes", type=int, default=MAX_RECORD_BYTES,
        help="skip a record larger than this many bytes",
    )
    claude.set_defaults(handler=_audit_claude)
    codex = audits.add_parser("codex-parentage", parents=[_shared("output")])
    codex.add_argument("--active", type=Path, default=CODEX_SESSIONS,
        help="the vendor's live session directory",
    )
    codex.add_argument("--archive", type=Path, default=CODEX_ARCHIVED_SESSIONS,
        help="the vendor's archived session directory",
    )
    codex.set_defaults(handler=_audit_codex)
    codex_features = audits.add_parser("codex-features", parents=[_shared("output")])
    codex_features.add_argument("--active", type=Path, default=CODEX_SESSIONS,
        help="the vendor's live session directory",
    )
    codex_features.add_argument("--archive", type=Path, default=CODEX_ARCHIVED_SESSIONS,
        help="the vendor's archived session directory",
    )
    codex_features.add_argument("--max-files", type=int, default=200,
        help="stop after reading this many files",
    )
    codex_features.add_argument("--max-record-bytes", type=int, default=MAX_RECORD_BYTES,
        help="skip a record larger than this many bytes",
    )
    codex_features.set_defaults(handler=_audit_codex_features)
    cursor = audits.add_parser("cursor-features", parents=[_shared("output", "store")])
    cursor.add_argument("--db", type=Path, default=CURSOR_DATA / "globalStorage" / "state.vscdb",
        help="the database to read",
    )
    cursor.set_defaults(handler=_audit_cursor)
    mcp = audits.add_parser("mcp-interactions", parents=[_shared("output", "store")])
    mcp.add_argument("--codex-rollout", type=Path, action="append", default=[],
        help="one Codex rollout file to read; repeatable",
    )
    mcp.add_argument("--include-excerpts", action="store_true",
        help="include content excerpts in the report",
    )
    mcp.set_defaults(handler=_audit_mcp)
    orientation = audits.add_parser("orientation", parents=[_shared("output", "store")])
    orientation.add_argument(
        "--project-id", action="append", default=[],
        help="a Project's stable identifier",
    )
    orientation.set_defaults(handler=_audit_orientation)

    config_family = families.add_parser("config")
    config_commands = config_family.add_subparsers(dest="config_command", required=True)
    discovery = config_commands.add_parser("discovery")
    discovery.add_argument("--work-root", type=Path,
        help="the directory holding the repositories to consider",
    )
    discovery.add_argument(
        "--no-propose", action="store_true",
        help="report the resolved configuration without reading the work root",
    )
    discovery.set_defaults(handler=_config_discovery)
    schema = families.add_parser("schema")
    schema_commands = schema.add_subparsers(dest="schema_command", required=True)
    compare_parser = schema_commands.add_parser("compare")
    compare_parser.add_argument("old", type=Path)
    compare_parser.add_argument("new", type=Path)
    compare_parser.add_argument("--declared", choices=RANK, default="same",
        help="the highest change class this comparison may report as expected",
    )
    compare_parser.set_defaults(handler=_schema_compare)

    session = families.add_parser("session")
    session_commands = session.add_subparsers(
        dest="session_command", required=True
    )
    # `set_name`, not `name`: the parser and the `--name` option it declares are
    # different things, and reusing one word for both made a reader -- and a type
    # checker -- take the parser for the string.
    set_name = session_commands.add_parser("name", parents=[_shared("project-id", "store")])
    set_name.add_argument("--session-id", required=True,
        help="the Session's vendor identifier",
    )
    set_name.add_argument("--name", required=True,
        help="the operator alias to record for the Session",
    )
    set_name.set_defaults(handler=_session_name)
    unname = session_commands.add_parser("unname", parents=[_shared("project-id", "store")])
    unname.add_argument("--session-id", required=True,
        help="the Session's vendor identifier",
    )
    unname.set_defaults(handler=_session_unname)
    names = session_commands.add_parser("names", parents=[_shared("store")])
    names.add_argument("--project-id",
        help="a Project's stable identifier",
    )
    names.set_defaults(handler=_session_names)

    storage = families.add_parser("storage")
    storage_commands = storage.add_subparsers(dest="storage_command", required=True)
    report = storage_commands.add_parser("report", parents=[_shared("output", "store")])
    report.add_argument(
        "--cursor-db", type=Path,
        default=CURSOR_DATA / "globalStorage" / "state.vscdb",
        help="the Cursor state database to read",
    )
    report.add_argument("--history-dir", type=Path,
        help="a directory of prior observations to compare against",
    )
    report.add_argument(
        "--no-record", action="store_true",
        help="report the observation without writing it to the store",
    )
    report.add_argument("--codess-limit-gb", type=float, default=2.0,
        help="warn when Codess storage exceeds this many gigabytes",
    )
    report.add_argument("--cursor-limit-gb", type=float, default=10.0,
        help="warn when Cursor storage exceeds this many gigabytes",
    )
    report.set_defaults(handler=_storage_report)
    prune = storage_commands.add_parser("prune", parents=[_shared("output", "store")])
    prune.add_argument("--reference-catalog", type=Path, action="append", default=[],
        help="a catalog to compare against; repeatable",
    )
    prune.add_argument("--apply", action="store_true",
        help="perform the reported operation; without it the run only reports",
    )
    prune.add_argument("--working-archives", action="store_true",
        help="include working archives in the assessment",
    )
    prune.add_argument(
        "--keep", type=int, default=None, metavar="N",
        help="keep N snapshots per Project, current included: 1 the current "
             "alone, 2 the current and one past, 0 every one "
             "(default: CODESS_KEEP_SNAPSHOTS)",
    )
    prune.add_argument(
        "--keep-comparison-revisions", action="store_true",
        help="explicitly retain multiple >=1 GiB revisions of one logical source",
    )
    prune.add_argument("--receipt", type=Path,
        help="write the run receipt here",
    )
    prune.set_defaults(handler=_storage_prune)
    registry_prune = storage_commands.add_parser("registry-prune", parents=[_shared("store")])
    registry_prune.add_argument(
        "--apply", action="store_true",
        help="remove the reported entries; without it the run only reports",
    )
    registry_prune.set_defaults(handler=_registry_prune)
    token_validate = storage_commands.add_parser("token-validate", parents=[_shared("output", "store")])
    token_validate.set_defaults(handler=_storage_token_validate)
    return parser


def _apply_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--raw-mode", type=canonical_raw_mode, choices=RAW_MODE_CHOICES,
        default="reference",
        help="how much vendor evidence to retain for each Source",
    )
    parser.add_argument("--store", dest="store_root", type=Path, required=True,
        help="the machine's durable store",
    )
    parser.add_argument("--report", type=Path,
        help="write the report here",
    )
    parser.add_argument("--repeat", action="store_true",
        help="run the ingest a second time to prove it is reproducible",
    )
    parser.add_argument("--approve-catalog", type=Path,
        help="record the outcome in this approval catalog",
    )
    parser.add_argument("--min-size", type=int, default=0,
        help="ignore a Source smaller than this many bytes",
    )
    parser.add_argument(
        "--no-smoke", action="store_true",
        help="skip the post-apply query check that confirms the published "
             "store answers a query",
    )
    parser.add_argument(
        "--resource-policy",
        type=Path,
        help="apply one ingest resource-policy file to both rebuilds",
    )


def _roots(args: argparse.Namespace) -> list[Path]:
    return parse_dir_list(args.dirs_file, args.dirs) or [Path.cwd()]


def _catalog_candidates(args: argparse.Namespace) -> int:
    policy = read_json(args.policy) if args.policy else None
    if policy:
        validate_policy(policy)
    roots = _roots(args)
    for root in roots:
        reason = unsafe_traversal_root_reason(root)
        if reason:
            return fail(f'codess: {reason}; select a project, workspace, or home subtree')
    report = refresh_candidates(
        roots,
        DiscoveryPolicy(
            vendor_filter=[item.strip() for item in args.source.split(",")],
            recent_days=args.days, include_git=args.git == "local",
            discover_git=args.discover_git, max_depth=args.max_depth,
            check_remotes=args.check_remotes,
            max_directories=args.max_directories,
            scan_timeout=args.scan_timeout,
            same_filesystem=args.same_filesystem,
        ),
        candidate_csv=args.candidate_csv, catalog_path=args.catalog,
        since=args.since, policy=policy,
    )
    if args.update_catalog:
        write_json_atomic(args.update_catalog, report)
    rows = [item for item in report["projects"] if (
        (not args.selection_state
         or item.get("curation", {}).get("selection_state") == args.selection_state)
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


def _catalog_decide(args: argparse.Namespace) -> int:
    _json(record_decision(
        args.catalog, project_ref=args.project, decision=args.decision,
        reviewer=args.reviewer, notes=args.notes,
    ))
    return 0


def _catalog_status(args: argparse.Namespace) -> int:
    report = catalog_readiness(args.store_root)
    _json(report)
    return 0 if report["summary"]["not_query_ready_projects"] == 0 else 1


def _catalog_lifecycle(args: argparse.Namespace) -> int:
    """Report every known Project and what happened to it.

    Reconciles the two records that describe a Project -- what scan saw and
    what ingest published -- which disagree in ways nothing else reports: a
    Project scanned and never ingested is absent from the catalog entirely, so
    every enumeration drawn from there inherits the omission.

    Exits nonzero when a Project was scanned and never ingested, because that
    is the state an operator would want to act on rather than merely read.
    """
    rows = project_lifecycle(args.store_root, load_catalog(args.store_root))
    if args.state:
        wanted = set(args.state)
        rows = [row for row in rows if row["state"] in wanted]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    _json({"projects": rows, "summary": counts})
    return 1 if counts.get("scanned") else 0


def _catalog_annotations(args: argparse.Namespace) -> int:
    report = build_project_annotations(
        args.store_root,
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


def _catalog_state(args: argparse.Namespace) -> int:
    _json(set_project_selection_state(
        args.store_root,
        args.project_id,
        args.state,
        related_project_id=args.related_project_id,
        note=args.note,
    ))
    return 0


def _catalog_onboard(args: argparse.Namespace) -> int:
    result = onboard_catalog(
        args.catalog,
        RunPolicy(
            registry=resolve_store_root(args), repo_root=REPO_ROOT,
            raw_mode=args.raw_mode, resource_policy=args.resource_policy,
        ),
        decision=args.review_decision, source=args.source,
        apply=args.apply, stop_after=args.stop_after, receipt_path=args.receipt,
    )
    _json(result)
    return 0 if result["status"] not in {"preflight_rejected", "apply_failed"} else 1


def _location_add(args: argparse.Namespace) -> int:
    _json(add_project_location(args.store_root, args.project_id, args.directory))
    return 0


def _location_retire(args: argparse.Namespace) -> int:
    _json(retire_location(args.store_root, args.project_id, args.directory))
    return 0


def _catalog_relocate(args: argparse.Namespace) -> int:
    _json(relocate_project(args.store_root, args.project_id, args.old_path, args.new_path))
    return 0


def _baseline_validate(args: argparse.Namespace) -> int:
    report = validate_project(
        args.directory, policy=load_policy(args.policy), raw_store_root=args.raw_store_root
    )
    if args.query_smoke and report["status"] != "rejected":
        smoke = run_query_smoke(args.directory.resolve())
        report["query_smoke"] = smoke
        failures = [name for name, item in smoke.items() if not item["passed"]]
        if failures:
            report["errors"].append("query_smoke: " + ", ".join(failures))
            report["status"] = "rejected"
    _write_optional(args.report, report)
    return 1 if report["status"] == "rejected" else 0


def _baseline_apply(args: argparse.Namespace) -> int:
    result = apply_project(
        args.directory,
        RunPolicy(
            registry=resolve_store_root(args), repo_root=REPO_ROOT,
            raw_mode=args.raw_mode, min_size=args.min_size,
            resource_policy=args.resource_policy,
        ),
        source=args.source, policy_path=args.policy, repeat=args.repeat,
        approve_catalog=args.approve_catalog, query_smoke=not args.no_smoke,
        report_path=args.report,
    )
    _json(result)
    return 0


def _baseline_freeze(args: argparse.Namespace) -> int:
    """Freeze the accepted Projects into the approved and reviewed catalogs.

    `catalog_base` is the selection document's own directory, which is what makes
    a selection and its policies portable as a pair. This passed `repo_root=` --
    a keyword the callee does not accept, so every invocation raised `TypeError`
    -- and the value would have been wrong too: resolving a relative `policy`
    against the checkout is exactly what moving the catalog out of it undid.
    """
    selection_path = Path(args.selection).expanduser().resolve()
    _json(freeze_reviewed_catalogs(
        load_baseline_selection(args.selection), approved_path=args.approved,
        reviewed_path=args.reviewed, catalog_base=selection_path.parent,
    ))
    return 0


def _baseline_verify(args: argparse.Namespace) -> int:
    _json(verify_reviewed_catalog(args.catalog))
    return 0


def _package_verify(_args: argparse.Namespace) -> int:
    """Verify every released file and report both digests.

    Takes `_args` and reads none of it: every handler is dispatched as
    `args.handler(args)`, so the parameter is the contract rather than an
    input. The underscore says the value is unused without breaking the call.

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


def _evidence_gather(args: argparse.Namespace) -> int:
    components = {}
    report = build_evidence_inventory(
        args.store_root, cursor_db=args.cursor_db, claude_root=args.claude_root,
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


def _audit_claude(args: argparse.Namespace) -> int:
    _write_optional(args.output, audit_claude_features(
        args.root, max_files=args.max_files,
        max_record_bytes=args.max_record_bytes,
    ))
    return 0


def _audit_codex(args: argparse.Namespace) -> int:
    _write_optional(args.output, audit_parentage([("active", args.active), ("archive", args.archive)]))
    return 0


def _audit_codex_features(args: argparse.Namespace) -> int:
    _write_optional(args.output, audit_codex_features(
        [("active", args.active), ("archive", args.archive)],
        max_files=args.max_files,
        max_record_bytes=args.max_record_bytes,
    ))
    return 0


def _audit_cursor(args: argparse.Namespace) -> int:
    _write_optional(args.output, audit_cursor_features(args.db, load_catalog(args.store_root)))
    return 0


def _audit_mcp(args: argparse.Namespace) -> int:
    _write_optional(args.output, audit_mcp_interactions(
        args.store_root,
        codex_rollouts=args.codex_rollout,
        include_excerpts=args.include_excerpts,
    ))
    return 0


def _audit_orientation(args: argparse.Namespace) -> int:
    report = audit_orientation(
        args.store_root, project_ids=args.project_id,
    )
    _write_optional(args.output, report)
    return 1 if report["summary"]["projects_failed"] else 0


def _config_discovery(args: argparse.Namespace) -> int:
    """Report the resolved discovery configuration, and propose exclusions.

    The first step of the documented setup sequence. It exists as a
    command because the values that matter are what *this process* resolved:
    an operator reading `env` sees what one shell exports, which disagrees
    with the running scan the moment a variable is set elsewhere.

    The logic lives in `tools/setup_discovery.py`, which is separately
    runnable from a checkout without an install. This routes to it rather than
    restating it, so the two cannot diverge.
    """
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from setup_discovery import propose, report_configuration

    from codess.config import DEFAULT_WORK

    configuration = report_configuration()
    proposal = (
        None if args.no_propose
        else propose(args.work_root or DEFAULT_WORK)
    )
    _json({"configuration": configuration, "proposal": proposal})
    return 0


def _schema_compare(args: argparse.Namespace) -> int:
    findings = list(compare(read_json(args.old), read_json(args.new)))
    need = required(findings)
    _json({"required": need, "declared": args.declared, "findings": [
        {"classification": level, "path": path, "message": message}
        for level, path, message in findings
    ]})
    return 1 if need == "manual" or RANK[args.declared] < RANK[need] else 0


def _session_name(args: argparse.Namespace) -> int:
    _json(set_session_name(
        args.store_root, args.project_id, args.session_id, args.name
    ))
    return 0


def _session_unname(args: argparse.Namespace) -> int:
    _json(remove_session_name(
        args.store_root, args.project_id, args.session_id
    ))
    return 0


def _session_names(args: argparse.Namespace) -> int:
    value = load_session_names(args.store_root)
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


def _baseline_recover_pointer(args: argparse.Namespace) -> int:
    """Rebuild a lost or corrupted `current.json` from a retained snapshot.

    `snapshot.recover_current_snapshot` could do this and no command reached
    it, so an operator with a hash mismatch was directed to `codess baseline`,
    which cannot recover a pointer. The operation is safe to run
    unconditionally: it republishes an existing snapshot that still validates
    and creates nothing, so it needs no `--apply` gate.
    """
    from codess.snapshot import SnapshotError, recover_current_snapshot

    try:
        result = recover_current_snapshot(
            args.directory, store_root=args.store_root, project_id=args.project_id,
        )
    except SnapshotError as exc:
        return fail(f'codess: cannot recover current pointer: {exc}')
    _json(result)
    return 0


def _baseline_recover_manifest(args: argparse.Namespace) -> int:
    """Reconstruct a corrupted `manifest.json` from the surviving stores.

    Reports by default and writes only under `--apply`, because unlike the
    pointer recovery this replaces a file: three fields (`parent_snapshot_id`,
    `build_policy`, `build_policy_digest`) are recorded nowhere else and come
    back as null, so an operator should see what is recoverable before
    overwriting what is there.
    """
    from codess.snapshot import SnapshotError, rebuild_manifest

    try:
        manifest = rebuild_manifest(args.snapshot)
    except SnapshotError as exc:
        return fail(f'codess: cannot reconstruct manifest: {exc}')
    if args.apply:
        write_json_atomic(args.snapshot / MANIFEST_FILE, manifest)
    _json({
        "snapshot": str(args.snapshot),
        "written": bool(args.apply),
        "unrecoverable_fields": sorted(
            key for key in
            ("parent_snapshot_id", "build_policy", "build_policy_digest")
            if manifest.get(key) is None
        ),
        "manifest": manifest,
    })
    return 0


def _storage_report(args: argparse.Namespace) -> int:
    if args.codess_limit_gb <= 0 or args.cursor_limit_gb <= 0:
        raise ValueError("storage size limits must be positive")
    report = build_storage_report(
        args.store_root,
        cursor_db=args.cursor_db,
        history_dir=args.history_dir,
        record=not args.no_record,
        codess_limit=GB(args.codess_limit_gb),
        cursor_limit=GB(args.cursor_limit_gb),
    )
    _write_optional(args.output, report)
    return 0


def _registry_prune(args: argparse.Namespace) -> int:
    """Report, and optionally remove, registry entries whose path is gone.

    The registry gains an entry per Project ever scanned and drops none, so a
    test run that scans a temporary directory leaves a permanent record. This
    reports by default and removes only under `--apply`, matching the other
    storage operations: a path can be absent because a volume is unmounted
    rather than because the Project is gone.
    """
    from codess.registry_store import prune_stale_entries

    result = prune_stale_entries(args.store_root, dry_run=not args.apply)
    _json(result)
    return 0


def _storage_prune(args: argparse.Namespace) -> int:
    catalogs = args.reference_catalog or [
        catalog_root() / "approved-baselines.json",
        catalog_root() / "reviewed-baselines.json",
    ]
    result = (
        apply_retention_plan(
            args.store_root, reference_catalogs=catalogs,
            receipt_path=args.receipt,
            include_working_archives=args.working_archives,
            allow_large_comparison_revisions=args.keep_comparison_revisions,
            keep_total=args.keep,
        )
        if args.apply else
        build_retention_plan(
            args.store_root, reference_catalogs=catalogs,
            include_working_archives=args.working_archives,
            allow_large_comparison_revisions=args.keep_comparison_revisions,
            keep_total=args.keep,
        )
    )
    _write_optional(args.output, result)
    return 0 if args.apply or result["safe_to_apply"] else 1


def _storage_token_validate(args: argparse.Namespace) -> int:
    stores, _ = all_store_paths(resolve_store_root(args))
    paths = source_paths(stores, "openai.codex")
    result = validate_codex_token_usage(paths)
    _write_optional(args.output, result)
    return 0


def run(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Before anything else, and for the same reason `scan`, `ingest`, and
    # `query` do it: a misconfigured variable reaches these commands as a wrong
    # store root or an unparseable bound, and every one of them can delete,
    # publish, or rewrite state under it.
    if fail_configuration():
        return 1
    # Attach a sink before dispatch, so an administrative command's events reach
    # somewhere rather than being dropped at `event()`'s first gate. Every one
    # of these commands can delete, publish, or rewrite state, and a run that
    # reports nothing leaves an operator with the exit code alone.
    reporting.configure(
        getattr(args, "report_profile", None),
        privacy=getattr(args, "report_privacy", None),
        redaction_roots={"home": Path.home(), "store": resolve_store_root(args)},
    )
    family = getattr(args, "family", None)
    command = next(
        (getattr(args, name) for name in dir(args) if name.endswith("_command")),
        None,
    )
    reporting.event(
        reporting.code("admin.start"), family=family, command=command,
    )
    try:
        code = args.handler(args)
        reporting.event(
            reporting.code("admin.done"),
            family=family, command=command, exit_code=code,
        )
        return code
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        # Both channels: the event carries the exception family for a structured
        # reader, and `fail` carries its text for the operator. Neither
        # substitutes for the other -- a sink may be a file, and stderr is what a
        # person is looking at.
        reporting.event(
            reporting.code("command.failed"), error_type=type(exc).__name__,
        )
        return fail(f'codess: {exc}')
    finally:
        # A command boundary: a batch smaller than the flush threshold must
        # still reach the sink before the process ends.
        reporting.flush()
