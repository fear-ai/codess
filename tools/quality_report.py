#!/usr/bin/env python3
"""Report lint, type, and test results as one measurement.

A clean run means the selected rules passed, and a rule set nobody selected proves
nothing. This runs the three checks the repository declares and reports each count, so a
change can be compared against the state before it rather than asserted to be clean.

**A count without a baseline cannot detect a regression.** Two new type errors in
a 144-error report are invisible to a reader, which is not hypothetical: two
name-shadowing defects reached the working tree in one session, both reported
precisely by mypy, both lost in the total. So the counts are compared against
recorded baselines and the run fails when one *rises*, while a nonzero baseline
stays acceptable.

That is the same distinction `codess.workload` makes for performance: recording a
timing is not the same as reporting whether it regressed.

Update a baseline deliberately, with `--accept`, when a change reduces a count or
when a new check legitimately raises one. The exit status gates on the test suite
and on any count exceeding its baseline.
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


BASELINE_PATH = ROOT / "schema" / "quality-baseline.json"

BASELINE_FORMAT = "codess.quality-baseline/1"


def load_baseline() -> dict[str, int]:
    """The recorded ceilings, or empty when none has been accepted yet."""
    try:
        document = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if document.get("format") != BASELINE_FORMAT:
        return {}
    counts = document.get("counts", {})
    return {key: int(value) for key, value in counts.items()}


def write_baseline(counts: dict[str, int]) -> None:
    BASELINE_PATH.write_text(
        json.dumps(
            {
                "format": BASELINE_FORMAT,
                "counts": dict(sorted(counts.items())),
                "note": (
                    "Ceilings, not targets. A count at or below its entry passes; "
                    "a rise fails. Lower an entry when a change reduces a count, "
                    "with tools/quality_report.py --accept."
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def compare(report: dict[str, object], baseline: dict[str, int]) -> dict[str, object]:
    """Which counts rose above their recorded ceiling.

    Reports each measured count beside its ceiling rather than only the failures,
    so a reader sees the margin and can tell a count that is one away from its
    ceiling from one that is fifty below.
    """
    measured: dict[str, int] = {}
    for section in ("lint", "types"):
        value = report.get(section)
        if isinstance(value, dict):
            measured[section] = int(value.get("total", 0))
    rows = {}
    regressed = []
    for key, count in sorted(measured.items()):
        ceiling = baseline.get(key)
        rows[key] = {
            "count": count,
            "baseline": ceiling,
            "margin": None if ceiling is None else ceiling - count,
        }
        if ceiling is not None and count > ceiling:
            regressed.append(key)
    return {
        "measured": rows,
        "regressed": regressed,
        "baseline_recorded": bool(baseline),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-tests", action="store_true",
        help="report lint and types only; the suite is the slow part",
    )
    parser.add_argument(
        "--accept", action="store_true",
        help="record the measured counts as the new baseline",
    )
    args = parser.parse_args(argv)

    report: dict[str, object] = {
        "format": "codess.quality-report/1",
        "lint": lint_counts(),
        "types": type_counts(),
    }
    if not args.skip_tests:
        report["tests"] = test_counts()

    baseline = load_baseline()
    comparison = compare(report, baseline)
    report["baseline"] = comparison

    if args.accept:
        counts = {
            key: int(row["count"])
            for key, row in comparison["measured"].items()  # type: ignore[union-attr]
        }
        write_baseline(counts)
        report["baseline"] = {"accepted": counts}

    print(json.dumps(report, indent=2, sort_keys=True))

    tests = report.get("tests")
    if isinstance(tests, dict) and not tests.get("clean"):
        return 1
    if not args.accept and comparison["regressed"]:
        print(
            "\nquality: "
            + ", ".join(str(key) for key in comparison["regressed"])
            + " rose above the recorded baseline. A count nobody compares cannot "
            "detect a regression -- reduce it, or accept a new ceiling with "
            "--accept and say why.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
