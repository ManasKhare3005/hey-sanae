"""Routine: tasks that come back on a schedule ("water the plants every day", "laundry every
Sunday", "pay rent on the 1st of every month").

Each task has a frequency rule:
  daily, weekdays, weekly:<0-6> (Monday = 0), monthly:<1-31> (a short month uses its last day).
A task is due on the days its rule says. Ticking it marks it done for that day (`done_day`);
unticking clears it. The morning briefing lists what's due today, and the phone sends a
"you forgot ..." notification in the evening for anything due today and still unticked (the
phone keeps its own copy, synced like todos, so that works with the laptop off).

Sync: matched by uid; a removed task ("deleted") always wins, otherwise the later edit.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
import time
from dataclasses import dataclass

from .reminders import new_uid, now_ms

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_DAY = r"(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day)?s?"


def _day_index(word: str) -> int:
    w = word.lower()[:3]
    return [d[:3] for d in DAYS].index(w)


def parse_freq(text: str, today: dt.date | None = None) -> str | None:
    """'every day' -> daily, 'every Sunday' -> weekly:6, 'on the 5th of every month' -> monthly:5.
    A bare 'weekly' / 'monthly' starts from today."""
    today = today or dt.date.today()
    t = text.lower().strip()
    if re.search(r"\b(week ?days|every weekday|mon(day)?\s*(-|to|through)\s*fri(day)?)\b", t):
        return "weekdays"
    if re.search(r"\b(daily|every ?day|each day|every morning|every night|every evening|nightly)\b", t):
        return "daily"
    if m := re.search(rf"\b{_DAY}\b", t):
        if re.search(r"\b(every|each|on|weekly|week)\b", t) or t == m.group(0):
            return f"weekly:{_day_index(m.group(1))}"
    if m := re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", t):
        if re.search(r"\b(month|monthly)\b", t) or re.search(r"\bthe \d", t):
            day = int(m.group(1))
            if 1 <= day <= 31:
                return f"monthly:{day}"
    if re.search(r"\b(weekly|every week|each week|once a week)\b", t):
        return f"weekly:{today.weekday()}"
    if re.search(r"\b(monthly|every month|each month|once a month)\b", t):
        return f"monthly:{today.day}"
    return None


def valid(rule: str) -> bool:
    if rule in ("daily", "weekdays"):
        return True
    kind, _, n = rule.partition(":")
    return n.isdigit() and ((kind == "weekly" and 0 <= int(n) <= 6) or (kind == "monthly" and 1 <= int(n) <= 31))


def due_on(rule: str, day: dt.date) -> bool:
    if rule == "daily":
        return True
    if rule == "weekdays":
        return day.weekday() < 5
    kind, _, n = rule.partition(":")
    if kind == "weekly" and n.isdigit():
        return day.weekday() == int(n)
    if kind == "monthly" and n.isdigit():
        last = calendar.monthrange(day.year, day.month)[1]
        return day.day == min(int(n), last)         # the 31st -> the 30th in a 30-day month
    return False


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def label(rule: str) -> str:
    """'every day', 'weekdays', 'every Sunday', 'monthly on the 5th'."""
    if rule == "daily":
        return "every day"
    if rule == "weekdays":
        return "weekdays"
    kind, _, n = rule.partition(":")
    if kind == "weekly" and n.isdigit():
        return f"every {DAYS[int(n)].capitalize()}"
    if kind == "monthly" and n.isdigit():
        return f"monthly on the {_ordinal(int(n))}"
    return rule


@dataclass
class Chore:
    uid: str
    text: str
    freq: str
    done_day: str = ""        # ISO date it was last ticked ("" = never / unticked)
    status: str = "active"    # active, deleted
    created: str = ""
    updated: int = 0

    def done_on(self, day: dt.date) -> bool:
        return self.done_day == day.isoformat()

    def to_sync(self) -> dict:
        return {"uid": self.uid, "text": self.text, "freq": self.freq, "done_day": self.done_day,
                "status": self.status, "created": self.created, "updated_ms": self.updated}


_ROUTINE = r"(?:my |the |today'?s )?(?:daily )?routine(?: list| tasks?)?"
SHOW = re.compile(rf"^\W*(?:(?:hey |ok(?:ay)? )?(?:what'?s|what is|read(?: me)?|show(?: me)?|tell me)\s+(?:on |in )?{_ROUTINE}"
                  rf"(?: (?:for )?today)?|what(?:'s| is) (?:left |still left )?(?:on|in) {_ROUTINE}(?: today)?|"
                  rf"what do i (?:still )?have (?:left )?(?:on|in) {_ROUTINE}(?: today)?)\W*$", re.I)


SHOW_ALL = re.compile(rf"\b(?:what'?s|what is|read(?: me)?|show(?: me)?|list|tell me)\s+(?:my |the )?"
                      rf"(?:whole |entire |full )?(?:daily )?routine(?: list| tasks?)?\W*$", re.I)
_ON_ROUTINE = r"(?:to|in|into|on|onto)\s+(?:my |the )?(?:daily )?routine"
ADD = re.compile(rf"\b(?:add|put|include|stick)\b.*\b{_ON_ROUTINE}\b|\bmake\b.*\bpart of (?:my |the )?routine\b", re.I)
REMOVE = re.compile(r"\b(?:take|remove|delete|drop|scratch)\s+(?P<item>.+?)\s+(?:off|from|out of)\s+(?:my |the )?(?:daily )?routine\W*$", re.I)
# "I watered the plants", "just did the laundry", "I've taken my vitamins": a past-tense verb first
TICK = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|yay|done|alright)\W+)?(?:i\s+(?:just\s+|already\s+|finally\s+)?(?:have\s+)?|"
                  r"i'?ve\s+(?:just\s+|already\s+|finally\s+)?|just\s+)"
                  r"(?!(?:needed|wanted|started|planned|forgot|tried|decided|used|liked|loved|hated|wished)\b)"
                  r"(?P<what>(?:did|done|finished|took|taken|went|ate|fed|paid|made|ran|got|wrote|read|swept|bought|had|gave|"
                  r"brushed|[a-z]+ed)\b.+?)\W*$"
                  r"|\b(?:check|tick|cross|mark)\s+(?P<what2>.+?)\s+(?:off|done|as done)\b", re.I)
UNTICK = re.compile(r"\b(?:untick|uncheck|unmark)\s+(?P<what>.+?)(?:\W+i\b.*)?\W*$"
                    r"|\bi\s+(?:didn'?t|did not|haven'?t|have not)\s+(?:actually\s+)?(?P<what2>.+?)(?:\s+yet)?\W*$", re.I)
_FILLER = re.compile(rf"\b(?:{_ON_ROUTINE}|(?:add|put|include|stick)(?: (?:that|it|this))?|make (?:it|that|this)? ?part of "
                     rf"(?:my |the )?routine|i (?:need|have|want|should) to|i gotta|remind me to|please|can you|could you|"
                     rf"for me|as well|too|also|and|so|okay|ok|hey)\b", re.I)
_FREQ_WORDS = re.compile(rf"\b(?:every ?day|daily|each day|every (?:morning|night|evening)|nightly|on weekdays|weekdays|"
                         rf"every weekday|(?:every|each|on) {_DAY}|weekly(?: on {_DAY})?|every week|each week|once a week|"
                         r"(?:on )?the \d{1,2}(?:st|nd|rd|th)?(?: of (?:every|each|the) month)?|monthly(?: on the \d{1,2}(?:st|nd|rd|th)?)?|"
                         r"every month(?: on the \d{1,2}(?:st|nd|rd|th)?)?|each month|once a month|"
                         rf"{_DAY})\b", re.I)


def task_words(text: str) -> str:
    """'I need to do laundry every Sunday, put it in my routine' -> 'do laundry'."""
    t = _FREQ_WORDS.sub(" ", text)
    t = _FILLER.sub(" ", t)
    t = re.sub(r"[,.;:!?]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -")
    t = re.sub(r"^(?:to|my|the|it|that|this)\s+", "", t, flags=re.I)
    t = re.sub(r"\s+(?:it|that|this)$", "", t, flags=re.I)
    return t


def _stems(text: str) -> set[str]:
    return {w[:4] for w in re.findall(r"[a-z]{3,}", text.lower())} - {"the", "did", "just", "alre", "fina", "toda", "yet"}


def matching(chores: "Chores", what: str, due_only: bool = True) -> "Chore | None":
    """A routine task sharing a content word (4-letter stem: 'watered' ~ 'water') with `what`."""
    pool = chores.due() if due_only else chores.active()
    words = _stems(what)
    hits = [c for c in pool if words & _stems(c.text)]
    return hits[0] if len(hits) == 1 else None


def chore_route(text: str, chores: "Chores | None" = None) -> tuple[str, dict] | None:
    """Routine requests done in code: the 4b model said "Done, plants get watered every day now"
    without calling add_routine_task, and answered 'what's my routine?' from the chat."""
    t = text.strip()
    if SHOW.search(t):
        return "routine_today", {}
    if SHOW_ALL.search(t):
        return "routine_today", {"which": "all"}
    if m := REMOVE.search(t):
        item = re.sub(r"^(?:the|my)\s+", "", m.group("item").strip(), flags=re.I)
        if item.lower() not in ("it", "that", "this"):
            return "remove_routine_task", {"which": item}
    if ADD.search(t):
        task = task_words(t)
        if task:
            return "add_routine_task", {"task": task, "how_often": parse_freq(t) or ""}   # no frequency: she asks
        return None
    asked = chores.asking if chores is not None else None
    if asked and time.time() - asked[1] < 600 and len(t.split()) <= 8 and (freq := parse_freq(t)):
        return "add_routine_task", {"task": asked[0], "how_often": freq}      # the answer to "how often?"
    if chores is None:
        return None
    if m := UNTICK.search(t):
        what = m.group("what") or m.group("what2") or ""
        if c := matching(chores, what):
            return "check_routine_task", {"which": c.text, "done": False}
        return None
    if m := TICK.search(t):
        what = m.group("what") or m.group("what2") or ""
        if (c := matching(chores, what)) and not c.done_on(chores.today()):
            return "check_routine_task", {"which": c.text}
    return None


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


class Chores:
    def __init__(self, store, today=dt.date.today):
        self.store = store                 # MemoryStore (its schema has the chores table)
        self.today = today
        self.asking: tuple[str, float] | None = None     # (task, when) after she asked "how often?"

    def _rows(self, where: str, args=()) -> list[Chore]:
        with self.store.lock:
            rows = self.store.db.execute(f"SELECT * FROM chores WHERE {where} ORDER BY created, rowid", args).fetchall()
        return [Chore(r["uid"], r["text"], r["freq"], r["done_day"], r["status"], r["created"], r["updated"]) for r in rows]

    def _write(self, c: Chore):
        with self.store.lock:
            self.store.db.execute(
                "INSERT INTO chores (uid, text, freq, done_day, status, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(uid) DO UPDATE SET text = excluded.text, freq = excluded.freq, done_day = excluded.done_day, "
                "status = excluded.status, updated = excluded.updated",
                (c.uid, c.text, c.freq, c.done_day, c.status,
                 c.created or dt.datetime.now().isoformat(timespec="seconds"), c.updated))
            self.store.db.commit()

    def add(self, text: str, freq: str) -> Chore:
        c = Chore(new_uid(), text.strip(), freq, "", "active", dt.datetime.now().isoformat(timespec="seconds"), now_ms())
        self._write(c)
        return c

    def by_uid(self, uid: str) -> Chore | None:
        rows = self._rows("uid = ?", (uid,))
        return rows[0] if rows else None

    def active(self) -> list[Chore]:
        return self._rows("status = 'active'")

    def due(self, day: dt.date | None = None) -> list[Chore]:
        day = day or self.today()
        return [c for c in self.active() if due_on(c.freq, day)]

    def left(self, day: dt.date | None = None) -> list[Chore]:
        day = day or self.today()
        return [c for c in self.due(day) if not c.done_on(day)]

    def tick(self, uid: str, done: bool = True, day: dt.date | None = None) -> Chore | None:
        c = self.by_uid(uid)
        if c is None or c.status != "active":
            return None
        c.done_day, c.updated = ((day or self.today()).isoformat() if done else ""), now_ms()
        self._write(c)
        return c

    def delete(self, uid: str) -> Chore | None:
        c = self.by_uid(uid)
        if c is None:
            return None
        c.status, c.updated = "deleted", now_ms()
        self._write(c)
        return c

    def find(self, description: str, pool: list[Chore] | None = None) -> Chore | None:
        """Best match for 'the plants one': shared words first, then meaning."""
        items = self.active() if pool is None else pool
        if not items:
            return None
        if len(items) == 1:
            return items[0]
        words = set(re.findall(r"[a-z0-9]{3,}", description.lower()))
        hits = [c for c in items if words & set(re.findall(r"[a-z0-9]{3,}", c.text.lower()))]
        if len(hits) == 1:
            return hits[0]
        pool = hits or items
        embedder = getattr(self.store, "embedder", None)
        if embedder is None:
            return pool[0]
        vecs = embedder.embed([description] + [c.text for c in pool])
        return pool[int((vecs[1:] @ vecs[0]).argmax())]

    def for_sync(self, recent_days: int = 14) -> list[Chore]:
        recent = int((dt.datetime.now() - dt.timedelta(days=recent_days)).timestamp() * 1000)
        return self._rows("status = 'active' OR updated >= ?", (recent,))

    def apply_sync(self, item: dict) -> Chore | None:
        from .sync import wins

        uid = str(item.get("uid") or "")
        text = str(item.get("text") or "").strip()
        freq = str(item.get("freq") or "")
        if not uid or not text or not valid(freq):
            return None
        status = "deleted" if item.get("status") == "deleted" else "active"
        incoming = Chore(uid, text, freq, str(item.get("done_day") or ""), status,
                         str(item.get("created") or "") or dt.datetime.now().isoformat(timespec="seconds"),
                         int(item.get("updated_ms") or now_ms()))
        ours = self.by_uid(uid)
        as_sync = lambda c: {"status": "cancelled" if c.status == "deleted" else "pending", "updated_ms": c.updated}
        if ours is None or wins(as_sync(incoming), as_sync(ours)):
            if ours is not None:
                incoming.updated = max(incoming.updated, ours.updated)
                incoming.created = ours.created
            self._write(incoming)
        return self.by_uid(uid)

    # ----- what she says -----
    def briefing_sentence(self) -> str | None:
        left = self.left()
        if not left:
            return None
        return "On your routine today: " + _join([c.text for c in left[:4]]) + (
            f", plus {len(left) - 4} more" if len(left) > 4 else "") + "."

    def spoken_today(self) -> str:
        day = self.today()
        due = self.due(day)
        if not self.active():
            return "Your routine is empty. Tell me something to do every day, week or month and I'll keep track."
        if not due:
            return "Nothing on your routine today."
        left = [c.text for c in due if not c.done_on(day)]
        done = [c.text for c in due if c.done_on(day)]
        if not left:
            return f"All done for today: {_join(done)}."
        out = f"Still to do today: {_join(left)}."
        return out + (f" Already done: {_join(done)}." if done else "")

    def spoken_all(self) -> str:
        items = self.active()
        if not items:
            return "Your routine is empty."
        return "Your routine: " + "; ".join(f"{c.text}, {label(c.freq)}" for c in items) + "."
