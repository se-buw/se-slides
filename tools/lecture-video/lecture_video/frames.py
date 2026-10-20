"""One 1920x1080 picture per step: every slide, then every fragment of it.

The deck runs in the pinned chrome-headless-shell at its own size (1280x720), scaled 1.5:
text and diagrams stay sharp. deck.html?video hides the navigation (se-slides.js).
Pictures are kept until the deck's HTML changes.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import course, deck as deckmod

SCALE = 1.5  # 1280x720 -> 1920x1080


def html_hash(deck: str) -> str:
    """The deck's HTML and the local scripts and styles it loads (se-slides.js changes the pictures)."""
    page = deckmod.html_path(deck)
    html = page.read_bytes()
    h = hashlib.sha256(html)
    for ref in sorted(set(re.findall(rb'(?:src|href)="([^"#?:]+\.(?:js|css))"', html))):
        f = page.parent / ref.decode()
        if f.exists():
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def manifest_path(deck: str) -> Path:
    return course.out_dir(deck) / "frames" / "manifest.json"


def capture(deck: str, force: bool = False) -> dict:
    """Returns the manifest: {"html": hash, "slides": [{"id", "title", "level", "section", "frames": [png, ...]}]}"""
    slides = deckmod.read_slides(deck)
    target = course.out_dir(deck) / "frames"
    mpath = manifest_path(deck)
    h = html_hash(deck)
    if not force and mpath.exists():
        m = json.loads(mpath.read_text(encoding="utf-8"))
        if m.get("html") == h and all((target / f).exists() for s in m["slides"] for f in s["frames"]):
            return m
    from playwright.sync_api import sync_playwright

    target.mkdir(parents=True, exist_ok=True)
    # fades and countdowns (build.py) are made from these pictures: away with them, too
    for old in [*target.glob("*.png"), *(course.out_dir(deck) / "pictures").glob("*.png")]:
        old.unlink()
    url = deckmod.html_path(deck).resolve().as_uri() + "?video"
    out = {"html": h, "slides": []}
    print(f"FRAMES {deck}")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=course.find_browser(), args=["--disable-gpu", "--hide-scrollbars"])
        page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=SCALE)
        page.goto(url, wait_until="networkidle")
        page.wait_for_function("window.Reveal && Reveal.isReady && Reveal.isReady()")
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(1500)  # diagrams (mermaid) and QR codes render after ready
        for s in slides:
            shown = page.evaluate(
                """id => { const el = document.getElementById(id); if (!el) return false;
                           const i = Reveal.getIndices(el); Reveal.slide(i.h, i.v, -1); return true; }""",
                s.id)
            if not shown:
                raise SystemExit(f"{deck}: slide {s.id} not found in the browser")
            page.wait_for_timeout(250)
            frames = []
            for k in range(s.fragments + 1):
                if k:
                    if not page.evaluate("Reveal.nextFragment()"):
                        raise SystemExit(f"{deck}/{s.id}: Reveal has fewer fragments than the {s.fragments} counted in the HTML")
                    page.wait_for_timeout(120)
                name = f"{s.position:03d}-{k}.png"
                page.screenshot(path=str(target / name))
                frames.append(name)
            if page.evaluate("Reveal.nextFragment()"):
                raise SystemExit(f"{deck}/{s.id}: Reveal has more fragments than the {s.fragments} counted in the HTML")
            out["slides"].append({"id": s.id, "title": s.title, "level": s.level, "section": s.section, "frames": frames})
        browser.close()
    mpath.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"FRAMES {deck} - {sum(len(s['frames']) for s in out['slides'])} pictures in {target}")
    return out
