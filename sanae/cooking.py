"""Cook with her: "what can I make with this?" (a photo of the fridge), then she walks you through it
step by step, hands-free (a call from the phone with earbuds in works well), with real timers.

  - A photo asking what to make: she looks for the ingredients and suggests two or three simple
    dishes, then offers to walk you through one.
  - "Let's cook fried rice" / "walk me through making pancakes": the model writes the recipe once
    (structured: ingredients, short steps, minutes where a step takes time); after that every step
    is handled in code: "next", "go back", "say that again", "what do I need?", "how much soy
    sauce?", "set a timer", "how long left?", "stop cooking".
  - Timers are real reminders (they ring at the laptop and on the phone).
  - A while after you finish, she asks how it turned out.

The recipe lives in kv (cooking:session) for 3 hours; the phone's Us tab shows it while it's on.
Finished dishes go in the recipe box (recipes.py): "make that again" cooks it the same way.

Recreate a dish: a photo of a restaurant meal with "can we make this at home?" (or "recreate this",
"how would I make this") -> she works out what it is from the photo and writes her home version
into the recipe box (not cooked yet, "from a photo at <place>"), then offers to cook it with you.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import time

from .initiative import Moment
from .part import Part
from .recipes import RecipeBox, stars_in

log = logging.getLogger(__name__)
SESSION_S = 3 * 3600
OFFER_S = 30 * 60
INGREDIENTS_Q = ("List the food and ingredients you can see, as one short comma-separated list (only what you're sure "
                 "of). Then: {q}")
RECIPE_PROMPT = (
    "Write a simple home recipe for: {dish}.{have}\n"
    "Return JSON: title (short), ingredients (list of short strings with amounts, e.g. \"2 eggs\"), steps (4 to 10 "
    "steps, each one short spoken sentence under 25 words, in order; minutes = how long that step takes when it's "
    "waiting/cooking time, else 0). Keep it doable in a small kitchen."
)
RECIPE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "ingredients": {"type": "array", "items": {"type": "string"}},
        "steps": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "minutes": {"type": "integer"}}, "required": ["text", "minutes"]}},
    },
    "required": ["title", "ingredients", "steps"],
}

RECREATE_PROMPT = (
    "{user} sent a photo of a dish they had{where}. What the photo shows: {description}\n"
    "What they said: \"{said}\"\n"
    "Work out what the dish is and write a home version that tastes as close as you can, doable in a small kitchen "
    "with normal supermarket ingredients. Return JSON: dish (what it is, plainly, e.g. \"chicken tikka masala\"), "
    "title (short, e.g. \"Home-style chicken tikka masala\"), ingredients (list of short strings with amounts), "
    "steps (4 to 10 steps, each one short spoken sentence under 25 words, in order; minutes = how long that step "
    "takes when it's waiting/cooking time, else 0)."
)
RECREATE_SCHEMA = {**RECIPE_SCHEMA, "properties": {**RECIPE_SCHEMA["properties"], "dish": {"type": "string"}},
                   "required": ["dish", *RECIPE_SCHEMA["required"]]}
RECREATE = re.compile(r"\b((?:can|could|should) (?:i|we|you) (?:make|recreate|copy|cook) (?:this|that|it)|recreate (?:this|that|it)|"
                      r"(?:make|cook) (?:this|that|it) at home|home ?made version|home version|copycat|"
                      r"how (?:do|would|could|can) (?:i|we) make (?:this|that|it)|replicate (?:this|that|it)|"
                      r"recipe for (?:this|that)|teach me (?:to make )?(?:this|that))\b", re.I)
WHERE = re.compile(r"\b(?:at|from)\s+(?P<where>(?:[A-Z][\w'&.-]*)(?:\s+(?:[A-Z][\w'&.-]*|&|and|de|la|of)){0,3})")
COOK_Q = re.compile(r"\b(what (can|could|should) i (make|cook)|what to (make|cook|eat)|(dinner|lunch|breakfast|meal) "
                    r"ideas|what'?s for (dinner|lunch)|recipe|my fridge|in the fridge|these ingredients|cook with (this|these))\b", re.I)
FOODISH = re.compile(r"\b(cook|cooking|bake|baking|recipe|dinner|lunch|breakfast|brunch|meal|food|pasta|rice|noodles?|"
                     r"ramen|curry|soup|salad|eggs?|omelet+e?|pancakes?|stir[- ]?fry|sandwich|cake|cookies|chicken|"
                     r"tofu|paneer|dal|tacos?|pizza|burger|sauce|bread)\b", re.I)
START = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|alright|hey)[, ]+)?(?:let'?s|can we|could we|help me|walk me through|"
                   r"teach me (?:how )?to|show me how to|how do i|i wanna|i want to|we'?re gonna|cook with me[, ]*(?:we'?re making)?)"
                   r"\s+(?:(?:make|cook|bake|making|cooking|baking)\s+)(?P<dish>.+?)\W*$"
                   r"|^\W*(?:give me |find me )?(?:a |the )?recipe for (?P<dish2>.+?)\W*$", re.I)
PICK = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|yeah|yes|alright|o+h+|mm+|hmm+)[, ]+)*(?:let'?s|i'?ll|i wanna|i want to|we can|we'?ll)\s+"
                  r"(?:make|do|try|go with|cook)\s+(?P<dish>.+?)\W*$"
                  r"|^\W*(?:the )?(?P<dish2>.+?) sounds? (?:good|great|nice|perfect|yummy)\W*$", re.I)
NEXT = re.compile(r"^\W*(?:(?:ok(?:ay)?|done|alright|got it|yep|yeah|yes|cool|finished|did it|ready)[,.! ]*)*"
                  r"(?:(?:what'?s |whats |what is )?next(?: step)?|what now|now what|then what|and then|what do i do now|"
                  r"what'?s after that|go on|keep going)?\W*$", re.I)
BACK = re.compile(r"\b(go back|previous step|last step|step before|back a step|one step back)\b", re.I)
REPEAT = re.compile(r"\b(repeat( that| the step| it)?|say (that|it) again|what was (that|the step)|come again|"
                    r"what step (am i|are we) on|where (am i|were we)|what was i doing|sorry what)\b", re.I)
NEED = re.compile(r"\b(what (do|did) (i|we) need|ingredients|what goes in|how (much|many) (?P<what>[a-z][a-z ]{1,30}?)\b"
                  r"(?: do i| should i| goes| did| again|\?|$))", re.I)
TIMER = re.compile(r"\b(?:set|start|put)\s+(?:a |the |my )?timer(?:\s+for\s+(?P<n>\d+|a|an|one|two|three|four|five|ten|"
                   r"fifteen|twenty|thirty)\s*(?P<unit>min\w*|sec\w*|hour\w*))?", re.I)
LEFT = re.compile(r"\b(how (long|much time)( is)? (left|remaining|to go|until)|how long (on|for) the timer|timer status)\b", re.I)
BOX = re.compile(r"\b(what (have|did) we (cook|made|make)\w*|(our|my|the) recipe box|(our|my) recipes|"
                 r"what have i cooked|favou?rite recipes)\b", re.I)
RATE = re.compile(r"\b(?:give|rate)\s+(?:the\s+|that\s+|our\s+)?(?P<what>.+?)\s+(?:a\s+)?(?P<n>[1-5]|one|two|three|four|five)"
                  r"(?:\s*(?:/\s*5|out of (?:5|five)|stars?))?\W*$", re.I)
DROP = re.compile(r"\b(?:delete|remove|forget|drop)\s+(?:the\s+|our\s+|that\s+)?(?P<what>.+?)\s+recipe"
                  r"(?:\s+from (?:the |our )?recipe box)?\W*$", re.I)
THAT = re.compile(r"^(that|it|this|that one|this one|the same|same thing|what we made last time)$", re.I)
STOP = re.compile(r"\b(stop cooking|(we'?re|i'?m) done cooking|(cancel|end|stop) (the |this )?(recipe|cooking)|"
                  r"never ?mind the recipe|forget the recipe)\b", re.I)
WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "fifteen": 15,
         "twenty": 20, "thirty": 30}


def clean_dish(dish: str) -> str:
    dish = re.sub(r"\b(for (dinner|lunch|breakfast|tonight|us|me)|tonight|now|real quick|please|with you|again|"
                  r"like (last time|before)|the same way( as (last time|before))?)\b", "", dish, flags=re.I)
    dish = re.sub(r"^(some|a|an|the|me)\s+", "", dish.strip(" ,.!?"), flags=re.I)
    return re.sub(r"\s+", " ", dish).strip(" ,.!?")[:60]


class Cooking(Part):
    name = "cooking"

    def __init__(self, store=None, clock=time.time, llm=None, model: str = "", reminders=None, vision=None,
                 publish=lambda kind, data: None, idle=lambda: 0.0):
        super().__init__(store, clock)
        self.llm, self.model, self.reminders, self.vision = llm, model, reminders, vision
        self.publish, self.idle = publish, idle
        self.box = RecipeBox(store, clock)

    # ----- the session -----
    def session(self) -> dict | None:
        s = self.get("session")
        if s and self.clock() - s.get("touched", s["started"]) < SESSION_S and not s.get("ended"):
            return s
        return None

    def _save(self, s: dict):
        s["touched"] = self.clock()
        self.put("session", s)
        self.publish("us", {"what": "cooking", "step": s.get("i", 0)})

    def recipe(self, dish: str) -> dict | None:
        if self.llm is None:
            return None
        have = ""
        seen = getattr(self.vision, "last", None) if self.vision is not None else None
        if seen is not None and self.clock() - (self.get("fridge", 0) or 0) < OFFER_S:   # only right after a fridge photo
            have = (f" In their fridge (from a photo): {seen.description[:400]}. Use those where they fit the dish, but "
                    f"it must still be {dish}, the normal way; other basics are fine.")
        from .agent import strip_thinking

        for attempt in range(2):
            try:
                raw = self.llm.chat(self.model, [{"role": "user", "content": RECIPE_PROMPT.format(dish=dish, have=have)}],
                                    options={"temperature": 0.4 + 0.2 * attempt, "num_predict": 700}, fmt=RECIPE_SCHEMA).content
                import json

                data = json.loads(strip_thinking(raw))
            except Exception as exc:
                log.info("cooking: recipe failed: %s", exc)
                continue
            steps = [{"text": " ".join(str(s.get("text", "")).split())[:220], "minutes": max(0, min(240, int(s.get("minutes") or 0)))}
                     for s in data.get("steps") or [] if str(s.get("text", "")).strip()]
            ingredients = [" ".join(str(i).split())[:80] for i in data.get("ingredients") or [] if str(i).strip()]
            if 3 <= len(steps) <= 14:
                return {"title": " ".join(str(data.get("title") or dish).split())[:60] or dish, "ingredients": ingredients[:20],
                        "steps": steps}
        return None

    def recreate(self, said: str = "") -> dict | None:
        """Her home version of the restaurant dish in the last photo, into the recipe box (not cooked)."""
        seen = getattr(self.vision, "last", None) if self.vision is not None else None
        if seen is None or self.llm is None:
            return None
        import json

        from .agent import strip_thinking

        m = WHERE.search(said or "")
        where = m.group("where").strip() if m else ""
        prompt = RECREATE_PROMPT.format(user="They", where=f" at {where}" if where else " out",
                                        description=seen.description[:600], said=(said or "").replace("(Sent a photo)", "").strip()[:200])
        for attempt in range(2):
            try:
                raw = self.llm.chat(self.model, [{"role": "user", "content": prompt}],
                                    options={"temperature": 0.4 + 0.2 * attempt, "num_predict": 800}, fmt=RECREATE_SCHEMA).content
                data = json.loads(strip_thinking(raw))
            except Exception as exc:
                log.info("cooking: recreate failed: %s", exc)
                continue
            steps = [{"text": " ".join(str(s.get("text", "")).split())[:220], "minutes": max(0, min(240, int(s.get("minutes") or 0)))}
                     for s in data.get("steps") or [] if str(s.get("text", "")).strip()]
            ingredients = [" ".join(str(i).split())[:80] for i in data.get("ingredients") or [] if str(i).strip()]
            dish = " ".join(str(data.get("dish") or "").split())[:60]
            if 3 <= len(steps) <= 14 and ingredients:
                title = " ".join(str(data.get("title") or dish or "Our home version").split())[:60]
                r = self.box.add({"title": title, "dish": dish, "ingredients": ingredients[:20], "steps": steps},
                                 source=f"from a photo at {where}" if where else "from a photo")
                if r is not None:
                    self.put("recreated", {"id": r["id"], "t": self.clock()})
                    self.put("offered", self.clock())
                    self.publish("us", {"what": "cooking", "action": "recreated"})
                return r
        return None

    def saved(self, dish: str) -> dict | None:
        """A dish from the recipe box: 'that' = the last one cooked."""
        return self.box.last() if THAT.match(dish.strip()) else self.box.find(dish)

    def start(self, dish: str, recipe_id: int | None = None) -> dict | None:
        dish = clean_dish(dish) or "something simple"
        kept = self.box.get_one(recipe_id) if recipe_id else self.saved(dish)
        if kept is not None:
            r = {"title": kept["title"], "ingredients": kept["ingredients"], "steps": kept["steps"],
                 "recipe_id": kept["id"], "again": kept["cooked"]}
        elif THAT.match(dish):
            return None
        else:
            r = self.recipe(dish)
        if r is None:
            return None
        s = {**r, "dish": dish, "i": -1, "started": self.clock(), "timer": None}
        self._save(s)
        self.put("offered", 0)
        return s

    def keep(self, s: dict) -> dict | None:
        """Into the recipe box (once per walkthrough)."""
        if s.get("saved"):
            return None
        r = self.box.save(s)
        if r is not None:
            s["saved"] = r["id"]
        return r

    def stop(self) -> dict | None:
        s = self.get("session")
        if s:
            if s.get("i", -1) + 1 >= max(2, len(s.get("steps", [])) * 0.6):    # mostly cooked: it counts
                self.keep(s)
            s["ended"] = self.clock()
            self.put("session", s)
            self.publish("us", {"what": "cooking", "action": "ended"})
        return s

    def _step_words(self, s: dict) -> str:
        i, steps = s["i"], s["steps"]
        st = steps[i]
        out = f"Step {i + 1} of {len(steps)}: {st['text']}"
        if st["minutes"] >= 2:
            out += f" That's about {st['minutes']} minutes. Want me to set a timer?"
        if i == len(steps) - 1:
            out += " That's the last step!"
        return out

    def step(self, action: str = "next") -> str:
        s = self.session()
        if s is None:
            return "We're not cooking anything right now. Tell me what you want to make!"
        n = len(s["steps"])
        if action == "next":
            if s["i"] >= n - 1:
                s["finished"] = self.clock()
                self.keep(s)
                self._save(s)
                self.stop()
                return f"That was the last step. {s['title']} is done, enjoy it! It's in our recipe box now."
            s["i"] += 1
        elif action == "back":
            s["i"] = max(0, s["i"] - 1)
        elif action == "repeat":
            if s["i"] < 0:
                s["i"] = 0
        elif action == "ingredients":
            return f"For {s['title']} you need: " + "; ".join(s["ingredients"]) + "."
        self._save(s)
        return self._step_words(s)

    def how_much(self, what: str) -> str:
        s = self.session()
        if s is None:
            return "We're not cooking anything right now."
        from .goals import mentions

        hits = [i for i in s["ingredients"] if mentions(i, what)]
        if not hits:
            return f"The recipe doesn't list {what}. Ingredients: " + "; ".join(s["ingredients"]) + "."
        return "You need " + " and ".join(hits) + "."

    def timer(self, minutes: int | None = None, label: str = "") -> str:
        s = self.session()
        if minutes is None or minutes <= 0:
            if s is None or s["i"] < 0 or s["steps"][s["i"]]["minutes"] <= 0:
                return "How long should the timer be?"
            minutes = s["steps"][s["i"]]["minutes"]
        what = label or (s["steps"][s["i"]]["text"][:60] if s and s["i"] >= 0 else "your timer")
        due = dt.datetime.fromtimestamp(self.clock() + minutes * 60)
        if self.reminders is not None:
            r = self.reminders.add(f"Timer's up: {what}", due)
            self.publish("reminder", {"action": "added", "uid": r.uid, "text": r.text, "due": due.isoformat(timespec="seconds")})
        if s is not None:
            s["timer"] = {"until": self.clock() + minutes * 60, "minutes": minutes, "what": what}
            self._save(s)
        return f"Timer set for {minutes} minute{'s' if minutes != 1 else ''}. I'll tell you when it's done."

    def time_left(self) -> str:
        s = self.session()
        t = s.get("timer") if s else None
        if not t or t["until"] <= self.clock():
            return "There's no timer running."
        left = t["until"] - self.clock()
        mins, secs = int(left // 60), int(left % 60)
        return f"{mins} minute{'s' if mins != 1 else ''} and {secs} seconds left." if mins else f"{secs} seconds left."

    # ----- in conversation -----
    def rating_note(self, user_text: str, last_reply: str) -> str | None:
        """Their answer to "how did it turn out?" sets the stars in the recipe box."""
        s = self.get("session")
        if not s or not s.get("saved") or s.get("rated") or not s.get("finished") or self.clock() - s["finished"] > 8 * 3600:
            return None
        title_words = [w for w in re.findall(r"[a-z]+", s["title"].lower()) if len(w) > 3]
        low = (last_reply or "").lower()
        if not (re.search(r"turn(ed)? out|how (was|did)|taste|any good", low) or any(w in low for w in title_words)):
            return None
        n = stars_in(user_text)
        if not n:
            return None
        self.box.rate(s["saved"], n)
        s["rated"] = n
        self.put("session", s)
        self.publish("us", {"what": "cooking", "action": "rated"})
        return (f"They told you how the {s['title']} turned out: you gave it {n} star{'s' if n != 1 else ''} in your shared "
                "recipe box (you can mention that lightly)")

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        from .vision import PHOTO_TAG

        if (rated := self.rating_note(user_text, last_reply)) is not None:
            return [rated]

        if user_text.startswith(PHOTO_TAG) and COOK_Q.search(user_text) and not RECREATE.search(user_text):
            self.put("offered", self.clock())
            self.put("fridge", self.clock())
            return ["They want to cook something with what's in the photo. Suggest two or three simple dishes they "
                    "could make with what you can see (name them, one line each), and offer to walk them through one "
                    "step by step"]
        if COOK_Q.search(user_text) and not self.session():
            self.put("offered", self.clock())
            return ["If you suggest dishes, keep it to two or three simple ones, and offer to walk them through one step "
                    "by step (they can send a photo of their fridge too)"]
        s = self.session()
        if s is not None:
            where = f"step {s['i'] + 1} of {len(s['steps'])}" if s["i"] >= 0 else "not started yet"
            return [f"You're cooking {s['title']} together right now ({where}). If they chat, keep it short and warm; "
                    "they're busy in the kitchen"]
        return []

    def route(self, user_text: str, last_reply: str = "") -> tuple[str, dict] | None:
        from .vision import PHOTO_TAG

        t = user_text.strip()
        if RECREATE.search(t):
            seen = getattr(self.vision, "last", None) if self.vision is not None else None
            recent = seen is not None and self.clock() - seen.at < 15 * 60
            if t.startswith(PHOTO_TAG) or (recent and re.search(r"\b(photo|pic|picture|dish|that|this)\b", t, re.I)):
                return "recreate_dish", {"said": t}
        made = self.get("recreated")
        if made and self.clock() - made["t"] < OFFER_S and "recipe box" in (last_reply or "").lower() and \
                re.match(r"(?i)\W*(yes|yeah|yep|sure|ok(ay)?|let'?s (do it|go|cook it|make it)|please|why not)\b", t):
            r = self.box.get_one(made["id"])
            if r is not None:
                return "start_cooking", {"dish": r["title"]}
        if BOX.search(t):
            return "list_recipes", {}
        if (m := RATE.search(t)) and self.box.find(m.group("what")) is not None:
            n = m.group("n").lower()
            return "rate_recipe", {"which": m.group("what"), "stars": int(n) if n.isdigit() else
                                   {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}[n]}
        if (m := DROP.search(t)) and self.box.find(m.group("what")) is not None:
            return "remove_recipe", {"which": m.group("what")}
        s = self.session()
        if s is not None:
            if STOP.search(t):
                return "stop_cooking", {}
            if (m := TIMER.search(t)):
                n = m.group("n")
                minutes = None
                if n:
                    v = int(n) if n.isdigit() else WORDS[n.lower()]
                    unit = (m.group("unit") or "min").lower()
                    minutes = max(1, round(v / 60)) if unit.startswith("sec") else v * 60 if unit.startswith("hour") else v
                return "cooking_timer", {"minutes": minutes or 0}
            if "timer" in (last_reply or "").lower() and re.match(r"(?i)\W*(yes|yeah|yep|sure|please|ok(ay)?|go ahead|do it)\b", t):
                return "cooking_timer", {"minutes": 0}
            if LEFT.search(t):
                return "cooking_timer_left", {}
            if BACK.search(t):
                return "cooking_step", {"action": "back"}
            if REPEAT.search(t):
                return "cooking_step", {"action": "repeat"}
            if (m := NEED.search(t)):
                if m.group("what") and not re.match(r"(?i)(time|long)", m.group("what")):
                    return "cooking_how_much", {"what": m.group("what").strip()}
                return "cooking_step", {"action": "ingredients"}
            if NEXT.fullmatch(t) and t.strip(" .!?"):
                return "cooking_step", {"action": "next"}
        m = START.search(t)
        dish = (m.group("dish") or m.group("dish2")) if m else None
        if dish and (FOODISH.search(t) or m.group("dish2") or self.clock() - (self.get("offered", 0) or 0) < OFFER_S
                     or self.saved(clean_dish(dish)) is not None):
            if not re.search(r"\b(website|app|game|video|playlist|bot|program|script|money|friends|time)\b", dish, re.I):
                return "start_cooking", {"dish": clean_dish(dish)}
        offered = self.get("offered", 0) or 0
        if s is None and self.clock() - offered < OFFER_S and (m := PICK.search(t)):
            return "start_cooking", {"dish": clean_dish(m.group("dish") or m.group("dish2"))}
        return None

    # ----- afterwards -----
    def moments(self, now: float) -> list[Moment]:
        s = self.get("session")
        if not s or not s.get("finished"):
            return []
        after = now - s["finished"]
        key = f"after:{int(s['started'])}"
        if 45 * 60 <= after <= 4 * 3600 and self.idle() < 300 and not self.done(key):
            return [Moment("cooking", f"Earlier you two cooked {s['title']} together (you walked {{user}} through it). "
                                      "Ask how it turned out, one playful line.", key=key, part=self.name)]
        return []

    def status(self) -> dict:
        s = self.session()
        if s is None:
            return {"session": None, "recipes": self.box.status()}
        t = s.get("timer")
        return {"recipes": self.box.status(), "session": {"title": s["title"], "ingredients": s["ingredients"], "steps": s["steps"], "i": s["i"],
                            "timer_until": t["until"] if t and t["until"] > self.clock() else None}}
