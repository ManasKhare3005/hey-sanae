"""How you sound, not just what you say: a speech-emotion model on the CPU.

audeering's wav2vec2 model (trained on natural podcast speech, MSP-Podcast) gives arousal,
dominance and valence (0-1) for a recording. Arousal (energy) is what voice models get right;
valence (positive / negative) from the voice alone is weak, so the words decide that part.
Measured on acted clips: angry / happy 0.6-0.75 arousal, sad / neutral 0.05-0.45. Exported to
ONNX with only the MatMuls in int8 (204 MB): ~130 ms for a 2-3 s command on 4 threads, run
next to Whisper so it adds no wait.

Your voice has its own normal level, so labels are relative to a running baseline of your
own commands (kept as two numbers). Nothing per message is stored: the label only goes into
that one request's notes, plus a daily tally ("tired x3 today") for the diary.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import re
import threading

import numpy as np

from .config import resolve_path

log = logging.getLogger(__name__)
SR = 16000
MIN_S = 1.0                 # shorter clips say little about tone
WARMUP = 20                 # commands before the personal baseline is trusted
Z = 1.2                     # this many standard deviations from your normal = worth a note
ABS_LOW, ABS_HIGH = 0.22, 0.70   # before the baseline is trusted

FINE = re.compile(r"^\s*(i'?m |it'?s |all )?(fine|okay|ok|good|alright|whatever|nothing|not much)\b", re.I)

HINTS = {
    ("low", "fine"): "They say they're fine but sound flat and low: don't push, a light, gentle check-in is okay",
    ("low", None): "They sound tired or low, whatever the words say: be soft and low-key",
    ("high", None): "They sound animated and full of energy: match it",
}


class ToneModel:
    def __init__(self, path: str = "models/tone/ser.mm8.onnx", threads: int = 4):
        import onnxruntime as ort

        p = resolve_path(path)
        if not p.exists():
            raise FileNotFoundError(f"tone model not found at {p} (run setup.ps1)")
        o = ort.SessionOptions()
        o.intra_op_num_threads = threads
        # No memory arena: with it, onnxruntime kept +460 MB of scratch after one 10 s clip, for
        # good. Without: +4 MB, ~250 ms slower, and that runs alongside Whisper (~2 s) anyway
        o.enable_cpu_mem_arena = False
        o.enable_mem_pattern = False
        self.session = ort.InferenceSession(str(p), o, providers=["CPUExecutionProvider"])

    def score(self, audio: np.ndarray) -> tuple[float, float, float] | None:
        """(arousal, dominance, valence) for 16 kHz mono audio, or None if it's too short."""
        x = np.asarray(audio, dtype=np.float32)
        if np.abs(x).max(initial=0) > 1.5:
            x = x / 32768.0
        if len(x) < MIN_S * SR:
            return None
        x = x[-10 * SR:]                                        # the last 10 s is plenty
        x = (x - x.mean()) / math.sqrt(float(x.var()) + 1e-7)
        a, d, v = self.session.run(None, {"input_values": x[None].astype(np.float32)})[0][0]
        return float(a), float(d), float(v)


class Baseline:
    """Your usual arousal (running mean / spread), kept in kv "tone:baseline"."""

    def __init__(self, memory=None):
        self.mem = memory
        raw = memory.get("tone:baseline") if memory is not None else None
        d = json.loads(raw) if raw else {}
        self.n, self.mean, self.var = int(d.get("n", 0)), float(d.get("mean", 0.4)), float(d.get("var", 0.02))

    def label(self, arousal: float) -> str | None:
        """"low" / "high" compared with your normal, or None."""
        if self.n < WARMUP:
            # Fixed cut-offs misread a normal voice: Alex's ordinary evening speech is 0.21-0.42, so
            # "< 0.22 = low" put a plain sentence into venting mode. Say nothing until it knows you.
            return None
        z = (arousal - self.mean) / math.sqrt(max(self.var, 1e-4))
        return "low" if z <= -Z else "high" if z >= Z else None

    def learn(self, arousal: float):
        """Only from your own voice (voice ID "you"); a slow running average (~50 commands)."""
        self.n += 1
        k = 1 / min(self.n, 50)
        delta = arousal - self.mean
        self.mean += k * delta
        self.var = (1 - k) * (self.var + k * delta * delta)
        if self.mem is not None:
            self.mem.set("tone:baseline", json.dumps({"n": self.n, "mean": round(self.mean, 4), "var": round(self.var, 5)}))


def hint(label: str | None, text: str, word_mood: str | None) -> str | None:
    """A note for the model from the voice, or None. The words win when they say how they feel;
    the voice adds what the words don't say (a flat "I'm fine")."""
    if label is None or word_mood is not None:
        return None
    if label == "low":
        return HINTS[("low", "fine")] if FINE.search(text or "") else HINTS[("low", None)]
    return HINTS[("high", None)]


def tally(memory, label: str | None, now: dt.datetime | None = None, keep_days: int = 14):
    """Daily counts only (for the diary): {"2026-10-14": {"low": 2, "high": 1, "n": 9}}."""
    if memory is None:
        return
    day = (now or dt.datetime.now()).date().isoformat()
    raw = memory.get("tone:days")
    days = json.loads(raw) if raw else {}
    t = days.setdefault(day, {"low": 0, "high": 0, "n": 0})
    t["n"] += 1
    if label:
        t[label] += 1
    for old in sorted(days)[:-keep_days]:
        del days[old]
    memory.set("tone:days", json.dumps(days))


def day_summary(memory, day: str) -> str | None:
    """"sounded tired or low a lot" for the diary, from the tally; None if nothing stood out."""
    raw = memory.get("tone:days") if memory is not None else None
    t = (json.loads(raw) if raw else {}).get(day)
    if not t or t["n"] < 3:
        return None
    if t["low"] / t["n"] >= 0.4:
        return "sounded tired or low a lot of the time"
    if t["high"] / t["n"] >= 0.4:
        return "sounded energetic and animated"
    return None


class ToneReader:
    """Runs the model in a thread next to Whisper; `result()` waits for it (briefly)."""

    def __init__(self, model: ToneModel, baseline: Baseline):
        self.model, self.baseline = model, baseline
        self._thread: threading.Thread | None = None
        self._scores: tuple[float, float, float] | None = None
        self._gen = 0

    def start(self, audio: np.ndarray):
        """Score this recording (an earlier, still-running one for the same command is dropped)."""
        self._gen += 1
        gen, self._scores = self._gen, None

        def run():
            try:
                scores = self.model.score(audio)
                if gen == self._gen:
                    self._scores = scores
            except Exception as exc:
                log.debug("tone failed: %s", exc)
        self._thread = threading.Thread(target=run, name="tone", daemon=True)
        self._thread.start()

    def result(self, owner: str, timeout: float = 1.0) -> str | None:
        """The label for the last recording; learns the baseline when it was surely the user."""
        if self._thread is None:
            return None
        self._thread.join(timeout)
        self._thread, scores = None, self._scores
        if scores is None:
            return None
        label = self.baseline.label(scores[0])
        log.info("tone: arousal %.2f (usual %.2f) -> %s", scores[0], self.baseline.mean, label or "as usual")
        if owner == "you":
            self.baseline.learn(scores[0])
        return label
