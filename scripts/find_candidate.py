#!/usr/bin/env python3
"""Ingestion candidate review: canonicalize, filter, collect metrics.
Aggregators (WP, ZK, Claw, etc.) are parent dirs; we keep leaf projects.
Metrics: weeks since last update, .git, remote status, session count/size/span.
Config: config.py (paths, dirs, exclude patterns)."""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
_src = _root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))
from codess.config import (
    AGGREGATORS,
    CC_PROJECTS,
    CODEX_SESSIONS,
    CURSOR_WS,
    EXCLUDE_REVIEW_DIRS,
    RECENT_DAYS,
    WORK,
)
from codess.helpers import is_excluded as helpers_is_excluded, slug_to_path


def path_recent(p: Path, cutoff: datetime) -> bool:
    try:
        return datetime.fromtimestamp(p.stat().st_mtime) > cutoff
    except OSError:
        return False


def is_git_repo(p: Path) -> bool:
    return (p / ".git").exists()


def weeks_since_mtime(p: Path) -> float | None:
    if not p.exists():
        return None
    try:
        return (datetime.now().timestamp() - p.stat().st_mtime) / (7 * 24 * 3600)
    except OSError:
        return None


def git_remote_status(p: Path, fetch_check: bool = False) -> str:
    """Remote status. fetch_check=True does git fetch --dry-run (slow)."""
    if not (p / ".git").exists():
        return "no-repo"
    try:
        r = subprocess.run(["git", "remote", "-v"], cwd=p, capture_output=True, text=True, timeout=5)
        if r.returncode != 0 or not r.stdout.strip():
            return "no-remote"
        if not fetch_check:
            return "has-remote"
        r2 = subprocess.run(["git", "fetch", "--dry-run"], cwd=p, capture_output=True, text=True, timeout=10)
        if r2.returncode != 0:
            err = (r2.stderr or "").lower()
            if "could not resolve" in err or "not found" in err or "404" in err or "repository not found" in err:
                return "remote-gone"
            return "fetch-fail"
        return "ok"
    except (subprocess.SubprocessError, FileNotFoundError):
        return "?"


def git_last_commit_weeks(p: Path) -> float | None:
    if not (p / ".git").exists():
        return None
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%ct"], cwd=p, capture_output=True, text=True, timeout=5)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        ts = int(r.stdout.strip())
        return (datetime.now().timestamp() - ts) / (7 * 24 * 3600)
    except (subprocess.SubprocessError, ValueError):
        return None


def is_aggregator(p: Path) -> bool:
    """True if path is an aggregator (e.g. Work/WP) - has no .git, is a known parent."""
    try:
        rel = p.relative_to(WORK)
        return len(rel.parts) == 1 and rel.parts[0] in AGGREGATORS
    except ValueError:
        return False


def is_excluded(p: Path) -> bool:
    """True if path is under backup or review dir (CSPlan §9.1, §9.2)."""
    try:
        rel = str(p.relative_to(WORK))
    except ValueError:
        return False
    # Backup: */OLD/*, */Save*
    if "/OLD/" in rel or rel.startswith("OLD/"):
        return True
    if "/Save" in rel or rel.startswith("Save"):
        return True
    # Review dirs: under CodingTools, MCP/MCPs, etc.
    for d in EXCLUDE_REVIEW_DIRS:
        if rel == d or rel.startswith(d + "/"):
            return True
    return False


def session_metrics_cc(p: Path) -> dict:
    """Main sessions only (top-level uuid.jsonl); exclude subagents (uuid/subagents/*.jsonl)."""
    slug = "-" + str(p).lstrip("/").replace("/", "-")
    cc_dir = CC_PROJECTS / slug
    count, total_bytes, min_ts, max_ts = 0, 0, float("inf"), 0.0
    if cc_dir.exists():
        for f in cc_dir.glob("*.jsonl"):
            count += 1
            try:
                total_bytes += f.stat().st_size
                mtime = f.stat().st_mtime * 1000
                min_ts = min(min_ts, mtime)
                max_ts = max(max_ts, mtime)
            except OSError:
                pass
    span = (max_ts - min_ts) / (7 * 24 * 3600 * 1000) if max_ts > min_ts else None
    return {"count": count, "size_mb": round(total_bytes / (1024 * 1024), 2), "span_weeks": round(span, 1) if span else None}


def session_metrics_codex(p: Path) -> dict:
    count, total_bytes, min_ts, max_ts = 0, 0, float("inf"), 0.0
    p_res = p.resolve()
    if CODEX_SESSIONS.exists():
        for f in CODEX_SESSIONS.rglob("*.jsonl"):
            try:
                d = json.loads(next(f.open()))
                if d.get("type") == "session_meta":
                    cwd = (d.get("payload") or {}).get("cwd", "")
                    if cwd and str(Path(cwd).resolve()) == str(p_res):
                        count += 1
                        total_bytes += f.stat().st_size
                        ts = d.get("timestamp")
                        if isinstance(ts, (int, float)):
                            ts_ms = ts * 1000 if ts < 1e12 else ts
                            if ts_ms:
                                min_ts = min(min_ts, ts_ms)
                                max_ts = max(max_ts, ts_ms)
            except (StopIteration, json.JSONDecodeError, OSError, KeyError):
                pass
    span = (max_ts - min_ts) / (7 * 24 * 3600 * 1000) if max_ts > min_ts else None
    return {"count": count, "size_mb": round(total_bytes / (1024 * 1024), 2), "span_weeks": round(span, 1) if span else None}


def main():
    cutoff = datetime.now() - timedelta(days=RECENT_DAYS)
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
                        if pp and str(Path(pp).resolve()).startswith(str(WORK)):
                            cc_paths.add(Path(pp).resolve())
                except (json.JSONDecodeError, OSError, KeyError):
                    pass
            p = Path(str(slug_to_path(d.name)))
            if str(p).startswith(str(WORK)):
                cc_paths.add(p.resolve())

    if CODEX_SESSIONS.exists():
        for f in CODEX_SESSIONS.rglob("*.jsonl"):
            try:
                d = json.loads(next(f.open()))
                if d.get("type") == "session_meta":
                    cwd = (d.get("payload") or {}).get("cwd", "")
                    if cwd and cwd.startswith(str(WORK)):
                        codex_paths.add(Path(cwd).resolve())
            except (StopIteration, json.JSONDecodeError, OSError):
                pass

    if CURSOR_WS.exists():
        for ws in CURSOR_WS.iterdir():
            wj = ws / "workspace.json"
            if wj.exists():
                try:
                    d = json.loads(wj.read_text())
                    f = d.get("folder") or ""
                    f = f.get("path", f) if isinstance(f, dict) else str(f)
                    if f.startswith("file://"):
                        f = f[7:]
                    if f and f.startswith(str(WORK)):
                        cursor_paths.add(Path(f).resolve())
                except (json.JSONDecodeError, OSError):
                    pass

    all_paths = cc_paths | codex_paths | cursor_paths

    # Canonicalize: don't keep aggregators; drop child only if non-aggregator parent in keep
    # Exclude paths under backup/review dirs (CSPlan §9)
    def canonicalize(paths):
        keep = set()
        for p in sorted(paths, key=lambda x: len(x.parts)):
            if is_aggregator(p) or is_excluded(p):
                continue
            skip = any(
                p != q and str(p).startswith(str(q) + "/")
                for q in keep
            )
            if not skip:
                keep.add(p)
        return keep

    canon_paths = canonicalize(all_paths)
    projects = sorted({p for p in canon_paths if p.exists()}, key=str)
    gone = sorted({p for p in canon_paths if not p.exists()}, key=str)

    print("=== GONE ===")
    for p in gone:
        try:
            print(" ", p.relative_to(WORK))
        except ValueError:
            print(" ", p)

    print("\n=== CANDIDATES (metrics) ===")
    print(f"{'Path':<40} {'Src':<12} {'WksM':<6} {'WksC':<6} {'Remote':<12} {'Sess':<5} {'MB':<6} {'SpanW':<6}")
    print("-" * 100)

    rows = []
    for p in projects:
        try:
            rel = p.relative_to(WORK)
        except ValueError:
            rel = p
        src = []
        if p in cc_paths:
            src.append("CC")
        if p in codex_paths:
            src.append("Codex")
        if p in cursor_paths:
            src.append("Cursor")
        src_str = "|".join(src)

        wks_mtime = weeks_since_mtime(p)
        wks_commit = git_last_commit_weeks(p)
        wks_str = f"{wks_mtime:.1f}" if wks_mtime is not None else "-"
        fetch_check = "--fetch-check" in __import__("sys").argv
        remote = git_remote_status(p, fetch_check=fetch_check) if is_git_repo(p) else "-"

        sess_count, sess_mb, span_w = 0, 0.0, None
        if p in cc_paths:
            m = session_metrics_cc(p)
            sess_count += m["count"]
            sess_mb += m["size_mb"]
            span_w = m["span_weeks"]
        if p in codex_paths:
            m = session_metrics_codex(p)
            sess_count += m["count"]
            sess_mb += m["size_mb"]
            span_w = span_w or m["span_weeks"]
        # Cursor: skip for now (would need DB scan)

        wks_c_str = f"{wks_commit:.1f}" if wks_commit is not None else "-"
        rows.append((str(rel), src_str, wks_str, wks_c_str, remote, sess_count, sess_mb, span_w))

    for r in sorted(rows, key=lambda x: (-x[5], x[0])):
        span_s = str(r[7]) if r[7] is not None else "-"
        print(f"{r[0]:<40} {r[1]:<12} {r[2]:<6} {r[3]:<6} {r[4]:<12} {r[5]:<5} {r[6]:<6} {span_s:<6}")

    # Discover more: git repos under aggregators not in our session data
    print("\n=== POTENTIAL MISSES (git repos under aggregators, no session data) ===")
    seen = {str(p) for p in projects}
    for agg in AGGREGATORS:
        agg_path = WORK / agg
        if not agg_path.exists():
            continue
        for child in agg_path.iterdir():
            if not child.is_dir():
                continue
            proj = child.resolve()
            if str(proj) in seen or is_excluded(proj):
                continue
            if not (proj / ".git").exists():
                continue
            try:
                rel = proj.relative_to(WORK)
            except ValueError:
                continue
            remote = git_remote_status(proj, fetch_check=False)
            wks_c = git_last_commit_weeks(proj)
            wks_c_str = f"{wks_c:.1f}" if wks_c is not None else "-"
            print(f"  {rel}  remote={remote}  wks_since_commit={wks_c_str}")

    print("\n=== Summary ===")
    print(f"Projects: {len(projects)} | Gone: {len(gone)}")
    print("WksM=weeks since dir mtime; WksC=weeks since last commit; Remote=git remote; Sess=session count; MB=size; SpanW=session span weeks")


def run_find(work_root: Path, vendor_filter: list[str] | None = None) -> list[dict]:
    """Discover projects with session data. Return list of dicts: path, vendor, sess, mb, span_weeks.
    vendor_filter: ['cc','codex','cursor'] or None for all."""
    # Re-run discovery with work_root
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
                            cc_paths.add(Path(pp).resolve())
                except (json.JSONDecodeError, OSError, KeyError):
                    pass
            p = Path(str(slug_to_path(d.name)))
            if str(p).startswith(str(work_root)):
                cc_paths.add(p.resolve())
    if CODEX_SESSIONS.exists():
        for f in CODEX_SESSIONS.rglob("*.jsonl"):
            try:
                d = json.loads(next(f.open()))
                if d.get("type") == "session_meta":
                    cwd = (d.get("payload") or {}).get("cwd", "")
                    if cwd and cwd.startswith(str(work_root)):
                        codex_paths.add(Path(cwd).resolve())
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
                        cursor_paths.add(Path(f).resolve())
                except (json.JSONDecodeError, OSError):
                    pass

    vendors = frozenset((vendor_filter or ["cc", "codex", "cursor"]))
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
        keep = set()
        for p in sorted(paths, key=lambda x: len(x.parts)):
            if _is_agg(p) or helpers_is_excluded(p, work_root):
                continue
            skip = any(p != q and str(p).startswith(str(q) + "/") for q in keep)
            if not skip:
                keep.add(p)
        return keep

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
        if p in cc_paths:
            m = session_metrics_cc(p)
            sess_count += m["count"]
            sess_mb += m["size_mb"]
            span_w = m["span_weeks"]
        if p in codex_paths:
            m = session_metrics_codex(p)
            sess_count += m["count"]
            sess_mb += m["size_mb"]
            span_w = span_w or m["span_weeks"]
        rows.append({
            "path": rel,
            "vendor": "|".join(src),
            "sess": sess_count,
            "mb": sess_mb,
            "span_weeks": span_w,
        })
    return rows


if __name__ == "__main__":
    main()
