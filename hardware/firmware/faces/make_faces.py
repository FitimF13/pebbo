"""Draw Pebbo's face for every emotion the firmware knows, in the style of the concept image.

Glowing warm-white eyes, pink blush and a pink mouth on black, like the concept's visor.
The firmware shows the picture for each emotion name (xiaozhi's 21 names, see
docs/devices.md); Pebbo's own emotions are mapped to them in the core.

    uv run --with pillow python make_faces.py
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).parent / "png"
W, H = 300, 176
SCALE = 4  # draw large, then shrink, for smooth edges
EYE = (255, 236, 205)
PINK = (255, 150, 170)
MOUTH = (255, 140, 160)
TONGUE = (255, 190, 200)
BLUSH = (255, 120, 140)
CX, EYE_Y, EYE_DX, MOUTH_Y = W / 2, 70, 62, 118

Draw = ImageDraw.ImageDraw


def s(value: float) -> int:
    return round(value * SCALE)


def arc(d: Draw, x: float, y: float, rx: float, ry: float, start: float, end: float, width: float, colour: tuple[int, int, int]) -> None:
    d.arc([s(x - rx), s(y - ry), s(x + rx), s(y + ry)], start, end, fill=colour, width=s(width))


def happy_eyes(d: Draw, y: float = EYE_Y, rx: float = 24) -> None:
    for side in (-1, 1):
        arc(d, CX + side * EYE_DX, y + 10, rx, 20, 195, 345, 10, EYE)


def sleepy_eyes(d: Draw) -> None:
    for side in (-1, 1):
        arc(d, CX + side * EYE_DX, EYE_Y - 6, 20, 14, 25, 155, 7, EYE)


def open_eyes(d: Draw, rx: float = 13, ry: float = 19, dy: float = 0) -> None:
    for side in (-1, 1):
        x = CX + side * EYE_DX
        d.ellipse([s(x - rx), s(EYE_Y + dy - ry), s(x + rx), s(EYE_Y + dy + ry)], fill=EYE)


def blush(d: Draw, strength: int = 3) -> None:
    for side in (-1, 1):
        for k in range(strength):
            x = CX + side * (EYE_DX + 14 + k * 9)
            d.line([s(x), s(EYE_Y + 26), s(x - side * 5), s(EYE_Y + 36)], fill=BLUSH, width=s(3))


def smile_open(d: Draw, w: float = 24, h: float = 20) -> None:
    d.pieslice([s(CX - w), s(MOUTH_Y - h), s(CX + w), s(MOUTH_Y + h)], 0, 180, fill=MOUTH)
    d.ellipse([s(CX - w * 0.5), s(MOUTH_Y + h * 0.35), s(CX + w * 0.5), s(MOUTH_Y + h * 0.95)], fill=TONGUE)


def smile_line(d: Draw, w: float = 18, h: float = 10) -> None:
    arc(d, CX, MOUTH_Y - 4, w, h, 20, 160, 6, MOUTH)


def frown(d: Draw) -> None:
    arc(d, CX, MOUTH_Y + 12, 16, 10, 200, 340, 6, MOUTH)


def o_mouth(d: Draw, r: float = 11) -> None:
    d.ellipse([s(CX - r * 0.8), s(MOUTH_Y - r), s(CX + r * 0.8), s(MOUTH_Y + r)], fill=MOUTH)


def heart(d: Draw, x: float, y: float, size: float) -> None:
    r = size / 2
    d.ellipse([s(x - size), s(y - r), s(x), s(y + r)], fill=PINK)
    d.ellipse([s(x), s(y - r), s(x + size), s(y + r)], fill=PINK)
    d.polygon([(s(x - size), s(y + 2)), (s(x + size), s(y + 2)), (s(x), s(y + size * 1.25))], fill=PINK)


def tongue_out(d: Draw) -> None:
    smile_line(d, 20, 9)
    d.rounded_rectangle([s(CX - 7), s(MOUTH_Y + 2), s(CX + 7), s(MOUTH_Y + 18)], radius=s(7), fill=TONGUE)


def face(draw_parts: Callable[[Draw], None]) -> Image.Image:
    big = Image.new("RGB", (W * SCALE, H * SCALE), (0, 0, 0))
    draw_parts(ImageDraw.Draw(big))
    sharp = big.resize((W, H), Image.LANCZOS)
    glow = sharp.filter(ImageFilter.GaussianBlur(5))
    out = Image.blend(sharp, glow, 0.0)
    pixels = [min(255, a + int(b * 0.55)) for a, b in zip(sharp.tobytes(), glow.tobytes(), strict=True)]
    out = Image.frombytes("RGB", sharp.size, bytes(pixels))
    return out


def wink(d: Draw) -> None:
    arc(d, CX - EYE_DX, EYE_Y + 8, 21, 17, 200, 340, 8, EYE)
    x = CX + EYE_DX
    d.ellipse([s(x - 13), s(EYE_Y - 19), s(x + 13), s(EYE_Y + 19)], fill=EYE)


FACES: dict[str, Callable[[Draw], None]] = {
    "neutral": lambda d: (open_eyes(d), smile_line(d, 14, 7)),
    "happy": lambda d: (happy_eyes(d), blush(d), smile_open(d)),
    "laughing": lambda d: (happy_eyes(d, EYE_Y - 4, 23), blush(d), smile_open(d, 30, 26)),
    "funny": lambda d: (wink(d), blush(d), tongue_out(d)),
    "sad": lambda d: (sleepy_eyes(d), frown(d)),
    "angry": lambda d: (
        [d.line([s(CX + side * (EYE_DX - 18)), s(EYE_Y - 4 + 0), s(CX + side * (EYE_DX + 18)), s(EYE_Y - 14)], fill=EYE, width=s(7)) for side in (-1, 1)],
        open_eyes(d, 11, 11, 8),
        frown(d),
    ),
    "crying": lambda d: (
        sleepy_eyes(d),
        [d.ellipse([s(CX + side * EYE_DX - 5), s(EYE_Y + 14), s(CX + side * EYE_DX + 5), s(EYE_Y + 30)], fill=(140, 200, 255)) for side in (-1, 1)],
        frown(d),
    ),
    "loving": lambda d: ([heart(d, CX + side * EYE_DX, EYE_Y - 6, 18) for side in (-1, 1)], blush(d), smile_open(d)),
    "embarrassed": lambda d: (happy_eyes(d), blush(d, 4), arc(d, CX, MOUTH_Y, 12, 6, 20, 160, 5, MOUTH)),
    "surprised": lambda d: (open_eyes(d, 15, 21), o_mouth(d)),
    "shocked": lambda d: (open_eyes(d, 18, 25), o_mouth(d, 16)),
    "thinking": lambda d: (open_eyes(d, 11, 17, -8), d.line([s(CX - 12), s(MOUTH_Y + 2), s(CX + 14), s(MOUTH_Y - 2)], fill=MOUTH, width=s(6))),
    "winking": lambda d: (wink(d), blush(d), smile_line(d)),
    "cool": lambda d: (
        d.rounded_rectangle([s(CX - EYE_DX - 30), s(EYE_Y - 14), s(CX + EYE_DX + 30), s(EYE_Y + 14)], radius=s(12), fill=EYE),
        d.rectangle([s(CX - 14), s(EYE_Y - 14), s(CX + 14), s(EYE_Y - 4)], fill=(0, 0, 0)),
        smile_line(d),
    ),
    "relaxed": lambda d: (sleepy_eyes(d), blush(d, 2), smile_line(d)),
    "delicious": lambda d: (happy_eyes(d), blush(d), tongue_out(d)),
    "kissy": lambda d: (happy_eyes(d), blush(d), heart(d, CX + 34, MOUTH_Y - 18, 9), o_mouth(d, 7)),
    "confident": lambda d: (
        [arc(d, CX + side * EYE_DX, EYE_Y + 2, 20, 12, 200, 340, 8, EYE) for side in (-1, 1)],
        arc(d, CX + 6, MOUTH_Y - 6, 20, 10, 10, 120, 6, MOUTH),
    ),
    "sleepy": lambda d: (
        sleepy_eyes(d),
        o_mouth(d, 6),
        [d.text((s(CX + 95 + i * 12), s(30 - i * 14)), "z", fill=EYE, font_size=s(16 + i * 6)) for i in range(2)],
    ),
    "silly": lambda d: (
        open_eyes(d, 9, 13),
        d.ellipse([s(CX + EYE_DX - 18), s(EYE_Y - 24), s(CX + EYE_DX + 18), s(EYE_Y + 24)], fill=EYE),
        tongue_out(d),
    ),
    "confused": lambda d: (
        open_eyes(d, 12, 18),
        d.line([(s(CX - 20 + i * 8), s(MOUTH_Y + (4 if i % 2 else -4))) for i in range(6)], fill=MOUTH, width=s(5), joint="curve"),
    ),
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, parts in FACES.items():
        face(parts).save(OUT / f"{name}.png", optimize=True)
    sheet = Image.new("RGB", (W * 7, H * 3), (20, 16, 24))
    for index, name in enumerate(FACES):
        sheet.paste(Image.open(OUT / f"{name}.png"), ((index % 7) * W, (index // 7) * H))
    sheet.save(Path(__file__).parent / "faces.png")
    print(f"{len(FACES)} faces in {OUT}")


if __name__ == "__main__":
    main()
