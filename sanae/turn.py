"""Is the user done talking? A small text model on the transcript so far, next to the word check.

Namo-Turn-Detector-v1-English (DistilBERT, Apache 2.0, int8 ONNX, ~30 ms on the CPU) reads the
words and says "finished" or "not yet". Measured on Whisper transcripts: it catches thoughts that
trail off without a dangling word ("So I was thinking that maybe" -> not yet), but it's
overconfident on some finished, punctuated sentences ("Honestly, kinda tired." -> not yet).
Whisper's own punctuation is the better signal there, so:
- ends in . ? or ! -> the word check decides (listen.looks_complete)
- no closing punctuation -> the model decides
"""
from __future__ import annotations

import logging
import re

import numpy as np

from .config import resolve_path
from .listen import looks_complete

log = logging.getLogger(__name__)


class TurnDetector:
    def __init__(self, model_dir: str = "models/turn", threads: int = 2):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        d = resolve_path(model_dir)
        if not (d / "model_quant.onnx").exists():
            raise FileNotFoundError(f"turn model not found in {d} (run setup.ps1)")
        self.tok = Tokenizer.from_file(str(d / "tokenizer.json"))
        self.tok.enable_truncation(max_length=128)
        o = ort.SessionOptions()
        o.intra_op_num_threads = threads
        self.session = ort.InferenceSession(str(d / "model_quant.onnx"), o, providers=["CPUExecutionProvider"])

    def p_done(self, text: str) -> float:
        e = self.tok.encode(text)
        logits = self.session.run(None, {"input_ids": np.array([e.ids], dtype=np.int64),
                                         "attention_mask": np.array([e.attention_mask], dtype=np.int64)})[0][0]
        p = np.exp(logits - logits.max())
        return float(p[1] / p.sum())


def completer(detector: TurnDetector | None):
    """A looks_complete() that also asks the model when Whisper left the sentence open."""
    def complete(text: str) -> bool:
        if not looks_complete(text):
            return False
        if detector is None or re.search(r"[.?!]['\")\]]*\s*$", text.strip()):
            return True
        try:
            p = detector.p_done(text)
        except Exception as exc:
            log.debug("turn model failed: %s", exc)
            return True
        if p < 0.5:
            log.info("turn model: not finished yet (%.2f): %r", p, text[-60:])
        return p >= 0.5
    return complete
