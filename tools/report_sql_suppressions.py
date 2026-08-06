#!/usr/bin/env python3
"""Report current ruff S608 exemption status instead of a number in prose.

CoPlan.md 10.4 documents *why* certain files are exempted from `S608` in
`pyproject.toml`'s `[tool.ruff.lint.per-file-ignores]` and how to tell a
rewritable site from one that genuinely needs the exemption. It deliberately
does not document which files carry the exemption or how many sites each
one has, because both change as sites are rewritten, files are added, or a
file's last site is eliminated (at which point its entry should be removed
from pyproject.toml, not left pointing at nothing). Run this instead of
grepping pyproject.toml or the source tree by hand.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PYPROJECT = ROOT / "pyproject.toml"


def exempted_files() -> set[str]:
    """Return the files pyproject.toml exempts from S608, as written there."""
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    ignores = (
        config.get("tool", {}).get("ruff", {}).get("lint", {})
        .get("per-file-ignores", {})
    )
    return {path for path, rules in ignores.items() if "S608" in rules}


def active_findings() -> list[dict]:
    """Return S608 findings ruff reports right now, respecting config."""
    import json

    result = subprocess.run(
        [
            sys.executable, "-m", "ruff", "check", str(SRC),
            "--select", "S608", "--output-format", "json",
        ],
        capture_output=True, text=True, check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"ruff failed: {result.stderr}")
    return json.loads(result.stdout or "[]")


def main(argv: list[str] | None = None) -> int:
    exempted = exempted_files()
    findings = active_findings()

    if findings:
        print(
            "ruff still reports S608 findings after per-file-ignores -- "
            "this should not happen; check pyproject.toml's "
            "[tool.ruff.lint.per-file-ignores] entries match these paths "
            "exactly:",
            file=sys.stderr,
        )
        for finding in findings:
            rel = str(Path(finding["filename"]).relative_to(ROOT))
            row = finding["location"]["row"]
            print(f"  {rel}:{row}", file=sys.stderr)
        return 1

    stale = sorted(
        path for path in exempted if not (ROOT / path).exists()
    )
    if stale:
        print(
            "pyproject.toml exempts file(s) that no longer exist -- "
            "remove these entries:",
            file=sys.stderr,
        )
        for path in stale:
            print(f"  {path}", file=sys.stderr)
        return 1

    print(f"S608-exempted files (see CoPlan.md 10.4 for why): {len(exempted)}")
    for path in sorted(exempted):
        print(f"  {path}")
    print(
        "\nNo unexempted S608 findings. If you just rewrote a file's last "
        "S608 site to avoid the warning, remove its pyproject.toml entry "
        "(this script will not do that for you, and a stale entry masks "
        "no risk today but hides one if new SQL is later added to that "
        "file without review)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
