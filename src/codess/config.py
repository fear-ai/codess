"""Unified config for Codess. Override via env: CODESS_CC_PROJECTS, CODESS_DAYS, etc."""

import os
import platform
import re
from pathlib import Path

# --- Paths (env overrides) ---
# Default work root when no explicit dir given (for is_excluded fallback)
DEFAULT_WORK = Path.home() / "Work"

CC_PROJECTS = Path(
    os.environ.get("CODESS_CC_PROJECTS", str(Path.home() / ".claude" / "projects"))
)
CODEX_SESSIONS = Path(
    os.environ.get("CODESS_CODEX_SESSIONS", str(Path.home() / ".codex" / "sessions"))
)
CODEX_HISTORY = Path(
    os.environ.get("CODESS_CODEX_HISTORY", str(Path.home() / ".codex" / "history.jsonl"))
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
CURSOR_WS = CURSOR_DATA / "workspaceStorage"

# --- Discovery ---
AGGREGATORS = frozenset(
    {"WP", "ZK", "Claw", "Claude", "Cursor", "Github", "CodingTools"}
)
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
EXCLUDE_RECURSE = frozenset({
    ".git", ".*", "node_modules", "__pycache__",
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

# --- Debug ---
DEBUG = os.environ.get("CODESS_DEBUG", "0").lower() in ("1", "true", "yes")

# --- Ingest ---
MIN_SIZE = int(os.environ.get("CODESS_MIN_SIZE", str(20 * 1024)))  # 20 KB
FORCE = os.environ.get("CODESS_FORCE", "0").lower() in ("1", "true", "yes")

# --- Truncation ---
TRUNCATE_RESPONSE = 1000
TRUNCATE_DIALOG = 200
TRUNCATE_TOOL_RESULT = 500
TRUNCATE_GREP_PATTERN = 120
TRUNCATE_PROMPT = 10000

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


def get_project_stores(project_root: Path) -> list[Path]:
    """Return existing DB paths: legacy sessions.db first, else per-vendor DBs."""
    base = project_root / STORE_DIR
    legacy = base / STORE_DB
    if legacy.exists():
        return [legacy]
    return [p for p in (base / STORE_DB_CC, base / STORE_DB_CODEX, base / STORE_DB_CURSOR) if p.exists()]
