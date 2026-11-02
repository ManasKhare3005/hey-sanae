"""Emotion and gesture tags in replies: "[happy][wave] Heyy!" -> spoken "Heyy!", the avatar smiles
and waves. The model is asked to start every reply with one emotion tag (persona.yaml lists them);
it sometimes forgets, puts it at the end or invents one, so parsing is forgiving and a cheap guess
fills in when there's no tag at all."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

EMOTIONS = ("neutral", "happy", "shy", "laugh", "thinking", "sad", "surprised", "sleepy")
GESTURES = ("wave", "nod", "cover_face", "cheer")
SYNONYMS = {
    "joy": "happy", "joyful": "happy", "excited": "happy", "smile": "happy", "smiling": "happy", "cheerful": "happy",
    "playful": "happy", "teasing": "happy", "glad": "happy", "love": "happy", "warm": "happy",
    "blush": "shy", "blushing": "shy", "embarrassed": "shy", "flustered": "shy", "nervous": "shy",
    "laughing": "laugh", "giggle": "laugh", "giggles": "laugh", "lol": "laugh", "haha": "laugh", "amused": "laugh",
    "think": "thinking", "curious": "thinking", "hmm": "thinking", "confused": "thinking", "pondering": "thinking",
    "sorry": "sad", "upset": "sad", "worried": "sad", "concerned": "sad", "sympathetic": "sad", "disappointed": "sad",
    "shocked": "surprised", "surprise": "surprised", "wow": "surprised", "amazed": "surprised",
    "tired": "sleepy", "yawn": "sleepy", "calm": "neutral", "serious": "neutral",
    "waving": "wave", "nodding": "nod", "hide_face": "cover_face", "facepalm": "cover_face", "cheering": "cheer",
    "yay": "cheer", "celebrate": "cheer",
}
TAG = re.compile(r"\[\s*([A-Za-z][A-Za-z _-]{0,20})\s*\]")
# Roleplay asides the model sometimes adds: *giggles*, *tilts head*
ASIDE = re.compile(r"\*[^*\n]{1,40}\*")
# ...which start with an action ("giggles", "tilts head"); any other *word* mid-sentence is emphasis
ACTION = re.compile(r"(giggle|laugh|smile|grin|wink|sigh|blush|nod|wave|tilt|pout|yawn|hug|lean|poke|shrug|gasp"
                    r"|chuckle|smirk|hum|stretch|look|glance|cheer|clap|bounce|hide|cover|blink|whisper|sniff"
                    r"|nuzzle|wiggle|twirl|sip|spin|jump|hop|grab|giggling|laughing|smiling)(s|es)?\b", re.I)
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")


@dataclass
class Tagged:
    text: str                          # what to say / show, tags removed
    emotion: str | None = None         # None: the reply had no (known) emotion tag
    gestures: list[str] = field(default_factory=list)


def _name(raw: str) -> str:
    n = re.sub(r"[\s-]+", "_", raw.strip().lower())
    return SYNONYMS.get(n, n)


def unwrap_emphasis(text: str, before: str = "") -> str:
    """'I was just *thinking* about you' is emphasis, not an aside: keep the word. A *...* counts
    as emphasis when it sits mid-sentence (after a word or comma); `before` = text already sent
    when this is a streamed piece."""
    def keep(m: re.Match) -> str:
        inner = m.group(0).strip("* ")
        prev = (before + text[: m.start()]).rstrip()
        mid = prev and (prev[-1].isalnum() or prev[-1] in ",'’")
        return inner if mid and not ACTION.match(inner) else m.group(0)

    return ASIDE.sub(keep, text or "")


def parse(text: str, emotions=EMOTIONS, gestures=GESTURES) -> Tagged:
    found_emotion, found_gestures = None, []
    text = unwrap_emphasis(text or "")
    for m in TAG.finditer(text or ""):
        n = _name(m.group(1))
        if n in emotions and found_emotion is None:
            found_emotion = n
        elif n in gestures and n not in found_gestures:
            found_gestures.append(n)
    clean = TAG.sub("", text or "")
    for m in ASIDE.finditer(clean):                 # *giggles* -> laugh, if there was no tag
        n = _name(m.group(0).strip("* ").split()[0])
        if found_emotion is None and n in emotions:
            found_emotion = n
    clean = EMOJI.sub("", ASIDE.sub("", clean))
    clean = re.sub(r"[ \t]{2,}", " ", clean)
    clean = re.sub(r"\s+([,.!?])", r"\1", clean).strip()
    return Tagged(clean, found_emotion, found_gestures)


CUES = [
    ("laugh", re.compile(r"\b(haha+|hehe+|lol|lmao)\b", re.I)),
    ("sad", re.compile(r"\b(sorry|aw+|oh no|that stinks|that sucks|rough|unfortunately|couldn'?t|failed)\b", re.I)),
    ("surprised", re.compile(r"\b(wait,? what|whoa|wow|no way|really\?)", re.I)),
    ("sleepy", re.compile(r"\b(sleepy|tired|yawn|bedtime|so late)\b", re.I)),
    ("thinking", re.compile(r"\b(hmm+|let me think|i think|maybe|not sure)\b", re.I)),
    ("happy", re.compile(r"\b(yay|great|awesome|nice|done|perfect|love|glad|hey+|hi+)\b|!", re.I)),
]


def guess(text: str, embed: Callable | None = None, prototypes: dict | None = None) -> str:
    """An emotion for a reply that came without a tag: wording cues first, then (if given) the
    closest of the persona's example replies by meaning; neutral when nothing stands out."""
    for emotion, pattern in CUES:
        if pattern.search(text or ""):
            return emotion
    if embed is not None and prototypes:
        try:
            import numpy as np

            names = list(prototypes)
            vecs = embed([text] + [prototypes[n] for n in names])
            sims = vecs[1:] @ vecs[0]
            best = int(np.argmax(sims))
            if sims[best] >= 0.6:
                return names[best]
        except Exception:
            pass
    return "neutral"


class TagFilter:
    """Removes tags from a reply while it streams in, piece by piece, and reports the first
    emotion/gestures as soon as they're complete (so the face changes before the voice starts)."""

    def __init__(self, out: Callable[[str | None], None], on_tags: Callable[[Tagged], None] | None = None,
                 emotions=EMOTIONS, gestures=GESTURES):
        self.out, self.on_tags = out, on_tags
        self.emotions, self.gestures = emotions, gestures
        self._held = ""
        self._told = False
        self._sent = ""                         # the end of what went out (emphasis vs aside)

    def __call__(self, piece: str | None):
        if piece is None:                      # a new model call
            self._held, self._told, self._sent = "", False, ""
            self.out(None)
            return
        text = self._held + piece
        self._held = ""
        cut = text.rfind("[")
        if cut != -1 and "]" not in text[cut:] and len(text) - cut < 24:
            text, self._held = text[:cut], text[cut:]          # maybe the start of a tag: wait
        star = text.rfind("*")
        if text.count("*") % 2 and len(text) - star < 44:
            text, self._held = text[:star], text[star:] + self._held   # an aside or *emphasis* still open: wait
        text = unwrap_emphasis(text, self._sent)
        tagged = parse_keep_space(text, self.emotions, self.gestures)
        if (tagged.emotion or tagged.gestures) and not self._told and self.on_tags is not None:
            self._told = True
            self.on_tags(tagged)
        if tagged.text:
            self._sent = (self._sent + tagged.text)[-40:]
            self.out(tagged.text)


def parse_keep_space(text: str, emotions=EMOTIONS, gestures=GESTURES) -> Tagged:
    """parse() for a fragment: keeps the spacing at the ends so streamed pieces join up."""
    t = parse(text, emotions, gestures)
    stripped = EMOJI.sub("", ASIDE.sub("", TAG.sub("", text)))
    if not stripped.strip():
        # a lone " " between two streamed words must stay ("doinggreat" made the end check fail and
        # the whole reply was spoken a second time)
        return Tagged(stripped if not TAG.search(text) and stripped else "", t.emotion, t.gestures)
    lead = "" if TAG.match(text.lstrip()) else stripped[: len(stripped) - len(stripped.lstrip())]
    trail = stripped[len(stripped.rstrip()):]
    return Tagged(lead + t.text + trail, t.emotion, t.gestures)
