"""Her mood, and a read on yours.

Her mood is two numbers kept across restarts (kv "mood"): energy (sleepy 0 .. lively 1) and cheer
(down 0 .. bright 1). Energy follows the time of day (low in the small hours, best in the afternoon);
cheer drifts back to a little above middle, rises with nice moments (thanks, laughs, being called
cute) and dips a bit when she's been ignored for days or spoken to rudely. It shows as her resting
face on the avatar and, when it's notable, as one line in the request ("You're feeling sleepy").

Your mood is read fresh from each message (stressed, tired, down, excited): it adds a hint to that
one request ("They sound stressed: be gentle"). Only daily counts are kept (kv "mood:days"), so the
diary can say how each day felt (day_label: good, stressed, a hard day...); never the messages.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import time
from dataclasses import dataclass

NICE = re.compile(r"\b(thanks?|thank you|ty|love (you|it|this)|you'?re (the best|cute|amazing|awesome|great|funny)|"
                  r"good (girl|job)|haha+|lol|lmao|nice one|you rock)\b", re.I)
RUDE = re.compile(r"\b(shut up|stupid|useless|dumb|idiot|hate you|you suck|annoying|go away forever)\b", re.I)

USER_MOODS = [
    ("stressed", re.compile(r"\b(stress(ed|ful)?|overwhelm\w*|panick\w*|freaking out|so much to do|deadline\w* (is|are) killing|"
                            r"behind on|anxious|nervous)\b", re.I), "They sound stressed: be calm, short and reassuring, no teasing."),
    ("tired", re.compile(r"\b(tired|exhausted|sleepy|drained|no sleep|didn'?t sleep|so done|burn(ed|t) out)\b", re.I),
     "They sound tired: be soft and low-key."),
    ("down", re.compile(r"\b(sad|upset|lonely|bad day|rough day|failed|crying|miserable|hate my life|feel(ing)? (bad|awful|terrible))\b", re.I),
     "They sound down: be kind and supportive, no teasing."),
    ("frustrated", re.compile(r"\b(ugh+|argh+|frustrat\w*|annoyed|so annoying|why won'?t|doesn'?t work|keeps? (crashing|failing)|wtf)\b", re.I),
     "They sound frustrated: be patient and helpful first, light humour at most."),
    ("excited", re.compile(r"\b(yay+|let'?s go+|i (did|got) it|i passed|aced|so excited|can'?t wait|amazing news|woo+)\b", re.I),
     "They sound excited: share it, be bubbly."),
]


def user_mood(text: str) -> tuple[str, str] | None:
    """(name, hint for the model) if the message carries a clear mood, else None."""
    for name, pattern, hint in USER_MOODS:
        if pattern.search(text or ""):
            return name, hint
    return None


DAY_MOODS = ("stressed", "tired", "down", "frustrated", "excited")
KEEP_DAYS = 14
DAY_STARTS = 4                 # a day runs 4 AM to 4 AM (like the diary)


def _day(ts: float) -> str:
    return (dt.datetime.fromtimestamp(ts) - dt.timedelta(hours=DAY_STARTS)).date().isoformat()


def _days(memory) -> dict:
    raw = memory.get("mood:days") if memory is not None else None
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def _put_days(memory, days: dict):
    for old in sorted(days)[:-KEEP_DAYS]:
        del days[old]
    memory.set("mood:days", json.dumps(days))


def tally_day(memory, text: str, now: float | None = None):
    """Count one message toward the day's mood: {"2026-10-16": {"n": 9, "stressed": 2, "nice": 3}}."""
    if memory is None:
        return
    days = _days(memory)
    t = days.setdefault(_day(now if now is not None else time.time()), {"n": 0})
    t["n"] += 1
    mood = user_mood(text)
    if mood:
        t[mood[0]] = t.get(mood[0], 0) + 1
    if NICE.search(text or ""):
        t["nice"] = t.get("nice", 0) + 1
    _put_days(memory, days)


def mark_day(memory, flag: str, now: float | None = None):
    """A flag on the day: "hard" (comfort mode), "better" (they felt better after)."""
    if memory is None:
        return
    days = _days(memory)
    days.setdefault(_day(now if now is not None else time.time()), {"n": 0})[flag] = True
    _put_days(memory, days)


def day_label(memory, day: str, sounded: str | None = None) -> str:
    """How the day felt, in a few words, for the diary; "" if they didn't talk that day."""
    t = _days(memory).get(day)
    if not t:
        return ""
    if t.get("hard"):
        return "a hard day, felt better by the end" if t.get("better") else "a hard day"
    n = t.get("n", 0)
    if not n:
        return ""
    neg = {k: t.get(k, 0) for k in ("stressed", "tired", "down", "frustrated")}
    worst = max(neg, key=neg.get)
    bad = sum(neg.values())
    good = t.get("excited", 0) + t.get("nice", 0)
    if bad >= 2 and good >= 2:
        return "mixed"
    if neg[worst] >= 2 or (neg[worst] and neg[worst] / n >= 0.25):
        return {"down": "low"}.get(worst, worst)
    if t.get("excited", 0) >= 2:
        return "great"
    if good >= 2:
        return "good"
    if sounded and "tired or low" in sounded:
        return "tired"
    return "okay"


def energy_for_hour(hour: float) -> float:
    """Lowest around 3-4 AM, highest mid-afternoon."""
    return 0.55 + 0.4 * math.cos((hour - 15) / 24 * 2 * math.pi)


@dataclass
class Mood:
    energy: float = 0.7
    cheer: float = 0.65
    updated: float = 0.0

    BASE_CHEER = 0.65

    def drift(self, now: float):
        """Time passes: energy toward the hour's level, cheer back toward its base (hours-long)."""
        if self.updated <= 0:
            self.updated = now
        hours = max(0.0, (now - self.updated) / 3600)
        local = time.localtime(now)
        target = energy_for_hour(local.tm_hour + local.tm_min / 60)
        k = 1 - math.exp(-hours / 0.75)
        self.energy += (target - self.energy) * k
        self.cheer += (self.BASE_CHEER - self.cheer) * (1 - math.exp(-hours / 6))
        self.updated = now

    def heard(self, text: str, now: float, gap_s: float = 0.0):
        """You said something to her: nice things lift her, rudeness stings a little, a long silence
        before it means she missed you (a small happy bump now)."""
        self.drift(now)
        if NICE.search(text):
            self.cheer += 0.08
        if RUDE.search(text):
            self.cheer -= 0.12
        if gap_s > 2 * 86400:
            self.cheer += 0.05
        self.energy = min(1.0, self.energy + 0.03)          # talking wakes her up a little
        self.cheer = max(0.0, min(1.0, self.cheer))

    def ignored(self, days: float):
        """No conversation for days: a little lonely (drifts back once you talk)."""
        self.cheer = max(0.2, self.cheer - 0.05 * min(days, 4))

    @property
    def resting_emotion(self) -> str:
        if self.energy < 0.3:
            return "sleepy"
        if self.cheer > 0.8:
            return "happy"
        if self.cheer < 0.35:
            return "sad"
        return "neutral"

    def note(self) -> str | None:
        """A line for the model, only when the mood is worth acting on."""
        bits = []
        if self.energy < 0.3:
            bits.append("sleepy and mellow (it's late)")
        elif self.energy > 0.88:
            bits.append("full of energy")
        if self.cheer > 0.85:
            bits.append("in a really good mood")
        elif self.cheer < 0.35:
            bits.append("a little down")
        return f"You're feeling {' and '.join(bits)}; let it show a little." if bits else None

    def to_json(self) -> str:
        return json.dumps({"energy": round(self.energy, 3), "cheer": round(self.cheer, 3), "updated": self.updated})

    @classmethod
    def from_json(cls, raw: str | None) -> "Mood":
        try:
            d = json.loads(raw or "")
            return cls(float(d["energy"]), float(d["cheer"]), float(d.get("updated", 0)))
        except (ValueError, KeyError, TypeError):
            return cls()


class MoodKeeper:
    """Loads / saves the mood and tells the avatar when her resting face changes."""

    def __init__(self, memory=None, publish=lambda kind, data: None, clock=time.time):
        self.memory = memory
        self.publish = publish
        self.clock = clock
        self.mood = Mood.from_json(memory.get("mood") if memory is not None else None)
        self._last_face = None
        self.hold: str | None = None     # a resting face held by comfort mode (comfort.py)
        self._last_talk = float(memory.get("mood:last_talk") or 0) if memory is not None else 0.0
        days = (clock() - self._last_talk) / 86400 if self._last_talk else 0
        if days > 1:
            self.mood.ignored(days)
        self.tick()

    def tick(self):
        self.mood.drift(self.clock())
        self._save()

    def heard(self, text: str):
        now = self.clock()
        self.mood.heard(text, now, now - self._last_talk if self._last_talk else 0)
        self._last_talk = now
        if self.memory is not None:
            self.memory.set("mood:last_talk", str(now))
        self._save()

    def _save(self):
        if self.memory is not None:
            self.memory.set("mood", self.mood.to_json())
        face = self.hold or self.mood.resting_emotion
        if face != self._last_face:
            self._last_face = face
            self.publish("mood", {"resting": face, "energy": round(self.mood.energy, 2), "cheer": round(self.mood.cheer, 2)})

    def hold_face(self, face: str | None):
        """Comfort mode holds a soft face (None lets her own mood show again)."""
        self.hold = face
        self._save()
