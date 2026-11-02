"""Asking about the notes she isn't sure of (friend.py holds them in `about_pending`): one at a time,
at most once a day, like any other thing she says first. A yes makes it a fact, a no drops it, in
code. Anything else leaves it on the About you page until it expires."""
from __future__ import annotations

from .initiative import Moment
from .part import Part

ANSWER_WITHIN_S = 15 * 60


class FactCheck(Part):
    name = "factcheck"

    def __init__(self, store=None, friend=None, clock=None, **kw):
        super().__init__(store, **({"clock": clock} if clock else {}), **kw)
        self.friend = friend

    def moments(self, now: float) -> list:
        if self.friend is None or self.done(f"day:{self.today()}"):
            return []
        fresh = next((p for p in self.friend.pending() if not p.asked), None)
        if fresh is None:
            return []
        return [Moment("factcheck", f"You aren't sure you heard this right: {fresh.text}", key=f"fact:{fresh.id}",
                       part=self.name, line=f"Quick check, I might've misheard you. I wrote down: {fresh.text}. Did I get that right?")]

    def used(self, moment, now: float):
        super().used(moment, now)
        self.once(f"day:{self.today()}")
        pending_id = int(moment.key.split(":", 1)[1])
        self.friend.mark_asked(pending_id)
        self.put("waiting", {"id": pending_id, "t": now})

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        from .agent import NO, parse_yes_no

        waiting = self.get("waiting")
        if self.friend is None or not waiting or self.clock() - waiting.get("t", 0) > ANSWER_WITHIN_S:
            return []
        if parse_yes_no(user_text):
            self.put("waiting", None)
            self.friend.confirm(waiting["id"])
            return ["They said yes, you heard that note right, and it's saved now. Acknowledge it in a few words"]
        if NO.search(user_text or ""):
            self.put("waiting", None)
            self.friend.reject(waiting["id"])
            return ["They said you misheard that note, so you've thrown it away. Say sorry in a few words"]
        return []
