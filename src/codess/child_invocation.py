"""The `python -m main ingest` child invocation, as one object.

Five parameters travelled together through seven functions -- `registry`,
`repo_root`, `resource_policy`, `raw_mode`, `source` -- and five of those carried
the complete set. They are not five unrelated inputs: they are exactly the argv
that three separate functions each built by hand for the same child process, so
the group was a structure that had never been named.

**What the duplication cost.** `baseline_operations`, `refresh_operations`, and
`catalog_operations` each spelled `--source`, `--raw-mode`, `--store`, and
`--min-size` into their own list, and each decided independently whether to add
`--no-progress`, `--validate`, `--force`, or `--candidate-snapshot`. A flag
renamed at the CLI reaches all three only if someone edits each, which is the
same defect the vendor table (`config.VENDORS`) and the row emitter
(`sanitize.tabular_row`) removed in their own areas.

**Why an object rather than a longer helper signature.** A function taking the
same five arguments would keep the ordering hazard the object removes: at a call
site, `run_ingest(project, source, raw_mode, registry, ...)` can be mis-ordered
silently because four of the five are the same type. A frozen dataclass names each
field at construction and cannot be built wrong by position.

**Not a settings bag.** This carries only what the child command line needs. The
run-wide options that ingest resolves for itself -- content policy, bounds, strict
mapping -- stay where they are: adding them here would make this a second
`settings`, which is the accumulation the object exists to avoid.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from codess.wallclock import system_clock

DEFAULT_TIMEOUT_SECONDS = 3_600


@dataclass(frozen=True, slots=True)
class RunPolicy:
    """What an ingest run does, decided once before the first Project.

    The half of an invocation that does not change between Projects: where the
    store is, what bounds apply, and how a child is run. Split from the target
    half because the two have different lifetimes -- a policy is settled at the
    command adapter from one setting declaration each, while a target changes
    every loop iteration.

    The split is what lets a relay take one argument instead of six. Both call
    sites of `_run_project_ingest` passed the same six policy values verbatim,
    so six of its eight arguments carried no information at either site.

    Holds the clock for the same reason it holds the store root: it is decided
    once before the first Project and read many times after, which is the
    lifetime every other field here has. A run that needs a fixed clock sets it
    on the policy rather than threading a parameter through three layers.
    """

    registry: Path
    repo_root: Path
    min_size: int = 0
    raw_mode: str = "reference"
    resource_policy: Path | None = None
    force: bool = False
    policy_timeout: int = DEFAULT_TIMEOUT_SECONDS
    clock: Callable[[], datetime] = system_clock


@dataclass(frozen=True, slots=True)
class ChildInvocation:

    """One `codess ingest` child run: what to ingest, and under which policy.

    Frozen because an invocation describes a decision already made. A caller that
    needs a different one builds a second object, which keeps the two visible
    side by side rather than mutating one and losing what it was.

    **What frozen costs, and why.** Measured over 300,000 constructions of a
    three-field class:

        plain dataclass    104 ns      slots only       94 ns
        frozen only        291 ns      frozen + slots  271 ns

    The cost is `frozen`, not `slots` -- `slots` is slightly *cheaper* than plain.
    A frozen `__init__` cannot use `STORE_ATTR`, because its own `__setattr__`
    raises, so it emits `object.__setattr__(self, field, value)` per field: three
    fields, three calls, 28 bytecode instructions against 14. Cost therefore grows
    with field count, and this class has thirteen.

    It is still right here. An invocation is built a handful of times per run and
    then read, so ~300 ns of construction is invisible beside a child process; what
    it buys is that a recorded invocation cannot be edited after the receipt quotes
    it. The measurement matters for the opposite case -- a frozen dataclass per
    decoded record would be the wrong structure, which is why `codess.reporting`
    uses a plain tuple on that path.
    """

    policy: RunPolicy
    projects: tuple[Path, ...]
    vendor_selector: str
    validate: bool = False
    candidate_snapshot: bool = False
    live_progress: bool = True
    extra_flags: tuple[str, ...] = field(default_factory=tuple)

    # The policy's fields, readable through the invocation so a call site that
    # holds one does not reach past it. Properties rather than copies: a second
    # binding is a second thing to keep in step, which is the duplication the
    # split removes.
    @property
    def registry(self) -> Path:
        return self.policy.registry

    @property
    def repo_root(self) -> Path:
        return self.policy.repo_root

    @property
    def raw_mode(self) -> str:
        return self.policy.raw_mode

    @property
    def min_size(self) -> int:
        return self.policy.min_size

    @property
    def resource_policy(self) -> Path | None:
        return self.policy.resource_policy

    @property
    def force(self) -> bool:
        return self.policy.force

    @property
    def policy_timeout(self) -> int:
        return self.policy.policy_timeout

    def command(self) -> list[str]:
        """The argv, built in one place.

        Ordering is fixed here rather than per caller so two runs of the same
        invocation produce byte-identical commands -- which is what lets a
        recorded `command` in a receipt be compared between runs.
        """
        command = [sys.executable, "-m", "main", "ingest"]
        for project in self.projects:
            command.extend(["--dir", str(project)])
        command.extend([
            "--source", self.vendor_selector,
            "--raw-mode", self.raw_mode,
            "--store", str(self.registry),
            "--min-size", str(self.min_size),
        ])
        if self.resource_policy is not None:
            command.extend(["--resource-policy", str(self.resource_policy)])
        if self.validate:
            command.append("--validate")
        if self.force:
            command.append("--force")
        if self.candidate_snapshot:
            command.append("--candidate-snapshot")
        if not self.live_progress:
            command.append("--no-progress")
        command.extend(self.extra_flags)
        return command

    def environment(self) -> dict[str, str]:
        """The child's environment, with `src` on the import path.

        Every caller set `PYTHONPATH` to the same value from its own copy of
        `os.environ`; doing it here means a child that cannot import `codess` is
        one bug rather than three.
        """
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.repo_root / "src")
        return env

    def run(self) -> subprocess.CompletedProcess[str]:
        """Run the child and return its result, uninterpreted.

        Deliberately does not read the ingest report or classify the outcome:
        those differ per caller -- a refresh writes a receipt, an apply verifies a
        snapshot -- and folding them in here would make this the ingest
        orchestrator rather than the command it invokes.
        """
        return subprocess.run(
            self.command(),
            cwd=self.repo_root,
            env=self.environment(),
            capture_output=True,
            text=True,
            timeout=self.policy_timeout,
            check=False,
        )
