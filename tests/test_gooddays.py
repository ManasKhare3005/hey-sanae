"""What makes your good days (gooddays.py): patterns from diary moods vs steps, sleep, late nights..."""
import datetime as dt

from sanae.gooddays import GoodDays
from sanae.memory import MemoryStore
from tests.test_journal import Clock, Embed

NOW = dt.datetime(2026, 10, 27, 19, 0)


def make(n=16):
    store = MemoryStore(":memory:", Embed())
    clock = Clock(NOW)
    g = GoodDays(store, clock=clock, idle=lambda: 10)
    with store.lock:
        for i in range(1, n + 1):
            day = (NOW.date() - dt.timedelta(days=i)).isoformat()
            walked = i % 2 == 0
            # walking days: good 7 of 8; the rest: good 2 of 8, stressed 5 of 8
            if walked:
                mood = "okay" if i == 8 else "good"
            else:
                mood = "good" if i in (1, 9) else "stressed" if i in (3, 5, 7, 11, 13) else "okay"
            store.db.execute("INSERT INTO diary (day, text, created, updated, mood) VALUES (?,?,?,?,?)",
                             (day, "a day", day, day, mood))
            store.db.execute("INSERT INTO health (day, steps, sleep_min, updated) VALUES (?,?,?,?)",
                             (day, 8000 if walked else 1500, 450, day))
            store.db.execute("INSERT INTO turns (ts, user, reply) VALUES (?,?,?)", (f"{day}T20:00:00", "hi", "hey"))
        store.db.commit()
    return g, clock, store


def test_walking_days_are_better():
    g, clock, _ = make()
    ps = g.patterns()
    assert [p["key"] for p in ps] == ["walked"]                     # sleep is the same every day: no pattern
    p = ps[0]
    assert p["better"] and p["with"] == {"days": 8, "good": 7, "rough": 0}
    assert p["text"] == "Days you walked 6,000+ steps were good 7 of 8 times, vs 2 of 8 otherwise."
    assert "walked 6,000+ steps" in g.spoken()
    assert g.route("what makes my good days?") == ("good_days", {})
    assert g.route("what's for dinner") is None
    # she brings it up once in the evening, then not again for a week
    m = g.moments(clock())[0]
    assert "good 7 of 8 times" in m.situation
    g.used(m, clock())
    clock.to(NOW + dt.timedelta(days=2))
    assert g.moments(clock()) == []
    st = g.status()
    assert st["days"] == 16 and st["patterns"][0]["label"] == "Walking 6k+ steps"


def test_not_enough_days_and_late_nights():
    g, clock, store = make(5)
    assert g.patterns() == [] and "only got 5 days" in g.spoken()
    g, clock, store = make(16)
    with store.lock:                                     # up past 1 AM before every stressed day
        for i in (3, 5, 7, 11, 13):
            day = (NOW.date() - dt.timedelta(days=i)).isoformat()
            store.db.execute("INSERT INTO turns (ts, user, reply) VALUES (?,?,?)", (f"{day}T01:30:00", "still up", "go to bed"))
        store.db.commit()
    late = next(p for p in g.patterns() if p["key"] == "late")
    assert not late["better"] and late["text"].startswith("Days after a night up past 1 AM were rough 5 of 5 times")
    assert g.moments(dt.datetime(2026, 10, 27, 12, 0).timestamp()) == []           # evenings only
