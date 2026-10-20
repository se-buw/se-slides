"""Chatterbox Multilingual (local, both languages, expressive, slow on a CPU).

  ref: 15-25 s WAV of the voice to clone; default voice/ref-<lang>.wav. Without one, Chatterbox uses
       its built-in English voice, and other languages get an English accent.
  exaggeration 0.25-1.0: more energy; cfg_weight 0.2-0.6: lower is slower and carries less accent;
  temperature (0.8): variation; seed: the same take on every build.

Code words in German sentences come tagged as English ([en]count[de], tts.Voice): one take per
sentence, the same voice, English pronunciation for the code.
"""
from __future__ import annotations

import hashlib
import os
import re
import warnings
from pathlib import Path

import numpy as np

from . import Engine


def prepared_ref(path: Path) -> Path:
    """The clip as Chatterbox needs it: mono 24 kHz, silence trimmed, loudness normalised (cached)."""
    import librosa
    import soundfile as sf
    data = path.read_bytes()
    out = Path("_video/cache/ref") / f"{path.stem}-{hashlib.sha256(data).hexdigest()[:12]}.wav"
    if out.exists():
        return out
    audio, sr = librosa.load(str(path), sr=24000, mono=True)
    audio, _ = librosa.effects.trim(audio, top_db=35)
    seconds = len(audio) / sr
    if seconds < 8:
        raise SystemExit(f"{path}: only {seconds:.0f} s of speech; record 15-25 s")
    if seconds > 30:
        print(f"{path}: {seconds:.0f} s, only the first 25 s are used")
        audio = audio[:25 * sr]
    if np.max(np.abs(audio)) >= 0.999:
        print(f"{path}: the recording clips (too loud); record again with less gain for a cleaner voice")
    rms = float(np.sqrt(np.mean(audio ** 2)))
    audio = np.clip(audio * (0.1 / max(rms, 1e-6)), -0.98, 0.98)  # about -20 dBFS
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out, audio, sr)
    return out


def patient_repetition_check():
    """Chatterbox ends a take as soon as two speech tokens in a row are the same (a 40 ms frame
    repeated, e.g. in a pause at a comma), even when the text is not spoken yet: the sentence is
    cut off. Count repetitions only once the whole text is spoken, where they mean babbling."""
    from chatterbox.models.t3.inference.alignment_stream_analyzer import AlignmentStreamAnalyzer
    step = AlignmentStreamAnalyzer.step
    if getattr(step, "patient", False):
        return

    def patient(self, logits, next_token=None):
        if not self.complete:
            self.generated_tokens.clear()
        return step(self, logits, next_token)
    patient.patient = True
    AlignmentStreamAnalyzer.step = patient


_model = None


def model():
    """The model, loaded once per run and shared by both languages (3 GB, loading takes a while)."""
    global _model
    if _model is None:
        import torch
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        gpu = torch.cuda.is_available()  # NVIDIA, or AMD with a ROCm build (bootstrap.ps1 -Gpu)
        if gpu and torch.version.hip and os.name == "nt":
            torch.backends.cudnn.enabled = False  # MIOpen cannot compile its kernels on Windows
        print(f"Chatterbox on {torch.cuda.get_device_name(0) if gpu else 'the CPU'}")
        _model = ChatterboxMultilingualTTS.from_pretrained(device="cuda" if gpu else "cpu")
        _model.builtin = _model.conds  # the built-in English voice
        # generate() always allows 1000 speech tokens (40 s); a take that misses its end then babbles
        # on. Capped by the text's length in synth (25 tokens per second).
        _model.max_tokens = 1000
        inference = _model.t3.inference

        def capped(**kw):
            kw["max_new_tokens"] = min(kw.get("max_new_tokens") or 1000, _model.max_tokens)
            return inference(**kw)
        _model.t3.inference = capped
        patient_repetition_check()
    return _model


class Chatterbox(Engine):
    def __init__(self, lang, cfg):
        super().__init__(lang, cfg)
        warnings.filterwarnings("ignore")
        import torch
        self.torch = torch
        self.model = model()
        self.sample_rate = self.model.sr
        ref = Path(cfg["ref"]) if cfg.get("ref") else Path("voice") / f"ref-{lang}.wav"
        self.exaggeration = float(cfg.get("exaggeration", 0.6))
        if ref.exists():
            self.model.prepare_conditionals(str(prepared_ref(ref)), exaggeration=self.exaggeration)
            self.conds = self.model.conds
        elif cfg.get("ref"):
            raise SystemExit(f"voices.{lang}.ref: {ref} not found")
        else:
            print(f"Chatterbox [{lang}]: no {ref}, using the built-in English voice")
            self.conds = self.model.builtin

    def synth(self, text, lang):
        # Chatterbox sometimes babbles on (mostly on short inputs): a take far longer than the text
        # can be is made again with the next seed; the shortest take wins.
        spoken = re.sub(r"\[\w\w\]", "", text)  # without the language tags
        limit = 2.5 + len(spoken) / 6  # s; speech is about 13-15 characters per second
        self.model.max_tokens = int(25 * (limit + 1))
        self.model.conds = self.conds  # the voice of this language (the model is shared)
        seed = int(self.cfg.get("seed", 0))
        takes = []
        for attempt in range(3):
            if "seed" in self.cfg or attempt:
                self.torch.manual_seed(seed + attempt)
            wav = self.model.generate(
                text, language_id=lang, exaggeration=self.exaggeration,
                cfg_weight=float(self.cfg.get("cfg_weight", 0.5)), temperature=float(self.cfg.get("temperature", 0.8)))
            audio = wav.squeeze(0).cpu().numpy().astype(np.float32)
            takes.append(audio)
            if len(audio) / self.sample_rate <= limit:
                break
            print(f"\nChatterbox [{lang}]: {len(audio) / self.sample_rate:.1f} s for {text!r}, speaking it again")
        return min(takes, key=len)
