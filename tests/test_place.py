import datetime as dt
from types import SimpleNamespace

from sanae.memory import MemoryStore
from sanae.place import Place
from tests.test_journal import Clock, Embed


def test_welcome_home_after_being_out():
    clock = Clock(dt.datetime(2026, 10, 20, 9, 0))
    ev = SimpleNamespace(title="Call with Maya", start=dt.datetime(2026, 10, 20, 19, 30), all_day=False)
    ctx = SimpleNamespace(events=SimpleNamespace(between=lambda a, b: [ev]), together=None)
    p = Place(MemoryStore(":memory:", Embed()), clock=clock, ctx=ctx, idle=lambda: 4000)
    assert p.report("arrived") == "arrived"              # first report: no "welcome", we didn't know they were out
    assert p.report("left", dt.datetime(2026, 10, 20, 9, 30).timestamp()) == "left"
    clock.to(dt.datetime(2026, 10, 20, 12, 0))
    assert p.notes("hey") == ["They're out (not home since 9:30 AM)"]
    assert p.report("left") is None                      # already out
    clock.to(dt.datetime(2026, 10, 20, 17, 40))
    assert p.report("arrived") == "welcome"
    ms = p.phone_moments(clock())
    assert ms and ms[0].important and "most of the day" in ms[0].situation and "Call with Maya at 7:30 PM" in ms[0].situation
    p.used(ms[0], clock())
    assert p.moments(clock()) == []
    clock.to(dt.datetime(2026, 10, 20, 18, 0))
    assert p.notes("hi") == ["They got home 20 minutes ago"]


def test_a_quick_trip_out_is_not_a_homecoming():
    clock = Clock(dt.datetime(2026, 10, 20, 9, 0))
    p = Place(MemoryStore(":memory:", Embed()), clock=clock, ctx=None)
    p.report("arrived")
    p.report("left")
    clock.to(dt.datetime(2026, 10, 20, 9, 10))
    assert p.report("arrived") == "arrived" and p.moments(clock()) == []
