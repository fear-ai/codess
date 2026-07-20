"""Resolve a normalized event to exact, explicitly qualified source evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codess.fileio import hash_file, source_fingerprint
from codess.raw_store import RawCaptureError, verify_captured_object


EVIDENCE_FORMAT = "codess.evidence-resolution/1"


def _snapshot_root(store_path: Path) -> Path | None:
    for parent in store_path.parents:
        if (parent / "manifest.json").is_file() and (parent / "raw-manifest.jsonl").is_file():
            return parent
    return None


def _raw_records(snapshot: Path | None) -> list[dict[str, Any]]:
    if snapshot is None:
        return []
    records = []
    try:
        with (snapshot / "raw-manifest.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                value = json.loads(line)
                if isinstance(value, dict):
                    records.append(value)
    except (OSError, json.JSONDecodeError):
        return []
    return records


def _captured_object(snapshot: Path, relpath: str) -> tuple[Path | None, str]:
    sealed = snapshot / "raw" / relpath
    if sealed.is_file():
        return sealed, "sealed"
    # Durable snapshots normally live at <registry>/projects/<id>/snapshots/<id>.
    # Resolve the single content-addressed object by manifest-relative identity;
    # do not materialize or copy it merely to answer an evidence query.
    for parent in snapshot.parents:
        if parent.name == "projects":
            captured = parent.parent / "raw" / "codess.raw-1" / relpath
            if captured.is_file():
                return captured, "captured"
            break
    return None, "captured"


def resolve_event(store: dict[str, Any], event_identifier: str) -> dict[str, Any]:
    """Resolve by stable global event ID or unambiguous local event ID."""
    conn = store["conn"]
    matches = conn.execute("""
        SELECT e.global_id,e.event_id,e.session_id,e.source_record_locator,
               e.source_record_type,e.source_file,s.global_id AS global_session_id,
               src.id AS source_id,src.source_system_id,src.source_uri,
               src.source_revision,src.source_mtime,src.source_size,
               src.availability,src.capture_method,
               src.consistency,src.content_sha256
        FROM events e JOIN sessions s ON s.id=e.session_id
        LEFT JOIN sources src ON src.id=e.source_id
        WHERE e.global_id=? OR e.event_id=?
    """, (event_identifier, event_identifier)).fetchall()
    if not matches:
        raise LookupError(f"event {event_identifier!r} was not found")
    if len(matches) > 1:
        raise LookupError(
            f"event ID {event_identifier!r} is ambiguous; use its global event ID"
        )
    row = matches[0]
    source_record = None
    if row["source_id"] is not None and row["source_record_locator"]:
        found = conn.execute("""
            SELECT id,source_locator,source_sequence,source_record_type,
                   source_record_subtype,parent_locator,record_at,classification
            FROM source_records WHERE source_id=? AND source_locator=?
        """, (row["source_id"], row["source_record_locator"])).fetchone()
        if found:
            source_record = dict(found)
    source_uri = row["source_uri"] or row["source_file"]
    candidates: list[dict[str, Any]] = []
    snapshot = _snapshot_root(Path(store["path"]))
    for record in _raw_records(snapshot):
        if source_uri and record.get("source_locator") != source_uri:
            continue
        relpath = record.get("object_relpath")
        object_path, object_kind = (
            _captured_object(snapshot, relpath)
            if snapshot and relpath else (None, "captured")
        )
        candidate = {
            "kind": object_kind,
            "location": None,
            "revision": record.get("source_revision_id"),
            "object_id": record.get("object_id"),
            "equality": "unverified",
            "available": False,
        }
        if object_path and object_path.is_file():
            candidate["location"] = str(object_path)
            candidate["available"] = True
            try:
                observed = verify_captured_object(object_path, record)
                expected = row["content_sha256"]
                candidate["equality"] = (
                    "exact" if observed["object_id"] == record.get("object_id")
                    and (expected is None or observed["object_id"] == f"sha256:{expected}")
                    else "mismatch"
                )
                candidate["verification"] = observed
            except RawCaptureError as exc:
                candidate["equality"] = "verification_failed"
                candidate["error"] = str(exc)
        candidates.append(candidate)
    if source_uri:
        live_path = Path(source_uri)
        live = {
            "kind": "live", "location": str(live_path),
            "available": live_path.is_file(), "equality": "unavailable",
        }
        if live_path.is_file():
            if row["content_sha256"]:
                stat = live_path.stat()
                recorded_mtime = row["source_mtime"]
                if (
                    row["source_size"] is not None
                    and (stat.st_size != row["source_size"] or (
                        recorded_mtime is not None
                        and abs(stat.st_mtime * 1000 - recorded_mtime) >= 0.5
                    ))
                ):
                    live.update({
                        "revision": f"stat:{stat.st_mtime_ns}:{stat.st_size}",
                        "equality": "mismatch",
                        "verification_method": "recorded-stat-change",
                    })
                else:
                    observed = hash_file(live_path)
                    live.update({
                        "revision": f"sha256:{observed}",
                        "equality": "exact" if observed == row["content_sha256"] else "mismatch",
                        "verification_method": "complete-sha256",
                    })
            else:
                revision, _mtime, _size, method, consistency = source_fingerprint(live_path)
                live.update({
                    "revision": revision,
                    "equality": "exact" if revision == row["source_revision"] else "mismatch",
                    "verification_method": method,
                    "consistency": consistency,
                })
        candidates.append(live)
    selected = next(
        (candidate for candidate in candidates if candidate["kind"] in {"sealed", "captured"}
         and candidate["available"] and candidate["equality"] == "exact"),
        None,
    )
    if selected is None:
        selected = next(
            (candidate for candidate in candidates if candidate["kind"] == "live"
             and candidate["available"] and candidate["equality"] == "exact"),
            None,
        )
    limitations = []
    if selected is None:
        limitations.append("no available candidate exactly matches the ingested source revision")
    if any(candidate["equality"] == "mismatch" for candidate in candidates):
        limitations.append("one or more available candidates belongs to a different revision")
    return {
        "format": EVIDENCE_FORMAT,
        "event": {
            "global_event_id": row["global_id"], "event_id": row["event_id"],
            "global_session_id": row["global_session_id"], "session_id": row["session_id"],
            "source_record_locator": row["source_record_locator"],
            "source_record_type": row["source_record_type"],
        },
        "source": {
            "source_system_id": row["source_system_id"], "source_uri": source_uri,
            "source_revision": row["source_revision"],
            "source_mtime": row["source_mtime"], "source_size": row["source_size"],
            "availability": row["availability"],
            "capture_method": row["capture_method"], "consistency": row["consistency"],
            "content_sha256": row["content_sha256"],
        },
        "source_record": source_record,
        "candidates": candidates,
        "selected": selected,
        "limitations": limitations,
    }
