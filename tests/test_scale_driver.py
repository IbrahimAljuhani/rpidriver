"""
Tests for scale protocol parsers (toledo8217 and adam).

Pure-function tests — no hardware required.
"""

import pytest

from rpidriver.plugins.scale_driver import parse_adam, parse_toledo8217


# ── parse_toledo8217 ──────────────────────────────────────────────────────────


def test_toledo_parses_float_weight():
    result = parse_toledo8217(b"W+000001.234kg\r\n")
    assert result == {"weight": 1.234, "unit": "kg", "status": "ok"}


def test_toledo_parses_integer_weight():
    result = parse_toledo8217(b"W+000005kg\r\n")
    assert result == {"weight": 5.0, "unit": "kg", "status": "ok"}


def test_toledo_parses_negative_weight():
    result = parse_toledo8217(b"W-000000.500kg\r\n")
    assert result is not None
    assert result["weight"] == pytest.approx(-0.5)
    assert result["unit"] == "kg"


def test_toledo_parses_grams():
    result = parse_toledo8217(b"W+000250g\r\n")
    assert result is not None
    assert result["unit"] == "g"


def test_toledo_parses_with_prefix_question_mark():
    # Some Toledo frames start with '?W'
    result = parse_toledo8217(b"?W+000001.234kg\r\n")
    assert result is not None
    assert result["weight"] == pytest.approx(1.234)


def test_toledo_returns_none_on_garbage():
    assert parse_toledo8217(b"GARBAGE\r\n") is None


def test_toledo_returns_none_on_empty():
    assert parse_toledo8217(b"") is None


def test_toledo_returns_none_on_non_ascii():
    assert parse_toledo8217(b"\xff\xfe\x00") is None


# ── parse_adam ────────────────────────────────────────────────────────────────


def test_adam_parses_float_weight():
    result = parse_adam(b"+   0.500 kg\r\n")
    assert result is not None
    assert result["weight"] == pytest.approx(0.5)
    assert result["unit"] == "kg"


def test_adam_parses_zero_weight():
    result = parse_adam(b"+   0.000 kg\r\n")
    assert result is not None
    assert result["weight"] == pytest.approx(0.0)


def test_adam_parses_negative_weight():
    result = parse_adam(b"-   0.100 kg\r\n")
    assert result is not None
    assert result["weight"] == pytest.approx(-0.1)


def test_adam_parses_grams():
    result = parse_adam(b"+  250.000 g\r\n")
    assert result is not None
    assert result["unit"] == "g"


def test_adam_returns_none_on_garbage():
    assert parse_adam(b"GARBAGE\r\n") is None


def test_adam_returns_none_on_empty():
    assert parse_adam(b"") is None
