"""Regenerate the add-in's ribbon/store icons.

manifest.xml points at assets/icon-{16,32,64,80}.png; without them Excel shows
a blank button in the ribbon and the sideload validator warns on the missing
IconUrl. Committed as a generator rather than four opaque binaries so the
monogram, the navy, and the exact sizes stay editable.

    python tools/make_icons.py

Navy is #16324f — the same value taskpane.html uses for its heading and
buttons. Sizes come from the manifest: 16/32/80 for the ribbon, 32 for
IconUrl, 64 for HighResolutionIconUrl.
"""

import pathlib

from PIL import Image, ImageDraw, ImageFont

NAVY = (0x16, 0x32, 0x4F, 0xFF)
SIZES = (16, 32, 64, 80)
SUPERSAMPLE = 8  # draw big, downsample once — Pillow has no antialiased draw
FONT_CANDIDATES = ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf")
OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "src" / "assets"


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    raise SystemExit(f"No bold font found; tried {', '.join(FONT_CANDIDATES)}")


def render(size: int) -> Image.Image:
    box = size * SUPERSAMPLE
    img = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Rounded tile, inset slightly so the corners aren't clipped by the ribbon.
    inset = box * 0.03
    draw.rounded_rectangle((inset, inset, box - inset, box - inset),
                           radius=box * 0.18, fill=NAVY)
    font = _font(int(box * 0.62))
    # anchor="mm" centres on the glyph's own ink, not the font's line box, so
    # the B doesn't sit low the way a baseline-anchored draw would.
    draw.text((box / 2, box / 2 * 1.04), "B", font=font, fill=(255, 255, 255, 255),
              anchor="mm")
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        path = OUT_DIR / f"icon-{size}.png"
        render(size).save(path, "PNG", optimize=True)
        print(f"wrote {path.relative_to(OUT_DIR.parent.parent)}")


if __name__ == "__main__":
    main()
