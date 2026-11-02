"""Screen time: a nudge after long stretches of gaming or laptop use.

  - gaming for more than `gaming_min` (2 h) -> a notification on the phone (the Galaxy Watch
    mirrors it) and a short line in her voice; again every `repeat_min` while it goes on
  - on the laptop for more than `laptop_min` (3 h) -> she tells you to get off for a bit (voice and
    a Windows notification); again every `repeat_min`

A stretch ends after `break_min` (10 min) without input / without the game in front; a break
of that length resets the clock. Gaming counts as laptop time too, but while you game only the
gaming nudge comes (one is enough). "Not now" (quiet mode) keeps her voice out of it; the
phone notification still comes.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

GAMING_LINES = [
    "You've been gaming for {h}. Take five: stretch, water, rest your eyes.",
    "{h} of games already. Quick break? Your eyes will thank you.",
    "Hey, it's been {h} of gaming. Maybe one more and then a breather?",
]
LAPTOP_LINES = [
    "You've been on the laptop for {h} straight. Get up for a bit: stretch, water, look at something far away.",
    "{h} on the laptop. Go take a real break, I'll be here.",
    "Okay, {h} without a break is a lot. Off the laptop for ten minutes, please?",
]


def hours(minutes: float) -> str:
    h, m = divmod(int(minutes), 60)
    if not h:
        return f"{m} minutes"
    hh = "an hour" if h == 1 else f"{h} hours"
    return hh if m < 10 else f"{hh} and {m} minutes"


@dataclass
class Stretch:
    start: float | None = None
    last: float = 0.0
    told_at: float = 0.0          # 0 = not told this stretch

    def feed(self, on: bool, now: float, break_s: float) -> float:
        """Minutes into the current stretch (0 when not in one)."""
        if on:
            if self.start is None or now - self.last > break_s:
                self.start, self.told_at = now, 0.0
            self.last = now
        elif self.start is not None and now - self.last > break_s:
            self.start, self.told_at = None, 0.0
        return (now - self.start) / 60 if self.start is not None and on else 0.0

    def due(self, minutes: float, limit: float, now: float, repeat_s: float) -> bool:
        return minutes >= limit and (not self.told_at or now - self.told_at >= repeat_s)


class ScreenTime:
    def __init__(self, idle_s, gaming, notify, clock=time.time, gaming_min: float = 120, laptop_min: float = 180,
                 repeat_min: float = 60, break_min: float = 10, active_idle_s: float = 300, rng=None):
        self.idle_s, self.gaming, self.notify, self.clock = idle_s, gaming, notify, clock
        self.gaming_min, self.laptop_min = gaming_min, laptop_min
        self.repeat_s, self.break_s, self.active_idle_s = repeat_min * 60, break_min * 60, active_idle_s
        self.rng = rng or random.Random()
        self.laptop = Stretch()
        self.game = Stretch()
        self._stop = threading.Event()

    def tick(self):
        now = self.clock()
        playing = bool(self.gaming())
        active = playing or self.idle_s() < self.active_idle_s
        laptop_m = self.laptop.feed(active, now, self.break_s)
        game_m = self.game.feed(playing, now, self.break_s)
        if playing and self.game.due(game_m, self.gaming_min, now, self.repeat_s):
            self.game.told_at = now
            self._say("gaming", game_m, GAMING_LINES)
        elif not playing and self.laptop.due(laptop_m, self.laptop_min, now, self.repeat_s):
            self.laptop.told_at = now
            self._say("laptop", laptop_m, LAPTOP_LINES)

    def _say(self, kind: str, minutes: float, lines: list[str]):
        text = self.rng.choice(lines).format(h=hours(minutes))
        log.info("screen time: %s for %.0f min -> nudge", kind, minutes)
        try:
            self.notify(kind, int(minutes), text)
        except Exception:
            log.exception("screen time nudge failed")

    def start(self, every_s: float = 30) -> "ScreenTime":
        def run():
            while not self._stop.wait(every_s):
                try:
                    self.tick()
                except Exception:
                    log.exception("screen time tick failed")
        threading.Thread(target=run, name="screentime", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()
