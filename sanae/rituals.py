"""Little rituals, the way close friends have their things:
  - highs and lows: some evenings (default Mon/Wed/Fri) the evening check-in becomes "what was
    the best and worst bit of today?" (it replaces the plain check-in that day);
  - Monday kickoff: Monday morning, one line about the week ahead (and your goals);
  - Friday: "any plans for the weekend?";
  - Sunday plan-the-week: what's coming up in the next seven days (her calendar, Canvas), and
    whether you want reminders for any of it.
Each at most once on its day, while you're at the laptop, through the normal initiative checks.
"""
from __future__ import annotations

import datetime as dt
import random
import time

from .initiative import Moment
from .part import Part, clock_words, in_hours

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class Rituals(Part):
    name = "rituals"

    def __init__(self, store=None, clock=time.time, ctx=None, goals=None, settings: dict | None = None,
                 idle=lambda: 0.0, rng=None):
        super().__init__(store, clock)
        s = settings or {}
        self.ctx, self.goals, self.idle = ctx, goals, idle
        self.highs = [d[:3].lower() for d in s.get("highs_lows", ["mon", "wed", "fri"])]
        self.plan_day = str(s.get("plan_week", "sun") or "")[:3].lower()
        self.weekend_day = str(s.get("weekend", "fri") or "")[:3].lower()
        self.monday = bool(s.get("monday", True))
        self.checkin = tuple(s.get("checkin", ["20:00", "23:00"]))
        self.rng = rng or random.Random()

    def week_ahead(self, d: dt.datetime) -> list[str]:
        start, end = d, d + dt.timedelta(days=7)
        out = []
        events = getattr(self.ctx, "events", None)
        try:
            for e in events.between(start, end) if events is not None else []:
                out.append(f"{e.title} ({e.start:%a}" + ("" if e.all_day else f" {clock_words(e.start)}") + ")")
        except Exception:
            pass
        canvas = getattr(self.ctx, "canvas", None)
        try:
            for item in canvas.items() if canvas is not None else []:
                if item.kind == "assignment" and start <= item.start < end:
                    out.append(f"{item.title} due {item.start:%a}")
        except Exception:
            pass
        return out[:8]

    def moments(self, now: float) -> list[Moment]:
        if self.idle() > 120:
            return []
        d = self.now()
        day = DAYS[d.weekday()]
        today = d.date().isoformat()
        out = []
        if day in self.highs and in_hours(d, *self.checkin) and not self.done(f"highs:{today}") \
                and self.rng.random() < 0.25:
            out.append(Moment("ritual", "Your little evening ritual with {user}: ask for their high and low of the day "
                                        "(the best bit and the worst bit), playfully. One short line.",
                              key=f"highs:{today}"))
        if self.monday and day == "mon" and 8 <= d.hour < 12 and not self.done(f"monday:{today}"):
            goals = "; ".join(g["text"] for g in self.goals.all()) if self.goals is not None else ""
            week = self.week_ahead(d)
            what = (f" This week: {', '.join(week[:4])}." if week else "") + (f" Their goals: {goals}." if goals else "")
            out.append(Moment("ritual", "It's Monday morning. One upbeat line to kick off the week with {user}" +
                              (f", mentioning one thing coming up.{what}" if what else ", no lecture."),
                              key=f"monday:{today}"))
        if day == self.weekend_day and 16 <= d.hour < 21 and not self.done(f"weekend:{today}") \
                and getattr(self.ctx, "weekend", None) is None:          # weekend.py asks (and plans) instead
            out.append(Moment("ritual", "It's Friday. Casually ask {user} if they've got plans for the weekend.",
                              key=f"weekend:{today}"))
        if day == self.plan_day and 18 <= d.hour < 21 and not self.done(f"plan:{today}"):
            week = self.week_ahead(d)
            if week:
                out.append(Moment("ritual", f"Sunday evening: help {{user}} look at the week ahead. Coming up: "
                                            f"{', '.join(week)}. Mention the one or two that matter most and ask if they "
                                            "want reminders for any. Two short lines at most.", key=f"plan:{today}"))
        return out[:1]

    def replaces_checkin(self, d: dt.datetime) -> bool:
        """On highs-and-lows evenings the plain "how did today go?" (initiative.py) stays quiet."""
        return DAYS[d.weekday()] in self.highs
