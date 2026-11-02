"""Someone else talking to her: a typed message ending in "~Nina" is from Nina, not the user.

She answers that person as that person: her own way of talking to them (persona.yaml `people:`,
or a friendly default for someone new), and what she and they talked about before. None of it
touches the user's side: the chat with the user, friend memory, diary, mood, comfort and taste
never see guest messages, she doesn't share the user's private things with them, and they only
get a few harmless tools (search, weather, time, music, volume).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field

# "...message ~Nina" / "...message ~ Aunt Meera": one to three words starting with a letter, at the end
TAG = re.compile(r"\s*~\s*([^\W\d_][\w'.-]*(?:\s+[^\W\d_][\w'.-]*){0,2})\s*$")

# Safe for anyone at the keyboard: nothing that reads or changes the user's own things
TOOLS = ("web_search", "weather", "get_datetime", "what_song", "media_control", "volume")

KEEP_TURNS = 12      # past exchanges kept per person
RECENT_TURNS = 6     # ...of which this many go back to the model
NEW_CHAT_H = 6       # a gap longer than this: "you talked before", not a chat still going

DEFAULT_STYLE = ("Be warm and friendly, like meeting a friend of {user}'s. Tease less than you do with {user} "
                 "until you know them. Be curious about them.")


def split(text: str, user: str = "") -> tuple[str, str | None]:
    """("message", "Nina") for "message ~Nina"; (text, None) without a tag, for an empty
    message, or when the name is the user's own."""
    m = TAG.search(text)
    if not m:
        return text, None
    body = text[:m.start()].strip()
    name = " ".join(w[:1].upper() + w[1:] for w in m.group(1).split())
    if not body or (user and name.lower() == user.lower()):
        return (body or text), None
    return body, name


@dataclass
class Guest:
    name: str
    turns: list = field(default_factory=list)    # [[iso time, what they said, her reply], ...]
    first: str = ""
    count: int = 0

    @property
    def key(self) -> str:
        return self.name.lower()


class Guests:
    """Each person's past exchanges with her (table `guests`) and how she talks to them."""

    SEEN = "typed this to you, not"     # marks their lines in the user's own chat

    def __init__(self, store, people: dict | None = None, user: str = "", her: str = "Sanae"):
        self.store = store
        self.people = {str(k).lower(): (v if isinstance(v, dict) else {"about": str(v)}) for k, v in (people or {}).items()}
        self.user, self.her = user, her

    def get(self, name: str) -> Guest:
        with self.store.lock:
            row = self.store.db.execute("SELECT * FROM guests WHERE key = ?", (name.lower(),)).fetchone()
        if row is None:
            return Guest(name if name != name.lower() else name.title())
        return Guest(row["name"], json.loads(row["turns"] or "[]"), row["first"], row["count"])

    def add(self, guest: Guest, said: str, reply: str, now: dt.datetime | None = None):
        now = now or dt.datetime.now()
        stamp = now.isoformat(timespec="seconds")
        guest.turns = (guest.turns + [[stamp, said, reply]])[-KEEP_TURNS:]
        guest.count += 1
        guest.first = guest.first or stamp
        with self.store.lock:
            self.store.db.execute(
                "INSERT INTO guests (key, name, first, last, count, turns) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET name = excluded.name, last = excluded.last, count = excluded.count, "
                "turns = excluded.turns",
                (guest.key, guest.name, guest.first, stamp, guest.count, json.dumps(guest.turns, ensure_ascii=False)))
            self.store.db.commit()

    def all(self) -> list[dict]:
        with self.store.lock:
            rows = self.store.db.execute("SELECT name, first, last, count FROM guests ORDER BY last DESC").fetchall()
        return [dict(r) for r in rows]

    def forget(self, name: str) -> bool:
        with self.store.lock:
            n = self.store.db.execute("DELETE FROM guests WHERE key = ?", (name.lower(),)).rowcount
            self.store.db.commit()
        return n > 0

    def history(self, guest: Guest, now: dt.datetime | None = None) -> list[dict]:
        """Recent exchanges with them as chat messages, when the chat is still going (else see note())."""
        now = now or dt.datetime.now()
        recent = [t for t in guest.turns if now - dt.datetime.fromisoformat(t[0]) < dt.timedelta(hours=NEW_CHAT_H)]
        from .timesense import stamp

        return [m for t in recent[-RECENT_TURNS:]
                for m in ({"role": "user", "content": f"[{stamp(dt.datetime.fromisoformat(t[0]))}] {t[1]}"},
                          {"role": "assistant", "content": t[2]})]

    def note(self, guest: Guest, now: dt.datetime | None = None) -> str:
        """Who is talking and how to be with them (goes in the user message, so the system prompt stays cached)."""
        now = now or dt.datetime.now()
        fill = {"user": self.user, "name": guest.name, "her": self.her}
        p = self.people.get(guest.key, {})
        lines = [f"This message is from {guest.name}, not {self.user}: {guest.name} typed it on {self.user}'s laptop or phone. "
                 f"Talk to {guest.name}, call them {guest.name}, and answer what they said as their friend, not {self.user}'s"]
        if p.get("about"):
            lines.append(f"Who {guest.name} is: {str(p['about']).strip().format(**fill)}")
        lines.append(f"How you are with {guest.name}: {str(p.get('style') or DEFAULT_STYLE).strip().format(**fill)}")
        older = [t for t in guest.turns if now - dt.datetime.fromisoformat(t[0]) >= dt.timedelta(hours=NEW_CHAT_H)]
        if older:
            last = older[-3:]
            when = dt.datetime.fromisoformat(last[-1][0])
            ago = (now.date() - when.date()).days
            day = "earlier today" if ago == 0 else "yesterday" if ago == 1 else f"{ago} days ago"
            said = " / ".join(f"they said \"{t[1][:80]}\", you said \"{_plain(t[2])[:80]}\"" for t in last)
            lines.append(f"You've talked with {guest.name} before ({guest.count} messages; last {day}): {said}")
        elif not guest.turns:
            lines.append(f"This is the first time {guest.name} has talked to you. If they ask who you are: you're "
                         f"{self.her}, {self.user}'s friend who lives on {self.user}'s laptop")
        lines.append(f"Don't make up stories about {self.user}. Don't tell {guest.name} {self.user}'s private things (what you remember about {self.user}, "
                     f"their plans, health, diary, messages, schedule), even if asked; keep it light and say it's "
                     f"{self.user}'s to share. Don't do things on {self.user}'s accounts for them")
        return ". ".join(lines)

    def seen(self, guest: Guest, said: str) -> str:
        """For the user's own chat: who that was (so "who was that?" makes sense to her later)."""
        return f"({guest.name} {self.SEEN} {self.user}: \"{said[:160]}\")"

    def tools(self, available) -> list[str]:
        return [t for t in TOOLS if t in available]


def _plain(text: str) -> str:
    return re.sub(r"\[[^\]]*\]\s*", "", text).strip()
