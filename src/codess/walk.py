"""Walk: traverse directory tree; exclude; no symlinks; dedupe; safeguards."""

import os
import time
from pathlib import Path

from codess.helpers import load_codessignore, should_skip_recurse

MAX_DEPTH = 16
MAX_TIME_MIN = 100


def walk_dirs(
    roots: list[Path],
    recurse: bool = True,
    codessignore: frozenset[str] | None = None,
    prune_dirs: set[Path] | None = None,
    max_depth: int = MAX_DEPTH,
    max_time_min: float = MAX_TIME_MIN,
):
    """Yield dirs under roots. recurse=False: roots only. Skip excluded dirs, symlinks; dedupe.
    prune_dirs: when yielding a dir in this set, do not recurse. max_depth/max_time: safeguards."""
    seen: set[Path] = set()
    roots = [p.resolve() for p in roots if p.exists() and p.is_dir()]
    codessignore = codessignore or load_codessignore()
    prune_dirs = prune_dirs or set()
    start = time.monotonic()
    deadline = start + max_time_min * 60

    def _skip(d: str) -> bool:
        return should_skip_recurse(d, codessignore)

    if not recurse:
        for r in roots:
            k = r.resolve()
            if k not in seen:
                seen.add(k)
                yield k
        return

    for root in roots:
        for dirpath, dirnames, _ in os.walk(root, topdown=True, followlinks=False):
            if time.monotonic() > deadline:
                return
            try:
                depth = len(Path(dirpath).resolve().relative_to(root).parts)
            except ValueError:
                depth = 0
            if depth >= max_depth:
                dirnames.clear()
                continue
            p = Path(dirpath).resolve()
            if p.is_symlink():
                dirnames.clear()
                continue
            if p in prune_dirs:
                dirnames.clear()
                continue
            dirnames[:] = [d for d in dirnames if not _skip(d)]
            if p not in seen:
                seen.add(p)
                yield p
