"""Goals she keeps you to, like a friend would.

"I want to go to the gym 3 times a week" -> she asks whether you want her to keep you to it; only
a yes saves it (or say it outright: "hold me accountable to reading every day"). After that:
  - "went to the gym today" / "skipped the gym" is logged from what you say (no tool call needed:
    the 4b model was unreliable with tools in casual chat), and she's proud or encouraging;
  - in the evening, at most once a day, she asks about a goal that's behind this week;
  - on Sunday evening, a short look at the week's goals;
  - hitting a weekly target counts as a win (wins.py).

Kept in kv "goals:list" (a handful of goals, each with the days it was done or missed).
"""
from __future__ import annotations

import datetime as dt
import re

from .initiative import Moment
from .part import Part, in_hours

OFFER_FOR_S = 10 * 60          # a "yes" this soon after she offered saves the goal
_NUM = {"once": 1, "one": 1, "twice": 2, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}

SAYS_GOAL = re.compile(
    r"\b(?:my goal is(?: to)?|my new goal is(?: to)?|i(?:'m| am) (?:trying|going|gonna try) to|i want to|i wanna|"
    r"i(?:'d| would) like to|i need to|i should|i(?:'m| am) gonna)\s+(?P<what>[^.?!]{4,90})", re.I)
# a goal, not a wish for right now ("I want to play valorant"): a rhythm, a habit or "my goal"
HABIT = re.compile(r"\b(every ?(day|morning|night|evening|week)|daily|each (day|morning|night|week)|"
                   r"(\d|once|one|twice|two|three|four|five|six|seven)\s*(times?|days?|x)\s*(a|per|each)\s*week|"
                   r"weekly|more often|regularly|consistently|habit|start (\w+ing)|stop (\w+ing)|"
                   r"get better at|by (the end of|next) \w+)\b", re.I)
SET_GOAL = re.compile(r"\b(?:hold me accountable (?:to|for)|keep me (?:to|on track with)|set (?:a|my) goal(?: to| of)?|"
                      r"add (?:a )?goal(?: to| of)?|new goal:?)\s+(?P<what>[^.?!]{4,90})", re.I)
DID = re.compile(r"\b(i |just |finally )?(did|went|finished|hit|got|ran|worked out|studied|read|meditated|practi[cs]ed|"
                 r"completed|made it|done with|managed to|stuck to)\b", re.I)
MISSED = re.compile(r"\b(skipped|missed|didn'?t (go|do|make it|get to|manage|have time)|couldn'?t|bailed|no time for|"
                    r"slacked|forgot to)\b", re.I)
GENERIC = set("""want need like more less every each daily week weekly times time start stop going trying better
get keep make sure really regularly consistently habit day days morning night evening once twice three four five
six seven again least some""".split())


def per_week(text: str) -> int:
    t = text.lower()
    if re.search(r"\b(every ?day|daily|each day|every (morning|night|evening))\b", t):
        return 7
    m = re.search(r"\b(\d|once|one|twice|two|three|four|five|six|seven)\s*(?:times?|days?|x)?\s*(?:a|per|each)\s*week\b", t)
    if m:
        n = m.group(1)
        return int(n) if n.isdigit() else _NUM.get(n, 0)
    if re.search(r"\b(weekly|every week|each week)\b", t):
        return 1
    return 0


def tidy(what: str) -> str:
    what = re.sub(r"\s+", " ", what).strip(" ,.")
    what = re.sub(r"^(to|start|be able to)\s+", "", what, flags=re.I)
    return what[:90]


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in GENERIC}


def mentions(goal_text: str, said: str) -> bool:
    """'went to the gym' is about 'go to the gym 3 times a week' (a shared word start, 4 letters)."""
    mine = _words(goal_text) - {"the", "and", "for", "with", "go", "went", "goes", "doing", "done"}
    theirs = _words(said)
    return any(a[:4] == b[:4] for a in mine if len(a) >= 4 for b in theirs if len(b) >= 4) or \
        any(a == b for a in mine for b in theirs)


def week_of(day: dt.date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


class Goals(Part):
    name = "goals"

    def __init__(self, store=None, clock=None, rng=None, evening=("18:00", "22:30")):
        import random
        import time

        super().__init__(store, clock or time.time)
        self.rng = rng or random.Random()
        self.evening = evening

    # ----- the list -----
    def all(self) -> list[dict]:
        return [g for g in self.get("list", []) if g.get("status") == "active"]

    def _save_all(self, goals: list[dict]):
        self.put("list", goals[-30:])

    def add(self, text: str, weekly: int | None = None) -> dict:
        text = tidy(text)
        goals = self.get("list", [])
        for g in goals:
            if g["status"] == "active" and g["text"].lower() == text.lower():
                return g
        g = {"id": max([x["id"] for x in goals] or [0]) + 1, "text": text,
             "per_week": per_week(text) if weekly is None else int(weekly),
             "created": self.today(), "status": "active", "done": [], "missed": []}
        self._save_all([*goals, g])
        return g

    def find(self, said: str) -> dict | None:
        hits = [g for g in self.all() if mentions(g["text"], said)]
        return hits[0] if len(hits) == 1 else None

    def drop(self, said: str) -> dict | None:
        goals = self.get("list", [])
        g = self.find(said)
        if g is None:
            return None
        for x in goals:
            if x["id"] == g["id"]:
                x["status"] = "dropped"
        self._save_all(goals)
        return g

    def log(self, g: dict, done: bool, day: str | None = None) -> dict:
        day = day or self.today()
        goals = self.get("list", [])
        for x in goals:
            if x["id"] == g["id"]:
                key, other = ("done", "missed") if done else ("missed", "done")
                if day not in x[key]:
                    x[key] = [*x[key], day][-120:]
                x[other] = [d for d in x[other] if d != day]
                g = x
        self._save_all(goals)
        return g

    def this_week(self, g: dict) -> int:
        wk = week_of(self.now().date())
        return sum(1 for d in g.get("done", []) if week_of(dt.date.fromisoformat(d)) == wk)

    def streak(self, g: dict) -> int:
        """Weeks in a row the target was met (daily-only goals without a target: days in a row)."""
        done = {dt.date.fromisoformat(d) for d in g.get("done", [])}
        if not g.get("per_week"):
            n, d = 0, self.now().date()
            while d in done:
                n, d = n + 1, d - dt.timedelta(days=1)
            return n
        n, start = 0, self.now().date() - dt.timedelta(days=self.now().weekday())
        if sum(1 for d in done if d >= start) >= g["per_week"]:
            n += 1
        while True:
            start -= dt.timedelta(days=7)
            if sum(1 for d in done if start <= d < start + dt.timedelta(days=7)) >= g["per_week"]:
                n += 1
            else:
                return n

    def progress(self, g: dict) -> str:
        n = self.this_week(g)
        if g.get("per_week"):
            return f"{n} of {g['per_week']} this week"
        return f"done {n} time{'s' if n != 1 else ''} this week"

    def spoken(self) -> str:
        goals = self.all()
        if not goals:
            return "You don't have any goals with me yet. Tell me one and I'll keep you to it."
        return " ".join(f"{g['text'][:1].upper()}{g['text'][1:]}: {self.progress(g)}." for g in goals)

    def week_wins(self) -> list[str]:
        """Goals whose weekly target was reached this week (for wins.py)."""
        return [g["text"] for g in self.all() if g.get("per_week") and self.this_week(g) >= g["per_week"]]

    # ----- in conversation -----
    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        from .agent import parse_yes_no

        now = self.clock()
        offer = self.get("offer")
        m = SET_GOAL.search(user_text)
        if m:
            g = self.add(m.group("what"))
            self.put("offer", None)
            return [self._saved(g)]
        if offer and now - offer["t"] < OFFER_FOR_S:
            if parse_yes_no(user_text) or re.search(r"\b(keep me|hold me|please|go for it)\b", user_text, re.I):
                g = self.add(offer["text"])
                self.put("offer", None)
                return [self._saved(g)]
            if re.search(r"\b(no|nah|nope|don'?t|not now)\b", user_text, re.I):
                self.put("offer", None)
                return []
        m = SAYS_GOAL.search(user_text)
        if m and (HABIT.search(user_text) or re.search(r"\bmy (new )?goal\b", user_text, re.I)):
            what = tidy(m.group("what"))
            if not any(g["text"].lower() == what.lower() for g in self.all()):
                self.put("offer", {"text": what, "t": now})
                return [f"They just mentioned a goal: \"{what}\". After answering, ask once, briefly, if they want you "
                        "to keep them to it (you'd check in now and then)"]
        out = []
        g = self.find(user_text) if self.all() else None
        if g is not None:
            if MISSED.search(user_text):
                g = self.log(g, False)
                out.append(f"They missed their goal \"{g['text']}\" today ({self.progress(g)}). No guilt: one kind, "
                           "encouraging line; maybe a smaller version for tomorrow")
            elif DID.search(user_text):
                before = self.this_week(g)
                g = self.log(g, True)
                hit = g.get("per_week") and before < g["per_week"] <= self.this_week(g)
                out.append(f"They kept their goal \"{g['text']}\" today ({self.progress(g)}"
                           + (", which hits this week's target" if hit else "") + "). Be genuinely proud of them, briefly")
        return out

    def _saved(self, g: dict) -> str:
        rhythm = {0: "", 7: " (every day)", 1: " (once a week)"}.get(g["per_week"], f" ({g['per_week']} times a week)")
        return (f"You're now keeping them to their goal: \"{g['text']}\"{rhythm}. It's saved; say so in a few warm "
                "words (you'll check in now and then)")

    # ----- her checking in -----
    def moments(self, now: float) -> list[Moment]:
        d = dt.datetime.fromtimestamp(now)
        goals = self.all()
        if not goals or not in_hours(d, *self.evening):
            return []
        today = d.date().isoformat()
        out = []
        if d.weekday() == 6 and d.hour >= 18 and not self.done(f"weekly:{week_of(d.date())}"):
            lines = "; ".join(f"{g['text']}: {self.progress(g)}" for g in goals)
            out.append(Moment("goals", f"It's the end of the week. {{user}}'s goals with you: {lines}. One or two warm "
                                       "lines looking back: proud of what they kept, easy on what they didn't.",
                              key=f"weekly:{week_of(d.date())}"))
            return out
        if self.done(f"asked:{today}"):
            return []
        days_left = 7 - d.weekday()
        behind = []
        for g in goals:
            if today in g.get("done", []) or today in g.get("missed", []):
                continue
            need = (g.get("per_week") or 0) - self.this_week(g)
            if need > 0 and (g["per_week"] == 7 or need >= days_left - 1 or self.rng.random() < 0.35):
                behind.append((g, need))
        if not behind:
            return []
        g, need = behind[0]
        out.append(Moment("goals", f"{{user}}'s goal: {g['text']} ({self.progress(g)}, {days_left} days left in the "
                                   "week). Casually ask if they got to it today, or cheer them on. One line, no guilt, "
                                   "no lecture.", key=f"asked:{today}"))
        return out
