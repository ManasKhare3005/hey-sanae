"""Getting to know you: what she picks up about you in conversation, and things to ask about later.

- "About you" facts (table `about`): likes, dislikes, people, plans, projects, routines, written as
  short third-person sentences ("Alex is learning Japanese"). Learned automatically: a few minutes
  after a conversation ends, the small model reads the new turns and lists what's worth keeping
  (JSON). Near-duplicates update the old fact instead of adding one. All of it is on the dashboard's
  About you page, where it can be edited or deleted.
- Never kept, whatever the model says: health, money, passwords and other credentials, religion,
  politics, sexuality, and other people's private details (`SENSITIVE`).
- Threads (table `threads`): things with an outcome worth asking about ("the CS 102 exam on
  Friday") and when to ask ("Friday 6 PM"). The initiative loop asks once, after that time.

Runs only when the laptop is otherwise quiet: not during a conversation, not while the models are
asleep or a game is in front.

The small model gets things wrong, so its answers are checked in code (all measured on real slips):
- Only the user's own words count: turns voice ID wasn't sure about (a video, someone else) are
  left out, and a fact needs a word from what the user said ("stretches regularly" came from her
  own break nudges).
- Follow-ups are only for things still ahead: not marked done by the model, not about something
  the user spoke of in the past tense ("I passed my quiz today"), from a message under 12 hours
  old, at most 14 days out.
- If the user says a follow-up was wrong ("I didn't have a quiz"), it and the facts about it go.
- Speech-to-text garbles things ("plans to go to the gym downwards"), so each new fact gets a sanity
  check first: kept, repaired, dropped, or held in `about_pending` until the user confirms it
  (factcheck.py asks, or the About you page). Held notes are never recalled or used.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .memory import RECALL_MIN, now_iso

log = logging.getLogger(__name__)

KINDS = ("like", "dislike", "person", "plan", "project", "routine", "other")
SAME_MIN = 0.9            # a new fact this close to a known one replaces it
QUIET_S = 180             # learn from a conversation once it's been over this long
MAX_FACTS = 4             # per conversation
THREAD_LIFE = dt.timedelta(days=3)    # an unasked thread this old past its time is dropped
THREAD_AHEAD = dt.timedelta(days=14)  # follow-ups further out than this are dropped
STALE = dt.timedelta(hours=12)        # turns older than this give facts but no follow-ups
DENY_WITHIN_S = 15 * 60               # "I didn't have a quiz" this soon after she asked about it
LEARN_FROM = ("", "you")              # turns.heard values to learn from ("" = typed)
PENDING_DAYS = 14                     # an unconfirmed note nobody answered is let go after this

# Words that don't tie a fact to anything the user said
GENERIC = set("""a an the and or but of to in on at for with about from into by as is are was were be been being
has have had do does did not no very really just also often usually always sometimes regularly lot lots
like likes liked dislike dislikes disliked love loves loved enjoy enjoys enjoyed hate hates hated prefer prefers
want wants wanted plan plans planning planned going get gets getting make makes making take takes
working work works thing things something someone his her their they them he she it its this that
my me i you your named called person people friend""".split())
PAST = re.compile(r"\b(passed|failed|finished|aced|bombed|took|wrote|went|had|was|were|did|got|gave|"
                  r"done|over|ended|yesterday|last (week|night|time))\b", re.I)
FUTURE = re.compile(r"\b(will|going to|gonna|tomorrow|tonight|later|next|upcoming|soon|have (a|an|my)|"
                    r"on (mon|tue|wed|thu|fri|sat|sun)\w*|this (week|weekend))\b|'ll\b", re.I)
DENY = re.compile(r"\b(didn'?t|did not|don'?t|do not|never|wasn'?t|isn'?t|won'?t) (have|had|take|took|get|got|"
                  r"give|gave|do|did|any|a|an|go|went)\b|\bthere (was|is|wasn'?t|isn'?t) no\b|\bno such\b|"
                  r"\bno idea what\b|^what \w+\s*\?*$|\bnot (a thing|real|true|mine)\b|"
                  r"\bi'?m not (giving|taking|having|doing|writing)\b|\bmade (that|it) up\b|\byou'?re wrong\b|"
                  r"\bthat'?s wrong\b|\bwrong person\b", re.I)


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z']+", text.lower().replace("'s ", " ")) if len(w) >= 3]


def _same_word(a: str, b: str) -> bool:
    """quiz ~ quizzes, stretch ~ stretching: a shared start of 4+ letters, or all of a short word."""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n >= 4 or (n >= 3 and n == min(len(a), len(b)))


def grounded(text: str, said: list[str], names: tuple[str, ...] = ()) -> bool:
    """True if a fact / follow-up shares a real word with what the user said (not just her words)."""
    skip = GENERIC | {n.lower() for n in names}
    mine = [w for w in _words(text) if w not in skip]
    theirs = {w for line in said for w in _words(line)}
    return any(_same_word(w, t) for w in mine for t in theirs)


DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def fix_day(when: dt.datetime, about: str, turns: list[dict]) -> dt.datetime:
    """The small model's date maths slips ("Thursday" -> Friday's date): if the user named the day
    ("on Thursday", "tomorrow"), use that day, counted from when they said it; keep the time."""
    for t in reversed(turns):
        line = t["user"].lower()
        if not grounded(about, [t["user"]]):
            continue
        said = dt.datetime.fromisoformat(t["ts"]).date()
        if "tomorrow" in line:
            return dt.datetime.combine(said + dt.timedelta(days=1), when.time())
        if re.search(r"\b(today|tonight)\b", line):
            return dt.datetime.combine(said, when.time())
        named = [i for i, d in enumerate(DAYS) if re.search(rf"\b{d}\b", line)]
        if len(named) == 1:
            ahead = (named[0] - said.weekday()) % 7
            return dt.datetime.combine(said + dt.timedelta(days=ahead), when.time())
        return when
    return when


def overlap(text: str, said: list[str], names: tuple[str, ...] = ()) -> float:
    """The share of a text's real words that come from `said` (0-1)."""
    skip = GENERIC | {n.lower() for n in names}
    mine = [w for w in _words(text) if w not in skip]
    theirs = {w for line in said for w in _words(line)}
    return sum(any(_same_word(w, t) for t in theirs) for w in mine) / len(mine) if mine else 0.0


def still_ahead(about: str, said: list[str]) -> bool:
    """False if every line the user mentioned it in talks about it in the past tense ("I passed my quiz")."""
    lines = [line for line in said if grounded(about, [line])]
    if not lines:
        return False
    return any(FUTURE.search(line) or not PAST.search(line) for line in lines)

SENSITIVE = re.compile(
    r"\b(health|medical|medicine|medication|pills?|diagnos\w*|doctor|therapy|therapist|depress\w*|anxiety|"
    r"disorder|illness|disease|pregnan\w*|surgery|hospital|password|passcode|pin\b|otp|credential\w*|"
    r"api key|token|ssn|social security|bank|account number|credit card|debit|salary|income|debt|loan|"
    r"religio\w*|church|mosque|temple|pray\w*|politic\w*|vote[sd]?|democrat\w*|republican\w*|"
    r"sexual\w*|gay|lesbian|bisexual|trans(gender)?|address is|lives at|phone number)\b", re.I)


EXTRACT_PROMPT = """You are helping {name} (an AI friend) remember things about {user}. Below is a conversation between them, and what {name} already knows.

List NEW things worth remembering about {user} as a friend would: what {user} likes or dislikes, people in {user}'s life (by first name and relation), plans, projects, routines, ongoing things. Only what {user} said or clearly meant, not {name}'s guesses. Not one-off requests (opening apps, the weather, asking for facts). Never: health, money, passwords or credentials, religion, politics, sexuality, addresses or phone numbers, or other people's private details. Write each as a short third-person sentence starting with "{user}". At most {max_facts}; an empty list is fine and common.

Also list "followups": things still AHEAD of {user} with an outcome a friend would ask about later (an exam, interview, game, trip, appointment-free event), with ask_after = when it should be over (ISO date-time, local time; now is {now}; if the time of day isn't known, use 18:00 that day) and status "upcoming". Something {user} already did or that is already over ("I passed my quiz") is status "done", never something to ask about. Only things {user} said, never what {name} said.{no_followups}

Known already:
{known}

Conversation:
{turns}

Reply as JSON: {{"facts": [{{"text": "...", "kind": "like|dislike|person|plan|project|routine|other"}}], "followups": [{{"about": "...", "ask_after": "YYYY-MM-DDTHH:MM", "status": "upcoming|done"}}]}}"""

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "kind": {"type": "string", "enum": list(KINDS)}}, "required": ["text", "kind"]}},
        "followups": {"type": "array", "items": {"type": "object", "properties": {
            "about": {"type": "string"}, "ask_after": {"type": "string"},
            "status": {"type": "string", "enum": ["upcoming", "done"]}}, "required": ["about", "ask_after", "status"]}},
    },
    "required": ["facts", "followups"],
}


SANITY_PROMPT = """{user} talks to {name} mostly by voice, so speech-to-text mishears words, and these notes about {user} were written from that. Check each note before it goes into {name}'s long-term memory.

For each one answer with a verdict:
- "keep": it makes clear sense as something true about {user}, and you're confident it was heard right.
- "fix": a word was clearly misheard or garbled and you can tell what was meant: give the corrected note in "text".
- "unsure": it could be real but something reads oddly or you can't tell what was meant. {name} will ask {user}.
- "drop": it's nonsense, or not something worth knowing about {user}.

Examples of how to judge: "Alex plans to go to the gym downwards" is garbled ("downwards" means nothing here), so "fix" only if the words {user} said make the meaning clear, otherwise "unsure". "Alex plans to play Valorant in game mode" describes the app rather than {user}: "drop". "Alex likes hiking" is "keep".

What {user} actually said:
{said}

Notes to check:
{facts}

Reply as JSON: {{"checks": [{{"note": 1, "verdict": "keep|fix|unsure|drop", "text": "the corrected note, only for fix"}}]}}"""

SANITY_SCHEMA = {
    "type": "object",
    "properties": {"checks": {"type": "array", "items": {"type": "object", "properties": {
        "note": {"type": "integer"}, "verdict": {"type": "string", "enum": ["keep", "fix", "unsure", "drop"]},
        "text": {"type": "string"}}, "required": ["note", "verdict"]}}},
    "required": ["checks"],
}


def sanity_check(llm, model: str, facts: list[tuple[str, str]], said: list[str], user: str, name: str,
                 ) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
    """(keep, ask about, dropped). If the check itself fails, or skips a note, that note waits for
    {user} to confirm: an unchecked note must never become a fact, but it isn't lost either."""
    if not facts:
        return [], [], []
    prompt = SANITY_PROMPT.format(user=user, name=name, said="\n".join(f"- {s}" for s in said[-20:]),
                                  facts="\n".join(f"{i}. {t}" for i, (t, _) in enumerate(facts, 1)))
    try:
        raw = llm.chat(model, [{"role": "user", "content": prompt}], fmt=SANITY_SCHEMA,
                       options={"temperature": 0.0, "num_predict": 400}).content
        checks = {c.get("note"): c for c in (json.loads(raw).get("checks") or []) if isinstance(c, dict)}
    except Exception as exc:
        log.info("couldn't check what she learned (%s); asking instead", exc)
        checks = {}
    keep, ask, dropped = [], [], []
    for i, (text, kind) in enumerate(facts, 1):
        c = checks.get(i) or {}
        verdict = c.get("verdict")
        fixed = str(c.get("text") or "").strip()
        if verdict == "keep":
            keep.append((text, kind))
        elif verdict == "drop":
            dropped.append(text)
        elif verdict == "fix" and fixed and grounded(fixed, said, (user, name)):
            log.info("repaired a note: %r -> %r", text, fixed)
            keep.append((fixed, kind))
        else:
            ask.append((text, kind))
    return keep, ask, dropped


@dataclass
class PendingFact:
    id: int
    text: str
    kind: str
    created: str
    asked: bool = False


@dataclass
class AboutFact:
    id: int
    text: str
    kind: str
    updated: str
    mentions: int = 1


@dataclass
class Thread:
    id: int
    about: str
    ask_after: str
    status: str


def sensitive(text: str) -> bool:
    return bool(SENSITIVE.search(text))


class FriendMemory:
    """The `about` and `threads` tables, in the same database as everything else (memory.py)."""

    def __init__(self, memory):
        self.mem = memory                        # tables `about` and `threads` are in memory.SCHEMA
        self._index = memory._load_vectors("about", "text")

    # ----- about you -----
    def facts(self) -> list[AboutFact]:
        with self.mem.lock:
            rows = self.mem.db.execute("SELECT id, text, kind, updated, mentions FROM about ORDER BY updated DESC").fetchall()
            return [AboutFact(r["id"], r["text"], r["kind"], r["updated"], r["mentions"]) for r in rows]

    def add(self, text: str, kind: str = "other") -> tuple[int, str] | None:
        """Keep a fact (or refresh the near-identical one). Returns (id, "added" / "updated"), or None if
        it's sensitive or already a saved "remember" fact."""
        text = " ".join(text.split()).strip().rstrip(".")
        if len(text) < 6 or sensitive(text):
            return None
        kind = kind if kind in KINDS else "other"
        with self.mem.lock:
            for _rid, score in self.mem._search(self.mem._facts, text, 1):
                if score >= SAME_MIN:
                    return None                                       # already an explicit memory
            for rid, score in self.mem._search(self._index, text, 1):
                if score >= SAME_MIN:
                    self.mem._unindex(self._index, rid)
                    self.mem.db.execute("UPDATE about SET text = ?, kind = ?, updated = ?, mentions = mentions + 1 WHERE id = ?",
                                        (text, kind, now_iso(), rid))
                    self.mem._index(self._index, "about", rid, text)
                    return rid, "updated"
            cur = self.mem.db.execute("INSERT INTO about (text, kind, created, updated) VALUES (?, ?, ?, ?)",
                                      (text, kind, now_iso(), now_iso()))
            self.mem._index(self._index, "about", cur.lastrowid, text)
            return cur.lastrowid, "added"

    def edit(self, fact_id: int, text: str) -> bool:
        text = " ".join(text.split()).strip()
        if not text:
            return self.delete(fact_id)
        with self.mem.lock:
            cur = self.mem.db.execute("UPDATE about SET text = ?, updated = ? WHERE id = ?", (text, now_iso(), fact_id))
            if not cur.rowcount:
                return False
            self.mem._unindex(self._index, fact_id)
            self.mem._index(self._index, "about", fact_id, text)
            return True

    def delete(self, fact_id: int) -> bool:
        with self.mem.lock:
            cur = self.mem.db.execute("DELETE FROM about WHERE id = ?", (fact_id,))
            self.mem.db.commit()
            self.mem._unindex(self._index, fact_id)
            return cur.rowcount > 0

    # ----- not sure yet: never recalled or used until confirmed -----
    def hold(self, text: str, kind: str = "other") -> int | None:
        text = " ".join(text.split()).strip().rstrip(".")
        if len(text) < 6 or sensitive(text):
            return None
        with self.mem.lock:
            if any(p.text.lower() == text.lower() for p in self.pending()):
                return None
            cur = self.mem.db.execute("INSERT INTO about_pending (text, kind, created) VALUES (?, ?, ?)",
                                      (text, kind if kind in KINDS else "other", now_iso()))
            self.mem.db.commit()
            return cur.lastrowid

    def pending(self) -> list[PendingFact]:
        """Unconfirmed notes, oldest first; ones nobody answered for PENDING_DAYS are let go."""
        cutoff = (dt.datetime.now() - dt.timedelta(days=PENDING_DAYS)).isoformat(timespec="seconds")
        with self.mem.lock:
            self.mem.db.execute("DELETE FROM about_pending WHERE created < ?", (cutoff,))
            self.mem.db.commit()
            rows = self.mem.db.execute("SELECT id, text, kind, created, asked FROM about_pending ORDER BY id").fetchall()
            return [PendingFact(r["id"], r["text"], r["kind"], r["created"], bool(r["asked"])) for r in rows]

    def mark_asked(self, pending_id: int):
        with self.mem.lock:
            self.mem.db.execute("UPDATE about_pending SET asked = 1 WHERE id = ?", (pending_id,))
            self.mem.db.commit()

    def reject(self, pending_id: int) -> bool:
        with self.mem.lock:
            cur = self.mem.db.execute("DELETE FROM about_pending WHERE id = ?", (pending_id,))
            self.mem.db.commit()
            return cur.rowcount > 0

    def confirm(self, pending_id: int) -> bool:
        """They said it's right: now it's a fact."""
        found = next((p for p in self.pending() if p.id == pending_id), None)
        if found is None:
            return False
        self.reject(pending_id)
        self.add(found.text, found.kind)
        return True

    def clear(self):
        with self.mem.lock:
            self.mem.db.execute("DELETE FROM about_pending")
            self.mem.db.execute("DELETE FROM about")
            self.mem.db.execute("DELETE FROM threads")
            self.mem.db.commit()
            self._index = {"ids": [], "vecs": []}
            self.mem.db.execute("VACUUM")

    def relevant(self, text: str, k: int = 2, min_score: float = RECALL_MIN) -> list[str]:
        try:
            with self.mem.lock:
                hits = [(rid, s) for rid, s in self.mem._search(self._index, text, k) if s >= min_score]
                return [self.mem.db.execute("SELECT text FROM about WHERE id = ?", (rid,)).fetchone()["text"] for rid, _ in hits]
        except Exception as exc:
            log.debug("about recall failed: %s", exc)
            return []

    def interests(self, k: int = 3, rng=None) -> list[str]:
        """A few things to chat about: likes, projects, plans (a random handful)."""
        import random

        rng = rng or random
        pool = [f.text for f in self.facts() if f.kind in ("like", "project", "plan", "routine")]
        return rng.sample(pool, min(k, len(pool)))

    # ----- things to ask about later -----
    def add_thread(self, about: str, ask_after: dt.datetime) -> int | None:
        about = " ".join(about.split()).strip().rstrip(".")
        if not about or sensitive(about):
            return None
        with self.mem.lock:
            for t in self.threads("open"):
                if t.about.lower() == about.lower():
                    return None
            cur = self.mem.db.execute("INSERT INTO threads (about, ask_after, created) VALUES (?, ?, ?)",
                                      (about, ask_after.isoformat(timespec="minutes"), now_iso()))
            self.mem.db.commit()
            return cur.lastrowid

    def threads(self, status: str | None = None) -> list[Thread]:
        with self.mem.lock:
            q = "SELECT id, about, ask_after, status FROM threads" + (" WHERE status = ?" if status else "") + " ORDER BY ask_after"
            rows = self.mem.db.execute(q, (status,) if status else ()).fetchall()
            return [Thread(r["id"], r["about"], r["ask_after"], r["status"]) for r in rows]

    def due_threads(self, now: dt.datetime) -> list[Thread]:
        """Open threads whose time has come (and not long gone)."""
        out = []
        for t in self.threads("open"):
            when = dt.datetime.fromisoformat(t.ask_after)
            if when <= now <= when + THREAD_LIFE:
                out.append(t)
            elif now > when + THREAD_LIFE:
                self.set_thread(t.id, "expired")
        return out

    def set_thread(self, thread_id: int, status: str) -> bool:
        with self.mem.lock:
            cur = self.mem.db.execute("UPDATE threads SET status = ? WHERE id = ?", (status, thread_id))
            self.mem.db.commit()
            return cur.rowcount > 0

    def asked(self, thread_id: int, now: float | None = None):
        """She just asked about this thread: remember it for a few minutes in case it was wrong."""
        about = next((t.about for t in self.threads() if t.id == thread_id), "")
        self.set_thread(thread_id, "asked")
        self.mem.set("friend:last_asked", json.dumps({"id": thread_id, "about": about,
                                                      "t": time.time() if now is None else now}))

    def denied(self, user_text: str, now: float | None = None, names: tuple[str, ...] = ()) -> str | None:
        """"I didn't have a quiz" right after she asked about one: drop the thread and the facts about
        it. Returns what was dropped (for a note to the model), or None."""
        try:
            last = json.loads(self.mem.get("friend:last_asked") or "{}")
        except ValueError:
            return None
        now = time.time() if now is None else now
        if not last or now - last.get("t", 0) > DENY_WITHIN_S or not DENY.search(user_text.strip()):
            return None
        self.mem.set("friend:last_asked", "{}")
        self.set_thread(int(last["id"]), "wrong")
        about = last.get("about", "")
        for f in self.facts():
            if about and grounded(f.text, [about], names):
                self.delete(f.id)
                log.info("dropped a wrong fact: %s", f.text)
        return about or "that"


def parse_extraction(raw: str, now: dt.datetime) -> tuple[list[tuple[str, str]], list[tuple[str, dt.datetime]]]:
    """The model's JSON -> ([(fact, kind)], [(about, ask_after)]). Bad pieces are dropped."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        m = re.search(r"\{.*\}", raw or "", re.S)
        try:
            data = json.loads(m.group(0)) if m else {}
        except ValueError:
            data = {}
    facts = []
    for f in (data.get("facts") or [])[:MAX_FACTS]:
        if isinstance(f, dict) and isinstance(f.get("text"), str) and f["text"].strip():
            facts.append((f["text"].strip(), str(f.get("kind", "other"))))
    follow = []
    for f in data.get("followups") or []:
        try:
            when = dt.datetime.fromisoformat(str(f["ask_after"]).strip().replace("Z", ""))
        except (KeyError, TypeError, ValueError):
            continue
        if when.tzinfo is not None:
            when = when.astimezone().replace(tzinfo=None)
        if str(f.get("status", "upcoming")).lower() != "upcoming":
            continue                                              # already happened: nothing to ask
        if now < when <= now + THREAD_AHEAD and str(f.get("about", "")).strip():
            follow.append((str(f["about"]).strip(), when))
    return facts, follow


class Learner:
    """Background: once a conversation has been over for a few minutes, learn from its new turns."""

    def __init__(self, ctx, friend: FriendMemory, llm, model: str, user: str, name: str,
                 can_run: Callable[[], bool] = lambda: True, publish=lambda kind, data: None, clock=time.time):
        self.ctx, self.friend, self.llm, self.model = ctx, friend, llm, model
        self.user, self.name = user, name
        self.can_run = can_run
        self.publish = publish
        self.clock = clock
        self._stop = threading.Event()
        self.failures = 0

    def _pending(self) -> list[dict]:
        mem = self.ctx.memory
        last = int(mem.get("friend:last_turn") or 0)
        if last == 0:                          # first run: start from now, don't mine old history
            turns = mem.recent_turns(1)
            mem.set("friend:last_turn", str(turns[-1]["id"] if turns else 0))
            return []
        return [t for t in mem.recent_turns(40) if t["id"] > last]

    def run_once(self) -> list[str]:
        """Learn from the finished conversation, if there is one. Returns the facts added (for tests)."""
        turns = self._pending()
        if not turns:
            return []
        last_ts = dt.datetime.fromisoformat(turns[-1]["ts"]).timestamp()
        if self.clock() - last_ts < QUIET_S or not self.can_run():
            return []
        now = dt.datetime.fromtimestamp(self.clock())
        end = turns[-1]["id"]
        # Old turns (it fell behind) give facts but no follow-ups, in a run of their own
        stale = [t for t in turns if now - dt.datetime.fromisoformat(t["ts"]) > STALE]
        if stale and len(stale) < len(turns):
            turns, end = stale, stale[-1]["id"]
        followups = not stale
        private = set(json.loads(self.ctx.memory.get("comfort:turns") or "[]"))    # a hard moment (comfort.py)
        turns = [t for t in turns if (t.get("heard") or "") in LEARN_FROM and t["id"] not in private]   # not a video / someone else
        if not turns:
            self.ctx.memory.set("friend:last_turn", str(end))
            return []
        known = [f.text for f in self.friend.facts()[:40]] + [h.text for h in self.ctx.memory.facts()[:20]]
        prompt = EXTRACT_PROMPT.format(
            name=self.name, user=self.user, max_facts=MAX_FACTS, now=now.isoformat(timespec="minutes"),
            known="\n".join(f"- {k}" for k in known) or "(nothing yet)",
            no_followups="" if followups else " These messages are old: list no followups.",
            turns="\n".join(f"[{t['ts'][5:16].replace('T', ' ')}] {self.user}: {t['user']}\n{self.name}: {t['reply']}"
                            for t in turns[-20:]))
        try:
            reply = self.llm.chat(self.model, [{"role": "user", "content": prompt}], fmt=JSON_SCHEMA,
                                  options={"temperature": 0.1, "num_predict": 400})
            raw = reply.content
        except Exception as exc:
            self.failures += 1
            log.info("learning from the conversation failed (%s)", exc)
            if self.failures < 3:
                return []
            raw = "{}"                                            # give up on these turns
        self.failures = 0
        self.ctx.memory.set("friend:last_turn", str(end))
        facts, follow = parse_extraction(raw, now)
        said = [t["user"] for t in turns]
        names = (self.user, self.name)
        dropped = [x for x, _ in facts if not grounded(x, said, names)]
        facts = [(x, k) for x, k in facts if x not in dropped]
        late = [a for a, _ in follow] if not followups else \
            [a for a, _ in follow if not grounded(a, said, names) or not still_ahead(a, said)]
        follow = [(a, w) for a, w in follow if a not in late]
        if dropped or late:
            log.info("not kept (not from %s's words, or already over): %s", self.user, dropped + late)
        facts, unsure, nonsense = sanity_check(self.llm, self.model, facts, said, self.user, self.name)
        if nonsense:
            log.info("not kept (didn't make sense): %s", nonsense)
        held = [text for text, kind in unsure if self.friend.hold(text, kind)]
        if held:
            log.info("%d note(s) waiting for %s to confirm", len(held), self.user)
            self.publish("about", {"pending": len(held)})
        added = []
        for text, kind in facts:
            r = self.friend.add(text, kind)
            if r:
                added.append(text)
        for about, when in follow:
            when = fix_day(when, about, turns)
            if when > now:
                self.friend.add_thread(about, when)
        if added or follow:
            log.info("learned %d thing(s) about %s, %d to ask about later", len(added), self.user, len(follow))
            self.publish("about", {"added": len(added), "threads": len(follow)})
        return added

    def start(self, interval_s: float = 60.0):
        def loop():
            while not self._stop.wait(interval_s):
                try:
                    self.run_once()
                except Exception as exc:
                    log.warning("friend memory: %s", exc)

        threading.Thread(target=loop, name="friend-learner", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()


def similar(embed: Callable[[list[str]], np.ndarray], text: str, others: list[str], threshold: float) -> bool:
    """True if `text` means nearly the same as one of `others` (for anti-repetition)."""
    if not others:
        return False
    vecs = embed([text, *others])
    return bool(np.max(vecs[1:] @ vecs[0]) >= threshold)
