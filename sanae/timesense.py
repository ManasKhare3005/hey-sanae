"""Her sense of time: one place for what time of day it is and what fits it.

The small model greeted with "good morning" at 1 PM: the time was in every prompt, but nothing
checked her words against it (and the chat summary carried made-up clock times from the morning).
So:
  - `stamp()` / `part_of_day()`: the same "[Sun Oct 19 2026, 1:10 PM (afternoon)]" everywhere;
  - `greeting_note()`: what greeting fits right now, for requests that are greetings and for her
    openers;
  - `fix()`: greetings that don't fit the hour are swapped for ones that do ("Good morning!" at
    2 PM -> "Good afternoon!", "Morning, Alex!" at 8 PM -> "Hey, Alex!", "good night" at noon ->
    "see you later"), and `TimeFilter` does the same while a reply streams in, so the voice never
    says the wrong one.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Callable

PARTS = ((0, 5, "late night"), (5, 8, "early morning"), (8, 12, "morning"), (12, 17, "afternoon"),
         (17, 21, "evening"), (21, 24, "night"))
_TAGS = r"(?:\[[a-z_ ]+\]\s*)*"
_START = r"(?:(?<=^)|(?<=[.!?]\s)|(?<=[.!?]\s\s)|(?<=\]\s)|(?<=\]))"
GREETINGS = re.compile(
    r"\b(?P<good>good\s+(?P<part>morning|afternoon|evening|night))\b"
    r"|(?P<rise>\brise and shine\b)"
    r"|(?P<jp>\b(?:ohayou?|oyasumi)\b)"
    rf"|{_START}(?P<bare>(?:morning|mornin'?|afternoon|evening))(?=\s*[,!.~]|\s*$)",
    re.I)
# Phrases to wait for while streaming: a piece ending in "Good" or "rise and" might become one
_PREFIXES = ("good morning", "good afternoon", "good evening", "good night", "rise and shine", "ohayou", "oyasumi",
             "morning", "mornin", "afternoon", "evening")
EVENING_FROM, NIGHT_FROM = 17, 20


def part_of_day(hour: int) -> str:
    """The small model read "7:35 PM" as night ("you've been at it all night"); the words help."""
    for lo, hi, name in PARTS:
        if lo <= hour < hi:
            return name
    return "night"


def stamp(d: dt.datetime, year: bool = True) -> str:
    """'Sun Oct 19 2026, 1:10 PM (afternoon)': no leading zeros, it's read aloud sometimes."""
    return (f"{d:%a %b} {d.day}{f' {d.year}' if year else ''}, {d.hour % 12 or 12}:{d:%M} "
            f"{'AM' if d.hour < 12 else 'PM'} ({part_of_day(d.hour)})")


def fitting_greeting(d: dt.datetime) -> str:
    """The greeting that fits the hour: 'good morning' 4 AM-noon, then afternoon, then evening."""
    h = d.hour
    if 4 <= h < 12:
        return "good morning"
    if 12 <= h < EVENING_FROM:
        return "good afternoon"
    return "good evening" if h >= EVENING_FROM else "hey"     # 0-4 AM: "good evening" is wrong too


def fits(part: str, d: dt.datetime) -> bool:
    """Is a "good <part>" greeting right at this hour?"""
    h = d.hour
    part = part.lower()
    if part.startswith("morn") or part in ("rise and shine", "ohayou", "ohayo"):
        return 4 <= h < 12
    if part == "afternoon":
        return 12 <= h < EVENING_FROM
    if part == "evening":
        return h >= 16
    if part in ("night", "oyasumi"):                   # a goodbye: only once it's late
        return h >= NIGHT_FROM or h < 5
    return True


def greeting_note(d: dt.datetime) -> str:
    """For a request that's a greeting (or her opener): which greeting fits now."""
    part = part_of_day(d.hour)
    fit = fitting_greeting(d)
    wrong = [g for g in ("good morning", "good afternoon", "good evening") if g != fit]
    say = f"\"{fit}\" or just hi" if fit != "hey" else "just hi (it's after midnight)"
    return (f"It's {d.hour % 12 or 12}:{d:%M} {'AM' if d.hour < 12 else 'PM'}, {part}: if you greet, say {say}; "
            f"never {' or '.join(wrong)}. If they said a greeting that doesn't fit the time, you can tease them about it")


def _swap(m: re.Match, d: dt.datetime) -> str:
    word = m.group(0)
    if m.group("good"):
        part = m.group("part")
        if fits(part, d):
            return word
        if part.lower() == "night":
            if re.search(r"(?:^|\W)a\s+$", m.string[:m.start()], re.I):      # "have a good night" in the evening is fine
                if d.hour >= EVENING_FROM or d.hour < 5:
                    return word
                new = "good day"
            else:
                new = "see you later"
        else:
            new = fitting_greeting(d)
            if new == "hey":
                return "Hey" if word[0].isupper() else "hey"
    elif m.group("rise"):
        if fits("rise and shine", d):
            return word
        new = "hey there"
    elif m.group("jp"):
        if fits(word.lower(), d):
            return word
        new = "see you later" if word.lower() == "oyasumi" else "hey"
    else:
        bare = word.lower()
        if fits("morning" if bare.startswith("morn") else bare, d):
            return word
        new = "hey"
    return new[0].upper() + new[1:] if word[0].isupper() else new


def fix(text: str, d: dt.datetime | None = None) -> str:
    """Greetings that don't fit the hour swapped for ones that do. Other uses stay ("this morning")."""
    if not text:
        return text
    d = d or dt.datetime.now()
    return GREETINGS.sub(lambda m: _swap(m, d), text)


def _hold_from(text: str) -> int:
    """Where a greeting might still be forming at the end of a streamed piece (len(text) = nothing to hold)."""
    low = text.lower()
    best = len(text)
    for phrase in _PREFIXES:
        for n in range(1, len(phrase) + 1):          # the tail is the start of the phrase (or all of it:
            head = phrase[:n]                        # "Morning" might still be followed by ", Alex!")
            if low.endswith(head):
                i = len(text) - n
                if i == 0 or not low[i - 1].isalpha():
                    best = min(best, i)
    return best


class TimeFilter:
    """Streams a reply through `fix()`: holds back a few characters while a greeting may still be
    forming, so a wrong one is never spoken. `out(None)` (a new model call) flushes what's held."""

    def __init__(self, out: Callable[[str | None], None], clock: Callable[[], dt.datetime] = dt.datetime.now):
        self.out, self.clock = out, clock
        self._held = ""
        self._tail = ""                 # the last bit already sent: sentence-start context for "Morning!"

    def __call__(self, piece: str | None):
        if piece is None:
            if self._held:
                self._send(self._held)
            self._held, self._tail = "", ""
            self.out(None)
            return
        text = self._held + piece
        cut = _hold_from(text)
        self._held = text[cut:]
        if cut:
            self._send(text[:cut])

    def _send(self, text: str):
        ctx = self._tail[-3:]             # "...today. " before "Morning!" makes it a sentence start
        fixed = fix(ctx + text, self.clock())[len(ctx):]
        self._tail = (self._tail + text)[-6:]
        if fixed:
            self.out(fixed)

    def flush(self):
        if self._held:
            self._send(self._held)
            self._held = ""
