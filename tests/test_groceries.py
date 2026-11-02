import datetime as dt
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sanae import us_api
from sanae.groceries import Groceries, key, section_for, split_items
from sanae.memory import MemoryStore
from sanae.tools import us as us_tools
from sanae.tools.registry import ToolRegistry
from tests.test_journal import Clock, Embed

SAT = dt.datetime(2026, 10, 31, 14, 0)


def make(at=SAT, cooking=None):
    clock = Clock(at)
    return Groceries(MemoryStore(":memory:", Embed()), clock=clock, idle=lambda: 10, cooking=cooking), clock


def tools(g):
    reg = ToolRegistry(context=SimpleNamespace(groceries=g))
    us_tools.register(reg)
    return lambda name, **args: reg.tools[name].func(**args)


def test_items_quantities_and_aisles():
    assert split_items("2 cans of tomatoes, milk and a dozen eggs") == [("tomatoes", "2 cans"), ("milk", ""), ("eggs", "12")]
    assert split_items("mac and cheese and some bananas") == [("mac and cheese", ""), ("bananas", "")]
    assert key("Bananas") == key("the banana") == "banana" and key("tomatoes") == "tomato"
    assert section_for("bananas") == "Produce" and section_for("oat milk") == "Dairy & eggs"
    assert section_for("pasta sauce") == "Pantry" and section_for("peanut butter") == "Pantry"
    assert section_for("ice cream") == "Frozen" and section_for("garlic bread") == "Bakery"
    assert section_for("chicken breast") == "Meat & fish" and section_for("toilet paper") == "Household"
    assert section_for("birthday candles") == "Other"


def test_list_dedupes_and_reads_by_aisle():
    g, _ = make()
    g.add("milk, bananas and pasta")
    g.add("2 milk")                                        # already there: the quantity changes, no second row
    assert [(r["item"], r["qty"]) for r in g.items()] == [("bananas", ""), ("milk", "2"), ("pasta", "")]
    assert g.spoken(by_section=True) == "produce: bananas; dairy & eggs: 2 milk; pantry: pasta."
    milk = g.find("the milk")
    g.check(milk["id"])
    assert [r["item"] for r in g.items(open_only=True)] == ["bananas", "pasta"]
    assert g.clear("done") == 1 and len(g.items()) == 2


def test_ideas_from_habits_pairs_recipes_and_staples():
    cooking = SimpleNamespace(session=lambda: {"title": "fried rice", "ingredients": ["2 eggs", "1 cup rice", "soy sauce"]})
    g, clock = make(cooking=cooking)
    ideas = g.suggestions(10)
    assert [i["item"] for i in ideas][:3] == ["eggs", "rice", "soy sauce"]       # the recipe being cooked
    assert any(i["why"] == "a staple" for i in ideas)                          # little history yet
    g2, clock2 = make(at=dt.datetime(2026, 10, 1, 12, 0))
    for day in (1, 8, 15):                               # coffee every week
        clock2.to(dt.datetime(2026, 10, day, 12, 0))
        r = g2.add("coffee")[0]
        g2.check(r["id"])
        g2.clear("done")
    clock2.to(dt.datetime(2026, 10, 21, 12, 0))
    g2.add("pasta")
    ideas = g2.suggestions(6)
    assert ideas[0] == {"item": "coffee", "why": "you usually get it every 7 days"}
    assert {"item": "pasta sauce", "why": "goes with the pasta"} in ideas
    assert "pasta" not in [i["item"] for i in ideas]                           # already on the list


def test_she_asks_and_they_answer():
    g, clock = make()
    g.add("pasta")
    run = tools(g)
    said = run("grocery_shopping")
    assert said.startswith("Here's the list by aisle: pantry: pasta.") and "Do you need pasta sauce, parmesan" in said
    assert g.shopping() and g.offered()[:2] == ["pasta sauce", "parmesan"]
    assert g.route("yes, just the parmesan") == ("grocery_answer", {"text": "yes, just the parmesan"})
    assert run("grocery_answer", text="yes, just the parmesan") == "Added parmesan."
    assert "pasta sauce" not in [i["item"] for i in g.suggestions(10)]         # not wanted: stays away a while
    assert g.route("got the pasta") == ("check_groceries", {"items": "pasta"})
    assert run("check_groceries", items="pasta") == "Ticked off pasta. 1 to go."
    assert g.route("done shopping") == ("done_shopping", {})
    assert run("done_shopping") == "Nice! Cleared 1 thing you got. Still on the list: parmesan."
    g.offer(["milk", "eggs"])
    assert g.route("no") is None                                               # her last reply wasn't the question
    assert g.route("nah I'm good", "Do you need milk or eggs?") == ("grocery_answer", {"text": "nah I'm good"})
    assert run("grocery_answer", text="nah I'm good") == "Okay, none of those then."
    assert run("add_groceries", items="__recipe__").startswith("We're not cooking")


def test_routes_and_the_todo_list_lets_go():
    g, _ = make()
    assert g.route("add milk and eggs to my grocery list") == ("add_groceries", {"items": "milk and eggs"})
    assert g.route("we're out of coffee") == ("add_groceries", {"items": "coffee"})
    assert g.route("shopping list: bread, butter") == ("add_groceries", {"items": "bread, butter"})
    assert g.route("what's on my grocery list?") == ("grocery_list", {})
    assert g.route("take the milk off the shopping list") == ("remove_groceries", {"items": "the milk"})
    assert g.route("I'm going to Costco") == ("grocery_shopping", {})
    assert g.route("heading to the grocery store") == ("grocery_shopping", {})
    assert g.route("what else do I need from the store?") == ("grocery_ideas", {})
    assert g.route("add the ingredients to my grocery list") == ("add_groceries", {"items": "__recipe__"})
    assert g.route("got the milk") is None                                  # not shopping right now
    assert g.route("I'm out of ideas for my essay") is None and g.route("we're running out of time") is None
    assert g.route("we're almost out of toilet paper") == ("add_groceries", {"items": "toilet paper"})
    from sanae.agent import direct_route

    todo = {"list_todos": 1, "add_todo": 1, "check_todo": 1, "clear_todos": 1}
    for said in ("what's on my grocery list?", "take the milk off the shopping list", "clear the grocery list"):
        assert direct_route(said, todo) is None, said                         # these belong to the grocery list
    assert direct_route("what's on my list?", todo) == ("list_todos", {})


def test_weekend_ask_when_running_low():
    g, clock = make(at=dt.datetime(2026, 10, 3, 12, 0))
    for item in ("milk", "eggs"):
        for day in (3, 10):
            clock.to(dt.datetime(2026, 10, day, 12, 0))
            g.check(g.add(item)[0]["id"])
            g.clear("done")
    clock.to(dt.datetime(2026, 10, 16, 12, 0))                  # a Friday: not yet
    assert g.moments(clock()) == []
    clock.to(dt.datetime(2026, 10, 17, 13, 0))                  # Saturday afternoon
    m = g.moments(clock())
    assert m and "milk, eggs" in m[0].situation
    g.used(m[0], clock())
    assert g.offered() == ["milk", "eggs"] and g.moments(clock()) == []      # once a week


def test_api_for_the_phone():
    g, _ = make()
    rt = SimpleNamespace(ctx=SimpleNamespace(groceries=g), bus=SimpleNamespace(publish=lambda *a: None))
    app = FastAPI()
    us_api.register(app, rt)
    client = TestClient(app)
    s = client.post("/api/groceries", json={"text": "bread and milk"}).json()
    assert [i["item"] for i in s["items"]] == ["bread", "milk"] and s["ideas"]
    bread = s["items"][0]["id"]
    assert client.post(f"/api/groceries/{bread}", json={"done": True}).json()["items"][-1]["done"]
    assert client.post("/api/groceries/skip", json={"text": "butter"}).status_code == 200
    assert "butter" not in [i["item"] for i in g.suggestions(10)]
    assert [i["item"] for i in client.post("/api/groceries/clear", json={"which": "done"}).json()["items"]] == ["milk"]
    assert client.delete("/api/groceries/999").status_code == 404
    assert "groceries" in client.get("/api/us").json()


def test_going_off_nudge():
    from sanae.recipes import RecipeBox

    box = RecipeBox.__new__(RecipeBox)
    box.all = lambda: [{"title": "Banana pancakes", "ingredients": ["2 ripe bananas", "1 cup flour"]}]
    g, clock = make(dt.datetime(2026, 10, 24, 12, 0), cooking=SimpleNamespace(box=box, session=lambda: None))
    for item in ["bananas", "milk", "frozen spinach", "rice", "chicken breast"]:
        g.add(item)
    for r in g.items():
        g.check(r["id"])
    assert g.shelf_life("chicken breast") == 2 and g.shelf_life("frozen spinach") == 0 and g.shelf_life("milk chocolate") == 0
    clock.to(dt.datetime(2026, 10, 28, 18, 0))           # 4 days on: bananas (5) and chicken (2, past) count, milk (7) not yet
    assert [x["item"] for x in g.going_off()] == ["chicken breast", "bananas"]
    m = g.moments(clock())[0]
    assert m.key == "off:2026-10-28" and "bananas (bought on Saturday" in m.situation and "Banana pancakes" in m.situation
    g.used(m, clock())
    assert g.moments(clock()) == []                       # once a day, and not the same ones again
    assert g.route("I finished the bananas") == ("groceries_used", {"items": "bananas"})
    assert g.route("the milk is still fine") == ("groceries_used", {"items": "milk"})
    assert g.route("I finished the essay") is None
    assert g.used_up("chicken breast") == ["chicken breast"]
    assert [x["item"] for x in g.going_off()] == ["bananas"]
    clock.to(dt.datetime(2026, 10, 30, 18, 0))
    assert [x["item"] for x in g.status()["going_off"]] == ["bananas", "milk"]      # the phone shows them until used
