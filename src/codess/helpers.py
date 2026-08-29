"""Shared helpers: path, slug, exclude, CSV, dir list."""

import csv
import json
import logging
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

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
to say so.

`CODESS_DISCOVERY_POLICY` names a replacement file. A malformed or missing
file falls back to the released one and warns rather than raising: discovery
degrading to the shipped defaults is recoverable, while a scan that refuses to
start because a policy has a trailing comma is not.
"""


# A directory name, as a filesystem bounds one. 255 is `NAME_MAX` on Linux and
# macOS: it bounds one path *segment*, not a whole path, which is why it is
# applied per name here and per segment in `valid_policy_path`.
NAME_MAX = 255
PATH_MAX = 1023
_NAME_CHARACTERS = re.compile(rf"^[A-Za-z0-9._-]{{1,{NAME_MAX}}}$")


def valid_policy_name(value: str) -> bool:
    """One directory name: alphanumeric with `-`, `_`, `.`, and no separator.

    `.` and `..` are both rejected. `..` lets an entry escape the scope it
    appears to name; `.` names the current directory, so excluding it would
    exclude everything the scan is standing in.

    The regex bounds the length, so no separate emptiness test is needed: it
    matches one character at minimum and cannot match an empty string.
    """
    name = value.strip()
    return name not in (".", "..") and bool(_NAME_CHARACTERS.match(name))


def valid_policy_path(value: str) -> bool:
    """An absolute path whose every segment is a valid directory name.

    Three bounds, each for its own reason. The whole path is capped at
    `PATH_MAX`, because a longer one cannot be opened. **Every segment is
    checked against `valid_policy_name`**, because a filesystem bounds each
    segment at `NAME_MAX` independently -- a path under the total limit can
    still carry a 300-character segment no filesystem will hold, and checking
    only the total accepts it. And `..` is rejected wherever it appears, since
    one traversal segment lets an entry escape the scope it names.

    A colon is refused rather than merely undocumented: it is excluded from the
    value character set so that a comma is unambiguous, and admitting one would
    let `/a:/b` read as either one path or two depending on who split it.
    """
    path = value.strip()
    if not path or len(path) > PATH_MAX or not path.startswith("/") or ":" in path:
        return False
    segments = [part for part in Path(path).parts if part != "/"]
    return all(valid_policy_name(segment) for segment in segments)


def _load_discovery_policy() -> tuple[
    frozenset[str], tuple[str, ...], dict[str, str], tuple[tuple[str, ...], tuple[str, ...]],
]:
    """Read the excluded names, prefixes, documented exceptions, and backup names.

    `exclude_dirs` is one flat list rather than the seven groups it replaced:
    the groups were documentation, and nothing read them apart. A name that
    fails `valid_policy_name` is dropped with a warning rather than admitted,
    so a `/` or a `..` in the file cannot become a segment match that silently
    excludes more than the operator wrote.
    """
    configured = os.environ.get("CODESS_DISCOVERY_POLICY")
    path = Path(configured).expanduser() if configured else DISCOVERY_POLICY_PATH
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("policy_format") != "codess.discovery-policy/1":
            raise ValueError(f"unsupported discovery policy format in {path}")
        return _policy_values(document)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        log.warning(
            "cannot load discovery policy from %s (%s); using the released set", path, exc
        )
        if configured:
            try:
                return _policy_values(
                    json.loads(DISCOVERY_POLICY_PATH.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        return frozenset(), (), {}, ((), ())


def _policy_values(document: dict) -> tuple[
    frozenset[str], tuple[str, ...], dict[str, str], tuple[tuple[str, ...], tuple[str, ...]],
]:
    """Project one policy document into the four values discovery reads.

    `CODESS_EXCLUDE_DIRS` replaces the file's list rather than extending it,
    which is the same rule the two path settings follow: a variable states one
    shell's answer, and an answer that could only ever be added to could not
    say "none of these".
    """
    configured = os.environ.get("CODESS_EXCLUDE_DIRS")
    stated = (
        parse_policy_list(configured, as_path=False)
        if configured is not None
        else [str(name) for name in document.get("exclude_dirs", ())]
    )
    names = frozenset(
        str(name).casefold()
        for name in stated
        if valid_policy_name(str(name))
    )
    prefixes = tuple(
        str(prefix).casefold()
        for prefix in document.get("exclude_dir_prefixes", ())
        if valid_policy_name(str(prefix))
    )
    traversed = {
        str(key): str(value)
        for key, value in (document.get("traversed_on_purpose") or {}).items()
    }
    backup_group = document.get("backup_conventions") or {}
    backups = (
        tuple(str(name) for name in backup_group.get("exact", ())),
        tuple(str(name) for name in backup_group.get("prefix", ())),
    )
    return names, prefixes, traversed, backups


def parse_policy_list(raw: str, *, as_path: bool) -> tuple[str, ...]:
    """Split a comma-separated setting, dropping entries that fail the syntax.

    Comma rather than colon: a colon is excluded from the value character set,
    so a comma is unambiguous, and PATH notation would wrongly imply precedence
    by position. An invalid entry is dropped with a warning rather than
    raising -- a malformed exclusion should not stop discovery, and silence
    would leave the operator believing a tree was excluded when it was not.
    """
    validator = valid_policy_path if as_path else valid_policy_name
    accepted: list[str] = []
    for item in raw.split(","):
        entry = item.strip()
        if not entry:
            continue
        if not validator(entry):
            log.warning(
                "discovery policy entry %r is not a valid %s and is ignored",
                entry, "path" if as_path else "name",
            )
            continue
        accepted.append(str(Path(entry)) if as_path else entry)
    return tuple(dict.fromkeys(accepted))


def _load_policy_paths(key: str, variable: str) -> tuple[str, ...]:
    """Read one path list: the environment for a shell, the file for a machine.

    The variable wins because it names one invocation's scope, while the file
    states a durable fact about this machine -- which is the home the setting
    lacked when it existed only as a variable a later shell forgets.
    """
    raw = os.environ.get(variable)
    if raw:
        return parse_policy_list(raw, as_path=True)
    configured = os.environ.get("CODESS_DISCOVERY_POLICY")
    path = Path(configured).expanduser() if configured else DISCOVERY_POLICY_PATH
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        entries = document.get(key) or ()
        return parse_policy_list(",".join(str(item) for item in entries), as_path=True)
    except (OSError, ValueError, TypeError, AttributeError):
        return ()


TRAVERSAL_PRUNE_DIRS, TRAVERSAL_PRUNE_PREFIXES, TRAVERSED_ON_PURPOSE, BACKUP_CONVENTIONS = (
    _load_discovery_policy()
)
"""Directory names never traversed, matched case-folded against each segment.

Names rather than paths, so the set is portable: `obj` under a .NET solution
and `obj` under a Makefile are both build output, and neither is anchored to
one tree. This is the opposite of `EXCLUDE_PATHS`, which names *where*
on one machine and therefore ships empty.

`TRAVERSED_ON_PURPOSE` records the names that look skippable and are not,
each with the reason -- `lib`, `data`, `etc`, and `secrets` among them. It is
data rather than a comment so `tools/setup_discovery.py` can report it to an
operator deciding what to exclude for their own tree.
"""

EXCLUDE_PATHS = _load_policy_paths("exclude_paths", "CODESS_EXCLUDE_PATHS")
"""Trees on this machine that are not the operator's own work.

Ships empty and is supplied per machine, because a path describes one layout: a
shipped default derived from one tree silently misclassifies directories on
every other machine, and the operator cannot see why.
"""

INCLUDE_PATHS = _load_policy_paths("include_paths", "CODESS_INCLUDE_PATHS")
"""Trees admitted despite a rule that would skip them.

Outranks every other rule, which is the whole reason it exists: name-based
exclusion over-reaches by design, and without an override the only repair is to
weaken the name rule for every tree at once.
"""


def within_policy_paths(candidate: Path, roots: tuple[str, ...]) -> bool:
    """True where `candidate` is one of `roots` or sits beneath one."""
    return any(
        candidate == Path(root) or candidate.is_relative_to(Path(root))
        for root in roots
    )


def path_scope_excludes(candidate: Path) -> bool:
    """Whether the *path* settings alone exclude `candidate`.

    The `include_paths > exclude_paths` half of the precedence, in one place.
    It was written twice -- here and in the discovery traversal -- and two
    copies of a precedence rule is how they come to disagree: the rule exists
    because name-based exclusion over-reaches, so an `include_paths` entry has
    to win even where a parent is excluded and a segment name is on the list.

    Separate from `is_excluded` because the two callers ask different
    questions. `is_excluded` asks whether a path is excluded *at all*, applying
    the name rules and the work-root anchor as well; the traversal asks only
    whether to descend, before it knows whether the directory is a Project.
    """
    return not within_policy_paths(candidate, INCLUDE_PATHS) and within_policy_paths(
        candidate, EXCLUDE_PATHS,
    )


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


HARNESS_WORKTREE_SEGMENTS = frozenset({".claude", "worktrees"})
"""Path segments marking a worktree the harness created for its own use.

Both must appear: `.claude/worktrees/<name>` is the observed layout, and
matching on `worktrees` alone would exclude a repository that keeps its own.
"""


def is_excluded(p: Path, work_root: Path | None = None) -> bool:
    """True if path is under backup or review dir.

    When ``work_root`` is omitted, ``DEFAULT_WORK`` (``~/Work``) is the anchor for
    ``relative_to`` — there is **no** matching CLI flag; pass an explicit scan/ingest
    work root when classifying paths under a different tree.
    """
    from codess.config import CLAUDE_WORKTREES, DEFAULT_WORK
    root = work_root or DEFAULT_WORK
    # Precedence: include_paths > exclude_paths > exclude_dirs > hidden names >
    # default traversal. The path half is `path_scope_excludes`, applied before
    # the work-root check below, which returns False for anything outside the
    # anchor -- an operator's exclusion must hold wherever the scan started.
    if within_policy_paths(p, INCLUDE_PATHS):
        return False
    if path_scope_excludes(p):
        return True
    try:
        rel = str(p.relative_to(root))
    except ValueError:
        return False
    if is_under_pruned_directory(p, root):
        return True
    # A worktree the harness created for itself, under the Project's own
    # `.claude`. It is the tool's working area rather than a place the operator
    # develops -- created and removed by the tool, generated name, pruned from
    # git without anyone acting -- so admitting it publishes a Project whose
    # path will not exist next week. `CODESS_CLAUDE_WORKTREES=1` admits them,
    # for a question about harness behaviour rather than about a repository.
    if not CLAUDE_WORKTREES and set(p.parts) >= HARNESS_WORKTREE_SEGMENTS:
        return True
    # Backup-copy conventions come from the discovery policy rather than from
    # this module: they are directory *names*, portable across machines, and a
    # tree using different ones replaces the list without editing code.
    segments = Path(rel).parts
    exact_names, prefix_names = BACKUP_CONVENTIONS
    return any(segment in exact_names for segment in segments) or any(
        segment.startswith(prefix_names) for segment in segments if prefix_names
    )


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
