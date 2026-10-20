"""The video of one deck and language: timeline, pictures, audio, ffmpeg.

Sync by construction: the timeline places every step's picture and every spoken paragraph on
one clock. A [click] starts the fade to the next fragment exactly where the narration reaches it.
Times are rounded to whole video frames, so picture and voice never drift apart.
"""
from __future__ import annotations

import datetime
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

from . import check, course, frames as framesmod, narration as nmod, speakcode
from .tts import Voice

W, H = 1920, 1080
FONT = Path(__file__).resolve().parents[3] / "fonts" / "Jost.ttf"  # se-slides/fonts
BLUE, INK, BG = (29, 78, 137), (26, 26, 26), (255, 255, 255)


@dataclass
class Shot:            # a picture from one frame to the next shot (end exclusive)
    image: Path
    start: int
    end: int = 0


@dataclass
class Cue:             # subtitle
    start: float
    end: float
    text: str


@dataclass
class Timeline:
    fps: int
    sr: int
    shots: list[Shot] = field(default_factory=list)
    audio: list[tuple[int, np.ndarray]] = field(default_factory=list)  # (start sample, samples)
    cues: list[Cue] = field(default_factory=list)
    slides: dict[str, list[float]] = field(default_factory=dict)       # id -> [start, length]
    chapters: list[tuple[float, str]] = field(default_factory=list)
    speech_seconds: float = 0.0
    words: int = 0
    end: float = 0.0

    def frame(self, t: float) -> int:
        return round(t * self.fps)

    def show(self, image: Path, t: float):
        """From time t on, the video shows this picture."""
        a = self.frame(t)
        if self.shots and self.shots[-1].start >= a:
            self.shots.pop()  # replaced within the same frame
        if not self.shots or self.shots[-1].image != image:
            self.shots.append(Shot(image, a))

    def finish(self, t: float):
        self.end = self.frame(t) / self.fps
        for s, nxt in zip(self.shots, self.shots[1:]):
            s.end = nxt.start
        self.shots[-1].end = self.frame(t)


# --- pictures made from the slides: fades and the countdown badge

def _font(size: int, weight: int = 600) -> ImageFont.FreeTypeFont:
    try:
        f = ImageFont.truetype(str(FONT), size)
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
        return f
    except OSError:
        return ImageFont.load_default(size)


def fade_frames(a: Path, b: Path, n: int, folder: Path) -> list[Path]:
    out = []
    folder.mkdir(parents=True, exist_ok=True)
    ia = ib = None
    for i in range(1, n):
        p = folder / f"fade-{a.stem}-{b.stem}-{i:02d}of{n}.png"
        if not p.exists():
            if ia is None:
                ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
            x = i / n
            Image.blend(ia, ib, x * x * (3 - 2 * x)).save(p)  # smoothstep, like a CSS ease
        out.append(p)
    return out


def countdown_frame(base: Path, left: int, total: int, label: str, folder: Path) -> Path:
    p = folder / f"think-{base.stem}-{left}of{total}.png"
    if p.exists():
        return p
    img = Image.open(base).convert("RGB")
    s = 3  # supersampling for smooth edges
    bw, bh = 400, 132
    badge = Image.new("RGBA", (bw * s, bh * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(badge)
    d.rounded_rectangle((0, 0, bw * s - 1, bh * s - 1), radius=26 * s, fill=(*BG, 245), outline=(*BLUE, 255), width=3 * s)
    cx, cy, r = 66 * s, bh * s // 2, 44 * s
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(217, 217, 212, 255), width=9 * s)
    if left:
        d.arc((cx - r, cy - r, cx + r, cy + r), -90, -90 + 360 * left / total, fill=(*BLUE, 255), width=9 * s)
    d.text((cx, cy), str(left), font=_font(40 * s, 600), fill=(*INK, 255), anchor="mm")
    d.text((128 * s, cy), label, font=_font(32 * s, 500), fill=(*INK, 255), anchor="lm")
    badge = badge.resize((bw, bh), Image.LANCZOS)
    img.paste(badge, (W - bw - 56, H - bh - 96), badge)
    img.save(p)
    return p


# --- timeline

def make_timeline(deck: str, lang: str, n: nmod.Narration, manifest: dict, voice: Voice, cfg: dict) -> Timeline:
    tl = Timeline(cfg["fps"], voice.sample_rate)
    frames_dir = course.out_dir(deck) / "frames"
    extra = course.out_dir(deck) / "pictures"
    extra.mkdir(parents=True, exist_ok=True)
    narrated = n.by_id()
    fade_n = max(1, round(cfg["fade_seconds"] * tl.fps))
    label = cfg["think_label"].get(lang, "Pause and think")
    t = 0.0
    total = len(manifest["slides"])
    for k, s in enumerate(manifest["slides"], 1):
        ns = narrated.get(s["id"])
        if ns is None:
            raise SystemExit(f"{deck} [{lang}]: no narration for {s['id']} (run check)")
        print(f"\rVOICE {deck} [{lang}] slide {k}/{total}", end="", flush=True)
        start = t
        if s["level"] < 2:  # title slide and sections (# headings) start chapters
            tl.chapters.append((t, s["title"]))
        pics = [frames_dir / f for f in s["frames"]]
        current = pics[0]
        tl.show(current, t)
        t += cfg["pause_before_slide"]
        for step, items in enumerate(ns.steps):
            if step:
                t = tl.frame(t) / tl.fps
                fades = fade_frames(pics[step - 1], pics[step], fade_n, extra)
                for i, f in enumerate(fades):
                    tl.show(f, t + i / tl.fps)
                current = pics[step]
                tl.show(current, t + len(fades) / tl.fps)
                t += cfg["pause_after_click"]
            first = True
            for item in items:
                if isinstance(item, nmod.Speech):
                    if not first:
                        t += cfg["pause_between_paragraphs"]
                    first = False
                    audio = voice.say(item.text)
                    t0 = tl.frame(t) / tl.fps  # voice starts on a frame boundary
                    tl.audio.append((round(t0 * tl.sr), audio))
                    dur = len(audio) / tl.sr
                    tl.cues += cues(speakcode.plain(item.text), t0, dur)
                    tl.speech_seconds += dur
                    tl.words += len(speakcode.plain(item.text).split())
                    t = t0 + dur
                elif isinstance(item, nmod.Silence):
                    t += item.seconds
                elif isinstance(item, nmod.Think):
                    secs = int(round(item.seconds or cfg["countdown_seconds"]))
                    t += 0.3
                    for left in range(secs, 0, -1):
                        tl.show(countdown_frame(current, left, secs, label, extra), t)
                        t += 1
                    tl.show(current, t)
                    t += 0.3
        t += cfg["pause_after_slide"]
        tl.slides[s["id"]] = [start, t - start]
    print()
    tl.finish(t)
    return tl


def cues(text: str, start: float, dur: float, max_chars: int = 84) -> list[Cue]:
    """Subtitles: sentences (long ones split), timed in proportion to their length."""
    parts = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        words, line = sent.split(), ""
        for w in words:
            if line and len(line) + 1 + len(w) > max_chars:
                parts.append(line)
                line = w
            else:
                line = f"{line} {w}".strip()
        if line:
            parts.append(line)
    total = sum(len(p) for p in parts) or 1
    out, t = [], start
    for p in parts:
        d = dur * len(p) / total
        out.append(Cue(t, t + d, p))
        t += d
    return out


# --- outputs

def ts(t: float, sep: str = ",") -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def clock(t: float) -> str:
    s = int(t)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def write_outputs(base: Path, tl: Timeline, deck: str, lang: str):
    """base: _video/<deck>.<lang>; writes base + .srt, .vtt, .chapters.txt, .timing.json"""
    def out(ext: str) -> Path:
        return base.parent / f"{base.name}{ext}"
    out(".srt").write_text(
        "".join(f"{i}\n{ts(c.start)} --> {ts(c.end)}\n{c.text}\n\n" for i, c in enumerate(tl.cues, 1)), encoding="utf-8")
    out(".vtt").write_text(
        "WEBVTT\n\n" + "".join(f"{ts(c.start, '.')} --> {ts(c.end, '.')}\n{c.text}\n\n" for c in tl.cues), encoding="utf-8")
    # YouTube: first chapter at 0:00, chapters at least 10 s apart
    kept: list[tuple[float, str]] = []
    for t, title in tl.chapters:
        if kept and t - kept[-1][0] < 10:
            continue
        kept.append((0.0 if not kept else t, title))
    out(".chapters.txt").write_text("".join(f"{clock(t)} {title}\n" for t, title in kept), encoding="utf-8")
    entry = {"id": "", "recording": f"generated {lang} {datetime.date.today().isoformat()}",
             "slides": {k: [int(v[0]), max(1, round(v[1]))] for k, v in tl.slides.items()}}
    out(".timing.json").write_text(json.dumps(entry, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    meta = [";FFMETADATA1", f"title={deck} ({lang})"]
    for i, (t, title) in enumerate(kept):
        end = kept[i + 1][0] if i + 1 < len(kept) else tl.end
        meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={round(t * 1000)}", f"END={round(end * 1000)}",
                 "title=" + re.sub(r"([=;#\\])", r"\\\1", title)]
    return "\n".join(meta) + "\n", kept


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if p.returncode:
        raise SystemExit(f"{Path(cmd[0]).name} failed:\n{p.stderr[-3000:]}")
    return p


def assemble(deck: str, lang: str, tl: Timeline, cfg: dict) -> Path:
    work = course.out_dir(deck) / lang
    work.mkdir(parents=True, exist_ok=True)
    out = Path("_video") / f"{deck}.{lang}.mp4"
    ffmpeg = course.find_tool("ffmpeg")

    # the voice track
    track = np.zeros(round(tl.end * tl.sr) + tl.sr, np.float32)
    for at, a in tl.audio:
        track[at:at + len(a)] += a[:max(0, len(track) - at)]
    voice = work / "voice.wav"
    sf.write(voice, track[:round(tl.end * tl.sr)], tl.sr, subtype="FLOAT")

    # pictures with their durations; durations are whole frames
    lines = ["ffconcat version 1.0"]
    for s in tl.shots:
        lines += [f"file '{s.image.resolve().as_posix()}'", f"duration {(s.end - s.start) / tl.fps:.6f}"]
    lines.append(f"file '{tl.shots[-1].image.resolve().as_posix()}'")
    concat = work / "pictures.ffconcat"
    concat.write_text("\n".join(lines) + "\n", encoding="utf-8")

    metadata, _ = write_outputs(Path("_video") / f"{deck}.{lang}", tl, deck, lang)
    meta = work / "chapters.ffmeta"
    meta.write_text(metadata, encoding="utf-8")

    # loudness in two passes: measure, then normalise linearly to -16 LUFS / -1 dBTP
    clean = f"{cfg['voice_filter']}," if cfg.get("voice_filter") else ""
    p = run([ffmpeg, "-hide_banner", "-i", str(voice), "-af", f"{clean}loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"])
    m = json.loads(p.stderr[p.stderr.rindex("{"):p.stderr.rindex("}") + 1])
    loudnorm = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
                f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    print(f"ENCODE {out} ({clock(tl.end)})")
    run([ffmpeg, "-hide_banner", "-y",
         "-f", "concat", "-safe", "0", "-i", str(concat),
         "-i", str(voice), "-i", str(meta),
         "-map", "0:v", "-map", "1:a", "-map_metadata", "2", "-map_chapters", "2",
         "-vf", f"fps={tl.fps},scale={W}:{H}:out_color_matrix=bt709:out_range=tv,format=yuv420p",
         "-c:v", "libx264", "-preset", cfg["preset"], "-crf", str(cfg["crf"]), "-tune", "stillimage",
         "-g", str(tl.fps * 5), "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
         "-af", f"{clean}{loudnorm},aresample=48000:resampler=soxr", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-t", f"{tl.end:.3f}", "-movflags", "+faststart", str(out)])
    return out


def remember_wpm(lang: str, cfg: dict, tl: Timeline):
    if tl.speech_seconds < 60:
        return
    p = Path("_video") / "wpm.json"
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    data[f"{lang}:{json.dumps(cfg['voices'][lang], sort_keys=True)}"] = round(tl.words / tl.speech_seconds * 60, 1)
    p.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


def build(decks: list[str], langs: list[str] | None, force: bool) -> int:
    cfg = course.load_config()
    for d in decks:
        for lang in langs or nmod.langs_of(d):
            if lang not in cfg["voices"]:
                raise SystemExit(f"No voice for {lang!r} in lecture-video.yml (voices.{lang})")
            errors = [f for f in check.check_deck(d, lang, cfg) if f.severity == check.ERROR]
            if errors and not force:
                print(f"VIDEO {d} [{lang}] - {len(errors)} narration error(s), see  lecture-video.ps1 {d} check  (or -Force)")
                return 2
        manifest = framesmod.capture(d, force)
        for lang in langs or nmod.langs_of(d):
            n = nmod.parse(d, lang)
            voice = Voice(lang, cfg["voices"][lang])
            tl = make_timeline(d, lang, n, manifest, voice, cfg)
            remember_wpm(lang, cfg, tl)
            if tl.end > cfg["max_minutes"] * 60:
                raise SystemExit(f"{d} [{lang}]: {clock(tl.end)} is longer than max_minutes {cfg['max_minutes']}: shorten the narration")
            out = assemble(d, lang, tl, cfg)
            print(f"VIDEO {out} - {clock(tl.end)}, {tl.words} words, {tl.words / max(tl.speech_seconds, 1) * 60:.0f} wpm; "
                  f"chapters, subtitles (.srt/.vtt) and slide times (.timing.json) next to it")
    return 0


SAMPLE = {
    "en": "Okay, here's the big question: how often does this loop actually run? Take a guess! "
          "The loop runs while `count < 5`, and `count++` adds one each time. "
          "Then we read `VisitorCount.in` with `Scanner.nextDouble()`, and print it with `System.out.println`. "
          "And when `c` reaches `Integer.MAX_VALUE`, it overflows. Silently!",
    "de": "Okay, jetzt die große Frage: Wie oft läuft diese Schleife eigentlich? Tippt mal! "
          "Die Schleife läuft, solange `count < 5` gilt, und `count++` erhöht den Zähler um eins. "
          "Dann lesen wir `VisitorCount.in` mit `Scanner.nextDouble()` und geben es mit `System.out.println` aus. "
          "Und wenn `c` den Wert `Integer.MAX_VALUE` erreicht, läuft es über. Ganz ohne Fehlermeldung!",
}


def sample(langs: list[str], text: str | None) -> int:
    """A code-heavy test paragraph with the configured voices: check a reference clip and settings in minutes."""
    cfg = course.load_config()
    folder = Path("_video") / "samples"
    folder.mkdir(parents=True, exist_ok=True)
    for lang in langs:
        if lang not in cfg["voices"]:
            raise SystemExit(f"No voice for {lang!r} in lecture-video.yml (voices.{lang})")
        vc = cfg["voices"][lang]
        v = Voice(lang, vc)
        audio = v.say(text or SAMPLE.get(lang, SAMPLE["en"]))
        f = folder / f"{lang}-{vc['engine']}.wav"
        sf.write(f, audio, v.sample_rate)
        if cfg.get("voice_filter"):  # as in the video
            raw = f.with_suffix(".raw.wav")
            f.replace(raw)
            run([course.find_tool("ffmpeg"), "-hide_banner", "-y", "-i", str(raw), "-af", cfg["voice_filter"], str(f)])
            raw.unlink()
        print(f"SAMPLE {f} ({len(audio) / v.sample_rate:.1f} s)")
    return 0
