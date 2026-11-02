"""She notices your wins and says so, and reminds you of them when you're down.

Wins (each said at most once):
  - commits today in one of your projects (Sanae itself is skipped: most of its commits are mine);
  - three or more todos finished today;
  - a goal's weekly target reached (goals.py);
  - three Valorant wins in a row today;
  - a good night's sleep (care.py adds it).

Every win is kept for 60 days (kv "wins:log"); when you say you're stressed, down, tired or
frustrated, the request gets one of them ("remember the build that took 3 days? you got through
that"), at most once every two hours.
"""
from __future__ import annotations

import datetime as dt
import logging
import time

from .initiative import Moment
from .part import Part

log = logging.getLogger(__name__)
KEEP_DAYS = 60
REMIND_GAP_S = 2 * 3600
DOWN = ("stressed", "down", "tired", "frustrated")
GIT_EVERY_S = 600


class Wins(Part):
    name = "wins"

    def __init__(self, store=None, clock=time.time, projects=None, todos=None, goals=None, valorant=None,
                 skip_projects=("Sanae",), rng=None):
        import random

        super().__init__(store, clock)
        self.projects, self.todos, self.goals, self.valorant = projects, todos, goals, valorant
        self.skip = {s.lower() for s in skip_projects}
        self.rng = rng or random.Random()
        self._git: tuple[float, list[tuple[str, str]]] = (0.0, [])

    # ----- the log -----
    def add(self, key: str, text: str) -> bool:
        """A new win (False if this one was already noted)."""
        wins = self.get("log", [])
        if any(w["key"] == key for w in wins):
            return False
        cutoff = (self.now().date() - dt.timedelta(days=KEEP_DAYS)).isoformat()
        self.put("log", [w for w in wins if w["day"] >= cutoff] + [{"key": key, "day": self.today(), "text": text,
                                                                    "said": False}])
        return True

    def recent(self, days: int = 30) -> list[dict]:
        cutoff = (self.now().date() - dt.timedelta(days=days)).isoformat()
        return [w for w in self.get("log", []) if w["day"] >= cutoff]

    # ----- finding them -----
    def scan(self):
        today = self.today()
        for project, subject, n in self._commits():
            self.add(f"git:{project}:{today}", f"made {n} commit{'s' if n != 1 else ''} on {project} today "
                                               f"(latest: \"{subject}\")")
        if self.todos is not None:
            try:
                start = dt.datetime.combine(self.now().date(), dt.time()).timestamp() * 1000
                done = [t for t in self.todos.shown() if t.done and t.updated >= start]
                if len(done) >= 3:
                    self.add(f"todos:{today}", f"finished {len(done)} things on their todo list today")
            except Exception as exc:
                log.debug("todo wins: %s", exc)
        if self.goals is not None:
            wk = self.now().date().isocalendar()
            for text in self.goals.week_wins():
                self.add(f"goal:{text}:{wk[0]}-{wk[1]}", f"reached this week's target for their goal \"{text}\"")
        if self.valorant is not None:
            try:
                tag = f"{self.now():%a %b %d}"
                games = [g for g in self.valorant.all() if str(g.get("when", "")).startswith(tag)]
                run = 0
                for g in reversed(games):
                    if g.get("result") != "Win":
                        break
                    run += 1
                if run >= 3:
                    self.add(f"valorant:{today}:{len(games)}", f"won {run} Valorant matches in a row today")
            except Exception as exc:
                log.debug("valorant wins: %s", exc)

    def _commits(self) -> list[tuple[str, str, int]]:
        stamp, cached = self._git
        if self.projects is None or time.monotonic() - stamp < GIT_EVERY_S and stamp:
            return cached if self.projects is not None else []
        out = []
        since = dt.datetime.combine(self.now().date(), dt.time()).strftime("%Y-%m-%d %H:%M")
        try:
            for p in self.projects.all():
                if p.name.lower() in self.skip:
                    continue
                subjects = [s for s in self.projects.git(p, "log", f"--since={since}", "--pretty=%s", timeout=10).splitlines()
                            if s.strip() and not s.startswith("Merge ")]
                if subjects:
                    out.append((p.name, subjects[0][:80], len(subjects)))
        except Exception as exc:
            log.debug("git wins: %s", exc)
        self._git = (time.monotonic(), out)
        return out

    # ----- saying so -----
    def moments(self, now: float) -> list[Moment]:
        self.scan()
        fresh = [w for w in self.recent(1) if not w["said"] and w["day"] == self.today()]
        if not fresh:
            return []
        w = fresh[0]
        return [Moment("win", f"You noticed: {{user}} {w['text']}. Tell them you noticed and you're proud of them, in one "
                              "short, specific line. Don't guess details you don't know.", key=w["key"])]

    def used(self, moment, now: float):
        self.put("log", [{**w, "said": True} if w["key"] == moment.key else w for w in self.get("log", [])])

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        from .mood import user_mood

        theirs = user_mood(user_text)
        if not theirs or theirs[0] not in DOWN or self.clock() - self.get("reminded", 0) < REMIND_GAP_S:
            return []
        older = [w for w in self.recent(30) if w["day"] < self.today()] or self.recent(30)
        if not older:
            return []
        w = self.rng.choice(older[-6:])
        self.put("reminded", self.clock())
        day = dt.date.fromisoformat(w["day"])
        when = "today" if w["day"] == self.today() else "yesterday" if (self.now().date() - day).days == 1 \
            else f"on {day:%A}" if (self.now().date() - day).days < 7 else f"on {day:%b} {day.day}"
        return [f"Something they pulled off lately: {when} they {w['text']}. If it fits, remind them of it as proof "
                "they can get through this one too (one line, after you've listened; skip it if it doesn't fit)"]
