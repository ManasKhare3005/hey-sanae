import datetime as dt
from types import SimpleNamespace

import numpy as np

from sanae.memory import MemoryStore
from sanae.weekend import Weekend, parse_plan, weekend_of


class Clock:
    def __init__(self, d):
        self.t = d.timestamp()

    def __call__(self):
        return self.t

    def to(self, d):
        self.t = d.timestamp()


class Embed:
    def embed(self, texts):
        return np.ones((len(texts), 4), dtype="float32") / 2


def make(tmp_path, at=dt.datetime(2026, 10, 23, 18, 0), bucket=None):      # a Friday evening
    clock = Clock(at)
    store = MemoryStore(str(tmp_path / "w.db"), embedder=Embed())
    return Weekend(store, clock=clock, idle=lambda: 10, bucket=bucket), clock


def test_plans_from_what_they_say():
    assert parse_plan("saturday morning I wanna go hiking") == {"day": "sat", "at": "10:00", "text": "go hiking"}
    assert parse_plan("sunday at 3 coffee with Maya") == {"day": "sun", "at": "15:00", "text": "coffee with Maya"}
    assert parse_plan("maybe I'll do laundry on sunday") == {"day": "sun", "at": "", "text": "laundry"}
    assert parse_plan("movie night saturday at 8:30 pm") == {"day": "sat", "at": "20:30", "text": "movie"}
    assert parse_plan("nothing really") is None
    assert weekend_of(dt.date(2026, 10, 25)) == dt.date(2026, 10, 24)      # Sunday: this weekend
    assert weekend_of(dt.date(2026, 10, 21)) == dt.date(2026, 10, 24)


def test_friday_ask_then_plan_together(tmp_path):
    bucket = SimpleNamespace(suggest=lambda: "watch the sunrise from a hill")
    w, clock = make(tmp_path, bucket=bucket)
    ms = w.moments(clock())
    assert ms and ms[0].key.startswith("ask:") and "sunrise" in ms[0].situation
    w.used(ms[0], clock())
    assert w.planning()
    notes = w.notes("saturday morning I wanna go hiking, and then sunday at 3 coffee with Maya")
    assert "go hiking" in notes[0] and "coffee with Maya" in notes[0]
    assert [p["text"] for p in w.plans()] == ["go hiking", "coffee with Maya"]
    assert w.notes("that's it!") and not w.planning()
    assert w.notes("saturday I'll sleep in") == []          # not planning any more: nothing saved
    assert w.status()["label"] == "Oct 24 – 25" and len(w.status()["plans"]) == 2


def test_weekend_moments(tmp_path):
    w, clock = make(tmp_path)
    hike = w.add("go hiking", "sat", "10:00")
    w.add("laundry", "sun")
    clock.to(dt.datetime(2026, 10, 24, 9, 0))
    today = w.moments(clock())
    assert any(m.key.startswith("today:") and "go hiking" in m.situation for m in today)
    clock.to(dt.datetime(2026, 10, 24, 9, 40))
    fun = [m for m in w.phone_moments(clock()) if m.key.startswith("fun:")]
    assert fun and fun[0].important
    clock.to(dt.datetime(2026, 10, 24, 14, 0))
    how = [m for m in w.moments(clock()) if m.key.startswith("how:")]
    assert how
    w.used(how[0], clock())
    assert "ticked off" in w.notes("it was so pretty up there")[0]
    assert w.get_one(hike["id"])["done"]
    clock.to(dt.datetime(2026, 10, 25, 19, 0))
    recap = [m for m in w.moments(clock()) if m.key.startswith("recap:")]
    assert recap and "go hiking" in recap[0].situation


def test_routes(tmp_path):
    w, _ = make(tmp_path)
    assert w.route("what are my weekend plans?") == ("weekend_plans", {})
    assert w.route("what am I doing this weekend") == ("weekend_plans", {})
    assert w.route("let's plan the weekend") == ("plan_weekend", {})
    assert w.route("add brunch on sunday to our weekend plans") == \
        ("add_weekend_plan", {"plan": "brunch", "day": "sun", "time": "11:00"})
    assert w.route("cancel the hike from my weekend plans") == ("drop_weekend_plan", {"plan": "the hike"})
    assert w.route("what's the weather this weekend") is None
