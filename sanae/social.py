"""Nudging your real social life, like a friend who wants you to have other friends too.

  - "hung out with Maya" / "called my mom" / "dinner with friends" is noted (kv social:last, the
    time only) and she's glad for you;
  - if a week goes by without any of that, once a week she asks lightly whether you've seen or
    talked to anyone, and may suggest texting someone she knows you care about (friend memory);
  - birthdays you told her about (diary dates, "Maya's birthday is Oct 20" facts): the day before,
    "Maya's birthday is tomorrow, got anything planned?"; on the day, "text Maya happy birthday!".
"""
from __future__ import annotations

import datetime as dt
import random
import re
import time

from .initiative import Moment
from .part import Part

SOCIAL = re.compile(r"\b(hung out|hang(ing)? out|hangout|met up|meeting up|meet(ing)? (up )?with|went out|going out|"
                    r"(grabbed|got|had|getting) (food|dinner|lunch|coffee|boba|drinks|brunch) with|"
                    r"with (my |the )?(friends?|roommates?|mom|dad|parents|family|sister|brother|cousins?|girlfriend|"
                    r"boyfriend|partner|crew|squad|team)|called (my )?(mom|dad|sister|brother|friend|parents|grandma)|"
                    r"facetimed|video called|party|game night|movie night|visited|visiting|sleepover|date night|"
                    r"played with (my )?friends|duo(ed)? with|queued with)\b", re.I)
QUIET_DAYS = 7
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
BDAY = re.compile(r"\b([A-Z][a-z]+)(?:'s)? (?:birthday|bday)\b.*?\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? "
                  r"(\d{1,2})", re.I)


def birthdays(texts: list[str]) -> list[tuple[str, str]]:
    """'Maya's birthday is October 20' -> ('Maya', '10-20')."""
    out = []
    for t in texts:
        m = BDAY.search(t)
        if m:
            out.append((m.group(1), f"{MONTHS[m.group(2).lower()[:3]]:02d}-{int(m.group(3)):02d}"))
    return out


class Social(Part):
    name = "social"

    def __init__(self, store=None, clock=time.time, friend=None, diary=None, idle=lambda: 0.0, rng=None):
        super().__init__(store, clock)
        self.friend, self.diary, self.idle = friend, diary, idle
        self.rng = rng or random.Random()
        if self.get("since") is None:
            self.put("since", self.clock())          # don't call it a quiet week before she's watched one

    def people(self) -> list[str]:
        try:
            from .reading import people_names

            return people_names(self.friend.facts()) if self.friend is not None else []
        except Exception:
            return []

    def _birthdays(self) -> list[tuple[str, str, str]]:
        """(who, MM-DD, where from): "facts" or "diary" (the diary already mentions its dates on the day)."""
        texts = []
        try:
            if self.friend is not None:
                texts += [f.text for f in self.friend.facts()]
        except Exception:
            pass
        out = [(who, day, "facts") for who, day in birthdays(texts)]
        try:
            if self.diary is not None:
                for m in self.diary.moments():
                    if m.kind == "date" and "birthday" in m.text.lower() and m.date:
                        who = re.findall(r"\b([A-Z][a-z]{2,})\b", m.text)
                        out.append((who[0] if who else m.text, m.date, "diary"))
        except Exception:
            pass
        seen, keep = set(), []
        for b in out:
            if b[:2] not in seen:
                seen.add(b[:2])
                keep.append(b)
        return keep

    def moments(self, now: float) -> list[Moment]:
        if self.idle() > 300:
            return []
        d = self.now()
        out = []
        if d.hour >= 9:
            tomorrow = f"{d.date() + dt.timedelta(days=1):%m-%d}"
            today = f"{d:%m-%d}"
            for who, day, source in self._birthdays():
                if day == tomorrow and not self.done(f"bday-eve:{who}:{d.year}"):
                    out.append(Moment("social", f"Tomorrow is {who}'s birthday (they told you). Mention it warmly, and "
                                                "ask if they've got something planned or want a reminder to text them.",
                                      True, f"bday-eve:{who}:{d.year}"))
                elif day == today and source == "facts" and not self.done(f"bday:{who}:{d.year}"):
                    out.append(Moment("social", f"Today is {who}'s birthday. Nudge {{user}} to text or call {who}, "
                                                "warmly, one line.", True, f"bday:{who}:{d.year}"))
        last = max(self.get("last", 0), self.get("since", 0))
        week = f"{d:%G-%V}"
        if now - last >= QUIET_DAYS * 86400 and 14 <= d.hour < 22 and not self.done(f"quiet:{week}") \
                and self.rng.random() < 0.03:
            names = self.people()
            who = f" You know about: {', '.join(names[:4])}." if names else ""
            out.append(Moment("social", "{user} hasn't mentioned seeing or talking to anyone in a while. Lightly ask if "
                                        "they've hung out with anyone lately, or suggest texting someone they care about."
                                        f"{who} One line, warm, not preachy; don't say you've been tracking it.",
                              key=f"quiet:{week}"))
        return out[:1]

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        if SOCIAL.search(user_text) and not re.search(r"\b(didn'?t|haven'?t|never|no one|nobody|cancel+ed)\b", user_text, re.I):
            self.put("last", self.clock())
            return ["They spent time with people: be glad for them, and ask about it if it fits"]
        return []
