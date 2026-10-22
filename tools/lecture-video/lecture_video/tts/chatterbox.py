"""Chatterbox Multilingual (local, both languages, expressive, slow on a CPU).

  ref: 15-25 s WAV of the voice to clone; default voice/ref-<lang>.wav. Without one, Chatterbox uses
       its built-in English voice, and other languages get an English accent.
  exaggeration 0.25-1.0: more energy; cfg_weight 0.2-0.6: lower is slower and carries less accent;
  temperature (0.8): variation; seed: the same take on every build.
  dtype: fp16 (default on a GPU: T3 1.6x and S3Gen's flow 1.2x faster, the same takes as float32 in
       tests) or fp32 (the default on a CPU); the same for all Chatterbox voices.

Code words in German sentences come tagged as English ([en]count[de], tts.Voice): one take per
sentence, the same voice, English pronunciation for the code.

A take is made in two stages: T3 writes speech tokens (what is said, timing, intonation), S3Gen turns
them into the voice of the reference clip. T3 rarely stops right after the text: it goes on with a
breath or the start of a new word until Chatterbox forces the end. The take reports where its
alignment reached the end of the text, and tts.cut_tail cuts there. The tokens are kept, so a new
reference clip can reuse them (revoice: S3Gen only, about half the time).
"""
from __future__ import annotations

import os
import re
import warnings

import numpy as np

from . import Engine, Take, cut_tail
from .ref import last_pause, prepared_ref, ref_path

TOKENS_PER_SECOND = 25  # one speech token is 40 ms of audio
# S3Gen's flow matching steps (Chatterbox: 10). Most of S3Gen's time, in proportion; 6 sound the same
# (speaker similarity 0.997 to 10 steps), 4 lose some of the voice. Change it with tts.VOCODER.
S3GEN_STEPS = 6
# S3Gen continues its prompt, the first 10 s of the reference clip. Cut in the middle of a word, every
# take started with the rest of that word (German: -35 dB for 300 ms); cut at a pause, it starts quiet.
S3GEN_PROMPT = 10.0


_analyzer = None  # the alignment of the last take: where it reached the end of the text


def patient_repetition_check():
    """Chatterbox ends a take as soon as two speech tokens in a row are the same (a 40 ms frame
    repeated, e.g. in a pause at a comma), even when the text is not spoken yet: the sentence is
    cut off. Count repetitions only once the whole text is spoken, where they mean babbling."""
    from chatterbox.models.t3.inference.alignment_stream_analyzer import AlignmentStreamAnalyzer
    step = AlignmentStreamAnalyzer.step
    if getattr(step, "patient", False):
        return

    def patient(self, logits, next_token=None):
        global _analyzer
        _analyzer = self
        if not self.complete:
            self.generated_tokens.clear()
        logits = step(self, logits, next_token)
        # where the alignment got furthest: the end of the text when it never quite reaches the end
        if int(self.text_position) > getattr(self, "furthest", -1):
            self.furthest, self.furthest_at = int(self.text_position), self.alignment.shape[0]
        return logits
    patient.patient = True
    AlignmentStreamAnalyzer.step = patient


def quiet():
    """Every take ends with a forced EOS (logged as a warning) after a progress bar of its own; both
    only bury the slide progress and the real retries ("speaking it again")."""
    import functools
    import logging
    import tqdm
    import chatterbox.models.t3.t3 as t3
    logging.getLogger("chatterbox.models.t3.inference.alignment_stream_analyzer").setLevel(logging.ERROR)
    t3.tqdm = functools.partial(tqdm.tqdm, disable=True)


_model = None


DTYPES = ("fp16", "fp32")


def model(dtype=None):
    """The model, loaded once per run and shared by both languages (3 GB, loading takes a while).
    dtype: of T3, which writes the speech tokens one by one: reading its weights for every token is
    much of the time, half as many bytes in fp16."""
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
        quiet()
        _model.dtype = dtype or ("fp16" if gpu else "fp32")  # fp16 on a CPU is slow
        if _model.dtype == "fp16":
            _model.t3.to(dtype=torch.float16)
            _model.builtin.t3.to(dtype=torch.float16)
            _model.s3gen.flow.decoder.estimator.to(dtype=torch.float16)  # the flow casts its inputs to it
    elif dtype and dtype != _model.dtype:
        raise SystemExit(f"Chatterbox runs in {_model.dtype} already: dtype must be the same for all Chatterbox voices")
    return _model


class Chatterbox(Engine):
    def __init__(self, lang, cfg):
        super().__init__(lang, cfg)
        warnings.filterwarnings("ignore")
        import torch
        self.torch = torch
        if cfg.get("dtype") not in (None, *DTYPES):
            raise SystemExit(f"voices.{lang}.dtype: {cfg['dtype']!r} (known: {', '.join(DTYPES)})")
        self.model = model(cfg.get("dtype"))
        self.sample_rate = self.model.sr
        ref = ref_path(lang, cfg)
        self.exaggeration = float(cfg.get("exaggeration", 0.6))
        if ref.exists():
            clip = prepared_ref(ref)
            self.model.prepare_conditionals(str(clip), exaggeration=self.exaggeration)
            self.conds = self.model.conds
            self.conds.t3.to(dtype=next(self.model.t3.parameters()).dtype)
            import soundfile as sf
            audio, sr = sf.read(clip, dtype="float32")
            s3gen = self.model.s3gen
            self.conds.gen = s3gen.embed_ref(torch.from_numpy(audio[:last_pause(audio, sr, S3GEN_PROMPT)]), sr,
                                             device=s3gen.device)
        elif cfg.get("ref"):
            raise SystemExit(f"voices.{lang}.ref: {ref} not found")
        else:
            print(f"Chatterbox [{lang}]: no {ref}, using the built-in English voice")
            self.conds = self.model.builtin

    def synth(self, text, lang):
        # Chatterbox sometimes babbles on (mostly on short inputs): a take far longer than the text
        # can be, or one whose alignment lost track of the text (no end to cut at), is made again
        # with the next seed; the shortest take with an end wins.
        spoken = re.sub(r"\[\w\w\]", "", text)  # without the language tags
        limit = 2.5 + len(spoken) / 6  # s; speech is about 13-15 characters per second
        self.model.max_tokens = int(TOKENS_PER_SECOND * (limit + 1))
        seed = int(self.cfg.get("seed", 0))
        takes = []
        for attempt in range(3):
            if "seed" in self.cfg or attempt:
                self.torch.manual_seed(seed + attempt)
            tokens, end = self.tokens(text, lang)
            take = Take(self.vocode(tokens), end, tokens)
            seconds = len(cut_tail(take.audio, self.sample_rate, end)) / self.sample_rate
            takes.append((end is None, seconds, take))
            if seconds <= limit and end is not None:
                break
            why = "lost track of the text" if end is None else f"{seconds:.1f} s"
            print(f"\nChatterbox [{lang}]: {why} for {text!r}, speaking it again")
        return min(takes, key=lambda t: t[:2])[2]

    def revoice(self, tokens):
        """A take spoken before, in the voice of the current reference clip."""
        return self.vocode(tokens)

    def tokens(self, text, lang):
        """T3, as in ChatterboxMultilingualTTS.generate: the speech tokens, and where the alignment
        reached the end of the text (s; None if it never did)."""
        from chatterbox import mtl_tts
        torch, m = self.torch, self.model
        conds = self.conds.t3
        if abs(float(self.exaggeration) - float(conds.emotion_adv[0, 0, 0].item())) > 1e-2:  # bf16 holds 0.65 as 0.6484
            conds = mtl_tts.T3Cond(speaker_emb=conds.speaker_emb, cond_prompt_speech_tokens=conds.cond_prompt_speech_tokens,
                                   emotion_adv=self.exaggeration * torch.ones(1, 1, 1)).to(
                device=m.device, dtype=conds.speaker_emb.dtype)
        text_tokens = m.tokenizer.text_to_tokens(mtl_tts.punc_norm(text), language_id=lang.lower()).to(m.device)
        text_tokens = torch.cat([text_tokens, text_tokens], dim=0)  # two sequences for CFG
        text_tokens = mtl_tts.F.pad(text_tokens, (1, 0), value=m.t3.hp.start_text_token)
        text_tokens = mtl_tts.F.pad(text_tokens, (0, 1), value=m.t3.hp.stop_text_token)
        global _analyzer
        _analyzer = None
        # every take's alignment analyzer hooks into three attention layers and never lets go: after
        # hundreds of takes each token ran hundreds of stale hooks (a build got 2x slower)
        attention = [layer.self_attn for layer in m.t3.tfmr.layers]
        hooks = [set(a._forward_hooks) for a in attention]
        try:
            with torch.inference_mode():
                speech = m.t3.inference(
                    t3_cond=conds, text_tokens=text_tokens, max_new_tokens=1000,
                    temperature=float(self.cfg.get("temperature", 0.8)), cfg_weight=float(self.cfg.get("cfg_weight", 0.5)),
                    repetition_penalty=2.0, min_p=0.05, top_p=1.0)
                speech = mtl_tts.drop_invalid_tokens(speech[0])
        finally:
            for a, before in zip(attention, hooks):
                for k in set(a._forward_hooks) - before:
                    del a._forward_hooks[k]
        a, done = _analyzer, None
        if a and a.completed_at is not None:
            done = a.completed_at
        elif a and getattr(a, "furthest", -1) >= 0.8 * a.alignment.shape[1]:
            done = a.furthest_at  # it repeated itself before the last tokens: cut after its furthest point
        # the alignment's first row is the start token, the speech tokens follow it
        end = max(0, done - 1) / TOKENS_PER_SECOND if done is not None else None
        return speech.cpu().numpy().astype(np.int16), end

    def vocode(self, tokens):
        """S3Gen, as in ChatterboxMultilingualTTS.generate: speech tokens in the voice of this language."""
        torch, m = self.torch, self.model
        with torch.inference_mode():
            wav, _ = m.s3gen.inference(speech_tokens=torch.from_numpy(np.asarray(tokens, np.int64)).to(m.device),
                                       ref_dict=self.conds.gen, n_cfm_timesteps=S3GEN_STEPS)
            wav = wav.squeeze(0).detach().cpu().numpy()
            wav = m.watermarker.apply_watermark(wav, sample_rate=m.sr)
        return np.asarray(wav, np.float32).reshape(-1)
