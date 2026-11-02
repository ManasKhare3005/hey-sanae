"""Looking after you: what the watch says (health.py) and the basics (food, water).

From the watch, at most once a day each, only while you're at the laptop:
  - morning: a short night (< 6 h) -> "rough night, go easy today"; a long one (>= 7.5 h) is a win;
  - evening: under 3,000 steps -> "walk with me?" (she's on your phone); 10,000+ is a win;
  - once a week: resting heart rate up 5+ bpm on the last 3 weeks -> a gentle "you've been running
    hot, maybe sleep / stress?" (never a diagnosis).
Saying you're tired after a short night adds the night to the request ("you slept 5 hours").

Basics: "I ate" / "had lunch" is noted (kv care:ate, the time only); at lunch and dinner time,
if you've been at the laptop and haven't mentioned food, "did you eat?"; one water nudge in the
afternoon some days.
"""
from __future__ import annotations

import datetime as dt
import random
import re
import time

from .health import length
from .initiative import Moment
from .part import Part, in_hours

ATE = re.compile(r"\b(i |just )?(ate|eating|had (lunch|dinner|breakfast|a snack|food|something)|grabbed (food|lunch|dinner|a bite)|"
                 r"ordered (food|pizza|dinner|lunch)|cooking|cooked|made (dinner|lunch|breakfast|food)|getting food)\b", re.I)
MEALS = {"lunch": ("13:00", "15:30"), "dinner": ("19:30", "22:00")}
USING_S = 120


class Care(Part):
    name = "care"

    def __init__(self, store=None, clock=time.time, health=None, wins=None, idle=lambda: 0.0, rng=None):
        super().__init__(store, clock)
        self.health = health
        self.wins = wins
        self.idle = idle
        self.rng = rng or random.Random()

    def _day(self, offset: int = 0):
        if self.health is None:
            return None
        try:
            return self.health.get((self.now().date() + dt.timedelta(days=offset)).isoformat())
        except Exception:
            return None

    # ----- talking first -----
    def moments(self, now: float) -> list[Moment]:
        if self.idle() > USING_S:
            return []
        d = self.now()
        today = d.date().isoformat()
        out = []
        day = self._day()
        if day is not None and day.sleep_min and 6 <= d.hour < 13 and not self.done(f"sleep:{today}"):
            if day.sleep_min < 360:
                out.append(Moment("wellbeing", f"From their watch: {{user}} slept only {length(day.sleep_min)} last night. "
                                          "Say something caring about it in one line (go easy today, coffee, maybe a nap "
                                          "later). No lecture.", key=f"sleep:{today}"))
            elif day.sleep_min >= 450 and self.wins is not None:
                self.wins.add(f"sleep:{today}", f"slept a solid {length(day.sleep_min)} last night")
                self.once(f"sleep:{today}")
        if day is not None and day.steps is not None and 17 <= d.hour < 21 and not self.done(f"steps:{today}"):
            if day.steps < 3000 and d.hour >= 18:
                out.append(Moment("wellbeing", f"From their watch: {{user}} has only {day.steps:,} steps today. Suggest a short "
                                          "walk, playfully (you can come along on their phone). One line.",
                                  key=f"steps:{today}"))
            elif day.steps >= 10000 and self.wins is not None:
                self.wins.add(f"steps:{today}", f"walked {day.steps:,} steps today")
                self.once(f"steps:{today}")
        week = f"{d:%G-%V}"
        if d.hour >= 10 and not self.done(f"hr:{week}"):
            rise = self.resting_rise()
            if rise is not None and rise[0] - rise[1] >= 5:
                out.append(Moment("wellbeing", f"From their watch: {{user}}'s resting heart rate is about {rise[0]} this week, "
                                          f"up from about {rise[1]}. Mention it gently and casually (often it's short sleep, "
                                          "stress or a cold); ask how they've been. No diagnosis, no alarm.",
                                  key=f"hr:{week}"))
            else:
                self.once(f"hr:{week}")
        for meal, (start, end) in MEALS.items():
            key = f"{meal}:{today}"
            if in_hours(d, start, end) and not self.done(key) and not self._ate_since(start):
                if self.rng.random() < 0.05:          # ~15 min into the window on average (30 s ticks)
                    out.append(Moment("wellbeing", f"It's {meal} time and {{user}} has been at the laptop; you don't know if "
                                              f"they've eaten. Ask casually if they had {meal} (one line, caring, not a nag).",
                                      key=key))
                    break
        if in_hours(d, "15:00", "18:00") and not self.done(f"water:{today}") and self.rng.random() < 0.002:   # some days
            out.append(Moment("wellbeing", "A tiny caring nudge to drink some water, playful, one line.", key=f"water:{today}"))
        return out[:1]

    def resting_rise(self) -> tuple[int, int] | None:
        """(this week's average resting heart rate, the three weeks before), with enough days of each."""
        if self.health is None:
            return None
        try:
            days = self.health.recent(28)
        except Exception:
            return None
        cut = (self.now().date() - dt.timedelta(days=6)).isoformat()
        new = [x.resting_hr for x in days if x.resting_hr and x.day >= cut]
        old = [x.resting_hr for x in days if x.resting_hr and x.day < cut]
        if len(new) < 4 or len(old) < 7:
            return None
        return round(sum(new) / len(new)), round(sum(old) / len(old))

    def _ate_since(self, start: str) -> bool:
        ate = self.get("ate", 0)
        h, m = (int(x) for x in start.split(":"))
        since = self.now().replace(hour=h, minute=m, second=0, microsecond=0) - dt.timedelta(hours=2)
        return ate >= since.timestamp()

    # ----- on a request -----
    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        out = []
        if ATE.search(user_text) and not re.search(r"\b(haven'?t|didn'?t|not)\b", user_text, re.I):
            self.put("ate", self.clock())
        from .mood import user_mood

        theirs = user_mood(user_text)
        if theirs and theirs[0] == "tired":
            day = self._day()
            if day is not None and day.sleep_min and day.sleep_min < 390:
                out.append(f"From their watch: they slept only {length(day.sleep_min)} last night; that's likely why. "
                           "Mention it kindly if it fits")
        return out
