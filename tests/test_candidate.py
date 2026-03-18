"""Unit tests for scripts/find_candidate.py."""

import sys
from pathlib import Path

# Allow importing from scripts/
scripts = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts))
import find_candidate as wf
import conf_candidate as conf


def test_slug_to_path_empty():
    assert wf.slug_to_path("") == Path(".")


def test_slug_to_path_leading_dash():
    assert wf.slug_to_path("-Users-walter-Work-WP") == Path("/Users/walter/Work/WP")


def test_slug_to_path_relative():
    assert wf.slug_to_path("WP-harduw") == Path("WP/harduw")


def test_is_excluded_backup_old():
    p = Path("/Users/walter/Work/WP/OLD/multiwp")
    assert wf.is_excluded(p)


def test_is_excluded_backup_save():
    p = Path("/Users/walter/Work/Github/Save/avtran")
    assert wf.is_excluded(p)


def test_is_excluded_review_codingtools():
    p = Path("/Users/walter/Work/CodingTools/codex/codex-rs")
    assert wf.is_excluded(p)


def test_is_excluded_review_mcp_mcps():
    p = Path("/Users/walter/Work/MCP/MCPs/fastmcp")
    assert wf.is_excluded(p)


def test_is_not_excluded_project():
    p = Path("/Users/walter/Work/WP/harduw")
    assert not wf.is_excluded(p)


def test_is_not_excluded_mcp_top_level():
    """MCP itself is not in EXCLUDE_REVIEW_DIRS; only MCP/MCPs."""
    p = Path("/Users/walter/Work/MCP")
    assert not wf.is_excluded(p)


def test_aggregators_contains_codingtools():
    assert "CodingTools" in conf.AGGREGATORS
