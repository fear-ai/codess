"""Slug decoding, review-tree exclusion, and aggregator configuration.

Paths here are synthetic. An earlier version asserted against one developer's
real directory layout -- `/Users/<name>/Work/<their-projects>` -- which tied
the suite to a machine, disclosed that machine in a released repository, and
tested the layout rather than the rule. What each of these establishes is a
property of the mechanism: which segment is matched, whether matching is
positional, and that configuration replaces the default rather than extending
it.
"""

from pathlib import Path

import pytest

from codess.config import env_path_list
from codess.helpers import is_excluded, slug_to_path


class TestSlugToPath:
    """Claude's slug encoding, reversed."""

    def test_empty_slug(self):
        assert slug_to_path("") == Path()

    def test_leading_separator_becomes_absolute(self):
        assert slug_to_path("-home-user-work-proj") == Path("/home/user/work/proj")

    def test_no_leading_separator_stays_relative(self):
        assert slug_to_path("group-proj") == Path("group/proj")


class TestReviewExclusion:
    """Review and backup trees are excluded by segment, not by substring.

    The exclusion set is empty by default (`config.DEFAULT_EXCLUDE_REVIEW_DIRS`)
    because which trees hold copies of other repositories is a property of one
    machine. These configure it explicitly, which is also how an operator uses
    it.
    """

    @pytest.fixture(autouse=True)
    def _configured(self, monkeypatch):
        monkeypatch.setenv(
            "CODESS_EXCLUDE_REVIEW_DIRS", "Tools,Mirror/Bundled,Research/Archive"
        )
        monkeypatch.setattr(
            "codess.helpers.EXCLUDE_REVIEW_DIRS",
            env_path_list("CODESS_EXCLUDE_REVIEW_DIRS", ()),
        )

    def test_a_configured_prefix_is_excluded(self):
        assert is_excluded(Path("/w/Tools/vendor-checkout"), Path("/w"))

    def test_a_multi_segment_prefix_is_excluded(self):
        assert is_excluded(Path("/w/Mirror/Bundled/library"), Path("/w"))

    def test_the_parent_of_a_multi_segment_prefix_is_not(self):
        """`Mirror/Bundled` is excluded; `Mirror` alone is a real location."""
        assert not is_excluded(Path("/w/Mirror"), Path("/w"))

    def test_an_unlisted_tree_is_not_excluded(self):
        assert not is_excluded(Path("/w/Clients/active-project"), Path("/w"))

    def test_exclusion_is_independent_of_the_scan_root(self):
        """The defect this fixed: matching was a prefix of the relative path.

        The same directory was excluded or included depending on where the
        scan started, so a Project appeared and disappeared with the argument
        rather than with its own location. Matching on segments means the two
        roots below agree.
        """
        assert is_excluded(Path("/one/Mirror/Bundled/library"), Path("/one"))
        assert is_excluded(
            Path("/another/root/Mirror/Bundled/library"), Path("/another/root")
        )


class TestBackupExclusion:
    """Backup directory names are excluded wherever they appear."""

    def test_an_old_directory_is_excluded(self):
        assert is_excluded(Path("/w/group/OLD/project"), Path("/w"))

    def test_a_save_directory_is_excluded(self):
        assert is_excluded(Path("/w/group/Save/project"), Path("/w"))

    def test_an_ordinary_project_is_not(self):
        assert not is_excluded(Path("/w/group/project"), Path("/w"))

    def test_a_path_outside_the_work_root_is_not_classified(self):
        """`is_excluded` answers about the tree it was given, not any path."""
        assert not is_excluded(Path("/elsewhere/OLD/project"), Path("/w"))


class TestAggregators:
    """Grouping directories are configured, never assumed.

    The default is empty: shipping one developer's grouping names would
    exclude directories on every other machine for a reason the operator
    could not see.
    """

    def test_the_default_is_empty(self):
        from codess.config import DEFAULT_AGGREGATORS

        assert DEFAULT_AGGREGATORS == ()

    def test_configuration_supplies_them(self, monkeypatch):
        monkeypatch.setenv("CODESS_AGGREGATORS", "Clients,Research,Sandbox")
        assert env_path_list("CODESS_AGGREGATORS", ()) == (
            "Clients", "Research", "Sandbox",
        )

    def test_an_empty_value_states_that_there_are_none(self, monkeypatch):
        """Distinct from unset, which would fall back to the default."""
        monkeypatch.setenv("CODESS_AGGREGATORS", "")
        assert env_path_list("CODESS_AGGREGATORS", ("Fallback",)) == ()
