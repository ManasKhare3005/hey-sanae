"""The exchange diary (kōkan nikki): one notebook you two take turns writing in.

  - You write a page on the phone (typed, or spoken on the walk home: the laptop transcribes it),
    with a mood and optionally marked private (she still reads and answers it, but never brings it
    up in chat).
  - The next morning her page is waiting: it answers yours specifically, tells you a bit of her
    day (herlife.py: what she's learning, her word of the day) and asks you one thing.
  - Now and then she notices a pattern across your pages and says it gently ("you always sound
    lighter on days you mention Maya"): worked out in code from your moods and the names / things
    that come up, never made up by the model.
  - A letter to future you: sealed, and handed back in 3 or 6 months.
  - In chat (laptop or phone) she knows your latest page and can bring it up, once.

Days run 4 AM to 4 AM, like her own diary.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY, uid TEXT NOT NULL, day TEXT NOT NULL, author TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'page',
    text TEXT NOT NULL, mood TEXT NOT NULL DEFAULT '', private INTEGER NOT NULL DEFAULT 0, voice INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL, reply_to INTEGER, deliver_on TEXT NOT NULL DEFAULT '', delivered INTEGER NOT NULL DEFAULT 0);
"""
MOODS = {"😄": 2, "🥰": 2, "🙂": 1, "😌": 1, "😐": 0, "😴": -0.5, "😕": -1, "😤": -1, "😢": -2, "😞": -2}
THINGS = ("gym", "run", "walk", "workout", "class", "work", "family", "friends", "game", "valorant", "code", "coding",
          "reading", "cook", "date", "music", "outside", "sleep")
NOTE_PROMPT = (
    "You are {her}, writing your page in an exchange diary (a kōkan nikki) that you share with your friend {user}. "
    "You take turns: they wrote, now it's your turn. You live on their laptop: you can't eat, go out or meet people, "
    "and you have no family. What happened in their page happened to THEM, not to you.\n\n"
    "Their page{s}:\n{pages}\n\n"
    "Your own life lately (the only things that happened to you): {life}\n{pattern}"
    "Write your page, {words} words, warm and casual, like a real friend's diary page, in three parts:\n"
    "1. Talk to them about their page (use \"you\"): react to one or two real details, the way a close friend would.\n"
    "2. A little of your own day, only from your life above.\n"
    "3. One question for them about their page.\n"
    "No date, no heading, no sign-off, no emojis, no lists, no numbers they didn't write. Don't invent things that "
    "happened to them, and don't give advice unless they asked for it."
)
PRONOUNS = re.compile(r"\b(he|him|his|she|her|hers)\b", re.I)


def her_day(now: dt.datetime) -> dt.date:
    """The day a page belongs to: 2 AM still counts as yesterday."""
    return (now - dt.timedelta(hours=4)).date()


def numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.:]\d+)?", text))


_WORD = re.compile(r"[a-z]{5,}")
_COMMON = set("""about after again always before being really really thing things today tonight their there these
think while would could should which where still little maybe something everything anything feels felt pretty
first ended start started finally trying tried kinda kind""".split())


def borrowed(page: str, theirs: str, life: str) -> str | None:
    """A sentence where she tells their day as her own ("Mom asked about job applications too, and I
    just said..."): first person, no "you", and a word from their page that isn't from her life."""
    theirs_w = {w[:5] for w in _WORD.findall(theirs.lower())} - {w[:5] for w in _WORD.findall(life.lower())}
    theirs_w -= {w[:5] for w in _COMMON}
    for sent in re.split(r"(?<=[.!?])\s+", page):
        low = sent.lower()
        if not re.search(r"\b(i|i'm|i've|my|me)\b", low) or re.search(r"\b(you|your|you're|you've)\b", low):
            continue
        hit = next((w for w in _WORD.findall(low) if w[:5] in theirs_w), None)
        if hit:
            return hit
    return None


class Journal:
    """The notebook. `llm` writes her pages; `life` (herlife.HerLife) is what's new with her.
    Sits with the friendship parts (part.py) for its chat notes; it has no moments of its own (her
    page reaches the phone as a notification)."""
    name = "journal"

    def __init__(self, store, llm=None, model: str = "", user: str = "them", her: str = "Sanae", life=None,
                 friend=None, clock: Callable[[], float] = time.time, can_run: Callable[[], bool] = lambda: True,
                 publish=lambda kind, data: None):
        self.store, self.llm, self.model, self.user, self.her = store, llm, model, user, her
        self.life, self.friend, self.clock, self.can_run, self.publish = life, friend, clock, can_run, publish
        self._stop = threading.Event()
        self.drawings = None                     # drawings.Drawings: her page comes with a little sketch
        with store.lock:
            store.db.executescript(SCHEMA)
            store.db.commit()

    # ----- storage -----
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

    def page(self, pid: int) -> dict | None:
        rows = self._rows("SELECT * FROM journal WHERE id = ?", (pid,))
        return rows[0] if rows else None

    def write(self, text: str, mood: str = "", private: bool = False, voice: bool = False,
              letter_months: int = 0) -> dict:
        from .reminders import new_uid

        text = text.strip()
        if not text:
            raise ValueError("an empty page")
        now = self.now()
        deliver = ""
        if letter_months:
            months = max(1, min(int(letter_months), 24))
            y, m = divmod(now.month - 1 + months, 12)
            day = min(now.day, 28)
            deliver = dt.date(now.year + y, m + 1, day).isoformat()
        since = (now - dt.timedelta(minutes=10)).isoformat(timespec="seconds")
        same = self._rows("SELECT id FROM journal WHERE author = 'you' AND text = ? AND created >= ? ORDER BY id DESC LIMIT 1",
                          (text[:6000], since))
        if same:                              # the phone sent it again (its outbox retried a slow answer)
            return self.page(same[0]["id"])
        cur = self._exec(
            "INSERT INTO journal (uid, day, author, kind, text, mood, private, voice, created, deliver_on) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (new_uid(), her_day(now).isoformat(), "you", "letter" if deliver else "page", text[:6000], mood[:8],
             int(private), int(voice), now.isoformat(timespec="seconds"), deliver))
        return self.page(cur.lastrowid)

    def set_private(self, pid: int, private: bool) -> dict | None:
        self._exec("UPDATE journal SET private = ? WHERE id = ? AND author = 'you'", (int(private), pid))
        return self.page(pid)

    def delete(self, pid: int) -> bool:
        p = self.page(pid)
        if p is None or p["author"] != "you":
            return False
        self._exec("DELETE FROM journal WHERE id = ? OR (author = 'her' AND reply_to = ?)", (pid, pid))
        return True

    def pages(self, limit: int = 40) -> list[dict]:
        """Newest first: your pages, her pages, and letters that have been handed back."""
        return self._rows("SELECT * FROM journal WHERE kind = 'page' OR delivered = 1 ORDER BY created DESC, id DESC LIMIT ?",
                          (limit,))

    def sealed(self) -> list[dict]:
        return self._rows("SELECT id, created, deliver_on FROM journal WHERE kind = 'letter' AND delivered = 0 "
                          "ORDER BY deliver_on")

    def unanswered(self) -> list[dict]:
        return self._rows("SELECT * FROM journal j WHERE author = 'you' AND kind = 'page' AND NOT EXISTS "
                          "(SELECT 1 FROM journal h WHERE h.author = 'her' AND h.reply_to >= j.id) ORDER BY id")

    def status(self) -> dict:
        def show(p: dict) -> dict:
            out = {k: p[k] for k in ("id", "uid", "day", "author", "kind", "text", "mood", "private", "voice",
                                     "created", "reply_to", "deliver_on")}
            if p["author"] == "her" and self.drawings is not None:
                d = self.drawings.for_why(f"page:{p['id']}")
                if d is not None:
                    out["drawing"] = d
            return out
        waiting = self.unanswered()
        return {"pages": [show(p) for p in self.pages()], "sealed": self.sealed(),
                "her_next": self.due_at(waiting).isoformat(timespec="minutes") if waiting else None}

    # ----- her page -----
    def due_at(self, waiting: list[dict]) -> dt.datetime:
        """Her page comes at 5 AM after the day of your page (a page written at 2 AM belongs to the
        day before, so hers comes that same morning)."""
        first = dt.datetime.fromisoformat(waiting[0]["created"])
        morning = dt.datetime.combine(her_day(first) + dt.timedelta(days=1), dt.time(5, 0))
        return morning

    def pattern(self) -> str | None:
        """A gentle, true pattern across their pages (at most once a week), or None."""
        last = self._rows("SELECT value FROM kv WHERE key = 'journal:pattern_at'")
        if last and self.clock() - float(last[0]["value"]) < 7 * 86400:
            return None
        pages = [p for p in self._rows("SELECT text, mood FROM journal WHERE author = 'you' AND kind = 'page' "
                                       "ORDER BY id DESC LIMIT 40") if p["mood"] in MOODS]
        if len(pages) < 6:
            return None
        overall = sum(MOODS[p["mood"]] for p in pages) / len(pages)
        names = set()
        if self.friend is not None:
            try:
                for f in self.friend.facts():
                    if f.kind == "person":
                        names |= {w for w in re.findall(r"\b[A-Z][a-z]{2,}\b", f.text) if w != self.user}
            except Exception:
                pass
        for p in pages:   # capitalised words mid-sentence: probably people and places
            names |= {w for w in re.findall(r"(?<=[a-z,] )[A-Z][a-z]{2,}\b", p["text"]) if w != self.user}
        best = None
        for thing in [*names, *THINGS]:
            pat = re.compile(rf"\b{re.escape(thing)}", re.I if thing in THINGS else 0)
            hits = [MOODS[p["mood"]] for p in pages if pat.search(p["text"])]
            if len(hits) < 3 or len(hits) > len(pages) - 2:
                continue
            diff = sum(hits) / len(hits) - overall
            if abs(diff) >= 0.8 and (best is None or abs(diff) > abs(best[1])):
                best = (thing, diff)
        if best is None:
            return None
        thing, diff = best
        about = thing if thing[0].isupper() else f"{thing}"
        how = "lighter, happier" if diff > 0 else "heavier"
        return f"you sound {how} on the days you write about {about}"

    def write_her_page(self) -> dict | None:
        waiting = self.unanswered()
        if not waiting or self.llm is None:
            return None
        if self.now() < self.due_at(waiting):
            return None
        pages = "\n\n".join(f"({dt.datetime.fromisoformat(p['created']):%A}{', feeling ' + p['mood'] if p['mood'] else ''})\n"
                            f"{p['text'][:1500]}" for p in waiting[-3:])
        life = self.life.summary() if self.life is not None else ""
        pattern = self.pattern()
        note = (f"Something you've noticed across their pages (say it gently, as an observation, only if it fits): "
                f"{pattern}.\n" if pattern else "")
        long = sum(len(p["text"].split()) for p in waiting) > 120
        prompt = NOTE_PROMPT.format(her=self.her, user=self.user, pages=pages, s="s" if len(waiting) > 1 else "",
                                    life=life or "nothing special", pattern=note,
                                    words="90 to 140" if long else "60 to 100")
        from .agent import strip_thinking

        text = None
        for attempt in range(2):
            try:
                raw = self.llm.chat(self.model, [{"role": "user", "content": prompt}],
                                    options={"temperature": 0.75 + 0.1 * attempt, "num_predict": 320}).content
            except Exception as exc:
                log.info("journal: her page failed: %s", exc)
                return None
            cand = strip_thinking(raw).strip().strip('"')
            cand = re.sub(r"^(dear [^,\n]+,?\s*)", "", cand, flags=re.I)
            cand = re.sub(r"\n*[-—–]\s*" + re.escape(self.her) + r"\W*$", "", cand).strip()
            allowed = numbers(pages) | numbers(life) | numbers(note)
            took = borrowed(cand, pages, life)
            if len(cand.split()) < 25 or (numbers(cand) - allowed) or took:
                log.info("journal: her page dropped (%s words, new numbers %s, their life as hers: %s)",
                         len(cand.split()), numbers(cand) - allowed, took)
                continue
            text = cand
            break
        if text is None:
            return None
        from .reminders import new_uid

        now = self.now()
        cur = self._exec("INSERT INTO journal (uid, day, author, kind, text, created, reply_to) VALUES (?,?,?,?,?,?,?)",
                         (new_uid(), her_day(now).isoformat(), "her", "page", text, now.isoformat(timespec="seconds"),
                          waiting[-1]["id"]))
        if pattern:
            self._exec("INSERT OR REPLACE INTO kv (key, value) VALUES ('journal:pattern_at', ?)", (str(self.clock()),))
        page = self.page(cur.lastrowid)
        if self.drawings is not None:
            try:
                from .drawings import subject_for

                thing = subject_for(" ".join(p["text"] for p in waiting))   # something from their page, if she can draw it
                self.drawings.draw(thing, why=f"page:{page['id']}", title=f"from your page: {thing}" if thing else "")
            except Exception as exc:
                log.info("journal: no sketch: %s", exc)
        self.publish("us", {"what": "journal", "action": "her_page", "id": page["id"]})
        log.info("journal: wrote her page (%d words)", len(text.split()))
        return page

    def deliver_letters(self) -> list[dict]:
        now = self.now()
        if now.hour < 9:
            return []
        out = []
        for p in self._rows("SELECT * FROM journal WHERE kind = 'letter' AND delivered = 0 AND deliver_on <= ?",
                            (now.date().isoformat(),)):
            self._exec("UPDATE journal SET delivered = 1 WHERE id = ?", (p["id"],))
            out.append(p)
            written = dt.datetime.fromisoformat(p["created"])
            self.publish("us", {"what": "journal", "action": "letter", "id": p["id"],
                                "written": f"{written:%B} {written.day}"})
            log.info("journal: handed back a letter from %s", p["created"][:10])
        return out

    def tick(self):
        self.deliver_letters()
        if self.can_run():
            self.write_her_page()

    def start(self, every_s: float = 600):
        def loop():
            self._stop.wait(90)
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception as exc:
                    log.warning("journal: %s", exc)
                self._stop.wait(every_s)

        threading.Thread(target=loop, name="journal", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    # ----- as a part (part.py) -----
    def moments(self, now: float) -> list:
        return []

    def used(self, moment, now: float):
        pass

    # ----- in chat -----
    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        """Their newest page (not private), once, while it's fresh (36 h)."""
        rows = self._rows("SELECT * FROM journal WHERE author = 'you' AND kind = 'page' AND private = 0 "
                          "ORDER BY id DESC LIMIT 1")
        if not rows:
            return []
        p = rows[0]
        written = dt.datetime.fromisoformat(p["created"])
        if (self.now() - written).total_seconds() > 36 * 3600:
            return []
        key = f"journal:told:{p['id']}"
        if self._rows("SELECT 1 FROM kv WHERE key = ?", (key,)):
            return []
        self._exec("INSERT OR REPLACE INTO kv (key, value) VALUES (?, '1')", (key,))
        from .conversation import when_words

        excerpt = p["text"] if len(p["text"]) <= 400 else p["text"][:400].rsplit(" ", 1)[0] + " …"
        return [f"They wrote in your shared notebook ({when_words(written.timestamp(), self.clock())}"
                f"{', feeling ' + p['mood'] if p['mood'] else ''}): \"{excerpt}\" You've read it. If it fits what they're "
                "saying now, bring one bit of it up naturally, like a friend who read their page; don't quote it back"]
