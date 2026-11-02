"""One running chat instead of separate commands.

What the model sees of the conversation, inside its small context window (4096 tokens, most
of it taken by her character and the tools):
  - the last few turns word for word (with their tool calls, so she doesn't start claiming
    actions she never took), for as long as they're recent (`verbatim_min`);
  - a short running summary of the whole chat ("Earlier in this chat: ..."), written by the
    model in the background whenever Sanae is idle, so a topic from an hour ago or before a
    pause still counts;
  - after a long break (`new_after_h`) a new chat starts, and the last one's summary is
    mentioned for its first few turns ("Last time you talked, yesterday at 11 PM: ...").

It's kept in the memory database (kv "conversation"), so restarting Sanae doesn't wipe it.
What gets saved is only what was said and done: the per-request notes (her mood, how the
user sounds and, above all, the window in front of them) are dropped first.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

KEY = "conversation"
BACKLOG = 5                     # chats waiting for their summary
RETRY_S, RETRY_MAX_S = 60, 900  # after a failed summary: wait 1 min, doubling up to 15
SUMMARY_PROMPT = (
    "You keep a running summary of an ongoing chat between {user} and {name}, their friend and assistant "
    "who lives on their laptop. Update the summary with the new part of the chat. Keep only facts that "
    "matter later: what {user} said they are doing, feeling and planning, deadlines, things {name} did for "
    "them (reminders, events, apps, searches) with their exact times, and real questions left open. "
    "Leave out {name}'s own wording: her metaphors, jokes, comparisons and descriptions of things are not "
    "facts, and never put her words in {user}'s mouth. Things that were happening (a song playing, a video) "
    "are over by now: write them in the past tense. Don't write what time things were said or say "
    "'this morning' / 'tonight' about the chat itself; only keep clock times that belong to plans, deadlines "
    "and reminders. Drop greetings and "
    "filler. Write at most {words} words in plain sentences, third person using the name \"{user}\" (no he/she), oldest first, "
    "and never drop a fact from the summary so far (deadlines, dates, plans) unless the new part "
    "changes it.\n\n"
    "Summary so far: {summary}\n\nNew part of the chat:\n{chat}\n\nUpdated summary:"
)
VERSION = 3                     # older summaries could carry her metaphors (v2) or made-up clock times (v3): dropped
STOP = set("""about above after again also always another anything around back because been before being
both came come could didn't does doing done down each even ever every feel feels from going gonna good
have here just keep kind know like little look looks made make makes maybe more most much need never only
other over really right same says some something still such sure take than that that's their them then
there these they thing things think this those through time very want well were what what's when where
which while will with would yeah your you're you've yours it's i'm let's into okay ohhh""".split())
_TIME = re.compile(r"^\[[^\]]*\]\s*")


def said(msg: dict) -> str:
    """A message as it should be kept: for the user, the first line only (no recall / mood /
    window notes); her own unprompted openers keep only that she spoke first."""
    content = str(msg.get("content") or "")
    if msg.get("role") != "user":
        return content
    first = content.split("\n", 1)[0]
    if "(Nobody said anything" in first:
        stamp = _TIME.match(first)
        return (stamp.group(0) if stamp else "") + "(You spoke first.)"
    return first


def turn_text(turn: list[dict], user: str, name: str) -> str:
    """A turn as plain lines for the summary: who said what, what was done."""
    lines = []
    for m in turn:
        role = m.get("role")
        if role == "user":
            text = _TIME.sub("", said(m)).strip()
            if text and text != "(You spoke first.)":
                lines.append(f"{user}: {text}")
        elif role == "tool":
            lines.append(f"  ({m.get('tool_name', 'tool')} -> {str(m.get('content', ''))[:160]})")
        elif role == "assistant" and m.get("content"):
            lines.append(f"{name}: {re.sub(r'^(\[[a-z_]+\])+\s*', '', str(m['content']))}")
    return "\n".join(lines)


def _words(text: str) -> set[str]:
    """Content words, cut to their first 5 letters so 'storms' and 'stormy' count as 'storm'."""
    return {w[:5] for w in re.findall(r"[a-z][a-z']{3,}", text.lower()) if w not in STOP}


def grounded_summary(summary: str, turns: list[list[dict]], before: str = "") -> str:
    """Drop sentences that rest on words only {name} used (her metaphors: "Alex is in a
    Beatle-powered storm"). The user's lines, tool results and the summary so far ground a word."""
    ours, hers = set(_words(before)), set()
    for turn in turns:
        for m in turn:
            text = _TIME.sub("", said(m)) if m.get("role") == "user" else str(m.get("content") or "")
            if m.get("role") == "assistant":
                hers |= _words(re.sub(r"\[[a-z_]+\]", "", text))
            else:
                ours |= _words(text)
    only_hers = hers - ours
    # Clock times nobody said: the summary made up "Sanae checks in at 8:15 AM" at 11:25, and every
    # reply after that thought it was morning
    said_times = {_clock(t) for t in CLOCK.findall(before)}
    for turn in turns:
        for m in turn:
            said_times |= {_clock(t) for t in CLOCK.findall(_TIME.sub("", said(m)) if m.get("role") == "user"
                                                           else str(m.get("content") or ""))}
    keep = [s for s in re.split(r"(?<=[.!?])\s+", summary.strip())
            if s and not (_words(s) & only_hers) and all(_clock(t) in said_times for t in CLOCK.findall(s))]
    return " ".join(keep)


CLOCK = re.compile(r"\b\d{1,2}(?::\d{2})?\s*[ap]\.?m\b|\b\d{1,2}:\d{2}\b", re.I)


def _clock(t: str) -> str:
    """'9:00 AM' / '9am' / '9 a.m.' -> '9am'; '21:00' -> '21:00'."""
    t = re.sub(r"[\s.]", "", t.lower())
    return re.sub(r":00(?=[ap])", "", t)


def worn_words(replies: list[str], user_lines: list[str], least: int = 2) -> list[str]:
    """Words she's used in `least` of her recent replies that the user never said: the metaphor
    the small model clings to for a whole chat ("storm" in every reply, even a reminder)."""
    said_by_user = set().union(*(_words(u) for u in user_lines)) if user_lines else set()
    counts: dict[str, int] = {}
    first: dict[str, str] = {}
    for r in replies:
        clean = re.sub(r"\[[a-z_]+\]", "", r).lower()
        for w in re.findall(r"[a-z][a-z']{3,}", clean):
            if w not in STOP and w[:5] not in said_by_user:
                first.setdefault(w[:5], w)
        for k in _words(clean) - said_by_user:
            counts[k] = counts.get(k, 0) + 1
    return [first[k] for k, n in counts.items() if n >= least and k in first]


def when_words(ts: float, now: float) -> str:
    """'this morning at 9 AM', 'yesterday at 11 PM', 'on Monday at 3 PM'."""
    d, n = dt.datetime.fromtimestamp(ts), dt.datetime.fromtimestamp(now)
    clock = f"{d.hour % 12 or 12}{d.strftime(':%M') if d.minute else ''} {'AM' if d.hour < 12 else 'PM'}"
    days = (n.date() - d.date()).days
    if days == 0:
        return f"earlier today at {clock}"
    if days == 1:
        return f"yesterday at {clock}"
    return f"on {d.strftime('%A')} at {clock}"


class Conversation:
    """`turns` is the agent's history (one list of messages per turn); `times` matches it."""

    def __init__(self, store=None, summarize: Callable[[str], str] | None = None, *,
                 verbatim_turns: int = 6, verbatim_chars: int = 4000, verbatim_min: float = 30,
                 new_after_h: float = 4, previous_for_h: float = 36, user: str = "the user",
                 name: str = "Sanae", summary_words: int = 90, clock: Callable[[], float] = time.time):
        self.store = store                  # MemoryStore (kv), or None: nothing kept across restarts
        self.summarize = summarize          # prompt -> text (the model), or None: no summary
        self.verbatim_turns = verbatim_turns
        self.verbatim_chars = verbatim_chars
        self.verbatim_s = verbatim_min * 60
        self.new_after_s = new_after_h * 3600
        self.previous_for_s = previous_for_h * 3600
        self.user, self.name, self.summary_words = user, name, summary_words
        self.clock = clock
        self.turns: list[list[dict]] = []
        self.times: list[float] = []
        self.folded = 0                     # turns[:folded] are in the summary
        self.dropped = False                # turns were let go (they live on in the summary only)
        self.summary = ""
        self.previous, self.previous_ts = "", 0.0
        self.backlog: list[dict] = []       # chats that ended before their summary could be written
        self.retry_at = 0.0                 # the last summary failed: not before this
        self.failed_s = 0.0
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._load()

    # ----- the agent's view -----
    def _sync(self):
        """Turns added or cleared from outside (initiative lines, evals) without times."""
        if len(self.times) > len(self.turns):
            self.times = self.times[:len(self.turns)]
            self.folded = min(self.folded, len(self.turns))
        while len(self.times) < len(self.turns):
            self.times.append(self.clock())

    @property
    def last(self) -> float:
        with self.lock:
            self._sync()
            return self.times[-1] if self.times else 0.0

    def touch(self):
        """Something was said just now (keeps a chat that's still going from being treated as over)."""
        with self.lock:
            self._sync()
            if self.times:
                self.times[-1] = self.clock()

    def _window(self, now: float) -> list[int]:
        """Indexes of the turns the model sees word for word."""
        waiting = self.summarize is not None          # not summarised yet: keep it word for word
        keep = [i for i in range(len(self.turns))
                if now - self.times[i] <= self.verbatim_s or (waiting and i >= self.folded)]
        keep = keep[-self.verbatim_turns:]

        def size(idx):
            return sum(len(str(m.get("content", ""))) + 80 * len(m.get("tool_calls", []))
                       for i in idx for m in self.turns[i])
        # an overflowing context would make Ollama cut the start of the prompt (the instructions)
        while len(keep) > 1 and size(keep) > self.verbatim_chars:
            keep = keep[1:]
        return keep

    def recent(self) -> list[dict]:
        with self.lock:
            self._sync()
            now = self.clock()
            if self.turns and now - self.times[-1] > self.new_after_s:
                self._new_chat()
            return [m for i in self._window(now) for m in self.turns[i]]

    def note(self) -> str | None:
        """'(Earlier in this chat: ...)' / '(Last time you talked ...)' for the user message, or None."""
        with self.lock:
            self._sync()
            now = self.clock()
            parts = []
            window = self._window(now)
            older = self.dropped or (bool(self.turns) and (not window or window[0] > 0))
            if self.summary and older:
                parts.append(f"Earlier in this chat: {self.summary}")
            recent = [self.turns[i] for i in window][-4:]
            worn = worn_words([str(m.get("content") or "") for t in recent for m in t if m.get("role") == "assistant"],
                              [_TIME.sub("", said(m)) for t in recent for m in t if m.get("role") == "user"])
            if worn:
                parts.append("You've said " + ", ".join(f'"{w}"' for w in worn[:5]) + " in your last few "
                             "replies; leave those words and that picture behind now")
            if (self.previous and len(self.turns) < 3 and not self.dropped
                    and now - self.previous_ts < self.previous_for_s):
                parts.append(f"Last time you two talked ({when_words(self.previous_ts, now)}): {self.previous} "
                             "Bring it up only if it fits")
            return " ".join(parts) or None

    def add(self, turn: list[dict]):
        # Kept as said: the one-off notes on a request (recall, mood, the window, the summary, her
        # "speak first" instructions with lines to avoid) stay out, or the model copies them later
        turn = [{**m, "content": said(m)} if m.get("role") == "user" else m for m in turn]
        with self.lock:
            self._sync()
            self.turns.append(turn)
            self.times.append(self.clock())
        self._save()

    def clear(self):
        with self.lock:
            self.turns.clear()
            self.times.clear()
            self.folded, self.dropped, self.summary = 0, False, ""
        self._save()

    def _new_chat(self):
        """A long break: what was said becomes "last time"; the new chat starts empty."""
        if self.summary or self.turns:
            self.previous = self.summary or " ".join(
                _TIME.sub("", said(m)) for t in self.turns[-2:] for m in t if m.get("role") == "user")[:300]
            self.previous_ts = self.times[-1] if self.times else self.clock()
        if self.summarize is not None and self.folded < len(self.turns):
            # Not summarised yet (the model was down): keep it to write up later, instead of losing it
            self.backlog = [*self.backlog, {"turns": self.turns[self.folded:], "summary": self.summary,
                                            "ts": self.previous_ts}][-BACKLOG:]
        self.turns.clear()
        self.times.clear()
        self.folded, self.dropped, self.summary = 0, False, ""
        self._save()

    # ----- the running summary -----
    def pending(self) -> int:
        with self.lock:
            self._sync()
            return len(self.turns) - self.folded

    def _write(self, summary: str, chat: str) -> str | None:
        """One model call; on failure, waits longer before the next try and returns None. The turns
        stay queued, and a failure is logged once, not on every retry."""
        prompt = SUMMARY_PROMPT.format(user=self.user, name=self.name, words=self.summary_words,
                                       summary=summary or "(nothing yet)", chat=chat)
        try:
            new = " ".join(str(self.summarize(prompt)).split())
        except Exception as exc:
            if not self.failed_s:
                log.warning("conversation summary failed, will retry: %s", exc)
            self.failed_s = min(self.failed_s * 2 or RETRY_S, RETRY_MAX_S)
            self.retry_at = self.clock() + self.failed_s
            return None
        if self.failed_s:
            log.info("conversation summaries work again")
        self.failed_s, self.retry_at = 0.0, 0.0
        return re.sub(r"^(updated summary|summary)\s*:\s*", "", new, flags=re.I).strip()

    def fold_backlog(self) -> bool:
        """Write up one chat that ended while the model was down. True if one was done."""
        if self.summarize is None:
            return False
        with self.lock:
            if not self.backlog:
                return False
            item = self.backlog[0]
        turns = item["turns"]
        chat = "\n".join(turn_text(t, self.user, self.name) for t in turns).strip()
        new = self._write(item.get("summary", ""), chat) if chat else item.get("summary", "")
        if new is None:
            return False
        new = grounded_summary(new, turns, item.get("summary", ""))
        with self.lock:
            self.backlog = [x for x in self.backlog if x is not item]
            if new and item.get("ts", 0) >= self.previous_ts:
                self.previous, self.previous_ts = new, item.get("ts", 0)
        self._save()
        return True

    def fold(self) -> bool:
        """Fold the turns not yet in the summary into it (one model call). True if it changed."""
        if self.summarize is None:
            return False
        with self.lock:
            self._sync()
            start, end = self.folded, len(self.turns)
            if start >= end:
                return False
            chat = "\n".join(turn_text(t, self.user, self.name) for t in self.turns[start:end]).strip()
            summary = self.summary
        if not chat:
            new = summary
        else:
            new = self._write(summary, chat)
            if new is None:
                return False
            with self.lock:
                folding = self.turns[start:end]
            new = grounded_summary(new, folding, summary)
            if not new:
                return False
        with self.lock:
            if len(self.turns) < end or self.folded != start:     # cleared or changed meanwhile
                return False
            self.summary, self.folded = new, end
            self._prune()
        self._save()
        log.info("conversation summary (%d turns): %s", end, new)
        return True

    def _prune(self):
        """Let go of summarised turns that are out of the window for good."""
        now = self.clock()
        window = self._window(now)
        first = min(window[0] if window else len(self.turns), self.folded, max(0, len(self.turns) - 12))
        if first > 0:
            del self.turns[:first]
            del self.times[:first]
            self.folded -= first
            self.dropped = True

    def tick(self, busy: Callable[[], bool] = lambda: False, idle_s: float = 45, batch: int = 3):
        """One round of the background loop: nothing while busy or waiting to retry a failure."""
        if busy() or self.clock() < self.retry_at:
            return
        waiting = self.pending()
        quiet = self.clock() - self.last
        if waiting and (quiet >= idle_s or (waiting >= batch and quiet >= 10)):
            self.fold()
        elif self.backlog and quiet >= idle_s:
            self.fold_backlog()

    def start(self, busy: Callable[[], bool] = lambda: False, idle_s: float = 45, every_s: float = 15,
              batch: int = 3):
        """Background folding: after `idle_s` of quiet, or once `batch` turns are waiting, and never
        while she's busy answering (the model does one thing at a time)."""
        def run():
            while not self._stop.wait(every_s):
                try:
                    self.tick(busy, idle_s, batch)
                except Exception as exc:
                    log.warning("conversation folding failed: %s", exc)
        threading.Thread(target=run, name="conversation", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    # ----- kept across restarts -----
    def _save(self):
        if self.store is None:
            return
        with self.lock:
            self._sync()
            data = {"turns": [[{**m, "content": said(m)} for m in t] for t in self.turns], "times": self.times,
                    "folded": self.folded, "dropped": self.dropped, "summary": self.summary,
                    "previous": self.previous, "previous_ts": self.previous_ts, "backlog": self.backlog, "v": VERSION}
        try:
            self.store.set(KEY, json.dumps(data))
        except Exception as exc:
            log.debug("couldn't save the conversation: %s", exc)

    def _load(self):
        if self.store is None:
            return
        try:
            data = json.loads(self.store.get(KEY) or "{}")
        except (ValueError, TypeError):
            return
        turns, times = data.get("turns") or [], data.get("times") or []
        if len(turns) != len(times):
            turns, times = [], []
        self.turns, self.times = turns, [float(t) for t in times]
        self.folded = min(int(data.get("folded") or 0), len(self.turns))
        self.dropped = bool(data.get("dropped"))
        self.summary = str(data.get("summary") or "")
        self.previous, self.previous_ts = str(data.get("previous") or ""), float(data.get("previous_ts") or 0)
        self.backlog = list(data.get("backlog") or [])
        if int(data.get("v") or 1) < VERSION:      # written by the old prompt: may hold her metaphors as facts
            self.summary, self.previous, self.folded = "", "", 0
