"""Speech engines behind one interface. Swap an engine in lecture-video.yml, no code changes:

    voices:
      en: { engine: chatterbox, ref: voice/ref-en.wav, exaggeration: 0.6 }
      de: { engine: piper, voice: de_DE-thorsten-high }

An engine turns text in one language into mono float32 samples at its sample_rate. Voice adds what
all engines share: sentences, code spans (speakcode.py), the lexicon and a cache per piece in
_video/cache/tts, so editing one sentence synthesises only that sentence.

Code spans are English. Chatterbox says them in English inside a German sentence: the sentence stays
one piece, the code is tagged with Chatterbox's language tokens ([en]count[de]). For the other
engines (and with `code: respell`) code words are respelled with the lexicon of the narration's
language (lectures/pronunciation.yml), e.g. for Piper.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import soundfile as sf

from .. import speakcode

ENGINES = ("chatterbox", "piper", "openai", "elevenlabs", "azure")
INLINE = {"chatterbox"}  # language switches inside one text: [en]word[de]
REVISION = {"chatterbox": 2}  # 2: sentences no longer cut off by the repetition check
SENTENCE_PAUSE = 0.22    # s between sentences
MIN_SENTENCE = 30        # characters: shorter sentences are spoken together with the one before


class Engine:
    sample_rate: int = 24000

    def __init__(self, lang: str, cfg: dict):
        self.lang = lang
        self.cfg = cfg

    def synth(self, text: str, lang: str) -> np.ndarray:
        raise NotImplementedError


def create(lang: str, cfg: dict) -> Engine:
    name = cfg.get("engine")
    if name == "piper":
        from .piper import Piper as E
    elif name == "chatterbox":
        from .chatterbox import Chatterbox as E
    elif name == "openai":
        from .cloud import OpenAI as E
    elif name == "elevenlabs":
        from .cloud import ElevenLabs as E
    elif name == "azure":
        from .cloud import Azure as E
    else:
        raise SystemExit(f"voices.{lang}: unknown engine {name!r} (known: {', '.join(ENGINES)})")
    return E(lang, cfg)


def sentences(text: str, max_chars: int = 280) -> list[str]:
    """Sentences, long ones split at commas; never inside a code span."""
    protected = speakcode.CODE.sub(lambda m: m.group(0).replace(". ", ".\0").replace(", ", ",\0"), text.strip())
    out = []
    for s in re.split(r"(?<=[.!?])\s+", protected):
        while len(s) > max_chars:
            cut = s.rfind(", ", 0, max_chars)
            cut = cut + 1 if cut > 0 else max_chars
            out.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            out.append(s)
    # very short inputs make some engines (Chatterbox) babble on: "Silently!" goes with the sentence before
    merged: list[str] = []
    for s in out:
        if merged and (len(s) < MIN_SENTENCE or len(merged[-1]) < MIN_SENTENCE):
            merged[-1] += " " + s
        else:
            merged.append(s)
    return [s.replace("\0", " ") for s in merged]


def pronunciation(section: str) -> dict[str, str]:
    """A section of lectures/pronunciation.yml, e.g. "de" or "de-code"."""
    p = Path("lectures/pronunciation.yml")
    if not p.exists():
        return {}
    import yaml
    # BaseLoader: every word stays a string (true, false, on, no are words here, not booleans)
    return (yaml.load(p.read_text(encoding="utf-8"), Loader=yaml.BaseLoader) or {}).get(section) or {}


class Lexicon:
    """lectures/pronunciation.yml: per language, words as the voice should say them."""

    def __init__(self, lang: str):
        self.rules: list[tuple[re.Pattern, str]] = []
        words = pronunciation(lang)
        for k in sorted(words, key=len, reverse=True):
            self.rules.append((re.compile(r"(?<![\w.])" + re.escape(str(k)) + r"(?![\w])"), str(words[k])))

    def apply(self, text: str) -> str:
        for pattern, say in self.rules:
            text = pattern.sub(say, text)
        return text


class Voice:
    """Engine + code spans + lexicon + cache for one language."""

    def __init__(self, lang: str, cfg: dict, cache: Path = Path("_video/cache/tts")):
        self.lang, self.cfg = lang, cfg
        self.lexicons: dict[str, Lexicon] = {}
        self.cache = cache / lang
        self.cache.mkdir(parents=True, exist_ok=True)
        self._engine: Engine | None = None
        self.key = json.dumps(cfg, sort_keys=True)
        if cfg.get("engine") in REVISION:  # takes made by an older engine setup are spoken again
            self.key += f"\nrev {REVISION[cfg['engine']]}"
        # a new recording of the reference voice must not reuse sentences spoken with the old one
        ref = Path(cfg["ref"]) if cfg.get("ref") else Path("voice") / f"ref-{lang}.wav"
        if cfg.get("engine") == "chatterbox" and ref.exists():
            self.key += "\n" + hashlib.sha256(ref.read_bytes()).hexdigest()
        self.inline = cfg.get("engine") in INLINE and cfg.get("code", "inline") == "inline"
        # code words that sound wrong even in English, said as words of this language (de-code: Integer)
        self.native = pronunciation(f"{lang}-code")
        # the sample rate is remembered, so a build from the cache never loads the engine
        self.meta = self.cache / f"{hashlib.sha256(self.key.encode()).hexdigest()[:16]}.json"

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = create(self.lang, self.cfg)
            self.meta.write_text(json.dumps({"voice": self.cfg, "sample_rate": self._engine.sample_rate}), encoding="utf-8")
        return self._engine

    @property
    def sample_rate(self) -> int:
        if self._engine is None and self.meta.exists():
            return json.loads(self.meta.read_text(encoding="utf-8"))["sample_rate"]
        return self.engine.sample_rate

    def lexicon(self, lang: str) -> Lexicon:
        if lang not in self.lexicons:
            self.lexicons[lang] = Lexicon(lang)
        return self.lexicons[lang]

    def say(self, text: str) -> np.ndarray:
        gap = np.zeros(int(SENTENCE_PAUSE * self.sample_rate), np.float32)
        out = []
        for sent in sentences(text):
            pieces = speakcode.runs(sent, self.lang, self.native)
            if self.inline:
                words = []
                for k, (t, l) in enumerate(pieces):
                    t = self.lexicon(l).apply(t)
                    if l != self.lang:
                        back = f"[{self.lang}]" if k + 1 < len(pieces) else ""
                        t = f"[{l}]{t}{back}"
                    words.append(t)
                text = " ".join(words)
            else:
                # code words are respelled with the lexicon of the narration's language
                text = self.lexicon(self.lang).apply(" ".join(t for t, _ in pieces))
            out += [self.piece(text, self.lang), gap]
        return np.concatenate(out[:-1]) if out else np.zeros(0, np.float32)

    def piece(self, text: str, lang: str) -> np.ndarray:
        h = hashlib.sha256(f"{self.key}\n{lang}\n{text}".encode()).hexdigest()[:24]
        f = self.cache / f"{h}.wav"
        if f.exists():
            return sf.read(f, dtype="float32")[0]
        audio = np.asarray(self.engine.synth(text, lang), dtype=np.float32).reshape(-1)
        audio = trim(audio, self.sample_rate)
        sf.write(f, audio, self.sample_rate, subtype="FLOAT")
        return audio


def trim(audio: np.ndarray, sr: int, threshold: float = 0.01, keep: float = 0.04) -> np.ndarray:
    """Engines add uneven silence at both ends; the timeline sets the pauses itself."""
    loud = np.nonzero(np.abs(audio) > threshold)[0]
    if not len(loud):
        return audio
    k = int(keep * sr)
    return audio[max(0, loud[0] - k):min(len(audio), loud[-1] + k)]
