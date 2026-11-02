"""She keeps thinking about your chats after they end, and brings a thought up later.

A while after a conversation (it's been quiet `QUIET_MIN`, you're idle, the model is free), the
fast model rereads what you said and picks ONE thing a friend would keep thinking about: a worry,
a plan, an idea, something you were excited about. It writes the thought she'd bring up next time
("I kept thinking about the internship thing: did you decide whether to apply?").

Grounded like friend memory: the thought must share real words with your own lines (not hers),
no sensitive topics (friend.SENSITIVE), no numbers you didn't say; never from a hard moment
(comfort) or from turns that weren't your voice. At most 3 waiting (kv thoughts:pending), each
kept 2 days. She brings one up at least an hour later, as small talk while you're at the laptop,
or when you ask "what have you been up to?".
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import random
import re
import threading
import time
from typing import Callable

from .initiative import Moment
from .part import Part

log = logging.getLogger(__name__)
QUIET_MIN = 20
KEEP_H = 48
AFTER_S = 3600                 # brought up no sooner than this after the chat
MAX_PENDING = 3
UP_TO = re.compile(r"\b(what (have|did) you (been )?(do|doing|up to|thinking)|what'?s new|what'?s on your mind|"
                   r"what are you thinking|what'?ve you been up to)\b", re.I)

PROMPT = """You are {name}, {user}'s close friend. Below is your last conversation with {user}.

Think about it the way a friend does afterwards. Pick ONE thing {user} said that you'd keep thinking about: a worry, a plan, a decision, an idea, something they were excited or nervous about. Write the thought you'd bring up next time you talk: a caring follow-up question, an idea for them, or how you feel about it.

Rules: only use what {user} actually said; never invent events, names, numbers or details. Not about health, money, religion or politics. "about" quotes {user}'s own words. "thought" is under 25 words, first person, casual, as you'd say it out loud. If nothing is worth thinking about (small talk, commands), give empty strings.

Conversation:
{turns}"""
SCHEMA = {"type": "object", "properties": {"about": {"type": "string"}, "thought": {"type": "string"}},
          "required": ["about", "thought"]}


COMMAND = re.compile(r"^\W*(?:hey \w+,? )?(remind|set|open|play|pause|stop|what('?s| is) the (time|weather)|what time|"
                     r"turn|add|cancel|show|search|look up|close|call|text|thanks|thank you|ok(ay)?|cool|nice|lol)\b", re.I)


def substance(lines: list[str]) -> list[str]:
    """Their lines that say something about them (6+ words, not a command or a thanks)."""
    return [l for l in lines if len(l.split()) >= 6 and not COMMAND.search(l)]


class Thoughts(Part):
    name = "thoughts"

    def __init__(self, store=None, clock=time.time, llm=None, model: str = "", user: str = "the user",
                 her: str = "Sanae", can_run: Callable[[], bool] = lambda: True, idle: Callable[[], float] = lambda: 0.0,
                 rng=None):
        super().__init__(store, clock)
        self.llm, self.model, self.user, self.her = llm, model, user, her
        self.can_run, self.idle = can_run, idle
        self.rng = rng or random.Random()
        self._stop = threading.Event()

    # ----- thinking -----
    def pending(self) -> list[dict]:
        cutoff = self.clock() - KEEP_H * 3600
        return [t for t in self.get("pending", []) if t["t"] >= cutoff]

    def _turns(self) -> list[dict]:
        mem = self.store
        if mem is None:
            return []
        last = int(self.get("last_turn", 0) or 0)
        turns = mem.recent_turns(30)
        if last == 0:                                   # first run: start from now
            self.put("last_turn", turns[-1]["id"] if turns else 0)
            return []
        return [t for t in turns if t["id"] > last]

    def think_once(self) -> str | None:
        turns = self._turns()
        if not turns:
            return None
        last_ts = dt.datetime.fromisoformat(turns[-1]["ts"]).timestamp()
        if self.clock() - last_ts < QUIET_MIN * 60 or not self.can_run():
            return None
        self.put("last_turn", turns[-1]["id"])
        private = set(json.loads(self.store.get("comfort:turns") or "[]")) if self.store is not None else set()
        mine = [t for t in turns if (t.get("heard") or "") in ("", "you") and t["id"] not in private and t["user"].strip()]
        said = substance([t["user"] for t in mine])
        if len(mine) < 3 or len(said) < 2:             # commands and small talk: nothing to think about
            return None
        prompt = PROMPT.format(name=self.her, user=self.user,
                               turns="\n".join(f"{self.user}: {t['user']}\n{self.her}: {t['reply']}" for t in mine[-14:]))
        try:
            raw = self.llm.chat(self.model, [{"role": "user", "content": prompt}], fmt=SCHEMA,
                                options={"temperature": 0.4, "num_predict": 120}).content
            data = json.loads(raw)
        except Exception as exc:
            log.info("thinking about the chat failed: %s", exc)
            return None
        return self.keep(str(data.get("thought") or ""), str(data.get("about") or ""), said)

    def keep(self, thought: str, about: str, said: list[str]) -> str | None:
        from .friend import grounded, sensitive

        thought = " ".join(thought.split()).strip().strip('"')
        if not thought or len(thought.split()) > 40:
            return None
        names = (self.user, self.her)
        theirs = " ".join(said)
        if not grounded(thought, said, names) or sensitive(thought) or sensitive(about):
            log.info("thought not kept (not from their words, or sensitive): %s", thought)
            return None
        if any(n not in theirs for n in re.findall(r"\d+", thought)):
            log.info("thought not kept (a number they didn't say): %s", thought)
            return None
        self.put("pending", [*self.pending(), {"t": self.clock(), "thought": thought, "about": about[:120]}][-MAX_PENDING:])
        log.info("a thought to bring up later: %s", thought)
        return thought

    # ----- bringing it up -----
    def _ready(self) -> dict | None:
        ready = [t for t in self.pending() if self.clock() - t["t"] >= AFTER_S]
        return ready[0] if ready else None

    def _drop(self, item: dict):
        self.put("pending", [t for t in self.pending() if t["t"] != item["t"]])

    def moments(self, now: float) -> list[Moment]:
        idle = self.idle()
        if idle < 20 or idle > 300 or self.rng.random() > 30 / (40 * 60):    # about once per 40 min of chances
            return []
        item = self._ready()
        if item is None:
            return []
        return [Moment("thought", f"Since your last chat you kept thinking about something {{user}} said "
                                  f"(\"{item['about']}\"). Your thought: {item['thought']} Bring it up naturally, like a "
                                  "friend picking a thread back up (\"I was thinking about what you said...\"). One or "
                                  "two short lines.", key=f"thought:{item['t']}")]

    def used(self, moment, now: float):
        t = float(moment.key.split(":", 1)[1])
        self.put("pending", [x for x in self.pending() if x["t"] != t])

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        if not UP_TO.search(user_text):
            return []
        item = self._ready() or (self.pending()[:1] or [None])[0]
        if item is None:
            return []
        self._drop(item)
        return [f"Something you've been thinking about since your last chat (about \"{item['about']}\"): "
                f"{item['thought']} Share it as part of your answer"]

    def start(self, every_s: float = 300):
        def loop():
            self._stop.wait(90)
            while not self._stop.is_set():
                try:
                    if self.idle() >= 60:
                        self.think_once()
                except Exception as exc:
                    log.warning("thoughts failed: %s", exc)
                self._stop.wait(every_s)

        threading.Thread(target=loop, name="thoughts", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()
