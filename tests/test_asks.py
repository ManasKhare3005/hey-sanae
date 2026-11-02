import datetime as dt
import random
from types import SimpleNamespace

from sanae.asks import Asks
from sanae.drawings import Drawings
from sanae.initiative import Moment
from sanae.memory import MemoryStore
from tests.test_journal import Clock, Embed


def make(at=dt.datetime(2026, 10, 20, 15, 0)):
    clock = Clock(at)
    store = MemoryStore(":memory:", Embed())
    heard = []
    life = SimpleNamespace(heard_artist=heard.append)
    vision = SimpleNamespace(last=SimpleNamespace(description="A blue sky with soft clouds over palm trees."))
    a = Asks(store, clock=clock, idle=lambda: 10, life=life, drawings=Drawings(store, clock=clock), vision=vision,
             rng=random.Random(3))
    return a, clock, heard


def ask(a, clock, kind):
    m = Moment("ask", "...", key=f"ask:{kind}:{clock.t}", part="asks")
    a.used(m, clock())


def test_she_asks_every_few_days_and_from_the_phone():
    a, clock, _ = make()
    ms = a.phone_moments(clock())
    assert ms and ms[0].key.startswith("ask:")
    a.used(ms[0], clock())
    assert a.phone_moments(clock()) == []                 # one at a time
    a.put("pending", None)
    clock.to(dt.datetime(2026, 10, 21, 15, 0))
    assert a.phone_moments(clock()) == []                 # every couple of days, not daily
    clock.to(dt.datetime(2026, 10, 22, 16, 0))
    assert a.phone_moments(clock())


def test_a_song_for_her():
    a, clock, heard = make()
    ask(a, clock, "song")
    note = a.notes("listen to Blinding Lights by The Weeknd")
    assert "\"Blinding Lights\" by The Weeknd" in note[0] and heard == ["The Weeknd"]
    clock.to(dt.datetime(2026, 10, 21, 13, 0))
    follow = a.moments(clock())
    assert follow and "kept it on" in follow[-1].situation
    assert a.status()["gifts"][0]["kind"] == "song"


def test_the_sky_and_drawing_requests():
    a, clock, _ = make()
    ask(a, clock, "sky")
    assert a.notes("what's for dinner tonight") == []        # not a photo: still waiting for the sky
    clock.to(dt.datetime(2026, 10, 20, 19, 0))
    assert "sky photo you asked for" in a.notes("(Sent a photo) here's my sky!")[0]
    a.put("last", 0)
    ask(a, clock, "draw")
    assert "it's in your sketchbook" in a.notes("draw a cat!")[0]
    assert a.status()["gifts"][0]["drawing"]["subject"] == "a cat"
    ask(a, clock, "good")
    assert a.notes("not now") == [] and a.status()["waiting"] is None
