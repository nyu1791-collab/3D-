"""Backgrounds and drawing styles: blackboard (default), whiteboard, gradient, or an image.

Everything is drawn here with Pillow (no third-party artwork). A theme decides the
background of every frame, the colours of generated cards (tables, charts,
points, quotes), and whether text looks like chalk.
"""

import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

THEMES = {
    "blackboard": {
        "card": None,  # cards are transparent: written straight on the board
        "ink": (243, 241, 232),
        "accent": (255, 228, 120),
        "muted": (196, 208, 196),
        "header_ink": (255, 228, 120),
        "rule": (230, 230, 220),
        "stripe": None,
        "bars": [(250, 250, 245), (255, 182, 200), (168, 214, 255), (255, 228, 120)],
        "title_ink": (243, 241, 232),
        "chalk": True,
    },
    "whiteboard": {
        "card": None,
        "ink": (32, 44, 70),
        "accent": (214, 52, 52),
        "muted": (110, 116, 128),
        "header_ink": (214, 52, 52),
        "rule": (120, 128, 140),
        "stripe": None,
        "bars": [(40, 96, 200), (214, 52, 52), (36, 150, 90), (240, 150, 30)],
        "title_ink": (32, 44, 70),
        "chalk": False,
    },
    "gradient": {
        "card": (250, 251, 253),
        "ink": (28, 33, 40),
        "accent": (255, 214, 0),
        "muted": (90, 98, 110),
        "header_ink": (255, 255, 255),
        "header_fill": (40, 62, 80),
        "rule": (200, 205, 212),
        "stripe": (236, 241, 246),
        "bars": [(126, 217, 87), (255, 126, 182), (90, 170, 230), (255, 214, 0)],
        "title_ink": (255, 255, 255),
        "chalk": False,
    },
}


def palette(name):
    return THEMES.get(name or "blackboard", THEMES["blackboard"])


def chalkify(layer, seed=7):
    """Rough, slightly broken strokes like chalk: thin out the alpha with noise."""
    if layer.mode != "RGBA":
        layer = layer.convert("RGBA")
    rng = random.Random(seed)
    noise = Image.effect_noise(layer.size, 70).point(lambda v: 255 if v > 70 + rng.random() * 4 else 150)
    alpha = ImageChops.multiply(layer.getchannel("A"), noise.filter(ImageFilter.GaussianBlur(0.6)))
    layer.putalpha(alpha)
    return layer


def _grain(draw, box, color, rng, lines=60):
    x0, y0, x1, y1 = box
    for _ in range(lines):
        y = rng.uniform(y0, y1)
        shade = tuple(max(0, min(255, c + rng.randint(-14, 10))) for c in color)
        draw.line([(x0, y), (x1, y + rng.uniform(-3, 3))], fill=shade, width=rng.randint(1, 3))


def _blackboard(size, band):
    w, h = size
    rng = random.Random(3)
    wood = (118, 78, 46)
    image = Image.new("RGB", size, wood)
    draw = ImageDraw.Draw(image)
    _grain(draw, (0, 0, w, h - band), wood, rng, 220)
    board = (26, 26, w - 26, h - band - 40)
    green = (33, 72, 52)
    draw.rectangle(board, fill=green)
    # Board texture and old eraser marks.
    noise = Image.effect_noise((board[2] - board[0], board[3] - board[1]), 18).convert("RGB")
    tinted = Image.blend(Image.new("RGB", noise.size, green), ImageChops.multiply(noise, Image.new("RGB", noise.size, (90, 140, 110))), 0.18)
    image.paste(tinted, board[:2])
    smudge = Image.new("RGBA", size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(smudge)
    for _ in range(9):
        cx, cy = rng.uniform(board[0], board[2]), rng.uniform(board[1], board[3])
        rx, ry = rng.uniform(120, 360), rng.uniform(40, 120)
        sdraw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(255, 255, 255, rng.randint(7, 15)))
    image = Image.alpha_composite(image.convert("RGBA"), smudge.filter(ImageFilter.GaussianBlur(40))).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle(board, outline=(70, 46, 26), width=4)
    # Chalk tray with a few sticks.
    tray = (26, board[3] + 4, w - 26, board[3] + 30)
    draw.rectangle(tray, fill=(140, 96, 58))
    _grain(draw, tray, (140, 96, 58), rng, 12)
    for x, color in [(w * 0.62, (250, 250, 245)), (w * 0.66, (255, 228, 120)), (w * 0.70, (255, 182, 200))]:
        draw.rounded_rectangle([x, tray[1] + 6, x + 70, tray[1] + 18], 6, fill=color)
    return image


def _whiteboard(size, band):
    w, h = size
    image = Image.new("RGB", size, (214, 218, 222))
    draw = ImageDraw.Draw(image)
    board = (30, 30, w - 30, h - band - 40)
    draw.rounded_rectangle(board, 8, fill=(250, 250, 248), outline=(176, 182, 190), width=14)
    shine = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(shine).polygon([(w * 0.55, board[1]), (w * 0.72, board[1]), (w * 0.42, board[3]), (w * 0.25, board[3])],
                                  fill=(255, 255, 255, 34))
    image = Image.alpha_composite(image.convert("RGBA"), shine.filter(ImageFilter.GaussianBlur(30))).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle([30, board[3] + 6, w - 30, board[3] + 26], fill=(176, 182, 190))
    for x, color in [(w * 0.62, (40, 96, 200)), (w * 0.67, (214, 52, 52)), (w * 0.72, (36, 150, 90))]:
        draw.rounded_rectangle([x, board[3] + 8, x + 90, board[3] + 22], 6, fill=color)
    return image


def background(size, theme="blackboard", image=None, band=170):
    """Full-canvas background for a frame."""
    if image and Path(image).is_file():
        art = Image.open(image).convert("RGB")
        scale = max(size[0] / art.width, size[1] / art.height)
        art = art.resize((round(art.width * scale), round(art.height * scale)), Image.LANCZOS)
        left, top = (art.width - size[0]) // 2, (art.height - size[1]) // 2
        return art.crop((left, top, left + size[0], top + size[1]))
    if theme == "whiteboard":
        return _whiteboard(size, band)
    if theme == "gradient":
        from .compose import _gradient

        return _gradient(size)
    return _blackboard(size, band)


def tape(width, height):
    """Two strips of masking tape for the top corners of a pinned page (RGBA layer)."""
    layer = Image.new("RGBA", (width + 60, height + 60), (0, 0, 0, 0))
    strip = Image.new("RGBA", (150, 40), (238, 226, 190, 210))
    for angle, (x, y) in [(-32, (-8, -8)), (32, (width - 92, -8))]:
        piece = strip.rotate(angle, expand=True, resample=Image.BICUBIC)
        layer.alpha_composite(piece, (max(0, x + 30), max(0, y + 22)))
    return layer
