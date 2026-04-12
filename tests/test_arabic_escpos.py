"""
Tests for the Arabic RTL printing engine (arabic_escpos.py).

These tests run without real hardware — they test the bitmap rendering
and ESC/POS byte generation logic only.
"""

import pytest

from rpidriver.plugins.arabic_escpos import (
    _needs_image_rendering,
    image_to_escpos_raster,
    is_available,
    reshape_arabic,
)

# ── Dependency guard ──────────────────────────────────────────────────────────

pytestmark = pytest.mark.skipif(
    not is_available(),
    reason="arabic-reshaper / python-bidi / Pillow not installed",
)


# ── _needs_image_rendering ────────────────────────────────────────────────────


def test_needs_image_rendering_arabic():
    assert _needs_image_rendering("مرحبا") is True


def test_needs_image_rendering_latin():
    assert _needs_image_rendering("Hello World") is False


def test_needs_image_rendering_mixed():
    assert _needs_image_rendering("Total مجموع") is True


def test_needs_image_rendering_empty():
    assert _needs_image_rendering("") is False


# ── reshape_arabic ────────────────────────────────────────────────────────────


def test_reshape_arabic_returns_string():
    result = reshape_arabic("مرحبا بكم")
    assert isinstance(result, str)
    assert len(result) > 0


def test_reshape_arabic_latin_passthrough():
    """Latin text must pass through without corruption."""
    result = reshape_arabic("Hello")
    assert "Hello" in result


# ── image_to_escpos_raster ────────────────────────────────────────────────────


def test_raster_starts_with_gs_v_0():
    """ESC/POS raster command must begin with GS v 0 (0x1d 0x76 0x30 0x00)."""
    from PIL import Image

    img = Image.new("1", (64, 8), color=1)
    data = image_to_escpos_raster(img)
    assert data[:4] == b"\x1d\x76\x30\x00"


def test_raster_length_correct():
    """Output length = 4 (GS v 0 m) + 2 (xL xH) + 2 (yL yH) + w_bytes * height."""
    from PIL import Image

    width, height = 64, 16
    img = Image.new("1", (width, height), color=1)
    data = image_to_escpos_raster(img)
    byte_width = width // 8
    expected_len = 4 + 2 + 2 + byte_width * height
    assert len(data) == expected_len


def test_raster_all_white_image():
    """All-white image (no ink) must produce a zero-byte bitmap."""
    from PIL import Image

    img = Image.new("1", (8, 1), color=1)  # 1 = white in mode "1"
    data = image_to_escpos_raster(img)
    # header is 8 bytes, pixel data should be 0x00 (no black pixels)
    assert data[8:] == b"\x00"


def test_raster_all_black_image():
    """All-black image must produce a 0xFF bitmap."""
    from PIL import Image

    img = Image.new("1", (8, 1), color=0)  # 0 = black in mode "1"
    data = image_to_escpos_raster(img)
    assert data[8:] == b"\xff"


# ── render_arabic_line integration ───────────────────────────────────────────


def test_render_arabic_line_returns_bytes():
    from rpidriver.plugins.arabic_escpos import render_arabic_line

    result = render_arabic_line("مرحبا بكم في RPiDriver", width_px=576)
    assert isinstance(result, bytes)
    assert len(result) > 8  # header + at least some pixel data
    assert result[:4] == b"\x1d\x76\x30\x00"
