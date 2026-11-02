"""Try the todo tools with the real model: does she pick the right tool for each request (and
not set a reminder or a calendar event instead)?

    .venv\\Scripts\\python scripts\\todo_lab.py

Throwaway database: nothing ends up in your real list or on the phone. Every yes/no answers no.
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
    ("add milk and eggs to my shopping list", "add_todo"),
    ("put finish the networking lab on my todo list", "add_todo"),
    ("I need to call the landlord at some point, add that to my list", "add_todo"),
    ("what's on my to do list?", "list_todos"),
    ("what do I still need to do?", "list_todos"),
    ("I bought the milk, check it off", "check_todo"),
    ("cross off the networking lab", "check_todo"),
    ("take eggs off my list", "clear_todos"),
    ("clear the done ones from my list", "clear_todos"),
    ("remind me to take out the trash at 8pm", "set_reminder"),
]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="todo-lab-"))
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
    right = 0
    for text, want in REQUESTS:
        calls.clear()
        asked.clear()
        t = time.time()
        reply = agent.handle(text)
        ok = want in [n for n, _ in calls]
        right += ok
        print(f"\n{'OK ' if ok else 'BAD'} > {text}   ({time.time() - t:.1f} s)")
        for name, args in calls:
            print(f"   tool {name}({args})")
        for a in asked:
            print(f"   asked: {a}")
        print(f"   {reply}")
    print(f"\n{right}/{len(REQUESTS)} right. List now: {[t.text for t in ctx.todos.shown()]}")


if __name__ == "__main__":
    main()
