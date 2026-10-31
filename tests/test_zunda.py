import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from explainer.zunda import collect, compose, http, pipeline, script, store, voicevox

RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<item><title>新しいAIチップ発表</title><link>https://news.example.jp/a</link>
<description>&lt;p&gt;半導体の新製品&lt;/p&gt;</description><pubDate>Fri, 15 Jan 2027 00:00:00 +0900</pubDate></item>
<item><title>古い話</title><link>https://news.example.jp/old</link><pubDate>Fri, 01 Jan 2027 00:00:00 +0900</pubDate></item>
</channel></rss>"""
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>クラウド障害の振り返り</title><link rel="alternate" href="https://atom.example/b"/>
<summary>原因と対策</summary><updated>2027-01-14T12:00:00Z</updated></entry></feed>"""
NOW = 1_800_000_000.0  # 2027-01-15 08:00 JST


class Reply(http.Response):
    def __init__(self, body, status=200, headers=None):
        raw = body if isinstance(body, bytes) else (body.encode() if isinstance(body, str) else json.dumps(body).encode())
        super().__init__(status, headers or {}, raw)


def fake_request(routes):
    def request(method, url, **kwargs):
        for prefix, reply in routes.items():
            if url.startswith(prefix):
                if isinstance(reply, Exception):
                    raise reply
                return reply
        raise http.HttpError(404, url, "not found")

    return request


class Collect(unittest.TestCase):
    def test_rss_and_atom_are_parsed(self):
        rss = collect.parse_feed(RSS, "Example")
        self.assertEqual(rss[0]["summary"], "半導体の新製品")
        atom = collect.parse_feed(ATOM, "Atom")
        self.assertEqual(atom[0]["url"], "https://atom.example/b")
        self.assertGreater(atom[0]["published"], 0)

    def test_gather_scores_skips_seen_old_and_broken_feeds(self):
        request = fake_request(
            {
                "https://feed.one": Reply(RSS),
                "https://feed.two": Reply(ATOM),
                "https://feed.broken": http.HttpError(500, "https://feed.broken"),
            }
        )
        feeds = [{"url": u, "name": n} for u, n in [("https://feed.one", "One"), ("https://feed.two", "Two"), ("https://feed.broken", "Bad")]]
        logs = []
        items = collect.gather(feeds, ["AI"], seen=["https://atom.example/b"], use_hn=False, request=request, now=NOW, log=logs.append)
        self.assertEqual([i["url"] for i in items], ["https://news.example.jp/a"])  # seen and >3 days old dropped
        self.assertTrue(any("Bad" in line for line in logs))

    def test_article_text_keeps_paragraphs_not_navigation(self):
        page = "<html><nav><p>メニューの項目がここにたくさん並んでいます</p></nav><p>本文の最初の段落で、十分な長さのある説明文です。</p><script>var x=1</script></html>"
        request = fake_request({"https://a": Reply(page, headers={"Content-Type": "text/html; charset=utf-8"})})
        text = collect.article_text("https://a", request=request)
        self.assertIn("本文の最初の段落", text)
        self.assertNotIn("メニュー", text)


class Script(unittest.TestCase):
    def test_validate_cleans_lines_and_sources(self):
        raw = {
            "title": "今日のAIニュース",
            "description": "説明",
            "thumbnail_text": "AIチップ",
            "lines": [{"speaker": "zundamon", "text": " こんにちは  なのだ ", "source": 5}]
            + [{"speaker": "metan", "text": "説明ですわ", "source": 0}] * 6
            + [{"speaker": "narrator", "text": "x", "source": 0}],
        }
        items = [{"title": "t", "source": "S", "text": "本文"}]
        result = script.validate(raw, items, log=lambda *a: None)
        first = result["lines"][0]
        self.assertEqual((first["speaker"], first["text"], first["source"]), ("zundamon", "こんにちは なのだ", -1))
        self.assertEqual(first["visual"], {"kind": "keep"})
        self.assertEqual(len(result["lines"]), 7)
        with self.assertRaises(ValueError):
            script.validate({"lines": raw["lines"][:2]}, items, log=lambda *a: None)


class Compose(unittest.TestCase):
    def test_frame_and_thumbnail_sizes(self):
        with tempfile.TemporaryDirectory() as folder:
            shot = Path(folder) / "shot.png"
            Image.new("RGB", (1920, 1200), (200, 220, 240)).save(shot)
            frame = compose.frame(Path(folder) / "f.png", title="タイトル", shot=shot, source="example.com", speaker="metan")
            self.assertEqual(Image.open(frame).size, (1920, 1080))
            thumb = compose.thumbnail(Path(folder) / "t.jpg", text="AIチップ発表", shot=shot)
            self.assertEqual(Image.open(thumb).size, (1280, 720))


class Voicevox(unittest.TestCase):
    def test_synthesize_posts_query_then_synthesis(self):
        calls = []

        def request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if "/audio_query" in url:
                return Reply({"speedScale": 1.0})
            return Reply(b"RIFF....WAVE")

        with tempfile.TemporaryDirectory() as folder:
            path = voicevox.synthesize("テストなのだ", "zundamon", Path(folder) / "a.wav", "http://vv:50021", request=request)
            self.assertTrue(path.read_bytes().startswith(b"RIFF"))
        self.assertIn("speaker=3", calls[0][1])
        self.assertEqual(calls[1][2]["json_body"]["speedScale"], 1.12)


class Store(unittest.TestCase):
    def test_prunes_old_seen_and_keeps_recent(self):
        with tempfile.TemporaryDirectory() as folder:
            db = store.Store(store.FileBackend(Path(folder) / "s.json"), clock=lambda: NOW)
            data = db.load()
            data["seen"] = {"old": NOW - 90 * 86400, "new": NOW}
            data["episodes"] = [{"date": str(i)} for i in range(100)]
            db.save(data)
            again = db.load()
            self.assertEqual(list(again["seen"]), ["new"])
            self.assertEqual(len(again["episodes"]), store.EPISODES)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg is not installed")
class Pipeline(unittest.TestCase):
    def test_full_episode_publishes_once_per_day(self):
        items = [
            {"title": "AIチップ", "url": "https://news.example.jp/a", "summary": "", "source": "One", "published": NOW, "score": 1},
            {"title": "障害", "url": "https://atom.example/b", "summary": "", "source": "Two", "published": NOW, "score": 1},
        ]
        episode = {
            "title": "AIチップと障害の話",
            "description": "二つのニュースを解説します。",
            "thumbnail_text": "AIチップ",
            "tags": ["AI"],
            "lines": [
                {"speaker": "zundamon", "text": "今日は【二つ】のニュースなのだ", "source": -1, "role": "intro",
                 "emotion": "happy", "visual": {"kind": "points", "points": ["AIチップ", "障害"]}},
                {"speaker": "metan", "text": "まずはAIチップの話ですわ", "source": 0, "role": "fact",
                 "emotion": "normal", "visual": {"kind": "page"}},
                {"speaker": "zundamon", "text": "次は障害の話なのだ", "source": 1, "role": "fact",
                 "emotion": "normal", "visual": {"kind": "keep"}},
            ],
        }

        def fake_wav(text, speaker, path, base_url, speed):
            subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=300:d=0.6", str(path)],
                check=True,
            )
            return Path(path)

        uploads, posts = [], []
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(
            pipeline.collect, "gather", return_value=items
        ), mock.patch.object(pipeline.collect, "article_text", return_value="本文"), mock.patch.object(
            pipeline.script, "write", return_value=episode
        ), mock.patch.object(
            pipeline.screenshot, "capture_many", return_value={}
        ), mock.patch.object(pipeline.voicevox, "wait_ready"), mock.patch.object(
            pipeline.voicevox, "synthesize", side_effect=fake_wav
        ), mock.patch.object(
            pipeline.youtube.Credentials, "from_env", return_value=object()
        ), mock.patch.object(
            pipeline.youtube, "upload", side_effect=lambda creds, video, **kw: uploads.append((video, kw)) or "VID1"
        ), mock.patch.object(pipeline.youtube, "set_thumbnail"), mock.patch.object(
            pipeline.x, "keys_from_env", return_value={}
        ), mock.patch.object(pipeline.x, "post", side_effect=lambda text, keys: posts.append(text) or "X1"):
            cfg = {"quality": "draft", "zunda": {"portraits": ""}}
            result = pipeline.run(cfg, Path(folder) / "out", data_dir=folder, clock=lambda: NOW, log=lambda *a: None)
            self.assertEqual(result["status"], "published")
            self.assertEqual(result["youtube"], "VID1")
            video, kwargs = uploads[0]
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
                capture_output=True, text=True, check=True,
            ).stdout
            self.assertIn("1920,1080", probe)
            self.assertIn("VOICEVOX:ずんだもん", kwargs["description"])
            self.assertIn("https://news.example.jp/a", kwargs["description"])
            self.assertTrue(posts and posts[0].endswith("https://youtu.be/VID1"))
            again = pipeline.run(cfg, Path(folder) / "out2", data_dir=folder, clock=lambda: NOW, log=lambda *a: None)
            self.assertEqual(again["status"], "already_published")
            saved = json.loads((Path(folder) / "zunda-state.json").read_text())
            self.assertIn("https://news.example.jp/a", saved["seen"])


if __name__ == "__main__":
    unittest.main()


class Chapters(unittest.TestCase):
    ITEMS = [{"title": "記事A"}, {"title": "記事B"}]

    def lines(self, sources):
        return [{"speaker": "zundamon", "text": "x", "source": s} for s in sources]

    def test_opening_articles_and_closing(self):
        result = pipeline.chapters(self.lines([-1, 0, 0, 1, 1, -1]), [12, 10, 10, 10, 10, 12], self.ITEMS)
        self.assertEqual(result, ["0:00 オープニング", "0:12 記事A", "0:32 記事B", "0:52 まとめ"])

    def test_too_short_chapters_are_left_out(self):
        self.assertEqual(pipeline.chapters(self.lines([-1, 0, 1]), [3, 3, 3], self.ITEMS), [])

    def test_line_cap(self):
        raw = {"lines": [{"speaker": "metan", "text": "説明ですわ", "source": -1}] * 200}
        self.assertEqual(len(script.validate(raw, [], log=lambda *a: None)["lines"]), script.MAX_LINES)


class Grounding(unittest.TestCase):
    ITEM = {
        "title": "新型チップ発表", "source": "Example", "summary": "",
        "text": "新しいチップは処理速度が従来の2.5倍になり、価格は3万9800円です。発売は来月。",
        "meta": {"paragraphs": [{"text": "発売は来月の予定です。", "box": [0, 0, 100, 20]}], "images": [],
                 "tables": [], "heading": [0, 0, 100, 40]},
    }

    def test_quotes_and_numbers_must_be_in_the_article(self):
        ok = script.check_visual({"kind": "quote", "quote": "処理速度が従来の2.5倍"}, self.ITEM)
        self.assertEqual(ok["kind"], "quote")
        self.assertEqual(script.check_visual({"kind": "quote", "quote": "10倍速くなった"}, self.ITEM)["kind"], "page")
        chart = {"kind": "chart", "items": [{"label": "速度", "value": 2.5}, {"label": "価格", "value": 39800}]}
        self.assertEqual(script.check_visual(chart, self.ITEM)["kind"], "chart")
        invented = {"kind": "chart", "items": [{"label": "速度", "value": 2.5}, {"label": "台数", "value": 100}]}
        self.assertEqual(script.check_visual(invented, self.ITEM)["kind"], "page")

    def test_references_must_exist(self):
        self.assertEqual(script.check_visual({"kind": "paragraph", "index": 0}, self.ITEM)["kind"], "paragraph")
        self.assertEqual(script.check_visual({"kind": "paragraph", "index": 7}, self.ITEM)["kind"], "page")
        self.assertEqual(script.check_visual({"kind": "image", "index": 0}, self.ITEM)["kind"], "page")
        self.assertEqual(script.check_visual({"kind": "nonsense"}, self.ITEM)["kind"], "keep")
        self.assertEqual(script.spoken("今日は【生成AI】の話"), "今日は生成AIの話")

    def test_formats_rotate(self):
        self.assertEqual({script.format_for(d) for d in range(7)}, {"roundup", "deep", "qa"})


class Visuals(unittest.TestCase):
    def test_every_builder_makes_layers_inside_the_panel(self):
        from explainer.zunda import visuals

        with tempfile.TemporaryDirectory() as folder:
            page = Path(folder) / "page.png"
            Image.new("RGB", (1920, 4000), (240, 240, 240)).save(page)
            meta = {"page": str(page), "scale": 1.5, "heading": [100, 300, 800, 60]}
            area = visuals.panel((1920, 1080))
            builders = [
                visuals.page_top(meta, area, folder, "a", 3),
                visuals.page_scroll(meta, area, folder, "b", 3),
                visuals.article_crop(meta, [100, 1500, 900, 120], area, folder, "c", 3),
                visuals.table_steps([["項目", "値"], ["速度", "2.5倍"], ["価格", "39800円"]], area, folder, "d", 3, "比較"),
                visuals.chart_steps({"title": "価格", "unit": "円", "items": [{"label": "A", "value": 1}, {"label": "B", "value": 2}]}, area, folder, "e", 3),
                visuals.points_steps(["一つ目", "二つ目"], area, folder, "f", 3),
                visuals.quote_card("引用の文", "Example", area, folder, "g", 3),
            ]
            for layers in builders:
                self.assertTrue(layers)
                for layer in layers:
                    self.assertGreaterEqual(layer["x"], area["x"] - 1)
                    self.assertLessEqual(layer["x"] + layer["w"], area["x"] + area["w"] + 1)
                    self.assertTrue(Path(layer["image"]).is_file())
            focus = builders[2][0]["focus"]
            self.assertTrue(0 <= focus[0] <= 1 and 0 <= focus[1] <= 1)
            self.assertEqual([l["motion"] for l in builders[3]][:2], ["pop", "still"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
    def test_layer_motions_render(self):
        from explainer.render import layer_graph

        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for name, size in [("base", (320, 180)), ("a", (100, 60)), ("b", (100, 200))]:
                Image.new("RGB", size, (120, 140, 160)).save(Path(folder) / f"{name}.png")
                paths.append(str(Path(folder) / f"{name}.png"))
            layers = [
                {"image": paths[1], "x": 10, "y": 10, "w": 100, "h": 60, "motion": "focus", "focus": (0.2, 0.8), "start": 0, "end": 1},
                {"image": paths[1], "x": 10, "y": 100, "w": 100, "h": 60, "motion": "hold", "zoom": 1.35, "start": 0, "end": 1},
                {"image": paths[2], "x": 200, "y": 10, "w": 100, "h": 200, "visible_h": 80, "motion": "pan", "start": 0, "end": 1},
                {"image": paths[1], "x": 200, "y": 100, "w": 100, "h": 60, "motion": "pop", "start": 0.3, "end": 1},
            ]
            graph, last = layer_graph(layers, 320, 180, 25, 1.0)
            command = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-loop", "1", "-i", paths[0],
                       "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            for layer in layers:
                command += ["-loop", "1", "-i", layer["image"]]
            command += ["-filter_complex", graph + f";[{last}]format=yuv420p[v]", "-map", "[v]", "-map", "1:a",
                        "-t", "1", "-c:v", "libx264", "-preset", "ultrafast", str(Path(folder) / "out.mp4")]
            subprocess.run(command, check=True, capture_output=True)
            self.assertGreater((Path(folder) / "out.mp4").stat().st_size, 0)
