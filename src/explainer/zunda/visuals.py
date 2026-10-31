"""Moving visuals for one explanation line: article crops with a highlight,
tables that fill row by row, bar charts that grow, key points that appear one by
one, quote cards and chapter cards.

Every builder returns a list of render layers (see explainer.render.layer_graph):
{image, x, y, w, h, motion, start, end[, focus, visible_h]} placed inside the panel.
Numbers and quotes shown on screen come from the article; the script step checks
that before anything is drawn.
"""

from pathlib import Path

from PIL import Image, ImageDraw

from . import themes
from .compose import _wrap, font

ACCENT = (255, 214, 0)
PANEL_WIDTH = 0.59
INK = (28, 33, 40)
PAPER = (250, 251, 253)


def panel(size, band=170, theme="gradient"):
    """The area visuals may use: left of the characters, between title bar and captions."""
    w, h = size
    # Ends left of the two characters (each about 42% of the free height wide).
    return {"x": 56, "y": 124, "w": round(w * PANEL_WIDTH), "h": h - 96 - band - 110, "theme": theme}


def _ink(area, key="ink"):
    return themes.palette(area.get("theme"))[key]


def _finish(area, card):
    """Chalk texture on the blackboard; other themes keep crisp lines."""
    return themes.chalkify(card) if themes.palette(area.get("theme"))["chalk"] else card


def _save(image, folder, name):
    path = Path(folder) / f"{name}.png"
    image.save(path)
    return path


def _bordered(image, border=6):
    framed = Image.new("RGB", (image.width + 2 * border, image.height + 2 * border), (255, 255, 255))
    framed.paste(image, (border, border))
    return framed


def _fit(image, box_w, box_h):
    scale = min(box_w / image.width, box_h / image.height)
    return image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.LANCZOS)


def _place(area, image):
    """Centre an image inside the panel; returns x, y."""
    return area["x"] + (area["w"] - image.width) // 2, area["y"] + (area["h"] - image.height) // 2


# ---------------------------------------------------------------- article crops
def article_crop(meta, box, area, folder, name, duration, highlight=True):
    """Window of the page around a box (CSS px), the box outlined, zooming toward it."""
    page = Image.open(meta["page"]).convert("RGB")
    scale = float(meta.get("scale", 1.5))
    x, y, bw, bh = [v * scale for v in box]
    aspect = area["w"] / area["h"]
    win_w = min(page.width, max(bw * 1.6, 900 * scale / 1.5))
    win_h = min(page.height, win_w / aspect)
    if bh * 1.3 > win_h:  # tall element: widen the window instead
        win_h = min(page.height, bh * 1.3)
        win_w = min(page.width, win_h * aspect)
    left = min(max(0, x + bw / 2 - win_w / 2), page.width - win_w)
    top = min(max(0, y + bh / 2 - win_h / 2), page.height - win_h)
    crop = page.crop((round(left), round(top), round(left + win_w), round(top + win_h)))
    if highlight:
        draw = ImageDraw.Draw(crop)
        pad = 8 * scale
        rect = [x - left - pad, y - top - pad, x - left + bw + pad, y - top + bh + pad]
        draw.rounded_rectangle(rect, radius=12, outline=(232, 52, 52), width=max(4, round(4 * scale)))
    image = _bordered(_fit(crop, area["w"] - 12, area["h"] - 12))
    px, py = _place(area, image)
    focus = ((x + bw / 2 - left) / win_w, (y + bh / 2 - top) / win_h)
    return _pinned(area, {"image": _save(image, folder, name), "x": px, "y": py, "w": image.width, "h": image.height,
                          "motion": "focus" if highlight else "zoom", "focus": focus, "start": 0, "end": duration},
                   folder, name)


def _pinned(area, layer, folder, name):
    """On a board, pages look pinned: a still tape layer above the moving page."""
    if area.get("theme") not in ("blackboard", "whiteboard"):
        return [layer]
    strips = themes.tape(layer["w"], min(layer["h"], layer.get("visible_h", layer["h"])))
    return [layer, {"image": _save(strips, folder, name + "-tape"), "x": layer["x"] - 30, "y": layer["y"] - 30,
                    "w": strips.width, "h": strips.height, "motion": "still", "start": layer["start"],
                    "end": layer["end"], "decor": True}]


def page_top(meta, area, folder, name, duration):
    """The top of the article, slowly pushing in."""
    page = Image.open(meta["page"]).convert("RGB")
    aspect = area["w"] / area["h"]
    # Start just above the headline: menus and banners above it are not the story.
    heading = meta.get("heading")
    top = max(0, round((heading[1] - 40) * float(meta.get("scale", 1.5)))) if heading else 0
    top = min(top, max(0, page.height - round(page.width / aspect)))
    crop = page.crop((0, top, page.width, min(page.height, top + round(page.width / aspect))))
    image = _bordered(_fit(crop, area["w"] - 12, area["h"] - 12))
    px, py = _place(area, image)
    return _pinned(area, {"image": _save(image, folder, name), "x": px, "y": py, "w": image.width, "h": image.height,
                          "motion": "zoom", "start": 0, "end": duration}, folder, name)


def page_scroll(meta, area, folder, name, duration):
    """Scroll down the article while a line is spoken (shows how long/rich it is)."""
    page = Image.open(meta["page"]).convert("RGB")
    width = area["w"] - 12
    scaled = page.resize((width, round(page.height * width / page.width)), Image.LANCZOS)
    visible = min(scaled.height, area["h"] - 12)
    scaled = scaled.crop((0, 0, width, min(scaled.height, visible * 4)))
    image = _bordered(scaled)
    return _pinned(area, {"image": _save(image, folder, name), "x": area["x"], "y": area["y"], "w": image.width,
                          "h": image.height, "visible_h": visible + 12, "motion": "pan", "start": 0, "end": duration},
                   folder, name)


# ---------------------------------------------------------------- generated cards
def _card(area, height=None):
    """A paper card (gradient theme) or a transparent sheet written on the board."""
    paper = themes.palette(area.get("theme"))["card"]
    size = (area["w"], height or area["h"])
    return Image.new("RGB", size, paper) if paper else Image.new("RGBA", size, (0, 0, 0, 0))


def _steps(images, area, folder, name, duration, reveal=0.45):
    """Show images one after another (each a fuller version), the last one stays."""
    layers, count = [], len(images)
    step = min(reveal, duration * 0.6 / max(1, count))
    for index, image in enumerate(images):
        start = index * step
        end = duration if index == count - 1 else (index + 1) * step
        px, py = _place(area, image)
        layers.append({"image": _save(image, folder, f"{name}-{index:02d}"), "x": px, "y": py, "w": image.width,
                       "h": image.height, "motion": "pop" if index == 0 else "still", "start": round(start, 3),
                       "end": round(end, 3)})
    return layers


def table_steps(rows, area, folder, name, duration, title=""):
    rows = [[str(c)[:24] for c in row[:5]] for row in rows if any(str(c).strip() for c in row)][:8]
    if len(rows) < 2:
        return []
    pal = themes.palette(area.get("theme"))
    columns = max(len(r) for r in rows)
    rows = [r + [""] * (columns - len(r)) for r in rows]
    face, head = font(32), font(32, bold=True)
    title_h = 76 if title else 0
    row_h = min(80, (area["h"] - title_h - 40) // len(rows))
    col_w = (area["w"] - 60) // columns
    frames = []
    for shown in range(2, len(rows) + 1):
        card = _card(area)
        draw = ImageDraw.Draw(card)
        if title:
            draw.text((30, 14), _wrap(draw, title, head, area["w"] - 60, 1)[0], font=head, fill=pal["accent"])
        for r, row in enumerate(rows[:shown]):
            top = title_h + 20 + r * row_h
            if pal.get("header_fill") and r == 0:
                draw.rectangle([30, top, area["w"] - 30, top + row_h - 4], fill=pal["header_fill"])
            elif pal.get("stripe") and r % 2:
                draw.rectangle([30, top, area["w"] - 30, top + row_h - 4], fill=pal["stripe"])
            if not pal.get("header_fill"):  # board themes: hand-drawn rules
                draw.line([(30, top + row_h - 4), (area["w"] - 30, top + row_h - 2)], fill=pal["rule"], width=4 if r == 0 else 2)
            ink = pal["header_ink"] if r == 0 else pal["ink"]
            for c, cell in enumerate(row):
                text = _wrap(draw, cell, head if r == 0 else face, col_w - 20, 1)[0]
                draw.text((44 + c * col_w, top + (row_h - 44) // 2), text, font=head if r == 0 else face, fill=ink)
        frames.append(_finish(area, card))
    return _steps(frames, area, folder, name, duration)


def chart_steps(chart, area, folder, name, duration):
    items = [(str(i["label"])[:14], float(i["value"])) for i in chart.get("items", [])][:6]
    if len(items) < 2 or max(v for _, v in items) <= 0:
        return []
    pal = themes.palette(area.get("theme"))
    unit = str(chart.get("unit", ""))[:8]
    top_value = max(v for _, v in items)
    face, head = font(30), font(34, bold=True)
    frames = []
    for progress in (0.25, 0.5, 0.75, 1.0):
        card = _card(area)
        draw = ImageDraw.Draw(card)
        draw.text((30, 14), _wrap(draw, str(chart.get("title", "")), head, area["w"] - 60, 1)[0], font=head, fill=pal["accent"])
        base, left = area["h"] - 70, 60
        slot = (area["w"] - 2 * left) // len(items)
        for index, (label, value) in enumerate(items):
            bar_h = (base - 120) * value / top_value * progress
            x0 = left + index * slot + slot * 0.18
            x1 = left + (index + 1) * slot - slot * 0.18
            draw.rectangle([x0, base - bar_h, x1, base], fill=pal["bars"][index % len(pal["bars"])])
            if progress == 1.0:
                text = f"{value:g}{unit}"
                draw.text(((x0 + x1) / 2 - draw.textlength(text, font=head) / 2, base - bar_h - 48), text, font=head, fill=pal["ink"])
            draw.text(((x0 + x1) / 2 - draw.textlength(label, font=face) / 2, base + 10), label, font=face, fill=pal["ink"])
        draw.line([left, base, area["w"] - left, base], fill=pal["ink"], width=4)
        frames.append(_finish(area, card))
    return _steps(frames, area, folder, name, duration, reveal=0.3)


def points_steps(points, area, folder, name, duration, title=""):
    points = [str(p)[:40] for p in points if str(p).strip()][:4]
    if not points:
        return []
    pal = themes.palette(area.get("theme"))
    face, head = font(50, bold=True), font(38, bold=True)
    frames = []
    for shown in range(1, len(points) + 1):
        card = _card(area)
        draw = ImageDraw.Draw(card)
        y = 24
        if title:
            draw.text((40, y), _wrap(draw, title, head, area["w"] - 80, 1)[0], font=head, fill=pal["accent"])
            y += 84
        for index, point in enumerate(points[:shown]):
            if pal["card"]:
                draw.rounded_rectangle([40, y, 86, y + 48], 10, fill=pal["accent"])
                draw.text((53, y), str(index + 1), font=head, fill=pal["ink"])
            else:  # a circled number written on the board
                draw.ellipse([38, y - 2, 90, y + 50], outline=pal["accent"], width=4)
                draw.text((53, y), str(index + 1), font=head, fill=pal["accent"])
            for line in _wrap(draw, point, face, area["w"] - 160, 2):
                draw.text((112, y - 8), line, font=face, fill=pal["ink"])
                y += 66
            y += 30
        frames.append(_finish(area, card))
    return _steps(frames, area, folder, name, duration)


def quote_card(text, source, area, folder, name, duration):
    pal = themes.palette(area.get("theme"))
    card = _card(area, round(area["h"] * 0.62))
    draw = ImageDraw.Draw(card)
    draw.rectangle([0, 0, 14, card.height], fill=pal["accent"])
    draw.text((40, 10), "“", font=font(120, bold=True), fill=pal["muted"])
    face = font(50, bold=True)
    y = 120
    for line in _wrap(draw, text, face, area["w"] - 120, 3):
        draw.text((70, y), line, font=face, fill=pal["ink"])
        y += 72
    draw.text((70, card.height - 60), f"— {source}", font=font(30), fill=pal["muted"])
    card = _finish(area, card)
    px, py = _place(area, card)
    return [{"image": _save(card, folder, name), "x": px, "y": py, "w": card.width, "h": card.height,
             "motion": "pop", "start": 0, "end": duration}]


def chapter_card(number, title, source, size, folder, name, theme="gradient", background_image=None):
    """Full-canvas still between articles: 'ニュース2' and the headline."""
    w, h = size
    pal = themes.palette(theme)
    if theme == "gradient" and not background_image:
        image = Image.new("RGB", size, (14, 24, 34)).convert("RGBA")
    else:
        image = themes.background(size, theme, background_image).convert("RGBA")
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    accent = pal["accent"] if theme != "gradient" else ACCENT
    ink = pal["ink"] if theme != "gradient" else (255, 255, 255)
    draw.text((120, h // 2 - 190), f"ニュース {number}", font=font(72, bold=True), fill=accent)
    draw.line([(120, h // 2 - 70), (w - 240, h // 2 - 66)], fill=accent, width=6)
    face = font(62, bold=True)
    y = h // 2 - 20
    for line in _wrap(draw, title, face, w - 300, 2):
        draw.text((120, y), line, font=face, fill=ink)
        y += 88
    draw.text((120, y + 30), source, font=font(36), fill=pal["muted"] if theme != "gradient" else (170, 180, 190))
    image.alpha_composite(themes.chalkify(layer) if pal["chalk"] else layer)
    return _save(image.convert("RGB"), folder, name)
