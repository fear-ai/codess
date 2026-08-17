"""Shared helpers: path, slug, exclude, CSV, dir list."""

import csv
import json
import logging
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from codess.config import EXCLUDE_REVIEW_DIRS
from codess.sanitize import protect_csv_row

log = logging.getLogger(__name__)


# Exact directory names that are implementation artifacts, dependency stores,
# caches, environments, or VCS internals rather than candidate Projects. The
# caller's explicit root remains eligible; these names prune only descendants.
DISCOVERY_POLICY_PATH = Path(__file__).resolve().parents[2] / "schema/discovery-policy.json"
"""The released discovery policy: which directory names are never traversed.

Externalized rather than hardcoded because the set is editable data, not a
rule: a tree that versions its `dist/` output, a monorepo with a package named
`build`, or a Go module vendoring dependencies it audits each needs a
different set, and a frozen tuple made those cases undiscoverable with no way
to say so (CoPlan W60).

`CODESS_DISCOVERY_POLICY` names a replacement file. A malformed or missing
file falls back to the released one and warns rather than raising: discovery
degrading to the shipped defaults is recoverable, while a scan that refuses to
start because a policy has a trailing comma is not.
"""


def _load_discovery_policy() -> tuple[frozenset[str], tuple[str, ...], dict[str, str]]:
    """Read the pruned names, pruned prefixes, and documented exceptions."""
    configured = os.environ.get("CODESS_DISCOVERY_POLICY")
    path = Path(configured).expanduser() if configured else DISCOVERY_POLICY_PATH
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("policy_format") != "codess.discovery-policy/1":
            raise ValueError(f"unsupported discovery policy format in {path}")
        names = {
            str(name).casefold()
            for group in document.get("pruned", {}).values()
            for name in group
        }
        prefixes = tuple(str(p).casefold() for p in document.get("pruned_prefixes", ()))
        traversed = {
            str(k): str(v) for k, v in document.get("traversed_on_purpose", {}).items()
        }
        return frozenset(names), prefixes, traversed
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        log.warning(
            "cannot load discovery policy from %s (%s); using the released set", path, exc
        )
        if configured:
            try:
                document = json.loads(DISCOVERY_POLICY_PATH.read_text(encoding="utf-8"))
                return (
                    frozenset(
                        str(n).casefold()
                        for g in document.get("pruned", {}).values() for n in g
                    ),
                    tuple(str(p).casefold() for p in document.get("pruned_prefixes", ())),
                    {str(k): str(v) for k, v in document.get("traversed_on_purpose", {}).items()},
                )
            except (OSError, ValueError):
                pass
        return frozenset(), (), {}


TRAVERSAL_PRUNE_DIRS, TRAVERSAL_PRUNE_PREFIXES, TRAVERSED_ON_PURPOSE = (
    _load_discovery_policy()
)
"""Directory names never traversed, matched case-folded against each segment.

Names rather than paths, so the set is portable: `obj` under a .NET solution
and `obj` under a Makefile are both build output, and neither is anchored to
one tree. This is the opposite of `EXCLUDE_REVIEW_DIRS`, which names *where*
on one machine and therefore ships empty.

`TRAVERSED_ON_PURPOSE` records the names that look skippable and are not,
each with the reason -- `lib`, `data`, `etc`, and `secrets` among them. It is
data rather than a comment so `tools/setup_discovery.py` can report it to an
operator deciding what to exclude for their own tree.
"""

_BROAD_TRAVERSAL_ROOTS = frozenset(
    Path(value).resolve()
    for value in (
        "/Applications", "/Library", "/Network", "/System", "/Users",
        "/Volumes", "/bin", "/boot", "/dev", "/etc", "/home", "/lib",
        "/lib64", "/media", "/mnt", "/opt", "/private", "/proc", "/root",
        "/run", "/sbin", "/srv", "/sys", "/tmp", "/usr", "/var",
    )
)

_EPHEMERAL_LOCATION_PREFIXES = tuple(
    Path(value).resolve()
    for value in (
        "/private/var/folders",
        "/private/tmp",
        "/tmp",
        "/var/folders",
    )
)


def should_prune_directory(name: str) -> bool:
    """Return whether a descendant directory is routine traversal noise."""
    folded = name.casefold()
    return folded in TRAVERSAL_PRUNE_DIRS or folded.startswith(TRAVERSAL_PRUNE_PREFIXES)


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


def ephemeral_project_location_reason(path: Path) -> str | None:
    """Explain why a path is unsuitable as a durable Project location."""
    resolved = path.expanduser().resolve()
    for prefix in _EPHEMERAL_LOCATION_PREFIXES:
        if resolved == prefix or resolved.is_relative_to(prefix):
            return f"ephemeral system location is not a durable Project: {resolved}"
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


def resolve_slug(slug: str, root: Path | None = None) -> Path | None:
    """Decode a Claude storage slug against the filesystem, or return None.

    The encoding is Claude's and is lossy: `/` and `-` both become `-`, so
    `<name>-<suffix>` and `<name>/<suffix>` produce the same slug, and the string alone
    cannot say which was meant. The only authority that can decide is the
    filesystem, so this matches slug tokens against directories that exist,
    preferring the longest name at each step -- the hyphenated directory is
    tried before the nested split, because a literal directory name is better
    evidence than a
    split that happens to parse.

    Returns None when no directory matches. That is the honest answer for a
    slug whose Project was deleted or moved, and it is what `slug_to_path`
    cannot express: a caller that needs to distinguish "resolved" from
    "guessed" asks here.

    A slug always encodes an absolute path, so the walk starts at `/`. Pass
    `root` to require the result to lie under a directory: the descent still
    begins at the filesystem root, and a match outside `root` is rejected
    rather than returned. A resolved path is always a real directory reached
    by ordinary descent, so a `..` token cannot redirect the walk -- it is
    matched as a literal directory name or not at all.
    """
    if not slug or not slug.startswith("-"):
        return None
    tokens = slug[1:].split("-")

    def descend(current: Path, index: int) -> Path | None:
        if index == len(tokens):
            return current
        # Longest first: a hyphenated directory name outranks a split that
        # only happens to exist.
        for end in range(len(tokens), index, -1):
            name = "-".join(tokens[index:end])
            if not name or name in (".", ".."):
                continue
            candidate = current / name
            if candidate.is_dir():
                found = descend(candidate, end)
                if found is not None:
                    return found
        return None

    found = descend(Path("/"), 0)
    if found is None or root is None:
        return found
    return found if found.is_relative_to(root.resolve()) else None


def slug_to_path(slug: str) -> Path:
    """Decode slug to path, falling back to the naive split when unresolvable.

    Prefers `resolve_slug`, which consults the filesystem and is correct for
    any Project that still exists. When nothing matches -- a deleted or moved
    Project -- this returns the naive one-token-per-segment reading so the
    caller still has a value to record and report.

    That fallback is a guess and can name the wrong directory: `A-..-B`
    reads as `A/../B`, which resolves to `B`. Callers that act on the path
    rather than display it should use `resolve_slug` and handle None. The
    containment check in `walk_sessions.in_work_root` resolves before
    comparing, so a fallback path cannot escape the configured work root.
    """
    if not slug:
        return Path()
    resolved = resolve_slug(slug)
    if resolved is not None:
        return resolved
    if slug.startswith("-"):
        return Path("/" + slug[1:].replace("-", "/"))
    return Path(slug.replace("-", "/"))


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
    # Match on path segments rather than a root-relative prefix: the same
    # directory must be excluded whether it is reached as `<group>/<tree>`
    # from a work root or `Work/<group>/<tree>` from the home directory above
    # it. Anchoring to one root
    # made exclusion depend on where the scan started.
    parts = p.parts
    for entry in EXCLUDE_REVIEW_DIRS:
        needle = tuple(entry.split("/"))
        if any(
            parts[i:i + len(needle)] == needle
            for i in range(len(parts) - len(needle) + 1)
        ):
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
