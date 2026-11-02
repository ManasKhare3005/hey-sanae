import datetime as dt
import json
from types import SimpleNamespace

from sanae.cooking import Cooking
from sanae.memory import MemoryStore
from sanae.reminders import Reminders
from tests.test_journal import Clock, Embed

RECIPE = {"title": "Egg fried rice", "ingredients": ["2 cups cooked rice", "2 eggs", "1 tbsp soy sauce", "1 spring onion"],
          "steps": [{"text": "Beat the eggs in a bowl.", "minutes": 0},
                    {"text": "Scramble the eggs in a hot pan, then set them aside.", "minutes": 2},
                    {"text": "Fry the rice until it's a bit crispy.", "minutes": 5},
                    {"text": "Add the eggs, soy sauce and spring onion, and toss.", "minutes": 0}]}


def make(at=dt.datetime(2026, 10, 20, 19, 0)):
    store = MemoryStore(":memory:", Embed())
    clock = Clock(at)
    prompts, published = [], []

    def chat(model, messages, **kw):
        prompts.append((messages[0]["content"], kw.get("fmt")))
        return SimpleNamespace(content=json.dumps(RECIPE))

    seen = SimpleNamespace(description="Eggs, a container of rice, spring onions, soy sauce.", at=clock())
    c = Cooking(store, clock=clock, llm=SimpleNamespace(chat=chat), model="m", reminders=Reminders(store),
                vision=SimpleNamespace(last=seen), publish=lambda k, d: published.append((k, d)), idle=lambda: 10)
    return c, clock, prompts, published


def test_fridge_photo_then_pick_a_dish():
    c, clock, prompts, _ = make()
    assert "two or three simple dishes" in c.notes("(Sent a photo) what can I make with this?")[0]
    assert c.route("ooh let's do the fried rice") == ("start_cooking", {"dish": "fried rice"})
    s = c.start("fried rice")
    assert s["title"] == "Egg fried rice" and "spring onions" in prompts[0][0] and prompts[0][1]["type"] == "object"


def test_walkthrough_in_code():
    c, clock, _, published = make()
    c.start("egg fried rice")
    assert c.route("next") == ("cooking_step", {"action": "next"})
    assert c.step("next").startswith("Step 1 of 4: Beat the eggs")
    two = c.step("next")
    assert "about 2 minutes" in two and "timer" in two
    assert c.route("yes please", two) == ("cooking_timer", {"minutes": 0})
    assert c.timer().startswith("Timer set for 2 minutes")
    assert c.reminders.pending()[0].text.startswith("Timer's up: Scramble")
    assert any(k == "reminder" for k, _ in published)
    clock.to(dt.datetime(2026, 10, 20, 19, 1))
    assert c.time_left() == "1 minute and 0 seconds left."
    assert c.route("how much soy sauce do I need?") == ("cooking_how_much", {"what": "soy sauce"})
    assert c.how_much("soy sauce") == "You need 1 tbsp soy sauce."
    assert c.route("set a timer for 10 minutes") == ("cooking_timer", {"minutes": 10})
    assert c.route("wait, say that again") == ("cooking_step", {"action": "repeat"})
    assert c.route("go back") == ("cooking_step", {"action": "back"})
    c.step("next")
    assert "last step" in c.step("next")
    assert "is done, enjoy" in c.step("next") and c.session() is None
    clock.to(dt.datetime(2026, 10, 20, 20, 0))
    assert "turned out" in c.moments(clock())[0].situation


def test_routes_stay_out_of_the_way():
    c, clock, _, _ = make()
    assert c.route("next") is None                              # not cooking: "next" isn't hers
    assert c.route("how do I make a website") is None
    assert c.route("let's make pancakes for breakfast") == ("start_cooking", {"dish": "pancakes"})
    assert c.route("recipe for banana bread") == ("start_cooking", {"dish": "banana bread"})
    c.start("pancakes")
    assert c.route("stop cooking") == ("stop_cooking", {})
    assert c.status()["session"]["title"] == "Egg fried rice"


def test_recipe_box():
    from sanae.recipes import stars_in

    c, clock, prompts, _ = make()
    assert c.route("what have we cooked?") == ("list_recipes", {})
    assert "empty" in c.box.spoken()
    c.start("egg fried rice")
    for _ in range(5):
        c.step("next")
    box = c.box.all()
    assert [r["title"] for r in box] == ["Egg fried rice"] and box[0]["cooked"] == 1
    # "how did it turn out?" -> the answer sets the stars, once
    note = c.notes("honestly so good, a bit salty", "How did the fried rice turn out?")
    assert "5 stars" in note[0] and c.box.all()[0]["stars"] == 5
    assert c.notes("so good", "How did the fried rice turn out?") == []
    # again: the saved recipe, no new one written
    n = len(prompts)
    assert c.route("let's make that again") == ("start_cooking", {"dish": "that"})
    s = c.start("that")
    assert s["recipe_id"] == box[0]["id"] and len(prompts) == n
    assert c.route("can we make the fried rice again") == ("start_cooking", {"dish": "fried rice"})
    c.step("next")
    c.stop()                                       # only 1 of 4 steps: not counted
    assert c.box.all()[0]["cooked"] == 1
    assert c.route("give the fried rice 4 stars") == ("rate_recipe", {"which": "fried rice", "stars": 4})
    assert c.route("delete the fried rice recipe") == ("remove_recipe", {"which": "fried rice"})
    assert c.route("give the pizza 4 stars") is None              # not in the box
    assert c.status()["recipes"][0]["title"] == "Egg fried rice"
    assert c.box.find("pesto pasta") is None
    assert [stars_in(t) for t in ("kinda burnt", "it was okay", "pretty good", "3 out of 5", "not bad", "hmm")] == [2, 3, 4, 3, 4, 0]


def test_recreate_a_restaurant_dish():
    c, clock, prompts, published = make()
    c.vision.last.description = "A bowl of creamy orange curry with chicken pieces and rice, garnished with cilantro."
    said = "(Sent a photo) we had this at Curry House, can we make this at home?"
    assert c.notes(said) == [] or "fridge" not in " ".join(c.notes(said))
    assert c.route(said) == ("recreate_dish", {"said": said})
    r = c.recreate(said)
    assert "at Curry House" in prompts[-1][0] and "creamy orange curry" in prompts[-1][0]
    assert prompts[-1][1]["required"][0] == "dish"
    assert r["cooked"] == 0 and r["source"] == "from a photo at Curry House"
    assert ("us", {"what": "cooking", "action": "recreated"}) in published
    assert "not made yet, from a photo at Curry House" in c.box.spoken()
    # "yes" to cooking it: the saved recipe, not a new one
    assert c.route("yes let's do it", "It's in our recipe box now. Want to cook it together?") == \
        ("start_cooking", {"dish": "Egg fried rice"})
    n = len(prompts)
    s = c.start("Egg fried rice")
    assert s["recipe_id"] == r["id"] and len(prompts) == n
    # a few minutes later, without the photo tag
    assert c.route("how would I make that dish from the photo?")[0] == "recreate_dish"
    clock.to(dt.datetime(2026, 10, 20, 20, 0))
    assert c.route("how would I make that dish from the photo?") is None              # the photo's old now
