"""
Arabic RTL printing engine for ESC/POS printers.

ESC/POS printers have no native Arabic Unicode support.  This module:
  1. Reshapes Arabic letters to their contextual forms (arabic_reshaper)
  2. Applies the Unicode Bidirectional Algorithm (python-bidi)
  3. Renders the result to a 1-bit PIL Image (Pillow)
  4. Encodes the bitmap as a GS v 0 ESC/POS raster command

Usage:
    from rpidriver.plugins.arabic_escpos import render_arabic_line, image_to_escpos_raster

    escpos_bytes = render_arabic_line("مرحبا بكم", width_px=576)
"""

import functools
import logging
import struct

logger = logging.getLogger(__name__)

# Warn once per process if arabic_font_path is not configured
_font_warning_issued = False

# ── Optional dependency guard ─────────────────────────────────────────────────

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    from PIL import Image, ImageDraw, ImageFont

    _ARABIC_SUPPORT = True

    @functools.lru_cache(maxsize=8)
    def _load_font(path: str, size: int):
        """Load a TrueType font; cached so the file is read only once per (path, size) pair."""
        return ImageFont.truetype(path, size)

except ImportError:
    _ARABIC_SUPPORT = False
    logger.warning(
        "Arabic printing dependencies not installed. "
        "Run: pip install arabic-reshaper python-bidi Pillow"
    )

    def _load_font(path: str, size: int):  # type: ignore[misc]
        raise RuntimeError("arabic-reshaper / python-bidi / Pillow not installed.")


# ── Public API ────────────────────────────────────────────────────────────────


def is_available() -> bool:
    """Return True if all Arabic printing dependencies are installed."""
    return _ARABIC_SUPPORT


def reshape_arabic(text: str) -> str:
    """
    Reshape Arabic text to contextual letter forms and apply bidi reordering.

    Non-Arabic text is returned unchanged.
    """
    if not _ARABIC_SUPPORT:
        raise RuntimeError("arabic-reshaper / python-bidi not installed.")
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)


def render_arabic_line(
    text: str,
    width_px: int = 576,
    font_path: str | None = None,
    font_size: int = 24,
    padding: int = 4,
) -> bytes:
    """
    Render a single line of Arabic (or mixed) text to ESC/POS raster bytes.

    Parameters
    ----------
    text      : The text to render (UTF-8 string, may contain Arabic).
    width_px  : Printer paper width in pixels (576 = 80mm @ 203dpi).
    font_path : Path to a TTF font supporting Arabic (e.g. NotoSansArabic).
                Falls back to PIL default if None — results will be ugly for Arabic.
    font_size : Font size in points.
    padding   : Vertical padding around the text in pixels.

    Returns
    -------
    bytes — ESC/POS GS v 0 raster command ready to send to the printer.
    """
    global _font_warning_issued

    if not _ARABIC_SUPPORT:
        raise RuntimeError("arabic-reshaper / python-bidi not installed.")

    visual_text = reshape_arabic(text)

    # ── Load font ─────────────────────────────────────────────────────────
    if font_path:
        font = _load_font(font_path, font_size)
    else:
        if not _font_warning_issued:
            logger.warning(
                "arabic_font_path not set — using PIL default bitmap font. "
                "Arabic characters will not render correctly. "
                "Set arabic_font_path in config.ini [escpos_driver]."
            )
            _font_warning_issued = True
        font = ImageFont.load_default()

    # ── Measure text ──────────────────────────────────────────────────────
    tmp = Image.new("1", (width_px, 1))
    draw = ImageDraw.Draw(tmp)
    bbox = draw.textbbox((0, 0), visual_text, font=font)
    text_height = bbox[3] - bbox[1]
    text_width = bbox[2] - bbox[0]

    # Guard against zero/negative height (empty string, unusual font metrics)
    img_height = max(1, text_height + padding * 2)

    # ── Draw on real image ────────────────────────────────────────────────
    img = Image.new("1", (width_px, img_height), color=1)  # white background
    draw = ImageDraw.Draw(img)

    # Right-align Arabic text; clamp x so text is never clipped on the left
    x = max(0, width_px - text_width - padding)
    y = padding

    draw.text((x, y), visual_text, font=font, fill=0)  # black ink

    return image_to_escpos_raster(img)


def render_receipt_lines(
    lines: list[str],
    width_px: int = 576,
    font_path: str | None = None,
    font_size: int = 24,
) -> bytes:
    """
    Render a list of text lines (Arabic or Latin) to ESC/POS bytes.

    Arabic lines are rendered as bitmaps; pure ASCII/Latin lines are sent
    as raw text commands for better performance.
    """
    parts = []
    for line in lines:
        if _needs_image_rendering(line):
            parts.append(render_arabic_line(
                line, width_px=width_px, font_path=font_path, font_size=font_size
            ))
        else:
            parts.append(line.encode("cp437", errors="replace") + b"\n")
    return b"".join(parts)


def image_to_escpos_raster(img) -> bytes:
    """
    Convert a PIL Image (mode "1" or "L") to an ESC/POS GS v 0 raster command.

    ESC/POS GS v 0 format:
        GS v 0 m xL xH yL yH d1...dk
    where:
        m   = 0 (normal density)
        xL,xH = (byte_width) & 0xFF, (byte_width) >> 8
        yL,yH = (height) & 0xFF, (height) >> 8
        d1..dk = bitmap data, MSB first, 8 pixels per byte
    """
    if img.mode != "1":
        img = img.convert("1")

    width, height = img.size
    byte_width = (width + 7) // 8
    padded_width = byte_width * 8

    if padded_width != width:
        padded = Image.new("1", (padded_width, height), color=1)
        padded.paste(img, (0, 0))
        img = padded

    pixels = img.load()
    data = bytearray()
    for y in range(height):
        for bx in range(byte_width):
            byte = 0
            for bit in range(8):
                x = bx * 8 + bit
                # PIL mode "1": 0 = black, 255 = white
                if pixels[x, y] == 0:
                    byte |= 1 << (7 - bit)
            data.append(byte)

    header = (
        b"\x1d\x76\x30\x00"
        + struct.pack("<H", byte_width)
        + struct.pack("<H", height)
    )
    return header + bytes(data)


# ── Internal helpers ──────────────────────────────────────────────────────────

# Arabic Unicode blocks detected for bitmap rendering:
#   U+0600–U+06FF  Arabic (main block)
#   U+0750–U+077F  Arabic Supplement
#   U+FB50–U+FDFF  Arabic Presentation Forms-A
#   U+FE70–U+FEFF  Arabic Presentation Forms-B
def _needs_image_rendering(text: str) -> bool:
    """Return True if the text contains Arabic characters requiring bitmap rendering."""
    return any(
        0x0600 <= ord(c) < 0x0700
        or 0x0750 <= ord(c) < 0x0780
        or 0xFB50 <= ord(c) < 0xFE00
        or 0xFE70 <= ord(c) < 0xFF00
        for c in text
    )
