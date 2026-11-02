"""Games by voice: twenty questions, trivia (on anything, or on your course material) and
would-you-rather.

The model plays; the code keeps what the small model can't: the secret for twenty questions is
picked here (so it can't change its mind mid-game), the question count is kept here, and trivia
on a course gets real passages from your course files to ask about. Each turn of a game adds a
short note with the rules to the request. A game ends with "stop the game" / "I give up" or after
15 quiet minutes.
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass

IDLE_END_S = 15 * 60
SECRETS = {
    "animal": ["penguin", "octopus", "giraffe", "honeybee", "red panda", "dolphin", "owl", "hedgehog", "kangaroo", "shark"],
    "object": ["umbrella", "toothbrush", "headphones", "candle", "bicycle", "mirror", "backpack", "kettle", "guitar", "keyboard"],
    "food": ["pizza", "sushi", "mango", "popcorn", "pancakes", "taco", "dumplings", "watermelon", "ramen", "chocolate"],
    "place": ["the moon", "a library", "the Eiffel Tower", "a beach", "an airport", "a volcano", "the Sahara", "a hospital"],
}
KINDS = ("twenty_questions", "trivia", "would_you_rather")
OPENERS = [
    "would you rather be able to talk to animals, or speak every human language?",
    "would you rather never have to sleep, or never have to eat?",
    "would you rather live by the beach, or in a cabin in the mountains?",
    "would you rather have a rewind button, or a pause button for your life?",
    "would you rather always be ten minutes early, or always twenty minutes late?",
    "would you rather explore space, or the deep ocean?",
    "would you rather have free coffee forever, or free Wi-Fi everywhere?",
    "would you rather be famous for something silly, or unknown for something great?",
]
GIVE_UP = re.compile(r"\b(i give up|tell me (the answer|what it is)|what was it)\b", re.I)


@dataclass
class Game:
    kind: str
    topic: str = ""
    secret: str = ""
    category: str = ""
    questions: int = 0
    material: str = ""
    last: float = 0.0


class Games:
    def __init__(self, ctx, clock=time.time, rng=None):
        self.ctx, self.clock = ctx, clock
        self.rng = rng or random.Random()
        self.game: Game | None = None

    def start(self, kind: str, topic: str = "") -> str:
        kind = kind if kind in KINDS else "trivia"
        g = Game(kind, topic.strip(), last=self.clock())
        if kind == "twenty_questions":
            g.category = self.rng.choice(sorted(SECRETS))
            g.secret = self.rng.choice(SECRETS[g.category])
            self.game = g
            return f"Okay, I'm thinking of {'an' if g.category[0] in 'aeiou' else 'a'} {g.category}. You get twenty yes-or-no questions. Go!"
        if kind == "trivia":
            g.material = self._material(g.topic)
            self.game = g
            what = f" on {g.topic}" if g.topic else ""
            src = " from your course files" if g.material else ""
            return f"Trivia{what}{src}! I'll ask, you answer. Ready for the first one?"
        self.game = g
        return "Would you rather, let's go! Okay: " + self.rng.choice(OPENERS)

    def _material(self, topic: str) -> str:
        course = getattr(self.ctx, "course", None)
        if course is None or not topic:
            return ""
        try:
            hits = course.search(topic, k=6)
        except Exception:
            return ""
        if not hits:
            return ""
        picked = self.rng.sample(hits, min(3, len(hits)))
        return " | ".join(f"({h.file} {h.page}) {h.text[:300]}" for h in picked)

    def stop(self) -> str:
        g, self.game = self.game, None
        if g is None:
            return "We're not playing anything right now."
        if g.kind == "twenty_questions":
            return f"Game over! It was {g.secret}. Good game!"
        return "Good game! That was fun."

    def note(self, user_text: str) -> str | None:
        """The rules for this turn of the game, or None if no game is on."""
        g = self.game
        if g is None:
            return None
        now = self.clock()
        if now - g.last > IDLE_END_S:
            self.game = None
            return None
        g.last = now
        if g.kind == "twenty_questions":
            if GIVE_UP.search(user_text):
                self.game = None
                return f"They gave up: the answer was {g.secret}. Reveal it playfully and say good game"
            if user_text.rstrip().endswith("?") or re.match(r"(?i)\s*(is|are|does|do|can|was|has|would|could)\b", user_text):
                g.questions += 1
            left = 20 - g.questions
            return (f"You're playing twenty questions. Your secret is: {g.secret} (a {g.category}). Never say it unless they "
                    f"guess it or give up. Answer their question truthfully with yes, no or sometimes, plus a few playful "
                    f"words. Questions used: {g.questions}, left: {max(left, 0)}. If they guess it, celebrate; if none are "
                    f"left, reveal it")
        if g.kind == "trivia":
            src = (f" Ask only about this material from their course files: {g.material}" if g.material
                   else f" Topic: {g.topic or 'general knowledge'}, things you're sure of.")
            return ("You're playing trivia: if they just answered, say if it's right (give the right answer if not) and "
                    "keep a running score, then ask the next question. One question at a time, short." + src)
        return ("You're playing would-you-rather: react to their pick in a line with your own pick and why, then give "
                "a new would-you-rather (fun, not gross, not dark)")
