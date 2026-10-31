"""One episode, start to finish, with no approval step (own channel only).

Steps and what happens when one fails:
- collect: a feed that fails is skipped; no fresh topic → stop quietly (nothing posted).
- script: Gemini failure stops the run (nothing posted, topics stay unused).
- screenshot: a page that fails gets a title card instead.
- voice / render: failure stops the run.
- publish: the video file is kept; topics are marked used only after a
  successful upload, so a failed day retries tomorrow with fresh topics.
- one episode per day: a second run on the same day does nothing unless forced.
"""

import json
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import collect, compose, screenshot, script, store, visuals, voicevox, x, youtube

DEFAULTS = {
    "feeds": None,  # None → collect.DEFAULT_FEEDS
    "keywords": ["AI", "生成AI", "OpenAI", "Google", "Apple", "セキュリティ", "半導体"],
    "hacker_news": True,
    "format": None,  # None → rotate by weekday (script.ROTATION); or roundup / deep / qa
    "topics": None,  # None → the format's number of articles
    "voicevox_url": "http://127.0.0.1:50021",
    "speed": 1.12,
    "caption_size": 16,
    "caption_outline": 3,
    "caption_y": -0.815,
    "emphasis_color": "#FFE14D",
    "theme": "blackboard",  # blackboard / whiteboard / gradient
    "background": "",  # an image file used as the background instead (cover-fit)
    "privacy": "public",
    "category": "28",  # 28 = 科学と技術
    "portraits": "assets/zunda",
    "portrait_credit": "",
    "hashtags": ["#ずんだもん", "#ニュース解説"],
    "post_x": True,
    "timezone_offset_hours": 9,
}
CAPTION = {"zundamon": "#B8F5A0", "metan": "#FFC2DD"}
CANVAS = (1920, 1080)


def silence(path, seconds):
    import wave

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(b"\x00\x00" * int(48000 * seconds))


def _still(layers, seconds):
    """Keep the previous visual on screen without animating it again
    (its final step, plus decorations such as tape)."""
    main = [layer for layer in layers if not layer.get("decor")]
    if not main or main[-1].get("motion") == "pan":
        return []  # a scrolled page has no single resting frame; the board shows instead
    last = dict(main[-1])
    if last.get("motion") in ("zoom", "focus"):
        last["zoom"] = 1.08 if last["motion"] == "zoom" else 1.35
        last["motion"] = "hold"  # stay zoomed where the previous line ended
    else:
        last["motion"] = "still"
    kept = [last] + [dict(layer) for layer in layers if layer.get("decor")]
    for layer in kept:
        layer.update(start=0, end=seconds)
    return kept


def layers_for(line, items, area, folder, name, seconds, previous):
    """Moving layers for one spoken line (see visuals.py)."""
    visual = line["visual"]
    kind = visual["kind"]
    item = items[line["source"]] if line["source"] >= 0 else None
    meta = (item or {}).get("meta")
    if kind == "keep":
        return _still(previous, seconds)
    if kind == "points":
        return visuals.points_steps(visual.get("points", []), area, folder, name, seconds, visual.get("title", ""))
    if kind == "chart":
        return visuals.chart_steps(visual, area, folder, name, seconds) or _still(previous, seconds)
    if kind == "quote" and item:
        return visuals.quote_card(visual["quote"], item["source"], area, folder, name, seconds)
    if kind == "table" and meta:
        return visuals.table_steps(meta["tables"][visual["index"]]["rows"], area, folder, name, seconds,
                                   visual.get("title", "")) or visuals.page_top(meta, area, folder, name, seconds)
    if item and not meta:  # the page could not be captured: show its headline card instead
        return visuals.page_top({"page": item["card"], "scale": 1}, area, folder, name, seconds)
    if not item:
        return _still(previous, seconds)
    if kind == "scroll":
        return visuals.page_scroll(meta, area, folder, name, seconds)
    if kind == "heading" and meta.get("heading"):
        return visuals.article_crop(meta, meta["heading"], area, folder, name, seconds)
    if kind == "paragraph":
        return visuals.article_crop(meta, meta["paragraphs"][visual["index"]]["box"], area, folder, name, seconds)
    if kind == "image":
        return visuals.article_crop(meta, meta["images"][visual["index"]], area, folder, name, seconds, highlight=False)
    return visuals.page_top(meta, area, folder, name, seconds)


def settings_for(cfg):
    return {**DEFAULTS, **(cfg.get("zunda") or {})}


def pick(items, count):
    """Best items, at most one per source while others remain (variety)."""
    chosen, used = [], set()
    for item in items:
        if item["source"] not in used:
            chosen.append(item)
            used.add(item["source"])
        if len(chosen) == count:
            return chosen
    for item in items:
        if item not in chosen:
            chosen.append(item)
        if len(chosen) == count:
            break
    return chosen


def stamp(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}" if seconds >= 3600 else f"{seconds // 60}:{seconds % 60:02d}"


def chapters(lines, durations, items):
    """YouTube chapters: opening, one per article, closing. Returned only when they
    meet YouTube's rules (start at 0:00, at least 3, each at least 10 s)."""
    marks, position, seen, current = [(0.0, "オープニング")], 0.0, set(), None
    for line, duration in zip(lines, durations):
        source = line["source"]
        if source >= 0 and source not in seen:
            seen.add(source)
            current = source
            marks.append((position, items[source]["title"][:40]))
        elif source < 0 and current is not None and marks[-1][1] != "まとめ" and len(seen) == len(items):
            marks.append((position, "まとめ"))
        position += duration
    if len(marks) > 1 and marks[1][0] < 10:
        marks.pop(0)  # no real opening: the first article starts at 0:00
        marks[0] = (0.0, marks[0][1])
    ends = [m[0] for m in marks[1:]] + [position]
    if len(marks) < 3 or any(end - start < 10 for (start, _), end in zip(marks, ends)):
        return []
    return [f"{stamp(start)} {title}" for start, title in marks]


def describe(episode, items, z, chapter_lines=()):
    lines = [episode["description"], ""]
    if chapter_lines:
        lines += ["目次:", *chapter_lines, ""]
    lines += ["出典:"]
    lines += [f"・{i['title']}（{i['source']}）\n  {i['url']}" for i in items]
    credits = [voicevox.SPEAKERS["zundamon"]["credit"], voicevox.SPEAKERS["metan"]["credit"]]
    if z.get("portrait_credit"):
        credits.append(z["portrait_credit"])
    lines += [
        "",
        "クレジット: " + " / ".join(credits),
        "※音声は VOICEVOX による合成音声です。解説と考察は番組の見方で、事実は各出典の記事をご確認ください。",
        "",
        " ".join(z["hashtags"]),
    ]
    return "\n".join(lines)


def today(z, clock=time.time):
    zone = timezone(timedelta(hours=z["timezone_offset_hours"]))
    return datetime.fromtimestamp(clock(), zone).date().isoformat()


def run(cfg, output, *, publish=True, force=False, env=os.environ, log=print, data_dir=None, clock=time.time):
    from ..builder import audio_seconds
    from ..render import render

    z = settings_for(cfg)
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    db = store.Store(store.backend_from_env(data_dir or output), clock=clock)
    state = db.load()
    day = today(z, clock)
    if not force and any(e.get("date") == day and e.get("youtube") for e in state["episodes"]):
        log(f"[zunda] {day} の回は投稿済みです")
        return {"status": "already_published", "date": day}

    zone = timezone(timedelta(hours=z["timezone_offset_hours"]))
    fmt = z["format"] or script.format_for(datetime.fromtimestamp(clock(), zone).weekday())
    topics = z["topics"] or script.FORMATS[fmt]["topics"]
    items = pick(collect.gather(z["feeds"], z["keywords"], state["seen"], z["hacker_news"], log=log), topics)
    if not items:
        log("[zunda] 新しい話題がありません。今日は投稿しません")
        return {"status": "no_topics", "date": day}
    for item in items:
        item["text"] = collect.article_text(item["url"])
    # Screenshots first: the script may point at paragraphs, images and tables they found.
    (output / "shots").mkdir(parents=True, exist_ok=True)
    pages = screenshot.capture_many([i["url"] for i in items], output / "shots", log=log)
    for index, item in enumerate(items):
        item["meta"] = pages.get(item["url"])
        item["card"] = str(screenshot.title_card(item["title"], item["source"], output / "shots" / f"card-{index:02d}.png"))
    (output / "topics.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    recent = [e.get("title", "") for e in state["episodes"]]
    episode = script.write(items, cfg, fmt, recent, log)
    (output / "script.json").write_text(json.dumps({"format": fmt, **episode}, ensure_ascii=False, indent=1), encoding="utf-8")

    assets = output / "assets"
    layers_dir = output / "layers"
    for folder in (assets, layers_dir):
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir()
    voicevox.wait_ready(z["voicevox_url"])
    portraits = Path(z["portraits"]) if z["portraits"] else None
    size = CANVAS  # the layout (panel, characters, caption band) is designed for 1080p
    area = visuals.panel(size, theme=z["theme"])
    bases, scenes, timeline = {}, [], []
    shown, previous_layers, number = set(), [], 0

    def base(speaker, emotion, source):
        key = (speaker, emotion, source)
        if key not in bases:
            bases[key] = compose.frame(
                output / f"base-{len(bases):03d}.png", title=episode["title"], shot=None,
                source=collect.domain(items[source]["url"]) if source >= 0 else None,
                speaker=speaker, portraits=portraits, size=size, emotion=emotion,
                theme=z["theme"], background_image=z["background"] or None,
            )
        return bases[key]

    for line in episode["lines"]:
        source = line["source"]
        if source >= 0 and source not in shown and len(items) > 1:
            shown.add(source)
            number += 1
            card = visuals.chapter_card(len(shown), items[source]["title"], items[source]["source"], size,
                                        layers_dir, f"chapter-{number:03d}", z["theme"], z["background"] or None)
            shutil.copyfile(card, assets / f"scene-{number:03d}.png")
            silence(assets / f"scene-{number:03d}.wav", 1.6)
            scenes.append({"scene_number": number, "narration": "", "camera_motion": "none"})
            timeline.append({"source": source, "seconds": 1.6})
            previous_layers = []
        elif source >= 0:
            shown.add(source)
        number += 1
        wav = assets / f"scene-{number:03d}.wav"
        voicevox.synthesize(script.spoken(line["text"]), line["speaker"], wav, z["voicevox_url"], z["speed"])
        seconds = audio_seconds(wav)
        layers = layers_for(line, items, area, layers_dir, f"scene-{number:03d}", seconds, previous_layers)
        previous_layers = layers
        shutil.copyfile(base(line["speaker"], line["emotion"], source), assets / f"scene-{number:03d}.png")
        scenes.append({"scene_number": number, "narration": line["text"], "camera_motion": "none",
                       "caption_color": CAPTION[line["speaker"]], "layers": layers})
        timeline.append({"source": source, "seconds": seconds})

    plan = {"title": episode["title"], "show_hook": False, "scenes": scenes}
    render_settings = {
        **cfg,
        "width": CANVAS[0],
        "height": CANVAS[1],
        "caption_size": z["caption_size"],
        "caption_outline": z["caption_outline"],
        "caption_y": z["caption_y"],
        "emphasis_color": z["emphasis_color"],
    }
    result = render(plan, assets, output / "video", render_settings)
    video = Path(result["video"])
    first = items[0].get("meta") or {}
    thumb = compose.thumbnail(
        output / "thumbnail-yt.jpg", text=episode["thumbnail_text"], shot=first.get("page") or items[0]["card"],
        portraits=portraits,
    )
    chapter_lines = chapters([{"source": t["source"]} for t in timeline], [t["seconds"] for t in timeline], items)
    description = describe(episode, items, z, chapter_lines)
    (output / "description.txt").write_text(description, encoding="utf-8")
    record = {"date": day, "title": episode["title"], "urls": [i["url"] for i in items], "video": str(video)}
    if not publish:
        log(f"[zunda] 書き出しのみ: {video}")
        return {"status": "rendered", **record}

    credentials = youtube.Credentials.from_env(env)
    video_id = youtube.upload(
        credentials,
        video,
        title=episode["title"],
        description=description,
        tags=[*episode["tags"], "ずんだもん", "四国めたん", "ニュース解説"],
        category=z["category"],
        privacy=z["privacy"],
    )
    record["youtube"] = video_id
    # Mark topics used as soon as the video exists, before optional extras.
    now = clock()
    state["seen"].update({u: now for u in record["urls"]})
    state["episodes"].append({k: v for k, v in record.items() if k != "video"})
    db.save(state)
    try:
        youtube.set_thumbnail(credentials, video_id, thumb)
    except Exception as error:  # custom thumbnails need a verified channel; optional
        log(f"[zunda] サムネイルは設定できませんでした: {str(error)[:160]}")
    if z["post_x"] and z["privacy"] == "public":
        try:
            text = x.fit(f"{episode['title']}\n{' '.join(z['hashtags'])}", f"https://youtu.be/{video_id}")
            record["x"] = x.post(text, x.keys_from_env(env))
            state["episodes"][-1]["x"] = record["x"]
            db.save(state)
        except Exception as error:  # X is optional; the video is already live
            log(f"[zunda] X には投稿しませんでした: {str(error)[:160]}")
    log(f"[zunda] 公開: https://youtu.be/{video_id}")
    return {"status": "published", **record}
