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
    assert "~sha256:" in first


def test_utf8_source_call_id_does_not_split_a_character():
    bounded = bounded_source_call_id("🙂" * 40)
    prefix, suffix = bounded.split("~sha256:", 1)
    assert prefix
    assert len(suffix) == 64
    assert len(bounded.encode("utf-8")) <= SOURCE_CALL_ID_MAX_BYTES
