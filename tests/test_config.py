"""Tests for config paths and options."""

import os
from pathlib import Path

import pytest

from config import (
    CC_PROJECTS_DIR,
    CODEX_SESSIONS_DIR,
    get_state_path,
    get_store_path,
    REDACT_PATTERNS,
    STORE_DB_NAME,
    STORE_DIR_NAME,
)


class TestPaths:
    """Path derivation."""

    def test_get_store_path(self, tmp_path):
        store = get_store_path(tmp_path)
        assert store == tmp_path / STORE_DIR_NAME / STORE_DB_NAME

    def test_get_state_path(self, tmp_path):
        state = get_state_path(tmp_path)
        assert state == tmp_path / STORE_DIR_NAME / "ingest_state.json"


class TestEnvOverrides:
    """Environment variable overrides."""

    def test_cc_projects_dir_default(self):
        assert "claude" in str(CC_PROJECTS_DIR).lower() or "projects" in str(CC_PROJECTS_DIR)

    def test_codex_sessions_dir_default(self):
        assert "codex" in str(CODEX_SESSIONS_DIR).lower()

    def test_paths_are_absolute(self):
        assert CC_PROJECTS_DIR.is_absolute()
        assert CODEX_SESSIONS_DIR.is_absolute()


class TestRedactPatterns:
    """REDACT_PATTERNS is non-empty and compilable."""

    def test_patterns_exist(self):
        assert len(REDACT_PATTERNS) >= 1

    def test_patterns_are_compiled(self):
        for p in REDACT_PATTERNS:
            assert hasattr(p, "search")
