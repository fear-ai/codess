"""The ingest child invocation: one command builder, one environment.

Five parameters travelled together through seven functions, five of them carrying
the complete set, and three separate functions each built the same `python -m main
ingest` argv by hand. These pin the properties that consolidation bought.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codess.child_invocation import ChildInvocation, RunPolicy

# The policy's fields and the target's, so a test names either without knowing
# which structure holds it. Splitting here rather than at each call site keeps
# every test below stating only what it varies.
_POLICY_FIELDS = frozenset(RunPolicy.__dataclass_fields__)


def _invocation(**overrides) -> ChildInvocation:
    fields = {
        "projects": (Path("/w/p"),),
        "vendor_selector": "all",
        "raw_mode": "reference",
        "registry": Path("/r"),
        "repo_root": Path("/repo"),
    }
    fields.update(overrides)
    policy = {k: v for k, v in fields.items() if k in _POLICY_FIELDS}
    target = {k: v for k, v in fields.items() if k not in _POLICY_FIELDS}
    return ChildInvocation(policy=RunPolicy(**policy), **target)


def _flag_value(command: list[str], flag: str) -> str | None:
    return command[command.index(flag) + 1] if flag in command else None


class TestTheCommandIsBuiltOnce:
    """The three callers' shapes, reproduced from one builder."""

    def test_the_core_flags_are_always_present(self) -> None:
        command = _invocation().command()
        assert command[1:4] == ["-m", "main", "ingest"]
        assert _flag_value(command, "--dir") == "/w/p"
        assert _flag_value(command, "--source") == "all"
        assert _flag_value(command, "--raw-mode") == "reference"
        assert _flag_value(command, "--store") == "/r"
        assert _flag_value(command, "--min-size") == "0"

    def test_several_projects_each_get_a_dir_flag(self) -> None:
        """The catalog path ingests a plan's Projects in one child run."""
        command = _invocation(
            projects=(Path("/w/a"), Path("/w/b")),
        ).command()
        assert [
            command[index + 1]
            for index, token in enumerate(command) if token == "--dir"
        ] == ["/w/a", "/w/b"]

    def test_an_absent_resource_policy_adds_no_flag(self) -> None:
        """A None policy must not become `--resource-policy None`."""
        assert "--resource-policy" not in _invocation().command()

    def test_each_optional_flag_appears_only_when_selected(self) -> None:
        for field, flag in (
            ("validate", "--validate"),
            ("force", "--force"),
            ("candidate_snapshot", "--candidate-snapshot"),
        ):
            assert flag not in _invocation().command()
            assert flag in _invocation(**{field: True}).command()

    def test_live_progress_is_expressed_by_its_absence(self) -> None:
        """`--no-progress` is the flag, so the default is to pass nothing."""
        assert "--no-progress" not in _invocation().command()
        assert "--no-progress" in _invocation(live_progress=False).command()

    def test_two_identical_invocations_build_identical_commands(self) -> None:
        """Ordering is fixed here rather than per caller, so a recorded command
        in a receipt can be compared between runs."""
        assert _invocation().command() == _invocation().command()

    def test_extra_flags_are_appended_last(self) -> None:
        command = _invocation(extra_flags=("--no-hash",)).command()
        assert command[-1] == "--no-hash"


class TestTheEnvironment:
    """Every caller set `PYTHONPATH` from its own copy of `os.environ`."""

    def test_src_is_on_the_import_path(self) -> None:
        assert _invocation().environment()["PYTHONPATH"] == "/repo/src"

    def test_the_parent_environment_is_inherited_not_replaced(self, monkeypatch) -> None:
        """A child that lost the parent's environment would lose every
        `CODESS_*` override an operator set."""
        monkeypatch.setenv("CODESS_TEST_MARKER", "kept")
        assert _invocation().environment()["CODESS_TEST_MARKER"] == "kept"

    def test_the_parent_environment_is_not_mutated(self, monkeypatch) -> None:
        import os

        monkeypatch.delenv("PYTHONPATH", raising=False)
        _invocation().environment()
        assert "PYTHONPATH" not in os.environ


class TestItIsFrozen:
    """An invocation describes a decision already made."""

    def test_a_field_cannot_be_reassigned(self) -> None:
        import dataclasses

        invocation = _invocation()
        with pytest.raises(dataclasses.FrozenInstanceError):
            invocation.vendor_selector = "cc"  # type: ignore[misc]

    def test_a_different_run_is_a_second_object(self) -> None:
        """Which keeps both visible rather than mutating one and losing what it
        was."""
        import dataclasses

        first = _invocation()
        second = dataclasses.replace(first, vendor_selector="cc")
        assert first.vendor_selector == "all"
        assert second.vendor_selector == "cc"


class TestOneRunnerForEveryCaller:
    """The consolidation's point: a single place a test patches, and a single
    place a flag rename reaches."""

    def test_the_run_goes_through_this_module(self, monkeypatch) -> None:
        seen = []

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(
            "codess.child_invocation.subprocess.run",
            lambda command, **kwargs: seen.append((command, kwargs)) or Result(),
        )
        _invocation(policy_timeout=7).run()
        command, kwargs = seen[0]
        assert command[1:4] == ["-m", "main", "ingest"]
        assert kwargs["timeout"] == 7
        assert kwargs["cwd"] == Path("/repo")
        assert kwargs["capture_output"] is True
        assert kwargs["check"] is False

    def test_no_caller_builds_the_ingest_argv_itself(self) -> None:
        """The duplication this replaced: three functions each spelled
        `--source`, `--raw-mode`, and `--registry` into their own list, so a flag
        renamed at the CLI reached all three only if someone edited each."""
        import codess.child_invocation as module

        root = Path(module.__file__).resolve().parents[1]
        offenders = []
        for path in sorted(root.rglob("*.py")):
            if path.name == "child_invocation.py" or "egg-info" in str(path):
                continue
            text = path.read_text(encoding="utf-8")
            if '"-m", "main", "ingest"' in text:
                offenders.append(path.name)
        assert offenders == [], (
            f"these build the ingest argv rather than using ChildInvocation: "
            f"{offenders}"
        )
