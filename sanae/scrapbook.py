"""Our scrapbook: photos you send her, kept only when you say so, with her caption (and sometimes her
sketch of it), a page per month.

  - Photos are never kept by default (vision.py holds the last one in memory for a few minutes).
    It goes in the scrapbook only if you say yes: the phone's Keep toggle when you send it, or
    "keep that one" / "put it in our scrapbook" (or "yes" when she asks) within a few minutes.
  - She writes a one-line caption from what she saw; if she can draw it (a mug, the sky, ramen...)
    she adds a little sketch (drawings.py).
  - A photo of something on your bucket list ticks it off (bucket.py).
  - The week in review gets the week's photos; the phone shows a page per month.

The kept copy is the re-encoded one (no EXIF/GPS), under data/scrapbook/<id>.jpg; deleting a photo
deletes the file, and "forget what you learned about me" clears the folder.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import time
from pathlib import Path

from .part import Part

log = logging.getLogger(__name__)
SCHEMA = """
CREATE TABLE IF NOT EXISTS scrapbook (
    id INTEGER PRIMARY KEY, file TEXT NOT NULL, caption TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    day TEXT NOT NULL, drawing INTEGER NOT NULL DEFAULT 0, bucket INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);
"""
CAPTION_PROMPT = (
    "You are {her}. {user} sent you this photo and asked you to keep it in your shared scrapbook. What it shows: "
    "{description}\n{said}"
    "Write the caption for the scrapbook page: one short, warm line in your voice (under 14 words), like a friend "
    "writing under a photo. No quotes, no emojis, no hashtags, no numbers that aren't above."
)
KEEP = re.compile(r"\b(keep (that|this|it)( one| photo| picture| pic)?|save (that|this|it)( one| photo| picture)?|"
                  r"(put|add|stick) (that|this|it)( one| photo| picture)? (in|into|to) (our|the|my) scrap ?book|"
                  r"scrap ?book (it|that|this))\b", re.I)
YES = re.compile(r"^\W*(yes|yeah|yep|sure|please|ok(ay)?|of course|definitely|do it|keep it)\b", re.I)
WORTH = re.compile(r"\b(screenshot|receipt|document|form|flyer|poster|syllabus|invoice|bill|fridge|label|error|code|"
                   r"text message|email|menu)\b", re.I)


class Scrapbook(Part):
    name = "scrapbook"

    def __init__(self, store=None, clock=time.time, vision=None, drawings=None, bucket=None, llm=None, model: str = "",
                 user: str = "them", her: str = "Sanae", folder: str | Path = "data/scrapbook", publish=lambda k, d: None):
        super().__init__(store, clock)
        self.vision, self.drawings, self.bucket = vision, drawings, bucket
        self.llm, self.model, self.user, self.her = llm, model, user, her
        if not Path(folder).is_absolute():
            from .config import resolve_path

            folder = resolve_path(str(folder))
        self.folder = Path(folder)
        self.publish = publish
        self.daily = None                    # dailyphoto.py: today's photo is kept by it, no "want to keep it?"
        self._schema(SCHEMA)

    # ----- keeping one -----
    def fresh(self):
        """The photo she just looked at, if it's still in memory (vision.py, a few minutes)."""
        s = getattr(self.vision, "last", None) if self.vision is not None else None
        if s is None or not getattr(s, "jpeg", b"") or self.clock() - s.at > getattr(self.vision, "remember_s", 600):
            return None
        return s

    def caption(self, description: str, said: str) -> str:
        fallback = re.split(r"(?<=[.!?])\s+", description.strip())[0][:90]
        if self.llm is None:
            return fallback
        from .agent import strip_thinking
        from .tags import ASIDE, EMOJI, TAG

        allowed = set(re.findall(r"\d+", description + said))
        try:
            raw = self.llm.chat(self.model, [{"role": "user", "content": CAPTION_PROMPT.format(
                her=self.her, user=self.user, description=description[:600],
                said=f"They said: \"{said}\"\n" if said else "")}], options={"temperature": 0.7, "num_predict": 40}).content
        except Exception as exc:
            log.info("scrapbook: caption failed: %s", exc)
            return fallback
        line = " ".join(EMOJI.sub("", ASIDE.sub("", TAG.sub("", strip_thinking(raw)))).split()).strip().strip('"')
        if not (2 <= len(line.split()) <= 18) or set(re.findall(r"\d+", line)) - allowed:
            return fallback
        return line

    def keep(self, said: str = "") -> dict | None:
        s = self.fresh()
        if s is None:
            return None
        if self.store is not None:
            same = self._rows("SELECT id FROM scrapbook WHERE created = ?", (dt.datetime.fromtimestamp(s.at).isoformat(timespec="seconds"),))
            if same:
                return self.get_one(same[0]["id"])
        question = s.question if s.question and "What's in it?" not in s.question else ""
        cap = self.caption(s.description, " ".join(x for x in (question, said) if x))
        self.folder.mkdir(parents=True, exist_ok=True)
        cur = self._exec("INSERT INTO scrapbook (file, caption, description, day, created) VALUES (?,?,?,?,?)",
                         ("", cap, s.description[:800], self.today(), dt.datetime.fromtimestamp(s.at).isoformat(timespec="seconds")))
        pid = cur.lastrowid
        path = self.folder / f"{pid}.jpg"
        path.write_bytes(s.jpeg)
        drawing = 0
        if self.drawings is not None:
            from .drawings import subject_for

            subject = subject_for(f"{question} {s.description}")
            if subject:
                try:
                    drawing = self.drawings.draw(subject, why=f"scrapbook:{pid}", title=subject)["id"]
                except Exception:
                    drawing = 0
        bucket = 0
        if self.bucket is not None:
            b = self.bucket.find(f"{question} {said}") if (question or said) else None
            if b is not None:
                self.bucket.mark_done(b["id"], photo=pid)
                bucket = b["id"]
        self._exec("UPDATE scrapbook SET file = ?, drawing = ?, bucket = ? WHERE id = ?", (str(path), drawing, bucket, pid))
        self.publish("us", {"what": "scrapbook", "action": "kept", "id": pid})
        return self.get_one(pid)

    def get_one(self, pid: int) -> dict | None:
        rows = self._rows("SELECT * FROM scrapbook WHERE id = ?", (int(pid),))
        return rows[0] if rows else None

    def delete(self, pid: int) -> bool:
        p = self.get_one(pid)
        if p is None:
            return False
        Path(p["file"]).unlink(missing_ok=True)
        self._exec("DELETE FROM scrapbook WHERE id = ?", (int(pid),))
        return True

    def between(self, start: dt.date, end: dt.date) -> list[dict]:
        return self._rows("SELECT * FROM scrapbook WHERE day >= ? AND day <= ? ORDER BY id", (start.isoformat(), end.isoformat()))

    # ----- in conversation -----
    def route(self, user_text: str, last_reply: str = "") -> tuple[str, dict] | None:
        if self.fresh() is None:
            return None
        if KEEP.search(user_text) or ("scrapbook" in (last_reply or "").lower() and YES.search(user_text)):
            return "keep_photo", {}
        return None

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        from .vision import PHOTO_TAG

        if not user_text.startswith(PHOTO_TAG) or self.fresh() is None or self.store is None:
            return []
        s = self.fresh()
        if self.daily is not None and (self.daily.counts(user_text) or self.daily.get("claimed") == s.at):
            return []
        if WORTH.search(f"{user_text} {s.description}") or self.get("asked_day") == self.today():
            return []
        self.put("asked_day", self.today())
        return ["If this photo feels like a moment worth remembering, you can ask (once, at the end) if they want it in "
                "your scrapbook. It's only kept if they say yes"]

    # ----- for the phone -----
    def status(self) -> dict:
        months: dict[str, list] = {}
        for r in self._rows("SELECT * FROM scrapbook ORDER BY id DESC LIMIT 120"):
            item = {"id": r["id"], "caption": r["caption"], "day": r["day"], "bucket": r["bucket"]}
            if r["drawing"] and self.drawings is not None:
                d = self.drawings.get_one(r["drawing"])
                if d is not None:
                    item["drawing"] = d
            months.setdefault(r["day"][:7], []).append(item)
        return {"months": [{"month": m, "label": dt.date.fromisoformat(m + "-01").strftime("%B %Y"), "photos": items}
                           for m, items in months.items()]}
