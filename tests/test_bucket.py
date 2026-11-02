import datetime as dt
import random

from sanae.bucket import Bucket
from sanae.drawings import Drawings
from sanae.memory import MemoryStore
from tests.test_journal import Clock, Embed


def make():
    clock = Clock(dt.datetime(2026, 10, 20, 19, 0))
    store = MemoryStore(":memory:", Embed())
    return Bucket(store, clock=clock, drawings=Drawings(store, clock=clock), idle=lambda: 10, rng=random.Random(2)), clock


def test_routes_and_list():
    b, _ = make()
    assert b.route("add watching the sunrise from a hill to our bucket list") == \
        ("add_to_bucket_list", {"what": "watching the sunrise from a hill"})
    assert b.route("what's on our bucket list?") == ("bucket_list", {})
    assert b.route("take skydiving off the bucket list") == ("drop_from_bucket_list", {"what": "skydiving"})
    from sanae.agent import direct_route

    tools = {"list_todos": 1, "add_todo": 1, "check_todo": 1, "clear_todos": 1, "list_activities": 1, "add_activity": 1,
             "drop_activity": 1}
    assert direct_route("add watching the sunrise from a hill to our bucket list", tools) is None   # not the todo list
    b.add("watching the sunrise from a hill")
    b.add("go to a concert")
    assert "watching the sunrise from a hill" in b.spoken()


def test_doing_one_ticks_it_and_sketches_it():
    b, _ = make()
    b.add("hike up to the hollywood sign")
    assert b.notes("we finally did the hollywood sign hike!!")[0].startswith("They did \"hike up to the hollywood sign\"")
    item = b.status()["items"][0]
    assert item["done_day"] == "2026-10-20" and item["drawing"]["subject"] == "mountains"
    assert b.notes("I want to go to the hollywood sign again someday") == []


def test_her_own_idea_and_weekend_suggestions():
    b, clock = make()
    for t in ("go to a concert", "learn to surf", "see the northern lights"):
        b.add(t)
    m = b.moments(clock())
    assert m and "one of your own" in m[0].situation
    b.used(m[0], clock())
    assert [x["who"] for x in b.items()].count("her") == 1 and b.moments(clock()) == []
    seen = {b.suggest() for _ in range(4)}
    assert len(seen) == 4 and b.suggest() is None             # each once, then not again for three weeks
