"""Administrative command families for catalog, baseline, evidence, and schema."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from codess.baseline_catalog import (
    freeze_reviewed_catalogs, load_baseline_selection, verify_reviewed_catalog,
)
from codess.baseline_operations import apply_project
from codess.baseline_validation import load_policy, run_query_smoke, validate_project
from codess.candidate_review import record_decision, refresh_candidates, validate_policy
from codess.catalog_operations import onboard_catalog, relocate_project, retire_location
from codess.config import CC_PROJECTS
from codess.codex_parent_audit import audit_parentage
from codess.cursor_feature_audit import audit_cursor_features
from codess.evidence import build_evidence_inventory
from codess.fileio import read_json, write_json_atomic
from codess.project_catalog import add_project_location, load_catalog
from codess.schema_evolution import RANK, compare, required
from codess.vendor_audits.claude_features import audit_claude_features


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codess")
    families = parser.add_subparsers(dest="family", required=True)

    catalog = families.add_parser("catalog")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    _candidate_parser(catalog_commands)
    decide = catalog_commands.add_parser("decide")
    decide.add_argument("--catalog", type=Path, required=True)
    decide.add_argument("--project", required=True)
    decide.add_argument("--decision", choices=("approved", "deferred", "excluded"), required=True)
    decide.add_argument("--reviewer")
    decide.add_argument("--notes")
    decide.set_defaults(handler=_catalog_decide)
    onboard = catalog_commands.add_parser("onboard")
    onboard.add_argument("--catalog", type=Path, required=True)
    onboard.add_argument("--registry", type=Path, default=Path.home() / ".codess")
    onboard.add_argument("--review-decision", default="approved")
    onboard.add_argument("--source", choices=("cc", "codex", "cursor", "all"), default="all")
    onboard.add_argument("--raw-mode", choices=("none", "reference", "capture", "seal"), default="reference")
    onboard_mode = onboard.add_mutually_exclusive_group()
    onboard_mode.add_argument("--validate-only", action="store_true")
    onboard_mode.add_argument("--apply", action="store_true")
    onboard.add_argument("--stop-after", choices=("plan", "preflight"))
    onboard.add_argument("--receipt", type=Path)
    onboard.set_defaults(handler=_catalog_onboard)
    location = catalog_commands.add_parser("location")
    location_commands = location.add_subparsers(dest="location_command", required=True)
    for name, handler in (("add", _location_add), ("retire", _location_retire)):
        command = location_commands.add_parser(name)
        command.add_argument("--registry", type=Path, default=Path.home() / ".codess")
        command.add_argument("--project-id", required=True)
        command.add_argument("--path", type=Path, required=True)
        command.set_defaults(handler=handler)
    relocate = catalog_commands.add_parser("relocate")
    relocate.add_argument("--registry", type=Path, default=Path.home() / ".codess")
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

    evidence = families.add_parser("evidence")
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    gather = evidence_commands.add_parser("gather")
    gather.add_argument("--registry", type=Path, default=Path.home() / ".codess")
    gather.add_argument("--cursor-db", type=Path, default=Path.home() / "Library/Application Support/Cursor/User/globalStorage/state.vscdb")
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
    claude.add_argument("--output", type=Path)
    claude.set_defaults(handler=_audit_claude)
    codex = audits.add_parser("codex-parentage")
    codex.add_argument("--active", type=Path, default=Path.home() / ".codex/sessions")
    codex.add_argument("--archive", type=Path, default=Path.home() / ".codex/archived_sessions")
    codex.add_argument("--output", type=Path)
    codex.set_defaults(handler=_audit_codex)
    cursor = audits.add_parser("cursor-features")
    cursor.add_argument("--db", type=Path, default=Path.home() / "Library/Application Support/Cursor/User/globalStorage/state.vscdb")
    cursor.add_argument("--registry", type=Path, default=Path.home() / ".codess")
    cursor.add_argument("--output", type=Path)
    cursor.set_defaults(handler=_audit_cursor)

    schema = families.add_parser("schema")
    schema_commands = schema.add_subparsers(dest="schema_command", required=True)
    compare_parser = schema_commands.add_parser("compare")
    compare_parser.add_argument("old", type=Path)
    compare_parser.add_argument("new", type=Path)
    compare_parser.add_argument("--declared", choices=RANK, default="same")
    compare_parser.set_defaults(handler=_schema_compare)
    return parser


def _apply_arguments(parser) -> None:
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source", choices=("cc", "codex", "cursor", "all"), default="all")
    parser.add_argument("--raw-mode", choices=("none", "reference", "capture", "seal"), default="reference")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--repeat", action="store_true")
    parser.add_argument("--preserve-legacy", action="store_true")
    parser.add_argument("--approve-catalog", type=Path)
    parser.add_argument("--min-size", type=int, default=0)
    parser.add_argument("--no-query-smoke", action="store_true")


def _roots(args) -> list[Path]:
    values = [Path(value).expanduser().resolve() for value in args.dirs]
    if args.dirs_file:
        for line in args.dirs_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                values.append(Path(line).expanduser().resolve())
    return values or [Path.cwd()]


def _catalog_candidates(args) -> int:
    policy = read_json(args.policy) if args.policy else None
    if policy:
        validate_policy(policy)
    report = refresh_candidates(
        _roots(args), vendor_filter=[item.strip() for item in args.source.split(",")],
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


def _catalog_onboard(args) -> int:
    result = onboard_catalog(
        args.catalog, registry=args.registry, repo_root=REPO_ROOT,
        decision=args.review_decision, source=args.source, raw_mode=args.raw_mode,
        apply=args.apply, stop_after=args.stop_after, receipt_path=args.receipt,
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
    if args.report:
        write_json_atomic(args.report, report)
    _json(report)
    return 1 if report["status"] == "rejected" else 0


def _baseline_apply(args) -> int:
    result = apply_project(
        args.project, source=args.source, raw_mode=args.raw_mode,
        registry=args.registry, policy_path=args.policy, repeat=args.repeat,
        preserve_legacy_stores=args.preserve_legacy,
        approve_catalog=args.approve_catalog, min_size=args.min_size,
        query_smoke=not args.no_query_smoke, repo_root=REPO_ROOT,
        report_path=args.report,
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
    _write_optional(args.output, audit_claude_features(args.root, max_files=args.max_files))
    return 0


def _audit_codex(args) -> int:
    _write_optional(args.output, audit_parentage([("active", args.active), ("archive", args.archive)]))
    return 0


def _audit_cursor(args) -> int:
    _write_optional(args.output, audit_cursor_features(args.db, load_catalog(args.registry)))
    return 0


def _schema_compare(args) -> int:
    findings = list(compare(read_json(args.old), read_json(args.new)))
    need = required(findings)
    _json({"required": need, "declared": args.declared, "findings": [
        {"classification": level, "path": path, "message": message}
        for level, path, message in findings
    ]})
    return 1 if need == "manual" or RANK[args.declared] < RANK[need] else 0


def run(argv: list[str]) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return args.handler(args)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"codess: {exc}", file=sys.stderr)
        return 1
