"""The course folder (current directory): configuration, decks, tool cache."""
from __future__ import annotations

import copy
import os
import re
import shutil
from pathlib import Path

CONFIG = Path("lecture-video.yml")

DEFAULTS = {
    "max_minutes": 90,             # hard limit: the build fails above it
    "target_minutes": 80,          # drafting budget: check reports decks above it
    "countdown_seconds": 8,        # [think] without a number
    "fade_seconds": 0.4,           # fragment fade at [click]
    "pause_before_slide": 0.3,     # silence on a new slide before the voice starts
    "pause_after_slide": 0.6,      # silence after the last sentence of a slide
    "pause_after_click": 0.15,     # silence after a [click] before the voice goes on
    "pause_between_paragraphs": 0.35,
    # ffmpeg filters on the voice before the loudness normalisation; "" for none. Chatterbox leaves a
    # noise floor in the pauses of a take (about 45 dB below the speech): rumble off, then noise
    # reduction, then a soft gate that lowers the pauses by 30 dB.
    "voice_filter": "highpass=f=70,afftdn=nr=12:nf=-50:tn=1,agate=threshold=0.012:ratio=4:range=0.03:attack=5:release=200:knee=4",
    "fps": 30,
    "crf": 16,
    "preset": "slow",
    "words_per_minute": {"en": 155, "de": 135},  # estimate before any audio exists
    "think_label": {"en": "Pause and think", "de": "Kurz nachdenken"},
    "voices": {
        "en": {"engine": "chatterbox", "exaggeration": 0.6, "cfg_weight": 0.4},
        "de": {"engine": "chatterbox", "exaggeration": 0.6, "cfg_weight": 0.4},
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k != "voices":
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _mini_yaml(text: str) -> dict:
    """Top-level scalars and one level of nested scalars: enough for `check` without PyYAML."""
    out: dict = {}
    current = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        m = re.match(r"^(\s*)([\w-]+):\s*(.*)$", line)
        if not m:
            continue
        indent, key, value = m.groups()
        if not indent:
            if value:
                out[key] = _scalar(value)
                current = None
            else:
                current = out.setdefault(key, {})
        elif current is not None and value and not value.startswith("{"):
            current[key] = _scalar(value)
    return out


def _scalar(v: str):
    v = v.strip().strip('"').strip("'")
    try:
        return float(v) if "." in v else int(v)
    except ValueError:
        return v


def load_config() -> dict:
    if not CONFIG.exists():
        return copy.deepcopy(DEFAULTS)
    text = CONFIG.read_text(encoding="utf-8")
    try:
        import yaml  # in the video environment; check also runs without it
        data = yaml.safe_load(text) or {}
    except ImportError:
        data = _mini_yaml(text)
        data.pop("voices", None)
    return _merge(DEFAULTS, data)


def all_decks() -> list[str]:
    return sorted(p.stem for p in Path("lectures").glob("*.qmd") if p.stem[:1].isdigit())


def resolve(names: list[str]) -> list[str]:
    """Lecture names as build.ps1 takes them: 05 or 05-loops; none: all decks with narration."""
    decks = all_decks()
    if not names:
        return [d for d in decks if list(Path("lectures").glob(f"{d}.narration.*.md"))]
    out = []
    for n in names:
        hit = [d for d in decks if d == n or d.startswith(n + "-")]
        if not hit:
            raise SystemExit(f"No lecture matches '{n}'")
        out += hit
    return out


def tool_cache() -> Path:
    return Path(os.environ.get("SE_SLIDES_HOME") or Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "se-slides")


def find_tool(name: str) -> str:
    """ffmpeg/ffprobe: the bootstrap copy, otherwise PATH."""
    exe = name + (".exe" if os.name == "nt" else "")
    cached = tool_cache() / "ffmpeg" / "bin" / exe
    if cached.exists():
        return str(cached)
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"{name} not found. Run _extensions/se-slides/tools/bootstrap.ps1 once.")
    return found


def find_browser() -> str:
    """Same order as Find-Browser in tools/build.ps1."""
    if os.environ.get("COURSE_BROWSER"):
        return os.environ["COURSE_BROWSER"]
    shell = tool_cache() / "chrome-headless-shell" / ("chrome-headless-shell.exe" if os.name == "nt" else "chrome-headless-shell")
    if shell.exists():
        return str(shell)
    for p in (Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
              Path(os.environ.get("ProgramFiles(x86)", "")) / "Google/Chrome/Application/chrome.exe",
              Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
              Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe"):
        if p.exists():
            return str(p)
    for n in ("chromium", "google-chrome", "chromium-browser"):
        if shutil.which(n):
            return shutil.which(n)
    raise SystemExit("No browser for the video frames. Run tools/bootstrap.ps1 or set COURSE_BROWSER.")


def out_dir(deck: str) -> Path:
    return Path("_video") / deck
