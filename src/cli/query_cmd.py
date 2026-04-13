"""session-query CLI command."""

import json
import logging
import re
import sys
from pathlib import Path

from codess.config import get_project_stores
from codess.project import RootsWhenEmpty, resolve_cli_roots, resolve_registry_directory
from codess.registry_store import merge_query_stats, update_project_entry
from codess.store import connect, init_db

log = logging.getLogger(__name__)

# Standard (built-in) tools for grouping; others are "loaded"
STANDARD_TOOLS = frozenset({
    "Bash", "Read", "Edit", "Write", "Grep", "Glob", "TodoWrite",
    "LS", "AskUserQuestion", "Skill", "Agent", "Task",
    "TaskCreate", "TaskUpdate", "TaskStop", "TaskList", "TaskOutput",
})


def _get_sessions_ordered(conn, limit: int | None = None) -> list:
    """Sessions by ended_at DESC (most recent first). limit=None = all."""
    sql = """
        SELECT id, source, started_at, ended_at, project_path
        FROM sessions
        ORDER BY COALESCE(ended_at, started_at) DESC
    """
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        return conn.execute(sql, (limit,)).fetchall()
    return conn.execute(sql).fetchall()


def _session_id_by_number(conn, n: int) -> str | None:
    """Return session id for 1-based number (1=most recent)."""
    rows = _get_sessions_ordered(conn, limit=n)
    if n < 1 or n > len(rows):
        return None
    return rows[n - 1]["id"]


def run(args) -> int:
    """Run session-query. Returns exit code."""
    roots, err = resolve_cli_roots(args, when_empty=RootsWhenEmpty.PROJECT_ROOT)
    if err:
        print(err, file=sys.stderr)
        return 1

    project_root = roots[0].resolve()
    stores = get_project_stores(project_root)
    if not stores:
        print("No store found. Run session-ingest first.", file=sys.stderr)
        return 1
    store_path = stores[0]
    init_db(store_path)
    conn = connect(store_path)

    try:
        if getattr(args, "stats", False):
            return _stats(conn, project_root, resolve_registry_directory(args))
        if getattr(args, "taxonomy", False):
            return _taxonomy(conn)
        if getattr(args, "tool", None) is not None:
            return _tool_table(conn, args.tool)
        if args.sessions:
            return _sessions(conn, getattr(args, "sess_id", False))
        if getattr(args, "sess", None) is not None:
            return _show_session(conn, args.sess, getattr(args, "show", None))
        if args.permissions:
            return _permissions(conn)
        if args.task_review:
            return _task_review(conn)
        print(
            "Specify --tool, --sessions, -sess, --permissions, --task-review, --stats, or --taxonomy",
            file=sys.stderr,
        )
        return 1
    finally:
        conn.close()


def _stats(conn, project_root: Path, registry_root: Path) -> int:
    """DB stats: sessions, events; merge counts into registry at ``registry_root``."""
    sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    print(f"Sessions: {sessions}")
    print(f"Events: {events}")
    proj_str = str(project_root.resolve())

    def mut(e: dict, s: int = sessions, ev: int = events) -> None:
        merge_query_stats(e, s, ev)

    try:
        update_project_entry(registry_root, proj_str, mut)
    except OSError as ex:
        log.warning("Registry update failed for %s: %s", proj_str, ex)
    return 0


def _taxonomy(conn) -> int:
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


def _tool_table(conn, recent: int) -> int:
    """Tool histogram: rows=tools (standard first, then loaded), cols=sessions. recent=0 all, 1=most recent."""
    limit = None if recent == 0 else recent
    sessions = _get_sessions_ordered(conn, limit=limit)
    if not sessions:
        return 0

    # Per-session tool counts: {session_id: {tool_name: count}}
    sess_ids = [r["id"] for r in sessions]
    sess_counts = {}
    for sid in sess_ids:
        cur = conn.execute(
            """
            SELECT tool_name, COUNT(*) as cnt
            FROM events
            WHERE event_type = 'tool_call' AND tool_name IS NOT NULL AND session_id = ?
            GROUP BY tool_name
            """,
            (sid,),
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
        print("  ".join([row[0].ljust(max_w)] + row[1:]))
    return 0


def _normalize_prompt(s: str) -> str:
    """Code fence, collapse whitespace."""
    if not s:
        return ""
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _normalize_response(s: str) -> str:
    """Remove empty lines, trailing whitespace."""
    if not s:
        return ""
    lines = [ln.rstrip() for ln in s.splitlines() if ln.strip()]
    return "\n".join(lines)


def _show_session(conn, sess_num: int, show_modes: list | None) -> int:
    """Show session content by number. show_modes: prompt, pr, agent, tool, perm; None/empty=all."""
    sid = _session_id_by_number(conn, sess_num)
    if not sid:
        print(f"No session {sess_num}", file=sys.stderr)
        return 1

    modes = show_modes if show_modes else ["prompt", "pr", "agent", "tool", "perm"]
    show_prompt = "prompt" in modes or "pr" in modes
    show_pr = "pr" in modes
    show_agent = "agent" in modes
    show_tool = "tool" in modes
    show_perm = "perm" in modes

    cur = conn.execute(
        """
        SELECT event_type, subtype, role, content, tool_name, tool_input
        FROM events
        WHERE session_id = ?
        ORDER BY timestamp, id
        """,
        (sid,),
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
                    print(f"[tool_result] {tool_name or ''}")
                    print((content or "")[:500])
                    print()
            elif subtype == "permission_denied":
                if show_perm:
                    print(f"[permission_denied] {tool_name or ''}")
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
                print(f"[agent] {tool_name}")
                print(f"  desc: {inp.get('description', '')[:80]}")
                print(f"  prompt: {inp.get('prompt', '')[:80]}")
                print()
            elif show_tool and not is_agent:
                print(f"[tool] {tool_name}")
                if tool_input:
                    print(f"  {str(tool_input)[:120]}")
                print()
    return 0


def _sessions(conn, with_id: bool) -> int:
    """List sessions. with_id: number them (1=most recent)."""
    rows = _get_sessions_ordered(conn)
    if not rows:
        return 0
    if with_id:
        print("id\tnum\tsource\tstarted_at\tended_at\tproject_path")
        for i, row in enumerate(rows, 1):
            print(f"{row['id']}\t{i}\t{row['source']}\t{row['started_at']}\t{row['ended_at']}\t{row['project_path'] or ''}")
    else:
        print("id\tsource\tstarted_at\tended_at\tproject_path")
        for row in rows:
            print(f"{row['id']}\t{row['source']}\t{row['started_at']}\t{row['ended_at']}\t{row['project_path'] or ''}")
    return 0


def _task_review(conn) -> int:
    """Review Task and Web* tool invocations: counts, descriptions, outcomes."""
    # Tool counts by category
    cur = conn.execute(
        """
        SELECT tool_name, COUNT(*) as cnt
        FROM events
        WHERE event_type = 'tool_call' AND tool_name IS NOT NULL
        GROUP BY tool_name
        ORDER BY cnt DESC
        """
    )
    all_tools = {row["tool_name"]: row["cnt"] for row in cur}

    task_tools = {k: v for k, v in all_tools.items() if k and ("Task" in k or k in ("mcp_task", "Task"))}
    web_tools = {k: v for k, v in all_tools.items() if k and ("Web" in k or "web" in k.lower())}

    print("=== Tool counts ===")
    for name, cnt in sorted(all_tools.items(), key=lambda x: -x[1]):
        print(f"  {name}\t{cnt}")

    print("\n=== Task tools ===")
    for name, cnt in sorted(task_tools.items(), key=lambda x: -x[1]):
        print(f"  {name}\t{cnt}")

    print("\n=== Web* tools ===")
    for name, cnt in sorted(web_tools.items(), key=lambda x: -x[1]):
        print(f"  {name}\t{cnt}")

    # Task/Agent invocations: description, prompt, outcome
    cur = conn.execute(
        """
        SELECT session_id, event_id, tool_name, tool_input, timestamp
        FROM events
        WHERE event_type = 'tool_call'
          AND (tool_name LIKE '%Task%' OR tool_name IN ('mcp_task', 'Task'))
        ORDER BY timestamp
        """
    )
    task_calls = cur.fetchall()

    if task_calls:
        print("\n=== Task/Agent invocations (description, prompt) ===")
        for row in task_calls:
            inp = {}
            if row["tool_input"]:
                try:
                    inp = json.loads(row["tool_input"])
                except json.JSONDecodeError:
                    pass
            desc = inp.get("description", "")[:80]
            prompt = inp.get("prompt", "")[:80]
            sub = inp.get("subagent_type", "")
            parts = [f"[{row['tool_name']}]"]
            if desc:
                parts.append(f"desc: {desc}…" if len(str(inp.get("description", ""))) > 80 else f"desc: {desc}")
            if prompt:
                parts.append(f"prompt: {prompt}…" if len(str(inp.get("prompt", ""))) > 80 else f"prompt: {prompt}")
            if sub:
                parts.append(f"subagent: {sub}")
            print("  " + " | ".join(parts))

    # Tool results (outcomes): match by session + tool_name, infer outcome from content
    cur = conn.execute(
        """
        SELECT session_id, tool_name, content, content_len
        FROM events
        WHERE event_type = 'user_message' AND subtype = 'tool_result' AND tool_name IS NOT NULL
          AND (tool_name LIKE '%Task%' OR tool_name IN ('mcp_task', 'Task'))
        ORDER BY session_id, id
        """
    )
    results = cur.fetchall()
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


def _permissions(conn) -> int:
    """Print permission_denied events."""
    cur = conn.execute(
        """
        SELECT session_id, timestamp, tool_name
        FROM events
        WHERE subtype = 'permission_denied'
        ORDER BY timestamp
        """
    )
    rows = cur.fetchall()
    if not rows:
        return 0
    print("session_id\ttimestamp\ttool_name")
    for row in rows:
        print(f"{row['session_id']}\t{row['timestamp']}\t{row['tool_name'] or ''}")
    return 0
