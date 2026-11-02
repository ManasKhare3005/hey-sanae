import datetime as dt
from types import SimpleNamespace

import numpy as np

from sanae.memory import MemoryStore
from sanae.roommate import Roommate
from sanae.together import Together


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


def make(at):
    store = MemoryStore(":memory:", Embed())
    clock = Clock(at)
    together = Together(store, clock=clock)
    life = SimpleNamespace(word_today=lambda: "today's is \"sora\" (sky)", heard=[], heard_artist=None)
    life.heard_artist = life.heard.append
    weather = SimpleNamespace(today=lambda: {"now": 104}, units="fahrenheit")
    return Roommate(store, clock, together=together, life=life, weather=weather), together, clock, life


def test_linked_app_ticks_and_duolingo_quiz():
    r, together, clock, _ = make(dt.datetime(2026, 10, 19, 18, 0))
    a = together.add("Duolingo", app="com.duolingo", minutes=5)
    assert r.report({"apps": {"com.duolingo": 3}}) == ["duolingo"]             # not long enough for the list yet
    assert together.how(a, "2026-10-19") is None
    seen = r.report({"apps": {"com.duolingo": 6}})
    assert "ticked:Duolingo" in seen and together.how(a, "2026-10-19") == "app"
    ms = r.moments(clock())
    assert ms and ms[0].part == "roommate"
    r.used(ms[0], clock())
    ms = r.moments(clock())
    assert ms and "sora" in ms[0].situation
    r.used(ms[0], clock())
    assert r.moments(clock()) == [] and r.report({"apps": {"com.duolingo": 9}}) == []


def test_late_scrolling_is_a_phone_text_once():
    r, _, clock, _ = make(dt.datetime(2026, 10, 20, 1, 10))
    assert r.report({"night": {"com.instagram.android": 20}}) == []
    assert r.report({"night": {"com.instagram.android": 25, "com.reddit.frontpage": 10}}) == ["doomscroll"]
    assert r.moments(clock()) == []                            # not for the laptop
    m = r.phone_moments(clock())[0]
    assert m.important and "Instagram for 35 minutes" in m.situation
    r.used(m, clock())
    assert r.report({"night": {"com.instagram.android": 60}}) == []


def test_workout_in_the_heat_and_song_on_repeat():
    r, _, clock, life = make(dt.datetime(2026, 10, 19, 18, 30))
    w = {"start": "2026-10-19T17:30:00", "end": "2026-10-19T18:05:00", "type": "running", "minutes": 35, "km": 5.02}
    assert r.report({"workouts": [w]}) == ["workout:2026-10-19T17:30:00"]
    m = r.moments(clock())[0]
    assert "a run (5 km, 35 minutes)" in m.situation and "104°F out, hot" in m.situation
    r.used(m, clock())
    assert r.report({"workouts": [w]}) == []
    for day in (19, 20, 21):
        clock.to(dt.datetime(2026, 10, day, 12))
        seen = r.report({"playing": {"title": "Pink + White", "artist": "Frank Ocean"}})
    assert seen == ["repeat:Pink + White"] and life.heard == ["Frank Ocean"] * 3
