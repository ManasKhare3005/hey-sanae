import datetime as dt
import random
from types import SimpleNamespace

from sanae.memory import MemoryStore
from sanae.winddown import WindDown
from tests.test_journal import Clock, Embed


def make(at, events=(), classes=(), idle=10):
    clock = Clock(at)
    ctx = SimpleNamespace(events=SimpleNamespace(between=lambda a, b: [e for e in events if a <= e.start <= b]),
                          canvas=SimpleNamespace(items=lambda: list(classes)), stories=object())
    return WindDown(MemoryStore(":memory:", Embed()), clock=clock, ctx=ctx, idle=lambda: idle, user="Alex",
                    rng=random.Random(0)), clock


def test_alarm_before_the_first_class_tomorrow():
    cls = SimpleNamespace(kind="class", course="CS 106", start=dt.datetime(2026, 10, 21, 9, 0))
    w, _ = make(dt.datetime(2026, 10, 20, 23, 50), classes=[cls])
    p = w.plan()
    assert p["wake"] == "07:30" and p["why"] == "CS 106 class at 9 AM" and "7:30 AM, you've got CS 106" in p["line"]
    w2, _ = make(dt.datetime(2026, 10, 21, 0, 5), classes=[cls])        # just after midnight: "tomorrow" is today
    assert w2.plan()["wake"] == "07:30"


def test_usual_time_and_never_too_early():
    w, _ = make(dt.datetime(2026, 10, 20, 23, 59))
    assert w.plan()["wake"] == "08:30" and w.plan()["why"] == ""
    early = SimpleNamespace(title="Flight", start=dt.datetime(2026, 10, 21, 6, 30), all_day=False)
    w, _ = make(dt.datetime(2026, 10, 20, 23, 59), events=[early])
    assert w.plan()["wake"] == "06:00"


def test_goodnight_at_the_laptop_once():
    w, clock = make(dt.datetime(2026, 10, 21, 0, 2))
    m = w.moments(clock())
    assert m and m[0].important and "bedtime story" in m[0].situation and "8:30 AM" in m[0].situation
    w.used(m[0], clock())
    assert w.moments(clock()) == []
    away, c2 = make(dt.datetime(2026, 10, 21, 0, 2), idle=3600)
    assert away.moments(c2()) == []                                   # not at the laptop: the phone does it
    late, c3 = make(dt.datetime(2026, 10, 21, 0, 40))
    assert late.moments(c3()) == []
