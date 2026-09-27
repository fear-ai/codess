"""The suite reads no operator data and writes no operator state."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import codess.config as config

HOME = Path.home()

# Stated here rather than imported from `conftest`: importing it by name loads a
# second copy that repeats its environment setup, and the list is the contract
# this file checks.
ISOLATED_LOCATIONS = (
    "CODESS_STORE_ROOT",
    "CODESS_CATALOG",
    "CODESS_CC_PROJECTS",
    "CODESS_CODEX_SESSIONS",
    "CODESS_CODEX_ARCHIVED_SESSIONS",
    "CODESS_CURSOR_DATA",
)


def _outside_home_codess(path: Path) -> bool:
    """Not under any location a default configuration would name."""
    defaults = (
        HOME / ".codess", HOME / ".claude", HOME / ".codex",
        HOME / "Library" / "Application Support" / "Cursor", HOME / ".config" / "Cursor",
    )
    resolved = path.resolve()
    return not any(resolved.is_relative_to(default.resolve()) for default in defaults)


def test_import_time_locations_are_isolated():
    """`config` resolves these at import, before any per-test fixture runs."""
    for location in (
        config.STORE_ROOT, config.CC_PROJECTS, config.CODEX_SESSIONS,
        config.CURSOR_DATA, config.catalog_root(),
    ):
        assert _outside_home_codess(Path(location)), location
    assert config.CODEX_ARCHIVED_SESSIONS is not None
    assert _outside_home_codess(config.CODEX_ARCHIVED_SESSIONS)


def _test_locations() -> list[Path]:
    return [Path(os.environ[name]) for name in ISOLATED_LOCATIONS]


def test_each_test_sees_its_own_locations(tmp_path):
    locations = _test_locations()
    assert locations[0].is_relative_to(tmp_path), "the registry is under tmp_path"
    for location in locations[1:]:
        assert location.is_dir() and not any(location.iterdir()), location
    assert all(_outside_home_codess(location) for location in locations)


def test_a_subprocess_inherits_the_isolation():
    """A child `codess` resolves the same isolated locations at its own import."""
    script = (
        "import codess.config as c; "
        "print(c.STORE_ROOT); print(c.CC_PROJECTS); print(c.CODEX_SESSIONS); "
        "print(c.CODEX_ARCHIVED_SESSIONS); print(c.CURSOR_DATA); print(c.catalog_root())"
    )
    src = Path(__file__).resolve().parent.parent / "src"
    result = subprocess.run(
        [sys.executable, "-c", script], env={**os.environ, "PYTHONPATH": str(src)},
        capture_output=True, text=True, check=True,
    )
    registry, cc, codex, archived, cursor, catalog = (
        Path(line) for line in result.stdout.splitlines()
    )
    assert [registry, catalog, cc, codex, archived, cursor] == _test_locations()
