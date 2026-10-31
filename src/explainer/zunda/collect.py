"""Gather today's candidate topics from RSS/Atom feeds and Hacker News.

Each item: {title, url, summary, source, published}. Items are scored by
freshness, keyword hits and source weight; URLs already used are skipped.
Article text is fetched separately (``article_text``) so the script can stick
to what the source actually says.
"""

import html
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from . import http

DEFAULT_FEEDS = [
    {"url": "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml", "name": "ITmedia NEWS", "weight": 1.0},
    {"url": "https://gigazine.net/news/rss_2.0/", "name": "GIGAZINE", "weight": 0.9},
    {"url": "https://www.publickey1.jp/atom.xml", "name": "Publickey", "weight": 1.0},
]
HN_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"
ATOM = "{http://www.w3.org/2005/Atom}"


def _text(node, *names):
    for name in names:
        found = node.find(name)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def _epoch(value):
    if not value:
        return 0.0
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def strip_tags(value):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def parse_feed(text, source):
    root = ET.fromstring(text)
    items = []
    for item in root.iter("item"):  # RSS 2.0
        items.append(
            {
                "title": strip_tags(_text(item, "title")),
                "url": _text(item, "link"),
                "summary": strip_tags(_text(item, "description"))[:600],
                "source": source,
                "published": _epoch(_text(item, "pubDate", "{http://purl.org/dc/elements/1.1/}date")),
            }
        )
    for entry in root.iter(ATOM + "entry"):  # Atom
        link = ""
        for node in entry.findall(ATOM + "link"):
            if node.get("rel", "alternate") == "alternate":
                link = node.get("href", "")
                break
        items.append(
            {
                "title": strip_tags(_text(entry, ATOM + "title")),
                "url": link,
                "summary": strip_tags(_text(entry, ATOM + "summary", ATOM + "content"))[:600],
                "source": source,
                "published": _epoch(_text(entry, ATOM + "published", ATOM + "updated")),
            }
        )
    return [i for i in items if i["title"] and i["url"].startswith(("http://", "https://"))]


def hacker_news(limit=15, request=http.request):
    ids = request("GET", HN_TOP).json()[:limit]
    items = []
    for item_id in ids:
        data = request("GET", HN_ITEM.format(item_id)).json() or {}
        if data.get("type") != "story" or not data.get("url"):
            continue
        items.append(
            {
                "title": data.get("title", ""),
                "url": data["url"],
                "summary": f"Hacker News {data.get('score', 0)} points",
                "source": "Hacker News",
                "published": float(data.get("time", 0)),
                "score_hint": min(data.get("score", 0) / 500, 1.0),
            }
        )
    return items


def score(item, keywords, weight, now):
    hours = max(0.0, (now - item["published"]) / 3600) if item["published"] else 48
    freshness = max(0.0, 1 - hours / 48)
    text = (item["title"] + " " + item["summary"]).lower()
    hits = sum(1 for k in keywords if k.lower() in text)
    return round(weight * (freshness + 0.6 * hits + item.get("score_hint", 0)), 4)


def gather(feeds=None, keywords=(), seen=(), use_hn=True, request=http.request, now=None, log=print):
    now = now or time.time()
    seen = set(seen)
    found = {}
    for feed in feeds or DEFAULT_FEEDS:
        try:
            for item in parse_feed(request("GET", feed["url"]).text(), feed.get("name", feed["url"])):
                item["score"] = score(item, keywords, float(feed.get("weight", 1.0)), now)
                found.setdefault(item["url"], item)
        except (http.HttpError, ET.ParseError) as error:
            log(f"[collect] {feed.get('name')}: 取得できませんでした（{error}）")
    if use_hn:
        try:
            for item in hacker_news(request=request):
                item["score"] = score(item, keywords, 0.8, now)
                found.setdefault(item["url"], item)
        except (http.HttpError, ValueError) as error:
            log(f"[collect] Hacker News: 取得できませんでした（{error}）")
    fresh = [i for i in found.values() if i["url"] not in seen and now - i["published"] < 3 * 86400]
    return sorted(fresh, key=lambda i: i["score"], reverse=True)


class _Paragraphs(HTMLParser):
    SKIP = {"script", "style", "nav", "header", "footer", "aside", "form", "noscript"}

    def __init__(self):
        super().__init__()
        self.depth_skip, self.in_p, self.parts, self.current = 0, False, [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth_skip += 1
        elif tag in ("p", "li", "h2", "h3") and not self.depth_skip:
            self.in_p, self.current = True, []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth_skip:
            self.depth_skip -= 1
        elif tag in ("p", "li", "h2", "h3") and self.in_p:
            text = " ".join("".join(self.current).split())
            if len(text) >= 20:  # Japanese paragraphs are dense; 20 characters is a sentence
                self.parts.append(text)
            self.in_p = False

    def handle_data(self, data):
        if self.in_p and not self.depth_skip:
            self.current.append(data)


def article_text(url, limit=3000, request=http.request):
    """Main paragraphs of an article (heuristic). Empty when unavailable."""
    try:
        reply = request("GET", url, headers={"Accept": "text/html"}, timeout=30)
    except http.HttpError:
        return ""
    charset = re.search(r"charset=([\w-]+)", reply.headers.get("content-type", ""))
    try:
        page = reply.body.decode(charset.group(1) if charset else "utf-8", "replace")
    except LookupError:
        page = reply.body.decode("utf-8", "replace")
    parser = _Paragraphs()
    parser.feed(page)
    return "\n".join(parser.parts)[:limit]


def domain(url):
    return urllib.parse.urlsplit(url).netloc.removeprefix("www.")
