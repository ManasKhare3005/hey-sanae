"""She talks first: a background loop that notices moments worth a word and lets the small model
say one short, in-character line about it.

Moments: hello at the start of the day, welcome back after being away, a break nudge after a long
stretch at the laptop, an event / class / Canvas deadline coming up soon (phase 1); asking how
something went (threads from friend.py), small talk from a topic pool (persona.yaml topics + things
she knows you like), noticing what's in front (the window title, read in memory only), and gentle
bedtime nudges late at night, at random gaps, only while you're actually using the laptop (phase 3).

Every 30 s: work out which moments apply -> skip if do-not-disturb says so (game, call, "not now",
asleep), she's busy with a request, she spoke first too recently (cooldown by chattiness), or she
already said her share today (daily cap; upcoming events and bedtime skip both) -> ask the model for
one line (it may answer SKIP) -> drop it if it means the same as something she said in the last two
weeks -> queue it to be spoken when the voice loop is idle (then she listens for a reply).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import random
import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

ACTIVE_IDLE_S = 5 * 60          # less idle than this = at the laptop
USING_S = 120                   # input within this = actually using it (bedtime nudges)
SAID_DAYS = 14                  # lines she started, kept this long to avoid repeating herself
SAME_LINE = 0.86                # a new line this close in meaning to a recent one isn't said
DAILY_CAP = {"quiet": 4, "normal": 8, "chatty": 14}
EXEMPT = ("upcoming", "bedtime", "care")    # skip the cooldown and the daily cap


def idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input (Windows)."""
    if sys.platform != "win32":
        return 0.0
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return max(0.0, (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0)


@dataclass
class Moment:
    kind: str                  # greeting | welcome_back | break | upcoming | callback | chat | noticing | bedtime
    situation: str             # what's going on, for the model
    important: bool = False    # spoken even inside the cooldown
    key: str = ""              # remembered once used (so an event is mentioned once)
    part: str = ""             # from a Part (part.py): its used() is called when said
    line: str = ""             # already written (e.g. her haiku): said as is, not generated


class Activity:
    """Tracks presence from input idle time: sessions at the laptop and time away."""

    def __init__(self, now: float):
        self.active_since = now          # start of the current stretch at the laptop
        self.away_since: float | None = None
        self.last_away_s = 0.0           # how long the last time away lasted (set when they come back)
        self.came_back = False

    def update(self, now: float, idle_s: float):
        self.came_back = False
        if idle_s >= ACTIVE_IDLE_S:
            if self.away_since is None:
                self.away_since = now - idle_s
        elif self.away_since is not None:
            self.last_away_s = now - idle_s - self.away_since
            self.away_since = None
            self.active_since = now - idle_s
            self.came_back = True

    @property
    def away(self) -> bool:
        return self.away_since is not None


class Initiative:
    def __init__(self, ctx, say: Callable[[str, dict], None], generate: Callable[[Moment], str | None],
                 dnd=None, busy: Callable[[], bool] = lambda: False, publish=lambda kind, data: None,
                 settings: dict | None = None, chattiness: str = "normal",
                 idle: Callable[[], float] = idle_seconds, clock: Callable[[], float] = time.time,
                 friend=None, window=None, topics: list[str] | None = None, embed=None, rng=None, diary=None,
                 reader=None, music=None, comfort=None, parts=None):
        self.ctx = ctx
        self.say = say                  # (line, info): queue the line to be spoken
        self.generate = generate        # Moment -> line with tags, or None to stay quiet
        self.dnd = dnd
        self.busy = busy
        self.publish = publish
        s = settings or {}
        self.greeting = s.get("greeting", True)
        self.break_after_s = float(s.get("break_after_min", 120)) * 60
        self.lead_s = float(s.get("calendar_lead_min", 15)) * 60
        self.welcome_after_s = float(s.get("welcome_back_after_min", 45)) * 60
        self.welcome_gap_s = float(s.get("welcome_back_gap_min", 180)) * 60     # at most one per this long
        self.break_gap_s = float(s.get("break_gap_min", s.get("break_after_min", 120))) * 60
        self.cooldowns = {**{"quiet": 90, "normal": 40, "chatty": 15}, **(s.get("cooldown_min") or {})}
        self.chattiness = chattiness
        self.idle, self.clock = idle, clock
        self.friend = friend            # friend.FriendMemory: threads to ask about, your interests
        self.diary = diary              # diary.Diary: the week's entries, shared moments, birthdays
        self.reader = reader            # reading.Reader: what she read while they were away
        self.music = music              # music.MusicWatch: a comment on a song now and then
        self.comfort = comfort          # comfort.Comfort: quiet while they're not okay; the next-day check-in
        self.parts = list(parts or [])  # part.Part: goals, wins, care... (their own moments)
        self.music_gap_s = float(s.get("music_gap_min", 60)) * 60 if s.get("music", True) else None
        self.last_music = 0.0
        self.window = window            # window.WindowWatch: what's in front (never stored)
        self.topics = list(topics or [])
        self.embed = embed              # texts -> vectors, for "said that already"
        self.rng = rng or random.Random()
        # small talk: on average every `chat_every_min` (beyond the cooldown); None = off
        self.chat_every_s = float(s["chat_every_min"]) * 60 if s.get("chat_every_min") else None
        self.notice_after_s = float(s.get("notice_after_min", 12)) * 60 if s.get("noticing", False) else None
        self.notice_gap_s = float(s.get("notice_gap_min", 75)) * 60
        self.last_noticed = 0.0
        b = s.get("bedtime") or {}
        self.bedtime = (b.get("from", "01:00"), b.get("until", "05:00"), b.get("every_min", [25, 55])) if b else None
        self.next_bedtime = 0.0
        self.daily_cap = int(s.get("daily_cap", {}).get(chattiness, DAILY_CAP.get(chattiness, 8))
                             if isinstance(s.get("daily_cap"), dict) else DAILY_CAP.get(chattiness, 8))
        self.activity = Activity(clock())
        self.last_spoke = 0.0
        self.last_break_nudge = 0.0
        self.last_welcome = 0.0
        c = s.get("checkin", {"from": "20:00", "until": "23:00"})
        self.checkin = (c.get("from", "20:00"), c.get("until", "23:00")) if c else None
        self.weekly = str(s.get("weekly", "sun") or "").lower()[:3]       # day for the look back at the week
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ----- state kept across restarts -----
    def _kv(self, key: str, default=None):
        mem = getattr(self.ctx, "memory", None)
        if mem is None:
            return default
        raw = mem.get(f"initiative:{key}")
        return json.loads(raw) if raw else default

    def _set(self, key: str, value):
        mem = getattr(self.ctx, "memory", None)
        if mem is not None:
            mem.set(f"initiative:{key}", json.dumps(value))

    # ----- what's worth saying -----
    def moments(self) -> list[Moment]:
        now = self.clock()
        self.activity.update(now, self.idle())
        for p in self.parts:                    # before the away check: a film is an hour without input
            try:
                if hasattr(p, "observe"):
                    p.observe(now)
            except Exception as exc:
                log.debug("%s observe failed: %s", getattr(p, "name", p), exc)
        if self.activity.away:
            return []
        if self.comfort is not None:
            care = self._care(now)
            if care or self.comfort.serious:
                return care                     # not okay: no small talk, music, nudges...
            if self.comfort.holding_back():     # easing back: only a class / event that's about to start
                return self._upcoming(dt.datetime.fromtimestamp(now))
        out: list[Moment] = []
        today = dt.datetime.fromtimestamp(now).date().isoformat()
        hour = dt.datetime.fromtimestamp(now).hour
        if self.greeting and self._kv("greeted") != today and hour >= 5:
            from .timesense import part_of_day

            part = part_of_day(hour)
            out.append(Moment("greeting", f"It's the first time you've seen {{user}} today, and it's {part} now"
                                          f"{'' if hour < 12 else ' (not morning: they may have been busy or out)'}. "
                                          "Say hello.",
                              key=f"greeted:{today}"))
        elif self.activity.came_back and self.activity.last_away_s >= self.welcome_after_s \
                and now - self.last_welcome >= self.welcome_gap_s:
            mins = round(self.activity.last_away_s / 60)
            away = f"{mins} minutes" if mins < 90 else f"about {round(mins / 60)} hours"
            # Not a stock "you're back!": carry on from the last chat when there's something to carry on
            read = self.reader.pending() if self.reader is not None else None
            extra = (f" While they were away you read something: {read['note']} If nothing from your last chat is "
                     "better to pick up, share this instead, in one line." if read else "")
            out.append(Moment("welcome_back", f"{{user}} was away {away} and is at the laptop again. If something from "
                                              "your last chat is worth picking back up, do that, naturally, as a friend "
                                              "would; otherwise just a short, casual line. Don't say they're back, "
                                              "don't ask where they went, don't invent things you did." + extra))
        stretch = now - self.activity.active_since
        if stretch >= self.break_after_s and now - self.last_break_nudge >= self.break_gap_s:
            hours = stretch / 3600
            length = f"{round(stretch / 60)} minutes" if hours < 1.5 else f"{hours:.1f} hours".replace(".0 ", " ")
            out.append(Moment("break", f"{{user}} has been at the laptop for {length} without a real break. "
                                       "Gently suggest a short one (stretch, water, rest the eyes)."))
        out += self._upcoming(dt.datetime.fromtimestamp(now))
        out += self._from_parts(now, important=True)
        out += self._bedtime(now)
        out += self._callbacks(dt.datetime.fromtimestamp(now))
        out += self._dates(dt.datetime.fromtimestamp(now))
        out += self._checkin(now)
        out += self._weekly(now)
        out += self._music(now)
        out += self._from_parts(now, important=False)
        out += self._noticing(now)
        out += self._chat(now)
        return out

    def _from_parts(self, now: float, important: bool) -> list[Moment]:
        out = []
        for p in self.parts:
            try:
                for m in p.moments(now):
                    if m.important == important:
                        m.part = m.part or p.name
                        out.append(m)
            except Exception as exc:
                log.debug("%s moments failed: %s", getattr(p, "name", p), exc)
        return out

    # ----- phase 3 moments -----
    def _bedtime(self, now: float) -> list[Moment]:
        if not self.bedtime:
            return []
        start, end, gap = self.bedtime
        d = dt.datetime.fromtimestamp(now)
        hm = f"{d:%H:%M}"
        late = start <= hm < end if start < end else (hm >= start or hm < end)
        if not late:
            self.next_bedtime = 0.0
            return []
        if self.idle() > USING_S:                      # only while the laptop is actually being used
            return []
        if not self.next_bedtime:                      # just got late: first nudge a little later
            self.next_bedtime = now + self.rng.uniform(5, 20) * 60
        if now < self.next_bedtime:
            return []
        clock = f"{d.hour % 12 or 12}:{d:%M} {'AM' if d.hour < 12 else 'PM'}"
        return [Moment("bedtime", f"It's {clock}, really late, and {{user}} is still up on the laptop. Gently nudge them "
                                  "toward bed: tease them about being a night owl, mention tomorrow, or offer to say goodnight "
                                  "(a different angle than before; no lecture, no weird metaphors).", True)]

    def _callbacks(self, now: dt.datetime) -> list[Moment]:
        if self.friend is None:
            return []
        try:
            return [Moment("callback", f"Earlier {{user}} mentioned this: {t.about}. If you remember right, it should be "
                                       "over by now. Ask casually and leave room to be wrong, e.g. \"you had <it> today, "
                                       "right? how'd it go?\" (one short question; no teasing, no guessing how it went).",
                           key=f"thread:{t.id}")
                    for t in self.friend.due_threads(now)[:1]]
        except Exception as exc:
            log.debug("threads check failed: %s", exc)
            return []

    def _noticing(self, now: float) -> list[Moment]:
        if self.window is None or self.notice_after_s is None or now - self.last_noticed < self.notice_gap_s:
            return []
        w = self.window.now()
        if w is None or self.window.steady_s() < self.notice_after_s or self.rng.random() > 0.25:
            return []
        mins = round(self.window.steady_s() / 60)
        return [Moment("noticing", f"{{user}} has had this in front for about {mins} minutes: {w.describe()}. If there's "
                                   "something light and friendly to say about it (curious, encouraging, a small joke), say it; "
                                   "never read the title out word for word. Otherwise SKIP.")]

    def _care(self, now: float) -> list[Moment]:
        """The day after a hard time: one gentle "how are you doing today?" (once, only that day)."""
        if not self.comfort.care_due(now) or self.idle() > USING_S:
            return []
        from .comfort import CARE_SITUATION, day_of

        return [Moment("care", CARE_SITUATION, True, key=f"care:{day_of(now)}")]

    # ----- phase B: evening check-in, the week, birthdays -----
    def _checkin(self, now: float) -> list[Moment]:
        if not self.checkin:
            return []
        d = dt.datetime.fromtimestamp(now)
        key = f"checkin:{d.date().isoformat()}"
        if not (self.checkin[0] <= f"{d:%H:%M}" < self.checkin[1]) or key in set(self._kv("upcoming", [])):
            return []
        if any(getattr(p, "replaces_checkin", lambda _d: False)(d) for p in self.parts):
            return []                                                      # a ritual asks instead (rituals.py)
        if self.idle() > USING_S or self.rng.random() > 0.25:            # while they're here; not always at 8:00
            return []
        return [Moment("checkin", "It's evening. Casually ask {user} how today went, in one short question; if you know "
                                  "something that was on their plate today, ask about that. Warm, no teasing.", key=key)]

    def _weekly(self, now: float) -> list[Moment]:
        d = dt.datetime.fromtimestamp(now)
        if self.diary is None or not self.weekly or f"{d:%a}".lower() != self.weekly or d.hour < 17:
            return []
        key = f"weekly:{d:%G-%V}"
        if key in set(self._kv("upcoming", [])) or self.idle() > USING_S:
            return []
        week = self.diary.week(d.date())
        if len(week) < 2:
            return []
        days = " | ".join(f"{dt.date.fromisoformat(e.day):%a}: {e.text[:220]}" for e in reversed(week))
        return [Moment("weekly", f"It's the end of the week. Your diary about {{user}}'s week: {days}. Give a short, warm "
                                 "look back (one or two lines): something they got through, something ahead. No lecture, "
                                 "no list.", key=key)]

    def _music(self, now: float) -> list[Moment]:
        if self.music is None or self.music_gap_s is None or now - self.last_music < self.music_gap_s:
            return []
        if self.idle() > USING_S or self.rng.random() > 0.2:
            return []
        try:
            t = self.music.steady()
        except Exception as exc:
            log.debug("music check failed: %s", exc)
            return []
        if t is None:
            return []
        key = f"music:{t.title}|{t.artist}"
        if key in set(self._kv("upcoming", [])):
            return []
        return [Moment("music", f"{{user}} is listening to {t.spoken()}. Make one short, genuine comment or question "
                                "about it: only things you're sure are true about it; if you don't know it, ask what "
                                "they like about it.", key=key)]

    def _dates(self, now: dt.datetime) -> list[Moment]:
        if self.diary is None or now.hour < 8:
            return []
        said = set(self._kv("upcoming", []))
        out = []
        try:
            for m in self.diary.dates_today(now.date()):
                key = f"date:{m.id}:{now.year}"
                if key not in said:
                    out.append(Moment("date", f"Today is a date {{user}} told you about: {m.text}. Mention it warmly, "
                                              "one line.", True, key))
        except Exception as exc:
            log.debug("dates check failed: %s", exc)
        return out[:1]

    def _chat(self, now: float) -> list[Moment]:
        if self.chat_every_s is None:
            return []
        idle = self.idle()
        if idle < 20 or idle > ACTIVE_IDLE_S:          # not mid-typing, but still here
            return []
        if self.rng.random() > 30 / self.chat_every_s:      # ~one chance per chat_every_s (ticks are 30 s)
            return []
        ideas = list(self.topics)
        if self.friend is not None:
            ideas += [f"something {{user}} is into: {x}" for x in self.friend.interests(3, self.rng)]
            if len(self.friend.facts()) < 25:
                ideas.append("get to know {user} better: ask one light personal question you don't know the answer to yet")
        shared = None
        if self.diary is not None:
            try:
                shared = self.diary.to_bring_up(dt.datetime.fromtimestamp(now))
            except Exception as exc:
                log.debug("moments check failed: %s", exc)
        if shared is not None:
            ideas.append(f"__shared__{shared.id}")
        if not ideas:
            return []
        recent = self._kv("topics", [])[-6:]
        fresh = [i for i in ideas if i not in recent] or ideas
        topic = self.rng.choice(fresh)
        self._set("topics", [*recent, topic][-12:])
        if shared is not None and topic == f"__shared__{shared.id}":
            what = {"joke": "a running joke between you", "nickname": "a nickname between you"}.get(shared.kind, "a moment you shared")
            return [Moment("chat", f"Bring up {what}, naturally, like a friend would (\"remember when...\"): {shared.text}. "
                                   "One short line.", key=f"shared:{shared.id}")]
        return [Moment("chat", f"You feel like chatting. Idea: {topic}. Start a short, casual conversation (a thought or a "
                               "question). Sometimes, when it fits, nudge {user} toward real life (friends, outside, food).")]

    def _upcoming(self, now: dt.datetime) -> list[Moment]:
        said = set(self._kv("upcoming", []))
        out = []
        events = getattr(self.ctx, "events", None)
        if events is not None:
            try:
                for e in events.between(now, now + dt.timedelta(days=1)):
                    if e.all_day or e.status != "active":
                        continue
                    left = (e.start - now).total_seconds()
                    key = f"event:{e.uid}"
                    if 0 < left <= self.lead_s and key not in said:
                        out.append(Moment("upcoming", f"{{user}}'s calendar: \"{e.title}\" starts in {max(1, round(left / 60))} minutes"
                                                      + (f" at {e.location}" if e.location else "") + ".", True, key))
            except Exception as exc:
                log.debug("events check failed: %s", exc)
        canvas = getattr(self.ctx, "canvas", None)
        if canvas is not None:
            try:
                for item in canvas.items():
                    left = (item.start - now).total_seconds()
                    key = f"canvas:{item.kind}|{item.course}|{item.title}|{item.start.isoformat()}"
                    if key in said or left <= 0:
                        continue
                    if item.kind == "class" and left <= self.lead_s:
                        out.append(Moment("upcoming", f"{{user}}'s {item.course} class starts in {max(1, round(left / 60))} minutes.", True, key))
                    elif item.kind == "assignment" and not item.all_day and left <= 2 * 3600:
                        out.append(Moment("upcoming", f"\"{item.title}\" for {item.course} is due in "
                                                      f"{max(1, round(left / 60))} minutes.", True, key))
            except Exception as exc:
                log.debug("canvas check failed: %s", exc)
        return out

    # ----- deciding and speaking -----
    def tick(self) -> str | None:
        """One check. Returns the line said (for tests), or None."""
        moments = self.moments()
        if not moments:
            return None
        why = self.dnd.reason() if self.dnd is not None else None
        if why:
            log.debug("initiative: quiet (%s)", why)
            return None
        if self.busy():
            return None
        now = self.clock()
        cooldown = self.cooldowns.get(self.chattiness, 40) * 60
        moment = next((m for m in moments if m.important), None)
        if moment is None:
            if now - self.last_spoke < cooldown or self._said_today() >= self.daily_cap:
                return None
            moment = moments[0]
        line = moment.line or self.generate(moment)
        self._used(moment, now)
        if not line:
            return None
        if self._repeats(line):
            log.info("initiative: skipped a line that repeats an earlier one")
            return None
        self._remember(line, moment, now)
        self.last_spoke = now
        if moment.kind == "care" and self.comfort is not None:
            self.comfort.care_asked(now)            # their next words answer it
        self.publish("initiative", {"trigger": moment.kind, "priority": "high" if moment.important else "normal",
                                    "spoken": True})
        self.say(line, {"trigger": moment.kind})
        return line

    # ----- not repeating herself, not overdoing it -----
    def recent_lines(self, n: int = 6) -> list[str]:
        return [x["text"] for x in self._kv("said", [])[-n:]]

    def _said_today(self) -> int:
        today = dt.datetime.fromtimestamp(self.clock()).date().isoformat()
        return sum(1 for x in self._kv("said", []) if x.get("day") == today and x.get("kind") not in EXEMPT)

    def _repeats(self, line: str) -> bool:
        if self.embed is None:
            return False
        from .friend import similar
        from .tags import parse

        try:
            return similar(self.embed, parse(line).text, [parse(t).text for t in self.recent_lines(40)], SAME_LINE)
        except Exception:
            return False

    def _remember(self, line: str, m: Moment, now: float):
        cutoff = now - SAID_DAYS * 86400
        said = [x for x in self._kv("said", []) if x.get("t", 0) >= cutoff]
        said.append({"t": now, "day": dt.datetime.fromtimestamp(now).date().isoformat(), "kind": m.kind, "text": line})
        self._set("said", said[-300:])

    def _used(self, m: Moment, now: float):
        if m.part:
            for p in self.parts:
                if p.name == m.part:
                    p.used(m, now)
            return
        if m.kind == "greeting":
            self._set("greeted", m.key.split(":", 1)[1])
        elif m.kind == "break":
            self.last_break_nudge = now
        elif m.kind == "welcome_back":
            self.last_welcome = now
            if self.reader is not None and "you read something" in m.situation:
                self.reader.used()
        elif m.kind == "music":
            self.last_music = now
            said = self._kv("upcoming", [])[-200:]
            self._set("upcoming", [*said, m.key])
        elif m.kind == "bedtime":
            lo, hi = self.bedtime[2] if self.bedtime else (25, 55)
            self.next_bedtime = now + self.rng.uniform(float(lo), float(hi)) * 60
        elif m.kind == "noticing":
            self.last_noticed = now
        elif m.key.startswith("shared:") and self.diary is not None:
            self.diary.used(int(m.key.split(":", 1)[1]))
        elif m.kind == "callback" and self.friend is not None:
            self.friend.asked(int(m.key.split(":", 1)[1]), now)   # "I didn't have a quiz" drops it
        elif m.key:
            said = self._kv("upcoming", [])[-200:]
            self._set("upcoming", [*said, m.key])

    def start(self, interval_s: float = 30.0):
        def loop():
            self._stop.wait(20)                    # let everything else start first
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception as exc:
                    log.warning("initiative check failed: %s", exc)
                self._stop.wait(interval_s)

        self._thread = threading.Thread(target=loop, name="initiative", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()


SKIP = re.compile(r"^\W*skip\W*$", re.I)
LIKES_TOPIC = re.compile(r"\b(cats?|anime|strawberry|rain(y)?|your likes)\b", re.I)


def _opening(text: str, user: str, n: int = 4) -> list[str]:
    """First few words of a line, without tags, punctuation or the user's name."""
    from .tags import TAG

    words = re.findall(r"[a-z']+", TAG.sub(" ", text).lower())
    return [w for w in words if w != user.lower()][:n]


def starts_like(text: str, recent: list[str], user: str) -> bool:
    """Starts with the same first four words as one of her recent lines."""
    head = _opening(text, user)
    return len(head) >= 4 and any(_opening(r, user) == head for r in recent)


def model_line(agent, llm, model: str, user: str, temperature: float = 0.8,
               context: Callable[[], list[str]] = lambda: [], recent: Callable[[], list[str]] = lambda: [],
               check: Callable | None = None):
    """Moment -> one short line from the model in her voice (tags kept), or None if it says SKIP.
    `context()`: extra notes (her mood...); `recent()`: lines she started lately (not to repeat);
    `check(line, situation, notes, chat, now)`: a second look before it's said (firstline.py), which
    may keep, fix or drop it."""
    def generate(moment: Moment) -> str | None:
        from .timesense import fix, greeting_note, stamp

        d = dt.datetime.now()
        now = stamp(d, year=False)
        situation = moment.situation.replace("{user}", user) + f" ({greeting_note(d)}.)"
        extra = " ".join(context())
        earlier = agent.conv.note() if hasattr(agent, "conv") else None
        if earlier:
            extra += f" ({earlier})"
        # Old lines are NOT listed as "don't repeat these": the small model copied them ("you've been
        # gone three hours—did you eat...?" came back three days later with strawberry milk in it).
        # A line that starts like a recent one is regenerated once instead.
        before = recent()
        likes = "" if LIKES_TOPIC.search(situation) else " Don't bring up your own likes."
        note = (f"[{now}] (Nobody said anything; you're speaking first. {situation} {extra}"
                f"Say ONE short, natural line to {user} (under 20 words), starting with an emotion tag. Plain words, "
                f"no emojis. Only mention things you actually know from this chat or your notes: don't make up how "
                f"long they were away or what they were doing.{likes} Vary how you start; don't mention this note. "
                f"If it isn't worth saying, reply SKIP.)")
        history = agent._recent_history()[-6:] if hasattr(agent, "_recent_history") else []
        from .agent import strip_thinking

        from .tags import ASIDE, EMOJI

        text = ""
        for attempt in range(2):
            reply = llm.chat(model, [agent._system(), *history, {"role": "user", "content": note}],
                             options={"temperature": temperature + 0.2 * attempt, "num_predict": 60})
            # one line, without emojis / *asides* (they'd show in the bubble and teach the model to repeat them)
            text = " ".join(strip_thinking(reply.content).split())
            text = fix(" ".join(ASIDE.sub("", EMOJI.sub("", text)).split()).strip().strip('"'), d)
            if not text or SKIP.match(text) or not starts_like(text, before, user):
                break
            log.info("opener started like a recent one; trying again: %s", text)
        if not text or SKIP.match(text) or starts_like(text, before, user):
            return None
        if check is not None:
            chat = [f"{'Them' if m['role'] == 'user' else 'Her'}: {m['content']}" for m in history
                    if isinstance(m.get("content"), str) and m.get("role") in ("user", "assistant")]
            try:
                checked = check(text, situation, extra.strip(), chat, d)
            except Exception as exc:
                log.info("first-line check failed: %s", exc)
                checked = text
            if not checked:
                return None
            text = checked
        # Her line becomes part of the conversation, so "yeah okay" next makes sense to the model.
        # Only that she spoke first: the note's instructions and its list of lines to avoid would
        # be copied into her next answers (she answered "Try it." with an old opener from that list)
        turn = [{"role": "user", "content": f"[{now}] (You spoke first.)"}, {"role": "assistant", "content": text}]
        if hasattr(agent, "conv"):
            agent.conv.add(turn)
        else:
            agent.history.append(turn)
        agent._last_turn = time.monotonic()
        return text
    return generate
