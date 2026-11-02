"""Speak the same test lines in every candidate voice and save WAVs to listen to and pick from.

    .venv\\Scripts\\python scripts\\tts_audition.py            all candidates
    .venv\\Scripts\\python scripts\\tts_audition.py af_heart   only voices whose name contains "af_heart"

Writes data/voices/<nn>-<engine>-<voice>.wav (the lines one after another), data/voices/name-*.wav
(ways to say the name) and data/voices/timing.csv: how long the first line took to make (what you'd
wait before she starts talking) and the real-time factor (seconds of work per second of speech).
"""
from __future__ import annotations

import csv
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sanae.tts import KokoroTTS, PiperTTS  # noqa: E402

NAME = "Sanae"
SOUNDS = {"Sanae": "Sah-nah-eh"}       # what config.yaml tts.spellings will use (pick below)
LINES = [
    f"Hey, it's {NAME}! You're back. I was starting to think you forgot about me.",
    "Your lab report is due tomorrow at eleven fifty nine. Want me to remind you tonight?",
    "Oh no, that sounds rough. Take a little break, okay? I'll be right here.",
    "Wait, really? You finished it already? That's amazing!",
]
KOKORO = "models/kokoro/kokoro-multi-lang-v1_0"
CANDIDATES = [
    ("kokoro", "af_heart"), ("kokoro", "af_bella"), ("kokoro", "af_nicole"), ("kokoro", "af_sky"),
    ("kokoro", "af_aoede"), ("kokoro", "bf_lily"), ("kokoro", {"af_heart": 0.6, "af_bella": 0.4}),
    ("kokoro", {"af_heart": 0.6, "af_sky": 0.4}),
    ("piper", "en_GB-jenny_dioco-medium"), ("piper", "en_US-amy-medium"),
    ("piper", "en_US-hfc_female-medium"), ("piper", "en_US-kristin-medium"),
]
SOFT = {"gain_db": -3.0, "treble_db": -2.0, "squeeze": 0.35}
SPEED = {"kokoro": 0.94, "piper": 0.95}
OUT = Path(__file__).resolve().parents[1] / "data" / "voices"


def label(voice) -> str:
    return voice if isinstance(voice, str) else "+".join(f"{k}{round(v * 10)}" for k, v in voice.items())


def make(engine: str, voice):
    if engine == "kokoro":
        return KokoroTTS(KOKORO, voice, SPEED["kokoro"], threads=4, spellings=SOUNDS, soft=SOFT)
    return PiperTTS(f"models/piper/{voice}.onnx", SPEED["piper"], spellings=SOUNDS, soft=SOFT)


def save(path: Path, audio: np.ndarray, sr: int):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def main():
    only = sys.argv[1:]
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for n, (engine, voice) in enumerate(CANDIDATES, 1):
        name = label(voice)
        if only and not any(o in name for o in only):
            continue
        try:
            tts = make(engine, voice)
        except Exception as exc:
            print(f"skip {engine} {name}: {exc}")
            continue
        tts.synthesize("Hi.")                              # warm up (first call loads things)
        parts, first_s, work, spoken, sr = [], 0.0, 0.0, 0.0, 24000
        for i, line in enumerate(LINES):
            t = time.perf_counter()
            audio, sr = tts.synthesize(line)
            dt = time.perf_counter() - t
            first_s = first_s or dt
            work += dt
            spoken += len(audio) / sr
            parts += [audio, np.zeros(int(0.6 * sr), np.float32)]
        path = OUT / f"{n:02d}-{engine}-{name}.wav"
        save(path, np.concatenate(parts), sr)
        rows.append({"file": path.name, "first_line_s": round(first_s, 2), "rtf": round(work / spoken, 3),
                     "speech_s": round(spoken, 1)})
        print(f"{path.name:44s} first line {first_s:.2f} s   rtf {work / spoken:.3f}")
    if rows and not only:
        with open(OUT / "timing.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    # ways to say the name, in the first Kokoro voice
    tts = KokoroTTS(KOKORO, "af_heart", SPEED["kokoro"], soft=SOFT)
    for i, spelling in enumerate(["Sanae", "Sah-nah-eh", "Sanaeh", "Sahnahay"], 1):
        audio, sr = tts.synthesize(f"Hi, I'm {spelling}. {spelling} is here.")
        save(OUT / f"name-{i}-{spelling}.wav", audio, sr)
    print(f"\nSaved to {OUT}")


if __name__ == "__main__":
    main()
