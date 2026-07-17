"""Unified config for Codess. Override via env: CODESS_CC_PROJECTS, CODESS_DAYS, etc."""

import os
import platform
import re
from pathlib import Path


_CONFIG_ERRORS: list[str] = []


def env_int(key: str, default: int) -> int:
    """Read an integer env value without making module import fail."""
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        _CONFIG_ERRORS.append(f"{key}={raw!r} must be an integer")
        return default


def env_bool(key: str, default: str = "0") -> bool:
    """True if env ``key`` is ``1`` / ``true`` / ``yes`` (case-insensitive); else false."""
    return os.environ.get(key, default).lower() in ("1", "true", "yes")


# --- Paths (env overrides) ---
# Fallback anchor for `helpers.is_excluded` when `work_root` is omitted (not CC/Codex/Cursor install roots).
DEFAULT_WORK = Path.home() / "Work"

CC_PROJECTS = Path(
    os.environ.get("CODESS_CC_PROJECTS", str(Path.home() / ".claude" / "projects"))
)
_CODEX_SESSIONS_OVERRIDE = os.environ.get("CODESS_CODEX_SESSIONS")
CODEX_SESSIONS = Path(
    _CODEX_SESSIONS_OVERRIDE or str(Path.home() / ".codex" / "sessions")
)
_CODEX_ARCHIVED_OVERRIDE = os.environ.get("CODESS_CODEX_ARCHIVED_SESSIONS")
CODEX_ARCHIVED_SESSIONS: Path | None = (
    Path(_CODEX_ARCHIVED_OVERRIDE)
    if _CODEX_ARCHIVED_OVERRIDE
    else (
        None
        if _CODEX_SESSIONS_OVERRIDE
        else Path.home() / ".codex" / "archived_sessions"
    )
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
    "Code/CodingTools",
    "MCP/MCPs",
    "Claw/Claws",
    "ZK/ZKs",
    "Spank/sOSS",
    "Claude/Claudes",
)
CODESS_DAYS = env_int("CODESS_DAYS", 90)

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

# --- Debug ---
DEBUG = env_bool("CODESS_DEBUG")

# --- Ingest ---
MIN_SIZE = env_int("CODESS_MIN_SIZE", 20 * 1024)  # 20 KB
FORCE = env_bool("CODESS_FORCE")

# --- Subagent (CC scan) ---
SUBAGENT = env_bool("CODESS_SUBAGENT")

# --- Ingest redaction default (CLI --redact ORs on top) ---
INGEST_REDACT = env_bool("CODESS_REDACT")
RAW_MODE = os.environ.get("CODESS_RAW_MODE", "reference").strip().lower()
STRICT_MAPPING = env_bool("CODESS_STRICT_MAPPING")
CONTENT_POLICY = os.environ.get("CODESS_CONTENT_POLICY")
MAX_SOURCE_BYTES = env_int("CODESS_MAX_SOURCE_BYTES", 8 * 1024**3)
MAX_EVENTS_PER_SOURCE = env_int("CODESS_MAX_EVENTS_PER_SOURCE", 500_000)
MAX_EVENTS_PER_SESSION = env_int("CODESS_MAX_EVENTS_PER_SESSION", 250_000)
MAX_CODESS_DB_BYTES = env_int("CODESS_MAX_CODESS_DB_BYTES", 2 * 1024**3)
MAX_CURSOR_DB_BYTES = env_int("CODESS_MAX_CURSOR_DB_BYTES", 10 * 1024**3)

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
    """Return path to ``ingested_projects.json`` — merged project registry.

    Updated by **scan** (index metrics), **ingest** (store counts), and **query**
    (for example, ``--stats``) via ``codess.registry_store``.
    """
    root = registry_root if registry_root is not None else REGISTRY
    return root / STATS_FILE


def validate_config() -> list[str]:
    """Return configuration errors. Empty if configuration is usable."""
    errs = list(_CONFIG_ERRORS)
    if CODESS_DAYS < 0 or CODESS_DAYS > 3650:
        errs.append(f"CODESS_DAYS={CODESS_DAYS} out of range [0, 3650]")
    if MIN_SIZE < 0:
        errs.append(f"CODESS_MIN_SIZE={MIN_SIZE} must be >= 0")
    for name, value in (
        ("CODESS_MAX_SOURCE_BYTES", MAX_SOURCE_BYTES),
        ("CODESS_MAX_EVENTS_PER_SOURCE", MAX_EVENTS_PER_SOURCE),
        ("CODESS_MAX_EVENTS_PER_SESSION", MAX_EVENTS_PER_SESSION),
        ("CODESS_MAX_CODESS_DB_BYTES", MAX_CODESS_DB_BYTES),
        ("CODESS_MAX_CURSOR_DB_BYTES", MAX_CURSOR_DB_BYTES),
    ):
        if value <= 0:
            errs.append(f"{name}={value} must be > 0")
    if RAW_MODE not in {"none", "reference", "capture", "seal"}:
        errs.append(
            f"CODESS_RAW_MODE={RAW_MODE!r} must be none, reference, capture, or seal"
        )
    if not CC_PROJECTS.is_absolute():
        errs.append(f"CODESS_CC_PROJECTS must be absolute: {CC_PROJECTS}")
    if not CODEX_SESSIONS.is_absolute():
        errs.append(f"CODESS_CODEX_SESSIONS must be absolute: {CODEX_SESSIONS}")
    if CODEX_ARCHIVED_SESSIONS is not None and not CODEX_ARCHIVED_SESSIONS.is_absolute():
        errs.append(
            "CODESS_CODEX_ARCHIVED_SESSIONS must be absolute: "
            f"{CODEX_ARCHIVED_SESSIONS}"
        )
    if not CURSOR_DATA.is_absolute():
        errs.append(f"CODESS_CURSOR_DATA must be absolute: {CURSOR_DATA}")
    return errs


def get_project_stores(project_root: Path) -> list[Path]:
    """Return current snapshot stores, falling back to legacy working paths."""
    from codess.snapshot import current_store_paths

    current = current_store_paths(project_root)
    if current:
        return current
    base = project_root / STORE_DIR
    legacy = base / STORE_DB
    if legacy.exists():
        return [legacy]
    return [p for p in (base / STORE_DB_CC, base / STORE_DB_CODEX, base / STORE_DB_CURSOR) if p.exists()]
