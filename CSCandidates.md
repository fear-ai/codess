# CodingSess Candidate Projects — Goals, Criteria, and Analysis

**Purpose:** General inclusion and exclusion criteria for ingestion candidates. Criteria are intended to be configurable (config file or CLI args) for future search/ingest scripts.

---

## 1. Goals

- **Discover** all projects with session data from Claude Code, Codex, or Cursor
- **Prioritize** candidates with sufficient history, active codebase, and meaningful session volume. Also important is git resence and history
- **Exclude** obsolete, backup, download-only, and low-value directories, projectis, repos
- **Document** criteria so the workflow is repeatable and configurable

---

## 2. Criteria Overview

Session data is scattered across vendor-specific stores: Claude Code (`~/.claude/projects/<slug>/*.jsonl`), Codex (`~/.codex/sessions/**/*.jsonl`), and Cursor (`state.vscdb`). Not all paths in those stores correspond to active projects. General categories to exclude:

- **Moved or renamed** — old paths stale after project relocation or renaming
- **Backup/obsolete** — backup copies, dropped initiatives
- **Download/review** — OSS tools, reference repos with no meaningful work with a coding agent
- **Worktree copies** — same repo, different worktree; sessions may be split and handling TBD

Positive signals: path exists, session data present, like `.claude` in directory, listed in `~/.claude/projects`. Strong plus: a git repo, particularly on Github, recent coding tool activity, multiple tool use

---

## 3. Inclusion Criteria

| Criterion | Description | CLI option / Check |
|-----------|-------------|----------------|
| **Path exists** | Directory exists on disk | `[ -d "$path" ]` |
| **Session data present** | At least one session file or DB record for the project | CC: `~/.claude/projects/<slug>/*.jsonl`; Codex: `session_meta.cwd`; Cursor: `workspace.json` folder |
| **Session volume** | >2 sessions OR at least one session of ≥20 KB | For example, JSONL file count and sizes |
| **Git repo** | `.git` indicates versioned codebase, check recent activity| `[ -d "$path/.git" ]` / mtime or last commit or push within 30, 90 days: `stat`, `git log -1` |
| **Github remote** | given a remote check Github path | |
| **Multiple sources** | Sessions from 2+ vendors (CC, Codex, Cursor) | Cross-reference vendor stores |

---

## 4. Exclusion Criteria

| Criterion | Description |
|-----------|-------------|
| **Path gone** | Directory no longer exists |
| **Slug decode artifact** | Path decode wrong | |
| **Moved/renamed** | Project relocated or newer better version found |
| **No session data** | Git repo but no sessions in any vendor store |
| **Backup directory** | Configured backup location or pattern |
| **Review directory** | Configured review dirs, OSS tools, reference repos |
| **Redundant** | Child/subdirectory of another candidate |
| **No git repo, no Github remote** | Unversioned; may be copy or temp |
| **Worktree duplicate** | Same repo but different worktrees:; sessions may be split. Handling configurable |

---

## . Directory Taxonomy

| Category | Purpose | Configurable |
|----------|---------|--------------|
| **Aggregators** | Parent dirs; contain many projects/repos |
| **Download/review** | OSS tools, for implementation review |
| **Obsolete** | Backup copies, dropped initiatives |
| **Mixed-content** | Github clones, forks |

## . Glossary

| Term | Definition |
|------|------------|
| **Aggregator** | Parent directory containing multiple projects/repos |
| **Slug** | CC path encoding: `/Users/x/y` → `-Users-x-y` |
| **Worktree** | Git worktree; separate working copy of same repo |
| **Download/review dir** | Directory of cloned OSS repos for search/review; little or no coding work |
| **Session data** | JSONL (CC, Codex) or SQLite (Cursor) records of coding sessions |

---
