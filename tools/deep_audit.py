#!/usr/bin/env python3
"""Run every check the repository knows how to run, and say which findings matter.

`quality_report.py` answers "did anything regress" against recorded ceilings and
is what a change runs before it lands. This answers a different question --
"what does the whole tool set see" -- by running rule families that are
deliberately *not* selected for the ordinary gate, plus tools that are not
installed as dependencies at all. It is a periodic audit rather than a gate.

**Why the two are separate.** A gate must be fast, deterministic, and clean, or
it stops being read. An audit is allowed to be slow, to report findings nobody
will act on today, and to depend on a tool that may be absent -- but it must
then say what it could not run, because a missing tool reporting nothing is
indistinguishable from a clean result.

**Findings are graded, because a raw union of every rule is unreadable.** The
grading is the point: ruff reports a missing trailing comma and a mutable
default argument with equal prominence, and only one of those is a defect. Each
family below is assigned a tier with the reason, so the output leads with what
is likely to be wrong rather than with what is merely numerous.

Writes a timestamped JSON log so successive runs can be compared, which is what
turns "197 docstring findings" into "12 more than last month".
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "output" / "audits"

# --- Grading -----------------------------------------------------------------
#
# LIKELY_DEFECT   the rule reports something that is probably wrong at runtime.
#                 Read every one of these.
# DESIGN          not wrong today, but the shape that produced past defects
#                 here: unbounded reads, silent excepts, complexity.
# CONVENTION      style the repository has decided against, kept visible so the
#                 decision stays a decision rather than becoming an accident.
LIKELY_DEFECT, DESIGN, CONVENTION = "likely-defect", "design", "convention"

RUFF_FAMILIES: dict[str, tuple[str, str]] = {
    # Selected in pyproject and therefore normally zero; listed so the audit
    # reports them at their tier rather than assuming the gate covered them.
    "F": (LIKELY_DEFECT, "undefined name, unused import, f-string without placeholders"),
    "B": (LIKELY_DEFECT, "bugbear: mutable default, loop-variable capture, assert on tuple"),
    "A": (LIKELY_DEFECT, "a name shadows a builtin"),
    "S": (LIKELY_DEFECT, "bandit: SQL construction and subprocess use"),
    "DTZ": (LIKELY_DEFECT, "naive datetime where the codebase requires UTC-aware"),
    # RUF100 (unused noqa) is excluded: running one family at a time makes
    # every noqa for a *different* family look unused, so it reports an
    # artifact of this tool's method rather than a finding about the code.
    "RUF": (LIKELY_DEFECT, "ruff's own checks, including mutable class defaults"),
    "PLE": (LIKELY_DEFECT, "pylint error class, as implemented by ruff"),
    "ASYNC": (LIKELY_DEFECT, "blocking call in async code"),
    # Not selected: reported for judgement rather than enforcement.
    "C90": (DESIGN, "mccabe complexity above the configured ceiling"),
    "PLR": (DESIGN, "pylint refactor class: too many branches, arguments, returns"),
    "TRY": (DESIGN, "exception handling shape"),
    "PERF": (DESIGN, "avoidable per-iteration work"),
    "SLF": (DESIGN, "private member accessed from outside its owner"),
    "ARG": (DESIGN, "an argument the function never reads"),
    "ANN": (CONVENTION, "annotation coverage; `Any` at a heterogeneous boundary is the rule here"),
    "D": (CONVENTION, "docstring conventions beyond D205, which is selected"),
    "COM": (CONVENTION, "trailing-comma placement"),
    "Q": (CONVENTION, "quote style"),
    "EM": (CONVENTION, "exception message assembled inline"),
}

TIER_ORDER = [LIKELY_DEFECT, DESIGN, CONVENTION]


def _run(command: list[str], timeout: int = 900) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True,
            check=False, timeout=timeout,
        )
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def _tool_available(module: str) -> bool:
    code, _ = _run([sys.executable, "-m", module, "--version"], timeout=60)
    return code == 0


def ruff_by_family(targets: list[str]) -> dict[str, dict[str, object]]:
    """Every graded family, counted separately.

    Run per family rather than once with everything selected: a single run
    reports a union in which the four findings that matter are buried under
    five hundred that do not, which is the readability problem this tool
    exists to solve.
    """
    results = {}
    for family, (tier, why) in RUFF_FAMILIES.items():
        code, output = _run(
            [sys.executable, "-m", "ruff", "check", "--select", family,
             "--ignore", "RUF100", "--statistics", *targets],
        )
        by_rule = {}
        for line in output.splitlines():
            match = re.match(r"\s*(\d+)\s+([A-Z]+\d+)\s", line)
            if match:
                by_rule[match.group(2)] = int(match.group(1))
        results[family] = {
            "tier": tier,
            "describes": why,
            "total": sum(by_rule.values()),
            "by_rule": dict(sorted(by_rule.items(), key=lambda item: -item[1])),
            "ran": code in (0, 1),
        }
    return results


def pylint_duplication() -> dict[str, object]:
    """Near-identical blocks across modules, which no ruff rule reports.

    This is the one capability that is not available elsewhere in the tool set:
    ruff has no cross-file duplicate detection, and the structural check in
    `tests/test_structural_duplication.py` compares whole functions, so it
    cannot see a repeated *fragment* shared by two larger functions.
    """
    if not _tool_available("pylint"):
        return {"available": False, "reason": "pylint is not installed"}
    code, output = _run(
        [sys.executable, "-m", "pylint", "codess", "cli",
         "--disable=all", "--enable=R0801", "--output-format=text"],
        timeout=1200,
    )
    clusters = []
    current: list[str] = []
    for line in output.splitlines():
        if "R0801" in line:
            if current:
                clusters.append(current)
            current = []
        elif line.startswith("=="):
            current.append(line.lstrip("=").strip())
    if current:
        clusters.append(current)
    return {
        "available": True,
        "clusters": len([c for c in clusters if c]),
        "pairs": [c for c in clusters if c][:20],
        "ran": code != 127,
    }


def complexity() -> dict[str, object]:
    """Functions too branchy to hold in mind, named rather than counted."""
    if not _tool_available("radon"):
        return {"available": False, "reason": "radon is not installed"}
    code, output = _run([sys.executable, "-m", "radon", "cc", "src", "-s", "-n", "D"])
    worst = []
    for line in output.splitlines():
        match = re.search(r"([FCM])\s+(\d+):\d+\s+(\S+)\s+-\s+([A-F])\s+\((\d+)\)", line)
        if match:
            worst.append({
                "name": match.group(3),
                "line": int(match.group(2)),
                "grade": match.group(4),
                "score": int(match.group(5)),
            })
    worst.sort(key=lambda item: -item["score"])
    return {"available": True, "above_c": len(worst), "worst": worst[:12], "ran": code == 0}


def dead_code() -> dict[str, object]:
    """Definitions nothing reaches, at a confidence that avoids the dynamic-attribute noise."""
    if not _tool_available("vulture"):
        return {"available": False, "reason": "vulture is not installed"}
    code, output = _run([sys.executable, "-m", "vulture", "src", "--min-confidence", "80"])
    findings = [line for line in output.splitlines() if ":" in line]
    return {"available": True, "findings": len(findings), "items": findings[:20], "ran": code in (0, 3)}


def interpret(report: dict[str, object]) -> list[str]:
    """What a reader should act on, in the order they should read it.

    Returns statements rather than counts: a count is what the report already
    holds, and an audit that only recounts it has not interpreted anything.
    """
    alerts: list[str] = []
    families: dict[str, dict[str, object]] = report["ruff"]  # type: ignore[assignment]

    for tier in TIER_ORDER:
        for family, data in sorted(families.items()):
            if data["tier"] != tier or not data["total"]:
                continue
            rules = ", ".join(f"{rule} x{count}" for rule, count in list(data["by_rule"].items())[:4])
            if tier == LIKELY_DEFECT:
                alerts.append(
                    f"DEFECT  ruff/{family}: {data['total']} finding(s) in a family that "
                    f"is selected and should be zero -- {rules}"
                )
            elif tier == DESIGN:
                alerts.append(
                    f"DESIGN  ruff/{family}: {data['total']} -- {data['describes']} ({rules})"
                )

    duplication: dict[str, object] = report["duplication"]  # type: ignore[assignment]
    if duplication.get("available") and duplication.get("clusters"):
        alerts.append(
            f"DESIGN  pylint/R0801: {duplication['clusters']} cluster(s) of near-identical "
            "lines across modules; no ruff rule reports this"
        )

    hardest: dict[str, object] = report["complexity"]  # type: ignore[assignment]
    if hardest.get("available") and hardest.get("worst"):
        worst = hardest["worst"][0]
        alerts.append(
            f"DESIGN  radon/cc: {hardest['above_c']} function(s) above grade C, worst "
            f"{worst['name']} at {worst['score']}"
        )

    unavailable = [
        name for name in ("duplication", "complexity", "dead_code")
        if isinstance(report.get(name), dict) and not report[name].get("available")
    ]
    if unavailable:
        alerts.append(
            "GAP     not run, so these report nothing rather than nothing found: "
            + ", ".join(unavailable)
        )
    if not alerts:
        alerts.append("No finding above the convention tier.")
    return alerts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--targets", nargs="*", default=["src", "tests", "tools"],
        help="paths to check (default: src tests tools)",
    )
    parser.add_argument(
        "--no-log", action="store_true",
        help="report without writing a timestamped log",
    )
    parser.add_argument(
        "--compare", type=Path,
        help="an earlier audit log to diff the graded totals against",
    )
    args = parser.parse_args(argv)

    report: dict[str, object] = {
        "format": "codess.deep-audit/1",
        "observed_at": datetime.now(UTC).isoformat(),
        "targets": args.targets,
        "ruff": ruff_by_family(args.targets),
        "duplication": pylint_duplication(),
        "complexity": complexity(),
        "dead_code": dead_code(),
    }
    report["alerts"] = interpret(report)

    if args.compare:
        try:
            earlier = json.loads(args.compare.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"codess: cannot read {args.compare}: {exc}", file=sys.stderr)
        else:
            moved = {}
            for family, data in report["ruff"].items():
                was = earlier.get("ruff", {}).get(family, {}).get("total")
                if was is not None and was != data["total"]:
                    moved[family] = {"was": was, "now": data["total"]}
            report["moved_since_compare"] = moved

    if not args.no_log:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = LOG_DIR / f"deep-audit-{stamp}.json"
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report["log"] = str(path.relative_to(ROOT))

    for alert in report["alerts"]:
        print(alert)
    if "log" in report:
        print(f"\nlog: {report['log']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
