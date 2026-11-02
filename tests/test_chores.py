"""Routine (chores.py): frequency rules, voice tools, the API, phone sync and the morning briefing."""
import datetime as dt

from sanae.chores import chore_route, due_on, label, parse_freq
from sanae.tools import memory as memory_tools
from sanae.tools.registry import ToolRegistry
from test_sanae import api_client

TUE = dt.date(2026, 10, 20)


def test_parse_freq():
    assert parse_freq("every day", TUE) == "daily"
    assert parse_freq("daily", TUE) == "daily"
    assert parse_freq("every morning", TUE) == "daily"
    assert parse_freq("on weekdays", TUE) == "weekdays"
    assert parse_freq("every Sunday", TUE) == "weekly:6"
    assert parse_freq("sundays", TUE) == "weekly:6"
    assert parse_freq("weekly on monday", TUE) == "weekly:0"
    assert parse_freq("weekly", TUE) == "weekly:1"                # from today (a Tuesday)
    assert parse_freq("on the 5th of every month", TUE) == "monthly:5"
    assert parse_freq("every month on the 1st", TUE) == "monthly:1"
    assert parse_freq("monthly", TUE) == "monthly:20"
    assert parse_freq("sometimes", TUE) is None


def test_due_on_and_labels():
    assert due_on("daily", TUE)
    assert due_on("weekdays", TUE) and not due_on("weekdays", dt.date(2026, 10, 25))
    assert due_on("weekly:1", TUE) and not due_on("weekly:6", TUE)
    assert due_on("monthly:20", TUE) and not due_on("monthly:21", TUE)
    assert due_on("monthly:31", dt.date(2026, 11, 30))            # short month: its last day
    assert not due_on("monthly:31", dt.date(2026, 11, 29))
    assert label("weekly:6") == "every Sunday"
    assert label("monthly:1") == "monthly on the 1st"
    assert label("monthly:22") == "monthly on the 22nd"
    assert label("monthly:12") == "monthly on the 12th"


def test_routine_by_voice_and_briefing():
    client, rt = api_client()
    rt.ctx.bus = rt.bus
    rt.ctx.chores.today = lambda: TUE
    reg = ToolRegistry(context=rt.ctx)
    memory_tools.register(reg)
    assert reg.run("routine_today", {}).startswith("Your routine is empty.")
    assert reg.run("add_routine_task", {"task": "water the plants", "how_often": "every day"}) == \
        "Added to your routine: water the plants, every day."
    assert reg.run("add_routine_task", {"task": "laundry", "how_often": "every Sunday"}) == \
        "Added to your routine: laundry, every Sunday."
    reg.run("add_routine_task", {"task": "gym", "how_often": "tuesdays"})
    assert reg.run("add_routine_task", {"task": "x", "how_often": "now and then"}).startswith("Error:")
    assert reg.run("routine_today", {}) == "Still to do today: water the plants and gym."
    assert rt.ctx.chores.briefing_sentence() == "On your routine today: water the plants and gym."
    assert reg.run("check_routine_task", {"which": "plants"}) == "Ticked off for today: water the plants. 1 left today."
    assert reg.run("routine_today", {}) == "Still to do today: gym. Already done: water the plants."
    assert reg.run("check_routine_task", {"which": "plants", "done": False}) == "Unticked: water the plants."
    assert reg.run("routine_today", {"which": "all"}) == \
        "Your routine: water the plants, every day; laundry, every Sunday; gym, every Tuesday."
    assert reg.run("remove_routine_task", {"which": "laundry"}) == "Took it off your routine: laundry (every Sunday)."
    assert [e["kind"] for e in rt.bus.recent].count("routine") >= 4      # the phone syncs on these


def test_routine_api_and_phone_sync():
    client, rt = api_client()
    chores = rt.ctx.chores
    chores.today = lambda: TUE
    made = client.post("/api/routine", json={"text": "take vitamins", "freq": "daily"}).json()
    assert made["label"] == "every day" and made["due_today"] and not made["done"]
    assert client.post("/api/routine", json={"text": "rent", "freq": "on the 1st of every month"}).json()["freq"] == "monthly:1"
    assert client.post("/api/routine", json={"text": "x", "freq": "whenever"}).status_code == 400
    uid = made["uid"]
    assert client.post(f"/api/routine/{uid}", json={"done": True}).json()["done"] is True
    assert [c["text"] for c in client.get("/api/today").json()["routine"]] == ["take vitamins"] or \
        dt.date.today().day == 1
    # the phone unticked it later, added one, and removed rent
    rent = chores.find("rent")
    later = chores.by_uid(uid).updated + 5
    out = client.post("/api/sync", json={"routine": [
        {"uid": uid, "text": "take vitamins", "freq": "daily", "done_day": "", "status": "active", "updated_ms": later},
        {"uid": "ph1", "text": "stretch", "freq": "weekdays", "done_day": "", "status": "active", "updated_ms": later},
        {"uid": rent.uid, "text": "rent", "freq": "monthly:1", "status": "deleted", "updated_ms": 1},
        {"uid": "bad", "text": "?", "freq": "sometimes", "updated_ms": later},
    ]}).json()
    assert chores.by_uid(uid).done_day == ""
    assert chores.by_uid("ph1").freq == "weekdays"
    assert chores.by_uid(rent.uid).status == "deleted"
    assert chores.by_uid("bad") is None
    assert {c["uid"]: c["status"] for c in out["routine"]} == {uid: "active", rent.uid: "deleted", "ph1": "active"}
    assert client.delete(f"/api/routine/{uid}").json() == {"ok": True}
    assert [c["text"] for c in client.get("/api/routine").json()] == ["stretch"]


def test_routine_question_skips_the_model():
    assert chore_route("what's on my routine today?") == ("routine_today", {})
    assert chore_route("what's left on my routine") == ("routine_today", {})
    assert chore_route("show me today's routine") == ("routine_today", {})
    assert chore_route("add gym to my routine") == ("add_routine_task", {"task": "gym", "how_often": ""})   # she asks


def test_routine_requests_done_in_code():
    _, rt = api_client()
    chores = rt.ctx.chores
    chores.today = lambda: TUE
    route = lambda text: chore_route(text, chores)
    assert route("add water the plants to my routine, every day") == \
        ("add_routine_task", {"task": "water the plants", "how_often": "daily"})
    assert route("I need to do laundry every Sunday, put it in my routine") == \
        ("add_routine_task", {"task": "do laundry", "how_often": "weekly:6"})
    assert route("pay rent on the 1st of every month, add that to my routine") == \
        ("add_routine_task", {"task": "pay rent", "how_often": "monthly:1"})
    assert route("what's my whole routine?") == ("routine_today", {"which": "all"})
    assert route("take laundry off my routine") == ("remove_routine_task", {"which": "laundry"})
    chores.add("water the plants", "daily")
    chores.add("do laundry", "weekly:6")
    assert route("I watered the plants") == ("check_routine_task", {"which": "water the plants"})
    assert route("I didn't water the plants yet") == ("check_routine_task", {"which": "water the plants", "done": False})
    assert route("I love plants") is None
    assert route("I needed to water the plants") is None
    assert route("I did the laundry") is None                  # not due today (Sundays): the model / todos handle it
    assert route("add milk to my list") is None


def test_she_asks_how_often():
    _, rt = api_client()
    chores = rt.ctx.chores
    reg = ToolRegistry(context=rt.ctx)
    memory_tools.register(reg)
    assert chore_route("add gym to my routine", chores) == ("add_routine_task", {"task": "gym", "how_often": ""})
    assert reg.run("add_routine_task", {"task": "gym", "how_often": ""}).startswith('How often should I put "gym"')
    assert chore_route("mondays", chores) == ("add_routine_task", {"task": "gym", "how_often": "weekly:0"})
    reg.run("add_routine_task", {"task": "gym", "how_often": "weekly:0"})
    assert chores.asking is None and chore_route("mondays", chores) is None
