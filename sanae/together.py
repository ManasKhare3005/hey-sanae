"""Doing it together: the little things you want to do each day, with her alongside, not a tracker.

  - Your list (phone "Us" tab, or by voice): "read 20 minutes", "drink water", "Duolingo"... each
    with the days it's for (every day, some weekdays, or N times a week), an optional time, and
    *why it matters to you*: she asks when you add one, and when you skip it she brings your own
    words back ("you said you wanted to read again because you missed getting lost in a story").
  - Company: "starting my reading" (or Start on the phone) -> she says she'll do her drawing
    alongside (herlife.py's current step); when the time's up she asks how it went and tells you
    what she drew.
  - A room you build together: every thing done adds a point and the room fills up (a sprout, a
    rug, a poster, fairy lights... a cat bed). Nothing done for 3 days and the plant droops; it
    never dies. The phone draws it.
  - She covers for you: once a week, on a day you can't ("too tired for my run today"), she says
    she's got you and that day doesn't break your streak.
  - Evening debrief instead of ticking boxes: "so how'd today go?" with what's still open; what
    you tell her ticks things off ("did my reading and the water, skipped the run").
  - At an activity's time she nudges once (on the phone if you're away), and streaks of 7 / 30 /
    100 days get a proud word.

Kept in the memory database (activities, activity_log); the phone reads it through /api/us.
"""
from __future__ import annotations

import datetime as dt
import random
import re
import time

from .goals import DID, MISSED, mentions
from .initiative import Moment
from .part import Part, clock_words, in_hours
from .reminders import new_uid

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# The room: (points needed, item). The phone draws each item it's given.
ROOM = [(1, "sprout"), (4, "rug"), (8, "poster"), (13, "plant"), (19, "fairy_lights"), (26, "bookshelf"),
        (35, "plant_big"), (45, "lamp"), (57, "cat_bed"), (70, "flowers"), (85, "window_plant"), (100, "stars"),
        (120, "beanbag"), (150, "cat")]
ROOM_NAMES = {"sprout": "a little sprout", "rug": "a rug", "poster": "a poster", "plant": "the plant grew",
              "fairy_lights": "fairy lights", "bookshelf": "a bookshelf", "plant_big": "the plant got big",
              "lamp": "a lamp", "cat_bed": "a cat bed", "flowers": "the plant flowered", "window_plant": "a window plant",
              "stars": "glow stars on the ceiling", "beanbag": "a beanbag", "cat": "a cat moved in"}
STREAKS = (7, 30, 100, 365)
START = re.compile(r"\b(?:start(?:ing)?|gonna (?:go )?(?:do|start)|going to (?:go )?(?:do|start)|about to (?:do|start)|"
                   r"time (?:for|to do)|let'?s do|doing)\s+(?:my |the |some )?(?P<what>[a-z][a-z' ]{2,40}?)\s*(?:now|rn|real quick)?\s*$",
                   re.I)
CANT = re.compile(r"\b(can'?t (do|make|manage)|too (tired|busy|sick|wiped)|not (today|up for)|skip(ping)?|"
                  r"no energy|won'?t (get to|make it)|rough day)\b", re.I)
ASK_WHY_FOR_S = 10 * 60
SESSION_MIN = 25


def parse_days(text: str) -> str:
    """'every day' -> 'daily'; 'mon wed fri' / 'weekdays' -> 'mon,wed,fri'; '3 times a week' -> '3/week'."""
    from .goals import per_week

    t = (text or "").lower().strip()
    if not t or re.search(r"\b(daily|every ?day|each day)\b", t):
        return "daily"
    if "weekday" in t:
        return "mon,tue,wed,thu,fri"
    if "weekend" in t:
        return "sat,sun"
    picked = [d for d in DAYS if re.search(rf"\b{d}", t)]
    if picked:
        return ",".join(picked)
    n = per_week(t)
    if n and n < 7:
        return f"{n}/week"
    return "daily"


def days_words(days: str) -> str:
    if days == "daily":
        return "every day"
    if days.endswith("/week"):
        n = int(days.split("/")[0])
        return "once a week" if n == 1 else f"{n} times a week"
    if days == "mon,tue,wed,thu,fri":
        return "weekdays"
    return ", ".join(d.title() for d in days.split(","))


def week_start(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


class Together(Part):
    name = "together"

    def __init__(self, store=None, clock=time.time, life=None, goals=None, idle=lambda: 0.0, rng=None,
                 settings: dict | None = None):
        super().__init__(store, clock)
        s = settings or {}
        self.life, self.goals, self.idle = life, goals, idle
        self.rng = rng or random.Random()
        self.debrief = tuple(s.get("debrief", ["20:30", "23:30"]))
        self.drawings = None                     # drawings.Drawings: a session's drawing becomes a real sketch
        self._mem_db = None
        if store is not None and hasattr(store, "db"):
            with store.lock:
                store.db.executescript(SCHEMA)
                store.db.commit()

    # ----- storage -----
    def _rows(self, sql: str, args=()) -> list[dict]:
        with self.store.lock:
            return [dict(r) for r in self.store.db.execute(sql, args).fetchall()]

    def _exec(self, sql: str, args=()):
        with self.store.lock:
            cur = self.store.db.execute(sql, args)
            self.store.db.commit()
            return cur

    def all(self) -> list[dict]:
        return self._rows("SELECT * FROM activities WHERE archived = 0 ORDER BY CASE WHEN at = '' THEN 1 ELSE 0 END, at, id")

    def get_one(self, ident) -> dict | None:
        rows = self._rows("SELECT * FROM activities WHERE id = ? OR uid = ?", (ident if str(ident).isdigit() else -1, str(ident)))
        return rows[0] if rows else None

    def add(self, title: str, why: str = "", days: str = "daily", at: str = "", app: str = "", minutes: int = 0) -> dict:
        title = re.sub(r"\s+", " ", title).strip(" .,!")[:80]
        if not title:
            raise ValueError("an activity needs a name")
        for a in self.all():
            if a["title"].lower() == title.lower():
                return a
        days = days if re.fullmatch(r"daily|\d/week|(mon|tue|wed|thu|fri|sat|sun)(,(mon|tue|wed|thu|fri|sat|sun))*", days or "") \
            else parse_days(days)
        at = at if re.fullmatch(r"\d{2}:\d{2}", at or "") else ""
        cur = self._exec("INSERT INTO activities (uid, title, why, days, at, app, minutes, created) VALUES (?,?,?,?,?,?,?,?)",
                         (new_uid(), title, why.strip()[:200], days, at, app.strip(), int(minutes or 0), self.today()))
        if not why:
            self.put("asking_why", {"id": cur.lastrowid, "t": self.clock()})
        return self.get_one(cur.lastrowid)

    def update(self, ident, **fields) -> dict | None:
        a = self.get_one(ident)
        if a is None:
            return None
        keep = {k: v for k, v in fields.items() if k in ("title", "why", "days", "at", "app", "minutes") and v is not None}
        if "days" in keep:
            keep["days"] = parse_days(keep["days"]) if not re.fullmatch(r"daily|\d/week|[a-z,]+", keep["days"]) else keep["days"]
        if "at" in keep and not re.fullmatch(r"(\d{2}:\d{2})?", keep["at"]):
            keep.pop("at")
        if keep:
            sets = ", ".join(f"{k} = ?" for k in keep)
            self._exec(f"UPDATE activities SET {sets} WHERE id = ?", (*keep.values(), a["id"]))
        return self.get_one(a["id"])

    def remove(self, ident) -> dict | None:
        a = self.get_one(ident)
        if a is not None:
            self._exec("UPDATE activities SET archived = 1 WHERE id = ?", (a["id"],))
        return a

    def find(self, said: str) -> dict | None:
        hits = [a for a in self.all() if mentions(a["title"], said)]
        return hits[0] if len(hits) == 1 else None

    def find_all(self, said: str) -> list[dict]:
        return [a for a in self.all() if mentions(a["title"], said)]

    # ----- days -----
    def log(self, a: dict, day: str | None = None, how: str = "tap") -> bool:
        """Done (or covered, how='pass') on `day`. True if it's new."""
        day = day or self.today()
        before = self.how(a, day)
        self._exec("INSERT OR REPLACE INTO activity_log (activity_id, day, how, ts) VALUES (?,?,?,?)",
                   (a["id"], day, how, int(self.clock())))
        return before is None

    def unlog(self, a: dict, day: str | None = None):
        self._exec("DELETE FROM activity_log WHERE activity_id = ? AND day = ?", (a["id"], day or self.today()))

    def how(self, a: dict, day: str) -> str | None:
        rows = self._rows("SELECT how FROM activity_log WHERE activity_id = ? AND day = ?", (a["id"], day))
        return rows[0]["how"] if rows else None

    def _logged(self, a: dict) -> dict[dt.date, str]:
        return {dt.date.fromisoformat(r["day"]): r["how"]
                for r in self._rows("SELECT day, how FROM activity_log WHERE activity_id = ?", (a["id"],))}

    def due(self, a: dict, day: dt.date) -> bool:
        """Is it on the list that day? 'N/week' ones are, until the week's N are done."""
        days = a["days"]
        if days == "daily":
            return True
        if days.endswith("/week"):
            n = int(days.split("/")[0])
            logged = self._logged(a)
            ws = week_start(day)
            before = sum(1 for d, h in logged.items() if ws <= d < day)
            return before < n or day in logged
        return DAYS[day.weekday()] in days.split(",")

    def streak(self, a: dict, today: dt.date | None = None) -> int:
        """Days in a row it was done (or covered) on the days it was due; today still open doesn't break it.
        'N/week' ones count weeks in a row with N done."""
        today = today or self.now().date()
        logged = self._logged(a)
        created = dt.date.fromisoformat(a["created"])
        if a["days"].endswith("/week"):
            n = int(a["days"].split("/")[0])
            count, ws = 0, week_start(today)
            if sum(1 for d in logged if ws <= d <= today) >= n:
                count += 1
            while True:
                ws -= dt.timedelta(days=7)
                if ws + dt.timedelta(days=6) < created:
                    return count
                if sum(1 for d in logged if ws <= d < ws + dt.timedelta(days=7)) >= n:
                    count += 1
                else:
                    return count
        count, d = 0, today
        while d >= created:
            if d in logged:
                count += 1
            elif self.due(a, d) and d != today:
                break
            d -= dt.timedelta(days=1)
        return count

    def week_done(self, a: dict, day: dt.date | None = None) -> int:
        day = day or self.now().date()
        ws = week_start(day)
        return sum(1 for d, h in self._logged(a).items() if ws <= d <= day and h != "pass")

    def open_today(self) -> list[dict]:
        d = self.now().date()
        return [a for a in self.all() if self.due(a, d) and self.how(a, d.isoformat()) is None]

    # ----- the room and the pass -----
    def points(self) -> int:
        rows = self._rows("SELECT COUNT(*) AS n FROM activity_log WHERE how != 'pass'")
        return int(rows[0]["n"]) if rows else 0

    def room(self) -> dict:
        pts = self.points()
        items = [name for need, name in ROOM if pts >= need]
        nxt = next(((need, name) for need, name in ROOM if pts < need), None)
        last = self._rows("SELECT MAX(day) AS day FROM activity_log WHERE how != 'pass'")
        last_day = last[0]["day"] if last and last[0]["day"] else None
        droopy = bool(items) and (last_day is None or (self.now().date() - dt.date.fromisoformat(last_day)).days >= 3)
        return {"points": pts, "items": items, "droopy": droopy,
                "next": {"item": nxt[1], "label": ROOM_NAMES[nxt[1]], "in": nxt[0] - pts} if nxt else None}

    def pass_free(self, day: dt.date | None = None) -> bool:
        day = day or self.now().date()
        return self.get("pass") != week_start(day).isoformat()

    def use_pass(self, a: dict, day: str | None = None) -> bool:
        d = dt.date.fromisoformat(day) if day else self.now().date()
        if not self.pass_free(d) or self.how(a, d.isoformat()) is not None:
            return False
        self.log(a, d.isoformat(), "pass")
        self.put("pass", week_start(d).isoformat())
        return True

    # ----- company -----
    def her_doing(self) -> str:
        step = None
        if self.life is not None:
            try:
                learning = self.life.learning or {}
                steps = learning.get("steps") or []
                if steps:
                    n = min(self.life.day() // max(1, int(learning.get("every_days", 3))), len(steps) - 1)
                    step = steps[n]
            except Exception:
                step = None
        return f"practise drawing {re.sub(r' [(].*', '', step)}" if step else "practise your Japanese words"

    def start(self, a: dict, minutes: int | None = None, origin: str = "laptop") -> dict:
        minutes = int(minutes or a.get("minutes") or SESSION_MIN)
        s = {"id": a["id"], "title": a["title"], "until": self.clock() + minutes * 60, "minutes": minutes,
             "her": self.her_doing(), "origin": origin}
        self.put("session", s)
        return s

    def session(self) -> dict | None:
        return self.get("session")

    # ----- for the phone -----
    def status(self) -> dict:
        d = self.now().date()
        items = []
        for a in self.all():
            items.append({"id": a["id"], "uid": a["uid"], "title": a["title"], "why": a["why"], "days": a["days"],
                          "days_words": days_words(a["days"]), "at": a["at"], "app": a["app"], "minutes": a["minutes"],
                          "due": self.due(a, d), "how": self.how(a, d.isoformat()), "streak": self.streak(a, d),
                          "week": self.week_done(a, d)})
        goals = []
        if self.goals is not None:
            try:
                goals = [{"text": g["text"], "progress": self.goals.progress(g)} for g in self.goals.all()]
            except Exception:
                goals = []
        s = self.session()
        return {"activities": items, "room": self.room(), "pass_free": self.pass_free(d), "goals": goals,
                "session": s if s and s["until"] > self.clock() else None, "her_doing": self.her_doing()}

    # ----- in conversation (code-side: the small model is unreliable with tools in chat) -----
    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        if self.store is None:
            return []
        now = self.clock()
        out = []
        asking = self.get("asking_why")
        if asking and now - asking["t"] < ASK_WHY_FOR_S and len(user_text.split()) >= 3 \
                and not START.search(user_text) and "?" not in user_text:
            a = self.get_one(asking["id"])
            self.put("asking_why", None)
            if a is not None and not a["why"]:
                self.update(a["id"], why=user_text.strip()[:200])
                out.append(f"They told you why \"{a['title']}\" matters to them; you saved it. Say you'll remember "
                           "that, warmly, in a few words")
                return out
        if asking and now - asking["t"] < 120:
            a = self.get_one(asking["id"])
            if a is not None and not a["why"]:
                out.append(f"\"{a['title']}\" is now on your shared daily list ({days_words(a['days'])}). Ask them, "
                           "briefly and warmly, why it matters to them")
        if not self.all():
            return out
        m = START.search(user_text.strip(" .!"))
        if m:
            a = self.find(m.group("what"))
            if a is not None:
                s = self.start(a)
                out.append(f"They're starting \"{a['title']}\" now. Say you'll {s['her']} alongside them while they do, "
                           f"like keeping each other company, and you'll check in in about {s['minutes']} minutes. Short")
                return out
        hits = self.find_all(user_text)
        if not hits:
            return out
        d = self.now().date()
        if MISSED.search(user_text) or CANT.search(user_text):
            for a in hits[:2]:
                if self.how(a, d.isoformat()) is not None:
                    continue
                if self.pass_free(d) and self.due(a, d):
                    self.use_pass(a)
                    out.append(f"They can't do \"{a['title']}\" today. You're covering for them: tell them warmly you've "
                               "got them and today doesn't count against their streak (you can do that once a week). "
                               "No guilt")
                elif a["why"]:
                    out.append(f"They're skipping \"{a['title']}\" today. Be kind; you can gently bring back why it "
                               f"matters to them, in their own words: \"{a['why']}\". One line, no lecture")
            return out
        if DID.search(user_text) or re.search(r"\b(done|did it|finished)\b", user_text, re.I):
            newly = [a for a in hits if self.log(a, d.isoformat(), "said")]
            for a in newly[:2]:
                st = self.streak(a, d)
                room = self.room()
                bit = f"; their streak is {st} days" if st >= 2 else ""
                if room["next"] and room["next"]["in"] <= 2:
                    bit += f"; your shared room is close to getting {room['next']['label']}"
                out.append(f"They did \"{a['title']}\" today (ticked on your shared list{bit}). Be glad with them, briefly")
        return out

    # ----- her bringing it up -----
    def moments(self, now: float) -> list[Moment]:
        return self._moments(now, phone=False)

    def phone_moments(self, now: float) -> list[Moment]:
        """For texts.py: the same moments, when they're away from the laptop."""
        return self._moments(now, phone=True)

    def _moments(self, now: float, phone: bool) -> list[Moment]:
        if self.store is None:
            return []
        d = dt.datetime.fromtimestamp(now)
        today = d.date().isoformat()
        out = []
        s = self.session()
        if s and now >= s["until"] and not self.done(f"session:{int(s['until'])}"):
            if (s.get("origin") == "phone") == phone or now - s["until"] > 15 * 60:
                out.append(Moment("together", f"{{user}} started \"{s['title']}\" {s['minutes']} minutes ago and you said "
                                              f"you'd {s['her']} alongside. Time's up: ask how it went and tell them, in a "
                                              "few words, how your drawing / practice went"
                                              + (" (the sketch is in your sketchbook on their phone)" if self.drawings is not None
                                                 and "draw" in s["her"] else "") + ". Two short lines at most.",
                                  True, f"session:{int(s['until'])}", part=self.name))
        if not phone and self.idle() > 300:
            return out
        open_now = self.open_today()
        for a in open_now:
            if not a["at"]:
                continue
            at = dt.datetime.combine(d.date(), dt.time.fromisoformat(a["at"]))
            if 0 <= (d - at).total_seconds() <= 20 * 60 and not self.done(f"at:{a['id']}:{today}"):
                why = f" They said it matters because: \"{a['why']}\"." if a["why"] else ""
                out.append(Moment("together", f"It's {clock_words(at)}, the time {{user}} set for \"{a['title']}\" on "
                                              f"your shared list.{why} A short, warm nudge, not a reminder robot.",
                                  True, f"at:{a['id']}:{today}", part=self.name))
        if in_hours(d, *self.debrief) and open_now and not self.done(f"debrief:{today}"):
            done = [a["title"] for a in self.all() if self.how(a, today) not in (None, "pass")]
            out.append(Moment("together", f"Evening debrief with {{user}}: ask casually how today went with your shared "
                                          f"list. Still open: {', '.join(a['title'] for a in open_now[:4])}."
                                          + (f" Already done: {', '.join(done[:4])}." if done else "")
                                          + " One line; no guilt, it's a chat not a checklist.",
                              key=f"debrief:{today}", part=self.name))
        for a in self.all():
            st = self.streak(a, d.date())
            if st in STREAKS and self.how(a, today) and not self.done(f"streak:{a['id']}:{st}"):
                unit = "weeks" if a["days"].endswith("/week") else "days"
                out.append(Moment("together", f"{{user}} has done \"{a['title']}\" {st} {unit} in a row. Be proud of them, "
                                              "genuinely, one line.", key=f"streak:{a['id']}:{st}", part=self.name))
                break
        return out

    def replaces_checkin(self, d: dt.datetime) -> bool:
        """The evening debrief is the check-in on days the list has something open."""
        return bool(self.store is not None and self.open_today())

    def used(self, moment, now: float):
        if moment.key:
            self.once(moment.key)
        s = self.session()
        if moment.key.startswith("session:") and self.drawings is not None and s and "draw" in s.get("her", ""):
            try:
                self.drawings.draw(why=moment.key)          # what she drew alongside them, for real
            except Exception:
                pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY, uid TEXT NOT NULL, title TEXT NOT NULL, why TEXT NOT NULL DEFAULT '',
    days TEXT NOT NULL DEFAULT 'daily', at TEXT NOT NULL DEFAULT '', app TEXT NOT NULL DEFAULT '',
    minutes INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS activity_log (
    activity_id INTEGER NOT NULL, day TEXT NOT NULL, how TEXT NOT NULL DEFAULT 'tap', ts INTEGER NOT NULL,
    PRIMARY KEY (activity_id, day));
"""


_DAILY = r"(?:my |our |the )?(?:daily|every ?day|together) list"
D_SHOW = re.compile(rf"^\W*(?:what'?s|what is|show(?: me)?|read(?: me)?|tell me)\s+(?:on |in |left on |left in )?{_DAILY}\W*$"
                    rf"|^\W*what'?s left (?:for |on )?(?:today|{_DAILY})\W*$", re.I)
D_ADD = re.compile(rf"\b(?:add|put)\s+(?P<what>.+?)\s+(?:to|on)\s+{_DAILY}\W*$", re.I)
D_REMOVE = re.compile(rf"\b(?:take|remove|delete|drop)\s+(?P<what>.+?)\s+(?:off|from)\s+{_DAILY}\W*$", re.I)


def together_route(text: str) -> tuple[str, dict] | None:
    """'what's on my daily list' / 'add X to our daily list' / 'take X off my daily list' -> its tool
    (the todo list's routes don't take "daily list", and the model mixed the two up)."""
    t = text.strip()
    if D_SHOW.search(t):
        return "list_activities", {}
    days = "every day"
    when = (r"\s+(every ?day|daily|on weekdays|weekdays|\d+ times a week|on (?:mon|tue|wed|thu|fri|sat|sun)\w*"
            r"(?:(?:,| and) (?:mon|tue|wed|thu|fri|sat|sun)\w*)*)")
    if dm := re.search(when + r"\W*$", t, re.I):          # "...to our daily list on weekdays"
        if D_ADD.search(t[:dm.start()]):
            days, t = dm.group(1), t[:dm.start()]
    if m := D_ADD.search(t):
        what = m.group("what").strip()
        if dm := re.search(when + r"$", what, re.I):      # "add reading on weekdays to our daily list"
            days, what = dm.group(1), what[:dm.start()]
        return "add_activity", {"title": what, "days": days}
    if m := D_REMOVE.search(t):
        return "drop_activity", {"title": m.group("what").strip()}
    return None
