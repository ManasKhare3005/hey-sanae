"""Morning briefing: the first time you wake her after 5 AM she runs through the day.

Weather (Open-Meteo, no key), classes, what's due, the first thing on the calendar, reminders
and the todo list, one short sentence each, spoken sentence by sentence so "skip" or "stop"
ends it. Once a day (kv "briefing:last"); if the first thing you say is a request, she answers
that first and the briefing follows. "Brief me" / "morning rundown" gives it any time.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import random
import re
import time
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

# What a "just saying hi" first request looks like: the briefing is the answer
GREETING = re.compile(r"^\W*((good )?(morning|mornin'?)|hi|hey|hello|yo|sup|what'?s up|i'?m (up|awake)|"
                      r"how'?s it going|wake up)(,? (sanae|sanai|there|girl|you))?\W*$", re.I)
ASK = re.compile(r"\b(brief me|(morning|daily) (briefing|rundown|update)|my briefing|the briefing|"
                 r"give me (my|the) rundown|run me through (my|the) day)\b", re.I)
# The 4b model made weather up ("around 15°C") and answered "my day" from an earlier reply
WEATHER_ASK = re.compile(r"\b(what'?s the weather|how'?s the weather|weather (like |today|outside|now)|"
                         r"(is it|will it|is it going to|gonna) (rain|snow|storm)|how (hot|cold|warm|chilly) is it|"
                         r"temperature (outside|today|right now)|do i need (an umbrella|a jacket|a coat))\b", re.I)
DAY_ASK = re.compile(r"\b(what does my day look like|how'?s my day (look|shap)ing|what'?s (on )?(for )?today(?!'?s)|"
                     r"what do i have today|what'?s my day like)\b", re.I)    # not "what's today's photo challenge"
# First requests after which a briefing would be unwelcome
NOT_NOW = {"free_gpu", "quiet_for", "power", "lock_screen", "hide_avatar", "morning_briefing"}

WEATHER = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "cloudy", 45: "foggy", 48: "foggy",
           51: "drizzly", 53: "drizzly", 55: "drizzly", 56: "icy drizzle", 57: "icy drizzle",
           61: "light rain", 63: "rainy", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
           71: "light snow", 73: "snowy", 75: "heavy snow", 77: "snowy", 80: "showers", 81: "showers",
           82: "heavy showers", 85: "snow showers", 86: "snow showers", 95: "thunderstorms",
           96: "thunderstorms", 99: "thunderstorms"}
OPENERS = ["[happy][wave] Good morning!", "[happy] Morning! Here's your day.", "[happy][wave] Rise and shine!",
           "[happy] Good morning! Quick rundown."]


def _hm(t: dt.datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


class Weather:
    """Today's weather from Open-Meteo, cached for 30 minutes."""

    def __init__(self, latitude: float, longitude: float, units: str = "fahrenheit", fetch=None, ttl_s: float = 1800):
        self.latitude, self.longitude, self.units = latitude, longitude, units
        self.fetch = fetch or self._fetch
        self.ttl_s = ttl_s
        self._cache: tuple[float, dict] | None = None

    def _fetch(self) -> dict:
        q = urllib.parse.urlencode({
            "latitude": self.latitude, "longitude": self.longitude, "timezone": "auto", "forecast_days": 1,
            "current": "temperature_2m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
            "temperature_unit": self.units})
        with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{q}", timeout=5) as r:
            return json.loads(r.read().decode())

    def today(self) -> dict | None:
        if self._cache and time.time() - self._cache[0] < self.ttl_s:
            return self._cache[1]
        try:
            data = self.fetch()
            cur, day = data.get("current") or {}, data.get("daily") or {}
            first = lambda key: (day.get(key) or [None])[0]
            out = {"now": cur.get("temperature_2m"), "code": cur.get("weather_code", first("weather_code")),
                   "high": first("temperature_2m_max"), "low": first("temperature_2m_min"),
                   "rain": first("precipitation_probability_max"), "day_code": first("weather_code")}
        except Exception as exc:
            log.warning("weather unavailable: %s", exc)
            return None
        self._cache = (time.time(), out)
        return out

    def sentence(self, rain_always: bool = False) -> str:
        """`rain_always`: say the chance of rain even when it's low ("is it going to rain?")."""
        w = self.today()
        if not w or w.get("now") is None:
            return ""
        sky = WEATHER.get(int(w["code"] or 0), "")
        text = f"It's {round(w['now'])} degrees{' and ' + sky if sky else ''} now"
        if w.get("high") is not None:
            text += f", with a high of {round(w['high'])}"
        rain = w.get("rain") or 0
        if rain >= 30 or rain_always:
            text += f" and a {round(rain)}% chance of rain"
        later = WEATHER.get(int(w.get("day_code") or 0), "")
        if rain < 30 and later in ("thunderstorms", "snowy", "heavy snow"):
            text += f", {later} later"
        return text + "."


class Briefing:
    def __init__(self, ctx, cfg: dict | None = None, clock=time.time, weather: Weather | None = None):
        cfg = cfg or {}
        self.ctx = ctx
        self.clock = clock
        self.from_hour = int(cfg.get("from_hour", 5))
        self.until_hour = int(cfg.get("until_hour", 12))
        loc = cfg.get("location") or {}
        self.weather = weather if weather is not None else (
            Weather(float(loc["latitude"]), float(loc["longitude"]), cfg.get("units", "fahrenheit"))
            if loc.get("latitude") is not None and loc.get("longitude") is not None else None)

    # ----- once a day -----
    def _kv(self, key, value=None):
        memory = getattr(self.ctx, "memory", None)
        if memory is None:
            return None
        with memory.lock:
            if value is None:
                row = memory.db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
                return row["value"] if row else None
            memory.db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                              (key, value))
            memory.db.commit()

    def due(self) -> bool:
        """The first wake after `from_hour` (until `until_hour`) that hasn't had one today."""
        now = dt.datetime.fromtimestamp(self.clock())
        if not self.from_hour <= now.hour < self.until_hour:
            return False
        return self._kv("briefing:last") != now.date().isoformat()

    def mark(self):
        self._kv("briefing:last", dt.datetime.fromtimestamp(self.clock()).date().isoformat())

    # ----- what she says -----
    def sentences(self) -> list[str]:
        from .digest import gather

        now = dt.datetime.fromtimestamp(self.clock())
        out = []
        if self.weather is not None:
            w = self.weather.sentence()
            if w:
                out.append(w)
        health = getattr(self.ctx, "health", None)
        if health is not None:
            sleep = health.sleep_sentence()
            if sleep:
                out.append(sleep)
        plan = gather(self.ctx, now.date())
        classes = [c for c in plan.classes if c.start + dt.timedelta(minutes=50) > now]
        if classes:
            out.append(("Class: " if len(classes) == 1 else "Classes: ")
                       + _join([f"{c.course or c.title} at {_hm(c.start)}" for c in classes[:3]]) + ".")
        if plan.due_today:
            out.append("Due today: " + _join([i.title + (f" for {i.course}" if i.course else "") + f" {i.when}"
                                              for i in plan.due_today[:3]]) + ".")
        elif plan.due_soon:
            first = plan.due_soon[0]
            out.append(f"Nothing due today; next up is {first.title}, {first.start:%A}.")
        events = [e for e in plan.events if e.all_day or e.end > now]
        if events:
            e = events[0]
            when = "today" if e.all_day else f"at {_hm(e.start)}"
            more = f", plus {len(events) - 1} more" if len(events) > 1 else ""
            out.append(f"First on your calendar: {e.title} {when}{more}.")
        reminders = [r for r in plan.reminders if r.due > now]
        if reminders:
            out.append("Reminders: " + _join([f"{r.text} at {_hm(r.due)}" for r in reminders[:2]]) + ".")
        todos = getattr(self.ctx, "todos", None)
        if todos is not None:
            items = todos.open()
            if items:
                names = [t.text for t in items[:3]] + ([f"{len(items) - 3} more"] if len(items) > 3 else [])
                out.append("On your list: " + _join(names) + ".")
        chores = getattr(self.ctx, "chores", None)
        if chores is not None:
            routine = chores.briefing_sentence()
            if routine:
                out.append(routine)
        if len(out) <= (1 if self.weather is not None else 0):
            out.append("Nothing on the schedule today. A free day!")
        return out

    def opener(self) -> str:
        from .timesense import fix

        return fix(random.choice(OPENERS))      # "brief me" at 3 PM: not "Good morning!"

    def text(self) -> str:
        """The whole briefing as one reply (typed / phone / "brief me")."""
        return " ".join(self.sentences())

    def deliver(self, say, line=lambda s: s, add_said=lambda s: None, after_request: bool = False) -> bool:
        """Speak it sentence by sentence; say(sentence) -> "stop"/"wake" when cut off. Returns
        False if the user cut it short. `line` turns her tagged opener into speech (face on)."""
        self.mark()
        from .timesense import fix

        opener = fix("[happy] Oh, and good morning! Quick rundown.") if after_request else self.opener()
        spoken = []
        for i, sentence in enumerate([opener] + self.sentences()):
            text = line(sentence) if i == 0 else sentence
            spoken.append(text)
            if say(text):
                add_said(" ".join(spoken) + " (cut short)")
                return False
        add_said(" ".join(spoken))
        return True

