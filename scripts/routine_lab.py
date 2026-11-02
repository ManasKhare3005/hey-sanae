"""Try routines with the real model: phrases go straight to the routine, other wordings ("run my
goodnight routine") need the model to pick run_routine.

    .venv\\Scripts\\python scripts\\routine_lab.py

Safe: tools that would touch the laptop (lock, close/open apps, media keys, freeing the GPU,
quiet mode, study sessions) are replaced by fakes that only print. Throwaway database; every
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

FAKED = ["lock_screen", "close_app", "open_app", "media_control", "free_gpu", "quiet_for", "start_study", "volume"]
REQUESTS = [
    ("goodnight!", "run_routine"),
    ("okay, gaming time", "run_routine"),
    ("study time", "run_routine"),
    ("run my goodnight routine", "run_routine"),
    ("can you start the gaming time routine?", "run_routine"),
    ("say goodnight to my mom for me", None),
]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="routine-lab-"))
    cfg = load_config()
    cfg["memory"] = {"enabled": True, "db": str(tmp / "lab.db")}
    cfg["notes"] = {**(cfg.get("notes") or {}), "folder": str(tmp / "notes"), "file": str(tmp / "quick.md")}
    asked = []
    ctx, llm, agent = build(cfg, lambda prompt: asked.append(prompt) or False, lambda kind, data: None)
    ran = []
    for name in FAKED:
        tool = agent.registry.get(name)
        if tool is not None:
            tool.func = (lambda n: lambda **kw: ran.append((n, kw)) or f"(fake {n} done)")(name)
    calls = []
    orig = agent.registry.run

    def spy(name, args):
        calls.append(name)
        return orig(name, args)

    agent.registry.run = spy
    right = 0
    for text, want in REQUESTS:
        calls.clear(), ran.clear(), asked.clear()
        t = time.time()
        reply = agent.handle(text)
        ok = (want in calls) if want else ("run_routine" not in calls)
        right += ok
        print(f"\n{'OK ' if ok else 'BAD'} > {text}   ({time.time() - t:.1f} s)")
        print(f"   tools {calls}  fakes {ran}  asked {asked}")
        print(f"   {reply}")
    print(f"\n{right}/{len(REQUESTS)} right.")


if __name__ == "__main__":
    main()
