"""Pytest fixtures and configuration."""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Every location a run reads operator data from or writes state to. `config`
# resolves most of them into constants at import, so they are set here, before
# any test module imports `codess`; the per-test fixture below repeats them for
# subprocesses and for the readers that resolve at call time.
ISOLATED_LOCATIONS = (
    "CODESS_STORE_ROOT",
    "CODESS_CATALOG",
    "CODESS_CC_PROJECTS",
    "CODESS_CODEX_SESSIONS",
    "CODESS_CODEX_ARCHIVED_SESSIONS",
    "CODESS_CURSOR_DATA",
    "CODESS_WORK_ROOT",
)


def _isolate_environment(root: Path) -> None:
    """Drop the developer's Codess settings and point every location at `root`.

    A shell's `CODESS_*` settings otherwise reach the suite: a changed day
    window or bound alters results, and a policy or discovery file names one
    machine's tree. The vendor locations point at empty directories, so a test
    that does not supply its own Sources reads none rather than the developer's.
    """
    for name in [name for name in os.environ if name.startswith("CODESS_")]:
        del os.environ[name]
    for name in ISOLATED_LOCATIONS:
        location = root / name.removeprefix("CODESS_").lower()
        location.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(location)


_SESSION_ROOT = Path(tempfile.mkdtemp(prefix="codess-tests-"))
atexit.register(shutil.rmtree, _SESSION_ROOT, ignore_errors=True)
_isolate_environment(_SESSION_ROOT)

# Ensure src/ is on path for codess package
_src = Path(__file__).resolve().parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))
# Test-support modules live beside the tests that use them.
_here = Path(__file__).parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))


def pytest_configure(config):
    """Check the released schema, then wire coverage for child processes."""
    _require_released_schema_agreement()
    _enable_subprocess_coverage()


def _require_released_schema_agreement() -> None:
    """Fail before collection when a released schema file is stale.

    Four files state the CoSchema format -- the constant that declares it, the
    manifest, the DDL's `PRAGMA user_version`, and the contract -- and each is
    otherwise compared only where it is read. A bump that misses one therefore
    surfaced as hundreds of store-opening tests failing on a message about the
    manifest, which reports the symptom a minute later and one layer away.

    Checked here because `pytest_configure` runs before collection: the run
    stops with the file named, rather than after the suite has exercised
    everything that happens to open a store.

    The check itself lives in `tools/format_agreement.py`, which the pre-commit
    hook also calls, so the same rule is enforced at the commit and at the run
    from one implementation rather than two that can disagree.
    """
    tools = Path(__file__).resolve().parent.parent / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    try:
        from format_agreement import failure_message
    except ImportError:
        return
    message = failure_message()
    if message:
        raise pytest.UsageError(message)




def _enable_subprocess_coverage() -> None:
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
def isolate_codess_registry(tmp_path, tmp_path_factory, monkeypatch):
    """No test or subprocess may read operator data or mutate operator state.

    Per test rather than only per session, so a subprocess one test starts
    cannot see what another left behind. The vendor locations sit outside
    `tmp_path`, which several tests assert holds only what they wrote.
    """
    monkeypatch.setenv("CODESS_STORE_ROOT", str(tmp_path / "codess-registry"))
    root = tmp_path_factory.mktemp("codess-isolated")
    for name in ISOLATED_LOCATIONS[1:]:
        location = root / name.removeprefix("CODESS_").lower()
        location.mkdir()
        monkeypatch.setenv(name, str(location))


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
