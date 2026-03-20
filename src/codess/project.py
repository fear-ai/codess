"""Project roots, slug/git/Cursor paths, CLI roots/options, and argparse dispatch."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from codess.config import CC_PROJECTS, CODEX_SESSIONS, CURSOR_DATA, VERBOSE

log = logging.getLogger(__name__)

CLI_VERSION = "0.1.0"


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


def path_to_slug(path: Path) -> str:
    """Encode path to CC slug format."""
    s = path.as_posix()
    if path.is_absolute():
        s = s.lstrip("/")
        return "-" + s.replace("/", "-") if s else ""
    return s.replace("/", "-")


def slug_to_path(slug: str) -> Path:
    """Decode slug to path."""
    if not slug:
        return Path(".")
    if slug.startswith("-"):
        return Path("/" + slug[1:].replace("-", "/"))
    return Path(slug.replace("-", "/"))


def get_cc_projects_dir() -> Path:
    """Return CC projects directory."""
    return CC_PROJECTS


def find_slug_for_project(project_root: Path) -> str | None:
    """Encode project_root; if dir exists under projects, return slug."""
    slug = path_to_slug(project_root.resolve())
    projects_dir = get_cc_projects_dir()
    if (projects_dir / slug).is_dir():
        return slug
    return None


def get_cc_session_dir(project_root: Path) -> Path | None:
    """Return CC session dir for project, or None if not found."""
    slug = find_slug_for_project(project_root)
    if slug:
        return get_cc_projects_dir() / slug
    return None


def get_codex_session_files(project_root: Path) -> list[Path]:
    """Return Codex JSONL files whose session_meta.cwd matches project. Empty if none."""
    project_root = project_root.resolve()
    project_str = str(project_root)
    files = []
    if not CODEX_SESSIONS.exists():
        return files
    for path in sorted(CODEX_SESSIONS.rglob("*.jsonl")):
        try:
            with path.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get("type") == "session_meta":
                            payload = rec.get("payload") or {}
                            cwd = payload.get("cwd") or ""
                            if cwd and (cwd == project_str or cwd.startswith(project_str + "/")):
                                files.append(path)
                            break
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
    return files


def get_cursor_global_db() -> Path | None:
    """Return global state.vscdb path. None if not found. Chat data in v44.9+ is here."""
    db = CURSOR_DATA / "globalStorage" / "state.vscdb"
    return db if db.exists() else None


def get_cursor_workspace_dbs(project_root: Path) -> list[Path]:
    """Return Cursor state.vscdb paths for workspaces matching project. Empty if none."""
    project_root = project_root.resolve()
    project_str = str(project_root)
    ws_dir = CURSOR_DATA / "workspaceStorage"
    if not ws_dir.exists():
        return []
    dbs = []
    for hash_dir in ws_dir.iterdir():
        if not hash_dir.is_dir():
            continue
        ws_json = hash_dir / "workspace.json"
        if not ws_json.exists():
            continue
        try:
            data = json.loads(ws_json.read_text(encoding="utf-8"))
            folder = data.get("folder")
            if isinstance(folder, dict):
                folder = folder.get("path") or ""
            folder = str(folder or "")
            if folder.startswith("file://"):
                folder = folder[7:]
            folder = str(Path(folder).resolve()) if folder else ""
            if folder and (folder == project_str or folder.startswith(project_str + "/")):
                db = hash_dir / "state.vscdb"
                if db.exists():
                    dbs.append(db)
        except (json.JSONDecodeError, OSError):
            continue
    return dbs


# --- CLI: bool merge, roots, run options (merged from former cli_options.py) ---


def flag_or_env(args: Any, attr: str, env_val: bool) -> bool:
    """True if CLI ``store_true`` *attr* is set or *env_val* (from ``config``) is true."""
    return bool(getattr(args, attr, False) or env_val)


class RootsWhenEmpty(Enum):
    """Default work root when ``--dirs`` / ``--dir`` yield no paths after merge."""

    CWD = "cwd"
    PROJECT_ROOT = "project_root"


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
    roots = parse_dir_list(dirs_file, dir_list)
    if not roots:
        roots = (
            [Path.cwd()]
            if when_empty is RootsWhenEmpty.CWD
            else [get_project_root()]
        )
    return roots, None


@dataclass(frozen=True)
class ScanRunOptions:
    """Resolved scan behavior for one CLI invocation."""

    stop_on_error: bool
    debug: bool
    subagent: bool
    norec: bool  # no recursion when walk applies (reserved; not yet passed to run_scan)
    recent_days: int | None  # None when debug bypasses day filter
    vendors: list[str] | None  # None = all vendors


def build_scan_run_options(args: Any) -> ScanRunOptions:
    from codess.config import CODESS_DAYS, DEBUG, NOREC, STOP, SUBAGENT

    stop_on_error = flag_or_env(args, "stop", STOP)
    debug = flag_or_env(args, "debug", DEBUG)
    subagent = flag_or_env(args, "subagent", SUBAGENT)
    norec = flag_or_env(args, "norec", NOREC)
    recent_days = None if debug else (
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
    return ScanRunOptions(
        stop_on_error=stop_on_error,
        debug=debug,
        subagent=subagent,
        norec=norec,
        recent_days=recent_days,
        vendors=vendors,
    )


@dataclass(frozen=True)
class IngestRunOptions:
    stop_on_error: bool
    force: bool
    min_size: int
    debug: bool
    redact: bool


def build_ingest_run_options(args: Any) -> IngestRunOptions:
    from codess.config import DEBUG, FORCE, INGEST_REDACT, MIN_SIZE, STOP

    raw_ms = getattr(args, "min_size", None)
    # Do not use `or MIN_SIZE`: --min-size 0 is valid (falsy int).
    min_size = int(MIN_SIZE if raw_ms is None else raw_ms)

    return IngestRunOptions(
        stop_on_error=flag_or_env(args, "stop", STOP),
        force=flag_or_env(args, "force", FORCE),
        min_size=min_size,
        debug=flag_or_env(args, "debug", DEBUG),
        redact=flag_or_env(args, "redact", INGEST_REDACT),
    )


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
        "--dirs",
        type=str,
        metavar="PATH",
        help="File with directory roots (one path per line; see CoPlan §4.2)",
    )
    p.add_argument(
        "--dir",
        action="append",
        dest="dir_list",
        default=None,
        help="Add directory root (repeatable)",
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
        "--norec",
        action="store_true",
        help="scan: no directory recursion where walk applies [CODESS_NOREC]",
    )
    p.add_argument(
        "--days",
        type=int,
        metavar="N",
        help="scan: [CODESS_DAYS] include sessions from last N days",
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
        metavar="PATH",
        help="ingest: [CODESS_REGISTRY] central registry dir",
    )

    p.add_argument(
        "--redact",
        action="store_true",
        help="ingest: redact secrets (patterns in config) [CODESS_REDACT]",
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
        "--stats",
        action="store_true",
        help="query: session/event counts",
    )
    p.add_argument(
        "--taxonomy",
        action="store_true",
        help="query: print event type taxonomy",
    )
    return p


def parse_and_run(argv: list[str] | None = None) -> int:
    """Parse argv (default sys.argv[1:]), apply logging, dispatch scan|ingest|query.

    Lazy-imports command modules to avoid import cycles (they import this package).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help(sys.stderr)
        return 2

    if args.verbose or VERBOSE:
        logging.basicConfig(level=logging.DEBUG)

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

