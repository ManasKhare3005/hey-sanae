"""Try phase 3 with the real model: what she learns from a sample conversation (friend memory, things
to ask about later), and the lines she'd say first for each kind of moment (asking how something went,
small talk, noticing the window in front, bedtime), a few times each, with her mood applied.

    .venv\\Scripts\\python scripts\\companion_lab.py

Throwaway database: nothing ends up in your real memory. Nothing is spoken.
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sanae.config import load_config  # noqa: E402
from sanae.main import build  # noqa: E402

CONVERSATION = [
    ("ugh i have my CS 102 midterm on thursday and i haven't started studying", "[sad] Oof, Thursday's close! Want me to block out study time?"),
    ("yeah maybe. also my friend rohan is coming over this weekend, we're gonna play valorant", "[happy] Ooh fun! Is Rohan any good or are you carrying him?"),
    ("lol i carry him. btw i've been really into lo-fi music while coding lately", "[happy] Lo-fi coding sessions are the best. Got a favourite playlist?"),
    ("chillhop mostly. i hate when people talk during movies by the way, my roommate does it constantly", "[laugh] Aw, that's the worst! Hand him a popcorn bucket to keep him busy."),
    ("my doctor said i should sleep more lol. also my bank app password is weird", "[sleepy] Your doctor's right, you know. Bed earlier this week?"),
    ("open spotify", "[happy] Done, Spotify's up!"),
]
WINDOWS = [("VS Code", "initiative.py - jarvis"), ("Chrome", "Two Sum - LeetCode"), ("Chrome", "Frieren Episode 12 - Crunchyroll")]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="companion-lab-"))
    cfg = load_config()
    cfg["memory"] = {"enabled": True, "db": str(tmp / "lab.db")}
    cfg["dev"] = {"enabled": False}
    cfg["notes"] = {**(cfg.get("notes") or {}), "folder": str(tmp / "notes"), "file": str(tmp / "quick.md")}
    ctx, llm, agent = build(cfg, lambda prompt: False, lambda kind, data: None)
    user, model = cfg.assistant.user_name, cfg.llm.fast_model

    # ----- friend memory -----
    from sanae.friend import Learner

    ctx.memory.set("friend:last_turn", "0")
    ctx.memory.log_turn("(earlier)", "(earlier)")
    ctx.memory.set("friend:last_turn", "1")
    for u, r in CONVERSATION:
        ctx.memory.log_turn(u, r)
    learner = Learner(ctx, ctx.friend, llm, model, user, ctx.persona.name, clock=lambda: time.time() + 600)
    t = time.perf_counter()
    learner.run_once()
    print(f"\n== learned ({time.perf_counter() - t:.1f} s)")
    for f in ctx.friend.facts():
        print(f"  [{f.kind}] {f.text}")
    for th in ctx.friend.threads("open"):
        print(f"  ask about: {th.about}  (after {th.ask_after})")

    # ----- lines she'd say first -----
    from sanae.initiative import Moment, model_line

    said: list[str] = []
    gen = model_line(agent, llm, model, user, context=lambda: [n for n in [ctx.mood.mood.note()] if n], recent=lambda: said[-5:])
    moments = []
    for th in ctx.friend.threads("open")[:1]:
        moments.append(Moment("callback", f"Earlier {{user}} told you about this: {th.about}. It has happened by now. Sincerely "
                                          "ask {user} how it went (this matters to them: no teasing, no guessing how it went, one short question)."))
    for topic in [*ctx.persona.topics[:3], *[f"something {{user}} is into: {x}" for x in ctx.friend.interests(2)]]:
        moments.append(Moment("chat", f"You feel like chatting. Idea: {topic}. Start a short, casual conversation (a thought or a question)."))
    for app, title in WINDOWS:
        moments.append(Moment("noticing", f"{{user}} has had this in front for about 25 minutes: {app}: {title}. If there's something "
                                          "light and friendly to say about it, say it; never read the title out word for word. Otherwise SKIP."))
    for clock in ("1:10 AM", "2:05 AM", "3:30 AM"):
        moments.append(Moment("bedtime", f"It's {clock}, really late, and {{user}} is still up on the laptop. Gently nudge them toward bed: "
                                         "tease them about being a night owl, mention tomorrow, or offer to say goodnight (a different "
                                         "angle than before; no lecture, no weird metaphors).", True))
    print("\n== lines")
    for m in moments:
        agent.history.clear()
        t = time.perf_counter()
        line = gen(m)
        print(f"  {m.kind:9} {time.perf_counter() - t:4.1f}s  {line or '(SKIP)'}")
        if line:
            said.append(line)


if __name__ == "__main__":
    main()
