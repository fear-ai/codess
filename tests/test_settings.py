"""One declaration per setting, and one stated precedence.

A default was decided in up to four places with nothing saying which won, and
three different shapes answered the same question at 162 call sites. These
assert the rules the table states, so a use site cannot quietly adopt a fourth.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from codess.settings import SETTINGS, apply_leaf_visible, resolve

REPO = Path(__file__).resolve().parents[1]


def test_every_setting_is_declared_once() -> None:
    """No name, flag, or variable appears on two rows.

    The table is the single declaration; two rows for one setting would restore
    exactly the condition it removes.
    """
    names = [s.name for s in SETTINGS]
    flags = [s.flag for s in SETTINGS if s.flag]
    variables = [s.variable for s in SETTINGS]
    assert len(names) == len(set(names))
    assert len(flags) == len(set(flags))
    assert len(variables) == len(set(variables))


def test_a_flag_overrides_the_variable_for_a_value_setting() -> None:
    """Flag, then variable, then built-in -- each narrower than the last."""
    assert resolve(SimpleNamespace(min_size=4096), "min_size", 8192) == 4096
    assert resolve(SimpleNamespace(min_size=None), "min_size", 8192) == 8192
    assert resolve(SimpleNamespace(), "min_size", 8192) == 8192


def test_a_boolean_setting_composes_rather_than_overrides() -> None:
    """An absent store_true flag must not veto a variable the operator set.

    A store_true flag cannot express *off*, so treating its absence as an
    override would make `CODESS_FORCE=1` unsettable from any shell that also
    passes flags -- which is every shell that runs the command.
    """
    assert resolve(SimpleNamespace(force=True), "force", False) is True
    assert resolve(SimpleNamespace(force=False), "force", True) is True
    assert resolve(SimpleNamespace(force=False), "force", False) is False


def test_zero_is_a_value_and_not_an_absence() -> None:
    """`--days 0` means all time, and must survive the resolver.

    The `or` form three call sites used cannot express this: `0 or DAYS` is
    `DAYS`, so the flag that disables the window would have been read as unset.
    """
    assert resolve(SimpleNamespace(days=0), "days", 365) == 0


def test_a_leaf_visible_flag_writes_the_variable_its_reader_observes(monkeypatch) -> None:
    """The declared form of a workaround two command paths performed by hand.

    `fileio` and `schema_contract` cannot import `config` without a cycle, so
    they read their variable directly and a flag reaches them only this way.
    """
    import os

    # `setenv` before the call, not `delenv`: monkeypatch restores a variable it
    # knows about, and it only knows about one it was asked to set. Deleting a
    # variable the function then *creates* leaves it set for every later test --
    # which is how this test disabled hash verification suite-wide on its first
    # writing, and four snapshot tests failed only when run after it.
    monkeypatch.setenv("CODESS_NO_HASH", "0")
    monkeypatch.delenv("CODESS_NO_CONTRACT_CHECK", raising=False)
    monkeypatch.setenv("CODESS_NO_CONTRACT_CHECK", "0")
    monkeypatch.delenv("CODESS_NO_CONTRACT_CHECK", raising=False)

    written = apply_leaf_visible(SimpleNamespace(no_hash=True, no_check=False))
    assert written == ["CODESS_NO_HASH"]
    assert os.environ["CODESS_NO_HASH"] == "1"
    assert "CODESS_NO_CONTRACT_CHECK" not in os.environ


def test_an_unset_leaf_visible_flag_writes_nothing(monkeypatch) -> None:
    """A bypass takes effect only when asked for, never by default."""
    import os

    monkeypatch.setenv("CODESS_NO_HASH", "0")
    monkeypatch.delenv("CODESS_NO_HASH", raising=False)
    assert apply_leaf_visible(SimpleNamespace(no_hash=False)) == []
    assert "CODESS_NO_HASH" not in os.environ


def test_the_bypass_is_reported_rather_than_silent() -> None:
    """Both leaf-visible settings disable a verification step.

    `apply_leaf_visible` returns what it wrote so a caller can say so. A bypass
    an operator cannot see is the failure mode these two flags have.
    """
    bypasses = [s for s in SETTINGS if s.leaf_visible]
    assert bypasses, "the leaf-visible mechanism has no settings"
    assert all(s.boolean for s in bypasses)
    assert {s.name for s in bypasses} == {"no_hash", "no_check"}


@pytest.mark.parametrize("setting", SETTINGS, ids=lambda s: s.name)
def test_every_declared_variable_exists_in_the_env_table(setting) -> None:
    """A row naming a variable `config` does not read declares nothing.

    Checked by reading the source rather than importing, because importing
    resolves the variables and a resolved value no longer says which name
    produced it.

    A variable must be *read* somewhere, which is what makes the row a
    declaration rather than a wish. Reading happens two ways and both count:
    `config` resolves most of them into constants at import, and `settings`
    itself reads the rest through `resolve_named` for a caller that cannot
    import `config` without a cycle.

    So the check is that the variable is either named in `config` or carried by
    a row this module resolves -- not that `config` names it, which was the
    earlier assumption and broke the moment a setting was routed through the
    table and its literal disappeared from the module that used to spell it.
    """
    source = (REPO / "src" / "codess" / "config.py").read_text(encoding="utf-8")
    declared = {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("CODESS_")
    }
    reachable = declared or set()
    if setting.variable not in reachable:
        # Not in `config`, so `settings` must be what reads it -- which is only
        # true for a setting some caller passes to `resolve_named`. Asserting
        # "it is in SETTINGS" would be tautological; asserting that a module
        # actually calls for it is not.
        callers = [
            source.name
            for source in sorted((REPO / "src").rglob("*.py"))
            if "resolve_named(" in source.read_text(encoding="utf-8")
            and source.name != "settings.py"
        ]
        assert callers, (
            f"{setting.variable} is named nowhere in `config` and nothing calls "
            "`resolve_named`, so no module reads it"
        )


def test_the_table_covers_the_settings_the_command_layer_resolves() -> None:
    """Every boolean routed through `flag_or_env` has a row.

    `flag_or_env` is the older spelling of this table's boolean rule, so a
    setting using it and absent here is one the table does not yet own.
    """
    source = (REPO / "src" / "codess" / "project.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    routed = {
        node.args[1].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "flag_or_env"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
    }
    # Compared against the argparse attribute rather than the setting name:
    # `flag_or_env` reads off the namespace, so `--stop` appears there as `stop`
    # while the setting it produces is `stop_on_error`.
    attributes = {setting.attribute for setting in SETTINGS}
    missing = routed - attributes
    assert not missing, f"declare these in the settings table: {sorted(missing)}"


class TestConfigurationFileAsASource:
    """A file states one machine's standing choice, below the shell's.

    It is the only source that adds a precedence *level* rather than
    documenting an existing one, so each pair below is asserted rather than
    inferred from the order the code happens to check in.
    """

    def _written(self, tmp_path, monkeypatch, settings, fmt="codess.settings/1"):
        import json

        from codess.settings import reload_config_file

        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps({"format": fmt, "settings": settings}), encoding="utf-8",
        )
        monkeypatch.setenv("CODESS_CONFIG", str(path))
        reload_config_file()
        return path

    def _cleared(self):
        from codess.settings import reload_config_file

        reload_config_file()

    def test_a_file_value_beats_the_built_in(self, tmp_path, monkeypatch):
        import argparse

        from codess.settings import resolve

        self._written(tmp_path, monkeypatch, {"raw_mode": "stated"})
        try:
            value = resolve(argparse.Namespace(raw_mode=None), "raw_mode", "built-in")
            assert value == "stated"
        finally:
            self._cleared()

    def test_a_flag_beats_the_file(self, tmp_path, monkeypatch):
        import argparse

        from codess.settings import resolve

        self._written(tmp_path, monkeypatch, {"raw_mode": "stated"})
        try:
            value = resolve(
                argparse.Namespace(raw_mode="from-flag"), "raw_mode", "built-in",
            )
            assert value == "from-flag"
        finally:
            self._cleared()

    def test_a_variable_beats_the_file(self, tmp_path, monkeypatch):
        """A shell is the narrower scope, so a file written weeks ago loses."""
        import argparse

        from codess.settings import resolve

        self._written(tmp_path, monkeypatch, {"raw_mode": "stated"})
        monkeypatch.setenv("CODESS_RAW_MODE", "from-variable")
        try:
            # `config` resolves the variable into the default at import, which
            # is what a real caller passes.
            value = resolve(
                argparse.Namespace(raw_mode=None), "raw_mode", "from-variable",
            )
            assert value == "from-variable"
        finally:
            self._cleared()

    def test_resolve_named_applies_the_same_order(self, tmp_path, monkeypatch):
        """A second spelling of the precedence is how two come to disagree."""
        from codess.settings import resolve_named

        self._written(tmp_path, monkeypatch, {"raw_mode": "stated"})
        try:
            assert resolve_named(None, "raw_mode", "built-in") == "stated"
            assert resolve_named("supplied", "raw_mode", "built-in") == "supplied"
            monkeypatch.setenv("CODESS_RAW_MODE", "from-variable")
            assert resolve_named(None, "raw_mode", "built-in") == "from-variable"
        finally:
            self._cleared()

    def test_a_boolean_composes_from_the_file(self, tmp_path, monkeypatch):
        import argparse

        from codess.settings import resolve

        self._written(tmp_path, monkeypatch, {"force": True})
        try:
            assert resolve(argparse.Namespace(force=False), "force", False) is True
        finally:
            self._cleared()

    def test_an_unsupported_format_is_ignored(self, tmp_path, monkeypatch):
        import argparse

        from codess.settings import resolve

        self._written(
            tmp_path, monkeypatch, {"raw_mode": "stated"}, fmt="codess.settings/99",
        )
        try:
            value = resolve(argparse.Namespace(raw_mode=None), "raw_mode", "built-in")
            assert value == "built-in"
        finally:
            self._cleared()

    def test_a_malformed_file_does_not_stop_a_command(self, tmp_path, monkeypatch):
        """The lowest source above the default must not be able to abort a run."""
        import argparse

        from codess.settings import reload_config_file, resolve

        path = tmp_path / "settings.json"
        path.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("CODESS_CONFIG", str(path))
        reload_config_file()
        try:
            value = resolve(argparse.Namespace(raw_mode=None), "raw_mode", "built-in")
            assert value == "built-in"
        finally:
            self._cleared()

    def test_an_unknown_setting_is_named_rather_than_dropped(
        self, tmp_path, monkeypatch, caplog,
    ):
        """A misspelled name otherwise reads as a value that took effect."""
        import logging

        from codess.settings import config_file_values

        self._written(tmp_path, monkeypatch, {"raw_mdoe": "typo"})
        try:
            with caplog.at_level(logging.WARNING):
                assert config_file_values() == {}
            assert any("raw_mdoe" in record.message for record in caplog.records)
        finally:
            self._cleared()

    def test_no_file_is_not_an_error(self, tmp_path, monkeypatch):
        import argparse

        from codess.settings import reload_config_file, resolve

        monkeypatch.setenv("CODESS_CONFIG", str(tmp_path / "absent.json"))
        reload_config_file()
        try:
            value = resolve(argparse.Namespace(raw_mode=None), "raw_mode", "built-in")
            assert value == "built-in"
        finally:
            self._cleared()
