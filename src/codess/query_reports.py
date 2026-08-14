"""Report queries over one or more selected Project store sets.

These are the reports the typed executor does not cover. `query_api.execute`
answers the four structured actions -- sessions, overview, events, search --
against a validated request; the reports here are fixed analyses over the same
stores: mapping diagnostics, Artifact evidence, tool lineage, permission
outcomes, normalized audit events, tool histograms, and Task review.

They live here rather than in `cli.query_cmd` because they are domain
queries, not presentation. Each returns ordered rows and leaves rendering to
the caller, so the command module keeps its column headers and terminal
formatting and owns no SQL. Ordering belongs with the query rather than the
renderer: it is part of what a report *is*, and a caller that sorted
differently would produce a different report under the same name.

Rows are plain dictionaries. A typed row per report would be eight classes
whose only behavior is attribute access, and the renderers consume them
positionally by column name either way.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from codess.identity import session_entity_id
from codess.schema_contract import column_names, table_names

SUPPORTED_AUDIT_SUBTYPES = (
    "permission_denied",
    "tool_failure",
    "turn_aborted",
    "context_compaction",
    "context_compaction_summary",
)
"""Event subtypes the audit report treats as normalized, evidence-backed.

A closed set by intent: the report states what the store recorded, so a
subtype is added here only once its evidence is normalized, never to widen
the report over shapes whose meaning is not settled.
"""

LINEAGE_RESULT_SUBTYPES = ("tool_result", "permission_denied", "tool_failure")
"""The subtypes that can close a tool call, whatever their outcome."""


class ReportScope(Protocol):
    """What a report needs from the caller's query scope.

    Narrower than the command module's `QueryScope`: reports read the open
    stores and the source predicate, and never open, close, or select them.
    """

    @property
    def stores(self) -> list[dict[str, Any]]: ...

    def source_predicate(self, alias: str = "s") -> tuple[str, tuple[str, ...]]: ...

    def diagnostics_predicate(self) -> tuple[str, tuple[str, ...]]: ...


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    """Whether one table exists, so a report can skip an older store shape."""
    return name in table_names(conn)


def json_metadata(raw: Any) -> dict[str, Any]:
    """Decode a stored metadata column, treating anything unusable as absent.

    Metadata is retained vendor evidence, so a value that does not decode is
    reported as no metadata rather than raising: one malformed record must not
    end a report over every other Project.
    """
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _timestamp_first(value: Any) -> float:
    """Sort key placing an absent timestamp last rather than first.

    A null timestamp means the source did not record one; ordering it at the
    start would present the least-evidenced rows as the earliest.
    """
    return float(value) if value is not None else float("inf")


def limited(rows: list[dict], limit: int | None) -> list[dict]:
    """Apply a row bound after ordering, so a limit takes the top of a report."""
    return rows if limit is None else rows[:limit]


def mapping_diagnostics(
    scope: ReportScope, limit: int | None = None,
) -> list[dict[str, Any]]:
    """Mapping loss and ambiguity, ordered by when each was recorded.

    Stores without the table are skipped rather than reported as empty: the
    table postdates some published stores, and an absent table is not the
    same claim as a store with no diagnostics.

    `severity` is projected as a literal when the column is absent for the
    same reason -- older rows were all warnings, and inventing a null would
    make an unrecorded severity indistinguishable from an unknown one.
    """
    rows: list[dict[str, Any]] = []
    for store_index, store in enumerate(scope.stores):
        conn = store["conn"]
        if not _has_table(conn, "mapping_diagnostics"):
            continue
        columns = column_names(conn, "mapping_diagnostics")
        severity_projection = (
            "d.severity" if "severity" in columns else "'warn' AS severity"
        )
        where, params = scope.diagnostics_predicate()
        for row in conn.execute(
            f"""
            SELECT d.level, {severity_projection}, d.reason_code,
                   d.source_field, d.source_value,
                   d.mapping_rule, d.detail, d.created_at, d.session_id,
                   e.event_id
            FROM mapping_diagnostics d
            LEFT JOIN events e ON e.id = d.event_id
            LEFT JOIN sessions s ON s.id = COALESCE(d.session_id, e.session_id)
            LEFT JOIN sources src ON src.id = d.source_id
            {where}
            """,
            params,
        ):
            item = dict(row)
            item["project_path"] = str(store["project_path"])
            item["store_index"] = store_index
            rows.append(item)
    rows.sort(key=lambda row: (
        row["created_at"], row["project_path"], row["store_index"],
        row["session_id"] or "", row["event_id"] or "",
    ))
    return limited(rows, limit)


def artifact_evidence(
    scope: ReportScope, limit: int | None = None,
) -> list[dict[str, Any]]:
    """Artifacts with the sources, operations, and Sessions that touched them.

    Grouped by Project, kind, and locator, and ordered by how many source
    systems touched each: an Artifact that several coding systems worked on is
    what this report exists to surface, so it leads.
    """
    grouped: dict[tuple[str, str, str], dict] = {}
    for store in scope.stores:
        conn = store["conn"]
        if not _has_table(conn, "artifacts") or not _has_table(conn, "event_artifacts"):
            continue
        correlations: dict[str, list[tuple]] = {}
        if _has_table(conn, "correlation_assertions"):
            for assertion in conn.execute(
                "SELECT object_id, relation_kind, evidence, confidence "
                "FROM correlation_assertions "
                "WHERE subject_kind='artifact' AND object_kind='project'"
            ):
                uri = json_metadata(assertion["evidence"]).get("artifact_uri")
                if uri:
                    correlations.setdefault(uri, []).append((
                        assertion["object_id"],
                        assertion["relation_kind"],
                        assertion["confidence"],
                    ))
        predicate, params = scope.source_predicate()
        project = str(store["project_path"])
        for row in conn.execute(
            f"""
            SELECT a.artifact_kind,
                   COALESCE(a.relative_path, a.uri, a.observed_absolute_path) AS locator,
                   ea.operation, s.source, e.session_id
            FROM artifacts a
            JOIN event_artifacts ea ON ea.artifact_id = a.id
            JOIN events e ON e.id = ea.event_id
            JOIN sessions s ON s.id = e.session_id
            WHERE COALESCE(a.relative_path, a.uri, a.observed_absolute_path) IS NOT NULL
              AND {predicate}
            """,
            params,
        ):
            key = (project, row["artifact_kind"], row["locator"])
            item = grouped.setdefault(key, {
                "sources": set(), "operations": set(), "sessions": set(),
                "evidence": 0, "correlations": set(),
            })
            item["sources"].add(row["source"])
            item["operations"].add(row["operation"])
            item["sessions"].add(row["session_id"])
            item["evidence"] += 1
            item["correlations"].update(correlations.get(row["locator"], []))
    rows = [
        {
            "project_path": project, "kind": kind, "locator": locator,
            "sources": ",".join(sorted(item["sources"])),
            "source_count": len(item["sources"]),
            "operations": ",".join(sorted(item["operations"])),
            "session_count": len(item["sessions"]),
            "evidence": item["evidence"],
            "correlations": ",".join(
                f"{project_id}|{relation}|{confidence:g}"
                for project_id, relation, confidence in sorted(item["correlations"])
            ),
        }
        for (project, kind, locator), item in grouped.items()
    ]
    rows.sort(key=lambda row: (
        -row["source_count"], -row["evidence"], row["project_path"], row["locator"],
    ))
    return limited(rows, limit)


def _result_outcome(subtype: str, *, unmatched: bool) -> str:
    """Name what a result record reports, whether or not it matched a call.

    A denial or failure keeps its own outcome even when no call was matched:
    the evidence that a tool was denied does not become less specific because
    the vendor recorded no link to the invocation.
    """
    return {
        "permission_denied": "permission_denied",
        "tool_failure": "tool_failure",
    }.get(subtype, "unlinked_result" if unmatched else "result")


def tool_lineage(
    scope: ReportScope,
    lineage_id: Callable[[Any], str],
    sort_key: Callable[..., tuple],
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Tool calls paired with their results through vendor lineage identifiers.

    Pairing is by recorded identifier only. A call with no result reports
    `missing_result` when it had an identifier to match on and `unlinked_call`
    when it did not -- the difference matters, since the first is missing
    evidence and the second is a vendor that recorded no link at all. Results
    that match no call are reported rather than dropped, for the same reason.

    `lineage_id` is supplied by the caller because reading a vendor's chosen
    identifier out of Event metadata is decode, not reporting.
    """
    rows: list[dict[str, Any]] = []
    result_subtypes = ", ".join(f"'{subtype}'" for subtype in LINEAGE_RESULT_SUBTYPES)
    for store_index, store in enumerate(scope.stores):
        predicate, params = scope.source_predicate()
        events = [
            dict(row)
            for row in store["conn"].execute(
                f"""
                SELECT e.session_id, e.event_id, e.event_type, e.subtype,
                       e.tool_name, e.content_len, e.timestamp, e.metadata
                FROM events e JOIN sessions s ON s.id=e.session_id
                WHERE (e.event_type = 'tool_call'
                   OR e.subtype IN ({result_subtypes}))
                  AND {predicate}
                ORDER BY e.timestamp, e.id
                """,
                params,
            )
        ]
        project = str(store["project_path"])
        results: dict[tuple[str, str], list[dict]] = {}
        unlinked_results: list[dict] = []
        calls: list[dict] = []
        for event in events:
            event["lineage_id"] = lineage_id(event["metadata"])
            if event["event_type"] == "tool_call":
                calls.append(event)
            elif event["lineage_id"]:
                results.setdefault(
                    (event["session_id"], event["lineage_id"]), []
                ).append(event)
            else:
                unlinked_results.append(event)

        for call in calls:
            matched = (
                results.get((call["session_id"], call["lineage_id"]), [])
                if call["lineage_id"] else []
            )
            result = matched.pop(0) if matched else None
            if result is None:
                outcome = "missing_result" if call["lineage_id"] else "unlinked_call"
                result_len: Any = ""
            else:
                outcome = _result_outcome(result["subtype"], unmatched=False)
                result_len = result["content_len"] or 0
            rows.append({
                "store_index": store_index,
                "project_path": project,
                "session_id": call["session_id"],
                "timestamp": call["timestamp"],
                "tool_name": call["tool_name"] or (
                    result["tool_name"] if result else ""
                ),
                "lineage_id": call["lineage_id"],
                "status": json_metadata(call["metadata"]).get("status", ""),
                "outcome": outcome,
                "result_len": result_len,
            })
        for remaining in results.values():
            unlinked_results.extend(remaining)
        for result in unlinked_results:
            rows.append({
                "store_index": store_index,
                "project_path": project,
                "session_id": result["session_id"],
                "timestamp": result["timestamp"],
                "tool_name": result["tool_name"] or "",
                "lineage_id": result.get("lineage_id", ""),
                "status": "",
                "outcome": _result_outcome(result["subtype"], unmatched=True),
                "result_len": result["content_len"] or 0,
            })
    rows.sort(key=lambda row: sort_key(
        row["timestamp"], row["project_path"], row["store_index"],
        row["session_id"], row["lineage_id"],
    ))
    return limited(rows, limit)


def permission_denials(
    scope: ReportScope, limit: int | None = None,
) -> list[dict[str, Any]]:
    """Permission-denied Events in recorded order."""
    rows: list[dict[str, Any]] = []
    for store in scope.stores:
        predicate, params = scope.source_predicate()
        for row in store["conn"].execute(
            f"""
            SELECT e.session_id, e.timestamp, e.tool_name
            FROM events e JOIN sessions s ON s.id=e.session_id
            WHERE e.subtype = 'permission_denied' AND {predicate}
            """,
            params,
        ):
            item = dict(row)
            item["project_path"] = str(store["project_path"])
            rows.append(item)
    rows.sort(key=lambda row: (
        _timestamp_first(row["timestamp"]),
        row["project_path"], row["session_id"], row["tool_name"] or "",
    ))
    return limited(rows, limit)


def audit_events(
    scope: ReportScope,
    sort_key: Callable[..., tuple],
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Normalized, evidence-backed audit Events across the selected stores."""
    rows: list[dict[str, Any]] = []
    placeholders = ",".join("?" for _ in SUPPORTED_AUDIT_SUBTYPES)
    for store_index, store in enumerate(scope.stores):
        predicate, source_params = scope.source_predicate()
        for row in store["conn"].execute(
            f"""
            SELECT e.session_id, e.event_id, e.timestamp, e.subtype,
                   e.tool_name, e.content_len, e.metadata, s.source
            FROM events e
            JOIN sessions s ON s.id = e.session_id
            WHERE e.subtype IN ({placeholders}) AND {predicate}
            """,
            (*SUPPORTED_AUDIT_SUBTYPES, *source_params),
        ):
            item = dict(row)
            item["project_path"] = str(store["project_path"])
            item["store_index"] = store_index
            rows.append(item)
    rows.sort(key=lambda row: sort_key(
        row["timestamp"], row["project_path"], row["store_index"],
        row["session_id"], row["event_id"],
    ))
    return limited(rows, limit)


def tool_counts_by_session(
    sessions: Iterable[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Per-Session tool-call counts, keyed by the caller's Session query id."""
    counts: dict[str, dict[str, int]] = {}
    for session in sessions:
        counts[session["query_id"]] = {
            row["tool_name"]: row["cnt"]
            for row in session["conn"].execute(
                """
                SELECT tool_name, COUNT(*) as cnt
                FROM events
                WHERE event_type = 'tool_call' AND tool_name IS NOT NULL
                  AND session_id = ?
                GROUP BY tool_name
                """,
                (session["id"],),
            )
        }
    return counts


def tool_totals(scope: ReportScope) -> dict[str, int]:
    """Tool-call counts across the selected stores, by exact tool name."""
    totals: dict[str, int] = {}
    for store in scope.stores:
        predicate, params = scope.source_predicate()
        for row in store["conn"].execute(
            f"""
            SELECT e.tool_name, COUNT(*) as cnt
            FROM events e JOIN sessions s ON s.id=e.session_id
            WHERE e.event_type = 'tool_call' AND e.tool_name IS NOT NULL
              AND {predicate}
            GROUP BY e.tool_name
            """,
            params,
        ):
            totals[row["tool_name"]] = totals.get(row["tool_name"], 0) + row["cnt"]
    return totals


def task_invocations(scope: ReportScope) -> list[dict[str, Any]]:
    """Task and agent tool calls, ordered by when each was recorded."""
    calls: list[dict[str, Any]] = []
    for store in scope.stores:
        predicate, params = scope.source_predicate()
        calls.extend(
            dict(row)
            for row in store["conn"].execute(
                f"""
                SELECT e.session_id, e.event_id, e.tool_name, e.tool_input,
                       e.timestamp
                FROM events e JOIN sessions s ON s.id=e.session_id
                WHERE e.event_type = 'tool_call'
                  AND (e.tool_name LIKE '%Task%'
                       OR e.tool_name IN ('mcp_task', 'Task'))
                  AND {predicate}
                """,
                params,
            )
        )
    calls.sort(key=lambda row: (
        _timestamp_first(row["timestamp"]), row["session_id"], row["event_id"],
    ))
    return calls


def selected_sessions(
    scope: ReportScope, sort_key: Callable[[dict], tuple], limit: int | None = None,
) -> list[dict[str, Any]]:
    """Sessions across the selected stores, globally ordered by recency.

    `entity_id` and `project_id` are projected as literals when a store
    predates the column, so an older store reports an absent identity rather
    than failing to open. A Session with no stored `entity_id` has one derived
    from its source system and vendor identifier, which is the same
    construction the store would have written -- the identity is a property of
    the Session, not of when the store was created.

    Each row carries the connection it came from, since the tool histogram
    queries per-Session counts against that same store.
    """
    sessions: list[dict[str, Any]] = []
    for store_index, store in enumerate(scope.stores):
        conn = store["conn"]
        columns = column_names(conn, "sessions")
        global_projection = (
            "session_entity_id," if "session_entity_id" in columns else "NULL AS session_entity_id,"
        )
        project_projection = (
            "project_id," if "project_id" in columns else "NULL AS project_id,"
        )
        predicate, params = scope.source_predicate()
        for row in conn.execute(
            f"""
            SELECT id, {global_projection} {project_projection}
                   source_system_id, vendor_session_id, source, release,
                   started_at, ended_at, project_path, metadata
            FROM sessions s
            WHERE {predicate}
            """,
            params,
        ):
            stable_id = row["session_entity_id"] or session_entity_id(
                row["source_system_id"], row["vendor_session_id"] or row["id"],
            )
            sessions.append({
                "id": row["id"],
                "session_entity_id": stable_id,
                "project_id": row["project_id"] or store.get("project_id"),
                "query_id": (store_index, row["id"]),
                "source": row["source"],
                "release": row["release"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "project_path": row["project_path"],
                "metadata": row["metadata"],
                "query_project": str(store["project_path"]),
                "conn": conn,
            })
    sessions.sort(key=sort_key)
    return sessions if limit is None else sessions[:limit]


def session_events(session: dict[str, Any]) -> list[dict[str, Any]]:
    """One Session's Events in the order the source recorded them.

    Ordering is by stored sequence first, falling back to time and finally to
    row identity, with unsequenced Events placed last: a vendor that recorded
    no sequence has not thereby claimed its Events came first. Reconstruction
    follows stored order rather than inferring it from timestamps.
    """
    return [
        dict(row)
        for row in session["conn"].execute(
            """
            SELECT event_type, subtype, role, content, tool_name, tool_input
            FROM events
            WHERE session_id = ?
            ORDER BY CASE WHEN sequence_no IS NULL THEN 1 ELSE 0 END,
                     sequence_no, COALESCE(event_at, timestamp), id
            """,
            (session["id"],),
        )
    ]


def task_results(scope: ReportScope) -> list[dict[str, Any]]:
    """Result records for Task and agent tool calls, in recorded order.

    Ordered inside the query by Session and row identity rather than by
    timestamp: a delegated Session's results are read as a sequence, and a
    result whose time the vendor did not record still has a position.
    """
    rows: list[dict[str, Any]] = []
    for store in scope.stores:
        predicate, params = scope.source_predicate()
        rows.extend(
            dict(row)
            for row in store["conn"].execute(
                f"""
                SELECT e.session_id, e.tool_name, e.content, e.content_len
                FROM events e JOIN sessions s ON s.id=e.session_id
                WHERE e.event_type = 'user_message' AND e.subtype = 'tool_result'
                  AND e.tool_name IS NOT NULL
                  AND (e.tool_name LIKE '%Task%'
                       OR e.tool_name IN ('mcp_task', 'Task'))
                  AND {predicate}
                ORDER BY e.session_id, e.id
                """,
                params,
            )
        )
    return rows


def store_counts(scope: ReportScope) -> dict[str, dict[str, int]]:
    """Session and Event counts per Project, over the stores actually open.

    Projects with no readable store are absent rather than zero; the caller
    decides whether an unqueryable Project should appear in its report as a
    zero row, since that is a presentation question about the roots the user
    named rather than a fact about the stores.
    """
    counts: dict[str, dict[str, int]] = {}
    for store in scope.stores:
        conn = store["conn"]
        predicate, params = scope.source_predicate()
        entry = counts.setdefault(
            str(store["project_path"]), {"sessions": 0, "events": 0},
        )
        entry["sessions"] += conn.execute(
            f"SELECT COUNT(*) FROM sessions s WHERE {predicate}", params,
        ).fetchone()[0]
        entry["events"] += conn.execute(
            f"""
            SELECT COUNT(*) FROM events e JOIN sessions s ON s.id=e.session_id
            WHERE {predicate}
            """,
            params,
        ).fetchone()[0]
    return counts
