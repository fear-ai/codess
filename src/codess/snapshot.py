"""Immutable CoSchema snapshot build, validation, and atomic promotion."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from codess import __version__
from codess.raw_store import RAW_FORMAT, RawStore
from codess.schema_contract import FORMAT_ID, FORMAT_VERSION, require_store, verify_package


class SnapshotError(RuntimeError):
    """Snapshot construction or verification failed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _software_revision() -> str | None:
    configured = os.environ.get("CODESS_BUILD_REVISION")
    if configured:
        return configured
    try:
        root = Path(__file__).resolve().parents[2]
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
            text=True, check=True, timeout=5,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True,
            text=True, check=True, timeout=5,
        ).stdout
        return revision + ("+dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return None


def _backup_store(
    source_path: Path,
    target_path: Path,
    *,
    snapshot_id: str,
    snapshot_created_at: str,
) -> None:
    source = sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)
    target = sqlite3.connect(target_path)
    try:
        require_store(source, write=False)
        source.backup(target)
        target.executemany(
            "INSERT OR REPLACE INTO store_meta(key, value) VALUES (?, ?)",
            (
                ("snapshot_id", snapshot_id),
                ("snapshot_created_at", snapshot_created_at),
                ("snapshot_software_version", __version__),
            ),
        )
        target.commit()
        result = target.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise SnapshotError(f"integrity_check failed for {source_path}: {result}")
        require_store(target, write=False)
    finally:
        target.close()
        source.close()


def _logical_counts(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    try:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("sources", "sessions", "interactions", "model_turns", "events", "tool_invocations", "tool_results", "artifacts", "mapping_diagnostics")
        }
    finally:
        conn.close()


def create_snapshot(
    project_root: Path,
    store_paths: Iterable[Path],
    raw_records: list[dict[str, Any]],
    *,
    raw_store: RawStore,
    seal: bool = False,
    build_policy: dict[str, Any] | None = None,
) -> Path:
    """Build beside prior snapshots, validate, and atomically promote current.json."""
    base = project_root / ".codess"
    snapshots = base / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    package_digest = verify_package()
    created_at = datetime.now(timezone.utc)
    created_at_text = created_at.isoformat()
    policy = build_policy or {"raw_mode": "seal" if seal else "unspecified"}
    policy_digest = hashlib.sha256(
        json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    identity = hashlib.sha256(
        f"{project_root.resolve()}\0{created_at_text}\0{package_digest}\0{policy_digest}".encode("utf-8")
    ).hexdigest()[:12]
    snapshot_id = f"{created_at.strftime('%Y%m%dT%H%M%S.%fZ')}-coschema{FORMAT_VERSION}-{identity}"
    parent_snapshot_id = None
    pointer = base / "current.json"
    if pointer.exists():
        try:
            previous = json.loads(pointer.read_text(encoding="utf-8"))
            previous_manifest = base / previous["path"] / "manifest.json"
            if _sha256(previous_manifest) != previous["manifest_sha256"]:
                raise SnapshotError("refusing to replace an invalid current snapshot pointer")
            parent_snapshot_id = previous.get("snapshot_id")
        except SnapshotError:
            raise
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise SnapshotError(
                f"refusing to replace an unreadable current snapshot pointer: {exc}"
            ) from exc
    with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=snapshots) as tmp_name:
        tmp = Path(tmp_name)
        stores: dict[str, Any] = {}
        for source_path in sorted(store_paths, key=lambda p: p.name):
            if not source_path.exists():
                continue
            target = tmp / source_path.name
            _backup_store(
                source_path, target, snapshot_id=snapshot_id,
                snapshot_created_at=created_at_text,
            )
            stores[source_path.name] = {
                "sha256": _sha256(target),
                "size": target.stat().st_size,
                "counts": _logical_counts(target),
            }
        if not stores:
            raise SnapshotError("cannot create a snapshot without a CoSchema store")

        raw_manifest = tmp / "raw-manifest.jsonl"
        with raw_manifest.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps({"record_type": "header", "raw_format": RAW_FORMAT}, sort_keys=True) + "\n")
            for record in raw_records:
                stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                if seal and record.get("availability") == "captured":
                    source_object = raw_store.resolve(record)
                    if source_object is None or not source_object.exists():
                        raise SnapshotError(f"missing raw object for {record.get('object_id')}")
                    target_object = tmp / "raw" / record["object_relpath"]
                    target_object.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        os.link(source_object, target_object)
                    except OSError:
                        shutil.copy2(source_object, target_object)
                    if _sha256(target_object) != record["stored_sha256"]:
                        raise SnapshotError(f"sealed raw hash mismatch: {record.get('object_id')}")

        manifest: dict[str, Any] = {
            "snapshot_format": "codess.snapshot/1",
            "snapshot_id": snapshot_id,
            "parent_snapshot_id": parent_snapshot_id,
            "created_at": created_at_text,
            "software_version": __version__,
            "software_revision": _software_revision(),
            "runtime": {
                "python": platform.python_version(),
                "sqlite": sqlite3.sqlite_version,
                "platform": platform.platform(),
            },
            "build_policy": policy,
            "build_policy_sha256": policy_digest,
            "format_id": FORMAT_ID,
            "format_version": FORMAT_VERSION,
            "package_digest": package_digest,
            "raw_format": RAW_FORMAT,
            "sealed": seal,
            "raw_manifest_sha256": _sha256(raw_manifest),
            "stores": stores,
        }
        (tmp / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        final = snapshots / snapshot_id
        os.replace(tmp, final)

    current = {
        "snapshot_id": snapshot_id,
        "path": str(final.relative_to(base)),
        "format_id": FORMAT_ID,
        "format_version": FORMAT_VERSION,
        "manifest_sha256": _sha256(final / "manifest.json"),
    }
    pointer_tmp = base / f".current.json.tmp-{os.getpid()}"
    pointer_tmp.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(pointer_tmp, base / "current.json")
    return final


def current_store_paths(project_root: Path) -> list[Path]:
    """Resolve validated current-snapshot DB paths, or return an empty list."""
    base = project_root / ".codess"
    pointer = base / "current.json"
    if not pointer.exists():
        return []
    try:
        current = json.loads(pointer.read_text(encoding="utf-8"))
        snapshot = base / current["path"]
        manifest_path = snapshot / "manifest.json"
        if _sha256(manifest_path) != current["manifest_sha256"]:
            raise SnapshotError("current snapshot manifest hash mismatch")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["format_id"] != FORMAT_ID or manifest["format_version"] != FORMAT_VERSION:
            raise SnapshotError("current snapshot format is unsupported")
        if manifest.get("package_digest") != verify_package():
            raise SnapshotError("current snapshot CoSchema package digest mismatch")
        raw_manifest = snapshot / "raw-manifest.jsonl"
        if _sha256(raw_manifest) != manifest.get("raw_manifest_sha256"):
            raise SnapshotError("current snapshot raw manifest hash mismatch")
        paths = []
        for name, entry in manifest["stores"].items():
            path = snapshot / name
            if _sha256(path) != entry["sha256"]:
                raise SnapshotError(f"current store hash mismatch: {name}")
            conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                require_store(conn, write=False)
                meta = dict(conn.execute("SELECT key, value FROM store_meta"))
                if meta.get("snapshot_id") != manifest.get("snapshot_id"):
                    raise SnapshotError(f"current store snapshot identity mismatch: {name}")
                if meta.get("package_digest") != manifest.get("package_digest"):
                    raise SnapshotError(f"current store package digest mismatch: {name}")
                if _logical_counts(path) != entry.get("counts"):
                    raise SnapshotError(f"current store logical counts mismatch: {name}")
            finally:
                conn.close()
            paths.append(path)
        return sorted(paths)
    except SnapshotError:
        raise
    except (OSError, KeyError, json.JSONDecodeError, sqlite3.Error) as exc:
        raise SnapshotError(f"invalid current snapshot pointer: {exc}") from exc
