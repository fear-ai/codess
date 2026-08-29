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

from codess import __version__, reporting
from codess.config import (
    CC_PROJECTS,
    RAW_MODE_CHOICES,
    SOURCE_LINKS_FILE,
    SOURCE_LINKS_FORMAT,
    STORE_DIR,
    VENDOR_KEYS,
    VERBOSE,
    canonical_raw_mode,
    link_source_system,
)

# Re-exported: the Claude slug encoding is `helpers`'. `project` carried a
# second copy whose `slug_to_path` lacked the filesystem fallback for
# hyphenated directory names, so the two disagreed on any path containing a
# hyphen -- a hyphenated directory decoded to a non-existent nested path (3.5.4).
from codess.helpers import path_to_slug as path_to_slug
from codess.helpers import slug_to_path as slug_to_path
from codess.investigation import INVESTIGATION_FORMAT
from codess.query_api import RESULT_FORMAT
from codess.reporting.levels import PRIVACY_PROFILES as REPORTING_PRIVACY
from codess.reporting.levels import PROFILES as REPORTING_PROFILES
from codess.settings import resolve

log = logging.getLogger(__name__)

CLI_VERSION = __version__


# --- Git / slug / vendor layout ---


def _git_output(cwd: Path, *arguments: str) -> str | None:
    """One `git rev-parse` reading, or None when git cannot answer.

    A missing git, a directory that is not a repository, and a timeout are all
    "no Git information available" rather than failures: discovery falls back
    to the path it was given.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", *arguments],
            cwd=cwd, capture_output=True, text=True, timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        log.warning("git rev-parse %s failed: %s", " ".join(arguments), exc)
        return None
    output = result.stdout.strip()
    return output if result.returncode == 0 and output else None


def get_project_root(cwd: Path | None = None) -> Path:
    """The repository a path belongs to, resolving a worktree to its parent.

    Resolved from `--git-common-dir` rather than `--show-toplevel`, because the
    latter returns the *worktree* root, and a clone reached through a second
    checkout would otherwise be a second repository with one location each.

    **This is repository identity, not Project identity.** A linked worktree is
    its own Project -- every vendor records it separately, which
    [CoSchema](../../CoSchema.md#project) states with the evidence -- and the
    catalog relates the two with `related_project_id` rather than merging them.
    What this function answers is which repository a path belongs to, which is
    what `project_locations` and the worktree relation are derived from.

    `--git-common-dir` names the shared `.git` directory: identical for every
    worktree of a repository, distinct across repositories. Its parent is the
    repository root. It is relative to the working directory when the
    repository is ordinary and absolute from a linked worktree, so it is
    resolved against `cwd` before the parent is taken.

    A bare repository reports `.` and has no worktree, so it falls back to
    `--show-toplevel`, which fails there and leaves `cwd` -- the same answer
    as before for a case that has no checkout to attribute anyway.
    """
    cwd = cwd or Path.cwd()
    common = _git_output(cwd, "--git-common-dir")
    if common:
        resolved = Path(common)
        if not resolved.is_absolute():
            resolved = cwd / resolved
        # A bare repository's common dir is the repository itself, so it has
        # no parent worktree to name; anything else is `<root>/.git`.
        if resolved.name == ".git":
            return resolved.parent.resolve()
    toplevel = _git_output(cwd, "--show-toplevel")
    return Path(toplevel) if toplevel else cwd


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
                    link_source_system(link) == "anthropic.claude-code"
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


def cc_session_files(cc_dir: Path) -> tuple[list[Path], list[Path]]:
    """Claude's transcripts under one project slug: main sessions and subagents.

    Two globs that must stay together, asked at three call sites -- `walk_sessions`
    twice and `ingest_sources` once. Claude writes a Session at the top level and
    a delegated one under `<session>/subagents/`, so a caller reading only
    `*.jsonl` silently omits every subagent Session, and one reading `**/*.jsonl`
    silently conflates the two kinds.

    Returned as a pair rather than a merged list because the distinction is the
    point: `--subagent` selects whether the second half participates, and a
    caller that cannot tell them apart cannot honour it.
    """
    return (
        sorted(cc_dir.glob("*.jsonl")),
        sorted(cc_dir.glob("*/subagents/**/*.jsonl")),
    )


def get_cc_session_dir(project_path: Path) -> Path | None:
    """Return CC session dir for project, or None if not found."""
    slug = find_slug_for_project(project_path)
    if slug:
        return get_cc_projects_dir() / slug
    return None


# --- CLI: bool merge, roots, run options (merged from former cli_options.py) ---


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


def resolve_store_root(args: Any) -> Path:
    """Directory for ``projects_state.json`` (``CODESS_STORE_ROOT``, default ``~/.codess``).

    ``--store PATH`` overrides that default for this invocation (ingest, scan writes,
    query ``--stats`` updates). Omitted flag -> **config** ``STORE_ROOT``.

    Accepts a ``Path`` or a string because a declaration may supply either, and
    normalizes both. Every consumer should reach the value through here rather
    than off ``args``: the flag is declared 22 times, and a direct read is what
    makes a differing declaration invisible.
    """
    from codess.config import STORE_ROOT

    # The precedence is `settings.resolve`'s, stated once there rather than
    # restated here. What this adds is one narrow rejection and one conversion.
    raw = resolve(args, "store_root", STORE_ROOT)
    # `.` and `..` are refused rather than replaced by the default. A relative
    # location names wherever the command happened to run, so accepting one puts
    # the durable store somewhere the operator did not choose and a later run
    # will not find. Substituting the default silently would be worse: the
    # command would succeed against the wrong store.
    #
    # `""` is caught by the same test, because `Path("")` is `Path(".")`. So is
    # `--store ""`, which argparse converts before the value arrives -- the two
    # are indistinguishable here, and a caller who wants the working directory
    # writes `--store "$PWD"`, which is unambiguous.
    #
    # `config.validate_config` reports the same condition for the variable, so an
    # operator sees it before a command runs; this is the guard for the flag and
    # for a library caller who never passed through validation.
    if raw is None:
        return STORE_ROOT
    # Compared as a `Path`, because `str("")` is `""` while `Path("")` is
    # `Path(".")` -- the string test alone lets the empty value through.
    candidate = Path(raw)
    if str(candidate) in (".", "..") or candidate.name == "..":
        raise ValueError(
            f"store root {str(raw)!r} is a relative location; "
            "give an absolute path, or omit --store for the default"
        )
    # `expanduser` and not `strip`: a trailing space is legal in a POSIX path,
    # so stripping one silently retargets the store to a different directory
    # than the operator named.
    return candidate.expanduser()


SCAN_SOURCE_TOKENS = frozenset(VENDOR_KEYS)


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
    from codess.config import DAYS, DEBUG, STOP, SUBAGENT

    stop_on_error = resolve(args, "stop_on_error", STOP)
    debug = resolve(args, "debug", DEBUG)
    subagent = resolve(args, "subagent", SUBAGENT)
    recent_days = resolve(args, "days", DAYS)
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
    content_policy, resource_policy (Path | str | None -- a `Path` from the
    flag, a `str` from the environment variable, so a reader normalizes);
    max_source_bytes, max_cursor_container_bytes, max_events_per_source,
    max_events_per_session, max_context_content_chars (int | None).
    """
    from codess.config import (
        CONTENT_POLICY,
        DEBUG,
        FORCE,
        MIN_SIZE,
        RAW_MODE,
        REDACT,
        RESOURCE_POLICY,
        STOP,
        STRICT_MAPPING,
    )
    from codess.resource_policy import load_resource_policy

    # `resolve` distinguishes absent from zero, which `or MIN_SIZE` cannot:
    # `--min-size 0` is a valid bound and would be read as unset.
    min_size = int(resolve(args, "min_size", MIN_SIZE))

    policy_path = resolve(args, "resource_policy", RESOURCE_POLICY)
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
    if getattr(args, "no_resource", False):
        policy = policy.disabled(origin="--no-resource")
    maximums = policy.maximums

    return {
        "stop_on_error": resolve(args, "stop_on_error", STOP),
        "force": resolve(args, "force", FORCE),
        "min_size": min_size,
        "debug": resolve(args, "debug", DEBUG),
        "redact": resolve(args, "redact", REDACT),
        # Canonicalized here as well as by the argparse `type`, because settings
        # resolution is reachable from a library caller that never built a parser.
        "raw_mode": canonical_raw_mode(
            str(resolve(args, "raw_mode", RAW_MODE)).lower()
        ),
        "strict_mapping": resolve(args, "strict_mapping", STRICT_MAPPING),
        "content_policy": resolve(args, "content_policy", CONTENT_POLICY),
        "resource_policy": policy.report(),
        "validate_only": bool(getattr(args, "validate", False)),
        "max_source_bytes": maximums["transcript_bytes"],
        "max_cursor_container_bytes": maximums["cursor_container_bytes"],
        "max_events_per_source": maximums["events_per_source"],
        "max_events_per_session": maximums["events_per_session"],
        "max_context_content_chars": maximums["context_content_chars"],
        "live_progress": not bool(getattr(args, "no_progress", False)),
        "report_profile": getattr(args, "report_profile", None),
        "report_privacy": getattr(args, "report_privacy", None),
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
        type=Path,
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
        # A comma-separated vendor spec rather than a filesystem path, so `str`
        # is the subject rather than the absence of a converter.
        type=str,
        default=None,
        metavar="SPEC",
        help="scan: comma-separated cc,codex,cursor (default all). ingest: cc|codex|cursor|all",
    )
    p.add_argument(
        "--out",
        # `str` rather than `Path` because `-` is a sentinel for stdout, not a
        # filename: converting it would make the sentinel a relative path named
        # `-` that the writer would then have to detect and undo.
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
        "--store",
        dest="store_root",
        # `Path`, matching the 21 declarations in `admin_cmd`: one flag name
        # yielding two types is a difference a caller moving between command
        # families cannot see. `resolve_store_root` normalizes either, so this
        # changes the declared contract rather than the behaviour.
        type=Path,
        default=None,
        metavar="PATH",
        help="Central registry dir for projects_state.json (default CODESS_STORE_ROOT). "
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
        type=canonical_raw_mode,
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
        # A path to a JSON file, not JSON text: `ingest_cmd` reads it with
        # `Path(...).expanduser()`, so the metavar named the file's content.
        type=Path,
        metavar="PATH",
        default=None,
        help="ingest: scoped content pre/post-processing policy [CODESS_CONTENT_POLICY]",
    )
    p.add_argument(
        "--resource-policy",
        type=Path,
        metavar="PATH",
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
        "--no-resource",
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
        "--report-profile", choices=tuple(sorted(REPORTING_PROFILES)),
        default=None,
        help="operational reporting volume and destination [CODESS_REPORT_PROFILE]",
    )
    p.add_argument(
        "--report-privacy", choices=REPORTING_PRIVACY,
        default=None,
        help="how much a reported field reveals: local verbatim, shared "
             "root-relative, strict root token only [CODESS_REPORT_PRIVACY]",
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
        "--snapshot-policy",
        dest="snapshot_policy",
        choices=("exact", "read-compatible"),
        default="exact",
        help="query: require the store's recorded contract to match, or explicitly "
             "allow same-format historical reads",
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
    p.add_argument(
        "--save-result",
        help=f"typed query: atomically save {RESULT_FORMAT} JSON",
    )
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
        help=f"query cite: atomically save {INVESTIGATION_FORMAT}",
    )
    return p


def parse_and_run(argv: list[str] | None = None) -> int:
    """Parse argv (default sys.argv[1:]), apply logging, dispatch scan|ingest|query.

    Lazy-imports command modules to avoid import cycles (they import this package).
    """
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv and raw_argv[0] in {
        "refresh", "catalog", "baseline", "config", "evidence", "package",
        "schema", "session", "storage",
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

    # `fileio` and `schema_contract` read their variables directly, because a
    # leaf module cannot import `config` without a cycle -- so a flag reaches
    # them by writing the variable. `settings.LEAF_VISIBLE` declares which
    # settings that applies to, and `apply_leaf_visible` performs the write once
    # instead of the two hand-written assignments this replaced.
    from codess.config import NO_HASH
    from codess.settings import apply_leaf_visible

    if resolve(args, "no_hash", NO_HASH):
        args.no_hash = True
    for variable in apply_leaf_visible(args):
        log.debug("verification bypassed by request: %s", variable)

    from cli.ingest_cmd import run as run_ingest
    from cli.query_cmd import run as run_query
    from cli.scan_cmd import run as run_scan

    handlers = {"scan": run_scan, "ingest": run_ingest}
    handler = handlers.get(args.command, run_query)

    # One command boundary for every family, rather than a flush before each of
    # the query command's 105 return points. `query` is configured here too:
    # scan and ingest configure their own profiles because they register vendor
    # roots for path redaction, and a second `configure` would discard those.
    if args.command not in handlers:
        reporting.configure(
            getattr(args, "report_profile", None),
            privacy=getattr(args, "report_privacy", None),
            redaction_roots={"home": Path.home()},
        )
    try:
        return handler(args)
    finally:
        # A batch below the flush threshold must still reach the sink before
        # the process ends. In `finally` so an error path reports what it had
        # recorded rather than losing it with the exception.
        reporting.flush()


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
