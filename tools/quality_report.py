#!/usr/bin/env python3
"""Report lint, type, and test results as one measurement.

A clean run means the selected rules passed, and a rule set nobody selected proves
nothing. This runs the three checks the repository declares and reports each count, so a
change can be compared against the state before it rather than asserted to be clean.

Only the test suite gates the exit status. Lint and type counts are reported
because both currently have a nonzero baseline that is being reduced against
named work items -- failing the run on them would make the report unusable
until that work finishes, which is when it is most needed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def lint_counts() -> dict[str, object]:
    """Ruff findings over the selected rule set, by rule."""
    code, output = _run([sys.executable, "-m", "ruff", "check", "--statistics", "src", "tests"])
    by_rule = {}
    for line in output.splitlines():
        match = re.match(r"\s*(\d+)\s+([A-Z]+\d+)\s", line)
        if match:
            by_rule[match.group(2)] = int(match.group(1))
    return {
        "total": sum(by_rule.values()),
        "by_rule": dict(sorted(by_rule.items(), key=lambda item: -item[1])),
        "clean": code == 0,
    }


def type_counts() -> dict[str, object]:
    """Mypy errors over the configured files, by category."""
    code, output = _run([sys.executable, "-m", "mypy"])
    by_category: dict[str, int] = {}
    for match in re.finditer(r"\[([a-z-]+)\]\s*$", output, re.MULTILINE):
        by_category[match.group(1)] = by_category.get(match.group(1), 0) + 1
    total = 0
    found = re.search(r"Found (\d+) error", output)
    if found:
        total = int(found.group(1))
    return {
        "total": total,
        "by_category": dict(sorted(by_category.items(), key=lambda item: -item[1])),
        "clean": code == 0,
    }


def test_counts() -> dict[str, object]:
    """Pytest results. The only check that gates the exit status."""
    code, output = _run([sys.executable, "-m", "pytest", "-q"])
    passed = failed = 0
    summary = re.search(r"(\d+) passed", output)
    if summary:
        passed = int(summary.group(1))
    failure = re.search(r"(\d+) failed", output)
    if failure:
        failed = int(failure.group(1))
    return {"passed": passed, "failed": failed, "clean": code == 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-tests", action="store_true",
        help="report lint and types only; the suite is the slow part",
    )
    args = parser.parse_args(argv)

    report: dict[str, object] = {
        "format": "codess.quality-report/1",
        "lint": lint_counts(),
        "types": type_counts(),
    }
    if not args.skip_tests:
        report["tests"] = test_counts()
    print(json.dumps(report, indent=2, sort_keys=True))
    tests = report.get("tests")
    if isinstance(tests, dict) and not tests.get("clean"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
