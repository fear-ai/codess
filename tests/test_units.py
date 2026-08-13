"""Byte-size conversion, kept as one symmetric set.

The reverse converters are used unevenly -- `BMB` at four sites, `BKB` and
`BGB` at none -- and dead-code detection reported the unused two. They are
retained deliberately: an incomplete set invites the next caller to write the
division inline, which is how one conversion acquires several spellings
(experiments/structural-analysis-tools.md).
"""

from __future__ import annotations

import pytest

from codess.units import BGB, BKB, BMB, GB, KB, MB


@pytest.mark.parametrize("forward,reverse,scale", [
    (KB, BKB, 1024),
    (MB, BMB, 1024**2),
    (GB, BGB, 1024**3),
])
def test_each_pair_is_an_inverse(forward, reverse, scale):
    """The property that makes the set worth keeping complete."""
    assert forward(1) == scale
    assert reverse(scale) == 1
    assert reverse(forward(7)) == 7


@pytest.mark.parametrize("convert,scale", [(KB, 1024), (MB, 1024**2), (GB, 1024**3)])
def test_forward_conversion_yields_whole_bytes(convert, scale):
    """A size in bytes is an integer; a fractional byte is not a size."""
    value = convert(1.5)
    assert isinstance(value, int)
    assert value == int(1.5 * scale)


@pytest.mark.parametrize("convert", [BKB, BMB, BGB])
def test_reverse_conversion_keeps_the_fraction(convert):
    """Reporting 1.5 MB as 1 would misstate what is stored."""
    assert isinstance(convert(1536), float)


def test_the_units_are_binary():
    """Codess reports sizes that the OS and SQLite also report as binary."""
    assert KB(1) == 1024
    assert MB(1) == 1_048_576
    assert GB(1) == 1_073_741_824


def test_zero_and_negative_pass_through():
    assert KB(0) == 0
    assert BMB(0) == 0.0
    assert MB(-1) == -1_048_576


def test_config_still_exposes_them():
    """Callers have long imported these from `config`; the path is kept."""
    from codess import config

    assert config.MB is MB
    assert config.BGB is BGB
