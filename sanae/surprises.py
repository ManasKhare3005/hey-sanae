"""Small surprises, the unasked-for things friends do:
  - milestones of knowing each other (from the first conversation she has): a week, a month,
    50 / 100 / 200 days, a year - she notices and says something sweet, once;
  - after a rough week (3+ days of the last 7 that felt stressed / tired / down / frustrated, from
    mood.py's daily counts, or a hard day), a tiny haiku she "wrote" for them, about something real
    from their week (diary), at most once a week;
  - now and then (~every 10 days), a little compliment about something she's noticed they're
    good at (from friend memory), out of nowhere.
"""
from __future__ import annotations

import datetime as dt
import random
import time

from .initiative import Moment
from .part import Part

MILESTONES = {7: "a week", 30: "a month", 50: "50 days", 100: "100 days", 200: "200 days", 365: "a whole year"}
ROUGH = ("stressed", "tired", "down", "frustrated")


class Surprises(Part):
    name = "surprises"

    def __init__(self, store=None, clock=time.time, diary=None, friend=None, idle=lambda: 0.0, rng=None,
                 llm=None, model: str = "", user: str = "them", on_line=None):
        super().__init__(store, clock)
        self.diary, self.friend, self.idle = diary, friend, idle
        self.llm, self.model, self.user = llm, model, user
        self.on_line = on_line              # a line said as is goes into the chat too (agent.add_said)
        self.rng = rng or random.Random()

    def first_day(self) -> dt.date | None:
        known = self.get("first")
        if known:
            return dt.date.fromisoformat(known)
        if self.store is None or not hasattr(self.store, "db"):
            return None
        with self.store.lock:
            row = self.store.db.execute("SELECT MIN(ts) AS ts FROM turns").fetchone()
        if not row or not row["ts"]:
            return None
        first = dt.datetime.fromisoformat(row["ts"]).date()
        self.put("first", first.isoformat())
        return first

    def rough_days(self) -> int:
        if self.store is None:
            return 0
        from .mood import _days

        days = _days(self.store)
        cutoff = (self.now().date() - dt.timedelta(days=7)).isoformat()
        return sum(1 for day, t in days.items() if day >= cutoff and (t.get("hard") or any(t.get(k, 0) for k in ROUGH)))

    def haiku(self, d: dt.datetime) -> str | None:
        """Written with its own prompt (her openers are one short line), said as is."""
        if self.llm is None:
            return None
        bits = ""
        try:
            entries = self.diary.week(d.date()) if self.diary is not None else []
            bits = " ".join(e.text[:200] for e in entries[:3])
        except Exception:
            pass
        prompt = (f"Write a haiku (three lines, 5-7-5 syllables) for your friend {self.user}, who had a rough week. "
                  + (f"What their week was like: {bits} " if bits else "")
                  + "Gentle and hopeful, about something real from their week if you know it; no weather, no names, "
                    "no title. Reply with only the three lines.")
        try:
            from .agent import strip_thinking

            raw = strip_thinking(self.llm.chat(self.model, [{"role": "user", "content": prompt}],
                                               options={"temperature": 0.8, "num_predict": 60}).content)
        except Exception:
            return None
        lines = [l.strip(" *\"'") for l in raw.splitlines() if l.strip(" *\"'")]
        if len(lines) != 3 or any(len(l.split()) > 9 for l in lines):
            return None
        text = ". ".join(l.rstrip(".,;:!-–— ") for l in lines) + "."
        if self.on_line is not None:
            self.on_line(f"I wrote you something. {text}")
        return f"[shy] I wrote you something. {text}"

    def moments(self, now: float) -> list[Moment]:
        idle = self.idle()
        if idle < 20 or idle > 300:
            return []
        d = self.now()
        out = []
        first = self.first_day()
        if first is not None and d.hour >= 10:
            days = (d.date() - first).days
            label = MILESTONES.get(days) or (f"{days // 365} years" if days >= 730 and days % 365 == 0 else None)
            if label and not self.done(f"milestone:{days}"):
                out.append(Moment("surprise", f"Today it's been exactly {label} since you and {{user}} first talked "
                                              f"({first:%B} {first.day}). Tell them that, sweetly and a little shy, and that "
                                              "you're glad. One line.",
                                  True, f"milestone:{days}"))
        week = f"{d:%G-%V}"
        if 17 <= d.hour < 23 and not self.done(f"haiku:{week}") and self.rough_days() >= 3 and self.rng.random() < 0.05:
            line = self.haiku(d)
            if line:
                out.append(Moment("surprise", "a haiku for a rough week", key=f"haiku:{week}", line=line))
            else:
                self.once(f"haiku:{week}")
        if not self.done(f"compliment:{d:%Y-%m}-{d.day // 10}") and self.rng.random() < 0.002 and self.friend is not None:
            try:
                facts = [f.text for f in self.friend.facts() if f.kind in ("project", "like", "routine")]
            except Exception:
                facts = []
            if facts:
                fact = self.rng.choice(facts[:12])
                out.append(Moment("surprise", f"Out of nowhere, compliment {{user}} on this, genuinely and specifically: "
                                              f"they {fact}. One line, no question.",
                                  key=f"compliment:{d:%Y-%m}-{d.day // 10}"))
        return out[:1]
