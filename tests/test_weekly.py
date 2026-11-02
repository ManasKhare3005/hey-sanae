import datetime as dt
import json
from types import SimpleNamespace

import numpy as np

from sanae.journal import Journal
from sanae.memory import MemoryStore
from sanae.together import Together
from sanae.weekly import Weekly


class Embed:
    def embed(self, texts):
        return np.ones((len(texts), 4), dtype="float32") / 2


def test_week_story_from_true_things():
    store = MemoryStore(":memory:", Embed())
    t = {"now": dt.datetime(2026, 10, 12, 9).timestamp()}          # Monday
    clock = lambda: t["now"]
    together = Together(store, clock=clock)
    a = together.add("read 20 minutes")
    for day in range(12, 18):
        t["now"] = dt.datetime(2026, 10, day, 21).timestamp()
        together.log(a)
        with store.lock:
            store.db.execute("INSERT INTO turns (ts, user, reply) VALUES (?, 'hi', 'hey')", (f"2026-10-{day}T21:00:00",))
            store.db.commit()
    Journal(store, clock=clock).write("Good day, finished the lab.", mood="😄")
    store.set("mood:days", json.dumps({"2026-10-13": {"n": 4, "nice": 2}, "2026-10-15": {"n": 3, "excited": 1},
                                       "2026-10-16": {"n": 5, "nice": 1}}))
    diary = SimpleNamespace(entries=lambda n: [SimpleNamespace(day="2026-10-15", text="Alex finally fixed the socket bug. Then pizza.", mood="great")],
                            moments=lambda: [SimpleNamespace(kind="joke", text="Professor Byte", day="2026-10-14")])
    wins = SimpleNamespace(recent=lambda days: [{"day": "2026-10-14", "text": "pushed 5 commits to Chat Room"},
                                                {"day": "2026-10-02", "text": "old win"}])
    rituals = SimpleNamespace(week_ahead=lambda d: ["CS 106 midterm (Thu 10:30 AM)", "Lab 4 due Fri"])
    ctx = SimpleNamespace(together=together, goals=None, wins=wins, diary=diary, rituals=rituals)
    prompts = []

    def chat(model, messages, **kw):
        prompts.append(messages[0]["content"])
        return SimpleNamespace(content="Six days of reading in a row, while fixing that socket bug? I'm so proud of you.")

    published = []
    t["now"] = dt.datetime(2026, 10, 18, 19).timestamp()           # Sunday evening
    w = Weekly(store, ctx=ctx, llm=SimpleNamespace(chat=chat), model="m", user="Alex", clock=clock,
               publish=lambda k, d: published.append(d))
    assert w.due_start() == dt.date(2026, 10, 12)
    data = w.make(w.due_start())
    kinds = [s["kind"] for s in data["slides"]]
    assert kinds == ["cover", "together", "wins", "notebook", "moment", "proud", "next"]
    cover, tog, wins_s, nb, mom, proud, nxt = data["slides"]
    assert cover["feel"] == "a really good week" and cover["talked"] == 6 and cover["range"] == "Oct 12 – Oct 18"
    assert tog["done"] == 6 and tog["best"] == {"title": "read 20 minutes", "streak": 6, "unit": "days"}
    assert "a little sprout" in tog["room"] and wins_s["items"] == ["pushed 5 commits to Chat Room"]
    assert nb["pages"] == 1 and nb["moods"] == ["😄"] and nb["highlight"] == "Alex finally fixed the socket bug."
    assert mom["text"] == "Professor Byte" and "6 days in a row" in prompts[0]
    assert published[-1]["action"] == "new" and w.make(w.due_start()) is None
    assert w.status()["weeks"][0]["week"] == "2026-W42"
