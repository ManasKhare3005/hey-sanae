"""Who the assistant is: persona.yaml (name, wake phrase, character sheet, speaking style, example
lines, notification lines, how chatty she is). Editable without touching code."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

import yaml

from .config import ROOT
from .tags import EMOTIONS, GESTURES

PERSONA_FILE = ROOT / "persona.yaml"


@dataclass
class Persona:
    name: str = "Sanae"
    wake_phrase: str = ""
    pronounce: dict = field(default_factory=dict)
    character: str = ""
    style: str = ""
    emotions: tuple = EMOTIONS
    gestures: tuple = GESTURES
    examples: list = field(default_factory=list)
    notify: dict = field(default_factory=dict)
    chattiness: str = "normal"
    initiative: dict = field(default_factory=dict)
    topics: list = field(default_factory=list)          # small-talk ideas when she starts a chat
    context: dict = field(default_factory=dict)         # window: read the window in front; blocklist: titles never read
    learn: bool = True                                  # pick up facts about the user from conversations
    support: dict = field(default_factory=dict)         # venting, taste, diary, breathing, reading, study; likes
    friend: dict = field(default_factory=dict)          # goals, wins, care... (friendship.py); each on unless false
    people: dict = field(default_factory=dict)          # name -> {about, style}: how she is with others ("~Name", guests.py)

    def prompt(self, user: str) -> str:
        """The character part of the system prompt (the tool rules come after it). Fixed text, so
        Ollama can keep reusing the processed prompt."""
        fill = {"name": self.name, "user": user}
        lines = [self.character.strip().format(**fill), "", "How you talk:", self.style.strip().format(**fill), "",
                 "Your replies are spoken aloud: no markdown, no lists, no emojis.",
                 "Start every final reply with one emotion tag: " + " ".join(f"[{e}]" for e in self.emotions)
                 + ". You may add one gesture tag right after it: " + " ".join(f"[{g}]" for g in self.gestures)
                 + ". Tags are never spoken and never go inside tool arguments. Pick the tag that matches your "
                 "feeling: [thinking] only while working something out, [neutral] for plain answers.", "", "Examples:"]
        for ex in self.examples:
            lines += [f"{user}: {ex['user']}", f"{self.name}: {ex['reply']}"]
        return "\n".join(lines)

    def emotion_prototypes(self) -> dict:
        """Example replies by emotion (for guessing an emotion when a reply has no tag)."""
        from .tags import parse

        out: dict[str, str] = {}
        for ex in self.examples:
            t = parse(ex["reply"], self.emotions, self.gestures)
            if t.emotion and t.emotion not in out:
                out[t.emotion] = t.text
        return out

    def line(self, kind: str, **fill) -> str:
        """A notification line in her voice ("Psst, {text}~")."""
        choices = self.notify.get(kind) or ["{text}"]
        try:
            return random.choice(choices).format(**{"text": "", "when": "", **fill})
        except (KeyError, IndexError):
            return fill.get("text", "")


def load_persona(path=None) -> Persona | None:
    path = path or PERSONA_FILE
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    known = Persona.__dataclass_fields__
    p = Persona(**{k: v for k, v in data.items() if k in known})
    p.emotions, p.gestures = tuple(p.emotions), tuple(p.gestures)
    return p
