"""A photo a day: every day she gives you a small challenge that gets you outside or moving ("the sky
from somewhere you walked to", "your shoes after a walk"), and the photo you send back goes in the
scrapbook. A streak, and a month of them as a grid on the phone (Us -> Photo a day).

  - The challenge is picked in code each morning: walking ones when you've barely moved by the
    afternoon (steps from the phone, health.py), indoor-friendly ones when it's pouring or very hot.
  - She tells you late morning (or texts you if you're away from the laptop), and the phone gets one
    gentle reminder around 5 PM if there's no photo yet.
  - The first photo you send her that day (not a screenshot / receipt / fridge) counts: she reacts to
    it against the challenge, and it's kept in the scrapbook with her caption.
  - "Skip today's photo" is fine once a week without losing the streak; "give me another challenge"
    rerolls it once.
  - She does it too: her own sketch of the challenge (drawings.py, in her sketchbook), drawn when your
    photo comes in, or mid-afternoon if she gets there first. The phone shows yours and hers side by side.
"""
from __future__ import annotations

import datetime as dt
import logging
import random
import re
import threading
import time

from .initiative import Moment
from .part import Part

log = logging.getLogger(__name__)
SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_photos (
    day TEXT PRIMARY KEY, challenge TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', scrapbook_id INTEGER NOT NULL DEFAULT 0,
    at TEXT NOT NULL DEFAULT '');
"""
WALKS = ["the sky from somewhere you walked to", "the farthest point of a walk today", "a street you've never walked down",
         "your shoes after a walk", "a tree you've never noticed before", "something red you spot on a walk",
         "your shadow, outside", "a dog (or cat) you meet outside", "water somewhere: a fountain, a lake, a puddle",
         "the view from the highest place you can walk to", "a door you like on your walk", "a flower growing somewhere unexpected"]
MOVES = ["stairs you took instead of the elevator", "your post-workout face (or snack)", "the spot where you stretched for 5 minutes",
         "something you carried home on foot", "the sunset or sunrise, from outside", "something green outside",
         "a bench you walked to and sat on", "your favourite spot on campus"]
INDOOR = ["the spot where you stretched for 5 minutes", "stairs you took instead of the elevator",
          "the weather out the window after 20 squats", "your water bottle, refilled for the third time",
          "a corner of home you tidied while moving around"]
SKIP = re.compile(r"\b(skip|no|not doing|pass on)\s+(today'?s\s+|the\s+|a\s+)?(daily\s+)?photo( challenge)?( today)?\b", re.I)
ASK = re.compile(r"\b(what'?s|what is|tell me) (today'?s|the|my) (daily )?(photo|picture) (challenge|of the day)\b|"
                 r"\bdaily photo\??$|\bphoto challenge\b", re.I)
REROLL = re.compile(r"\b(another|different|new|other) (photo )?challenge\b", re.I)
NOT_DAILY = re.compile(r"\b(screenshot|receipt|document|form|flyer|poster|syllabus|invoice|bill|fridge|label|error|code|"
                       r"text message|email|menu|homework|slide)\b", re.I)
# what she draws for a challenge (first match), from drawings.SUBJECTS
HER_SUBJECTS = [("shoes", "some shoes"), ("shadow", "a long shadow"), ("dog", "a dog"), ("cat", "a cat"), ("door", "a door"),
                ("water bottle", "a water bottle"), ("fountain", "water"), ("lake", "water"), ("puddle", "water"),
                ("stairs", "stairs"), ("bench", "a bench"), ("sunset", "a sunset"), ("sunrise", "a sunset"),
                ("street", "a street"), ("tree", "a tree"), ("flower", "a flower"), ("red", "a flower"), ("sky", "the sky"),
                ("highest", "mountains"), ("green", "a plant"), ("tidied", "a plant"), ("campus", "a tree"),
                ("carried", "a book"), ("stretch", "stick figures"), ("squats", "stick figures"), ("workout", "stick figures"),
                ("walk", "a street")]
HER_CAPTIONS = ["I did it too: {c}", "my entry for today: {c}", "{c}, my version", "couldn't let you do it alone: {c}"]
HER_FROM = 15                          # she does hers by mid-afternoon if your photo hasn't come in yet
ASK_FROM, ASK_UNTIL = 9.5, 13          # she brings it up (hours)
NUDGE_FROM, NUDGE_UNTIL = 17, 19       # the phone's reminder


class DailyPhoto(Part):
    name = "dailyphoto"

    def __init__(self, store=None, clock=time.time, health=None, weather=None, scrapbook=None, idle=lambda: 0.0,
                 publish=lambda kind, data: None, rng=None, drawings=None):
        super().__init__(store, clock)
        self.health, self.weather, self.scrapbook, self.drawings = health, weather, scrapbook, drawings
        self.idle, self.publish = idle, publish
        self.rng = rng or random.Random()
        self._schema(SCHEMA)

    # ----- the challenge -----
    def _steps(self) -> int | None:
        try:
            d = self.health.today() if self.health is not None else None
        except Exception:
            return None
        return d.steps if d is not None else None

    def _bad_weather(self) -> bool:
        try:
            w = self.weather.today() if self.weather is not None else None
        except Exception:
            return False
        if not w:
            return False
        code = w.get("code") or 0
        hot = (w.get("now") or 0) >= (100 if getattr(self.weather, "units", "fahrenheit") == "fahrenheit" else 38)
        return hot or 51 <= code <= 67 or 80 <= code <= 82 or code >= 95

    def pick(self, avoid: str = "") -> str:
        recent = {r["challenge"] for r in self._rows("SELECT challenge FROM daily_photos ORDER BY day DESC LIMIT 14")}
        if self._bad_weather():
            pool = INDOOR
        else:
            steps = self._steps()
            pool = WALKS if (steps is not None and steps < 3000) or self.rng.random() < 0.6 else MOVES
        fresh = [c for c in pool if c not in recent and c != avoid] or [c for c in pool if c != avoid]
        return self.rng.choice(fresh)

    def today_row(self, create: bool = True) -> dict | None:
        day = self.today()
        rows = self._rows("SELECT * FROM daily_photos WHERE day = ?", (day,))
        if rows or not create:
            return rows[0] if rows else None
        self._exec("INSERT OR IGNORE INTO daily_photos (day, challenge) VALUES (?, ?)", (day, self.pick()))
        return self._rows("SELECT * FROM daily_photos WHERE day = ?", (day,))[0]

    def reroll(self) -> str | None:
        r = self.today_row()
        if r["status"] != "open" or self.get("rerolled") == r["day"]:
            return None
        new = self.pick(avoid=r["challenge"])
        self._exec("UPDATE daily_photos SET challenge = ? WHERE day = ?", (new, r["day"]))
        self.put("rerolled", r["day"])
        return new

    def skip(self) -> bool:
        """Returns True if the streak is kept (one free skip a week)."""
        r = self.today_row()
        week = self.now().isocalendar()[:2]
        free = self.get("free_skip") != list(week)
        self._exec("UPDATE daily_photos SET status = ? WHERE day = ?", ("skipped" if free else "missed", r["day"]))
        if free:
            self.put("free_skip", list(week))
        return free

    def streak(self) -> int:
        """Days in a row with a photo (a free skip doesn't break it; today still open doesn't either)."""
        rows = {r["day"]: r["status"] for r in self._rows("SELECT day, status FROM daily_photos ORDER BY day DESC LIMIT 400")}
        d, n = self.now().date(), 0
        if rows.get(d.isoformat(), "open") == "open":
            d -= dt.timedelta(days=1)
        while True:
            s = rows.get(d.isoformat())
            if s == "done":
                n += 1
            elif s != "skipped":
                return n
            d -= dt.timedelta(days=1)

    # ----- hers -----
    @staticmethod
    def her_subject(challenge: str) -> str:
        low = challenge.lower()
        for word, subject in HER_SUBJECTS:
            if word in low:
                return subject
        return "the sky"

    def hers(self, create: bool = False) -> dict | None:
        """Her sketch for today's challenge (made once, if `create`)."""
        if self.drawings is None or self.store is None:
            return None
        r = self.today_row(create=create)
        if r is None:
            return None
        why = f"dailyphoto:{r['day']}"
        have = self.drawings.for_why(why)
        if have is not None or not create or r["status"] in ("skipped", "missed"):
            return have
        mine = re.sub(r"\byour\b", "my", r["challenge"])
        return self.drawings.draw(self.her_subject(r["challenge"]), why=why, title=mine,
                                  caption=self.rng.choice(HER_CAPTIONS).format(c=mine))

    # ----- the photo -----
    def counts(self, user_text: str) -> bool:
        """Is this photo today's daily photo? (the first real photo of the day, after 6 AM)"""
        from .vision import PHOTO_TAG

        if self.store is None or not user_text.startswith(PHOTO_TAG) or self.now().hour < 6:
            return False
        r = self.today_row()
        seen = getattr(getattr(self.scrapbook, "vision", None), "last", None)
        what = f"{user_text} {getattr(seen, 'description', '')}"
        return r["status"] == "open" and not NOT_DAILY.search(what)

    def got(self, user_text: str) -> dict:
        r = self.today_row()
        seen = getattr(getattr(self.scrapbook, "vision", None), "last", None)
        if seen is not None:
            self.put("claimed", seen.at)            # the scrapbook doesn't ask "keep it?" about this one
        self._exec("UPDATE daily_photos SET status = 'done', at = ? WHERE day = ?",
                   (self.now().isoformat(timespec="minutes"), r["day"]))
        if self.scrapbook is not None:
            def keep():
                try:
                    p = self.scrapbook.keep(said=f"daily photo: {r['challenge']}")
                    if p is not None:
                        self._exec("UPDATE daily_photos SET scrapbook_id = ? WHERE day = ?", (p["id"], r["day"]))
                        self.publish("us", {"what": "dailyphoto", "action": "kept"})
                except Exception as exc:
                    log.info("daily photo: keep failed: %s", exc)

            threading.Thread(target=keep, name="dailyphoto-keep", daemon=True).start()
        return self.today_row()

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        if not self.counts(user_text):
            return []
        r = self.got(user_text)
        n = self.streak()
        steps = self._steps()
        moved = f", and they've done {steps:,} steps today" if steps and steps >= 3000 else ""
        out = [f"This is their daily photo for today's challenge (\"{r['challenge']}\"). Only from what you can see, "
               f"say if it fits the challenge, and be proud of them for getting out and doing it; their streak is {n} "
               f"day{'s' if n != 1 else ''}{moved}. It's in your scrapbook now"]
        try:
            hers = self.hers(create=True)
        except Exception as exc:
            log.info("daily photo: her sketch failed: %s", exc)
            hers = None
        if hers is not None:
            out.append(f"You did the challenge too: you drew {hers['subject']} in your sketchbook (\"{hers['caption']}\"). "
                       "Mention it at the end, a little shy or proud; it's next to their photo on the phone (Us tab)")
        return out

    # ----- in conversation -----
    def route(self, user_text: str, last_reply: str = "") -> tuple[str, dict] | None:
        t = user_text.strip()
        if SKIP.search(t):
            return "daily_photo", {"action": "skip"}
        if REROLL.search(t) and ("challenge" in (last_reply or "").lower() or "photo" in t.lower()):
            return "daily_photo", {"action": "reroll"}
        if ASK.search(t):
            return "daily_photo", {"action": "show"}
        return None

    def spoken(self) -> str:
        r = self.today_row()
        n = self.streak()
        streak = f" You're on a {n}-day streak." if n >= 2 else ""
        if r["status"] == "done":
            return f"You already did today's: {r['challenge']}.{streak}"
        if r["status"] in ("skipped", "missed"):
            return "We're skipping today's photo. Tomorrow's a new one!"
        return f"Today's photo challenge: {r['challenge']}. Send it to me when you've got it!{streak}"

    # ----- on her own -----
    def _ask(self, now: float, phone: bool) -> list[Moment]:
        if self.store is None:
            return []
        d = dt.datetime.fromtimestamp(now)
        if not ASK_FROM <= d.hour + d.minute / 60 < ASK_UNTIL or (not phone and self.idle() > 120):
            return []
        r = self.today_row()
        key = f"ask:{r['day']}"
        if r["status"] != "open" or self.done(key):
            return []
        n = self.streak()
        streak = f" They're on a {n}-day streak." if n >= 2 else ""
        return [Moment("dailyphoto", f"Give {{user}} today's photo-a-day challenge, word for word: \"{r['challenge']}\". "
                                     f"It's to get them outside or moving a bit.{streak} Playful, one or two short lines, "
                                     "ask them to send you the photo"
                                     + (", and say you'll do it too (you'll draw yours)." if self.drawings is not None else "."),
                       key=key, part=self.name)]

    def moments(self, now: float) -> list[Moment]:
        return self._ask(now, phone=False)

    def phone_moments(self, now: float) -> list[Moment]:
        return self._ask(now, phone=True)

    def observe(self, now: float):
        """Her own sketch by mid-afternoon; the phone's one reminder, late afternoon, if there's no photo yet."""
        if self.store is None:
            return
        d = dt.datetime.fromtimestamp(now)
        if d.hour >= HER_FROM and self.drawings is not None and self.once(f"hers:{d.date().isoformat()}"):
            try:
                if self.hers(create=True) is not None:
                    self.publish("us", {"what": "dailyphoto", "action": "hers"})
            except Exception as exc:
                log.info("daily photo: her sketch failed: %s", exc)
        if not NUDGE_FROM <= d.hour < NUDGE_UNTIL:
            return
        r = self.today_row()
        if r["status"] != "open" or not self.once(f"nudge:{r['day']}"):
            return
        n = self.streak()
        tail = f" Keep the {n}-day streak going!" if n >= 2 else ""
        self.publish("nudge", {"kind": "dailyphoto", "text": f"📸 Photo of the day: {r['challenge']}.{tail}"})

    def status(self) -> dict:
        r = self.today_row()
        first = self.now().date().replace(day=1).isoformat()
        month = self._rows("SELECT day, challenge, status, scrapbook_id FROM daily_photos WHERE day >= ? ORDER BY day", (first,))
        best = self.get("best", 0)
        n = self.streak()
        if n > best:
            self.put("best", n)
            best = n
        hers = self.hers()
        return {"today": {"challenge": r["challenge"], "status": r["status"], "scrapbook_id": r["scrapbook_id"],
                          "hers": hers}, "streak": n, "best": best,
                "month_label": self.now().strftime("%B"), "month": month}
