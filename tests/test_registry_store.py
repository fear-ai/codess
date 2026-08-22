"""Unit tests for registry merge helpers."""

import argparse
import json

from codess.registry_store import (
    merge_ingest_sources,
    merge_scan_rows,
    never_ingested_entries,
    project_lifecycle,
    save_registry_data,
    update_project_entry,
)


def test_merge_preserves_scan_when_ingest(tmp_path):
    """Ingest merge does not drop prior scan block."""
    proj = str((tmp_path / "work" / "proj").resolve())

    def seed(e):
        merge_scan_rows(e, [{"vendor": "cc", "sess": 1, "mb": 0.1, "span_weeks": 1}])

    update_project_entry(tmp_path, proj, seed)

    def ingest(e):
        merge_ingest_sources(e, {"Claude": {"sessions": 2, "events": 3}})

    update_project_entry(tmp_path, proj, ingest)

    import json

    from codess.config import get_stats_path

    raw = json.loads(get_stats_path(tmp_path).read_text())
    ent = next(p for p in raw["projects"] if p["path"] == proj)
    assert "scan" in ent
    assert ent["sources"]["Claude"]["sessions"] == 2


class TestRegistryRetention:
    """The registry drops entries whose Project is gone.

    It gained one per Project ever scanned and pruned none, so a suite run
    that scans temporary directories enlarged a developer's registry
    permanently: 1,455 entries observed, of which 1,424 were vanished
    temporary paths.
    """

    def _registry(self, tmp_path, paths):
        from codess.registry_store import save_registry_data
        save_registry_data(tmp_path, {"projects": [{"path": str(p)} for p in paths]})
        return tmp_path

    def test_a_missing_path_is_reported_and_a_live_one_is_not(self, tmp_path):
        from codess.registry_store import stale_entries

        live = tmp_path / "live"
        live.mkdir()
        registry = self._registry(tmp_path / "reg", [live, tmp_path / "gone"])
        stale = stale_entries(registry)
        assert [e["path"] for e in stale] == [str(tmp_path / "gone")]

    def test_a_dry_run_reports_without_writing(self, tmp_path):
        from codess.registry_store import load_registry_data, prune_stale_entries

        registry = self._registry(tmp_path / "reg", [tmp_path / "gone"])
        result = prune_stale_entries(registry, dry_run=True)
        assert (result["removed"], result["retained"]) == (1, 0)
        assert len(load_registry_data(registry)["projects"]) == 1, (
            "a dry run must not modify the registry"
        )

    def test_applying_removes_only_the_missing(self, tmp_path):
        from codess.registry_store import load_registry_data, prune_stale_entries

        live = tmp_path / "live"
        live.mkdir()
        registry = self._registry(tmp_path / "reg", [live, tmp_path / "gone"])
        result = prune_stale_entries(registry)
        assert (result["removed"], result["retained"]) == (1, 1)
        remaining = [e["path"] for e in load_registry_data(registry)["projects"]]
        assert remaining == [str(live)]

    def test_the_reported_path_list_is_bounded(self, tmp_path):
        """An accumulated registry holds over a thousand stale entries."""
        from codess.registry_store import REPORTED_PATH_SAMPLE, prune_stale_entries

        registry = self._registry(
            tmp_path / "reg", [tmp_path / f"gone{n}" for n in range(60)]
        )
        result = prune_stale_entries(registry, dry_run=True)
        assert len(result["removed_paths"]) == REPORTED_PATH_SAMPLE
        assert result["removed_paths_truncated"] == 60 - REPORTED_PATH_SAMPLE
        assert result["removed"] == 60

    def test_an_empty_registry_is_not_an_error(self, tmp_path):
        from codess.registry_store import prune_stale_entries

        result = prune_stale_entries(tmp_path / "empty", dry_run=True)
        assert (result["examined"], result["removed"]) == (0, 0)


class TestNeverIngested:
    """A Project scanned and never ingested is reported.

    Scan records every Project it observes; ingest publishes only what it is
    told to read; the catalog holds what ingest published. So a scanned-only
    Project is absent from the catalog, and any enumeration drawn from there
    inherits the omission with no way to notice. Eight Projects on one machine
    were in that state, including one holding 68,655 Events.
    """

    def test_a_scanned_project_is_reported(self, tmp_path):
        project = tmp_path / "live"
        project.mkdir()
        save_registry_data(tmp_path, {"projects": [
            {"path": str(project), "last_scan": "2026-08-17T00:00:00+00:00"},
        ]})
        assert [e["path"] for e in never_ingested_entries(tmp_path)] == [str(project)]

    def test_an_ingested_project_is_not_reported(self, tmp_path):
        project = tmp_path / "live"
        project.mkdir()
        save_registry_data(tmp_path, {"projects": [
            {
                "path": str(project),
                "last_scan": "2026-08-17T00:00:00+00:00",
                "last_ingestion": "2026-08-20T00:00:00+00:00",
            },
        ]})
        assert never_ingested_entries(tmp_path) == []

    def test_a_vanished_path_is_not_reported(self, tmp_path):
        """That is `stale_entries`'s condition; it cannot be ingested anyway."""
        save_registry_data(tmp_path, {"projects": [
            {"path": str(tmp_path / "gone"), "last_scan": "2026-08-17T00:00:00+00:00"},
        ]})
        assert never_ingested_entries(tmp_path) == []

    def test_an_empty_registry_reports_nothing(self, tmp_path):
        assert never_ingested_entries(tmp_path) == []


class TestProjectLifecycle:
    """Every Project this machine has known, reconciled from two records.

    `ingested_projects.json` records what scan saw and `projects.json` what
    ingest published, and nothing joined them: a Project scanned and never
    ingested was absent from the catalog entirely, and a catalogued path whose
    directory had been removed stayed indefinitely. The state is derived rather
    than stored, so no fifth writer can disagree with the four facts under it.
    """

    def _registry(self, tmp_path, entries):
        save_registry_data(tmp_path, {"projects": entries})
        return tmp_path

    def test_an_ingested_project(self, tmp_path):
        project = tmp_path / "live"
        project.mkdir()
        store = self._registry(tmp_path, [
            {"path": str(project), "last_scan": "2026-08-01T00:00:00+00:00",
             "last_ingestion": "2026-08-02T00:00:00+00:00"},
        ])
        assert project_lifecycle(store)[0]["state"] == "ingested"

    def test_a_scanned_project_is_not_ingested(self, tmp_path):
        project = tmp_path / "live"
        project.mkdir()
        store = self._registry(tmp_path, [
            {"path": str(project), "last_scan": "2026-08-01T00:00:00+00:00"},
        ])
        assert project_lifecycle(store)[0]["state"] == "scanned"

    def test_a_removed_directory(self, tmp_path):
        """A Project that has left the machine stays a record."""
        store = self._registry(tmp_path, [
            {"path": str(tmp_path / "gone"),
             "last_scan": "2026-08-01T00:00:00+00:00",
             "last_ingestion": "2026-08-02T00:00:00+00:00"},
        ])
        row = project_lifecycle(store)[0]
        assert row["state"] == "removed"
        assert row["path_exists"] is False

    def test_a_moved_project(self, tmp_path):
        """A retired location whose Project lives elsewhere is `moved`.

        Reporting it as `removed` would say the work was lost when the catalog
        records exactly where it went, and would keep reporting it after the
        operator had already answered.
        """
        old = tmp_path / "old"
        new = tmp_path / "new"
        new.mkdir()
        store = self._registry(tmp_path, [
            {"path": str(old), "last_ingestion": "2026-08-01T00:00:00+00:00"},
        ])
        catalog = {"projects": [{
            "project_id": "codess:project:x",
            "locations": [
                {"path": str(new), "state": "active"},
                {"path": str(old), "state": "retired", "path_obsolete": True},
            ],
        }]}
        assert project_lifecycle(store, catalog)[0]["state"] == "moved"

    def test_a_removed_project_is_not_moved(self, tmp_path):
        """Without a retirement, a vanished path is still `removed`."""
        store = self._registry(tmp_path, [
            {"path": str(tmp_path / "gone"),
             "last_ingestion": "2026-08-01T00:00:00+00:00"},
        ])
        assert project_lifecycle(store)[0]["state"] == "removed"

    def test_a_disposition_outranks_the_other_facts(self, tmp_path):
        """A reviewed retirement is the answer even for a live, ingested path."""
        project = tmp_path / "live"
        project.mkdir()
        store = self._registry(tmp_path, [
            {"path": str(project), "last_scan": "2026-08-01T00:00:00+00:00",
             "last_ingestion": "2026-08-02T00:00:00+00:00"},
        ])
        catalog = {"projects": [{
            "project_id": "codess:project:x",
            "locations": [{"path": str(project)}],
            "catalog_disposition": {"state": "excluded"},
        }]}
        row = project_lifecycle(store, catalog)[0]
        # `retired` rather than `superseded`: the operator excluded this
        # Project. A linked worktree reports `worktree`, which is an ordinary
        # live sibling rather than an answered duplicate.
        assert row["state"] == "retired"
        assert row["project_id"] == "codess:project:x"

    def test_a_worktree_is_not_retired(self, tmp_path):
        """A linked worktree is a live sibling, not an answered duplicate."""
        project = tmp_path / "live"
        project.mkdir()
        store = self._registry(tmp_path, [
            {"path": str(project), "last_ingestion": "2026-08-02T00:00:00+00:00"},
        ])
        catalog = {"projects": [{
            "project_id": "codess:project:x",
            "locations": [{"path": str(project)}],
            "catalog_disposition": {"state": "worktree"},
        }]}
        assert project_lifecycle(store, catalog)[0]["state"] == "worktree"

    def test_a_second_live_location_is_a_copy(self, tmp_path):
        """One identity in two live places is a copy, not two Projects.

        A directory copied or restored beside its original carries the same
        binding, so both paths claim one `project_id`. Naming the second a
        `copy` is what lets a later step decline to re-ingest it.
        """
        original = tmp_path / "original"
        duplicate = tmp_path / "duplicate"
        original.mkdir()
        duplicate.mkdir()
        store = self._registry(tmp_path, [
            {"path": str(original), "last_ingestion": "2026-08-01T00:00:00+00:00"},
            {"path": str(duplicate), "last_ingestion": "2026-08-02T00:00:00+00:00"},
        ])
        catalog = {"projects": [{
            "project_id": "codess:project:x",
            "locations": [{"path": str(original)}, {"path": str(duplicate)}],
        }]}
        rows = {row["path"]: row for row in project_lifecycle(store, catalog)}
        assert rows[str(original)]["state"] == "ingested"
        assert rows[str(duplicate)]["state"] == "copy"
        assert rows[str(duplicate)]["copy_of"] == str(original)

    def test_a_transition_records_what_it_left(self, tmp_path):
        """An initial state has no `previous_state`; a change does."""
        project = tmp_path / "live"
        project.mkdir()
        store = self._registry(tmp_path, [
            {"path": str(project), "last_ingestion": "2026-08-02T00:00:00+00:00"},
        ])
        catalog = {"projects": [{
            "project_id": "codess:project:x",
            "locations": [{"path": str(project)}],
            "catalog_disposition": {
                "state": "excluded",
                "updated_at": "2026-08-20T00:00:00+00:00",
                "previous_state": "candidate",
            },
        }]}
        row = project_lifecycle(store, catalog)[0]
        assert row["state_since"] == "2026-08-20T00:00:00+00:00"
        assert row["previous_state"] == "candidate"

    def test_ordered_by_last_activity(self, tmp_path):
        older = tmp_path / "older"
        newer = tmp_path / "newer"
        older.mkdir()
        newer.mkdir()
        store = self._registry(tmp_path, [
            {"path": str(older), "last_ingestion": "2026-01-01T00:00:00+00:00"},
            {"path": str(newer), "last_ingestion": "2026-08-01T00:00:00+00:00"},
        ])
        assert [row["path"] for row in project_lifecycle(store)] == [
            str(newer), str(older),
        ]


class TestLifecycleCommand:
    """`catalog lifecycle` reports the reconciled view and flags scanned-only.

    The exit status is the part worth pinning: a Project scanned and never
    ingested is the one state an operator would act on rather than merely read,
    and it is invisible to every list drawn from the catalog.
    """

    def test_a_scanned_project_exits_nonzero(self, tmp_path, capsys):
        from cli.admin_cmd import _catalog_lifecycle
        project = tmp_path / "live"
        project.mkdir()
        save_registry_data(tmp_path, {"projects": [
            {"path": str(project), "last_scan": "2026-08-01T00:00:00+00:00"},
        ]})
        args = argparse.Namespace(store_root=tmp_path, state=[])
        assert _catalog_lifecycle(args) == 1
        report = json.loads(capsys.readouterr().out)
        assert report["summary"] == {"scanned": 1}

    def test_an_ingested_project_exits_zero(self, tmp_path, capsys):
        from cli.admin_cmd import _catalog_lifecycle
        project = tmp_path / "live"
        project.mkdir()
        save_registry_data(tmp_path, {"projects": [
            {"path": str(project), "last_ingestion": "2026-08-02T00:00:00+00:00"},
        ]})
        args = argparse.Namespace(store_root=tmp_path, state=[])
        assert _catalog_lifecycle(args) == 0
        assert json.loads(capsys.readouterr().out)["summary"] == {"ingested": 1}

    def test_state_filter_selects(self, tmp_path, capsys):
        from cli.admin_cmd import _catalog_lifecycle
        live = tmp_path / "live"
        live.mkdir()
        save_registry_data(tmp_path, {"projects": [
            {"path": str(live), "last_ingestion": "2026-08-02T00:00:00+00:00"},
            {"path": str(tmp_path / "gone"), "last_scan": "2026-08-01T00:00:00+00:00"},
        ]})
        args = argparse.Namespace(store_root=tmp_path, state=["removed"])
        assert _catalog_lifecycle(args) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["summary"] == {"removed": 1}
