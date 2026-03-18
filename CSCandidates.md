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

