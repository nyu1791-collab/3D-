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

from . import collect, compose, screenshot, script, store, voicevox, x, youtube

DEFAULTS = {
    "feeds": None,  # None → collect.DEFAULT_FEEDS
    "keywords": ["AI", "生成AI", "OpenAI", "Google", "Apple", "セキュリティ", "半導体"],
    "hacker_news": True,
    "topics": 3,
    "lines": 40,
    "voicevox_url": "http://127.0.0.1:50021",
    "speed": 1.12,
    "width": 1920,
    "height": 1080,
    "caption_size": 15,
    "caption_outline": 3,
    "caption_y": -0.815,
    "privacy": "public",
    "category": "28",  # 28 = 科学と技術
    "portraits": "assets/zunda",
    "portrait_credit": "",
    "hashtags": ["#ずんだもん", "#ニュース解説"],
    "post_x": True,
    "timezone_offset_hours": 9,
}
CAPTION = {"zundamon": "#B8F5A0", "metan": "#FFC2DD"}


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


def describe(episode, items, z):
    lines = [episode["description"], "", "出典:"]
    lines += [f"・{i['title']}（{i['source']}）\n  {i['url']}" for i in items]
    credits = [voicevox.SPEAKERS["zundamon"]["credit"], voicevox.SPEAKERS["metan"]["credit"]]
    if z.get("portrait_credit"):
        credits.append(z["portrait_credit"])
    lines += ["", "クレジット: " + " / ".join(credits), "", " ".join(z["hashtags"])]
    return "\n".join(lines)


def today(z, clock=time.time):
    zone = timezone(timedelta(hours=z["timezone_offset_hours"]))
    return datetime.fromtimestamp(clock(), zone).date().isoformat()


def run(cfg, output, *, publish=True, force=False, env=os.environ, log=print, data_dir=None, clock=time.time):
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

    items = pick(collect.gather(z["feeds"], z["keywords"], state["seen"], z["hacker_news"], log=log), z["topics"])
    if not items:
        log("[zunda] 新しい話題がありません。今日は投稿しません")
        return {"status": "no_topics", "date": day}
    for item in items:
        item["text"] = collect.article_text(item["url"])
    (output / "topics.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    episode = script.write(items, cfg, z["lines"])
    (output / "script.json").write_text(json.dumps(episode, ensure_ascii=False, indent=1), encoding="utf-8")

    (output / "shots").mkdir(parents=True, exist_ok=True)
    shots = screenshot.capture_many([i["url"] for i in items], output / "shots", log=log)
    for index, item in enumerate(items):
        if not shots.get(item["url"]):
            shots[item["url"]] = screenshot.title_card(
                item["title"], item["source"], output / "shots" / f"card-{index:02d}.png"
            )

    assets = output / "assets"
    if assets.exists():
        shutil.rmtree(assets)
    assets.mkdir()
    voicevox.wait_ready(z["voicevox_url"])
    portraits = Path(z["portraits"]) if z["portraits"] else None
    frames, scenes = {}, []
    current = items[0]
    for number, line in enumerate(episode["lines"], 1):
        if line["source"] >= 0:
            current = items[line["source"]]
        key = (current["url"], line["speaker"])
        if key not in frames:
            frames[key] = compose.frame(
                output / f"frame-{len(frames):03d}.png",
                title=episode["title"],
                shot=shots[current["url"]],
                source=collect.domain(current["url"]),
                speaker=line["speaker"],
                portraits=portraits,
                size=(z["width"], z["height"]),
            )
        shutil.copyfile(frames[key], assets / f"scene-{number:03d}.png")
        voicevox.synthesize(line["text"], line["speaker"], assets / f"scene-{number:03d}.wav", z["voicevox_url"], z["speed"])
        scenes.append(
            {"scene_number": number, "narration": line["text"], "camera_motion": "none", "caption_color": CAPTION[line["speaker"]]}
        )

    plan = {"title": episode["title"], "show_hook": False, "scenes": scenes}
    render_settings = {
        **cfg,
        "width": z["width"],
        "height": z["height"],
        "caption_size": z["caption_size"],
        "caption_outline": z["caption_outline"],
        "caption_y": z["caption_y"],
    }
    result = render(plan, assets, output / "video", render_settings)
    video = Path(result["video"])
    thumb = compose.thumbnail(
        output / "thumbnail-yt.jpg", text=episode["thumbnail_text"], shot=shots[items[0]["url"]], portraits=portraits
    )
    description = describe(episode, items, z)
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
