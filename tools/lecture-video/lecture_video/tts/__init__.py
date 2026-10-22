"""Speech engines behind one interface. Swap an engine in lecture-video.yml, no code changes:

    voices:
      en: { engine: chatterbox, ref: voice/ref-en.wav, exaggeration: 0.6 }
      de: { engine: qwen, seed: 7 }       # or { engine: piper, voice: de_DE-thorsten-high }

An engine turns text in one language into mono float32 samples at its sample_rate. Voice adds what
all engines share: sentences, code spans (speakcode.py), the lexicon and a cache per piece in
_video/cache/tts, so editing one sentence synthesises only that sentence.

Code spans are English. Chatterbox says them in English inside a German sentence: the sentence stays
one piece, the code is tagged with Chatterbox's language tokens ([en]count[de]). For the other
engines (and with `code: respell`) code words are respelled with the lexicon of the narration's
language (lectures/pronunciation.yml), e.g. for Piper.

The cache keeps each take as the engine made it, with where its text ended (<hash>.json): the cut
(cut_tail, trim) is made on every read, so changing it needs no new synthesis. Chatterbox's speech
tokens are kept under a key without the reference clip (tokens/): with revoice, a new clip gives the
takes its timbre without speaking them again (rhythm and intonation stay those of the old clip).
A new VOCODER revision (e.g. S3Gen settings) makes the audio again from the tokens, without T3.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .. import speakcode
from .ref import ref_path

ENGINES = ("chatterbox", "qwen", "piper", "openai", "elevenlabs", "azure")
CLONING = {"chatterbox", "qwen"}  # clone voice/ref-<lang>.wav: a new recording speaks everything again
BREATH = {"qwen"}  # takes start with a breath before the speech: cut_head
INLINE = {"chatterbox"}  # language switches inside one text: [en]word[de]
REVISION = {"chatterbox": 3}  # 2: sentences no longer cut off by the repetition check; 3: uncut takes, end of text, tokens
# the step from tokens to sound: a new revision makes the audio again from the cached tokens, without T3
VOCODER = {"chatterbox": 3}  # 2: S3Gen with 6 flow steps instead of 10; 3: its prompt ends at a pause
SENTENCE_PAUSE = 0.22    # s between sentences
MIN_SENTENCE = 30        # characters: shorter sentences are spoken together with the one before


@dataclass
class Take:
    audio: np.ndarray
    end: float | None = None            # s: where the text was spoken; after it the engine may babble
    tokens: np.ndarray | None = None    # Chatterbox's speech tokens, for revoice


class Engine:
    sample_rate: int = 24000

    def __init__(self, lang: str, cfg: dict):
        self.lang = lang
        self.cfg = cfg

    def synth(self, text: str, lang: str) -> np.ndarray | Take:
        raise NotImplementedError


def create(lang: str, cfg: dict) -> Engine:
    name = cfg.get("engine")
    if name == "piper":
        from .piper import Piper as E
    elif name == "chatterbox":
        from .chatterbox import Chatterbox as E
    elif name == "qwen":
        from .qwen import Qwen as E
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

    def __init__(self, lang: str, cfg: dict, cache: Path = Path("_video/cache/tts"), revoice: bool = False):
        self.lang, self.cfg, self.revoice = lang, cfg, revoice
        self.lexicons: dict[str, Lexicon] = {}
        self.cache = cache / lang
        self.cache.mkdir(parents=True, exist_ok=True)
        self._engine: Engine | None = None
        self.key = json.dumps(cfg, sort_keys=True)
        # tokens outlive a new recording of the reference voice, under the same name or another (revoice)
        self.token_key = json.dumps({k: v for k, v in cfg.items() if k != "ref"}, sort_keys=True)
        if cfg.get("engine") in REVISION:  # takes made by an older engine setup are spoken again
            self.key += f"\nrev {REVISION[cfg['engine']]}"
            self.token_key += f"\nrev {REVISION[cfg['engine']]}"
        if cfg.get("engine") in VOCODER and VOCODER[cfg["engine"]] > 1:
            self.key += f"\nvocoder {VOCODER[cfg['engine']]}"
        # a new recording of the reference voice must not reuse sentences spoken with the old one
        ref = ref_path(lang, cfg)
        self.ref = ""
        if cfg.get("engine") in CLONING and ref.exists():
            self.ref = hashlib.sha256(ref.read_bytes()).hexdigest()
            self.key += "\n" + self.ref
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
        f, meta = self.cache / f"{h}.wav", self.cache / f"{h}.json"
        if f.exists():
            end = json.loads(meta.read_text(encoding="utf-8"))["end"] if meta.exists() else None
            return self.finish(sf.read(f, dtype="float32")[0], end)
        t = hashlib.sha256(f"{self.token_key}\n{lang}\n{text}".encode()).hexdigest()[:24]
        tokens = self.cache / "tokens" / f"{t}.npz"
        z = np.load(tokens) if tokens.exists() else None
        # tokens of the same reference clip (only the vocoder changed), or of another one with revoice;
        # a take without an end (its alignment lost the text) is spoken again, with the retries of synth
        if (z is not None and z["end"] >= 0 and (self.revoice or str(z["ref"]) == self.ref)
                and hasattr(self.engine, "revoice")):
            take = Take(self.engine.revoice(z["tokens"]), float(z["end"]), z["tokens"])
        else:
            take = self.engine.synth(text, lang)
            take = take if isinstance(take, Take) else Take(take)
        audio = np.asarray(take.audio, dtype=np.float32).reshape(-1)
        sf.write(f, audio, self.sample_rate, subtype="FLOAT")
        if take.end is not None:
            meta.write_text(json.dumps({"end": take.end}), encoding="utf-8")
        if take.tokens is not None:
            tokens.parent.mkdir(exist_ok=True)
            np.savez(tokens, tokens=np.asarray(take.tokens, np.int16), ref=self.ref,
                     end=take.end if take.end is not None else -1.0)
        return self.finish(audio, take.end)

    def finish(self, audio: np.ndarray, end: float | None) -> np.ndarray:
        if self.cfg.get("engine") in BREATH:
            audio = cut_head(audio, self.sample_rate)
        return trim(cut_tail(audio, self.sample_rate, end), self.sample_rate)


def fade(audio: np.ndarray, sr: int, start: float = 0.0, stop: float = 0.0) -> np.ndarray:
    """Raised-cosine fade-in over `start` s and fade-out over `stop` s: no click where a take is cut."""
    audio = audio.copy()
    for seconds, out in ((start, False), (stop, True)):
        n = min(int(seconds * sr), len(audio))
        if n:
            ramp = ((1 - np.cos(np.linspace(0, np.pi, n))) / 2).astype(np.float32)
            if out:
                audio[-n:] *= ramp[::-1]
            else:
                audio[:n] *= ramp
    return audio


def cut_tail(audio: np.ndarray, sr: int, end: float | None, quiet_db: float = -40, pause: float = 0.12,
             keep: float = 0.06, babble: float = 0.4) -> np.ndarray:
    """Chatterbox goes on after the text (a breath, the start of a new word) until it is stopped.
    Cut at the first pause after `end`, where the text was spoken; without a pause, `babble` s after it."""
    if end is None:
        return audio
    start, n = int(end * sr), int(0.01 * sr)
    tail = audio[start:]
    frames = len(tail) // n
    rms = np.sqrt(np.mean(tail[:frames * n].reshape(frames, n) ** 2, axis=1)) if frames else np.zeros(0)
    quiet, need, run, cut = rms < 10 ** (quiet_db / 20), round(pause / 0.01), 0, None
    for i, q in enumerate(quiet):
        run = run + 1 if q else 0
        if run == need:
            cut = start + (i + 1 - need) * n + int(keep * sr)
            break
    if cut is None:
        if len(tail) <= int((babble + 0.1) * sr):
            return audio
        cut = start + int(babble * sr)
    return fade(audio[:cut], sr, stop=0.02)


def cut_head(audio: np.ndarray, sr: int, quiet_db: float = -50, loud_db: float = -30, within: float = 0.8) -> np.ndarray:
    """Qwen starts every take with about 300 ms of breath (-43 dB, peaks above trim's threshold), a
    short silence, then the speech: cut at the last frame below `quiet_db` before the first one above
    `loud_db`, if that is within `within` s. A take that starts speaking at once is not touched."""
    n = int(0.01 * sr)
    frames = min(len(audio), int(within * sr)) // n
    rms = 20 * np.log10(np.sqrt(np.mean(audio[:frames * n].reshape(frames, n) ** 2, axis=1)) + 1e-9)
    loud = np.flatnonzero(rms > loud_db)
    if not len(loud):
        return audio
    quiet = np.flatnonzero(rms[:loud[0]] < quiet_db)
    return audio[quiet[-1] * n:] if len(quiet) else audio


def trim(audio: np.ndarray, sr: int, threshold: float = 0.01, keep: float = 0.04) -> np.ndarray:
    """Engines add uneven silence at both ends; the timeline sets the pauses itself."""
    loud = np.nonzero(np.abs(audio) > threshold)[0]
    if not len(loud):
        return audio
    k = int(keep * sr)
    return fade(audio[max(0, loud[0] - k):min(len(audio), loud[-1] + k)], sr, 0.01, 0.01)
