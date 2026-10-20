"""Piper (local, CPU, fast, many languages): voice de_DE-thorsten-high, en_US-ryan-high, ...
Voices with several speakers (de_DE-thorsten_emotional-medium) take `speaker` (a name or number).
length_scale < 1 speaks faster. Voices are downloaded once into the tool cache.
Piper cannot switch languages: code words are respelled with the lexicon (lectures/pronunciation.yml)."""
from __future__ import annotations

import subprocess
import sys

import numpy as np

from . import Engine
from ..course import tool_cache


class Piper(Engine):
    def __init__(self, lang, cfg):
        super().__init__(lang, cfg)
        from piper import PiperVoice, SynthesisConfig
        name = cfg.get("voice", "de_DE-thorsten-high" if lang == "de" else "en_US-ryan-high")
        folder = tool_cache() / "lecture-video" / "voices"
        model = folder / f"{name}.onnx"
        if not model.exists():
            folder.mkdir(parents=True, exist_ok=True)
            subprocess.run([sys.executable, "-m", "piper.download_voices", name, "--data-dir", str(folder)], check=True)
        self.voice = PiperVoice.load(str(model))
        self.sample_rate = self.voice.config.sample_rate
        speaker = cfg.get("speaker")
        if isinstance(speaker, str) and not speaker.isdigit():
            ids = self.voice.config.speaker_id_map or {}
            if speaker not in ids:
                raise SystemExit(f"voices.{lang}.speaker: {speaker!r} not in {name} (speakers: {', '.join(ids) or 'none'})")
            speaker = ids[speaker]
        self.config = SynthesisConfig(speaker_id=int(speaker) if speaker is not None else None,
                                      length_scale=float(cfg.get("length_scale", 1.0)),
                                      noise_scale=float(cfg.get("noise_scale", 0.667)),
                                      noise_w_scale=float(cfg.get("noise_w_scale", 0.8)))

    def synth(self, text, lang):
        parts = [c.audio_float_array for c in self.voice.synthesize(text, syn_config=self.config)]
        return np.concatenate(parts) if parts else np.zeros(0, np.float32)
