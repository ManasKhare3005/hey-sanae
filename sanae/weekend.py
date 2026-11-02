"""Weekend plans, made together: she helps you plan Saturday and Sunday and is around while they happen.

  - Friday evening she asks what the weekend looks like and offers to plan it (this replaces the
    plain "any plans?" ritual). "Let's plan the weekend" works any day too.
  - While you plan, what you say turns into plans in code ("saturday morning I wanna go hiking",
    "sunday at 3 coffee with Maya"): day, a rough time, what. Or add them on the phone (Us tab).
  - Saturday / Sunday morning: today's plan in one line (a text on the phone if you're away).
  - A plan with a time: "have fun!" just before; a few hours later (or that evening) "how was it?";
    your answer ticks it off.
  - Sunday evening: how was the weekend, with what you actually did.

Kept in the memory database (weekend_plans); the phone reads it through /api/us.
"""
from __future__ import annotations

import datetime as dt
import re
import time

from .initiative import Moment
from .part import Part, clock_words, in_hours

SCHEMA = """
CREATE TABLE IF NOT EXISTS weekend_plans (
    id INTEGER PRIMARY KEY, weekend TEXT NOT NULL, day TEXT NOT NULL DEFAULT '', at TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL, asked INTEGER NOT NULL DEFAULT 0);
"""
PLANNING_S = 2 * 3600
MEALS = ("brunch", "lunch", "dinner")
HOW_WAS_S = 30 * 60
TIMES = {"early morning": "08:00", "morning": "10:00", "brunch": "11:00", "noon": "12:00", "lunch": "12:30",
         "afternoon": "14:00", "evening": "18:00", "dinner": "19:00", "tonight": "20:00", "night": "20:00"}
DAY_WORDS = re.compile(r"\b(?:on |this |next )?(sat(?:urday|urdays)?|sun(?:day|days)?)\b", re.I)
TIME_WORDS = re.compile(r"\b(?:in the |on |at |around |for |by )?(?:(sat(?:urday)?|sun(?:day)?) )?"
                        r"(early morning|morning|brunch|noon|lunch|afternoon|evening|dinner|tonight|night)\b", re.I)
CLOCK = re.compile(r"\b(?:at |around |by |from )?(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?(?=\W|$)", re.I)
FILLER = re.compile(r"^(?:(?:and|so|also|then|maybe|probably|i think|ok(?:ay)?|well|um+|uh+|like|plus)[, ]+)*"
                    r"(?:i(?:'?m| am)? (?:wanna|want to|would like to|gonna|going to|planning to|plan to|might|will|'ll|should|"
                    r"need to|have to|hope to)|i'?ll|we(?:'re| are)? (?:gonna|going to|should|could|might)|we'?ll|"
                    r"let'?s|i'?d like to|i might|maybe)?\s*", re.I)
WEEKEND_WORD = re.compile(r"\b(this |the |over the |on the )?weekend\b", re.I)
SAT_SUN = re.compile(r"\b(sat(urday)?|sun(day)?|this weekend|on the weekend|weekend)\b", re.I)
DONE_PLANNING = re.compile(r"\b(that'?s (it|all|everything)|nothing else|i'?m good|that'?s the plan|we'?re done|"
                           r"no(pe)?,? that'?s (it|all))\b", re.I)
NOT_DONE = re.compile(r"\b(didn'?t|did not|never|cancel+ed|skipped|bailed|fell through|called (it )?off|"
                      r"couldn'?t|no time|rain(ed)? out|postponed)\b", re.I)
ACTIVITY = re.compile(r"[a-z]{3,}", re.I)

_OUR = r"(?:my|our|the|this)"
W_SHOW = re.compile(rf"^\W*(?:what(?:'?s| is| are)|show(?: me)?|tell me|remind me of)\s+{_OUR}\s+(?:weekend\s+)?plans?"
                    rf"(?:\s+(?:for|this|on)\s+(?:the |this )?weekend)?\W*$"
                    rf"|^\W*what(?:'?s| is| are| am| do) (?:i|we)(?: got| have| doing| up to)? (?:on |planned )?(?:for )?(?:this|the) weekend\W*$"
                    rf"|^\W*(?:my|our) weekend plans?\W*$", re.I)
W_PLAN = re.compile(rf"\b(?:let'?s|help me|can we|could we|wanna|want to|let me|time to)\s+plan\s+{_OUR}\s+weekend\b"
                    rf"|^\W*plan\s+{_OUR}\s+weekend\b", re.I)
W_ADD = re.compile(rf"\b(?:add|put)\s+(?P<what>.+?)\s+(?:to|on|in)\s+{_OUR}\s+weekend(?:\s+plans?)?\W*$", re.I)
W_DROP = re.compile(rf"\b(?:remove|take|drop|cancel|delete)\s+(?P<what>.+?)\s+(?:from|off)\s+{_OUR}\s+weekend(?:\s+plans?)?\W*$", re.I)


def weekend_of(d: dt.date) -> dt.date:
    """The Saturday of the weekend we're in (Sat/Sun) or the next one (Mon-Fri)."""
    if d.weekday() == 6:
        return d - dt.timedelta(days=1)
    return d + dt.timedelta(days=(5 - d.weekday()) % 7)


def parse_plan(text: str) -> dict | None:
    """'saturday morning I wanna go hiking' -> {day: 'sat', at: '10:00', text: 'go hiking'}; None if
    there's no activity in it."""
    t = " " + re.sub(r"\s+", " ", text.strip()) + " "
    day = ""
    if m := DAY_WORDS.search(t):
        day = "sat" if m.group(1).lower().startswith("sat") else "sun"
    at = ""
    if m := CLOCK.search(t):
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower().replace(".", "")
        if ap or m.group(2) or re.search(r"\b(at|around|by|from)\s+$", t[:m.start(1)]):
            if 1 <= h <= 12 and ap in ("pm",) and h != 12:
                h += 12
            elif ap == "am" and h == 12:
                h = 0
            elif not ap and 1 <= h <= 7:
                h += 12                           # "at 3": the afternoon
            if 0 <= h < 24 and 0 <= mi < 60:
                at = f"{h:02d}:{mi:02d}"
                t = t[:m.start()] + " " + t[m.end():]
    found = list(TIME_WORDS.finditer(t))
    times = [m.group(2).lower() for m in found]
    plain = [w for w in times if w not in MEALS]
    if not at and times:
        at = TIMES[(plain or times)[0]]
    for m in reversed(found):                   # "dinner" is the plan itself; "night" is only when
        if m.group(1) and not day:
            day = "sat" if m.group(1).lower().startswith("sat") else "sun"
        word = m.group(2).lower()
        t = t[:m.start()] + " " + (word if word in MEALS else "") + " " + t[m.end():]
    t = DAY_WORDS.sub(" ", t)
    t = WEEKEND_WORD.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,.!?;:-")
    t = FILLER.sub("", t).strip(" ,.!?;:-")
    t = re.sub(r"^(?:to|do|go do|and)\s+", "", t, flags=re.I).strip(" ,.!?")
    t = re.sub(r"\s+(?:i think|maybe|probably|or something|if i can|too)$", "", t, flags=re.I).strip(" ,.!?")
    if len(ACTIVITY.findall(t)) < 1 or len(t) < 3 or len(t.split()) > 12:
        return None
    if re.fullmatch(r"(?i)(nothing|not much|no plans?|idk|i don'?t know|not sure|free|chill(ing)?|nothing really)", t):
        return None
    return {"day": day, "at": at, "text": t[:80]}


def day_label(day: str) -> str:
    return {"sat": "Saturday", "sun": "Sunday"}.get(day, "the weekend")


class Weekend(Part):
    name = "weekend"

    def __init__(self, store=None, clock=time.time, idle=lambda: 0.0, bucket=None, settings: dict | None = None):
        super().__init__(store, clock)
        s = settings or {}
        self.idle = idle
        self.bucket = bucket                    # bucket.py: something to suggest when the weekend is empty
        self.ask_day = str(s.get("ask", "fri"))[:3].lower()
        self.ask_hours = tuple(s.get("ask_hours", ["16:00", "21:00"]))
        self._schema(SCHEMA)

    # ----- storage -----
    def weekend(self, d: dt.date | None = None) -> dt.date:
        return weekend_of(d or self.now().date())

    def plans(self, weekend: dt.date | None = None) -> list[dict]:
        w = (weekend or self.weekend()).isoformat()
        return self._rows("SELECT * FROM weekend_plans WHERE weekend = ? ORDER BY CASE day WHEN 'sat' THEN 0 WHEN 'sun' "
                          "THEN 1 ELSE 2 END, CASE WHEN at = '' THEN 1 ELSE 0 END, at, id", (w,))

    def get_one(self, pid) -> dict | None:
        rows = self._rows("SELECT * FROM weekend_plans WHERE id = ?", (int(pid),))
        return rows[0] if rows else None

    def add(self, text: str, day: str = "", at: str = "") -> dict:
        text = re.sub(r"\s+", " ", text or "").strip(" .,!")[:80]
        if not text:
            raise ValueError("a plan needs a what")
        day = day.lower()[:3] if (day or "").lower()[:3] in ("sat", "sun") else ""
        at = at if re.fullmatch(r"\d{2}:\d{2}", at or "") else ""
        w = self.weekend()
        for p in self.plans(w):
            if p["text"].lower() == text.lower():
                if (day and day != p["day"]) or (at and at != p["at"]):
                    self._exec("UPDATE weekend_plans SET day = ?, at = ? WHERE id = ?", (day or p["day"], at or p["at"], p["id"]))
                return self.get_one(p["id"])
        cur = self._exec("INSERT INTO weekend_plans (weekend, day, at, text, created) VALUES (?,?,?,?,?)",
                         (w.isoformat(), day, at, text, self.now().isoformat(timespec="seconds")))
        return self.get_one(cur.lastrowid)

    def find(self, said: str) -> dict | None:
        from .goals import mentions

        for p in self.plans():
            if mentions(p["text"], said):
                return p
        return None

    def remove(self, pid) -> dict | None:
        p = self.get_one(pid)
        if p is not None:
            self._exec("DELETE FROM weekend_plans WHERE id = ?", (p["id"],))
        return p

    def set_done(self, pid, done: int = 1) -> dict | None:
        p = self.get_one(pid)
        if p is not None:
            self._exec("UPDATE weekend_plans SET done = ? WHERE id = ?", (int(done), p["id"]))
        return self.get_one(pid)

    def when_words(self, p: dict) -> str:
        bits = [day_label(p["day"]) if p["day"] else ""]
        if p["at"]:
            bits.append(clock_words(dt.datetime.combine(dt.date.today(), dt.time.fromisoformat(p["at"]))))
        return " ".join(b for b in bits if b) or "sometime this weekend"

    def spoken(self) -> str:
        plans = self.plans()
        if not plans:
            return "Nothing planned for the weekend yet. Want to plan it together?"
        return "This weekend: " + "; ".join(f"{p['text']} ({self.when_words(p)})" for p in plans) + "."

    # ----- planning together -----
    def start_planning(self):
        self.put("planning", self.clock() + PLANNING_S)

    def planning(self) -> bool:
        return self.get("planning", 0) > self.clock()

    def _start_of(self, p: dict) -> dt.datetime | None:
        if not p["at"]:
            return None
        sat = dt.date.fromisoformat(p["weekend"])
        day = sat + dt.timedelta(days=1) if p["day"] == "sun" else sat
        return dt.datetime.combine(day, dt.time.fromisoformat(p["at"]))

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        if self.store is None:
            return []
        out = []
        now = self.clock()
        asked = self.get("asked")                       # "how was the hike?" waiting for an answer
        if asked and now - asked["t"] < HOW_WAS_S and not W_SHOW.search(user_text):
            self.put("asked", None)
            p = self.get_one(asked["id"])
            if p is not None:
                if NOT_DONE.search(user_text):
                    out.append(f"\"{p['text']}\" didn't happen this weekend. Be easy about it, no guilt; maybe it moves "
                               "to another weekend")
                else:
                    self.set_done(p["id"])
                    out.append(f"They told you how \"{p['text']}\" went (ticked off on your weekend plans). React to "
                               "what they said, like a friend who wanted to hear about it")
                return out
        if not self.planning():
            return out
        if DONE_PLANNING.search(user_text):
            self.put("planning", 0)
            plans = self.plans()
            if plans:
                out.append("You're done planning the weekend together. The plan: " +
                           "; ".join(f"{p['text']} ({self.when_words(p)})" for p in plans) +
                           ". Wrap it up in one happy line; you'll be around")
            return out
        if W_SHOW.search(user_text) or W_PLAN.search(user_text) or "?" in user_text:
            return out
        saved = []
        for chunk in re.split(r"(?<=[.!?;])\s+|,?\s+\band then\b\s+|,?\s+\bthen\b\s+|,\s+(?=(?:and )?(?:on )?(?:sat|sun))",
                              user_text):
            if not chunk.strip():
                continue
            plan = parse_plan(chunk)
            if plan is None:
                continue
            saved.append(self.add(plan["text"], plan["day"], plan["at"]))
        if saved:
            self.put("planning", now + PLANNING_S)
            out.append("You saved to your weekend plans: " + "; ".join(f"{p['text']} ({self.when_words(p)})" for p in saved)
                       + ". React briefly (excited, or a small tease), and ask if there's anything else for the weekend")
        return out

    # ----- her bringing it up -----
    def moments(self, now: float) -> list[Moment]:
        return self._moments(now, phone=False)

    def phone_moments(self, now: float) -> list[Moment]:
        return self._moments(now, phone=True)

    def _moments(self, now: float, phone: bool) -> list[Moment]:
        if self.store is None:
            return []
        d = dt.datetime.fromtimestamp(now)
        today = d.date()
        key_day = today.isoformat()
        out = []
        dow = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[today.weekday()]
        plans = self.plans(weekend_of(today))
        # timed plans: have fun before, how was it after
        for p in plans:
            start = self._start_of(p)
            if start is None or start.date() != today:
                continue
            before = (start - d).total_seconds()
            if 0 <= before <= 30 * 60 and not self.done(f"fun:{p['id']}"):
                out.append(Moment("weekend", f"{{user}} has \"{p['text']}\" at {clock_words(start)} (from your weekend "
                                             "plans). A short \"have fun\" line, warm.", True, f"fun:{p['id']}",
                                  part=self.name))
            after = (d - start).total_seconds()
            if 3 * 3600 <= after <= 8 * 3600 and not p["done"] and not self.done(f"how:{p['id']}"):
                out.append(Moment("weekend", f"Earlier today {{user}} had \"{p['text']}\" (from your weekend plans). Ask "
                                             "how it went, curious, one line.", key=f"how:{p['id']}", part=self.name))
        if not phone and self.idle() > 300:
            return out
        if dow == self.ask_day and in_hours(d, *self.ask_hours) and not self.done(f"ask:{key_day}"):
            if plans:
                out.append(Moment("weekend", "It's Friday. You two already planned some of the weekend: " +
                                  "; ".join(f"{p['text']} ({self.when_words(p)})" for p in plans) +
                                  ". Mention it, excited, and ask if they want to add anything. One line.",
                                  key=f"ask:{key_day}", part=self.name))
            else:
                idea = self._idea()
                out.append(Moment("weekend", "It's Friday. Ask {user} what the weekend looks like and offer to plan it "
                                             "together" + (f" (you could suggest something from your shared bucket "
                                                          f"list: \"{idea}\")" if idea else "") + ". One line.",
                                  key=f"ask:{key_day}", part=self.name))
        if dow in ("sat", "sun") and 9 <= d.hour < 12 and not self.done(f"today:{key_day}"):
            todays = [p for p in plans if p["day"] in (dow, "") and not p["done"]]
            if todays:
                out.append(Moment("weekend", f"It's {day_label(dow)} morning. Today's plan, from what you two planned: " +
                                  "; ".join(f"{p['text']}" + (f" at {clock_words(self._start_of(p))}" if p['at'] and p['day'] == dow else "")
                                            for p in todays) + ". One cheerful line about the day.",
                                  key=f"today:{key_day}", part=self.name))
            elif dow == "sat" and not plans:
                idea = self._idea()
                if idea:
                    out.append(Moment("weekend", f"It's Saturday morning and {{user}} has nothing planned. Suggest, lightly, "
                                                 f"one thing from your shared bucket list: \"{idea}\". One line.",
                                      key=f"today:{key_day}", part=self.name))
        if dow == "sun" and in_hours(d, "18:00", "22:00") and plans and not self.done(f"recap:{key_day}"):
            done = [p["text"] for p in self.plans(weekend_of(today)) if p["done"]]
            out.append(Moment("weekend", "Sunday evening. Ask {user} how the weekend was" +
                              (f"; they did: {', '.join(done)}" if done else
                               f"; the plans were: {', '.join(p['text'] for p in plans[:4])}") +
                              ". One warm line.", key=f"recap:{key_day}", part=self.name))
        return out

    def _idea(self) -> str | None:
        if self.bucket is None:
            return None
        try:
            return self.bucket.suggest()
        except Exception:
            return None

    def used(self, moment, now: float):
        if moment.key:
            self.once(moment.key)
        if moment.key.startswith("ask:"):
            self.start_planning()                 # her question opens the planning chat
        if moment.key.startswith("how:"):
            self.put("asked", {"id": int(moment.key.split(":")[1]), "t": now})
            self._exec("UPDATE weekend_plans SET asked = 1 WHERE id = ?", (int(moment.key.split(":")[1]),))

    def replaces_ritual(self, d: dt.datetime) -> bool:
        return True

    # ----- straight to the tools -----
    def route(self, user_text: str, last_reply: str = "") -> tuple[str, dict] | None:
        t = user_text.strip()
        if W_SHOW.search(t):
            return "weekend_plans", {}
        if m := W_ADD.search(t):
            plan = parse_plan(m.group("what")) or {"text": m.group("what"), "day": "", "at": ""}
            return "add_weekend_plan", {"plan": plan["text"], "day": plan["day"], "time": plan["at"]}
        if m := W_DROP.search(t):
            return "drop_weekend_plan", {"plan": m.group("what").strip()}
        if W_PLAN.search(t):
            return "plan_weekend", {}
        return None

    # ----- for the phone -----
    def status(self) -> dict:
        w = self.weekend()
        sun = w + dt.timedelta(days=1)
        return {"weekend": w.isoformat(), "label": f"{w:%b} {w.day} – {sun.day}" if w.month == sun.month
                else f"{w:%b} {w.day} – {sun:%b} {sun.day}",
                "plans": [{"id": p["id"], "day": p["day"], "at": p["at"], "text": p["text"], "done": bool(p["done"]),
                           "when": self.when_words(p)} for p in self.plans(w)],
                "planning": self.planning()}
