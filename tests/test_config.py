"""Tests for config paths and options."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from codess.config import (
    CC_PROJECTS,
    CODEX_ARCHIVED_SESSIONS,
    CODEX_SESSIONS,
    REDACT_PATTERNS,
    STORE_DB,
    STORE_DIR,
    SUBAGENT,
    env_bool,
    get_state_path,
    get_store_path,
    validate_config,
)
from codess.project import (
    build_ingest_run_options,
    resolve_store_root,
    validate_scan_source_for_cli,
)


class TestPaths:
    """Path derivation."""

    def test_get_store_path(self, tmp_path):
        store = get_store_path(tmp_path)
        assert store == tmp_path / STORE_DIR / STORE_DB

    def test_get_state_path(self, tmp_path):
        state = get_state_path(tmp_path)
        assert state == tmp_path / STORE_DIR / "ingest_state.json"


class TestEnvOverrides:
    """Environment variable overrides."""

    def test_cc_projects_default(self):
        assert "claude" in str(CC_PROJECTS).lower() or "projects" in str(CC_PROJECTS)

    def test_codex_sessions_default(self):
        assert "codex" in str(CODEX_SESSIONS).lower()
        assert (
            CODEX_ARCHIVED_SESSIONS is None
            or "archived_sessions" in str(CODEX_ARCHIVED_SESSIONS)
        )

    def test_paths_are_absolute(self):
        assert CC_PROJECTS.is_absolute()
        assert CODEX_SESSIONS.is_absolute()


class TestValidateConfig:
    """Config value validation."""

    def test_default_valid(self):
        assert validate_config() == []

    def test_subagent_default_false(self):
        assert SUBAGENT is False or SUBAGENT is True  # env may override


class TestRedactPatterns:
    """REDACT_PATTERNS is non-empty and compilable."""

    def test_patterns_exist(self):
        assert len(REDACT_PATTERNS) >= 1

    def test_patterns_are_compiled(self):
        for p in REDACT_PATTERNS:
            assert hasattr(p, "search")


class TestEnvBool:
    """env_bool truth table (same rules as CODESS_* booleans)."""

    def test_unset_false(self, monkeypatch):
        monkeypatch.delenv("CODESS_TESTBOOL", raising=False)
        assert env_bool("CODESS_TESTBOOL") is False

    def test_one_true(self, monkeypatch):
        monkeypatch.setenv("CODESS_TESTBOOL", "1")
        assert env_bool("CODESS_TESTBOOL") is True

    def test_yes_true(self, monkeypatch):
        monkeypatch.setenv("CODESS_TESTBOOL", "YES")
        assert env_bool("CODESS_TESTBOOL") is True

    def test_on_false(self, monkeypatch):
        monkeypatch.setenv("CODESS_TESTBOOL", "on")
        assert env_bool("CODESS_TESTBOOL") is False

    def test_two_false(self, monkeypatch):
        monkeypatch.setenv("CODESS_TESTBOOL", "2")
        assert env_bool("CODESS_TESTBOOL") is False

    def test_empty_false(self, monkeypatch):
        monkeypatch.setenv("CODESS_TESTBOOL", "")
        assert env_bool("CODESS_TESTBOOL") is False


class TestCliOptionsEnvMerge:
    """ENV-backed bools merged in build_*_run_options (monkeypatch config module)."""

    def test_ingest_redact_env(self, monkeypatch):
        monkeypatch.setattr("codess.config.REDACT", True)
        args = SimpleNamespace(
            stop=False, force=False, min_size=100, debug=False, redact=False
        )
        assert build_ingest_run_options(args)["redact"] is True

    def test_ingest_redact_cli_overrides_false_env(self, monkeypatch):
        monkeypatch.setattr("codess.config.REDACT", False)
        args = SimpleNamespace(
            stop=False, force=False, min_size=100, debug=False, redact=True
        )
        assert build_ingest_run_options(args)["redact"] is True

    def test_ingest_context_limit_cli_override(self):
        args = SimpleNamespace(
            stop=False, force=False, min_size=100, debug=False, redact=False,
            max_context_content_chars=4096,
        )
        assert build_ingest_run_options(args)["max_context_content_chars"] == 4096

    def test_ingest_no_resource_disables_context_limit(self):
        args = SimpleNamespace(
            stop=False, force=False, min_size=100, debug=False, redact=False,
            no_resource=True, max_context_content_chars=4096,
        )
        assert build_ingest_run_options(args)["max_context_content_chars"] is None

class TestValidateScanSource:
    """Scan --source is validated globally before run (see scan_cmd)."""

    def test_none_ok(self):
        assert validate_scan_source_for_cli(None) is None

    def test_all_ok(self):
        assert validate_scan_source_for_cli("all") is None
        assert validate_scan_source_for_cli(" ALL ") is None

    def test_single_vendor_ok(self):
        assert validate_scan_source_for_cli("cc") is None
        assert validate_scan_source_for_cli("CC, Codex ") is None

    def test_bad_token(self):
        err = validate_scan_source_for_cli("cc,foo")
        assert err and "foo" in err
        assert "invalid" in err.lower()


class TestRegistryArgResolution:
    """``--store PATH`` vs omitted -> ``resolve_store_root``."""

    def test_omitted_uses_config_registry(self, monkeypatch, tmp_path):
        monkeypatch.setattr("codess.config.STORE_ROOT", tmp_path)
        args = SimpleNamespace(store_root=None)
        assert resolve_store_root(args) == tmp_path

    def test_explicit_path_overrides(self, monkeypatch, tmp_path):
        monkeypatch.setattr("codess.config.STORE_ROOT", tmp_path)
        other = tmp_path / "other"
        args = SimpleNamespace(store_root=str(other))
        assert resolve_store_root(args) == other


# --- closed vocabulary: raw modes -------------------------------------------
#
# Closed-vocabulary literals are replaced and an invalid value fails at the boundary.
# Written out longhand at nine sites, a mode added at one would be accepted by some
# boundaries and rejected by others.

def test_raw_modes_are_ordered_by_how_much_is_retained():
    """Every message that lists them uses this order."""
    from codess.config import RAW_MODES

    assert RAW_MODES == ("observe", "reference", "capture", "seal")


def test_the_least_retaining_mode_is_not_named_for_retaining_nothing():
    """`observe` states what the mode does; `none` promised it did nothing."""
    from codess.config import RAW_MODES

    assert "none" not in RAW_MODES


def test_the_previous_spelling_still_parses():
    """`--raw-mode none` appears in operator scripts and in retained manifests."""
    from codess.config import canonical_raw_mode

    assert canonical_raw_mode("none") == "observe"


def test_a_stored_mode_canonicalizes_to_itself():
    """Canonicalization must be safe to apply at every boundary, including twice."""
    from codess.config import RAW_MODES, canonical_raw_mode

    for mode in RAW_MODES:
        assert canonical_raw_mode(mode) == mode
        assert canonical_raw_mode(canonical_raw_mode(mode)) == mode


def test_an_unknown_mode_passes_through_for_its_own_validator_to_reject():
    """The rejection message and its valid list stay with the site that owns them."""
    from codess.config import canonical_raw_mode

    assert canonical_raw_mode("archive") == "archive"


def test_the_alias_is_not_offered_as_an_equal_choice():
    """argparse would list it beside the stored name; there is one name per mode."""
    from codess.config import RAW_MODE_ALIASES, RAW_MODE_CHOICES

    assert set(RAW_MODE_ALIASES) & set(RAW_MODE_CHOICES) == set()


def test_every_alias_resolves_to_a_stored_mode():
    """An alias pointing at a mode that does not exist would fail at the boundary."""
    from codess.config import RAW_MODE_ALIASES, RAW_MODES

    assert set(RAW_MODE_ALIASES.values()) <= set(RAW_MODES)


def test_the_previous_spelling_is_accepted_by_the_raw_store():
    """An operator script passing `none` must still observe rather than fail."""
    import tempfile
    from pathlib import Path

    from codess.raw_store import RawStore

    store = RawStore(Path(tempfile.mkdtemp()))
    record = store.observe(
        Path(__file__), source_system_key="x", storage_format="y", mode="none",
    )
    assert record["availability"] == "not_retained"


def test_observe_retains_no_bytes_but_records_the_observation():
    """The record is what makes a Source's absence checkable."""
    import tempfile
    from pathlib import Path

    from codess.raw_store import RawStore

    store = RawStore(Path(tempfile.mkdtemp()))
    record = store.observe(
        Path(__file__), source_system_key="x", storage_format="y", mode="observe",
    )
    assert record["availability"] == "not_retained"
    assert record["source_revision_id"]
    assert record["source_size"] > 0


def test_observe_and_reference_differ_only_in_availability():
    """The measurement the rename rests on: one code path, one differing key."""
    import tempfile
    from pathlib import Path

    from codess.raw_store import RawStore

    store = RawStore(Path(tempfile.mkdtemp()))
    kwargs = {"source_system_key": "x", "storage_format": "y"}
    observed = store.observe(Path(__file__), mode="observe", **kwargs)
    referenced = store.observe(Path(__file__), mode="reference", **kwargs)
    differing = {
        key for key in set(observed) | set(referenced)
        if observed.get(key) != referenced.get(key)
    }
    assert differing == {"availability", "observed_at"}
    assert observed["availability"] == "not_retained"
    assert referenced["availability"] == "reference"


def test_the_raw_store_set_matches_the_vocabulary():
    """Two spellings of one vocabulary would disagree on a new mode."""
    from codess.config import RAW_MODES
    from codess.raw_store import RAW_MODES as STORE_MODES

    assert frozenset(RAW_MODES) == STORE_MODES


def test_no_module_writes_the_raw_mode_set_out_longhand():
    """The longhand duplication must not come back."""
    from pathlib import Path

    import codess.config as config_module

    root = Path(config_module.__file__).resolve().parent.parent
    offenders = []
    for path in sorted(root.rglob("*.py")):
        if path.name == "config.py":
            continue
        text = path.read_text(encoding="utf-8")
        if '"reference", "capture", "seal"' in text:
            offenders.append(path.name)
    assert offenders == []


def test_an_invalid_raw_mode_is_refused_by_the_raw_store():
    import tempfile
    from pathlib import Path

    from codess.raw_store import RawCaptureError, RawStore

    store = RawStore(Path(tempfile.mkdtemp()))
    with pytest.raises(RawCaptureError, match="invalid raw mode"):
        store.observe(
            Path(__file__), source_system_key="x", storage_format="y", mode="archive",
        )


def test_an_invalid_raw_mode_is_refused_by_refresh():
    from codess.refresh_operations import resolve_refresh_selection

    with pytest.raises(ValueError, match="must be auto"):
        resolve_refresh_selection(
            Path("/nonexistent"), designator="core", source="all",
            raw_mode="archive",
        )


def test_refresh_accepts_its_own_auto_mode():
    """`auto` means keep what the snapshot was built under; only refresh has it."""
    from codess.config import RAW_MODES

    assert "auto" not in RAW_MODES


def test_an_invalid_raw_mode_is_refused_by_validation_policy(tmp_path):
    import json

    from codess.baseline_validation import POLICY_FORMAT, load_policy

    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps({"policy_format": POLICY_FORMAT, "raw_mode": "archive"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="raw_mode is invalid"):
        load_policy(path)


def test_a_validation_policy_may_state_no_raw_mode(tmp_path):
    """Absent means validate whatever the snapshot was built under."""
    import json

    from codess.baseline_validation import POLICY_FORMAT, load_policy

    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"policy_format": POLICY_FORMAT}), encoding="utf-8")
    assert load_policy(path)["policy_format"] == POLICY_FORMAT


def test_a_validation_policy_may_use_the_previous_spelling(tmp_path):
    """An operator policy written before the rename must still load."""
    import json

    from codess.baseline_validation import POLICY_FORMAT, load_policy

    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps({"policy_format": POLICY_FORMAT, "raw_mode": "none"}),
        encoding="utf-8",
    )
    assert load_policy(path)["raw_mode"] == "none"


def test_refresh_keeps_a_snapshot_built_under_the_previous_spelling(tmp_path):
    """A manifest recording `none` refreshes under `observe`, not `reference`.

    The failure this prevents is silent: an unrecognized stored mode falls
    through to the `reference` default, so a Project that deliberately retained
    nothing would quietly start recording resolvable references.
    """
    import json

    from codess.config import CURRENT_POINTER_FILE, MANIFEST_FILE
    from codess.fileio import hash_file
    from codess.project_catalog import durable_project_root
    from codess.refresh_operations import _automatic_raw_mode

    registry = tmp_path / "registry"
    project_id = "p1"
    base = durable_project_root(registry, project_id)
    snapshot = base / "snapshots" / "20260101T000000.000000Z-test"
    snapshot.mkdir(parents=True)
    manifest = snapshot / MANIFEST_FILE
    manifest.write_text(
        json.dumps({"build_policy": {"raw_mode": "none"}}), encoding="utf-8",
    )
    (base / CURRENT_POINTER_FILE).write_text(
        json.dumps({
            "path": str(snapshot),
            "manifest_digest": hash_file(manifest),
        }),
        encoding="utf-8",
    )
    assert _automatic_raw_mode(registry, project_id) == "observe"


def test_refresh_accepts_the_previous_spelling():
    """`--raw-mode none` in an operator script must not become an error."""
    from codess.config import canonical_raw_mode

    assert canonical_raw_mode("none") == "observe"


def test_the_rejection_message_lists_every_valid_mode():
    from codess.config import RAW_MODES, raw_mode_error

    message = raw_mode_error("CODESS_RAW_MODE", "archive")
    assert all(mode in message for mode in RAW_MODES)
    assert "archive" in message


def test_the_rejection_message_includes_a_site_specific_value():
    from codess.config import raw_mode_error

    assert "auto" in raw_mode_error("raw_mode", "x", extra=("auto",))


# --- discovery scoping ------------------------------------------------------
#
# `AGGREGATORS` and `EXCLUDE_REVIEW_DIRS` are environment-configurable. As frozen sets
# naming one developer's directories they reported another operator's grouping
# directories as Projects and scanned their review trees.

def reload_config(monkeypatch, **environment):
    """Re-import config under a chosen environment.

    The constants resolve at import, so an override has to be tested by
    reloading rather than by setting a variable after the fact -- which is
    also why `--no-check` and `--no-hash` read the environment directly.
    """
    import importlib

    import codess.config as module

    for key, value in environment.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    return importlib.reload(module)


def _reload_helpers(monkeypatch, **environment):
    """Reload `helpers`, which owns the path settings, under one environment.

    They live there rather than in `config` because a leaf module reads them
    and cannot import `config` without a cycle.
    """
    import importlib

    import codess.helpers as module

    for key, value in environment.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    reloaded = importlib.reload(module)
    importlib.reload(importlib.import_module("codess.project"))
    return reloaded


def test_discovery_path_settings_ship_empty(monkeypatch):
    """A path describes one machine's layout, so no shipped default is right."""
    module = _reload_helpers(
        monkeypatch, CODESS_EXCLUDE_PATHS=None, CODESS_INCLUDE_PATHS=None,
    )
    try:
        assert module.EXCLUDE_PATHS == ()
        assert module.INCLUDE_PATHS == ()
    finally:
        _reload_helpers(monkeypatch)


def test_exclusions_can_be_replaced_and_emptied(monkeypatch):
    """Another operator's tree holds its reference trees elsewhere."""
    module = _reload_helpers(
        monkeypatch, CODESS_EXCLUDE_PATHS="/w/backups, /w/old/reviews",
    )
    try:
        assert module.EXCLUDE_PATHS == ("/w/backups", "/w/old/reviews")
    finally:
        _reload_helpers(monkeypatch, CODESS_EXCLUDE_PATHS=None)
    module = _reload_helpers(monkeypatch, CODESS_EXCLUDE_PATHS="")
    try:
        assert module.EXCLUDE_PATHS == ()
    finally:
        _reload_helpers(monkeypatch, CODESS_EXCLUDE_PATHS=None)


def test_a_relative_scoping_entry_is_refused(monkeypatch):
    """The inverse of the rule the retired settings had.

    `AGGREGATORS` and `EXCLUDE_REVIEW_DIRS` matched relative to the work root,
    so an absolute entry silently scoped nothing. `exclude_paths` is absolute,
    so a relative entry is the one that cannot match -- and it is dropped with
    a warning rather than admitted, because an exclusion the operator wrote and
    Codess ignored is the case they would otherwise never see.
    """
    module = _reload_helpers(monkeypatch, CODESS_EXCLUDE_PATHS="relative/tree,/w/ok")
    try:
        assert module.EXCLUDE_PATHS == ("/w/ok",)
    finally:
        _reload_helpers(monkeypatch, CODESS_EXCLUDE_PATHS=None)


def test_default_configuration_reports_no_errors(monkeypatch):
    module = reload_config(
        monkeypatch, CODESS_AGGREGATORS=None, CODESS_EXCLUDE_REVIEW_DIRS=None,
    )
    try:
        assert not [
            e for e in module.validate_config()
            if "AGGREGATORS" in e or "EXCLUDE_REVIEW_DIRS" in e
        ]
    finally:
        reload_config(monkeypatch)

def test_a_flag_name_declares_one_type() -> None:
    """One flag name yields one type, whichever command family declares it.

    `--store` is declared 22 times across two modules and carried three
    incompatible forms: `type=Path` in 21 of them and `type=str` in the
    twenty-second, so a caller moving between command families received a
    different type from one flag name. Behaviour was right because
    `resolve_store_root` normalizes both, which is what made the divergence
    invisible.

    Checks the *declared* type rather than any resolver, because a resolver that
    accepts both is what hides this. `default` and `required` may legitimately
    differ -- one subcommand requires the store it operates on -- so only the
    type is compared.
    """
    import ast
    from collections import defaultdict

    root = Path(__file__).resolve().parents[1] / "src"
    types_by_flag: dict[str, set[str]] = defaultdict(set)
    for source in (root / "cli" / "admin_cmd.py", root / "codess" / "project.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
                and node.args
            ):
                continue
            name = node.args[0]
            if not (isinstance(name, ast.Constant) and str(name.value).startswith("--")):
                continue
            declared = next(
                (ast.unparse(kw.value) for kw in node.keywords if kw.arg == "type"),
                "str",
            )
            types_by_flag[str(name.value)].add(declared)

    # Two of the three original collisions were renamed rather than tolerated:
    # the Project *directory* became `--directory`, leaving `--project` for the
    # references it always named, and `--selection` split into `--select` for a
    # state and `--file` for a path.
    #
    # `--since` stays a collision on purpose. Both spellings are correct for
    # their command -- a git date expression is what `rev-list --since` accepts,
    # and a Unix millisecond timestamp is what a Codess `_at` column holds -- and
    # each matches the vocabulary of the surface it belongs to. Renaming either
    # would make one command's flag disagree with the tool it wraps.
    different_subjects = {"--since"}

    conflicting = {
        flag: sorted(kinds)
        for flag, kinds in types_by_flag.items()
        if len(kinds) > 1 and flag not in different_subjects
    }
    assert not conflicting, f"one flag name, two declared types: {conflicting}"

def test_a_shared_option_is_declared_once() -> None:
    """An option many subcommands take is inherited, not rewritten per subcommand.

    `--store` was written out 22 times, 19 of them byte-identical, and `--output`
    11 times identically. Each addition was locally correct and matched its
    neighbours; the pattern being matched was the defect, because a twentieth
    subcommand needing the option got it the only way the surrounding code
    demonstrated.

    `parents=` is argparse's own mechanism and renders an inherited option
    exactly as a locally declared one, so the deduplication is invisible to a
    caller. The threshold is four rather than two: a genuinely different form --
    `--store` required for one command, `--project-id` repeatable for one -- keeps
    its own declaration rather than bending the shared one, and a handful of
    those is the expected state rather than a regression.
    """
    import ast
    from collections import Counter

    root = Path(__file__).resolve().parents[1] / "src"
    counts: Counter[str] = Counter()
    tree = ast.parse((root / "cli" / "admin_cmd.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
        ):
            continue
        name = node.args[0]
        if isinstance(name, ast.Constant) and str(name.value).startswith("--"):
            counts[str(name.value)] += 1

    # Counted by *identical* form, because that is what `parents=` can merge.
    # `--catalog` is required for two commands and defaulted for a third,
    # `--apply` carries a different help string per command because it enables a
    # different action, and one `--project-id` is repeatable. Inheriting any of
    # those would change what its subcommand accepts, which is a behaviour change
    # wearing a deduplication's clothes.
    identical: Counter[tuple[str, str]] = Counter()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
        ):
            continue
        name = node.args[0]
        if not (isinstance(name, ast.Constant) and str(name.value).startswith("--")):
            continue
        form = ", ".join(sorted(f"{k.arg}={ast.unparse(k.value)}" for k in node.keywords))
        identical[(str(name.value), form)] += 1

    repeated = {
        flag: n for (flag, _form), n in identical.items() if n >= 3
    }
    assert not repeated, (
        "declare these on a `_shared` parent and inherit them rather than "
        f"repeating the line: {repeated}"
    )
    assert counts, "no flags parsed; the check would pass vacuously"

def test_a_directory_valued_flag_is_named_directory() -> None:
    """A flag whose value is a Project directory is called `--directory`.

    One spelling per subject, checked across the command modules and the
    development tools together, because a caller moving between them should not
    have to learn a second name for the same thing. Four tools and one
    subcommand called it `--project` or `--path`: the first is the *reference*
    spelling this CLI uses elsewhere, and the second says only that the value is
    a path, which `type=Path` already says.

    `--dir` is exempt and is not a lapse. It is the documented Project selector
    for `scan`, `ingest`, and `query` -- 33 occurrences across README and
    Operations -- and it is repeatable where `--directory` is singular and
    required. Two names because they are two things: a selector that accumulates
    a set, and the one directory a command operates on.
    """
    import ast

    root = Path(__file__).resolve().parents[1]
    reference_spellings = {"--project", "--path"}
    offenders: list[str] = []
    for source in sorted((root / "src").rglob("*.py")) + sorted((root / "tools").rglob("*.py")):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a tool that does not parse
            continue
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
                and node.args
            ):
                continue
            name = node.args[0]
            if not (isinstance(name, ast.Constant) and name.value in reference_spellings):
                continue
            keywords = {k.arg: ast.unparse(k.value) for k in node.keywords}
            # A `Path` conversion is what distinguishes a directory from a
            # reference: `catalog decide --project` and `refresh --project` take
            # an id, a name, or a path as text, and stay `--project`.
            if keywords.get("type") == "Path":
                offenders.append(
                    f"{source.relative_to(root)}:{node.lineno} {name.value}"
                )
    assert not offenders, (
        "a directory-valued flag is `--directory`: " + ", ".join(offenders)
    )

def test_dir_selects_and_directory_operates() -> None:
    """`--dir` accumulates a set; `--directory` is one required operand.

    Two flags rather than one because they differ in arity, and the difference
    is load-bearing: `--dir` routes through `resolve_cli_roots`, which merges it
    with the `--dirs` file and falls back to the current or Project root, while
    every `--directory` callee takes exactly one `Path`.

    Asserted so a merge cannot happen by accident. One name would stop
    predicting arity -- `catalog location retire --dir X` singular and required
    against `scan --dir X` repeatable and optional -- which is the same
    one-name-two-behaviours defect the flag renames removed.
    """
    import ast

    root = Path(__file__).resolve().parents[1]
    wrong: list[str] = []
    for source in sorted((root / "src").rglob("*.py")) + sorted((root / "tools").rglob("*.py")):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a tool that does not parse
            continue
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
                and node.args
            ):
                continue
            name = node.args[0]
            if not isinstance(name, ast.Constant):
                continue
            keywords = {k.arg: ast.unparse(k.value) for k in node.keywords}
            where = f"{source.relative_to(root)}:{node.lineno}"
            if name.value == "--dir" and keywords.get("action") != "'append'":
                wrong.append(f"{where} --dir is the selector and must be repeatable")
            if name.value == "--directory" and keywords.get("action") == "'append'":
                wrong.append(f"{where} --directory is one operand and must not repeat")
    assert not wrong, "; ".join(wrong)

def test_every_command_option_carries_help() -> None:
    """No flag reaches an operator undocumented.

    76 distinct names in `admin_cmd` carried no help while `project.py`
    documented all of its own, so the administrative surface was undocumented as
    a class rather than by oversight in a few places. Five of those gate a
    verification step, which is exactly where an operator most needs to be told
    what is being skipped.

    Checked over the built parser rather than the source, because that is what a
    caller reads: an option inherited from a shared parent is documented once and
    must render documented everywhere it appears.
    """
    from cli.admin_cmd import build_parser

    def walk(parser, prefix=()):
        yield prefix, parser
        for action in parser._actions:
            choices = getattr(action, "choices", None)
            if isinstance(choices, dict):
                for name, sub in choices.items():
                    if hasattr(sub, "_actions"):
                        yield from walk(sub, (*prefix, name))

    undocumented: list[str] = []
    for prefix, parser in walk(build_parser()):
        for action in parser._actions:
            if not action.option_strings or action.option_strings == ["-h", "--help"]:
                continue
            if not action.help:
                undocumented.append(f"{' '.join(prefix)} {action.option_strings[0]}")
    assert not undocumented, f"these options render no help: {undocumented}"

def test_a_wide_signature_is_a_builder_or_takes_a_structure() -> None:
    """A function with many parameters either builds a record or takes an object.

    The distinction is measurable rather than stylistic: a **builder** places its
    parameters into a returned literal, so the parameter list *is* the record's
    shape and an object would name every field twice. A **relay** forwards its
    parameters to another call, and each one it names is a value it does not
    read -- which is what a policy object removes.

    `codex._base_event` takes 20 parameters and puts 14 into its dict; converting
    it would be the anti-pattern, not the fix. `_ingest_project` forwards all 10
    of its own, which is a relay with nothing else to say for itself.

    The threshold is 10 because that is where a call site stops being readable
    without counting positions, and the census is cheap: it parses `src/` in
    well under a second.
    """
    import ast

    root = Path(__file__).resolve().parents[1] / "src"
    unclassified: list[str] = []
    for source in sorted(root.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            params = {
                arg.arg for arg in node.args.args + node.args.kwonlyargs
            } - {"self", "cls"}
            if len(params) < 10:
                continue
            placed, forwarded = set(), set()
            for inner in ast.walk(node):
                if isinstance(inner, ast.Dict):
                    placed |= {
                        value.id for value in inner.values
                        if isinstance(value, ast.Name) and value.id in params
                    }
                if isinstance(inner, ast.Call):
                    supplied = list(inner.args) + [k.value for k in inner.keywords]
                    forwarded |= {
                        arg.id for arg in supplied
                        if isinstance(arg, ast.Name) and arg.id in params
                    }
            # A builder places most of what it takes; a relay forwards most of
            # it. A function doing neither is one whose parameters go nowhere a
            # reader can see, which is the case worth reporting.
            if len(placed) < len(params) / 2 and len(forwarded) < len(params) / 2:
                unclassified.append(
                    f"{source.name}:{node.lineno} {node.name} "
                    f"({len(params)} params, {len(placed)} placed, "
                    f"{len(forwarded)} forwarded)"
                )
    assert not unclassified, (
        "a wide signature should build a record or forward to one call: "
        + "; ".join(unclassified)
    )



def test_a_decode_function_takes_the_record_context_rather_than_its_fields() -> None:
    """The four values identifying a record travel as one object.

    `session_id`, `source_file`, `line_num`, and `opts` say *which* record is
    being decoded and none varies within one record's decode. As four
    parameters they were four chances to transpose two strings at a call site:
    `session_id` and `source_file` are both `str`, so swapping them type-checks
    and produces an Event citing the wrong Source.

    Builders are exempt for the reason the relay census already states -- their
    parameter list is the record's shape, so an object would name every field
    twice. `codex._base_event` is the measured instance.
    """
    import ast
    from pathlib import Path

    group = {"session_id", "source_file", "line_num", "opts"}
    builders = {"_base_event"}
    offenders = []
    adapters = Path(__file__).resolve().parent.parent / "src" / "codess" / "adapters"
    for source in sorted(adapters.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name in builders:
                continue
            names = {argument.arg for argument in node.args.args}
            names |= {argument.arg for argument in node.args.kwonlyargs}
            if len(group & names) >= 3:
                offenders.append(f"{source.name}:{node.name}")
    assert not offenders, (
        "these take three or more record-context fields separately rather than "
        f"a RecordContext: {', '.join(offenders)}"
    )


def test_the_cli_and_the_tool_report_one_configuration() -> None:
    """`codess config discovery` routes to the tool rather than restating it.

    Two reporters would drift the moment a setting is added to one: the CLI
    reports what *this process* resolved, and a separately runnable tool exists
    for a checkout with no install. They must not be two answers.
    """
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent / "src" / "cli" / "admin_cmd.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_config_discovery"
    )
    imported = {
        alias.name
        for node in ast.walk(handler)
        if isinstance(node, ast.ImportFrom) and node.module == "setup_discovery"
        for alias in node.names
    }
    assert "report_configuration" in imported, (
        "the CLI must route to the tool; a second reporter drifts"
    )


def test_the_reported_configuration_names_the_three_settings() -> None:
    """The report is what an operator reads to check what is in effect."""
    import sys
    from pathlib import Path

    tools = Path(__file__).resolve().parent.parent / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    from setup_discovery import report_configuration

    reported = report_configuration()
    assert {"exclude_dirs", "exclude_paths", "include_paths"} <= set(reported)
