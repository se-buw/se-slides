"""Qwen3-TTS in its own environment (qwen-tts pins transformers 4.57, Chatterbox 5.2). tts/qwen.py
starts it once per voice and sends one JSON line per take; it answers with one JSON line and writes
the audio as a WAV file. Anything else it prints goes to stderr.

    python -I qwen_worker.py <model> <reference clip> <language> <dtype>

  request  {"text": ..., "seed": 7, "max_new_tokens": 300, "out": "<wav path>"}
  reply    {"sr": 24000}  or  {"error": "..."}
"""
import importlib.util
import json
import os
import sys
import warnings
from pathlib import Path


def main():
    model_id, ref, language, dtype = sys.argv[1:5]
    protocol, sys.stdout = sys.stdout, sys.stderr  # the libraries' prints must not reach the protocol
    warnings.filterwarnings("ignore")
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    # ref.py alone, not the lecture_video package (its imports are not in this environment)
    spec = importlib.util.spec_from_file_location("ref", Path(__file__).with_name("ref.py"))
    refmod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(refmod)
    clip = refmod.prepared_ref(Path(ref))

    gpu = torch.cuda.is_available()
    if gpu and torch.version.hip and os.name == "nt":
        # MIOpen lacks workspace for the speech decoder's convolutions on Windows: 2.5x real time with
        # it, 1.8x without (Radeon 890M), the same audio
        torch.backends.cudnn.enabled = False
    dt ={"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[dtype if gpu else "fp32"]
    model = Qwen3TTSModel.from_pretrained(model_id, device_map="cuda:0" if gpu else "cpu", dtype=dt,
                                          attn_implementation="sdpa")
    # the speaker embedding of the clip only: no transcript needed; with one (ICL) the model continued
    # the transcript's last words into the take
    prompt = model.create_voice_clone_prompt(ref_audio=str(clip), x_vector_only_mode=True)

    def reply(**kw):
        protocol.write(json.dumps(kw) + "\n")
        protocol.flush()

    reply(ready=True, device=torch.cuda.get_device_name(0) if gpu else "the CPU")
    for line in sys.stdin:
        req = json.loads(line)
        try:
            torch.manual_seed(int(req["seed"]))
            wavs, sr = model.generate_voice_clone(text=req["text"], language=language, voice_clone_prompt=prompt,
                                                  max_new_tokens=int(req["max_new_tokens"]))
            sf.write(req["out"], wavs[0], sr, subtype="FLOAT")
            reply(sr=sr)
        except Exception as e:  # one failed take must not end the build's worker silently
            reply(error=f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
