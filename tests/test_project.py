"""Project/slug corner cases and edge cases."""

import json
from pathlib import Path
from types import SimpleNamespace

from codess.cursor_source import (
    get_global_db as get_cursor_global_db,
    get_workspace_dbs as get_cursor_workspace_dbs,
    get_workspace_ids as get_cursor_workspace_ids,
)
from codess.project import (
    find_slug_for_project,
    path_to_slug,
    resolve_cli_roots,
    slug_to_path,
    RootsWhenEmpty,
)


class TestResolveCliRoots:
    def test_explicit_missing_root_is_error(self, tmp_path):
        missing = tmp_path / "missing"
        args = SimpleNamespace(dirs=None, dir_list=[str(missing)])
        roots, err = resolve_cli_roots(args, when_empty=RootsWhenEmpty.CWD)
        assert roots is None
        assert err and "does not exist" in err

    def test_explicit_file_root_is_error(self, tmp_path):
        file_path = tmp_path / "not-a-directory"
        file_path.write_text("x")
        args = SimpleNamespace(dirs=None, dir_list=[str(file_path)])
        roots, err = resolve_cli_roots(args, when_empty=RootsWhenEmpty.CWD)
        assert roots is None
        assert err and "not a directory" in err

    def test_all_disallowed_roots_do_not_fall_back_to_cwd(self):
        args = SimpleNamespace(dirs=None, dir_list=["../outside"])
        roots, err = resolve_cli_roots(args, when_empty=RootsWhenEmpty.CWD)
        assert roots is None
        assert err and "no valid directory roots" in err

    def test_no_explicit_roots_uses_existing_cwd(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        args = SimpleNamespace(dirs=None, dir_list=None)
        roots, err = resolve_cli_roots(args, when_empty=RootsWhenEmpty.CWD)
        assert err is None
        assert roots == [tmp_path]

    def test_symlink_root_resolves_to_target(self, tmp_path):
        target = tmp_path / "target"
        target.mkdir()
        link = tmp_path / "link"
        link.symlink_to(target, target_is_directory=True)
        args = SimpleNamespace(dirs=None, dir_list=[str(link)])
        roots, err = resolve_cli_roots(args, when_empty=RootsWhenEmpty.CWD)
        assert err is None
        assert roots == [target.resolve()]


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

    def test_approved_relocation_link_finds_historical_claude_slug(self, tmp_path, monkeypatch):
        cc_dir = tmp_path / "cc"
        cc_dir.mkdir()
        old = tmp_path / "old" / "project"
        new = tmp_path / "new" / "project"
        new.mkdir(parents=True)
        old_slug = path_to_slug(old.resolve())
        (cc_dir / old_slug).mkdir(parents=True)
        sidecar = new / ".codess"
        sidecar.mkdir()
        (sidecar / "source-links.json").write_text(json.dumps({
            "format": "codess.source-links/1",
            "links": [{
                "source_system_id": "anthropic.claude-code",
                "source_project_path": str(old.resolve()),
                "target_project_path": str(new.resolve()),
                "relation_kind": "project_relocation",
                "selection_state": "approved",
            }],
        }))
        monkeypatch.setattr("codess.project.CC_PROJECTS", cc_dir)
        assert find_slug_for_project(new) == old_slug


class TestGetCcSessionDir:
    """get_cc_session_dir returns None when not found."""

    def test_none_when_no_slug(self, tmp_path, monkeypatch):
        monkeypatch.setattr("codess.project.CC_PROJECTS", tmp_path)
        import codess.project as proj_mod
        proj = tmp_path / "orphan"
        proj.mkdir()
        assert proj_mod.get_cc_session_dir(proj) is None


class TestGetCursorPaths:
    """get_cursor_workspace_dbs and get_cursor_global_db."""

    def test_global_db_none_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("codess.cursor_source.CURSOR_DATA", tmp_path / "cursor")
        assert get_cursor_global_db() is None

    def test_global_db_returns_path_when_exists(self, tmp_path, monkeypatch):
        base = tmp_path / "cursor" / "User"
        base.mkdir(parents=True)
        global_dir = base / "globalStorage"
        global_dir.mkdir()
        db = global_dir / "state.vscdb"
        db.touch()
        monkeypatch.setattr("codess.cursor_source.CURSOR_DATA", base)
        assert get_cursor_global_db() == db

    def test_approved_project_source_link_adds_renamed_cursor_workspace(
        self, tmp_path, monkeypatch
    ):
        base = tmp_path / "cursor" / "User"
        (base / "workspaceStorage").mkdir(parents=True)
        monkeypatch.setattr("codess.cursor_source.CURSOR_DATA", base)
        project = tmp_path / "renamed-project"
        links = project / ".codess" / "source-links.json"
        links.parent.mkdir(parents=True)
        links.write_text(json.dumps({
            "format": "codess.source-links/1",
            "links": [{
                "source_system_id": "cursor.composer",
                "source_identity": {"workspace_id": "workspace-old"},
                "relation_kind": "renamed_from",
                "source_project_path": str(tmp_path / "old-name"),
                "selection_state": "approved",
            }],
        }))
        assert get_cursor_workspace_ids(project) == ["workspace-old"]

    def test_unapproved_or_wrong_vendor_source_links_are_not_used(
        self, tmp_path, monkeypatch
    ):
        base = tmp_path / "cursor" / "User"
        (base / "workspaceStorage").mkdir(parents=True)
        monkeypatch.setattr("codess.cursor_source.CURSOR_DATA", base)
        project = tmp_path / "project"
        links = project / ".codess" / "source-links.json"
        links.parent.mkdir(parents=True)
        links.write_text(json.dumps({
            "format": "codess.source-links/1",
            "links": [
                {"source_system_id": "cursor.composer", "source_identity": {"workspace_id": "pending"}, "selection_state": "needs_review"},
                {"source_system_id": "openai.codex", "source_identity": {"workspace_id": "wrong"}, "selection_state": "approved"},
            ],
        }))
        assert get_cursor_workspace_ids(project) == []

    def test_workspace_dbs_empty_when_no_match(self, tmp_path, monkeypatch):
        monkeypatch.setattr("codess.cursor_source.CURSOR_DATA", tmp_path / "cursor")
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
        monkeypatch.setattr("codess.cursor_source.CURSOR_DATA", base)
        dbs = get_cursor_workspace_dbs(proj)
        assert len(dbs) == 1
        assert dbs[0].name == "state.vscdb"
        assert get_cursor_workspace_ids(proj) == ["abc123"]

    def test_workspace_ids_reject_remote_editor_uri(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        project.mkdir()
        base = tmp_path / "cursor" / "User"
        ws = base / "workspaceStorage" / "remote"
        ws.mkdir(parents=True)
        (ws / "workspace.json").write_text(json.dumps({
            "folder": "vscode-remote://ssh-remote+host/home/user/project"
        }))
        (ws / "state.vscdb").touch()
        monkeypatch.setattr("codess.cursor_source.CURSOR_DATA", base)
        assert get_cursor_workspace_ids(project) == []
