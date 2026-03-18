"""Project/slug corner cases and edge cases."""

from pathlib import Path

import pytest

from ingest.project import (
    find_slug_for_project,
    get_cc_session_dir,
    path_to_slug,
    slug_to_path,
)


class TestPathToSlug:
    """path_to_slug edge cases."""

    def test_absolute(self):
        assert path_to_slug(Path("/a/b/c")) == "-a-b-c"

    def test_root(self):
        assert path_to_slug(Path("/")) == ""

    def test_relative(self):
        assert path_to_slug(Path("a/b/c")) == "a-b-c"
        assert path_to_slug(Path(".")) == "."

    def test_empty_relative(self):
        # Path("") normalizes to Path(".")
        assert path_to_slug(Path("")) == "."

    def test_single_segment(self):
        assert path_to_slug(Path("/home")) == "-home"


class TestSlugToPath:
    """slug_to_path edge cases."""

    def test_empty(self):
        assert slug_to_path("") == Path(".")

    def test_leading_dash_absolute(self):
        assert slug_to_path("-a-b-c") == Path("/a/b/c")

    def test_no_leading_dash_relative(self):
        assert slug_to_path("a-b-c") == Path("a/b/c")

    def test_roundtrip_absolute(self):
        p = Path("/Users/walter/Work/proj")
        assert slug_to_path(path_to_slug(p)) == p

    def test_roundtrip_relative(self):
        p = Path("src/utils")
        assert slug_to_path(path_to_slug(p)) == p


class TestFindSlugForProject:
    """find_slug_for_project with temp dirs."""

    def test_not_found(self, tmp_path):
        proj = tmp_path / "nonexistent_proj"
        proj.mkdir()
        assert find_slug_for_project(proj) is None

    def test_found(self, tmp_path, monkeypatch):
        cc_dir = tmp_path / "cc"
        cc_dir.mkdir()
        proj = tmp_path / "myproj"
        proj.mkdir()
        slug = path_to_slug(proj.resolve())
        (cc_dir / slug).mkdir(parents=True)
        monkeypatch.setattr("ingest.project.CC_PROJECTS_DIR", cc_dir)
        import ingest.project as proj_mod
        found = proj_mod.find_slug_for_project(proj)
        assert found == slug


class TestGetCcSessionDir:
    """get_cc_session_dir returns None when not found."""

    def test_none_when_no_slug(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ingest.project.CC_PROJECTS_DIR", tmp_path)
        import ingest.project as proj_mod
        proj = tmp_path / "orphan"
        proj.mkdir()
        assert proj_mod.get_cc_session_dir(proj) is None
