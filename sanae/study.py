"""Study buddy: "study with me for an hour" -> focus / break rounds (25 / 5 by default).

During focus she doesn't start conversations (do-not-disturb's quiet_for), but still answers when
spoken to. At each break she checks in (one line from the model, then a conversation window, so
"ugh, slow start makes no sense" gets an answer), at the end of a break she says it's time to
focus again, and at the end she wraps up. The day's sessions (topic and minutes) are kept as daily
counts in kv "study:days" for the diary ("studied networks for 75 minutes").
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger(__name__)


@dataclass
class Session:
    topic: str
    rounds: int
    focus_min: float
    break_min: float
    started: float
    round: int = 1
    phase: str = "focus"          # focus | break | done
    phase_ends: float = 0.0
    stopped: threading.Event = field(default_factory=threading.Event)

    def status(self, now: float) -> str:
        left = max(0, round((self.phase_ends - now) / 60))
        what = f" on {self.topic}" if self.topic else ""
        if self.phase == "focus":
            return f"Round {self.round} of {self.rounds}{what}: {left} minutes of focus left."
        if self.phase == "break":
            return f"Break: {left} minutes left, then round {self.round + 1} of {self.rounds}."
        return "No study session right now."


class StudyBuddy:
    def __init__(self, ctx, say_line: Callable[[str, bool], None], line_for: Callable[[str], str | None] | None = None,
                 focus_min: float = 25, break_min: float = 5, clock=time.time, sleep: Callable[[float], bool] | None = None):
        """`say_line(text, chat)`: speak it (chat=True opens a conversation window after it).
        `line_for(situation)`: one line in her voice from the model, or None for the plain line."""
        self.ctx, self.say_line, self.line_for = ctx, say_line, line_for
        self.focus_min, self.break_min = focus_min, break_min
        self.clock = clock
        self.session: Session | None = None
        self._sleep = sleep

    def _wait(self, s: Session, seconds: float) -> bool:
        """True if the session was stopped while waiting."""
        if self._sleep is not None:
            return self._sleep(seconds) or s.stopped.is_set()
        return s.stopped.wait(seconds)

    def _quiet(self, minutes: float):
        dnd = getattr(self.ctx, "dnd", None)
        if dnd is not None:
            if minutes > 0:
                dnd.quiet_for(minutes)
            else:
                dnd.resume()

    def _line(self, situation: str, plain: str) -> str:
        if self.line_for is not None:
            try:
                return self.line_for(situation) or plain
            except Exception as exc:
                log.debug("study line: %s", exc)
        return plain

    def start(self, minutes: float = 60, topic: str = "") -> str:
        if self.session is not None and self.session.phase != "done":
            return "We're already studying. " + self.session.status(self.clock())
        minutes = max(10.0, min(float(minutes or 60), 240.0))
        cycle = self.focus_min + self.break_min
        rounds = max(1, round(minutes / cycle))
        s = Session(topic.strip(), rounds, self.focus_min, self.break_min, self.clock())
        self.session = s
        threading.Thread(target=self._run, args=(s,), name="study", daemon=True).start()
        what = f" {topic.strip()}" if topic.strip() else ""
        return (f"Okay, let's study{what}: {rounds} round{'s' if rounds > 1 else ''} of {self.focus_min:g} minutes, "
                f"with {self.break_min:g}-minute breaks. I'll stay quiet till the break. Go!")

    def stop(self) -> str:
        s = self.session
        if s is None or s.phase == "done":
            return "We're not studying right now."
        s.stopped.set()
        s.phase = "done"
        self._quiet(0)
        done = (self.clock() - s.started) / 60
        self._tally(s.topic, done)
        if done < 3:
            return "Okay, no study session then. Just say the word when you're ready."
        return f"Okay, stopping. That was {round(done)} minutes, nice work."

    def status(self) -> str:
        return self.session.status(self.clock()) if self.session else "No study session right now."

    def _run(self, s: Session):
        topic = s.topic or "their work"
        try:
            for r in range(1, s.rounds + 1):
                s.round, s.phase = r, "focus"
                s.phase_ends = self.clock() + s.focus_min * 60
                self._quiet(s.focus_min + 0.5)
                if self._wait(s, s.focus_min * 60):
                    return
                if r == s.rounds:
                    break
                s.phase = "break"
                s.phase_ends = self.clock() + s.break_min * 60
                self._quiet(0)
                self.say_line(self._line(
                    f"{{user}} just finished focus round {r} of {s.rounds} studying {topic}. It's a {s.break_min:g}-minute "
                    "break: cheer them a little and ask one short question about how it's going or what's tricky.",
                    f"Break time! {s.break_min:g} minutes. How's {topic} going?"), True)
                if self._wait(s, s.break_min * 60):
                    return
                self.say_line(f"Okay, back to it: round {r + 1} of {s.rounds}.", False)
            self._quiet(0)
            self._tally(s.topic, s.rounds * s.focus_min)
            self.say_line(self._line(
                f"{{user}} just finished a study session: {s.rounds} rounds on {topic}. Celebrate it warmly in one line, "
                "and suggest a real break.", f"Done! {s.rounds} rounds on {topic}. Go take a real break."), True)
            s.phase = "done"
        except Exception as exc:
            log.warning("study session: %s", exc)
            s.phase = "done"

    def _tally(self, topic: str, minutes: float):
        mem = getattr(self.ctx, "memory", None)
        if mem is None or minutes < 5:
            return
        day = dt.date.fromtimestamp(self.clock()).isoformat()
        raw = mem.get("study:days")
        days = json.loads(raw) if raw else {}
        days.setdefault(day, []).append({"topic": topic, "minutes": round(minutes)})
        for old in sorted(days)[:-14]:
            del days[old]
        mem.set("study:days", json.dumps(days))


def day_summary(memory, day: str) -> str | None:
    """"studied networks for 50 minutes" for the diary."""
    raw = memory.get("study:days") if memory is not None else None
    sessions = (json.loads(raw) if raw else {}).get(day) or []
    if not sessions:
        return None
    by_topic: dict[str, int] = {}
    for x in sessions:
        by_topic[x["topic"] or "something"] = by_topic.get(x["topic"] or "something", 0) + x["minutes"]
    return "studied " + ", ".join(f"{t} for {m} minutes" for t, m in by_topic.items())
