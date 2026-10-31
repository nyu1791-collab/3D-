"""Dialogue script for ずんだもん and 四国めたん, written by Gemini from collected articles.

The script may only use what the articles say. Each line names which article it
explains, so the matching page is on screen while it is spoken.
"""

import json

SPEAKERS = ("zundamon", "metan")
MAX_LINES = 80
RULES = """あなたはYouTubeの解説動画の構成作家です。ずんだもんと四国めたんの掛け合いで、
渡された記事だけを根拠にニュースを分かりやすく解説する台本を書きます。

キャラクター:
- ずんだもん: 一人称「ボク」。語尾は「〜のだ」「〜なのだ」。素直で好奇心旺盛、疑問を投げかける役。
- 四国めたん: 一人称「わたくし」。丁寧なお嬢様口調（「〜ですわ」「〜ですのよ」）。落ち着いて説明する役。

守ること:
- 記事にない事実・数字・固有名詞・発言を作らない。分からないことは「記事では触れられていない」と言う。
- 記事の文章を長く引き写さず、要点を自分の言葉で説明する。誰の情報かを「〇〇によると」で示す。
- 推測は推測と分かる言い方にする。人物や企業を貶めない。医療・投資の助言をしない。
- 1行は話し言葉で60文字以内。記号や絵文字を使わず、読み上げやすい表記にする。英字略語はそのままでよい。
- 冒頭2行で「今日は何の話か」と見る理由を伝える。最後は短いまとめと、控えめなチャンネル登録のお願い。
- 各行の source には説明している記事の番号を入れる。導入・まとめなど特定の記事でない行は -1。

JSON だけを返します。"""

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "thumbnail_text": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string", "enum": list(SPEAKERS)},
                    "text": {"type": "string"},
                    "source": {"type": "integer"},
                },
                "required": ["speaker", "text", "source"],
            },
        },
    },
    "required": ["title", "description", "thumbnail_text", "lines"],
}


def prompt(items, lines_goal):
    articles = [
        {
            "番号": index,
            "見出し": item["title"],
            "媒体": item["source"],
            "URL": item["url"],
            "要約": item.get("summary", ""),
            "本文の抜粋": item.get("text", "")[:2500],
        }
        for index, item in enumerate(items)
    ]
    return (
        f"次の{len(items)}本の記事を、約{lines_goal}行（目安）の掛け合いで解説してください。"
        "記事ごとに区切りが分かるようにし、最後に全体をまとめます。"
        "タイトルは内容が具体的に分かる日本語で40文字以内、thumbnail_text は12文字以内の見出し、"
        "description は3文以内の動画説明（ハッシュタグなし）。\n"
        + json.dumps(articles, ensure_ascii=False)
    )


def validate(value, item_count):
    """Keep only well-formed lines; raise if nothing usable remains."""
    if not isinstance(value, dict):
        raise ValueError("台本を読み取れません")
    lines = []
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
        lines.append({"speaker": speaker, "text": text[:90], "source": source if 0 <= source < item_count else -1})
    lines = lines[:MAX_LINES]  # a run-away script must not become an hour-long video
    if len(lines) < 6:
        raise ValueError(f"台本の行が少なすぎます（{len(lines)}行）")
    title = " ".join(str(value.get("title", "")).split())[:70] or "今日のニュース解説"
    return {
        "title": title,
        "description": str(value.get("description", "")).strip()[:600],
        "thumbnail_text": " ".join(str(value.get("thumbnail_text", "")).split())[:16] or title[:12],
        "tags": [str(t).strip() for t in value.get("tags", []) if str(t).strip()][:10],
        "lines": lines,
    }


def write(items, settings, lines_goal=40):
    """Ask Gemini (route and model from the explainer settings)."""
    from google.genai import types

    from ..providers import _text_client

    model = settings.get("gemini_model") or "gemini-3.8-flash"
    with _text_client(settings) as client:
        response = client.models.generate_content(
            model=model,
            contents=prompt(items, lines_goal),
            config=types.GenerateContentConfig(
                system_instruction=RULES,
                response_mime_type="application/json",
                response_schema=SCHEMA,
                temperature=0.7,
            ),
        )
    return validate(json.loads(response.text or "{}"), len(items))
