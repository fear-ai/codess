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
    staging = tmp_path / "staging"
    cfg = config(tmp_path, options={"validate_only": True}, staging_root=staging)
    store = cfg.vendor_store(tmp_path, "codex")
    assert staging in store.path.parents
    assert store.path.name == "sessions_codex.db"


def test_store_path_follows_a_staged_root_when_one_is_registered(tmp_path):
    staged = tmp_path / "rebuilt"
    cfg = config(tmp_path, staged_store_roots={tmp_path.resolve(): staged})
    assert staged in cfg.vendor_store(tmp_path, "cursor").path.parents


def test_preflight_store_paths_differ_by_project(tmp_path):
    cfg = config(
        tmp_path, options={"validate_only": True}, staging_root=tmp_path / "staging",
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


def test_project_scoped_options_list_matches_what_is_reset():
    """The declared key set and the reset must not drift apart."""
    import ast
    import inspect

    from cli.ingest_cmd import PROJECT_SCOPED_OPTIONS, _begin_project

    tree = ast.parse(inspect.getsource(_begin_project))
    written = {
        node.slice.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.ctx, ast.Store)
        and isinstance(node.slice, ast.Constant)
    }
    assert written == set(PROJECT_SCOPED_OPTIONS)


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
    from codess.ingest_publication import resync_project_catalog

    import tempfile
    from pathlib import Path as P

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
