"""A shared bucket list: things you want to try, kept together.

  - "Add watching the sunrise from a hill to our bucket list", or the phone (Us tab).
  - She suggests one when your weekend is free (weekend.py asks her for an idea).
  - Did one? "We finally did the sunrise hike!" (or tick it on the phone, or send a photo of it and
    mention it): she celebrates, ticks it off, and draws a little sketch of it for the list.
  - Once the list has a few of yours she adds one of her own (she lives on the laptop, so hers are
    things you'd do for her: "send me a photo from somewhere you've never been").
"""
from __future__ import annotations

import datetime as dt
import random
import re
import time

from .goals import mentions
from .initiative import Moment
from .part import Part

SCHEMA = """
CREATE TABLE IF NOT EXISTS bucket (
    id INTEGER PRIMARY KEY, text TEXT NOT NULL, who TEXT NOT NULL DEFAULT 'you', added TEXT NOT NULL,
    done_day TEXT NOT NULL DEFAULT '', drawing INTEGER NOT NULL DEFAULT 0, photo INTEGER NOT NULL DEFAULT 0);
"""
HER_IDEAS = ["send me a photo from somewhere you've never been", "watch a sunrise and tell me the colours",
             "show me the ocean (a photo counts)", "cook something you've never cooked, with me",
             "learn ten Japanese words with me", "stargaze somewhere dark and tell me what you saw",
             "take me to a museum (photos, please)", "try a food you've never had and describe it to me"]
_OUR = r"(?:my|our|the)"
B_ADD = re.compile(rf"\b(?:add|put)\s+(?P<what>.+?)\s+(?:to|on)\s+{_OUR}\s+bucket ?list\W*$"
                   rf"|^\W*{_OUR}?\s*bucket ?list\s*[:,-]\s*(?:add\s+)?(?P<what2>.+?)\W*$", re.I)
B_SHOW = re.compile(rf"^\W*(?:what'?s|what is|show(?: me)?|read(?: me)?|tell me)\s+(?:on |in )?{_OUR}\s+bucket ?list\W*$"
                    rf"|^\W*{_OUR}\s+bucket ?list\W*$", re.I)
B_DROP = re.compile(rf"\b(?:take|remove|delete|drop|cross)\s+(?P<what>.+?)\s+(?:off|from)\s+{_OUR}\s+bucket ?list\W*$", re.I)
DONE = re.compile(r"\b(we did it|finally did|we did|i did|did the|went to|finished|crossed (it )?off|ticked (it )?off|"
                  r"checked (it )?off|made it to|got to|tried|watched the|saw the|climbed|visited)\b", re.I)


class Bucket(Part):
    name = "bucket"

    def __init__(self, store=None, clock=time.time, drawings=None, idle=lambda: 0.0, rng=None):
        super().__init__(store, clock)
        self.drawings, self.idle = drawings, idle
        self.rng = rng or random.Random()
        self._schema(SCHEMA)

    def items(self, open_only: bool = False) -> list[dict]:
        where = "WHERE done_day = ''" if open_only else ""
        return self._rows(f"SELECT * FROM bucket {where} ORDER BY CASE WHEN done_day = '' THEN 0 ELSE 1 END, id")

    def get_one(self, bid) -> dict | None:
        rows = self._rows("SELECT * FROM bucket WHERE id = ?", (int(bid),))
        return rows[0] if rows else None

    def add(self, text: str, who: str = "you") -> dict:
        text = re.sub(r"\s+", " ", text or "").strip(" .,!")
        text = re.sub(r"^(?:to|that we|we|i)\s+", "", text, flags=re.I)[:100]
        if not text:
            raise ValueError("what should go on the bucket list?")
        for b in self.items():
            if b["text"].lower() == text.lower():
                return b
        cur = self._exec("INSERT INTO bucket (text, who, added) VALUES (?,?,?)", (text, who, self.today()))
        return self.get_one(cur.lastrowid)

    def find(self, said: str, open_only: bool = True) -> dict | None:
        for b in self.items(open_only):
            if mentions(b["text"], said):
                return b
        return None

    def remove(self, bid) -> dict | None:
        b = self.get_one(bid)
        if b is not None:
            self._exec("DELETE FROM bucket WHERE id = ?", (b["id"],))
        return b

    def mark_done(self, bid, day: str | None = None, photo: int = 0) -> dict | None:
        b = self.get_one(bid)
        if b is None:
            return None
        drawing = b["drawing"]
        if not b["done_day"] and self.drawings is not None and not drawing:
            try:
                from .drawings import subject_for

                d = self.drawings.draw(subject_for(b["text"]) or "a star", why=f"bucket:{b['id']}", title=b["text"])
                drawing = d["id"]
            except Exception:
                drawing = 0
        self._exec("UPDATE bucket SET done_day = ?, drawing = ?, photo = CASE WHEN ? > 0 THEN ? ELSE photo END WHERE id = ?",
                   (day or self.today(), drawing, photo, photo, b["id"]))
        return self.get_one(b["id"])

    def undo(self, bid) -> dict | None:
        self._exec("UPDATE bucket SET done_day = '' WHERE id = ?", (int(bid),))
        return self.get_one(bid)

    def suggest(self) -> str | None:
        """One open item that hasn't been suggested in the last three weeks."""
        recent = self.get("suggested", {})
        cutoff = (self.now() - dt.timedelta(days=21)).date().isoformat()
        fresh = [b for b in self.items(True) if recent.get(str(b["id"]), "") < cutoff]
        if not fresh:
            return None
        b = self.rng.choice(fresh)
        recent[str(b["id"])] = self.today()
        self.put("suggested", recent)
        return b["text"]

    def spoken(self) -> str:
        items = self.items(True)
        done = [b for b in self.items() if b["done_day"]]
        if not items and not done:
            return "Our bucket list is empty! What's something you've always wanted to do?"
        out = ("On our bucket list: " + "; ".join(b["text"] for b in items) + ".") if items else "Everything on our list is done!"
        if done:
            out += f" Done so far: {len(done)}."
        return out

    # ----- in conversation -----
    def route(self, user_text: str, last_reply: str = "") -> tuple[str, dict] | None:
        t = user_text.strip()
        if B_SHOW.search(t):
            return "bucket_list", {}
        if m := B_ADD.search(t):
            return "add_to_bucket_list", {"what": (m.group("what") or m.group("what2")).strip()}
        if m := B_DROP.search(t):
            return "drop_from_bucket_list", {"what": m.group("what").strip()}
        return None

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        if self.store is None or not DONE.search(user_text) or re.search(r"\b(didn'?t|never|not yet|someday|want to)\b", user_text, re.I):
            return []
        b = self.find(user_text)
        if b is None:
            return []
        from .vision import PHOTO_TAG

        b = self.mark_done(b["id"])
        sketch = " You drew a little sketch of it for the list (it's on their phone)." if b["drawing"] else ""
        photo = " They sent a photo of it." if user_text.startswith(PHOTO_TAG) else ""
        return [f"They did \"{b['text']}\" from your shared bucket list! It's ticked off.{photo}{sketch} Celebrate with "
                "them and ask how it was, excited, short"]

    def moments(self, now: float) -> list[Moment]:
        if self.store is None:
            return []
        mine = [b for b in self.items() if b["who"] == "you"]
        hers = [b for b in self.items() if b["who"] == "her"]
        month = dt.datetime.fromtimestamp(now).strftime("%Y-%m")
        if len(mine) >= 3 and len(hers) < len(HER_IDEAS) and not self.done_key(f"hers:{month}") and self.idle() < 120:
            have = {b["text"] for b in hers}
            idea = next((i for i in HER_IDEAS if i not in have), None)
            if idea:
                return [Moment("bucket", f"You just added one of your own to your shared bucket list: \"{idea}\". Tell "
                                         "{user}, a little shy, one line.", key=f"hers:{month}:{idea}", part=self.name)]
        return []

    def done_key(self, prefix: str) -> bool:
        return any(k.startswith(prefix) for k in self.get("once", []))

    def used(self, moment, now: float):
        if moment.key:
            self.once(moment.key)
        if moment.key.startswith("hers:"):
            self.add(moment.key.split(":", 2)[2], who="her")

    def status(self) -> dict:
        out = []
        for b in self.items():
            item = {"id": b["id"], "text": b["text"], "who": b["who"], "done_day": b["done_day"] or None}
            if b["drawing"] and self.drawings is not None:
                item["drawing"] = self.drawings.get_one(b["drawing"])
            out.append(item)
        return {"items": out}
