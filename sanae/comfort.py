"""Comfort mode: when the user isn't okay, she stays with them like a friend would.

- Noticing: "I'm not okay", "I feel so alone", "I can't do this anymore" (low) and talk of not wanting
  to be here or hurting themselves (dark) are caught by phrases. A vague down message ("today was
  just bad, idk") can be checked by a short model call, which can only ever say "low": dark comes
  from the user's own clear words. Everyday phrases ("this homework is killing me", "I'm dead
  tired", "I give up" in a game) never count.
- While it lasts: no teasing or jokes, a soft concerned face and voice, no talking first in the
  background (no music remarks, games, small talk). The request carries a note with ways to
  comfort (persona.yaml support.comfort.ways, editable): stay, name the feeling, gentle questions,
  real things about them, small comforts, no advice unless asked. No helplines, no calling anyone.
  At the dark level she also asks, once, whether there's someone they could be with or text
  tonight; if the model leaves that out, a written line in her voice is added.
- Easing back: "I feel better", "thanks, that helped" -> warm and gentle for a couple of replies,
  then lighter, then her usual self after 30-60 min (random per time). Not okay again -> back to
  comfort.
- Next day, once: she asks how they're doing (initiative "care", or in her first reply if they talk
  first). "Better" -> back to normal; anything else -> balanced (warm, a little light, not too
  cheerful, not too serious) for the rest of that chat. Only the day is stored for this, never
  what was said; the check-in expires at the end of that day.

A day here runs 4 AM to 4 AM, like the diary.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import random
import re
import time
from typing import Callable

log = logging.getLogger(__name__)

NOT_OKAY = re.compile(
    r"\b(i'?m (really |just |so |honestly )?not (okay|ok|alright|fine|doing (well|good|great|okay|ok))|"
    r"not feeling (okay|ok|good|great|well|like myself)|"
    r"i feel (so |really |completely |kinda |kind of )?(empty|numb|hopeless|worthless|alone|lonely|broken|lost|"
    r"awful|terrible|horrible|like (a failure|crying|giving up|nobody cares|a burden))|"
    r"i'?m (so |really |just |completely |kinda )?(alone|lonely|hopeless|worthless|broken|miserable|a burden|"
    r"falling apart|a mess|not doing well|struggling)|"
    r"everything (sucks|is falling apart|feels (pointless|hopeless|heavy))|"
    r"i can'?t (do this|take (it|this)|cope|handle (it|this)|keep going)( anymore| any more)|"
    r"i hate my(self| life)|(nobody|no one) (cares|would care|would notice)|"
    r"i'?ve been (crying|really down|so down|feeling (really )?(down|low|empty))|"
    r"what'?s the point (anymore|of (anything|trying|it all|any of this))|"
    r"give up on (everything|life|myself))\b", re.I)
DARK = re.compile(
    r"\b(kill(ing)? myself(?! (laugh|lol|haha))|end (it all|my life)|"
    r"(want(ed)?|wanna|going) to die(?! (of|from|laughing|lol))|"
    r"don'?t want to (be here|live|exist|be alive|wake up)( anymore)?|"
    r"better off (dead|without me)|(hurt|harm|cut)(ing)? myself|self[- ]?harm|"
    r"suicid\w*(?! squad)|no reason to (live|be here)|not worth living)\b", re.I)
BETTER = re.compile(
    r"\b(i'?m (feeling |doing )?((a )?(bit|little|lot) |much |so much )?(better|okay now|ok now|alright now|"
    r"fine now|good now)|(feel|feeling) ((a )?(bit|little|lot) |much |so much |way )?better|"
    r"(that|this|you) (really )?helped|thanks?,? (that|this|you) (really )?(helped|means a lot)|"
    r"i'?ll be (okay|ok|fine|alright)|much better|i'?m okay now|feeling lighter)\b", re.I)
# Their answer to "how are you doing today?"
GOOD = re.compile(r"\b(better|good|great|fine|okay|ok|alright|well|not bad|pretty good|amazing)\b", re.I)
NOT_GOOD = re.compile(r"\b((not|n'?t|still) (really |that |so |too )?(good|great|okay|ok|fine|better|well|alright)|"
                      r"not really|meh|still (bad|sad|down|rough|low|the same)|same as yesterday|worse|"
                      r"could be better)\b", re.I)
SOMEONE = re.compile(r"\b(someone|somebody|anyone|anybody|a friend|friends|family|people (you|who)|"
                     r"text|call|be with|reach out)\b", re.I)

# ways that need things she actually knows about them (friend memory): left out when she knows nothing
KNOWN_ONLY = re.compile(r"\b(actually know|if you know|someone they care)\b", re.I)

COMFORT_S = 3 * 3600            # comfort fades to balanced after this long without talking
CARE_ANSWER_S = 30 * 60         # their reply within this long answers "how are you doing today?"
STAGE1_REPLIES = 2              # still very gentle for this many replies after "I feel better"
DAY_STARTS = 4                  # a day is 4 AM to 4 AM

DEFAULT_WAYS = [
    "Stay with them: say you're right here and not going anywhere",
    "Name what they feel instead of fixing it (\"that sounds really heavy\")",
    "Ask one gentle, open question at a time, and let them talk",
    "Remind them of something real and good about them that you actually know",
    "Mention someone they care about, softly, if you know of one",
    "Offer one small comfort as a short question, never pushed and never started without a yes: the breathing "
    "exercise, their music, water, a minute outside, a silly distraction, or just sitting together quietly",
    "No advice or fixes unless they ask for it",
]
DEFAULT_SOMEONE = ("And I really want you to have someone with you tonight too. Is there anyone you could text "
                   "or be with?")

NOTE_LOW = ("{user} isn't okay right now. Be their friend: gentle, warm, patient, and present. No teasing, no "
            "jokes, no cheerful tags; use [sad] or [neutral]. Short replies, plain words. Ways to comfort (pick what "
            "fits, one at a time, don't list them): {ways}. Don't mention helplines or professionals.")
NOTE_DARK = (" They've talked about not wanting to be here or hurting themselves. Take it seriously and stay calm "
             "and close. Once, gently, ask if there's someone they could be with or text tonight; then keep "
             "talking with them whatever they answer.")
NOTE_EASE1 = ("{user} said they feel better after a hard time. Be glad and warm, still gentle: no teasing yet, "
              "don't bring up your own likes, and don't bring the heavy stuff back up unless they do.")
NOTE_EASE2 = ("{user} is feeling better after a hard time earlier. Your warmth and a small smile can come back, "
              "a little gentle humour is fine; no teasing about what happened, don't bring up your own likes.")
NOTE_BALANCED = ("{user} had a hard time recently and isn't fully back to themselves. Be easy company: warm and a "
                 "little light, not too cheerful and not too serious; no teasing about it.")
NOTE_CARE = ("Yesterday was a hard day for {user} and you two talked it through. Somewhere in this reply, gently "
             "ask how they're doing today (one short question, no details about yesterday).")
CARE_SITUATION = ("Yesterday was a hard day for {user} and you two talked it through. Gently ask how they're "
                  "doing today: one short, warm question. Don't bring up details.")
NOTE_CARE_GOOD = "{user} says they're doing better today. Be genuinely glad, then just be your usual self."


def day_of(ts: float) -> str:
    """The 4 AM-to-4 AM day a moment belongs to."""
    return (dt.datetime.fromtimestamp(ts) - dt.timedelta(hours=DAY_STARTS)).date().isoformat()


def level_of(text: str) -> str | None:
    if DARK.search(text or ""):
        return "dark"
    if NOT_OKAY.search(text or ""):
        return "low"
    return None


class Comfort:
    """State: off | comfort | easing | balanced. Saved in kv "comfort" so a restart doesn't flip her
    back to cheerful mid-conversation; kv "comfort:care" holds only the day to check in after."""

    def __init__(self, memory=None, user: str = "them", settings: dict | None = None,
                 set_face: Callable[[str | None], None] = lambda face: None,
                 classify: Callable[[str], str | None] | None = None,
                 clock: Callable[[], float] = time.time, rng=None, knows_them: Callable[[], bool] = lambda: True):
        s = settings or {}
        self.mem, self.user, self.set_face, self.classify = memory, user, set_face, classify
        self.clock, self.rng = clock, rng or random.Random()
        self.knows_them = knows_them    # any friend facts? without them "something real about them" got invented
        self.ways = list(s.get("ways") or DEFAULT_WAYS)
        self.someone_line = str(s.get("someone_line") or DEFAULT_SOMEONE)
        lo, hi = (s.get("ease_min") or [30, 60])[:2]
        self.ease_range = (float(lo) * 60, float(hi) * 60)
        self.state, self.level = "off", None
        self.since = self.last_talk = self.ease_start = 0.0
        self.ease_s = self.ease_range[0]
        self.replies_since_ease = 0
        self.someone_asked = False
        self.care_asked_at = 0.0
        self._load()

    # ----- kept across restarts -----
    def _load(self):
        raw = self.mem.get("comfort") if self.mem is not None else None
        try:
            d = json.loads(raw) if raw else {}
        except ValueError:
            d = {}
        self.state = d.get("state", "off")
        self.level = d.get("level")
        self.since, self.last_talk = float(d.get("since", 0)), float(d.get("last_talk", 0))
        self.ease_start, self.ease_s = float(d.get("ease_start", 0)), float(d.get("ease_s", self.ease_range[0]))
        self.replies_since_ease = int(d.get("replies", 0))
        self.someone_asked = bool(d.get("someone_asked", False))
        self._expire()
        if self.state != "off":
            self.set_face(self.face)

    def _save(self):
        if self.mem is not None:
            self.mem.set("comfort", json.dumps({
                "state": self.state, "level": self.level, "since": self.since, "last_talk": self.last_talk,
                "ease_start": self.ease_start, "ease_s": self.ease_s, "replies": self.replies_since_ease,
                "someone_asked": self.someone_asked}))

    def _care(self) -> dict:
        raw = self.mem.get("comfort:care") if self.mem is not None else None
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            return {}

    def _set_care(self, d: dict):
        if self.mem is not None:
            self.mem.set("comfort:care", json.dumps(d))

    # ----- state changes -----
    def _to(self, state: str, level: str | None = None):
        now = self.clock()
        if state == "comfort":
            if self.state != "comfort":
                self.since = now
                self.someone_asked = False
            stays_dark = self.state == "comfort" and self.level == "dark"
            self.level = "dark" if stays_dark else (level or "low")
            self._set_care({"day": day_of(now)})                 # check in tomorrow (only the day is kept)
            self._mark_hard_day(now)
        elif state == "easing":
            from .mood import mark_day

            if self.mem is not None:
                mark_day(self.mem, "better", now)                    # the diary says they felt better by the end
            self.ease_start = now
            self.ease_s = self.rng.uniform(*self.ease_range)
            self.replies_since_ease = 0
        elif state == "off":
            self.level = None
        if state != self.state:
            log.info("comfort: %s -> %s", self.state, state)
        self.state = state
        self._save()
        self.set_face(self.face if state != "off" else None)

    def _mark_hard_day(self, now: float):
        if self.mem is None:
            return
        from .mood import mark_day

        mark_day(self.mem, "hard", now)

    def _expire(self):
        """Time passing: easing ends after its 30-60 min, comfort fades to balanced after hours of
        silence, balanced ends with the day."""
        now = self.clock()
        if self.state == "easing" and now - self.ease_start >= self.ease_s:
            self._to("off")
        if self.state == "comfort" and self.last_talk and now - self.last_talk >= COMFORT_S:
            self._to("balanced")
        if self.state == "balanced" and self.last_talk and day_of(now) != day_of(self.last_talk):
            self._to("off")

    # ----- per message -----
    def hear(self, text: str, word_mood: str | None = None) -> list[str]:
        """The user said something: update the state and return notes for this request."""
        now = self.clock()
        self._expire()
        self.last_talk = now                       # before any change: expiry counts from this message
        notes: list[str] = []
        level = level_of(text)
        if level is None and self.state == "off" and word_mood == "down" \
                and self.classify is not None and len(text.split()) >= 6:
            try:
                level = "low" if self.classify(text) == "low" else None    # the model can never say "dark"
            except Exception as exc:
                log.debug("comfort check failed: %s", exc)
        care = self._care()
        answering = bool(self.care_asked_at) and now - self.care_asked_at < CARE_ANSWER_S
        self.care_asked_at = 0.0
        if level:
            self._to("comfort", level)
        elif answering:                                          # their answer to "how are you today?"
            if GOOD.search(text) and not NOT_GOOD.search(text):
                self._to("off")
                notes.append(NOTE_CARE_GOOD.format(user=self.user))
            else:
                self._to("balanced")
        elif BETTER.search(text) and self.state in ("comfort", "balanced"):
            self._to("easing")
        elif self.state == "comfort" and NOT_GOOD.search(text):
            pass                                                 # still not okay: stay
        if not level and self.care_due(now) and not care.get("asked"):
            notes.append(NOTE_CARE.format(user=self.user))         # they talked first today: ask in this reply
            self.care_asked(now)
        self._save()
        note = self.note()
        return ([note] if note else []) + notes

    def note(self) -> str | None:
        u = self.user
        if self.state == "comfort":
            ways = self.ways if self.knows_them() else [w for w in self.ways if not KNOWN_ONLY.search(w)]
            ways = "; ".join(self.rng.sample(ways, min(4, len(ways))))
            text = NOTE_LOW.format(user=u, ways=ways)
            if self.level == "dark" and not self.someone_asked:
                text += NOTE_DARK
            return text
        if self.state == "easing":
            return (NOTE_EASE1 if self.stage == 1 else NOTE_EASE2).format(user=u)
        if self.state == "balanced":
            return NOTE_BALANCED.format(user=u)
        return None

    def after_reply(self, user_text: str, answer: str) -> str | None:
        """After her reply: count easing replies; at the dark level make sure she asked, once,
        whether there's someone they could be with (the small model can leave it out)."""
        if self.state == "easing":
            self.replies_since_ease += 1
            self._save()
            return None
        if self.state != "comfort" or self.level != "dark" or self.someone_asked:
            return None
        self.someone_asked = True
        self._save()
        return None if SOMEONE.search(answer or "") else self.someone_line

    @property
    def stage(self) -> int:
        """Easing: 1 = still gentle, 2 = warmth coming back."""
        if self.replies_since_ease < STAGE1_REPLIES and self.clock() - self.ease_start < self.ease_s * 0.3:
            return 1
        return 2

    @property
    def serious(self) -> bool:
        """Comfort proper: other request notes (teasing, games, her mood, venting) stand down."""
        self._expire()
        return self.state == "comfort"

    def holding_back(self) -> bool:
        """She doesn't start conversations in the background (only the next-day check-in)."""
        self._expire()
        return self.state in ("comfort", "easing")

    @property
    def face(self) -> str:
        return {"comfort": "sad", "easing": "neutral", "balanced": "neutral"}.get(self.state, "neutral")

    def calm(self, emotion: str | None, gestures: list[str]) -> tuple[str | None, list[str]]:
        """Her tags, toned down to fit: no laughing or cheering while they're not okay."""
        self._expire()
        if self.state == "comfort":
            if emotion in ("happy", "laugh", "surprised", "shy"):
                emotion = "sad"
            return emotion, [g for g in gestures if g == "nod"]
        if self.state == "easing" and self.stage == 1 and emotion in ("laugh", "surprised"):
            emotion = "happy"
        if self.state in ("easing", "balanced"):
            gestures = [g for g in gestures if g != "cheer"]
        return emotion, gestures

    def private_turn(self, turn_id: int):
        """A turn logged while they weren't okay: friend memory never learns from it (no follow-ups
        beyond the one next-day check-in)."""
        if self.mem is None or self.state not in ("comfort", "easing"):
            return
        ids = json.loads(self.mem.get("comfort:turns") or "[]")
        self.mem.set("comfort:turns", json.dumps([*ids, turn_id][-300:]))

    # ----- the next-day check-in -----
    def care_due(self, now: float | None = None) -> bool:
        now = self.clock() if now is None else now
        self._expire()
        care = self._care()
        if not care.get("day") or care.get("asked"):
            return False
        return day_of(now) == (dt.date.fromisoformat(care["day"]) + dt.timedelta(days=1)).isoformat()

    def care_asked(self, now: float | None = None):
        now = self.clock() if now is None else now
        d = self._care()
        d["asked"] = True                                          # once only
        self._set_care(d)
        self.care_asked_at = now

    def line_note(self) -> str | None:
        """For lines she starts herself (an upcoming class while easing...): the same tone."""
        return self.note() if self.state != "off" else None


CLASSIFY_PROMPT = """Does this message from {user} say they are not okay emotionally (hurting, hopeless, very low, falling apart), beyond an ordinary bad mood or tiredness? Answer with one word: low or no.

Message: {text}"""


def model_classifier(llm, model: str, user: str) -> Callable[[str], str | None]:
    """A one-word check for vague messages ("idk today was just bad and I'm tired of everything")."""
    def classify(text: str) -> str | None:
        reply = llm.chat(model, [{"role": "user", "content": CLASSIFY_PROMPT.format(user=user, text=text[:500])}],
                         options={"temperature": 0, "num_predict": 3})
        return "low" if (reply.content or "").strip().lower().startswith("low") else None
    return classify
