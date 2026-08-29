"""The command layer has one fatal-error channel, and it stays observable.

Four command modules each grew their own stderr convention: 59 direct writes,
eleven of which omitted the `codess:` prefix, and three copies of the same
configuration-validation block. A convention held per call site is one a new
call site does not inherit, which is what these assert instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from cli.failure import fail, fail_configuration, warn

COMMAND_MODULES = ("admin_cmd", "scan_cmd", "ingest_cmd", "query_cmd")
SRC = Path(__file__).resolve().parents[1] / "src"


def test_no_command_module_writes_to_stderr_directly() -> None:
    """The channel is `cli.failure`, not a convention repeated per call site.

    Asserted over the syntax tree rather than by grep so a write spelled
    `print(x, file=sys.stderr)` and one spelled with an aliased stream are both
    caught. `failure.py` itself is the exception, because it is the channel.
    """
    offenders: list[str] = []
    for name in COMMAND_MODULES:
        path = SRC / "cli" / f"{name}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders.extend(
            f"{name}.py:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr == "stderr"
        )
    assert not offenders, (
        "report through `cli.failure.fail`/`warn` rather than writing stderr: "
        + ", ".join(offenders)
    )


def test_a_fatal_message_carries_the_prefix(capsys) -> None:
    """One prefix, so our output is distinguishable from a subprocess's."""
    assert fail("--limit must be >= 0") == 1
    assert capsys.readouterr().err == "codess: --limit must be >= 0\n"


def test_an_already_prefixed_message_is_not_prefixed_twice(capsys) -> None:
    """A validator returning a complete line passes through unchanged.

    Several validators compose their own `codess: ...` line and the caller
    printed it verbatim; re-prefixing would produce `codess: codess: ...`.
    """
    assert fail("codess: --source cursor is unavailable") == 1
    assert capsys.readouterr().err == "codess: --source cursor is unavailable\n"


def test_a_fatal_message_reports_the_offending_value_verbatim(capsys) -> None:
    """Maximum observability: the value that failed is in the message.

    A fatal line reports the operator's own machine to the operator on their own
    terminal, so it carries the path, flag, or exception text that names the
    fault. Redaction exists for the event stream, which can be written to a file
    and shipped; a fatal message has no such path, and a redacted one would be
    the single message least able to do its job.
    """
    fail("cannot read /Users/someone/secret/path.json: No such file")
    err = capsys.readouterr().err
    assert "/Users/someone/secret/path.json" in err
    assert "No such file" in err


def test_a_warning_returns_nothing(capsys) -> None:
    """`warn` cannot be written `return warn(...)`.

    Distinct from `fail` by return type rather than by destination: a warning
    that could be returned eventually would be, and the run would exit on a
    condition it was built to survive.
    """
    assert warn("warning: registry has no projects") is None
    assert capsys.readouterr().err == "codess: warning: registry has no projects\n"


def test_configuration_errors_are_all_reported(monkeypatch, capsys) -> None:
    """Every fault, not the first: two faults otherwise take two runs to find."""
    monkeypatch.setattr(
        "codess.config.validate_config",
        lambda: ["AGGREGATORS entry is absolute", "EXCLUDE_REVIEW_DIRS is empty"],
    )
    assert fail_configuration() == 1
    err = capsys.readouterr().err
    assert "AGGREGATORS entry is absolute" in err
    assert "EXCLUDE_REVIEW_DIRS is empty" in err


def test_a_clean_configuration_reports_nothing(monkeypatch, capsys) -> None:
    """Returns 0 so a caller's `if fail_configuration():` does not stop a good run."""
    monkeypatch.setattr("codess.config.validate_config", lambda: [])
    assert fail_configuration() == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("name", COMMAND_MODULES)
def test_every_command_module_imports_the_channel(name: str) -> None:
    """A module reporting failures reaches them the one way.

    Guards the case a converted module is later edited to reintroduce a direct
    write *and* drop the import, which the stderr check above would then pass
    vacuously.
    """
    source = (SRC / "cli" / f"{name}.py").read_text(encoding="utf-8")
    assert "from cli.failure import" in source

@pytest.mark.parametrize("name", COMMAND_MODULES)
def test_every_command_validates_configuration_before_acting(name: str) -> None:
    """A misconfigured variable is refused before a command changes state.

    Each of the four can delete, publish, or rewrite something under a wrong
    store root or an unparseable bound, and `validate_config` is what catches
    those before the first write. `admin_cmd` was the module doing the most
    writing and the only one not checking.
    """
    source = (SRC / "cli" / f"{name}.py").read_text(encoding="utf-8")
    assert "fail_configuration" in source


@pytest.mark.parametrize("name", COMMAND_MODULES)
def test_every_command_attaches_a_sink_and_flushes(name: str) -> None:
    """A command's events reach somewhere, and reach it before the process ends.

    `event()` returns at its first gate when no sink is attached, so a module
    that reports without configuring reports nothing. The ring holds 256 events
    and no command comes close, so a run without a flush emits nothing even with
    a sink attached -- the two are one requirement in two halves.
    """
    source = (SRC / "cli" / f"{name}.py").read_text(encoding="utf-8")
    assert "reporting.configure" in source, f"{name} attaches no sink"
    assert "reporting.flush" in source, f"{name} never flushes"

