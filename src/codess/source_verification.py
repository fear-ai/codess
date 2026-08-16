"""Locate an Event's original bytes and report whether they still match.

Named for what it answers rather than for the step it performs. Given an Event, it
reports every place the source can still be read -- the sealed snapshot, a raw capture,
the live vendor file -- and for each, whether the bytes are still the ones the store was
built from. "Resolver" described the mechanism and left the question implicit; the
question is whether a citation still stands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codess.config import MANIFEST_FILE, RAW_MANIFEST_FILE
from codess.fileio import hash_file, read_source_revision
from codess.raw_store import RawCaptureError, verify_raw

VERIFICATION_FORMAT = "codess.source-verification/1"


def _snapshot_root(store_path: Path) -> Path | None:
    for parent in store_path.parents:
        if (parent / MANIFEST_FILE).is_file() and (parent / RAW_MANIFEST_FILE).is_file():
            return parent
    return None


def _raw_records(snapshot: Path | None) -> list[dict[str, Any]]:
    if snapshot is None:
        return []
    records = []
    try:
        with (snapshot / RAW_MANIFEST_FILE).open(encoding="utf-8") as stream:
            for line in stream:
                value = json.loads(line)
                if isinstance(value, dict):
                    records.append(value)
    except (OSError, json.JSONDecodeError):
        return []
    return records


def _locate_raw_object(snapshot: Path, relpath: str) -> tuple[Path | None, str]:
    """Find one stored raw object and report how it is retained.

    Named for the raw object rather than for a capture mode: `captured` is one
    of four raw modes, so the old name only parsed for a reader who already
    knew that vocabulary, and would have gone stale if the modes changed. The
    returned kind stays mode-shaped because it is the disposition a caller
    reports, not this function's subject.
    """
    sealed = snapshot / "raw" / relpath
    if sealed.is_file():
        return sealed, "sealed"
    # Durable snapshots normally live at <registry>/projects/<id>/snapshots/<id>.
    # Resolve the single content-addressed object by manifest-relative identity;
    # do not read or copy it merely to answer an evidence query.
    for parent in snapshot.parents:
        if parent.name == "projects":
            captured = parent.parent / "raw" / "codess.raw-1" / relpath
            if captured.is_file():
                return captured, "captured"
            break
    return None, "captured"


def verify_event_source(store: dict[str, Any], event_identifier: str) -> dict[str, Any]:
    """Resolve by stable event entity ID or unambiguous local event ID."""
    conn = store["conn"]
    matches = conn.execute("""
        SELECT e.event_entity_id,e.event_id,e.session_id,e.source_record_locator,
               e.source_record_type,e.source_file,s.session_entity_id AS session_entity_id,
               src.id AS source_id,src.source_system_id,src.source_path,
               src.source_revision,src.source_mtime,src.source_size,
               src.availability,src.capture_method,
               src.consistency,src.content_digest
        FROM events e JOIN sessions s ON s.id=e.session_id
        LEFT JOIN sources src ON src.id=e.source_id
        WHERE e.event_entity_id=? OR e.event_id=?
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
    source_path = row["source_path"] or row["source_file"]
    candidates: list[dict[str, Any]] = []
    snapshot = _snapshot_root(Path(store["path"]))
    for record in _raw_records(snapshot):
        if source_path and record.get("source_locator") != source_path:
            continue
        relpath = record.get("object_relpath")
        object_path, object_kind = (
            _locate_raw_object(snapshot, relpath)
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
                observed = verify_raw(object_path, record)
                expected = row["content_digest"]
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
    if source_path:
        live_path = Path(source_path)
        live = {
            "kind": "live", "location": str(live_path),
            "available": live_path.is_file(), "equality": "unavailable",
        }
        if live_path.is_file():
            if row["content_digest"]:
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
                        "equality": "exact" if observed == row["content_digest"] else "mismatch",
                        "verification_method": "complete-sha256",
                    })
            else:
                revision, _mtime, _size, method, consistency = (
                    read_source_revision(live_path)
                )
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
        "format": VERIFICATION_FORMAT,
        "event": {
            "event_entity_id": row["event_entity_id"], "event_id": row["event_id"],
            "session_entity_id": row["session_entity_id"], "session_id": row["session_id"],
            "source_record_locator": row["source_record_locator"],
            "source_record_type": row["source_record_type"],
        },
        "source": {
            "source_system_id": row["source_system_id"], "source_path": source_path,
            "source_revision": row["source_revision"],
            "source_mtime": row["source_mtime"], "source_size": row["source_size"],
            "availability": row["availability"],
            "capture_method": row["capture_method"], "consistency": row["consistency"],
            "content_digest": row["content_digest"],
        },
        "source_record": source_record,
        "candidates": candidates,
        "selected": selected,
        "limitations": limitations,
    }
