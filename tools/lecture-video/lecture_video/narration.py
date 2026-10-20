"""Narration files: lectures/<deck>.narration.<lang>.md, the spoken text of each slide.

    ## The while loop {#while-loop}      one block per slide, keyed by the slide id
    Text of the first step.               paragraphs are spoken one after another
    While `count < 5`, `count++` runs.    code as on the slide, in backticks (speakcode.py)
    [click]                               the next fragment appears (fragment 1, 2, ...)
    Text while fragment 1 is visible.
    [think]                               pause prompt with countdown (countdown_seconds)
    [think 5]                             ... with 5 s
    [pause 1.5]                           silence, 1.5 s
    <!-- review notes, not spoken -->

Text before the first slide heading (a # title, front matter) is ignored.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .speakcode import CODE, plain

HEADING = re.compile(r"^##\s+(?:(.*?)\s*)?\{#([^}\s]+)\}\s*$")
MARKER = re.compile(r"^\[(click|think|pause)(?:\s+([\d.]+))?\]\s*$")


@dataclass
class Speech:
    text: str
    line: int


@dataclass
class Silence:
    seconds: float


@dataclass
class Think:
    seconds: float | None  # None: countdown_seconds from the configuration


@dataclass
class NSlide:
    id: str
    title: str
    line: int
    steps: list[list] = field(default_factory=lambda: [[]])  # step k: items while k fragments are shown

    @property
    def clicks(self) -> int:
        return len(self.steps) - 1

    def speeches(self):
        for step in self.steps:
            for item in step:
                if isinstance(item, Speech):
                    yield item

    @property
    def words(self) -> int:
        return sum(len(plain(s.text).split()) for s in self.speeches())


@dataclass
class Narration:
    deck: str
    lang: str
    path: Path
    slides: list[NSlide]
    problems: list[tuple[int, str]]  # (line, message): syntax errors

    def by_id(self) -> dict[str, NSlide]:
        return {s.id: s for s in self.slides}


def path_of(deck: str, lang: str) -> Path:
    return Path("lectures") / f"{deck}.narration.{lang}.md"


def langs_of(deck: str) -> list[str]:
    return sorted(p.name.split(".")[-2] for p in Path("lectures").glob(f"{deck}.narration.*.md"))


def parse(deck: str, lang: str, path: Path | None = None) -> Narration:
    path = path or path_of(deck, lang)
    lines = path.read_text(encoding="utf-8").splitlines()
    slides: list[NSlide] = []
    problems: list[tuple[int, str]] = []
    para: list[str] = []
    para_line = 0
    in_comment = False

    def flush():
        nonlocal para
        if para and slides:
            slides[-1].steps[-1].append(Speech(" ".join(para), para_line))
        para = []

    for no, raw in enumerate(lines, 1):
        line = raw.strip()
        if in_comment:
            if "-->" in line:
                in_comment = False
                line = line.split("-->", 1)[1].strip()
            else:
                continue
        while "<!--" in line:
            before, _, rest = line.partition("<!--")
            if "-->" in rest:
                line = (before + " " + rest.split("-->", 1)[1]).strip()
            else:
                line, in_comment = before.strip(), True
        m = HEADING.match(line)
        if m:
            flush()
            slides.append(NSlide(m.group(2), (m.group(1) or "").strip(), no))
            continue
        if line.startswith("#"):
            flush()
            if slides:
                problems.append((no, f"heading without slide id: {line!r} (write  ## Title {{#slide-id}})"))
            continue
        if not slides:
            continue
        m = MARKER.match(line)
        if m:
            flush()
            kind, num = m.group(1), m.group(2)
            if kind == "click":
                if num:
                    problems.append((no, "[click] takes no number"))
                slides[-1].steps.append([])
            elif kind == "think":
                slides[-1].steps[-1].append(Think(float(num) if num else None))
            else:
                if not num:
                    problems.append((no, "[pause] needs the seconds, e.g. [pause 1.5]"))
                slides[-1].steps[-1].append(Silence(float(num or 1)))
            continue
        if line.startswith("[") and line.endswith("]"):
            problems.append((no, f"unknown marker {line} (known: [click], [think], [think 5], [pause 1.5])"))
            continue
        if not line:
            flush()
            continue
        if not para:
            para_line = no
        para.append(line)
    flush()
    return Narration(deck, lang, path, slides, problems)


# Characters a speech engine reads out wrongly or not at all, outside code spans:
# write them as words, or put the code in backticks (speakcode.py says it).
UNSPEAKABLE = re.compile(r"[*_{}\[\]<>|\\#;=~^$]|\(\)|//|\+\+|--(?!-)")


def unspeakable(text: str) -> list[str]:
    bad = set(UNSPEAKABLE.findall(CODE.sub(" ", text)))
    if text.count("`") % 2:
        bad.add("unpaired `")
    return sorted(bad)
