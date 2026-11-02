"""Try the routine (chores.py) with the real model: does she add, read, tick and remove routine
tasks with the right tool, and keep them apart from todos, reminders and voice routines?

    .venv\\Scripts\\python scripts\\chores_lab.py

Throwaway database (SANAE_LAB=1): nothing ends up in your real memory or on the phone. Every
yes/no answers no.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["SANAE_LAB"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sanae.config import load_config  # noqa: E402
from sanae.main import build  # noqa: E402

REQUESTS = [
    "add water the plants to my routine, every day",
    "I need to do laundry every Sunday, put it in my routine",
    "pay rent on the 1st of every month, add that to my routine",
    "take my vitamins every morning, add it to my routine",
    "what's on my routine today?",
    "I watered the plants",
    "actually untick the plants, I didn't do it yet",
    "what's my whole routine?",
    "take laundry off my routine",
    "add gym to my routine",
    "mondays",
    "add milk to my list",
]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="chores-lab-"))
    cfg = load_config()
    cfg["memory"] = {"enabled": True, "db": str(tmp / "lab.db")}
    cfg["notes"] = {**(cfg.get("notes") or {}), "folder": str(tmp / "notes"), "file": str(tmp / "quick.md")}
    asked = []
    ctx, llm, agent = build(cfg, lambda prompt: asked.append(prompt) or False, lambda kind, data: None)
    calls = []
    orig = agent.registry.run

    def spy(name, args):
        calls.append((name, args))
        return orig(name, args)

    agent.registry.run = spy
    for text in REQUESTS:
        calls.clear()
        asked.clear()
        t = time.time()
        reply = agent.handle(text)
        print(f"\n> {text}   ({time.time() - t:.1f} s)")
        for name, args in calls:
            print(f"   tool {name}({args})")
        for a in asked:
            print(f"   asked: {a}")
        print(f"   {reply}")
    print("\nbriefing line:", ctx.chores.briefing_sentence())


if __name__ == "__main__":
    main()
