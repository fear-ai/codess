"""External artifact correlation uses catalog evidence, not ownership guesses."""

from pathlib import Path

from codess.artifact_correlation import (
    AMBIGUOUS_RELATION,
    RELATION,
    correlate_external_artifacts,
)
from codess.store import connect, init_db


def _store(tmp_path: Path):
    path = tmp_path / "store.db"
    init_db(path)
    return connect(path)


def _artifact(conn, path: Path):
    conn.execute(
        "INSERT INTO artifacts(artifact_kind, uri) VALUES ('file', ?)",
        (path.resolve().as_uri(),),
    )


def test_longest_catalog_root_wins(tmp_path):
    conn = _store(tmp_path)
    outer = tmp_path / "work"
    inner = outer / "repo"
    target = inner / "src/file.py"
    _artifact(conn, target)
    catalog = {"projects": [
        {"project_id": "outer", "locations": [{"path": str(outer), "location_id": "l1", "state": "active"}]},
        {"project_id": "inner", "locations": [{"path": str(inner), "location_id": "l2", "state": "active"}]},
    ]}
    result = correlate_external_artifacts(conn, catalog)
    row = conn.execute("SELECT object_id, relation_kind, confidence, evidence FROM correlation_assertions").fetchone()
    assert result == {"external_artifacts": 1, "matched": 1, "ambiguous": 0, "unmatched": 0}
    assert (row["object_id"], row["relation_kind"], row["confidence"]) == ("inner", RELATION, 1.0)
    assert '"relative_path":"src/file.py"' in row["evidence"]
    conn.close()


def test_equal_roots_are_candidates_not_identity_claims(tmp_path):
    conn = _store(tmp_path)
    root = tmp_path / "repo"
    _artifact(conn, root / "file.py")
    catalog = {"projects": [
        {"project_id": project, "locations": [{"path": str(root), "location_id": project, "state": "active"}]}
        for project in ("one", "two")
    ]}
    result = correlate_external_artifacts(conn, catalog)
    rows = conn.execute("SELECT relation_kind, confidence FROM correlation_assertions").fetchall()
    assert result["ambiguous"] == 1
    assert [(row[0], row[1]) for row in rows] == [(AMBIGUOUS_RELATION, .5)] * 2
    conn.close()
