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
    """A reference tree is excluded by absolute path.

    `EXCLUDE_REVIEW_DIRS` took work-root-relative segments and was retired into
    `exclude_paths`, which takes absolute paths. The change is not cosmetic: a
    segment list could not name a tree outside the work root, and matched by
    segment anywhere in a path, so `Tools` excluded every directory of that
    name at any depth rather than the one the operator meant.

    Ships empty, so these configure it explicitly -- which is also how an
    operator uses it.
    """

    def _with_exclusions(self, monkeypatch, *paths):
        import importlib

        import codess.helpers as helpers

        monkeypatch.setenv("CODESS_EXCLUDE_PATHS", ",".join(str(p) for p in paths))
        importlib.reload(helpers)
        return helpers

    def _restored(self, monkeypatch):
        import importlib

        import codess.helpers as helpers

        monkeypatch.delenv("CODESS_EXCLUDE_PATHS", raising=False)
        importlib.reload(helpers)
        importlib.reload(importlib.import_module("codess.project"))

    def test_a_configured_tree_is_excluded(self, monkeypatch):
        helpers = self._with_exclusions(monkeypatch, "/w/Tools")
        try:
            assert helpers.is_excluded(Path("/w/Tools/vendor-checkout"), Path("/w"))
        finally:
            self._restored(monkeypatch)

    def test_a_nested_tree_is_excluded(self, monkeypatch):
        helpers = self._with_exclusions(monkeypatch, "/w/Mirror/Bundled")
        try:
            assert helpers.is_excluded(Path("/w/Mirror/Bundled/library"), Path("/w"))
        finally:
            self._restored(monkeypatch)

    def test_the_parent_of_an_excluded_tree_is_not(self, monkeypatch):
        """`Mirror/Bundled` is excluded; `Mirror` alone is a real location."""
        helpers = self._with_exclusions(monkeypatch, "/w/Mirror/Bundled")
        try:
            assert not helpers.is_excluded(Path("/w/Mirror"), Path("/w"))
        finally:
            self._restored(monkeypatch)

    def test_a_same_named_tree_elsewhere_is_not_excluded(self, monkeypatch):
        """The defect the absolute form removes.

        A segment list matched `Tools` at any depth under any parent, so
        excluding one reference tree excluded every directory sharing its name.
        """
        helpers = self._with_exclusions(monkeypatch, "/w/Tools")
        try:
            assert not helpers.is_excluded(Path("/w/project/Tools/src"), Path("/w"))
        finally:
            self._restored(monkeypatch)

    def test_a_tree_outside_the_work_root_can_be_named(self, monkeypatch):
        """A work-root-relative segment could not express this at all."""
        helpers = self._with_exclusions(monkeypatch, "/elsewhere/reference")
        try:
            assert helpers.is_excluded(Path("/elsewhere/reference/clone"), Path("/w"))
        finally:
            self._restored(monkeypatch)


class TestBackupExclusion:
    """Backup directory names are excluded wherever they appear."""

    def test_an_old_directory_is_excluded(self):
        assert is_excluded(Path("/w/group/OLD/project"), Path("/w"))

    def test_backup_names_come_from_the_policy(self):
        """The conventions are policy data, not constants in this module.

        A machine using different backup names replaces the list without
        editing code, which is the property that keeps one tree's conventions
        out of the released source.
        """
        from codess.helpers import BACKUP_CONVENTIONS
        exact, prefix = BACKUP_CONVENTIONS
        assert "OLD" in exact
        assert "Save" in prefix

    def test_lowercase_old_is_a_real_name(self):
        """Matching is case-sensitive, so an ordinary directory survives.

        `old` in lowercase is a name a project legitimately uses; only the
        shouted `OLD` is the kept-aside-copy convention. Case-folding here
        excluded real Projects from discovery.
        """
        assert not is_excluded(Path("/w/group/old/project"), Path("/w"))

    def test_save_matches_as_a_prefix(self):
        """`Save2` and `Saved` are the same convention as `Save`."""
        assert is_excluded(Path("/w/group/Save2/project"), Path("/w"))
        assert is_excluded(Path("/w/group/Saved/project"), Path("/w"))

    def test_a_save_directory_is_excluded(self):
        assert is_excluded(Path("/w/group/Save/project"), Path("/w"))

    def test_an_ordinary_project_is_not(self):
        assert not is_excluded(Path("/w/group/project"), Path("/w"))

    def test_a_path_outside_the_work_root_is_not_classified(self):
        """`is_excluded` answers about the tree it was given, not any path."""
        assert not is_excluded(Path("/elsewhere/OLD/project"), Path("/w"))


class TestAggregatorsRetired:
    """`CODESS_AGGREGATORS` is gone; `exclude_paths` answers what it asked.

    It named a container by structure -- "holds many repositories" -- while the
    operator's criterion is intent: a collection kept for reference rather than
    developed in, which may hold one repository or fifty. On that definition it
    and `EXCLUDE_REVIEW_DIRS` were the same setting under two names.
    """

    def test_the_setting_is_gone(self):
        import codess.config as config

        assert not hasattr(config, "AGGREGATORS")
        assert not hasattr(config, "DEFAULT_AGGREGATORS")

    def test_paths_still_ship_empty(self):
        """A path describes one machine's layout, so no default is portable."""
        import json

        from codess.helpers import DISCOVERY_POLICY_PATH

        document = json.loads(DISCOVERY_POLICY_PATH.read_text(encoding="utf-8"))
        assert document["exclude_paths"] == []
        assert document["include_paths"] == []

    def test_names_still_ship_non_empty(self):
        """A name means the same thing everywhere, so shipping one is correct."""
        from codess.helpers import TRAVERSAL_PRUNE_DIRS

        assert "node_modules" in TRAVERSAL_PRUNE_DIRS
