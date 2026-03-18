# CodingSess Candidate Projects — Goals, Criteria, and Analysis

**Purpose:** General inclusion and exclusion criteria for ingestion candidates. Configurable (config file or CLI args) for future search/ingest scripts. Project-specific conventions (paths, directory names) live in the implementation plan.

---

## 1. Goals

- **Discover** all projects with session data from Claude Code, Codex, or Cursor
- **Prioritize** candidates with sufficient history, active codebase, meaningful session volume, git presence, and recent activity
- **Exclude** obsolete, backup, download-only, and low-value directories
- **Document** criteria so the workflow is repeatable and configurable

---

## 2. Narrative

Session data is scattered across vendor-specific stores: Claude Code (`~/.claude/projects/<slug>/*.jsonl`), Codex (`~/.codex/sessions/**/*.jsonl`), and Cursor (`state.vscdb`). Discovery is nontrivial: not all paths correspond to active projects; slug encoding is lossy (hyphen→slash); worktrees split sessions; mixed-content dirs contain both active work and OSS clones. §3–§4 define inclusion/exclusion criteria and directory categories.

---

## 3. Criteria

### Inclusion

| Criterion | Description | Check |
|-----------|-------------|-------|
| Path exists | Directory exists on disk | `[ -d "$path" ]` |
| Session data present | At least one session file or DB record for the project | CC: `~/.claude/projects/<slug>/*.jsonl`; Codex: `session_meta.cwd`; Cursor: `workspace.json` folder |
| Session volume | >2 sessions OR at least one session of ≥20 KB | JSONL file count and sizes |
| Git repo | `.git` indicates versioned codebase; check recent activity | `[ -d "$path/.git" ]` / mtime or last commit within 30, 90 days: `stat`, `git log -1` |
| Github remote | Given a remote, check Github path | |
| Multiple sources | Sessions from 2+ vendors (CC, Codex, Cursor) | Cross-reference vendor stores |
| Not under backup/obsolete | Not in configured backup dirs | Path check; config |
| Not download/review | Not in configured review dirs | Path check; config |

### Exclusion

| Criterion | Description |
|-----------|-------------|
| Path gone | Directory no longer exists |
| Slug decode artifact | Path from slug decode wrong (hyphen→slash lossy) |
| Moved/renamed | Project relocated or newer better version found |
| Backup directory | Configured backup location or pattern |
| Review directory | Configured review dirs, OSS tools, reference repos |
| Plural/aggregate names | Often collections of downloaded repos |
| No session data | Git repo but no sessions in any vendor store |
| No git repo, no Github remote | Unversioned; may be copy or temp |
| Redundant | Child/subdirectory of another candidate |
| Worktree duplicate | Same repo but different worktrees; sessions may be split. Handling configurable |

---

## 4. Directory Categories

| Category | Purpose | Configurable |
|----------|---------|--------------|
| **Aggregators** | Parent dirs; contain many projects/repos | Yes |
| **Download/review** | OSS tools, for implementation review | Yes |
| **Obsolete/backup** | Backup copies, dropped initiatives | Yes |
| **Mixed-content** | Clones, forks, some active; per-project | Yes |

---

## 5. Analysis Tiers

| Tier | Criteria |
|------|----------|
| **Strong** | Session data + recent + git |
| **Marginal** | Some data; no git or low volume |
| **Store-only, 0 sessions** | In vendor store but 0 sessions in metrics |
| **Gone** | Path does not exist |
| **Potential misses** | Git repo, no session data |

---

## 6. Recommendations

1. **Expand CC discovery:** Scan for `.claude` in dirs + `~/.claude/projects` + `sessions-index.json`; decode slugs; match to existing paths
2. **Mixed-content dirs:** Manual review; include if session data found; exclude dumping grounds
3. **Canonicalize:** Prefer current path over relocated; resolve worktree vs main repo

---

## 7. Glossary

| Term | Definition |
|------|------------|
| **Slug** | CC path encoding: `/Users/x/y` → `-Users-x-y` |
| **Worktree** | Git worktree; separate working copy of same repo |
| **Download/review dir** | Directory of cloned OSS repos for search/review; little or no coding work |
| **Session data** | JSONL (CC, Codex) or SQLite (Cursor) records of coding sessions |

---

## Appendix A: Storage, Layout, and Formats by Vendor

### Claude Code (CC)

| Aspect | Details |
|--------|---------|
| **Storage** | `~/.claude/projects/<slug>/` |
| **Layout** | One dir per project; slug = path encoded (hyphen→slash) |
| **Format** | JSONL (one file per session). Each line: `type`, `payload`, `timestamp` (ms) |
| **Discovery** | Decode `slug` → path; match to existing dirs |
| **Timestamps** | Unix ms in JSONL; absolute |

### Codex

| Aspect | Details |
|--------|---------|
| **Storage** | `~/.codex/sessions/**/*.jsonl` |
| **Layout** | Flat or nested; `session_meta.cwd` identifies project |
| **Format** | JSONL. First line often `session_meta` with `payload.cwd` |
| **Discovery** | Scan JSONL; match `cwd` to project path |
| **Timestamps** | Unix ms in JSONL; absolute |

### Cursor

| Aspect | Details |
|--------|---------|
| **Storage** | `state.vscdb` (SQLite) in `workspaceStorage/<hash>/` or `globalStorage/` |
| **Layout** | One DB per workspace; hash from `workspace.json` folder path |
| **Format** | Two tables: `ItemTable` (VSCode key-value), `cursorDiskKV` (chat bubbles) |
| **Discovery** | `workspace.json` → `folder.path`; match to project path |
| **Timestamps** | `bubbleId.timingInfo.clientStartTime` = ms since session start (relative); `ItemTable` keys for absolute dates |

**Cursor format variants:**

| Variant | Source | When | Notes |
|---------|--------|------|-------|
| **Old** | ItemTable `workbench.panel.aichat.view.aichat.chatdata` | Pre–v44.9 | workspaceStorage only; tab.timestamp |
| **New** | cursorDiskKV `bubbleId:*`, `composerData`, `composer.content` | v44.9+ | globalStorage; clientStartTime relative |

**Workspace hash:** `birthtime_ms` (macOS/Windows), inode (Linux) of `workspace.json` folder.

---

## Appendix B: External References and OSS Tools

### OSS Cursor Decode Tools

| Project | URL | Language | Notes |
|---------|-----|----------|-------|
| **legel/Xinihiko** | [gist](https://gist.github.com/legel/ebd0bbc012bf019a1db5212b825e7d16) | Python | composerData or bubbleId; clientStartTime/1000 as datetime (produces 1970 if relative) |
| **cursor-chat-browser** | [thomas-pedersen/cursor-chat-browser](https://github.com/thomas-pedersen/cursor-chat-browser) | TypeScript | Browse, search, export; v44.9+ globalStorage |
| **cursor-chat-export** | [somogyijanos/cursor-chat-export](https://github.com/somogyijanos/cursor-chat-export) | Python | ItemTable `workbench.panel.aichat` (older format); workspaceStorage only; archived; last pushed 2024-08-30 |
| **cursor-view** | [saharmor/cursor-view](https://github.com/saharmor/cursor-view) | — | Browse, search, export |
| **cursor-export** | [WooodHead/cursor-export](https://github.com/WooodHead/cursor-export) | — | Export |

**cursor-chat-export archived vs updated:** Repo marked `archived` (owner no longer maintains). `updated_at` from GitHub reflects metadata (issues, PRs, Dependabot). Last code push 2024-08-30; no code changes since.

### VSCode References

| Resource | URL | Notes |
|----------|-----|-------|
| VSCode storage.ts | [microsoft/vscode storage.ts](https://github.com/microsoft/vscode/blob/main/src/vs/platform/storage/common/storage.ts) | ItemTable key-value |
| VSCode global state | [mattreduce: Exploring VS Code's Global State](https://mattreduce.com/posts/vscode-global-state/) | ItemTable schema, extension state |
| Workspace hash | [Stack Overflow: workspaceStorage folder](https://stackoverflow.com/questions/74155386/how-does-visual-studio-code-determine-the-workspacestorage-folder-for-a-given-w) | birthtime_ms (macOS/Windows), inode (Linux) |

### Cursor Forum / Docs

| Topic | URL |
|-------|-----|
| state.vscdb questions | [forum.cursor.com/questions-about-state-vscdb](https://forum.cursor.com/t/questions-about-state-vscdb/47299) |
| Chat history folder | [forum.cursor.com/chat-history-folder](https://forum.cursor.com/t/chat-history-folder/7653) |
| Export guide | [forum.cursor.com/exporting-chats-prompts](https://forum.cursor.com/t/guide-5-steps-exporting-chats-prompts-from-cursor/2825) |

---

## Appendix C: Fresh Cursor Ingest and Filtering

### Setting Aside Cursor Sessions for a Clean Test Run

1. **Backup current store:** `cp .coding-sess/sessions.db .coding-sess/sessions.db.bak`
2. **Clear Cursor ingest state:** Edit `ingest_state.json`; remove keys starting with `cursor:` (or delete the file to reset all).
3. **Option A — Remove only Cursor rows:** `DELETE FROM events WHERE session_id IN (SELECT id FROM sessions WHERE source='Cursor'); DELETE FROM sessions WHERE source='Cursor';`
4. **Option B — Replace DB:** `rm .coding-sess/sessions.db`; next ingest recreates it.
5. **Run test sessions:** Use Cursor in a project; generate 2–3 sessions with ≥10 events, ≥10 min, ≥10 KB.
6. **Re-ingest:** `session-ingest --source cursor --force` (or with `--cursor-global` if using global DB).

### First-Try Filter Thresholds

| Filter | Threshold | Rationale |
|--------|-----------|-----------|
| Duration | < 10 min | Short sessions; low signal |
| Event count | < 10 | Minimal interaction |
| Content size | < 10 KB | Sparse or command-only |

**Sessions without timestamps:** Not uniformly short. Observed: 83 no-ts vs 20 with-ts; no-ts range 1–12,208 events, 0–768 KB. 69/83 no-ts have < 10 KB content; 9/83 have < 10 events. Timestamp absence is format-related (e.g. older bubbles or missing timingInfo), not length-related.

---

## Appendix D: Store Layout — Per-Vendor Per-Directory DBs

Until we have a superset schema, stable decodes, and clean filters: use **per vendor, per directory/repo** DBs. One `sessions.db` per project per vendor (e.g. `sessions_cc.db`, `sessions_codex.db`, `sessions_cursor.db`) or per-aggregator layout. Avoid merging into a single store until schema and decode pipelines are settled.

