"""Qwen3-TTS (local, GPU recommended; 10 languages). Clones voices.<lang>.ref, default
voice/ref-<lang>.wav, from its speaker embedding alone: no transcript of the clip needed.

  model: Qwen/Qwen3-TTS-12Hz-1.7B-Base (default; -0.6B-Base is no faster on a Radeon 890M);
  seed: the same take on every build; dtype: bf16 (default on a GPU) or fp32.

qwen-tts and Chatterbox pin different transformers versions, so Qwen runs in a worker process with
its own environment (bootstrap.ps1 -Qwen; lecture-video.ps1 passes its python as LV_QWEN_PYTHON).
It cannot switch languages within a take: code words are respelled with the lexicon of the narration's
language (lectures/pronunciation.yml), as for Piper. About 1.8x real time on a Radeon 890M.
"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
from pathlib import Path

import numpy as np

from . import Engine
from .ref import ref_path

LANGUAGE = {"de": "German", "en": "English", "fr": "French", "es": "Spanish", "it": "Italian",
            "pt": "Portuguese", "ru": "Russian", "zh": "Chinese", "ja": "Japanese", "ko": "Korean"}
FRAMES_PER_SECOND = 12.5  # Qwen3-TTS-12Hz: one frame is 80 ms of audio


class Qwen(Engine):
    def __init__(self, lang, cfg):
        super().__init__(lang, cfg)
        if lang not in LANGUAGE:
            raise SystemExit(f"voices.{lang}: Qwen3-TTS does not speak {lang!r} (known: {', '.join(LANGUAGE)})")
        python = os.environ.get("LV_QWEN_PYTHON")
        if not python or not Path(python).exists():
            raise SystemExit(f"voices.{lang}: Qwen needs its own environment: run tools/bootstrap.ps1 -Qwen once")
        ref = ref_path(lang, cfg)
        if not ref.exists():
            raise SystemExit(f"voices.{lang}: Qwen clones a voice and needs {ref} (15-25 s, see the README)")
        self.cache = Path("_video/cache/qwen")
        self.cache.mkdir(parents=True, exist_ok=True)
        self.log = open(self.cache / f"worker-{lang}.log", "w", encoding="utf-8")
        model = cfg.get("model", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")
        self.proc = subprocess.Popen(
            [python, "-I", str(Path(__file__).with_name("qwen_worker.py")), model, str(ref), LANGUAGE[lang],
             cfg.get("dtype", "bf16")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True, encoding="utf-8")
        atexit.register(self.close)
        ready = self.receive()
        print(f"Qwen [{lang}] on {ready['device']}")

    def receive(self) -> dict:
        line = self.proc.stdout.readline()
        if not line:
            self.log.flush()
            tail = (self.cache / f"worker-{self.lang}.log").read_text(encoding="utf-8", errors="replace")[-3000:]
            raise SystemExit(f"Qwen [{self.lang}]: the worker stopped:\n{tail}")
        return json.loads(line)

    def take(self, text, seed, max_new_tokens) -> np.ndarray:
        import soundfile as sf
        out = self.cache / f"take-{self.lang}.wav"
        self.proc.stdin.write(json.dumps({"text": text, "seed": seed, "max_new_tokens": max_new_tokens,
                                          "out": str(out.resolve())}) + "\n")
        self.proc.stdin.flush()
        r = self.receive()
        if "error" in r:
            raise SystemExit(f"Qwen [{self.lang}]: {r['error']} for {text!r}")
        audio, sr = sf.read(out, dtype="float32")
        if sr != self.sample_rate:
            raise SystemExit(f"Qwen [{self.lang}]: {sr} Hz, expected {self.sample_rate}")
        return audio

    def synth(self, text, lang):
        # as for Chatterbox: a take far longer than the text can be is made again with the next seed
        limit = 2.5 + len(text) / 6  # s; speech is about 13-15 characters per second
        seed = int(self.cfg.get("seed", 0))
        takes = []
        for attempt in range(3):
            audio = self.take(text, seed + attempt, int(FRAMES_PER_SECOND * (limit + 1)))
            takes.append(audio)
            if len(audio) / self.sample_rate <= limit:
                break
            print(f"\nQwen [{lang}]: {len(audio) / self.sample_rate:.1f} s for {text!r}, speaking it again")
        return min(takes, key=len)

    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.log.close()
