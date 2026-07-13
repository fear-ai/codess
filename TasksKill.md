# Claude Code background work and process cleanup

Claude's task view and the operating-system process list track different state.

| State | Inspect | Stop or update |
|---|---|---|
| Shell process | `jobs`, `ps` | `kill`, or a timeout around the command |
| Claude-managed background command or agent | `/tasks` | Task controls in Claude Code or `TaskStop` |
| Claude task-list item | `~/.claude/tasks/<session>/` | Update task status; it is metadata, not a process |

Stopping one layer does not prove that the others changed. Files under
`~/.claude/tasks/` contain task descriptions and statuses, not live PIDs.

## Bound commands that may hang

Use the project's pyenv environment. Add GNU `gtimeout` when a command needs a
hard deadline:

```bash
pyenv exec pytest tests/
gtimeout --kill-after=5s 180s pyenv exec pytest tests/
```

After 180 seconds `gtimeout` sends `TERM`; five seconds later it sends `KILL` if
the command is still alive. Do not add `--foreground` when children must also be
timed out. Exit status `124` means the deadline expired; `137` indicates `KILL`.

Claude Code may move a long Bash call into the background. The environment
variables `BASH_DEFAULT_TIMEOUT_MS` and `BASH_MAX_TIMEOUT_MS` control Bash tool
timing, but neither proves that an external process exited.

## Inspect before killing

```bash
jobs -l
ps -o pid=,ppid=,pgid=,state=,etime=,command= -p <pid>
ps ax -o pid=,ppid=,pgid=,etime=,command= | rg '[p]ytest|[p]ython.*specific_script'
```

Match a distinctive script, test path, or argument. Counts such as
`pgrep -c python3` include unrelated work and are not safe cleanup criteria.

Stop only a confirmed process:

```bash
kill -TERM <pid>
ps -p <pid>
kill -KILL <pid>  # only if the same process remains
```

Before signaling a process group, compare its PGID with the current shell:

```bash
ps -o pid=,ppid=,pgid=,command= -p <pid>
ps -o pgid= -p $$
```

Use `kill -TERM -- -<pgid>` only when the target group is confirmed to be
separate from the shell. Never use blanket commands such as `pkill python3`, and
never reuse PIDs copied from an old log.

## Reconcile Claude-managed work

Use `/tasks` to inspect work known to the current Claude session. Stop the
selected command or agent through Claude Code, then check `ps` if it launched
external workers or detached a daemon. Deleting `~/.claude/tasks/` files does
not stop an OS process.

Tests that create child processes should own teardown in a fixture or `finally`
block. The project does not need a general-purpose reaper.
