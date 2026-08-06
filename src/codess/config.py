"""Unified config for Codess. Override via env: CODESS_CC_PROJECTS, CODESS_DAYS, etc."""

import os
import platform
import re
from pathlib import Path

from codess.resource_policy import BUILTIN_MAXIMUMS


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


def env_str(key: str, default: str | None) -> str | None:
    """Read a string env value, or ``default`` (including ``None``) if unset."""
    return os.environ.get(key, default)


def env_path(key: str, default: str) -> Path:
    """Read a path env value as ``Path(value)``, or ``Path(default)`` if unset."""
    return Path(os.environ.get(key, default))


def env_raw_mode(key: str, default: str) -> str:
    """Read CODESS_RAW_MODE, normalized like the hand-written form it replaces."""
    return os.environ.get(key, default).strip().lower()


def env_expanded_path(key: str, default: str) -> Path:
    """Read a path env value and expand ``~``, for registry-style roots."""
    return Path(os.environ.get(key, default)).expanduser()


# --- Table-driven env vars: one row per var, uniform (key, reader, default)
# shape. Adding a variable is a table row, not a new module-level call site.
# A row fits here when its value is `reader(key, default)` alone -- no
# cross-referencing another CODESS_* var and no platform branching. Three
# variables do not fit and stay hand-written below: CODEX_ARCHIVED_SESSIONS
# (default depends on whether CODEX_SESSIONS was itself overridden) and
# CURSOR_DATA (default depends on platform.system()). CODEX_SESSIONS could
# be table-driven on its own, but its override is read into
# _CODEX_SESSIONS_OVERRIDE first specifically so CODEX_ARCHIVED_SESSIONS can
# branch on whether an override was given -- moving it into the table would
# require reading it back out afterward, i.e. no simplification.
_IS_ENV_TABLE = (
    ("CODESS_DAYS", env_int, 90),
    ("CODESS_VERBOSE", env_bool, "0"),
    ("CODESS_DEBUG", env_bool, "0"),
    ("CODESS_MIN_SIZE", env_int, 20 * 1024),  # 20 KB
    ("CODESS_FORCE", env_bool, "0"),
    ("CODESS_SUBAGENT", env_bool, "0"),
    ("CODESS_REDACT", env_bool, "0"),
    ("CODESS_STRICT_MAPPING", env_bool, "0"),
    ("CODESS_MAX_TRANSCRIPT_BYTES", env_int, BUILTIN_MAXIMUMS["transcript_bytes"]),
    (
        "CODESS_MAX_CURSOR_CONTAINER_BYTES", env_int,
        BUILTIN_MAXIMUMS["cursor_container_bytes"],
    ),
    (
        "CODESS_MAX_EVENTS_PER_SOURCE", env_int,
        BUILTIN_MAXIMUMS["events_per_source"],
    ),
    (
        "CODESS_MAX_EVENTS_PER_SESSION", env_int,
        BUILTIN_MAXIMUMS["events_per_session"],
    ),
    (
        "CODESS_MAX_CONTEXT_CONTENT_CHARS", env_int,
        BUILTIN_MAXIMUMS["context_content_chars"],
    ),
    ("CODESS_MAX_CODESS_DB_BYTES", env_int, 2 * 1024**3),
    ("CODESS_MAX_CURSOR_DB_BYTES", env_int, 10 * 1024**3),
    ("CODESS_CC_PROJECTS", env_path, str(Path.home() / ".claude" / "projects")),
    ("CODESS_RAW_MODE", env_raw_mode, "reference"),
    ("CODESS_CONTENT_POLICY", env_str, None),
    ("CODESS_RESOURCE_POLICY", env_str, None),
    ("CODESS_REGISTRY", env_expanded_path, str(Path.home() / ".codess")),
    ("CODESS_STOP", env_bool, "0"),
)
_IS_ENV_VALUES = {key: reader(key, default) for key, reader, default in _IS_ENV_TABLE}


# --- Paths (env overrides) ---
# Fallback anchor for `helpers.is_excluded` when `work_root` is omitted (not CC/Codex/Cursor install roots).
DEFAULT_WORK = Path.home() / "Work"

CC_PROJECTS = _IS_ENV_VALUES["CODESS_CC_PROJECTS"]
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
CODESS_DAYS = _IS_ENV_VALUES["CODESS_DAYS"]

# --- Store layout ---
STORE_DIR = ".codess"
STORE_DB = "sessions.db"
STORE_DB_CC = "sessions_cc.db"
STORE_DB_CODEX = "sessions_codex.db"
STORE_DB_CURSOR = "sessions_cursor.db"
STATE_FILE = "ingest_state.json"
STATS_FILE = "ingested_projects.json"

# --- Registry (central ingested_projects.json, default ~/.codess) ---
REGISTRY = _IS_ENV_VALUES["CODESS_REGISTRY"]

# --- CLI / logging ---
VERBOSE = _IS_ENV_VALUES["CODESS_VERBOSE"]

# --- Debug ---
DEBUG = _IS_ENV_VALUES["CODESS_DEBUG"]

# --- Ingest ---
MIN_SIZE = _IS_ENV_VALUES["CODESS_MIN_SIZE"]
FORCE = _IS_ENV_VALUES["CODESS_FORCE"]

# --- Subagent (CC scan) ---
SUBAGENT = _IS_ENV_VALUES["CODESS_SUBAGENT"]

# --- Ingest redaction default (CLI --redact ORs on top) ---
INGEST_REDACT = _IS_ENV_VALUES["CODESS_REDACT"]
RAW_MODE = _IS_ENV_VALUES["CODESS_RAW_MODE"]
STRICT_MAPPING = _IS_ENV_VALUES["CODESS_STRICT_MAPPING"]
CONTENT_POLICY = _IS_ENV_VALUES["CODESS_CONTENT_POLICY"]
RESOURCE_POLICY = _IS_ENV_VALUES["CODESS_RESOURCE_POLICY"]
MAX_TRANSCRIPT_BYTES = _IS_ENV_VALUES["CODESS_MAX_TRANSCRIPT_BYTES"]
# Compatibility alias. New configuration should use MAX_TRANSCRIPT_BYTES.
# Not table-driven: its default is MAX_TRANSCRIPT_BYTES itself (another
# env-derived value), so it must resolve after the table, not as a row in it.
MAX_SOURCE_BYTES = env_int("CODESS_MAX_SOURCE_BYTES", MAX_TRANSCRIPT_BYTES)
MAX_CURSOR_CONTAINER_BYTES = _IS_ENV_VALUES["CODESS_MAX_CURSOR_CONTAINER_BYTES"]
MAX_EVENTS_PER_SOURCE = _IS_ENV_VALUES["CODESS_MAX_EVENTS_PER_SOURCE"]
MAX_EVENTS_PER_SESSION = _IS_ENV_VALUES["CODESS_MAX_EVENTS_PER_SESSION"]
MAX_CONTEXT_CONTENT_CHARS = _IS_ENV_VALUES["CODESS_MAX_CONTEXT_CONTENT_CHARS"]
MAX_CODESS_DB_BYTES = _IS_ENV_VALUES["CODESS_MAX_CODESS_DB_BYTES"]
MAX_CURSOR_DB_BYTES = _IS_ENV_VALUES["CODESS_MAX_CURSOR_DB_BYTES"]

# --- Batch / resilience: stop entire command on first error (otherwise log and continue) ---
STOP = _IS_ENV_VALUES["CODESS_STOP"]

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


def get_store_path(project_path: Path, source: str | None = None) -> Path:
    """Return path to sessions DB under project. source='Claude'|'Codex'|'Cursor' uses per-vendor DB."""
    base = project_path / STORE_DIR
    if source == "Claude":
        return base / STORE_DB_CC
    if source == "Codex":
        return base / STORE_DB_CODEX
    if source == "Cursor":
        return base / STORE_DB_CURSOR
    return base / STORE_DB


def get_state_path(project_path: Path) -> Path:
    """Return path to ingest_state.json under project."""
    return project_path / STORE_DIR / STATE_FILE


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
        ("CODESS_MAX_TRANSCRIPT_BYTES", MAX_TRANSCRIPT_BYTES),
        ("CODESS_MAX_CURSOR_CONTAINER_BYTES", MAX_CURSOR_CONTAINER_BYTES),
        ("CODESS_MAX_EVENTS_PER_SOURCE", MAX_EVENTS_PER_SOURCE),
        ("CODESS_MAX_EVENTS_PER_SESSION", MAX_EVENTS_PER_SESSION),
        ("CODESS_MAX_CONTEXT_CONTENT_CHARS", MAX_CONTEXT_CONTENT_CHARS),
        ("CODESS_MAX_CODESS_DB_BYTES", MAX_CODESS_DB_BYTES),
        ("CODESS_MAX_CURSOR_DB_BYTES", MAX_CURSOR_DB_BYTES),
    ):
        if value <= 0:
            errs.append(f"{name}={value} must be > 0")
    if "CODESS_MAX_SOURCE_BYTES" in os.environ and MAX_SOURCE_BYTES <= 0:
        errs.append(
            f"CODESS_MAX_SOURCE_BYTES={MAX_SOURCE_BYTES} must be > 0"
        )
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


def get_project_stores(project_path: Path) -> list[Path]:
    """Return current snapshot stores, falling back to legacy working paths."""
    from codess.snapshot import current_store_paths

    current = current_store_paths(project_path)
    if current:
        return current
    base = project_path / STORE_DIR
    legacy = base / STORE_DB
    if legacy.exists():
        return [legacy]
    return [p for p in (base / STORE_DB_CC, base / STORE_DB_CODEX, base / STORE_DB_CURSOR) if p.exists()]
