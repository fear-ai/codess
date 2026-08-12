"""Contract for the single hash derivation and verification point."""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from codess.hashing import (
    GENERATED_BITS,
    SUPPORTED_TRUNCATED_BITS,
    HashContractError,
    canonical_bytes,
    codess_bytes_hash,
    codess_canonical_hash,
    codess_check_bytes_hash,
    codess_check_canonical_hash,
    codess_check_hash,
    codess_check_stream_hash,
    codess_digest,
    codess_hash,
    codess_stream_hash,
    codess_text_hash,
)

MODES = (
    ("components", lambda g, t: codess_hash(g, t, ["value"])),
    ("canonical", lambda g, t: codess_canonical_hash(g, t, {"a": 1})),
    ("bytes", lambda g, t: codess_bytes_hash(g, t, b"value")),
    ("stream", lambda g, t: codess_stream_hash(g, t, [b"val", b"ue"])),
    ("text", lambda g, t: codess_text_hash(g, t, "value")),
)


def test_supported_widths_are_the_declared_set():
    assert GENERATED_BITS == 256
    assert SUPPORTED_TRUNCATED_BITS == (256, 128, 64)


@pytest.mark.parametrize("name,call", MODES, ids=[m[0] for m in MODES])
@pytest.mark.parametrize("truncated_bits", SUPPORTED_TRUNCATED_BITS)
def test_output_width_matches_request(name, call, truncated_bits):
    value = call(256, truncated_bits)
    assert len(value) == truncated_bits // 4
    assert value == value.lower()
    int(value, 16)  # valid hex


@pytest.mark.parametrize("name,call", MODES, ids=[m[0] for m in MODES])
def test_truncation_keeps_leading_bits(name, call):
    """Shorter widths must be prefixes of the full value, not another region."""
    full = call(256, 256)
    assert call(256, 128) == full[:32]
    assert call(256, 64) == full[:16]


@pytest.mark.parametrize("name,call", MODES, ids=[m[0] for m in MODES])
@pytest.mark.parametrize("generated_bits", [128, 255, 512])
def test_unsupported_generated_width_is_rejected(name, call, generated_bits):
    with pytest.raises(HashContractError):
        call(generated_bits, 128)


@pytest.mark.parametrize("name,call", MODES, ids=[m[0] for m in MODES])
@pytest.mark.parametrize("truncated_bits", [32, 96, 129, 512])
def test_unsupported_truncated_width_is_rejected(name, call, truncated_bits):
    with pytest.raises(HashContractError):
        call(256, truncated_bits)


# --- component mode ---------------------------------------------------------

def test_inputs_are_separated_so_concatenation_cannot_collide():
    assert codess_hash(256, 256, ["ab", "c"]) != codess_hash(256, 256, ["a", "bc"])


def test_input_order_is_significant():
    assert codess_hash(256, 256, ["a", "b"]) != codess_hash(256, 256, ["b", "a"])


def test_bytes_and_text_inputs_are_both_accepted():
    assert codess_hash(256, 128, [b"value"]) == codess_hash(256, 128, ["value"])


def test_component_mode_is_tagged_and_differs_from_raw_bytes():
    """The format tag keeps component keys distinct from content digests."""
    assert codess_hash(256, 256, ["value"]) != codess_bytes_hash(256, 256, b"value")


# --- canonical mode ---------------------------------------------------------

def test_key_order_does_not_change_a_canonical_digest():
    assert codess_canonical_hash(256, 256, {"a": 1, "b": 2}) == codess_canonical_hash(
        256, 256, {"b": 2, "a": 1}
    )


def test_different_content_changes_a_canonical_digest():
    assert codess_canonical_hash(256, 256, {"a": 1}) != codess_canonical_hash(
        256, 256, {"a": 2}
    )


def test_canonical_bytes_emit_utf8_rather_than_escapes():
    """ensure_ascii=False is load-bearing: the two forms are different bytes."""
    assert canonical_bytes({"n": "café"}) == b'{"n":"caf\xc3\xa9"}'
    escaped = json.dumps(
        {"n": "café"}, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert canonical_bytes({"n": "café"}) != escaped


def test_undecodable_path_text_is_hashed_rather_than_raising():
    """A filename with invalid UTF-8 reaches Python as a lone surrogate."""
    import os

    name = os.fsdecode(b"caf\xe9")
    assert "\udce9" in name
    assert len(codess_canonical_hash(256, 256, {"path": name})) == 64
    assert len(codess_hash(256, 256, [name])) == 64


def test_canonical_digest_matches_a_hash_of_canonical_bytes():
    value = {"b": [1, 2], "a": "x"}
    expected = hashlib.sha256(canonical_bytes(value)).hexdigest()
    assert codess_canonical_hash(256, 256, value) == expected


# --- bytes and stream modes -------------------------------------------------

def test_text_mode_matches_a_utf8_digest_of_the_string():
    """Text digests must agree with an external digest of the same bytes."""
    assert codess_text_hash(256, 256, "payload") == hashlib.sha256(
        b"payload"
    ).hexdigest()
    assert codess_text_hash(256, 256, "café") == codess_bytes_hash(
        256, 256, "café".encode("utf-8")
    )


def test_text_mode_tolerates_lone_surrogates():
    import os

    assert len(codess_text_hash(256, 256, os.fsdecode(b"caf\xe9"))) == 64


def test_bytes_mode_matches_a_plain_sha256_of_the_content():
    """Content digests must agree with what an external tool computes."""
    assert codess_bytes_hash(256, 256, b"payload") == hashlib.sha256(
        b"payload"
    ).hexdigest()


def test_stream_and_bytes_modes_agree_on_the_same_content():
    chunks = [b"one", b"two", b"three"]
    assert codess_stream_hash(256, 256, chunks) == codess_bytes_hash(
        256, 256, b"".join(chunks)
    )


def test_stream_chunk_boundaries_do_not_change_the_result():
    assert codess_stream_hash(256, 256, [b"abcdef"]) == codess_stream_hash(
        256, 256, [b"ab", b"cd", b"ef"]
    )


def test_empty_input_is_hashed_rather_than_rejected():
    assert codess_stream_hash(256, 256, []) == codess_bytes_hash(256, 256, b"")


def test_codess_digest_supports_a_caller_owned_read_policy():
    digest = codess_digest()
    digest.update(b"abc")
    assert digest.hexdigest() == codess_bytes_hash(256, 256, b"abc")


# --- verification -----------------------------------------------------------

def test_check_accepts_matching_values_in_every_mode():
    assert codess_check_hash(256, 128, ["v"], codess_hash(256, 128, ["v"]))
    assert codess_check_canonical_hash(
        256, 128, {"a": 1}, codess_canonical_hash(256, 128, {"a": 1})
    )
    assert codess_check_bytes_hash(
        256, 128, b"v", codess_bytes_hash(256, 128, b"v")
    )
    assert codess_check_stream_hash(
        256, 128, [b"v"], codess_stream_hash(256, 128, [b"v"])
    )


def test_check_rejects_a_different_input():
    assert not codess_check_hash(256, 128, ["other"], codess_hash(256, 128, ["v"]))
    assert not codess_check_canonical_hash(
        256, 128, {"a": 2}, codess_canonical_hash(256, 128, {"a": 1})
    )
    assert not codess_check_bytes_hash(
        256, 128, b"other", codess_bytes_hash(256, 128, b"v")
    )


def test_check_rejects_a_value_of_another_width():
    full = codess_hash(256, 256, ["v"])
    assert not codess_check_hash(256, 128, ["v"], full)


def test_check_tolerates_case_and_surrounding_space():
    value = codess_hash(256, 128, ["v"])
    assert codess_check_hash(256, 128, ["v"], f"  {value.upper()}  ")


def test_check_rejects_empty_and_none_without_raising():
    assert not codess_check_hash(256, 128, ["v"], "")
    assert not codess_check_hash(256, 128, ["v"], None)
    assert not codess_check_bytes_hash(256, 128, b"v", None)


def test_underlying_algorithm_is_sha256_over_tagged_input():
    """Pin the construction so a silent algorithm change fails here first."""
    expected = hashlib.sha256(b"codess.hash/1\0value").hexdigest()
    assert codess_hash(256, 256, ["value"]) == expected


def test_direct_hashlib_use_is_confined_to_the_hashing_module():
    """Digest construction belongs in codess.hashing, with no exceptions.

    Four modules were exempt while they used truncation widths this module
    did not offer. W20 settled those widths -- the 48- and 96-bit sites moved
    to the narrowest supported 64 -- so the exemptions are gone and the rule
    is now what it always claimed to be.
    """
    root = pathlib.Path(__file__).resolve().parents[1] / "src"
    offenders = sorted(
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if p.name != "hashing.py" and "hashlib." in p.read_text(encoding="utf-8")
    )
    assert offenders == [], f"use codess.hashing instead of hashlib in: {offenders}"


def test_every_derived_width_is_a_supported_one():
    """No site may truncate to a width the module does not declare."""
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "src"
    unsupported = []
    for path in sorted(root.rglob("*.py")):
        for match in re.finditer(r"codess_\w*hash\(\s*(\d+),\s*(\d+)", path.read_text(encoding="utf-8")):
            truncated = int(match.group(2))
            if truncated not in SUPPORTED_TRUNCATED_BITS:
                unsupported.append(f"{path.name}: {truncated}")
    assert unsupported == [], f"unsupported truncation widths: {unsupported}"
