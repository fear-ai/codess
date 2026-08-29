"""The released manifest stays in step with the files it records.

Manifest hashes were maintained by hand, so a deliberate change to the DDL or
a mapping profile left every loader raising until someone edited a digest
correctly. The tool makes that a command; these tests fix what it may and may
not do, because a tool that rewrites an integrity record is one that must not
paper over an accidental edit.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "tools" / "refresh_schema_manifest.py"


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_released_manifest_is_current():
    """The checked-in manifest matches the checked-in files.

    This is the assertion the tool exists to keep true: a released contract
    whose recorded hashes disagree with the files disables every loader, not
    only the write gate.
    """
    result = _run("--check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "manifest is current" in result.stdout


class TestAgainstACopiedTree:
    """Exercised against a copy, so a test never rewrites the real manifest."""

    @pytest.fixture
    def tree(self, tmp_path):
        root = tmp_path / "repo"
        (root / "tools").mkdir(parents=True)
        shutil.copytree(REPO_ROOT / "schema", root / "schema")
        shutil.copy(TOOL, root / "tools" / TOOL.name)
        shutil.copytree(REPO_ROOT / "src", root / "src")
        return root

    def _manifest(self, tree: Path) -> dict:
        return json.loads(
            (tree / "schema/coschema/manifest.json").read_text(encoding="utf-8")
        )

    def _run_in(self, tree: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(tree / "tools" / TOOL.name), *args],
            cwd=str(tree), capture_output=True, text=True, timeout=120,
        )

    def test_check_reports_a_stale_entry_without_writing(self, tree):
        """`--check` is the verification mode, so it must not repair."""
        ddl = tree / "schema/coschema/sqlite/schema.sql"
        before = self._manifest(tree)["files"]["sqlite_schema"]["digest"]
        ddl.write_text(ddl.read_text(encoding="utf-8") + "\n-- edit\n", encoding="utf-8")

        result = self._run_in(tree, "--check")

        assert result.returncode == 1
        assert "stale: sqlite_schema" in result.stdout
        assert self._manifest(tree)["files"]["sqlite_schema"]["digest"] == before

    def test_refresh_updates_only_the_changed_entry(self, tree):
        ddl = tree / "schema/coschema/sqlite/schema.sql"
        before = self._manifest(tree)["files"]
        ddl.write_text(ddl.read_text(encoding="utf-8") + "\n-- edit\n", encoding="utf-8")

        result = self._run_in(tree)

        assert result.returncode == 0
        after = self._manifest(tree)["files"]
        assert after["sqlite_schema"]["digest"] != before["sqlite_schema"]["digest"]
        unchanged = {
            role for role in before
            if role != "sqlite_schema"
            and before[role]["digest"] == after[role]["digest"]
        }
        assert unchanged == set(before) - {"sqlite_schema"}

    def test_a_refreshed_manifest_then_checks_clean(self, tree):
        ddl = tree / "schema/coschema/sqlite/schema.sql"
        ddl.write_text(ddl.read_text(encoding="utf-8") + "\n-- edit\n", encoding="utf-8")
        assert self._run_in(tree).returncode == 0
        assert self._run_in(tree, "--check").returncode == 0

    def test_a_missing_released_file_is_an_error_not_a_refresh(self, tree):
        """A file that is gone is a broken release, not a stale hash.

        Recording its absence would turn a detectable fault into a manifest
        that describes a tree nobody can rebuild from.
        """
        (tree / "schema/coschema/sqlite/schema.sql").unlink()

        result = self._run_in(tree)

        assert result.returncode == 2
        assert "missing" in result.stderr

    def test_the_manifest_keeps_its_shape(self, tree):
        """Only the hashes move; roles, paths, and the format stay put."""
        ddl = tree / "schema/coschema/sqlite/schema.sql"
        before = self._manifest(tree)
        ddl.write_text(ddl.read_text(encoding="utf-8") + "\n-- edit\n", encoding="utf-8")
        self._run_in(tree)
        after = self._manifest(tree)

        assert set(before) == set(after)
        assert before["format_version"] == after["format_version"]
        assert set(before["files"]) == set(after["files"])
        assert all(
            before["files"][role]["path"] == after["files"][role]["path"]
            for role in before["files"]
        )


class TestFormatNumberAgreement:
    """The four files stating the CoSchema format agree with the declaration.

    `FORMAT_VERSION` declares it; the manifest, the DDL's `PRAGMA user_version`,
    and the contract each restate it. Every restatement is compared at the point
    it is used -- on a store open, at store creation, on a contract read -- so
    a stale value is detected, but only when something exercises that path.

    These assert the agreement directly, so a bump that misses a file fails on
    the file rather than on whichever store operation happened to run first.
    """

    def test_manifest_states_the_declared_format(self):
        from codess.schema_contract import FORMAT_VERSION, MANIFEST_PATH
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        assert manifest["format_version"] == FORMAT_VERSION, (
            "run tools/refresh_schema_manifest.py"
        )

    def test_ddl_stamps_the_declared_format(self):
        """`PRAGMA user_version` is what labels a newly written store."""
        import re

        from codess.schema_contract import DDL_PATH, FORMAT_VERSION
        stamped = re.search(
            r"PRAGMA\s+user_version\s*=\s*(\d+)",
            DDL_PATH.read_text(encoding="utf-8"),
        )
        assert stamped is not None, "the DDL declares no user_version"
        assert int(stamped.group(1)) == FORMAT_VERSION

    def test_contract_states_the_declared_format(self):
        """Read by no code, so only a check keeps it honest."""
        from codess.schema_contract import CONTRACT_PATH, FORMAT_VERSION
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        assert contract["format_version"] == FORMAT_VERSION

    def test_the_manifest_hashes_are_current(self):
        """`--check` reports staleness without writing, and must find none."""
        result = subprocess.run(
            [sys.executable, str(TOOL), "--check"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, (
            f"released schema files disagree with the manifest; run "
            f"tools/refresh_schema_manifest.py\n{result.stdout}"
        )


class TestFormatAgreementIsCheckableAtTheCommit:
    """The four declarations are checked from one implementation, not three.

    Detection moved outward in three steps: the next store open, then the test
    run (`pytest_configure`), and now the commit that broke it. Each reads the
    same checker, so the hook cannot enforce a different rule than the suite.
    """

    def test_the_released_files_agree_today(self):
        import sys
        from pathlib import Path

        tools = Path(__file__).resolve().parent.parent / "tools"
        if str(tools) not in sys.path:
            sys.path.insert(0, str(tools))
        from format_agreement import failure_message

        assert failure_message() is None

    def test_a_stale_contract_is_named_with_its_remedy(self, monkeypatch, tmp_path):
        """The message names the file, not the symptom a layer away."""
        import json
        import sys
        from pathlib import Path

        tools = Path(__file__).resolve().parent.parent / "tools"
        if str(tools) not in sys.path:
            sys.path.insert(0, str(tools))
        import format_agreement

        from codess.schema_contract import CONTRACT_PATH, FORMAT_VERSION

        stale = tmp_path / "contract.json"
        document = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        document["format_version"] = FORMAT_VERSION + 90
        stale.write_text(json.dumps(document), encoding="utf-8")
        monkeypatch.setattr(
            "codess.schema_contract.CONTRACT_PATH", stale, raising=False,
        )
        found, remedies = format_agreement.disagreements()
        assert any("contract.json states" in item for item in found)
        assert any("contract.json" in item for item in remedies)

    def test_the_conftest_gate_and_the_hook_share_one_checker(self):
        """Two copies of this rule could disagree about what is stale."""
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        conftest = (root / "tests" / "conftest.py").read_text(encoding="utf-8")
        hook_tool = (root / "tools" / "install_hooks.py").read_text(encoding="utf-8")
        assert "from format_agreement import failure_message" in conftest
        assert "format_agreement.py" in hook_tool

    def test_the_hook_leaves_an_escape_hatch(self):
        """A hook with no bypass is one an operator disables permanently."""
        from pathlib import Path

        hook = (
            Path(__file__).resolve().parent.parent / "tools" / "install_hooks.py"
        ).read_text(encoding="utf-8")
        assert "--no-verify" in hook

    def test_installing_does_not_overwrite_a_foreign_hook(self, tmp_path):
        import sys
        from pathlib import Path

        tools = Path(__file__).resolve().parent.parent / "tools"
        if str(tools) not in sys.path:
            sys.path.insert(0, str(tools))
        from install_hooks import install

        hooks = tmp_path / "hooks"
        hooks.mkdir()
        existing = hooks / "pre-commit"
        existing.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
        message = install(hooks)
        assert "already exists" in message
        assert existing.read_text(encoding="utf-8") == "#!/bin/sh\necho mine\n"

    def test_installing_writes_an_executable_hook(self, tmp_path):
        import os
        import sys
        from pathlib import Path

        tools = Path(__file__).resolve().parent.parent / "tools"
        if str(tools) not in sys.path:
            sys.path.insert(0, str(tools))
        from install_hooks import install

        hooks = tmp_path / "hooks"
        message = install(hooks)
        assert "installed" in message
        target = hooks / "pre-commit"
        assert os.access(target, os.X_OK)
        assert "format_agreement.py" in target.read_text(encoding="utf-8")
