"""Try the persona in text mode with the real model: a fixed set of messages, each reply printed with
its emotion tag, then a score card (tag rate, length, banned phrases, repeated openers).

    .venv\\Scripts\\python scripts\\persona_lab.py            run the set
    .venv\\Scripts\\python scripts\\persona_lab.py --speak    ...and say each reply in her voice
    .venv\\Scripts\\python scripts\\persona_lab.py --chat     type your own messages

Uses a throwaway memory database, so nothing here ends up in your real memories or chat log.
Tools still run (opening apps etc. is real), so the set only uses harmless ones.
"""
from __future__ import annotations

import re
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sanae.config import load_config  # noqa: E402
from sanae.main import build  # noqa: E402

MESSAGES = [
    "hey", "good morning", "how are you", "what are you up to", "i'm so tired",
    "i aced my midterm!", "i failed my quiz", "you're just a program", "you're cute", "tell me a joke",
    "what's the time", "what's 12 times 15", "what should i eat for dinner", "i've been coding for 5 hours",
    "do you like anime", "what do you think about pineapple on pizza", "i'm bored", "remind me to stretch in 10 minutes",
    "what's on my calendar today", "i'm going to sleep", "thanks", "can you help me", "who are you",
    "i think python is better than javascript", "my friend cancelled on me",
]
BANNED = re.compile(r"how can i (help|assist)|as an ai|i'?m here to help|is there anything else|"
                    r"let me know if|i'?m just an? (ai|assistant|program)|feel free to", re.I)


def main():
    speak = "--speak" in sys.argv
    chat = "--chat" in sys.argv
    tmp = Path(tempfile.mkdtemp(prefix="persona-lab-"))
    cfg = load_config()
    cfg["memory"] = {"enabled": True, "db": str(tmp / "lab.db")}
    cfg["dev"] = {"enabled": False}
    cfg["notes"] = {**(cfg.get("notes") or {}), "folder": str(tmp / "notes"), "file": str(tmp / "quick.md")}
    events = []
    ctx, llm, agent = build(cfg, lambda prompt: False, lambda kind, data: events.append((kind, data)))
    voice = None
    if speak:
        from sanae.audio import play
        from sanae.tts import clean_for_speech, make_voice

        voice = make_voice(dict(cfg.tts))
    rows = []

    def one(msg: str):
        n = len(events)
        t = time.perf_counter()
        reply = agent.handle(msg)
        dt = time.perf_counter() - t
        raw = agent.history[-1][-1]["content"] if agent.history else reply
        emo = next((d for k, d in events[n:] if k == "emotion"), {})
        rows.append({"msg": msg, "reply": reply, "raw": raw, "emotion": emo.get("emotion"),
                     "source": emo.get("source"), "gestures": emo.get("gestures", []), "s": dt})
        g = ("+" + ",".join(emo.get("gestures", []))) if emo.get("gestures") else ""
        print(f"you > {msg}\n{cfg.assistant.name.lower()} [{emo.get('emotion')}{g} {emo.get('source')}] ({dt:.1f}s) > {reply}\n")
        if voice is not None:
            audio, sr = voice.synthesize(clean_for_speech(reply))
            play(audio, sr)

    if chat:
        while True:
            msg = input("you > ").strip()
            if msg in ("quit", "exit", ""):
                break
            one(msg)
        return
    for msg in MESSAGES:
        one(msg)
        agent.history.clear()                      # each message on its own, like a fresh chat
    llm_rows = [r for r in rows if r["source"] == "tag" or r["raw"] != r["reply"] or r["source"] == "guess"]
    tagged = sum(r["source"] == "tag" for r in rows)
    words = [len(r["reply"].split()) for r in rows]
    openers = Counter(" ".join(r["reply"].lower().split()[:2]) for r in rows)
    banned = [r["reply"] for r in rows if BANNED.search(r["reply"])]
    leaks = [r["reply"] for r in rows if re.search(r"\[|\]|\*", r["reply"])]
    print("=" * 60)
    print(f"tag rate:        {tagged}/{len(rows)} ({100 * tagged / len(rows):.0f}%)")
    print(f"emotions:        {dict(Counter(r['emotion'] for r in rows))}")
    print(f"gestures:        {dict(Counter(g for r in rows for g in r['gestures']))}")
    print(f"words per reply: avg {sum(words) / len(words):.1f}, max {max(words)}")
    print(f"avg time:        {sum(r['s'] for r in rows) / len(rows):.2f} s")
    print(f"repeated openers:{[(k, v) for k, v in openers.items() if v > 2]}")
    print(f"banned phrases:  {banned or 'none'}")
    print(f"tag leaks:       {leaks or 'none'}")
    del llm_rows


if __name__ == "__main__":
    main()
