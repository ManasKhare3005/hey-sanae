"""A voice call with her: "Call Sanae" on the phone, earbuds in, talking while you walk or cook.

The phone records what you say (it stops at a pause), sends it to /api/call/turn, plays her
answer, and listens again. Here a call is just a flag that changes how she talks (short, spoken,
like on the phone) plus her hello and goodbye. It ends when you hang up, say bye, or after 3 quiet
minutes. The laptop must be on: the model runs here.
"""
from __future__ import annotations

import random
import re
import time

ENDS = re.compile(r"\b(bye|bye[- ]bye|good ?bye|hang(ing)? up|gotta go|got to go|talk (to you )?later|ttyl|"
                  r"see (you|ya)( later| tomorrow)?|good ?night|night night)\b\W*$", re.I)
OPENERS = ["[happy] Hey you! You called?", "[happy] Hi! I was hoping you'd call.", "[happy] Hey! What's up?",
           "[happy] Oh, hi! I'm here.", "[happy] Hey! Talk to me."]
LATE = ["[shy] Hey... it's late. Can't sleep?", "[happy] Hi, night owl. What's up?"]
NOTE = ("You're on a voice call with them right now (they called you from their phone, earbuds in, maybe walking or "
        "cooking). Talk like on a phone call: short, natural, spoken sentences, one thought at a time, no lists or "
        "markdown. If they say bye, say a warm goodbye")
QUIET_S = 180


class Call:
    def __init__(self, clock=time.time, rng=None):
        self.clock = clock
        self.rng = rng or random.Random()
        self.started = 0.0
        self.last = 0.0

    def start(self):
        self.started = self.last = self.clock()

    def touch(self):
        self.last = self.clock()
        if not self.started:
            self.started = self.last

    def end(self):
        self.started = self.last = 0.0

    def active(self) -> bool:
        return bool(self.started) and self.clock() - self.last < QUIET_S

    def opener(self, name: str = "Sanae") -> str:
        hour = time.localtime(self.clock()).tm_hour
        from .timesense import fix

        return fix(self.rng.choice(LATE if hour >= 23 or hour < 4 else OPENERS))

    def note(self) -> str | None:
        return NOTE if self.active() else None
