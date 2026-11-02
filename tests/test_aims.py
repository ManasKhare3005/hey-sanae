"""Her own aims for the week (aims.py): decided on Monday from her filtered diary, acted on in the evenings."""
import datetime as dt
import tempfile

from sanae.aims import Aims
from sanae.cloudbrain import CloudBrain
from sanae.goals import Goals
from sanae.memory import MemoryStore
from tests.test_journal import Clock, Embed

ANSWER = {"aims": [{"aim": "Help the user settle into the new job", "why": "The user started work on Tuesday and was anxious.",
                    "ways": ["Ask how one specific part of work went", "Say you're proud when they mention a win"],
                    "check": "They tell her about work without being asked"}],
          "last_week": "no aims yet"}


def make(at=dt.datetime(2026, 11, 2, 9, 0)):          # a Monday
    store = MemoryStore(":memory:", Embed())
    sent = []

    def run(system, prompt, schema):
        sent.append(prompt)
        return ANSWER

    clock = Clock(at)
    brain = CloudBrain({"cloud": True}, "Alex", "Sanae", run=run, clock=clock, folder=tempfile.mkdtemp())
    goals = Goals(store)
    goals.add("go to the gym", 3)
    a = Aims(store, clock=clock, brain=brain, user="Alex", goals=goals)
    with store.lock:
        for day, text, mood in [("2026-10-27", "Alex started a new job and was anxious, then enjoyed it.", "good"),
                                ("2026-10-28", "Alex watched a comedy and told me about Nina's cat.", "okay"),
                                ("2026-10-29", "A rough night; we talked it through.", "a hard day"),
                                ("2026-10-30", "Alex's doctor visit went fine. We planned the weekend.", "good")]:
            store.db.execute("INSERT INTO diary (day, text, created, updated, mood) VALUES (?,?,?,?,?)", (day, text, day, day, mood))
        store.db.commit()
    return a, store, sent, clock


def test_monday_aims_from_the_filtered_diary():
    a, store, sent, clock = make()
    assert a.due()
    a.tick()
    p = sent[0]
    assert "the user started a new job" in p and "rough night" not in p                 # hard day left out
    assert "doctor" not in p and "We planned the weekend" in p and "[name]'s cat" in p and "Nina" not in p
    assert "go to the gym" in p
    w = a.status()
    assert w["aims"][0]["aim"] == "Help Alex settle into the new job" and w["week"] == "2026-W45"
    assert a.notes("hey")[0].startswith("This week you're quietly trying to help Alex settle into the new job")
    a.tick()
    assert len(sent) == 1 and not a.due()


def test_acting_on_it_every_other_evening():
    a, store, sent, clock = make()
    a.tick()
    clock.to(dt.datetime(2026, 11, 2, 15, 0))
    assert a.moments(clock()) == []                                                     # not evening
    clock.to(dt.datetime(2026, 11, 2, 19, 0))
    m = a.moments(clock())[0]
    assert "Ask how one specific part of work went" in m.situation and "{user}" in m.situation
    a.used(m, clock())
    assert a.moments(clock()) == []
    clock.to(dt.datetime(2026, 11, 3, 19, 0))
    assert a.moments(clock()) == []                                                     # every other evening
    clock.to(dt.datetime(2026, 11, 4, 19, 0))
    assert "Say you're proud" in a.moments(clock())[0].situation                       # the next way
    assert a.status()["done"] == {"0": 1}


def test_quiet_week_and_late_in_the_week():
    a, store, sent, clock = make(dt.datetime(2026, 11, 5, 9, 0))                        # Thursday: too late
    assert not a.due()
    a2, store2, sent2, clock2 = make()
    with store2.lock:
        store2.db.execute("DELETE FROM diary")
        store2.db.commit()
    a2.tick()
    assert sent2 == [] and not a2.due() and a2.status()["aims"] == []


def test_their_own_words_beat_her_diary():
    from sanae.journal import Journal

    a, store, sent, clock = make()
    j = Journal(store, clock=lambda: dt.datetime(2026, 10, 27, 21, 0).timestamp())
    j.write("First day at work, I was anxious but enjoyed it.")
    j.write("Something I don't want anyone to read.", private=True)
    with store.lock:
        store.db.execute("INSERT INTO turns (ts, user, reply, heard) VALUES (?,?,?,?)",
                         ("2026-10-28T19:00:00", "work was long but my team is nice", "Glad!", ""))
        store.db.execute("INSERT INTO turns (ts, user, reply, heard) VALUES (?,?,?,?)",
                         ("2026-10-28T19:05:00", "turn the volume down please now", "Done", "other"))
        store.db.commit()
    a.tick()
    p = sent[0]
    assert "Wed 19:00: work was long but my team is nice" in p and "volume" not in p
    assert "First day at work" in p and "don't want anyone" not in p
