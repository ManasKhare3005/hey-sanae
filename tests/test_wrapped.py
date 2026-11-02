"""Your month, wrapped (wrapped.py): last month's recap from what's true, on the 1st."""
import datetime as dt
import json
from types import SimpleNamespace

from sanae.cooking import Cooking
from sanae.dailyphoto import DailyPhoto
from sanae.gooddays import GoodDays
from sanae.memory import MemoryStore
from sanae.playlist import Playlist
from sanae.watching import Watching
from sanae.wrapped import Wrapped, month_range
from tests.test_journal import Clock, Embed


def make(at=dt.datetime(2026, 11, 1, 11, 0), proud="You showed up for yourself all October, photo after photo."):
    store = MemoryStore(":memory:", Embed())
    clock = Clock(at)
    prompts, published = [], []

    def chat(model, messages, **kw):
        prompts.append(messages[0]["content"])
        return SimpleNamespace(content=proud)

    ctx = SimpleNamespace()
    ctx.playlist = Playlist(store, clock=clock, find=lambda t, a: "")
    ctx.watching = Watching(store, clock=clock, read=lambda: ("", "", "", ""))
    ctx.cooking = Cooking(store, clock=clock)
    ctx.dailyphoto = DailyPhoto(store, clock=clock)
    ctx.gooddays = GoodDays(store, clock=clock)
    w = Wrapped(store, ctx=ctx, llm=SimpleNamespace(chat=chat), model="m", user="Alex", clock=clock,
                publish=lambda k, d: published.append((k, d)))
    return w, ctx, store, clock, prompts, published


def fill(store, ctx):
    was = ctx.playlist.clock.t                           # one clock for all: put it back after
    with store.lock:
        for day in range(1, 32):
            d = f"2026-10-{day:02d}"
            store.db.execute("INSERT INTO turns (ts, user, reply) VALUES (?,?,?)", (f"{d}T20:00:00", "hi", "hey"))
            mood = "great" if day == 12 else "good" if day % 3 == 0 else "stressed" if day % 7 == 0 else "okay"
            store.db.execute("INSERT INTO diary (day, text, created, updated, mood) VALUES (?,?,?,?,?)",
                             (d, "Alex aced the networks quiz and we celebrated with ramen. Then they slept early.", d, d, mood))
            if day >= 20:
                store.db.execute("INSERT INTO daily_photos (day, challenge, status) VALUES (?,?,?)",
                                 (d, "your shadow, outside", "skipped" if day == 25 else "done"))
        store.db.execute("INSERT INTO turns (ts, user, reply) VALUES (?,?,?)", ("2026-09-30T20:00:00", "old", "old"))
        store.db.commit()
    for day in (3, 9, 15, 22):
        ctx.playlist.clock.to(dt.datetime(2026, 10, day, 21, 0))
        ctx.playlist.heard("Espresso", "Sabrina Carpenter")
    ctx.watching.clock.to(dt.datetime(2026, 10, 24, 23, 0))
    ctx.watching.rate_movie("Dune: Part Two", 5)
    with store.lock:
        store.db.execute("INSERT INTO watched (show, kind, day, started, minutes) VALUES ('Frieren', 'show', '2026-10-05', "
                         "'2026-10-05T21:00', 300), ('Dune: Part Two', 'movie', '2026-10-24', '2026-10-24T20:00', 166)")
        store.db.execute("INSERT INTO recipes (title, ingredients, steps, cooked, stars, last_cooked, added, source) VALUES "
                         "('Egg fried rice', '[]', '[]', 3, 5, '2026-10-20T19:30', '2026-10-02T19:00', ''), "
                         "('Home-style tikka masala', '[]', '[]', 0, 0, '', '2026-10-18T13:00', 'from a photo at Curry House')")
        store.db.commit()
    ctx.playlist.clock.t = was


def test_october_wrapped():
    w, ctx, store, clock, prompts, published = make()
    fill(store, ctx)
    assert w.due_month() == "2026-10"
    w.tick()
    data = w.status()["months"][0]
    kinds = [s["kind"] for s in data["slides"]]
    assert data["label"] == "your October"
    assert kinds == ["cover", "songs", "screen", "kitchen", "photo_a_day", "bestday", "proud"]
    cover, songs, screen, kitchen, photos, best = data["slides"][:6]
    assert cover["talked"] == 31 and cover["days"] == 31 and cover["good"] == 10
    assert songs["top"] == [{"title": "Espresso", "artist": "Sabrina Carpenter", "days": 4}]
    assert screen["hours"] == "8 hours" and screen["top_show"] == "Frieren" and screen["movies"] == [{"title": "Dune: Part Two", "stars": 5}]
    assert kitchen["cooked"] == 1 and kitchen["best"]["title"] == "Egg fried rice" and kitchen["recreated"] == ["Home-style tikka masala"]
    assert photos["done"] == 11 and photos["best"] == 11                 # the free skip doesn't break the streak
    assert best["day"] == "Monday, October 12" and best["text"] == "Alex aced the networks quiz and we celebrated with ramen."
    assert "Most-played song: Espresso (on 4 days)" in prompts[0] and "Sent 11 daily photos, best streak 11 days" in prompts[0]
    assert ("nudge", {"kind": "wrapped", "text": "🎁 Your October, wrapped by Sanae. Us → Your month"}) in published
    w.tick()                                                             # once a month
    assert len(w.status()["months"]) == 1 and len(prompts) == 1
    assert w.spoken().startswith("Your October, wrapped: we talked on 31 of 31 days, 10 good days, Espresso was on repeat")
    assert w.route("show me my month wrapped") == ("month_wrapped", {})


def test_when_and_made_up_numbers():
    w, ctx, store, clock, prompts, published = make(dt.datetime(2026, 11, 1, 9, 0), proud="You walked 400 miles this month!")
    assert w.due_month() is None                                         # before 10 AM on the 1st
    clock.to(dt.datetime(2026, 11, 5, 9, 0))
    assert w.due_month() == "2026-10"                                    # the laptop was off: catch up
    clock.to(dt.datetime(2026, 11, 9, 12, 0))
    assert w.due_month() is None
    fill(store, ctx)
    data = w.make_month("2026-10")
    assert "proud" not in [s["kind"] for s in data["slides"]]           # "400" isn't in the facts: dropped
    assert month_range("2026-02") == (dt.date(2026, 2, 1), dt.date(2026, 2, 28))
    w2, *_ = make()
    assert w2.make_month("2026-10") is None                             # nothing happened: no recap
