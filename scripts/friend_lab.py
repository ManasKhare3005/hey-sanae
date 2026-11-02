"""Friendship parts with the real model: a short scripted chat per part, on a throwaway database.

    .venv/Scripts/python scripts/friend_lab.py goals

Safe: SANAE_LAB=1, temp DB, every yes/no answers no.
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

from sanae.config import load_config  # noqa: E402
from sanae.main import build  # noqa: E402

CHATS = {
    "goals": ["I want to go to the gym 3 times a week", "yeah keep me to it", "just got back from the gym!",
              "what are my goals?"],
    "pushback": ["ok one more valorant game", "nah i'm fine, just one"],
    "care": ["ugh I'm so tired today", "what should I eat"],
    "social": ["I hung out with Maya today, we got boba", "how's your day"],
    "thoughts": ["what have you been up to?"],
    "life": ["what have you been up to?", "what are you into lately?"],
}


def main():
    which = sys.argv[1:] or list(CHATS)
    tmp = Path(tempfile.mkdtemp(prefix="friend-lab-"))
    cfg = load_config()
    cfg["memory"] = {"enabled": True, "db": str(tmp / "lab.db")}
    cfg["notes"] = {**(cfg.get("notes") or {}), "folder": str(tmp / "notes"), "file": str(tmp / "quick.md")}
    ctx, llm, agent = build(cfg, lambda prompt: False, lambda kind, data: None)
    setup = globals().get("SETUP")
    for name in which:
        agent.history.clear()
        if setup and name in setup:
            setup[name](ctx)
        print(f"===== {name}")
        for text in CHATS[name]:
            print(f"you: {text}\n  her: {agent.handle(text)}")
        print()


if __name__ == "__main__":
    main()
