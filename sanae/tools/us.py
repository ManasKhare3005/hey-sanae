"""Things you two do together beyond the daily list: weekend plans (weekend.py), and more as they're
added. Most requests reach these through the parts' own routes (part.Part.route), since the small
model was unreliable at picking them in chat."""
from __future__ import annotations

from .registry import ToolRegistry


def register(reg: ToolRegistry):
    ctx = reg.context

    # ----- cooking together (cooking.py) -----
    def cooking():
        return getattr(ctx, "cooking", None)

    @reg.tool("Cook something together: write the recipe and walk the user through it step by step ('let's cook "
              "fried rice', 'walk me through making pancakes').",
              params={"dish": {"type": "string", "description": "What to cook, e.g. 'egg fried rice'"}},
              required=["dish"], direct=True)
    def start_cooking(dish: str):
        c = cooking()
        if c is None:
            return "Cooking together is turned off."
        s = c.start(dish)
        if s is None:
            if c.saved(dish) is None and dish.strip().lower() in ("that", "it", "this", "that one", "the same"):
                return "Our recipe box is still empty, so I'm not sure which one you mean. What should we make?"
            return "Hmm, I couldn't put a recipe together for that. Want to try something else?"
        again = " Same way as last time, from our recipe box." if s.get("again") else ""
        return (f"Okay, {s['title']}!{again} You'll need: " + "; ".join(s["ingredients"]) +
                f". It's {len(s['steps'])} steps. Say \"next\" when you're ready for step one.")

    @reg.tool("From a photo of a restaurant dish: work out what it is and write a home version into the recipe box "
              "('can we make this at home?').", params={"said": {"type": "string", "description": "What the user said"}},
              direct=True)
    def recreate_dish(said: str = ""):
        c = cooking()
        if c is None:
            return "Cooking together is turned off."
        r = c.recreate(said)
        if r is None:
            return "Hmm, I couldn't work out a home version of that one. What's the dish called?"
        return (f"Ooh, I think I've got it: {r['title']}! It's in our recipe box now. You'll need: "
                + "; ".join(r["ingredients"][:8]) + (" and a few more things" if len(r["ingredients"]) > 8 else "")
                + f". {len(r['steps'])} steps. Want to cook it together?")

    @reg.tool("What's in your shared recipe box (dishes you cooked together, with stars).", params={}, direct=True)
    def list_recipes():
        c = cooking()
        return c.box.spoken() if c is not None else "Cooking together is turned off."

    @reg.tool("Give a dish in the recipe box 1 to 5 stars ('give the fried rice 5 stars').",
              params={"which": {"type": "string"}, "stars": {"type": "integer"}}, required=["which", "stars"], direct=True)
    def rate_recipe(which: str, stars: int):
        c = cooking()
        r = c.box.find(which) if c is not None else None
        if r is None:
            return f"I can't find {which} in our recipe box."
        c.box.rate(r["id"], stars)
        return f"{r['title']}: {max(1, min(5, int(stars)))} stars in our recipe box."

    @reg.tool("Take a dish out of the recipe box.", params={"which": {"type": "string"}}, required=["which"],
              direct=True, risky=True, confirm="Take {which} out of our recipe box?")
    def remove_recipe(which: str):
        c = cooking()
        r = c.box.find(which) if c is not None else None
        if r is None:
            return f"I can't find {which} in our recipe box."
        c.box.remove(r["id"])
        return f"Took {r['title']} out of our recipe box."

    @reg.tool("The cooking walkthrough: the next step, go back, repeat, or the ingredients.",
              params={"action": {"type": "string", "enum": ["next", "back", "repeat", "ingredients"]}},
              required=["action"], direct=True)
    def cooking_step(action: str = "next"):
        c = cooking()
        return c.step(action) if c is not None else "Cooking together is turned off."

    @reg.tool("How much of an ingredient the recipe you're cooking needs ('how much soy sauce?').",
              params={"what": {"type": "string"}}, required=["what"], direct=True)
    def cooking_how_much(what: str):
        c = cooking()
        return c.how_much(what) if c is not None else "Cooking together is turned off."

    @reg.tool("Set a kitchen timer while cooking (0 minutes = as long as the current step).",
              params={"minutes": {"type": "integer"}}, direct=True)
    def cooking_timer(minutes: int = 0):
        c = cooking()
        return c.timer(minutes or None) if c is not None else "Cooking together is turned off."

    @reg.tool("How long is left on the kitchen timer.", params={}, direct=True)
    def cooking_timer_left():
        c = cooking()
        return c.time_left() if c is not None else "There's no timer running."

    @reg.tool("Stop the cooking walkthrough ('stop cooking', 'we're done cooking').", params={}, direct=True)
    def stop_cooking():
        c = cooking()
        s = c.stop() if c is not None else None
        return "Okay, I've put the recipe away." if s else "We weren't cooking anything."

    # ----- photo a day (dailyphoto.py) -----
    @reg.tool("Today's photo-a-day challenge: show it, skip today, or get a different one.",
              params={"action": {"type": "string", "enum": ["show", "skip", "reroll"]}}, direct=True)
    def daily_photo(action: str = "show"):
        d = getattr(ctx, "dailyphoto", None)
        if d is None:
            return "Photo a day is turned off."
        if action == "skip":
            kept = d.skip()
            return "Okay, no photo today." + (" Your streak's safe, that's your free skip this week." if kept else
                                              " That one ends the streak though, start a new one tomorrow!")
        if action == "reroll":
            new = d.reroll()
            return f"Okay, new one: {new}." if new else "You only get one swap a day! " + d.spoken()
        return d.spoken()

    # ----- what makes your good days (gooddays.py) -----
    @reg.tool("What makes the user's good days: patterns between how their days felt and what they did (steps, "
              "sleep, the photo challenge, cooking, late nights), from real counts.", params={}, direct=True)
    def good_days():
        g = getattr(ctx, "gooddays", None)
        return g.spoken() if g is not None else "Good-day patterns are turned off."

    @reg.tool("The user's month, wrapped: last month's recap (talk days, moods, songs, movies, photos), on the phone.",
              params={}, direct=True)
    def month_wrapped():
        w = getattr(ctx, "wrapped", None)
        return w.spoken() if w is not None else "The monthly recap is turned off."

    # ----- movie night (watching.py) -----
    def watching():
        return getattr(ctx, "watching", None)

    @reg.tool("Pick something to watch tonight ('movie night', 'what should we watch?'): from the watchlist and shows "
              "in progress, by the time left before bed and the day's mood.", params={}, direct=True)
    def what_to_watch():
        w = watching()
        return w.pick_words() if w is not None else "Watching together is turned off."

    @reg.tool("Add a movie or show to your shared watchlist.", params={"title": {"type": "string"}}, required=["title"],
              direct=True)
    def add_to_watchlist(title: str):
        w = watching()
        if w is None:
            return "Watching together is turned off."
        item = w.add_watch(title)
        return f"Added {item['title']} to our watchlist." + (" Movie night soon?" if item["kind"] == "movie" else "")

    @reg.tool("Take a movie or show off the watchlist.", params={"title": {"type": "string"}}, required=["title"], direct=True)
    def drop_from_watchlist(title: str):
        w = watching()
        item = w.drop_watch(title) if w is not None else None
        return f"Took {item['title']} off our watchlist." if item else f"{title} isn't on our watchlist."

    @reg.tool("Rate a movie 1 to 5 stars in your shared movie log ('rate Dune 4 stars'); 0 stars just logs it as watched.",
              params={"title": {"type": "string"}, "stars": {"type": "integer"}}, required=["title"], direct=True)
    def rate_movie(title: str, stars: int = 0):
        w = watching()
        if w is None:
            return "Watching together is turned off."
        r = w.rate_movie(title, stars) if stars else w.log_movie(title, how="you")
        return (f"{r['title']}: {r['stars']} star{'s' if r['stars'] != 1 else ''}, in our movie log." if r["stars"] else
                f"Logged {r['title']} in our movie log. How many stars?")

    @reg.tool("Your shared movie log: every movie watched, with stars.", params={}, direct=True)
    def movie_log():
        w = watching()
        return w.log_words() if w is not None else "Watching together is turned off."

    @reg.tool("What's on your shared watchlist.", params={}, direct=True)
    def watchlist():
        w = watching()
        return w.watchlist_words() if w is not None else "Watching together is turned off."

    # ----- our playlist (playlist.py) -----
    def playlist():
        return getattr(ctx, "playlist", None)

    @reg.tool("What's on your shared playlist with the user.", params={}, direct=True)
    def our_playlist():
        p = playlist()
        return p.spoken() if p is not None else "Our playlist is turned off."

    @reg.tool("Add the song playing right now to your shared playlist ('add this song to our playlist').",
              params={}, direct=True)
    def add_to_playlist():
        p = playlist()
        if p is None:
            return "Our playlist is turned off."
        r = p.add_now()
        if r is None:
            return "I can't tell what's playing right now. Play it and ask me again?"
        p.told(r["id"])
        return f"Added {r['title']}" + (f" by {r['artist']}" if r["artist"] else "") + " to our playlist!"

    @reg.tool("This week's song of the week from your shared playlist, and why she picked it.", params={}, direct=True)
    def song_of_the_week():
        p = playlist()
        return p.week_words() if p is not None else "Our playlist is turned off."

    @reg.tool("Play your shared playlist (opens it on YouTube).", params={}, direct=True)
    def play_playlist():
        from ..events import current_origin

        p = playlist()
        if p is None:
            return "Our playlist is turned off."
        url = p.play_url()
        if url is None:
            return "Our playlist is empty so far."
        bus = getattr(ctx, "bus", None)
        if current_origin() == "phone" and bus is not None:
            bus.publish("phone_open", {"url": url, "title": "Our playlist"})
        else:
            import webbrowser

            webbrowser.open(url)
        return f"Here's our playlist ({len(p.items())} songs)!"

    @reg.tool("Take a song off your shared playlist.", params={"which": {"type": "string"}}, required=["which"], direct=True)
    def remove_from_playlist(which: str):
        p = playlist()
        r = p.search(which) if p is not None else None
        if r is None:
            return f"{which} isn't on our playlist."
        p.remove(r["id"])
        return f"Took {r['title']} off our playlist."

    # ----- the week's dinners (meals.py) -----
    def meals():
        return getattr(ctx, "meals", None)

    def missing_line(m) -> str:
        miss = m.missing()
        if not miss:
            m.put("offered", 0)
            return " Looks like you've got what you need."
        shown = ", ".join(miss[:6]) + (f" and {len(miss) - 6} more" if len(miss) > 6 else "")
        return f" You'd still need {shown}. Want me to put those on the grocery list?"

    @reg.tool("Plan dinners for the coming days ('plan dinners this week', 'plan 3 meals'): from your recipe box plus a "
              "few new ideas, then offer to add what's missing to the grocery list.",
              params={"count": {"type": "integer", "description": "How many dinners (default 5)"}}, direct=True)
    def plan_meals(count: int = 5):
        m = meals()
        if m is None:
            return "Meal planning is turned off."
        rows = m.plan(count)
        if not rows:
            return "I couldn't put a plan together right now. Want to try again in a bit?"
        boxed = sum(1 for r in rows if r["recipe_id"])
        from_box = f" ({boxed} from our recipe box)" if boxed else ""
        return f"Here's the plan{from_box}: {m.spoken(rows)}" + missing_line(m)

    @reg.tool("The meal plan for the week, or tonight's dinner.", params={"day": {"type": "string", "enum": ["week", "tonight"]}},
              direct=True)
    def meal_plan(day: str = "week"):
        m = meals()
        if m is None:
            return "Meal planning is turned off."
        if day == "tonight":
            r = m.on(m.now().date())
            if r is None:
                return "Nothing's planned for tonight."
            return f"Tonight it's {r['title']}" + (", and you already made it!" if r["cooked"] else ". Want to cook it together?")
        return m.spoken()

    @reg.tool("Swap one planned dinner for something else ('swap Thursday').",
              params={"day": {"type": "string", "description": "tonight, tomorrow or a weekday"}}, required=["day"], direct=True)
    def swap_meal(day: str):
        m = meals()
        if m is None:
            return "Meal planning is turned off."
        r = m.swap(m._day(day))
        return f"Okay, {m.day_name(r['day'])} is {r['title']} now." if r else f"There's nothing planned for {day}."

    @reg.tool("Put what the meal plan still needs on the grocery list.", params={}, direct=True)
    def meal_plan_groceries():
        m = meals()
        if m is None:
            return "Meal planning is turned off."
        added = m.to_groceries()
        if not added:
            return "You've already got everything for the plan."
        return f"Added {len(added)} thing{'s' if len(added) != 1 else ''} to the grocery list: {', '.join(added)}."

    # ----- learning Japanese together (japanese.py) -----
    def jp():
        return getattr(ctx, "japanese", None)

    @reg.tool("A Japanese lesson or quiz with you: 'teach me some Japanese' (new words, then a quiz) or 'quiz me on "
              "Japanese' (words that are due).",
              params={"kind": {"type": "string", "enum": ["lesson", "quiz"]}}, direct=True)
    def japanese_lesson(kind: str = "lesson"):
        j = jp()
        return j.lesson(kind) if j is not None else "Japanese practice is turned off."

    @reg.tool("The user's answer in your Japanese quiz.", params={"answer": {"type": "string"}}, required=["answer"],
              direct=True)
    def japanese_answer(answer: str):
        j = jp()
        return j.answer(answer) if j is not None else "Japanese practice is turned off."

    @reg.tool("The user quizzes you on a Japanese word ('what does sora mean?').", params={"question": {"type": "string"}},
              required=["question"], direct=True)
    def japanese_her_turn(question: str):
        j = jp()
        return j.her_answer(question) if j is not None else "Japanese practice is turned off."

    @reg.tool("The user corrected your Japanese.", params={}, direct=True)
    def japanese_corrected():
        j = jp()
        return j.corrected() if j is not None else "Oh, thanks!"

    @reg.tool("Stop the Japanese practice.", params={}, direct=True)
    def japanese_stop():
        j = jp()
        return j.stop() if j is not None else "Okay."

    # ----- the shared bucket list (bucket.py) -----
    def bucket():
        return getattr(ctx, "bucket", None)

    @reg.tool("What's on your shared bucket list ('what's on our bucket list?').", params={}, direct=True)
    def bucket_list():
        b = bucket()
        return b.spoken() if b is not None else "The bucket list is turned off."

    @reg.tool("Add something to your shared bucket list ('add skydiving to our bucket list').",
              params={"what": {"type": "string"}}, required=["what"], direct=True)
    def add_to_bucket_list(what: str):
        b = bucket()
        if b is None:
            return "The bucket list is turned off."
        try:
            item = b.add(what)
        except ValueError as exc:
            return str(exc).capitalize()
        return f"On the list: {item['text']}. Someday soon!"

    @reg.tool("Take something off your shared bucket list.", params={"what": {"type": "string"}}, required=["what"],
              direct=True)
    def drop_from_bucket_list(what: str):
        b = bucket()
        found = b.find(what, open_only=False) if b is not None else None
        if found is None:
            return "I couldn't find that on our bucket list."
        b.remove(found["id"])
        return f"Okay, {found['text']} is off the list."

    # ----- the scrapbook (scrapbook.py) -----
    @reg.tool("Keep the photo the user just sent in your shared scrapbook, when they say so ('keep that one', "
              "'put it in our scrapbook').", params={}, direct=True)
    def keep_photo():
        s = getattr(ctx, "scrapbook", None)
        if s is None:
            return "The scrapbook is turned off."
        kept = s.keep()
        if kept is None:
            return "I don't have that photo anymore; I only hold onto them for a few minutes. Send it again?"
        extra = " I drew a little something next to it." if kept["drawing"] else ""
        return f"It's in our scrapbook: \"{kept['caption']}\".{extra}"

    # ----- the bedtime story serial (stories.py) -----
    @reg.tool("Tell the next chapter of your bedtime story serial ('tell me a story', 'bedtime story'); again=true "
              "repeats last night's chapter.", params={"again": {"type": "boolean"}}, direct=True)
    def bedtime_story(again: bool = False):
        s = getattr(ctx, "stories", None)
        return s.tell(bool(again)) if s is not None else "Story time is turned off."

    # ----- watching together (watching.py) -----
    @reg.tool("What the user has been watching lately on the laptop (shows with the episode they're on, movies): "
              "'what have I been watching?', 'where was I in that show?'.", params={}, direct=True)
    def watch_history():
        w = getattr(ctx, "watching", None)
        return w.spoken() if w is not None else "I don't keep track of what you watch (it's turned off)."

    # ----- weekend plans (weekend.py) -----
    def weekend():
        return getattr(ctx, "weekend", None)

    @reg.tool("The user's plans for this weekend that you made together: 'what are my weekend plans?', "
              "'what am I doing this weekend?'.", params={}, direct=True)
    def weekend_plans():
        w = weekend()
        return w.spoken() if w is not None else "Weekend plans are turned off."

    @reg.tool("Start planning the weekend together with the user ('let's plan the weekend', 'help me plan my weekend').",
              params={}, direct=True)
    def plan_weekend():
        w = weekend()
        if w is None:
            return "Weekend plans are turned off."
        w.start_planning()
        plans = w.plans()
        if plans:
            return ("Okay, let's plan! So far: " + "; ".join(f"{p['text']} ({w.when_words(p)})" for p in plans)
                    + ". What else do you want to do?")
        return "Ooh, okay, let's plan it! What do you want to do on Saturday?"

    @reg.tool("Add something to the user's weekend plans ('add hiking on saturday morning to my weekend plans').",
              params={"plan": {"type": "string", "description": "What, in a few words, e.g. 'go hiking'"},
                      "day": {"type": "string", "description": "'sat', 'sun' or '' for either"},
                      "time": {"type": "string", "description": "Optional time, 24h HH:MM"}},
              required=["plan"], direct=True)
    def add_weekend_plan(plan: str, day: str = "", time: str = ""):
        w = weekend()
        if w is None:
            return "Weekend plans are turned off."
        try:
            p = w.add(plan, day, time)
        except ValueError:
            return "What should I put on the weekend plans?"
        w.start_planning()
        return f"Added to our weekend: {p['text']}, {w.when_words(p)}."

    @reg.tool("Take something off the user's weekend plans ('cancel the hike from my weekend plans').",
              params={"plan": {"type": "string", "description": "Which plan, in their words"}},
              required=["plan"], direct=True)
    def drop_weekend_plan(plan: str):
        w = weekend()
        found = w.find(plan) if w is not None else None
        if found is None:
            return "I couldn't find that in our weekend plans."
        w.remove(found["id"])
        return f"Okay, {found['text']} is off the weekend plans."

    # ----- the grocery list (groceries.py) -----
    def groceries():
        return getattr(ctx, "groceries", None)

    def names(rows) -> str:
        labels = [f"{r['qty']} {r['item']}" if r["qty"] else r["item"] for r in rows]
        return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + f" and {labels[-1]}"

    def ask_more(g, ideas=None) -> str:
        ideas = g.suggestions(4) if ideas is None else ideas
        if not ideas:
            return ""
        g.offer([i["item"] for i in ideas[:4]])
        return " " + g.ask_line(ideas)

    @reg.tool("What's on the grocery / shopping list ('what's on my grocery list?').", params={}, direct=True)
    def grocery_list():
        g = groceries()
        return g.spoken(by_section=g.shopping()) if g is not None else "The grocery list is turned off."

    @reg.tool("Add food or household things to the grocery / shopping list ('add milk and eggs to the grocery "
              "list', 'we're out of coffee').",
              params={"items": {"type": "string", "description": "The items, comma separated, e.g. '2 milk, eggs, bread'"}},
              required=["items"], direct=True)
    def add_groceries(items: str):
        g = groceries()
        if g is None:
            return "The grocery list is turned off."
        if items == "__recipe__":
            s = g.cooking.session() if g.cooking is not None else None
            if not s:
                return "We're not cooking anything right now. Tell me the dish and I'll write the recipe first!"
            items = ", ".join(s["ingredients"])
        try:
            added = g.add(items)
        except ValueError:
            return "What should I put on the grocery list?"
        return f"Added {names(added)} to the grocery list."

    @reg.tool("Take things off the grocery list (not bought, just not needed).",
              params={"items": {"type": "string"}}, required=["items"], direct=True)
    def remove_groceries(items: str):
        from ..groceries import split_items

        g = groceries()
        if g is None:
            return "The grocery list is turned off."
        gone = [r for r in (g.find(i, open_only=False) for i, _ in split_items(items)) if r]
        for r in gone:
            g.remove(r["id"])
        return f"Took {names(gone)} off the list." if gone else "I couldn't find that on the grocery list."

    @reg.tool("Tick things off the grocery list while shopping ('got the milk').",
              params={"items": {"type": "string"}}, required=["items"], direct=True)
    def check_groceries(items: str):
        from ..groceries import split_items

        g = groceries()
        if g is None:
            return "The grocery list is turned off."
        got = [r for r in (g.find(i) for i, _ in split_items(items)) if r]
        for r in got:
            g.check(r["id"])
        if not got:
            return "Hmm, that's not on the list."
        left = g.items(open_only=True)
        return f"Ticked off {names(got)}. " + (f"{len(left)} to go." if left else "That's everything!")

    @reg.tool("Clear the grocery list: which='done' (ticked items) or 'all'.",
              params={"which": {"type": "string", "enum": ["done", "all"]}}, direct=True)
    def clear_groceries(which: str = "done"):
        g = groceries()
        if g is None:
            return "The grocery list is turned off."
        n = g.clear("all" if which == "all" else "done")
        return "The grocery list is empty now." if which == "all" else f"Cleared {n} ticked item{'s' if n != 1 else ''}."

    @reg.tool("The user is going grocery shopping ('I'm going to the store'): read the list aisle by aisle and ask "
              "about things they might need.", params={}, direct=True)
    def grocery_shopping():
        g = groceries()
        if g is None:
            return "The grocery list is turned off."
        g.put("shopping", g.clock())
        have = g.items(open_only=True)
        start = (f"Here's the list by aisle: {g.spoken(by_section=True)}" if have else
                 "The list's empty so far.")
        more = ask_more(g)
        return start + (more or " Tick things off on your phone, or tell me what you got.")

    @reg.tool("Ideas for the grocery list: things the user usually buys and is probably out of, things that go with "
              "what's on the list ('what else do I need?').", params={}, direct=True)
    def grocery_ideas():
        g = groceries()
        if g is None:
            return "The grocery list is turned off."
        ideas = g.suggestions(4)
        if not ideas:
            return "I can't think of anything missing. Looks complete!"
        why = "; ".join(f"{i['item']} ({i['why']})" for i in ideas[:4])
        g.offer([i["item"] for i in ideas[:4]])
        return f"Maybe: {why}. Want any of those on the list?"

    @reg.tool("The user's answer to your question about extra groceries ('yes, the eggs', 'no').",
              params={"text": {"type": "string"}}, required=["text"], direct=True)
    def grocery_answer(text: str):
        g = groceries()
        res = g.answer(text) if g is not None else None
        if res is None:
            return "Which ones should I add?"
        added, dropped = res
        if not added:
            return "Okay, none of those then."
        return f"Added {names(added)}."

    @reg.tool("The user finished grocery shopping: clear what they ticked off.", params={}, direct=True)
    def done_shopping():
        g = groceries()
        if g is None:
            return "The grocery list is turned off."
        n = g.clear("done")
        g.put("shopping", 0)
        left = g.items(open_only=True)
        out = f"Nice! Cleared {n} thing{'s' if n != 1 else ''} you got."
        return out + (f" Still on the list: {names(left)}." if left else "")

    @reg.tool("Fresh groceries the user finished, threw out, or says are still fine ('I finished the milk'), so you "
              "stop reminding them they're about to go off.", params={"items": {"type": "string"}}, required=["items"],
              direct=True)
    def groceries_used(items: str):
        g = groceries()
        if g is None:
            return "The grocery list is turned off."
        done = g.used_up(items)
        return f"Got it, I'll stop counting the {names([{'qty': '', 'item': d} for d in done])}." if done else "Okay!"
