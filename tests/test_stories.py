import datetime as dt
import json
import random
from types import SimpleNamespace

from sanae.memory import MemoryStore
from sanae.stories import Stories
from tests.test_journal import Clock, Embed

CHAPTER = " ".join(["Mochi the lighthouse cat yawned and watched the boats come home."] * 18)


def make(tmp_path):
    prompts = []

    def chat(model, messages, **kw):
        prompts.append(messages[0]["content"])
        n = len(prompts)
        return SimpleNamespace(content=json.dumps({"title": f"The {n} lanterns", "text": CHAPTER,
                                                   "summary": f"Summary of chapter {n}."}))

    diary = SimpleNamespace(moments=lambda: [SimpleNamespace(kind="nickname", text="Captain Sleepyhead"),
                                             SimpleNamespace(kind="joke", text="the pasta disaster"),
                                             SimpleNamespace(kind="memory", text="the hike")])
    s = Stories(MemoryStore(":memory:", Embed()), clock=Clock(dt.datetime(2026, 10, 20, 23, 30)),
                llm=SimpleNamespace(chat=chat), model="m", user="Alex", diary=diary, rng=random.Random(1),
                folder=tmp_path / "stories")
    return s, prompts


def test_a_serial_that_carries_on(tmp_path):
    s, prompts = make(tmp_path)
    assert s.route("can you tell me a bedtime story?") == ("bedtime_story", {"again": False})
    one = s.tell()
    assert one.startswith("Chapter 1: The 1 lanterns. Mochi")
    assert "Captain Sleepyhead" in prompts[0] and "the pasta disaster" in prompts[0] and "very first chapter" in prompts[0]
    s.tell()
    assert "Chapter 1 (The 1 lanterns): Summary of chapter 1." in prompts[1]
    assert s.bible()["place"] in prompts[0] and s.bible()["place"] in prompts[1]      # the same world every night
    assert s.route("read last night's story again") == ("bedtime_story", {"again": True})
    assert s.tell(again=True).startswith("Chapter 2:") and len(prompts) == 2
    assert s.route("yes please", "Want me to tell you the next part of our story?") == ("bedtime_story", {"again": False})
    assert s.route("tell me a joke") is None
    assert [c["n"] for c in s.status()["chapters"]] == [2, 1]
