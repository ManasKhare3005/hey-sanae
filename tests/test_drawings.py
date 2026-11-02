import datetime as dt
import random
from types import SimpleNamespace

from sanae.drawings import SUBJECTS, Drawings, render, subject_for, subject_for_step
from sanae.herlife import DEFAULT_LEARNING
from sanae.memory import MemoryStore
from tests.test_journal import HER, PAGE, Clock, Embed
from tests.test_journal import make as make_journal


def life_on_day(day: int):
    return SimpleNamespace(learning=DEFAULT_LEARNING, day=lambda: day)


def wobble(strokes):
    """How far the strokes stray from straight lines, roughly: the sum of turning between steps."""
    total = 0
    for s in strokes:
        pts = list(zip(s[::2], s[1::2]))
        for a, b, c in zip(pts, pts[1:], pts[2:]):
            total += abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
    return total


def test_every_subject_draws_inside_the_page():
    for name in SUBJECTS:
        strokes = render(name, 0.5, 3)
        assert strokes and all(len(s) >= 4 and len(s) % 2 == 0 for s in strokes), name
        assert all(0 <= v <= 200 for s in strokes for v in s), name


def test_her_hand_steadies_as_she_learns():
    assert wobble(render("shapes", 0.95, 1)) < wobble(render("shapes", 0.1, 1))
    assert subject_for_step("hands (they're so hard)") == "a hand"
    assert subject_for_step("a cat sleeping") == "a sleeping cat"
    assert subject_for("ramen with Maya tonight") == "a bowl of noodles"
    assert subject_for("we went hiking!") == "mountains"
    assert subject_for("nothing special") is None


def test_sketchbook(tmp_path):
    store = MemoryStore(":memory:", Embed())
    d = Drawings(store, clock=Clock(dt.datetime(2026, 10, 20, 9)), life=life_on_day(7), rng=random.Random(4))
    a = d.draw()
    assert a["subject"] == "an eye" and a["strokes"]          # day 7, a step every 3 days: eyes
    b = d.draw()
    assert b["caption"].startswith("attempt #2")
    c = d.draw("a mug", why="ask:1", title="your coffee")
    assert c["caption"].lower().startswith("your coffee")
    assert [x["id"] for x in d.status()["drawings"]] == [c["id"], b["id"], a["id"]]
    assert "sketchbook" in d.notes("can I see what you drew?")[0]
    assert d.notes("I drew a blank on the quiz") == []


def test_her_notebook_page_comes_with_a_sketch():
    j, clock, prompts, published = make_journal(HER)
    j.drawings = Drawings(j.store, clock=clock, life=life_on_day(7))
    j.write(PAGE, mood="😄")
    clock.to(dt.datetime(2026, 10, 20, 7, 0))
    her = j.write_her_page()
    page = next(p for p in j.status()["pages"] if p["id"] == her["id"])
    assert page["drawing"]["subject"] == "a bowl of noodles" and page["drawing"]["strokes"]   # their ramen
    assert "drawing" not in next(p for p in j.status()["pages"] if p["author"] == "you")


def test_a_session_together_leaves_a_drawing(tmp_path):
    from sanae.together import Together

    clock = Clock(dt.datetime(2026, 10, 20, 20, 0))
    store = MemoryStore(str(tmp_path / "d.db"), embedder=Embed())
    life = life_on_day(13)
    t = Together(store, clock=clock, life=life)
    t.drawings = Drawings(store, clock=clock, life=life)
    t.start(t.add("read 20 minutes", why="stories"), 20, origin="laptop")
    clock.to(dt.datetime(2026, 10, 20, 20, 21))
    m = t.moments(clock())[0]
    assert "sketchbook" in m.situation
    t.used(m, clock())
    assert t.drawings.for_why(m.key)["subject"] == "a sleeping cat"


def test_she_practises_every_afternoon_on_her_own(tmp_path):
    clock = Clock(dt.datetime(2026, 10, 27, 9, 0))
    d = Drawings(MemoryStore(str(tmp_path / "d.db"), embedder=Embed()), clock=clock, life=life_on_day(4))
    d.observe(clock())
    assert len(d.latest()) == 1 and d.latest()[0]["why"] == "practice"   # an empty sketchbook gets one right away
    d.observe(clock())
    clock.to(dt.datetime(2026, 10, 27, 13, 59))
    d.observe(clock())
    assert len(d.latest()) == 1                                        # not twice a day
    clock.to(dt.datetime(2026, 10, 28, 10, 0))
    d.observe(clock())
    assert len(d.latest()) == 1                                        # mornings: not yet
    clock.to(dt.datetime(2026, 10, 28, 15, 0))
    d.observe(clock())
    d.observe(clock())
    assert len(d.latest()) == 2 and d.status()["drawings"][0]["subject"] == subject_for_step(d.skill()[0])
