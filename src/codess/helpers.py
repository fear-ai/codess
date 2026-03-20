"""Shared helpers: path, slug, exclude, CSV, dir list."""

import csv
import logging
from pathlib import Path

from codess.config import EXCLUDE_REVIEW_DIRS

log = logging.getLogger(__name__)


def load_codessignore(cwd: Path | None = None) -> frozenset[str]:
    """Load .codessignore: cwd first, else ~/.codessignore. One dir name per line. Case-insensitive."""
    cwd = cwd or Path.cwd()
    for p in (cwd / ".codessignore", Path.home() / ".codessignore"):
        if p.exists():
            try:
                names = {
                    ln.strip().lower()
                    for ln in p.read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.strip().startswith("#")
                }
                return frozenset(names)
            except OSError:
                pass
    return frozenset()


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
    if "/OLD/" in rel or rel.startswith("OLD/"):
        return True
    if "/Save" in rel or rel.startswith("Save"):
        return True
    for d in EXCLUDE_REVIEW_DIRS:
        if rel == d or rel.startswith(d + "/"):
            return True
    return False


def should_skip_recurse(dirname: str, codessignore: frozenset[str] | None = None) -> bool:
    """True if dirname should be skipped when recursing (case-insensitive)."""
    from codess.config import EXCLUDE_RECURSE
    if dirname.startswith("."):
        return True
    if dirname in EXCLUDE_RECURSE or dirname.lower() in {d.lower() for d in EXCLUDE_RECURSE}:
        return True
    if codessignore and dirname.lower() in codessignore:
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
        w.writerows(rows)


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
    """If ``--dirs`` was passed, ensure the file exists, is readable, and has ≥1 path line.

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
    lines = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if not lines:
        return f"codess: --dirs file has no path lines (empty or comments only): {path}"
    return None


def parse_dir_list(dirs_file: Path | None, dir_args: list[str]) -> list[Path]:
    """Parse ``--dirs`` file (caller validated with ``validate_dirs_file`` if required) and ``--dir`` args.

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
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
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
