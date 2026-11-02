"""A piece of her friendship (goals, wins, care...) that plugs into the two places she acts on her own:

  - `moments(now)`: things worth saying first, picked up by the initiative loop (initiative.py)
    like the built-in ones (same do-not-disturb, cooldown, daily cap and "said that already" checks);
  - `notes(user_text, last_reply)`: one-off lines for the model on a request (main.companion_mind),
    never stored in the chat history;
  - `used(moment, now)`: one of its moments was said;
  - `observe(now)`: every tick, even while they're away or she's quiet (following what's on screen).

State goes in the memory database's kv table as JSON, under the part's own prefix.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from typing import Callable


class Part:
    name = "part"

    def __init__(self, store=None, clock: Callable[[], float] = time.time):
        self.store = store                   # MemoryStore (kv), or None: nothing kept
        self.clock = clock

    # ----- kv -----
    def get(self, key: str, default=None):
        if self.store is None:
            return getattr(self, "_mem", {}).get(key, default)
        raw = self.store.get(f"{self.name}:{key}")
        try:
            return json.loads(raw) if raw else default
        except ValueError:
            return default

    def put(self, key: str, value):
        if self.store is None:
            self.__dict__.setdefault("_mem", {})[key] = value
            return
        self.store.set(f"{self.name}:{key}", json.dumps(value))

    # ----- tables (parts that keep rows in the memory database) -----
    def _schema(self, sql: str):
        if self.store is not None and hasattr(self.store, "db"):
            with self.store.lock:
                self.store.db.executescript(sql)
                self.store.db.commit()

    def _rows(self, sql: str, args=()) -> list[dict]:
        with self.store.lock:
            return [dict(r) for r in self.store.db.execute(sql, args).fetchall()]

    def _exec(self, sql: str, args=()):
        with self.store.lock:
            cur = self.store.db.execute(sql, args)
            self.store.db.commit()
            return cur

    def now(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.clock())

    def today(self) -> str:
        return self.now().date().isoformat()

    def once(self, key: str) -> bool:
        """True the first time `key` is seen (kept in kv, last 300)."""
        seen = self.get("once", [])
        if key in seen:
            return False
        self.put("once", [*seen, key][-300:])
        return True

    def done(self, key: str) -> bool:
        return key in self.get("once", [])

    # ----- hooks -----
    def observe(self, now: float):
        """Every initiative tick, even while they're away from the keyboard or she's keeping quiet
        (watching a film is "away": no input for an hour). For following along, not for talking."""

    def moments(self, now: float) -> list:
        return []

    def used(self, moment, now: float):
        if moment.key:
            self.once(moment.key)

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        return []

    def route(self, user_text: str, last_reply: str = "") -> tuple[str, dict] | None:
        """A request that should go straight to one of this part's tools (agent.py), or None."""
        return None


def clock_words(d: dt.datetime) -> str:
    return f"{d.hour % 12 or 12}{d.strftime(':%M') if d.minute else ''} {'AM' if d.hour < 12 else 'PM'}"


def in_hours(d: dt.datetime, start: str, end: str) -> bool:
    """'21:00'-'23:30' (or across midnight, '23:00'-'02:00')."""
    hm = f"{d:%H:%M}"
    return start <= hm < end if start < end else (hm >= start or hm < end)
