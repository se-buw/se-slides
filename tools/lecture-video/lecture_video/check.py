"""Narration against the slides: check, stamp, fix-ids, estimate. Standard library only.

The lock file lectures/<deck>.narration.<lang>.lock.json (written by stamp after a review) keeps
the slides as they were when the narration was right: position, fragments, hash and visible text.
"""
from __future__ import annotations

import datetime
import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import course, deck as deckmod, narration as nmod, speakcode

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"
ORDER = {ERROR: 0, WARN: 1, INFO: 2}


@dataclass
class Finding:
    severity: str
    slide: str
    message: str
    detail: str = ""
    position: int = 0


def lock_path(deck: str, lang: str) -> Path:
    return Path("lectures") / f"{deck}.narration.{lang}.lock.json"


def read_lock(deck: str, lang: str) -> dict | None:
    p = lock_path(deck, lang)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def word_diff(old: str, new: str, max_hunks: int = 6) -> str:
    a, b = old.split(), new.split()
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        ctx = " ".join(a[max(0, i1 - 4):i1])
        line = f"… {ctx} " if ctx else ""
        if i2 > i1:
            line += "[-" + " ".join(a[i1:i2]) + "-]"
        if j2 > j1:
            line += "{+" + " ".join(b[j1:j2]) + "+}"
        out.append(line)
        if len(out) == max_hunks:
            out.append("…")
            break
    return "\n".join(out)


TOKEN = re.compile(r"\b\w+(?:\.\w+)+\b|\b[A-Za-z]\w*[A-Z_]\w*\b|\b\d+(?:[.,]\d+)?\b|\"([^\"]{2,40})\"")


def tokens(text: str) -> set[str]:
    """Code the narration talks about: code spans as written, and names or numbers in the text."""
    out = {t.strip(".,;:()") for t in speakcode.spans(text)} - {""}
    text = speakcode.CODE.sub(" ", text)
    for m in TOKEN.finditer(text):
        out.add(m.group(1) or m.group(0))
    return out


def suggest(nid: str, ntitle: str, free: list[deckmod.Slide]) -> deckmod.Slide | None:
    """The un-narrated slide that most likely is the renamed one."""
    best, score, second = None, 0.0, 0.0
    for s in free:
        r = max(difflib.SequenceMatcher(None, nid, s.id).ratio(),
                difflib.SequenceMatcher(None, ntitle.lower(), s.title.lower()).ratio() if ntitle else 0)
        if r > score:
            best, score, second = s, r, score
        elif r > second:
            second = r
    return best if score >= 0.6 and score - second >= 0.1 else None


def estimate_seconds(n: nmod.Narration, cfg: dict) -> float:
    wpm = measured_wpm(n.lang, cfg) or cfg["words_per_minute"].get(n.lang, 150)
    total = 0.0
    for s in n.slides:
        total += cfg["pause_before_slide"] + cfg["pause_after_slide"]
        total += s.clicks * (cfg["fade_seconds"] + cfg["pause_after_click"])
        for step in s.steps:
            speeches = [i for i in step if isinstance(i, nmod.Speech)]
            total += max(0, len(speeches) - 1) * cfg["pause_between_paragraphs"]
            for i in step:
                if isinstance(i, nmod.Think):
                    total += i.seconds or cfg["countdown_seconds"]
                elif isinstance(i, nmod.Silence):
                    total += i.seconds
        total += s.words / wpm * 60
    return total


def measured_wpm(lang: str, cfg: dict) -> float | None:
    """Words per minute of the configured voice, measured by the last video build."""
    p = Path("_video") / "wpm.json"
    if not p.exists():
        return None
    voice = cfg.get("voices", {}).get(lang)
    key = f"{lang}:{json.dumps(voice, sort_keys=True)}" if voice else None
    return json.loads(p.read_text(encoding="utf-8")).get(key)


def check_deck(deck: str, lang: str, cfg: dict, slides: list[deckmod.Slide] | None = None) -> list[Finding]:
    slides = slides if slides is not None else deckmod.read_slides(deck)
    n = nmod.parse(deck, lang)
    lock = read_lock(deck, lang)
    found: list[Finding] = []
    current = {s.id: s for s in slides}
    narrated = n.by_id()

    for line, msg in n.problems:
        found.append(Finding(ERROR, f"line {line}", msg))
    seen = set()
    for ns in n.slides:
        if ns.id in seen:
            found.append(Finding(ERROR, ns.id, f"narrated twice (line {ns.line})"))
        seen.add(ns.id)

    free = [s for s in slides if s.id not in narrated]
    for ns in n.slides:
        if ns.id not in current:
            sug = suggest(ns.id, ns.title, free)
            hint = f"probably renamed to {sug.id!r} ({sug.title}): run fix-ids" if sug else "slide renamed or deleted"
            found.append(Finding(ERROR, ns.id, f"no such slide (line {ns.line}); {hint}"))
    for s in slides:
        ns = narrated.get(s.id)
        if ns is None:
            found.append(Finding(ERROR, s.id, f"no narration for slide {s.position} ({s.title})", position=s.position))
            continue
        if ns.clicks != s.fragments:
            found.append(Finding(ERROR, s.id, f"{ns.clicks} [click] in the narration, {s.fragments} fragment(s) on the slide "
                                 f"(line {ns.line})", position=s.position))
        if not ns.words:
            found.append(Finding(WARN, s.id, f"slide has no spoken text (line {ns.line})", position=s.position))
        for sp in ns.speeches():
            bad = nmod.unspeakable(sp.text)
            if bad:
                found.append(Finding(WARN, s.id, f"line {sp.line}: write as words: {' '.join(bad)}", position=s.position))

    if lock is None:
        found.append(Finding(INFO, "-", f"not stamped yet: after the review run  lecture-video.ps1 {deck} stamp -Lang {lang}"))
    else:
        old = {s["id"]: s for s in lock["slides"]}
        old_order = [s["id"] for s in lock["slides"]]
        new_order = [s.id for s in slides]
        for s in slides:
            o = old.get(s.id)
            ns = narrated.get(s.id)
            if o is None or ns is None:
                continue
            if o["hash"] != s.hash:
                detail = word_diff(o["text"], s.text)
                if o["fragments"] != s.fragments:
                    detail = f"fragments {o['fragments']} -> {s.fragments}\n" + detail
                found.append(Finding(WARN, s.id, f"slide changed since the narration was stamped ({lock.get('stamped', '?')})",
                                     detail, s.position))
                spoken = " ".join(sp.text for sp in ns.speeches())
                gone = sorted(t for t in tokens(spoken) if t in o["text"] and t not in s.text)
                if gone:
                    found.append(Finding(WARN, s.id, "narration mentions what is no longer on the slide: " + ", ".join(gone),
                                         position=s.position))
            i, j = old_order.index(s.id) if s.id in old_order else -1, new_order.index(s.id)
            if i >= 0:
                before_old = old_order[i - 1] if i > 0 else None
                before_new = new_order[j - 1] if j > 0 else None
                if before_old != before_new and before_new in old:
                    found.append(Finding(INFO, s.id, f"now after {before_new!r}, was after {before_old!r}: check the transition",
                                         position=s.position))

    secs = estimate_seconds(n, cfg)
    if secs > cfg["max_minutes"] * 60:
        found.append(Finding(ERROR, "-", f"estimated {secs / 60:.0f} min, more than max_minutes {cfg['max_minutes']}"))
    elif secs > cfg["target_minutes"] * 60:
        found.append(Finding(INFO, "-", f"estimated {secs / 60:.0f} min, more than target_minutes {cfg['target_minutes']}"))
    found.sort(key=lambda f: (ORDER[f.severity], f.position))
    return found


def run_check(decks: list[str], langs: list[str] | None, stale: bool = False, quiet: bool = False) -> int:
    cfg = course.load_config()
    errors = 0
    for d in decks:
        slides = deckmod.read_slides(d)
        for lang in langs or nmod.langs_of(d):
            if not nmod.path_of(d, lang).exists():
                print(f"NARRATION {d} [{lang}] - no {nmod.path_of(d, lang)}")
                continue
            found = check_deck(d, lang, cfg, slides)
            if stale:
                found = [f for f in found if f.severity == WARN and f.detail]
            errs = sum(f.severity == ERROR for f in found)
            errors += errs
            shown = [f for f in found if not quiet or f.severity != INFO]
            counts = ", ".join(f"{sum(f.severity == s for f in found)} {s.lower()}" for s in (ERROR, WARN, INFO)
                               if any(f.severity == s for f in found))
            print(f"NARRATION {d} [{lang}] - {counts or 'ok'}")
            for f in shown:
                print(f"  {f.severity:5} {f.slide}: {f.message}")
                if f.detail:
                    for line in f.detail.splitlines():
                        print(f"        {line}")
            if stale and found:
                n = nmod.parse(d, lang).by_id()
                for f in found:
                    ns = n.get(f.slide)
                    if ns:
                        print(f"\n  --- current narration of {f.slide} (line {ns.line}) ---")
                        for k, step in enumerate(ns.steps):
                            if k:
                                print("  [click]")
                            for item in step:
                                if isinstance(item, nmod.Speech):
                                    print("  " + item.text)
                                elif isinstance(item, nmod.Think):
                                    print("  [think]")
    return 2 if errors else 0


def stamp(decks: list[str], langs: list[str] | None, force: bool) -> int:
    cfg = course.load_config()
    for d in decks:
        slides = deckmod.read_slides(d)
        for lang in langs or nmod.langs_of(d):
            errs = [f for f in check_deck(d, lang, cfg, slides) if f.severity == ERROR]
            if errs and not force:
                print(f"STAMP {d} [{lang}] - refused, {len(errs)} error(s); fix them or use -Force")
                for f in errs:
                    print(f"  {f.slide}: {f.message}")
                return 2
            narrated = nmod.parse(d, lang).by_id()
            lock = {
                "deck": d, "lang": lang, "stamped": datetime.date.today().isoformat(),
                "slides": [{"id": s.id, "position": s.position, "title": s.title, "fragments": s.fragments,
                            "hash": s.hash, "text": s.text} for s in slides if s.id in narrated],
            }
            lock_path(d, lang).write_text(json.dumps(lock, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"STAMP {d} [{lang}] - {len(lock['slides'])} slides -> {lock_path(d, lang)}")
    return 0


def fix_ids(decks: list[str], langs: list[str] | None) -> int:
    for d in decks:
        slides = deckmod.read_slides(d)
        current = {s.id for s in slides}
        for lang in langs or nmod.langs_of(d):
            n = nmod.parse(d, lang)
            narrated = n.by_id()
            free = [s for s in slides if s.id not in narrated]
            lines = n.path.read_text(encoding="utf-8").splitlines(keepends=True)
            changed = 0
            for ns in n.slides:
                if ns.id in current:
                    continue
                sug = suggest(ns.id, ns.title, free)
                if not sug:
                    print(f"FIX-IDS {d} [{lang}] {ns.id}: no clear match, edit line {ns.line} by hand")
                    continue
                lines[ns.line - 1] = lines[ns.line - 1].replace("{#" + ns.id + "}", "{#" + sug.id + "}")
                if ns.title and ns.title != sug.title:
                    lines[ns.line - 1] = lines[ns.line - 1].replace(ns.title, sug.title, 1)
                free.remove(sug)
                changed += 1
                print(f"FIX-IDS {d} [{lang}] {ns.id} -> {sug.id}")
            if changed:
                n.path.write_text("".join(lines), encoding="utf-8")
    return 0


def estimate(decks: list[str], langs: list[str] | None) -> int:
    cfg = course.load_config()
    for d in decks:
        for lang in langs or nmod.langs_of(d):
            n = nmod.parse(d, lang)
            wpm = measured_wpm(lang, cfg)
            src = f"measured {wpm:.0f} wpm" if wpm else f"assumed {cfg['words_per_minute'].get(lang, 150)} wpm"
            secs = estimate_seconds(n, cfg)
            words = sum(s.words for s in n.slides)
            print(f"ESTIMATE {d} [{lang}] {secs / 60:5.1f} min  {words} words, {len(n.slides)} slides ({src})")
    return 0
