"""Génère les icônes PWA (soleil blanc sur terracotta) : python scripts/make_icons.py"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"
BG = (194, 94, 56)  # --primary, #c25e38
FG = (255, 255, 255)
SS = 4  # suréchantillonnage


def sun(draw: ImageDraw.ImageDraw, cx: float, cy: float, unit: float) -> None:
    """Soleil de la marque (viewBox 24) : disque r=4, 8 rayons de r=7 à r=9,5, trait 2, bouts ronds."""
    r = 4 * unit
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=FG)
    w = max(2, round(2 * unit))  # entier : trait et bouts ronds identiques
    for k in range(8):
        a = math.radians(45 * k)
        x0, y0 = cx + 7 * unit * math.cos(a), cy + 7 * unit * math.sin(a)
        x1, y1 = cx + 9.5 * unit * math.cos(a), cy + 9.5 * unit * math.sin(a)
        draw.line((x0, y0, x1, y1), fill=FG, width=w)
        for x, y in ((x0, y0), (x1, y1)):
            draw.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=FG)


def render(size: int, *, radius: float, extent: float, name: str) -> None:
    """radius : arrondi du fond (0 = plein cadre) ; extent : rayon du soleil en part de la taille."""
    s = size * SS
    img = Image.new("RGB", (s, s), BG)
    if radius:
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=radius * s, fill=255)
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        img.paste(Image.new("RGB", (s, s), BG), (0, 0), mask)
    sun(ImageDraw.Draw(img), s / 2, s / 2, extent * s / 10.5)
    img.resize((size, size), Image.LANCZOS).save(OUT / name, optimize=True)


if __name__ == "__main__":
    render(192, radius=0.22, extent=0.36, name="icon-192.png")
    render(512, radius=0.22, extent=0.36, name="icon-512.png")
    render(512, radius=0, extent=0.30, name="icon-maskable-512.png")  # zone de sécurité 80 %
    render(180, radius=0, extent=0.34, name="apple-touch-icon.png")  # iOS arrondit lui-même
