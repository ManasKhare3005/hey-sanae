"""She asks for small things too, so it isn't only you asking her.

Every few days (at the laptop, or as a text on the phone when you're away) she asks for one little
thing, and remembers what you gave her:
  - "send me a picture of the sky where you are" -> your next photo (within a day) is her sky;
  - "pick a song for me today" -> what you answer; she "listens" (the artist joins her music) and
    tells you the next day she kept it on;
  - "what should I draw next?" -> she draws it (drawings.py) if she can, else she says she'll try;
  - "tell me one good thing from your day" -> she keeps it;
  - "teach me a word I don't know" -> she keeps it and tries using it.
Your answers are recognised in code (the reply right after she asks; a photo for the sky). What
you gave her is kept in the gifts table and shown on the phone ("From you").
"""
from __future__ import annotations

import datetime as dt
import random
import re
import time

from .initiative import Moment
from .part import Part, in_hours

SCHEMA = """
CREATE TABLE IF NOT EXISTS gifts (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL, day TEXT NOT NULL, drawing INTEGER NOT NULL DEFAULT 0);
"""
ASKS = {
    "sky": ("Ask {user}, a little shyly, to send you a photo of the sky wherever they are right now (you can't see "
            "outside). One line.", ("09:00", "18:30")),
    "song": ("Ask {user} to pick a song for you today, any song they like, so you can listen to it. One playful line.",
             ("11:00", "22:00")),
    "draw": ("You're practising drawing. Ask {user} what you should draw next. One line.", ("10:00", "22:00")),
    "good": ("Ask {user} to tell you one good thing from their day, even a tiny one. One warm line.", ("17:00", "22:30")),
    "word": ("Ask {user} to teach you a word you probably don't know (any language, slang, a big word). One line.",
             ("11:00", "22:00")),
}
EVERY_S = 2 * 86400
ANSWER_S = 15 * 60
SKY_S = 24 * 3600
NOT_AN_ANSWER = re.compile(r"\b(not now|later|no+pe?|can'?t|busy|nah|maybe later|skip)\b", re.I)
SONG = re.compile(r"(?:(?:listen to|try|play|pick|picking|it'?s|go with|how about)\s+)?[\"“]?(?P<title>[^\"”]+?)[\"”]?"
                  r"(?:\s+(?:by|from)\s+(?P<artist>[^.,!?]+))?\W*$", re.I)


class Asks(Part):
    name = "asks"

    def __init__(self, store=None, clock=time.time, idle=lambda: 0.0, life=None, drawings=None, vision=None, rng=None):
        super().__init__(store, clock)
        self.idle, self.life, self.drawings, self.vision = idle, life, drawings, vision
        self.rng = rng or random.Random()
        self._schema(SCHEMA)

    def gifts(self, n: int = 20) -> list[dict]:
        return self._rows("SELECT * FROM gifts ORDER BY id DESC LIMIT ?", (n,))

    def _gift(self, kind: str, text: str, drawing: int = 0) -> dict:
        cur = self._exec("INSERT INTO gifts (kind, text, day, drawing) VALUES (?,?,?,?)",
                         (kind, " ".join(text.split())[:200], self.today(), drawing))
        return self._rows("SELECT * FROM gifts WHERE id = ?", (cur.lastrowid,))[0]

    # ----- asking -----
    def _pick(self, d: dt.datetime) -> str | None:
        recent = self.get("recent", [])
        kinds = [k for k, (_, hours) in ASKS.items() if in_hours(d, *hours) and k not in recent[-3:]]
        return self.rng.choice(kinds) if kinds else None

    def _moment(self, now: float, phone: bool) -> list[Moment]:
        if self.store is None or self.get("pending"):
            p = self.get("pending")
            if p and now - p["t"] > (SKY_S if p["kind"] == "sky" else ANSWER_S):
                self.put("pending", None)
            return []
        if now - self.get("last", 0) < EVERY_S:
            return []
        if not phone and (self.idle() > 120 or self.rng.random() > 0.05):
            return []
        d = dt.datetime.fromtimestamp(now)
        kind = self._pick(d)
        if kind is None:
            return []
        return [Moment("ask", ASKS[kind][0], key=f"ask:{kind}:{d.date().isoformat()}", part=self.name)]

    def moments(self, now: float) -> list[Moment]:
        out = self._moment(now, phone=False)
        out += self._follow_up(now)
        return out

    def phone_moments(self, now: float) -> list[Moment]:
        return self._moment(now, phone=True)

    def _follow_up(self, now: float) -> list[Moment]:
        """The day after they picked her a song: she kept it on."""
        d = dt.datetime.fromtimestamp(now)
        yday = (d - dt.timedelta(days=1)).date().isoformat()
        for g in self.gifts(5):
            if g["kind"] == "song" and g["day"] == yday and not self.done(f"song:{g['id']}") and self.idle() < 120 \
                    and 10 <= d.hour < 22:
                return [Moment("ask", f"Yesterday {{user}} picked a song for you: {g['text']}. Tell them you kept it on "
                                      "and liked it; only the title and artist, don't invent lyrics or details. One line.",
                               key=f"song:{g['id']}", part=self.name)]
        return []

    def used(self, moment, now: float):
        if moment.key:
            self.once(moment.key)
        if moment.key.startswith("ask:"):
            kind = moment.key.split(":")[1]
            self.put("pending", {"kind": kind, "t": now})
            self.put("last", now)
            self.put("recent", [*self.get("recent", []), kind][-5:])

    # ----- their answer -----
    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        p = self.get("pending")
        if self.store is None or not p:
            return []
        from .vision import PHOTO_TAG

        now = self.clock()
        kind = p["kind"]
        if kind == "sky":
            if not user_text.startswith(PHOTO_TAG) or now - p["t"] > SKY_S:
                return []
            seen = getattr(self.vision, "last", None)
            what = seen.description[:200] if seen is not None else "the sky where they are"
            self.put("pending", None)
            self._gift("sky", what)
            return [f"They sent the sky photo you asked for! It shows: {what}. Be delighted (you can't see outside), thank "
                    "them, say something about it. Short"]
        text = user_text.strip()
        if now - p["t"] > ANSWER_S:
            self.put("pending", None)
            return []
        if user_text.startswith(PHOTO_TAG):
            return []
        if NOT_AN_ANSWER.search(text) and len(text.split()) <= 4:     # "not now": she lets it go
            self.put("pending", None)
            return []
        if text.endswith("?") and len(text.split()) > 3:
            return []
        self.put("pending", None)
        if kind == "song":
            m = SONG.search(text)
            title = (m.group("title") if m else text).strip(" .!")
            artist = (m.group("artist") or "").strip() if m else ""
            label = f"\"{title}\"" + (f" by {artist}" if artist else "")
            self._gift("song", label)
            if artist and self.life is not None and hasattr(self.life, "heard_artist"):
                self.life.heard_artist(artist)
            return [f"They picked a song for you: {label}. Thank them, excited to listen to it later; don't pretend you "
                    "know its lyrics. Short"]
        if kind == "draw":
            from .drawings import subject_for

            subject = subject_for(text)
            if subject and self.drawings is not None:
                d = self.drawings.draw(subject, why="ask", title=text.strip(" .!")[:60])
                self._gift("draw", text, d["id"])
                return [f"They told you to draw: \"{text}\". You did, right away (it's in your sketchbook on their phone, "
                        "a bit wobbly). Tell them, a little shy. Short"]
            self._gift("draw", text)
            return [f"They told you to draw: \"{text}\". That's hard for you right now, but say you'll try it, playfully. Short"]
        if kind == "good":
            self._gift("good", text)
            return ["They told you one good thing from their day. Be glad with them, and say you'll keep it. Short"]
        if kind == "word":
            self._gift("word", text)
            return ["They taught you a word. Repeat it back, try using it in a sentence, playfully. Short"]
        return []

    def status(self) -> dict:
        out = []
        for g in self.gifts(20):
            item = {"id": g["id"], "kind": g["kind"], "text": g["text"], "day": g["day"]}
            if g["drawing"] and self.drawings is not None:
                d = self.drawings.get_one(g["drawing"])
                if d is not None:
                    item["drawing"] = d
            out.append(item)
        p = self.get("pending")
        return {"gifts": out, "waiting": p["kind"] if p else None}
