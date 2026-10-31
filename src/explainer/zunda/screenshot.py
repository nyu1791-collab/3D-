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


def capture_many(urls, folder, timeout_ms=25000, log=print):
    """{url: png path or None}. One browser for all pages."""
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
            device_scale_factor=1.5,
            locale="ja-JP",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
            ),
        )
        for index, url in enumerate(urls):
            page = context.new_page()
            target = folder / f"shot-{index:02d}.png"
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
                page.evaluate(HIDE_OVERLAYS)
                page.screenshot(path=str(target), timeout=timeout_ms)
                results[url] = target
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
