"""Tests for walk module: traversal, exclusion, termination."""

from pathlib import Path

import pytest

from codess.walk import walk_dirs


class TestWalkDirs:
    def test_roots_only_norec(self, tmp_path):
        """--norec: yield roots only, no recursion."""
        d1 = tmp_path / "a"
        d2 = tmp_path / "b"
        d1.mkdir()
        (d1 / "sub").mkdir()
        d2.mkdir()
        out = list(walk_dirs([d1, d2], recurse=False))
        assert len(out) == 2
        assert d1.resolve() in out and d2.resolve() in out

    def test_recurse_excludes_git(self, tmp_path):
        """Recurse skips .git and hidden dirs."""
        (tmp_path / "proj").mkdir()
        (tmp_path / "proj" / ".git").mkdir()
        (tmp_path / "proj" / "src").mkdir()
        out = list(walk_dirs([tmp_path / "proj"]))
        names = [p.name for p in out]
        assert ".git" not in names
        assert "src" in names

    def test_recurse_excludes_node_modules(self, tmp_path):
        """Recurse skips node_modules."""
        (tmp_path / "proj").mkdir()
        (tmp_path / "proj" / "node_modules").mkdir()
        (tmp_path / "proj" / "src").mkdir()
        out = list(walk_dirs([tmp_path / "proj"]))
        names = [p.name for p in out]
        assert "node_modules" not in names

    def test_prune_dirs_terminates(self, tmp_path):
        """prune_dirs: do not recurse into pruned dir."""
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "b").mkdir()
        (tmp_path / "a" / "b" / "c").mkdir()
        prune = {tmp_path / "a" / "b"}
        out = list(walk_dirs([tmp_path / "a"], prune_dirs=prune))
        assert (tmp_path / "a" / "b" / "c").resolve() not in out

    def test_max_depth_terminates(self, tmp_path):
        """max_depth: stop at depth."""
        p = tmp_path
        for i in range(20):
            p = p / f"d{i}"
            p.mkdir()
        out = list(walk_dirs([tmp_path], max_depth=3))
        depths = [len(p.relative_to(tmp_path).parts) for p in out]
        assert max(depths) <= 3
