"""Resolve a vendor model string to its API name, family, generation, strength, and speed.

Vendors spell the same model differently and order its parts differently, so one parser
would misread one vendor to satisfy another. Claude writes `claude-opus-4-8`, family
second and no strength; Cursor writes `claude-4.6-opus-high-thinking`, generation second,
family third, strength appended; Codex writes `gpt-5.6-sol`, which carries no family at
all. Resolution is therefore a table lookup first and a per-vendor tokenizer second.

**A name that resolves to nothing is recorded unresolved, never guessed.** The vendor
string is retained verbatim in every case; only the derived fields are left null. That
distinction is the point of the module: a store can state that it did not recognize a
model, which is different from stating the model had no family.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ALIAS_PATH = Path(__file__).resolve().parents[2] / "schema" / "model-aliases.json"

# Declared in the alias table and repeated here only as the fallback tokenizers' guard: a
# token outside this set is not accepted as a family merely because it sits in the family
# position. `mythos` is reserved and unobserved, so it resolves but is never inferred.
FAMILIES = frozenset({"opus", "sonnet", "haiku", "fable", "mython", "mythos"})


@dataclass(frozen=True)
class ModelName:
    """One resolved model string. `resolved` false means nothing below it is asserted."""

    label: str
    resolved: bool = False
    api: str | None = None
    provider: str | None = None
    family: str | None = None
    generation: str | None = None
    revision: str | None = None
    strength: str | None = None
    speed: str | None = None
    variant: str | None = None
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


def _from_alias(entry: dict, label: str) -> ModelName:
    return ModelName(
        label=label,
        resolved=True,
        api=entry.get("api"),
        provider=entry.get("provider"),
        family=entry.get("family"),
        generation=entry.get("generation"),
        revision=entry.get("revision"),
        strength=entry.get("strength"),
        speed=entry.get("speed"),
        variant=entry.get("variant"),
        basis="alias",
    )


# `claude-<family>-<gen>[-<gen2>][-<revision>]`: family second, generation dotted or
# hyphenated, an optional trailing date revision.
_CLAUDE = re.compile(
    r"^claude-(?P<family>[a-z]+)-(?P<gen>\d+(?:-\d+)?)(?:-(?P<revision>\d{6,}))?$"
)

# `gpt-<gen>[-<variant>]`: no family token, generation dotted, variant free-form.
_CODEX = re.compile(r"^gpt-(?P<gen>\d+(?:\.\d+)?)(?:-(?P<variant>[a-z0-9-]+))?$")

# `[cursor-]<vendor>-<gen>-<family>-<strength>-thinking` and the `-fast` suffix forms:
# generation precedes family here, which is the order Claude's own names invert.
_CURSOR_THINKING = re.compile(
    r"^(?P<vendor>[a-z]+)-(?P<gen>\d+(?:\.\d+)?)-(?P<family>[a-z]+)"
    r"-(?P<strength>[a-z]+)-thinking$"
)


def _tokenize(label: str, vendor: str | None) -> ModelName | None:
    """Per-vendor fallback for a name absent from the table."""
    folded = label.casefold()
    if vendor == "Cursor":
        match = _CURSOR_THINKING.match(folded)
        if match and match.group("family") in FAMILIES:
            gen = match.group("gen")
            return ModelName(
                label=label, resolved=True,
                api=f"{match.group('vendor')}-{match.group('family')}-{gen.replace('.', '-')}",
                family=match.group("family"), generation=gen,
                strength=match.group("strength"), basis="tokenizer.cursor",
            )
        return None
    if vendor == "Claude":
        match = _CLAUDE.match(folded)
        if match and match.group("family") in FAMILIES:
            return ModelName(
                label=label, resolved=True, api=folded,
                provider="anthropic", family=match.group("family"),
                generation=match.group("gen").replace("-", "."),
                revision=match.group("revision"), basis="tokenizer.claude",
            )
        return None
    if vendor == "Codex":
        match = _CODEX.match(folded)
        if match:
            return ModelName(
                label=label, resolved=True, api=folded, provider="openai",
                generation=match.group("gen"), variant=match.group("variant"),
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
