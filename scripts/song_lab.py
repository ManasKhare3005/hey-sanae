"""Ask about "the song" with the real model: she should name what's actually playing (faked here)
and not invent how it sounds; with nothing playing she should ask which song.

    .venv\\Scripts\\python scripts\\song_lab.py

Safe: throwaway database, every yes/no answers no, the media session is faked.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["SANAE_LAB"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sanae import music  # noqa: E402
from sanae.config import load_config  # noqa: E402
from sanae.main import build  # noqa: E402

CASES = [
    (music.Track("Oh My Love (Remastered 2010)", "John Lennon - Topic", True), "what do you feel about this song?"),
    (music.Track("Everlong", "Foo Fighters", True), "how is the song?"),
    (music.Track("Numb (Official Music Video) [4K UPGRADE]", "Linkin Park", True), "do you like this song?"),
    (music.Track("Midnight Static", "Glass Harbor", True), "what do you think of this track?"),   # made up: she shouldn't know it
    (None, "how's the song?"),
]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="song-lab-"))
    cfg = load_config()
    cfg["memory"] = {"enabled": True, "db": str(tmp / "lab.db")}
    cfg["notes"] = {**(cfg.get("notes") or {}), "folder": str(tmp / "notes"), "file": str(tmp / "quick.md")}
    ctx, llm, agent = build(cfg, lambda prompt: False, lambda kind, data: None)
    for track, text in CASES:
        music.now_playing = lambda t=track: t
        agent.history.clear()
        reply = agent.handle(text)
        print(f"[{track.spoken() if track else 'nothing playing'}] you: {text}\n  her: {reply}\n")


if __name__ == "__main__":
    main()
