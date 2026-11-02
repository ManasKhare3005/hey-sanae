import datetime as dt
import random
from types import SimpleNamespace

from sanae.japanese import Japanese, meaning_ok, word_ok
from sanae.memory import MemoryStore
from tests.test_journal import Clock, Embed


def make(day=5, wrong_rate=0.0, seed=1):
    clock = Clock(dt.datetime(2026, 10, 20, 19, 0))
    life = SimpleNamespace(day=lambda: day, word_today=lambda: "today's word")
    return Japanese(MemoryStore(":memory:", Embed()), clock=clock, life=life, idle=lambda: 10,
                    rng=random.Random(seed), wrong_rate=wrong_rate), clock


def test_grading_in_code():
    assert meaning_ok("it's cat", "cat") and meaning_ok("umm good mornin", "good morning")
    assert not meaning_ok("dog", "cat")
    assert word_ok("neko", "neko") and word_ok("nekko", "neko") and not word_ok("ame", "neko")


def test_lesson_quiz_then_her_turn():
    j, clock = make(day=5)
    assert j.route("teach me some japanese") == ("japanese_lesson", {"kind": "lesson"})
    out = j.lesson("lesson")
    assert out.startswith("New words: ") and "Quiz time!" in out
    s = j.session()
    assert len(s["queue"]) == 3                   # three new words, nothing due yet
    for _ in range(3):
        asked = j.session()["asked"]
        word = asked["word"]
        meaning = dict((r["word"], r["meaning"]) for r in j.deck())[word]
        assert j.route("hmm") == ("japanese_answer", {"answer": "hmm"})
        reply = j.answer(word if asked["reverse"] else f"it's {meaning}")
        assert reply.startswith("Yes!")
    assert "3 of 3" in reply and "Your turn" in reply
    assert j.route("what does neko mean?") == ("japanese_her_turn", {"question": "what does neko mean?"})
    assert j.her_answer("what does neko mean?") == "Easy! neko means cat."
    assert j.her_answer("how do you say rain?") == "That's ame!"
    assert all(r["box"] == 1 for r in j.deck()) and j.streak() == 1
    assert j.status()["due"] == 0                 # all right: back tomorrow


def test_she_slips_so_you_can_correct_her():
    j, clock = make(day=5, wrong_rate=1.0)
    j.lesson("lesson")
    j.put("session", {**j.session(), "mode": "her_turn"})
    said = j.her_answer("what does neko mean?")
    assert "neko means" in said and "cat" not in said
    assert j.route("no, it's cat!") == ("japanese_corrected", {})
    assert j.corrected().startswith("Ugh, you're right, neko is cat")
    assert j.status()["corrections"] == 1


def test_misses_come_back_and_phone_flashcards():
    j, clock = make(day=5)
    j.lesson("lesson")
    j.stop()
    first = j.deck()[0]["word"]
    j.review([{"word": first, "right": False}, {"word": j.deck()[1]["word"], "right": True}])
    due = [r["word"] for r in j.due()]
    assert first in due and len(due) == 2         # the miss and the untouched one; the right one waits
    assert j.route("quiz me on japanese") == ("japanese_lesson", {"kind": "quiz"})
    assert j.route("quiz me on history") is None
    from sanae.agent import direct_route

    assert direct_route("quiz me on japanese", {"play_game": 1}) is None
