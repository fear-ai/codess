"""Project/slug corner cases and edge cases."""

from pathlib import Path

import pytest

from codess.project import (
    find_slug_for_project,
    get_cc_session_dir,
    get_codex_session_files,
    get_cursor_global_db,
    get_cursor_workspace_dbs,
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
        monkeypatch.setattr("codess.project.CC_PROJECTS", cc_dir)
        import codess.project as proj_mod
        found = proj_mod.find_slug_for_project(proj)
        assert found == slug


class TestGetCcSessionDir:
    """get_cc_session_dir returns None when not found."""

    def test_none_when_no_slug(self, tmp_path, monkeypatch):
        monkeypatch.setattr("codess.project.CC_PROJECTS", tmp_path)
        import codess.project as proj_mod
        proj = tmp_path / "orphan"
        proj.mkdir()
        assert proj_mod.get_cc_session_dir(proj) is None


class TestGetCodexSessionFiles:
    """get_codex_session_files filters by cwd."""

    def test_empty_when_no_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("codess.project.CODEX_SESSIONS", tmp_path / "nonexistent")
        proj = tmp_path / "proj"
        proj.mkdir()
        assert get_codex_session_files(proj) == []

    def test_matches_cwd(self, tmp_path, monkeypatch):
        monkeypatch.setattr("codess.project.CODEX_SESSIONS", tmp_path / "codex")
        (tmp_path / "codex").mkdir()
        proj = tmp_path / "myproj"
        proj.mkdir()
        sess_dir = tmp_path / "codex" / "2024" / "01"
        sess_dir.mkdir(parents=True)
        f = sess_dir / "rollout-abc.jsonl"
        f.write_text(f'{{"type":"session_meta","payload":{{"cwd":"{proj}"}}}}\n')
        files = get_codex_session_files(proj)
        assert len(files) == 1
        assert files[0].name == "rollout-abc.jsonl"


class TestGetCursorPaths:
    """get_cursor_workspace_dbs and get_cursor_global_db."""

    def test_global_db_none_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("codess.project.CURSOR_DATA", tmp_path / "cursor")
        assert get_cursor_global_db() is None

    def test_global_db_returns_path_when_exists(self, tmp_path, monkeypatch):
        base = tmp_path / "cursor" / "User"
        base.mkdir(parents=True)
        global_dir = base / "globalStorage"
        global_dir.mkdir()
        db = global_dir / "state.vscdb"
        db.touch()
        monkeypatch.setattr("codess.project.CURSOR_DATA", base)
        assert get_cursor_global_db() == db

    def test_workspace_dbs_empty_when_no_match(self, tmp_path, monkeypatch):
        monkeypatch.setattr("codess.project.CURSOR_DATA", tmp_path / "cursor")
        (tmp_path / "cursor" / "workspaceStorage").mkdir(parents=True)
        proj = tmp_path / "other"
        proj.mkdir()
        assert get_cursor_workspace_dbs(proj) == []

    def test_workspace_dbs_matches_folder(self, tmp_path, monkeypatch):
        proj = tmp_path / "myproj"
        proj.mkdir()
        base = tmp_path / "cursor" / "User"
        ws = base / "workspaceStorage" / "abc123"
        ws.mkdir(parents=True)
        (ws / "workspace.json").write_text(
            f'{{"folder":{{"path":"{proj}"}}}}'
        )
        (ws / "state.vscdb").touch()
        monkeypatch.setattr("codess.project.CURSOR_DATA", base)
        dbs = get_cursor_workspace_dbs(proj)
        assert len(dbs) == 1
        assert dbs[0].name == "state.vscdb"
