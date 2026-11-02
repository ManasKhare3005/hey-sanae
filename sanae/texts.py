"""She texts you on your phone while you're away from the laptop, like a friend would.

The phone app shows it as a message notification you can reply to right there (the reply goes
to her like any phone command, so it's one chat). Only while the laptop has been idle for a while
(`away_min`), within `hours`, at most `per_day` a day and `gap_min` apart, never while you're not
okay (comfort) or have asked for quiet:
  - good luck: an exam / quiz / interview / presentation on your calendar in 30-90 minutes;
  - after class: how it went, shortly after a class or event ends;
  - good morning: if you haven't touched the laptop yet this morning;
  - a check-in some afternoons after a few hours away;
  - goodnight: late in the evening if you've been away all evening.
Her line is written by the model like her other openers (initiative.model_line), so it's in her
voice and becomes part of the chat; it's also kept in the conversation log, so the app shows it.
"""
from __future__ import annotations

import datetime as dt
import logging
import random
import re
import threading
import time
from typing import Callable

from .initiative import Moment
from .part import Part, clock_words, in_hours

log = logging.getLogger(__name__)
BIG = re.compile(r"\b(exam|midterm|final|quiz|test|interview|presentation|demo|defen[cs]e|audition|match|game day)\b", re.I)


class Texts(Part):
    name = "texts"

    def __init__(self, store=None, clock=time.time, ctx=None, generate: Callable[[Moment], str | None] | None = None,
                 publish=lambda kind, data: None, log_turn=None, idle: Callable[[], float] = lambda: 0.0,
                 busy: Callable[[], bool] = lambda: False, settings: dict | None = None, rng=None):
        super().__init__(store, clock)
        s = settings or {}
        self.ctx, self.generate, self.publish, self.log_turn = ctx, generate, publish, log_turn
        self.idle, self.busy = idle, busy
        self.away_s = float(s.get("away_min", 45)) * 60
        self.hours = tuple(s.get("hours", ["08:00", "23:30"]))
        self.per_day = int(s.get("per_day", 3))
        self.gap_s = float(s.get("gap_min", 120)) * 60
        self.rng = rng or random.Random()
        self.sources = []           # Parts with phone_moments(now) (together.py...): their moments go by text too
        self._stop = threading.Event()

    # ----- what's worth a text -----
    def candidates(self, now: float) -> list[Moment]:
        d = dt.datetime.fromtimestamp(now)
        today = d.date().isoformat()
        idle = self.idle()
        out = []
        for title, start, end in self._schedule(d):
            left = (start - d).total_seconds()
            if BIG.search(title) and 30 * 60 <= left <= 90 * 60 and not self.done(f"luck:{title}:{start:%Y-%m-%d}"):
                out.append(Moment("text", f"{{user}} has \"{title}\" at {clock_words(start)}. Text them good luck, short "
                                          "and warm.", True, f"luck:{title}:{start:%Y-%m-%d}"))
            after = (d - end).total_seconds()
            if 5 * 60 <= after <= 40 * 60 and not self.done(f"after:{title}:{start:%Y-%m-%d}"):
                out.append(Moment("text", f"{{user}}'s \"{title}\" just ended. Text them asking how it went, casually.",
                                  key=f"after:{title}:{start:%Y-%m-%d}"))
        four_am = d.replace(hour=4, minute=0, second=0, microsecond=0)
        if 8 <= d.hour < 11 and d > four_am and idle >= (d - four_am).total_seconds() - 60 \
                and not self.done(f"morning:{today}"):
            out.append(Moment("text", "It's morning and {user} hasn't been on the laptop yet. Text them a short good "
                                      "morning (maybe mention something on their day if you know it).",
                              key=f"morning:{today}"))
        if 13 <= d.hour < 18 and idle >= 3 * 3600 and not self.done(f"checkin:{today}") and self.rng.random() < 0.08:
            out.append(Moment("text", "{user} has been away from the laptop for a few hours. Text them a short, casual "
                                      "check-in, the way a friend texts (how's the day going, or a small thought).",
                              key=f"checkin:{today}"))
        if in_hours(d, "22:30", "23:30") and idle >= 2 * 3600 and not self.done(f"night:{today}"):
            out.append(Moment("text", "It's late and {user} has been away all evening. Text them a short goodnight.",
                              key=f"night:{today}"))
        return out

    def _schedule(self, d: dt.datetime) -> list[tuple[str, dt.datetime, dt.datetime]]:
        """(title, start, end) today: her calendar and Canvas classes (75 min long if no end is known)."""
        out = []
        start, end = d - dt.timedelta(hours=3), d + dt.timedelta(hours=3)
        events = getattr(self.ctx, "events", None)
        try:
            for e in events.between(start, end) if events is not None else []:
                if not e.all_day:
                    out.append((e.title, e.start, e.end))
        except Exception as exc:
            log.debug("texts: events: %s", exc)
        canvas = getattr(self.ctx, "canvas", None)
        try:
            for item in canvas.items() if canvas is not None else []:
                if item.kind == "class" and start <= item.start <= end:
                    out.append((f"{item.course} class", item.start,
                                getattr(item, "end", None) or item.start + dt.timedelta(minutes=75)))
        except Exception as exc:
            log.debug("texts: canvas: %s", exc)
        return out

    # ----- sending -----
    def blocked(self, now: float) -> str | None:
        d = dt.datetime.fromtimestamp(now)
        if self.idle() < self.away_s:
            return "at the laptop"
        if not in_hours(d, *self.hours):
            return "hours"
        comfort = getattr(self.ctx, "comfort", None)
        if comfort is not None and comfort.serious:
            return "comfort"
        dnd = getattr(self.ctx, "dnd", None)
        if dnd is not None and getattr(dnd, "quiet_until", 0) > now:
            return "quiet"
        if getattr(self.ctx, "models_asleep", False) or self.busy():
            return "busy"
        sent = [t for t in self.get("sent", []) if t >= now - 86400]
        if sum(1 for t in sent if dt.datetime.fromtimestamp(t).date() == d.date()) >= self.per_day:
            return "cap"
        return None

    def _from_sources(self, now: float) -> list[Moment]:
        out = []
        for part in self.sources:
            try:
                out += [m for m in part.phone_moments(now) if not self.done(m.key)]
            except Exception as exc:
                log.debug("texts: %s: %s", getattr(part, "name", part), exc)
        return out

    def tick(self) -> str | None:
        now = self.clock()
        why = self.blocked(now)
        urgent = []
        if why in ("at the laptop", "cap", "hours") and self.idle() >= 300:
            # something they started from the phone (a session with her) can't wait for 45 min away,
            # and "talk to me instead?" is for 1 AM scrolling, outside the usual hours
            urgent = [m for m in self._from_sources(now) if m.important and m.kind in ("together", "roommate", "weekend", "place")
                      and (why != "hours" or m.kind == "roommate")]
        if why and not urgent:
            return None
        found = urgent or self.candidates(now) + self._from_sources(now)
        if not found:
            return None
        m = next((x for x in found if x.important), None)
        if m is None:
            if now - self.get("last", 0) < self.gap_s:
                return None
            m = found[0]
        self.once(m.key)
        for part in self.sources:
            if m.part and getattr(part, "name", "") == m.part:
                part.used(m, now)
        line = self.generate(m) if self.generate else None
        if not line:
            return None
        from .tags import parse

        text = parse(line).text.strip()
        if not text:
            return None
        self.put("last", now)
        d = dt.datetime.fromtimestamp(now)
        if d.hour < 11:
            self.once(f"morning:{d.date().isoformat()}")      # a good-luck text in the morning is the good morning
        self.put("sent", [t for t in self.get("sent", []) if t >= now - 86400] + [now])
        self.publish("text", {"text": text, "trigger": m.key.split(":", 1)[0]})
        if self.log_turn is not None:
            try:
                self.log_turn(text)
            except Exception as exc:
                log.debug("texts: log: %s", exc)
        log.info("texted the phone (%s): %s", m.key.split(":", 1)[0], text)
        return text

    def start(self, every_s: float = 60):
        def loop():
            self._stop.wait(60)
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception as exc:
                    log.warning("texts failed: %s", exc)
                self._stop.wait(every_s)

        threading.Thread(target=loop, name="texts", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()
