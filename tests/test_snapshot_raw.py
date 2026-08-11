"""Raw evidence capture and immutable snapshot promotion."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import zstandard

from codess.ingest_sources import _record_raw
from codess.raw_store import (
    RawCaptureError, RawStore,
    restore_raw,
    verify_raw,
)
from codess.snapshot import (
    SnapshotError,
    create_snapshot,
    current_raw_records,
    current_stores,
    read_manifest,
    rebuild_manifest,
    recover_current_snapshot,
    snapshot_store_paths,
)
from codess.store import connect, ensure_source, init_db, replace_session_events


def test_jsonl_capture_is_content_addressed_and_recoverable(tmp_path):
    source = tmp_path / "source.jsonl"
    content = b'{"type":"message"}\n'
    source.write_bytes(content)
    raw = RawStore(tmp_path / "raw")
    record = raw.observe(
        source,
        source_system_id="openai.codex",
        storage_format="codex-jsonl",
        mode="capture",
    )
    assert record["availability"] == "captured"
    assert record["capture_method"] == "stable-file-read"
    object_path = raw.resolve(record)
    assert object_path is not None
    assert zstandard.ZstdDecompressor().decompress(object_path.read_bytes()) == content
    assert raw.observe(
        source,
        source_system_id="openai.codex",
        storage_format="codex-jsonl",
        mode="capture",
    )["object_id"] == record["object_id"]


def test_content_addressed_capture_reuses_a_different_valid_zstd_encoding(tmp_path):
    source = tmp_path / "source.jsonl"
    source.write_bytes(b'{"type":"message","payload":"same content"}\n' * 10_000)
    raw = RawStore(tmp_path / "raw")
    first = raw.observe(
        source,
        source_system_id="openai.codex",
        storage_format="codex-jsonl",
        mode="capture",
    )
    object_path = raw.resolve(first)
    replacement = tmp_path / "alternative.zst"
    with source.open("rb") as input_stream, replacement.open("wb") as output_stream:
        zstandard.ZstdCompressor(level=1).copy_stream(input_stream, output_stream)
    object_path.write_bytes(replacement.read_bytes())

    second = raw.observe(
        source,
        source_system_id="openai.codex",
        storage_format="codex-jsonl",
        mode="capture",
    )
    assert second["object_id"] == first["object_id"]
    assert second["stored_sha256"] == verify_raw(
        object_path, second
    )["stored_sha256"]
    assert second["stored_sha256"] != first["stored_sha256"]


def test_raw_capture_streams_without_path_read_bytes(tmp_path, monkeypatch):
    source = tmp_path / "large.jsonl"
    unit = b'{"type":"message","payload":"bounded"}\n'
    with source.open("wb") as stream:
        for _ in range(80_000):
            stream.write(unit)

    def reject_unbounded_read(_path):
        raise AssertionError("raw capture must not call Path.read_bytes")

    monkeypatch.setattr(Path, "read_bytes", reject_unbounded_read)
    raw = RawStore(tmp_path / "raw")
    record = raw.observe(
        source,
        source_system_id="openai.codex",
        storage_format="codex-jsonl",
        mode="capture",
    )

    assert record["uncompressed_size"] == source.stat().st_size
    restored = tmp_path / "restored.jsonl"
    with raw.resolve(record).open("rb") as compressed, restored.open("wb") as output:
        zstandard.ZstdDecompressor().copy_stream(compressed, output)
    assert restored.stat().st_size == source.stat().st_size
    assert restored.open("rb").read(len(unit)) == unit


def test_raw_capture_failure_never_promotes_partial_object(tmp_path, monkeypatch):
    source = tmp_path / "source.jsonl"
    source.write_bytes(b'{"payload":"failure injection"}\n')
    raw = RawStore(tmp_path / "raw")

    def fail_compression(*_args, **_kwargs):
        raise RawCaptureError("injected compression failure")

    monkeypatch.setattr("codess.raw_store._compress_file", fail_compression)
    with pytest.raises(RawCaptureError, match="injected"):
        raw.observe(
            source, source_system_id="openai.codex",
            storage_format="codex-jsonl", mode="capture",
        )
    assert not list((raw.root / ".staging").glob("*"))
    assert not list((raw.root / "objects").rglob("*.zst"))


def test_raw_verification_streams_without_path_read_bytes(tmp_path, monkeypatch):
    source = tmp_path / "large.jsonl"
    unit = b'{"type":"message","payload":"bounded verification"}\n'
    with source.open("wb") as stream:
        for _ in range(80_000):
            stream.write(unit)
    raw = RawStore(tmp_path / "raw")
    record = raw.observe(
        source,
        source_system_id="openai.codex",
        storage_format="codex-jsonl",
        mode="capture",
    )

    def reject_unbounded_read(_path):
        raise AssertionError("raw verification must not call Path.read_bytes")

    monkeypatch.setattr(Path, "read_bytes", reject_unbounded_read)
    observed = verify_raw(raw.resolve(record), record)

    assert observed["stored_sha256"] == record["stored_sha256"]
    assert observed["stored_size"] == record["stored_size"]
    assert observed["object_id"] == record["object_id"]
    assert observed["uncompressed_size"] == record["uncompressed_size"]


def test_raw_restore_streams_and_verifies_before_promotion(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE payload(value BLOB)")
        conn.executemany(
            "INSERT INTO payload VALUES (?)",
            [(b"bounded materialization",)] * 100_000,
        )
    raw = RawStore(tmp_path / "raw")
    record = raw.observe(
        source,
        source_system_id="cursor.composer",
        storage_format="cursor-sqlite",
        mode="capture",
    )

    def reject_unbounded_read(_path):
        raise AssertionError("raw restore must not call Path.read_bytes")

    monkeypatch.setattr(Path, "read_bytes", reject_unbounded_read)
    target = tmp_path / "restored.db"
    observed = restore_raw(raw.resolve(record), target, record)
    assert observed["object_id"] == record["object_id"]
    assert target.stat().st_size == source.stat().st_size


def test_related_external_content_has_stable_identity_and_parent_link(tmp_path):
    sidecar = tmp_path / "tool-results" / "result.txt"
    sidecar.parent.mkdir()
    sidecar.write_text("full external output", encoding="utf-8")
    raw = RawStore(tmp_path / "raw")
    record = raw.observe_related(
        sidecar,
        source_system_id="anthropic.claude-code",
        storage_format="text/plain",
        mode="capture",
        parent_source_locator="/source/session.jsonl",
        relation_kind="persisted_tool_result",
    )
    assert record["record_type"] == "related_content_revision"
    assert record["record_id"].startswith("rawrel:sha256:")
    assert record["parent_source_locator"] == "/source/session.jsonl"
    assert record["relation_kind"] == "persisted_tool_result"
    assert zstandard.ZstdDecompressor().decompress(
        raw.resolve(record).read_bytes()
    ) == b"full external output"


def test_raw_capture_updates_normalized_source_provenance(tmp_path):
    source = tmp_path / "session.jsonl"
    source.write_text('{"type":"user"}\n', encoding="utf-8")
    store = tmp_path / "store.db"
    init_db(store)
    conn = connect(store)
    ensure_source(conn, source="Claude", source_file=str(source))
    records = []
    _record_raw(
        {
            "raw_store": RawStore(tmp_path / "raw"),
            "raw_records": records,
            "raw_mode": "capture",
        },
        source,
        "Claude",
        conn,
    )
    row = conn.execute(
        "SELECT availability, capture_method, consistency, content_sha256 FROM sources"
    ).fetchone()
    assert tuple(row[:3]) == ("captured", "stable-file-read", "stable")
    assert row[3] == records[0]["object_id"].removeprefix("sha256:")
    conn.close()


def test_cursor_capture_uses_consistent_sqlite_backup(tmp_path):
    source = tmp_path / "state.vscdb"
    writer = sqlite3.connect(source)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE items(value TEXT)")
    writer.execute("INSERT INTO items VALUES ('captured')")
    writer.commit()
    observed_source_stat = source.stat()
    raw = RawStore(tmp_path / "raw")
    working_copy = tmp_path / "cohort.db"
    progress_events = []
    record = raw.observe(
        source,
        source_system_id="cursor.composer",
        storage_format="cursor-sqlite",
        mode="capture",
        working_target=working_copy,
        progress=lambda event, **fields: progress_events.append((event, fields)),
    )
    writer.close()
    assert record["capture_method"] == "sqlite-backup"
    assert record["source_mtime_ns"] == observed_source_stat.st_mtime_ns
    assert record["source_size"] == observed_source_stat.st_size
    assert [event for event, _fields in progress_events] == [
        "raw.sqlite_backup.start",
        "raw.sqlite_backup.done",
        "raw.compress.start",
        "raw.compress.done",
        "raw.object_promoted",
        "raw.working_file.written",
    ]
    with sqlite3.connect(
        working_copy.resolve().as_uri() + "?mode=ro", uri=True
    ) as conn:
        assert conn.execute("SELECT value FROM items").fetchone()[0] == "captured"
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    data = zstandard.ZstdDecompressor().decompress(raw.resolve(record).read_bytes())
    restored = tmp_path / "restored.db"
    restored.write_bytes(data)
    conn = sqlite3.connect(restored.resolve().as_uri() + "?mode=ro", uri=True)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert conn.execute("SELECT value FROM items").fetchone()[0] == "captured"
    conn.close()


def test_snapshot_is_validated_promoted_and_sealable(tmp_path):
    project = tmp_path / "project"
    store = project / ".codess" / "sessions_codex.db"
    source = tmp_path / "source.jsonl"
    source.write_text('{"x":1}\n', encoding="utf-8")
    init_db(store)
    conn = connect(store)
    replace_session_events(
        conn,
        {"id": "s1", "source": "Codex", "type": "Code", "project_path": str(project)},
        [{"session_id": "s1", "event_id": "1", "event_type": "user_message", "subtype": "prompt", "role": "user", "content": "hello", "source_file": str(source)}],
        session_id="s1",
    )
    conn.commit()
    conn.close()
    raw = RawStore(tmp_path / "raw")
    record = raw.observe(
        source,
        source_system_id="openai.codex",
        storage_format="codex-jsonl",
        mode="capture",
    )
    snapshot = create_snapshot(project, [store], [record], raw_store=raw, seal=True)
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["software_version"]
    assert manifest["runtime"]["sqlite"]
    assert len(manifest["build_policy_sha256"]) == 64
    assert (snapshot / "raw" / record["object_relpath"]).exists()
    resolved = current_stores(project)
    assert len(resolved) == 1
    check = sqlite3.connect(resolved[0])
    assert check.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    meta = dict(check.execute("SELECT key, value FROM store_meta"))
    check.close()
    assert meta["snapshot_id"] == manifest["snapshot_id"]

    successor = create_snapshot(project, [store], [record], raw_store=raw)
    successor_manifest = json.loads(
        (successor / "manifest.json").read_text(encoding="utf-8")
    )
    assert successor_manifest["parent_snapshot_id"] == manifest["snapshot_id"]

    pointer = project / ".codess" / "current.json"
    current = json.loads(pointer.read_text(encoding="utf-8"))
    current["manifest_sha256"] = "0" * 64
    pointer.write_text(json.dumps(current), encoding="utf-8")
    with pytest.raises(SnapshotError):
        current_stores(project)


def test_partial_refresh_carries_current_raw_records(tmp_path):
    project = tmp_path / "project"
    store = project / ".codess" / "sessions_cursor.db"
    init_db(store)
    raw = RawStore(tmp_path / "raw")
    source = tmp_path / "session.jsonl"
    source.write_bytes(b"one")
    first = raw.observe(
        source,
        source_system_id="openai.codex",
        storage_format="codex-jsonl",
        mode="capture",
    )
    create_snapshot(project, [store], [first], raw_store=raw)
    assert current_raw_records(project) == [first]


def test_current_raw_records_rejects_unparseable_raw_manifest(tmp_path):
    """Malformed content in an existing snapshot still errors, without a
    per-read hash re-check: manifest.json and raw-manifest.jsonl are
    write-once (see snapshot.py::read_manifest), so nothing in this module
    re-verifies their content against a recorded hash on every read anymore
    -- corruption is caught only if it also happens to make the content
    unparseable, not detected as a distinct "tampered" condition."""
    project = tmp_path / "project"
    store = project / ".codess" / "sessions_cursor.db"
    init_db(store)
    raw = RawStore(tmp_path / "raw")
    source = tmp_path / "session.jsonl"
    source.write_bytes(b"one")
    first = raw.observe(
        source,
        source_system_id="openai.codex",
        storage_format="codex-jsonl",
        mode="capture",
    )
    create_snapshot(project, [store], [first], raw_store=raw)

    raw_manifest = next((project / ".codess" / "snapshots").glob("*/raw-manifest.jsonl"))
    raw_manifest.write_text("not valid json\n", encoding="utf-8")
    with pytest.raises(SnapshotError, match="cannot read current raw records"):
        current_raw_records(project)


def test_snapshot_preserves_older_store_format_identity(tmp_path):
    project = tmp_path / "project"
    store = project / ".codess" / "sessions_cursor.db"
    init_db(store)
    with sqlite3.connect(store) as conn:
        conn.execute("PRAGMA user_version = 3")
        conn.execute(
            "UPDATE store_meta SET value='3' WHERE key='format_version'"
        )
        conn.execute(
            "UPDATE store_meta SET value='legacy-package' WHERE key='package_digest'"
        )
    raw = RawStore(tmp_path / "raw")
    source = tmp_path / "session.jsonl"
    source.write_bytes(b"legacy")
    record = raw.observe(
        source,
        source_system_id="openai.codex",
        storage_format="codex-jsonl",
        mode="capture",
    )
    snapshot = create_snapshot(project, [store], [record], raw_store=raw)
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    assert "coschema3" in snapshot.name
    assert manifest["format_version"] == 3
    assert manifest["package_digest"] == "legacy-package"


def test_snapshot_build_failure_does_not_replace_current_pointer(tmp_path, monkeypatch):
    project = tmp_path / "project"
    store = project / ".codess" / "sessions_codex.db"
    init_db(store)
    raw = RawStore(tmp_path / "raw")
    first = create_snapshot(project, [store], [], raw_store=raw)
    pointer = project / ".codess" / "current.json"
    before = pointer.read_bytes()
    snapshots_before = {path.name for path in first.parent.iterdir()}

    def fail_backup(*_args, **_kwargs):
        raise RuntimeError("injected backup failure")

    monkeypatch.setattr("codess.snapshot._backup_store", fail_backup)
    with pytest.raises(RuntimeError, match="injected"):
        create_snapshot(project, [store], [], raw_store=raw)
    assert pointer.read_bytes() == before
    assert {path.name for path in first.parent.iterdir()} == snapshots_before


def test_snapshot_rejects_raw_manifest_tamper(tmp_path):
    project = tmp_path / "project"
    store = project / ".codess" / "sessions_cc.db"
    init_db(store)
    raw = RawStore(tmp_path / "raw")
    source = tmp_path / "session.jsonl"
    source.write_text('{"type":"user"}\n', encoding="utf-8")
    record = raw.observe(
        source,
        source_system_id="claude-code",
        storage_format="jsonl",
        mode="capture",
    )
    snapshot = create_snapshot(project, [store], [record], raw_store=raw)
    (snapshot / "raw-manifest.jsonl").write_text("tamper\n", encoding="utf-8")
    with pytest.raises(SnapshotError, match="raw manifest hash mismatch"):
        current_stores(project)


def _seed_one_snapshot(tmp_path, name="session.jsonl"):
    project = tmp_path / "project"
    store = project / ".codess" / "sessions_cursor.db"
    init_db(store)
    raw = RawStore(tmp_path / "raw")
    source = tmp_path / name
    source.write_bytes(b"one")
    record = raw.observe(
        source,
        source_system_id="openai.codex",
        storage_format="codex-jsonl",
        mode="capture",
    )
    create_snapshot(project, [store], [record], raw_store=raw)
    return project


def test_recover_current_snapshot_rebuilds_a_deleted_pointer(tmp_path):
    project = _seed_one_snapshot(tmp_path)
    (project / ".codess" / "current.json").unlink()
    assert current_stores(project) == []

    result = recover_current_snapshot(project)
    assert result["snapshot_id"]
    assert len(current_stores(project)) == 1


def test_recover_current_snapshot_rebuilds_a_corrupted_pointer(tmp_path):
    project = _seed_one_snapshot(tmp_path)
    (project / ".codess" / "current.json").write_text("not json{{{", encoding="utf-8")
    with pytest.raises(SnapshotError):
        current_stores(project)

    result = recover_current_snapshot(project)
    assert result["snapshot_id"]
    assert len(current_stores(project)) == 1


def test_recover_current_snapshot_skips_a_tampered_newest_snapshot(tmp_path):
    project = _seed_one_snapshot(tmp_path, name="first.jsonl")
    assert len(current_stores(project)) == 1  # sanity: resolves before tamper

    store = project / ".codess" / "sessions_cursor.db"
    raw = RawStore(tmp_path / "raw")
    source = tmp_path / "second.jsonl"
    source.write_bytes(b"two")
    record = raw.observe(
        source, source_system_id="openai.codex", storage_format="codex-jsonl",
        mode="capture",
    )
    newest = create_snapshot(project, [store], [record], raw_store=raw)
    (newest / "raw-manifest.jsonl").write_text("tamper\n", encoding="utf-8")

    result = recover_current_snapshot(project)
    assert result["snapshot_id"] != newest.name
    assert len(current_stores(project)) == 1


def test_recover_current_snapshot_raises_when_nothing_is_retained(tmp_path):
    project = tmp_path / "project"
    (project / ".codess").mkdir(parents=True)
    with pytest.raises(SnapshotError, match="no retained snapshots"):
        recover_current_snapshot(project)


def test_read_manifest_falls_back_to_backup_copy(tmp_path):
    project = _seed_one_snapshot(tmp_path)
    snapshot_dir = next((project / ".codess" / "snapshots").iterdir())
    original = read_manifest(snapshot_dir)
    (snapshot_dir / "manifest.json").unlink()
    assert read_manifest(snapshot_dir) == original


def test_read_manifest_raises_when_both_copies_are_missing(tmp_path):
    project = _seed_one_snapshot(tmp_path)
    snapshot_dir = next((project / ".codess" / "snapshots").iterdir())
    (snapshot_dir / "manifest.json").unlink()
    (snapshot_dir / "manifest.json.bak").unlink()
    with pytest.raises(SnapshotError, match="manifest.json missing"):
        read_manifest(snapshot_dir)


def test_rebuild_manifest_reproduces_recoverable_fields(tmp_path):
    project = _seed_one_snapshot(tmp_path)
    snapshot_dir = next((project / ".codess" / "snapshots").iterdir())
    original = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    (snapshot_dir / "manifest.json").unlink()
    (snapshot_dir / "manifest.json.bak").unlink()

    rebuilt = rebuild_manifest(snapshot_dir)
    assert rebuilt["reconstructed"] is True
    assert rebuilt["snapshot_id"] == original["snapshot_id"]
    assert rebuilt["format_version"] == original["format_version"]
    assert rebuilt["package_digest"] == original["package_digest"]
    assert rebuilt["raw_manifest_sha256"] == original["raw_manifest_sha256"]
    assert rebuilt["stores"] == original["stores"]
    assert rebuilt["parent_snapshot_id"] is None
    assert rebuilt["build_policy"] is None


def test_rebuild_manifest_requires_a_surviving_store_database(tmp_path):
    project = _seed_one_snapshot(tmp_path)
    snapshot_dir = next((project / ".codess" / "snapshots").iterdir())
    for db in snapshot_dir.glob("*.db"):
        db.unlink()
    with pytest.raises(SnapshotError, match="store database"):
        rebuild_manifest(snapshot_dir)


def test_rebuild_manifest_requires_raw_manifest_jsonl(tmp_path):
    project = _seed_one_snapshot(tmp_path)
    snapshot_dir = next((project / ".codess" / "snapshots").iterdir())
    (snapshot_dir / "raw-manifest.jsonl").unlink()
    with pytest.raises(SnapshotError, match="raw-manifest.jsonl"):
        rebuild_manifest(snapshot_dir)


def test_retained_snapshot_requires_exact_package_unless_explicitly_compatible(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    store = project / ".codess" / "sessions_codex.db"
    init_db(store)
    raw = RawStore(tmp_path / "raw")
    source = tmp_path / "session.jsonl"
    source.write_text('{"type":"user"}\n', encoding="utf-8")
    record = raw.observe(
        source,
        source_system_id="openai.codex",
        storage_format="codex-jsonl",
        mode="capture",
    )
    snapshot = create_snapshot(project, [store], [record], raw_store=raw)
    snapshot_id = snapshot.name
    assert snapshot_store_paths(project, snapshot_id)

    monkeypatch.setattr("codess.snapshot.verify_package", lambda: "f" * 64)
    with pytest.raises(SnapshotError, match="package digest mismatch"):
        snapshot_store_paths(project, snapshot_id)
    assert snapshot_store_paths(
        project, snapshot_id, allow_package_mismatch=True
    )
