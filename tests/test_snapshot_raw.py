"""Raw evidence capture and immutable snapshot promotion."""

from __future__ import annotations

import json
import sqlite3

import pytest
import zstandard

from cli.ingest_cmd import _record_raw
from codess.raw_store import RawStore
from codess.snapshot import SnapshotError, create_snapshot, current_store_paths
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
    assert tuple(row[:3]) == ("captured", "stable-file-read", "stable-stat")
    assert row[3] == records[0]["object_id"].removeprefix("sha256:")
    conn.close()


def test_cursor_capture_uses_consistent_sqlite_backup(tmp_path):
    source = tmp_path / "state.vscdb"
    writer = sqlite3.connect(source)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE items(value TEXT)")
    writer.execute("INSERT INTO items VALUES ('captured')")
    writer.commit()
    raw = RawStore(tmp_path / "raw")
    record = raw.observe(
        source,
        source_system_id="cursor.composer",
        storage_format="cursor-sqlite",
        mode="capture",
    )
    writer.close()
    assert record["capture_method"] == "sqlite-backup"
    data = zstandard.ZstdDecompressor().decompress(raw.resolve(record).read_bytes())
    restored = tmp_path / "restored.db"
    restored.write_bytes(data)
    conn = sqlite3.connect(restored)
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
    resolved = current_store_paths(project)
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
        current_store_paths(project)


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
        current_store_paths(project)
