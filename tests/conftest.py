"""Pytest fixtures and configuration."""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure src/ is on path for codess package
_src = Path(__file__).resolve().parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))
# Test-support modules live beside the tests that use them.
_here = Path(__file__).parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))


def pytest_configure(config):
    """Let child `codess` processes contribute to the coverage run.

    Domain operations launch a second `codess` process, and the CLI integration
    tests drive the command layer through it. A child starts with no coverage
    active, so a parent-only run reports those modules as unexecuted however
    thoroughly the tests exercise them -- `scan_cmd` measured 0% against 53
    tests that run it.

    `coverage` starts in a subprocess only if `COVERAGE_PROCESS_START` names a
    configuration *and* something calls `coverage.process_startup()` during
    interpreter start-up. The supported hook for the second half is a `.pth`
    file in site-packages, which a checkout must not write. A `sitecustomize`
    module on `PYTHONPATH` is imported at the same point and needs nothing
    installed, so the directory holding one is prepended here.

    Does nothing unless the parent is already measuring coverage, so an
    ordinary `pytest` run is unaffected.
    """
    if not os.environ.get("COVERAGE_RUN") and "coverage" not in sys.modules:
        return
    support = Path(__file__).parent / "coverage_support"
    if not (support / "sitecustomize.py").is_file():
        return
    os.environ["COVERAGE_PROCESS_START"] = str(
        Path(__file__).resolve().parent.parent / "pyproject.toml"
    )
    existing = os.environ.get("PYTHONPATH", "")
    if str(support) not in existing.split(os.pathsep):
        os.environ["PYTHONPATH"] = (
            f"{support}{os.pathsep}{existing}" if existing else str(support)
        )


@pytest.fixture(autouse=True)
def isolate_codess_registry(tmp_path, monkeypatch):
    """No test or subprocess may mutate the operator's personal catalog."""
    monkeypatch.setenv("CODESS_REGISTRY", str(tmp_path / "codess-registry"))


@pytest.fixture
def durable_tmp_path():
    """A per-test scratch directory that is not under an OS temp prefix.

    `tmp_path` sits under the OS temp root, which `helpers.
    ephemeral_project_location_reason` rejects as a durable Project
    location by design. Tests that ingest a real Project into the
    registry need a project path the ephemeral-location guard will not
    flag; this fixture provides one under `tests/.scratch/` (gitignored)
    instead of the OS temp directory.
    """
    root = Path(__file__).resolve().parent / ".scratch"
    root.mkdir(exist_ok=True)
    created = tempfile.mkdtemp(dir=root)
    try:
        yield Path(created)
    finally:
        shutil.rmtree(created, ignore_errors=True)
