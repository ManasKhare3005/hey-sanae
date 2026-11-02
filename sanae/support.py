"""Being a good listener: venting vs fixing, learning how the user likes to be talked to, and not
leaning on her own likes.

- Venting (Pi's trick): when the user is letting off steam, she listens first: says back what
  they feel, validates it, no fixes or advice unless asked. "just let me vent" keeps her in
  listening mode for a while; "what should I do?" switches to helping.
- Taste: reactions to her replies nudge three dials (0-1, start 0.5): length, teasing and
  questions. "lol" after a tease -> more teasing; "too long" -> shorter; "stop asking" -> fewer
  questions. Kept in kv "taste"; shown (and reset) on the dashboard.
- Likes: the 4b model mentions cats / anime / strawberry milk in nearly every reply whatever the
  style rules say (measured in the 2026-10-13 lab); if one came up in her recent replies, the
  next request carries a note not to.
"""
from __future__ import annotations

import json
import re
import time

VENT = re.compile(
    r"\b(ugh+|i hate|so sick of|sick and tired|fed up|i can'?t (even|do this|take)|i'?m so (done|tired of|over)|"
    r"this sucks|everything (is|sucks|keeps)|why does (this|everything)|nothing (works|goes)|"
    r"i just (feel|want|can'?t)|i don'?t know what to do|it'?s (so )?(unfair|frustrating|annoying)|"
    r"(rough|bad|awful|terrible|long) day|"
    r"i'?m (so |really |super |kinda |just )?(stressed|overwhelmed|exhausted|frustrated|upset|annoyed|pissed))\b", re.I)
JUST_LISTEN = re.compile(r"\b(just (let me|wanna|want to|need to) vent|just listen|don'?t (fix|solve)|no advice|"
                         r"i just need to (vent|rant))\b", re.I)
WANTS_HELP = re.compile(r"\b(what should i do|any (ideas|advice|tips|suggestions)|help me (with|figure|fix)|how (do|can|should) i|"
                        r"what do you think i should|can you help|suggest|suggestions?|recommend|"
                        r"(give|tell|get) me (some |a few |any )?(ideas|plans?|advice|tips|options)|"
                        r"(some|any|a few) (ideas|plans|advice|tips|options)|i want (ideas|advice|help)|"
                        r"what can i do)\b", re.I)
# Their answer right after she asked "do you want ideas, or just need to vent?"
ANSWER_IDEAS = re.compile(r"\b(ideas?|plans?|advice|tips|suggest\w*|help|fix|solutions?|options)\b", re.I)
ANSWER_VENT = re.compile(r"\b(vent|rant|just listen|listen|just talk|no advice)\b", re.I)
VENT_MOODS = ("stressed", "down", "frustrated", "tired")
LISTEN_FOR_S = 20 * 60

HINT_VENT = ("They seem to be venting. Listen first: say back what they're feeling in your own words and validate "
             "it; no fixes, advice or teasing. If you can't tell whether they want help, ask if they want ideas or "
             "just need to vent")
HINT_LISTEN = "They asked you to just listen: no advice or fixes, just be there and reflect what they say"
HINT_HELP = "They're asking for help now: practical, kind, one or two concrete ideas"
HINT_STILL = ("They're still venting: keep listening, say back what they feel, take their side. No fixes, and "
              "end without a question this time")
HINT_BREATHE = ("They're stressed. Say you get it in a few words, then offer to do a one-minute breathing exercise "
                "together right now (one short question). If they say yes, call breathing_exercise")
ASKED_WITHIN_S = 10 * 60


class Listener:
    """Venting vs fixing, with a short memory of "just let me vent"."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.listen_until = 0.0
        self.vented_at = 0.0                # the last venting hint (asked "ideas or vent?" then)
        self.asked_at = 0.0                 # when she asked "ideas or vent?" (their next words answer it)

    def hint(self, text: str, word_mood: str | None, tone: str | None) -> str | None:
        now = self.clock()
        answering = now - self.asked_at < ASKED_WITHIN_S
        self.asked_at = 0.0
        if answering and ANSWER_VENT.search(text) and not ANSWER_IDEAS.search(text):
            self.listen_until = now + LISTEN_FOR_S
            return HINT_LISTEN
        if WANTS_HELP.search(text) or (answering and ANSWER_IDEAS.search(text)):
            self.listen_until = self.vented_at = 0.0
            return HINT_HELP
        if JUST_LISTEN.search(text):
            self.listen_until = now + LISTEN_FOR_S
            return HINT_LISTEN
        if now < self.listen_until:
            self.listen_until = now + LISTEN_FOR_S        # still venting: keep listening
            return HINT_LISTEN
        # The words have to sound upset: a quiet voice alone isn't venting ("I've been coding all
        # day" in a tired evening voice got "ideas or vent?")
        long_and_low = len(text.split()) >= 12 and word_mood in VENT_MOODS
        still = now - self.vented_at < ASKED_WITHIN_S
        if VENT.search(text) or long_and_low or (still and word_mood in VENT_MOODS):
            hint = HINT_STILL if still else HINT_VENT          # ask "ideas or vent?" once, not every turn
            if hint == HINT_VENT:
                self.asked_at = now
            self.vented_at = now
            return hint
        if still and len(text.split()) >= 6 and not text.rstrip().endswith("?"):
            self.vented_at = now
            return HINT_STILL                                  # more of the same story
        return None


# ----- taste: how they like to be talked to -----
DIALS = ("length", "tease", "questions")
STEP = 0.08
SIGNALS = [
    # (pattern on the user's reply, dial, direction, only if her last reply ...)
    (re.compile(r"\b(too long|shorter|tl;?dr|get to the point|less words|ramble|rambling|keep it short)\b", re.I), "length", -1, None),
    (re.compile(r"\b(tell me more|go on|more detail|explain more|elaborate)\b", re.I), "length", +1, None),
    (re.compile(r"\b(stop teasing|not funny|be serious|cut it out|that'?s mean|rude)\b", re.I), "tease", -1, None),
    (re.compile(r"\b(haha+|hehe+|lol+|lmao|rofl)\b|😂|🤣", re.I), "tease", +1, "teased"),
    (re.compile(r"\b(stop asking|so many questions|too many questions|quit asking)\b", re.I), "questions", -1, None),
]
TEASED = re.compile(r"\b(huh|again\?|rude|you nerd|silly|admit it|hehe|told you|caught you)\b|\[laugh\]", re.I)


class Taste:
    def __init__(self, memory=None):
        self.mem = memory
        raw = memory.get("taste") if memory is not None else None
        d = json.loads(raw) if raw else {}
        self.dials = {k: float(d.get(k, 0.5)) for k in DIALS}

    def _save(self):
        if self.mem is not None:
            self.mem.set("taste", json.dumps({k: round(v, 3) for k, v in self.dials.items()}))

    def react(self, user_text: str, last_reply: str | None, interrupted: bool = False) -> list[str]:
        """Read the user's reaction to her last reply; returns the dials that moved."""
        moved = []
        if last_reply:
            for pattern, dial, sign, needs in SIGNALS:
                if needs == "teased" and not TEASED.search(last_reply):
                    continue
                if pattern.search(user_text):
                    self.nudge(dial, sign)
                    moved.append(dial)
        if interrupted and "length" not in moved:              # cut her off: a little shorter
            self.nudge("length", -0.5)
            moved.append("length")
        if moved:
            self._save()
        return moved

    def nudge(self, dial: str, sign: float):
        self.dials[dial] = min(1.0, max(0.0, self.dials[dial] + STEP * sign))

    def reset(self):
        self.dials = {k: 0.5 for k in DIALS}
        self._save()

    def notes(self) -> list[str]:
        d, out = self.dials, []
        if d["length"] <= 0.35:
            out.append("They like very short replies: one short sentence")
        elif d["length"] >= 0.7:
            out.append("They like a bit more detail from you")
        if d["tease"] <= 0.35:
            out.append("Go easy on the teasing; they're not into it right now")
        elif d["tease"] >= 0.7:
            out.append("They enjoy your teasing")
        if d["questions"] <= 0.35:
            out.append("Don't end with a question")
        return out


def likes_note(recent_replies: list[str], likes: list[str]) -> str | None:
    """If one of her likes came up in her last few replies, ask her to leave them out this time."""
    used = [w for w in likes if any(re.search(rf"\b{re.escape(w)}", r, re.I) for r in recent_replies)]
    if not used:
        return None
    return f"You've brought up {', '.join(used)} recently: don't mention {', '.join(likes)} in this reply"
