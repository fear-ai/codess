"""Tests for helpers module."""

import csv
from pathlib import Path

import pytest

from codess.helpers import (
    is_excluded,
    is_under_pruned_directory,
    parse_dir_list,
    path_to_slug,
    slug_to_path,
    should_prune_directory,
    unsafe_traversal_root_reason,
    user_root_string_disallowed,
    validate_dirs_file,
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

    @pytest.mark.parametrize(
        "name",
        [
            "build", "Debug", ".git", "node_modules", ".cache", ".ccache",
            ".pyenv", ".venv", "target", "cmake-build-debug",
        ],
    )
    def test_generated_and_cache_descendants_are_excluded(self, tmp_path, name):
        p = tmp_path / "project" / name / "nested"
        p.mkdir(parents=True)
        assert should_prune_directory(name)
        assert is_under_pruned_directory(p, tmp_path)
        assert is_excluded(p, tmp_path)

    def test_explicit_root_named_like_artifact_remains_eligible(self, tmp_path):
        root = tmp_path / "build"
        root.mkdir()
        assert not is_under_pruned_directory(root, root)
        assert not is_excluded(root, root)

    def test_broad_system_roots_are_unsafe_but_scoped_descendants_are_allowed(self):
        assert unsafe_traversal_root_reason(Path("/"))
        assert unsafe_traversal_root_reason(Path("/var"))
        assert unsafe_traversal_root_reason(Path.home()) is None
        assert unsafe_traversal_root_reason(Path("/var/www/project")) is None


class TestWriteCsv:
    def test_writes_headers_and_rows(self, tmp_path):
        out = tmp_path / "out.csv"
        write_csv(out, [["a", "1"], ["b", "2"]], headers=["x", "y"])
        content = out.read_text()
        assert content.startswith("x,y\n") or content.startswith("x,y\r\n")
        assert "a,1" in content and "b,2" in content

    def test_protects_string_cells_from_spreadsheet_formulas(self, tmp_path):
        out = tmp_path / "out.csv"
        write_csv(out, [["=cmd", -1]], headers=["name", "count"])
        with out.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.reader(stream))
        assert rows[1] == ["\t=cmd", "-1"]


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

    def test_candidate_csv(self, tmp_path):
        d1 = tmp_path / "d1"
        d1.mkdir()
        f = tmp_path / "candidates.csv"
        f.write_text(
            "title,directory_path,repo_url,notes\n"
            f'one,{d1},https://example.invalid/one,"a, b"\n'
        )
        assert parse_dir_list(f, []) == [d1.resolve()]
        assert validate_dirs_file(f) is None

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

    def test_validate_dirs_file_missing(self, tmp_path):
        missing = tmp_path / "nope.txt"
        assert validate_dirs_file(missing) is not None

    def test_validate_dirs_file_empty(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("# only\n\n")
        assert validate_dirs_file(f) is not None

    def test_user_root_hidden_relative_skipped(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".hidden").mkdir()
        result = parse_dir_list(None, [".hidden"])
        assert result == []
        d = tmp_path / "ok"
        d.mkdir()
        result2 = parse_dir_list(None, ["ok"])
        assert result2 == [d.resolve()]

    def test_skip_empty_and_comments(self, tmp_path):
        d1 = tmp_path / "d1"
        d1.mkdir()
        f = tmp_path / "dirs.txt"
        f.write_text("\n# skip\n  \n" + str(d1) + "\n")
        result = parse_dir_list(f, [])
        assert result == [d1.resolve()]
