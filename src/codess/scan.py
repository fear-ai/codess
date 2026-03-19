"""Scan: discover projects with session data from CC, Codex, Cursor."""

import json
import time
from datetime import datetime
from pathlib import Path

from codess.adapters.cursor import get_db_metrics
from codess.config import AGGREGATORS, CC_PROJECTS, CODEX_SESSIONS, CODESS_DAYS, CURSOR_WS
from codess.helpers import is_excluded, slug_to_path
from codess.project import get_cursor_global_db, get_cursor_workspace_dbs


def _days_ago(max_ts: float) -> float | None:
    """(now - max_ts) in days. None if max_ts is 0 or invalid."""
    if not max_ts:
        return None
    return round((time.time() * 1000 - max_ts) / (24 * 3600 * 1000), 1)


def _session_metrics_cc(p: Path, cutoff_ms: float | None = None) -> dict:
    """Use sessions-index.json when present; else top-level *.jsonl. Exclude subagents. cutoff_ms: only count sessions with mtime >= cutoff."""
    slug = "-" + str(p).lstrip("/").replace("/", "-")
    cc_dir = CC_PROJECTS / slug
    count, total_bytes, events, min_ts, max_ts = 0, 0, 0, float("inf"), 0.0
    p_res = str(p.resolve())
    if cc_dir.exists():
        idx = cc_dir / "sessions-index.json"
        if idx.exists():
            try:
                data = json.loads(idx.read_text())
                for e in data.get("entries", []):
                    if str(Path(e.get("projectPath", "")).resolve()) != p_res:
                        continue
                    mtime = e.get("fileMtime") or 0
                    if cutoff_ms and mtime < cutoff_ms:
                        continue
                    if e.get("isSidechain"):
                        continue
                    count += 1
                    events += e.get("messageCount", 0)
                    if mtime:
                        min_ts = min(min_ts, mtime)
                        max_ts = max(max_ts, mtime)
                    sid = e.get("sessionId", "")
                    fp = e.get("fullPath")
                    added = False
                    if fp:
                        try:
                            total_bytes += Path(fp).stat().st_size
                            added = True
                        except OSError:
                            pass
                    if not added and sid:
                        sess_dir = cc_dir / sid
                        if sess_dir.exists():
                            for jf in sess_dir.rglob("*.jsonl"):
                                try:
                                    total_bytes += jf.stat().st_size
                                except OSError:
                                    pass
            except (json.JSONDecodeError, OSError, KeyError):
                pass
        if count == 0:
            for f in cc_dir.glob("*.jsonl"):
                try:
                    mtime = f.stat().st_mtime * 1000
                    if cutoff_ms and mtime < cutoff_ms:
                        continue
                    count += 1
                    total_bytes += f.stat().st_size
                    min_ts = min(min_ts, mtime)
                    max_ts = max(max_ts, mtime)
                except OSError:
                    pass
    span = (max_ts - min_ts) / (7 * 24 * 3600 * 1000) if max_ts > min_ts else None
    return {"count": count, "events": events, "size_mb": round(total_bytes / (1024 * 1024), 2), "span_weeks": round(span, 1) if span else None, "max_ts": max_ts, "days_ago": _days_ago(max_ts)}


def _session_metrics_codex(p: Path, cutoff_ms: float | None = None) -> dict:
    count, total_bytes, events, min_ts, max_ts = 0, 0, 0, float("inf"), 0.0
    p_res = str(p.resolve())
    if CODEX_SESSIONS.exists():
        for f in CODEX_SESSIONS.rglob("*.jsonl"):
            try:
                with f.open() as fp:
                    first = next(fp, None)
                if not first:
                    continue
                d = json.loads(first)
                if d.get("type") != "session_meta":
                    continue
                cwd = (d.get("payload") or {}).get("cwd", "")
                if not cwd or str(Path(cwd).resolve()) != p_res:
                    continue
                ts = d.get("timestamp")
                if isinstance(ts, (int, float)):
                    ts_ms = ts * 1000 if ts < 1e12 else ts
                elif isinstance(ts, str):
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        ts_ms = dt.timestamp() * 1000
                    except (ValueError, TypeError):
                        ts_ms = 0
                else:
                    ts_ms = 0
                if cutoff_ms and ts_ms < cutoff_ms:
                    continue
                count += 1
                total_bytes += f.stat().st_size
                try:
                    with f.open() as fp:
                        events += sum(1 for _ in fp if _.strip())
                except OSError:
                    pass
                if ts_ms:
                    min_ts = min(min_ts, ts_ms)
                    max_ts = max(max_ts, ts_ms)
            except (StopIteration, json.JSONDecodeError, OSError, KeyError):
                pass
    span = (max_ts - min_ts) / (7 * 24 * 3600 * 1000) if max_ts > min_ts else None
    return {"count": count, "events": events, "size_mb": round(total_bytes / (1024 * 1024), 2), "span_weeks": round(span, 1) if span else None, "max_ts": max_ts, "days_ago": _days_ago(max_ts)}


def _session_metrics_cursor(p: Path) -> dict:
    """Workspace DBs for project. sess=composers, events=bubbles, size=db bytes."""
    dbs = get_cursor_workspace_dbs(p)
    count, events, total_bytes = 0, 0, 0
    for db in dbs:
        m = get_db_metrics(db)
        count += m["count"]
        events += m["events"]
        total_bytes += m["size_bytes"]
    return {"count": count, "events": events, "size_mb": round(total_bytes / (1024 * 1024), 2), "span_weeks": None, "max_ts": None, "days_ago": None}


def _session_metrics_cursor_global() -> dict:
    """Central/global DB. No project filter."""
    db = get_cursor_global_db()
    if not db:
        return {"count": 0, "events": 0, "size_mb": 0.0, "span_weeks": None, "max_ts": None, "days_ago": None}
    m = get_db_metrics(db)
    return {"count": m["count"], "events": m["events"], "size_mb": round(m["size_bytes"] / (1024 * 1024), 2), "span_weeks": None, "max_ts": None, "days_ago": None}


def run_scan(work_root: Path, vendor_filter: list[str] | None = None, recent_days: int | None = None, debug: bool = False) -> list[dict]:
    """Discover projects with session data. Return list of dicts: path, vendor, sess, mb, span_weeks.
    recent_days: if set, only include sessions from last N days (CODESS_DAYS).
    debug: print each dir visited with findings; include all projects regardless of filters."""
    import sys
    cc_paths, codex_paths, cursor_paths = set(), set(), set()
    if CC_PROJECTS.exists():
        for d in CC_PROJECTS.iterdir():
            if not d.is_dir():
                continue
            idx = d / "sessions-index.json"
            if idx.exists():
                try:
                    data = json.loads(idx.read_text())
                    for e in data.get("entries", []):
                        pp = e.get("projectPath")
                        if pp and str(Path(pp).resolve()).startswith(str(work_root)):
                            r = Path(pp).resolve()
                            if r not in cc_paths:
                                cc_paths.add(r)
                                if debug:
                                    print(f"[dir] CC dir: {d} -> {r}", file=sys.stderr)
                except (json.JSONDecodeError, OSError, KeyError):
                    pass
            p = Path(str(slug_to_path(d.name)))
            if str(p).startswith(str(work_root)):
                r = p.resolve()
                if r not in cc_paths:
                    cc_paths.add(r)
                    if debug:
                        print(f"[dir] CC dir: {d} -> {r}", file=sys.stderr)
    if CODEX_SESSIONS.exists():
        for f in CODEX_SESSIONS.rglob("*.jsonl"):
            try:
                d = json.loads(next(f.open()))
                if d.get("type") == "session_meta":
                    cwd = (d.get("payload") or {}).get("cwd", "")
                    if cwd and cwd.startswith(str(work_root)):
                        r = Path(cwd).resolve()
                        if r not in codex_paths:
                            codex_paths.add(r)
                            if debug:
                                print(f"[dir] Codex file: {f} -> {r}", file=sys.stderr)
            except (StopIteration, json.JSONDecodeError, OSError):
                pass
    if CURSOR_WS.exists():
        for ws in CURSOR_WS.iterdir():
            wj = ws / "workspace.json"
            if wj.exists():
                try:
                    data = json.loads(wj.read_text())
                    f = data.get("folder") or ""
                    f = f.get("path", f) if isinstance(f, dict) else str(f)
                    if f.startswith("file://"):
                        f = f[7:]
                    if f and f.startswith(str(work_root)):
                        r = Path(f).resolve()
                        if r not in cursor_paths:
                            cursor_paths.add(r)
                            if debug:
                                print(f"[dir] Cursor workspace: {ws} -> {r}", file=sys.stderr)
                except (json.JSONDecodeError, OSError):
                    pass

    vendors = frozenset((vendor_filter or ["cc", "codex", "cursor"]))
    cursor_global_has_data = False
    if "cursor" in vendors:
        gdb = get_cursor_global_db()
        if gdb and gdb.exists():
            m = get_db_metrics(gdb)
            if m["count"] or m["events"]:
                cursor_global_has_data = True
                if debug:
                    print(f"[dir] Cursor central: {gdb}", file=sys.stderr)
    all_paths = set()
    if "cc" in vendors:
        all_paths |= cc_paths
    if "codex" in vendors:
        all_paths |= codex_paths
    if "cursor" in vendors:
        all_paths |= cursor_paths

    def _is_agg(p: Path) -> bool:
        try:
            rel = p.relative_to(work_root)
            return len(rel.parts) == 1 and rel.parts[0] in AGGREGATORS
        except ValueError:
            return False

    def canonicalize(paths):
        """Keep most specific (leaf) paths; drop parent when child exists."""
        keep = set()
        for p in sorted(paths, key=lambda x: -len(x.parts)):
            if _is_agg(p) or is_excluded(p, work_root):
                continue
            skip = any(q != p and str(q).startswith(str(p) + "/") for q in keep)
            if not skip:
                keep.add(p)
        return keep

    cutoff_ms = None
    if recent_days is not None and recent_days > 0 and not debug:
        import time
        cutoff_ms = (time.time() - recent_days * 86400) * 1000

    projects = sorted({p for p in canonicalize(all_paths) if p.exists()}, key=str)
    rows = []
    for p in projects:
        try:
            rel = str(p.relative_to(work_root))
        except ValueError:
            rel = str(p)
        src = []
        if "cc" in vendors and p in cc_paths:
            src.append("CC")
        if "codex" in vendors and p in codex_paths:
            src.append("Codex")
        if "cursor" in vendors and p in cursor_paths:
            src.append("Cursor")
        if not src:
            continue
        sess_count, sess_mb, span_w = 0, 0.0, None
        has_recent = False
        m_cc, m_codex = {}, {}
        if p in cc_paths:
            m_cc = _session_metrics_cc(p, cutoff_ms)
            if not cutoff_ms or m_cc.get("max_ts", 0) >= cutoff_ms:
                has_recent = True
            sess_count += m_cc["count"]
            sess_mb += m_cc["size_mb"]
            span_w = m_cc["span_weeks"]
        if p in codex_paths:
            m_codex = _session_metrics_codex(p, cutoff_ms)
            if not cutoff_ms or m_codex.get("max_ts", 0) >= cutoff_ms:
                has_recent = True
            sess_count += m_codex["count"]
            sess_mb += m_codex["size_mb"]
            span_w = span_w or m_codex["span_weeks"]
        m_cursor = {}
        if p in cursor_paths:
            has_recent = True
            m_cursor = _session_metrics_cursor(p)
            sess_count += m_cursor["count"]
            sess_mb += m_cursor["size_mb"]
        if not debug and cutoff_ms and not has_recent:
            continue
        row = {
            "path": rel,
            "dir_path": str(p),
            "vendor": "|".join(src),
            "sess": sess_count,
            "mb": sess_mb,
            "span_weeks": span_w,
        }
        if debug:
            print(f"[scan] project {p} path={rel}", file=sys.stderr)
            if m_cc:
                print(f"  CC: sess={m_cc.get('count')} events={m_cc.get('events', 0)} mb={m_cc.get('size_mb')} span_weeks={m_cc.get('span_weeks')} days_ago={m_cc.get('days_ago')}", file=sys.stderr)
            if m_codex:
                print(f"  Codex: sess={m_codex.get('count')} events={m_codex.get('events', 0)} mb={m_codex.get('size_mb')} span_weeks={m_codex.get('span_weeks')} days_ago={m_codex.get('days_ago')}", file=sys.stderr)
            if m_cursor:
                print(f"  Cursor: sess={m_cursor.get('count')} events={m_cursor.get('events', 0)} mb={m_cursor.get('size_mb')}", file=sys.stderr)
        rows.append(row)

    if cursor_global_has_data and "cursor" in vendors:
        m_global = _session_metrics_cursor_global()
        rows.append({
            "path": "(global)",
            "dir_path": "",
            "vendor": "Cursor",
            "sess": m_global["count"],
            "mb": m_global["size_mb"],
            "span_weeks": None,
        })
        if debug:
            print(f"[scan] project (global) path=(global)", file=sys.stderr)
            print(f"  Cursor central: sess={m_global.get('count')} events={m_global.get('events', 0)} mb={m_global.get('size_mb')}", file=sys.stderr)
    return rows
