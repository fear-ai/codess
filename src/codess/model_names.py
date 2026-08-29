"""Resolve a vendor model string into its named parts.

A model name decomposes along three axes plus two selected settings: the **line**
(`claude`, `gpt`, `grok`, `composer`), the **generation** it belongs to counted in whole
numbers, the **version** within that generation, and the **gradation** -- the capability
level, which Anthropic names after literary and mythological forms (opus, sonnet, haiku,
fable, mythos) and OpenAI after celestial bodies (sol, terra, luna). Other vendors write
`thinking` or `coding` in the same slot. A **variant** is a superseded or purpose-marking
designator that has occupied the same position -- `codex`, `latest` -- kept apart so a
historical one is not read as a current capability level. **Strength** and **speed** are settings a user
selects rather than parts of the model's identity.

Generation and version are distinct and are both kept: Claude has gone through
generations 3, 4, and 5, and `claude-opus-4-8` is version 4.8 of generation 4, exactly as
`gpt-5.6` is version 5.6 of generation 5. Conflating them would make `4.8` and `5` look
like values on one scale.

Vendors order these parts differently, so one parser would misread one vendor to satisfy
another. Claude writes `claude-opus-4-8` -- line, gradation, hyphenated version. Codex
writes `gpt-5.6-sol` -- line, dotted version, gradation. Cursor writes
`claude-4.6-opus-high-thinking` -- line, version, gradation, strength. Resolution is
therefore a table lookup first and a per-vendor tokenizer second.

**A name that resolves to nothing is recorded unresolved, never guessed.** The vendor
string is retained verbatim in every case; only the derived fields are left null. That
distinction is the point of the module: a store can state that it did not recognize a
model, which is different from stating the model had no gradation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ALIAS_PATH = Path(__file__).resolve().parents[2] / "schema" / "model-aliases.json"

# Capability levels within a version, and the guard for the fallback tokenizers: a token
# outside this set is not accepted as a gradation merely because it sits in that position.
# Anthropic names these after literary and mythological forms, OpenAI after a purpose.
# Mythos is named and not generally available, so it is declared and unobserved.
GRADATIONS = frozenset({
    "opus", "sonnet", "haiku", "fable", "mythos",
    "sol", "terra", "luna",
})

# Superseded or purpose-marking designators a vendor has used in the gradation position at
# other times. Kept apart from GRADATIONS so a historical `codex` is not read as a current
# capability level.
VARIANTS = frozenset({"codex", "codex-max", "latest"})

# The model series a vendor ships. A line is not a gradation: `gpt` names OpenAI's series
# as `claude` names Anthropic's, while `opus` and `sol` are levels within one version.
LINES = frozenset({"claude", "gpt", "grok", "composer"})


@dataclass(frozen=True)
class ModelName:
    """One resolved model string. `resolved` false means nothing below it is asserted."""

    label: str
    resolved: bool = False
    api: str | None = None
    provider: str | None = None
    line: str | None = None
    generation: str | None = None
    version: str | None = None
    gradation: str | None = None
    gradation_rank: int | None = None
    variant: str | None = None
    revision: str | None = None
    strength: str | None = None
    speed: str | None = None
    sentinel: bool = False
    basis: str | None = None


@lru_cache(maxsize=1)
def _table(path: str | None = None) -> tuple[dict, dict]:
    """Load the alias table once. Returns (aliases by folded label, sentinels)."""
    source = Path(path) if path else ALIAS_PATH
    data = json.loads(source.read_text(encoding="utf-8"))
    aliases = {
        str(entry["label"]).casefold(): entry
        for entry in data.get("aliases", [])
        if entry.get("label")
    }
    sentinels = {
        str(key).casefold(): value
        for key, value in (data.get("sentinels") or {}).items()
    }
    return aliases, sentinels


@lru_cache(maxsize=1)
def _ranks() -> dict[str, int]:
    """Gradation to 1-based rank, low capability to high, per the vendor's ordering."""
    data = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
    ranks: dict[str, int] = {}
    for values in data.get("gradations", {}).values():
        if not isinstance(values, list):
            continue
        ranks.update(
            {str(name).casefold(): index for index, name in enumerate(values, 1)}
        )
    return ranks


def gradation_rank(gradation: str | None) -> int | None:
    """Where a gradation sits in its vendor's capability order, 1 being lowest.

    The order is stated by the vendor and is not recoverable from the names -- nothing in
    `haiku`, `sonnet`, `opus` says which is more capable -- so it is data, and a gradation
    absent from the table has no rank rather than a guessed one.
    """
    if not gradation:
        return None
    return _ranks().get(gradation.casefold())


def _from_alias(entry: dict, label: str) -> ModelName:
    return ModelName(
        label=label,
        resolved=True,
        api=entry.get("api"),
        provider=entry.get("provider"),
        line=entry.get("line"),
        generation=entry.get("generation"),
        version=entry.get("version"),
        gradation=entry.get("gradation"),
        gradation_rank=gradation_rank(entry.get("gradation")),
        variant=entry.get("variant"),
        revision=entry.get("revision"),
        strength=entry.get("strength"),
        speed=entry.get("speed"),
        basis="alias",
    )


# `claude-<gradation>-<version>[-<revision>]`: line, gradation, hyphenated version, an
# optional trailing date build.
_CLAUDE = re.compile(
    r"^claude-(?P<gradation>[a-z]+)-(?P<version>\d+(?:-\d+)?)"
    r"(?:-(?P<revision>\d{6,}))?$"
)

# `<line>-<version>[-<suffix>]`: line first as Claude does, but the version is dotted
# rather than hyphenated. The suffix is a gradation where the vocabulary declares one and
# a variant otherwise, since the same position has carried both.
_CODEX = re.compile(
    r"^(?P<line>[a-z]+)-(?P<version>\d+(?:\.\d+)?)(?:-(?P<suffix>[a-z0-9-]+))?$"
)

# `[cursor-]<line>-<version>-<gradation>-<strength>-thinking`: the version precedes the
# gradation here, which is the order Claude's own names invert.
_CURSOR_THINKING = re.compile(
    r"^(?P<line>[a-z]+)-(?P<version>\d+(?:\.\d+)?)-(?P<gradation>[a-z]+)"
    r"-(?P<strength>[a-z]+)-thinking$"
)


def _generation(version: str) -> str:
    """The whole-number generation a version belongs to: 4.8 and 4.6 are both 4."""
    return version.split(".")[0]


def _tokenize(label: str, vendor: str | None) -> ModelName | None:
    """Per-vendor fallback for a name absent from the table."""
    folded = label.casefold()
    if vendor == "Cursor":
        match = _CURSOR_THINKING.match(folded)
        if match and match.group("gradation") in GRADATIONS:
            version = match.group("version")
            gradation = match.group("gradation")
            return ModelName(
                label=label, resolved=True,
                api=f"{match.group('line')}-{gradation}-{version.replace('.', '-')}",
                line=match.group("line"), generation=_generation(version),
                version=version, gradation=gradation,
                strength=match.group("strength"), basis="tokenizer.cursor",
            )
        return None
    if vendor == "Claude":
        match = _CLAUDE.match(folded)
        if match and match.group("gradation") in GRADATIONS:
            version = match.group("version").replace("-", ".")
            return ModelName(
                label=label, resolved=True, api=folded, provider="anthropic",
                line="claude", generation=_generation(version), version=version,
                gradation=match.group("gradation"),
                gradation_rank=gradation_rank(match.group("gradation")),
                revision=match.group("revision"), basis="tokenizer.claude",
            )
        return None
    if vendor == "Codex":
        match = _CODEX.match(folded)
        if match and match.group("line") in LINES:
            version = match.group("version")
            suffix = match.group("suffix")
            return ModelName(
                label=label, resolved=True, api=folded, provider="openai",
                line=match.group("line"), generation=_generation(version),
                version=version,
                gradation=suffix if suffix in GRADATIONS else None,
                gradation_rank=(
                    gradation_rank(suffix) if suffix in GRADATIONS else None
                ),
                variant=suffix if suffix and suffix not in GRADATIONS else None,
                basis="tokenizer.codex",
            )
    return None


def resolve(label: object, vendor: str | None = None) -> ModelName:
    """Resolve one vendor model string.

    `vendor` is the adapter key (`Claude`, `Codex`, `Cursor`). It selects the fallback
    tokenizer only; the alias table is consulted for every vendor first, because a label
    one harness invents can name another's model.
    """
    if label is None:
        return ModelName(label="", basis="absent")
    text = str(label).strip()
    if not text:
        return ModelName(label="", basis="absent")
    aliases, sentinels = _table()
    folded = text.casefold()
    if folded in sentinels:
        return ModelName(label=text, sentinel=True, basis="sentinel")
    entry = aliases.get(folded)
    if entry is not None:
        return _from_alias(entry, text)
    tokenized = _tokenize(text, vendor)
    if tokenized is not None:
        return tokenized
    return ModelName(label=text, basis="unresolved")
