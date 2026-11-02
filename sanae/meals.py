"""Dinners for the week, planned together, feeding the grocery list.

  - "Plan dinners this week" / "plan 3 meals": one dinner a day from today (tomorrow after 8 PM)
    until the count is reached. Most come from the recipe box (recipes.py): rated ones first, not
    cooked in the last week, and ones that use something about to go off (groceries.py); the rest
    are new simple dishes the model suggests (titles + ingredients only, steps come when you cook).
  - Then she offers to put what you're missing on the grocery list: the ingredients minus kitchen
    basics, what's already on the list, and what you bought in the last few days.
  - "What's for dinner?" -> tonight's; "swap tonight" / "swap Thursday" -> another dish.
  - Around dinner time on a planned day she asks if you want to cook it together (cooking.py).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import re
import time

from .initiative import Moment
from .part import Part

log = logging.getLogger(__name__)
SCHEMA = """
CREATE TABLE IF NOT EXISTS meal_plan (
    id INTEGER PRIMARY KEY, day TEXT NOT NULL, title TEXT NOT NULL, recipe_id INTEGER NOT NULL DEFAULT 0,
    ingredients TEXT NOT NULL, cooked INTEGER NOT NULL DEFAULT 0, added TEXT NOT NULL);
"""
IDEAS_PROMPT = (
    "Suggest {n} different simple weeknight dinners for {user}, cooking for themselves in a small kitchen, each doable in "
    "under 40 minutes.{likes}{use}{avoid}\n"
    "Return JSON: meals (list of {{title (short dish name), ingredients (list of short strings with amounts, e.g. "
    "\"200 g pasta\")}})."
)
IDEAS_SCHEMA = {"type": "object", "properties": {"meals": {"type": "array", "items": {"type": "object", "properties": {
    "title": {"type": "string"}, "ingredients": {"type": "array", "items": {"type": "string"}}},
    "required": ["title", "ingredients"]}}}, "required": ["meals"]}
BASICS = {"salt", "pepper", "black pepper", "oil", "olive oil", "vegetable oil", "cooking oil", "water", "sugar", "flour",
          "salt and pepper", "ice", "butter"}
WORD_N = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "a few": 3, "a couple of": 2}
PLAN = re.compile(r"\b(?:plan|make|do|set up|sort out|figure out)\s+(?:a |my |our |the |some )?(?:(?P<n>\d|one|two|three|four|five|six|"
                  r"seven|a few|a couple of)\s+)?(?:dinners?|meals?|meal plan|week of (?:dinners|meals)|food for the week)"
                  r"(?:\s+(?:this|for the|for this|next)\s+week)?\b|\bmeal plan(?:ning)? for (?:the|this|next) week\b|"
                  r"\bwhat should i (?:eat|cook|make) this week\b", re.I)
SHOW = re.compile(r"\b(what'?s (?:on )?(?:my|our|the) meal plan|show (?:me )?(?:my|our|the) meal plan|"
                  r"what (?:are|is) (?:we|i) (?:eating|having|cooking) this week|(?:my|our|the) dinners this week)\b", re.I)
TONIGHT = re.compile(r"\b(what'?s for dinner(?: tonight)?|what am i (?:eating|having|cooking|making) (?:tonight|for dinner)|"
                     r"what'?s (?:the plan )?for dinner|dinner tonight\?)", re.I)
SWAP = re.compile(r"\b(?:swap|change|switch|replace|skip)\s+(?:the\s+)?(?:dinner\s+(?:for|on)\s+)?(?P<day>tonight|today|"
                  r"tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:'?s)?(?:\s+(?:dinner|meal))?\b", re.I)
YES = re.compile(r"^\W*(yes|yeah|yep|sure|please|ok(ay)?|go ahead|do it|add (them|it|those)|sounds good)\b", re.I)
PREP = re.compile(r"\b(cooked|chopped|diced|minced|sliced|grated|fresh|freshly|large|small|medium|ripe|boneless|"
                  r"skinless|shredded|crushed|ground|leftover|day-old|cold|warm|softened|melted|finely|roughly)\s+", re.I)
AMOUNT = re.compile(r"^\s*(?:about\s+|around\s+)?[\d½¼¾⅓⅔⅛.,/\- ]+\s*(?:(?:cups?|c\.|tbsps?|tablespoons?|g|grams?|kg|"
                    r"ml|l|liters?|oz|ounces?|lbs?|pounds?|cloves?|cans?|tins?|slices?|pieces?|handfuls?|bunch(?:es)?|"
                    r"heads?|stalks?|sprigs?|packs?|packets?|jars?|bottles?|sticks?)\b\.?\s*)?(?:of\s+)?", re.I)
PANTRY_AMOUNT = re.compile(r"\b(tsps?|teaspoons?|pinch(?:es)?|dash(?:es)?|to taste|for garnish|optional|as needed)\b", re.I)


def shopping_name(ingredient: str) -> str:
    """'1/4 cup grated Parmesan' -> 'parmesan'; '1/2 tsp paprika' / 'salt and pepper to taste' -> '' (you have those)."""
    if PANTRY_AMOUNT.search(ingredient):
        return ""
    s = re.sub(r"\(.*?\)|,.*$", "", ingredient)
    s = AMOUNT.sub("", s)
    for _ in range(2):
        s = PREP.sub("", s)
    s = re.sub(r"\s+(cloves?|leaves|stalks?|sprigs?)$", "", s.strip(), flags=re.I).strip(" .-").lower()
    return "" if not s or s in BASICS or s in ("salt and pepper", "water") else s


DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class Meals(Part):
    name = "meals"

    def __init__(self, store=None, clock=time.time, llm=None, model: str = "", cooking=None, groceries=None,
                 friend=None, user: str = "them", idle=lambda: 0.0, publish=lambda kind, data: None):
        super().__init__(store, clock)
        self.llm, self.model, self.cooking, self.groceries, self.friend = llm, model, cooking, groceries, friend
        self.user, self.idle, self.publish = user, idle, publish
        self._schema(SCHEMA)

    @property
    def box(self):
        return getattr(self.cooking, "box", None)

    # ----- the plan -----
    def week(self) -> list[dict]:
        """Planned dinners from today on (and the last 2 days, for the phone)."""
        since = (self.now().date() - dt.timedelta(days=2)).isoformat()
        rows = self._rows("SELECT * FROM meal_plan WHERE day >= ? ORDER BY day, id", (since,))
        return [{**r, "ingredients": json.loads(r["ingredients"])} for r in rows]

    def on(self, day: dt.date) -> dict | None:
        rows = [r for r in self.week() if r["day"] == day.isoformat()]
        return rows[0] if rows else None

    def _food_likes(self) -> str:
        if self.friend is None:
            return ""
        from .cooking import FOODISH

        try:
            facts = [f.text for f in self.friend.facts() if f.kind in ("like", "dislike") and FOODISH.search(f.text)]
        except Exception:
            return ""
        return (" What you know about their taste: " + "; ".join(facts[:6]) + ".") if facts else ""

    def ideas(self, n: int, avoid: list[str], use: list[str]) -> list[dict]:
        if self.llm is None or n <= 0:
            return []
        from .agent import strip_thinking

        prompt = IDEAS_PROMPT.format(
            n=n, user=self.user, likes=self._food_likes(),
            use=f" If it fits, use up: {', '.join(use)}." if use else "",
            avoid=f" Not these (already planned): {', '.join(avoid)}." if avoid else "")
        for attempt in range(2):
            try:
                raw = self.llm.chat(self.model, [{"role": "user", "content": prompt}],
                                    options={"temperature": 0.7 + 0.2 * attempt, "num_predict": 900}, fmt=IDEAS_SCHEMA).content
                meals = json.loads(strip_thinking(raw)).get("meals") or []
            except Exception as exc:
                log.info("meals: ideas failed: %s", exc)
                continue
            out, seen = [], {a.lower() for a in avoid}
            for m in meals:
                title = " ".join(str(m.get("title") or "").split())[:60]
                ing = [" ".join(str(i).split())[:80] for i in m.get("ingredients") or [] if str(i).strip()]
                if title and title.lower() not in seen and 2 <= len(ing) <= 16:
                    seen.add(title.lower())
                    out.append({"title": title, "ingredients": ing, "recipe_id": 0})
            if out:
                return out[:n]
        return []

    def _from_box(self, k: int, skip: set[str], use: list[str]) -> list[dict]:
        if self.box is None or k <= 0:
            return []
        week_ago = (self.now() - dt.timedelta(days=7)).isoformat()
        from .groceries import key

        def score(r):
            uses = sum(1 for u in use if any(key(u).split()[-1] in key(i) for i in r["ingredients"]))
            return (r["stars"] or 3) + 2 * uses - (2 if r["last_cooked"] >= week_ago else 0)

        rs = [r for r in self.box.all() if r["title"].lower() not in skip and (r["stars"] == 0 or r["stars"] >= 3)]
        return [{"title": r["title"], "ingredients": r["ingredients"], "recipe_id": r["id"]}
                for r in sorted(rs, key=score, reverse=True)[:k]]

    def plan(self, n: int = 5) -> list[dict]:
        n = max(1, min(7, int(n or 5)))
        d = self.now()
        first = d.date() + dt.timedelta(days=1 if d.hour >= 20 else 0)
        days = [first + dt.timedelta(days=i) for i in range(n)]
        self._exec("DELETE FROM meal_plan WHERE day >= ?", (first.isoformat(),))
        use = [g["item"] for g in self.groceries.going_off()] if self.groceries is not None else []
        picks = self._from_box(math.ceil(n * 0.6), set(), use)
        picks += self.ideas(n - len(picks), [p["title"] for p in picks], use)
        if len(picks) < n:                       # no model / few new ones: more from the box
            picks += self._from_box(n - len(picks), {p["title"].lower() for p in picks}, use)
        now = d.isoformat(timespec="minutes")
        for day, p in zip(days, picks):
            self._exec("INSERT INTO meal_plan (day, title, recipe_id, ingredients, added) VALUES (?,?,?,?,?)",
                       (day.isoformat(), p["title"], p["recipe_id"], json.dumps(p["ingredients"]), now))
        self.put("offered", self.clock())
        self.publish("us", {"what": "meals", "action": "planned"})
        return [r for r in self.week() if r["day"] >= first.isoformat()]

    def swap(self, day: dt.date) -> dict | None:
        old = self.on(day)
        if old is None:
            return None
        planned = [r["title"] for r in self.week()]
        use = [g["item"] for g in self.groceries.going_off()] if self.groceries is not None else []
        new = (self.ideas(1, planned, use) or self._from_box(1, {t.lower() for t in planned}, use) or [None])[0]
        if new is None:
            return None
        self._exec("UPDATE meal_plan SET title = ?, recipe_id = ?, ingredients = ?, cooked = 0 WHERE id = ?",
                   (new["title"], new["recipe_id"], json.dumps(new["ingredients"]), old["id"]))
        self.publish("us", {"what": "meals", "action": "swapped"})
        return self.on(day)

    def remove(self, mid: int) -> bool:
        cur = self._exec("DELETE FROM meal_plan WHERE id = ?", (int(mid),))
        return cur.rowcount > 0

    # ----- what's missing -----
    def missing(self) -> list[str]:
        from .groceries import key, split_items

        today = self.now().date().isoformat()
        need: dict[str, str] = {}
        for r in self.week():
            if r["day"] < today or r["cooked"]:
                continue
            for ing in r["ingredients"]:
                item = shopping_name(ing)
                if item and key(item) and key(item) not in {key(b) for b in BASICS}:
                    need.setdefault(key(item), item)
        if self.groceries is not None:
            on_list = {key(g["item"]) for g in self.groceries.items(open_only=True)}
            since = (self.now().date() - dt.timedelta(days=5)).isoformat()
            fresh = {key(r["item"]) for r in self.groceries._rows("SELECT item FROM grocery_bought WHERE day >= ?", (since,))}
            need = {k: v for k, v in need.items() if k not in on_list and k not in fresh
                    and self.groceries.find(v) is None}
        return list(need.values())

    def to_groceries(self) -> list[str]:
        if self.groceries is None:
            return []
        items = self.missing()
        if items:
            self.groceries.add(", ".join(items), who="plan")
            self.publish("us", {"what": "groceries", "action": "added"})
        self.put("offered", 0)
        return items

    # ----- words -----
    def day_name(self, day: str) -> str:
        d = dt.date.fromisoformat(day)
        today = self.now().date()
        return "tonight" if d == today else "tomorrow" if d == today + dt.timedelta(days=1) else d.strftime("%A")

    def spoken(self, rows: list[dict] | None = None) -> str:
        today = self.now().date().isoformat()
        rows = [r for r in (rows if rows is not None else self.week()) if r["day"] >= today]
        if not rows:
            return "There's no meal plan yet. Say \"plan dinners this week\" and I'll put one together."
        return "; ".join(f"{self.day_name(r['day'])}: {r['title']}" + (" (done)" if r["cooked"] else "") for r in rows) + "."

    # ----- in conversation -----
    def offered(self) -> bool:
        return self.clock() - (self.get("offered") or 0) <= 15 * 60

    def _day(self, word: str) -> dt.date:
        word = word.lower()
        today = self.now().date()
        if word in ("tonight", "today"):
            return today
        if word == "tomorrow":
            return today + dt.timedelta(days=1)
        return today + dt.timedelta(days=(DAYS.index(word) - today.weekday()) % 7)

    def route(self, user_text: str, last_reply: str = "") -> tuple[str, dict] | None:
        t = user_text.strip()
        if self.offered() and "grocery list" in (last_reply or "").lower() and YES.search(t):
            return "meal_plan_groceries", {}
        if (m := PLAN.search(t)) and not re.search(r"\b(lunch|breakfast)\b", t, re.I):
            n = m.group("n")
            return "plan_meals", {"count": (int(n) if n and n.isdigit() else WORD_N.get((n or "").lower(), 5))}
        if SHOW.search(t):
            return "meal_plan", {}
        if (m := SWAP.search(t)) and (self.on(self._day(m.group("day"))) is not None):
            return "swap_meal", {"day": m.group("day").lower()}
        if TONIGHT.search(t) and self.on(self.now().date()) is not None:
            return "meal_plan", {"day": "tonight"}
        return None

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        r = self.on(self.now().date())
        from .cooking import COOK_Q

        if r is not None and not r["cooked"] and COOK_Q.search(user_text):
            return [f"Your meal plan says {r['title']} tonight; suggest that first (you can walk them through it)"]
        return []

    # ----- on her own -----
    def observe(self, now: float):
        """A planned dish that got cooked (it's in the recipe box as cooked today) is ticked."""
        r = self.on(dt.datetime.fromtimestamp(now).date()) if self.store is not None else None
        if r is None or r["cooked"] or self.box is None:
            return
        from .recipes import words

        today = dt.datetime.fromtimestamp(now).date().isoformat()
        for b in self.box.all():
            if b["last_cooked"][:10] == today and (b["id"] == r["recipe_id"] or words(b["title"]) & words(r["title"])):
                self._exec("UPDATE meal_plan SET cooked = 1, recipe_id = ? WHERE id = ?", (b["id"], r["id"]))
                break

    def moments(self, now: float) -> list[Moment]:
        if self.store is None:
            return []
        d = dt.datetime.fromtimestamp(now)
        if not (17 <= d.hour < 20) or self.idle() > 120:
            return []
        r = self.on(d.date())
        key = f"tonight:{d.date().isoformat()}"
        if r is None or r["cooked"] or self.done(key):
            return []
        return [Moment("meals", f"Your meal plan says {r['title']} for dinner tonight. Ask {{user}}, lightly, if they want "
                                "to cook it together (you'd walk them through it). One line.", key=key, part=self.name)]

    def status(self) -> dict:
        rows = self.week()
        today = self.now().date().isoformat()
        return {"days": [{"id": r["id"], "day": r["day"], "label": self.day_name(r["day"]) if r["day"] >= today else
                          dt.date.fromisoformat(r["day"]).strftime("%A"), "title": r["title"], "cooked": bool(r["cooked"]),
                          "from_box": bool(r["recipe_id"]), "past": r["day"] < today} for r in rows],
                "missing": self.missing()}
