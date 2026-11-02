"""Learning Japanese together: she's been picking up a word a day (herlife.py); now you learn with her.

  - "Teach me some Japanese" / "Japanese lesson": up to three new words from the ones she's learned,
    then a quick quiz (both ways: "what does neko mean?" / "how do you say rain?").
  - "Quiz me on Japanese": just the words that are due (spaced repetition: a word you get right
    comes back later and later; a miss comes back today).
  - Then your turn to quiz her. She knows her words, but now and then she gets one wrong on purpose
    so you can correct her ("no, it's sky!" -> "ugh, you're right, thanks sensei").
  - Some evenings she asks if you're up for three words.
Everything is graded in code, not by the model. Your deck is on the phone (Us tab) with flashcards
that work offline.
"""
from __future__ import annotations

import datetime as dt
import difflib
import random
import re
import time

from .herlife import WORDS
from .initiative import Moment
from .part import Part

SCHEMA = """
CREATE TABLE IF NOT EXISTS jp_deck (
    word TEXT PRIMARY KEY, meaning TEXT NOT NULL, added TEXT NOT NULL, box INTEGER NOT NULL DEFAULT 0,
    due TEXT NOT NULL, right INTEGER NOT NULL DEFAULT 0, wrong INTEGER NOT NULL DEFAULT 0, last TEXT NOT NULL DEFAULT '');
"""
GAPS = [0, 1, 2, 4, 7, 14, 30]          # days until a word comes back, by box
LESSON = re.compile(r"\b(teach me (some |a little |more )?japanese|japanese (lesson|class|words?)|let'?s (do|learn|practi[cs]e) "
                    r"(some )?japanese|learn japanese (with you|together)|new japanese words?)\b", re.I)
QUIZ = re.compile(r"\b(quiz me on (my |the |our )?japanese|japanese quiz|test me on (my |the )?japanese|"
                  r"(practi[cs]e|review) (my |our )?japanese( words)?)\b", re.I)
STOP = re.compile(r"\b(stop|enough|that'?s enough|i'?m done|done with japanese|no more|let'?s stop|end the (quiz|lesson))\b", re.I)
HER_ASK = re.compile(r"\bwhat(?:'?s| is| does)\s+[\"']?(?P<word>[a-z]+)[\"']?\s*(?:mean|in english)?\b|"
                     r"\bhow (?:do you|would you|do i) say\s+[\"']?(?P<en>[a-z' ]+?)[\"']?(?: in japanese)?\W*$", re.I)
CORRECT = re.compile(r"\b(no+|nope|wrong|not quite|that'?s not (it|right)|actually it'?s|it'?s actually|incorrect|"
                     r"try again|close but)\b", re.I)
SKIP = re.compile(r"^\W*(i don'?t know|idk|no idea|pass|skip|no clue|give up|tell me)\W*$", re.I)
NOISE = {"the", "a", "an", "to", "it", "is", "its", "it's", "means", "mean", "like", "um", "uh", "i", "think", "maybe"}


def _norm(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z']+", text.lower()) if w not in NOISE]


def meaning_ok(said: str, meaning: str) -> bool:
    """'it's cat' is 'cat'; 'good morning' is 'good morning'; a close spelling counts."""
    want = _norm(meaning)
    got = _norm(said)
    if not want or not got:
        return False
    if all(any(difflib.SequenceMatcher(None, w, g).ratio() >= 0.8 for g in got) for w in want):
        return True
    return difflib.SequenceMatcher(None, " ".join(want), " ".join(got)).ratio() >= 0.8


def word_ok(said: str, word: str) -> bool:
    got = "".join(_norm(said)) or said.lower()
    return difflib.SequenceMatcher(None, got.replace(" ", ""), word).ratio() >= 0.8 or word in got


class Japanese(Part):
    name = "japanese"

    def __init__(self, store=None, clock=time.time, life=None, idle=lambda: 0.0, rng=None, wrong_rate: float = 0.2):
        super().__init__(store, clock)
        self.life, self.idle = life, idle
        self.rng = rng or random.Random()
        self.wrong_rate = wrong_rate
        self._schema(SCHEMA)

    # ----- the deck -----
    def her_words(self) -> list[tuple[str, str]]:
        """The words she's learned so far (one a day since she started), oldest first."""
        day = self.life.day() if self.life is not None else len(WORDS) - 1
        n = min(len(WORDS), day + 1)
        start = (day + 1 - n) % len(WORDS)
        return [WORDS[(start + i) % len(WORDS)] for i in range(n)]

    def deck(self) -> list[dict]:
        return self._rows("SELECT * FROM jp_deck ORDER BY added, word")

    def due(self) -> list[dict]:
        return self._rows("SELECT * FROM jp_deck WHERE due <= ? ORDER BY box, due, word", (self.today(),))

    def add_new(self, n: int = 3) -> list[dict]:
        have = {r["word"] for r in self.deck()}
        fresh = [(w, m) for w, m in reversed(self.her_words()) if w not in have][:n]
        for w, m in fresh:
            self._exec("INSERT OR IGNORE INTO jp_deck (word, meaning, added, due) VALUES (?,?,?,?)", (w, m, self.today(), self.today()))
        return [r for r in self.deck() if r["word"] in {w for w, _ in fresh}]

    def grade(self, word: str, right: bool, day: str | None = None):
        rows = self._rows("SELECT * FROM jp_deck WHERE word = ?", (word,))
        if not rows:
            return
        r = rows[0]
        box = min(len(GAPS) - 1, r["box"] + 1) if right else 0
        d = dt.date.fromisoformat(day or self.today())
        self._exec("UPDATE jp_deck SET box = ?, due = ?, right = right + ?, wrong = wrong + ?, last = ? WHERE word = ?",
                   (box, (d + dt.timedelta(days=GAPS[box])).isoformat(), int(right), int(not right), d.isoformat(), word))
        days = self.get("days", [])
        if d.isoformat() not in days:
            self.put("days", [*days, d.isoformat()][-60:])

    def streak(self) -> int:
        days = set(self.get("days", []))
        d = self.now().date()
        if d.isoformat() not in days:
            d -= dt.timedelta(days=1)
        n = 0
        while d.isoformat() in days:
            n += 1
            d -= dt.timedelta(days=1)
        return n

    # ----- a lesson / quiz (state in kv, graded here) -----
    def lesson(self, kind: str = "lesson") -> str:
        new = self.add_new(3) if kind == "lesson" else []
        due = [r for r in self.due() if r["word"] not in {n["word"] for n in new}]
        queue = [r["word"] for r in new] + [r["word"] for r in due][: max(2, 5 - len(new))]
        if not queue:
            if kind == "quiz":
                new = self.add_new(3)
                queue = [r["word"] for r in new]
            if not queue:
                return "You're all caught up on our words! I'll have a new one tomorrow."
        self.put("session", {"mode": "quiz", "queue": queue, "i": 0, "right": 0, "asked": None, "her_turns": 0,
                             "t": self.clock()})
        intro = ""
        if new:
            intro = "New words: " + ", ".join(f"{r['word']} means {r['meaning']}" for r in new) + ". "
        return intro + "Quiz time! " + self._ask()

    def session(self) -> dict | None:
        s = self.get("session")
        return s if s and self.clock() - s["t"] < 20 * 60 else None

    def _meaning(self, word: str) -> str:
        return dict(WORDS).get(word, "")

    def _ask(self) -> str:
        s = self.get("session")
        word = s["queue"][s["i"]]
        reverse = self.rng.random() < 0.4
        s["asked"] = {"word": word, "reverse": reverse}
        s["t"] = self.clock()
        self.put("session", s)
        return f"How do you say \"{self._meaning(word)}\" in Japanese?" if reverse else f"What does \"{word}\" mean?"

    def answer(self, said: str) -> str:
        s = self.session()
        if s is None or s["mode"] != "quiz" or not s.get("asked"):
            return "We're not in a quiz right now. Want one?"
        word, reverse = s["asked"]["word"], s["asked"]["reverse"]
        meaning = self._meaning(word)
        right = not SKIP.match(said) and (word_ok(said, word) if reverse else meaning_ok(said, meaning))
        self.grade(word, right)
        s["right"] += int(right)
        s["i"] += 1
        self.put("session", s)
        out = (f"Yes! {word} is {meaning}." if right else f"{'Close! ' if not SKIP.match(said) else ''}It's {word}, {meaning}.")
        if s["i"] < len(s["queue"]):
            return out + " " + self._ask()
        s = self.get("session")
        s.update(mode="her_turn", asked=None, t=self.clock())
        self.put("session", s)
        return out + f" You got {s['right']} of {len(s['queue'])}! Your turn: quiz me on any of our words."

    def her_answer(self, question: str) -> str:
        s = self.session()
        known = dict(self.her_words())
        m = HER_ASK.search(question)
        if m is None:
            return "Ask me like \"what does sora mean?\" or \"how do you say rain?\""
        if m.group("word"):
            word = m.group("word").lower()
            if word not in known:
                return f"Hmm, \"{word}\" isn't one of mine yet. Teach me?"
            meaning = known[word]
            wrong = self.rng.random() < self.wrong_rate
            if wrong:
                others = [v for k, v in known.items() if k != word]
                guess = self.rng.choice(others) if others else meaning
                self.put("mistake", {"word": word, "said": guess, "t": self.clock()})
                said = f"Ooh, I know this one... {word} means {guess}!"
            else:
                said = f"Easy! {word} means {meaning}."
        else:
            en = m.group("en").strip().lower()
            back = {v.lower(): k for k, v in known.items()}
            if en not in back:
                return f"I haven't learned how to say \"{en}\" yet. Teach me?"
            said = f"That's {back[en]}!"
        if s is not None:
            s["her_turns"] += 1
            s["t"] = self.clock()
            self.put("session", s)
            if s["her_turns"] >= 3:
                self.put("session", None)
                said += " Okay, good practice. Same time tomorrow?"
        return said

    def corrected(self) -> str:
        mk = self.get("mistake")
        self.put("mistake", None)
        if not mk:
            return "Oh! Thanks for checking."
        right = dict(WORDS).get(mk["word"], "")
        n = self.get("corrections", 0) + 1
        self.put("corrections", n)
        return f"Ugh, you're right, {mk['word']} is {right}, not {mk['said']}. Thanks, sensei."

    def stop(self) -> str:
        s = self.session()
        self.put("session", None)
        if s and s["mode"] == "quiz" and s["i"]:
            return f"Okay! You got {s['right']} of {s['i']}. Good practice."
        return "Okay, Japanese is done for today."

    # ----- in conversation -----
    def route(self, user_text: str, last_reply: str = "") -> tuple[str, dict] | None:
        t = user_text.strip()
        if QUIZ.search(t):
            return "japanese_lesson", {"kind": "quiz"}
        if LESSON.search(t):
            return "japanese_lesson", {"kind": "lesson"}
        mk = self.get("mistake")
        if mk and self.clock() - mk["t"] < 120 and (CORRECT.search(t) or meaning_ok(t, dict(WORDS).get(mk["word"], "@"))):
            return "japanese_corrected", {}
        s = self.session()
        if s is None:
            return None
        if STOP.search(t) and len(t.split()) <= 6:
            return "japanese_stop", {}
        if s["mode"] == "quiz" and s.get("asked") and "?" not in t:
            return "japanese_answer", {"answer": t}
        if s["mode"] == "her_turn" and HER_ASK.search(t):
            return "japanese_her_turn", {"question": t}
        return None

    def moments(self, now: float) -> list[Moment]:
        if self.store is None:
            return []
        d = dt.datetime.fromtimestamp(now)
        key = f"invite:{d.date().isoformat()}"
        if not (15 <= d.hour < 22) or self.done(key) or self.idle() > 120 or d.date().isoformat() in self.get("days", []):
            return []
        if self.rng.random() > 0.02:            # a few chances an evening (ticks are 30 s)
            return []
        due = len(self.due())
        fresh = len([w for w, _ in self.her_words() if w not in {r["word"] for r in self.deck()}])
        if due < 2 and fresh == 0:
            return []
        word = self.life.word_today() if self.life is not None else None
        return [Moment("japanese", "Invite {user} to a quick Japanese practice with you (three words, you're learning "
                                   "together)" + (f"; you could tease them with today's word: {word}" if word else "") +
                                   ". If they say yes they can say \"teach me some Japanese\". One playful line.",
                       key=key, part=self.name)]

    def status(self) -> dict:
        deck = self.deck()
        today = self.today()
        return {"deck": [{"word": r["word"], "meaning": r["meaning"], "box": r["box"], "due": r["due"] <= today,
                          "right": r["right"], "wrong": r["wrong"]} for r in deck],
                "due": sum(1 for r in deck if r["due"] <= today), "streak": self.streak(),
                "corrections": self.get("corrections", 0),
                "her_word": (lambda w: {"word": w[0], "meaning": w[1]})(self.her_words()[-1]) if self.her_words() else None}

    def review(self, results: list[dict]) -> int:
        """Flashcards from the phone: [{word, right, day}]."""
        n = 0
        for r in results:
            if r.get("word"):
                self.grade(str(r["word"]), bool(r.get("right")), str(r.get("day") or "") or None)
                n += 1
        return n
