"""Wind-down at midnight: the phone goes quiet, she says goodnight, and the morning alarm is set.

The phone does the work at 12 AM by itself (WindDown.kt: Do Not Disturb if you allowed it, her
goodnight as a notification, an alarm), so it works with the laptop off. When the laptop answers,
the phone asks it here (GET /api/winddown) for:
  - when to wake you: 90 minutes before tomorrow's first class or event (never before `earliest`),
    else your usual time (`wake`, persona.yaml friend.winddown);
  - her goodnight line, mentioning the alarm and why.
If you're still at the laptop at midnight she says goodnight there too, once, and offers a story.
"""
from __future__ import annotations

import datetime as dt
import random
import time

from .initiative import Moment
from .part import Part, clock_words

LINES = ["It's midnight, {user}. I'm putting your phone on quiet now. {alarm} Sleep well.",
         "Okay, wind-down time. Phone's going quiet. {alarm} Goodnight, {user}.",
         "Midnight! Time to rest those eyes, {user}. {alarm} I'll be here in the morning.",
         "Goodnight, {user}. Your phone's quiet now. {alarm} Sweet dreams."]


class WindDown(Part):
    name = "winddown"

    def __init__(self, store=None, clock=time.time, ctx=None, idle=lambda: 0.0, settings: dict | None = None,
                 user: str = "you", rng=None):
        super().__init__(store, clock)
        s = settings or {}
        self.ctx, self.idle, self.user = ctx, idle, user
        self.at = str(s.get("at", "00:00"))
        self.wake = str(s.get("wake", "08:30"))
        self.earliest = str(s.get("earliest", "06:00"))
        self.before_min = int(s.get("before_min", 90))
        self.rng = rng or random.Random()

    def _first_tomorrow(self, d: dt.datetime) -> tuple[str, dt.datetime] | None:
        day = (d - dt.timedelta(hours=4)).date() + dt.timedelta(days=1)       # at 00:30 "tomorrow" is today
        start, end = dt.datetime.combine(day, dt.time(4, 0)), dt.datetime.combine(day, dt.time(14, 0))
        found = []
        events = getattr(self.ctx, "events", None)
        try:
            found += [(e.title, e.start) for e in (events.between(start, end) if events is not None else []) if not e.all_day]
        except Exception:
            pass
        canvas = getattr(self.ctx, "canvas", None)
        try:
            found += [(f"{i.course} class", i.start) for i in (canvas.items() if canvas is not None else [])
                      if i.kind == "class" and start <= i.start <= end]
        except Exception:
            pass
        return min(found, key=lambda x: x[1]) if found else None

    def plan(self, d: dt.datetime | None = None, usual: str | None = None) -> dict:
        """{wake: 'HH:MM', why, line}: tomorrow's alarm and her goodnight. `usual`: the phone's own
        usual wake time, if set there."""
        d = d or self.now()
        day = (d - dt.timedelta(hours=4)).date() + dt.timedelta(days=1)
        usual = dt.datetime.combine(day, dt.time.fromisoformat(usual or self.wake))
        earliest = dt.datetime.combine(day, dt.time.fromisoformat(self.earliest))
        wake, why = usual, ""
        first = self._first_tomorrow(d)
        if first is not None:
            t = first[1] - dt.timedelta(minutes=self.before_min)
            t = t.replace(minute=t.minute - t.minute % 5, second=0, microsecond=0)
            if t < usual:
                wake, why = max(t, earliest), f"{first[0]} at {clock_words(first[1])}"
        alarm = f"Alarm's set for {clock_words(wake)}" + (f", you've got {why}." if why else ".")
        line = self.rng.choice(LINES).format(user=self.user, alarm=alarm)
        return {"wake": f"{wake:%H:%M}", "why": why, "line": line, "at": self.at}

    def moments(self, now: float) -> list[Moment]:
        d = dt.datetime.fromtimestamp(now)
        h, m = (int(x) for x in self.at.split(":"))
        start = d.replace(hour=h, minute=m, second=0, microsecond=0)
        if d < start:
            start -= dt.timedelta(days=1)
        if not (0 <= (d - start).total_seconds() <= 20 * 60) or self.idle() > 300:
            return []
        key = f"night:{start.date().isoformat()}"
        if self.done(key):
            return []
        p = self.plan(d)
        story = " and offer a bedtime story if they want one (\"tell me a story\")" \
            if getattr(self.ctx, "stories", None) is not None else ""
        return [Moment("winddown", f"It's {clock_words(d)}, wind-down time, and {{user}} is still at the laptop. Say "
                                   f"goodnight warmly: their phone is going quiet now, alarm at {clock_words(dt.datetime.strptime(p['wake'], '%H:%M'))}"
                                   + (f" (for {p['why']})" if p["why"] else "") + f"{story}. No lecture. Two short lines.",
                       True, key, part=self.name)]

    def status(self) -> dict:
        return self.plan()
