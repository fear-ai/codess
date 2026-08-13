"""Tests for helpers module."""

import csv
from pathlib import Path

import pytest

from codess.helpers import (
    ephemeral_project_location_reason,
    is_excluded,
    is_under_pruned_directory,
    local_path_from_uri,
    parse_dir_list,
    path_to_slug,
    resolve_slug,
    should_prune_directory,
    slug_to_path,
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
        assert path_to_slug(Path()) == "."


class TestSlugToPath:
    def test_empty(self):
        assert slug_to_path("") == Path()

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
    def test_generated_and_cache_dirs(self, tmp_path, name):
        p = tmp_path / "project" / name / "nested"
        p.mkdir(parents=True)
        assert should_prune_directory(name)
        assert is_under_pruned_directory(p, tmp_path)
        assert is_excluded(p, tmp_path)

    def test_explicit_root_named_like_artifact(self, tmp_path):
        root = tmp_path / "build"
        root.mkdir()
        assert not is_under_pruned_directory(root, root)
        assert not is_excluded(root, root)



class TestWriteCsv:
    def test_headers_and_rows(self, tmp_path):
        out = tmp_path / "out.csv"
        write_csv(out, [["a", "1"], ["b", "2"]], headers=["x", "y"])
        content = out.read_text()
        assert content.startswith("x,y\n") or content.startswith("x,y\r\n")
        assert "a,1" in content and "b,2" in content

    def test_formula_injection(self, tmp_path):
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

    def test_hidden_relative_root(self, tmp_path, monkeypatch):
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


class TestSlugEncodingHasOneImplementation:
    """`project` re-exports `helpers`; it used to carry a weaker copy.

    `path_to_slug` was byte-identical in both, but `project.slug_to_path`
    lacked the filesystem fallback that resolves a hyphen inside a directory
    name. The two therefore disagreed on any such path -- the encoding is
    lossy, so decoding needs the filesystem to choose between readings
    (3.5.4).
    """

    def test_one_implementation(self):
        from codess import helpers, project

        assert project.slug_to_path is helpers.slug_to_path
        assert project.path_to_slug is helpers.path_to_slug

    def test_hyphenated_leaf(self):
        """The fallback rejoins the last two parts, and only those.

        A slug is lossy -- `spank-py` and `spank/py` encode identically -- so
        decoding consults the filesystem. The fallback tries one rejoining,
        of the final two segments, which covers a hyphenated project
        directory under an unhyphenated parent. That is the observed real
        case: `~/Work/Spank/spank-py`.
        """
        import tempfile

        from codess.helpers import path_to_slug, slug_to_path

        parent = Path(tempfile.mkdtemp()).resolve()
        if "-" in str(parent):
            pytest.skip("temporary root itself contains a hyphen")
        target = parent / "spank-py"
        target.mkdir()
        assert slug_to_path(path_to_slug(target)) == target

    def test_hyphens_nested(self, tmp_path):
        """The former limit, since removed.

        The old fallback rejoined only the final two segments, so a path
        whose parents also contained hyphens decoded wrongly. Four of the
        eighteen real slugs on the development machine were in that class.
        Descending the filesystem token by token resolves all of them,
        because each step asks which directory actually exists rather than
        guessing where the separators fall.
        """
        from codess.helpers import path_to_slug, slug_to_path

        target = tmp_path / "pytest-of-walter" / "a-b" / "c-d"
        target.mkdir(parents=True)
        assert slug_to_path(path_to_slug(target)) == target

    def test_encoding_is_unchanged(self, tmp_path):
        from codess.helpers import path_to_slug

        assert path_to_slug(Path("/a/b/c")) == "-a-b-c"
        assert path_to_slug(Path("a/b")) == "a-b"

    def test_absent_path(self):
        """With no directory to consult, the lossy split is all there is."""
        from codess.helpers import slug_to_path

        assert slug_to_path("-nonexistent-a-b") == Path("/nonexistent/a/b")


class TestLocalPathFromUri:
    """Vendor workspace records carry a URI; only a local file one is a path.

    Cursor and Claude both record a workspace `folder` that may be a plain
    path, a `file://` URI, or a remote scheme for a container, SSH, or WSL
    workspace. Treating a remote URI as a local path attributes another
    machine's Sessions to a local Project, so the rejection is the point of
    the function rather than a detail of it.
    """

    def test_plain_path(self, tmp_path):
        assert local_path_from_uri(str(tmp_path)) == tmp_path.resolve()

    def test_file_uri(self, tmp_path):
        assert local_path_from_uri(f"file://{tmp_path}") == tmp_path.resolve()

    def test_percent_escape(self):
        assert local_path_from_uri("file:///a/b%20c") == Path("/a/b c")

    def test_file_uri_localhost(self):
        assert local_path_from_uri("file://localhost/a/b") == Path("/a/b")

    @pytest.mark.parametrize(
        "uri",
        [
            "vscode-remote://ssh-remote%2Bhost/a/b",
            "ssh://host/a/b",
            "file://otherhost/a/b",
            "http://example.invalid/a/b",
        ],
    )
    def test_remote_scheme(self, uri):
        assert local_path_from_uri(uri) is None

    def test_relative_path(self):
        assert local_path_from_uri("a/b") is None

    @pytest.mark.parametrize("value", [None, "", "   ", {}])
    def test_absent_value(self, value):
        assert local_path_from_uri(value) is None

    def test_dict_path_key(self, tmp_path):
        assert local_path_from_uri({"path": str(tmp_path)}) == tmp_path.resolve()


class TestUserRootStringDisallowed:
    """A user-supplied root is a traversal surface; `..` is rejected outright.

    The asymmetry is deliberate. An absolute root may contain a dot segment,
    because `~/.config` and similar are ordinary. A relative root may not,
    because there is no established base to resolve it against.
    """

    @pytest.mark.parametrize(
        "raw",
        ["..", "../x", "a/../b", "/a/../b", "a/..", "/../etc"],
    )
    def test_parent_segment(self, raw):
        assert user_root_string_disallowed(raw)

    @pytest.mark.parametrize("raw", ["", "   "])
    def test_empty_root(self, raw):
        assert user_root_string_disallowed(raw)

    @pytest.mark.parametrize("raw", ["/a/b", "/Users/x/Work", "/a/.config/b"])
    def test_absolute_dot_segment(self, raw):
        assert not user_root_string_disallowed(raw)

    @pytest.mark.parametrize("raw", [".hidden/x", "a/.git/b", ".ssh"])
    def test_relative_hidden_segment(self, raw):
        assert user_root_string_disallowed(raw)

    @pytest.mark.parametrize("raw", ["a/b", "./a/b", "."])
    def test_relative_ordinary(self, raw):
        assert not user_root_string_disallowed(raw)


class TestResolveSlug:
    """Slug decoding consults the filesystem instead of guessing separators.

    Claude's encoding maps both `/` and `-` to `-`, so the string alone is
    ambiguous and no amount of parsing recovers the original. `resolve_slug`
    therefore descends real directories, and says None when none matches --
    which is the answer for a Project that was deleted or moved, and the
    thing the previous decoder could not express.
    """

    def test_hyphenated_vs_split(self, tmp_path):
        """`spank-py` is preferred over `spank/py` when both could exist."""
        both = tmp_path / "spank-py"
        both.mkdir()
        (tmp_path / "spank" / "py").mkdir(parents=True)
        assert resolve_slug(path_to_slug(both), root=tmp_path.resolve()) == both

    def test_split_only(self, tmp_path):
        target = tmp_path / "spank" / "py"
        target.mkdir(parents=True)
        slug = path_to_slug(tmp_path.resolve() / "spank-py")
        assert resolve_slug(slug, root=tmp_path.resolve()) == target

    def test_hyphens_nested(self, tmp_path):
        target = tmp_path / "a-b" / "c-d" / "e-f"
        target.mkdir(parents=True)
        assert resolve_slug(path_to_slug(target), root=tmp_path.resolve()) == target

    def test_absent(self, tmp_path):
        """The four real slugs whose directories are gone land here.

        Returning None lets a caller report the Project as absent. The old
        decoder returned a path that did not exist and looked like any other.
        """
        slug = path_to_slug(tmp_path.resolve() / "gone-away")
        assert resolve_slug(slug, root=tmp_path.resolve()) is None

    def test_parent_token(self, tmp_path):
        """`..` cannot redirect the walk; it is a name or it is nothing.

        A slug segment reading `..` is matched against real directory names,
        so `A-..-B` can only resolve if a directory is literally called `..`
        -- which no filesystem permits. The walk descends and never ascends.
        """
        (tmp_path / "A").mkdir()
        (tmp_path / "B").mkdir()
        slug = path_to_slug(tmp_path.resolve() / "A" / ".." / "B")
        assert resolve_slug(slug, root=tmp_path.resolve()) is None

    def test_leading_dotdot(self, tmp_path):
        """A directory genuinely named `..-evil` resolves to itself.

        The name is legal and the old decoder read it as `../evil`, escaping
        the parent. Matching literal names keeps it where it is.
        """
        target = tmp_path / "..-evil"
        target.mkdir()
        resolved = resolve_slug(path_to_slug(target), root=tmp_path.resolve())
        assert resolved == target
        assert resolved.is_relative_to(tmp_path.resolve())

    def test_relative(self):
        assert resolve_slug("a-b") is None

    def test_empty(self):
        assert resolve_slug("") is None

    def test_fallback(self, tmp_path):
        """`slug_to_path` still returns a value; it is a guess, not evidence.

        The fallback splits on every hyphen, so it recovers neither the
        absent leaf nor any hyphenated parent. That is the point of keeping
        `resolve_slug` separate: a caller acting on the path can tell the two
        apart, where a single function returning a Path cannot.
        """
        slug = path_to_slug(tmp_path.resolve() / "gone-away")
        assert resolve_slug(slug, root=tmp_path.resolve()) is None
        guess = slug_to_path(slug)
        assert guess.parts[-2:] == ("gone", "away")
        assert not guess.exists()


class TestRejectionReasons:
    """The `_reason` pair returns text explaining a refusal, or None.

    The suffix states the return: a caller that refuses has a sentence to
    report, and a caller that accepts gets None. Asserting only truthiness
    would pass on a wrong or unhelpful reason, so these check that the
    message names the path it rejected -- which is what makes the refusal
    actionable at the point it surfaces.
    """

    @pytest.mark.parametrize("path", [Path("/"), Path("/var")])
    def test_broad(self, path):
        reason = unsafe_traversal_root_reason(path)
        assert reason is not None
        assert str(path) in reason

    @pytest.mark.parametrize("path", ["~", "/var/www/project"])
    def test_scoped(self, path):
        assert unsafe_traversal_root_reason(Path(path).expanduser()) is None

    @pytest.mark.parametrize(
        "path",
        ["/private/var/folders/example/T/tmp/project", "/tmp/project"],
    )
    def test_ephemeral(self, path):
        reason = ephemeral_project_location_reason(Path(path))
        assert reason is not None
        assert "ephemeral" in reason

    def test_durable(self, tmp_path):
        assert ephemeral_project_location_reason(Path.home() / "Work" / "p") is None
