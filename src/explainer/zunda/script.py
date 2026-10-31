"""Dialogue script for ずんだもん and 四国めたん, written by Gemini from collected articles.

Each line carries what to show while it is spoken (visual), the speaker's
emotion, and 【keywords】 to colour in the caption. Everything drawn on screen is
checked against the article: a quote must appear verbatim, every chart value must
appear in the text, a paragraph/table/image must exist. Anything that fails the
check falls back to showing the article page itself.

Formats rotate so the channel is not a template: roundup (several stories),
deep (one story in depth), qa (questions a viewer would ask). Every format must
contain analysis lines (why it matters, who is affected, what to watch), clearly
separated from the facts — the part that makes each episode the channel's own.
"""

import json
import re

SPEAKERS = ("zundamon", "metan")
EMOTIONS = ("normal", "happy", "surprised", "thinking", "worried")
VISUALS = ("page", "scroll", "heading", "paragraph", "image", "table", "chart", "points", "quote", "keep")
MAX_LINES = 80
FORMATS = {
    "roundup": {"topics": 3, "lines": 40, "brief": "複数のニュースを順に紹介し、最後に共通点や流れをまとめる回"},
    "deep": {"topics": 1, "lines": 45, "brief": "1本のニュースを深掘りする回（背景→何が起きたか→仕組み→影響→今後）"},
    "qa": {"topics": 2, "lines": 40, "brief": "視聴者が抱きそうな疑問をずんだもんが聞き、めたんが記事を根拠に答えるQ&A回"},
}
ROTATION = ["roundup", "deep", "roundup", "qa", "roundup", "deep", "qa"]  # Monday..Sunday

RULES = """あなたはYouTubeの解説動画の構成作家です。ずんだもんと四国めたんの掛け合いで、
渡された記事だけを根拠にニュースを分かりやすく解説する台本を書きます。

キャラクター:
- ずんだもん: 一人称「ボク」。語尾は「〜のだ」「〜なのだ」。素直で好奇心旺盛、疑問を投げかける役。
- 四国めたん: 一人称「わたくし」。丁寧なお嬢様口調（「〜ですわ」「〜ですのよ」）。落ち着いて説明する役。

事実について:
- 記事にない事実・数字・固有名詞・発言を作らない。分からないことは「記事では触れられていない」と言う。
- 記事の文章を長く引き写さず、要点を自分の言葉で説明する。誰の情報かを「〇〇によると」で示す。
- 推測は推測と分かる言い方にする。人物や企業を貶めない。医療・投資の助言をしない。

この番組ならではの視点（必須）:
- role が "analysis" の行を3行以上入れる。「なぜ重要か」「誰に影響があるか」「注意すべき点」「今後の見どころ」を、
  事実と分けて「わたくしの見方では」「ボクが気になるのは」のように考察だと分かる言い方で話す。
- 専門用語は一度かみ砕いて言い換える。身近な例えを1つ以上入れる。

画面（visual）:
- 1行ごとに画面に出すものを選ぶ。同じ画面が続くなら kind="keep"。3〜4行に1回は画面を変える。
- page=記事の冒頭, scroll=記事を上から流す, heading=見出しを強調, paragraph=記事の段落を強調（index は段落番号）,
  image=記事内の画像（index）, table=記事内の表（index）, chart=棒グラフ（記事にある数値だけ。items の value は記事の数字そのまま）,
  points=要点の箇条書き（2〜4個、短く）, quote=記事からの短い引用（40文字以内、記事の文字列そのまま）。
- 数字が出てきたら chart か points で見せる。説明が長くなる所は points で整理する。

字幕と声:
- 1行は話し言葉で60文字以内。記号や絵文字を使わず、読み上げやすい表記にする。
- 特に大事な語を1行に1つまで【】で囲む（例: 【生成AI】）。
- emotion は normal / happy / surprised / thinking / worried から選ぶ。
- 冒頭2行で「今日は何の話か」と見る理由を伝える。最後は短いまとめと、控えめなチャンネル登録のお願い。
- source には説明している記事の番号。導入・まとめなど特定の記事でない行は -1。

JSON だけを返します。"""

LINE = {
    "type": "object",
    "properties": {
        "speaker": {"type": "string", "enum": list(SPEAKERS)},
        "text": {"type": "string"},
        "source": {"type": "integer"},
        "role": {"type": "string", "enum": ["intro", "fact", "analysis", "outro"]},
        "emotion": {"type": "string", "enum": list(EMOTIONS)},
        "visual": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(VISUALS)},
                "index": {"type": "integer"},
                "title": {"type": "string"},
                "unit": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"label": {"type": "string"}, "value": {"type": "number"}},
                        "required": ["label", "value"],
                    },
                },
                "points": {"type": "array", "items": {"type": "string"}},
                "quote": {"type": "string"},
            },
            "required": ["kind"],
        },
    },
    "required": ["speaker", "text", "source", "role", "emotion", "visual"],
}
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "thumbnail_text": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "lines": {"type": "array", "items": LINE},
    },
    "required": ["title", "description", "thumbnail_text", "lines"],
}


def format_for(weekday):
    return ROTATION[weekday % 7]


def prompt(items, fmt, recent_titles=()):
    info = FORMATS[fmt]
    articles = []
    for index, item in enumerate(items):
        meta = item.get("meta") or {}
        articles.append(
            {
                "番号": index,
                "見出し": item["title"],
                "媒体": item["source"],
                "要約": item.get("summary", ""),
                "本文の抜粋": item.get("text", "")[:2500],
                "段落": [f"{i}: {p['text'][:160]}" for i, p in enumerate(meta.get("paragraphs", []))],
                "表": [f"{i}: " + " / ".join(" | ".join(r) for r in t["rows"][:3]) for i, t in enumerate(meta.get("tables", []))],
                "画像の数": len(meta.get("images", [])),
            }
        )
    avoid = "、".join(recent_titles[-10:]) or "なし"
    return (
        f"今回の形式: {info['brief']}。約{info['lines']}行（目安）。\n"
        f"最近の回のタイトル（似た言い回し・同じ構成を避ける）: {avoid}\n"
        "タイトルは内容が具体的に分かる日本語で40文字以内、thumbnail_text は12文字以内の見出し、"
        "description は3文以内の動画説明（ハッシュタグなし）。\n"
        + json.dumps(articles, ensure_ascii=False)
    )


def _normal(text):
    return re.sub(r"[\s,，、。．.・「」『』（）()]", "", str(text))


_NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)(億)?(?:(\d[\d,]*)?(万))?(\d[\d,]*)?")


def numbers_in(text):
    """Every number written in the text: 1,234 / 2.5 / 3万9800 / 1億2000万 / 12万."""
    found = set()
    for match in _NUMBER.finditer(str(text).translate(str.maketrans("０１２３４５６７８９．，", "0123456789.,"))):
        head, oku, man_digits, man, tail = match.groups()
        value = float(head.replace(",", ""))
        found.add(value)
        if oku:
            total = value * 1e8
            if man:
                total += float((man_digits or "0").replace(",", "")) * 1e4
            if tail:
                total += float(tail.replace(",", ""))
            found.add(total)
        elif man:
            # "3万9800" arrives as head=3, man='万', tail=9800 (man_digits is empty)
            total = value * 1e4 + (float(tail.replace(",", "")) if tail else 0)
            found.add(total)
            if man_digits:
                found.add(float(man_digits.replace(",", "")))
        elif tail:
            found.add(float(tail.replace(",", "")))
    return found


def _number_in(value, text):
    """A chart value counts only if the same number is written in the article."""
    return any(abs(value - n) < 1e-9 for n in numbers_in(text))


def check_visual(visual, item):
    """Return a safe visual for this line, or {'kind': 'page'} when the claim is not in the article."""
    if not isinstance(visual, dict) or visual.get("kind") not in VISUALS:
        return {"kind": "keep"}
    kind = visual["kind"]
    if kind == "keep":
        return {"kind": "keep"}
    if item is None:
        return {"kind": "points", "points": visual.get("points", [])[:4]} if kind == "points" and visual.get("points") else {"kind": "keep"}
    meta = item.get("meta") or {}
    corpus = " ".join([item.get("text", ""), item.get("summary", ""), item["title"]]
                      + [p["text"] for p in meta.get("paragraphs", [])]
                      + [" ".join(c for r in t["rows"] for c in r) for t in meta.get("tables", [])])
    index = visual.get("index", 0)
    if kind == "paragraph":
        return {"kind": "paragraph", "index": index} if 0 <= index < len(meta.get("paragraphs", [])) else {"kind": "page"}
    if kind == "image":
        return {"kind": "image", "index": index} if 0 <= index < len(meta.get("images", [])) else {"kind": "page"}
    if kind == "table":
        return {"kind": "table", "index": index, "title": str(visual.get("title", ""))[:40]} if 0 <= index < len(meta.get("tables", [])) else {"kind": "page"}
    if kind == "heading":
        return {"kind": "heading"} if meta.get("heading") else {"kind": "page"}
    if kind == "quote":
        quote = " ".join(str(visual.get("quote", "")).split())
        if 4 <= len(quote) <= 60 and _normal(quote) in _normal(corpus):
            return {"kind": "quote", "quote": quote}
        return {"kind": "page"}
    if kind == "chart":
        items = [i for i in visual.get("items", []) if isinstance(i, dict) and isinstance(i.get("value"), (int, float))]
        if len(items) >= 2 and all(_number_in(float(i["value"]), corpus) for i in items):
            return {"kind": "chart", "title": str(visual.get("title", ""))[:40], "unit": str(visual.get("unit", ""))[:8],
                    "items": [{"label": str(i.get("label", ""))[:14], "value": float(i["value"])} for i in items[:6]]}
        return {"kind": "page"}
    if kind == "points":
        points = [str(p).strip()[:40] for p in visual.get("points", []) if str(p).strip()][:4]
        return {"kind": "points", "points": points, "title": str(visual.get("title", ""))[:40]} if points else {"kind": "keep"}
    return {"kind": kind}  # page / scroll


def validate(value, items, log=print):
    """Keep only well-formed lines; check every visual; raise if nothing usable remains."""
    if not isinstance(value, dict):
        raise ValueError("台本を読み取れません")
    item_count = len(items)
    lines, dropped = [], 0
    for row in value.get("lines") or []:
        if not isinstance(row, dict):
            continue
        speaker = row.get("speaker")
        text = " ".join(str(row.get("text", "")).split())
        if speaker not in SPEAKERS or not text:
            continue
        try:
            source = int(row.get("source", -1))
        except (TypeError, ValueError):
            source = -1
        source = source if 0 <= source < item_count else -1
        visual = check_visual(row.get("visual"), items[source] if source >= 0 else None)
        if visual["kind"] == "page" and (row.get("visual") or {}).get("kind") not in (None, "page"):
            dropped += 1
        lines.append(
            {
                "speaker": speaker,
                "text": text[:90],
                "source": source,
                "role": row.get("role") if row.get("role") in ("intro", "fact", "analysis", "outro") else "fact",
                "emotion": row.get("emotion") if row.get("emotion") in EMOTIONS else "normal",
                "visual": visual,
            }
        )
    lines = lines[:MAX_LINES]  # a run-away script must not become an hour-long video
    if len(lines) < 6:
        raise ValueError(f"台本の行が少なすぎます（{len(lines)}行）")
    if dropped:
        log(f"[script] 記事で確認できない画面指定 {dropped} 件を記事ページ表示に置き換えました")
    if sum(1 for line in lines if line["role"] == "analysis") < 3:
        log("[script] 考察の行が3行未満です")
    title = " ".join(str(value.get("title", "")).split())[:70] or "今日のニュース解説"
    return {
        "title": title,
        "description": str(value.get("description", "")).strip()[:600],
        "thumbnail_text": " ".join(str(value.get("thumbnail_text", "")).split())[:16] or title[:12],
        "tags": [str(t).strip() for t in value.get("tags", []) if str(t).strip()][:10],
        "lines": lines,
    }


def spoken(text):
    """Text for the voice: no emphasis brackets."""
    return re.sub(r"【(.+?)】", r"\1", text)


def write(items, settings, fmt="roundup", recent_titles=(), log=print):
    """Ask Gemini (route and model from the explainer settings)."""
    from google.genai import types

    from ..providers import _text_client

    model = settings.get("gemini_model") or "gemini-3.8-flash"
    with _text_client(settings) as client:
        response = client.models.generate_content(
            model=model,
            contents=prompt(items, fmt, list(recent_titles)),
            config=types.GenerateContentConfig(
                system_instruction=RULES,
                response_mime_type="application/json",
                response_schema=SCHEMA,
                temperature=0.75,
            ),
        )
    return validate(json.loads(response.text or "{}"), items, log)
