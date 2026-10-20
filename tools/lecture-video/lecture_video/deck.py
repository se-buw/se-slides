"""The slides of a rendered deck (_site/lectures/<deck>.html), read without a browser.

Standard library only: `check` runs in every build, also where the video environment is missing.
frames.py compares the fragment counts with what Reveal reports in the browser.
"""
from __future__ import annotations

import hashlib
import html.parser
import re
from dataclasses import dataclass, field
from pathlib import Path

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
# not part of what the viewer reads on the slide
SKIP_CLASSES = {"notes", "code-copy-button", "course-overflow-label", "code-annotation-anchor"}
SKIP_TAGS = {"script", "style", "aside", "template", "button"}


@dataclass
class Node:
    tag: str
    attrs: dict[str, str]
    children: list = field(default_factory=list)  # Node or str
    parent: "Node | None" = None

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.walk()


class _Builder(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {})
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, parent=self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, {k: (v or "") for k, v in attrs}, parent=self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


@dataclass
class Slide:
    id: str
    title: str
    level: int            # 0 title slide, 1 section (# heading), 2 slide (## heading)
    section: str          # title of the section the slide belongs to
    fragments: int        # clicks on the slide (fragments and code line steps)
    text: str             # visible text, whitespace collapsed (with image alt texts)
    position: int = 0     # 1-based among the narrated slides

    @property
    def hash(self) -> str:
        return hashlib.sha256(f"{self.fragments}\n{self.text}".encode()).hexdigest()[:16]


def _text(node: Node, out: list[str]):
    for c in node.children:
        if isinstance(c, str):
            out.append(c)
            continue
        if c.tag in SKIP_TAGS or c.classes & SKIP_CLASSES:
            continue
        if c.tag == "img":
            alt = c.attrs.get("alt", "").strip()
            out.append(f" [image: {alt or Path(c.attrs.get('src', '')).name}] ")
            continue
        _text(c, out)
        if c.tag in {"p", "li", "div", "pre", "h1", "h2", "h3", "tr", "br", "section"}:
            out.append(" ")


def _fragments(section: Node) -> int:
    indices: set[str] = set()
    unindexed = 0
    steps = 0
    for n in section.walk():
        if n is section:
            continue
        if n.tag in SKIP_TAGS or n.classes & SKIP_CLASSES:
            continue
        if "fragment" in n.classes:
            i = n.attrs.get("data-fragment-index")
            if i is None:
                unindexed += 1
            else:
                indices.add(i)
        lines = n.attrs.get("data-code-line-numbers")
        if lines and "|" in lines:
            steps += len(lines.split("|")) - 1
    return len(indices) + unindexed + steps


def _inside_skipped(n: Node) -> bool:
    p = n.parent
    while p is not None:
        if p.tag in SKIP_TAGS or p.classes & SKIP_CLASSES:
            return True
        p = p.parent
    return False


def html_path(deck: str) -> Path:
    return Path("_site/lectures") / f"{deck}.html"


def read_slides(deck: str) -> list[Slide]:
    """The narratable slides in order: title slide, sections and slides; not the credits slide."""
    path = html_path(deck)
    if not path.exists():
        raise FileNotFoundError(f"{path} missing: build the deck first (./build.ps1 {deck})")
    b = _Builder()
    b.feed(path.read_text(encoding="utf-8"))
    container = next((n for n in b.root.walk() if n.tag == "div" and "slides" in n.classes), None)
    if container is None:
        raise ValueError(f"{path}: no reveal.js slides found")
    slides: list[Slide] = []
    section = ""
    for s in container.walk():
        if s.tag != "section" or s is container or _inside_skipped(s):
            continue
        if any(isinstance(c, Node) and c.tag == "section" for c in s.children):
            continue  # vertical stack: its slides are listed themselves
        cls = s.classes
        if "credits" in cls or s.attrs.get("data-visibility") == "hidden" or not s.attrs.get("id"):
            continue
        level = 1 if "level1" in cls else 2 if "level2" in cls else 0
        heading = next((n for n in s.walk() if n.tag in ("h1", "h2")), None)
        parts: list[str] = []
        if heading is not None:
            _text(heading, parts)
        title = re.sub(r"\s+", " ", "".join(parts)).strip()
        if level == 0:
            title = title or "Title"
        if level == 1:
            section = title
        parts = []
        _text(s, parts)
        text = re.sub(r"\s+", " ", "".join(parts)).strip()
        slides.append(Slide(s.attrs["id"], title, level, section if level else "", _fragments(s), text))
    for i, sl in enumerate(slides, 1):
        sl.position = i
    return slides
