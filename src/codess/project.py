"""Project/Git roots, Claude slugs, shared CLI options, and dispatch."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Any

from codess import __version__
from codess.config import (
    CC_PROJECTS,
    RAW_MODE_CHOICES,
    SOURCE_LINKS_FILE,
    SOURCE_LINKS_FORMAT,
    STORE_DIR,
    VERBOSE,
)

# Re-exported: the Claude slug encoding is `helpers`'. `project` carried a
# second copy whose `slug_to_path` lacked the filesystem fallback for
# hyphenated directory names, so the two disagreed on any path containing a
# hyphen -- `spank-py` decoded to the non-existent `spank/py` here (3.5.4).
from codess.helpers import path_to_slug as path_to_slug
from codess.helpers import slug_to_path as slug_to_path

log = logging.getLogger(__name__)

CLI_VERSION = __version__


# --- Git / slug / vendor layout ---


def get_project_root(cwd: Path | None = None) -> Path:
    """Run git rev-parse --show-toplevel; on failure return cwd or Path.cwd()."""
    cwd = cwd or Path.cwd()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        log.warning("git rev-parse failed: %s; using cwd", e)
    return cwd


def get_cc_projects_dir() -> Path:
    """Return CC projects directory."""
    return CC_PROJECTS


def find_slug_for_project(project_path: Path) -> str | None:
    """Find the current or explicitly linked historical Claude project slug."""
    slug = path_to_slug(project_path.resolve())
    projects_dir = get_cc_projects_dir()
    if (projects_dir / slug).is_dir():
        return slug
    link_path = project_path.resolve() / STORE_DIR / SOURCE_LINKS_FILE
    if link_path.exists():
        try:
            value = json.loads(link_path.read_text(encoding="utf-8"))
            if value.get("format") != SOURCE_LINKS_FORMAT:
                raise ValueError("unsupported source-link format")
            for link in value.get("links") or []:
                if not isinstance(link, dict):
                    continue
                source_path = link.get("source_project_path")
                if (
                    link.get("source_system_id") == "anthropic.claude-code"
                    and link.get("selection_state") == "approved"
                    and isinstance(source_path, str)
                    and Path(source_path).is_absolute()
                ):
                    linked_slug = path_to_slug(Path(source_path).resolve())
                    if (projects_dir / linked_slug).is_dir():
                        return linked_slug
        except (OSError, json.JSONDecodeError, ValueError, AttributeError) as exc:
            log.warning("Cannot read Claude source links from %s: %s", link_path, exc)
    return None


def get_cc_session_dir(project_path: Path) -> Path | None:
    """Return CC session dir for project, or None if not found."""
    slug = find_slug_for_project(project_path)
    if slug:
        return get_cc_projects_dir() / slug
    return None


# --- CLI: bool merge, roots, run options (merged from former cli_options.py) ---


def flag_or_env(args: Any, attr: str, env_val: bool) -> bool:
    """True if CLI ``store_true`` *attr* is set or *env_val* (from ``config``) is true."""
    return bool(getattr(args, attr, False) or env_val)


class RootsWhenEmpty(Enum):
    """Default work root when ``--dirs`` / ``--dir`` yield no paths after merge."""

    CWD = "cwd"
    PROJECT_ROOT = "project_path"


def resolve_cli_roots(
    args: Any,
    *,
    when_empty: RootsWhenEmpty,
) -> tuple[list[Path] | None, str | None]:
    """Validate ``--dirs`` if present, merge with ``--dir`` list.

    On empty merged list: use ``Path.cwd()`` (scan) or ``get_project_root()`` (ingest/query).

    Returns ``(roots, err)``. If ``err`` is set, print it and return exit code 1 from the command.
    """
    from codess.helpers import parse_dir_list, validate_dirs_file

    dirs_file = Path(args.dirs) if getattr(args, "dirs", None) else None
    if dirs_file is not None:
        err = validate_dirs_file(dirs_file)
        if err:
            return None, err

    dir_list = getattr(args, "dir_list", None) or []
    supplied_roots = dirs_file is not None or any(
        isinstance(raw, str) and raw.strip() for raw in dir_list
    )
    roots = parse_dir_list(dirs_file, dir_list)
    if not roots:
        if supplied_roots:
            return None, "codess: no valid directory roots were supplied"
        roots = (
            [Path.cwd()]
            if when_empty is RootsWhenEmpty.CWD
            else [get_project_root()]
        )
    for root in roots:
        if not root.exists():
            return None, f"codess: directory root does not exist: {root}"
        if not root.is_dir():
            return None, f"codess: directory root is not a directory: {root}"
    return roots, None


def resolve_registry_directory(args: Any) -> Path:
    """Directory for ``ingested_projects.json`` (``CODESS_REGISTRY``, default ``~/.codess``).

    ``--registry PATH`` overrides that default for this invocation (ingest, scan writes,
    query ``--stats`` updates). Omitted flag → **config** ``REGISTRY``.
    """
    from codess.config import REGISTRY

    raw = getattr(args, "registry", None)
    if raw is None or not str(raw).strip():
        return REGISTRY
    return Path(str(raw).strip()).expanduser()


SCAN_SOURCE_TOKENS = frozenset({"cc", "codex", "cursor"})


def validate_scan_source_for_cli(source: str | None) -> str | None:
    """Return stderr line if ``--source`` is invalid for scan; else ``None``.

    Scan ``--source`` is a comma list (or ``all``). Invalid tokens are a
    **global** invocation error: reject the whole argv, do not partially apply.
    """
    if source is None or not str(source).strip():
        return None
    raw = str(source).strip()
    if raw.lower() == "all":
        return None
    bad: list[str] = []
    for part in raw.split(","):
        t = part.strip().lower()
        if not t:
            continue
        if t not in SCAN_SOURCE_TOKENS:
            bad.append(part.strip())
    if not bad:
        return None
    return (
        "codess: invalid --source token(s) for scan: "
        + ", ".join(repr(x) for x in bad)
        + " (allowed: cc, codex, cursor, all; comma-separated)"
    )


def build_scan_run_options(args: Any) -> dict[str, Any]:
    """Return resolved scan behavior for one CLI invocation.

    Keys: stop_on_error, debug, subagent (bool); recent_days (int | None,
    None meaning no time window); vendors (list[str] | None, None meaning
    all vendors).

    `debug` does not widen the window. Diagnostic output must describe the
    same selection an ordinary run produces, or a reader cannot reproduce
    what they were shown; use `--days 0` to select all time.
    """
    from codess.config import CODESS_DAYS, DEBUG, STOP, SUBAGENT

    stop_on_error = flag_or_env(args, "stop", STOP)
    debug = flag_or_env(args, "debug", DEBUG)
    subagent = flag_or_env(args, "subagent", SUBAGENT)
    recent_days = (
        args.days if getattr(args, "days", None) is not None else CODESS_DAYS
    )
    source_filter = getattr(args, "source", None)
    if source_filter and source_filter.strip().lower() == "all":
        source_filter = None
    vendors = (
        [v.strip().lower() for v in source_filter.split(",") if v.strip()]
        if source_filter
        else None
    )
    return {
        "stop_on_error": stop_on_error,
        "debug": debug,
        "subagent": subagent,
        "recent_days": recent_days,
        "vendors": vendors,
    }


def build_ingest_run_options(args: Any) -> dict[str, Any]:
    """Return resolved ingest behavior for one CLI invocation.

    Keys: stop_on_error, force, debug, redact, strict_mapping, validate_only,
    live_progress, candidate_snapshot (bool); min_size (int); raw_mode (str);
    content_policy (str | None); resource_policy (dict[str, Any] report);
    max_source_bytes, max_cursor_container_bytes, max_events_per_source,
    max_events_per_session, max_context_content_chars (int | None).
    """
    from codess.config import (
        CONTENT_POLICY,
        DEBUG,
        FORCE,
        INGEST_REDACT,
        MIN_SIZE,
        RAW_MODE,
        RESOURCE_POLICY,
        STOP,
        STRICT_MAPPING,
    )
    from codess.resource_policy import load_resource_policy

    raw_ms = getattr(args, "min_size", None)
    # Do not use `or MIN_SIZE`: --min-size 0 is valid (falsy int).
    min_size = int(MIN_SIZE if raw_ms is None else raw_ms)

    policy_path = getattr(args, "resource_policy", None) or RESOURCE_POLICY
    policy = load_resource_policy(policy_path)
    env_overrides: dict[str, int] = {}
    for env_name, key in (
        ("CODESS_MAX_TRANSCRIPT_BYTES", "transcript_bytes"),
        ("CODESS_MAX_CURSOR_CONTAINER_BYTES", "cursor_container_bytes"),
        ("CODESS_MAX_EVENTS_PER_SOURCE", "events_per_source"),
        ("CODESS_MAX_EVENTS_PER_SESSION", "events_per_session"),
        ("CODESS_MAX_CONTEXT_CONTENT_CHARS", "context_content_chars"),
    ):
        if env_name in os.environ:
            try:
                env_overrides[key] = int(os.environ[env_name])
            except ValueError:
                # validate_config reports the corresponding environment error.
                continue
    if env_overrides:
        policy = policy.with_overrides(env_overrides, origin="environment")

    cli_overrides: dict[str, int] = {}
    for attr, key in (
        ("max_source_bytes", "transcript_bytes"),
        ("max_cursor_container_bytes", "cursor_container_bytes"),
        ("max_events_per_source", "events_per_source"),
        ("max_events_per_session", "events_per_session"),
        ("max_context_content_chars", "context_content_chars"),
    ):
        value = getattr(args, attr, None)
        if value is not None:
            cli_overrides[key] = int(value)
    if cli_overrides:
        policy = policy.with_overrides(cli_overrides, origin="command-line")
    if getattr(args, "no_resource_limits", False):
        policy = policy.disabled(origin="--no-resource-limits")
    maximums = policy.maximums

    return {
        "stop_on_error": flag_or_env(args, "stop", STOP),
        "force": flag_or_env(args, "force", FORCE),
        "min_size": min_size,
        "debug": flag_or_env(args, "debug", DEBUG),
        "redact": flag_or_env(args, "redact", INGEST_REDACT),
        "raw_mode": str(getattr(args, "raw_mode", None) or RAW_MODE).lower(),
        "strict_mapping": flag_or_env(args, "strict_mapping", STRICT_MAPPING),
        "content_policy": getattr(args, "content_policy", None) or CONTENT_POLICY,
        "resource_policy": policy.report(),
        "validate_only": bool(getattr(args, "validate", False)),
        "max_source_bytes": maximums["transcript_bytes"],
        "max_cursor_container_bytes": maximums["cursor_container_bytes"],
        "max_events_per_source": maximums["events_per_source"],
        "max_events_per_session": maximums["events_per_session"],
        "max_context_content_chars": maximums["context_content_chars"],
        "live_progress": not bool(getattr(args, "no_progress", False)),
        "candidate_snapshot": bool(getattr(args, "candidate_snapshot", False)),
    }


# --- Argparse + dispatch (minimal main.py delegates here) ---


def build_parser() -> argparse.ArgumentParser:
    """Define all flags once (no subparsers). CMD selects behavior."""
    p = argparse.ArgumentParser(
        prog="codess",
        description="Session record store. CMD is scan | ingest | query.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging (Python logging DEBUG) [CODESS_VERBOSE]",
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {CLI_VERSION}",
        help="Print version and exit",
    )
    p.add_argument(
        "command",
        nargs="?",
        metavar="CMD",
        choices=("scan", "ingest", "query"),
        help="scan: discover projects; ingest: load into .codess/; query: read store",
    )
    p.add_argument(
        "query_action",
        nargs="?",
        choices=(
            "sessions", "overview", "events", "search", "evidence",
            "configurations", "cite",
        ),
        help="query action (typed interface); legacy query report flags remain compatible",
    )

    p.add_argument(
        "--dirs",
        type=str,
        metavar="PATH",
        help="Plain path list or candidate CSV with directory_path (see README: Selecting Project and vendor scope)",
    )
    p.add_argument(
        "--dir",
        action="append",
        dest="dir_list",
        default=None,
        help="Add directory root (repeatable)",
    )
    p.add_argument(
        "--project-id",
        action="append",
        dest="project_ids",
        default=None,
        help="query: select an exact catalog Project ID (repeatable)",
    )
    p.add_argument(
        "--project-set",
        type=Path,
        help="query: select the exact Projects/snapshots in codess.project-set/1",
    )
    p.add_argument(
        "--all-current",
        action="store_true",
        help="query: select every eligible catalog Project with a verified central current snapshot",
    )

    p.add_argument(
        "--source",
        type=str,
        default=None,
        metavar="SPEC",
        help="scan: comma-separated cc,codex,cursor (default all). ingest: cc|codex|cursor|all",
    )
    p.add_argument(
        "--out",
        type=str,
        default="codess_walk.csv",
        help="scan: output CSV path (- for stdout)",
    )
    p.add_argument(
        "--stop",
        action="store_true",
        help="[CODESS_STOP] Stop on first error (scan/ingest); default log and continue",
    )
    p.add_argument(
        "--days",
        type=int,
        metavar="N",
        help="scan: [CODESS_DAYS] include sessions from last N days; 0 means all time",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="scan: trace dirs/CSV; ingest: source_raw etc. (see CODESS_DEBUG)",
    )
    p.add_argument(
        "--subagent",
        action="store_true",
        help="scan: [CC] include sidechain sessions [CODESS_SUBAGENT]",
    )
    p.add_argument(
        "--registry",
        type=str,
        default=None,
        metavar="PATH",
        help="Central registry dir for ingested_projects.json (default CODESS_REGISTRY). "
        "PATH overrides ~/.codess default. scan: also filters CSV to known paths + reg_* "
        "when set; scan always merges index metrics into registry (default or PATH).",
    )

    p.add_argument(
        "--redact",
        action="store_true",
        help="ingest: redact secrets (patterns in config) [CODESS_REDACT]",
    )
    p.add_argument(
        "--no-hash",
        action="store_true",
        help=(
            "skip snapshot/manifest hash verification on read; trusts file "
            "content as-is instead of raising on a mismatch [CODESS_NO_HASH]. "
            "For recovery/debugging only -- every read this bypasses is "
            "logged as a warning."
        ),
    )
    p.add_argument(
        "--no-check",
        action="store_true",
        help=(
            "proceed when the released CoSchema contract does not verify or "
            "does not match the one a store was written under "
            "[CODESS_NO_CONTRACT_CHECK]. Intended for tests and recovery; "
            "each bypass logs a warning, and a store created under it records "
            "`contract_override` in its metadata."
        ),
    )
    p.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="ingest: [CODESS_FORCE] ignore incremental ingest state",
    )
    p.add_argument(
        "--min-size",
        type=int,
        dest="min_size",
        metavar="BYTES",
        default=None,
        help="ingest: [CODESS_MIN_SIZE] skip smaller sources (default from env at import)",
    )
    p.add_argument(
        "--raw-mode",
        choices=RAW_MODE_CHOICES,
        default=None,
        help="ingest: raw evidence mode [CODESS_RAW_MODE] (default reference)",
    )
    p.add_argument(
        "--candidate-snapshot",
        action="store_true",
        help=(
            "ingest: build an immutable candidate snapshot without changing "
            "Project-local or central current pointers"
        ),
    )
    p.add_argument(
        "--strict-mapping",
        action="store_true",
        help="ingest: fail a source on unsupported/lossy records [CODESS_STRICT_MAPPING]",
    )
    p.add_argument(
        "--content-policy",
        type=str,
        metavar="JSON",
        default=None,
        help="ingest: scoped content pre/post-processing policy [CODESS_CONTENT_POLICY]",
    )
    p.add_argument(
        "--resource-policy",
        type=str,
        metavar="JSON",
        default=None,
        help=(
            "ingest: versioned resource-limit policy "
            "[CODESS_RESOURCE_POLICY]"
        ),
    )
    p.add_argument("--validate", action="store_true", help="ingest: parse and validate using temporary stores; do not mutate project or registry")
    p.add_argument(
        "--max-source-bytes",
        type=int,
        metavar="N",
        help="ingest: maximum bytes per Claude/Codex transcript",
    )
    p.add_argument(
        "--max-cursor-container-bytes",
        type=int,
        metavar="N",
        help="ingest: maximum bytes in a Cursor SQLite source container",
    )
    p.add_argument("--max-events-per-source", type=int, metavar="N", help="ingest: maximum normalized events per source")
    p.add_argument("--max-events-per-session", type=int, metavar="N", help="ingest: maximum normalized events per session")
    p.add_argument(
        "--max-context-content-chars",
        type=int,
        metavar="N",
        help=(
            "ingest: maximum normalized characters in each context or "
            "compaction body [CODESS_MAX_CONTEXT_CONTENT_CHARS]"
        ),
    )
    p.add_argument(
        "--no-resource-limits",
        action="store_true",
        help=(
            "ingest: explicitly disable transcript, Cursor-container, event, "
            "and context-content maximums"
        ),
    )
    p.add_argument(
        "--no-progress", action="store_true",
        help="ingest: suppress live progress on stderr; retain structured trace",
    )

    p.add_argument(
        "--tool",
        type=int,
        nargs="?",
        default=None,
        const=0,
        metavar="N",
        help="query: tool-call histogram; N=0 all sessions, N=1 most recent only; bare --tool => 0",
    )
    p.add_argument(
        "--sessions",
        action="store_true",
        help="query: list sessions",
    )
    p.add_argument(
        "--id",
        action="store_true",
        dest="sess_id",
        help="query: with --sessions, number rows (1=most recent)",
    )
    p.add_argument(
        "-sess",
        type=int,
        metavar="N",
        dest="sess",
        help="query: show session content by number from --id list",
    )
    p.add_argument(
        "--session-id",
        dest="session_identifier",
        help="query: show one session by stable global ID or exact vendor session ID",
    )
    p.add_argument(
        "--show",
        nargs="*",
        choices=["prompt", "pr", "agent", "tool", "perm"],
        default=None,
        metavar="MODE",
        help="query: with -sess, which parts to show",
    )
    p.add_argument(
        "--permissions",
        action="store_true",
        help="query: list permission_denied events",
    )
    p.add_argument(
        "--task-review",
        action="store_true",
        help="query: Task/Web tool review block",
    )
    p.add_argument(
        "--lineage",
        action="store_true",
        help="query: tool call/result lineage, status, and missing outcomes",
    )
    p.add_argument(
        "--audit",
        action="store_true",
        help="query: permission denials, tool failures, aborts, and compactions",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="query: globally limit rows for sessions, permissions, lineage, and audit",
    )
    p.add_argument(
        "--stats",
        action="store_true",
        help="query: session/event counts",
    )
    p.add_argument(
        "--taxonomy",
        action="store_true",
        help="query: print event type taxonomy",
    )
    p.add_argument(
        "--diagnostics",
        action="store_true",
        help="query: print structured CoSchema mapping diagnostics",
    )
    p.add_argument(
        "--artifacts",
        action="store_true",
        help="query: correlate artifact evidence across sessions and vendors",
    )
    p.add_argument(
        "--coverage",
        action="store_true",
        help="query: report what was mapped, what was not, and which record "
             "shapes were seen, per store",
    )
    p.add_argument(
        "--snapshot-id",
        help="query: select one retained snapshot (requires exactly one project)",
    )
    p.add_argument(
        "--snapshot-package-policy",
        choices=("exact", "read-compatible"),
        default="exact",
        help="query: require matching package, or explicitly allow same-format historical reads",
    )
    p.add_argument(
        "--output-format", choices=("table", "jsonl", "csv"), default="table",
        help="query: human table, versioned JSON Lines, or CSV rows",
    )
    p.add_argument("--event-id", action="append", dest="event_ids", help="query: stable/global event ID (repeatable)")
    p.add_argument("--interaction-id", action="append", dest="interaction_ids", help="query: Interaction ID (repeatable)")
    p.add_argument("--model-turn-id", action="append", dest="model_turn_ids", help="query: Model Turn ID (repeatable)")
    p.add_argument("--event-kind", action="append", dest="event_kinds", help="query: normalized event kind (repeatable)")
    p.add_argument("--status", action="append", dest="query_statuses", help="query: normalized/source status (repeatable)")
    p.add_argument("--model", action="append", dest="query_models", help="query: exact model name (repeatable)")
    p.add_argument("--model-provider", action="append", dest="query_model_providers", help="query: exact model provider (repeatable)")
    p.add_argument("--model-line", action="append", dest="query_model_lines", help="query: model line, e.g. claude or gpt (repeatable)")
    p.add_argument("--model-generation", action="append", dest="query_model_generations", help="query: model generation, e.g. 5 (repeatable)")
    p.add_argument("--model-version", action="append", dest="query_model_versions", help="query: model version within a generation, e.g. 5.6 (repeatable)")
    p.add_argument("--model-gradation", action="append", dest="query_model_gradations", help="query: capability level, e.g. opus or sol (repeatable)")
    p.add_argument("--model-variant", action="append", dest="query_model_variants", help="query: superseded designator, e.g. codex (repeatable)")
    p.add_argument("--model-revision", action="append", dest="query_model_revisions", help="query: exact model revision (repeatable)")
    p.add_argument("--reasoning-effort", action="append", dest="query_reasoning_efforts", help="query: exact observed reasoning effort (repeatable)")
    p.add_argument("--speed-tier", action="append", dest="query_speed_tiers", help="query: exact observed speed tier (repeatable)")
    p.add_argument("--service-tier", action="append", dest="query_service_tiers", help="query: exact observed service tier (repeatable)")
    p.add_argument("--request-tier", action="append", dest="query_request_tiers", help="query: tier the client requested (repeatable)")
    p.add_argument("--model-mode", action="append", dest="query_model_modes", help="query: exact observed model/collaboration mode (repeatable)")
    p.add_argument("--tool-name", action="append", dest="query_tool_names", help="query: exact tool name (repeatable)")
    p.add_argument("--actor-kind", action="append", dest="query_actor_kinds", help="query: normalized actor kind (repeatable)")
    p.add_argument("--content-role", action="append", dest="query_content_roles", help="query: normalized content role (repeatable)")
    p.add_argument("--origin-kind", action="append", dest="query_origin_kinds", help="query: normalized origin kind (repeatable)")
    p.add_argument("--parent-session-id", action="append", dest="parent_session_ids", help="query: exact parent Session ID (repeatable)")
    p.add_argument("--session-relation", action="append", dest="session_relation_kinds", help="query: Session relation kind (repeatable)")
    p.add_argument("--initiation-kind", action="append", dest="initiation_kinds", help="query: human, autonomous, or unknown Interaction initiation (repeatable)")
    p.add_argument("--artifact", dest="query_artifact", help="query: artifact-path substring")
    p.add_argument("--text", dest="query_text", help="query search: normalized content/tool/artifact substring")
    p.add_argument("--since", type=float, help="query: inclusive Unix timestamp in milliseconds")
    p.add_argument("--until", type=float, help="query: inclusive Unix timestamp in milliseconds")
    p.add_argument("--byte-limit", type=int, default=None, help="typed query: maximum returned inline content bytes (default 16 MiB)")
    p.add_argument("--active-gap-cap", type=int, action="append", dest="active_gap_caps", help="overview: active-time gap cap in minutes (repeatable; default 5,30,120)")
    p.add_argument("--expand", choices=("interaction", "model-turn"), help="events: expand selected IDs to a complete Interaction or Model Turn")
    p.add_argument("--before", type=int, default=0, help="events: include N preceding sequence events around each --event-id")
    p.add_argument("--after", type=int, default=0, help="events: include N following sequence events around each --event-id")
    p.add_argument("--group-repetitions", action="store_true", help="events/search: report bounded exact repetition groups without removing occurrences")
    p.add_argument("--facet-limit", type=int, default=50, help="typed events/search: maximum values per facet and repetition groups")
    p.add_argument("--request", dest="query_request", help="typed query: load codess.query-request/1 JSON")
    p.add_argument("--save-request", help="typed query: atomically save canonical request JSON")
    p.add_argument("--save-result", help="typed query: atomically save codess.query-result/1 JSON")
    p.add_argument("--result-input", help="typed query: restrict by stable IDs from a prior result")
    p.add_argument("--compare-result", help="typed query: compare stable row identities with a prior result; exit 3 when changed")
    p.add_argument(
        "--summary-file",
        type=Path,
        help="query cite: UTF-8 summary body to bind to a saved result",
    )
    p.add_argument(
        "--processor-id",
        help="query cite: identity/version of the human, model, or process producing the summary",
    )
    p.add_argument(
        "--save-investigation",
        type=Path,
        help="query cite: atomically save codess.investigation/1",
    )
    return p


def parse_and_run(argv: list[str] | None = None) -> int:
    """Parse argv (default sys.argv[1:]), apply logging, dispatch scan|ingest|query.

    Lazy-imports command modules to avoid import cycles (they import this package).
    """
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv and raw_argv[0] in {
        "refresh", "catalog", "baseline", "evidence", "package", "schema",
        "session", "storage",
    }:
        from cli.admin_cmd import run as run_admin
        return run_admin(raw_argv)
    if raw_argv and raw_argv[0] == "candidate-review":
        from cli.admin_cmd import run as run_admin
        return run_admin(["catalog", "candidates", *raw_argv[1:]])
    parser = build_parser()
    args = parser.parse_args(raw_argv)

    if args.command is None:
        parser.print_help(sys.stderr)
        return 2

    if args.verbose or VERBOSE:
        logging.basicConfig(level=logging.DEBUG)

    if getattr(args, "no_check", False):
        # schema_contract.contract_check_disabled reads the environment
        # directly, for the same reason as CODESS_NO_HASH below: config's
        # constants have already resolved by the time a flag is parsed.
        os.environ["CODESS_NO_CONTRACT_CHECK"] = "1"
    from codess.config import NO_HASH
    if flag_or_env(args, "no_hash", NO_HASH):
        # fileio.read_hash/rewrite_hash read CODESS_NO_HASH directly (a leaf
        # module cannot import config), so the CLI flag's only effect is
        # setting the same env var those calls already observe.
        os.environ["CODESS_NO_HASH"] = "1"

    from cli.ingest_cmd import run as run_ingest
    from cli.query_cmd import run as run_query
    from cli.scan_cmd import run as run_scan

    if args.command == "scan":
        return run_scan(args)
    if args.command == "ingest":
        return run_ingest(args)
    return run_query(args)


def main() -> int:
    return parse_and_run()


def console_main() -> int:
    """Console-script entry point with quiet downstream-pipe handling."""
    try:
        return main()
    except BrokenPipeError:
        # Avoid a second BrokenPipeError during interpreter shutdown after a
        # downstream consumer such as ``head`` closes stdout.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 0
