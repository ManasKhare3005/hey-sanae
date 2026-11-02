"""Someone else typing "... ~Name" (guests.py): parsed, answered as that person, kept apart from the user."""
import datetime as dt

import pytest

from sanae.guests import Guests, split
from sanae.llm import ChatReply
from sanae.memory import MemoryStore
from sanae.persona import Persona
from tests.test_journal import Embed
from tests.test_sanae import FakeLLM, make_agent, make_registry


@pytest.mark.parametrize("text,expected", [
    ("hiii how are you ~Nina", ("hiii how are you", "Nina")),
    ("what's up~ nina", ("what's up", "Nina")),
    ("hello there ~ aunt meera", ("hello there", "Aunt Meera")),
    ("ok see you~Maya ", ("ok see you", "Maya")),
    ("remind me in ~5 minutes", ("remind me in ~5 minutes", None)),     # not a name
    ("~Nina", ("~Nina", None)),                                  # nothing said
    ("it's me ~Alex", ("it's me", None)),                             # the user themself
    ("no tag here", ("no tag here", None)),
])
def test_split(text, expected):
    assert split(text, "Alex") == expected


def make_guests(people=None):
    return Guests(MemoryStore(":memory:", Embed()), people or {}, "Alex", "Sanae")


def test_note_for_someone_new_and_known():
    g = make_guests({"Nina": {"about": "{user}'s best friend from school", "style": "Tease her about her cat"}})
    now = dt.datetime(2026, 10, 23, 18, 0)
    new = g.note(g.get("Ravi"), now)
    assert "from Ravi, not Alex" in new and "first time" in new and "Tease less" in new
    assert "private things" in new
    s = g.get("nina")
    known = g.note(s, now)
    assert "Alex's best friend from school" in known and "Tease her about her cat" in known
    g.add(s, "i got a new kitten!", "[happy] No way, what's her name?", now - dt.timedelta(days=2))
    s = g.get("Nina")
    later = g.note(s, now)
    assert "talked with Nina before" in later and "2 days ago" in later and "new kitten" in later
    assert "[happy]" not in later
    assert g.history(s, now) == []                       # an old chat is only a note
    g.add(s, "she's called Mochi", "[laugh] Mochi! Perfect.", now - dt.timedelta(minutes=5))
    hist = g.history(g.get("Nina"), now)
    assert [m["role"] for m in hist] == ["user", "assistant"] and hist[0]["content"].endswith("she's called Mochi")
    assert [p["name"] for p in g.all()] == ["Nina"]
    assert g.forget("NINA") and g.all() == []


def test_agent_answers_the_guest_and_keeps_the_users_side_clean(tmp_path):
    reg = make_registry(tmp_path)
    llm = FakeLLM([ChatReply(content="Hi Nina! Nice to meet you."), ChatReply(content="Hey Alex.")])
    agent = make_agent(reg, llm)
    agent.persona = Persona()
    turns, noted = [], []
    agent.on_turn = lambda *a: turns.append(a)
    agent.notes = lambda text: noted.append(text) or ["ALEX MOOD NOTE"]
    agent.recall = lambda text: "Alex has an exam Friday"
    agent.guests = make_guests()

    reply = agent.handle("hi, who are you?", guest="Nina")
    assert reply == "Hi Nina! Nice to meet you."
    sent = llm.calls[0]
    user_msg = sent["messages"][-1]["content"]
    assert "from Nina, not Alex" in user_msg
    assert "ALEX MOOD NOTE" not in user_msg and "exam Friday" not in user_msg
    assert set(sent["tools"]) <= {"web_search", "weather", "get_datetime", "what_song", "media_control", "volume", "think_harder"}
    assert "open_app" not in sent["tools"]
    assert turns == [] and noted == []
    assert agent.history[0][0]["content"].endswith('(Nina typed this to you, not Alex: "hi, who are you?")')
    assert agent.guests.get("Nina").turns[0][1] == "hi, who are you?"
    llm.replies.insert(0, ChatReply(content="Still me!"))
    agent.handle("you again?", guest="Nina")
    again = llm.calls[1]["messages"]
    assert all(isinstance(m, dict) for m in again)       # her earlier exchange comes back as plain messages
    assert again[-2] == {"role": "assistant", "content": "Hi Nina! Nice to meet you."}

    agent.handle("back to me")                           # the user's own chat doesn't see hers
    mine = llm.calls[2]["messages"]
    assert "typed this to you, not Alex" in str(mine)        # she knows someone else talked...
    assert "from Nina, not Alex" not in mine[-1]["content"]   # ...but this one is the user
    assert "from Alex again" in mine[-1]["content"]
    assert len(turns) == 1
