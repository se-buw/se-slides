"""Cloud engines: plain HTTPS, no packages. The text is sent to the provider; keys from the environment.

  openai:     OPENAI_API_KEY      { engine: openai, model: gpt-4o-mini-tts, voice: ash, instructions: "Energetic ..." }
  elevenlabs: ELEVENLABS_API_KEY  { engine: elevenlabs, voice_id: "...", model: eleven_multilingual_v2, style: 0.4 }
  azure:      AZURE_SPEECH_KEY, AZURE_SPEECH_REGION
              { engine: azure, voice: de-DE-ConradNeural, style: cheerful, rate: "+5%" }
"""
from __future__ import annotations

import io
import json
import os
import urllib.request
from xml.sax.saxutils import escape

import numpy as np
import soundfile as sf

from . import Engine, sentences


def _key(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"{name} is not set")
    return v


def _post(url: str, body: bytes, headers: dict) -> bytes:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


class OpenAI(Engine):
    sample_rate = 24000

    def synth(self, text, lang):
        out = []
        for chunk in sentences(text, 3500):
            body = {"model": self.cfg.get("model", "gpt-4o-mini-tts"), "voice": self.cfg.get("voice", "ash"),
                    "input": chunk, "response_format": "pcm"}
            if self.cfg.get("instructions"):
                body["instructions"] = self.cfg["instructions"]
            pcm = _post("https://api.openai.com/v1/audio/speech", json.dumps(body).encode(),
                        {"Authorization": f"Bearer {_key('OPENAI_API_KEY')}", "Content-Type": "application/json"})
            out.append(np.frombuffer(pcm, "<i2").astype(np.float32) / 32768)
        return np.concatenate(out)


class ElevenLabs(Engine):
    sample_rate = 44100

    def synth(self, text, lang):
        body = {"text": text, "model_id": self.cfg.get("model", "eleven_multilingual_v2"),
                "language_code": self.lang,
                "voice_settings": {"stability": float(self.cfg.get("stability", 0.4)),
                                   "similarity_boost": float(self.cfg.get("similarity_boost", 0.75)),
                                   "style": float(self.cfg.get("style", 0.4))}}
        pcm = _post(f"https://api.elevenlabs.io/v1/text-to-speech/{self.cfg['voice_id']}?output_format=pcm_44100",
                    json.dumps(body).encode(), {"xi-api-key": _key("ELEVENLABS_API_KEY"), "Content-Type": "application/json"})
        return np.frombuffer(pcm, "<i2").astype(np.float32) / 32768


class Azure(Engine):
    sample_rate = 24000

    def synth(self, text, lang):
        voice = self.cfg.get("voice", "de-DE-ConradNeural" if self.lang == "de" else "en-US-AndrewMultilingualNeural")
        inner = f'<prosody rate="{self.cfg.get("rate", "+0%")}">{escape(text)}</prosody>'
        if self.cfg.get("style"):
            inner = f'<mstts:express-as style="{self.cfg["style"]}">{inner}</mstts:express-as>'
        ssml = (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="https://www.w3.org/2001/mstts" '
                f'xml:lang="{self.lang}"><voice name="{voice}">{inner}</voice></speak>')
        region = _key("AZURE_SPEECH_REGION")
        wav = _post(f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1", ssml.encode(),
                    {"Ocp-Apim-Subscription-Key": _key("AZURE_SPEECH_KEY"), "Content-Type": "application/ssml+xml",
                     "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm", "User-Agent": "se-slides-lecture-video"})
        audio, _ = sf.read(io.BytesIO(wav), dtype="float32")
        return audio
