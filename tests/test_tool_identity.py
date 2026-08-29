import pytest

from codess.tool_identity import (
    SOURCE_CALL_ID_MAX_BYTES,
    bounded_source_call_id,
)


def test_short_source_call_id_is_unchanged():
    assert bounded_source_call_id("toolu_123") == "toolu_123"


def test_long_source_call_id_is_bounded_and_collision_resistant():
    first = bounded_source_call_id("x" * 150 + "a")
    second = bounded_source_call_id("x" * 150 + "b")
    assert len(first.encode("utf-8")) <= SOURCE_CALL_ID_MAX_BYTES
    assert len(second.encode("utf-8")) <= SOURCE_CALL_ID_MAX_BYTES
    assert first != second
    assert "~digest:" in first


def test_utf8_source_call_id_does_not_split_a_character():
    bounded = bounded_source_call_id("🙂" * 40)
    prefix, suffix = bounded.split("~digest:", 1)
    assert prefix
    assert len(suffix) == 64
    assert len(bounded.encode("utf-8")) <= SOURCE_CALL_ID_MAX_BYTES


def test_a_limit_too_small_for_the_derived_tail_is_refused():
    """The bound must leave room for the marker and the whole digest.

    The threshold is computed from `_SUFFIX_PREFIX`, so it moved when the
    marker names the derivation rather than the algorithm. A limit at or
    below the tail length would truncate the digest itself, which is what
    makes two distinct identifiers collide.
    """
    from codess.tool_identity import (
        _DIGEST_HEX_CHARS,
        _SUFFIX_PREFIX,
        bounded_source_call_id,
    )

    smallest_valid = len(_SUFFIX_PREFIX) + _DIGEST_HEX_CHARS + 1
    with pytest.raises(ValueError, match="too small"):
        bounded_source_call_id("x" * 500, max_bytes=smallest_valid - 1)
    bounded = bounded_source_call_id("x" * 500, max_bytes=smallest_valid)
    assert len(bounded.encode("utf-8")) <= smallest_valid


def test_the_derived_tail_does_not_name_the_algorithm():
    """`source_call_id` is a stored value, so it must not pin the digest.

    Naming SHA-256 here made changing the algorithm a wire-format change,
    which is the rule `hashing` exists to keep in one module.
    """
    from codess.tool_identity import bounded_source_call_id

    bounded = bounded_source_call_id("y" * 500)
    assert "~digest:" in bounded
    assert "sha256" not in bounded
