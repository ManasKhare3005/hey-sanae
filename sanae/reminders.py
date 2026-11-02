"""Reminders: stored in the memory database, fired by a background scheduler.

When one is due, Sanae says it out loud and shows a Windows notification. Reminders that
came due while Sanae wasn't running are announced at the next start ("While you were away"),
except ones the phone has a copy of: the phone already showed those, so Sanae stays quiet.

Repeating reminders ("the 5th of every month", "every Monday at 8") are one row with a rule
(`repeat`: daily, weekdays, weekly, monthly:<day>, yearly:<month>-<day>); when one goes off, its
due time moves on to the next occurrence instead of it being marked done.

Every reminder has a `uid` (shared with the phone, which keeps its own copy and fires it even
when the laptop is off) and an `updated` time; sync.py merges the two sides.
"""
from __future__ import annotations

import calendar
import datetime as dt
import logging
import re
import threading
import uuid
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

DEFAULT_HOUR = 9          # "remind me Friday" with no time -> 9 AM

# Phrases dateparser doesn't understand, rewritten into ones it does
_REWRITES = [
    (r"\bnext\s+(mon|tues|wednes|thurs|fri|satur|sun)day\b", r"\1day"),
    (r"\btonight\s+at\s+(\d{1,2})(?::(\d{2}))?\b(?!\s*[ap]\.?m)", lambda m: f"today at {m.group(1)}:{m.group(2) or '00'} pm"),
    (r"\btonight\b", "today at 8 pm"),
    (r"\bthis\s+(morning|afternoon|evening)\b", r"today \1"),
    (r"\bmorning\b", "9 am"),
    (r"\bafternoon\b", "2 pm"),
    (r"\bevening\b", "6 pm"),
    (r"\bnight\b", "9 pm"),
]
_HAS_TIME = re.compile(r"\d\s*(am|pm|a\.m|p\.m)|\d:\d\d|\bnoon\b|\bmidnight\b|\bin\s+\d+\s*(min|hour|sec)|o'?clock", re.I)


def has_time(text: str) -> bool:
    """Does the phrase name a time of day (not just a day)?"""
    phrase = text
    for pattern, repl in _REWRITES:
        phrase = re.sub(pattern, repl, phrase, flags=re.I)
    return bool(_HAS_TIME.search(phrase)) or bool(re.search(r"T\d\d:\d\d", phrase))


def new_uid() -> str:
    return uuid.uuid4().hex


def now_ms() -> int:
    return int(dt.datetime.now().timestamp() * 1000)


def parse_when(text: str, now: dt.datetime | None = None) -> dt.datetime | None:
    """'Friday at 9am', 'tomorrow morning', 'in 2 hours', '2026-10-02T09:00' -> datetime."""
    import dateparser

    now = now or dt.datetime.now()
    phrase = text.strip()
    for pattern, repl in _REWRITES:
        phrase = re.sub(pattern, repl, phrase, flags=re.I)
    when = dateparser.parse(phrase, settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": now,
                                              "RETURN_AS_TIMEZONE_AWARE": False})
    if when is None:
        return None
    if not _HAS_TIME.search(phrase) and "T" not in phrase:
        when = when.replace(hour=DEFAULT_HOUR, minute=0, second=0, microsecond=0)
    if when <= now and when.date() == now.date() and not _HAS_TIME.search(phrase):
        when += dt.timedelta(days=1)
    return when.replace(microsecond=0)


# ----- repeating reminders -----
REPEAT_KINDS = ("daily", "weekdays", "weekly", "monthly", "yearly")
_DAY = r"(mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?s?"
_ORD = r"(\d{1,2})(?:st|nd|rd|th)?"
_EVERY = r"(?:every|each)"
# (kind, pattern): the first that matches wins; its words are left out when the rest of the phrase is read
_REPEATS = [
    ("weekdays", rf"\b{_EVERY}\s+(?:week\s*|work\s*)days?\b|\b(?:on\s+)?week\s*days\b"),
    ("monthly", rf"\b(?:on\s+)?(?:the\s+)?{_ORD}\s+(?:day\s+)?of\s+{_EVERY}\s+month\b"),
    ("monthly", rf"\b{_EVERY}\s+month'?s\s+{_ORD}(?:\s+day)?\b"),
    ("monthly", rf"\b(?:{_EVERY}\s+month|monthly)(?:\s+on)?(?:\s+the)?(?:\s+{_ORD}(?:\s+day)?\b(?!\s*(?::|[ap]\.?\s*m\b)))?"),
    ("weekly", rf"\b{_EVERY}\s+(?:week\s+on\s+)?{_DAY}\b|\bon\s+{_DAY}s\b"),
    ("weekly", rf"\b(?:{_EVERY}\s+week|weekly)\b"),
    ("daily", rf"\b{_EVERY}\s+(?:day|morning|afternoon|evening|night)\b|\bdaily\b|\bnightly\b"),
    ("yearly", rf"\b(?:{_EVERY}\s+year|yearly|annually)\b"),
]
_TIME_OF_DAY = {"morning": "9 am", "afternoon": "2 pm", "evening": "6 pm", "night": "9 pm"}
_CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\b\.?|\b(\d{1,2}):(\d{2})\b|\b(noon|midnight)\b", re.I)


def _clock(phrase: str) -> tuple[int, int] | None:
    """The time of day in a phrase: '8am', '5:30 pm', '17:00', 'noon', 'every morning' -> (hour, minute)."""
    for word, t in _TIME_OF_DAY.items():
        phrase = re.sub(rf"\b{word}\b", t, phrase, flags=re.I)
    m = _CLOCK.search(phrase)
    if not m:
        return None
    if m.group(6):
        return (12, 0) if m.group(6).lower() == "noon" else (0, 0)
    if m.group(4):
        h, mi = int(m.group(4)), int(m.group(5))
    else:
        h, mi = int(m.group(1)) % 12, int(m.group(2) or 0)
        if m.group(3).lower() == "p":
            h += 12
    return (h, mi) if h < 24 and mi < 60 else None


def _on_day(year: int, month: int, day: int) -> dt.date:
    """That day of the month, or the month's last day when it's shorter (the 31st in April -> the 30th)."""
    return dt.date(year, month, min(day, calendar.monthrange(year, month)[1]))


def next_due(due: dt.datetime, repeat: str, after: dt.datetime) -> dt.datetime:
    """The first occurrence of a repeating reminder later than `after` (skips any that were missed)."""
    kind, _, anchor = repeat.partition(":")
    when = due
    for _ in range(5000):
        if when > after:
            return when
        if kind == "daily":
            when += dt.timedelta(days=1)
        elif kind == "weekdays":
            when += dt.timedelta(days={4: 3, 5: 2}.get(when.weekday(), 1))
        elif kind == "weekly":
            when += dt.timedelta(days=7)
        elif kind == "monthly":
            y, m = (when.year + 1, 1) if when.month == 12 else (when.year, when.month + 1)
            when = dt.datetime.combine(_on_day(y, m, int(anchor or when.day)), when.time())
        elif kind == "yearly":
            mo, d = (int(x) for x in anchor.split("-")) if anchor else (when.month, when.day)
            when = dt.datetime.combine(_on_day(when.year + 1, mo, d), when.time())
        else:
            raise ValueError(f"unknown repeat {repeat!r}")
    raise ValueError("no next occurrence")


def parse_repeating(text: str, kind: str = "", now: dt.datetime | None = None) -> tuple[dt.datetime, str] | None:
    """'the 5th of every month', 'every Monday at 8am', 'daily at 9pm', 'every year on March 3'
    -> (first occurrence, rule). `kind` says how often when the phrase doesn't (the tool's
    repeat="monthly" with when="the 5th"). None: not a repeating phrase."""
    now = (now or dt.datetime.now()).replace(microsecond=0)
    phrase, found, m = text.strip(), "", None
    for k, pattern in _REPEATS:
        m = re.search(pattern, phrase, flags=re.I)
        if m:
            found = k
            break
    kind = found or kind.strip().lower()
    if kind not in REPEAT_KINDS:
        return None
    rest = (phrase[:m.start()] + " " + phrase[m.end():]) if found else phrase
    groups = [g for g in (m.groups() if found else ()) if g]
    at = dt.time(*(_clock(phrase) or (DEFAULT_HOUR, 0)))

    if kind == "monthly":
        day = next((int(g) for g in groups if g.isdigit()), None)
        if day is None:
            o = re.search(rf"\b{_ORD}\b(?!\s*(?::|[ap]\.?\s*m\b))", rest, flags=re.I)
            day = int(o.group(1)) if o else now.day
        if not 1 <= day <= 31:
            return None
        rule = f"monthly:{day}"
        return next_due(dt.datetime.combine(_on_day(now.year, now.month, day), at), rule, now), rule
    if kind == "weekly":
        name = next((g for g in groups if not g.isdigit()), None)
        if name is None:
            w = re.search(rf"\b{_DAY}\b", rest, flags=re.I)
            name = w.group(1) if w else None
        wd = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(name.lower()[:3]) if name else now.weekday()
        start = dt.datetime.combine(now.date() + dt.timedelta(days=(wd - now.weekday()) % 7), at)
        return next_due(start, "weekly", now), "weekly"
    if kind in ("daily", "weekdays"):
        start = dt.datetime.combine(now.date(), at)
        if kind == "weekdays" and start.weekday() >= 5:
            start += dt.timedelta(days=7 - start.weekday())
        return next_due(start, kind, now), kind
    # yearly: the date comes from the rest of the phrase ("on March 3"), else today's
    import dateparser

    words = re.sub(r"\b(at|on|the|in)\b", " ", _CLOCK.sub(" ", rest), flags=re.I).strip(" ,.")
    date = dateparser.parse(words, settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": now}) if words else None
    day = date.date() if date else now.date()
    rule = f"yearly:{day.month}-{day.day}"
    return next_due(dt.datetime.combine(_on_day(now.year, day.month, day.day), at), rule, now), rule


def _clock_words(when: dt.datetime) -> str:
    return f"{when.hour % 12 or 12}{when.strftime(':%M') if when.minute else ''} {'AM' if when.hour < 12 else 'PM'}"


def spoken_repeat(rule: str, when: dt.datetime) -> str:
    """'every Monday at 8 AM', 'on the 5th of every month at 9 AM'."""
    kind, _, anchor = rule.partition(":")
    clock = _clock_words(when)

    def nth(n: int) -> str:
        return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"

    if kind == "daily":
        return f"every day at {clock}"
    if kind == "weekdays":
        return f"every weekday at {clock}"
    if kind == "weekly":
        return f"every {when.strftime('%A')} at {clock}"
    if kind == "monthly":
        return f"on the {nth(int(anchor or when.day))} of every month at {clock}"
    if kind == "yearly":
        mo, d = (int(x) for x in anchor.split("-")) if anchor else (when.month, when.day)
        return f"every year on {calendar.month_name[mo]} {d} at {clock}"
    return spoken_time(when)


def spoken_time(when: dt.datetime, now: dt.datetime | None = None) -> str:
    """'today at 6 PM', 'tomorrow at 9 AM', 'Friday, October 2 at 9:30 AM'."""
    now = now or dt.datetime.now()
    clock = _clock_words(when)
    days =(when.date() - now.date()).days
    if days == 0:
        return f"today at {clock}"
    if days == 1:
        return f"tomorrow at {clock}"
    return f"{when.strftime('%A, %B')} {when.day} at {clock}"


@dataclass
class Reminder:
    id: int
    text: str
    due: dt.datetime
    status: str = "pending"
    uid: str = ""
    updated: int = 0              # ms since the epoch, for sync
    on_phone: bool = False        # the phone has a copy (and fires it itself)
    repeat: str = ""              # "" = once; daily, weekdays, weekly, monthly:<day>, yearly:<month>-<day>

    def to_sync(self) -> dict:
        return {"uid": self.uid, "text": self.text, "due_ms": int(self.due.timestamp() * 1000),
                "status": self.status, "updated_ms": self.updated, "repeat": self.repeat}

    def spoken(self, now: dt.datetime | None = None) -> str:
        """'tomorrow at 9 AM', or 'on the 5th of every month at 9 AM, starting Thursday, November 5'."""
        if not self.repeat:
            return spoken_time(self.due, now)
        return f"{spoken_repeat(self.repeat, self.due)}, starting {spoken_time(self.due, now).rsplit(' at ', 1)[0]}"


def migrate(db):
    """Older databases: add uid / updated / on_phone / repeat_rule to reminders."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(reminders)")}
    if "uid" not in cols:
        db.execute("ALTER TABLE reminders ADD COLUMN uid TEXT")
    if "updated" not in cols:
        db.execute("ALTER TABLE reminders ADD COLUMN updated INTEGER NOT NULL DEFAULT 0")
    if "on_phone" not in cols:
        db.execute("ALTER TABLE reminders ADD COLUMN on_phone INTEGER NOT NULL DEFAULT 0")
    if "repeat_rule" not in cols:
        db.execute("ALTER TABLE reminders ADD COLUMN repeat_rule TEXT NOT NULL DEFAULT ''")
    for (rid,) in db.execute("SELECT id FROM reminders WHERE uid IS NULL OR uid = ''").fetchall():
        db.execute("UPDATE reminders SET uid = ?, updated = ? WHERE id = ?", (new_uid(), now_ms(), rid))
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS reminders_uid ON reminders(uid)")
    db.commit()


class Reminders:
    def __init__(self, store):
        self.store = store            # MemoryStore (shares its database and lock)
        with store.lock:
            migrate(store.db)

    def add(self, text: str, due: dt.datetime, uid: str = "", repeat: str = "") -> Reminder:
        uid, updated = uid or new_uid(), now_ms()
        due = due.replace(microsecond=0)
        with self.store.lock:
            cur = self.store.db.execute(
                "INSERT INTO reminders (text, due, created, uid, updated, repeat_rule) VALUES (?, ?, ?, ?, ?, ?)",
                (text.strip(), due.isoformat(timespec="seconds"),
                 dt.datetime.now().isoformat(timespec="seconds"), uid, updated, repeat))
            self.store.db.commit()
            return Reminder(cur.lastrowid, text.strip(), due, uid=uid, updated=updated, repeat=repeat)

    def _rows(self, where: str, args=()) -> list[Reminder]:
        with self.store.lock:
            rows = self.store.db.execute(
                f"SELECT id, text, due, status, uid, updated, on_phone, repeat_rule FROM reminders "
                f"WHERE {where} ORDER BY due", args).fetchall()
        return [Reminder(r["id"], r["text"], dt.datetime.fromisoformat(r["due"]), r["status"], r["uid"],
                         r["updated"], bool(r["on_phone"]), r["repeat_rule"] or "") for r in rows]

    def by_uid(self, uid: str) -> Reminder | None:
        rows = self._rows("uid = ?", (uid,))
        return rows[0] if rows else None

    def for_sync(self, days: int = 14) -> list[Reminder]:
        """Pending ones, and any that changed lately (so the phone hears about done / cancelled)."""
        since = int((dt.datetime.now() - dt.timedelta(days=days)).timestamp() * 1000)
        return self._rows("status = 'pending' OR updated >= ?", (since,))

    def apply_sync(self, item: dict) -> Reminder | None:
        """A reminder from the phone: insert it, or update ours if theirs wins (sync.wins)."""
        from .sync import wins

        uid = str(item.get("uid") or "")
        if not uid or not str(item.get("text") or "").strip():
            return None
        due = dt.datetime.fromtimestamp(int(item["due_ms"]) / 1000).replace(microsecond=0)
        status = item.get("status") if item.get("status") in ("pending", "done", "cancelled") else "pending"
        updated = int(item.get("updated_ms") or now_ms())
        ours = self.by_uid(uid)
        # an older phone app doesn't send "repeat": keep ours then
        repeat = str(item.get("repeat") or "") if "repeat" in item else (ours.repeat if ours else "")
        with self.store.lock:
            if ours is None:
                self.store.db.execute(
                    "INSERT INTO reminders (text, due, created, status, uid, updated, on_phone, repeat_rule) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                    (str(item["text"]).strip(), due.isoformat(timespec="seconds"),
                     dt.datetime.now().isoformat(timespec="seconds"), status, uid, updated, repeat))
            elif wins({**item, "status": status, "updated_ms": updated}, ours.to_sync()):
                updated = max(updated, ours.updated)      # never older than what we had (phone clocks drift)
                self.store.db.execute(
                    "UPDATE reminders SET text = ?, due = ?, status = ?, updated = ?, on_phone = 1, repeat_rule = ? "
                    "WHERE uid = ?",
                    (str(item["text"]).strip(), due.isoformat(timespec="seconds"), status, updated, repeat, uid))
            else:
                self.store.db.execute("UPDATE reminders SET on_phone = 1 WHERE uid = ?", (uid,))
            self.store.db.commit()
        return self.by_uid(uid)

    def mark_on_phone(self, uids: list[str]):
        with self.store.lock:
            self.store.db.executemany("UPDATE reminders SET on_phone = 1 WHERE uid = ?", [(u,) for u in uids])
            self.store.db.commit()

    def pending(self) -> list[Reminder]:
        return self._rows("status = 'pending'")

    def due(self, now: dt.datetime | None = None) -> list[Reminder]:
        now = now or dt.datetime.now()
        return self._rows("status = 'pending' AND due <= ?", (now.isoformat(timespec="seconds"),))

    def set_status(self, rid: int, status: str):
        with self.store.lock:
            self.store.db.execute("UPDATE reminders SET status = ?, fired = ?, updated = ? WHERE id = ?",
                                  (status, dt.datetime.now().isoformat(timespec="seconds"), now_ms(), rid))
            self.store.db.commit()

    def advance(self, r: Reminder, now: dt.datetime | None = None) -> dt.datetime:
        """A repeating reminder went off: move it on to its next occurrence (it stays pending)."""
        nxt = next_due(r.due, r.repeat, now or dt.datetime.now())
        with self.store.lock:
            self.store.db.execute("UPDATE reminders SET due = ?, fired = ?, updated = ? WHERE id = ?",
                                  (nxt.isoformat(timespec="seconds"), dt.datetime.now().isoformat(timespec="seconds"),
                                   now_ms(), r.id))
            self.store.db.commit()
        return nxt

    def find(self, description: str) -> Reminder | None:
        """Best pending match for 'the exam reminder' (by meaning, via the embedder)."""
        items = self.pending()
        if not items:
            return None
        if len(items) == 1:
            return items[0]
        vecs = self.store.embedder.embed([description] + [r.text for r in items])
        scores = vecs[1:] @ vecs[0]
        return items[int(scores.argmax())]


class ReminderScheduler:
    """Checks for due reminders every few seconds and hands them to `fire`."""

    def __init__(self, reminders: Reminders, fire: Callable[[Reminder, bool], None], interval_s: float = 10.0,
                 missed_after_s: float = 300.0):
        self.reminders = reminders
        self.fire = fire               # fire(reminder, missed)
        self.interval_s = interval_s
        self.missed_after_s = missed_after_s
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._run, name="reminders", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    def check(self, now: dt.datetime | None = None):
        now = now or dt.datetime.now()
        for r in self.reminders.due(now):
            missed = (now - r.due).total_seconds() > self.missed_after_s
            if not (missed and r.on_phone):    # the phone showed it while Sanae was away: stay quiet
                try:
                    self.fire(r, missed)
                except Exception as exc:
                    log.warning("reminder %s failed to fire: %s", r.id, exc)
            if r.repeat:
                try:
                    self.reminders.advance(r, now)
                    continue
                except ValueError as exc:
                    log.warning("reminder %s: bad repeat %r (%s), done instead", r.id, r.repeat, exc)
            self.reminders.set_status(r.id, "done")

    def _run(self):
        while not self._stop.is_set():
            self.check()
            self._stop.wait(self.interval_s)


APP_NAME = "Sanae"      # who notifications come from; main sets it to the persona's name


def toast(title: str, message: str):
    """Windows notification; silently skipped elsewhere or if it fails."""
    try:
        from winotify import Notification, audio

        n = Notification(app_id=APP_NAME, title=title, msg=message, duration="long")
        n.set_audio(audio.Reminder, loop=False)
        n.show()
    except Exception as exc:
        log.debug("toast failed: %s", exc)
