"""A bedtime story serial: ask for a story and she tells you the next chapter, about two minutes,
in her soft night voice. It carries on night after night.

  - The first time, she sets up the story's world once: a cosy place (picked here) and characters
    taken from your inside jokes and nicknames (diary moments), plus you; kept in kv so every
    chapter is the same story.
  - Each chapter is written by the model from the story so far (each earlier chapter is kept as a
    two-sentence summary), gentle and sleepy, ending softly rather than on a cliffhanger.
  - "Read last night's again" repeats the last chapter. The phone keeps every chapter to read or
    listen to (her voice, made on first play).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import random
import re
import time
from pathlib import Path

from .part import Part

log = logging.getLogger(__name__)
SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    id INTEGER PRIMARY KEY, n INTEGER NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL, summary TEXT NOT NULL,
    day TEXT NOT NULL, created TEXT NOT NULL);
"""
PLACES = ["a floating library that drifts above a sleepy sea", "a little train that runs between the stars at night",
          "a lantern-lit forest where the trees hum when it rains", "a tiny seaside town where the lighthouse keeper is a cat",
          "a bakery on the moon that only opens after midnight", "a snowy mountain inn where lost letters arrive by owl"]
STORY = re.compile(r"\b(tell me a (bedtime |little |short )?story|bedtime story|story time|read me (a|the|our) story|"
                   r"(continue|next chapter of|keep going with) (the |our )?story|what happens next in (the |our )?story|"
                   r"another (chapter|story))\b", re.I)
AGAIN = re.compile(r"\b((read|tell) (me )?(last night'?s|the last|that) (story|chapter) again|repeat (the|last) (story|chapter))\b", re.I)
PROMPT = (
    "You are {her}, telling {user} the next chapter of your bedtime story serial, out loud, in a soft sleepy voice.\n"
    "The story's world: {place}.\nThe characters: {cast}.\n{sofar}\n"
    "Write chapter {n}: about 250 words, simple spoken sentences (it will be read aloud), cosy and gentle, a small "
    "adventure or a warm moment, nothing scary, no real-life worries, and end softly and sleepily (not a cliffhanger). "
    "Continue the same story and characters. {user} uses they/them: always \"they\", \"them\", \"their\" for {user}, "
    "never he or she. Start straight with the story (no greeting). No lists, no markdown, no emojis.\n"
    "Return JSON: title (a few words), text (the chapter), summary (two sentences of what happened, for next time)."
)
SCHEMA_OUT = {"type": "object", "properties": {"title": {"type": "string"}, "text": {"type": "string"},
                                               "summary": {"type": "string"}}, "required": ["title", "text", "summary"]}


class Stories(Part):
    name = "stories"

    def __init__(self, store=None, clock=time.time, llm=None, model: str = "", user: str = "them", her: str = "Sanae",
                 diary=None, rng=None, folder: str | Path = "data/stories"):
        super().__init__(store, clock)
        self.llm, self.model, self.user, self.her, self.diary = llm, model, user, her, diary
        self.rng = rng or random.Random()
        if not Path(folder).is_absolute():
            from .config import resolve_path

            folder = resolve_path(str(folder))
        self.folder = Path(folder)
        self._schema(SCHEMA)

    def bible(self) -> dict:
        b = self.get("bible")
        if b:
            return b
        cast = [f"{self.user} (the hero; gentle, curious, a little sleepy)"]
        moments = []
        if self.diary is not None:
            try:
                moments = [m for m in self.diary.moments() if m.kind in ("nickname", "joke")]
            except Exception:
                moments = []
        for m in moments[:2]:
            text = m.text.strip()
            if m.kind == "nickname":
                cast.append(f"{text} (a character named after {self.user}'s nickname; kind and funny)")
            else:
                cast.append(f"a small character inspired by your running joke \"{text}\"")
        cast.append(f"a quiet narrator who is you, {self.her}, sometimes peeking into the story")
        b = {"place": self.rng.choice(PLACES), "cast": cast}
        self.put("bible", b)
        return b

    def chapters(self) -> list[dict]:
        return self._rows("SELECT * FROM stories ORDER BY n")

    def write(self) -> dict | None:
        if self.llm is None:
            return None
        b = self.bible()
        done = self.chapters()
        n = len(done) + 1
        sofar = ("The story so far:\n" + "\n".join(f"Chapter {c['n']} ({c['title']}): {c['summary']}" for c in done[-6:])
                 if done else "This is the very first chapter: introduce the place and the characters.")
        from .agent import strip_thinking
        from .tags import ASIDE, EMOJI, TAG

        for attempt in range(2):
            try:
                raw = self.llm.chat(self.model, [{"role": "user", "content": PROMPT.format(
                    her=self.her, user=self.user, place=b["place"], cast="; ".join(b["cast"]), sofar=sofar, n=n)}],
                    options={"temperature": 0.8, "num_predict": 900}, fmt=SCHEMA_OUT).content
                data = json.loads(strip_thinking(raw))
            except Exception as exc:
                log.info("stories: chapter failed: %s", exc)
                continue
            text = " ".join(EMOJI.sub("", ASIDE.sub("", TAG.sub("", str(data.get("text", ""))))).split())
            if 120 <= len(text.split()) <= 450:
                title = " ".join(str(data.get("title") or f"Chapter {n}").split())[:60]
                summary = " ".join(str(data.get("summary") or text[:200]).split())[:400]
                cur = self._exec("INSERT INTO stories (n, title, text, summary, day, created) VALUES (?,?,?,?,?,?)",
                                 (n, title, text, summary, self.today(), self.now().isoformat(timespec="seconds")))
                return self.get_one(cur.lastrowid)
            log.info("stories: chapter dropped (%d words)", len(text.split()))
        return None

    def get_one(self, sid: int) -> dict | None:
        rows = self._rows("SELECT * FROM stories WHERE id = ?", (int(sid),))
        return rows[0] if rows else None

    def tell(self, again: bool = False) -> str:
        if again:
            done = self.chapters()
            if not done:
                return "We haven't started our story yet. Want me to begin it?"
            c = done[-1]
        else:
            c = self.write()
            if c is None:
                return "Mm, my head's too sleepy for a story right now. Ask me again in a bit?"
        return f"Chapter {c['n']}: {c['title']}. {c['text']}"

    def route(self, user_text: str, last_reply: str = "") -> tuple[str, dict] | None:
        if AGAIN.search(user_text):
            return "bedtime_story", {"again": True}
        if STORY.search(user_text) and not re.search(r"\b(about (the|my|your) (day|life)|joke)\b", user_text, re.I):
            return "bedtime_story", {"again": False}
        if "story" in (last_reply or "").lower() and re.match(r"(?i)\W*(yes|yeah|yep|sure|please|ok(ay)?|mhm)\b", user_text):
            return "bedtime_story", {"again": False}
        return None

    def audio_file(self, sid: int) -> Path:
        return self.folder / f"{int(sid)}.wav"

    def status(self) -> dict:
        b = self.get("bible") or {}
        return {"place": b.get("place"), "chapters": [{"id": c["id"], "n": c["n"], "title": c["title"], "text": c["text"],
                                                        "day": c["day"]} for c in reversed(self.chapters()[-30:])]}
