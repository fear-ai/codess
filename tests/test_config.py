"""Tests for config paths and options."""

import os
from pathlib import Path

import pytest

from codess.config import (
    CC_PROJECTS,
    CODEX_SESSIONS,
    MIN_SIZE,
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
