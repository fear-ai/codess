"""One declaration per setting: its flag, its variable, its default, its kind.

A setting's default was decided in up to four places -- a constant in `config`,
an `env_*` reader, an argparse `default=`, and a `getattr(args, ...) or CONSTANT`
fallback at the use site -- and nothing stated which won. Three shapes were in
use for the same question, and one of them said nothing at all:

    flag_or_env(args, "force", FORCE)          10 sites, boolean, flag OR env
    getattr(args, "content_policy", None) or CONTENT_POLICY
                                                3 sites, value, flag then env
    bool(getattr(args, "no_progress", False))  16 sites, flag only
    getattr(args, name, None)                 133 sites, precedence unstated

This table states each once, and `resolve` applies the precedence so a use site
does not restate it.

## Precedence

**Flag, then environment variable, then configuration file, then built-in
default.** Stated here so it is arguable rather than incidental to the order
three modules happened to check in. The reason is that each is narrower than the
last: a flag names one invocation, a variable names one shell, a file names one
machine, and a built-in names every machine that never chose.

The file sits below the variable rather than above it because a shell is the
narrower scope: an operator who exports a variable for one session is making a
decision about that session, and a file they wrote weeks ago must not override
it. `CODESS_CONFIG` names the file; otherwise it is `settings.json` in the
machine's durable store, beside the registry it configures.

**A boolean setting is the exception, and it composes rather than overrides.**
`--force` with `CODESS_FORCE=0` is force; so is `CODESS_FORCE=1` with no flag.
That is `flag_or_env`'s existing behaviour and it is deliberate: a store_true
flag cannot express *off*, so treating its absence as an override would make the
variable unsettable from a shell that also passes flags.

## The Import-Order Constraint

`config`'s constants resolve at import, which is before a flag is parsed. A leaf
module -- `fileio`, `schema_contract` -- cannot import `config` without a cycle, so
it reads its variable directly and a flag reaches it only by writing that
variable. `LEAF_VISIBLE` marks those settings, and `apply_leaf_visible` performs
the write in one place rather than in two hand-written assignments.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Setting:
    """One setting's declaration: where it comes from and how it composes."""

    name: str
    """The key callers read."""

    flag: str | None
    """The command-line spelling, or `None` for a setting only the variable sets."""

    variable: str
    """The environment variable, which is also the leaf-visible write target."""

    dest: str = ""
    """The argparse `dest`, when it differs from `name`.

    `--stop` parses into `stop` while the setting is `stop_on_error`: the flag
    names the action and the setting names the condition it sets. Empty means
    the two agree, which is the common case.
    """

    boolean: bool = False
    """Whether flag and variable compose with OR rather than the flag overriding."""

    @property
    def attribute(self) -> str:
        """The name to read off an `argparse.Namespace`."""
        return self.dest or self.name

    leaf_visible: bool = False
    """Whether a leaf module reads the variable directly, so a flag must write it."""


SETTINGS: tuple[Setting, ...] = (
    Setting("stop_on_error", "--stop", "CODESS_STOP", dest="stop", boolean=True),
    Setting("force", "--force", "CODESS_FORCE", boolean=True),
    Setting("debug", "--debug", "CODESS_DEBUG", boolean=True),
    Setting("verbose", "--verbose", "CODESS_VERBOSE", boolean=True),
    Setting("redact", "--redact", "CODESS_REDACT", boolean=True),
    Setting("strict_mapping", "--strict-mapping", "CODESS_STRICT_MAPPING", boolean=True),
    Setting("subagent", "--subagent", "CODESS_SUBAGENT", boolean=True),
    # Both are read by a module that cannot import `config`, so the flag's only
    # effect is to set the variable those reads already observe.
    Setting("no_hash", "--no-hash", "CODESS_NO_HASH", boolean=True, leaf_visible=True),
    Setting(
        "no_check", "--no-check", "CODESS_NO_CONTRACT_CHECK",
        boolean=True, leaf_visible=True,
    ),
    Setting("min_size", "--min-size", "CODESS_MIN_SIZE"),
    Setting("raw_mode", "--raw-mode", "CODESS_RAW_MODE"),
    Setting("content_policy", "--content-policy", "CODESS_CONTENT_POLICY"),
    Setting("resource_policy", "--resource-policy", "CODESS_RESOURCE_POLICY"),
    Setting("days", "--days", "CODESS_DAYS"),
    Setting("store_root", "--store", "CODESS_STORE_ROOT"),
    Setting("max_directories", "--max-directories", "CODESS_MAX_SCAN_DIRECTORIES"),
    # `scan_timeout`, qualified: `policy_timeout` on `RunPolicy` bounds
    # a child process, and two unrelated bounds under one name is the collision
    # the naming rules exist to prevent.
    Setting(
        "scan_timeout", "--scan-timeout",
        "CODESS_SCAN_TIMEOUT",
    ),
    # Variable-only: retention depth is a machine policy rather than a per-run
    # choice for the trim that follows every publication. `storage prune` takes
    # `--keep` to override it for one run, which is a different flag on a
    # different command and so a different row would misdescribe this one.
    Setting("keep_snapshots", None, "CODESS_KEEP_SNAPSHOTS"),
    # Cursor's `agentKv` corpus: the harness system prompt, reasoning parts,
    # and reasoning for requests whose bubbles the vendor has pruned. Off by
    # default because it reads a 200,000-row key space to add evidence a
    # Session-level question does not need, and admitting it should be the
    # operator's choice rather than a cost every ingest pays.
    Setting("include_agent_kv", "--agent-kv", "CODESS_AGENT_KV", boolean=True),
    Setting("catalog", "--catalog", "CODESS_CATALOG"),
    Setting("report_profile", "--report-profile", "CODESS_REPORT_PROFILE"),
    Setting("report_privacy", "--report-privacy", "CODESS_REPORT_PRIVACY"),
)

BY_NAME: dict[str, Setting] = {setting.name: setting for setting in SETTINGS}

CONFIG_FILE_FORMAT = "codess.settings/1"
CONFIG_FILE_VARIABLE = "CODESS_CONFIG"
CONFIG_FILE_NAME = "settings.json"


def _config_file_path() -> Path | None:
    """The configuration file to read, or None when none is selected.

    `CODESS_CONFIG` names one explicitly; otherwise the machine's durable store
    holds it, beside the registry it configures. The store root is read from its
    own variable rather than from `config`, because this module is imported by
    leaves that cannot import `config` without a cycle -- the constraint
    `leaf_visible` names from the other direction.
    """
    configured = os.environ.get(CONFIG_FILE_VARIABLE)
    if configured:
        return Path(configured).expanduser()
    store_root = os.environ.get("CODESS_STORE_ROOT")
    base = Path(store_root).expanduser() if store_root else Path.home() / ".codess"
    return base / CONFIG_FILE_NAME


@lru_cache(maxsize=1)
def config_file_values() -> dict[str, Any]:
    """Settings stated by the configuration file, keyed by setting name.

    Cached because `resolve` is called per option per command and the file does
    not change within a run. A test that writes one calls `reload_config_file`.

    An unreadable or unsupported file yields nothing rather than raising: a
    configuration file is the lowest-authority source above the built-in
    default, so a malformed one must not stop a command that names every value
    it needs on the command line. It warns, because a file the operator wrote
    and Codess ignored is the case they would otherwise never see.
    """
    path = _config_file_path()
    if path is None or not path.is_file():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("cannot read settings file %s (%s); ignoring it", path, exc)
        return {}
    if not isinstance(document, dict):
        log.warning("settings file %s is not an object; ignoring it", path)
        return {}
    if document.get("format") != CONFIG_FILE_FORMAT:
        log.warning(
            "settings file %s states format %r rather than %r; ignoring it",
            path, document.get("format"), CONFIG_FILE_FORMAT,
        )
        return {}
    stated = document.get("settings")
    if not isinstance(stated, dict):
        return {}
    values: dict[str, Any] = {}
    for name, value in stated.items():
        if name not in BY_NAME:
            # Named rather than dropped: a misspelled setting in a file the
            # operator wrote is silent otherwise, and reads as a value that
            # took effect.
            log.warning("settings file %s names unknown setting %r", path, name)
            continue
        values[name] = value
    return values


def reload_config_file() -> None:
    """Drop the cached file, so a test or a rewritten file is read again."""
    config_file_values.cache_clear()


def resolve(args: Any, name: str, default: Any) -> Any:
    """One setting's value, by the precedence this module states.

    `default` is passed rather than held on the row because `config` resolves it
    at import from the same variable, and duplicating it here would create the
    second declaration the table exists to remove. The row owns the *name* and
    the *composition rule*; `config` owns the value.
    """
    setting = BY_NAME[name]
    supplied = getattr(args, setting.attribute, None)
    stated = config_file_values().get(name)
    if setting.boolean:
        # Composes rather than overrides: a store_true flag cannot say "off", so
        # an absent flag must not veto a variable the operator set. The file
        # composes on the same terms and for the same reason.
        return bool(supplied) or bool(default) or bool(stated)
    if supplied is not None:
        return supplied
    # The file loses to the variable and wins over the built-in. `default`
    # already carries the variable's value where one is set -- `config`
    # resolves it at import -- so the variable is tested directly rather than
    # inferred from `default`, which cannot distinguish the two.
    if stated is not None and not os.environ.get(setting.variable):
        return stated
    return default


def resolve_named(supplied: Any, name: str, default: Any) -> Any:
    """One setting's value where the caller holds it as a plain argument.

    `resolve` reads off an `argparse.Namespace`; this takes the value directly,
    for a caller that never built a parser -- a library entry point, or a leaf
    module that receives its option as a parameter. The precedence is the same
    and stated in one place, which is the point: a second spelling of
    flag-then-variable-then-default is how two of them come to disagree.

    The environment is read here rather than taken from `config`, because a leaf
    cannot import `config` without a cycle. That is the same constraint
    `LEAF_VISIBLE` names from the other direction.
    """
    setting = BY_NAME[name]
    stated = config_file_values().get(name)
    if setting.boolean:
        return bool(supplied) or _env_truth(setting.variable) or bool(stated)
    if supplied is not None:
        return supplied
    configured = os.environ.get(setting.variable)
    if configured:
        return configured
    return stated if stated is not None else default


def _env_truth(variable: str) -> bool:
    """Whether an environment variable states a true value."""
    return os.environ.get(variable, "0").strip().lower() in ("1", "true", "yes")


def apply_leaf_visible(args: Any) -> list[str]:
    """Write the variables that leaf modules read, and report which were set.

    The declared form of the workaround two command paths performed by hand.
    Returns the variable names written so a caller can report a bypass rather
    than have it take effect silently -- both settings disable a verification
    step, which is where an operator most needs to be told.
    """
    written: list[str] = []
    for setting in SETTINGS:
        if not setting.leaf_visible:
            continue
        if getattr(args, setting.attribute, None):
            os.environ[setting.variable] = "1"
            written.append(setting.variable)
    return written
