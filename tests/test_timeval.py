"""Contract for `codess.timeval`.

The module is standalone by constraint, so the first test asserts that
constraint rather than a behaviour: a dependency added here would be invisible
until something imported half of Codess to parse a timestamp.

The rest cover the two representations CoSchema fixes -- `_at` Unix
milliseconds and `_when` RFC 3339 UTC -- and the sanity gate that separates a
reported instant from a counter that happens to parse.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from codess.timeval import (
    EPOCH_MS_FLOOR,
    SANITY_FLOOR_MS,
    epoch_ms,
    is_sane,
    iso_to_ms,
    month_key,
    now_iso,
    now_ms,
    parse_iso,
    to_iso,
)

# 2026-08-17T07:40:53.596Z, a Claude record stamp.
CLAUDE_STAMP = "2026-08-17T07:40:53.596Z"
# A Cursor `clientRpcSendTime`: epoch milliseconds, already in CoSchema's unit.
CURSOR_EPOCH_MS = 1754779537731
# A Cursor `clientStartTime`: milliseconds since process start, not an epoch.
CURSOR_UPTIME = 98813.09999990463

NOW_MS = 1_800_000_000_000.0


def test_module_imports_nothing_from_codess() -> None:
    """The standalone constraint, asserted rather than described.

    `timeval` holds no schema, vendor, or configuration knowledge, so a caller
    can parse a timestamp without importing the package around it.
    """
    source = Path(__file__).resolve().parents[1] / "src" / "codess" / "timeval.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not [name for name in imported if name.split(".")[0] == "codess"]


def test_module_does_not_read_an_ambient_clock() -> None:
    """`now_ms` takes the clock; nothing here calls `datetime.now` itself.

    An ambient clock makes a receipt's timestamp depend on when the process ran.
    """
    source = Path(__file__).resolve().parents[1] / "src" / "codess" / "timeval.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"now", "utcnow", "today"}
    ]
    assert not calls


@pytest.mark.parametrize(
    "value",
    [CLAUDE_STAMP, "2026-08-17T07:40:53.596+00:00", f"  {CLAUDE_STAMP}  "],
)
def test_epoch_ms_reads_iso_text(value: str) -> None:
    """ISO text parses, and surrounding whitespace never decides the result."""
    assert epoch_ms(value) == pytest.approx(1786952453596.0)


def test_epoch_ms_scales_seconds_and_keeps_milliseconds() -> None:
    """Both numeric scales appear across the vendors and neither is stated."""
    assert epoch_ms(CURSOR_EPOCH_MS) == float(CURSOR_EPOCH_MS)
    assert epoch_ms(CURSOR_EPOCH_MS / 1000) == pytest.approx(float(CURSOR_EPOCH_MS))
    assert epoch_ms(EPOCH_MS_FLOOR) == float(EPOCH_MS_FLOOR)


def test_epoch_ms_rejects_booleans() -> None:
    """`True` is an `int`, so a flag misread as a time would become 1970."""
    assert epoch_ms(True) is None
    assert epoch_ms(False) is None


@pytest.mark.parametrize("value", [None, "", "   ", "not a time", [], {}, float("nan")])
def test_epoch_ms_returns_none_rather_than_raising(value: object) -> None:
    """One bad field must not abort a decode.

    A caller pairs the result with a field state instead.
    """
    assert epoch_ms(value) is None


def test_epoch_ms_reads_a_numeric_string() -> None:
    """A quoted epoch is a stated value, not text Codess failed to read."""
    assert epoch_ms(str(CURSOR_EPOCH_MS)) == float(CURSOR_EPOCH_MS)


def test_parse_iso_reads_a_naive_stamp_as_utc() -> None:
    """A naive stamp is UTC.

    Read as local time it would shift by the reader's offset, with nothing
    recording why.
    """
    parsed = parse_iso("2026-08-17T07:40:53.596")
    assert parsed is not None
    assert parsed.tzinfo is UTC


def test_to_iso_round_trips_through_epoch_ms() -> None:
    """`_when` text and an `_at` number describe the same instant."""
    rendered = to_iso(CURSOR_EPOCH_MS)
    assert rendered is not None
    assert iso_to_ms(rendered) == pytest.approx(float(CURSOR_EPOCH_MS))


def test_to_iso_of_no_instant_is_none() -> None:
    assert to_iso(None) is None
    assert to_iso("not a time") is None


def test_iso_to_ms_converts_a_when_value_for_comparison() -> None:
    """The two clocks meet here and nowhere else.

    The conversion happens at query time rather than in a stored column.
    """
    assert iso_to_ms(CLAUDE_STAMP) == pytest.approx(1786952453596.0)
    assert iso_to_ms(None) is None


def test_month_key_validates_by_parsing() -> None:
    """`2026-13` has the shape of a month and is not one."""
    assert month_key(CLAUDE_STAMP) == "2026-08"
    assert month_key("2026-13") == "unknown"
    assert month_key(None) == "unknown"


def test_is_sane_rejects_the_cursor_uptime_counter() -> None:
    """A counter that parses must not reach `_derived`.

    `clientStartTime` holds milliseconds since process start, so read as an
    epoch it lands in 1970.
    """
    assert is_sane(epoch_ms(CURSOR_UPTIME), now_milliseconds=NOW_MS) is False


def test_is_sane_accepts_a_reported_instant() -> None:
    assert is_sane(float(CURSOR_EPOCH_MS), now_milliseconds=NOW_MS) is True


def test_is_sane_bounds_both_ends() -> None:
    """Both ends are bounded.

    The floor excludes pre-2020 values; the ceiling allows a clock ahead of this
    one without admitting a counter.
    """
    assert is_sane(SANITY_FLOOR_MS, now_milliseconds=NOW_MS) is True
    assert is_sane(SANITY_FLOOR_MS - 1, now_milliseconds=NOW_MS) is False
    assert is_sane(NOW_MS + 25 * 60 * 60 * 1000, now_milliseconds=NOW_MS) is False


@pytest.mark.parametrize("value", [None, True, "1754779537731", float("inf")])
def test_is_sane_rejects_non_numbers(value: object) -> None:
    assert is_sane(value, now_milliseconds=NOW_MS) is False


def test_now_ms_uses_the_injected_clock() -> None:
    """A fixed clock produces a fixed result.

    That is what makes a receipt testable.
    """
    fixed = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)
    assert now_ms(lambda: fixed) == fixed.timestamp() * 1000


def test_now_iso_uses_the_injected_clock() -> None:
    """The `_when` counterpart to `now_ms`, fixed by the same clock."""
    fixed = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)
    assert now_iso(lambda: fixed) == "2026-08-23T12:00:00+00:00"


def test_now_iso_reads_a_naive_clock_as_utc() -> None:
    """A clock returning a naive stamp is read as UTC, matching `parse_iso`.

    Read as local time instead, a receipt's stamp shifts by the operator's
    offset with nothing recording why.
    """
    naive = datetime(2026, 8, 23, 12, 0, 0)  # noqa: DTZ001 -- naive is the case under test
    assert now_iso(lambda: naive) == "2026-08-23T12:00:00+00:00"


def test_now_iso_converts_a_non_utc_clock() -> None:
    """A clock in another zone is converted rather than relabelled."""
    eastern = datetime(2026, 8, 23, 8, 0, 0, tzinfo=timezone(timedelta(hours=-4)))
    assert now_iso(lambda: eastern) == "2026-08-23T12:00:00+00:00"

# Empty, and kept rather than deleted: it is the record that the exemption
# existed and closed. A module named here is one whose clock reads have not been
# converted; the set was four modules while relay consolidation was pending and
# is now none.
DEFERRED: frozenset[str] = frozenset()


def test_the_ambient_clock_has_one_definition() -> None:
    """`wallclock.system_clock` is the only `datetime.now` in the package.

    The constraint above keeps `timeval` free of an ambient clock; this one
    keeps the clock from reappearing everywhere else. Before it, 43 sites spelled
    `datetime.now(UTC).isoformat()` inline, so a test that needed a fixed clock
    had 43 things to patch and patched none of them.

    `reporting.clock` is exempt: it anchors monotonic ticks for event timing,
    which is a different clock and a different hazard -- a backward NTP step
    there produces a negative duration.

    `DEFERRED` is empty. It held four relay modules while their signatures were
    pending, and each was removed as its module converted -- which is what the
    list form was for: removing a name is an edit a reviewer sees, where a
    pattern would have widened silently.
    """
    source_root = Path(__file__).resolve().parents[1] / "src"
    offenders: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(source_root)
        if relative.parts[:2] == ("codess", "reporting"):
            continue
        if relative.name in {"wallclock.py", *DEFERRED}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders.extend(
            f"{relative}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"now", "utcnow", "today"}
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "datetime"
        )
    assert not offenders, (
        "read the clock through `wallclock.system_clock` rather than directly: "
        + ", ".join(offenders)
    )

