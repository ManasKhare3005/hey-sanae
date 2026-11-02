"""A life of her own: while you're away she reads one thing related to what you're into, and
brings it up when you're back ("I read about QUIC while you were gone...").

Away for 30+ minutes (no keyboard or mouse), at most once every 3 hours, never during a game
or while the models are asleep. The search terms come only from your interests ("about you"
facts) and course names, are written by the small model, and are checked before anything is
sent to the search engine: at most 6 words, nothing sensitive (friend.SENSITIVE), no names of
people you know. The pages are read through the local search setup (web.py); her note must
keep every number from what she read. One note waits at a time and expires after 12 hours.
"""
from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from typing import Callable

from .friend import sensitive

log = logging.getLogger(__name__)

AWAY_S = 30 * 60
GAP_S = 3 * 3600
KEEP_S = 12 * 3600

QUERY_PROMPT = """{user} is into these things: {seeds}.
Pick ONE of them and write a web search query (3 to 6 words) for something new and interesting to read about it today: a recent development, a surprising fact, a cool idea. Not about {user} personally. Reply with the query only."""

NOTE_PROMPT = """You are {name}, {user}'s friend who lives on their laptop. While {user} was away you read this about "{query}":

{passages}

In ONE or two short sentences (under 35 words), say the most interesting thing you learned, the way you'd tell a friend ("I read that..."). Only facts from the text above. Plain words, no emojis."""

NUMBERS = re.compile(r"\b\d+(?:[.,]\d+)?%?")


def safe_query(query: str, people: list[str]) -> str | None:
    """The search query if it's fit to send out, else None."""
    q = " ".join(query.strip().strip('"').split())
    q = re.sub(r"^(query|search)\s*:\s*", "", q, flags=re.I)
    words = q.split()
    if not 2 <= len(words) <= 6 or sensitive(q):
        return None
    low = q.lower()
    if any(p and re.search(rf"\b{re.escape(p.lower())}\b", low) for p in people):
        return None
    return q


def people_names(facts: list) -> list[str]:
    """First names from "person" facts ("Alex's sister is Maya" -> Maya), never searched for."""
    names = set()
    for f in facts:
        if getattr(f, "kind", "") == "person":
            names.update(re.findall(r"\b([A-Z][a-z]{2,})\b", f.text))
    return sorted(names)


class Reader:
    def __init__(self, ctx, llm, model: str, user: str, name: str, idle: Callable[[], float],
                 can_run: Callable[[], bool] = lambda: True, clock=time.time, rng=None):
        self.ctx, self.llm, self.model = ctx, llm, model
        self.user, self.name = user, name
        self.idle, self.can_run, self.clock = idle, can_run, clock
        self.rng = rng or random.Random()
        self._stop = threading.Event()

    # ----- the waiting note -----
    def pending(self) -> dict | None:
        raw = self.ctx.memory.get("reading:pending")
        note = json.loads(raw) if raw else None
        if note and self.clock() - note.get("t", 0) > KEEP_S:
            self.ctx.memory.set("reading:pending", "")
            return None
        return note or None

    def used(self):
        self.ctx.memory.set("reading:pending", "")

    # ----- reading -----
    def seeds(self) -> list[str]:
        out = []
        friend = getattr(self.ctx, "friend", None)
        if friend is not None:
            out += [f.text for f in friend.facts() if f.kind in ("like", "project", "plan")][:12]
        course = getattr(self.ctx, "course", None)
        if course is not None:
            try:
                with course.lock:
                    out += [r[0] for r in course.db.execute("SELECT DISTINCT course FROM files").fetchall()][:6]
            except Exception as exc:
                log.debug("course names: %s", exc)
        return out

    def due(self) -> bool:
        last = float(self.ctx.memory.get("reading:last") or 0)
        return (self.idle() >= AWAY_S and self.clock() - last >= GAP_S and self.pending() is None
                and getattr(self.ctx, "web", None) is not None and self.can_run())

    def read_once(self) -> dict | None:
        from .agent import strip_thinking

        seeds = self.seeds()
        if not seeds:
            return None
        self.ctx.memory.set("reading:last", str(self.clock()))
        picked = self.rng.sample(seeds, min(4, len(seeds)))
        reply = self.llm.chat(self.model, [{"role": "user", "content": QUERY_PROMPT.format(
            user=self.user, seeds="; ".join(picked))}], options={"temperature": 0.7, "num_predict": 24})
        friend = getattr(self.ctx, "friend", None)
        people = people_names(friend.facts() if friend is not None else []) + [self.user]
        query = safe_query(strip_thinking(reply.content).splitlines()[0] if reply.content else "", people)
        if query is None:
            log.info("reading: no safe query this time")
            return None
        results, passages = self.ctx.web.research(query, pages=2, passages_per_page=2)
        text = "\n".join(p for r in results for p in passages.get(r.url, []))[:1600]
        if len(text) < 200:
            return None
        reply = self.llm.chat(self.model, [{"role": "user", "content": NOTE_PROMPT.format(
            name=self.name, user=self.user, query=query, passages=text)}], options={"temperature": 0.4, "num_predict": 90})
        note = " ".join(strip_thinking(reply.content).split())
        if not note or any(n not in text for n in NUMBERS.findall(note)):     # a number she didn't read
            log.info("reading: note dropped (empty or invented a number)")
            return None
        url = next((r.url for r in results if passages.get(r.url)), "")
        out = {"query": query, "note": note, "url": url, "t": self.clock()}
        self.ctx.memory.set("reading:pending", json.dumps(out))
        log.info("reading: read about %r while you were away", query)
        return out

    def start(self, interval_s: float = 300.0):
        def loop():
            while not self._stop.wait(interval_s):
                try:
                    if self.due():
                        self.read_once()
                except Exception as exc:
                    log.info("reading: %s", exc)

        threading.Thread(target=loop, name="reading", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()
