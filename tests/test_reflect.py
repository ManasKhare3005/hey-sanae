"""The nightly look back (reflect.py): yesterday's filtered chats -> a few lessons she keeps."""
import datetime as dt
import json

from sanae.cloudbrain import CloudBrain
from sanae.memory import MemoryStore
from sanae.reflect import Reflection
from tests.test_journal import Clock, Embed


def make(answer, at=dt.datetime(2026, 10, 28, 9, 0)):
    store = MemoryStore(":memory:", Embed())
    sent = []

    def run(system, prompt, schema):
        sent.append(prompt)
        return answer(prompt) if callable(answer) else answer

    clock = Clock(at)
    brain = CloudBrain({"cloud": True}, "Alex", "Sanae", people=lambda: [], run=run, clock=clock,
                       folder=__import__("tempfile").mkdtemp())
    return Reflection(store, clock=clock, brain=brain, user="Alex", her="Sanae"), store, sent, clock


def chat(store, day, rows):
    with store.lock:
        for ts, user, reply, heard in rows:
            store.db.execute("INSERT INTO turns (ts, user, reply, heard) VALUES (?,?,?,?)", (f"{day}T{ts}", user, reply, heard))
        store.db.commit()


YESTERDAY = [("16:11:00", "", "21 hours? That's a record!", "she"),
             ("19:24:00", "21 hrs of?", "Wait, 21 hours? How'd you manage that?", ""),
             ("19:26:00", "I ate mac n cheese", "You're not skipping breakfast, are you?", ""),
             ("19:30:00", "my doctor said my blood pressure is high", "Oh no, take care.", ""),
             ("23:55:00", "A black cat reminded me of Nina", "Nina? Hope she's well.", ""),
             ("23:56:00", "Yes!", "Nina sounds amazing.", ""),
             ("23:58:00", "is someone there", "Just me!", "other")]


def test_yesterday_becomes_lessons():
    r, store, sent, clock = make({"lessons": [
        {"text": "Don't quote numbers you can't explain, like how long the user was away.", "kind": "made_up",
         "evidence": "21 hours? That's a record"},
        {"text": "Don't ask about breakfast in the evening.", "kind": "timing", "evidence": "skipping breakfast at 7:26 PM"}],
        "retire": []})
    chat(store, "2026-10-27", YESTERDAY)
    assert r.due_day() == dt.date(2026, 10, 27)
    r.tick()
    prompt = sent[0]
    assert "[16:11] [she spoke first] Sanae: 21 hours?" in prompt and "the user: I ate mac n cheese" in prompt
    assert "blood pressure" not in prompt and "doctor" not in prompt          # health: never sent
    assert "Nina" not in prompt and "a friend" in prompt and "Alex" not in prompt
    assert "is someone there" not in prompt                                   # not their voice
    assert [l["text"] for l in r.lessons()] == ["Don't quote numbers you can't explain, like how long Alex was away.",
                                                "Don't ask about breakfast in the evening."]
    assert r.notes("hey")[0].startswith("Your own lessons from past chats: Don't quote numbers")
    r.tick()
    assert len(sent) == 1                                                     # once a day
    lid = r.lessons()[1]["id"]
    assert r.remove(lid) and len(r.lessons()) == 1


def test_seen_again_kept_longer_and_retired():
    answers = iter([
        {"lessons": [{"text": "Don't ask about breakfast in the evening.", "kind": "timing", "evidence": "x"}], "retire": []},
        {"lessons": [{"text": "Don't ask about breakfast in the evening!", "kind": "timing", "evidence": "y"}], "retire": []},
        {"lessons": [], "retire": [1]}])
    r, store, sent, clock = make(lambda p: next(answers))
    for day in ("2026-10-25", "2026-10-26", "2026-10-27"):
        chat(store, day, [*YESTERDAY[:3], ("20:00:00", "we love to watch movies", "Comedy?", "")])
    clock.to(dt.datetime(2026, 10, 26, 9, 0))
    r.tick()
    clock.to(dt.datetime(2026, 10, 27, 9, 0))
    r.tick()
    assert [(l["id"], l["seen"]) for l in r.lessons()] == [(1, 2)]
    assert "1. Don't ask about breakfast" in sent[1]                          # Claude sees what she already knows
    clock.to(dt.datetime(2026, 10, 28, 9, 0))
    r.tick()
    assert r.lessons() == []


def test_private_days_and_quiet_days_stay_home():
    r, store, sent, clock = make({"lessons": [], "retire": []})
    chat(store, "2026-10-27", YESTERDAY)
    store.set("comfort:turns", json.dumps([2]))                                # a hard moment that day
    r.tick()
    assert sent == [] and r.get("last_day") == "2026-10-27"
    clock.to(dt.datetime(2026, 10, 29, 9, 0))
    chat(store, "2026-10-28", [("10:00:00", "hi", "hey", "")])
    r.tick()
    assert sent == []                                                          # too little to learn from
    clock.to(dt.datetime(2026, 10, 30, 3, 0))
    assert r.due_day() is None                                                 # the day isn't over yet
