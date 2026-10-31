"""Frame and thumbnail composition with Pillow.

Layout (1920x1080):
  ┌ title bar ────────────────────────────────────────────┐
  │ ┌ quoted page (screenshot) ───────┐   めたん  ずんだもん │
  │ │                                 │   (speaker bright,  │
  │ └─────────────────────────────────┘    other dimmed)    │
  │  出典: example.com                                     │
  ├ caption band (subtitles are drawn by the renderer) ────┤
Character art is optional: put zundamon.png / metan.png (transparent PNG) in
the portraits folder and credit the artist in settings. Without them a
coloured badge with the name stands in.
"""

import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

COLORS = {"zundamon": (126, 217, 87), "metan": (255, 126, 182)}
NAMES = {"zundamon": "ずんだもん", "metan": "四国めたん"}
FALLBACK_FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "C:/Windows/Fonts/meiryob.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
]


@lru_cache(maxsize=None)
def _font_path(bold):
    try:
        query = "Noto Sans CJK JP:style=Bold" if bold else "Noto Sans CJK JP"
        found = subprocess.run(["fc-match", "-f", "%{file}", query], capture_output=True, text=True, timeout=10)
        if found.returncode == 0 and found.stdout and Path(found.stdout).is_file():
            return found.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return next((p for p in FALLBACK_FONTS if Path(p).is_file()), None)


@lru_cache(maxsize=None)
def font(size, bold=False):
    path = _font_path(bold)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)


def _gradient(size, top=(18, 32, 47), bottom=(28, 70, 64)):
    w, h = size
    base = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        base.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return base.resize((w, h))


def _fit(image, box):
    image = image.convert("RGB")
    scale = min(box[0] / image.width, box[1] / image.height)
    return image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.LANCZOS)


def _wrap(draw, text, face, width, limit):
    lines, line = [], ""
    for char in text:
        if draw.textlength(line + char, font=face) > width:
            lines.append(line)
            line = char
        else:
            line += char
    lines.append(line)
    if len(lines) > limit:
        lines = lines[:limit]
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def _badge(name, color, height):
    size = round(height * 0.42)
    image = Image.new("RGBA", (size, size + 70), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse([0, 0, size - 1, size - 1], fill=color + (255,), outline=(255, 255, 255, 255), width=8)
    face = font(round(size * 0.16), bold=True)
    width = draw.textlength(name, font=face)
    draw.text(((size - width) / 2, size * 0.42), name, font=face, fill=(20, 20, 20, 255))
    return image


def portrait(speaker, portraits, height, emotion=None):
    """<speaker>_<emotion>.png if present, else <speaker>.png, else a name badge."""
    path = None
    if portraits:
        for name in ([f"{speaker}_{emotion}.png"] if emotion else []) + [f"{speaker}.png"]:
            if (Path(portraits) / name).is_file():
                path = Path(portraits) / name
                break
    if path:
        art = Image.open(path).convert("RGBA")
        scale = height / art.height
        return art.resize((round(art.width * scale), height), Image.LANCZOS)
    return _badge(NAMES[speaker], COLORS[speaker], height)


def frame(path, *, title, shot, source, speaker, portraits=None, size=(1920, 1080), band=170, emotion=None):
    """One still for one speaker over one quoted page."""
    w, h = size
    canvas = _gradient(size).convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, w, 96], fill=(10, 18, 28, 255))
    draw.rectangle([0, 92, w, 98], fill=COLORS["zundamon"] + (255,))
    title_face = font(46, bold=True)
    draw.text((48, 20), _wrap(draw, title, title_face, w - 96, 1)[0], font=title_face, fill=(255, 255, 255, 255))

    panel = (round(w * 0.59), h - 96 - band - 110)  # same as visuals.panel
    if shot and Path(shot).is_file():
        page = _fit(Image.open(shot), panel)
        x, y = 56, 124
        shadow = Image.new("RGBA", (page.width + 40, page.height + 40), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rectangle([20, 20, page.width + 20, page.height + 20], fill=(0, 0, 0, 150))
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(12)), (x - 14, y - 8))
        framed = Image.new("RGB", (page.width + 12, page.height + 12), (255, 255, 255))
        framed.paste(page, (6, 6))
        canvas.paste(framed, (x - 6, y - 6))
        label_face = font(30)
        draw.rounded_rectangle([x - 6, y + page.height + 18, x + 24 + draw.textlength("出典: " + source, font=label_face), y + page.height + 66], 10, fill=(0, 0, 0, 170))
        draw.text((x + 8, y + page.height + 22), "出典: " + source, font=label_face, fill=(235, 235, 235, 255))
    elif source:
        # Visuals are layered on later; the source label sits under the panel area.
        label_face = font(30)
        y = 124 + panel[1] + 18
        draw.rounded_rectangle([50, y, 80 + draw.textlength("出典: " + source, font=label_face), y + 48], 10, fill=(0, 0, 0, 170))
        draw.text((64, y + 4), "出典: " + source, font=label_face, fill=(235, 235, 235, 255))

    height = h - 96 - band - 20
    right = w - 20
    placed = {}
    for name in ("zundamon", "metan"):  # zundamon at the far right, metan beside her
        art = portrait(
            name, portraits, round(height * (1.0 if name == speaker else 0.92)), emotion if name == speaker else None
        )
        if name != speaker:
            alpha = art.getchannel("A")
            art = ImageEnhance.Brightness(art.convert("RGB")).enhance(0.5).convert("RGBA")
            art.putalpha(alpha)
        x = right - art.width
        placed[name] = (art, (x, h - band - art.height))
        # Tall character art may overlap a little; stand-in badges sit side by side.
        has_art = bool(portraits) and (Path(portraits) / f"{name}.png").is_file()
        right = x + round(art.width * 0.25) if has_art else x - 16
    for name in sorted(placed, key=lambda n: n == speaker):  # the speaker is drawn last, in front
        art, position = placed[name]
        canvas.alpha_composite(art, position)

    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, h - band, w, h], fill=(0, 0, 0, 185))
    draw.rectangle([0, h - band, 14, h], fill=COLORS[speaker] + (255,))
    canvas.convert("RGB").save(path)
    return Path(path)


def thumbnail(path, *, text, shot=None, portraits=None, size=(1280, 720)):
    """Big two-line headline over the dimmed page, characters on the right."""
    w, h = size
    if shot and Path(shot).is_file():
        base = Image.open(shot).convert("RGB").resize(size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(3))
        base = ImageEnhance.Brightness(base).enhance(0.45)
    else:
        base = _gradient(size)
    canvas = base.convert("RGBA")
    art = portrait("zundamon", portraits, round(h * 0.9))
    canvas.alpha_composite(art, (w - art.width + 30, h - art.height))
    draw = ImageDraw.Draw(canvas)
    face = font(92, bold=True)
    lines = _wrap(draw, text, face, w - art.width - 40, 3)
    y = (h - len(lines) * 112) // 2
    for line in lines:
        draw.text((48, y), line, font=face, fill=(255, 229, 104, 255), stroke_width=8, stroke_fill=(0, 0, 0, 255))
        y += 112
    canvas.convert("RGB").save(path, quality=92)
    return Path(path)
