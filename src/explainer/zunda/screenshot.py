"""Page screenshots with Playwright (Chromium), and a title card when a page fails.

The visible top of the article is captured at 1280x800 (x1.5 for sharp text).
Cookie banners and other fixed overlays that cover the page are hidden first.
A screenshot is shown with its source as quotation material next to the
commentary; it is never the main content of the video.
"""

import os
from pathlib import Path

from PIL import Image, ImageDraw

from .compose import font

HIDE_OVERLAYS = """
() => {
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if ((s.position === 'fixed' || s.position === 'sticky') && el.offsetHeight * el.offsetWidth > 0.08 * innerWidth * innerHeight) {
      el.style.setProperty('display', 'none', 'important');
    }
  }
  document.documentElement.style.overflow = 'auto';
  document.body.style.overflow = 'auto';
}
"""
CONSENT = ["同意", "同意する", "すべて許可", "OK", "Accept", "Accept all", "I agree", "Agree"]


COLLECT = """
() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 40 && r.height > 10 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const box = (el) => { const r = el.getBoundingClientRect(); return [r.left + scrollX, r.top + scrollY, r.width, r.height]; };
  const h1 = [...document.querySelectorAll('h1')].find(visible);
  const seen = new Set();
  const paragraphs = [...document.querySelectorAll('article p, main p, p')]
    .filter(visible)
    .map((p) => ({ box: box(p), text: p.innerText.trim().replace(/\\s+/g, ' ') }))
    .filter((p) => p.text.length >= 30 && !seen.has(p.text) && seen.add(p.text))
    .slice(0, 15);
  const images = [...document.images]
    .filter((i) => visible(i) && i.naturalWidth >= 300 && i.getBoundingClientRect().width >= 250)
    .map(box).slice(0, 4);
  const tables = [...document.querySelectorAll('table')].filter(visible).slice(0, 2).map((t) => ({
    box: box(t),
    rows: [...t.rows].slice(0, 10).map((r) => [...r.cells].slice(0, 6).map((c) => c.innerText.trim().slice(0, 40))),
  }));
  return { heading: h1 ? box(h1) : null, heading_text: h1 ? h1.innerText.trim() : '', paragraphs, images, tables,
           height: document.documentElement.scrollHeight };
}
"""
SCROLL = """
async () => {
  for (let y = 0; y < Math.min(document.documentElement.scrollHeight, 6000); y += 700) {
    window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 120));
  }
  window.scrollTo(0, 0);
}
"""
SCALE = 1.5
MAX_HEIGHT = 6000


def capture_many(urls, folder, timeout_ms=25000, log=print):
    """{url: metadata or None}. metadata: page (PNG of the top of the article, up to
    6000 CSS px), scale, and boxes/text for the heading, paragraphs, images, tables."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    results = {url: None for url in urls}
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("[screenshot] playwright が無いのでタイトルカードを使います")
        return results
    with sync_playwright() as p:
        try:
            # ZUNDA_CHROMIUM: use an already installed Chromium instead of Playwright's own.
            browser = p.chromium.launch(executable_path=os.environ.get("ZUNDA_CHROMIUM") or None)
        except PlaywrightError as error:
            log(f"[screenshot] ブラウザを起動できないのでタイトルカードを使います: {str(error).splitlines()[0][:160]}")
            return results
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            device_scale_factor=SCALE,
            locale="ja-JP",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
            ),
        )
        for index, url in enumerate(urls):
            page = context.new_page()
            target = folder / f"page-{index:02d}.png"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(1500)
                for label in CONSENT:
                    button = page.get_by_role("button", name=label, exact=True)
                    if button.count():
                        try:
                            button.first.click(timeout=1500)
                            break
                        except PlaywrightError:
                            pass
                page.evaluate(SCROLL)  # load lazy images
                page.evaluate(HIDE_OVERLAYS)
                meta = page.evaluate(COLLECT)
                height = min(int(meta.get("height") or 800), MAX_HEIGHT)
                page.screenshot(
                    path=str(target), full_page=True, clip={"x": 0, "y": 0, "width": 1280, "height": height},
                    timeout=timeout_ms,
                )
                meta.update(page=str(target), scale=SCALE)
                results[url] = meta
            except PlaywrightError as error:
                log(f"[screenshot] {url}: {str(error).splitlines()[0][:160]}")
            finally:
                page.close()
        browser.close()
    return results


def title_card(title, source, path, size=(1280, 800)):
    """Fallback image: the headline and its source on a plain card."""
    image = Image.new("RGB", size, (245, 247, 250))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, size[0], 14], fill=(46, 125, 50))
    heading = font(54, bold=True)
    lines, line = [], ""
    for char in title:
        if draw.textlength(line + char, font=heading) > size[0] - 160:
            lines.append(line)
            line = char
        else:
            line += char
    lines.append(line)
    y = 220
    for text in lines[:4]:
        draw.text((80, y), text, font=heading, fill=(30, 30, 30))
        y += 78
    draw.text((80, size[1] - 120), source, font=font(34), fill=(90, 90, 90))
    image.save(path)
    return Path(path)
