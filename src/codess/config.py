"""Unified config for Codess. Override via env: CODESS_CC_PROJECTS, CODESS_DAYS, etc."""

import os
import platform
import re
from pathlib import Path


def env_bool(key: str, default: str = "0") -> bool:
    """True if env ``key`` is ``1`` / ``true`` / ``yes`` (case-insensitive); else false."""
    return os.environ.get(key, default).lower() in ("1", "true", "yes")


# --- Paths (env overrides) ---
# Fallback anchor for `helpers.is_excluded` when `work_root` is omitted (not CC/Codex/Cursor install roots).
DEFAULT_WORK = Path.home() / "Work"

CC_PROJECTS = Path(
    os.environ.get("CODESS_CC_PROJECTS", str(Path.home() / ".claude" / "projects"))
)
CODEX_SESSIONS = Path(
    os.environ.get("CODESS_CODEX_SESSIONS", str(Path.home() / ".codex" / "sessions"))
)


def _cursor_data() -> Path:
    override = os.environ.get("CODESS_CURSOR_DATA")
    if override:
        return Path(override)
    home = Path.home()
    sys = platform.system()
    if sys == "Darwin":
        return home / "Library/Application Support/Cursor/User"
    if sys == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "Cursor" / "User"
    return home / ".config" / "Cursor" / "User"


CURSOR_DATA = _cursor_data()
# Cursor stores per-workspace state under User/workspaceStorage/<hash>/ (see CursorSchema).
CURSOR_WS = CURSOR_DATA / "workspaceStorage"

# --- Discovery ---
# Top-level folder names under a work root treated as “aggregator” parents (skip as leaf projects in scan canonicalize).
AGGREGATORS = frozenset(
    {"WP", "ZK", "Claw", "Claude", "Cursor", "Github", "CodingTools"}
)
# Path prefixes (relative to work root) excluded as review/backup-style trees in `is_excluded`.
EXCLUDE_REVIEW_DIRS = (
    "CodingTools",
    "MCP/MCPs",
    "Claw/Claws",
    "ZK/ZKs",
    "Spank/sOSS",
    "Claude/Claudes",
)
CODESS_DAYS = int(os.environ.get("CODESS_DAYS", "90"))

# --- Recursion exclude (case-insensitive) ---
# Dirname skip: `helpers.should_skip_recurse` also skips any name starting with "." (covers .git, .venv, …).
EXCLUDE_RECURSE = frozenset({
    "node_modules", "__pycache__",
    "build", "debug", "release", "test", "tests",
    "doc", "docs", "bin", "lib", "libs", "var", "log", "logs",
    "env", "venv", "OLD", "Save",
})

# --- Store layout ---
STORE_DIR = ".codess"
STORE_DB = "sessions.db"
STORE_DB_CC = "sessions_cc.db"
STORE_DB_CODEX = "sessions_codex.db"
STORE_DB_CURSOR = "sessions_cursor.db"
STATE_FILE = "ingest_state.json"
STATS_FILE = "ingested_projects.json"

# --- Registry (central ingested_projects.json, default ~/.codess) ---
REGISTRY = Path(os.environ.get("CODESS_REGISTRY", str(Path.home() / ".codess"))).expanduser()

# --- CLI / logging ---
VERBOSE = env_bool("CODESS_VERBOSE")

# --- Scan (walk / recursion; flag not yet passed through run_scan — see scan_cmd) ---
NOREC = env_bool("CODESS_NOREC")

# --- Debug ---
DEBUG = env_bool("CODESS_DEBUG")

# --- Ingest ---
MIN_SIZE = int(os.environ.get("CODESS_MIN_SIZE", str(20 * 1024)))  # 20 KB
FORCE = env_bool("CODESS_FORCE")

# --- Subagent (CC scan) ---
SUBAGENT = env_bool("CODESS_SUBAGENT")

# --- Ingest redaction default (CLI --redact ORs on top) ---
INGEST_REDACT = env_bool("CODESS_REDACT")

# --- Batch / resilience: stop entire command on first error (otherwise log and continue) ---
STOP = env_bool("CODESS_STOP")

# --- Truncation (display / stored excerpt limits) ---
TRUNCATE_RESPONSE = 2000
TRUNCATE_DIALOG = 200
TRUNCATE_TOOL_RESULT = 2000
TRUNCATE_GREP_PATTERN = 200
TRUNCATE_PROMPT = 2000

# --- Redaction ---
REDACT_PATTERNS = [
    re.compile(r'sk-[a-zA-Z0-9]{20,}', re.I),
    re.compile(r'api[_-]?key["\']?\s*[:=]\s*["\']?[a-zA-Z0-9_\-]{20,}', re.I),
    re.compile(r'bearer\s+[a-zA-Z0-9_\-\.]{20,}', re.I),
]


def get_store_path(project_root: Path, source: str | None = None) -> Path:
    """Return path to sessions DB under project. source='Claude'|'Codex'|'Cursor' uses per-vendor DB."""
    base = project_root / STORE_DIR
    if source == "Claude":
        return base / STORE_DB_CC
    if source == "Codex":
        return base / STORE_DB_CODEX
    if source == "Cursor":
        return base / STORE_DB_CURSOR
    return base / STORE_DB


def get_state_path(project_root: Path) -> Path:
    """Return path to ingest_state.json under project."""
    return project_root / STORE_DIR / STATE_FILE


def get_stats_path(registry_root: Path | None = None) -> Path:
    """Return path to ingested_projects.json (registry of decoded/ingested projects)."""
    root = registry_root if registry_root is not None else REGISTRY
    return root / STATS_FILE


def validate_config() -> list[str]:
    """Return list of validation warnings/errors. Empty if ok."""
    errs = []
    if CODESS_DAYS < 1 or CODESS_DAYS > 3650:
        errs.append(f"CODESS_DAYS={CODESS_DAYS} out of range [1, 3650]")
    if MIN_SIZE < 0:
        errs.append(f"CODESS_MIN_SIZE={MIN_SIZE} must be >= 0")
    if not CC_PROJECTS.is_absolute():
        errs.append(f"CODESS_CC_PROJECTS must be absolute: {CC_PROJECTS}")
    return errs


def get_project_stores(project_root: Path) -> list[Path]:
    """Return existing DB paths: legacy sessions.db first, else per-vendor DBs."""
    base = project_root / STORE_DIR
    legacy = base / STORE_DB
    if legacy.exists():
        return [legacy]
    return [p for p in (base / STORE_DB_CC, base / STORE_DB_CODEX, base / STORE_DB_CURSOR) if p.exists()]
