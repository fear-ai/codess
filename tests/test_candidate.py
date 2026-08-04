"""Unit tests for codess.helpers and codess.config (slug, exclude, aggregators)."""

from pathlib import Path

from codess.config import AGGREGATORS as conf_aggregators
from codess.helpers import is_excluded, slug_to_path


def test_slug_to_path_empty():
    assert slug_to_path("") == Path(".")


def test_slug_to_path_leading_dash():
    assert slug_to_path("-home-user-work-project") == Path("/home/user/work/project")


def test_slug_to_path_relative():
    assert slug_to_path("WP-proj-n") == Path("group/project")


def test_is_excluded_backup_old():
    p = Path("/home/user/work/project")
    assert is_excluded(p)


def test_is_excluded_backup_save():
    p = Path("/home/user/work/project")
    assert is_excluded(p)


def test_is_excluded_review_codingtools():
    p = Path("/home/user/work/project")
    assert is_excluded(p)


def test_is_excluded_actual_code_codingtools_layout():
    p = Path("/home/user/work/project")
    assert is_excluded(p)


def test_is_excluded_review_mcp_mcps():
    p = Path("/home/user/work/project")
    assert is_excluded(p)


def test_is_not_excluded_project():
    p = Path("/home/user/work/project")
    assert not is_excluded(p)


def test_is_not_excluded_mcp_top_level():
    """MCP itself is not in EXCLUDE_REVIEW_DIRS; only MCP/review."""
    p = Path("/home/user/work/project")
    assert not is_excluded(p)


def test_aggregators_contains_codingtools():
    assert "CodingTools" in conf_aggregators
