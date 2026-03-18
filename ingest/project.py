"""Project derivation, slug encode/decode."""

import logging
import subprocess
from pathlib import Path

from config import CC_PROJECTS_DIR

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
    return CC_PROJECTS_DIR


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
