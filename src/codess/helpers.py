"""Shared helpers: path, slug, exclude, CSV, dir list."""

import csv
from pathlib import Path

from codess.config import EXCLUDE_REVIEW_DIRS


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
    """True if path is under backup or review dir."""
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
    """Write rows to CSV file. headers optional."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if headers:
            w.writerow(headers)
        w.writerows(rows)


def parse_dir_list(dirs_file: Path | None, dir_args: list[str]) -> list[Path]:
    """Parse --dirs file and --dir args into list of Paths. Dedupe, resolve, no .."""
    seen = set()
    out = []
    if dirs_file and dirs_file.exists():
        for line in dirs_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ".." in line:
                continue
            p = Path(line).resolve()
            k = str(p)
            if k not in seen:
                seen.add(k)
                out.append(p)
    for s in dir_args:
        if not s or ".." in s:
            continue
        p = Path(s).resolve()
        k = str(p)
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out
