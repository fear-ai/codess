"""Scan: discover projects with session data from CC, Codex, Cursor."""

import json
import logging
import time
from datetime import datetime
from pathlib import Path

from codess.config import AGGREGATORS, BMB, CC_PROJECTS, CURSOR_WS
from codess.cursor_source import (
    get_db_metrics,
    get_global_db as get_cursor_global_db,
    get_project_composer_headers,
    get_workspace_dbs as get_cursor_workspace_dbs,
    get_workspace_ids as get_cursor_workspace_ids,
)
from codess.helpers import is_excluded, local_path_from_uri, slug_to_path
from codess.codex_source import build_session_index as build_codex_session_index
from codess.codex_source import get_session_files as get_codex_session_files
from codess.project import get_cc_session_dir

log = logging.getLogger(__name__)


def _record_diagnostic(
    diagnostics: dict | None,
    category: str,
    path: Path,
    message: str,
) -> None:
    """Record a source diagnostic once per command, even across multiple roots."""
    if diagnostics is None:
        return
    seen = diagnostics.setdefault("_seen", set())
    key = (category, str(path.resolve()))
    if key in seen:
        return
    seen.add(key)
    diagnostics[category] = diagnostics.get(category, 0) + 1
    log.warning("Scan source issue at %s: %s", path, message)


def _record_invalid_keys(
    diagnostics: dict | None,
    path: Path,
    count: int,
) -> None:
    if diagnostics is None or not count:
        return
    seen = diagnostics.setdefault("_invalid_key_sources", set())
    key = str(path.resolve())
    if key in seen:
        return
    seen.add(key)
    diagnostics["invalid_keys"] = diagnostics.get("invalid_keys", 0) + count


def _record_count(diagnostics: dict | None, category: str, count: int) -> None:
    if diagnostics is not None and count:
        diagnostics[category] = diagnostics.get(category, 0) + count


def _days_ago(max_ts: float) -> float | None:
    """(now - max_ts) in days. None if max_ts is 0 or invalid."""
    if not max_ts:
        return None
    return round((time.time() * 1000 - max_ts) / (24 * 3600 * 1000), 1)


def _session_metrics_cc(p: Path, cutoff_ms: float | None = None, subagent: bool = False) -> dict:
    """Use sessions-index.json when present; else top-level *.jsonl. Exclude subagents unless subagent. cutoff_ms: only count sessions with mtime >= cutoff."""
    cc_dir = get_cc_session_dir(p)
    count, total_bytes, events, min_ts, max_ts = 0, 0, 0, float("inf"), 0.0
    stale_index_entries = 0
    main_sessions = 0
    subagent_sessions = 0
    p_res = str(p.resolve())
    if cc_dir is not None and cc_dir.exists():
        idx = cc_dir / "sessions-index.json"
        if idx.exists():
            try:
                data = json.loads(idx.read_text())
                for e in data.get("entries", []):
                    if str(Path(e.get("projectPath", "")).resolve()) != p_res:
                        continue
                    fp = e.get("fullPath")
                    if fp and not Path(fp).is_file():
                        stale_index_entries += 1
                        continue
                    mtime = e.get("fileMtime") or 0
                    if cutoff_ms and mtime < cutoff_ms:
                        continue
                    if e.get("isSidechain"):
                        subagent_sessions += 1
                        if not subagent:
                            continue
                    else:
                        main_sessions += 1
                    count += 1
                    events += e.get("messageCount", 0)
                    if mtime:
                        min_ts = min(min_ts, mtime)
                        max_ts = max(max_ts, mtime)
                    sid = e.get("sessionId", "")
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
            main_files = list(cc_dir.glob("*.jsonl"))
            nested_files = list(cc_dir.glob("*/subagents/**/*.jsonl"))
            subagent_sessions = len(nested_files)
            selected = [(path, False) for path in main_files]
            if subagent:
                selected.extend((path, True) for path in nested_files)
            for f, is_subagent in selected:
                try:
                    mtime = f.stat().st_mtime * 1000
                    if cutoff_ms and mtime < cutoff_ms:
                        continue
                    count += 1
                    if not is_subagent:
                        main_sessions += 1
                    total_bytes += f.stat().st_size
                    min_ts = min(min_ts, mtime)
                    max_ts = max(max_ts, mtime)
                except OSError:
                    pass
    span = (max_ts - min_ts) / (7 * 24 * 3600 * 1000) if max_ts > min_ts else None
    if cc_dir is not None and not subagent_sessions:
        subagent_sessions = len(list(cc_dir.glob("*/subagents/**/*.jsonl")))
    return {"count": count, "events": events, "size_mb": round(BMB(total_bytes), 2), "span_weeks": round(span, 1) if span else None, "max_ts": max_ts, "days_ago": _days_ago(max_ts), "stale_index_entries": stale_index_entries, "main_sessions": main_sessions, "subagent_sessions_available": subagent_sessions, "subagents_included": subagent}


def _session_metrics_codex(
    p: Path, cutoff_ms: float | None = None,
    *, codex_index: list[dict] | None = None,
) -> dict:
    count, total_bytes, events, min_ts, max_ts = 0, 0, 0, float("inf"), 0.0
    p_res = str(p.resolve())
    by_path = {str(item.get("path")): item for item in (codex_index or [])}
    for f in get_codex_session_files(p, index=codex_index):
        try:
            item = by_path.get(str(f.resolve()), {})
            cwd = str(item.get("cwd") or "")
            if not cwd or str(Path(cwd).resolve()) != p_res:
                continue
            ts = item.get("timestamp")
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
            total_bytes += int(item.get("size", 0))
            cached_count = item.get("record_count")
            if isinstance(cached_count, int):
                events += cached_count
            else:
                try:
                    with f.open() as fp:
                        events += sum(1 for line in fp if line.strip())
                except OSError:
                    pass
            if ts_ms:
                min_ts = min(min_ts, ts_ms)
                max_ts = max(max_ts, ts_ms)
        except (StopIteration, json.JSONDecodeError, OSError, KeyError):
            pass
    span = (max_ts - min_ts) / (7 * 24 * 3600 * 1000) if max_ts > min_ts else None
    return {"count": count, "events": events, "size_mb": round(BMB(total_bytes), 2), "span_weeks": round(span, 1) if span else None, "max_ts": max_ts, "days_ago": _days_ago(max_ts)}


def _session_metrics_cursor(p: Path) -> dict:
    """Workspace DBs for project. sess=composers, events=bubbles, size=db bytes."""
    dbs = get_cursor_workspace_dbs(p)
    count, events, total_bytes, invalid_keys = 0, 0, 0, 0
    header_count, timed_header_count = 0, 0
    min_ts, max_ts = float("inf"), 0.0
    errors = []
    for db in dbs:
        m = get_db_metrics(db)
        count += m["count"]
        events += m["events"]
        total_bytes += m["size_bytes"]
        invalid_keys += m.get("invalid_keys", 0)
        header_count += m.get("header_count", 0)
        timed_header_count += m.get("timed_header_count", 0)
        if m.get("min_ts") is not None:
            min_ts = min(min_ts, m["min_ts"])
        if m.get("max_ts") is not None:
            max_ts = max(max_ts, m["max_ts"])
        if m.get("error"):
            errors.append(f"{db}: {m['error']}")
    workspace_ids = set(get_cursor_workspace_ids(p))
    global_db = get_cursor_global_db()
    if workspace_ids and global_db:
        composer_ids = set(get_project_composer_headers(global_db, p))
        if composer_ids:
            m = get_db_metrics(global_db, composer_ids)
            count += m["count"]
            events += m["events"]
            total_bytes += m["size_bytes"]
            invalid_keys += m.get("invalid_keys", 0)
            header_count += m.get("header_count", 0)
            timed_header_count += m.get("timed_header_count", 0)
            if m.get("min_ts") is not None:
                min_ts = min(min_ts, m["min_ts"])
            if m.get("max_ts") is not None:
                max_ts = max(max_ts, m["max_ts"])
            if m.get("error"):
                errors.append(f"{global_db}: {m['error']}")
    span = (max_ts - min_ts) / (7 * 24 * 3600 * 1000) if max_ts > min_ts else None
    return {"count": count, "events": events, "size_mb": round(BMB(total_bytes), 2), "span_weeks": round(span, 1) if span else None, "max_ts": max_ts or None, "days_ago": _days_ago(max_ts), "invalid_keys": invalid_keys, "header_count": header_count, "timed_header_count": timed_header_count, "errors": errors}


def _session_metrics_cursor_global() -> dict:
    """Central/global DB. No project filter."""
    db = get_cursor_global_db()
    if not db:
        return {"count": 0, "events": 0, "size_mb": 0.0, "span_weeks": None, "max_ts": None, "days_ago": None}
    m = get_db_metrics(db)
    min_ts, max_ts = m.get("min_ts"), m.get("max_ts")
    span = (max_ts - min_ts) / (7 * 24 * 3600 * 1000) if min_ts is not None and max_ts is not None and max_ts > min_ts else None
    return {"count": m["count"], "events": m["events"], "size_mb": round(BMB(m["size_bytes"]), 2), "span_weeks": round(span, 1) if span else None, "max_ts": max_ts, "days_ago": _days_ago(max_ts), "invalid_keys": m.get("invalid_keys", 0), "header_count": m.get("header_count", 0), "timed_header_count": m.get("timed_header_count", 0), "errors": [m["error"]] if m.get("error") else []}


def _has_any_sessions(
    project: Path,
    cc_paths: set,
    codex_paths: set,
    cursor_paths: set,
    subagent: bool,
    codex_index: list | None,
) -> bool:
    """Report whether a Project has any retained Session, ignoring recency.

    Used only to distinguish "hidden by the time window" from "no coding
    work", so an omission can be reported rather than looked like absence.
    """
    if project in cc_paths and _session_metrics_cc(project, None, subagent)["count"]:
        return True
    if project in codex_paths and _session_metrics_codex(
        project, None, codex_index=codex_index
    )["count"]:
        return True
    return bool(project in cursor_paths and _session_metrics_cursor(project)["count"])


def walk_sessions(
    work_root: Path,
    vendor_filter: list[str] | None = None,
    recent_days: int | None = None,
    debug: bool = False,
    subagent: bool = False,
    diagnostics: dict | None = None,
    include_cursor_global: bool = True,
    codex_index: list[dict] | None = None,
) -> list[dict]:
    """Discover projects with session data. Return list of dicts: path, vendor, sess, mb, span_weeks.
    recent_days: if set, only include sessions from last N days (CODESS_DAYS).
    debug: print each dir visited with findings; include all projects regardless of filters."""
    import sys
    work_root = work_root.resolve()
    vendors = frozenset((vendor_filter or ["cc", "codex", "cursor"]))
    cc_paths, codex_paths, cursor_paths = set(), set(), set()

    def in_work_root(raw_path: str) -> bool:
        try:
            Path(raw_path).resolve().relative_to(work_root)
            return True
        except ValueError:
            return False

    if "cc" in vendors and CC_PROJECTS.exists():
        # An exact root may link to its historical Claude storage slug after
        # the checkout itself was relocated.
        linked_cc_dir = get_cc_session_dir(work_root)
        if linked_cc_dir is not None:
            cc_paths.add(work_root)
            if debug:
                print(f"[dir] CC source link: {linked_cc_dir} -> {work_root}", file=sys.stderr)
        for d in CC_PROJECTS.iterdir():
            if not d.is_dir():
                continue
            idx = d / "sessions-index.json"
            if idx.exists():
                try:
                    data = json.loads(idx.read_text())
                    entries = data.get("entries", [])
                    if not isinstance(entries, list):
                        raise TypeError("entries must be a list")
                    for e in entries:
                        if not isinstance(e, dict):
                            continue
                        pp = e.get("projectPath")
                        if pp and in_work_root(str(pp)):
                            r = Path(pp).resolve()
                            if r not in cc_paths:
                                cc_paths.add(r)
                                if debug:
                                    print(f"[dir] CC dir: {d} -> {r}", file=sys.stderr)
                except (json.JSONDecodeError, KeyError, TypeError) as exc:
                    _record_diagnostic(
                        diagnostics, "malformed_sources", idx, str(exc)
                    )
                except OSError as exc:
                    _record_diagnostic(
                        diagnostics, "failed_sources", idx, str(exc)
                    )
            p = Path(str(slug_to_path(d.name)))
            if in_work_root(str(p)):
                r = p.resolve()
                if r not in cc_paths:
                    cc_paths.add(r)
                    if debug:
                        print(f"[dir] CC dir: {d} -> {r}", file=sys.stderr)
    if "codex" in vendors:
        if codex_index is None:
            codex_index = build_codex_session_index(include_record_counts=True)
        for item in codex_index:
            cwd = str(item.get("cwd") or "")
            if cwd and in_work_root(cwd):
                r = Path(cwd).resolve()
                if r not in codex_paths:
                    codex_paths.add(r)
                    if debug:
                        print(f"[dir] Codex file: {item.get('path')} -> {r}", file=sys.stderr)
    if "cursor" in vendors and CURSOR_WS.exists():
        # Exact-root scans must honor the same reviewed source links as
        # ingestion.  A remote or historical Cursor workspace can remain a
        # valid source selection even though its workspace.json URI cannot be
        # interpreted as a current local child of the Project directory.
        linked_workspace_ids = get_cursor_workspace_ids(work_root)
        if linked_workspace_ids:
            cursor_paths.add(work_root)
            if debug:
                print(
                    "[dir] Cursor source link: "
                    f"{','.join(linked_workspace_ids)} -> {work_root}",
                    file=sys.stderr,
                )
        for ws in CURSOR_WS.iterdir():
            wj = ws / "workspace.json"
            if wj.exists():
                try:
                    data = json.loads(wj.read_text())
                    local_folder = local_path_from_uri(data.get("folder"))
                    if local_folder and in_work_root(str(local_folder)):
                        r = local_folder
                        if r not in cursor_paths:
                            cursor_paths.add(r)
                            if debug:
                                print(f"[dir] Cursor workspace: {ws} -> {r}", file=sys.stderr)
                except (json.JSONDecodeError, TypeError) as exc:
                    _record_diagnostic(
                        diagnostics, "malformed_sources", wj, str(exc)
                    )
                except OSError as exc:
                    _record_diagnostic(
                        diagnostics, "failed_sources", wj, str(exc)
                    )

    cursor_global_has_data = False
    if include_cursor_global and "cursor" in vendors:
        gdb = get_cursor_global_db()
        if gdb and gdb.exists():
            m = get_db_metrics(gdb)
            _record_invalid_keys(
                diagnostics, gdb, int(m.get("invalid_keys", 0))
            )
            if m.get("error"):
                _record_diagnostic(
                    diagnostics, "failed_sources", gdb, str(m["error"])
                )
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

    # Attribute a nested workspace to an already-observed Git-root Project
    # unless the nested path is itself a repository. This keeps workspace
    # granularity from hiding the repository-level Claude/Codex evidence.
    live_paths = {path for path in all_paths if path.exists()}

    def project_boundary(path: Path) -> Path:
        candidate = path
        while candidate == work_root or candidate.is_relative_to(work_root):
            if (candidate / ".git").exists():
                return candidate
            if candidate == work_root:
                break
            candidate = candidate.parent
        parents = [
            candidate for candidate in live_paths
            if candidate != path
            and (candidate / ".git").exists()
            and path.is_relative_to(candidate)
        ]
        return max(parents, key=lambda item: len(item.parts)) if parents else path

    cc_paths = {project_boundary(path) for path in cc_paths}
    codex_paths = {project_boundary(path) for path in codex_paths}
    cursor_paths = {project_boundary(path) for path in cursor_paths}
    all_paths = cc_paths | codex_paths | cursor_paths

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

    # Recency is a selection, not a diagnostic: `debug` must not change which
    # Projects are reported, or a reader cannot trust a scan they did not run
    # with it. Projects excluded by the window are counted and reported.
    cutoff_ms = None
    if recent_days is not None and recent_days > 0:
        import time
        cutoff_ms = (time.time() - recent_days * 86400) * 1000
    excluded_by_recency = 0

    projects = sorted(canonicalize({p for p in all_paths if p.exists()}), key=str)
    rows = []
    for p in projects:
        try:
            rel = str(p.relative_to(work_root))
        except ValueError:
            rel = str(p)
        src = []
        sess_count, sess_mb, span_w = 0, 0.0, None
        has_recent = False
        m_cc, m_codex = {}, {}
        if p in cc_paths:
            m_cc = _session_metrics_cc(p, cutoff_ms, subagent)
            _record_count(
                diagnostics, "stale_index_entries",
                int(m_cc.get("stale_index_entries", 0)),
            )
            if m_cc["count"]:
                src.append("CC")
            if not cutoff_ms or m_cc.get("max_ts", 0) >= cutoff_ms:
                has_recent = True
            sess_count += m_cc["count"]
            sess_mb += m_cc["size_mb"]
            span_w = m_cc["span_weeks"]
        if p in codex_paths:
            m_codex = _session_metrics_codex(
                p, cutoff_ms, codex_index=codex_index
            )
            if m_codex["count"]:
                src.append("Codex")
            if not cutoff_ms or m_codex.get("max_ts", 0) >= cutoff_ms:
                has_recent = True
            sess_count += m_codex["count"]
            sess_mb += m_codex["size_mb"]
            span_w = span_w or m_codex["span_weeks"]
        m_cursor = {}
        if p in cursor_paths:
            m_cursor = _session_metrics_cursor(p)
            # A workspace DB with zero recognized headers is still a useful
            # empty/legacy detection result, unlike a missing transcript file.
            src.append("Cursor")
            _record_invalid_keys(
                diagnostics, p, int(m_cursor.get("invalid_keys", 0))
            )
            for error in m_cursor.get("errors", []):
                db_name, _, detail = error.partition(": ")
                _record_diagnostic(
                    diagnostics,
                    "failed_sources",
                    Path(db_name),
                    detail or error,
                )
            if not cutoff_ms or m_cursor.get("max_ts") is None or m_cursor["max_ts"] >= cutoff_ms:
                has_recent = True
            sess_count += m_cursor["count"]
            sess_mb += m_cursor["size_mb"]
            span_w = span_w or m_cursor["span_weeks"]
        if not src:
            # No sessions survived selection. When a window is active, check
            # whether the Project has work at all: a Project hidden by the
            # window is a different outcome from one with no coding work, and
            # a reader cannot tell them apart from an empty result.
            if cutoff_ms and _has_any_sessions(p, cc_paths, codex_paths, cursor_paths, subagent, codex_index):
                excluded_by_recency += 1
            continue
        if cutoff_ms and not has_recent:
            excluded_by_recency += 1
            continue
        row = {
            "path": rel,
            "dir_path": str(p),
            "vendor": "|".join(src),
            "sess": sess_count,
            "mb": sess_mb,
            "span_weeks": span_w,
            "source_metrics": {
                **({"Claude": {
                    "sessions": m_cc.get("count", 0),
                    "main_sessions": m_cc.get("main_sessions", 0),
                    "subagent_sessions_available": m_cc.get(
                        "subagent_sessions_available", 0
                    ),
                    "subagents_included": m_cc.get("subagents_included", False),
                    "observed_records": m_cc.get("events", 0),
                    "record_basis": "claude_index_message_count",
                    "size_mb": m_cc.get("size_mb", 0),
                }} if m_cc else {}),
                **({"Codex": {
                    "sessions": m_codex.get("count", 0),
                    "observed_records": m_codex.get("events", 0),
                    "record_basis": "codex_jsonl_lines",
                    "size_mb": m_codex.get("size_mb", 0),
                }} if m_codex else {}),
                **({"Cursor": {
                    "sessions": m_cursor.get("count", 0),
                    "observed_records": m_cursor.get("events", 0),
                    "record_basis": "cursor_raw_bubble_rows",
                    "size_mb": m_cursor.get("size_mb", 0),
                    "workspace_trace": True,
                }} if m_cursor else {}),
            },
        }
        if debug:
            print(f"[scan] project {p} path={rel}", file=sys.stderr)
            if m_cc:
                print(f"  CC: sess={m_cc.get('count')} events={m_cc.get('events', 0)} mb={m_cc.get('size_mb')} span_weeks={m_cc.get('span_weeks')} days_ago={m_cc.get('days_ago')}", file=sys.stderr)
            if m_codex:
                print(f"  Codex: sess={m_codex.get('count')} events={m_codex.get('events', 0)} mb={m_codex.get('size_mb')} span_weeks={m_codex.get('span_weeks')} days_ago={m_codex.get('days_ago')}", file=sys.stderr)
            if m_cursor:
                print(f"  Cursor: sess={m_cursor.get('count')} events={m_cursor.get('events', 0)} mb={m_cursor.get('size_mb')} span_weeks={m_cursor.get('span_weeks')} days_ago={m_cursor.get('days_ago')} headers={m_cursor.get('header_count', 0)} timed_headers={m_cursor.get('timed_header_count', 0)}", file=sys.stderr)
        rows.append(row)

    if include_cursor_global and cursor_global_has_data and "cursor" in vendors:
        m_global = _session_metrics_cursor_global()
        global_recent = not cutoff_ms or m_global.get("max_ts") is None or m_global["max_ts"] >= cutoff_ms
        if global_recent:
            rows.append({
                "path": "(global)",
                "dir_path": "",
                "vendor": "Cursor",
                "sess": m_global["count"],
                "mb": m_global["size_mb"],
                "span_weeks": m_global["span_weeks"],
            })
            if debug:
                print("[scan] project (global) path=(global)", file=sys.stderr)
                print(f"  Cursor central: sess={m_global.get('count')} events={m_global.get('events', 0)} mb={m_global.get('size_mb')} span_weeks={m_global.get('span_weeks')} days_ago={m_global.get('days_ago')} headers={m_global.get('header_count', 0)} timed_headers={m_global.get('timed_header_count', 0)}", file=sys.stderr)
    if excluded_by_recency:
        _record_count(diagnostics, "projects_outside_recency_window", excluded_by_recency)
    return rows
