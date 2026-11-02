"""What makes your good days: patterns between how your days felt and what you did, worked out in code.

  - How a day felt: the diary's mood for that day (diary.py writes one every day you talk), and the
    last two weeks of daily mood counts (mood.py) for days the diary hasn't written yet. "great" and
    "good" are good days; stressed / tired / low / frustrated / a hard day are rough ones.
  - What you did: steps and sleep (health.py, from the watch), the photo-a-day challenge, the daily
    list you do together, a page in your shared notebook, cooking dinner, a late night up past 1 AM.
  - A pattern needs at least MIN_EACH days with and MIN_EACH without, and a real gap in how often
    those days were good (GAP). The numbers are the real counts, nothing guessed.
  - She brings one up now and then in the evening ("I noticed something..."), once a week at most,
    and "what makes my good days?" answers from the same numbers. The phone shows them (Us -> Good days).
"""
from __future__ import annotations

import datetime as dt
import re
import time

from .initiative import Moment
from .part import Part

MIN_EACH = 4
GAP = 0.25
LOOKBACK = 120
GOOD = ("great", "good")
ROUGH = ("stressed", "tired", "low", "frustrated", "a hard day")
# key, how it reads in a sentence, a short label for the phone
FACTORS = [
    ("walked", "days you walked 6,000+ steps", "Walking 6k+ steps"),
    ("slept", "days after 7+ hours of sleep", "7+ hours of sleep"),
    ("photo", "days you did the photo challenge", "The photo challenge"),
    ("together", "days you did something from our daily list", "Our daily list"),
    ("journal", "days you wrote in our notebook", "Writing in our notebook"),
    ("cooked", "days you cooked dinner", "Cooking dinner"),
    ("late", "days after a night up past 1 AM", "Staying up past 1 AM"),
]
ASK = re.compile(r"\b(what makes (my|me have) (a )?good days?|when am i (happiest|at my best)|(about |on )?my good days|"
                 r"what (makes|made) (my|me) days? (better|good|great)|patterns? in my (days|moods?)|"
                 r"what helps my (mood|days?))\b", re.I)


def _good(label: str) -> bool:
    return label in GOOD


def _rough(label: str) -> bool:
    return any(label.startswith(r) for r in ROUGH)


class GoodDays(Part):
    name = "gooddays"

    def __init__(self, store=None, clock=time.time, idle=lambda: 0.0):
        super().__init__(store, clock)
        self.idle = idle

    def _safe(self, sql: str, args=()) -> list[dict]:
        try:
            return self._rows(sql, args)
        except Exception:
            return []                          # that part is off (no table yet)

    # ----- how the days felt -----
    def moods(self, lookback: int = LOOKBACK) -> dict[str, str]:
        """{day: label} for finished days (today isn't over)."""
        if self.store is None:
            return {}
        from .mood import DAY_STARTS, day_label

        today = (self.now() - dt.timedelta(hours=DAY_STARTS)).date()
        since = (today - dt.timedelta(days=lookback)).isoformat()
        out = {r["day"]: r["mood"] for r in self._safe("SELECT day, mood FROM diary WHERE day >= ? AND day < ? AND mood != ''",
                                                         (since, today.isoformat()))}
        for i in range(1, 15):
            d = (today - dt.timedelta(days=i)).isoformat()
            if d not in out:
                label = day_label(self.store, d)
                if label:
                    out[d] = label
        return {d: m for d, m in out.items() if m}

    # ----- what happened on them -----
    def _since_first(self, days: list[str], first: str | None, did: set[str]) -> dict[str, bool]:
        """Known only from the day the thing started existing (no list before = not "didn't do it")."""
        if not first:
            return {}
        return {d: d in did for d in days if d >= first}

    def factors(self, days: list[str]) -> dict[str, dict[str, bool]]:
        if not days:
            return {}
        lo = min(days)
        out: dict[str, dict[str, bool]] = {}
        health = self._safe("SELECT day, steps, sleep_min FROM health WHERE day >= ?", (lo,))
        out["walked"] = {r["day"]: r["steps"] >= 6000 for r in health if r["steps"] is not None}
        out["slept"] = {r["day"]: r["sleep_min"] >= 420 for r in health if r["sleep_min"]}
        out["photo"] = {r["day"]: r["status"] == "done" for r in self._safe("SELECT day, status FROM daily_photos WHERE day >= ?", (lo,))}
        first = self._safe("SELECT MIN(substr(created, 1, 10)) AS d FROM activities")
        did = {r["day"] for r in self._safe("SELECT DISTINCT day FROM activity_log WHERE how != 'pass' AND day >= ?", (lo,))}
        out["together"] = self._since_first(days, first[0]["d"] if first else None, did)
        first = self._safe("SELECT MIN(day) AS d FROM journal WHERE author = 'you' AND kind = 'page'")
        did = {r["day"] for r in self._safe("SELECT DISTINCT day FROM journal WHERE author = 'you' AND kind = 'page' AND day >= ?", (lo,))}
        out["journal"] = self._since_first(days, first[0]["d"] if first else None, did)
        first = self._safe("SELECT MIN(day) AS d FROM meal_plan")
        did = {r["day"] for r in self._safe("SELECT DISTINCT day FROM meal_plan WHERE cooked = 1 AND day >= ?", (lo,))}
        out["cooked"] = self._since_first(days, first[0]["d"] if first else None, did)
        late = {r["d"] for r in self._safe("SELECT DISTINCT substr(ts, 1, 10) AS d FROM turns WHERE ts >= ? "
                                           "AND substr(ts, 12, 5) >= '01:00' AND substr(ts, 12, 5) < '04:00'", (lo,))}
        talked = {r["d"] for r in self._safe("SELECT DISTINCT substr(ts, 1, 10) AS d FROM turns WHERE ts >= ?", (lo,))}
        prev = {d: (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat() for d in days}
        out["late"] = {d: d in late for d in days if d in talked or prev[d] in talked}
        return out

    # ----- the patterns -----
    def patterns(self) -> list[dict]:
        moods = self.moods()
        days = sorted(moods)
        facts = self.factors(days)
        out = []
        for key, phrase, label in FACTORS:
            f = facts.get(key) or {}
            yes = [d for d in days if f.get(d) is True]
            no = [d for d in days if f.get(d) is False]
            if len(yes) < MIN_EACH or len(no) < MIN_EACH:
                continue
            gy, gn = sum(_good(moods[d]) for d in yes), sum(_good(moods[d]) for d in no)
            ry, rn = sum(_rough(moods[d]) for d in yes), sum(_rough(moods[d]) for d in no)
            diff = gy / len(yes) - gn / len(no)
            rough_diff = ry / len(yes) - rn / len(no)
            if abs(diff) < GAP and abs(rough_diff) < GAP:
                continue
            better = diff > 0 if abs(diff) >= abs(rough_diff) else rough_diff < 0
            head = phrase[0].upper() + phrase[1:]
            if abs(diff) >= abs(rough_diff):
                text = f"{head} were good {gy} of {len(yes)} times, vs {gn} of {len(no)} otherwise."
            else:
                text = f"{head} were rough {ry} of {len(yes)} times, vs {rn} of {len(no)} otherwise."
            out.append({"key": key, "label": label, "better": better, "text": text,
                        "metric": "good" if abs(diff) >= abs(rough_diff) else "rough",
                        "with": {"days": len(yes), "good": gy, "rough": ry}, "without": {"days": len(no), "good": gn, "rough": rn},
                        "strength": round(max(abs(diff), abs(rough_diff)), 2)})
        return sorted(out, key=lambda p: -p["strength"])

    def spoken(self) -> str:
        moods = self.moods()
        ps = self.patterns()
        if not ps:
            need = "" if len(moods) >= 2 * MIN_EACH else f" I've only got {len(moods)} day{'s' if len(moods) != 1 else ''} to go on so far."
            return "I don't see a clear pattern yet; give it a few more weeks of us talking." + need
        lines = [p["text"] for p in ps[:3]]
        return "Here's what I've noticed, from your days: " + " ".join(lines)

    # ----- on her own / asked -----
    def route(self, user_text: str, last_reply: str = "") -> tuple[str, dict] | None:
        return ("good_days", {}) if ASK.search(user_text) else None

    def moments(self, now: float) -> list[Moment]:
        if self.store is None:
            return []
        d = dt.datetime.fromtimestamp(now)
        if not 18 <= d.hour < 22 or self.idle() > 120:
            return []
        last = self.get("last_told", "")
        if last and (d.date() - dt.date.fromisoformat(last)).days < 7:
            return []
        told = self.get("told", {})
        for p in self.patterns():
            sign = "up" if p["better"] else "down"
            when = told.get(f"{p['key']}:{sign}", "")
            if when and (d.date() - dt.date.fromisoformat(when)).days < 30:
                continue
            habit = ("If it's a habit worth keeping, cheer it on lightly" if p["better"] else
                     "Be gentle, no lecture: just something you noticed, maybe ask what they think")
            return [Moment("gooddays", f"You noticed a pattern in {{user}}'s days, worked out from their moods (all true, keep "
                                       f"the numbers exactly): {p['text']} Share it as something you noticed, warm and a little "
                                       f"curious. {habit}. One or two short lines.", key=f"{p['key']}:{sign}", part=self.name)]
        return []

    def used(self, moment, now: float):
        today = dt.datetime.fromtimestamp(now).date().isoformat()
        self.put("last_told", today)
        self.put("told", {**self.get("told", {}), moment.key: today})

    def status(self) -> dict:
        moods = self.moods()
        return {"patterns": self.patterns()[:6], "days": len(moods), "good": sum(_good(m) for m in moods.values()),
                "rough": sum(_rough(m) for m in moods.values()), "need": 2 * MIN_EACH}
