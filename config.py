"""Paths, options, and defaults for CodingSess."""

import os
import platform
import re
from pathlib import Path

CC_PROJECTS_DIR = Path(
    os.environ.get("CODINGSESS_CC_PROJECTS_DIR", str(Path.home() / ".claude" / "projects"))
)

# Codex
CODEX_SESSIONS_DIR = Path(
    os.environ.get("CODINGSESS_CODEX_SESSIONS_DIR", str(Path.home() / ".codex" / "sessions"))
)
CODEX_HISTORY_PATH = Path(
    os.environ.get("CODINGSESS_CODEX_HISTORY_PATH", str(Path.home() / ".codex" / "history.jsonl"))
)

# Cursor (platform-specific)
def _cursor_user_data() -> Path:
    override = os.environ.get("CODINGSESS_CURSOR_USER_DATA")
    if override:
        return Path(override)
    home = Path.home()
    sys = platform.system()
    if sys == "Darwin":
        return home / "Library/Application Support/Cursor/User"
    if sys == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "Cursor" / "User"
    return home / ".config" / "Cursor" / "User"

CURSOR_USER_DATA = _cursor_user_data()
STORE_DIR_NAME = ".coding-sess"
STORE_DB_NAME = "sessions.db"
STORE_DB_CC = "sessions_cc.db"
STORE_DB_CODEX = "sessions_codex.db"
STORE_DB_CURSOR = "sessions_cursor.db"
STATE_FILE_NAME = "ingest_state.json"
STATS_FILE_NAME = "ingested_projects.json"

TRUNCATE_RESPONSE = 1000
TRUNCATE_DIALOG = 200
TRUNCATE_TOOL_RESULT = 500
TRUNCATE_GREP_PATTERN = 120
TRUNCATE_PROMPT = 10000  # User prompts (Codex/Cursor)

# Skip session files smaller than this (bytes). Small files are typically command-only or resume chains.
MIN_SESSION_FILE_SIZE = 20 * 1024  # 20 KB

# Default redaction patterns: API keys, tokens, .env-style values
REDACT_PATTERNS = [
    re.compile(r'sk-[a-zA-Z0-9]{20,}', re.I),
    re.compile(r'api[_-]?key["\']?\s*[:=]\s*["\']?[a-zA-Z0-9_\-]{20,}', re.I),
    re.compile(r'bearer\s+[a-zA-Z0-9_\-\.]{20,}', re.I),
]


def get_store_path(project_root: Path, source: str | None = None) -> Path:
    """Return path to sessions DB under project. source='Claude'|'Codex'|'Cursor' uses per-vendor DB."""
    base = project_root / STORE_DIR_NAME
    if source == "Claude":
        return base / STORE_DB_CC
    if source == "Codex":
        return base / STORE_DB_CODEX
    if source == "Cursor":
        return base / STORE_DB_CURSOR
    return base / STORE_DB_NAME


def get_state_path(project_root: Path) -> Path:
    """Return path to ingest_state.json under project."""
    return project_root / STORE_DIR_NAME / STATE_FILE_NAME


def get_stats_path(registry_root: Path) -> Path:
    """Return path to ingested_projects.json (registry of decoded/ingested projects)."""
    return registry_root / STORE_DIR_NAME / STATS_FILE_NAME


def get_project_stores(project_root: Path) -> list[Path]:
    """Return existing DB paths: legacy sessions.db first, else per-vendor DBs."""
    base = project_root / STORE_DIR_NAME
    legacy = base / STORE_DB_NAME
    if legacy.exists():
        return [legacy]
    return [p for p in (base / STORE_DB_CC, base / STORE_DB_CODEX, base / STORE_DB_CURSOR) if p.exists()]
