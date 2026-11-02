"""The week's dinners (meals.py): from the recipe box + new ideas, what's missing goes on the grocery list."""
import datetime as dt
import json
from types import SimpleNamespace

from sanae.cooking import Cooking
from sanae.groceries import Groceries
from sanae.meals import Meals
from sanae.memory import MemoryStore
from tests.test_cooking import RECIPE
from tests.test_journal import Clock, Embed

IDEAS = {"meals": [{"title": "Pesto pasta", "ingredients": ["200 g pasta", "3 tbsp pesto", "parmesan, grated", "salt"]},
                   {"title": "Chicken tacos", "ingredients": ["2 chicken thighs", "4 tortillas", "1 lime", "olive oil"]},
                   {"title": "Egg fried rice", "ingredients": ["rice"]}]}


def make(at=dt.datetime(2026, 10, 26, 12, 0)):
    store = MemoryStore(":memory:", Embed())
    clock = Clock(at)
    prompts = []

    def chat(model, messages, **kw):
        prompts.append(messages[0]["content"])
        return SimpleNamespace(content=json.dumps(IDEAS if "weeknight dinners" in messages[0]["content"] else RECIPE))

    llm = SimpleNamespace(chat=chat)
    cooking = Cooking(store, clock=clock, llm=llm, model="m", idle=lambda: 10)
    groceries = Groceries(store, clock=clock, idle=lambda: 10, cooking=cooking)
    meals = Meals(store, clock=clock, llm=llm, model="m", cooking=cooking, groceries=groceries, idle=lambda: 10)
    return meals, cooking, groceries, clock, prompts


def test_plan_from_the_box_and_new_ideas():
    m, cooking, groceries, clock, prompts = make()
    cooking.start("egg fried rice")
    for _ in range(5):
        cooking.step("next")
    groceries.add("rice")
    assert m.route("can you plan dinners this week?") == ("plan_meals", {"count": 5})
    assert m.route("plan 3 meals") == ("plan_meals", {"count": 3})
    rows = m.plan(3)
    assert [r["title"] for r in rows] == ["Egg fried rice", "Pesto pasta", "Chicken tacos"]
    assert rows[0]["recipe_id"] and rows[0]["day"] == "2026-10-26"
    assert "Not these (already planned): Egg fried rice" in prompts[-1]
    assert m.spoken() == "tonight: Egg fried rice; tomorrow: Pesto pasta; Wednesday: Chicken tacos."
    # missing: basics, what's on the list and the planned-but-cooked are left out
    missing = m.missing()
    assert "rice" not in missing and "salt" not in missing and "olive oil" not in missing
    assert {"pasta", "pesto", "parmesan", "chicken thighs", "tortillas", "lime"} <= set(missing)
    assert m.route("yes please", "You'd still need pasta. Want me to put those on the grocery list?") == ("meal_plan_groceries", {})
    added = m.to_groceries()
    assert set(added) == set(missing) and m.missing() == []
    assert groceries.find("pesto")["who"] == "plan"
    # tonight
    assert m.route("what's for dinner tonight?") == ("meal_plan", {"day": "tonight"})
    assert m.route("swap thursday") is None                       # nothing planned then
    assert m.route("swap tomorrow") == ("swap_meal", {"day": "tomorrow"})
    clock.to(dt.datetime(2026, 10, 26, 18, 0))
    assert "Egg fried rice for dinner tonight" in m.moments(clock())[0].situation
    # it got cooked: ticked, no more asking
    cooking.start("that")
    for _ in range(5):
        cooking.step("next")
    m.observe(clock())
    assert m.week()[0]["cooked"] == 1 and m.moments(clock()) == []
    assert m.status()["days"][0]["label"] == "tonight"


def test_plan_after_8pm_starts_tomorrow_and_no_box():
    m, _, _, _, _ = make(dt.datetime(2026, 10, 26, 21, 0))
    rows = m.plan(2)
    assert [r["day"] for r in rows] == ["2026-10-27", "2026-10-28"]
    assert m.route("what's for dinner?") is None                  # nothing tonight


def test_shopping_names_and_day_ask():
    from sanae.briefing import DAY_ASK
    from sanae.meals import shopping_name

    assert [shopping_name(x) for x in ("1/4 cup Parmesan", "Salt and pepper to taste", "1/2 tsp paprika", "2 cloves garlic, minced",
                                       "1 can (400 g) chopped tomatoes", "1 1/2 cups cooked rice", "olive oil")] == \
        ["parmesan", "", "", "garlic", "tomatoes", "rice", ""]
    assert DAY_ASK.search("what's today's photo challenge?") is None and DAY_ASK.search("what's on today?")
