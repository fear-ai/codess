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

        A slug is lossy -- `name-suffix` and `name/suffix` encode identically -- so
        decoding consults the filesystem. The fallback tries one rejoining,
        of the final two segments, which covers a hyphenated project
        directory under an unhyphenated parent. That is the observed real
        case: `~/Work/Group/name-suffix`.
        """
        import tempfile

        from codess.helpers import path_to_slug, slug_to_path

        parent = Path(tempfile.mkdtemp()).resolve()
        if "-" in str(parent):
            pytest.skip("temporary root itself contains a hyphen")
        target = parent / "name-suffix"
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

        target = tmp_path / "pytest-of-user" / "a-b" / "c-d"
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
        """`name-suffix` is preferred over `name/suffix` when both could exist."""
        both = tmp_path / "name-suffix"
        both.mkdir()
        (tmp_path / "name" / "suffix").mkdir(parents=True)
        assert resolve_slug(path_to_slug(both), root=tmp_path.resolve()) == both

    def test_split_only(self, tmp_path):
        target = tmp_path / "name" / "suffix"
        target.mkdir(parents=True)
        slug = path_to_slug(tmp_path.resolve() / "name-suffix")
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


class TestTraversalPruning:
    """Directory names never traversed, and why the set is names not paths.

    `TRAVERSAL_PRUNE_DIRS` is portable: `obj` under a .NET solution and `obj`
    under a Makefile are both build output. This is the opposite of
    `EXCLUDE_REVIEW_DIRS`, which names *where* on one machine and therefore
    ships empty.
    """

    def _pruned(self, name):
        from codess.helpers import TRAVERSAL_PRUNE_DIRS

        folded = name.casefold()
        return folded in TRAVERSAL_PRUNE_DIRS or folded.startswith("cmake-build-")

    @pytest.mark.parametrize("name", ["tmp", "TMP", "Temp", "temp"])
    def test_scratch_directories_are_pruned_case_folded(self, name):
        """A directory named for temporary content holds work not meant to be kept.

        Matching is case-folded, so the lowercase entry covers the `TMP` and
        `Temp` spellings that Windows and macOS produce.
        """
        assert self._pruned(name)

    @pytest.mark.parametrize("name", ["obj", "bin", "x64", "x86", "packages", ".vs"])
    def test_windows_build_output_is_pruned(self, name):
        """`obj`/`bin` are the .NET convention and `packages` the NuGet one.

        Codess runs on whichever platform the operator uses, so a prune set
        covering only POSIX build names would traverse a Visual Studio tree.
        """
        assert self._pruned(name)

    @pytest.mark.parametrize("name", ["build", "dist", "target", "out", "node_modules"])
    def test_common_build_and_dependency_output_is_pruned(self, name):
        assert self._pruned(name)

    @pytest.mark.parametrize("name", ["src", "lib", "docs", "app", "tests"])
    def test_ordinary_source_directories_are_not_pruned(self, name):
        """The set must not swallow the directories a Project is made of."""
        assert not self._pruned(name)

    def test_a_generated_prefix_is_pruned(self):
        assert self._pruned("cmake-build-debug")
        assert not self._pruned("cmake-configuration")


class TestSymlinkContainment:
    """A link must not carry discovery outside the root it was given."""

    def test_a_symlink_escaping_the_root_resolves_outside_it(self, tmp_path):
        """`resolve()` before comparing is what detects the escape.

        `walk_sessions.in_work_root` compares resolved paths, so a directory
        linked from inside the root to a target outside it is refused rather
        than followed -- otherwise a link would attribute another tree's
        Sessions to this one.
        """
        root = tmp_path / "root"
        outside = tmp_path / "outside"
        (root / "inside").mkdir(parents=True)
        outside.mkdir()
        (root / "escape").symlink_to(outside)

        assert (root / "inside").resolve().is_relative_to(root.resolve())
        assert not (root / "escape").resolve().is_relative_to(root.resolve())

    def test_a_self_referential_link_resolves_rather_than_looping(self, tmp_path):
        """A link to its own parent terminates instead of recursing."""
        root = tmp_path / "root"
        root.mkdir()
        (root / "loop").symlink_to(root)
        assert (root / "loop").resolve() == root.resolve()


class TestPruneSetBoundaries:
    """Names deliberately absent from the prune set, and why.

    Each was proposed and rejected on evidence: pruning it would hide a
    Project rather than noise. Pinned because the reasoning is not visible
    from the name alone, and a later edit adding one would be silent -- a
    Project simply stops being discovered.
    """

    def _pruned(self, name):
        from codess.helpers import TRAVERSAL_PRUNE_DIRS

        folded = name.casefold()
        return folded in TRAVERSAL_PRUNE_DIRS or folded.startswith("cmake-build-")

    @pytest.mark.parametrize("name", ["lib", "etc", "conf", "data", "web"])
    def test_source_directories_stay_traversed(self, name):
        """Each is a source directory in a common project layout.

        `lib` holds a library's own source in C, Ruby, and Node projects;
        `etc` and `conf` hold checked-in configuration; `data` holds fixtures
        and migrations; `web` is the front-end half of a full-stack tree.
        """
        assert not self._pruned(name)

    @pytest.mark.parametrize("name", ["private", "secrets", "credentials"])
    def test_access_intent_does_not_prune(self, name):
        """Pruning is not a security control.

        It stops traversal, which changes what is discovered rather than what
        is protected: a Session that already read a credential records it
        whether or not Codess later walks the directory. Content exclusion is
        the content policy's subject, and a name-based skip that looked like
        protection would be worse than none.
        """
        assert not self._pruned(name)

    def test_a_platform_source_directory_stays_traversed(self):
        """`windows` names a port, not build output, in cross-platform trees."""
        assert not self._pruned("windows")

    @pytest.mark.parametrize("name", [
        "bin", "obj", "debug", "release", "out", "output", "dist",
        "logs", "downloads", "uploads", "cache", "web_modules",
        "bower_components", "jspm_packages", "vendor", "venv", "env",
    ])
    def test_generated_and_transient_directories_are_pruned(self, name):
        assert self._pruned(name)


class TestDiscoveryPolicyIsExternal:
    """The prune set is editable data, not a frozen rule.

    A tree that versions its `dist/` output, a monorepo with a package named
    `build`, or a Go module vendoring dependencies it audits each needs a
    different set. Hardcoding one made those cases undiscoverable with no way
    to say so.
    """

    def _policy(self, tmp_path, document):
        import json as _json

        path = tmp_path / "policy.json"
        path.write_text(_json.dumps(document), encoding="utf-8")
        return path

    def test_the_released_policy_loads(self):
        from codess.helpers import (
            DISCOVERY_POLICY_PATH,
            TRAVERSAL_PRUNE_DIRS,
            TRAVERSED_ON_PURPOSE,
        )

        assert DISCOVERY_POLICY_PATH.is_file()
        assert "node_modules" in TRAVERSAL_PRUNE_DIRS
        assert "lib" in TRAVERSED_ON_PURPOSE, (
            "the documented exceptions must travel with the policy, so a setup "
            "tool can report them"
        )

    def test_a_configured_policy_replaces_the_set(self, tmp_path, monkeypatch):
        policy = self._policy(tmp_path, {
            "policy_format": "codess.discovery-policy/1",
            "exclude_dirs": ["scratchwork"],
            "exclude_dir_prefixes": ["gen-"],
        })
        monkeypatch.setenv("CODESS_DISCOVERY_POLICY", str(policy))
        import importlib

        import codess.helpers as helpers

        importlib.reload(helpers)
        try:
            assert helpers.should_prune_directory("scratchwork")
            assert helpers.should_prune_directory("gen-api")
            assert not helpers.should_prune_directory("node_modules"), (
                "a replacement policy replaces rather than extends"
            )
        finally:
            monkeypatch.delenv("CODESS_DISCOVERY_POLICY")
            importlib.reload(helpers)

    def test_a_broken_policy_falls_back_rather_than_raising(self, tmp_path, monkeypatch):
        """Discovery degrading to the shipped set is recoverable; refusing is not.

        A scan that will not start because a policy has a trailing comma is a
        worse failure than one that warns and uses the released names.
        """
        broken = tmp_path / "broken.json"
        broken.write_text("not json", encoding="utf-8")
        monkeypatch.setenv("CODESS_DISCOVERY_POLICY", str(broken))
        import importlib

        import codess.helpers as helpers

        importlib.reload(helpers)
        try:
            assert helpers.should_prune_directory("node_modules")
        finally:
            monkeypatch.delenv("CODESS_DISCOVERY_POLICY")
            importlib.reload(helpers)

    def test_an_unsupported_format_is_refused(self, tmp_path, monkeypatch):
        policy = self._policy(tmp_path, {
            "policy_format": "codess.discovery-policy/99",
            "exclude_dirs": ["anything"],
        })
        monkeypatch.setenv("CODESS_DISCOVERY_POLICY", str(policy))
        import importlib

        import codess.helpers as helpers

        importlib.reload(helpers)
        try:
            assert not helpers.should_prune_directory("anything")
            assert helpers.should_prune_directory("node_modules")
        finally:
            monkeypatch.delenv("CODESS_DISCOVERY_POLICY")
            importlib.reload(helpers)


class TestDiscoveryPathSettings:
    """Path inclusion and exclusion, configured rather than assumed.

    Every test states its own paths and asserts which rule matched. A test
    naming a real directory would test this machine's layout, and the rule is
    what has to hold on every other one.
    """

    def _reloaded(self, monkeypatch, **variables):
        import importlib

        import codess.helpers as helpers

        for name, value in variables.items():
            monkeypatch.setenv(name, value)
        return importlib.reload(helpers)

    def _restored(self, monkeypatch, *names):
        import importlib

        import codess.helpers as helpers

        for name in names:
            monkeypatch.delenv(name, raising=False)
        importlib.reload(helpers)

    def test_both_path_lists_ship_empty(self):
        """A shipped path misclassifies every tree but the one it came from."""
        import json

        from codess.helpers import DISCOVERY_POLICY_PATH

        document = json.loads(DISCOVERY_POLICY_PATH.read_text(encoding="utf-8"))
        assert document["exclude_paths"] == []
        assert document["include_paths"] == []

    def test_a_variable_replaces_the_shipped_names(self, monkeypatch):
        """The three settings resolve the same way: variable, then file.

        An operator should not have to remember which one is file-only.
        """
        try:
            helpers = self._reloaded(monkeypatch, CODESS_EXCLUDE_DIRS="mine,other")
            assert frozenset({"mine", "other"}) == helpers.TRAVERSAL_PRUNE_DIRS
        finally:
            self._restored(monkeypatch, "CODESS_EXCLUDE_DIRS")

    def test_an_empty_name_variable_states_that_there_are_none(self, monkeypatch):
        """Replaces rather than extends, so "none of these" is expressible."""
        try:
            helpers = self._reloaded(monkeypatch, CODESS_EXCLUDE_DIRS="")
            assert frozenset() == helpers.TRAVERSAL_PRUNE_DIRS
        finally:
            self._restored(monkeypatch, "CODESS_EXCLUDE_DIRS")

    def test_names_ship_non_empty(self):
        """A name means the same thing on every machine, so it is safe to ship."""
        from codess.helpers import TRAVERSAL_PRUNE_DIRS

        assert "node_modules" in TRAVERSAL_PRUNE_DIRS

    def test_an_excluded_tree_is_excluded(self, tmp_path, monkeypatch):
        tree = tmp_path / "reference"
        try:
            helpers = self._reloaded(
                monkeypatch, CODESS_EXCLUDE_PATHS=str(tree),
            )
            assert helpers.is_excluded(tree / "vendored")
        finally:
            self._restored(monkeypatch, "CODESS_EXCLUDE_PATHS")

    def test_include_outranks_exclude_for_a_nested_tree(self, tmp_path, monkeypatch):
        """The reason `include_paths` exists: name exclusion over-reaches."""
        tree = tmp_path / "reference"
        kept = tree / "mine"
        try:
            helpers = self._reloaded(
                monkeypatch,
                CODESS_EXCLUDE_PATHS=str(tree),
                CODESS_INCLUDE_PATHS=str(kept),
            )
            assert helpers.is_excluded(tree / "vendored")
            assert not helpers.is_excluded(kept / "project")
        finally:
            self._restored(
                monkeypatch, "CODESS_EXCLUDE_PATHS", "CODESS_INCLUDE_PATHS",
            )

    def test_a_variable_overrides_the_file(self, tmp_path, monkeypatch):
        """A variable names one shell's scope; the file states the machine's."""
        import json

        policy = tmp_path / "policy.json"
        policy.write_text(json.dumps({
            "policy_format": "codess.discovery-policy/1",
            "exclude_paths": ["/from/the/file"],
        }), encoding="utf-8")
        try:
            helpers = self._reloaded(
                monkeypatch,
                CODESS_DISCOVERY_POLICY=str(policy),
                CODESS_EXCLUDE_PATHS="/from/the/variable",
            )
            assert helpers.EXCLUDE_PATHS == ("/from/the/variable",)
        finally:
            self._restored(
                monkeypatch, "CODESS_DISCOVERY_POLICY", "CODESS_EXCLUDE_PATHS",
            )

    def test_the_file_supplies_a_durable_machine_decision(self, tmp_path, monkeypatch):
        import json

        policy = tmp_path / "policy.json"
        policy.write_text(json.dumps({
            "policy_format": "codess.discovery-policy/1",
            "exclude_paths": ["/from/the/file"],
        }), encoding="utf-8")
        try:
            helpers = self._reloaded(
                monkeypatch, CODESS_DISCOVERY_POLICY=str(policy),
            )
            assert helpers.EXCLUDE_PATHS == ("/from/the/file",)
        finally:
            self._restored(monkeypatch, "CODESS_DISCOVERY_POLICY")

    def test_a_traversal_segment_is_rejected_in_either_list(self):
        """`..` lets an entry escape the scope it appears to name."""
        from codess.helpers import parse_policy_list, valid_policy_name

        assert parse_policy_list("/a/../b", as_path=True) == ()
        assert not valid_policy_name("..")

    def test_a_relative_path_is_rejected(self):
        from codess.helpers import parse_policy_list

        assert parse_policy_list("relative/tree", as_path=True) == ()

    def test_lists_are_comma_separated_not_colon_separated(self):
        """A colon is excluded from the value set, so a comma is unambiguous."""
        from codess.helpers import parse_policy_list

        assert parse_policy_list("/a,/b", as_path=True) == ("/a", "/b")
        assert parse_policy_list("/a:/b", as_path=True) == ()

    def test_whitespace_is_stripped(self):
        from codess.helpers import parse_policy_list

        assert parse_policy_list(" /a , /b ", as_path=True) == ("/a", "/b")

    def test_a_name_admits_only_its_stated_characters(self):
        from codess.helpers import valid_policy_name

        assert valid_policy_name("node_modules")
        assert valid_policy_name(".venv")
        assert not valid_policy_name("has/separator")
        assert not valid_policy_name("x" * 256)

    def test_dot_codess_is_read_by_path_rather_than_traversal(self):
        """The hidden-name rule must not reach the directories Codess reads.

        `.codess` and `.claude` are opened by explicit path, so the rule does
        not apply to them -- asserted because it is the kind of thing that
        breaks silently.
        """
        from pathlib import Path

        from codess.config import PROJECT_FILE, STORE_DIR
        from codess.project_catalog import _binding_path

        assert _binding_path(Path("/p")) == Path("/p") / STORE_DIR / PROJECT_FILE


class TestDiscoveryFollowsNoSymlink:
    """A link inside an excluded tree would re-admit excluded content."""

    def test_traversal_does_not_follow_a_symlink(self, tmp_path):
        import ast
        import inspect

        import codess.review_project as review_project

        source = inspect.getsource(review_project.discover_git_roots)
        walks = [
            node for node in ast.walk(ast.parse(source.strip()))
            if isinstance(node, ast.Call)
            and getattr(node.func, "attr", None) == "walk"
        ]
        assert walks, "discovery no longer calls os.walk; re-check the rule"
        for call in walks:
            follow = [k for k in call.keywords if k.arg == "followlinks"]
            assert follow and follow[0].value.value is False
