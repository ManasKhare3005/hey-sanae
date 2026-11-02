"""Your week in review, her version: on Sunday evening a short story-style recap on the phone (tap
through like stories), built from what's true this week:

  1. the week at a glance: how it felt (your daily moods), days you two talked;
  2. doing it together: things done, best streak, what's new in your shared room, goals hit;
  3. wins she noticed (wins.py);
  4. your notebook: pages written and their moods, and a highlight from her diary of your chats;
  5. a moment from the week (a running joke, a nickname, something you'll remember);
  6. what she's proud of you for (the model, from the slides above only; no made-up numbers);
  7. next week: the one or two things coming up.

Made once per week (Sunday from 18:00, or Monday if the laptop was off), kept in the `weekly` table;
the phone shows the newest and lets you rewatch the last few.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS weekly (
    id INTEGER PRIMARY KEY, week TEXT NOT NULL UNIQUE, start TEXT NOT NULL, data TEXT NOT NULL, created TEXT NOT NULL);
"""
PROUD_PROMPT = (
    "You are {her}, {user}'s close friend. Here's their week, all true:\n{facts}\n\n"
    "In one or two short sentences (under 40 words), tell them the one thing you're proudest of them for this week, "
    "warmly and specifically, picking from the facts above. Talk to them (\"you\"). No emojis, no numbers that aren't "
    "above, nothing invented."
)
ROUGH = ("stressed", "tired", "down", "frustrated")
FEELS = {"great": "a really good week", "good": "a good week", "okay": "an okay week", "mixed": "a bit of everything",
         "rough": "a rough week, honestly"}


def week_start(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


class Weekly:
    name = "weekly"

    def __init__(self, store, ctx=None, llm=None, model: str = "", user: str = "them", her: str = "Sanae",
                 clock: Callable[[], float] = time.time, can_run: Callable[[], bool] = lambda: True,
                 publish=lambda kind, data: None):
        self.store, self.ctx, self.llm, self.model, self.user, self.her = store, ctx, llm, model, user, her
        self.clock, self.can_run, self.publish = clock, can_run, publish
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

    # ----- the slides -----
    def _days_in(self, start: dt.date) -> list[str]:
        return [(start + dt.timedelta(days=i)).isoformat() for i in range(7)]

    def feel(self, start: dt.date) -> tuple[str, int]:
        from .mood import _days

        days = _days(self.store)
        week = [days[d] for d in self._days_in(start) if d in days]
        if not week:
            return "", 0
        rough = sum(1 for t in week if t.get("hard") or any(t.get(k, 0) for k in ROUGH))
        nice = sum(1 for t in week if t.get("nice", 0) or t.get("excited", 0))
        if rough >= 4:
            label = "rough"
        elif rough >= 2:
            label = "mixed"
        elif nice >= 3:
            label = "great"
        elif nice >= 1:
            label = "good"
        else:
            label = "okay"
        return label, len(week)

    def talked_days(self, start: dt.date) -> int:
        end = start + dt.timedelta(days=7)
        rows = self._rows("SELECT COUNT(DISTINCT substr(ts, 1, 10)) AS n FROM turns WHERE ts >= ? AND ts < ?",
                          (start.isoformat(), end.isoformat()))
        return int(rows[0]["n"]) if rows else 0

    def together(self, start: dt.date) -> dict | None:
        t = getattr(self.ctx, "together", None)
        if t is None:
            return None
        days = self._days_in(start)
        try:
            done = self._rows(f"SELECT COUNT(*) AS n FROM activity_log WHERE how != 'pass' AND day IN ({','.join('?' * 7)})", days)[0]["n"]
            before = self._rows("SELECT COUNT(*) AS n FROM activity_log WHERE how != 'pass' AND day < ?", (days[0],))[0]["n"]
        except Exception:
            return None
        from .together import ROOM, ROOM_NAMES

        new_items = [ROOM_NAMES[name] for need, name in ROOM if before < need <= before + done]
        end = dt.date.fromisoformat(days[-1])
        best = None
        for a in t.all():
            st = t.streak(a, end)
            if st >= 2 and (best is None or st > best[1]):
                best = (a["title"], st, "weeks" if a["days"].endswith("/week") else "days")
        goals = getattr(self.ctx, "goals", None)
        hit = goals.week_wins() if goals is not None else []
        if not done and not hit:
            return None
        return {"done": done, "best": {"title": best[0], "streak": best[1], "unit": best[2]} if best else None,
                "room": new_items, "goals": hit}

    def wins(self, start: dt.date) -> list[str]:
        w = getattr(self.ctx, "wins", None)
        if w is None:
            return []
        days = set(self._days_in(start))
        return [x["text"] for x in w.recent(14) if x["day"] in days][:4]

    def notebook(self, start: dt.date) -> dict | None:
        days = self._days_in(start)
        try:
            pages = self._rows(f"SELECT mood FROM journal WHERE author = 'you' AND kind = 'page' AND day IN ({','.join('?' * 7)}) "
                               "ORDER BY id", days)
        except Exception:
            pages = []
        diary = getattr(self.ctx, "diary", None)
        highlight = ""
        if diary is not None:
            try:
                entries = [e for e in diary.entries(14) if e.day in days]
                good = [e for e in entries if getattr(e, "mood", "") in ("great", "good")] or entries
                if good:
                    highlight = re.split(r"(?<=[.!?])\s+", good[0].text.strip())[0][:220]
            except Exception:
                highlight = ""
        if not pages and not highlight:
            return None
        return {"pages": len(pages), "moods": [p["mood"] for p in pages if p["mood"]], "highlight": highlight}

    def moment(self, start: dt.date) -> dict | None:
        diary = getattr(self.ctx, "diary", None)
        if diary is None:
            return None
        days = set(self._days_in(start))
        try:
            found = [m for m in diary.moments() if m.day in days]
        except Exception:
            return None
        order = {"joke": 0, "nickname": 1, "memory": 2, "date": 3}
        found.sort(key=lambda m: order.get(m.kind, 9))
        return {"type": found[0].kind, "text": found[0].text} if found else None

    def photos(self, start: dt.date) -> list[dict]:
        book = getattr(self.ctx, "scrapbook", None)
        if book is None:
            return []
        try:
            return [{"id": p["id"], "caption": p["caption"]} for p in book.between(start, start + dt.timedelta(days=6))][-4:]
        except Exception:
            return []

    def next_week(self, start: dt.date) -> list[str]:
        rituals = getattr(self.ctx, "rituals", None)
        if rituals is None:
            return []
        try:
            return rituals.week_ahead(dt.datetime.combine(start + dt.timedelta(days=7), dt.time(0, 0)))[:3]
        except Exception:
            return []

    def proud(self, facts: list[str]) -> str:
        if self.llm is None or not facts:
            return ""
        from .agent import strip_thinking
        from .tags import ASIDE, EMOJI, TAG

        text = "\n".join(f"- {f}" for f in facts)
        allowed = set(re.findall(r"\d+", text))
        for attempt in range(2):
            try:
                raw = self.llm.chat(self.model, [{"role": "user", "content": PROUD_PROMPT.format(
                    her=self.her, user=self.user, facts=text)}], options={"temperature": 0.7 + 0.1 * attempt, "num_predict": 90}).content
            except Exception as exc:
                log.info("weekly: proud line failed: %s", exc)
                return ""
            line = " ".join(EMOJI.sub("", ASIDE.sub("", TAG.sub("", strip_thinking(raw)))).split()).strip().strip('"')
            if 5 <= len(line.split()) <= 50 and not (set(re.findall(r"\d+", line)) - allowed):
                return line
        return ""

    def build(self, start: dt.date) -> dict:
        end = start + dt.timedelta(days=6)
        feel, mood_days = self.feel(start)
        talked = self.talked_days(start)
        together = self.together(start)
        wins = self.wins(start)
        notebook = self.notebook(start)
        moment = self.moment(start)
        photos = self.photos(start)
        nxt = self.next_week(start)
        facts = []
        if together:
            facts.append(f"Did {together['done']} things from your shared daily list together")
            if together["best"]:
                b = together["best"]
                facts.append(f"{b['streak']} {b['unit']} in a row of {b['title']}")
            facts += [f"Hit their weekly goal: {g}" for g in together["goals"]]
        facts += wins
        if notebook and notebook["pages"]:
            facts.append(f"Wrote {notebook['pages']} page{'s' if notebook['pages'] != 1 else ''} in your shared notebook")
        if feel == "rough":
            facts.append("It was a rough week and they kept going anyway")
        slides = [{"kind": "cover", "title": "Your week", "range": f"{start:%b} {start.day} – {end:%b} {end.day}",
                   "feel": FEELS.get(feel, ""), "talked": talked}]
        if together:
            slides.append({"kind": "together", **together})
        if wins:
            slides.append({"kind": "wins", "items": wins})
        if notebook:
            slides.append({"kind": "notebook", **notebook})
        if moment:
            slides.append({"kind": "moment", **moment})
        if photos:
            slides.append({"kind": "photos", "items": photos})
            facts.append(f"Kept {len(photos)} photo{'s' if len(photos) != 1 else ''} in your shared scrapbook: "
                         + "; ".join(p["caption"] for p in photos))
        proud = self.proud(facts)
        if proud:
            slides.append({"kind": "proud", "text": proud})
        if nxt:
            slides.append({"kind": "next", "items": nxt})
        return {"week": f"{start:%G-W%V}", "start": start.isoformat(), "slides": slides}

    def make(self, start: dt.date | None = None) -> dict | None:
        start = start or week_start(self.now().date())
        week = f"{start:%G-W%V}"
        if self._rows("SELECT 1 FROM weekly WHERE week = ?", (week,)):
            return None
        data = self.build(start)
        if len(data["slides"]) < 3 and not data["slides"][0]["talked"]:
            return None                                  # nothing happened: no recap
        self._exec("INSERT INTO weekly (week, start, data, created) VALUES (?,?,?,?)",
                   (week, start.isoformat(), json.dumps(data), self.now().isoformat(timespec="seconds")))
        self.publish("us", {"what": "weekly", "action": "new", "week": week})
        log.info("weekly: made %s (%d slides)", week, len(data["slides"]))
        return data

    def status(self) -> dict:
        return {"weeks": [{**json.loads(r["data"]), "created": r["created"]}
                          for r in self._rows("SELECT * FROM weekly ORDER BY start DESC LIMIT 4")]}

    # ----- when -----
    def due_start(self) -> dt.date | None:
        """Sunday from 18:00 -> this week; Monday (missed it) -> last week."""
        d = self.now()
        if d.weekday() == 6 and d.hour >= 18:
            return week_start(d.date())
        if d.weekday() == 0 and d.hour >= 8:
            return week_start(d.date()) - dt.timedelta(days=7)
        return None

    def tick(self):
        start = self.due_start()
        if start is not None and self.can_run() and not self._rows("SELECT 1 FROM weekly WHERE week = ?", (f"{start:%G-W%V}",)):
            self.make(start)

    def start(self, every_s: float = 900):
        def loop():
            self._stop.wait(150)
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception as exc:
                    log.warning("weekly: %s", exc)
                self._stop.wait(every_s)

        threading.Thread(target=loop, name="weekly", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    # part.py hooks
    def moments(self, now: float) -> list:
        return []

    def used(self, moment, now: float):
        pass

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        return []
