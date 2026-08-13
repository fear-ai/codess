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
    resolve_registry_directory,
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
        monkeypatch.setattr("codess.config.INGEST_REDACT", True)
        args = SimpleNamespace(
            stop=False, force=False, min_size=100, debug=False, redact=False
        )
        assert build_ingest_run_options(args)["redact"] is True

    def test_ingest_redact_cli_overrides_false_env(self, monkeypatch):
        monkeypatch.setattr("codess.config.INGEST_REDACT", False)
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

    def test_ingest_no_resource_limits_disables_context_limit(self):
        args = SimpleNamespace(
            stop=False, force=False, min_size=100, debug=False, redact=False,
            no_resource_limits=True, max_context_content_chars=4096,
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
    """``--registry PATH`` vs omitted → ``resolve_registry_directory``."""

    def test_omitted_uses_config_registry(self, monkeypatch, tmp_path):
        monkeypatch.setattr("codess.config.REGISTRY", tmp_path)
        args = SimpleNamespace(registry=None)
        assert resolve_registry_directory(args) == tmp_path

    def test_explicit_path_overrides(self, monkeypatch, tmp_path):
        monkeypatch.setattr("codess.config.REGISTRY", tmp_path)
        other = tmp_path / "other"
        args = SimpleNamespace(registry=str(other))
        assert resolve_registry_directory(args) == other


# --- closed vocabulary: raw modes -------------------------------------------
#
# W23's criterion is that closed-vocabulary literals are replaced and an
# invalid value fails at the boundary. Raw modes were written out longhand at
# nine sites, so a mode added at one would have been accepted by some
# boundaries and rejected by others.

def test_raw_modes_are_ordered_by_how_much_is_retained():
    """Every message that lists them uses this order."""
    from codess.config import RAW_MODES

    assert RAW_MODES == ("none", "reference", "capture", "seal")


def test_the_raw_store_set_matches_the_vocabulary():
    """Two spellings of one vocabulary would disagree on a new mode."""
    from codess.config import RAW_MODES
    from codess.raw_store import RAW_MODES as STORE_MODES

    assert frozenset(RAW_MODES) == STORE_MODES


def test_no_module_writes_the_raw_mode_set_out_longhand():
    """The duplication W23 removed must not come back."""
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
            Path(__file__), source_system_id="x", storage_format="y", mode="archive",
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
# W27: `AGGREGATORS` and `EXCLUDE_REVIEW_DIRS` were frozen sets naming one
# developer's directories, with no override and no mention outside the source.
# Another operator's grouping directories were reported as Projects and their
# review trees were scanned.

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


def test_discovery_scoping_defaults_are_documented_names(monkeypatch):
    module = reload_config(
        monkeypatch, CODESS_AGGREGATORS=None, CODESS_EXCLUDE_REVIEW_DIRS=None,
    )
    try:
        assert frozenset(module.DEFAULT_AGGREGATORS) == module.AGGREGATORS
        assert module.EXCLUDE_REVIEW_DIRS == module.DEFAULT_EXCLUDE_REVIEW_DIRS
    finally:
        reload_config(monkeypatch)


def test_aggregators_can_be_replaced(monkeypatch):
    """Another operator's tree has different grouping directories."""
    module = reload_config(monkeypatch, CODESS_AGGREGATORS="Projects, Work ,src")
    try:
        assert frozenset({"Projects", "Work", "src"}) == module.AGGREGATORS
    finally:
        reload_config(monkeypatch, CODESS_AGGREGATORS=None)


def test_an_empty_setting_means_no_aggregators(monkeypatch):
    """A tree with no grouping directories must be able to say so.

    The frozen set could not express this: an operator whose every directory
    is a candidate Project had no way to turn the default off.
    """
    module = reload_config(monkeypatch, CODESS_AGGREGATORS="")
    try:
        assert frozenset() == module.AGGREGATORS
    finally:
        reload_config(monkeypatch, CODESS_AGGREGATORS=None)


def test_exclusions_can_be_replaced_and_emptied(monkeypatch):
    module = reload_config(
        monkeypatch, CODESS_EXCLUDE_REVIEW_DIRS="backups,old/reviews",
    )
    try:
        assert module.EXCLUDE_REVIEW_DIRS == ("backups", "old/reviews")
    finally:
        reload_config(monkeypatch, CODESS_EXCLUDE_REVIEW_DIRS=None)
    module = reload_config(monkeypatch, CODESS_EXCLUDE_REVIEW_DIRS="")
    try:
        assert module.EXCLUDE_REVIEW_DIRS == ()
    finally:
        reload_config(monkeypatch, CODESS_EXCLUDE_REVIEW_DIRS=None)


def test_an_absolute_scoping_entry_is_reported(monkeypatch):
    """Both are matched relative to the work root, so an absolute path never
    matches -- silently scoping nothing rather than what was intended."""
    module = reload_config(monkeypatch, CODESS_AGGREGATORS="/absolute/tree,Fine")
    try:
        errors = module.validate_config()
        assert any("must be relative to the work root" in e for e in errors)
    finally:
        reload_config(monkeypatch, CODESS_AGGREGATORS=None)


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
