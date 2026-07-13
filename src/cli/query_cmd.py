"""session-query CLI command."""

import json
import logging
import re
import sqlite3
import sys
from pathlib import Path

from codess.config import get_project_stores, validate_config
from codess.project import RootsWhenEmpty, resolve_cli_roots, resolve_registry_directory
from codess.registry_store import merge_query_stats, update_project_entry
from codess.sanitize import sanitize_for_display, sanitize_tabular, sanitize_text
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


def _open_query_scope(roots: list[Path]) -> tuple[QueryScope, list[Path]]:
    """Open every existing project store read-only without an attachment limit."""
    scope = QueryScope()
    roots_without_stores = []
    try:
        for root in roots:
            resolved_root = root.resolve()
            stores = get_project_stores(resolved_root)
            if not stores:
                roots_without_stores.append(resolved_root)
                continue
            for path in stores:
                conn = None
                try:
                    conn = sqlite3.connect(
                        f"file:{path.resolve()}?mode=ro", uri=True
                    )
                    conn.row_factory = sqlite3.Row
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
        rows = store["conn"].execute(
            """
            SELECT id, source, started_at, ended_at, project_path
            FROM sessions
            """
        )
        for row in rows:
            sessions.append(
                {
                    "id": row["id"],
                    "query_id": (store_index, row["id"]),
                    "source": row["source"],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "project_path": row["project_path"],
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
    if limit is not None and limit > 0:
        return sessions[:limit]
    return sessions


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

    roots, err = resolve_cli_roots(args, when_empty=RootsWhenEmpty.PROJECT_ROOT)
    if err:
        print(err, file=sys.stderr)
        return 1
    resolved_roots = [root.resolve() for root in roots]
    try:
        scope, missing_roots = _open_query_scope(resolved_roots)
    except sqlite3.Error as exc:
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

    try:
        if getattr(args, "stats", False):
            return _stats(scope, resolved_roots, resolve_registry_directory(args))
        if getattr(args, "taxonomy", False):
            return _taxonomy(scope)
        if getattr(args, "tool", None) is not None:
            return _tool_table(scope, args.tool)
        if args.sessions:
            return _sessions(scope, getattr(args, "sess_id", False))
        if getattr(args, "sess", None) is not None:
            return _show_session(scope, args.sess, getattr(args, "show", None))
        if args.permissions:
            return _permissions(scope)
        if args.task_review:
            return _task_review(scope)
        print(
            "Specify --tool, --sessions, -sess, --permissions, --task-review, --stats, or --taxonomy",
            file=sys.stderr,
        )
        return 1
    finally:
        scope.close()


def _stats(scope: QueryScope, project_roots: list[Path], registry_root: Path) -> int:
    """Print aggregate stats and merge per-project counts into the registry."""
    counts = {
        str(root.resolve()): {"sessions": 0, "events": 0}
        for root in project_roots
    }
    for store in scope.stores:
        project = str(store["project_root"])
        counts[project]["sessions"] += store["conn"].execute(
            "SELECT COUNT(*) FROM sessions"
        ).fetchone()[0]
        counts[project]["events"] += store["conn"].execute(
            "SELECT COUNT(*) FROM events"
        ).fetchone()[0]
    sessions = sum(item["sessions"] for item in counts.values())
    events = sum(item["events"] for item in counts.values())
    print(f"Sessions: {sessions}")
    print(f"Events: {events}")
    for project_root in project_roots:
        proj_str = str(project_root.resolve())
        project_sessions = counts[proj_str]["sessions"]
        project_events = counts[proj_str]["events"]

        def mut(e: dict, s: int = project_sessions, ev: int = project_events) -> None:
            merge_query_stats(e, s, ev)

        try:
            update_project_entry(registry_root, proj_str, mut)
        except OSError as ex:
            log.warning("Registry update failed for %s: %s", proj_str, ex)
    return 0


def _taxonomy(_scope: QueryScope) -> int:
    """Event types and subtypes, vertical list."""
    print("tool_call")
    print("user_message")
    print("  prompt")
    print("  slash_command")
    print("  tool_result")
    print("  permission_denied")
    print("assistant_message")
    print("  response")
    print("  dialog")
    print("  truncated")
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
            elif subtype == "tool_result":
                if show_tool:
                    print(f"[tool_result] {sanitize_tabular(tool_name)}")
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


def _sessions(scope: QueryScope, with_id: bool) -> int:
    """List sessions. with_id: number them (1=most recent)."""
    rows = _get_sessions_ordered(scope)
    if not rows:
        return 0
    if with_id:
        print("id\tnum\tsource\tstarted_at\tended_at\tproject_path")
        for i, row in enumerate(rows, 1):
            project = row["project_path"] or row["query_project"]
            print(
                f"{sanitize_tabular(row['id'])}\t{i}\t"
                f"{sanitize_tabular(row['source'])}\t{row['started_at']}\t"
                f"{row['ended_at']}\t{sanitize_tabular(project)}"
            )
    else:
        print("id\tsource\tstarted_at\tended_at\tproject_path")
        for row in rows:
            project = row["project_path"] or row["query_project"]
            print(
                f"{sanitize_tabular(row['id'])}\t{sanitize_tabular(row['source'])}\t"
                f"{row['started_at']}\t{row['ended_at']}\t{sanitize_tabular(project)}"
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


def _permissions(scope: QueryScope) -> int:
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
            row["session_id"],
        )
    )
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
