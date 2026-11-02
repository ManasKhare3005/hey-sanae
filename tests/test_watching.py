import datetime as dt

from sanae.memory import MemoryStore
from sanae.watching import Watching, parse
from tests.test_journal import Clock, Embed


def test_titles_to_shows():
    w = parse("chrome.exe", "Watch Frieren: Beyond Journey's End Season 1 Episode 5 - Phantoms of the Dead - Crunchyroll")
    assert (w.show, w.season, w.episode, w.service) == ("Frieren: Beyond Journey's End", 1, 5, "Crunchyroll")
    w = parse("vlc.exe", "The.Bear.S02E03.1080p.WEB-DL.mkv - VLC media player")
    assert (w.show, w.kind, w.season, w.episode, w.service) == ("The Bear", "show", 2, 3, "VLC")
    w = parse("chrome.exe", "Netflix", "Stranger Things", "S4:E1 Chapter One: The Hellfire Club")
    assert (w.show, w.season, w.episode, w.ep_title) == ("Stranger Things", 4, 1, "Chapter One: The Hellfire Club")
    w = parse("chrome.exe", "Dune: Part Two | Prime Video")
    assert (w.show, w.kind) == ("Dune: Part Two", "movie")
    assert parse("chrome.exe", "How TCP really works - YouTube").kind == "video"
    assert parse("code.exe", "main.py - jarvis") is None
    assert parse("chrome.exe", "Netflix") is None                     # browsing, nothing playing


def test_watching_along(tmp_path):
    clock = Clock(dt.datetime(2026, 10, 20, 21, 0))
    now = {"read": ("vlc.exe", "The.Bear.S02E03.mkv - VLC media player", "", "")}
    idle = {"s": 400}
    w = Watching(MemoryStore(str(tmp_path / "w.db"), embedder=Embed()), clock=clock, read=lambda: now["read"],
                 idle=lambda: idle["s"])

    def tick():                     # what the initiative loop does every 30 s
        w.observe(clock())
        return w.moments(clock())

    for minute in range(0, 31, 1):
        clock.to(dt.datetime(2026, 10, 20, 21, minute))
        assert tick() == []
    assert w.quiet_reason() == "watching The Bear"
    now["read"] = ("vlc.exe", "The.Bear.S02E04.mkv - VLC media player", "", "")          # autoplay: the next one
    for minute in range(31, 60):
        clock.to(dt.datetime(2026, 10, 20, 21, minute))
        tick()
    now["read"] = ("code.exe", "main.py - jarvis", "", "")
    idle["s"] = 10
    clock.to(dt.datetime(2026, 10, 20, 22, 2))
    tick()
    assert w.quiet_reason() is None
    clock.to(dt.datetime(2026, 10, 20, 22, 5))
    after = tick()
    assert after and "season 2 episode 4" in after[0].situation and "no spoilers" in after[0].situation
    w.used(after[0], clock())
    assert [(r["episode"], r["minutes"]) for r in w.history()] == [(4, 28), (3, 30)]
    assert "The Bear (up to season 2 episode 4)" in w.spoken()
    assert "up to season 2 episode 4" in w.notes("the bear is so stressful")[0]
    clock.to(dt.datetime(2026, 10, 21, 19, 0))
    nxt = tick()
    assert nxt and nxt[0].key.startswith("next:") and "next one tonight" in nxt[0].situation
    assert w.route("what have I been watching lately?") == ("watch_history", {})
    assert w.status()["shows"][0]["where"] == "The Bear (up to season 2 episode 4)"


def test_movie_night():
    import json

    store = MemoryStore(":memory:", Embed())
    clock = Clock(dt.datetime(2026, 10, 24, 19, 0))
    now = {"read": ("", "", "", "")}
    w = Watching(store, clock=clock, read=lambda: now["read"], bedtime="00:30")
    assert w.route("what should we watch tonight?") == ("what_to_watch", {})
    assert "watchlist's empty" in w.pick_words()
    assert w.route("add Dune: Part Two to our watchlist") == ("add_to_watchlist", {"title": "Dune: Part Two"})
    assert w.route("we should watch Arcane sometime") == ("add_to_watchlist", {"title": "Arcane"})
    assert w.route("we should watch out for that") is None
    assert w.route("take arcane off the watchlist") == ("drop_from_watchlist", {"title": "arcane"})
    w.add_watch("Dune: Part Two")
    assert w.add_watch("dune part two")["id"] == 1                      # no duplicate
    w.add_watch("Arcane season 2")
    assert [x["kind"] for x in w.watchlist()] == ["movie", "show"]
    # a free evening (5.5 h till bed): the movie
    assert w.minutes_left() == 330
    p = w.pick()
    assert p["pick"] == "Dune: Part Two" and p["alt"]["pick"] == "Arcane season 2"
    # a show in progress, late and worn out: the next episode instead
    for minute in range(0, 30):
        clock.to(dt.datetime(2026, 10, 24, 22, minute))
        now["read"] = ("vlc.exe", "The.Bear.S02E03.mkv - VLC media player", "", "")
        w.observe(clock())
    now["read"] = ("", "", "", "")
    clock.to(dt.datetime(2026, 10, 24, 23, 45))
    w.observe(clock())
    store.set("mood:days", json.dumps({"2026-10-24": {"n": 5, "tired": 2}}))
    assert w.minutes_left() == 45 and w.day_mood() == "tired"
    p = w.pick()
    assert p["pick"] == "The Bear, season 2 episode 4" and "long day" in p["why"]
    # watching the movie ticks it off the watchlist
    clock.to(dt.datetime(2026, 10, 25, 20, 0))
    now["read"] = ("chrome.exe", "Dune: Part Two | Prime Video", "", "")
    for minute in range(0, 40):
        clock.to(dt.datetime(2026, 10, 25, 20, minute))
        w.observe(clock())
    now["read"] = ("", "", "", "")
    clock.to(dt.datetime(2026, 10, 25, 21, 0))
    w.observe(clock())
    assert [x["title"] for x in w.watchlist()] == ["Arcane season 2"]
    assert w.status()["tonight"]["pick"]


def test_movie_log():
    clock = Clock(dt.datetime(2026, 10, 24, 20, 0))
    now = {"read": ("chrome.exe", "Dune: Part Two | Prime Video", "", "")}
    w = Watching(MemoryStore(":memory:", Embed()), clock=clock, read=lambda: now["read"], idle=lambda: 10)
    for minute in range(0, 150, 1):
        clock.to(dt.datetime(2026, 10, 24, 20, 0) + dt.timedelta(minutes=minute))
        w.observe(clock())
    now["read"] = ("explorer.exe", "", "", "")
    clock.to(dt.datetime(2026, 10, 24, 22, 40))
    w.observe(clock())
    clock.to(dt.datetime(2026, 10, 24, 22, 45))
    w.observe(clock())
    assert [(r["title"], r["stars"]) for r in w.movie_log()] == [("Dune: Part Two", 0)]
    m = w.moments(clock())[0]
    assert "stars out of 5" in m.situation
    w.used(m, clock())
    # their answer sets the stars; her reply to it is her take
    note = w.notes("honestly so good, 9/10", "[happy] Movie's over! How was Dune? Stars out of 5?")
    assert "rated Dune: Part Two 5 out of 5" in note[0]
    w.notes("what's next", "[happy] Five stars?! The sandworms must've won you over. I'm jealous I missed it!")
    r = w.movie_log()[0]
    assert r["stars"] == 5 and r["your_take"] == "honestly so good, 9/10"
    assert r["her_take"] == "Five stars?! The sandworms must've won you over."
    # by hand
    assert w.route("rate Dune Part Two 4 stars") == ("rate_movie", {"title": "Dune Part Two", "stars": 4})
    assert w.route("rate the movie Arrival 8/10") == ("rate_movie", {"title": "Arrival", "stars": 4})
    assert w.route("rate this burger 5 stars") is None                    # not a movie she knows of
    assert w.route("what's in our movie log?") == ("movie_log", {})
    assert w.route("add Past Lives to our movie log") == ("rate_movie", {"title": "Past Lives", "stars": 0})
    w.rate_movie("Arrival", 4)
    assert w.log_words() == ("Our movie log (2): Arrival (4 stars); Dune: Part Two (5 stars). "
                             "Favourites so far: Dune: Part Two, Arrival.")
    assert w.status()["log"][1]["her_take"].startswith("Five stars")
    assert w.remove_logged(w.find_logged("Arrival")["id"]) and len(w.movie_log()) == 1
