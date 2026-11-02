"""Your month, wrapped: on the 1st of each month a story-style recap of the month before on the phone
(tap through like stories, the same player as the week in review), built only from what's true:

  1. the month at a glance: days you talked, how the days felt (the diary's moods), your best stretch;
  2. on repeat: your most-played songs and what joined our playlist;
  3. on screen: hours watched, the show you were into, movies with your stars (movie log);
  4. the kitchen: dishes cooked, the best-rated, home versions of restaurant dishes;
  5. photo a day: photos sent, best streak, a few from the scrapbook;
  6. doing it together: things done from the daily list, notebook pages;
  7. what makes your good days (gooddays.py), the strongest pattern;
  8. the best day, from her diary;
  9. what she's proudest of (the model, from the slides above only; no made-up numbers).

Made once per month (from 10 AM on the 1st, or the next days if the laptop was off), kept in the
`wrapped` table; the phone gets a notification and keeps the last few to rewatch (Us -> Your month).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
import time
from typing import Callable

from .weekly import Weekly

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS wrapped (
    id INTEGER PRIMARY KEY, month TEXT NOT NULL UNIQUE, data TEXT NOT NULL, created TEXT NOT NULL);
"""
GOOD = ("great", "good")
ROUGH = ("stressed", "tired", "low", "frustrated", "a hard day")
CATCH_UP_DAYS = 7
ASK = re.compile(r"\b(?:my|our|the) (?:month|monthly) (?:wrapped|recap|in review)\b|\b(?:my|our|the) wrapped\b|"
                 r"\bmonth,? wrapped\b|\bhow was my month\b", re.I)


def month_range(month: str) -> tuple[dt.date, dt.date]:
    """'2026-10' -> (Oct 1, Oct 31)."""
    first = dt.date.fromisoformat(month + "-01")
    nxt = (first + dt.timedelta(days=32)).replace(day=1)
    return first, nxt - dt.timedelta(days=1)


def hours(minutes: int) -> str:
    h = minutes / 60
    return f"{h:.0f} hour{'s' if round(h) != 1 else ''}" if h >= 1.5 else f"{minutes} minutes"


class Wrapped(Weekly):
    name = "wrapped"

    def __init__(self, store, ctx=None, llm=None, model: str = "", user: str = "them", her: str = "Sanae",
                 clock: Callable[[], float] = time.time, can_run: Callable[[], bool] = lambda: True,
                 publish=lambda kind, data: None):
        super().__init__(store, ctx=ctx, llm=llm, model=model, user=user, her=her, clock=clock, can_run=can_run,
                         publish=publish)
        with store.lock:
            store.db.executescript(SCHEMA)
            store.db.commit()

    def _safe(self, sql: str, args=()) -> list[dict]:
        try:
            return self._rows(sql, args)
        except Exception:
            return []                          # that part is off (no table yet)

    # ----- the slides -----
    def cover(self, first: dt.date, last: dt.date) -> dict:
        talked = self._safe("SELECT COUNT(DISTINCT substr(ts, 1, 10)) AS n FROM turns WHERE ts >= ? AND ts < ?",
                            (first.isoformat(), (last + dt.timedelta(days=1)).isoformat()))
        moods = [r["mood"] for r in self._safe("SELECT mood FROM diary WHERE day >= ? AND day <= ? AND mood != ''",
                                                (first.isoformat(), last.isoformat()))]
        good = sum(m in GOOD for m in moods)
        rough = sum(any(m.startswith(r) for r in ROUGH) for m in moods)
        return {"kind": "cover", "title": f"Your {first:%B}", "range": f"{first:%B %Y}",
                "talked": int(talked[0]["n"]) if talked else 0, "days": (last - first).days + 1,
                "good": good, "rough": rough, "okay": len(moods) - good - rough}

    def songs(self, month: str, first: dt.date, last: dt.date) -> dict | None:
        p = getattr(self.ctx, "playlist", None)
        if p is None:
            return None
        top = p.month_top(month, 3)
        added = self._safe("SELECT title, artist FROM playlist WHERE substr(added, 1, 10) >= ? AND substr(added, 1, 10) <= ?",
                           (first.isoformat(), last.isoformat()))
        if not top and not added:
            return None
        return {"kind": "songs", "top": top, "added": [a["title"] for a in added][:5]}

    def screen(self, first: dt.date, last: dt.date) -> dict | None:
        rows = self._safe("SELECT show, kind, SUM(minutes) AS m FROM watched WHERE day >= ? AND day <= ? GROUP BY lower(show) "
                          "ORDER BY m DESC", (first.isoformat(), last.isoformat()))
        movies = self._safe("SELECT title, stars FROM movie_log WHERE day >= ? AND day <= ? ORDER BY stars DESC, id",
                            (first.isoformat(), last.isoformat()))
        total = sum(int(r["m"] or 0) for r in rows if r["kind"] != "video")
        shows = [r for r in rows if r["kind"] == "show"]
        if not total and not movies:
            return None
        return {"kind": "screen", "hours": hours(total) if total else "", "top_show": shows[0]["show"] if shows else "",
                "movies": [{"title": m["title"], "stars": m["stars"]} for m in movies[:4]], "movie_count": len(movies)}

    def kitchen(self, first: dt.date, last: dt.date) -> dict | None:
        lo, hi = first.isoformat(), last.isoformat()
        cooked = self._safe("SELECT title, stars, source FROM recipes WHERE substr(last_cooked, 1, 10) >= ? AND "
                            "substr(last_cooked, 1, 10) <= ? ORDER BY stars DESC, cooked DESC", (lo, hi))
        new = self._safe("SELECT title, source FROM recipes WHERE substr(added, 1, 10) >= ? AND substr(added, 1, 10) <= ?", (lo, hi))
        dinners = self._safe("SELECT COUNT(*) AS n FROM meal_plan WHERE cooked = 1 AND day >= ? AND day <= ?", (lo, hi))
        recreated = [r["title"] for r in new if (r.get("source") or "").startswith("from a photo")]
        if not cooked and not new:
            return None
        best = next((r for r in cooked if r["stars"] >= 4), None)
        return {"kind": "kitchen", "cooked": len(cooked), "new": len(new), "planned_dinners": int(dinners[0]["n"]) if dinners else 0,
                "best": {"title": best["title"], "stars": best["stars"]} if best else None, "recreated": recreated[:3]}

    def photo_a_day(self, first: dt.date, last: dt.date) -> dict | None:
        rows = self._safe("SELECT day, status FROM daily_photos WHERE day >= ? AND day <= ? ORDER BY day",
                          (first.isoformat(), last.isoformat()))
        done = [r for r in rows if r["status"] == "done"]
        if not done:
            return None
        best = run = 0
        for r in rows:
            if r["status"] == "done":
                run += 1
                best = max(best, run)
            elif r["status"] != "skipped":
                run = 0
        book = getattr(self.ctx, "scrapbook", None)
        photos = []
        if book is not None:
            try:
                photos = [{"id": p["id"], "caption": p["caption"]} for p in book.between(first, last)][-4:]
            except Exception:
                photos = []
        return {"kind": "photo_a_day", "done": len(done), "best": best, "items": photos}

    def together_month(self, first: dt.date, last: dt.date) -> dict | None:
        lo, hi = first.isoformat(), last.isoformat()
        done = self._safe("SELECT COUNT(*) AS n FROM activity_log WHERE how != 'pass' AND day >= ? AND day <= ?", (lo, hi))
        pages = self._safe("SELECT COUNT(*) AS n FROM journal WHERE author = 'you' AND kind = 'page' AND day >= ? AND day <= ?",
                           (lo, hi))
        top = self._safe("SELECT a.title, COUNT(*) AS n FROM activity_log l JOIN activities a ON a.id = l.activity_id "
                         "WHERE l.how != 'pass' AND l.day >= ? AND l.day <= ? GROUP BY a.id ORDER BY n DESC LIMIT 1", (lo, hi))
        d, p = (int(done[0]["n"]) if done else 0), (int(pages[0]["n"]) if pages else 0)
        if not d and not p:
            return None
        return {"kind": "together_month", "done": d, "pages": p,
                "top": {"title": top[0]["title"], "times": top[0]["n"]} if top and d else None}

    def pattern(self) -> dict | None:
        g = getattr(self.ctx, "gooddays", None)
        if g is None:
            return None
        try:
            ps = g.patterns()
        except Exception:
            return None
        return {"kind": "pattern", "label": ps[0]["label"], "better": ps[0]["better"], "text": ps[0]["text"]} if ps else None

    def best_day(self, first: dt.date, last: dt.date) -> dict | None:
        rows = self._safe("SELECT day, text, mood FROM diary WHERE day >= ? AND day <= ? AND mood IN ('great', 'good') "
                          "ORDER BY CASE mood WHEN 'great' THEN 0 ELSE 1 END, day", (first.isoformat(), last.isoformat()))
        if not rows:
            return None
        r = rows[0]
        d = dt.date.fromisoformat(r["day"])
        line = re.split(r"(?<=[.!?])\s+", r["text"].strip())[0][:220]
        return {"kind": "bestday", "day": f"{d:%A}, {d:%B} {d.day}", "text": line}

    def build_month(self, month: str) -> dict:
        first, last = month_range(month)
        cover = self.cover(first, last)
        slides = [cover]
        facts = [f"Talked on {cover['talked']} of {cover['days']} days"] if cover["talked"] else []
        if cover["good"]:
            facts.append(f"{cover['good']} good days")
        for s in (self.songs(month, first, last), self.screen(first, last), self.kitchen(first, last),
                  self.photo_a_day(first, last), self.together_month(first, last), self.pattern(), self.best_day(first, last)):
            if s is None:
                continue
            slides.append(s)
            k = s["kind"]
            if k == "songs" and s["top"]:
                facts.append(f"Most-played song: {s['top'][0]['title']} (on {s['top'][0]['days']} days)")
            elif k == "screen" and s["movie_count"]:
                facts.append(f"Watched {s['movie_count']} movie{'s' if s['movie_count'] != 1 else ''} together")
            elif k == "kitchen":
                facts.append(f"Cooked {s['cooked']} dish{'es' if s['cooked'] != 1 else ''}" if s["cooked"] else
                             f"Saved {s['new']} new recipe{'s' if s['new'] != 1 else ''}")
            elif k == "photo_a_day":
                facts.append(f"Sent {s['done']} daily photos, best streak {s['best']} days")
            elif k == "together_month":
                if s["done"]:
                    facts.append(f"Did {s['done']} things from your shared daily list")
                if s["pages"]:
                    facts.append(f"Wrote {s['pages']} page{'s' if s['pages'] != 1 else ''} in your shared notebook")
            elif k == "bestday":
                facts.append(f"Best day: {s['day']}: {s['text']}")
        if cover["rough"] >= 5:
            facts.append("Some rough days this month, and they kept going")
        proud = self.proud(facts)
        if proud:
            slides.append({"kind": "proud", "text": proud})
        return {"month": month, "label": f"your {first:%B}", "slides": slides}

    def make_month(self, month: str) -> dict | None:
        if self._rows("SELECT 1 FROM wrapped WHERE month = ?", (month,)):
            return None
        data = self.build_month(month)
        if len(data["slides"]) < 3 and not data["slides"][0]["talked"]:
            return None                                  # nothing happened: no recap
        self._exec("INSERT INTO wrapped (month, data, created) VALUES (?,?,?)",
                   (month, json.dumps(data), self.now().isoformat(timespec="seconds")))
        first, _ = month_range(month)
        self.publish("us", {"what": "wrapped", "action": "new", "month": month})
        self.publish("nudge", {"kind": "wrapped", "text": f"🎁 Your {first:%B}, wrapped by {self.her}. Us → Your month"})
        log.info("wrapped: made %s (%d slides)", month, len(data["slides"]))
        return data

    def status(self) -> dict:
        return {"months": [{**json.loads(r["data"]), "created": r["created"]}
                           for r in self._rows("SELECT * FROM wrapped ORDER BY month DESC LIMIT 6")]}

    def spoken(self) -> str:
        rows = self._rows("SELECT data FROM wrapped ORDER BY month DESC LIMIT 1")
        if not rows:
            return "Your first month, wrapped, comes on the 1st. I'm keeping track till then!"
        data = json.loads(rows[0]["data"])
        c = data["slides"][0]
        bits = [f"we talked on {c['talked']} of {c['days']} days"] if c["talked"] else []
        if c["good"]:
            bits.append(f"{c['good']} good day{'s' if c['good'] != 1 else ''}")
        for s in data["slides"][1:]:
            if s["kind"] == "songs" and s["top"]:
                bits.append(f"{s['top'][0]['title']} was on repeat")
            elif s["kind"] == "photo_a_day":
                bits.append(f"{s['done']} daily photos")
            elif s["kind"] == "screen" and s["movie_count"]:
                bits.append(f"{s['movie_count']} movie{'s' if s['movie_count'] != 1 else ''}")
        head = data["label"][0].upper() + data["label"][1:]
        return f"{head}, wrapped: " + (", ".join(bits) + ". " if bits else "") + "Watch the whole thing on your phone, Us, Your month."

    # part.py hooks
    def route(self, user_text: str, last_reply: str = "") -> tuple[str, dict] | None:
        return ("month_wrapped", {}) if ASK.search(user_text) else None

    # ----- when -----
    def due_month(self) -> str | None:
        """From 10 AM on the 1st (or the next few days if missed): last month."""
        d = self.now()
        if d.day > CATCH_UP_DAYS or (d.day == 1 and d.hour < 10):
            return None
        return f"{d.date().replace(day=1) - dt.timedelta(days=1):%Y-%m}"

    def tick(self):
        month = self.due_month()
        if month is not None and self.can_run() and not self._rows("SELECT 1 FROM wrapped WHERE month = ?", (month,)):
            self.make_month(month)

    def start(self, every_s: float = 900):
        def loop():
            self._stop.wait(180)
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception as exc:
                    log.warning("wrapped: %s", exc)
                self._stop.wait(every_s)

        threading.Thread(target=loop, name="wrapped", daemon=True).start()
        return self
