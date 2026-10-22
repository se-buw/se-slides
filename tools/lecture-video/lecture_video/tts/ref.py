"""The reference clip of a cloned voice (Chatterbox, Qwen): voices.<lang>.ref, default voice/ref-<lang>.wav.
Only numpy, soundfile and librosa: the Qwen worker imports this from its own environment."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np


def ref_path(lang: str, cfg: dict) -> Path:
    return Path(cfg["ref"]) if cfg.get("ref") else Path("voice") / f"ref-{lang}.wav"


def prepared_ref(path: Path) -> Path:
    """The clip as the engines need it: mono 24 kHz, silence trimmed, loudness normalised (cached)."""
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


def last_pause(audio: np.ndarray, sr: int, before: float, pause: float = 0.15, quiet_db: float = -45) -> int:
    """Samples up to the last pause (>= `pause` s of 10 ms frames below `quiet_db`) that starts
    within the first `before` s; `before` s if there is none. A clip cut there ends in silence."""
    n = int(0.01 * sr)
    frames = min(len(audio), int(before * sr)) // n
    rms = np.sqrt(np.mean(audio[:frames * n].reshape(frames, n) ** 2, axis=1))
    quiet = rms < 10 ** (quiet_db / 20)
    need, run, cut = round(pause / 0.01), 0, None
    for i in range(frames):
        run = run + 1 if quiet[i] else 0
        if run == need and i + 1 - need >= 100:  # not the silence at the start of the clip
            cut = (i + 1 - need) * n + n * 5  # 50 ms into the pause
    return cut if cut else min(len(audio), int(before * sr))
