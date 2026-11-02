"""A second look before she speaks first: is the line true, timely and worth saying?

The local model writes the lines she starts (initiative.model_line: openers, check-ins, texts
to the phone). It invents things ("21 hours? That's a record!", "did you see any cats on your
walk?"), misjudges the hour and ignores her own lessons. Before such a line is said, her slow
brain (cloudbrain.py, Claude) gets the same situation, notes and recent chat (filtered like
everything it sees) and answers keep / rewrite / drop:
  - keep: said as written;
  - rewrite: a fixed line in her voice (the [emotion] tag kept); a rewrite that would need a
    hidden name or detail back ("a friend", "[name]") isn't used: the line is dropped instead;
  - drop: not said (she'll find another moment).
Without the slow brain, during a hard moment, or when it fails, the line goes out as before.
Lines her code wrote whole (haiku, templates) aren't checked: only model-written ones.
"""
from __future__ import annotations

import datetime as dt
import logging
import re

log = logging.getLogger(__name__)
MAX_WORDS = 28
TAG = re.compile(r"^\s*((?:\[[a-z_]+\]\s*)+)")
HIDDEN = re.compile(r"\ba friend\b|\[name\]|\[number\]|\[link\]|\[email\]|\[hidden\]", re.I)

SCHEMA = {"type": "object",
          "properties": {"verdict": {"type": "string", "enum": ["keep", "rewrite", "drop"]},
                         "line": {"type": "string"}, "reason": {"type": "string"}},
          "required": ["verdict", "line", "reason"]}

SYSTEM = """{her} is an AI companion and close friend to the user. Her small local model just wrote a line she wants to say first, without being asked. You check it before she says it.

Keep it if every fact in it comes from what she knows (the situation, her notes, the recent chat), it fits the time of day, it doesn't break her lessons, and it doesn't repeat what she just said. Rewrite it if it's worth saying but invents something, assumes something she can't know (where they've been, what they did, how long), or misjudges the hour: same warmth and playful voice, under 25 words, start with the same [emotion] tag, only facts she knows. Drop it if there's nothing real to say. Names and some details were hidden for privacy ("a friend", [name], [number]); don't add any yourself."""

PROMPT = """Now: {now}
Situation: {situation}
Her notes: {notes}
Recent chat (oldest first):
{chat}

The line she wants to say: {line}"""


class FirstLineCheck:
    def __init__(self, brain, her: str = "Sanae"):
        self.brain, self.her = brain, her

    def __call__(self, line: str, situation: str, notes: str = "", chat: list[str] | None = None,
                 now: dt.datetime | None = None) -> str | None:
        if self.brain is None or not self.brain.available:
            return line
        chat = (chat or [])[-8:]
        cleaned = self.brain.clean_all([line, situation, notes, *chat])
        safe_line, sit, note = cleaned[0], cleaned[1], cleaned[2]
        if not safe_line or not sit:
            return line                                   # too private to check: as before
        d = now or dt.datetime.now()
        from .timesense import stamp

        prompt = PROMPT.format(now=stamp(d, year=False), situation=sit,
                               notes=note or "(none)", chat="\n".join(c for c in cleaned[3:] if c) or "(nothing yet today)",
                               line=safe_line)
        got = self.brain.ask("first line", SYSTEM.format(her=self.her), prompt, SCHEMA)
        if got is None:
            return line
        verdict = got.get("verdict")
        if verdict == "keep":
            return line
        if verdict == "drop":
            log.info("first line dropped (%s): %s", got.get("reason", ""), line)
            return None
        new = " ".join(str(got.get("line") or "").split()).strip().strip('"')
        if not new or len(TAG.sub("", new).split()) > MAX_WORDS or HIDDEN.search(TAG.sub("", new)):
            log.info("first line rewrite not usable, dropped: %s -> %s", line, new)
            return None
        if not TAG.match(new):
            m = TAG.match(line)
            new = (m.group(1).strip() + " " + new) if m else new
        new = self.brain.redactor.back(new)
        log.info("first line rewritten (%s): %s -> %s", got.get("reason", ""), line, new)
        return new
