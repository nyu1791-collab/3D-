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

from .compose import COLORS, _wrap, font

ACCENT = (255, 214, 0)
PANEL_WIDTH = 0.59
INK = (28, 33, 40)
PAPER = (250, 251, 253)


def panel(size, band=170):
    """The area visuals may use: left of the characters, between title bar and captions."""
    w, h = size
    # Ends left of the two characters (each about 42% of the free height wide).
    return {"x": 56, "y": 124, "w": round(w * PANEL_WIDTH), "h": h - 96 - band - 110}


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
    return [{"image": _save(image, folder, name), "x": px, "y": py, "w": image.width, "h": image.height,
             "motion": "focus" if highlight else "zoom", "focus": focus, "start": 0, "end": duration}]


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
    return [{"image": _save(image, folder, name), "x": px, "y": py, "w": image.width, "h": image.height,
             "motion": "zoom", "start": 0, "end": duration}]


def page_scroll(meta, area, folder, name, duration):
    """Scroll down the article while a line is spoken (shows how long/rich it is)."""
    page = Image.open(meta["page"]).convert("RGB")
    width = area["w"] - 12
    scaled = page.resize((width, round(page.height * width / page.width)), Image.LANCZOS)
    visible = min(scaled.height, area["h"] - 12)
    scaled = scaled.crop((0, 0, width, min(scaled.height, visible * 4)))
    image = _bordered(scaled)
    return [{"image": _save(image, folder, name), "x": area["x"], "y": area["y"], "w": image.width,
             "h": image.height, "visible_h": visible + 12, "motion": "pan", "start": 0, "end": duration}]


# ---------------------------------------------------------------- generated cards
def _card(area, height=None):
    return Image.new("RGB", (area["w"], height or area["h"]), PAPER)


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
    columns = max(len(r) for r in rows)
    rows = [r + [""] * (columns - len(r)) for r in rows]
    face, head = font(30), font(30, bold=True)
    title_h = 70 if title else 0
    row_h = min(78, (area["h"] - title_h - 40) // len(rows))
    col_w = (area["w"] - 60) // columns
    frames = []
    for shown in range(2, len(rows) + 1):
        card = _card(area)
        draw = ImageDraw.Draw(card)
        if title:
            draw.text((30, 18), _wrap(draw, title, head, area["w"] - 60, 1)[0], font=head, fill=INK)
        for r, row in enumerate(rows[:shown]):
            top = title_h + 20 + r * row_h
            fill = (40, 62, 80) if r == 0 else ((236, 241, 246) if r % 2 else PAPER)
            draw.rectangle([30, top, area["w"] - 30, top + row_h - 4], fill=fill)
            for c, cell in enumerate(row):
                text = _wrap(draw, cell, head if r == 0 else face, col_w - 20, 1)[0]
                draw.text((44 + c * col_w, top + (row_h - 40) // 2), text, font=head if r == 0 else face,
                          fill=(255, 255, 255) if r == 0 else INK)
        frames.append(card)
    return _steps(frames, area, folder, name, duration)


def chart_steps(chart, area, folder, name, duration):
    items = [(str(i["label"])[:14], float(i["value"])) for i in chart.get("items", [])][:6]
    if len(items) < 2 or max(v for _, v in items) <= 0:
        return []
    unit = str(chart.get("unit", ""))[:8]
    top_value = max(v for _, v in items)
    face, head = font(28), font(32, bold=True)
    frames = []
    for progress in (0.25, 0.5, 0.75, 1.0):
        card = _card(area)
        draw = ImageDraw.Draw(card)
        draw.text((30, 18), _wrap(draw, str(chart.get("title", "")), head, area["w"] - 60, 1)[0], font=head, fill=INK)
        base, left = area["h"] - 70, 60
        slot = (area["w"] - 2 * left) // len(items)
        for index, (label, value) in enumerate(items):
            bar_h = (base - 110) * value / top_value * progress
            x0 = left + index * slot + slot * 0.18
            x1 = left + (index + 1) * slot - slot * 0.18
            draw.rectangle([x0, base - bar_h, x1, base], fill=COLORS["zundamon"] if index % 2 == 0 else COLORS["metan"])
            if progress == 1.0:
                text = f"{value:g}{unit}"
                draw.text(((x0 + x1) / 2 - draw.textlength(text, font=face) / 2, base - bar_h - 40), text, font=face, fill=INK)
            draw.text(((x0 + x1) / 2 - draw.textlength(label, font=face) / 2, base + 10), label, font=face, fill=INK)
        draw.line([left, base, area["w"] - left, base], fill=INK, width=3)
        frames.append(card)
    return _steps(frames, area, folder, name, duration, reveal=0.3)


def points_steps(points, area, folder, name, duration, title=""):
    points = [str(p)[:40] for p in points if str(p).strip()][:4]
    if not points:
        return []
    face, head = font(46, bold=True), font(36, bold=True)
    frames = []
    for shown in range(1, len(points) + 1):
        card = _card(area)
        draw = ImageDraw.Draw(card)
        y = 30
        if title:
            draw.text((40, y), _wrap(draw, title, head, area["w"] - 80, 1)[0], font=head, fill=(90, 98, 110))
            y += 80
        for index, point in enumerate(points[:shown]):
            draw.rounded_rectangle([40, y, 84, y + 44], 10, fill=ACCENT)
            draw.text((52, y - 2), str(index + 1), font=head, fill=INK)
            for line in _wrap(draw, point, face, area["w"] - 160, 2):
                draw.text((110, y - 6), line, font=face, fill=INK)
                y += 62
            y += 30
        frames.append(card)
    return _steps(frames, area, folder, name, duration)


def quote_card(text, source, area, folder, name, duration):
    card = _card(area, round(area["h"] * 0.62))
    draw = ImageDraw.Draw(card)
    draw.rectangle([0, 0, 14, card.height], fill=ACCENT)
    draw.text((40, 10), "“", font=font(120, bold=True), fill=(200, 205, 212))
    face = font(48, bold=True)
    y = 120
    for line in _wrap(draw, text, face, area["w"] - 120, 3):
        draw.text((70, y), line, font=face, fill=INK)
        y += 70
    draw.text((70, card.height - 60), f"— {source}", font=font(30), fill=(90, 98, 110))
    px, py = _place(area, card)
    return [{"image": _save(card, folder, name), "x": px, "y": py, "w": card.width, "h": card.height,
             "motion": "pop", "start": 0, "end": duration}]


def chapter_card(number, title, source, size, folder, name):
    """Full-canvas still between articles: 'ニュース2' and the headline."""
    w, h = size
    image = Image.new("RGB", size, (14, 24, 34))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, h // 2 - 4, w, h // 2 + 4], fill=COLORS["zundamon"])
    label = font(64, bold=True)
    draw.text((120, h // 2 - 170), f"ニュース {number}", font=label, fill=ACCENT)
    face = font(60, bold=True)
    y = h // 2 + 50
    for line in _wrap(draw, title, face, w - 240, 2):
        draw.text((120, y), line, font=face, fill=(255, 255, 255))
        y += 84
    draw.text((120, h - 120), source, font=font(34), fill=(170, 180, 190))
    return _save(image, folder, name)
