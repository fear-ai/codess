"""Pytest fixtures and configuration."""

import sys
from pathlib import Path

import pytest

# Ensure src/ is on path for codess package
_src = Path(__file__).resolve().parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


@pytest.fixture(autouse=True)
def isolate_codess_registry(tmp_path, monkeypatch):
    """No test or subprocess may mutate the operator's personal catalog."""
    monkeypatch.setenv("CODESS_REGISTRY", str(tmp_path / "codess-registry"))
