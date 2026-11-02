"""Home: when your phone joins your home Wi-Fi, she knows you got home.

The phone decides (Settings -> Home Wi-Fi: "this is my home Wi-Fi"; it checks the network itself
and sends only "arrived" / "left" with the time, never a location or the network's name):
POST /api/phone/place. Here:
  - got home after being out a while (20+ minutes): a warm "welcome home" (said at the laptop, or a
    text if the laptop's idle), mentioning what's next tonight if something is;
  - while you're out / just home, a short note for her replies ("you're out", "they just got home").
"""
from __future__ import annotations

import datetime as dt
import time

from .initiative import Moment
from .part import Part, clock_words

AWAY_MIN_S = 20 * 60
WELCOME_S = 15 * 60
FRESH_S = 2 * 3600


class Place(Part):
    name = "place"

    def __init__(self, store=None, clock=time.time, ctx=None, idle=lambda: 0.0):
        super().__init__(store, clock)
        self.ctx, self.idle = ctx, idle

    def report(self, event: str, at: float | None = None) -> str | None:
        """'arrived' / 'left' from the phone. Returns what happened ('welcome' when it's worth a hello)."""
        at = float(at or self.clock())
        s = self.get("state") or {"home": None, "since": 0.0}
        if event == "left":
            if s.get("home") is False:
                return None
            self.put("state", {"home": False, "since": at})
            return "left"
        if event != "arrived" or s.get("home") is True:
            return None
        away = at - s["since"] if s.get("home") is False and s.get("since") else None
        self.put("state", {"home": True, "since": at, "away_s": away})
        return "welcome" if away is not None and away >= AWAY_MIN_S else "arrived"

    def state(self) -> dict:
        return self.get("state") or {"home": None, "since": 0.0}

    def _next_tonight(self, d: dt.datetime) -> str:
        events = getattr(self.ctx, "events", None)
        try:
            later = [e for e in events.between(d, d.replace(hour=23, minute=59)) if not e.all_day] if events is not None else []
        except Exception:
            later = []
        if later:
            e = later[0]
            return f" Next up today: {e.title} at {clock_words(e.start)}."
        together = getattr(self.ctx, "together", None)
        try:
            left = [a["title"] for a in together.open_today()] if together is not None else []
        except Exception:
            left = []
        return f" Still on your shared daily list today: {', '.join(left[:2])}." if left else ""

    def _welcome(self, now: float) -> list[Moment]:
        s = self.state()
        if not s.get("home") or not s.get("away_s") or s["away_s"] < AWAY_MIN_S or now - s["since"] > WELCOME_S:
            return []
        key = f"home:{int(s['since'])}"
        if self.done(key):
            return []
        d = dt.datetime.fromtimestamp(now)
        hours = s["away_s"] / 3600
        away = ("since yesterday" if hours >= 16 else "most of the day" if hours >= 8 else f"{round(hours)} hours" if hours >= 1.5
                else "about an hour" if hours >= 0.75 else "a little while")
        return [Moment("place", f"{{user}} just got home (their phone joined the home Wi-Fi) after being out {away}. "
                                f"Welcome them home, warm and short.{self._next_tonight(d)} One or two lines.",
                       True, key, part=self.name)]

    def moments(self, now: float) -> list[Moment]:
        return self._welcome(now)

    def phone_moments(self, now: float) -> list[Moment]:
        return self._welcome(now)

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        s = self.state()
        now = self.clock()
        if s.get("home") is False and s.get("since"):
            return [f"They're out (not home since {clock_words(dt.datetime.fromtimestamp(s['since']))})"]
        if s.get("home") and s.get("away_s") and now - s["since"] < FRESH_S:
            mins = int((now - s["since"]) // 60)
            return [f"They got home {mins} minutes ago" if mins >= 2 else "They just got home"]
        return []

    def status(self) -> dict:
        s = self.state()
        return {"home": s.get("home"), "since": s.get("since") or None}
