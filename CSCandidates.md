# CodingSess Candidate Projects — Goals, Criteria, and Analysis

**Purpose:** Identify and evaluate project/directory/repo candidates for ingestion into CodingSess. Aggregate inclusion and exclusion criteria, qualitative and quantitative analysis, and comparison tables.

---

## 1. Goals

- **Discover** all projects under `~/Work` that have session data from Claude Code, Codex, or Cursor
- **Prioritize** candidates with sufficient history, active codebase, and meaningful session volume
- **Exclude** obsolete, backup, download-only, and low-value directories
- **Document** criteria so the workflow is repeatable and auditable

---

## 2. Narrative

Session data is scattered across vendor-specific stores: Claude Code (`~/.claude/projects/<slug>/*.jsonl`), Codex (`~/.codex/sessions/**/*.jsonl`), and Cursor (`state.vscdb` in workspace or global storage). Not all paths in those stores correspond to active projects. Some are:

- **Moved or renamed** (e.g. WP/spank-py → Spank/spank-py)
- **Worktree copies** (e.g. Claw/openclaw-docs of Claw/openclaw)
- **Download/review** directories (OSS tools, no meaningful coding work)
- **Backup/obsolete** (OLD, Save*)
- **Cloned or forked** repos never worked on with a coding agent

Conversely, projects worked on with Claude Code may not appear in `~/.claude/projects` if the slug format changed or sessions were stored elsewhere. Presence of `.claude` in a directory and entries in `~/.claude/projects` or `sessions-index.json` help surface additional candidates.

**CodingSess vs CodeSess:** The real project and repo is CodingSess; the directory `CodingSess` has the codebase and more recent modifications.

---

## 3. Inclusion Criteria (Positive Signs)

| Criterion | Description | Source / Check |
|-----------|-------------|----------------|
| **Session data present** | At least one session file or DB record for the project | CC: `~/.claude/projects/<slug>/*.jsonl`; Codex: `session_meta.cwd`; Cursor: `workspace.json` folder |
| **Path exists** | Directory exists on disk | `[ -d "$path" ]` |
| **Git repo** | Has `.git`; indicates versioned codebase | `[ -d "$path/.git" ]` |
| **Recent activity** | Dir mtime or last commit within 90 days | `stat`, `git log -1` |
| **Multiple sources** | Sessions from 2+ vendors (CC, Codex, Cursor) | Cross-reference vendor stores |
| **Session volume** | ≥2 sessions or ≥1 MB total | Count JSONL files; sum sizes |
| **`.claude` in dir** | Project used with Claude Code | `[ -d "$path/.claude" ]` |
| **Listed in ~/.claude** | Slug in `~/.claude/projects/` or `sessions-index.json` | List `~/.claude/projects/*` |
| **Not under OLD/Save*** | Not in obsolete or backup location | Path check |
| **Not download/review** | Not in CODE, MCP, Claws, ZKs, sOSS, etc. | Path check |

---

## 4. Exclusion Criteria (Negative Indicators)

| Criterion | Description | Examples |
|-----------|-------------|----------|
| **Path gone** | Directory no longer exists | Cursor/Study, ZK/ZeroM |
| **Slug decode artifact** | Path from slug decode is wrong (hyphen→slash) | Spank/spank/py (real: spank-py) |
| **Moved/renamed** | Project relocated; old path stale | WP/spank-py, WP/splunk-py → Spank/spank-py |
| **Under OLD** | In `*/OLD/` or `*/OLD/*` | WP/OLD/multiwp0, WP/OLD/SplunkOLD |
| **Under Save*** | In `Save`, `Save*` | Github/Save (AVTran backups) |
| **Download/review dir** | OSS tools, reference repos, no meaningful work | CODE, MCP/MCPs, Claw/Claws, ZK/ZKs, Spank/sOSS |
| **Plural/aggregate names** | Often collections of downloaded repos | CODE, MCPs, Claws, ZKs, sOSS |
| **No session data** | Git repo but no sessions in any vendor store | Most under Github, CODE |
| **No git repo** | Unversioned; may be copy or temp | WP/wp (some), zduploads |
| **Redundant** | Child of another candidate (e.g. `zerowalletmac/src`) | Prefer parent |
| **Worktree duplicate** | Same repo, different worktree; sessions may be split | Claw/openclaw-docs vs openclaw |

---

## 5. Directory Taxonomy

| Category | Paths | Purpose |
|----------|-------|---------|
| **Aggregators** | WP, ZK, Claw, Claude, Cursor, Github, CODE | Parent dirs; contain many projects |
| **Download/review** | CODE, MCP, MCP/MCPs, Claw/Claws, ZK/ZKs, Spank/sOSS | OSS tools, old repos, implementation review |
| **Obsolete/backup** | */OLD, */OLD/*, Save, Save* | Backup copies, dropped initiatives |
| **Github** | Github/* | Mixed: clones, forks, some active (e.g. Transcript/avtran) |
| **Special** | CodingSess | Project itself; ingest from Cursor global |

---

## 6. Quantitative Analysis

### 6.1 Session Data by Vendor

| Vendor | Store | Projects with data |
|--------|-------|---------------------|
| Claude Code | `~/.claude/projects/<slug>/` | Spank/spank-py, WP, WP/harduw, WP/multiwp, WP/multiwp-python, WP/must-py, WP/spank-py, WP/splunk-py |
| Codex | `~/.codex/sessions` cwd | openclaw, openclaw-docs, WP/ZD, WP/harduw, WP/wp, WP/wpages, zduploads, CODE/codex/codex-rs |
| Cursor | workspaceStorage, globalStorage | claude-code, claude-code-system-prompts, openclaw, cStudy, Github/Schema, Github/skip, ZK/ZeroMac, ZK/zerowalletmac |

### 6.2 Candidate Tiers (from workflow run)

| Tier | Count | Criteria |
|------|-------|----------|
| Strong | 3 | Session data + recent + git |
| Marginal | 4 | Some data; no git or low volume |
| Cursor/CC-only, 0 sessions | 7 | In Cursor/CC store but 0 sessions in CodingSess metrics |
| Gone | 7 | Path does not exist |
| Potential misses | 30+ | Git repo, no session data |

### 6.3 Projects with `.claude` in Directory

| Path | In ~/.claude/projects? |
|------|------------------------|
| Claude/claude-code | No |
| Claude/tweakcc | No |
| CODE/grokCLI | No |
| CODE | No |
| MCP/MCPs/fastmcp | No |
| MCP/MCPs/mcpconf_cl | No |
| MCP/MCPs/mcpred | No |
| WP | Yes (slug) |
| WP/OLD/* | Yes (obsolete) |
| WP/must-py | Yes |
| WP/multiwp/python0 | Yes |
| WP/harduw | Yes |
| Github/decent | No |
| Github/skip | No |
| Claw/Emails/inbox-zero | No |
| Spank/spank-py | Yes |
| liquid-il | No |

---

## 7. Comparison Tables

### 7.1 Strong vs Marginal vs Excluded

| Project | Sources | Sess | MB | Git | Recent | Verdict |
|---------|---------|------|-----|-----|--------|---------|
| Claw/openclaw | Codex, Cursor | 7 | 78.7 | ✓ | ✓ | **Include** |
| WP/wpages | Codex | 5 | 46.9 | ✓ | ✓ | **Include** |
| Claw/openclaw-docs | Codex | 2 | 6.2 | ✓ | ✓ | **Include** (worktree; expected more sessions) |
| WP/wp | Codex | 2 | 1.1 | — | — | Marginal |
| zduploads | Codex | 2 | 0.08 | — | ✓ | Marginal |
| CODE/codex/codex-rs | Codex | 1 | 0.6 | — | — | Marginal |
| WP/harduw | CC, Codex | 1 | 0.2 | ✓ | — | Marginal |
| Cursor/Study | — | — | — | — | — | **Exclude** (gone) |
| WP/ZD | — | — | — | — | — | **Exclude** (gone) |
| ZK/ZeroM | — | — | — | — | — | **Exclude** (gone) |

### 7.2 Github: Special Attention

| Project | Notes |
|---------|-------|
| Github/Transcript | Audio Visual Transcript (avtran); of interest |
| Github/Save | Dumping ground; AVTran backups; exclude |
| Github/skip | Cursor workspace; no sessions; 30+ weeks idle |
| Github/decent | Has `.claude`; no sessions in stores |
| Others | Clones, forks; no session data; exclude unless manually verified |

### 7.3 Download/Review Directories

| Path | Content |
|------|---------|
| CODE | OSS coding tools (cline, continue, codex, etc.) |
| MCP, MCP/MCPs | MCP-related repos |
| Claw/Claws | (if exists) |
| ZK/ZKs | (if exists) |
| Spank/sOSS | Spank OSS |
| Claude | Mix of tools (tweakcc, claude-code-proxy, agency-agents) |

---

## 8. Recommendations

1. **Ingest immediately:** Claw/openclaw, WP/wpages, Claw/openclaw-docs
2. **Investigate:** Claw/openclaw-docs — worktree of openclaw; expected more sessions; check Codex cwd mapping
3. **Expand CC discovery:** Scan for `.claude` in dirs + `~/.claude/projects` + `sessions-index.json`; decode slugs; match to existing paths
4. **Exclude by path:** `*/OLD/*`, `*/Save*`, CODE, MCP/MCPs, Claw/Claws, ZK/ZKs, Spank/sOSS
5. **Github:** Manual review; include Transcript/avtran if session data found; exclude Save
6. **Canonicalize:** Prefer Spank/spank-py over WP/spank-py; resolve worktree vs main repo

---

## 9. Glossary

| Term | Definition |
|------|------------|
| **Aggregator** | Parent directory (WP, ZK, Claw, etc.) containing multiple projects |
| **Slug** | CC path encoding: `/Users/x/y` → `-Users-x-y` |
| **Worktree** | Git worktree; separate working copy of same repo |
| **Download/review dir** | Directory of cloned OSS repos for search/review; little or no coding work |
| **Session data** | JSONL (CC, Codex) or SQLite (Cursor) records of coding sessions |
| **avtran** | Audio Visual Transcript; project under Github/Transcript |

---

## 10. References

- [CSPlan §8 Discovered Projects](CSPlan.md#8-discovered-projects-work)
- [CodingSess §3 Provider Comparison](CodingSess.md#3-provider-comparison--session-store-and-features)
- [scripts/test_candidate_workflow.py](scripts/test_candidate_workflow.py) — workflow script
- [REVIEW_CODEX_CURSOR.md](REVIEW_CODEX_CURSOR.md) — Cursor/Codex storage layout
