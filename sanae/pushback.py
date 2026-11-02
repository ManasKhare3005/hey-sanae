"""Honest pushback, like a friend: not a yes-machine.

When what you're about to do clashes with something real, the request gets a note to push back
once, kindly and honestly, with a deal ("one more and then bed?"):
  - it's late (after bedtime starts) and you're starting another game / episode / staying up;
  - something is due or starts tomorrow (her calendar, Canvas) and you're about to skip or put it off;
  - you're about to skip one of your goals (goals.py).
If you push back on her ("nah, just one"), she lets it go for the night. "Should I...?" questions
get her honest opinion instead of whatever you want to hear.

Starting Valorant late with something due tomorrow swaps the game-mode hello for a gentle one.
"""
from __future__ import annotations

import datetime as dt
import random
import re
import time

from .part import Part, clock_words, in_hours

FUN = re.compile(r"\b(one more( \w+)? (game|match|round|episode|ep|video)|another( \w+)? (game|match|round|episode)|"
                 r"(play|playing|queue|queuing|hop on|hopping on|run) (some )?(valorant|val|league|ranked|comp|games?)|"
                 r"(watch|watching|binge|binging) (a movie|netflix|anime|youtube|another|one more|a show)|"
                 r"stay(ing)? up|all[- ]?nighter|not (going to|gonna) sleep|sleep later|"
                 r"skip(ping)? (class|lecture|the gym|gym|studying|the lecture|my run|it)|"
                 r"not (going|gonna go) to (class|the gym|lecture)|do it tomorrow|start (it )?tomorrow|"
                 r"(put|putting) (it|that) off|procrastinat\w*)\b", re.I)
SHOULD = re.compile(r"^\W*(?:hey \w+,? )?(should i|do you think i should|is it (a )?(bad|good|dumb|smart) idea|"
                    r"would it be (bad|okay|fine) (if|to)|be honest)\b", re.I)
BACK_OFF = re.compile(r"\b(nah|no|i'?m (fine|good|okay)|just (one|this one|a bit)|leave (me|it)|stop|i know|"
                      r"let me (be|live)|chill|relax|it'?s fine|don'?t care|whatever|i got this)\b", re.I)
HONEST = ("They're asking for your opinion: give your honest take, even if it's not what they want to hear, "
          "with one reason; then it's their call")
PUSHED_FOR_S = 15 * 60
GAME_LINES = [
    "{game} at {clock}? You've got {thing} tomorrow. One game and bed, deal?",
    "Okay, but just one, yeah? {thing} tomorrow. I'll be quiet till you're done.",
    "One {game} match, then sleep? Don't forget {thing} tomorrow.",
]


def night_of(d: dt.datetime) -> str:
    """Evenings run 4 PM to 4 AM: 1 AM still counts as the night before."""
    return (d - dt.timedelta(hours=4)).date().isoformat()


class Pushback(Part):
    name = "pushback"

    def __init__(self, store=None, clock=time.time, ctx=None, goals=None, late_from: str = "00:30",
                 rng=None):
        super().__init__(store, clock)
        self.ctx = ctx
        self.goals = goals
        self.late = (late_from, "05:00")
        self.rng = rng or random.Random()

    def tomorrow(self) -> list[str]:
        """What's on tomorrow (or later today, after midnight): events, classes before 1 PM, things due."""
        d = self.now()
        start = (d - dt.timedelta(hours=4)).replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)
        if d.hour < 4:
            start = d.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + dt.timedelta(days=1)
        out = []
        events = getattr(self.ctx, "events", None)
        try:
            for e in events.between(start, end) if events is not None else []:
                if not e.all_day:
                    out.append(f"{e.title} at {clock_words(e.start)}")
        except Exception:
            pass
        canvas = getattr(self.ctx, "canvas", None)
        try:
            for item in canvas.items() if canvas is not None else []:
                if not (start <= item.start < end):
                    continue
                if item.kind == "assignment":
                    out.append(f"{item.title} due")
                elif item.kind == "class" and item.start.hour < 13:
                    out.append(f"{item.course} class at {clock_words(item.start)}")
        except Exception:
            pass
        return out[:3]

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        now = self.clock()
        night = night_of(self.now())
        pushed = self.get("pushed")
        if pushed and pushed.get("night") == night and now - pushed["t"] < PUSHED_FOR_S and BACK_OFF.search(user_text):
            self.put("pushed", {**pushed, "t": 0})
            self.put("dropped", night)
            return ["You already pushed back and they've decided: respect it and drop it for tonight (at most a "
                    "light \"okay, but I'm holding you to it\"). No second lecture"]
        if SHOULD.search(user_text):
            return [HONEST]
        if not FUN.search(user_text) or self.get("dropped") == night:
            return []
        why = []
        d = self.now()
        if in_hours(d, *self.late):
            why.append(f"it's {clock_words(d)}, really late")
        plans = self.tomorrow()
        if plans:
            why.append("tomorrow they have " + ", ".join(plans))
        if self.goals is not None and re.search(r"\bskip|not (going|gonna)|tomorrow|put .* off", user_text, re.I):
            g = self.goals.find(user_text)
            if g is not None:
                why.append(f"it's one of their goals ({g['text']}, {self.goals.progress(g)})")
        if not why:
            return []
        self.put("pushed", {"night": night, "t": now})
        return [f"Be an honest friend here: {'; '.join(why)}. Push back once, kindly, with a reason and a deal "
                "(\"one more and then bed?\"), not a lecture. If they insist, it's their call"]

    def game_line(self, game: str) -> str | None:
        """Starting a game late with something tomorrow: a gentle hello instead of the cheerful one."""
        d = self.now()
        if not in_hours(d, *self.late) or self.get("dropped") == night_of(d):
            return None
        plans = self.tomorrow()
        if not plans:
            return None
        from .gamemode import game_name

        return self.rng.choice(GAME_LINES).format(game=game_name(game), clock=clock_words(d), thing=plans[0])
