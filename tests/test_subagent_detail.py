"""Test and print detailed subagent vs main session field/size/format comparison."""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


def _run(cmd, env=None, **kw):
    env = env or os.environ.copy()
    return subprocess.run(
        [sys.executable, "-m", "main"] + cmd,
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        **kw,
    )


def _scan_env(base: Path, **extra: str) -> dict:
    reg = base / "_test_codess_registry"
    reg.mkdir(parents=True, exist_ok=True)
    return {**os.environ.copy(), "CODESS_REGISTRY": str(reg), **extra}


def test_cc_subagent_vs_main_detailed(capsys):
    """Print detailed field/size/format comparison: main vs subagent sessions."""
    mtime_ms = int((time.time() - 1) * 1000)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        work = tmp / "work"
        work.mkdir()
        proj = work / "proj"
        proj.mkdir()
        cc = tmp / "cc"
        cc.mkdir()
        slug = "-" + str(proj.resolve()).lstrip("/").replace("/", "-")
        slug_dir = cc / slug
        slug_dir.mkdir(parents=True)

        # Main session: top-level s1.jsonl
        main_file = slug_dir / "s1.jsonl"
        main_content = [
            {"type": "user", "message": {"content": [{"type": "text", "text": "Hello"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}},
        ]
        main_file.write_text("\n".join(json.dumps(r) for r in main_content))
        main_size = main_file.stat().st_size

        # Subagent session: s1/subagents/s2.jsonl (nested under parent)
        sub_dir = slug_dir / "s1" / "subagents"
        sub_dir.mkdir(parents=True)
        sub_file = sub_dir / "s2.jsonl"
        sub_content = [
            {"type": "assistant", "isSidechain": True, "agentId": "sub-1", "message": {"content": [{"type": "text", "text": "Sub task"}]}},
        ]
        sub_file.write_text("\n".join(json.dumps(r) for r in sub_content))
        sub_size = sub_file.stat().st_size

        # Index: main (s1) + subagent (s2). fullPath for main; subagent uses fallback (sess_dir)
        idx_entries = [
            {
                "projectPath": str(proj),
                "sessionId": "s1",
                "fileMtime": mtime_ms,
                "messageCount": 5,
                "isSidechain": False,
                "fullPath": str(main_file),
            },
            {
                "projectPath": str(proj),
                "sessionId": "s2",
                "fileMtime": mtime_ms,
                "messageCount": 3,
                "isSidechain": True,
                # no fullPath - fallback uses cc_dir/s2; create s2 dir for subagent
            },
        ]
        # Subagent sess_dir = cc_dir/s2; put subagent file there
        s2_dir = slug_dir / "s2"
        s2_dir.mkdir()
        sub_file2 = s2_dir / "s2.jsonl"
        sub_file2.write_text("\n".join(json.dumps(r) for r in sub_content))
        sub_size2 = sub_file2.stat().st_size
        idx_entries[1]["fullPath"] = str(sub_file2)

        (slug_dir / "sessions-index.json").write_text(json.dumps({"entries": idx_entries}))

        (tmp / "codex").mkdir()
        cursor_base = tmp / "cursor" / "User"
        cursor_base.mkdir(parents=True)
        env = _scan_env(
            tmp,
            CODESS_CC_PROJECTS=str(cc),
            CODESS_CODEX_SESSIONS=str(tmp / "codex"),
            CODESS_CURSOR_DATA=str(cursor_base),
        )

        # Scan without --subagent
        r_excl = _run(["scan", "--dir", str(work), "--out", "-"], env=env)
        assert r_excl.returncode == 0
        lines_excl = r_excl.stdout.strip().split("\n")

        # Scan with --subagent
        r_incl = _run(["scan", "--dir", str(work), "--subagent", "--out", "-"], env=env)
        assert r_incl.returncode == 0
        lines_incl = r_incl.stdout.strip().split("\n")

        # Parse and compare
        def parse_row(lines):
            if len(lines) < 2:
                return None
            parts = lines[1].split(",")
            return {"path": parts[0], "vendor": parts[1], "sess": int(parts[2]), "mb": float(parts[3])}

        row_excl = parse_row(lines_excl)
        row_incl = parse_row(lines_incl)

        # Print detailed comparison
        out = []
        out.append("=== CC Subagent vs Main: Detailed Comparison ===")
        out.append("")
        out.append("Fixture layout:")
        out.append(f"  Main:    {main_file.relative_to(slug_dir)}  size={main_size} B  format=JSONL (user/assistant)")
        out.append(f"  Subagent: {sub_file2.relative_to(slug_dir)}  size={sub_size2} B  format=JSONL (isSidechain, agentId)")
        out.append("")
        out.append("Index entries:")
        for i, e in enumerate(idx_entries):
            kind = "main" if not e.get("isSidechain") else "subagent"
            out.append(f"  [{i}] {kind}: sessionId={e['sessionId']} messageCount={e['messageCount']} isSidechain={e.get('isSidechain')} fullPath={'yes' if e.get('fullPath') else 'no'}")
        out.append("")
        out.append("Scan results:")
        out.append(f"  Exclude subagent (default): sess={row_excl['sess']} mb={row_excl['mb']}")
        out.append(f"  Include subagent (--subagent): sess={row_incl['sess']} mb={row_incl['mb']}")
        out.append("")
        out.append("Field availability:")
        out.append("  Main:    sessionId, fullPath, messageCount, fileMtime, projectPath, isSidechain=false")
        out.append("  Subagent: sessionId, fullPath, messageCount, fileMtime, projectPath, isSidechain=true")
        out.append("  Subagent JSONL: isSidechain, agentId on messages; (future) parentSessionId, parentToolCallId in session_meta")
        out.append("")
        out.append("Size: main uses fullPath; subagent uses fullPath or fallback sess_dir/**/*.jsonl")
        out.append("Format: both JSONL; same record types (user, assistant); subagent adds isSidechain, agentId")

        printed = "\n".join(out)
        print(printed, file=sys.stderr)

        assert row_excl["sess"] == 1
        assert row_incl["sess"] == 2
        assert row_incl["mb"] >= row_excl["mb"]
