"""The command layer's fatal-error channel: one prefix, one stream, one shape.

A fatal message is written directly to stderr rather than through
`codess.reporting`, and that is a decision rather than an omission. The
reporting facility drops an event when no sink is attached, and only `ingest`
and `scan` call `reporting.configure()` -- so an error emitted from `admin` or
`query` would reach nobody. Its `HumanSink` also renders every event as
`codess: progress <time> +<elapsed>s key=value`, which is the wrong shape for a
condition that ends the run.

**Observability is maximal here on purpose.** A fatal message reports the
operator's own machine to the operator, on their own terminal, at the moment a
command is refusing to continue -- so it carries the offending value verbatim: a
path, a flag, an identifier, an exception's text. Truncating or tokenizing it
would leave the one message whose entire job is to say what went wrong unable to
say it. This matches `reporting`'s own `local` privacy profile, which is the
default for every profile and emits every field verbatim including unregistered
ones, for the same reason: nothing is leaving the machine.

The redaction profiles exist for the *event stream*, which can be written to a
file, shipped, or attached to a report. A fatal message is not part of that
stream and has no such path. If one is ever wanted -- a support bundle, say --
the answer is a sink that captures these, not a policy that blinds them here.

Two functions rather than one, because the two callers differ in what they hold:

    fail("--limit must be >= 0")            # a message this code composed
    fail_with(exc, "cannot open stores")    # an exception whose text to carry

Both return 1, so a caller writes `return fail(...)` and the exit code cannot
drift from the message.
"""

from __future__ import annotations

import sys

PREFIX = "codess"
"""Every fatal line starts here, so a reader can tell our output from a
subprocess's. Eleven sites omitted it before this module existed, which is what
a per-site convention produces."""


def fail(message: str, *, code: int = 1) -> int:
    """Report a fatal condition on stderr and return the exit code.

    The message is written verbatim after the prefix. A caller that already
    holds a prefixed line -- a validator returning `codess: ...` -- passes it
    through unchanged rather than acquiring a second prefix.
    """
    text = message if message.startswith(f"{PREFIX}:") else f"{PREFIX}: {message}"
    print(text, file=sys.stderr)
    return code


def fail_with(error: BaseException, context: str, *, code: int = 1) -> int:
    """Report a fatal condition arising from an exception.

    The exception's text is carried, not its type name and not a traceback: the
    text is what names the file, value, or constraint that failed, and the type
    alone has repeatedly proved unactionable. A traceback belongs in a debug
    profile, not on the line an operator reads.
    """
    return fail(f"{context}: {error}", code=code)


def warn(message: str) -> None:
    """Report a condition the run continues past, on the same channel as `fail`.

    Distinct from `fail` because it returns nothing: a warning that could be
    written `return warn(...)` would eventually be, and the run would exit on a
    condition it was designed to survive. The prefix and stream are shared so an
    operator reads one output, and the word `warning` in the message is what
    separates the two -- not the destination.

    Not routed through `codess.reporting` for the reason the module docstring
    gives: two of the four command modules attach no sink, so an event from them
    is dropped. A warning that reaches nobody is worse than one on stderr.
    """
    fail(message)


def fail_configuration() -> int:
    """Report every configuration error and return 1, or 0 when there are none.

    `scan`, `ingest`, and `query` each opened with the same four lines: validate,
    print each error prefixed, and return 1 if there were any. Three copies of a
    block whose shape is `if it fails, say why and stop` is what a helper is for,
    and the copies had already begun to differ in where they imported the
    validator from.

    Reports *every* error rather than the first: a configuration with two faults
    otherwise takes two runs to diagnose, and the second is invisible until the
    first is fixed.
    """
    from codess.config import validate_config

    errors = validate_config()
    for message in errors:
        fail(message)
    return 1 if errors else 0
