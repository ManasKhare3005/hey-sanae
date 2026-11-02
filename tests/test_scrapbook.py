import datetime as dt
from types import SimpleNamespace

from sanae.bucket import Bucket
from sanae.drawings import Drawings
from sanae.memory import MemoryStore
from sanae.scrapbook import Scrapbook
from sanae.vision import Seen
from tests.test_journal import Clock, Embed


def make(tmp_path, caption="Our first sunrise, and you actually woke up for it"):
    clock = Clock(dt.datetime(2026, 10, 20, 7, 0))
    store = MemoryStore(":memory:", Embed())
    vision = SimpleNamespace(last=None, remember_s=600)
    drawings = Drawings(store, clock=clock)
    bucket = Bucket(store, clock=clock, drawings=drawings)
    llm = SimpleNamespace(chat=lambda model, messages, **kw: SimpleNamespace(content=caption))
    book = Scrapbook(store, clock=clock, vision=vision, drawings=drawings, bucket=bucket, llm=llm, model="m",
                     user="Alex", folder=tmp_path / "scrapbook")
    return book, vision, bucket, clock


def test_only_kept_when_they_say_so(tmp_path):
    book, vision, bucket, clock = make(tmp_path)
    assert book.route("keep that one") is None                 # no photo in memory: nothing to keep
    bucket.add("watch the sunrise from a hill")
    vision.last = Seen("A sunrise over hills, orange sky and clouds.", "we did the sunrise!", clock(), b"\xff\xd8jpeg")
    note = book.notes("(Sent a photo) we did the sunrise!")
    assert note and "only kept if they say yes" in note[0]
    assert book.route("yes please", "Want me to put this in our scrapbook?") == ("keep_photo", {})
    assert book.route("put it in our scrapbook") == ("keep_photo", {})
    kept = book.keep()
    assert kept["caption"].startswith("Our first sunrise") and (tmp_path / "scrapbook" / f"{kept['id']}.jpg").read_bytes() == b"\xff\xd8jpeg"
    assert kept["drawing"] and kept["bucket"]                   # a sketch of the sky, and the bucket list ticked
    assert bucket.items()[0]["done_day"] == "2026-10-20"
    assert book.keep()["id"] == kept["id"]                      # saying it twice keeps it once
    month = book.status()["months"][0]
    assert month["label"] == "October 2026" and month["photos"][0]["drawing"]["subject"] == "the sky"
    clock.to(dt.datetime(2026, 10, 20, 7, 11))
    assert book.fresh() is None                                 # gone from memory after a few minutes
    assert book.delete(kept["id"]) and not (tmp_path / "scrapbook" / f"{kept['id']}.jpg").exists()


def test_captions_dont_invent_numbers(tmp_path):
    book, vision, _, clock = make(tmp_path, caption="Day 3 of your 10 day streak, look at you")
    vision.last = Seen("A latte with heart foam art on a wooden table.", "", clock(), b"jpeg")
    assert book.keep()["caption"] == "A latte with heart foam art on a wooden table."
    assert book.notes("(Sent a photo) here's my syllabus") == []   # documents aren't scrapbook moments
