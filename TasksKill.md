# Claude Code background work and process cleanup

Use this note when a command launched from Claude Code keeps running, or when the
Claude task UI and the operating-system process list appear to disagree. The
examples below match macOS, Claude Code 2.1.92, GNU `gtimeout` from Homebrew, and
this project's pyenv setup.

## Three different kinds of state

Keep these separate when diagnosing a stuck task:

| State | Where to inspect it | What stops it |
|---|---|---|
| Foreground or background shell process | `jobs`, `ps` | `kill` or a timeout around the command |
| Claude-managed background command or agent | Claude Code `/tasks` view | `TaskStop`, or the corresponding task control in the UI |
| Claude task-list item | `~/.claude/tasks/<session>/` | Update its task status; it is metadata, not a process |

Stopping one layer does not prove that the other layers changed. In particular,
JSON files under `~/.claude/tasks/` contain task descriptions and statuses, not
live PIDs.

## Put a hard limit around commands that may hang

For a command that must finish within a known time, use GNU `gtimeout` at the
call site:

```bash
gtimeout --kill-after=5s 120s pyenv exec pytest tests/
```

The command receives `TERM` after 120 seconds and, if it is still alive, `KILL`
five seconds later. Do not add `--foreground` when child-process cleanup is the
goal; GNU timeout documents that children are not timed out in foreground mode.

Useful timeout exit statuses:

- `124`: the duration expired.
- `137`: the command or `gtimeout` was killed with `KILL`.
- Any other ordinary status: the wrapped command's status.

Claude Code can also auto-background a long-running Bash command instead of
killing it. `BASH_DEFAULT_TIMEOUT_MS` controls when that occurs and
`BASH_MAX_TIMEOUT_MS` caps an explicitly requested Bash timeout. Those are
environment variables, not proof that the underlying process was terminated.

## Inspect before killing

For a job started in the current shell:

```bash
jobs -l
```

For a known PID:

```bash
ps -o pid=,ppid=,pgid=,state=,etime=,command= -p <pid>
```

For a narrowly identified command when the PID is unknown:

```bash
ps ax -o pid=,ppid=,pgid=,etime=,command= | rg '[p]ytest|[p]ython.*specific_script'
```

Prefer matching a distinctive script, test path, or argument. A count such as
`pgrep -c python3` includes unrelated work and is not a safe admission-control
or cleanup mechanism.

## Stop a confirmed OS process

Ask the exact process to exit, verify, then escalate only if necessary:

```bash
kill -TERM <pid>
ps -p <pid>
kill -KILL <pid>  # only if the same process is still present
```

If a command created worker children, first inspect its process group:

```bash
ps -o pid=,ppid=,pgid=,command= -p <pid>
ps -o pgid= -p $$
```

Only when the target PGID is confirmed to be separate from the current shell's
PGID, signal the group with `kill -TERM -- -<pgid>`. This avoids accidentally
terminating the controlling shell. Prefer `gtimeout` from the start when a
process tree needs a predictable lifetime.

Never use blanket commands such as `pkill python3` or kill PIDs copied from an
old log. PIDs are reused and other projects may be running concurrently.

## Reconcile Claude-managed background work

Use `/tasks` to inspect background commands and agents known to the current
Claude Code session. Stop the selected item through the UI or with `TaskStop`.
Afterward, check `ps` if the command launched external workers or deliberately
detached a daemon.

The task-list files under `~/.claude/tasks/` are retained session metadata and
may include pending or completed plan items long after execution. Editing or
deleting those files is not an OS-process cleanup method.

## Practical default for this project

Run the suite through pyenv, with a hard timeout only when diagnosing hangs:

```bash
pyenv exec pytest tests/
gtimeout --kill-after=5s 180s pyenv exec pytest tests/
```

The ordinary suite does not require a custom reaper script. If a future test
intentionally starts child processes, that test should own their teardown and
verify it in a `finally` block or fixture cleanup.
