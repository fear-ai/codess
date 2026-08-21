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

    A missing or unreadable released file is left to the tests that cover it,
    since failing the whole run on an absent path would hide which check was
    actually broken.
    """
    import re

    try:
        from codess.schema_contract import (
            CONTRACT_PATH,
            DDL_PATH,
            FORMAT_VERSION,
            MANIFEST_PATH,
        )
    except ImportError:
        return

    stale: list[str] = []
    remedies: list[str] = []
    manifest_version = _json_format_version(MANIFEST_PATH)
    if manifest_version is not None and manifest_version != FORMAT_VERSION:
        stale.append(f"{MANIFEST_PATH.name} states {manifest_version}")
        remedies.append("run tools/refresh_schema_manifest.py")
    contract_version = _json_format_version(CONTRACT_PATH)
    if contract_version is not None and contract_version != FORMAT_VERSION:
        stale.append(f"{CONTRACT_PATH.name} states {contract_version}")
        remedies.append(f"edit {CONTRACT_PATH.name}")
    try:
        stamped = re.search(
            r"PRAGMA\s+user_version\s*=\s*(\d+)",
            DDL_PATH.read_text(encoding="utf-8"),
        )
    except OSError:
        stamped = None
    if stamped and int(stamped.group(1)) != FORMAT_VERSION:
        stale.append(f"{DDL_PATH.name} stamps {stamped.group(1)}")
        remedies.append(f"edit {DDL_PATH.name}")

    # A released file edited without refreshing its recorded digest fails the
    # same way and worse: the version checks above name a file, while a stale
    # digest surfaces as several hundred store-opening tests failing on a hash.
    try:
        from codess.schema_contract import contract_digest
        contract_digest()
    except ImportError:
        pass
    except Exception as exc:  # SchemaContractError, and anything it wraps
        stale.append(str(exc))
        remedies.append("run tools/refresh_schema_manifest.py")

    if stale:
        raise pytest.UsageError(
            f"declared CoSchema {FORMAT_VERSION}, {'; '.join(stale)}: "
            f"{', '.join(dict.fromkeys(remedies))}"
        )


def _json_format_version(path):
    """The `format_version` a released JSON file states, or None."""
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8")).get("format_version")
    except (OSError, ValueError):
        return None


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
def isolate_codess_registry(tmp_path, monkeypatch):
    """No test or subprocess may mutate the operator's personal catalog."""
    monkeypatch.setenv("CODESS_STORE_ROOT", str(tmp_path / "codess-registry"))


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
