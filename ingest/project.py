"""Project derivation, slug encode/decode, Codex/Cursor paths."""

import json
import logging
import subprocess
from pathlib import Path

from config import CC_PROJECTS, CODEX_SESSIONS, CURSOR_USER_DATA

log = logging.getLogger(__name__)


def get_project_root(cwd: Path | None = None) -> Path:
    """Run git rev-parse --show-toplevel; on failure return cwd or Path.cwd()."""
    cwd = cwd or Path.cwd()
    try:
        out = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
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
        s = s.lstrip('/')
        return '-' + s.replace('/', '-') if s else ''
    return s.replace('/', '-')


def slug_to_path(slug: str) -> Path:
    """Decode slug to path."""
    if not slug:
        return Path('.')
    if slug.startswith('-'):
        return Path('/' + slug[1:].replace('-', '/'))
    return Path(slug.replace('-', '/'))


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
    db = CURSOR_USER_DATA / "globalStorage" / "state.vscdb"
    return db if db.exists() else None


def get_cursor_workspace_dbs(project_root: Path) -> list[Path]:
    """Return Cursor state.vscdb paths for workspaces matching project. Empty if none."""
    project_root = project_root.resolve()
    project_str = str(project_root)
    ws_dir = CURSOR_USER_DATA / "workspaceStorage"
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
