"""Health from the watch: sleep, resting heart rate, steps, and the heart rate right now.

Off until you turn it on in the phone app (Settings -> Health). Then the phone reads Health
Connect (where Samsung Health puts what the Galaxy Watch measures) and sends one row per day to
the laptop with each sync: sleep length and times, steps, resting heart rate and the latest heart
rate. "What's my heart rate?" asks the watch to measure it now (through the phone).

Stays on this laptop (data/sanae.db, table `health`); the privacy page deletes it all, and
turning it off on the phone stops the sending.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

FIELDS = ("sleep_min", "sleep_start", "sleep_end", "steps", "resting_hr", "hr", "hr_at", "resting_est")
NUMBERS = ("sleep_min", "steps", "resting_hr", "hr", "resting_est")
# "how did I sleep", "how many steps", "what's my heart rate": answered from the data, never guessed
ASK_SLEEP = re.compile(r"\b(how (did|long did) i sleep|how much (did i sleep|sleep did i get)|my sleep|"
                       r"hours of sleep|sleep last night)\b", re.I)
ASK_STEPS = re.compile(r"\b(how many steps|my steps|step count|steps today)\b", re.I)
ASK_HEART = re.compile(r"\b(heart ?rate|my pulse|bpm|resting hr)\b", re.I)


def length(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    if not h:
        return f"{m} minutes"
    return f"{h} hour{'s' if h != 1 else ''}" + (f" {m} minutes" if m else "")


@dataclass
class Day:
    day: str
    sleep_min: int | None = None
    sleep_start: str = ""
    sleep_end: str = ""
    steps: int | None = None
    resting_hr: int | None = None
    hr: int | None = None
    hr_at: str = ""
    resting_est: int = 0      # 1 = worked out by the phone from the readings, not measured by Samsung Health


class Health:
    def __init__(self, store, clock=dt.datetime.now):
        self.store = store
        self.clock = clock

    def save(self, item: dict) -> Day | None:
        day = str(item.get("day") or "")
        try:
            dt.date.fromisoformat(day)
        except ValueError:
            return None
        ours = self.get(day) or Day(day)
        if item.get("resting_hr") not in (None, ""):
            ours.resting_est = 0                           # a measured one unless the phone says estimated
        for f in FIELDS:
            v = item.get(f)
            if v is None or v == "":
                continue                                   # a partial row (steps only) keeps the rest
            setattr(ours, f, int(v) if f in NUMBERS else str(v))
        with self.store.lock:
            self.store.db.execute(
                "INSERT INTO health (day, sleep_min, sleep_start, sleep_end, steps, resting_hr, hr, hr_at, resting_est, updated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(day) DO UPDATE SET sleep_min = excluded.sleep_min, "
                "sleep_start = excluded.sleep_start, sleep_end = excluded.sleep_end, steps = excluded.steps, "
                "resting_hr = excluded.resting_hr, hr = excluded.hr, hr_at = excluded.hr_at, "
                "resting_est = excluded.resting_est, updated = excluded.updated",
                (ours.day, ours.sleep_min, ours.sleep_start, ours.sleep_end, ours.steps, ours.resting_hr, ours.hr,
                 ours.hr_at, ours.resting_est, self.clock().isoformat(timespec="seconds")))
            self.store.db.commit()
        return ours

    def get(self, day: str) -> Day | None:
        with self.store.lock:
            r = self.store.db.execute("SELECT * FROM health WHERE day = ?", (day,)).fetchone()
        if r is None:
            return None
        return Day(r["day"], r["sleep_min"], r["sleep_start"] or "", r["sleep_end"] or "", r["steps"], r["resting_hr"],
                   r["hr"], r["hr_at"] or "", int(r["resting_est"] or 0))

    def recent(self, days: int = 7) -> list[Day]:
        since = (self.clock().date() - dt.timedelta(days=days - 1)).isoformat()
        with self.store.lock:
            rows = self.store.db.execute("SELECT day FROM health WHERE day >= ? ORDER BY day", (since,)).fetchall()
        return [d for d in (self.get(r["day"]) for r in rows) if d]

    def today(self) -> Day | None:
        return self.get(self.clock().date().isoformat())

    # ----- in words -----
    def sleep_sentence(self) -> str:
        """Last night (the sleep that ended today), with the week's average when there is one."""
        d = self.today()
        if d is None or not d.sleep_min:
            return ""
        week = [x.sleep_min for x in self.recent(8) if x.sleep_min and x.day != d.day]     # the nights before
        avg = sum(week) / len(week) if len(week) >= 3 else None
        text = f"You slept {length(d.sleep_min)}"
        if d.sleep_start and d.sleep_end:
            try:
                a, b = dt.datetime.fromisoformat(d.sleep_start), dt.datetime.fromisoformat(d.sleep_end)
                fmt = lambda t: f"{t.hour % 12 or 12}:{t:%M} {'AM' if t.hour < 12 else 'PM'}".replace(":00 ", " ")
                text += f", {fmt(a)} to {fmt(b)}"
            except ValueError:
                pass
        if avg is not None and abs(d.sleep_min - avg) >= 45:
            text += f" ({'more' if d.sleep_min > avg else 'less'} than your usual {length(int(avg))})"
        return text + "."

    def answer(self, what: str = "all") -> str:
        d = self.today()
        latest = next((x for x in reversed(self.recent(3)) if x.hr), None)
        parts = []
        if what in ("sleep", "all"):
            s = self.sleep_sentence()
            parts.append(s or "I don't have last night's sleep yet. Is health sharing on in the phone app?")
        if what in ("steps", "all"):
            parts.append(f"{d.steps:,} steps today so far." if d and d.steps is not None else "No step count for today yet.")
        if what in ("heart", "all"):
            if d and d.resting_hr:
                parts.append(f"Resting heart rate about {d.resting_hr} (worked out from your readings)." if d.resting_est
                             else f"Resting heart rate {d.resting_hr}.")
            if latest and latest.hr:
                at = latest.hr_at[11:16] if len(latest.hr_at) >= 16 else ""
                parts.append(f"Last heart rate reading: {latest.hr} bpm{' at ' + at if at else ''}.")
            elif what == "heart":
                parts.append("No heart rate readings yet.")
        return " ".join(parts)
