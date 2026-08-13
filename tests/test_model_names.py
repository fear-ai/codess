"""Model-name resolution: alias table, per-vendor tokenizers, and what stays unresolved."""

import json

import pytest

from codess.model_names import FAMILIES, resolve


class TestAliasTable:
    """A label present in the table resolves from data rather than parsing."""

    def test_claude(self):
        result = resolve("claude-opus-5", "Claude")
        assert (result.api, result.family, result.generation) == (
            "claude-opus-5", "opus", "5",
        )
        assert result.basis == "alias"

    def test_cursor_label(self):
        """Cursor states a label, not an API name, so the two differ here."""
        result = resolve("claude-4.6-opus-high-thinking", "Cursor")
        assert result.api == "claude-opus-4-6"
        assert result.label == "claude-4.6-opus-high-thinking"
        assert (result.family, result.generation, result.strength) == (
            "opus", "4.6", "high",
        )

    def test_case_folded(self):
        assert resolve("CLAUDE-OPUS-5", "Claude").api == "claude-opus-5"

    def test_provider_not_vendor(self):
        """A Cursor Session running an Anthropic model names Anthropic."""
        assert resolve("claude-4.6-opus-high-thinking", "Cursor").provider == "anthropic"
        assert resolve("grok-4.5", "Cursor").provider == "xai"
        assert resolve("composer-2", "Cursor").provider == "anysphere"


class TestTokenizers:
    """A name absent from the table is parsed by its own vendor's rules."""

    def test_claude_order(self):
        """Claude puts the family second and states no strength."""
        result = resolve("claude-opus-9-9", "Claude")
        assert (result.family, result.generation) == ("opus", "9.9")
        assert result.basis == "tokenizer.claude"

    def test_cursor_order(self):
        """Cursor puts the generation second and the family third, so the same
        parser cannot serve both; the API name is rebuilt in Claude's order."""
        result = resolve("claude-9.9-opus-low-thinking", "Cursor")
        assert result.api == "claude-opus-9-9"
        assert (result.family, result.generation, result.strength) == (
            "opus", "9.9", "low",
        )

    def test_codex_no_family(self):
        """Codex names carry a generation and a variant but no family token."""
        result = resolve("gpt-7.1-nova", "Codex")
        assert (result.generation, result.variant) == ("7.1", "nova")
        assert result.family is None

    def test_claude_revision(self):
        result = resolve("claude-haiku-9-9-20260101", "Claude")
        assert (result.family, result.generation, result.revision) == (
            "haiku", "9.9", "20260101",
        )

    def test_wrong_vendor_tokenizer(self):
        """A Cursor-shaped label offered as Claude does not parse: applying one
        vendor's order to another's name is the misreading this prevents."""
        assert resolve("claude-9.9-opus-low-thinking", "Claude").resolved is False

    def test_unknown_family(self):
        """The family position is not accepted merely because it is filled."""
        assert resolve("claude-zephyr-9-9", "Claude").resolved is False


class TestUnresolved:
    """What is not recognized is recorded as such, never guessed."""

    def test_unknown(self):
        result = resolve("totally-unknown", "Cursor")
        assert result.resolved is False
        assert result.label == "totally-unknown"
        assert (result.api, result.family, result.generation) == (None, None, None)
        assert result.basis == "unresolved"

    def test_synthetic(self):
        """Claude's own placeholder for no model, on 62 real records. A sentinel
        rather than a name, so it never yields a family."""
        result = resolve("<synthetic>", "Claude")
        assert result.sentinel is True
        assert result.resolved is False
        assert result.family is None

    def test_cursor_default(self):
        """`default` records the absence of a choice, not an unknown model."""
        result = resolve("default", "Cursor")
        assert result.sentinel is True
        assert result.resolved is False

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_absent(self, value):
        assert resolve(value, "Claude").basis == "absent"

    def test_no_vendor(self):
        """Without a vendor the table still applies; only the fallback needs one."""
        assert resolve("claude-opus-5").api == "claude-opus-5"
        assert resolve("claude-opus-9-9").resolved is False


def test_every_observed_name_resolves():
    """Every model name in the real corpus resolves or is a declared sentinel.

    The list is the distinct set across all three vendors' stores. A vendor
    shipping a new name is expected; one already observed and unresolved means
    the table drifted from the evidence.
    """
    observed = {
        "Claude": [
            "claude-opus-5", "claude-sonnet-5", "claude-fable-5",
            "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        ],
        "Codex": [
            "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.5", "gpt-5.4",
            "gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.1-codex-max",
        ],
        "Cursor": [
            "claude-4.6-opus-high-thinking", "composer-1.5", "composer-2",
            "composer-2.5", "grok-4.5", "grok-4.6",
        ],
    }
    for vendor, names in observed.items():
        for name in names:
            assert resolve(name, vendor).resolved, f"{vendor}: {name}"


def test_alias_families_match_the_vocabulary():
    """The table's own family values stay inside the declared vocabulary."""
    from codess.model_names import ALIAS_PATH

    data = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
    declared = set(data["families"]["vocabulary"]) | set(data["families"]["reserved"])
    assert declared == set(FAMILIES)
    for entry in data["aliases"]:
        if entry.get("family"):
            assert entry["family"] in declared, entry["label"]


class TestSpeedAndStrength:
    """Cursor states both in one label, so they resolve to separate fields."""

    def test_both(self):
        """`cursor-grok-4.5-high-fast` is a high reasoning strength at a fast
        speed tier. Collapsing them into one field would lose one."""
        result = resolve("cursor-grok-4.5-high-fast", "Cursor")
        assert (result.strength, result.speed) == ("high", "fast")

    def test_speed_only(self):
        result = resolve("composer-2-fast", "Cursor")
        assert (result.strength, result.speed) == (None, "fast")
        assert result.api == "composer-2"

    def test_strength_only(self):
        result = resolve("claude-4.6-opus-high-thinking", "Cursor")
        assert (result.strength, result.speed) == ("high", None)
