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

    from codess.config import get_stats_path
    import json

    raw = json.loads(get_stats_path(tmp_path).read_text())
    ent = next(p for p in raw["projects"] if p["path"] == proj)
    assert "scan" in ent
    assert ent["sources"]["Claude"]["sessions"] == 2
