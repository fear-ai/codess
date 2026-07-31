#!/usr/bin/env bash
# Cheap, content-free Project orientation before any large vendor extraction.

set -u

requested_project=${1:-"$PWD"}
project=$requested_project
registry=${2:-"${CODESS_REGISTRY:-$HOME/.codess}"}

if ! project=$(cd "$project" 2>/dev/null && pwd -P); then
  printf 'codess status: Project location is unavailable: %s\n' "$requested_project" >&2
  exit 1
fi

mtime_epoch() {
  stat -f '%m' "$1" 2>/dev/null || stat -c '%Y' "$1" 2>/dev/null || printf '0\n'
}

mtime_text() {
  local epoch
  epoch=$(mtime_epoch "$1")
  if [ "$epoch" -gt 0 ] 2>/dev/null; then
    date -r "$epoch" -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null \
      || date -u -d "@$epoch" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null \
      || printf '%s' "$epoch"
  else
    printf 'unavailable'
  fi
}

file_size() {
  stat -f '%z' "$1" 2>/dev/null || stat -c '%s' "$1" 2>/dev/null || printf 'unknown\n'
}

newest_file_under() {
  local root=$1 max_depth=${2:-3} newest= newest_epoch=0 candidate epoch
  while IFS= read -r candidate; do
    epoch=$(mtime_epoch "$candidate")
    if [ "$epoch" -gt "$newest_epoch" ]; then
      newest_epoch=$epoch
      newest=$candidate
    fi
  done < <(find "$root" -maxdepth "$max_depth" -type f -print 2>/dev/null)
  printf '%s\n' "$newest"
}

printf 'Project: %s\n' "$project"
printf 'Observed: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
printf 'Registry: %s\n' "$registry"

printf '\nGit\n'
if git_root=$(git -C "$project" rev-parse --show-toplevel 2>/dev/null); then
  printf '  root: %s\n' "$git_root"
  printf '  branch: %s\n' "$(git -C "$project" branch --show-current 2>/dev/null || true)"
  printf '  head: %s\n' "$(git -C "$project" rev-parse --short=12 HEAD 2>/dev/null || true)"
  printf '  head_at: %s\n' "$(git -C "$project" show -s --format=%cI HEAD 2>/dev/null || true)"
  porcelain=$(git -C "$project" status --porcelain=v1 --untracked-files=normal 2>/dev/null || true)
  if [ -n "$porcelain" ]; then
    changed=$(printf '%s\n' "$porcelain" | awk 'END {print NR}')
    printf '  worktree: changed (%s paths)\n' "$changed"
    shown=0
    while IFS= read -r -d '' changed_path; do
      [ "$shown" -ge 20 ] && break
      absolute_changed="$git_root/$changed_path"
      if [ -e "$absolute_changed" ]; then
        printf '    %s\t%s\n' "$(mtime_text "$absolute_changed")" "$changed_path"
      else
        printf '    deleted\t%s\n' "$changed_path"
      fi
      shown=$((shown + 1))
    done < <(
      git -C "$project" diff HEAD --name-only -z 2>/dev/null
      git -C "$project" ls-files --others --exclude-standard -z 2>/dev/null
    )
    if [ "$changed" -gt "$shown" ]; then
      printf '    ... bounded display; %s additional status entries\n' "$((changed - shown))"
    fi
  else
    printf '  worktree: clean\n'
  fi
  upstream=$(git -C "$project" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)
  if [ -n "$upstream" ]; then
    divergence=$(git -C "$project" rev-list --left-right --count "${upstream}...HEAD" 2>/dev/null || true)
    printf '  upstream: %s\n' "$upstream"
    printf '  upstream_behind_ahead: %s\n' "${divergence:-unavailable}"
  else
    printf '  upstream: not configured\n'
  fi
  reflog=$(git -C "$project" reflog -1 --date=iso-strict --format='%gD %gs' 2>/dev/null || true)
  if [ -n "$reflog" ]; then
    printf '  latest_local_ref_update: %s\n' "$reflog"
  fi
  common_dir=$(git -C "$project" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
  git_dir=$(git -C "$project" rev-parse --path-format=absolute --git-dir 2>/dev/null || true)
  printf '  git_dir: %s\n' "$git_dir"
  if [ -n "$common_dir" ] && [ "$common_dir" != "$git_dir" ]; then
    printf '  worktree_relation: linked worktree of %s\n' "$common_dir"
  else
    printf '  worktree_relation: primary or standalone worktree\n'
  fi
else
  printf '  state: not a Git worktree\n'
fi

project_id=
binding="$project/.codess/project.json"
if [ -f "$binding" ] && command -v jq >/dev/null 2>&1; then
  project_id=$(jq -r '.project_id // empty' "$binding" 2>/dev/null || true)
fi
if [ -z "$project_id" ] && [ -f "$registry/projects.json" ] \
  && command -v jq >/dev/null 2>&1; then
  project_id=$(jq -r --arg path "$project" \
    '.projects[] | select(any(.locations[]?; .path == $path)) | .project_id' \
    "$registry/projects.json" 2>/dev/null | head -n 1)
fi

printf '\nCodess snapshot\n'
if [ -n "$project_id" ]; then
  printf '  project_id: %s\n' "$project_id"
  central="$registry/projects/${project_id#codess:project:}"
  pointer="$central/current.json"
  if [ ! -f "$pointer" ]; then
    pointer="$project/.codess/current.json"
  fi
  if [ -f "$pointer" ]; then
    printf '  current_pointer: %s\n' "$pointer"
    printf '  pointer_mtime: %s\n' "$(mtime_text "$pointer")"
    if command -v jq >/dev/null 2>&1; then
      printf '  snapshot_id: %s\n' \
        "$(jq -r '.snapshot_id // empty' "$pointer" 2>/dev/null || true)"
    fi
  else
    printf '  current_pointer: missing\n'
  fi
else
  printf '  project_id: not bound\n'
  pointer="$project/.codess/current.json"
fi

report="$project/.codess/last-ingest-report.json"
if [ -f "$report" ]; then
  printf '  last_ingest_report: %s\n' "$report"
  printf '  report_mtime: %s\n' "$(mtime_text "$report")"
  if command -v jq >/dev/null 2>&1; then
    printf '  last_ingest_status: %s\n' \
      "$(jq -r '.status // .projects[0].status // "unknown"' "$report" 2>/dev/null || true)"
  fi
else
  printf '  last_ingest_report: missing\n'
fi

printf '\nClaude project store\n'
slug="-${project#/}"
slug=${slug//\//-}
claude_dir="$HOME/.claude/projects/$slug"
if [ -d "$claude_dir" ]; then
  printf '  path: %s\n' "$claude_dir"
  latest_claude_epoch=0
  latest_claude=
  while IFS= read -r source; do
    epoch=$(mtime_epoch "$source")
    if [ "$epoch" -gt "$latest_claude_epoch" ]; then
      latest_claude_epoch=$epoch
      latest_claude=$source
    fi
  done < <(find "$claude_dir" -maxdepth 1 -type f -name '*.jsonl' -print 2>/dev/null)
  if [ -n "$latest_claude" ]; then
    printf '  newest_source: %s\n' "$latest_claude"
    printf '  newest_source_mtime: %s\n' "$(mtime_text "$latest_claude")"
    printf '  newest_source_bytes: %s\n' "$(file_size "$latest_claude")"
    pointer_epoch=0
    if [ -f "$pointer" ]; then
      pointer_epoch=$(mtime_epoch "$pointer")
    fi
    if [ "$latest_claude_epoch" -gt "$pointer_epoch" ]; then
      printf '  snapshot_relation: source newer than current pointer; assess/reingest\n'
    else
      printf '  snapshot_relation: no newer direct Claude source observed\n'
    fi
  else
    printf '  newest_source: none\n'
  fi
  newest_claude_state=
  newest_claude_state_epoch=0
  while IFS= read -r state_file; do
    state_epoch=$(mtime_epoch "$state_file")
    if [ "$state_epoch" -gt "$newest_claude_state_epoch" ]; then
      newest_claude_state_epoch=$state_epoch
      newest_claude_state=$state_file
    fi
  done < <(find "$claude_dir" -maxdepth 3 -type f ! -name '*.jsonl' -print 2>/dev/null)
  if [ -n "$newest_claude_state" ]; then
    printf '  newest_non_transcript_state: %s\n' "$newest_claude_state"
    printf '  newest_non_transcript_state_mtime: %s\n' "$(mtime_text "$newest_claude_state")"
    printf '  state_attribution: Claude Project store, not necessarily a conversation record\n'
  fi
else
  printf '  path: not present for current Project path\n'
fi

printf '\nTool-state markers\n'
for marker in "$project/.claude" "$project/CLAUDE.md" "$project/AGENTS.md" \
  "$project/.codess"; do
  if [ -e "$marker" ]; then
    printf '  %s\t%s\n' "$(mtime_text "$marker")" "$marker"
    if [ -d "$marker" ]; then
      newest_marker=$(newest_file_under "$marker" 3)
      if [ -n "$newest_marker" ]; then
        printf '    newest file: %s\t%s\n' \
          "$(mtime_text "$newest_marker")" "$newest_marker"
      fi
    fi
  fi
done

cursor_db="$HOME/Library/Application Support/Cursor/User/globalStorage/state.vscdb"
printf '\nCursor container observation\n'
if [ -f "$cursor_db" ]; then
  printf '  path: %s\n' "$cursor_db"
  printf '  mtime: %s\n' "$(mtime_text "$cursor_db")"
  printf '  bytes: %s\n' "$(file_size "$cursor_db")"
  printf '  attribution: global container only; run a Project-limited scan before ingest\n'
  cursor_epoch=$(mtime_epoch "$cursor_db")
  pointer_epoch=0
  if [ -f "$pointer" ]; then
    pointer_epoch=$(mtime_epoch "$pointer")
  fi
  if [ "$cursor_epoch" -gt "$pointer_epoch" ]; then
    printf '  snapshot_relation: global Cursor container is newer; Project change not yet established\n'
  else
    printf '  snapshot_relation: global Cursor container is not newer than current pointer\n'
  fi
else
  printf '  path: unavailable\n'
fi

printf '\nAssessment order\n'
printf '  1. Treat Git as a strong primary change signal, not an exclusive one.\n'
printf '  2. Review vendor/project marker mtimes and the current ingest report.\n'
printf '  3. Run: codess scan --dir %q --source cc,codex,cursor --out -\n' "$project"
printf '  4. Run a full ingest only when selected source observations changed or validation requires it.\n'
