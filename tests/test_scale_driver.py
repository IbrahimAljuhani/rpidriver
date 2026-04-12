"""
Tests for scale protocol parsers (toledo8217 and adam).

Toledo 8217 real frame format (from Mettler-Toledo 8217 protocol manual):
    STX  <spaces>  <digits>[.<digits>]  [N]  CR
e.g. b'\\x02  1.234\\r'  or  b'\\x02  1234N\\r'

The driver sends 'W', the scale responds with one of these frames.

Pure-function tests — no hardware required.
"""

import pytest

from rpidriver.plugins.scale_driver import parse_adam, parse_toledo8217


# ── parse_toledo8217 ──────────────────────────────────────────────────────────


def test_toledo_parses_float_weight():
    # Real Toledo 8217 response frame: STX + spaces + digits + CR
    result = parse_toledo8217(b"\x02  1.234\r")
    assert result is not None
    assert result["weight"] == pytest.approx(1.234)
    assert result["unit"] == "kg"
    assert result["status"] == "ok"


def test_toledo_parses_integer_weight():
    result = parse_toledo8217(b"\x02  5\r")
    assert result is not None
    assert result["weight"] == pytest.approx(5.0)


def test_toledo_parses_negative_with_N_suffix():
    # Toledo uses 'N' suffix for negative weights on some firmware versions
    result = parse_toledo8217(b"\x02  500N\r")
    assert result is not None
    assert result["weight"] == pytest.approx(500.0)


def test_toledo_parses_zero():
    result = parse_toledo8217(b"\x02  0.000\r")
    assert result is not None
    assert result["weight"] == pytest.approx(0.0)


def test_toledo_returns_none_on_garbage():
    assert parse_toledo8217(b"GARBAGE\r\n") is None


def test_toledo_returns_none_on_empty():
    assert parse_toledo8217(b"") is None


def test_toledo_returns_none_on_non_ascii():
    assert parse_toledo8217(b"\xff\xfe\x00") is None


def test_toledo_strips_stx_and_whitespace():
    # Ensure STX and surrounding spaces don't break parsing
    result = parse_toledo8217(b"\x02   2.500\r")
    assert result is not None
    assert result["weight"] == pytest.approx(2.5)


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
