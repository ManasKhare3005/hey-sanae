"""Her diary of your days, and the little shared history between you.

- Diary (table `diary`): after 4 AM, each day you talked gets one short entry, written by the fast
  model from that day's conversation log (only your own voice or typing, as with friend memory)
  plus how you sounded that day (tone.day_summary: daily counts, nothing per message) and how the
  day felt (mood.day_label: good, stressed, a hard day..., from daily counts; saved with every
  entry, whatever the mood). Recall finds
  entries by meaning ("when was I stressed about the midterm?") and by date ("what did I do last
  Tuesday?"). Editable and deletable on the dashboard's Diary tab.
- Moments (table `moments`): running jokes, nicknames, memorable moments and dates (birthdays,
  anniversaries) picked from the same day, so she can say "remember when..." now and then and
  mention a birthday on the day. Each needs words from the day's chat (the model invents otherwise).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .friend import overlap, sensitive
from .memory import now_iso

log = logging.getLogger(__name__)

WRITE_AFTER_HOUR = 4          # a day is written up after 4 AM the next morning (night owls)
BACKFILL_DAYS = 7
RECALL_MIN = 0.66             # diary entries are longer than facts, so they score a bit lower
SAME_MOMENT = 0.88
MOMENT_GAP = dt.timedelta(days=7)
KINDS = ("joke", "nickname", "memory", "date")

DIARY_PROMPT = """You are {name}, {user}'s friend who lives on their laptop, writing your private diary at the end of the day.
Below is today's chat between you ({day}). Write 3 to 5 short, plain sentences: what {user} did or talked about, how {user} seemed, and anything still open (plans, worries, things coming up). Only what's in the chat; never invent. Call them {user}, never "he" or "she". No lists, no title.{tone}{mood}

Chat:
{chat}"""

MOMENTS_PROMPT = """From today's chat between {name} and {user} below, list things worth remembering as shared history:
- "joke": a funny bit they both laughed about
- "nickname": a nickname one of them actually called the other, word for word as it was said
- "memory": a moment {user} would like being reminded of later
- "date": a birthday or anniversary {user} mentioned, with "date" as MM-DD
Each "text" is a short label (under 10 words), not an explanation or a quote. Only what's clearly in the chat; most
days have NONE, and an empty list is the right answer then. Never health, money or anything private.

Chat:
{chat}

Reply as JSON: {{"moments": [{{"kind": "joke|nickname|memory|date", "text": "...", "date": "MM-DD or empty"}}]}}"""

MOMENTS_SCHEMA = {
    "type": "object",
    "properties": {"moments": {"type": "array", "items": {"type": "object", "properties": {
        "kind": {"type": "string", "enum": list(KINDS)}, "text": {"type": "string"}, "date": {"type": "string"}},
        "required": ["kind", "text", "date"]}}},
    "required": ["moments"],
}

REWRITE_PROMPT = """Rewrite this diary entry so it never uses he, she, him, her, his or hers for {user}: use "{user}" or "they" instead. Change nothing else.

{text}"""
NAMING = re.compile(r"\b(call(ing)? (you|me|him|her|them)|nickname|i'?ll call|you'?re my)\b", re.I)
PRONOUNS = re.compile(r"\b(he|she|him|his|hers?|himself|herself)\b", re.I)
NOT_A_MOMENT = re.compile(r"\b(says|said|not a|no (nickname|joke)|isn'?t|aren'?t|none|nothing)\b|[\"“”]", re.I)

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")


@dataclass
class Entry:
    day: str
    text: str
    tone: str
    updated: str
    mood: str = ""


@dataclass
class Moment:
    id: int
    kind: str
    text: str
    date: str
    day: str
    uses: int
    last_used: str


def mentioned_day(text: str, today: dt.date) -> dt.date | None:
    """The day a message points at: "yesterday", "last Tuesday", "on monday", "Oct 13"."""
    t = text.lower()
    if re.search(r"\byesterday\b|\blast night\b", t):
        return today - dt.timedelta(days=1)
    m = re.search(rf"\b(?:last |on |this past )?({'|'.join(WEEKDAYS)})\b", t)
    if m:
        back = (today.weekday() - WEEKDAYS.index(m.group(1))) % 7 or 7
        return today - dt.timedelta(days=back)
    m = re.search(rf"\b({'|'.join(x[:3] for x in MONTHS)})[a-z]*\.? (\d{{1,2}})(?:st|nd|rd|th)?\b", t)
    if m:
        month = [x[:3] for x in MONTHS].index(m.group(1)) + 1
        try:
            d = dt.date(today.year, month, int(m.group(2)))
        except ValueError:
            return None
        return d if d <= today else d.replace(year=today.year - 1)
    return None


class Diary:
    """Tables `diary` and `moments` (memory.SCHEMA), with vectors for search by meaning."""

    def __init__(self, memory):
        self.mem = memory
        self._entries = memory._load_vectors("diary", "text")
        self._moments = memory._load_vectors("moments", "text")

    # ----- diary -----
    def entries(self, limit: int = 60) -> list[Entry]:
        with self.mem.lock:
            rows = self.mem.db.execute("SELECT day, text, tone, updated, mood FROM diary ORDER BY day DESC LIMIT ?",
                                       (limit,)).fetchall()
        return [Entry(r["day"], r["text"], r["tone"], r["updated"], r["mood"]) for r in rows]

    def get(self, day: str) -> Entry | None:
        with self.mem.lock:
            r = self.mem.db.execute("SELECT day, text, tone, updated, mood FROM diary WHERE day = ?", (day,)).fetchone()
        return Entry(r["day"], r["text"], r["tone"], r["updated"], r["mood"]) if r else None

    def put(self, day: str, text: str, tone: str = "", mood: str = "") -> int:
        text = " ".join(text.split()).strip()
        with self.mem.lock:
            row = self.mem.db.execute("SELECT id FROM diary WHERE day = ?", (day,)).fetchone()
            if row:
                self.mem.db.execute("UPDATE diary SET text = ?, tone = ?, mood = ?, updated = ? WHERE id = ?",
                                    (text, tone, mood, now_iso(), row["id"]))
                rid = row["id"]
                self.mem._unindex(self._entries, rid)
            else:
                rid = self.mem.db.execute("INSERT INTO diary (day, text, tone, mood, created, updated) VALUES (?, ?, ?, ?, ?, ?)",
                                          (day, text, tone, mood, now_iso(), now_iso())).lastrowid
            self.mem._index(self._entries, "diary", rid, text)
            return rid

    def delete(self, day: str) -> bool:
        with self.mem.lock:
            row = self.mem.db.execute("SELECT id FROM diary WHERE day = ?", (day,)).fetchone()
            if not row:
                return False
            self.mem.db.execute("DELETE FROM diary WHERE id = ?", (row["id"],))
            self.mem.db.commit()
            self.mem._unindex(self._entries, row["id"])
            return True

    def recall(self, text: str, today: dt.date | None = None) -> list[str]:
        """Diary lines that fit a message: the day it names, else the closest entry by meaning."""
        today = today or dt.date.today()
        day = mentioned_day(text, today)
        if day is not None:
            e = self.get(day.isoformat())
            return [f"your diary for {spoken_day(day, today)}: {e.text}"] if e else []
        try:
            with self.mem.lock:
                hits = [(rid, s) for rid, s in self.mem._search(self._entries, text, 1) if s >= RECALL_MIN]
                rows = [self.mem.db.execute("SELECT day, text FROM diary WHERE id = ?", (rid,)).fetchone() for rid, _ in hits]
        except Exception as exc:
            log.debug("diary recall failed: %s", exc)
            return []
        return [f"your diary for {spoken_day(dt.date.fromisoformat(r['day']), today)}: {r['text']}" for r in rows if r]

    def week(self, today: dt.date) -> list[Entry]:
        start = (today - dt.timedelta(days=7)).isoformat()
        return [e for e in self.entries(14) if start <= e.day < today.isoformat()]

    # ----- moments -----
    def moments(self) -> list[Moment]:
        with self.mem.lock:
            rows = self.mem.db.execute("SELECT id, kind, text, date, day, uses, last_used FROM moments ORDER BY day DESC").fetchall()
        return [Moment(r["id"], r["kind"], r["text"], r["date"], r["day"], r["uses"], r["last_used"]) for r in rows]

    def add_moment(self, kind: str, text: str, day: str, date: str = "") -> int | None:
        text = " ".join(text.split()).strip().rstrip(".")
        if kind not in KINDS or len(text) < 6 or sensitive(text):
            return None
        if kind == "date" and not re.fullmatch(r"\d{2}-\d{2}", date or ""):
            return None
        with self.mem.lock:
            for _rid, score in self.mem._search(self._moments, text, 1):
                if score >= SAME_MOMENT:
                    return None
            rid = self.mem.db.execute("INSERT INTO moments (kind, text, date, day, created) VALUES (?, ?, ?, ?, ?)",
                                      (kind, text, date if kind == "date" else "", day, now_iso())).lastrowid
            self.mem._index(self._moments, "moments", rid, text)
            return rid

    def delete_moment(self, moment_id: int) -> bool:
        with self.mem.lock:
            cur = self.mem.db.execute("DELETE FROM moments WHERE id = ?", (moment_id,))
            self.mem.db.commit()
            self.mem._unindex(self._moments, moment_id)
            return cur.rowcount > 0

    def used(self, moment_id: int, now: dt.datetime | None = None):
        with self.mem.lock:
            self.mem.db.execute("UPDATE moments SET uses = uses + 1, last_used = ? WHERE id = ?",
                                ((now or dt.datetime.now()).isoformat(timespec="seconds"), moment_id))
            self.mem.db.commit()

    def to_bring_up(self, now: dt.datetime) -> Moment | None:
        """A joke / nickname / memory not brought up in the last week, least used first."""
        ok = [m for m in self.moments() if m.kind != "date" and m.day < now.date().isoformat()
              and (not m.last_used or now - dt.datetime.fromisoformat(m.last_used) >= MOMENT_GAP)]
        return min(ok, key=lambda m: (m.uses, m.last_used or ""), default=None)

    def dates_today(self, today: dt.date) -> list[Moment]:
        return [m for m in self.moments() if m.kind == "date" and m.date == f"{today:%m-%d}"]


def spoken_day(day: dt.date, today: dt.date) -> str:
    if day == today - dt.timedelta(days=1):
        return "yesterday"
    if today - day < dt.timedelta(days=7):
        return f"{day:%A}"
    return f"{day:%a %b} {day.day}"


class Writer:
    """Background: writes up each finished day (after 4 AM) that had a conversation."""

    def __init__(self, ctx, diary: Diary, llm, model: str, user: str, name: str,
                 can_run: Callable[[], bool] = lambda: True, publish=lambda kind, data: None, clock=time.time):
        self.ctx, self.diary, self.llm, self.model = ctx, diary, llm, model
        self.user, self.name = user, name
        self.can_run, self.publish, self.clock = can_run, publish, clock
        self._stop = threading.Event()

    def due_days(self) -> list[dt.date]:
        now = dt.datetime.fromtimestamp(self.clock())
        last = (now - dt.timedelta(hours=WRITE_AFTER_HOUR)).date() - dt.timedelta(days=1)   # the last finished day
        done = self.ctx.memory.get("diary:last_day")
        start = dt.date.fromisoformat(done) + dt.timedelta(days=1) if done else last
        start = max(start, last - dt.timedelta(days=BACKFILL_DAYS - 1))
        return [start + dt.timedelta(days=i) for i in range((last - start).days + 1)]

    def chat_for(self, day: dt.date) -> tuple[str, list[str]]:
        """The day's log as lines (only the user's own voice or typing) and the user's own lines."""
        from .friend import LEARN_FROM

        a = dt.datetime.combine(day, dt.time(WRITE_AFTER_HOUR)).isoformat(timespec="seconds")
        b = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(WRITE_AFTER_HOUR)).isoformat(timespec="seconds")
        turns = [t for t in self.ctx.memory.turns_between(a, b) if (t.get("heard") or "") in LEARN_FROM]
        turns = turns[-60:]
        lines = [f"[{t['ts'][11:16]}] {self.user}: {t['user'][:300]}\n{self.name}: {re.sub(r'^(\[[a-z_]+\])+\s*', '', t['reply'])[:300]}"
                 for t in turns]
        return "\n".join(lines), [t["user"] for t in turns]

    def write(self, day: dt.date) -> str | None:
        from .agent import strip_thinking
        from .tone import day_summary

        chat, said = self.chat_for(day)
        if not said:
            return None
        sounded = day_summary(self.ctx.memory, day.isoformat())
        tone_line = f"\nHow {self.user} sounded today (from their voice): {sounded}." if sounded else ""
        from .study import day_summary as study_summary

        studied = study_summary(self.ctx.memory, day.isoformat())
        if studied:
            tone_line += f"\nStudy sessions together today: {self.user} {studied}."
        from .mood import day_label

        felt = day_label(self.ctx.memory, day.isoformat(), sounded)
        mood_line = f"\nHow the day felt for {self.user}: {felt}." if felt else ""
        if felt.startswith("a hard day"):
            mood_line += (" Say gently that it was a hard day and that you two talked it through; don't write down "
                          f"anything {self.user} said about hurting themselves.")
        reply = self.llm.chat(self.model, [{"role": "user", "content": DIARY_PROMPT.format(
            name=self.name, user=self.user, day=f"{day:%A %b} {day.day}", tone=tone_line, mood=mood_line, chat=chat)}],
            options={"temperature": 0.3, "num_predict": 220})
        text = " ".join(strip_thinking(reply.content).split())
        if not text:
            return None
        if PRONOUNS.search(text):                  # the 4b model says "he" whatever the prompt says
            again = self.llm.chat(self.model, [{"role": "user", "content": REWRITE_PROMPT.format(user=self.user, text=text)}],
                                  options={"temperature": 0.1, "num_predict": 260})
            fixed = " ".join(strip_thinking(again.content).split())
            if fixed and len(PRONOUNS.findall(fixed)) < len(PRONOUNS.findall(text)):
                text = fixed
        self.diary.put(day.isoformat(), text, sounded or "", felt)
        try:
            self.moments(day, chat, said)
        except Exception as exc:
            log.info("moments for %s failed: %s", day, exc)
        return text

    def moments(self, day: dt.date, chat: str, said: list[str]) -> list[str]:
        reply = self.llm.chat(self.model, [{"role": "user", "content": MOMENTS_PROMPT.format(
            name=self.name, user=self.user, chat=chat)}], fmt=MOMENTS_SCHEMA, options={"temperature": 0.1, "num_predict": 300})
        try:
            items = json.loads(reply.content).get("moments") or []
        except (TypeError, ValueError):
            return []
        whole = chat.splitlines()
        kept = []
        for m in items[:4]:
            kind, text, date = str(m.get("kind", "")), str(m.get("text", "")), str(m.get("date", ""))
            text = text.split(",")[0].strip()                    # "pasta disaster, instant noodles" -> the label
            source = whole if kind == "nickname" else said     # mostly the user's own words (not her likes)
            if overlap(text, source, (self.user, self.name)) < 0.5:
                continue
            if len(text.split()) > 12 or NOT_A_MOMENT.search(text) or re.search(r"[.,!?…]", text):  # a label, not a sentence
                continue
            if kind == "nickname" and (text.lower() not in chat.lower() or not NAMING.search(chat)):
                continue                                         # said word for word, as a name
            if self.diary.add_moment(kind, text, day.isoformat(), date):
                kept.append(text)
        return kept

    def run_once(self) -> list[str]:
        if not self.can_run():
            return []
        written = []
        for day in self.due_days():
            try:
                if self.write(day):
                    written.append(day.isoformat())
            except Exception as exc:
                log.info("diary for %s failed: %s", day, exc)
                return written                                   # try again later
            self.ctx.memory.set("diary:last_day", day.isoformat())
        if written:
            log.info("diary written for %s", ", ".join(written))
            self.publish("diary", {"days": written})
        return written

    def start(self, interval_s: float = 600.0):
        def loop():
            while not self._stop.wait(interval_s):
                try:
                    self.run_once()
                except Exception as exc:
                    log.warning("diary: %s", exc)

        threading.Thread(target=loop, name="diary", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()
