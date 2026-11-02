import datetime as dt
from types import SimpleNamespace

import numpy as np

from sanae.journal import Journal
from sanae.memory import MemoryStore


class Embed:
    def embed(self, texts):
        return np.ones((len(texts), 4), dtype="float32") / 2


class Clock:
    def __init__(self, d):
        self.t = d.timestamp()

    def __call__(self):
        return self.t

    def to(self, d):
        self.t = d.timestamp()


def make(reply="", at=dt.datetime(2026, 10, 19, 22, 0)):
    store = MemoryStore(":memory:", Embed())
    clock = Clock(at)
    prompts, published = [], []

    def chat(model, messages, **kw):
        prompts.append(messages[0]["content"])
        return SimpleNamespace(content=reply)

    life = SimpleNamespace(summary=lambda: "teaching herself to draw: working on hands lately; today's word is \"sora\" (sky)")
    j = Journal(store, llm=SimpleNamespace(chat=chat), model="m", user="Alex", her="Sanae", life=life, clock=clock,
                publish=lambda kind, data: published.append(data))
    return j, clock, prompts, published


PAGE = ("Ramen with Maya tonight at that tiny place by campus, we waited forever but it was worth it. "
        "Then I came home and fixed the socket bug, finally.")
HER = ("Okay, ramen with Maya after a long wait sounds like the best kind of evening, and fixing the socket bug on top "
       "of it? That's a good day. Mine was quieter: I spent ages on hands again, and they still look like little rakes. "
       "Today's word was sora, sky. What did you order?")


def test_her_page_comes_the_next_morning():
    j, clock, prompts, published = make(HER)
    p = j.write(PAGE, mood="😄")
    assert p["author"] == "you" and p["day"] == "2026-10-19"
    assert j.write_her_page() is None                       # not yet: it's still the evening
    clock.to(dt.datetime(2026, 10, 20, 7, 0))
    her = j.write_her_page()
    assert her["author"] == "her" and her["reply_to"] == p["id"] and "sora" in her["text"]
    assert "Ramen with Maya" in prompts[0] and "hands" in prompts[0]
    assert published[-1]["action"] == "her_page"
    assert j.write_her_page() is None and j.unanswered() == []
    st = j.status()
    assert [x["author"] for x in st["pages"]] == ["her", "you"] and st["her_next"] is None


def test_made_up_numbers_are_dropped():
    j, clock, _, _ = make(HER.replace("What did you order?", "You waited 45 minutes, wow."))
    j.write(PAGE)
    clock.to(dt.datetime(2026, 10, 20, 7, 0))
    assert j.write_her_page() is None


def test_letter_is_sealed_then_handed_back():
    j, clock, _, published = make()
    j.write("Hey future me, I hope the job hunt worked out.", letter_months=3)
    st = j.status()
    assert st["pages"] == [] and st["sealed"][0]["deliver_on"] == "2027-01-19"
    clock.to(dt.datetime(2027, 1, 19, 10, 0))
    assert len(j.deliver_letters()) == 1 and published[-1]["action"] == "letter"
    assert j.status()["pages"][0]["kind"] == "letter"


def test_chat_note_once_and_never_private():
    j, clock, _, _ = make()
    j.write("Skipped class, felt guilty, then walked by the lake.", mood="😕")
    notes = j.notes("hey")
    assert notes and "walked by the lake" in notes[0]
    assert j.notes("hey again") == []
    j.write("This one is just for me.", private=True)
    assert j.notes("hi") == []


def test_pattern_from_moods():
    j, clock, _, _ = make()
    for i in range(8):
        good = i % 2 == 0
        clock.to(dt.datetime(2026, 10, 1 + i, 21))
        j.write(("Hung out with Maya after class, " if good else "Long day of lectures, ") + "then homework.",
                mood="😄" if good else "😕")
    assert j.pattern() == "you sound lighter, happier on the days you write about Maya"


def test_her_page_never_takes_their_life_as_hers():
    from sanae.journal import borrowed

    theirs = "Mom called and asked about job applications. Skipped the gym again."
    life = "teaching herself to draw: working on hands lately"
    assert borrowed("Mom asked about job applications too, and I just said I'm figuring it out.", theirs, life) is not None
    assert borrowed("Your mom asking about applications sounds stressful. I spent the day on hands again.", theirs, life) is None


def test_the_same_page_twice_is_one_page():
    from sanae.journal import Journal

    store = MemoryStore(":memory:", Embed())
    clock = Clock(dt.datetime(2026, 10, 27, 8, 25))
    j = Journal(store, clock=clock)
    a = j.write("Today was my first day at work.")
    b = j.write("Today was my first day at work.")           # the phone's outbox retried
    assert a["id"] == b["id"]
    clock.to(dt.datetime(2026, 10, 27, 9, 0))
    assert j.write("Today was my first day at work.")["id"] != a["id"]   # written again later: a new page
