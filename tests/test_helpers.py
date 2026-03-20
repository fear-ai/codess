"""Tests for helpers module."""

from pathlib import Path

import pytest

from codess.helpers import (
    is_excluded,
    parse_dir_list,
    path_to_slug,
    should_skip_recurse,
    slug_to_path,
    write_csv,
)


class TestPathToSlug:
    def test_absolute(self):
        assert path_to_slug(Path("/a/b/c")) == "-a-b-c"

    def test_relative(self):
        assert path_to_slug(Path("a/b/c")) == "a-b-c"

    def test_empty(self):
        assert path_to_slug(Path(".")) == "."


class TestSlugToPath:
    def test_empty(self):
        assert slug_to_path("") == Path(".")

    def test_leading_dash(self):
        assert slug_to_path("-a-b-c") == Path("/a/b/c")

    def test_relative(self):
        assert slug_to_path("a-b-c") == Path("a/b/c")


class TestIsExcluded:
    def test_old_dir(self, tmp_path):
        p = tmp_path / "OLD" / "foo"
        p.mkdir(parents=True)
        assert is_excluded(p, tmp_path)

    def test_save_dir(self, tmp_path):
        p = tmp_path / "Save" / "bar"
        p.mkdir(parents=True)
        assert is_excluded(p, tmp_path)

    def test_not_excluded(self, tmp_path):
        p = tmp_path / "proj" / "src"
        p.mkdir(parents=True)
        assert not is_excluded(p, tmp_path)


class TestShouldSkipRecurse:
    def test_git(self):
        assert should_skip_recurse(".git")

    def test_node_modules(self):
        assert should_skip_recurse("node_modules")

    def test_case_insensitive(self):
        assert should_skip_recurse("NODE_MODULES")

    def test_not_skipped(self):
        assert not should_skip_recurse("src")


class TestWriteCsv:
    def test_writes_headers_and_rows(self, tmp_path):
        out = tmp_path / "out.csv"
        write_csv(out, [["a", "1"], ["b", "2"]], headers=["x", "y"])
        content = out.read_text()
        assert content.startswith("x,y\n") or content.startswith("x,y\r\n")
        assert "a,1" in content and "b,2" in content


class TestParseDirList:
    def test_empty(self, tmp_path):
        assert parse_dir_list(None, []) == []

    def test_dir_args(self, tmp_path):
        d1 = tmp_path / "d1"
        d1.mkdir()
        result = parse_dir_list(None, [str(d1)])
        assert result == [d1.resolve()]

    def test_dirs_file(self, tmp_path):
        d1 = tmp_path / "d1"
        d1.mkdir()
        f = tmp_path / "dirs.txt"
        f.write_text(f"{d1}\n")
        result = parse_dir_list(f, [])
        assert result == [d1.resolve()]

    def test_mixed_dir_and_dirs_dedup(self, tmp_path):
        """Mixed --dir and --dirs: dedupe, dirs file first then dir args."""
        d1 = tmp_path / "d1"
        d2 = tmp_path / "d2"
        d1.mkdir()
        d2.mkdir()
        f = tmp_path / "dirs.txt"
        f.write_text(f"{d1}\n# comment\n{d2}\n")
        result = parse_dir_list(f, [str(d1), str(d2)])
        assert len(result) == 2
        assert d1.resolve() in result and d2.resolve() in result

    def test_skip_dotdot(self, tmp_path):
        """Paths with .. are skipped."""
        result = parse_dir_list(None, ["/a/b/../c"])
        assert result == []

    def test_skip_empty_and_comments(self, tmp_path):
        d1 = tmp_path / "d1"
        d1.mkdir()
        f = tmp_path / "dirs.txt"
        f.write_text("\n# skip\n  \n" + str(d1) + "\n")
        result = parse_dir_list(f, [])
        assert result == [d1.resolve()]
