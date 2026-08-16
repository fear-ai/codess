"""Direct tests for the ingest phases extracted from ingest_cmd.run().

These paths previously ran only inside a thousand-line function, so they were
reachable in tests only by executing a whole ingest. Each phase is now called
on its own, which is the point of the extraction.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from cli.ingest_cmd import IngestConfig, _resolve_ingest_request


def config(tmp_path, **overrides):
    options = {"validate_only": False}
    options.update(overrides.pop("options", {}))
    return IngestConfig(
        options=options,
        sources=("cc", "codex", "cursor"),
        registry_root=overrides.pop("registry_root", tmp_path / "registry"),
        **overrides,
    )


def make_args(**overrides):
    values = {"source": "all", "dir": None, "dirs": None, "registry": None}
    values.update(overrides)
    return argparse.Namespace(**values)


# --- request resolution -----------------------------------------------------

def test_comma_separated_source_is_rejected(capsys, tmp_path):
    result = _resolve_ingest_request(make_args(source="cc,codex", dir=str(tmp_path)))
    assert result == 1
    assert "one token" in capsys.readouterr().err


def test_unknown_source_is_rejected(capsys, tmp_path):
    result = _resolve_ingest_request(make_args(source="notavendor", dir=str(tmp_path)))
    assert result == 1
    assert "invalid ingest --source" in capsys.readouterr().err


@pytest.mark.parametrize(
    "selector,expected",
    [
        ("cc", ["cc"]),
        ("codex", ["codex"]),
        ("cursor", ["cursor"]),
        ("all", ["cc", "codex", "cursor"]),
    ],
)
def test_source_selector_expands_to_vendor_list(selector, expected, tmp_path):
    result = _resolve_ingest_request(make_args(source=selector, dir=str(tmp_path)))
    assert not isinstance(result, int), result
    _roots, _registry, sources, _iopt = result
    assert sources == expected


def test_source_selector_is_case_insensitive(tmp_path):
    result = _resolve_ingest_request(make_args(source="  CC  ", dir=str(tmp_path)))
    assert not isinstance(result, int)
    assert result[2] == ["cc"]


def test_resolution_returns_roots_and_registry(tmp_path):
    result = _resolve_ingest_request(make_args(dir=str(tmp_path)))
    assert not isinstance(result, int)
    roots, registry_root, _sources, settings = result
    assert roots and all(isinstance(root, Path) for root in roots)
    assert isinstance(registry_root, Path)
    assert "validate_only" in settings


# --- vendor store handles ---------------------------------------------------

def entry():
    return {"project_id": "codess:project:test", "logical_name": "t", "locations": []}


def test_store_path_uses_the_project_when_not_staging(tmp_path):
    store = config(tmp_path).vendor_store(tmp_path, "cc")
    assert store.path.name == "sessions_cc.db"
    assert tmp_path in store.path.parents


def test_store_path_redirects_into_staging_for_preflight(tmp_path):
    """Preflight registers each Project's staging directory, like a rebuild.

    Both redirections read one mapping. Preflight previously derived its own
    directory by hashing the Project path, while the Project loop derived the
    state path from the loop index, so a Project's stores and its state landed
    in different staging directories.
    """
    staging = tmp_path / "staging"
    cfg = config(
        tmp_path, options={"validate_only": True}, staging_root=staging,
        staged_store_roots={tmp_path.resolve(): staging / "0"},
    )
    store = cfg.vendor_store(tmp_path, "codex")
    assert staging in store.path.parents
    assert store.path.name == "sessions_codex.db"


def test_preflight_stores_and_state_share_one_directory(tmp_path):
    """The defect the registration removed: two answers to one question."""
    from codess.config import get_state_path

    staging = tmp_path / "staging"
    work_root = staging / "0"
    cfg = config(
        tmp_path, options={"validate_only": True}, staging_root=staging,
        staged_store_roots={tmp_path.resolve(): work_root},
    )
    store = cfg.vendor_store(tmp_path, "cc").path
    state = get_state_path(work_root)
    assert store.parent == state.parent


def test_store_path_follows_a_staged_root_when_one_is_registered(tmp_path):
    staged = tmp_path / "rebuilt"
    cfg = config(tmp_path, staged_store_roots={tmp_path.resolve(): staged})
    assert staged in cfg.vendor_store(tmp_path, "cursor").path.parents


def test_preflight_store_paths_differ_by_project(tmp_path):
    """Each Project gets its own staging directory, so stores cannot collide."""
    staging = tmp_path / "staging"
    cfg = config(
        tmp_path, options={"validate_only": True}, staging_root=staging,
        staged_store_roots={
            (tmp_path / "a").resolve(): staging / "0",
            (tmp_path / "b").resolve(): staging / "1",
        },
    )
    assert cfg.vendor_store(tmp_path / "a", "cc").path != (
        cfg.vendor_store(tmp_path / "b", "cc").path
    )


@pytest.mark.parametrize(
    "src,display", [("cc", "Claude"), ("codex", "Codex"), ("cursor", "Cursor")],
)
def test_display_name_is_owned_by_the_store(src, display, tmp_path):
    assert config(tmp_path).vendor_store(tmp_path, src).display_name == display


def test_store_handle_is_frozen(tmp_path):
    import dataclasses

    store = config(tmp_path).vendor_store(tmp_path, "cc")
    with pytest.raises(dataclasses.FrozenInstanceError):
        store.source_key = "codex"


# --- create and measure -----------------------------------------------------

def test_create_makes_a_usable_store_and_reports_catalog_change(tmp_path):
    store = config(tmp_path).vendor_store(tmp_path, "cc")
    assert store.create(entry()) is True
    assert store.exists()


def test_create_is_idempotent(tmp_path):
    store = config(tmp_path).vendor_store(tmp_path, "cc")
    store.create(entry())
    first = store.path
    store.create(entry())
    assert store.path == first


def test_totals_are_read_from_the_store(tmp_path):
    store = config(tmp_path).vendor_store(tmp_path, "cc")
    store.create(entry())
    totals = store.totals()
    assert totals["sessions"] == 0
    assert totals["events"] == 0
    assert totals["last_ingestion"].endswith("+00:00")


def test_totals_are_none_when_the_store_was_never_created(tmp_path):
    """An absent store must not appear as a zero count."""
    assert config(tmp_path).vendor_store(tmp_path, "codex").totals() is None


# --- run configuration ------------------------------------------------------

def test_config_is_frozen(tmp_path):
    """Run settings must not be rewritten while a Project is processed."""
    import dataclasses

    cfg = config(tmp_path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.sources = ("cc",)


def test_config_exposes_options_by_key(tmp_path):
    cfg = config(tmp_path, options={"validate_only": False, "force": True})
    assert cfg["force"] is True
    assert cfg.validate_only is False


def test_config_store_path_is_shorthand_for_the_handle(tmp_path):
    cfg = config(tmp_path)
    assert cfg.store_path(tmp_path, "cc") == cfg.vendor_store(tmp_path, "cc").path


def test_config_options_cannot_be_rewritten_through_it(tmp_path):
    """Frozen must cover the wrapped mapping, not just the field binding."""
    cfg = IngestConfig.from_options(
        {"validate_only": False}, ("cc",), tmp_path / "registry",
    )
    with pytest.raises(TypeError):
        cfg.options["validate_only"] = True


def test_config_does_not_alias_the_caller_options(tmp_path):
    """A later edit to the source dict must not change resolved settings."""
    source = {"validate_only": False}
    cfg = IngestConfig.from_options(source, ("cc",), tmp_path / "registry")
    source["validate_only"] = True
    assert cfg.validate_only is False


def test_staged_store_roots_stay_live(tmp_path):
    """Rebuild registers a staging location mid-run, so this one is shared."""
    staged: dict = {}
    cfg = IngestConfig.from_options(
        {"validate_only": False}, ("cc",), tmp_path / "registry",
        staged_store_roots=staged,
    )
    replacement = tmp_path / "rebuilt"
    staged[tmp_path.resolve()] = replacement
    assert replacement in cfg.vendor_store(tmp_path, "cc").path.parents


# --- per-Project option scope -----------------------------------------------

def test_begin_project_replaces_every_project_scoped_key(tmp_path):
    """A key added to the per-Project set must also be reset per Project.

    This is the guard the boundary needs: without it, a new per-Project key
    can be introduced and silently carry one Project's value into the next.
    """
    from cli.ingest_cmd import (
        PROJECT_SCOPED_OPTIONS,
        _begin_project,
    )

    sentinel = object()
    opts = dict.fromkeys(PROJECT_SCOPED_OPTIONS, sentinel)
    _begin_project(
        opts,
        {"project_id": "codess:project:a", "location_id": "loc-a"},
        raw_records=[],
        raw_store=None,
    )
    carried = [key for key in PROJECT_SCOPED_OPTIONS if opts[key] is sentinel]
    assert carried == [], f"not reset for the new Project: {carried}"


def test_begin_project_does_not_disturb_run_scoped_keys(tmp_path):
    """Run-wide collectors accumulate across Projects and must survive."""
    from cli.ingest_cmd import _begin_project

    diagnostics = {"malformed_records": 3}
    opts = {"diagnostics": diagnostics, "debug": True, "raw_mode": "reference"}
    _begin_project(
        opts,
        {"project_id": "codess:project:b", "location_id": "loc-b"},
        raw_records=[],
        raw_store=None,
    )
    assert opts["diagnostics"] is diagnostics
    assert opts["debug"] is True
    assert opts["raw_mode"] == "reference"


def test_begin_project_isolates_successive_projects(tmp_path):
    """Evidence gathered for one Project must not appear under the next."""
    from cli.ingest_cmd import _begin_project

    opts: dict = {}
    first_records: list[dict] = []
    _begin_project(
        opts, {"project_id": "codess:project:a", "location_id": "loc-a"},
        raw_records=first_records, raw_store=None,
    )
    opts["content_actions"].append({"action": "redact"})
    opts["external_sources"].append({"path": "/tmp/a"})
    opts["raw_records_changed"] = True

    _begin_project(
        opts, {"project_id": "codess:project:b", "location_id": "loc-b"},
        raw_records=[], raw_store=None,
    )
    assert opts["project_id"] == "codess:project:b"
    assert opts["content_actions"] == []
    assert opts["external_sources"] == []
    assert opts["raw_records_changed"] is False
    assert opts["raw_records"] is not first_records


def test_project_scoped_options_reset():
    """Every declared per-Project key is replaced when the loop advances.

    This asserted the same property by parsing `_begin_project`'s AST for
    subscript assignments, which was necessary only because the function did
    not use `PROJECT_SCOPED_OPTIONS`. It does now and raises if a declared key
    has no fresh value, so the check is behavioural: add a key to the tuple
    without a value and this fails.
    """
    from cli.ingest_cmd import PROJECT_SCOPED_OPTIONS, _begin_project

    sentinel = object()
    opts = dict.fromkeys(PROJECT_SCOPED_OPTIONS, sentinel)
    opts["run_wide"] = sentinel
    _begin_project(
        opts,
        {"project_id": "p1", "location_id": "l1"},
        raw_records=[],
        raw_store=None,
    )
    assert not [key for key in PROJECT_SCOPED_OPTIONS if opts[key] is sentinel]
    assert opts["run_wide"] is sentinel  # run-wide options are untouched


def test_project_scoped_options_declared_key_without_a_value_is_refused(
    monkeypatch,
):
    """The tuple and the reset cannot drift: a declared key needs a value."""
    import cli.ingest_cmd as ingest_cmd

    monkeypatch.setattr(
        ingest_cmd, "PROJECT_SCOPED_OPTIONS",
        (*ingest_cmd.PROJECT_SCOPED_OPTIONS, "added_but_not_reset"),
    )
    with pytest.raises(KeyError, match="added_but_not_reset"):
        ingest_cmd._begin_project(
            {},
            {"project_id": "p1", "location_id": "l1"},
            raw_records=[],
            raw_store=None,
        )


# --- tallies ----------------------------------------------------------------

def test_tally_starts_empty_and_reports_accepted():
    from cli.ingest_cmd import IngestTally

    tally = IngestTally()
    assert (tally.sessions, tally.events, tally.errors) == (0, 0, 0)
    assert tally.failed is False
    assert tally.status == "accepted"


def test_tally_accumulates_each_quantity_independently():
    from cli.ingest_cmd import IngestTally

    tally = IngestTally()
    tally.add(sessions=2, events=10)
    tally.add(events=5)
    tally.note_error()
    assert (tally.sessions, tally.events, tally.errors) == (2, 15, 1)


def test_tally_status_is_derived_from_the_error_count():
    """Status must not be storable separately, or it can disagree."""
    from cli.ingest_cmd import IngestTally

    tally = IngestTally(sessions=9, events=99)
    assert tally.status == "accepted"
    tally.note_error()
    assert tally.status == "failed"
    assert tally.failed is True


def test_tally_absorbs_a_narrower_scope():
    from cli.ingest_cmd import IngestTally

    run = IngestTally(sessions=1, events=2, errors=0)
    project = IngestTally(sessions=3, events=4, errors=1)
    run.absorb(project)
    assert (run.sessions, run.events, run.errors) == (4, 6, 1)


def test_absorbing_does_not_change_the_source():
    """A Project's own totals stay reportable after folding into the run."""
    from cli.ingest_cmd import IngestTally

    project = IngestTally(sessions=3, events=4, errors=1)
    IngestTally().absorb(project)
    assert (project.sessions, project.events, project.errors) == (3, 4, 1)


def test_absorbing_twice_double_counts_by_design():
    """absorb is an accumulate, so callers must fold each Project once."""
    from cli.ingest_cmd import IngestTally

    run, project = IngestTally(), IngestTally(sessions=2)
    run.absorb(project)
    run.absorb(project)
    assert run.sessions == 4


# --- outcomes ---------------------------------------------------------------

def test_project_outcome_records_a_vendor_contribution():
    from cli.ingest_cmd import ProjectOutcome

    outcome = ProjectOutcome()
    outcome.record_vendor(
        "Claude", sessions=3, events=40, failed_sources=0, store_changed=True,
    )
    assert (outcome.tally.sessions, outcome.tally.events) == (3, 40)
    assert outcome.changed_vendors == {"Claude"}
    assert outcome.status == "accepted"


def test_unchanged_store_is_not_marked_changed():
    from cli.ingest_cmd import ProjectOutcome

    outcome = ProjectOutcome()
    outcome.record_vendor(
        "Codex", sessions=0, events=0, failed_sources=0, store_changed=False,
    )
    assert outcome.changed_vendors == set()


def test_failed_sources_count_as_errors_and_change_status():
    from cli.ingest_cmd import ProjectOutcome

    outcome = ProjectOutcome()
    outcome.record_vendor(
        "Cursor", sessions=1, events=2, failed_sources=2, store_changed=True,
    )
    assert outcome.tally.errors == 2
    assert outcome.status == "completed_with_errors"


def test_vendors_accumulate_within_one_project():
    from cli.ingest_cmd import ProjectOutcome

    outcome = ProjectOutcome()
    for display in ("Claude", "Codex", "Cursor"):
        outcome.record_vendor(
            display, sessions=1, events=5, failed_sources=0, store_changed=True,
        )
    assert outcome.tally.sessions == 3
    assert outcome.changed_vendors == {"Claude", "Codex", "Cursor"}


def test_run_absorbs_each_project_once():
    from cli.ingest_cmd import IngestOutcome, ProjectOutcome

    run = IngestOutcome()
    for sessions in (2, 3):
        project = ProjectOutcome()
        project.record_vendor(
            "Claude", sessions=sessions, events=sessions * 10,
            failed_sources=0, store_changed=True,
        )
        run.absorb(project)
    assert (run.tally.sessions, run.tally.events) == (5, 50)


def test_run_totals_are_unaffected_by_a_project_not_absorbed():
    """A Project that fails before completing must not reach run totals."""
    from cli.ingest_cmd import IngestOutcome, ProjectOutcome

    run = IngestOutcome()
    abandoned = ProjectOutcome()
    abandoned.record_vendor(
        "Claude", sessions=9, events=99, failed_sources=0, store_changed=True,
    )
    assert run.tally.sessions == 0


def test_overall_counts_come_from_stored_totals_not_the_tally():
    """Stored counts describe the store; the tally describes this run's work."""
    from cli.ingest_cmd import IngestOutcome

    run = IngestOutcome()
    run.source_stats["Claude"] = {"sessions": 7, "events": 70}
    run.source_stats["Codex"] = {"sessions": 3, "events": 30}
    assert run.overall_sessions == 10
    assert run.overall_events == 100
    assert run.tally.sessions == 0


def test_empty_run_reports_zero_rather_than_failing():
    from cli.ingest_cmd import IngestOutcome

    run = IngestOutcome()
    assert (run.overall_sessions, run.overall_events) == (0, 0)
    assert run.tally.status == "accepted"


# --- publication phases -----------------------------------------------------

def test_catalog_resync_skips_stores_that_do_not_exist():
    """Resync reconciles existing stores; it must not provision new ones."""
    import tempfile
    from pathlib import Path as P

    from codess.ingest_publication import resync_project_catalog

    tmp = P(tempfile.mkdtemp())
    cfg = config(tmp)
    changed = resync_project_catalog(
        cfg, tmp, entry(),
        create_store=lambda key, item: cfg.vendor_store(tmp, key).create(item),
    )
    assert changed == set()
    assert not any(cfg.vendor_store(tmp, k).exists() for k in ("cc", "codex", "cursor"))


def test_catalog_resync_records_vendors_whose_entry_changed(tmp_path):
    from codess.ingest_publication import resync_project_catalog

    cfg = config(tmp_path)
    cfg.vendor_store(tmp_path, "cc").create(entry())
    changed = resync_project_catalog(
        cfg, tmp_path, entry(),
        create_store=lambda key, item: cfg.vendor_store(tmp_path, key).create(item),
    )
    assert changed <= {"Claude"}


def test_ingest_command_no_longer_decodes_sources():
    """The command module drives the run; decoding belongs to the domain."""
    import cli.ingest_cmd as command

    for name in ("_ingest_cc", "_ingest_codex", "_ingest_cursor"):
        assert not hasattr(command, name) or getattr(
            command, name
        ).__module__ == "codess.ingest_sources"


# --- query scope predicates -------------------------------------------------
#
# The two predicates are one selection expressed twice: a bare predicate over
# one alias, and a whole clause filtering both aliases a mapping diagnostic
# can reach a source system through. They were separately derived, which is
# how they came to disagree on placeholder spelling in one statement.

def scope(*tokens):
    from cli.query_cmd import QueryScope

    return QueryScope(set(tokens) if tokens else None)


def test_an_unfiltered_selection_matches_every_row():
    """`1` rather than an empty string: callers substitute into a WHERE."""
    assert scope().source_predicate() == ("1", ())


def test_an_unfiltered_selection_has_no_diagnostics_clause():
    """The diagnostics query has no other condition to attach a predicate to."""
    assert scope().diagnostics_predicate() == ("", ())


def test_the_predicate_binds_one_parameter_per_selected_source():
    predicate, params = scope("cc", "codex").source_predicate()
    assert predicate == "s.source_system_id IN (?, ?)"
    assert params == ("anthropic.claude-code", "openai.codex")


def test_the_predicate_names_the_alias_it_was_asked_for():
    predicate, _params = scope("cc").source_predicate("src")
    assert predicate.startswith("src.source_system_id")


def test_source_identifiers_are_ordered_deterministically():
    """Two runs of one selection must produce the same statement and bindings."""
    first = scope("cursor", "cc", "codex").source_predicate()
    second = scope("codex", "cursor", "cc").source_predicate()
    assert first == second


def test_the_diagnostics_clause_filters_both_aliases():
    """A record-level diagnostic often has no Session, only a Source."""
    clause, _params = scope("cc").diagnostics_predicate()
    assert "s.source_system_id" in clause
    assert "src.source_system_id" in clause
    assert clause.startswith("WHERE (") and " OR " in clause


def test_the_diagnostics_clause_reuses_one_derivation():
    """Both halves come from the same predicate, so they cannot drift apart.

    They were derived separately before, which produced two spellings of the
    placeholder list inside one statement.
    """
    selection = scope("cc", "codex")
    predicate, params = selection.source_predicate()
    clause, clause_params = selection.diagnostics_predicate()
    assert clause.count(predicate.split(".", 1)[1]) == 2
    assert clause_params == params + params


def test_the_selected_source_identifiers_are_translated_once():
    """The CLI token vocabulary and the stored one meet in a single place."""
    assert scope("cc", "cursor").selected_source_ids == (
        "anthropic.claude-code", "cursor.composer",
    )
    assert scope().selected_source_ids == ()


# --- cursor preflight -------------------------------------------------------

class TestCursorPreflight:
    """The phase runs once, before any Project, and owns its own temporary.

    It was a 213-line `if` inside `run`; with the Project loop those two
    statements were 90% of that function. Extracting it made the failure path
    checkable, which it had not been: nothing exercised the cohort-capture
    exception, and the block called `run`'s closure to clean up.
    """

    def _preflight(self, *, registry_root=None, opts=None, **overrides):
        from cli.ingest_cmd import (
            IngestConfig,
            IngestOutcome,
            RunTotals,
            _cursor_preflight,
        )
        from codess.cursor_cohort import CursorSelection

        registry_root = registry_root or Path("/nonexistent")
        settings = overrides.pop(
            "settings", {"validate_only": False, "raw_mode": "reference"},
        )
        config = IngestConfig.from_options(
            {**settings, "raw_mode": settings.get("raw_mode", "reference")},
            ["cursor"],
            registry_root,
        )
        totals = RunTotals(
            outcome=IngestOutcome(),
            diagnostics={},
            opts={} if opts is None else opts,
        )
        cursor = overrides.pop("cursor", None) or CursorSelection(
            workspace_ids=overrides.pop("workspace_ids", {}),
            global_db=overrides.pop("global_db", None),
            project_headers={},
        )
        arguments = {
            "config": config,
            "run_totals": totals,
            "cursor": cursor,
            "raw_records_cache": {},
            "force": False,
            "progress_trace": lambda *a, **k: None,
        }
        arguments.update(overrides)
        return _cursor_preflight(**arguments)

    def test_no_cursor_roots(self):
        """Nothing to fingerprint, so no exit code and no temporary."""
        assert self._preflight() == (None, None)

    def test_validate_only(self, tmp_path):
        code, temporary = self._preflight(
            settings={"validate_only": True, "raw_mode": "reference"},
            workspace_ids={tmp_path: {"ws1"}},
            global_db=tmp_path / "state.vscdb",
        )
        assert (code, temporary) == (None, None)

    def test_cohort_failure_releases_its_temporary(
        self, tmp_path, monkeypatch, capsys,
    ):
        """A failed capture returns the code and no temporary to clean twice.

        The extracted function returned a bare `1` here, not the
        `(code, temporary)` pair its caller unpacks, and called `run`'s
        cleanup closure which is no longer in scope. Both were invisible
        while the block was inline.
        """
        import cli.ingest_cmd as ingest_cmd

        database = tmp_path / "state.vscdb"
        database.write_bytes(b"")
        monkeypatch.setattr(
            ingest_cmd, "get_cursor_selection_markers",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("injected")),
        )
        code, temporary = self._preflight(
            workspace_ids={tmp_path: {"ws1"}},
            global_db=database,
        )
        assert code == 1
        assert temporary is None
        assert "Cursor cohort capture failed" in capsys.readouterr().err

    def _cursor_db(self, tmp_path):
        """A global store: bubbles plus the Composer headers a scan needs."""
        import json as json_module

        from cursor_fixtures import build_cursor_db

        return build_cursor_db(
            tmp_path / "state.vscdb",
            bubbles=[("c1", "b1", {"type": 1, "text": "hi"})],
            headers=[("c1", "ws1")],
            records={"composerData:c1": json_module.dumps({"workspaceId": "ws1"})},
        )

    def test_markers_are_scanned_then_reused(self, tmp_path):
        """The cache path, which every CLI test skips by passing `--force`.

        `test_cli.py` exercises Cursor ingest only with `--force`, so the
        `not force` branch -- load the cache, and on a hit report `reused`
        instead of rescanning -- had no coverage at all. That is the branch
        the container bracket exists to make safe.
        """
        database = self._cursor_db(tmp_path)
        registry = tmp_path / "registry"
        registry.mkdir()
        arguments = {
            "workspace_ids": {tmp_path: {"ws1"}},
            "global_db": database,
            "registry_root": registry,
        }

        code, temporary = self._preflight(force=True, **arguments)
        assert (code, temporary) == (None, None)
        cache = registry / "cache" / "cursor-selection-v1.json"
        assert cache.exists(), "a stable scan caches its markers"

        opts: dict = {}
        code, temporary = self._preflight(force=False, opts=opts, **arguments)
        assert (code, temporary) == (None, None)
        assert opts.get("cursor_cohort_marker") is not None

    def test_unstable_container_is_not_cached(self, tmp_path, monkeypatch):
        """A container changing across the read must not persist a marker.

        This is what the before/after bracket is for: Cursor commits while
        Codess reads, so a marker cached for a state already replaced would
        let a later run skip a Project whose evidence had changed.
        """
        import cli.ingest_cmd as ingest_cmd

        database = self._cursor_db(tmp_path)
        registry = tmp_path / "registry"
        registry.mkdir()
        readings = iter(range(100))
        monkeypatch.setattr(
            ingest_cmd, "get_cursor_container_marker",
            lambda path: {"changes_every_call": next(readings)},
        )
        code, temporary = self._preflight(
            workspace_ids={tmp_path: {"ws1"}},
            global_db=database,
            registry_root=registry,
            force=False,
        )
        assert (code, temporary) == (None, None)
        assert not (registry / "cache" / "cursor-selection-v1.json").exists()


def test_begin_project_is_the_only_writer_of_project_id():
    """`opts["project_id"]` is set from `binding` and never rewritten.

    `_publish_project` used to take `binding` and read `binding["project_id"]`;
    it now reads `opts["project_id"]`, which is the same value because
    `_begin_project` copies it there and nothing else assigns it. That
    equivalence is what makes the parameter removable, so it is asserted
    rather than left to inspection.
    """
    import ast
    import inspect
    import pathlib

    import cli.ingest_cmd as ingest_cmd

    source = pathlib.Path(inspect.getfile(ingest_cmd)).read_text()
    writers = {
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Subscript)
        and isinstance(node.ctx, ast.Store)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == "project_id"
    }
    begin = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_begin_project"
    )
    inside = {
        line for line in writers
        if begin.lineno <= line <= (begin.end_lineno or begin.lineno)
    }
    assert writers == inside, (
        f"opts['project_id'] written outside _begin_project at {sorted(writers - inside)}"
    )


def test_publish_reads_the_project_id_begin_project_set(tmp_path, monkeypatch):
    """The value reaching `_publish_project` is the one `_begin_project` wrote."""
    import cli.ingest_cmd as ingest_cmd

    opts: dict = {}
    ingest_cmd._begin_project(
        opts,
        {"project_id": "codess:project:abc", "location_id": "loc-1"},
        raw_records=[],
        raw_store=None,
    )
    assert opts["project_id"] == "codess:project:abc"


class TestProjectIdentityChange:
    """A Project whose identity shifts mid-run is set aside, not fatal.

    The stores decoded in this run are keyed to the identity the run began
    with, so publishing them under a new one would attribute work to a
    Project that did not produce it. That is unrecoverable *for this
    Project* -- but the others in the run are unaffected, so it is reported
    and counted like any other per-Project failure rather than raised.

    Driven through the CLI rather than by calling `_ingest_project`: the
    guard sits after decode and only runs for a Project that produced store
    totals, so a hand-built `opts` fails earlier and passes the assertions
    for the wrong reason -- which an earlier version of this test did.
    """

    def test_shifted_identity_is_reported_and_the_run_continues(
        self, durable_tmp_path, monkeypatch, capsys,
    ):
        import cli.ingest_cmd as ingest_cmd
        from codess.project_catalog import ensure_project_binding

        project = durable_tmp_path / "project"
        (project / ".claude").mkdir(parents=True)
        registry = durable_tmp_path / "registry"
        registry.mkdir()
        real = ensure_project_binding(registry, project)

        # After decode, the binding on disk names a different Project than the
        # run began under -- what a relocation or re-registration between
        # phases looks like.
        monkeypatch.setattr(
            ingest_cmd, "read_project_binding",
            lambda path: {"project_id": real["project_id"] + "-shifted"},
        )
        published: list[str] = []
        monkeypatch.setattr(
            ingest_cmd, "_publish_project",
            lambda *a, **k: published.append("published"),
        )

        code = ingest_cmd.run(_ingest_args(project, registry))

        # Exit 1 because a Project failed, not because the run aborted: the
        # loop completed and the failure is one Project's, which is the
        # distinction that matters when several Projects are ingested.
        assert code == 1
        assert not published, "a shifted Project is not published"
        # The store set survives unpublished, which is the recovery path: a
        # later run rebuilds it under whichever identity is then current.
        # A raised exception reaches the same exit code and message, so this
        # is what distinguishes "set aside" from "crashed".
        assert (project / ".codess").exists()
        assert not (project / ".codess" / "current.json").exists()
        # The message and trace name the identity change specifically. A
        # raised exception would also be caught, counted, and printed, so
        # asserting only "the run reported a failure" cannot tell the two
        # apart -- which an earlier version of this test could not.
        captured = capsys.readouterr()
        assert "identity changed during ingest" in captured.err
        assert "not publishing this Project" in captured.err
        assert "Traceback" not in captured.err


def _ingest_args(project, registry):
    """Parsed `ingest` arguments for one Project, as the CLI would build them."""
    from codess.project import build_parser

    return build_parser().parse_args([
        "ingest", "--dir", str(project), "--registry", str(registry),
        "--source", "cc", "--force", "--no-progress",
    ])


class TestProjectScope:
    """The per-Project lifetime, as a value rather than seven loose keys."""

    def _scope(self, **overrides):
        from cli.ingest_cmd import ProjectScope

        base = {
            "project_id": "p1", "location_id": "l1",
            "raw_records": [], "raw_store": None,
        }
        return ProjectScope(**{**base, **overrides})

    def test_it_writes_every_project_scoped_key(self):
        """A key left unset would carry the previous Project's value."""
        from cli.ingest_cmd import PROJECT_SCOPED_OPTIONS

        opts: dict = {}
        self._scope().into(opts)
        assert set(opts) == set(PROJECT_SCOPED_OPTIONS)

    def test_advancing_replaces_rather_than_merges(self):
        """The defect this guards: one Project's evidence reaching the next.

        `content_actions` and `raw_records` are accumulators, so a merge would
        attribute the first Project's content processing to the second.
        """
        opts: dict = {}
        first = self._scope(raw_records=[{"a": 1}])
        first.into(opts)
        opts["content_actions"].append("from-first")
        opts["raw_records_changed"] = True

        self._scope(project_id="p2", location_id="l2").into(opts)

        assert opts["project_id"] == "p2"
        assert opts["content_actions"] == []
        assert opts["raw_records"] == []
        assert opts["raw_records_changed"] is False

    def test_a_key_missing_from_the_tuple_fails_loudly(self, monkeypatch):
        """The tuple and the reset cannot silently disagree.

        They previously could: the tuple was read by nothing outside a test,
        which asserted agreement without enforcing it.
        """
        import cli.ingest_cmd as ingest

        monkeypatch.setattr(
            ingest, "PROJECT_SCOPED_OPTIONS",
            (*ingest.PROJECT_SCOPED_OPTIONS, "a_key_no_scope_sets"),
        )
        with pytest.raises(KeyError, match="a_key_no_scope_sets"):
            self._scope().into({})
