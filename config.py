"""Paths, options, and defaults for CodingSess."""

import os
import re
from pathlib import Path

CC_PROJECTS_DIR = Path(
    os.environ.get("CODINGSESS_CC_PROJECTS_DIR", str(Path.home() / ".claude" / "projects"))
)
STORE_DIR_NAME = ".coding-sess"
STORE_DB_NAME = "sessions.db"
STATE_FILE_NAME = "ingest_state.json"

TRUNCATE_RESPONSE = 1000
TRUNCATE_DIALOG = 200
TRUNCATE_TOOL_RESULT = 500
TRUNCATE_GREP_PATTERN = 120

# Skip session files smaller than this (bytes). Small files are typically command-only or resume chains.
MIN_SESSION_FILE_SIZE = 20 * 1024  # 20 KB

# Default redaction patterns: API keys, tokens, .env-style values
REDACT_PATTERNS = [
    re.compile(r'sk-[a-zA-Z0-9]{20,}', re.I),
    re.compile(r'api[_-]?key["\']?\s*[:=]\s*["\']?[a-zA-Z0-9_\-]{20,}', re.I),
    re.compile(r'bearer\s+[a-zA-Z0-9_\-\.]{20,}', re.I),
]


def get_store_path(project_root: Path) -> Path:
    """Return path to sessions.db under project."""
    return project_root / STORE_DIR_NAME / STORE_DB_NAME


def get_state_path(project_root: Path) -> Path:
    """Return path to ingest_state.json under project."""
    return project_root / STORE_DIR_NAME / STATE_FILE_NAME
