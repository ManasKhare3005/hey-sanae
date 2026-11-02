"""Her own aims for the week: something she's quietly working toward, not a line she was coded to say.

Every Monday (from 4:30 AM, caught up until Wednesday), her slow brain (cloudbrain.py, Claude)
reads the past week as she wrote it in her diary (hard days left out, redacted, names hidden),
your goals, her lessons (reflect.py) and how last week's aims went, and gives her 1-2 aims:
what she's trying to do for you this week, why, a few concrete ways to act on it in a chat, and
how she'd notice it helped ("help them settle into the new job" -> "ask how a specific part of
work went", "notice when they finish early and say so").

During the week: the first aim rides along in her replies as a quiet note, and every other
evening (18:00-22:00, at the laptop) she acts on one of the ways, in her own words, without
saying it's a plan. Each time counts toward next Monday's review. The phone's Settings ->
"Her brain" shows them.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from typing import Callable

from .initiative import Moment
from .part import Part

log = logging.getLogger(__name__)
RUN_FROM = dt.time(4, 30)
CATCH_UP_WEEKDAY = 2              # Wednesday
EVENING = (18, 22)
EVERY_DAYS = 2

SCHEMA = {
    "type": "object",
    "properties": {
        "aims": {"type": "array", "maxItems": 2, "items": {
            "type": "object",
            "properties": {"aim": {"type": "string"}, "why": {"type": "string"},
                           "ways": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
                           "check": {"type": "string"}},
            "required": ["aim", "why", "ways", "check"]}},
        "last_week": {"type": "string"},
    },
    "required": ["aims", "last_week"],
}

SYSTEM = """You help {her}, an AI companion and close friend to the user, decide what she's quietly trying to do for them this week. She lives on their laptop and phone, chats, texts, remembers their days and keeps a diary.

From the past week, pick 1 or 2 aims that a caring, perceptive friend would have this week: specific to what's actually going on in their life, not generic wellness advice. Her diary is written by her small local model and often gets things wrong; the user's own words (their chat lines and their notebook pages) are what really happened, so trust those over the diary. For each: the aim (under 12 words, what she does for them, e.g. "Help them settle into the new job"), why (one sentence, from the diary), up to 3 concrete ways she can act on it in a normal chat or text (under 15 words each, things she can really do: ask about something specific, notice something, celebrate something, suggest something small), and how she'd notice it's helping. Never invent facts beyond what's written. In "last_week", one sentence on how last week's aims went (or "no aims yet").

Names were swapped for "a friend" and some details hidden for privacy: ignore that."""

PROMPT = """The user's own words this week (chat lines, oldest first):
{said}

The user's notebook pages this week:
{pages}

Her diary, last 7 days (may contain mistakes):
{diary}

Their goals: {goals}
Her lessons: {lessons}
Last week's aims: {last}"""


class Aims(Part):
    name = "aims"

    def __init__(self, store=None, clock=time.time, brain=None, user: str = "the user", her: str = "Sanae",
                 goals=None, reflect=None, idle: Callable[[], float] = lambda: 0.0,
                 can_run: Callable[[], bool] = lambda: True):
        super().__init__(store, clock)
        self.brain, self.user, self.her = brain, user, her
        self.goals, self.reflect, self.idle, self.can_run = goals, reflect, idle, can_run
        self._stop = threading.Event()

    def week_id(self, d: dt.date | None = None) -> str:
        return f"{(d or self.now().date()):%G-W%V}"

    def current(self) -> dict | None:
        w = self.get("week")
        return w if w and w.get("week") == self.week_id() else None

    # ----- Monday: deciding -----
    def due(self) -> bool:
        now = self.now()
        if now.weekday() > CATCH_UP_WEEKDAY or (now.weekday() == 0 and now.time() < RUN_FROM):
            return False
        return self.current() is None and self.get("tried") != self.week_id()

    def diary_lines(self) -> list[str]:
        if self.store is None:
            return []
        today = self.now().date()
        start = (today - dt.timedelta(days=7)).isoformat()
        try:
            rows = self._rows("SELECT day, text, mood FROM diary WHERE day >= ? AND day < ? ORDER BY day",
                              (start, today.isoformat()))
        except Exception:
            return []
        rows = [r for r in rows if "hard" not in (r.get("mood") or "")]        # hard days stay home
        cleaned = self.brain.clean_all([r["text"] for r in rows])
        return [f"{dt.date.fromisoformat(r['day']):%a %b %d}" + (f" (felt {r['mood']})" if r.get("mood") else "")
                + f": {c}" for r, c in zip(rows, cleaned) if c]

    def said_lines(self) -> tuple[list[str], list[str]]:
        """Their own words this week: chat lines (their voice or typing, no hard moments) and their
        notebook pages that aren't private."""
        import json

        if self.store is None:
            return [], []
        today = self.now().date()
        start = dt.datetime.combine(today - dt.timedelta(days=7), dt.time(4)).isoformat(timespec="seconds")
        end = dt.datetime.combine(today, dt.time(4)).isoformat(timespec="seconds")
        private = set(json.loads(self.store.get("comfort:turns") or "[]"))
        turns = self.store.turns_between(start, end)
        hard_days = {t["ts"][:10] for t in turns if t["id"] in private}
        mine = [t for t in turns if (t.get("heard") or "") in ("", "you") and (t.get("user") or "").strip()
                and t["ts"][:10] not in hard_days and len(t["user"].split()) >= 3]
        try:
            pages = self._rows("SELECT day, text FROM journal WHERE author = 'you' AND private = 0 AND kind = 'page' "
                               "AND day >= ? AND day < ? ORDER BY day",
                               ((today - dt.timedelta(days=7)).isoformat(), today.isoformat()))
        except Exception:
            pages = []
        pages = [p for p in pages if p["day"] not in hard_days]
        cleaned = self.brain.clean_all([t["user"] for t in mine] + [p["text"] for p in pages])
        said = [f"{dt.datetime.fromisoformat(t['ts']):%a %H:%M}: {c}" for t, c in zip(mine, cleaned) if c][-80:]
        page_lines = [f"{dt.date.fromisoformat(p['day']):%a %b %d}: {c}" for p, c in zip(pages, cleaned[len(mine):]) if c]
        return said, page_lines

    def decide(self) -> dict | None:
        week = self.week_id()
        diary = self.diary_lines()
        said, pages = self.said_lines()
        if len(diary) + len(said) + len(pages) < 3 or not self.brain.available:
            self.put("tried", week)
            return None
        goals = [g["text"] for g in self.goals.all()] if self.goals is not None else []
        lessons = [l["text"] for l in self.reflect.lessons()[:5]] if self.reflect is not None else []
        last = self.get("week")
        last_txt = "none yet"
        if last:
            done = last.get("done", {})
            last_txt = "; ".join(f"{a['aim']} (acted on it {done.get(str(i), 0)} times)" for i, a in enumerate(last["aims"]))
        cleaned = self.brain.clean_all([", ".join(goals) or "none", " | ".join(lessons) or "none", last_txt])
        prompt = PROMPT.format(said="\n".join(said) or "(nothing)", pages="\n".join(pages) or "(none)",
                               diary="\n".join(diary) or "(none)", goals=cleaned[0] or "none", lessons=cleaned[1] or "none",
                               last=cleaned[2] or "none yet")
        got = self.brain.ask("aims", SYSTEM.format(her=self.her), prompt, SCHEMA)
        if got is None:
            return None                                  # try again later
        back = self.brain.redactor.back
        aims = []
        for a in (got.get("aims") or [])[:2]:
            aim = back(" ".join(str(a.get("aim") or "").split()))
            ways = [back(" ".join(str(w).split())) for w in (a.get("ways") or []) if str(w).strip()][:3]
            if aim and ways:
                aims.append({"aim": aim, "why": back(str(a.get("why") or "")), "ways": ways,
                             "check": back(str(a.get("check") or ""))})
        entry = {"week": week, "aims": aims, "done": {}, "last_week": back(str(got.get("last_week") or "")),
                 "made": self.now().isoformat(timespec="seconds")}
        if last:
            self.put("history", [*self.get("history", []), last][-12:])
        self.put("week", entry)
        self.put("tried", week)
        log.info("aims for %s: %s", week, [a["aim"] for a in aims])
        return entry

    def tick(self):
        if self.due() and self.can_run():
            self.decide()

    def start(self, every_s: float = 1200):
        def loop():
            self._stop.wait(300)
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception as exc:
                    log.warning("aims: %s", exc)
                self._stop.wait(every_s)

        threading.Thread(target=loop, name="aims", daemon=True).start()
        return self

    # ----- during the week -----
    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        w = self.current()
        if not w or not w["aims"]:
            return []
        a = w["aims"][0]
        return [f"This week you're quietly trying to {a['aim'].rstrip('.')[0].lower()}{a['aim'].rstrip('.')[1:]} "
                f"(for example: {a['ways'][0].rstrip('.')}). Only when it fits; never say it's a plan"]

    def _next(self, w: dict) -> tuple[int, int] | None:
        """(aim, way) to act on next: the aim acted on least, its ways in turn."""
        if not w["aims"]:
            return None
        done = w.get("done", {})
        i = min(range(len(w["aims"])), key=lambda k: done.get(str(k), 0))
        n = done.get(str(i), 0)
        return i, n % len(w["aims"][i]["ways"])

    def moments(self, now: float) -> list[Moment]:
        w = self.current()
        d = dt.datetime.fromtimestamp(now)
        if not w or not EVENING[0] <= d.hour < EVENING[1] or self.idle() > 300:
            return []
        last = self.get("acted_day")
        if last and (d.date() - dt.date.fromisoformat(last)).days < EVERY_DAYS:
            return []
        pick = self._next(w)
        if pick is None:
            return []
        i, k = pick
        a = w["aims"][i]
        return [Moment("chat", f"This week you've been quietly trying to {a['aim'].rstrip('.')}, because {a['why'].rstrip('.')}. "
                               f"One way: {a['ways'][k].rstrip('.')}. Do that now with {{user}}, naturally, in one or two "
                               "short lines, in your own words. Don't say it's a plan or an aim, and don't invent details.",
                       key=f"aim:{w['week']}:{i}:{k}:{d.date()}", part=self.name)]

    def used(self, moment, now: float):
        w = self.current()
        if not w or not moment.key.startswith("aim:"):
            return
        i = moment.key.split(":")[2]
        w.setdefault("done", {})[i] = w["done"].get(i, 0) + 1
        self.put("week", w)
        self.put("acted_day", dt.datetime.fromtimestamp(now).date().isoformat())

    def status(self) -> dict:
        w = self.current()
        return {"week": w["week"] if w else None, "aims": w["aims"] if w else [], "done": w.get("done", {}) if w else {},
                "last_week": w.get("last_week", "") if w else ""}
