"""Try the code-project tools with the real model: does she pick the right tool and project for
each request? Reads your real repos (read-only: status, GitHub, what's running). Claude is NOT
started: code_change jobs are recorded but never run, and nothing is merged or pushed (every
yes/no answers no).

    .venv\\Scripts\\python scripts\\code_lab.py

Throwaway database and jobs file: nothing ends up in your real memory or the phone's job list.
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

from sanae import devloop  # noqa: E402
from sanae.config import load_config  # noqa: E402
from sanae.main import build  # noqa: E402

REQUESTS = [
    "what projects do I have?",
    "what changed in Flock this week?",
    "any open issues on San-AI?",
    "is resume builder running?",
    "ask Claude to add a dark mode toggle to the resume builder",
    "is Claude done yet?",
    "merge it",
    "throw that change away",
    "push Flock",
    "what was my last commit in Lofty?",
]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="code-lab-"))
    devloop.JOBS_FILE = tmp / "jobs.json"
    devloop.DevLoop._work = lambda self, job: None          # never start Claude here
    cfg = load_config()
    cfg["memory"] = {"enabled": True, "db": str(tmp / "lab.db")}
    cfg["dev"] = {"enabled": True}
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


if __name__ == "__main__":
    main()
