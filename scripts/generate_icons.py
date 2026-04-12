"""
Generate PWA icon PNGs from scratch using Pillow.

Reproduces the design from html/icons/icon-512.svg:
  - Dark background (#0a0f1e) with rounded corners
  - Blue border (#63b3ed)
  - "Pi" text in large bold monospace (#63b3ed)
  - "Driver" text below in smaller monospace (#48bb78)

Outputs:
  html/icons/icon-192.png  (192 x 192)
  html/icons/icon-512.png  (512 x 512)

Usage:
  pip install Pillow
  python scripts/generate_icons.py
"""

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("Pillow is not installed. Run:  pip install Pillow")

# ── Colour palette ────────────────────────────────────────────────────────────
BG    = (10, 15, 30)       # #0a0f1e
BLUE  = (99, 179, 237)     # #63b3ed
GREEN = (72, 187, 120)     # #48bb78

OUT_DIR = Path(__file__).parent.parent / "html" / "icons"


def _draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = round(size * 96 / 512)          # rx=96 at 512px, scaled

    # ── Background rounded rect ───────────────────────────────────────────
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=BG)

    # ── Border ───────────────────────────────────────────────────────────
    border = max(2, round(size * 8 / 512))   # stroke-width=8 at 512px
    margin = round(size * 32 / 512)          # x=32 at 512px
    draw.rounded_rectangle(
        [margin, margin, size - margin - 1, size - margin - 1],
        radius=max(2, round(size * 72 / 512)),
        outline=BLUE,
        width=border,
    )

    # ── "Pi" text ─────────────────────────────────────────────────────────
    pi_size   = round(size * 156 / 512)
    drv_size  = round(size * 40  / 512)

    try:
        # Prefer a system monospace font if available
        font_pi  = ImageFont.truetype("cour.ttf",  pi_size)
        font_drv = ImageFont.truetype("cour.ttf",  drv_size)
    except OSError:
        try:
            font_pi  = ImageFont.truetype("DejaVuSansMono.ttf", pi_size)
            font_drv = ImageFont.truetype("DejaVuSansMono.ttf", drv_size)
        except OSError:
            # Ultimate fallback: built-in bitmap font (no sizing)
            font_pi  = ImageFont.load_default()
            font_drv = ImageFont.load_default()

    cx = size // 2

    # "Pi" — vertically centred slightly above midpoint (y=295 at 512)
    pi_y = round(size * 295 / 512)
    bbox = draw.textbbox((0, 0), "Pi", font=font_pi)
    text_h = bbox[3] - bbox[1]
    draw.text((cx, pi_y - text_h), "Pi", font=font_pi, fill=BLUE, anchor="mt")

    # "Driver" — below "Pi" (y=370 at 512)
    drv_y = round(size * 370 / 512)
    bbox2 = draw.textbbox((0, 0), "Driver", font=font_drv)
    text_h2 = bbox2[3] - bbox2[1]
    draw.text((cx, drv_y - text_h2), "Driver", font=font_drv, fill=GREEN, anchor="mt")

    return img


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        img = _draw_icon(size)
        out = OUT_DIR / f"icon-{size}.png"
        img.save(out, "PNG", optimize=True)
        print(f"  Saved {out}  ({size}x{size})")
    print("Done.")


if __name__ == "__main__":
    main()
