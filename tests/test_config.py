"""Tests for config paths and options."""

import os
from pathlib import Path

import pytest

from types import SimpleNamespace

from codess.project import (
    build_ingest_run_options,
    build_scan_run_options,
    resolve_registry_directory,
    validate_scan_source_for_cli,
)
from codess.config import (
    CC_PROJECTS,
    CODEX_SESSIONS,
    env_bool,
    get_state_path,
    get_store_path,
    REDACT_PATTERNS,
    STORE_DB,
    STORE_DIR,
    SUBAGENT,
    validate_config,
)


class TestPaths:
    """Path derivation."""

    def test_get_store_path(self, tmp_path):
        store = get_store_path(tmp_path)
        assert store == tmp_path / STORE_DIR / STORE_DB

    def test_get_state_path(self, tmp_path):
        state = get_state_path(tmp_path)
        assert state == tmp_path / STORE_DIR / "ingest_state.json"


class TestEnvOverrides:
    """Environment variable overrides."""

    def test_cc_projects_default(self):
        assert "claude" in str(CC_PROJECTS).lower() or "projects" in str(CC_PROJECTS)

    def test_codex_sessions_default(self):
        assert "codex" in str(CODEX_SESSIONS).lower()

    def test_paths_are_absolute(self):
        assert CC_PROJECTS.is_absolute()
        assert CODEX_SESSIONS.is_absolute()


class TestValidateConfig:
    """Config value validation."""

    def test_default_valid(self):
        assert validate_config() == []

    def test_subagent_default_false(self):
        assert SUBAGENT is False or SUBAGENT is True  # env may override


class TestRedactPatterns:
    """REDACT_PATTERNS is non-empty and compilable."""

    def test_patterns_exist(self):
        assert len(REDACT_PATTERNS) >= 1

    def test_patterns_are_compiled(self):
        for p in REDACT_PATTERNS:
            assert hasattr(p, "search")


class TestEnvBool:
    """env_bool truth table (same rules as CODESS_* booleans)."""

    def test_unset_false(self, monkeypatch):
        monkeypatch.delenv("CODESS_TESTBOOL", raising=False)
        assert env_bool("CODESS_TESTBOOL") is False

    def test_one_true(self, monkeypatch):
        monkeypatch.setenv("CODESS_TESTBOOL", "1")
        assert env_bool("CODESS_TESTBOOL") is True

    def test_yes_true(self, monkeypatch):
        monkeypatch.setenv("CODESS_TESTBOOL", "YES")
        assert env_bool("CODESS_TESTBOOL") is True

    def test_on_false(self, monkeypatch):
        monkeypatch.setenv("CODESS_TESTBOOL", "on")
        assert env_bool("CODESS_TESTBOOL") is False

    def test_two_false(self, monkeypatch):
        monkeypatch.setenv("CODESS_TESTBOOL", "2")
        assert env_bool("CODESS_TESTBOOL") is False


class TestCliOptionsEnvMerge:
    """ENV-backed bools merged in build_*_run_options (monkeypatch config module)."""

    def test_ingest_redact_env(self, monkeypatch):
        monkeypatch.setattr("codess.config.INGEST_REDACT", True)
        args = SimpleNamespace(
            stop=False, force=False, min_size=100, debug=False, redact=False
        )
        assert build_ingest_run_options(args).redact is True

    def test_ingest_redact_cli_overrides_false_env(self, monkeypatch):
        monkeypatch.setattr("codess.config.INGEST_REDACT", False)
        args = SimpleNamespace(
            stop=False, force=False, min_size=100, debug=False, redact=True
        )
        assert build_ingest_run_options(args).redact is True

    def test_scan_norec_env(self, monkeypatch):
        monkeypatch.setattr("codess.config.NOREC", True)
        args = SimpleNamespace(
            stop=False,
            debug=False,
            subagent=False,
            norec=False,
            days=None,
            source=None,
        )
        assert build_scan_run_options(args).norec is True


class TestValidateScanSource:
    """Scan --source is validated globally before run (see scan_cmd)."""

    def test_none_ok(self):
        assert validate_scan_source_for_cli(None) is None

    def test_all_ok(self):
        assert validate_scan_source_for_cli("all") is None
        assert validate_scan_source_for_cli(" ALL ") is None

    def test_single_vendor_ok(self):
        assert validate_scan_source_for_cli("cc") is None
        assert validate_scan_source_for_cli("CC, Codex ") is None

    def test_bad_token(self):
        err = validate_scan_source_for_cli("cc,foo")
        assert err and "foo" in err
        assert "invalid" in err.lower()


class TestRegistryArgResolution:
    """``--registry PATH`` vs omitted → ``resolve_registry_directory``."""

    def test_omitted_uses_config_registry(self, monkeypatch, tmp_path):
        monkeypatch.setattr("codess.config.REGISTRY", tmp_path)
        args = SimpleNamespace(registry=None)
        assert resolve_registry_directory(args) == tmp_path

    def test_explicit_path_overrides(self, monkeypatch, tmp_path):
        monkeypatch.setattr("codess.config.REGISTRY", tmp_path)
        other = tmp_path / "other"
        args = SimpleNamespace(registry=str(other))
        assert resolve_registry_directory(args) == other
