"""Todo list (todos.py): voice tools, the API the phone and its widget use, and phone sync."""
from sanae.todos import split_items
from sanae.tools import memory as memory_tools
from sanae.tools.registry import DECLINED, ToolRegistry
from test_sanae import api_client


def test_split_items():
    assert split_items("milk, eggs and bread") == ["milk", "eggs", "bread"]
    assert split_items("call mom and dad") == ["call mom and dad"]
    assert split_items("finish the lab report.") == ["finish the lab report"]
    assert split_items("  ") == []


def test_todo_tools_by_voice():
    client, rt = api_client()
    answers = []
    rt.ctx.confirm = lambda prompt: answers.append(prompt) or False
    rt.ctx.bus = rt.bus
    reg = ToolRegistry(context=rt.ctx)
    memory_tools.register(reg)
    assert reg.run("list_todos", {}) == "Your todo list is empty."
    assert reg.run("add_todo", {"items": "milk, eggs and bread"}) == "Added to your list: milk, eggs and bread. That's 3 open."
    reg.run("add_todo", {"items": "finish the networking lab"})
    assert reg.run("list_todos", {}).startswith("You have 4 things on your list: milk; eggs; bread; finish")
    assert reg.run("check_todo", {"which": "the networking lab"}) == "Ticked off: finish the networking lab. 3 left."
    assert reg.run("check_todo", {"which": "eggs"}).startswith("Ticked off: eggs")
    assert [t["done"] for t in client.get("/api/todos").json()] == [False, False, True, True]   # open first
    assert reg.run("clear_todos", {"which": "milk"}) == "Took it off your list: milk."
    assert reg.run("clear_todos", {"which": "done"}) == "Cleared 2 finished items."
    assert reg.run("clear_todos", {"which": "all"}) == DECLINED and answers[-1] == "Clear all 1 item from your todo list?"
    rt.ctx.confirm = lambda prompt: True
    assert reg.run("clear_todos", {"which": "everything"}) == "Cleared your whole list (1 item)."
    assert reg.run("list_todos", {}) == "Your todo list is empty."
    assert [e["kind"] for e in rt.bus.recent].count("todo") >= 5        # the phone syncs on these


def test_todo_api_and_phone_sync():
    client, rt = api_client()
    todos = rt.ctx.todos
    added = client.post("/api/todos", json={"text": "laundry, groceries"}).json()
    assert [t["text"] for t in added] == ["laundry", "groceries"]
    laundry = added[0]["uid"]
    assert client.post(f"/api/todos/{laundry}", json={"done": True}).json()["done"] is True
    assert [t["text"] for t in client.get("/api/today").json()["todos"]] == ["groceries", "laundry"]
    # the phone, offline: added one, unticked laundry later, and deleted groceries
    groceries = todos.find("groceries")
    later = todos.by_uid(laundry).updated + 5
    out = client.post("/api/sync", json={"todos": [
        {"uid": "ph1", "text": "pay rent", "status": "open", "updated_ms": later},
        {"uid": laundry, "text": "laundry", "status": "open", "updated_ms": later},
        {"uid": groceries.uid, "text": "groceries", "status": "deleted", "updated_ms": 1},   # deleted wins even if older
    ]}).json()
    assert todos.by_uid("ph1").text == "pay rent"
    assert todos.by_uid(laundry).status == "open"
    assert todos.by_uid(groceries.uid).status == "deleted"
    got = {t["uid"]: t["status"] for t in out["todos"]}
    assert got == {"ph1": "open", laundry: "open", groceries.uid: "deleted"}     # deleted sent so the phone drops it
    # an old tick from the phone doesn't undo a newer untick here, and deleted never comes back
    todos.set_status("ph1", "done")
    client.post("/api/sync", json={"todos": [{"uid": "ph1", "text": "pay rent", "status": "open", "updated_ms": 3}]})
    assert todos.by_uid("ph1").status == "done"
    client.post("/api/sync", json={"todos": [{"uid": groceries.uid, "text": "groceries", "status": "open",
                                              "updated_ms": 10**13}]})
    assert todos.by_uid(groceries.uid).status == "deleted"
    assert client.delete(f"/api/todos/{laundry}").json() == {"ok": True}
    assert client.post("/api/todos/clear/done").json() == {"cleared": 1}
    assert client.get("/api/todos").json() == []
    assert client.post("/api/todos", json={"text": " "}).status_code == 400


def test_clear_todo_requests_skip_the_model():
    from sanae.todos import todo_route

    assert todo_route("what's on my to do list?") == ("list_todos", {})
    assert todo_route("what do I still need to do?") == ("list_todos", {})
    assert todo_route("read me my shopping list") is None                 # the grocery list's (groceries.py)
    assert todo_route("what do I need to do for the lab?") is None
    assert todo_route("take eggs off my list") == ("clear_todos", {"which": "eggs"})
    assert todo_route("remove the milk from my shopping list") is None
    assert todo_route("clear the done ones from my list") == ("clear_todos", {"which": "done"})
    assert todo_route("clear my whole list") == ("clear_todos", {"which": "all"})
    assert todo_route("take it off the list") is None
    assert todo_route("add milk to my list") is None
