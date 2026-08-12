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


def KB(count: float) -> int:
    """`count` kibibytes as bytes (`count * 1024`)."""
    return int(count * 1024)


def MB(count: float) -> int:
    """`count` mebibytes as bytes (`count * 1024**2`)."""
    return int(count * 1024**2)


def GB(count: float) -> int:
    """`count` gibibytes as bytes (`count * 1024**3`)."""
    return int(count * 1024**3)


def BKB(count: float) -> float:
    """`count` bytes as kibibytes (`count / 1024`); inverse of `KB`."""
    return count / 1024


def BMB(count: float) -> float:
    """`count` bytes as mebibytes (`count / 1024**2`); inverse of `MB`."""
    return count / 1024**2


def BGB(count: float) -> float:
    """`count` bytes as gibibytes (`count / 1024**3`); inverse of `GB`."""
    return count / 1024**3


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
    # One year. The window exists to keep an incremental rescan cheap, not to
    # decide what is worth ingesting: for anyone using coding tools routinely,
    # 90 days omits most of a Project's history on the first ingest, which is
    # exactly when the complete record is wanted. Use --days 0 for all time.
    ("CODESS_DAYS", env_int, 365),
    ("CODESS_VERBOSE", env_bool, "0"),
    ("CODESS_DEBUG", env_bool, "0"),
    ("CODESS_MIN_SIZE", env_int, KB(20)),
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
    ("CODESS_MAX_CODESS_DB_BYTES", env_int, GB(2)),
    ("CODESS_MAX_CURSOR_DB_BYTES", env_int, GB(10)),
    ("CODESS_CC_PROJECTS", env_path, str(Path.home() / ".claude" / "projects")),
    ("CODESS_RAW_MODE", env_raw_mode, "reference"),
    ("CODESS_CONTENT_POLICY", env_str, None),
    ("CODESS_RESOURCE_POLICY", env_str, None),
    ("CODESS_REGISTRY", env_expanded_path, str(Path.home() / ".codess")),
    ("CODESS_STOP", env_bool, "0"),
    ("CODESS_NO_HASH", env_bool, "0"),
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
LAST_INGEST_REPORT_FILE = "last-ingest-report.json"
PROJECT_FILE = "project.json"
SOURCE_LINKS_FILE = "source-links.json"
SOURCE_LINKS_FORMAT = "codess.source-links/1"
WORKING_ARCHIVES_DIR = "working-archives"

# --- Snapshot layout (under STORE_DIR or a durable registry project root) ---
SNAPSHOTS_DIR = "snapshots"
MANIFEST_FILE = "manifest.json"
MANIFEST_BACKUP_FILE = "manifest.json.bak"
CURRENT_POINTER_FILE = "current.json"
RAW_MANIFEST_FILE = "raw-manifest.jsonl"

# --- Registry (central ingested_projects.json, default ~/.codess) ---
REGISTRY = _IS_ENV_VALUES["CODESS_REGISTRY"]

# --- CLI / logging ---
VERBOSE = _IS_ENV_VALUES["CODESS_VERBOSE"]

# --- Debug ---
DEBUG = _IS_ENV_VALUES["CODESS_DEBUG"]

# --- Ingest ---
MIN_SIZE = _IS_ENV_VALUES["CODESS_MIN_SIZE"]

# --- Vendor feature audits: cap on files scanned per run (evidence.py,
# vendor_audits.claude_features, vendor_audits.codex_features) ---
DEFAULT_AUDIT_MAX_FILES = 200
FORCE = _IS_ENV_VALUES["CODESS_FORCE"]

# --- Subagent (CC scan) ---
SUBAGENT = _IS_ENV_VALUES["CODESS_SUBAGENT"]

# --- Ingest redaction default (CLI --redact ORs on top) ---
INGEST_REDACT = _IS_ENV_VALUES["CODESS_REDACT"]
RAW_MODES = ("none", "reference", "capture", "seal")
"""How much of a Source's exact bytes a run retains, in increasing degree.

A closed vocabulary: unlike `actor_kind`, `content_role`, and `origin_kind` --
which CoSchema keeps open so vendor evidence can introduce useful new values
-- these four are the modes Codess implements, and a fifth would be new
behavior rather than a new observation. Written out longhand at six sites
before W23, so a mode added here would have been accepted by some boundaries
and rejected by others.

Ordered from least to most retained, which is the order every message that
lists them uses. `config` owns it because config is a leaf module: the
validators that consult it live above, and `raw_store` re-exports it as a
set for membership tests.
"""

RAW_MODE_CHOICES = RAW_MODES
"""Alias for argparse `choices`, where the plural reads as the parameter."""


def raw_mode_error(name: str, value: object, *, extra: tuple[str, ...] = ()) -> str:
    """Phrase one rejection message for an invalid raw mode.

    The five sites that reject a mode each spelled the valid list into their
    own message, so adding a mode meant editing prose in five files and the
    vocabulary in six. `extra` carries the values a particular site accepts
    beyond the stored ones, which is `auto` for refresh.
    """
    allowed = tuple(extra) + RAW_MODES
    listed = ", ".join(allowed[:-1]) + f", or {allowed[-1]}"
    return f"{name}={value!r} must be {listed}"


RAW_MODE = _IS_ENV_VALUES["CODESS_RAW_MODE"]
STRICT_MAPPING = _IS_ENV_VALUES["CODESS_STRICT_MAPPING"]
CONTENT_POLICY = _IS_ENV_VALUES["CODESS_CONTENT_POLICY"]
RESOURCE_POLICY = _IS_ENV_VALUES["CODESS_RESOURCE_POLICY"]
MAX_TRANSCRIPT_BYTES = _IS_ENV_VALUES["CODESS_MAX_TRANSCRIPT_BYTES"]
MAX_CURSOR_CONTAINER_BYTES = _IS_ENV_VALUES["CODESS_MAX_CURSOR_CONTAINER_BYTES"]
MAX_EVENTS_PER_SOURCE = _IS_ENV_VALUES["CODESS_MAX_EVENTS_PER_SOURCE"]
MAX_EVENTS_PER_SESSION = _IS_ENV_VALUES["CODESS_MAX_EVENTS_PER_SESSION"]
MAX_CONTEXT_CONTENT_CHARS = _IS_ENV_VALUES["CODESS_MAX_CONTEXT_CONTENT_CHARS"]
MAX_CODESS_DB_BYTES = _IS_ENV_VALUES["CODESS_MAX_CODESS_DB_BYTES"]
MAX_CURSOR_DB_BYTES = _IS_ENV_VALUES["CODESS_MAX_CURSOR_DB_BYTES"]

# --- Reporting and CLI-default thresholds (not env-overridable ingest limits;
# see resource_policy.BUILTIN_MAXIMUMS for those) ---
# A Project at or above this many events is labelled "large" in refresh
# annotations and the admin --large-events report default.
LARGE_EVENT_COUNT = 25_000
# A normalized store at or above this size is labelled "large" in refresh
# annotations and the admin --large-bytes report default.
LARGE_STORE_BYTES = MB(128)
# A single-line source record above this size is rejected during bounded
# JSONL reads (bounded_jsonl) and is the CLI --max-record-bytes default.
MAX_RECORD_BYTES = MB(2)
# A distinct captured raw revision at or above this size is flagged in
# retention planning as worth explicit --keep-comparison-revisions review.
LARGE_RAW_REVISION_BYTES = GB(1)
# A single JSONL line above this size during token-usage scanning is
# treated as implausible and skipped rather than parsed.
MAX_TOKEN_LINE_BYTES = MB(8)
# Above this size, source fingerprinting samples bounded windows instead of
# hashing the complete file (see fileio.source_fingerprint).
SOURCE_FULL_HASH_MAX = MB(64)
# A raw-capture object above this size is called out individually in a
# storage report rather than only contributing to the aggregate total.
LARGE_RAW_OBJECT_BYTES = MB(300)
# Default maximum inline content bytes for one typed query result
# (query --byte-limit); explicit --byte-limit overrides this default.
DEFAULT_QUERY_BYTE_LIMIT = MB(16)

# --- I/O chunk sizes (streaming buffer tuning, not a policy limit or
# threshold; grouped here for one place to look, not because these values
# are duplicated anywhere) ---
DEFAULT_HASH_CHUNK_BYTES = MB(1)
SOURCE_SAMPLE_CHUNK_BYTES = MB(1)
RAW_CAPTURE_CHUNK_BYTES = MB(1)

# --- Batch / resilience: stop entire command on first error (otherwise log and continue) ---
STOP = _IS_ENV_VALUES["CODESS_STOP"]

# --- Snapshot/manifest hash verification bypass (recovery/debugging; see fileio.read_hash) ---
NO_HASH = _IS_ENV_VALUES["CODESS_NO_HASH"]

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
    if RAW_MODE not in RAW_MODES:
        errs.append(raw_mode_error("CODESS_RAW_MODE", RAW_MODE))
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
    """Return the current snapshot's stores, or the working stores if unpublished.

    A Project that has been ingested but not yet published has no snapshot
    pointer, so the per-vendor working stores are the only thing to read.
    """
    from codess.snapshot import current_stores

    current = current_stores(project_path)
    if current:
        return current
    base = project_path / STORE_DIR
    return [
        path for path in (
            base / STORE_DB_CC, base / STORE_DB_CODEX, base / STORE_DB_CURSOR,
        )
        if path.exists()
    ]
