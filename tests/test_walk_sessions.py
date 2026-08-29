"""Path canonicalization: which directory is the Project.

These rules were nested inside `walk_sessions` and reachable only by running
vendor discovery over a populated filesystem, so the logic most likely to be
wrong was the logic hardest to test. Lifting them made these cases
expressible; every one below is new coverage rather than relocated coverage.

Paths are synthetic. A repository is a directory holding `.git`, which is what
`project_boundary` looks for, so a marker directory is enough.
"""

from __future__ import annotations

from pathlib import Path

from codess.walk_sessions import (
    canonicalize,
    in_work_root,
    project_boundary,
)


def _repo(path: Path) -> Path:
    """A directory that looks like a repository to boundary resolution."""
    (path / ".git").mkdir(parents=True)
    return path


class TestInWorkRoot:
    def test_a_path_inside_is_accepted(self, tmp_path):
        inside = tmp_path / "project"
        inside.mkdir()
        assert in_work_root(str(inside), tmp_path.resolve())

    def test_a_path_outside_is_refused(self, tmp_path):
        outside = tmp_path.parent / "elsewhere"
        assert not in_work_root(str(outside), (tmp_path / "root").resolve())

    def test_a_symlink_escaping_the_root_is_refused(self, tmp_path):
        """Resolution happens before comparison, which is what detects it.

        Without resolving, a link inside the root would attribute another
        tree's Sessions to this one.
        """
        root = tmp_path / "root"
        outside = tmp_path / "outside"
        root.mkdir()
        outside.mkdir()
        (root / "link").symlink_to(outside)
        assert not in_work_root(str(root / "link"), root.resolve())

    def test_the_root_itself_is_inside(self, tmp_path):
        assert in_work_root(str(tmp_path), tmp_path.resolve())


class TestProjectBoundary:
    def test_a_repository_is_its_own_boundary(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        assert project_boundary(repo, tmp_path, {repo}) == repo

    def test_a_nested_path_resolves_to_its_repository(self, tmp_path):
        """A Session recorded in a subdirectory belongs to the repository."""
        repo = _repo(tmp_path / "repo")
        nested = repo / "src" / "deep"
        nested.mkdir(parents=True)
        assert project_boundary(nested, tmp_path, {repo}) == repo

    def test_the_innermost_repository_wins(self, tmp_path):
        """A repository inside a repository is its own Project."""
        outer = _repo(tmp_path / "outer")
        inner = _repo(outer / "inner")
        assert project_boundary(inner, tmp_path, {outer, inner}) == inner

    def test_the_walk_stops_at_the_work_root(self, tmp_path):
        """A repository above the scanned tree must not capture paths in it."""
        _repo(tmp_path)
        root = tmp_path / "root"
        plain = root / "plain"
        plain.mkdir(parents=True)
        assert project_boundary(plain, root, {plain}) == plain

    def test_a_live_ancestor_is_used_when_no_git_is_found(self, tmp_path):
        """The fallback: the deepest reported path containing this one."""
        root = tmp_path
        repo = _repo(root / "repo")
        orphan = root / "repo" / "sub"
        orphan.mkdir(parents=True)
        assert project_boundary(orphan, root, {repo, orphan}) == repo

    def test_an_unattributable_path_is_returned_unchanged(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert project_boundary(plain, tmp_path, {plain}) == plain


class TestAggregatorsRetired:
    """`AGGREGATORS` is gone, and `exclude_paths` answers what it asked.

    It named a container by structure -- "holds many repositories" -- while the
    operator's criterion is intent: a collection kept for reference rather than
    developed in, which may hold one repository or fifty. On that definition it
    and `EXCLUDE_REVIEW_DIRS` were one setting.
    """

    def test_the_setting_is_gone(self):
        import codess.config as config

        assert not hasattr(config, "AGGREGATORS")
        assert not hasattr(config, "DEFAULT_AGGREGATORS")

    def test_the_predicate_is_gone(self):
        import codess.walk_sessions as walk_sessions

        assert not hasattr(walk_sessions, "is_aggregator")

    def test_an_excluded_tree_is_dropped_at_any_depth(self, tmp_path, monkeypatch):
        """The structural limit went with the name.

        Only a direct child of the work root could be an aggregator, so a
        reference tree one level deeper could not be named at all. An absolute
        path carries no such limit.
        """
        import importlib

        import codess.helpers as helpers

        deep = tmp_path / "work" / "vendor" / "reference"
        monkeypatch.setenv("CODESS_EXCLUDE_PATHS", str(deep))
        importlib.reload(helpers)
        try:
            assert helpers.is_excluded(deep / "someclone", tmp_path / "work")
        finally:
            monkeypatch.delenv("CODESS_EXCLUDE_PATHS")
            importlib.reload(helpers)
            importlib.reload(importlib.import_module("codess.project"))


class TestCanonicalize:
    """Exclusion now comes from `exclude_paths` rather than a name list.

    The fixture that patched `AGGREGATORS` is gone with the setting; a test
    needing an excluded tree configures `CODESS_EXCLUDE_PATHS` and reloads,
    which is what an operator does.
    """

    def test_a_parent_is_dropped_when_a_child_is_present(self, tmp_path):
        parent = tmp_path / "parent"
        child = parent / "child"
        child.mkdir(parents=True)
        assert canonicalize({parent, child}, tmp_path) == {child}

    def test_unrelated_paths_are_both_kept(self, tmp_path):
        first = tmp_path / "one"
        second = tmp_path / "two"
        for path in (first, second):
            path.mkdir()
        assert canonicalize({first, second}, tmp_path) == {first, second}

    def test_an_excluded_tree_is_dropped(self, tmp_path, monkeypatch):
        """A tree the operator excluded is not a candidate Project.

        Configured by absolute path rather than by a name that had to be a
        direct child of the work root, which is what the retired setting
        required and could not express otherwise.
        """
        import importlib

        import codess.helpers as helpers
        import codess.walk_sessions as walk_sessions

        reference = tmp_path / "Clients"
        project = reference / "project"
        project.mkdir(parents=True)
        monkeypatch.setenv("CODESS_EXCLUDE_PATHS", str(reference))
        importlib.reload(helpers)
        importlib.reload(walk_sessions)
        try:
            assert walk_sessions.canonicalize(
                {reference, project}, tmp_path,
            ) == set()
        finally:
            monkeypatch.delenv("CODESS_EXCLUDE_PATHS")
            importlib.reload(helpers)
            importlib.reload(walk_sessions)
            # `project` re-exports `helpers`' slug functions, so a reload here
            # leaves it holding the previous objects and an identity assertion
            # elsewhere fails on a difference this test caused.
            importlib.reload(importlib.import_module("codess.project"))

    def test_a_sibling_prefix_is_not_treated_as_a_child(self, tmp_path):
        """`/w/app` must not swallow `/w/application`.

        The comparison appends a separator for this reason; a bare
        `startswith` would drop the second as nested inside the first.
        """
        short = tmp_path / "app"
        long = tmp_path / "application"
        for path in (short, long):
            path.mkdir()
        assert canonicalize({short, long}, tmp_path) == {short, long}

    def test_an_empty_set_is_empty(self, tmp_path):
        assert canonicalize(set(), tmp_path) == set()
