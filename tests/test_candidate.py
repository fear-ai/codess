"""Unit tests for codess.helpers and codess.config (slug, exclude, aggregators)."""

from pathlib import Path

from codess.config import AGGREGATORS as conf_aggregators
from codess.helpers import is_excluded, slug_to_path


def test_slug_to_path_empty():
    assert slug_to_path("") == Path(".")


def test_slug_to_path_leading_dash():
    assert slug_to_path("-Users-walter-Work-WP") == Path("/Users/walter/Work/WP")


def test_slug_to_path_relative():
    assert slug_to_path("WP-harduw") == Path("WP/harduw")


def test_is_excluded_backup_old():
    p = Path("/Users/walter/Work/WP/OLD/multiwp")
    assert is_excluded(p)


def test_is_excluded_backup_save():
    p = Path("/Users/walter/Work/Github/Save/avtran")
    assert is_excluded(p)


def test_is_excluded_review_codingtools():
    p = Path("/Users/walter/Work/CodingTools/codex/codex-rs")
    assert is_excluded(p)


def test_is_excluded_review_mcp_mcps():
    p = Path("/Users/walter/Work/MCP/MCPs/fastmcp")
    assert is_excluded(p)


def test_is_not_excluded_project():
    p = Path("/Users/walter/Work/WP/harduw")
    assert not is_excluded(p)


def test_is_not_excluded_mcp_top_level():
    """MCP itself is not in EXCLUDE_REVIEW_DIRS; only MCP/MCPs."""
    p = Path("/Users/walter/Work/MCP")
    assert not is_excluded(p)


def test_aggregators_contains_codingtools():
    assert "CodingTools" in conf_aggregators
