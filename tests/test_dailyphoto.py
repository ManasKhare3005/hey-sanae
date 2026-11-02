"""Photo a day (dailyphoto.py): a daily active challenge, the photo kept, streaks, the phone's reminder."""
import datetime as dt
import random
import time
from types import SimpleNamespace

from sanae.dailyphoto import INDOOR, WALKS, DailyPhoto
from sanae.memory import MemoryStore
from tests.test_journal import Clock, Embed


class Book:
    """A stand-in scrapbook: keeps what vision.last holds."""
    def __init__(self, clock):
        self.vision = SimpleNamespace(last=SimpleNamespace(at=clock(), description="A blue sky over palm trees."))
        self.kept = []

    def keep(self, said=""):
        self.kept.append(said)
        return {"id": len(self.kept)}


def make(at=dt.datetime(2026, 10, 27, 10, 0), steps=None, weather=None):
    clock = Clock(at)
    published = []
    health = SimpleNamespace(today=lambda: SimpleNamespace(steps=steps) if steps is not None else None)
    book = Book(clock)
    d = DailyPhoto(MemoryStore(":memory:", Embed()), clock=clock, health=health,
                   weather=SimpleNamespace(today=lambda: weather, units="fahrenheit") if weather else None,
                   scrapbook=book, idle=lambda: 10, publish=lambda k, x: published.append((k, x)), rng=random.Random(3))
    return d, clock, book, published


def test_a_day_with_a_photo():
    d, clock, book, published = make(steps=900)
    m = d.moments(clock())[0]
    r = d.today_row()
    assert r["challenge"] in WALKS and r["challenge"] in m.situation           # barely moved: a walking one
    d.used(m, clock())
    assert d.moments(clock()) == []
    assert d.route("what's today's photo challenge?") == ("daily_photo", {"action": "show"})
    assert d.route("can I get a different challenge?", "Today's photo challenge: x") == ("daily_photo", {"action": "reroll"})
    assert d.route("skip today's photo") == ("daily_photo", {"action": "skip"})
    assert d.notes("(Sent a photo) here's a screenshot of my code") == []       # not a daily one
    note = d.notes("(Sent a photo) look!")
    assert "daily photo for today's challenge" in note[0] and "streak is 1 day" in note[0]
    for _ in range(50):
        if book.kept:
            break
        time.sleep(0.02)
    assert book.kept == [f"daily photo: {r['challenge']}"] and d.today_row()["scrapbook_id"] == 1
    assert d.notes("(Sent a photo) another one") == []                         # only the first counts
    assert d.get("claimed") == book.vision.last.at
    clock.to(dt.datetime(2026, 10, 27, 17, 30))
    d.observe(clock())
    assert published[-1][0] != "nudge"                                          # done: no reminder
    assert d.status()["month"][0]["status"] == "done"


def test_streak_skips_and_the_reminder():
    d, clock, _, published = make(at=dt.datetime(2026, 10, 20, 12, 0), weather={"code": 63, "now": 70})
    assert d.today_row()["challenge"] in INDOOR                                 # raining: indoors
    for day in (20, 21, 22):
        clock.to(dt.datetime(2026, 10, day, 12, 0))
        d.notes("(Sent a photo) done!")
    clock.to(dt.datetime(2026, 10, 23, 12, 0))
    assert d.skip() is True                                                     # free skip this week
    clock.to(dt.datetime(2026, 10, 24, 12, 0))
    assert d.streak() == 3                                                      # today still open
    clock.to(dt.datetime(2026, 10, 24, 17, 15))
    d.observe(clock())
    assert published[-1] == ("nudge", {"kind": "dailyphoto", "text": f"📸 Photo of the day: {d.today_row()['challenge']}. "
                                                                      "Keep the 3-day streak going!"})
    d.observe(clock())
    assert len([p for p in published if p[0] == "nudge"]) == 1                 # once a day
    assert d.skip() is False                                                    # second skip in a week: streak ends
    clock.to(dt.datetime(2026, 10, 25, 12, 0))
    assert d.streak() == 0
    first = d.today_row()["challenge"]
    assert d.reroll() not in (None, first) and d.reroll() is None              # one swap a day


def test_she_does_it_too():
    from sanae.drawings import Drawings

    d, clock, book, published = make(steps=900)
    d.drawings = Drawings(d.store, clock=clock, rng=random.Random(1))
    assert "you'll draw yours" in d.moments(clock())[0].situation
    assert d.hers() is None and d.status()["today"]["hers"] is None
    clock.to(dt.datetime(2026, 10, 27, 12, 0))
    notes = d.notes("(Sent a photo) here's mine!")
    assert len(notes) == 2 and "You did the challenge too" in notes[1]
    hers = d.status()["today"]["hers"]
    assert hers["strokes"] and hers["why"] == "dailyphoto:2026-10-27" and "your" not in hers["caption"]
    clock.to(dt.datetime(2026, 10, 27, 16, 0))
    d.observe(clock())                                   # already drawn: not again
    assert len(d.drawings.latest(10)) == 1
    # a day without a photo: hers is there by mid-afternoon
    clock.to(dt.datetime(2026, 10, 28, 15, 30))
    d.observe(clock())
    assert d.status()["today"]["hers"]["day"] == "2026-10-28" and ("us", {"what": "dailyphoto", "action": "hers"}) in published
    assert DailyPhoto.her_subject("your shoes after a walk") == "some shoes"
