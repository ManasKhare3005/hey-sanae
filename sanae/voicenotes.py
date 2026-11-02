"""Voice notes from her: some mornings there's a short voice message waiting on your phone, in her
own voice, like a friend's morning voice memo.

Made overnight here (from 3 AM, while the laptop is free): a few sentences that are about *you*,
from what's true (last night's notebook page if it isn't private, how yesterday felt, what's on
today), then spoken with her voice (Piper) into data/voicenotes/<day>.wav. The phone downloads it
on its next sync and shows it in the morning, so it plays even without the laptop.

Not every day: about four mornings a week, and always when something big is on today, you wrote
in the notebook last night, or yesterday was a hard day.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
import threading
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS voicenotes (
    id INTEGER PRIMARY KEY, day TEXT NOT NULL UNIQUE, text TEXT NOT NULL, file TEXT NOT NULL, seconds REAL NOT NULL DEFAULT 0,
    created TEXT NOT NULL);
"""
BIG = re.compile(r"\b(exam|midterm|final|quiz|test|interview|presentation|demo|due|deadline|defen[cs]e)\b", re.I)
PROMPT = (
    "You are {her}. Record a short voice message for your friend {user} to hear when they wake up this morning "
    "({day}). It's like a friend's morning voice memo: personal, warm, a little playful, about THEM.\n\n"
    "What's true right now (use only this, pick one or two things, don't list them):\n{facts}\n\n"
    "Write only the words you'll say: {words} words, 2 to 4 short spoken sentences, starting with a natural "
    "good-morning. Be kind about anything they felt bad about (no judging, no \"that's so you\"). No emojis, no stage "
    "directions, no asterisks, no numbers or times that aren't above. Don't invent "
    "plans or events."
)
KEEP_DAYS = 21


class VoiceNotes:
    name = "voicenotes"

    def __init__(self, store, llm=None, model: str = "", user: str = "them", her: str = "Sanae", ctx=None,
                 voice: Callable[[], object] | None = None, folder: str | Path = "data/voicenotes",
                 clock: Callable[[], float] = time.time, can_run: Callable[[], bool] = lambda: True,
                 publish=lambda kind, data: None, settings: dict | None = None):
        s = settings or {}
        self.store, self.llm, self.model, self.user, self.her, self.ctx = store, llm, model, user, her, ctx
        self.voice = voice                      # () -> object with synthesize(text) -> (audio, sr)
        from .config import resolve_path

        self.folder = resolve_path(str(folder)) if not Path(folder).is_absolute() else Path(folder)
        self.clock, self.can_run, self.publish = clock, can_run, publish
        self.per_week = int(s.get("per_week", 4))
        self.from_hour, self.until_hour = int(s.get("from_hour", 3)), int(s.get("until_hour", 8))
        self._stop = threading.Event()
        with store.lock:
            store.db.executescript(SCHEMA)
            store.db.commit()

    def _rows(self, sql: str, args=()) -> list[dict]:
        with self.store.lock:
            return [dict(r) for r in self.store.db.execute(sql, args).fetchall()]

    def _exec(self, sql: str, args=()):
        with self.store.lock:
            cur = self.store.db.execute(sql, args)
            self.store.db.commit()
            return cur

    def now(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.clock())

    # ----- what's true this morning -----
    def facts(self, today: dt.date) -> tuple[list[str], bool]:
        """(lines for the prompt, whether today is worth a note for sure)."""
        out, must = [], False
        yesterday = (today - dt.timedelta(days=1)).isoformat()
        try:
            j = self._rows("SELECT text, mood, created FROM journal WHERE author = 'you' AND kind = 'page' AND private = 0 "
                           "AND day = ? ORDER BY id DESC LIMIT 1", (yesterday,))
        except Exception:
            j = []
        if j:
            page = j[0]["text"]
            out.append(f"Last night they wrote in your shared notebook{' (feeling ' + j[0]['mood'] + ')' if j[0]['mood'] else ''}: "
                       f"\"{page[:500]}\"")
            must = True
        try:
            from .mood import day_label

            felt = day_label(self.store, yesterday)
        except Exception:
            felt = ""
        if felt:
            out.append(f"Yesterday felt like {felt} for them.")
            must = must or felt.startswith("a hard day")
        start = dt.datetime.combine(today, dt.time(0, 0))
        end = start + dt.timedelta(days=1)
        today_items = []
        events = getattr(self.ctx, "events", None)
        try:
            for e in events.between(start, end) if events is not None else []:
                today_items.append(e.title + ("" if e.all_day else f" at {e.start.hour % 12 or 12}"
                                              f"{e.start.strftime(':%M') if e.start.minute else ''} {'AM' if e.start.hour < 12 else 'PM'}"))
        except Exception as exc:
            log.debug("voicenotes: events: %s", exc)
        canvas = getattr(self.ctx, "canvas", None)
        try:
            for item in canvas.items() if canvas is not None else []:
                if item.kind == "assignment" and start <= item.start < end:
                    today_items.append(f"{item.title} due today")
        except Exception as exc:
            log.debug("voicenotes: canvas: %s", exc)
        if today_items:
            out.append("On today: " + "; ".join(today_items[:4]) + ".")
            must = must or any(BIG.search(x) for x in today_items)
        life = getattr(self.ctx, "life", None)
        try:
            word = life.word_today() if life is not None else None
        except Exception:
            word = None
        if word:
            out.append(f"About you (optional, only if it fits): you're {word}.")
        return out, must

    def wanted(self, today: dt.date, must: bool) -> bool:
        """About `per_week` mornings a week, the same answer all day (hash of the date)."""
        if must:
            return True
        h = int(hashlib.sha1(today.isoformat().encode()).hexdigest(), 16) % 7
        return h < self.per_week

    # ----- making one -----
    def write(self, today: dt.date) -> str | None:
        facts, _ = self.facts(today)
        if not facts or self.llm is None:
            return None
        from .agent import strip_thinking
        from .tags import ASIDE, EMOJI, TAG

        context = "\n".join(f"- {f}" for f in facts)
        prompt = PROMPT.format(her=self.her, user=self.user, day=f"{today:%A}", facts=context, words="35 to 70")
        allowed = set(re.findall(r"\d+", context))
        for attempt in range(2):
            try:
                raw = self.llm.chat(self.model, [{"role": "user", "content": prompt}],
                                    options={"temperature": 0.8 + 0.1 * attempt, "num_predict": 160}).content
            except Exception as exc:
                log.info("voicenotes: model failed: %s", exc)
                return None
            text = " ".join(EMOJI.sub("", ASIDE.sub("", TAG.sub("", strip_thinking(raw)))).split()).strip().strip('"')
            n = len(text.split())
            if 15 <= n <= 110 and not (set(re.findall(r"\d+", text)) - allowed):
                from .timesense import fix

                return fix(text, dt.datetime.combine(today, dt.time(8, 0)))
            log.info("voicenotes: dropped a draft (%d words): %s", n, text[:120])
        return None

    def make(self, today: dt.date | None = None, force: bool = False) -> dict | None:
        today = today or self.now().date()
        if self._rows("SELECT 1 FROM voicenotes WHERE day = ?", (today.isoformat(),)):
            return None
        facts, must = self.facts(today)
        if not force and not self.wanted(today, must):
            self._exec("INSERT OR IGNORE INTO kv (key, value) VALUES (?, 'skip')", (f"voicenotes:skip:{today}",))
            return None
        text = self.write(today)
        if not text or self.voice is None:
            return None
        from .remote import encode_wav

        audio, sr = self.voice().synthesize(text)
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{today.isoformat()}.wav"
        path.write_bytes(encode_wav(audio, sr))
        secs = round(len(audio) / float(sr), 1)
        cur = self._exec("INSERT INTO voicenotes (day, text, file, seconds, created) VALUES (?,?,?,?,?)",
                         (today.isoformat(), text, str(path), secs, self.now().isoformat(timespec="seconds")))
        self._prune()
        note = self.get(cur.lastrowid)
        self.publish("us", {"what": "voicenotes", "action": "new", "id": note["id"]})
        log.info("voicenotes: made %s (%.1fs): %s", today, secs, text)
        return note

    def _prune(self):
        cutoff = (self.now().date() - dt.timedelta(days=KEEP_DAYS)).isoformat()
        for r in self._rows("SELECT id, file FROM voicenotes WHERE day < ?", (cutoff,)):
            try:
                Path(r["file"]).unlink(missing_ok=True)
            except OSError:
                pass
            self._exec("DELETE FROM voicenotes WHERE id = ?", (r["id"],))

    def get(self, nid: int) -> dict | None:
        rows = self._rows("SELECT * FROM voicenotes WHERE id = ?", (nid,))
        return rows[0] if rows else None

    def status(self) -> dict:
        return {"notes": [{"id": r["id"], "day": r["day"], "text": r["text"], "seconds": r["seconds"], "created": r["created"]}
                          for r in self._rows("SELECT * FROM voicenotes ORDER BY day DESC LIMIT 10")]}

    # ----- overnight -----
    def due(self) -> bool:
        d = self.now()
        if not self.from_hour <= d.hour < self.until_hour:
            return False
        today = d.date().isoformat()
        return not self._rows("SELECT 1 FROM voicenotes WHERE day = ?", (today,)) and \
            not self._rows("SELECT 1 FROM kv WHERE key = ?", (f"voicenotes:skip:{today}",))

    def tick(self):
        if self.due() and self.can_run():
            self.make()

    def start(self, every_s: float = 600):
        def loop():
            self._stop.wait(120)
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception as exc:
                    log.warning("voicenotes: %s", exc)
                self._stop.wait(every_s)

        threading.Thread(target=loop, name="voicenotes", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    # part.py hooks: no moments, no notes
    def moments(self, now: float) -> list:
        return []

    def used(self, moment, now: float):
        pass

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        return []
