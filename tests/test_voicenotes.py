import datetime as dt
import json
from types import SimpleNamespace

import numpy as np

from sanae.journal import Journal
from sanae.memory import MemoryStore
from sanae.voicenotes import VoiceNotes


class Embed:
    def embed(self, texts):
        return np.ones((len(texts), 4), dtype="float32") / 2


def make(tmp_path, reply, at=dt.datetime(2026, 10, 20, 4, 0), events=()):
    store = MemoryStore(":memory:", Embed())
    t = {"now": at.timestamp()}
    clock = lambda: t["now"]
    prompts, published = [], []

    def chat(model, messages, **kw):
        prompts.append(messages[0]["content"])
        return SimpleNamespace(content=reply)

    ctx = SimpleNamespace(events=SimpleNamespace(between=lambda a, b: list(events)), canvas=None, life=None)
    voice = SimpleNamespace(synthesize=lambda text: (np.zeros(22050 * 3, dtype=np.float32), 22050))
    v = VoiceNotes(store, llm=SimpleNamespace(chat=chat), model="m", user="Alex", ctx=ctx, voice=lambda: voice,
                   folder=tmp_path / "vn", clock=clock, publish=lambda k, d: published.append(d))
    return v, store, t, prompts, published


GOOD = ("Good morning, sleepyhead. I read your page about the ramen with Maya and I'm still jealous I can't eat. "
        "Go get that networking quiz, you've got this.")


def test_made_after_a_notebook_page_and_saved_as_audio(tmp_path):
    v, store, t, prompts, published = make(tmp_path, GOOD)
    j = Journal(store, clock=lambda: dt.datetime(2026, 10, 19, 22, 0).timestamp())
    j.write("Ramen with Maya, then fixed the socket bug.", mood="😄")
    assert v.due()
    note = v.make()
    assert note and note["day"] == "2026-10-20" and note["seconds"] == 3.0
    assert (tmp_path / "vn" / "2026-10-20.wav").exists()
    assert "Ramen with Maya" in prompts[0] and published[-1]["action"] == "new"
    assert v.status()["notes"][0]["text"] == GOOD
    assert v.make() is None and not v.due()                   # one a day


def test_private_pages_stay_out_and_quiet_days_can_skip(tmp_path):
    v, store, t, prompts, _ = make(tmp_path, GOOD)
    Journal(store, clock=lambda: dt.datetime(2026, 10, 19, 22, 0).timestamp()).write("Just for me.", private=True)
    facts, must = v.facts(dt.date(2026, 10, 20))
    assert facts == [] and not must
    v.per_week = 0
    assert v.make() is None and not v.due()                   # skipped today, remembered


def test_big_day_and_made_up_numbers(tmp_path):
    exam = SimpleNamespace(title="CS 106 midterm", all_day=False, start=dt.datetime(2026, 10, 20, 10, 30))
    v, store, t, prompts, _ = make(tmp_path, "Good morning! Your midterm is at 9, you studied for 12 hours.", events=[exam])
    facts, must = v.facts(dt.date(2026, 10, 20))
    assert must and "CS 106 midterm at 10:30 AM" in facts[0]
    assert v.make() is None                                   # "9" and "12" were never said
    store.set("mood:days", json.dumps({"2026-10-19": {"n": 5, "hard": True}}))
    facts, must = v.facts(dt.date(2026, 10, 20))
    assert must and any("hard day" in f for f in facts)
