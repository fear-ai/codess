"""Unit tests for registry merge helpers."""

from codess.registry_store import merge_ingest_sources, merge_scan_rows, update_project_entry


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
    """The registry drops entries whose Project is gone (W28).

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
