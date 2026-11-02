"""Our playlist (playlist.py) + phone media: songs vs. videos from YouTube ReVanced (roommate.py -> watching.py)."""
import datetime as dt
from types import SimpleNamespace

from sanae.memory import MemoryStore
from sanae.playlist import Playlist, song_key, tidy
from sanae.roommate import Roommate
from sanae.watching import Watching
from tests.test_journal import Clock, Embed


def make(at=dt.datetime(2026, 10, 20, 20, 0)):
    store = MemoryStore(":memory:", Embed())
    clock = Clock(at)
    playing = {"t": None}
    p = Playlist(store, clock=clock, now_playing=lambda: playing["t"], find=lambda t, a: "abcdefghijk" if "Espresso" in t else "",
                 idle=lambda: 10)
    return p, clock, playing, store


def test_tidy_youtube_titles():
    assert tidy("Sabrina Carpenter - Espresso (Official Video)", "SabrinaCarpenterVEVO") == ("Espresso", "Sabrina Carpenter")
    assert tidy("Espresso", "Sabrina Carpenter - Topic") == ("Espresso", "Sabrina Carpenter")
    assert song_key("Espresso (feat. X)", "Sabrina") == song_key("espresso", "sabrina")


def test_on_repeat_three_days_becomes_ours():
    p, clock, playing, _ = make()
    for day in (20, 22):
        clock.to(dt.datetime(2026, 10, day, 20, 0))
        assert p.heard("Espresso", "Sabrina Carpenter") is None
        assert p.heard("Espresso", "Sabrina Carpenter") is None          # twice a day is still one day
    clock.to(dt.datetime(2026, 10, 25, 9, 0))
    row = p.heard("Sabrina Carpenter - Espresso (Official Video)", "SabrinaCarpenterVEVO", "phone")
    assert row["title"] == "Espresso" and row["why"] == "on repeat for 3 days in mid October"
    import time
    for _ in range(50):
        if p.items()[0]["video_id"]:
            break
        time.sleep(0.02)
    assert p.status()["play_url"] == "https://www.youtube.com/watch_videos?video_ids=abcdefghijk"
    m = p.moments(clock())[0]
    assert "on repeat for 3 days" in m.situation
    p.used(m, clock())
    assert p.moments(clock()) == []
    assert p.heard("Espresso", "Sabrina Carpenter") is None            # already ours


def test_add_this_song_and_routes():
    p, clock, playing, _ = make()
    assert p.route("add this song to our playlist") == ("add_to_playlist", {})
    assert p.route("play our playlist") == ("play_playlist", {})
    assert p.route("what's on our playlist?") == ("our_playlist", {})
    assert p.add_now() is None                                          # nothing playing
    playing["t"] = SimpleNamespace(title="Golden Hour", artist="JVKE", playing=True)
    r = p.add_now()
    assert r["title"] == "Golden Hour" and r["why"].startswith("you added it on October 20")
    assert p.status()["songs"][0]["url"].startswith("https://www.youtube.com/results?search_query=Golden+Hour+JVKE")
    assert p.route("take golden hour off our playlist") == ("remove_from_playlist", {"which": "golden hour"})
    assert "Golden Hour by JVKE" in p.spoken()


def test_phone_youtube_revanced_video_vs_music():
    p, clock, _, store = make()
    w = Watching(store, clock=clock, read=lambda: ("", "", "", ""))
    r = Roommate(store, clock=clock)
    r.playlist, r.watching = p, w
    vid = {"title": "I Built a Mechanical Keyboard From Scratch", "artist": "Some Channel", "package": "app.revanced.android.youtube"}
    assert r.report({"playing": vid}) == ["watching:I Built a Mechanical Keyboard From Scratch"]
    for minutes in (4, 8, 12, 16):
        clock.to(dt.datetime(2026, 10, 20, 20, minutes))
        r.report({"playing": vid})
    clock.to(dt.datetime(2026, 10, 20, 20, 40))
    w.observe(clock())                                                  # no report for 10+ min: it's over
    assert [(x["show"], x["kind"], x["minutes"]) for x in w.history(1)] == [("I Built a Mechanical Keyboard From Scratch", "video", 20)]
    song = {"title": "Sabrina Carpenter - Espresso (Official Music Video)", "artist": "SabrinaCarpenterVEVO",
            "package": "app.revanced.android.youtube"}
    r.report({"playing": song})
    assert "espresso|sabrinacarpenter" in p.get("plays")
    # 3 days on the phone: the roommate tease says it's on the playlist, no second line from the playlist
    for day in (21, 22):
        clock.to(dt.datetime(2026, 10, day, 20, 0))
        r.report({"playing": song})
    assert "shared playlist" in r.phone_moments(clock())[0].situation
    assert p.moments(clock()) == [] and len(p.items()) == 1


def test_song_of_the_week():
    p, clock, playing, _ = make(dt.datetime(2026, 10, 19, 20, 0))
    assert p.week_song(pick=True) is None                              # empty playlist
    p.add("Espresso", "Sabrina Carpenter", "you added it")
    p.add("Pink + White", "Frank Ocean", "you added it")
    for day in (20, 21, 23):                                           # Mon, Tue, Thu
        clock.to(dt.datetime(2026, 10, day, 21, 0))
        p.heard("Pink + White", "Frank Ocean")
    clock.to(dt.datetime(2026, 10, 25, 10, 0))                         # Sunday morning: not yet
    assert p.moments(clock()) == [] and "I pick one from our playlist on Sundays" in p.week_words()
    clock.to(dt.datetime(2026, 10, 25, 12, 0))
    m = p.moments(clock())[0]
    assert '"Pink + White" by Frank Ocean, because you played it on 3 days this week' in m.situation
    assert p.phone_moments(clock())[0].key == m.key == "week:2026-W43"
    p.used(m, clock())
    assert p.moments(clock()) == [] and p.status()["week_song"]["title"] == "Pink + White"
    assert p.route("what's our song of the week?") == ("song_of_the_week", {})
    # all week it stays; next Sunday another one (not the same twice in a row)
    clock.to(dt.datetime(2026, 10, 29, 9, 0))
    assert p.week_words().startswith("Our song of the week: Pink + White")
    clock.to(dt.datetime(2026, 11, 1, 12, 0))
    w = p.week_song(pick=True)
    assert w["title"] == "Espresso" and w["why"] == "it's been ours since mid October and never had its week"
    assert p.month_top("2026-10") == [{"title": "Pink + White", "artist": "Frank Ocean", "days": 3}]
