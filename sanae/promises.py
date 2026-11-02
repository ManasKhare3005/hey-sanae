"""Pinky promises, both ways.

  - "I promise I'll sleep before 1" / "pinky promise" / "fine, I promise" to her "promise?" ->
    your promise, with a deadline when you said one ("before 1", "tonight", "tomorrow", "this week").
  - "promise you'll remind me about the gym tomorrow" -> her promise; a reminder in it becomes a
    real reminder (so she actually keeps it) and it counts as kept when the reminder goes off.
  - Checked the way a friend would: on the laptop at 1:20 AM after promising bed before 1 -> caught
    ("I see you 👀"); otherwise the next morning, or the day after the deadline, she asks if you kept
    it, and your answer settles it. Promises without a deadline get asked about after 3 days.
  - The phone's Us tab shows the open ones (yours and hers) and lets you settle or add them.
"""
from __future__ import annotations

import datetime as dt
import re
import time

from .initiative import Moment
from .part import Part

SCHEMA = """
CREATE TABLE IF NOT EXISTS promises (
    id INTEGER PRIMARY KEY, who TEXT NOT NULL, text TEXT NOT NULL, due TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open', created TEXT NOT NULL, resolved TEXT NOT NULL DEFAULT '',
    reminder TEXT NOT NULL DEFAULT '', asked TEXT NOT NULL DEFAULT '');
"""
_TAIL = r"(?P<what>[^.?!]{3,100})"
MINE = re.compile(r"\b(?:i (?:pinky )?promise(?: you)?(?: (?:that|to))?|pinky promise(?: i(?:'ll| will))?|i swear(?: i(?:'ll| will))?)"
                  r"\s+(?:i(?:'ll| will) |i(?:'m| am) gonna |to )?" + _TAIL, re.I)
JUST_YES = re.compile(r"^\W*(?:ok(?:ay)?|fine|alright|yes|yeah|yep|sure|deal)?[\s,]*(?:i )?(?:pinky )?promise\W*$", re.I)
HERS = re.compile(r"\b(?:you )?(?:pinky )?promise (?:me )?(?:you(?:'ll| will) |to )" + _TAIL, re.I)
ASKED = re.compile(r"\bpromise(?: me)?(?: you(?:'ll| will)| to| that you(?:'ll| will))? (?P<what>[^.?!]{3,100})\?", re.I)
SLEEP = re.compile(r"\b(sleep|bed|asleep|lights out|log off|logging off|get off)\b", re.I)
KEPT = re.compile(r"\b(yes|yeah|yep|i did|kept it|i kept|did it|of course|sure did|totally)\b", re.I)
BROKEN = re.compile(r"\b(no|nope|nah|didn'?t|i broke|broke it|failed|oops|not really|kinda not)\b", re.I)
REMIND = re.compile(r"\bremind me (?:to |about |of )?(?P<what>.+?)(?:\s+(?P<when>(?:tomorrow|tonight|today|on \w+|at \d|in \d|this|next)\b.*))?$", re.I)
ANSWER_FOR_S = 30 * 60


def due_from(text: str, now: dt.datetime) -> dt.datetime | None:
    """'before 1' -> 1 AM tonight; 'by 11 pm' -> today 11 PM; 'tonight' / 'tomorrow' / 'this week' -> end of it."""
    t = text.lower()
    m = re.search(r"\b(?:before|by|until|till)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", t)
    if m:
        h, mins, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").replace(".", "")
        if ap == "pm" and h < 12:
            h += 12
        elif ap == "am" and h == 12:
            h = 0
        elif not ap and h <= 6:
            pass                                    # "before 1" at night means 1 AM
        elif not ap and h < 12 and now.hour >= 12:
            h += 12
        if h > 23:
            return None
        at = now.replace(hour=h, minute=mins, second=0, microsecond=0)
        return at if at > now else at + dt.timedelta(days=1)
    end = lambda d: dt.datetime.combine(d, dt.time(23, 59))
    if "tonight" in t or "today" in t:
        return end(now.date())
    if "tomorrow" in t:
        return end(now.date() + dt.timedelta(days=1))
    if "this week" in t:
        return end(now.date() + dt.timedelta(days=6 - now.weekday()))
    return None


def tidy(what: str) -> str:
    what = re.sub(r"\s+", " ", what).strip(" ,.!")
    return re.sub(r"^(that |to )", "", what, flags=re.I)[:100]


class Promises(Part):
    name = "promises"

    def __init__(self, store=None, clock=time.time, reminders=None, publish=lambda kind, data: None,
                 idle=lambda: 9999.0):
        super().__init__(store, clock)
        self.reminders, self.publish, self.idle = reminders, publish, idle
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

    def get_one(self, pid: int) -> dict | None:
        rows = self._rows("SELECT * FROM promises WHERE id = ?", (pid,))
        return rows[0] if rows else None

    def open(self) -> list[dict]:
        return self._rows("SELECT * FROM promises WHERE status = 'open' ORDER BY id")

    def make(self, who: str, text: str, due: dt.datetime | None = None, when_words: str = "") -> dict:
        text = tidy(text)
        now = self.now()
        due = due or due_from(when_words or text, now)
        for p in self.open():
            if p["who"] == who and p["text"].lower() == text.lower():
                return p
        reminder = ""
        if who == "her" and self.reminders is not None:
            m = REMIND.search(text)
            if m:
                from .reminders import parse_when

                at = parse_when(m.group("when") or "tomorrow at 9am", now)
                if at is not None and at > now:
                    r = self.reminders.add(m.group("what").strip(" ."), at)
                    reminder = r.uid
                    due = due or at
                    self.publish("reminder", {"action": "added", "uid": r.uid, "text": r.text, "due": at.isoformat()})
        cur = self._exec("INSERT INTO promises (who, text, due, created, reminder) VALUES (?,?,?,?,?)",
                         (who, text, due.isoformat(timespec="minutes") if due else "", now.isoformat(timespec="seconds"),
                          reminder))
        self.publish("us", {"what": "promises", "action": "made"})
        return self.get_one(cur.lastrowid)

    def settle(self, pid: int, status: str) -> dict | None:
        if status not in ("kept", "broken", "dropped", "open"):
            return None
        self._exec("UPDATE promises SET status = ?, resolved = ? WHERE id = ?",
                   (status, "" if status == "open" else self.now().isoformat(timespec="seconds"), pid))
        self.publish("us", {"what": "promises", "action": status})
        return self.get_one(pid)

    def status(self) -> dict:
        recent = self._rows("SELECT * FROM promises WHERE status != 'open' AND status != 'dropped' ORDER BY resolved DESC LIMIT 6")
        kept = self._rows("SELECT who, COUNT(*) AS n FROM promises WHERE status = 'kept' GROUP BY who")
        return {"open": self.open(), "recent": recent, "kept": {r["who"]: r["n"] for r in kept}}

    # ----- in chat -----
    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        out = []
        now = self.clock()
        text = user_text.strip()
        waiting = self.get("asking")
        if waiting and now - waiting["t"] < ANSWER_FOR_S:
            p = self.get_one(waiting["id"])
            if p is not None and p["status"] == "open":
                broke, kept = BROKEN.search(text), KEPT.search(text)
                if broke or kept:
                    self.put("asking", None)
                    p = self.settle(p["id"], "broken" if broke else "kept")
                    out.append(f"They {'kept' if p['status'] == 'kept' else 'broke'} their pinky promise (\"{p['text']}\"). "
                               + ("Be proud, a little smug about it, one line." if p["status"] == "kept"
                                  else "Tease them gently and let it go; no guilt."))
                    return out
        asked = ASKED.search(last_reply or "")
        hers = [h for h in HERS.finditer(text) if not re.search(r"\bi\s+(?:pinky\s+)?$", text[:h.start()], re.I)]
        deal = asked and hers and re.match(r"^\W*(ok(ay)?|fine|deal|alright|sure)\b", text, re.I)   # "fine, but you promise..."
        if asked and (JUST_YES.match(text) or deal):
            p = self.make("you", asked.group("what"))
            out.append(self._sealed(p))
        else:
            m = MINE.search(text)
            if m:
                p = self.make("you", m.group("what"))
                out.append(self._sealed(p))
        h = hers[0] if hers else None
        if h:
            p = self.make("her", h.group("what"))
            extra = " (it's set as a real reminder, so you'll keep it)" if p["reminder"] else ""
            out.append(f"They made you pinky promise: you'll {p['text']}{extra}. Promise it back, playfully, like it's "
                       "sealed")
        return out

    def _sealed(self, p: dict) -> str:
        when = ""
        if p["due"]:
            d = dt.datetime.fromisoformat(p["due"])
            when = f" (by {d.hour % 12 or 12}{d.strftime(':%M') if d.minute else ''} {'AM' if d.hour < 12 else 'PM'})"
        return (f"They just pinky promised you: they'll {p['text']}{when}. It's saved; react like it's a sealed pinky "
                "promise, light and a little teasing (you'll check on it)")

    # ----- checking on them -----
    def moments(self, now: float) -> list[Moment]:
        return self._check(now, phone=False)

    def phone_moments(self, now: float) -> list[Moment]:
        return self._check(now, phone=True)

    def _check(self, now: float, phone: bool) -> list[Moment]:
        d = dt.datetime.fromtimestamp(now)
        out = []
        for p in self.open():
            if p["who"] == "her":
                if p["reminder"] and self.reminders is not None:
                    r = self.reminders.by_uid(p["reminder"])
                    if r is not None and r.status != "pending":
                        self.settle(p["id"], "kept")
                continue
            due = dt.datetime.fromisoformat(p["due"]) if p["due"] else None
            created = dt.datetime.fromisoformat(p["created"])
            if due and SLEEP.search(p["text"]) and not phone and 10 * 60 <= (d - due).total_seconds() <= 3 * 3600 \
                    and self.idle() < 120 and not self.done(f"caught:{p['id']}"):
                out.append(Moment("promise", f"{{user}} pinky promised to {p['text']} (by {due.hour % 12 or 12}"
                                             f"{due.strftime(':%M') if due.minute else ''}), and it's "
                                             f"{d.hour % 12 or 12}:{d:%M} and they're still at the laptop. Catch them, "
                                             "playful, like 'I see you'; one line.", True, f"caught:{p['id']}", part=self.name))
                continue
            ask_from = None
            if due:
                ask_from = max(due + dt.timedelta(minutes=30), dt.datetime.combine(due.date(), dt.time(9, 0))) \
                    if due.hour < 6 else due + dt.timedelta(hours=1)
                if SLEEP.search(p["text"]):
                    ask_from = dt.datetime.combine((due - dt.timedelta(hours=6)).date() + dt.timedelta(days=1), dt.time(9, 0))
            elif (d - created).days >= 3:
                ask_from = d
            if ask_from and d >= ask_from and 9 <= d.hour < 23 and not self.done(f"ask:{p['id']}"):
                out.append(Moment("promise", f"Ask {{user}}, casually and a bit playfully, whether they kept their pinky "
                                             f"promise: \"{p['text']}\". One line.", key=f"ask:{p['id']}", part=self.name))
        return out[:1]

    def used(self, moment, now: float):
        if moment.key:
            self.once(moment.key)
        if moment.key.startswith("ask:"):
            self.put("asking", {"id": int(moment.key.split(":")[1]), "t": now})
        if moment.key.startswith("caught:"):
            self.settle(int(moment.key.split(":")[1]), "broken")
