import datetime as dt

from sanae.memory import MemoryStore
from sanae.together import Together, parse_days, together_route


class Clock:
    def __init__(self, d: dt.datetime):
        self.t = d.timestamp()

    def __call__(self):
        return self.t

    def to(self, d: dt.datetime):
        self.t = d.timestamp()


class NoEmbed:
    def embed(self, texts):
        import numpy as np

        return np.zeros((len(texts), 4), dtype="float32") + 0.5


def make(tmp_path, at=dt.datetime(2026, 10, 19, 10, 0)):      # a Monday
    clock = Clock(at)
    store = MemoryStore(str(tmp_path / "t.db"), embedder=NoEmbed())
    return Together(store, clock=clock), clock


def test_days_parse():
    assert parse_days("every day") == "daily"
    assert parse_days("weekdays") == "mon,tue,wed,thu,fri"
    assert parse_days("mon wed fri") == "mon,wed,fri"
    assert parse_days("3 times a week") == "3/week"


def test_streak_room_and_pass(tmp_path):
    t, clock = make(tmp_path)
    a = t.add("read 20 minutes", why="I miss getting lost in a story")
    assert t.status()["room"]["items"] == []
    for i in range(3):
        clock.to(dt.datetime(2026, 10, 19 + i, 21))
        t.log(a)
    clock.to(dt.datetime(2026, 10, 22, 21))
    assert t.use_pass(a)                       # a bad day: covered
    assert not t.use_pass(t.add("water"))      # once a week
    clock.to(dt.datetime(2026, 10, 23, 9))
    assert t.streak(a) == 4                    # today still open doesn't break it
    room = t.room()
    assert room["points"] == 3 and "sprout" in room["items"] and not room["droopy"]
    clock.to(dt.datetime(2026, 10, 27, 9))
    assert t.room()["droopy"]                  # nothing for days: the plant droops
    assert t.streak(a) == 0


def test_weekly_target(tmp_path):
    t, clock = make(tmp_path)
    a = t.add("gym", days="3 times a week")
    for day in (19, 20, 21):
        clock.to(dt.datetime(2026, 10, day, 18))
        assert t.due(a, clock.to and t.now().date())
        t.log(a)
    clock.to(dt.datetime(2026, 10, 22, 18))
    assert not t.due(a, t.now().date())        # three done: not on today's list
    assert t.streak(a) == 1


def test_conversation_ticks_asks_why_and_covers(tmp_path):
    t, clock = make(tmp_path)
    a = t.add("reading")
    notes = t.notes("ok")
    assert any("why it matters" in n for n in notes)
    clock.t += 30
    notes = t.notes("because I used to love books and I miss it")
    assert "matters to them" in notes[0] and t.get_one(a["id"])["why"].startswith("because I used")
    clock.t += 60
    notes = t.notes("starting my reading now")
    assert "alongside" in notes[0] and t.session()["title"] == "reading"
    clock.t += 26 * 60
    ms = t.moments(clock.t)
    assert ms and ms[0].important and "Time's up" in ms[0].situation
    t.used(ms[0], clock.t)
    notes = t.notes("finally did my reading")
    assert "They did" in notes[0] and t.how(a, t.today()) == "said"
    b = t.add("run", why="to feel strong")
    notes = t.notes("too tired for my run today")
    assert "covering for them" in notes[0] and t.how(b, t.today()) == "pass"


def test_debrief_and_time_nudge(tmp_path):
    t, clock = make(tmp_path, dt.datetime(2026, 10, 19, 21, 5))
    t.add("water", at="21:00")
    t.idle = lambda: 10
    ms = t.moments(clock.t)
    kinds = [m.key.split(":")[0] for m in ms]
    assert "at" in kinds and "debrief" in kinds
    assert t.replaces_checkin(t.now())


def test_route():
    assert together_route("what's on my daily list") == ("list_activities", {})
    assert together_route("add reading 20 minutes to our daily list on weekdays") == \
        ("add_activity", {"title": "reading 20 minutes", "days": "on weekdays"})
    assert together_route("take water off my daily list") == ("drop_activity", {"title": "water"})
    assert together_route("add milk to my list") is None
