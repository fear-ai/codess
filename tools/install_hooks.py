#!/usr/bin/env python3
"""Install the git hooks that move a check from the test run to the commit.

One hook today: the CoSchema format agreement. Four files state the format and
each restatement is otherwise compared where it is *read*, so a bump that misses
one is detected at the next store open -- correct, and a layer away from the edit
that caused it.

`pytest` already gates on this before collection, which moves detection to the
test run. This moves it to the commit that broke it, which is the last position
available before the value reaches another reader.

Installed rather than committed, because `.git/hooks` is not version-controlled
and a hook that runs without the operator having asked is a surprise. Run once
per checkout:

    python tools/install_hooks.py            # install
    python tools/install_hooks.py --check    # report what is installed
    python tools/install_hooks.py --remove   # uninstall

The hook is a few lines that delegate to `tools/format_agreement.py`, so the
check has one implementation and the hook cannot drift from what the suite
enforces. `git commit --no-verify` bypasses it, which is the escape hatch a
hook must leave.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

MARKER = "# codess-format-agreement"
HOOK = f"""#!/bin/sh
{MARKER}
# Refuse a commit that leaves the four CoSchema format declarations disagreeing.
# Installed by tools/install_hooks.py; `git commit --no-verify` bypasses it.
exec python3 "$(git rev-parse --show-toplevel)/tools/format_agreement.py" >&2
"""


def _hooks_dir() -> Path | None:
    """The repository's hooks directory, honouring `core.hooksPath`."""
    try:
        common = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if common.returncode != 0 or not common.stdout.strip():
        return None
    git_dir = Path(common.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = REPO_ROOT / git_dir
    configured = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "config", "--get", "core.hooksPath"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if configured.returncode == 0 and configured.stdout.strip():
        path = Path(configured.stdout.strip())
        return path if path.is_absolute() else REPO_ROOT / path
    return git_dir / "hooks"


def install(hooks: Path) -> str:
    """Write the hook, refusing to overwrite one this tool did not write."""
    target = hooks / "pre-commit"
    if target.exists() and MARKER not in target.read_text(encoding="utf-8"):
        return (
            f"a pre-commit hook already exists at {target} and was not written "
            f"by this tool; add the line yourself rather than losing it:\n"
            f"  python tools/format_agreement.py || exit 1"
        )
    hooks.mkdir(parents=True, exist_ok=True)
    target.write_text(HOOK, encoding="utf-8")
    target.chmod(0o755)
    return f"installed {target}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--check", action="store_true",
        help="report whether the hook is installed, changing nothing",
    )
    action.add_argument(
        "--remove", action="store_true", help="uninstall the hook",
    )
    args = parser.parse_args(argv)

    hooks = _hooks_dir()
    if hooks is None:
        print("codess: not a git repository; no hooks to install", file=sys.stderr)
        return 1
    target = hooks / "pre-commit"

    if args.check:
        installed = target.exists() and MARKER in target.read_text(encoding="utf-8")
        print(f"{target}: {'installed' if installed else 'not installed'}")
        return 0 if installed else 1
    if args.remove:
        if target.exists() and MARKER in target.read_text(encoding="utf-8"):
            target.unlink()
            print(f"removed {target}")
        else:
            print(f"{target}: nothing this tool installed")
        return 0

    print(install(hooks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
