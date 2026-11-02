import datetime as dt
from types import SimpleNamespace

import numpy as np

from sanae.memory import MemoryStore
from sanae.promises import Promises, due_from
from sanae.reminders import Reminders


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


def make(at=dt.datetime(2026, 10, 19, 23, 10)):
    store = MemoryStore(":memory:", Embed())
    clock = Clock(at)
    rem = Reminders(store)
    published = []
    p = Promises(store, clock, reminders=rem, publish=lambda k, d: published.append((k, d)), idle=lambda: 30)
    return p, clock, rem, published


def test_due_words():
    night = dt.datetime(2026, 10, 19, 23, 10)
    assert due_from("sleep before 1", night) == dt.datetime(2026, 10, 20, 1, 0)
    assert due_from("finish it by 11 pm", dt.datetime(2026, 10, 19, 15)) == dt.datetime(2026, 10, 19, 23, 0)
    assert due_from("call mom tomorrow", night) == dt.datetime(2026, 10, 20, 23, 59)
    assert due_from("drink more water", night) is None


def test_their_promise_caught_then_settled():
    p, clock, _, _ = make()
    notes = p.notes("ok ok I promise I'll sleep before 1")
    assert "pinky promised" in notes[0] and "by 1 AM" in notes[0]
    mine = p.open()[0]
    assert mine["who"] == "you" and mine["due"] == "2026-10-20T01:00"
    clock.to(dt.datetime(2026, 10, 20, 1, 20))
    m = p.moments(clock())[0]
    assert m.important and "still at the laptop" in m.situation
    p.used(m, clock())
    assert p.get_one(mine["id"])["status"] == "broken"


def test_yes_to_her_ask_and_morning_check():
    p, clock, _, _ = make(dt.datetime(2026, 10, 19, 22, 0))
    notes = p.notes("fine, I promise", last_reply="Okay but promise you'll drink some water before bed?")
    assert notes and p.open()[0]["text"] == "drink some water before bed"
    clock.to(dt.datetime(2026, 10, 23, 12, 0))                 # no deadline: asked after 3 days
    m = p.moments(clock())[0]
    p.used(m, clock())
    notes = p.notes("yeah I did, every night")
    assert "kept" in notes[0] and p.status()["kept"] == {"you": 1}


def test_her_promise_becomes_a_reminder():
    p, clock, rem, published = make(dt.datetime(2026, 10, 19, 20, 0))
    notes = p.notes("fine but you promise to remind me about the gym tomorrow at 7am")
    hers = [x for x in p.open() if x["who"] == "her"][0]
    assert hers["reminder"] and "real reminder" in notes[-1]
    r = rem.by_uid(hers["reminder"])
    assert r.text == "the gym" and r.due == dt.datetime(2026, 10, 20, 7, 0)
    assert p.notes("I promise to call my mom") and [x["who"] for x in p.open()] == ["her", "you"]
