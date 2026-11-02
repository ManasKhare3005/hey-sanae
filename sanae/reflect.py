"""The nightly look back: Claude rereads yesterday's chats and she keeps a few lessons.

Once a day (after the day ends at 4 AM; caught up later if the laptop was off), the day's
turns go to her slow brain (cloudbrain.py), already filtered: only your voice or typing and her
own lines, nothing from a hard moment (a day with one is skipped entirely), sensitive sentences
dropped and names swapped. Claude looks at HOW she talked (made-up things, odd timing, repeating
herself, missing what you asked, questions that landed) and writes at most 3 lessons as notes to
herself ("Don't ask whether they ate breakfast in the evening").

Lessons live in the `lessons` table for LESSON_DAYS (seen again = kept longer, at most
MAX_ACTIVE); Claude can also retire ones the day showed were wrong. The newest few go into her
replies and the lines she says first, as "(Your own lessons from past chats: ...)". The phone's
Settings -> "Her brain" lists them; you can delete any.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
import time
from typing import Callable

from .part import Part

log = logging.getLogger(__name__)
LESSON_DAYS = 21
MAX_ACTIVE = 8
IN_NOTES = 3
MIN_TURNS = 3
DAY_START_H = 4                      # her days run 4 AM to 4 AM (like the diary)
RUN_FROM = dt.time(4, 30)
CATCH_UP_DAYS = 2

SCHEMA = {
    "type": "object",
    "properties": {
        "lessons": {"type": "array", "maxItems": 3, "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "kind": {"type": "string",
                           "enum": ["made_up", "timing", "repetition", "listening", "tone", "worked"]},
                           "evidence": {"type": "string"}},
            "required": ["text", "kind", "evidence"]}},
        "retire": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["lessons", "retire"],
}

SYSTEM = """You coach {her}, an AI companion who lives on the user's laptop and phone. She runs on a small local model, so she makes things up, misjudges the time of day, repeats herself and sometimes misses what the user asked. You read one day of her chats with the user and help her get better at being a real friend.

Write at most 3 lessons, as short notes to herself (under 20 words each, plain words, "you" = {her}), that would have made this day's chats better, or that capture something that clearly worked. Only lessons the chat itself shows; never guess about the user's life. Prefer concrete ones ("Don't ask whether they ate breakfast in the evening") over vague ones ("Be more caring"). Each lesson needs a short quote or description of the moment that shows it (evidence). Skip anything already covered by her current lessons. If the day shows a current lesson is wrong or no longer needed, put its number in "retire". A quiet day can have no lessons.

Lines starting "[she spoke first]" are messages she started on her own. Names were swapped for "a friend" and some details hidden as [number] or [link] for privacy: ignore that."""

PROMPT = """{her}'s current lessons:
{lessons}

The chats on {day} ({weekday}):
{turns}"""


def overlap(a: str, b: str) -> float:
    wa, wb = set(re.findall(r"[a-z']{3,}", a.lower())), set(re.findall(r"[a-z']{3,}", b.lower()))
    return len(wa & wb) / max(1, min(len(wa), len(wb)))


class Reflection(Part):
    name = "reflect"

    def __init__(self, store=None, clock=time.time, brain=None, user: str = "the user", her: str = "Sanae",
                 can_run: Callable[[], bool] = lambda: True):
        super().__init__(store, clock)
        self.brain, self.user, self.her, self.can_run = brain, user, her, can_run
        self._stop = threading.Event()
        self._schema("""CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY, text TEXT NOT NULL, kind TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '',
            day TEXT NOT NULL, created TEXT NOT NULL, expires TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 1)""")

    # ----- lessons -----
    def lessons(self) -> list[dict]:
        today = self.now().date().isoformat()
        return self._rows("SELECT * FROM lessons WHERE expires >= ? ORDER BY seen DESC, created DESC", (today,))

    def remove(self, lid: int) -> bool:
        before = len(self._rows("SELECT id FROM lessons WHERE id = ?", (lid,)))
        self._exec("DELETE FROM lessons WHERE id = ?", (lid,))
        return bool(before)

    def add(self, text: str, kind: str, evidence: str, day: str) -> str:
        text = " ".join(text.split()).strip().strip('"')
        if not text or len(text.split()) > 30:
            return "dropped"
        now = self.now()
        until = (now.date() + dt.timedelta(days=LESSON_DAYS)).isoformat()
        for old in self.lessons():
            if overlap(old["text"], text) >= 0.7:            # the same lesson again: it matters, keep it longer
                self._exec("UPDATE lessons SET seen = seen + 1, expires = ? WHERE id = ?", (until, old["id"]))
                return "seen again"
        self._exec("INSERT INTO lessons (text, kind, evidence, day, created, expires) VALUES (?,?,?,?,?,?)",
                   (text, kind, evidence[:200], day, now.isoformat(timespec="seconds"), until))
        active = self.lessons()
        for extra in sorted(active, key=lambda r: (r["seen"], r["created"]))[:max(0, len(active) - MAX_ACTIVE)]:
            self._exec("DELETE FROM lessons WHERE id = ?", (extra["id"],))
        return "added"

    def note(self) -> str | None:
        top = [l["text"].rstrip(".") for l in self.lessons()[:IN_NOTES]]
        return ("Your own lessons from past chats: " + "; ".join(top)) if top else None

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        n = self.note()
        return [n] if n else []

    # ----- the day -----
    def day_window(self, day: dt.date) -> tuple[str, str]:
        start = dt.datetime.combine(day, dt.time(DAY_START_H))
        return start.isoformat(timespec="seconds"), (start + dt.timedelta(days=1)).isoformat(timespec="seconds")

    def day_lines(self, day: dt.date) -> list[str] | None:
        """The day's chat as it may leave the laptop, or None when the day is private."""
        if self.store is None or self.brain is None:
            return None
        start, end = self.day_window(day)
        turns = self.store.turns_between(start, end)
        private = set(json.loads(self.store.get("comfort:turns") or "[]"))
        if any(t["id"] in private for t in turns):
            return None                                     # a hard moment that day: none of it goes out
        turns = [t for t in turns if (t.get("heard") or "") in ("", "you", "she")]   # not someone else's voice
        texts = [x for t in turns for x in ((t.get("user") or "").strip(), (t.get("reply") or "").strip())]
        cleaned = iter(self.brain.clean_all(texts))
        lines = []
        for t in turns:
            heard = t.get("heard") or ""
            clock = t["ts"][11:16]
            user = (t.get("user") or "").strip()
            said, reply = next(cleaned), next(cleaned)
            if user and heard != "she" and said:
                lines.append(f"[{clock}] the user: {said}")
            if reply:
                who = f"[{clock}] [she spoke first] {self.her}" if not user or heard == "she" else f"[{clock}] {self.her}"
                lines.append(f"{who}: {reply}")
        return lines

    def due_day(self) -> dt.date | None:
        now = self.now()
        if now.time() < RUN_FROM:
            return None
        last = self.get("last_day")
        yesterday = now.date() - dt.timedelta(days=1)
        if last is None:
            return yesterday                               # first run: start with yesterday
        for back in range(CATCH_UP_DAYS - 1, -1, -1):
            d = yesterday - dt.timedelta(days=back)
            if last is None or d.isoformat() > last:
                return d
        return None

    def reflect(self, day: dt.date) -> list[str]:
        """One day -> lessons kept (texts). Marks the day done even when there was nothing to learn."""
        lines = self.day_lines(day)
        if lines is None or not self.brain.available:
            self.put("last_day", day.isoformat())
            return []
        users = [l for l in lines if "] the user: " in l]
        if len(users) < MIN_TURNS:
            self.put("last_day", day.isoformat())
            return []
        current = self.lessons()
        listed = "\n".join(f"{l['id']}. {self.brain.clean(l['text']) or l['text']}" for l in current) or "(none yet)"
        prompt = PROMPT.format(her=self.her, lessons=listed, day=day.isoformat(), weekday=f"{day:%A}",
                               turns="\n".join(lines[-160:]))
        got = self.brain.ask("reflect", SYSTEM.format(her=self.her), prompt, SCHEMA)
        if got is None:
            return []                                      # try again later (limit, offline...)
        self.put("last_day", day.isoformat())
        ids = {l["id"] for l in current}
        for lid in got.get("retire") or []:
            if isinstance(lid, int) and lid in ids:
                self.remove(lid)
                log.info("reflect: retired lesson %d", lid)
        kept = []
        for item in (got.get("lessons") or [])[:3]:
            text = self.brain.redactor.back(str(item.get("text") or ""))
            what = self.add(text, str(item.get("kind") or ""), str(item.get("evidence") or ""), day.isoformat())
            if what != "dropped":
                kept.append(text)
                log.info("reflect: lesson (%s): %s", what, text)
        return kept

    def tick(self):
        day = self.due_day()
        if day is not None and self.can_run():
            self.reflect(day)

    def start(self, every_s: float = 900):
        def loop():
            self._stop.wait(240)
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception as exc:
                    log.warning("reflect: %s", exc)
                self._stop.wait(every_s)

        threading.Thread(target=loop, name="reflect", daemon=True).start()
        return self

    def status(self) -> dict:
        return {"lessons": [{k: l[k] for k in ("id", "text", "kind", "evidence", "day", "seen")} for l in self.lessons()],
                "last_day": self.get("last_day")}
