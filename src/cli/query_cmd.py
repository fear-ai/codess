"""session-query CLI command."""

import json
import logging
import re
import sqlite3
import sys
from pathlib import Path

from codess.config import get_project_stores, validate_config
from codess.identity import global_session_id
from codess.project import RootsWhenEmpty, resolve_cli_roots, resolve_registry_directory
from codess.registry_store import merge_query_stats, update_project_entry
from codess.sanitize import sanitize_for_display, sanitize_tabular, sanitize_text
from codess.schema_contract import SchemaContractError
from codess.snapshot import SnapshotError, snapshot_store_paths
from codess.store import connect as connect_store
log = logging.getLogger(__name__)

# Standard (built-in) tools for grouping; others are "loaded"
STANDARD_TOOLS = frozenset({
    "Bash", "Read", "Edit", "Write", "Grep", "Glob", "TodoWrite",
    "LS", "AskUserQuestion", "Skill", "Agent", "Task",
    "TaskCreate", "TaskUpdate", "TaskStop", "TaskList", "TaskOutput",
})


class QueryScope:
    """Read-only stores selected for one logical query."""

    def __init__(self) -> None:
        self.stores: list[dict] = []

    def close(self) -> None:
        for store in self.stores:
            store["conn"].close()


def _open_query_scope(
    roots: list[Path],
    *,
    snapshot_id: str | None = None,
    allow_package_mismatch: bool = False,
) -> tuple[QueryScope, list[Path]]:
    """Open every existing project store read-only without an attachment limit."""
    scope = QueryScope()
    roots_without_stores = []
    try:
        for root in roots:
            resolved_root = root.resolve()
            stores = (
                snapshot_store_paths(
                    resolved_root, snapshot_id,
                    allow_package_mismatch=allow_package_mismatch,
                )
                if snapshot_id
                else get_project_stores(resolved_root)
            )
            if not stores:
                roots_without_stores.append(resolved_root)
                continue
            for path in stores:
                conn = None
                try:
                    conn = connect_store(path, read_only=True)
                    conn.execute("SELECT 1 FROM sessions LIMIT 1")
                    conn.execute("SELECT 1 FROM events LIMIT 1")
                except Exception:
                    if conn is not None:
                        conn.close()
                    raise
                scope.stores.append(
                    {"conn": conn, "path": path, "project_root": resolved_root}
                )
        return scope, roots_without_stores
    except Exception:
        scope.close()
        raise


def _get_sessions_ordered(scope: QueryScope, limit: int | None = None) -> list[dict]:
    """Return sessions across stores, globally ordered by recency."""
    sessions = []
    for store_index, store in enumerate(scope.stores):
        session_columns = {
            row[1] for row in store["conn"].execute("PRAGMA table_info(sessions)")
        }
        global_projection = "global_id," if "global_id" in session_columns else "NULL AS global_id,"
        rows = store["conn"].execute(
            f"""
            SELECT id, {global_projection} source_system_id, vendor_session_id, source, release, started_at, ended_at,
                   project_path, metadata
            FROM sessions
            """
        )
        for row in rows:
            source_system_id = row["source_system_id"]
            if not source_system_id or source_system_id == "legacy.unknown":
                # Pre-provenance stores did not persist a source namespace.  Keep
                # their IDs globally distinct by deriving a compatibility
                # namespace from the recorded vendor label.
                source_system_id = f"legacy.vendor:{str(row['source']).casefold()}"
            sessions.append(
                {
                    "id": row["id"],
                    "global_id": (
                        row["global_id"]
                        if row["global_id"] and not row["global_id"].startswith("codess:legacy:")
                        else global_session_id(
                            source_system_id, row["vendor_session_id"] or row["id"]
                        )
                    ),
                    "query_id": (store_index, row["id"]),
                    "source": row["source"],
                    "release": row["release"],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "project_path": row["project_path"],
                    "metadata": row["metadata"],
                    "query_project": str(store["project_root"]),
                    "conn": store["conn"],
                }
            )

    def sort_key(session: dict) -> tuple:
        timestamp = session["ended_at"]
        if timestamp is None:
            timestamp = session["started_at"]
        try:
            recency = float(timestamp) if timestamp is not None else float("-inf")
        except (TypeError, ValueError):
            recency = float("-inf")
        return (
            -recency,
            session["query_project"],
            session["source"],
            session["id"],
        )

    sessions.sort(key=sort_key)
    if limit is not None:
        return sessions[:limit]
    return sessions


def _limited(rows: list[dict], limit: int | None) -> list[dict]:
    return rows if limit is None else rows[:limit]


def _session_by_number(scope: QueryScope, n: int) -> dict | None:
    """Return the 1-based globally ordered session reference."""
    rows = _get_sessions_ordered(scope, limit=n)
    if n < 1 or n > len(rows):
        return None
    return rows[n - 1]


def run(args) -> int:
    """Run session-query. Returns exit code."""
    config_errors = validate_config()
    for msg in config_errors:
        print(f"codess: {msg}", file=sys.stderr)
    if config_errors:
        return 1

    limit = getattr(args, "limit", None)
    if limit is not None and limit < 0:
        print("codess: --limit must be >= 0", file=sys.stderr)
        return 1

    roots, err = resolve_cli_roots(args, when_empty=RootsWhenEmpty.PROJECT_ROOT)
    if err:
        print(err, file=sys.stderr)
        return 1
    resolved_roots = [root.resolve() for root in roots]
    snapshot_id = getattr(args, "snapshot_id", None)
    package_policy = getattr(args, "snapshot_package_policy", "exact")
    if snapshot_id and len(resolved_roots) != 1:
        print("codess: --snapshot-id requires exactly one project root", file=sys.stderr)
        return 1
    try:
        scope, missing_roots = _open_query_scope(
            resolved_roots,
            snapshot_id=snapshot_id,
            allow_package_mismatch=package_policy == "read-compatible",
        )
    except (sqlite3.Error, SchemaContractError, SnapshotError) as exc:
        print(f"codess: cannot open query stores: {exc}", file=sys.stderr)
        return 1
    if not scope.stores:
        print("No store found. Run session-ingest first.", file=sys.stderr)
        return 1
    for root in missing_roots:
        print(
            f"codess: warning: no store found for {sanitize_tabular(root)}",
            file=sys.stderr,
        )
    if snapshot_id and package_policy == "read-compatible":
        print(
            "codess: warning: historical snapshot package differs or was not "
            "required to match; hashes and format were verified, mapping parity was not",
            file=sys.stderr,
        )

    try:
        if getattr(args, "output_format", "table") == "jsonl":
            return _jsonl_output(
                scope, args, resolved_roots, limit,
                resolve_registry_directory(args),
                update_registry=not bool(snapshot_id),
            )
        if getattr(args, "stats", False):
            return _stats(
                scope, resolved_roots, resolve_registry_directory(args),
                update_registry=not bool(snapshot_id),
            )
        if getattr(args, "taxonomy", False):
            return _taxonomy(scope)
        if getattr(args, "tool", None) is not None:
            return _tool_table(scope, args.tool)
        if args.sessions:
            return _sessions(scope, getattr(args, "sess_id", False), limit)
        if getattr(args, "sess", None) is not None:
            return _show_session(scope, args.sess, getattr(args, "show", None))
        if args.permissions:
            return _permissions(scope, limit)
        if args.task_review:
            return _task_review(scope)
        if getattr(args, "lineage", False):
            return _lineage(scope, limit)
        if getattr(args, "audit", False):
            return _audit(scope, limit)
        if getattr(args, "diagnostics", False):
            return _diagnostics(scope, limit)
        if getattr(args, "artifacts", False):
            return _artifacts(scope, limit)
        print(
            "Specify --tool, --sessions, -sess, --permissions, --task-review, "
            "--lineage, --audit, --diagnostics, --artifacts, --stats, or --taxonomy",
            file=sys.stderr,
        )
        return 1
    finally:
        scope.close()


def _emit_jsonl(report: str, data: dict, *, project_path: str | None = None, row_number: int | None = None) -> None:
    envelope = {
        "schema": "codess.query-row/1",
        "report": report,
        "project_path": project_path,
        "row_number": row_number,
        "data": data,
    }
    print(json.dumps(envelope, sort_keys=True, separators=(",", ":")))


def _project_counts(scope: QueryScope, roots: list[Path]) -> dict[str, dict[str, int]]:
    counts = {str(root.resolve()): {"sessions": 0, "events": 0} for root in roots}
    for store in scope.stores:
        project = str(store["project_root"])
        counts[project]["sessions"] += store["conn"].execute(
            "SELECT COUNT(*) FROM sessions"
        ).fetchone()[0]
        counts[project]["events"] += store["conn"].execute(
            "SELECT COUNT(*) FROM events"
        ).fetchone()[0]
    return counts


def _merge_stats_into_registry(
    counts: dict[str, dict[str, int]], roots: list[Path], registry_root: Path,
) -> None:
    for project_root in roots:
        project = str(project_root.resolve())

        def mut(e: dict, values: dict = counts[project]) -> None:
            merge_query_stats(e, values["sessions"], values["events"])

        try:
            update_project_entry(registry_root, project, mut)
        except OSError as exc:
            log.warning("Registry update failed for %s: %s", project, exc)


def _jsonl_output(
    scope: QueryScope,
    args,
    roots: list[Path],
    limit: int | None,
    registry_root: Path,
    *,
    update_registry: bool,
) -> int:
    """Versioned typed prototype for reports with settled row semantics."""
    if args.sessions:
        for number, row in enumerate(_get_sessions_ordered(scope, limit), 1):
            _emit_jsonl("sessions", {
                "session_id": row["id"], "global_session_id": row["global_id"],
                "source": row["source"], "release": row["release"],
                "started_at": row["started_at"], "ended_at": row["ended_at"],
                "source_project_path": row["project_path"],
                "metadata": _json_metadata(row["metadata"]),
            }, project_path=row["query_project"], row_number=number)
        return 0
    if getattr(args, "stats", False):
        counts = _project_counts(scope, roots)
        for number, root in enumerate(roots, 1):
            project = str(root.resolve())
            _emit_jsonl(
                "stats.project", counts[project],
                project_path=project, row_number=number,
            )
        _emit_jsonl("stats.total", {
            "projects": len(counts),
            "sessions": sum(item["sessions"] for item in counts.values()),
            "events": sum(item["events"] for item in counts.values()),
        })
        if update_registry:
            _merge_stats_into_registry(counts, roots, registry_root)
        return 0
    print("codess: JSON Lines prototype currently supports --sessions and --stats", file=sys.stderr)
    return 1


def _stats(
    scope: QueryScope,
    project_roots: list[Path],
    registry_root: Path,
    *,
    update_registry: bool = True,
) -> int:
    """Print aggregate stats and merge per-project counts into the registry."""
    counts = _project_counts(scope, project_roots)
    sessions = sum(item["sessions"] for item in counts.values())
    events = sum(item["events"] for item in counts.values())
    print(f"Sessions: {sessions}")
    print(f"Events: {events}")
    if not update_registry:
        return 0
    _merge_stats_into_registry(counts, project_roots, registry_root)
    return 0


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _diagnostics(scope: QueryScope, limit: int | None = None) -> int:
    """Print structured mapping loss/ambiguity without hiding source values."""
    rows: list[dict] = []
    for store_index, store in enumerate(scope.stores):
        conn = store["conn"]
        if not _has_table(conn, "mapping_diagnostics"):
            continue
        for row in conn.execute(
            """
            SELECT d.level, d.reason_code, d.source_field, d.source_value,
                   d.mapping_rule, d.detail, d.created_at, d.session_id,
                   e.event_id
            FROM mapping_diagnostics d
            LEFT JOIN events e ON e.id = d.event_id
            """
        ):
            item = dict(row)
            item["project"] = str(store["project_root"])
            item["store_index"] = store_index
            rows.append(item)
    rows.sort(key=lambda row: (
        row["created_at"], row["project"], row["store_index"],
        row["session_id"] or "", row["event_id"] or "",
    ))
    rows = _limited(rows, limit)
    if not rows:
        return 0
    print("project_path\tsession_id\tevent_id\tlevel\treason_code\tsource_field\tsource_value\tmapping_rule\tdetail")
    for row in rows:
        print("\t".join(sanitize_tabular(row.get(key)) for key in (
            "project", "session_id", "event_id", "level", "reason_code",
            "source_field", "source_value", "mapping_rule", "detail",
        )))
    return 0


def _artifacts(scope: QueryScope, limit: int | None = None) -> int:
    """Aggregate evidence for artifacts touched by one or more coding systems."""
    grouped: dict[tuple[str, str, str], dict] = {}
    for store in scope.stores:
        conn = store["conn"]
        if not _has_table(conn, "artifacts") or not _has_table(conn, "event_artifacts"):
            continue
        correlations = {}
        if _has_table(conn, "correlation_assertions"):
            for assertion in conn.execute(
                "SELECT object_id, relation_kind, evidence, confidence FROM correlation_assertions "
                "WHERE subject_kind='artifact' AND object_kind='project'"
            ):
                evidence = _json_metadata(assertion["evidence"])
                uri = evidence.get("artifact_uri")
                if uri:
                    correlations.setdefault(uri, []).append(
                        (assertion["object_id"], assertion["relation_kind"], assertion["confidence"])
                    )
        rows = conn.execute(
            """
            SELECT a.artifact_kind,
                   COALESCE(a.relative_path, a.uri, a.observed_absolute_path) AS locator,
                   ea.operation, s.source, e.session_id
            FROM artifacts a
            JOIN event_artifacts ea ON ea.artifact_id = a.id
            JOIN events e ON e.id = ea.event_id
            JOIN sessions s ON s.id = e.session_id
            WHERE COALESCE(a.relative_path, a.uri, a.observed_absolute_path) IS NOT NULL
            """
        )
        project = str(store["project_root"])
        for row in rows:
            key = (project, row["artifact_kind"], row["locator"])
            item = grouped.setdefault(key, {"sources": set(), "operations": set(), "sessions": set(), "evidence": 0, "correlations": set()})
            item["sources"].add(row["source"])
            item["operations"].add(row["operation"])
            item["sessions"].add(row["session_id"])
            item["evidence"] += 1
            item["correlations"].update(correlations.get(row["locator"], []))
    rows = []
    for (project, kind, locator), item in grouped.items():
        rows.append({
            "project": project, "kind": kind, "locator": locator,
            "sources": ",".join(sorted(item["sources"])),
            "source_count": len(item["sources"]),
            "operations": ",".join(sorted(item["operations"])),
            "session_count": len(item["sessions"]), "evidence": item["evidence"],
            "correlations": ",".join(
                f"{project_id}|{relation}|{confidence:g}"
                for project_id, relation, confidence in sorted(item["correlations"])
            ),
        })
    rows.sort(key=lambda row: (-row["source_count"], -row["evidence"], row["project"], row["locator"]))
    rows = _limited(rows, limit)
    if not rows:
        return 0
    print("project_path\tartifact_kind\tlocator\tsources\tsource_count\toperations\tsession_count\tevidence_count\tproject_correlations")
    for row in rows:
        print(
            f"{sanitize_tabular(row['project'])}\t{sanitize_tabular(row['kind'])}\t"
            f"{sanitize_tabular(row['locator'])}\t{sanitize_tabular(row['sources'])}\t"
            f"{row['source_count']}\t{sanitize_tabular(row['operations'])}\t"
            f"{row['session_count']}\t{row['evidence']}\t{sanitize_tabular(row['correlations'])}"
        )
    return 0


def _taxonomy(_scope: QueryScope) -> int:
    """Event types and subtypes, vertical list."""
    print("tool_call")
    print("user_message")
    print("  prompt")
    print("  slash_command")
    print("  tool_result")
    print("  permission_denied")
    print("  tool_failure")
    print("assistant_message")
    print("  response")
    print("  dialog")
    print("  truncated")
    print("  turn_aborted")
    print("system_event")
    print("  context_compaction")
    return 0


def _tool_table(scope: QueryScope, recent: int) -> int:
    """Tool histogram: rows=tools (standard first, then loaded), cols=sessions. recent=0 all, 1=most recent."""
    limit = None if recent == 0 else recent
    sessions = _get_sessions_ordered(scope, limit=limit)
    if not sessions:
        return 0

    # Per-session tool counts: {session_id: {tool_name: count}}
    sess_ids = [r["query_id"] for r in sessions]
    sess_counts = {}
    for session in sessions:
        sid = session["query_id"]
        cur = session["conn"].execute(
            """
            SELECT tool_name, COUNT(*) as cnt
            FROM events
            WHERE event_type = 'tool_call' AND tool_name IS NOT NULL AND session_id = ?
            GROUP BY tool_name
            """,
            (session["id"],),
        )
        sess_counts[sid] = {row["tool_name"]: row["cnt"] for row in cur}

    # All tools, totals, sorted by total desc
    all_tools = {}
    for sid in sess_ids:
        for t, c in sess_counts[sid].items():
            all_tools[t] = all_tools.get(t, 0) + c
    tools_sorted = sorted(all_tools.keys(), key=lambda t: -all_tools[t])

    # Group: standard first (alphabetical), then loaded (alphabetical)
    standard = sorted([t for t in tools_sorted if t in STANDARD_TOOLS])
    loaded = sorted([t for t in tools_sorted if t not in STANDARD_TOOLS])
    tools_ordered = standard + loaded

    # Header: Sess 1 2 3 Total
    n = len(sessions)
    header = ["", "Sess"] + [str(i + 1) for i in range(n)] + ["Total"]
    print("  ".join(header))

    max_w = max(len(t) for t in tools_ordered) if tools_ordered else 10
    for tool in tools_ordered:
        row = [tool]
        for i, sid in enumerate(sess_ids):
            row.append(str(sess_counts[sid].get(tool, 0)))
        row.append(str(all_tools[tool]))
        print("  ".join([sanitize_tabular(row[0]).ljust(max_w)] + row[1:]))
    return 0


def _normalize_prompt(s: str) -> str:
    """Code fence, collapse whitespace."""
    if not s:
        return ""
    s = sanitize_text(s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _normalize_response(s: str) -> str:
    """Remove empty lines, trailing whitespace."""
    if not s:
        return ""
    lines = [ln.rstrip() for ln in sanitize_text(s).splitlines() if ln.strip()]
    return "\n".join(lines)


def _show_session(scope: QueryScope, sess_num: int, show_modes: list | None) -> int:
    """Show session content by number. show_modes: prompt, pr, agent, tool, perm; None/empty=all."""
    session = _session_by_number(scope, sess_num)
    if not session:
        print(f"No session {sess_num}", file=sys.stderr)
        return 1

    modes = show_modes if show_modes else ["prompt", "pr", "agent", "tool", "perm"]
    show_prompt = "prompt" in modes or "pr" in modes
    show_pr = "pr" in modes
    show_agent = "agent" in modes
    show_tool = "tool" in modes
    show_perm = "perm" in modes

    cur = session["conn"].execute(
        """
        SELECT event_type, subtype, role, content, tool_name, tool_input
        FROM events
        WHERE session_id = ?
        ORDER BY timestamp, id
        """,
        (session["id"],),
    )
    for row in cur:
        etype, subtype, role, content, tool_name, tool_input = (
            row["event_type"], row["subtype"], row["role"],
            row["content"], row["tool_name"], row["tool_input"],
        )
        if etype == "user_message":
            if subtype in ("prompt", "slash_command"):
                if show_prompt:
                    text = _normalize_prompt(content or "")
                    print("## User")
                    print("```")
                    print(text)
                    print("```")
                    print()
            elif subtype in ("tool_result", "tool_failure"):
                if show_tool:
                    print(f"[{subtype}] {sanitize_tabular(tool_name)}")
                    print(sanitize_for_display(content or "", 500))
                    print()
            elif subtype == "permission_denied":
                if show_perm:
                    print(f"[permission_denied] {sanitize_tabular(tool_name)}")
                    print()
        elif etype == "assistant_message":
            # Skip dialog (short pre-tool chatter); keep response and truncated only
            if subtype in ("response", "truncated") and show_pr:
                text = _normalize_response(content or "")
                if text:
                    print("## Model")
                    print(text)
                    print()
        elif etype == "tool_call":
            is_agent = tool_name and ("Task" in tool_name or tool_name in ("mcp_task", "Task", "Agent"))
            if is_agent and show_agent:
                inp = {}
                if tool_input:
                    try:
                        inp = json.loads(tool_input)
                    except json.JSONDecodeError:
                        pass
                print(f"[agent] {sanitize_tabular(tool_name)}")
                print(f"  desc: {sanitize_for_display(inp.get('description', ''), 80)}")
                print(f"  prompt: {sanitize_for_display(inp.get('prompt', ''), 80)}")
                print()
            elif show_tool and not is_agent:
                print(f"[tool] {sanitize_tabular(tool_name)}")
                if tool_input:
                    print(f"  {sanitize_for_display(str(tool_input), 120)}")
                print()
    return 0


def _sessions(scope: QueryScope, with_id: bool, limit: int | None = None) -> int:
    """List sessions. with_id: number them (1=most recent)."""
    rows = _get_sessions_ordered(scope, limit=limit)
    if not rows:
        return 0
    if with_id:
        print("id\tglobal_id\tnum\tsource\trelease\tdetails\tstarted_at\tended_at\tproject_path")
        for i, row in enumerate(rows, 1):
            project = row["project_path"] or row["query_project"]
            details = _session_details(row["metadata"])
            print(
                f"{sanitize_tabular(row['id'])}\t{row['global_id']}\t{i}\t"
                f"{sanitize_tabular(row['source'])}\t"
                f"{sanitize_tabular(row['release'])}\t{details}\t"
                f"{row['started_at']}\t"
                f"{row['ended_at']}\t{sanitize_tabular(project)}"
            )
    else:
        print("id\tglobal_id\tsource\trelease\tdetails\tstarted_at\tended_at\tproject_path")
        for row in rows:
            project = row["project_path"] or row["query_project"]
            details = _session_details(row["metadata"])
            print(
                f"{sanitize_tabular(row['id'])}\t{row['global_id']}\t{sanitize_tabular(row['source'])}\t"
                f"{sanitize_tabular(row['release'])}\t{details}\t"
                f"{row['started_at']}\t{row['ended_at']}\t{sanitize_tabular(project)}"
            )
    return 0


def _json_metadata(raw) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _session_details(raw) -> str:
    metadata = _json_metadata(raw)
    details = []
    for key in ("originator", "source", "storage", "parent_session_id"):
        if metadata.get(key) is not None:
            details.append(f"{key}={metadata[key]}")
    if metadata.get("is_sidechain"):
        details.append("sidechain=true")
    return sanitize_tabular(",".join(details))


def _lineage_id(raw) -> str:
    metadata = _json_metadata(raw)
    return str(metadata.get("call_id") or metadata.get("tool_use_id") or "")


def _lineage(scope: QueryScope, limit: int | None = None) -> int:
    """Print tool calls joined to results using vendor lineage identifiers."""
    rows = []
    for store_index, store in enumerate(scope.stores):
        events = [
            dict(row)
            for row in store["conn"].execute(
                """
                SELECT session_id, event_id, event_type, subtype, tool_name,
                       content_len, timestamp, metadata
                FROM events
                WHERE event_type = 'tool_call'
                   OR subtype IN ('tool_result', 'permission_denied', 'tool_failure')
                ORDER BY timestamp, id
                """
            )
        ]
        results: dict[tuple[str, str], list[dict]] = {}
        unlinked_results = []
        calls = []
        for event in events:
            lineage_id = _lineage_id(event["metadata"])
            event["lineage_id"] = lineage_id
            if event["event_type"] == "tool_call":
                calls.append(event)
            elif lineage_id:
                results.setdefault(
                    (event["session_id"], lineage_id), []
                ).append(event)
            else:
                unlinked_results.append(event)

        for call in calls:
            key = (call["session_id"], call["lineage_id"])
            matched = results.get(key, []) if call["lineage_id"] else []
            result = matched.pop(0) if matched else None
            call_metadata = _json_metadata(call["metadata"])
            if result is None:
                outcome = (
                    "missing_result" if call["lineage_id"] else "unlinked_call"
                )
                result_len = ""
            else:
                outcome = {
                    "permission_denied": "permission_denied",
                    "tool_failure": "tool_failure",
                }.get(result["subtype"], "result")
                result_len = result["content_len"] or 0
            rows.append({
                "store_index": store_index,
                "project": str(store["project_root"]),
                "session_id": call["session_id"],
                "timestamp": call["timestamp"],
                "tool_name": call["tool_name"] or (
                    result["tool_name"] if result else ""
                ),
                "lineage_id": call["lineage_id"],
                "status": call_metadata.get("status", ""),
                "outcome": outcome,
                "result_len": result_len,
            })

        for remaining in results.values():
            unlinked_results.extend(remaining)
        for result in unlinked_results:
            rows.append({
                "store_index": store_index,
                "project": str(store["project_root"]),
                "session_id": result["session_id"],
                "timestamp": result["timestamp"],
                "tool_name": result["tool_name"] or "",
                "lineage_id": result.get("lineage_id", ""),
                "status": "",
                "outcome": {
                    "permission_denied": "permission_denied",
                    "tool_failure": "tool_failure",
                }.get(result["subtype"], "unlinked_result"),
                "result_len": result["content_len"] or 0,
            })

    def sort_key(row: dict) -> tuple:
        try:
            timestamp = float(row["timestamp"])
        except (TypeError, ValueError):
            timestamp = float("inf")
        return (
            timestamp,
            row["project"],
            row["store_index"],
            row["session_id"],
            row["lineage_id"],
        )

    rows.sort(key=sort_key)
    rows = _limited(rows, limit)
    if not rows:
        return 0
    print(
        "project_path\tsession_id\ttimestamp\ttool_name\tlineage_id\t"
        "status\toutcome\tresult_len"
    )
    for row in rows:
        print(
            f"{sanitize_tabular(row['project'])}\t"
            f"{sanitize_tabular(row['session_id'])}\t{row['timestamp']}\t"
            f"{sanitize_tabular(row['tool_name'])}\t"
            f"{sanitize_tabular(row['lineage_id'])}\t"
            f"{sanitize_tabular(row['status'])}\t{row['outcome']}\t"
            f"{row['result_len']}"
        )
    return 0


def _task_review(scope: QueryScope) -> int:
    """Review Task and Web* tool invocations: counts, descriptions, outcomes."""
    # Tool counts by category
    all_tools = {}
    for store in scope.stores:
        cur = store["conn"].execute(
            """
            SELECT tool_name, COUNT(*) as cnt
            FROM events
            WHERE event_type = 'tool_call' AND tool_name IS NOT NULL
            GROUP BY tool_name
            """
        )
        for row in cur:
            all_tools[row["tool_name"]] = (
                all_tools.get(row["tool_name"], 0) + row["cnt"]
            )

    task_tools = {k: v for k, v in all_tools.items() if k and ("Task" in k or k in ("mcp_task", "Task"))}
    web_tools = {k: v for k, v in all_tools.items() if k and ("Web" in k or "web" in k.lower())}

    print("=== Tool counts ===")
    for name, cnt in sorted(all_tools.items(), key=lambda x: -x[1]):
        print(f"  {sanitize_tabular(name)}\t{cnt}")

    print("\n=== Task tools ===")
    for name, cnt in sorted(task_tools.items(), key=lambda x: -x[1]):
        print(f"  {sanitize_tabular(name)}\t{cnt}")

    print("\n=== Web* tools ===")
    for name, cnt in sorted(web_tools.items(), key=lambda x: -x[1]):
        print(f"  {sanitize_tabular(name)}\t{cnt}")

    # Task/Agent invocations: description, prompt, outcome
    task_calls = []
    for store in scope.stores:
        cur = store["conn"].execute(
            """
            SELECT session_id, event_id, tool_name, tool_input, timestamp
            FROM events
            WHERE event_type = 'tool_call'
              AND (tool_name LIKE '%Task%' OR tool_name IN ('mcp_task', 'Task'))
            """
        )
        task_calls.extend(dict(row) for row in cur)
    task_calls.sort(
        key=lambda row: (
            float(row["timestamp"]) if row["timestamp"] is not None else float("inf"),
            row["session_id"],
            row["event_id"],
        )
    )

    if task_calls:
        print("\n=== Task/Agent invocations (description, prompt) ===")
        for row in task_calls:
            inp = {}
            if row["tool_input"]:
                try:
                    inp = json.loads(row["tool_input"])
                except json.JSONDecodeError:
                    pass
            desc = sanitize_for_display(inp.get("description", ""), 80)
            prompt = sanitize_for_display(inp.get("prompt", ""), 80)
            sub = sanitize_tabular(inp.get("subagent_type", ""))
            parts = [f"[{sanitize_tabular(row['tool_name'])}]"]
            if desc:
                parts.append(f"desc: {sanitize_tabular(desc)}")
            if prompt:
                parts.append(f"prompt: {sanitize_tabular(prompt)}")
            if sub:
                parts.append(f"subagent: {sub}")
            print("  " + " | ".join(parts))

    # Tool results (outcomes): match by session + tool_name, infer outcome from content
    results = []
    for store in scope.stores:
        cur = store["conn"].execute(
            """
            SELECT session_id, tool_name, content, content_len
            FROM events
            WHERE event_type = 'user_message' AND subtype = 'tool_result'
              AND tool_name IS NOT NULL
              AND (tool_name LIKE '%Task%' OR tool_name IN ('mcp_task', 'Task'))
            ORDER BY session_id, id
            """
        )
        results.extend(dict(row) for row in cur)
    if results:
        outcomes = {}
        for row in results:
            c = (row["content"] or "").lower()
            if "timeout" in c:
                outcomes["timeout"] = outcomes.get("timeout", 0) + 1
            elif "not_ready" in c or "not ready" in c:
                outcomes["not_ready"] = outcomes.get("not_ready", 0) + 1
            elif "success" in c or "completed" in c:
                outcomes["success"] = outcomes.get("success", 0) + 1
            else:
                outcomes["unknown"] = outcomes.get("unknown", 0) + 1
        print("\n=== Task tool result outcomes (inferred from content) ===")
        for k, v in sorted(outcomes.items(), key=lambda x: -x[1]):
            print(f"  {k}\t{v}")

    return 0


def _permissions(scope: QueryScope, limit: int | None = None) -> int:
    """Print permission_denied events."""
    rows = []
    for store in scope.stores:
        cur = store["conn"].execute(
            """
            SELECT session_id, timestamp, tool_name
            FROM events
            WHERE subtype = 'permission_denied'
            """
        )
        for row in cur:
            item = dict(row)
            item["project_path"] = str(store["project_root"])
            rows.append(item)
    rows.sort(
        key=lambda row: (
            float(row["timestamp"]) if row["timestamp"] is not None else float("inf"),
            row["project_path"],
            row["session_id"],
            row["tool_name"] or "",
        )
    )
    rows = _limited(rows, limit)
    if not rows:
        return 0
    print("session_id\tproject_path\ttimestamp\ttool_name")
    for row in rows:
        print(
            f"{sanitize_tabular(row['session_id'])}\t"
            f"{sanitize_tabular(row['project_path'])}\t"
            f"{row['timestamp']}\t{sanitize_tabular(row['tool_name'])}"
        )
    return 0


def _audit(scope: QueryScope, limit: int | None = None) -> int:
    """Print only normalized, evidence-backed audit events."""
    rows = []
    supported = (
        "permission_denied",
        "tool_failure",
        "turn_aborted",
        "context_compaction",
    )
    placeholders = ",".join("?" for _ in supported)
    for store_index, store in enumerate(scope.stores):
        cur = store["conn"].execute(
            f"""
            SELECT e.session_id, e.event_id, e.timestamp, e.subtype,
                   e.tool_name, e.metadata, s.source
            FROM events e
            JOIN sessions s ON s.id = e.session_id
            WHERE e.subtype IN ({placeholders})
            """,
            supported,
        )
        for row in cur:
            item = dict(row)
            item["project_path"] = str(store["project_root"])
            item["store_index"] = store_index
            rows.append(item)

    def sort_key(row: dict) -> tuple:
        try:
            timestamp = float(row["timestamp"])
        except (TypeError, ValueError):
            timestamp = float("inf")
        return (
            timestamp,
            row["project_path"],
            row["store_index"],
            row["session_id"],
            row["event_id"],
        )

    rows.sort(key=sort_key)
    rows = _limited(rows, limit)
    if not rows:
        return 0
    print(
        "project_path\tsession_id\tsource\ttimestamp\taudit_kind\t"
        "tool_name\tdetail"
    )
    for row in rows:
        metadata = _json_metadata(row["metadata"])
        detail = ""
        if row["subtype"] == "context_compaction":
            detail = f"trigger={metadata.get('trigger', 'unknown')}"
        elif metadata.get("status") is not None:
            detail = f"status={metadata['status']}"
        print(
            f"{sanitize_tabular(row['project_path'])}\t"
            f"{sanitize_tabular(row['session_id'])}\t"
            f"{sanitize_tabular(row['source'])}\t{row['timestamp']}\t"
            f"{row['subtype']}\t{sanitize_tabular(row['tool_name'])}\t"
            f"{sanitize_tabular(detail)}"
        )
    return 0
