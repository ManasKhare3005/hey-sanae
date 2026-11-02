"""Sanae for Claude Desktop (mcp_server.py): the protocol, and private things staying out."""
import datetime as dt
import io
import json

from sanae import mcp_server as m
from sanae.memory import MemoryStore
from tests.test_journal import Embed

NOW = dt.datetime(2026, 10, 29, 12, 0)


def make_db(tmp_path):
    path = tmp_path / "sanae.db"
    store = MemoryStore(str(path), Embed())
    from sanae.journal import Journal
    Journal(store)
    with store.lock:
        x = store.db.execute
        x("INSERT INTO turns (id, ts, user, reply, heard) VALUES (1, '2026-10-28T19:24:00', 'I started my new job', 'Proud of you!', '')")
        x("INSERT INTO turns (id, ts, user, reply, heard) VALUES (2, '2026-10-28T23:00:00', 'I feel awful tonight', 'I am here.', '')")
        x("INSERT INTO turns (id, ts, user, reply, heard) VALUES (3, '2026-10-28T23:10:00', 'turn it up', 'Done', 'other')")
        x("INSERT INTO turns (id, ts, user, reply, heard) VALUES (4, '2026-10-28T23:20:00', 'my doctor changed my pills. Maya says hi', 'Say hi back!', '')")
        x("INSERT INTO kv (key, value) VALUES ('comfort:turns', '[2]')")
        x("INSERT INTO diary (day, text, created, updated, mood) VALUES ('2026-10-27', 'Alex started work and loved it.', 'a', 'a', 'good')")
        x("INSERT INTO diary (day, text, created, updated, mood) VALUES ('2026-10-28', 'A rough night, we talked.', 'a', 'a', 'a hard day')")
        x("INSERT INTO journal (uid, day, author, kind, text, private, created) VALUES ('a', '2026-10-27', 'you', 'page', 'First day at work!', 0, 'x')")
        x("INSERT INTO journal (uid, day, author, kind, text, private, created) VALUES ('b', '2026-10-27', 'you', 'page', 'First day at work!', 0, 'x')")
        x("INSERT INTO journal (uid, day, author, kind, text, private, created) VALUES ('c', '2026-10-27', 'you', 'page', 'A secret page', 1, 'x')")
        x("INSERT INTO about (text, kind, created, updated, mentions, vec) VALUES ('Alex likes Valorant', 'like', 'a', 'a', 1, x'')")
        x("INSERT INTO about (text, kind, created, updated, mentions, vec) VALUES ('Alex has a bank loan', 'other', 'a', 'a', 1, x'')")
        x("INSERT INTO todos (uid, text, status, created, updated) VALUES ('t1', 'buy milk', 'open', '2026-10-28', 1)")
        x("INSERT INTO events (uid, title, start, end, all_day, location, status, created, updated) VALUES "
          "('e1', 'Study group', '2026-10-30T14:00:00', '2026-10-30T15:00:00', 0, 'Library', 'active', 'x', 1)")
        store.db.commit()
    store.db.close()
    return path


def test_private_things_stay_out(tmp_path):
    db = m.connect(make_db(tmp_path))
    chats = m.recent_chats(db)
    assert "I started my new job" in chats and "awful" not in chats and "turn it up" not in chats
    assert "pills" not in chats and "Maya says hi" in chats                # health sentence out, names kept
    d = m.diary(db, 7, NOW)
    assert "started work and loved it" in d and "rough night" not in d and "(a private day, not shared)" in d
    n = m.notebook(db, 14, NOW)
    assert n.count("First day at work") == 1 and "secret" not in n
    knows = m.what_she_knows(db)
    assert "Valorant" in knows and "loan" not in knows
    assert "Valorant" in m.what_she_knows(db, "games valorant") and m.what_she_knows(db, "pizza") == "Nothing about that."
    up = m.upcoming(db, 7, NOW)
    assert "Study group: Fri Oct 30, 2:00 PM at Library" in up and "To do: buy milk" in up


def test_protocol(tmp_path, monkeypatch):
    out = io.StringIO()
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "sanae_recent_chats", "arguments": {"query": "job"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "sanae_add_todo", "arguments": {"text": "milk"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "nope"}]
    monkeypatch.setattr(m, "DB", make_db(tmp_path))
    monkeypatch.setattr(m, "API", "http://127.0.0.1:9")                      # Sanae not running
    m.serve(io.StringIO("\n".join(json.dumps(x) for x in msgs) + "\n"), out)
    replies = [json.loads(l) for l in out.getvalue().splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3, 4, 5]                      # the notification got no answer
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    names = [t["name"] for t in replies[1]["result"]["tools"]]
    assert "sanae_today" in names and "sanae_add_reminder" in names
    assert "I started my new job" in replies[2]["result"]["content"][0]["text"]
    assert replies[3]["result"]["isError"] and "isn't running" in replies[3]["result"]["content"][0]["text"]
    assert replies[4]["error"]["code"] == -32601


def test_install_keeps_the_rest_of_the_config(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"preferences": {"sidebarMode": "chat"}}), encoding="utf-8")
    m.install(cfg)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["preferences"] == {"sidebarMode": "chat"}
    assert data["mcpServers"]["sanae"]["args"] == ["-m", "sanae.mcp_server"]
    assert json.loads((tmp_path / "claude_desktop_config.json.before-sanae").read_text(encoding="utf-8")) == {"preferences": {"sidebarMode": "chat"}}
