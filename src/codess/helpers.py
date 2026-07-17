"""Shared helpers: path, slug, exclude, CSV, dir list."""

import csv
import logging
from pathlib import Path
from urllib.parse import unquote, urlparse

from codess.config import EXCLUDE_REVIEW_DIRS
from codess.sanitize import protect_csv_row

log = logging.getLogger(__name__)


# Exact directory names that are implementation artifacts, dependency stores,
# caches, environments, or VCS internals rather than candidate Projects. The
# caller's explicit root remains eligible; these names prune only descendants.
TRAVERSAL_PRUNE_DIRS = frozenset({
    ".build", ".cache", ".ccache", ".codess", ".direnv", ".eggs", ".git",
    ".gradle", ".hg", ".idea", ".mypy_cache", ".next", ".nox", ".npm",
    ".nuxt", ".parcel-cache", ".pnpm-store", ".pyenv", ".pytest_cache",
    ".ruff_cache", ".svn", ".terraform", ".tox", ".turbo", ".venv",
    ".vscode", ".yarn", "__pycache__", "bazel-bin", "bazel-out",
    "bazel-testlogs", "build", "coverage", "debug", "deriveddata", "dist",
    "env", "node_modules", "out", "pods", "release", "site-packages",
    "target", "venv",
})

_BROAD_TRAVERSAL_ROOTS = frozenset(
    Path(value).resolve()
    for value in (
        "/Applications", "/Library", "/Network", "/System", "/Users",
        "/Volumes", "/bin", "/boot", "/dev", "/etc", "/home", "/lib",
        "/lib64", "/media", "/mnt", "/opt", "/private", "/proc", "/root",
        "/run", "/sbin", "/srv", "/sys", "/tmp", "/usr", "/var",
    )
)


def should_prune_directory(name: str) -> bool:
    """Return whether a descendant directory is routine traversal noise."""
    folded = name.casefold()
    return folded in TRAVERSAL_PRUNE_DIRS or folded.startswith("cmake-build-")


def is_under_pruned_directory(path: Path, root: Path) -> bool:
    """Return whether ``path`` is below a pruned descendant of explicit ``root``."""
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return any(should_prune_directory(part) for part in relative.parts)


def unsafe_traversal_root_reason(path: Path) -> str | None:
    """Explain why a root is too broad for discovery, or return ``None``."""
    resolved = path.expanduser().resolve()
    if resolved.parent == resolved or resolved in _BROAD_TRAVERSAL_ROOTS:
        return f"broad system traversal root is not allowed: {resolved}"
    return None


def local_path_from_uri(value: object) -> Path | None:
    """Return an absolute local path, rejecting remote/editor URI schemes."""
    if isinstance(value, dict):
        value = value.get("path") or ""
    text = str(value or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme:
        if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
            return None
        text = unquote(parsed.path)
    path = Path(text).expanduser()
    if not path.is_absolute():
        return None
    return path.resolve()


def path_to_slug(path: Path) -> str:
    """Encode path to CC slug format."""
    s = path.as_posix()
    if path.is_absolute():
        s = s.lstrip("/")
        return "-" + s.replace("/", "-") if s else ""
    return s.replace("/", "-")


def slug_to_path(slug: str) -> Path:
    """Decode slug to path. Lossy: 'spank-py' and 'spank/py' both encode to same slug."""
    if not slug:
        return Path(".")
    if slug.startswith("-"):
        p = Path("/" + slug[1:].replace("-", "/"))
    else:
        p = Path(slug.replace("-", "/"))
    # Fallback: decoded path may be wrong (e.g. spank/py vs spank-py). Try hyphen variant.
    if not p.exists() and len(p.parts) >= 3:
        alt = Path(*p.parts[:-2], p.parts[-2] + "-" + p.parts[-1])
        if alt.exists():
            return alt
    return p


def is_excluded(p: Path, work_root: Path | None = None) -> bool:
    """True if path is under backup or review dir.

    When ``work_root`` is omitted, ``DEFAULT_WORK`` (``~/Work``) is the anchor for
    ``relative_to`` — there is **no** matching CLI flag; pass an explicit scan/ingest
    work root when classifying paths under a different tree.
    """
    from codess.config import DEFAULT_WORK
    root = work_root or DEFAULT_WORK
    try:
        rel = str(p.relative_to(root))
    except ValueError:
        return False
    if is_under_pruned_directory(p, root):
        return True
    if "/OLD/" in rel or rel.startswith("OLD/"):
        return True
    if "/Save" in rel or rel.startswith("Save"):
        return True
    for d in EXCLUDE_REVIEW_DIRS:
        if rel == d or rel.startswith(d + "/"):
            return True
    return False
def write_csv(path: Path, rows: list[list], headers: list[str] | None = None) -> None:
    """Write rows to CSV file. headers optional.

    Creates **parent directories** for ``path`` (``mkdir(parents=True)``) so a deep
    ``--out`` like ``reports/jan/codess_walk.csv`` works without pre-creating folders.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if headers:
            w.writerow(headers)
        w.writerows(protect_csv_row(row) for row in rows)


def user_root_string_disallowed(raw: str) -> bool:
    """True if user-supplied root string must be rejected (.. or hidden relative segments).

    Absolute paths may contain segments like ``.config`` under the home tree; relative
    roots may not use a ``.name`` component other than ``.`` / ``..``.
    """
    s = raw.strip()
    if not s:
        return True
    p = Path(s)
    parts = p.parts
    if ".." in parts:
        return True
    if not p.is_absolute():
        for part in parts:
            if part.startswith(".") and part not in (".", ".."):
                return True
    return False


def validate_dirs_file(path: Path) -> str | None:
    """Validate a plain path list or a candidate CSV with ``directory_path``.

    Returns an error message (stderr-ready), or ``None`` if ok.
    """
    if not path.exists():
        return f"codess: --dirs file does not exist: {path}"
    if not path.is_file():
        return f"codess: --dirs path is not a file: {path}"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return f"codess: cannot read --dirs file {path}: {e}"
    if not _dirs_file_values(text):
        return f"codess: --dirs file has no path lines (empty or comments only): {path}"
    return None


def _dirs_file_values(text: str) -> list[str]:
    """Extract roots from a plain list or a CSV carrying ``directory_path``."""
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        return []
    header = next(csv.reader([lines[0]]), [])
    if "directory_path" in header:
        return [
            str(row.get("directory_path") or "").strip()
            for row in csv.DictReader(lines)
            if str(row.get("directory_path") or "").strip()
        ]
    return [line.strip() for line in lines]


def parse_dir_list(dirs_file: Path | None, dir_args: list[str]) -> list[Path]:
    """Parse a path-list/candidate-CSV ``--dirs`` file and ``--dir`` args.

    Skips disallowed roots (``..``, relative ``.hidden`` segments); logs a warning per skip.
    """
    seen: set[str] = set()
    out: list[Path] = []
    if dirs_file is not None:
        try:
            text = dirs_file.read_text(encoding="utf-8")
        except OSError as e:
            log.warning("Cannot read dirs file %s: %s", dirs_file, e)
            return out
        for line in _dirs_file_values(text):
            if user_root_string_disallowed(line):
                log.warning("Skipping disallowed root line: %s", line)
                continue
            p = Path(line).resolve()
            k = str(p)
            if k not in seen:
                seen.add(k)
                out.append(p)
    for s in dir_args:
        if not s:
            continue
        if user_root_string_disallowed(s):
            log.warning("Skipping disallowed --dir: %s", s)
            continue
        p = Path(s).resolve()
        k = str(p)
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out
