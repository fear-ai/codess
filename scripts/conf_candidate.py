"""Configuration for find_candidate: paths, dirs, and local settings.
Override via env: CODINGSESS_WORK_ROOT, CODINGSESS_CC_PROJECTS, etc."""

import os
from pathlib import Path

# Work root (projects live under here)
WORK = Path(os.environ.get("CODINGSESS_WORK_ROOT", "/Users/walter/Work"))

# Vendor session stores
CC_PROJECTS = Path(
    os.environ.get("CODINGSESS_CC_PROJECTS", str(Path.home() / ".claude" / "projects"))
)
CODEX_SESSIONS = Path(
    os.environ.get("CODINGSESS_CODEX_SESSIONS", str(Path.home() / ".codex" / "sessions"))
)
CURSOR_WS = Path(
    os.environ.get(
        "CODINGSESS_CURSOR_WS",
        str(Path.home() / "Library/Application Support/Cursor/User/workspaceStorage"),
    )
)

# Parent dirs that aggregate projects; don't treat as projects (CSPlan §9)
AGGREGATORS = frozenset(
    {"WP", "ZK", "Claw", "Claude", "Cursor", "Github", "CodingTools"}
)

# Backup/obsolete: exclude paths under OLD or Save* (CSPlan §9.1)
EXCLUDE_BACKUP_PATTERNS = ("/OLD/", "/Save")

# Download/review dirs: exclude paths under these (CSPlan §9.2)
EXCLUDE_REVIEW_DIRS = (
    "CodingTools",
    "MCP/MCPs",
    "Claw/Claws",
    "ZK/ZKs",
    "Spank/sOSS",
    "Claude/Claudes",
)

RECENT_DAYS = 90
