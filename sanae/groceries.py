"""The grocery list, kept together, for the actual shop.

  - "Add milk, eggs and 2 cans of tomatoes to the grocery list", "we're out of coffee", or the phone
    (Us tab -> Groceries). Each item lands in a store section (produce, dairy, ...), so in the shop
    the list reads aisle by aisle.
  - Before you go ("I'm going grocery shopping", or the phone's "Ideas"), she asks about things you
    might need: what you usually buy and are probably out of by now (from what you've ticked off
    before), what goes with what's already on the list (pasta -> sauce, parmesan), a recipe you're
    cooking together, and a few staples while there's no history yet. Say "yes, eggs and coffee" or
    "no" and she adds or drops them (dropped ideas stay away for two weeks).
  - In the shop: tick items on the phone, or "got the milk". "Done shopping" clears what you ticked.
  - Now and then (a weekend afternoon) she asks first when things are probably running low.
  - Fresh things you ticked off (milk, bread, berries, chicken...) have a rough shelf life (SHELF);
    an evening when one is about to turn, she says so ("the milk from Tuesday is probably going off,
    use it tonight?"), with a dish from your recipe box that uses it if there is one. "I finished the
    milk" / "threw out the spinach" / "it's still fine" and she stops counting it.
All suggestions are worked out in code, so nothing is made up.
"""
from __future__ import annotations

import datetime as dt
import re
import statistics
import time

from .initiative import Moment
from .part import Part

SCHEMA = """
CREATE TABLE IF NOT EXISTS groceries (
    id INTEGER PRIMARY KEY, item TEXT NOT NULL, qty TEXT NOT NULL DEFAULT '', section TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0, who TEXT NOT NULL DEFAULT 'you', added TEXT NOT NULL, done_at TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS grocery_bought (id INTEGER PRIMARY KEY, item TEXT NOT NULL, day TEXT NOT NULL);
"""
# Store order: how a shop is usually walked
SECTIONS = ["Produce", "Bakery", "Dairy & eggs", "Meat & fish", "Frozen", "Pantry", "Snacks", "Drinks", "Household",
            "Personal care", "Other"]
SECTION_WORDS = {
    "Produce": "apple banana orange lemon lime grape berry strawberry blueberry raspberry avocado tomato potato onion "
               "garlic ginger carrot lettuce spinach kale cucumber pepper chili broccoli cauliflower mushroom zucchini "
               "celery cilantro coriander parsley basil mint herb corn peas bean sprout cabbage mango pineapple melon "
               "watermelon peach pear plum kiwi fruit vegetable veggie salad scallion squash pumpkin beet radish okra",
    "Bakery": "bread bagel bun roll baguette croissant tortilla wrap pita naan muffin cake cookie donut loaf",
    "Dairy & eggs": "milk egg butter cheese yogurt yoghurt cream paneer curd ghee parmesan mozzarella cheddar feta",
    "Meat & fish": "chicken beef pork lamb mutton turkey bacon sausage ham salmon tuna fish shrimp prawn steak mince",
    "Frozen": "frozen ice cream pizza nugget fries dumpling popsicle",
    "Pantry": "rice pasta noodle spaghetti macaroni flour sugar salt oil vinegar sauce ketchup mayo mayonnaise mustard "
              "honey jam jelly peanut nut almond cereal oat oatmeal granola lentil dal chickpea can canned soup stock "
              "broth spice masala cumin turmeric paprika cinnamon oregano soy syrup ramen tofu quinoa breadcrumb",
    "Snacks": "chip crisp cracker popcorn chocolate candy biscuit pretzel snack bar trail",
    "Drinks": "water juice soda coke pepsi sprite coffee tea beer wine kombucha lemonade drink energy",
    "Household": "paper towel tissue toilet detergent soap dish sponge trash garbage bag foil wrap battery bulb cleaner "
                 "bleach napkin",
    "Personal care": "shampoo conditioner toothpaste toothbrush floss deodorant razor lotion sunscreen pad tampon "
                     "vitamin medicine bandage",
}
OVERRIDES = {"peanut butter": "Pantry", "almond butter": "Pantry", "ice cream": "Frozen", "cream cheese": "Dairy & eggs",
             "coconut milk": "Pantry", "toilet paper": "Household", "paper towel": "Household", "sour cream": "Dairy & eggs",
             "salad dressing": "Pantry", "maple syrup": "Pantry", "hot sauce": "Pantry"}
# Things that go together: on the list -> worth asking about
PAIRS = {
    "pasta": ["pasta sauce", "parmesan"], "spaghetti": ["pasta sauce", "parmesan"], "cereal": ["milk"],
    "bread": ["butter"], "taco": ["tortillas", "salsa", "cheese"], "tortilla": ["salsa", "cheese"],
    "burger": ["buns", "cheese", "lettuce"], "rice": ["soy sauce"], "pancake": ["maple syrup", "eggs"],
    "coffee": ["milk"], "tea": ["milk"], "salad": ["salad dressing"], "lettuce": ["salad dressing", "tomatoes"],
    "chips": ["salsa"], "peanut butter": ["bread", "jam"], "oatmeal": ["bananas"], "oats": ["bananas"],
    "chicken": ["rice", "garlic"], "steak": ["potatoes"], "noodles": ["soy sauce"], "ramen": ["eggs"],
    "yogurt": ["granola"], "bagels": ["cream cheese"], "eggs": ["bread"], "curry": ["rice", "naan"],
}
# Rough fridge life in days for fresh things (the last word of the item, singular)
SHELF = {"milk": 7, "bread": 6, "loaf": 6, "bagel": 5, "bun": 5, "roll": 5, "tortilla": 10, "naan": 5, "banana": 5,
         "berry": 4, "strawberry": 4, "blueberry": 6, "raspberry": 3, "grape": 7, "peach": 5, "pear": 6, "avocado": 4,
         "mango": 5, "spinach": 5, "lettuce": 5, "salad": 4, "kale": 6, "cilantro": 5, "coriander": 5, "parsley": 6,
         "basil": 4, "mint": 5, "herb": 5, "mushroom": 5, "tomato": 6, "cucumber": 6, "zucchini": 6, "sprout": 3,
         "scallion": 6, "chicken": 2, "beef": 2, "pork": 2, "mince": 2, "steak": 3, "fish": 2, "salmon": 2, "shrimp": 2,
         "prawn": 2, "turkey": 2, "sausage": 4, "yogurt": 12, "yoghurt": 12, "cream": 7, "paneer": 5, "tofu": 5,
         "hummus": 7, "juice": 7, "egg": 25}
NOT_FRESH = re.compile(r"\b(frozen|canned|can of|dried|powder|uht|oat milk|almond milk|soy milk|long life|sauce|"
                       r"butter|cheese|ice cream|chips?|crackers?|chocolate|bars?|shake|candy)\b", re.I)
USED = re.compile(r"\b(?:i|we)\s+(?:just\s+)?(?:used up|used|finished|threw out|threw away|tossed|binned|ate|drank|"
                  r"cooked)\s+(?:all\s+)?(?:the|my|our|that)\s+(?P<what>.+?)\W*$"
                  r"|\b(?:the\s+)?(?P<what2>[a-z ]{2,30}?)\s+(?:is|are|was|were|'?s)\s+(?:still\s+(?:fine|good|okay|ok)|"
                  r"gone|finished|used up|all gone)\b", re.I)
STAPLES = ["milk", "eggs", "bread", "bananas", "rice", "onions", "coffee", "toilet paper"]
SKIP_DAYS = 14
OFFER_S = 15 * 60            # her question about extras is answered within this long
SHOP_S = 2 * 3600            # "I'm going shopping": "got the milk" ticks things off for this long
KEEP_WHOLE = re.compile(r"\b(mac and cheese|salt and pepper|peanut butter and jelly|fish and chips|half and half|"
                        r"sweet and sour \w+|chips and salsa|rice and beans)\b", re.I)
NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "a dozen": "12", "dozen": "12",
                "a couple of": "2", "a couple": "2", "a few": "a few"}
UNITS = r"(?:bags?|boxes|box|bottles?|cans?|jars?|packs?|packets?|cartons?|loaf|loaves|lbs?|pounds?|kg|kilos?|grams?|g|" \
        r"gallons?|liters?|litres?|l|ml|oz|ounces?|bunch(?:es)?|dozen|tubs?|blocks?|heads?|cloves?|rolls?|cups?|" \
        r"tablespoons?|tbsp|teaspoons?|tsp|pinch(?:es)?|slices?|pieces?|sticks?|handfuls?)"
QTY = re.compile(rf"^(?P<n>\d+(?:\.\d+)?|one|two|three|four|five|six|a dozen|dozen|a couple of|a couple|a few)\s+"
                 rf"(?:(?P<unit>{UNITS})\s+(?:of\s+)?)?(?P<item>.+)$", re.I)
FILLER = re.compile(r"^(?:some|more|a|an|the|fresh|new|extra)\s+", re.I)

_LIST = r"(?:my |the |our )?(?:grocery|groceries|shopping)(?: list)?"
G_ADD = re.compile(rf"\b(?:add|put|throw|stick)\s+(?P<what>.+?)\s+(?:to|on|in(?:to)?)\s+{_LIST}\W*$"
                   rf"|^\W*{_LIST}\s*[:,-]\s*(?:add\s+)?(?P<what2>.+?)\W*$"
                   rf"|\b(?:we'?re|i'?m|we are|i am|we|i)\s+(?:all\s+)?(?:out of|almost out of|running low on|low on|"
                   rf"ran out of|run out of)\s+(?P<what3>.+?)\W*$", re.I)
G_SHOW = re.compile(rf"^\W*(?:(?:hey |ok(?:ay)? )?(?:what'?s|what is|read(?: me)?|show(?: me)?|tell me)\s+(?:on |in )?{_LIST}"
                    rf"|what (?:do|did) (?:i|we) need (?:to buy|to get|from the (?:store|shop|supermarket))"
                    rf"|{_LIST})\W*$", re.I)
G_DROP = re.compile(rf"\b(?:take|remove|delete|drop|scratch|cross)\s+(?P<what>.+?)\s+(?:off|from)\s+{_LIST}\W*$", re.I)
G_CLEAR = re.compile(rf"^\W*(?:clear|wipe|empty|delete)\s+(?:the |my |our )?(?:whole |entire )?{_LIST}\W*$", re.I)
G_DONE = re.compile(r"\b(?:done|finished|back from) (?:the )?(?:grocery |groceries |food )?(?:shopping|store|shop|supermarket)\b|"
                    r"\bgot everything\b", re.I)
G_SHOP = re.compile(r"\b(?:i'?m|i am|we'?re|we are|heading|going|gonna go|about to go|off)\s+(?:to\s+)?(?:go\s+)?"
                    r"(?:do\s+(?:the\s+)?)?(?:grocery shopping|groceries|shopping for (?:food|groceries)|food shopping|"
                    r"(?:to |at )?(?:the )?(?:grocery store|supermarket|store|costco|walmart|target|trader joe'?s|"
                    r"safeway|kroger|aldi|whole foods|fry'?s|sprouts|frys))\b|"
                    r"\b(?:help me|let'?s) (?:with (?:the )?)?(?:shop|grocery shop|do (?:the )?groceries)\b|"
                    r"\b(?:i'?m|we'?re) at the (?:grocery store|store|supermarket|costco|walmart|target)\b", re.I)
G_IDEAS = re.compile(rf"\b(?:what else (?:do|should|could|might) (?:i|we) (?:need|get|buy|grab)|anything else (?:i|we) (?:need|should get)|"
                     rf"(?:suggest|ideas for|help me think of) (?:some )?(?:groceries|things to buy|stuff to buy)|"
                     rf"what (?:am i|are we) (?:missing|forgetting)(?: on {_LIST})?)\b", re.I)
G_GOT = re.compile(r"^\W*(?:got|grabbed|picked up|have|found)\s+(?:the\s+)?(?P<what>.+?)\W*$|"
                   r"^\W*(?:check|tick|cross)\s+(?:off\s+)?(?P<what2>.+?)(?:\s+off)?\W*$", re.I)
G_RECIPE = re.compile(rf"\b(?:add|put)\s+(?:the |all the )?ingredients\s+(?:to|on)\s+{_LIST}\b", re.I)
YES = re.compile(r"^\W*(?:yes|yeah|yep|yup|sure|ok(?:ay)?|please|all of (?:them|it)|both|all|add (?:them|those|it|all))\b", re.I)
NO = re.compile(r"^\W*(?:no|nah|nope|none|not really|i'?m good|we'?re good|i have (?:them|those|it|everything)|"
                r"all good|nothing)\b", re.I)


def section_for(item: str) -> str:
    """The aisle: a few fixed phrases, then the last word ('pasta sauce' is a sauce), then any word."""
    low = item.lower()
    for phrase, name in OVERRIDES.items():
        if phrase in low:
            return name
    words = re.findall(r"[a-z]+", low)

    def match(w: str) -> str | None:
        forms = {w, w[:-1] if w.endswith("s") else w, w[:-2] if w.endswith("es") else w,
                 w[:-3] + "y" if w.endswith("ies") else w}
        return next((name for name in SECTIONS[:-1] if forms & set(SECTION_WORDS[name].split())), None)

    for w in ([words[-1]] if words else []) + words:
        if found := match(w):
            return found
    return "Other"


def key(item: str) -> str:
    """'Bananas' / 'banana' / 'the bananas' -> 'banana' (for matching, not for showing)."""
    w = FILLER.sub("", item.lower().strip())
    w = re.sub(r"[^a-z0-9 ]+", "", w)
    w = re.sub(r"\s+", " ", w).strip()
    if w.endswith("oes"):
        return w[:-2]
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    return w


def split_items(text: str) -> list[tuple[str, str]]:
    """'2 cans of tomatoes, milk and a dozen eggs' -> [('tomatoes', '2 cans'), ('milk', ''), ('eggs', '12')]."""
    keep: dict[str, str] = {}

    def hold(m):
        token = f"\x00{len(keep)}\x00"
        keep[token] = m.group(0)
        return token

    text = KEEP_WHOLE.sub(hold, (text or "").strip().strip(".!?"))
    parts = re.split(r"\s*(?:,|;|\+|&|\band\b|\bplus\b|\balso\b)\s*", text, flags=re.I)
    out = []
    for p in parts:
        for token, whole in keep.items():
            p = p.replace(token, whole)
        p = re.sub(r"^(?:and|also|some more|some|more|a|an|the)\s+", "", p.strip(), flags=re.I).strip(" .")
        if not p:
            continue
        qty = ""
        if m := QTY.match(p):
            n = NUMBER_WORDS.get(m.group("n").lower(), m.group("n"))
            qty = f"{n} {m.group('unit')}" if m.group("unit") else n
            p = m.group("item")
        p = FILLER.sub("", p).strip(" .")[:60]
        if p and key(p):
            out.append((p, qty))
    return out


class Groceries(Part):
    name = "groceries"

    def __init__(self, store=None, clock=time.time, idle=lambda: 0.0, cooking=None):
        super().__init__(store, clock)
        self.idle, self.cooking = idle, cooking
        self._schema(SCHEMA)

    # ----- the list -----
    def items(self, open_only: bool = False) -> list[dict]:
        where = "WHERE done = 0" if open_only else ""
        rows = self._rows(f"SELECT * FROM groceries {where} ORDER BY done, id")
        order = {s: i for i, s in enumerate(SECTIONS)}
        return sorted(rows, key=lambda r: (r["done"], order.get(r["section"], 99), r["id"]))

    def get_one(self, gid) -> dict | None:
        rows = self._rows("SELECT * FROM groceries WHERE id = ?", (int(gid),))
        return rows[0] if rows else None

    def find(self, said: str, open_only: bool = True) -> dict | None:
        k = key(said)
        if not k:
            return None
        rows = self.items(open_only)
        for r in rows:
            if key(r["item"]) == k:
                return r
        for r in rows:                       # "the milk" for "oat milk", "tomatoes" for "cherry tomatoes"
            rk = key(r["item"])
            if re.search(rf"\b{re.escape(k)}\b", rk) or re.search(rf"\b{re.escape(rk)}\b", k):
                return r
        return None

    def add(self, text: str, who: str = "you") -> list[dict]:
        """Every item in `text` (comma / 'and' separated); one already on the list gets its quantity
        updated instead of a second row."""
        out = []
        for item, qty in split_items(text):
            have = self.find(item)
            if have is not None:
                if qty and qty != have["qty"]:
                    self._exec("UPDATE groceries SET qty = ? WHERE id = ?", (qty, have["id"]))
                out.append(self.get_one(have["id"]))
                continue
            cur = self._exec("INSERT INTO groceries (item, qty, section, who, added) VALUES (?,?,?,?,?)",
                             (item, qty, section_for(item), who, self.now().isoformat(timespec="minutes")))
            out.append(self.get_one(cur.lastrowid))
        if not out:
            raise ValueError("what should go on the grocery list?")
        self.put("skipped", {k: v for k, v in self.get("skipped", {}).items() if k not in {key(i["item"]) for i in out}})
        return out

    def check(self, gid, done: bool = True) -> dict | None:
        g = self.get_one(gid)
        if g is None:
            return None
        if done and not g["done"]:
            self._exec("INSERT INTO grocery_bought (item, day) VALUES (?, ?)", (g["item"].lower(), self.today()))
        elif not done and g["done"]:          # unticked: that purchase didn't happen
            self._exec("DELETE FROM grocery_bought WHERE id = (SELECT MAX(id) FROM grocery_bought WHERE item = ? AND day = ?)",
                       (g["item"].lower(), self.today()))
        self._exec("UPDATE groceries SET done = ?, done_at = ? WHERE id = ?",
                   (1 if done else 0, self.now().isoformat(timespec="minutes") if done else "", g["id"]))
        return self.get_one(g["id"])

    def remove(self, gid) -> dict | None:
        g = self.get_one(gid)
        if g is not None:
            self._exec("DELETE FROM groceries WHERE id = ?", (g["id"],))
        return g

    def clear(self, which: str = "done") -> int:
        cur = self._exec("DELETE FROM groceries" + (" WHERE done = 1" if which == "done" else ""))
        return cur.rowcount

    # ----- what you might need -----
    def _skipped(self) -> set[str]:
        cutoff = (self.now() - dt.timedelta(days=SKIP_DAYS)).date().isoformat()
        return {k for k, day in self.get("skipped", {}).items() if day >= cutoff}

    def skip(self, items: list[str]):
        s = self.get("skipped", {})
        for i in items:
            s[key(i)] = self.today()
        self.put("skipped", s)

    def suggestions(self, n: int = 5) -> list[dict]:
        """[{item, why}]: running low (bought before, usual gap passed), goes with what's on the list,
        the recipe being cooked, then staples while there's little history."""
        on_list = {key(r["item"]) for r in self.items(open_only=True)}
        skip = self._skipped() | on_list
        today = self.now().date()
        out: list[dict] = []

        def offer(item: str, why: str):
            k = key(item)
            if k and k not in skip and all(key(o["item"]) != k for o in out):
                out.append({"item": item, "why": why})

        bought: dict[str, list[dt.date]] = {}          # the name as last bought -> the days
        named: dict[str, str] = {}
        for r in self._rows("SELECT item, day FROM grocery_bought ORDER BY day, id"):
            named[key(r["item"])] = r["item"]
        for r in self._rows("SELECT item, day FROM grocery_bought ORDER BY day, id"):
            days = bought.setdefault(named[key(r["item"])], [])
            d = dt.date.fromisoformat(r["day"])
            if not days or days[-1] != d:
                days.append(d)
        due = []
        for item, days in bought.items():
            if len(days) < 2:
                continue
            gap = statistics.median((b - a).days for a, b in zip(days, days[1:]))
            since = (today - days[-1]).days
            if gap >= 2 and since >= 0.85 * gap:
                due.append((since / gap, item, round(gap)))
        for _, item, gap in sorted(due, reverse=True):
            offer(item, f"you usually get it every {gap} days" if gap < 14 else f"about every {round(gap / 7)} weeks")
        for r in self.items(open_only=True):
            k = key(r["item"])
            for base, extras in PAIRS.items():
                if re.search(rf"\b{re.escape(key(base))}\b", k):
                    for e in extras:
                        offer(e, f"goes with the {r['item']}")
        s = self.cooking.session() if self.cooking is not None else None
        for ing in (s or {}).get("ingredients", [])[:12]:
            for item, _ in split_items(re.sub(r"\(.*?\)", "", ing))[:1]:
                offer(item, f"for the {s.get('title', 'recipe')}")
        if len(bought) < 6:
            recent = {k for k, days in bought.items() if (today - days[-1]).days < 10}
            for st in STAPLES:
                if key(st) not in recent:
                    offer(st, "a staple")
        return out[:n]

    def offer(self, items: list[str]):
        """She just asked about these: the next answer ("yes, the eggs", "no") is about them."""
        self.put("offered", {"t": self.clock(), "items": items})

    def offered(self) -> list[str]:
        o = self.get("offered")
        return o["items"] if o and self.clock() - o["t"] <= OFFER_S else []

    def answer(self, text: str) -> tuple[list[dict], list[str]] | None:
        """Their answer to her "need any of these?": (added, dropped), or None if it isn't one."""
        offered = self.offered()
        if not offered:
            return None
        named = [o for o in offered if re.search(rf"\b{re.escape(key(o))}", key(text))]
        if NO.search(text) and not named:
            self.skip(offered)
            self.put("offered", None)
            return [], offered
        if not named and not YES.search(text):
            return None
        take = named or offered
        if re.search(r"\b(?:just|only)\b", text, re.I) and named:
            take = named
        added = self.add(", ".join(take), who="her")
        self.skip([o for o in offered if o not in take])
        self.put("offered", None)
        return added, [o for o in offered if o not in take]

    # ----- what's about to go off -----
    @staticmethod
    def shelf_life(item: str) -> int:
        if NOT_FRESH.search(item):
            return 0
        words = key(item).split()
        if not words:
            return 0
        return SHELF.get(words[-1]) or next((SHELF[w] for w in words if w in SHELF), 0)

    def going_off(self) -> list[dict]:
        """Fresh things bought lately that are about to turn (or just did): [{id, item, day, age, life}]."""
        if self.store is None:
            return []
        today = self.now().date()
        since = (today - dt.timedelta(days=30)).isoformat()
        rows = self._rows("SELECT id, item, day FROM grocery_bought WHERE day >= ? ORDER BY day, id", (since,))
        gone = set(self.get("used", {}))
        latest: dict[str, dict] = {}
        for r in rows:
            latest[key(r["item"])] = r                 # bought again since: only the newest counts
        out = []
        for r in latest.values():
            life = self.shelf_life(r["item"])
            if not life or str(r["id"]) in gone:
                continue
            age = (today - dt.date.fromisoformat(r["day"])).days
            if life - 1 <= age <= life + 2:
                out.append({"id": r["id"], "item": r["item"], "day": r["day"], "age": age, "life": life})
        return sorted(out, key=lambda x: x["age"] - x["life"], reverse=True)

    def used_up(self, text: str) -> list[str]:
        """"I finished the milk" / "the spinach is still fine": stop counting those."""
        said = [key(i) for i, _ in split_items(text)]
        marked = self.get("used", {})
        names = []
        for g in self.going_off() + self._recent_bought():
            k = key(g["item"])
            if any(s and (s == k or re.search(rf"\b{re.escape(s)}\b", k) or re.search(rf"\b{re.escape(k)}\b", s)) for s in said):
                if str(g["id"]) not in marked:
                    marked[str(g["id"])] = self.today()
                    names.append(g["item"])
        cutoff = (self.now().date() - dt.timedelta(days=40)).isoformat()
        self.put("used", {k: v for k, v in marked.items() if v >= cutoff})
        return names

    def _recent_bought(self) -> list[dict]:
        since = (self.now().date() - dt.timedelta(days=14)).isoformat()
        return [r for r in self._rows("SELECT id, item, day FROM grocery_bought WHERE day >= ?", (since,))
                if self.shelf_life(r["item"])]

    def use_tonight(self, item: str) -> str | None:
        """A dish from the recipe box that uses it."""
        box = getattr(self.cooking, "box", None) if self.cooking is not None else None
        if box is None:
            return None
        k = key(item).split()[-1]
        for r in box.all():
            if any(re.search(rf"\b{re.escape(k)}", key(i)) for i in r["ingredients"]):
                return r["title"]
        return None

    def shopping(self) -> bool:
        return self.clock() - (self.get("shopping") or 0) <= SHOP_S

    # ----- words -----
    @staticmethod
    def _label(r: dict) -> str:
        return f"{r['qty']} {r['item']}" if r["qty"] else r["item"]

    def spoken(self, by_section: bool = False) -> str:
        items = self.items(open_only=True)
        if not items:
            return "The grocery list is empty."
        if not by_section:
            return f"On the grocery list ({len(items)}): " + ", ".join(self._label(r) for r in items) + "."
        parts = []
        for s in SECTIONS:
            here = [self._label(r) for r in items if r["section"] == s]
            if here:
                parts.append(f"{s.lower()}: {', '.join(here)}")
        return "; ".join(parts) + "."

    def ask_line(self, ideas: list[dict]) -> str:
        if not ideas:
            return ""
        names = [i["item"] for i in ideas[:4]]
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" or {names[-1]}"
        return f"Do you need {listed}?"

    # ----- in conversation -----
    def route(self, user_text: str, last_reply: str = "") -> tuple[str, dict] | None:
        t = user_text.strip()
        offered = self.offered()
        if offered and not G_ADD.search(t) and not G_DROP.search(t):
            named = any(re.search(rf"\b{re.escape(key(o))}", key(t)) for o in offered)
            asked = any(re.search(rf"\b{re.escape(key(o))}", key(last_reply)) for o in offered)
            if named or (asked and (YES.search(t) or NO.search(t))):    # a bare "yes" only right after her question
                return "grocery_answer", {"text": t}
        if G_RECIPE.search(t):
            return "add_groceries", {"items": "__recipe__"}
        if m := G_DROP.search(t):
            return "remove_groceries", {"items": m.group("what")}
        if G_CLEAR.search(t):
            return "clear_groceries", {"which": "all"}
        if m := G_ADD.search(t):
            what = m.group("what") or m.group("what2") or m.group("what3")
            # "I'm out of ideas / time": only things a shop sells count when no list was named
            if m.group("what3") is None or all(section_for(i) != "Other" for i, _ in split_items(what) or [("", "")]):
                return "add_groceries", {"items": what.strip()}
        if G_DONE.search(t) and (self.shopping() or self.items()):
            return "done_shopping", {}
        if G_SHOP.search(t):
            return "grocery_shopping", {}
        if G_IDEAS.search(t) and (self.shopping() or self.items(open_only=True) or re.search(r"grocer|shop|store|buy", t, re.I)):
            return "grocery_ideas", {}
        if G_SHOW.search(t):
            return "grocery_list", {}
        if (m := USED.search(t)):
            what = (m.group("what") or m.group("what2") or "").strip()
            if what and any(key(g["item"]).split()[-1] in key(what) or key(what) in key(g["item"])
                            for g in self.going_off() + self._recent_bought()):
                return "groceries_used", {"items": what}
        if self.shopping() and (m := G_GOT.match(t)):
            what = m.group("what") or m.group("what2")
            if what and self.find(what) is not None:
                return "check_groceries", {"items": what}
        return None

    def moments(self, now: float) -> list[Moment]:
        """A weekend afternoon, when a few things are probably running low: she asks first (once a week).
        An evening when something fresh is about to go off: she says so (once a day)."""
        if self.store is None:
            return []
        d = dt.datetime.fromtimestamp(now)
        off = self._off_moment(d)
        if off is not None:
            return [off]
        if d.weekday() < 5 or not 11 <= d.hour < 18 or self.idle() > 120:
            return []
        week = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
        if self.done(f"ask:{week}"):
            return []
        low = [s for s in self.suggestions(4) if s["why"].startswith(("you usually", "about every"))]
        if len(low) < 2:
            return []
        names = ", ".join(s["item"] for s in low)
        return [Moment("groceries", f"From what {{user}} usually buys, they're probably running low on: {names}. Ask "
                                    "casually if they need any of it (you can add it to the grocery list). One line, "
                                    "name the items exactly, nothing else.", key=f"ask:{week}", part=self.name)]

    def _off_moment(self, d: dt.datetime) -> Moment | None:
        if not 16 <= d.hour < 20 or self.idle() > 120 or self.done(f"off:{d.date().isoformat()}"):
            return None
        told = set(self.get("told", []))
        items = [g for g in self.going_off() if str(g["id"]) not in told][:3]
        if not items:
            return None

        def when(g):
            day = dt.date.fromisoformat(g["day"])
            return "yesterday" if g["age"] == 1 else f"on {day:%A}" if g["age"] < 7 else f"{g['age']} days ago"

        what = "; ".join(f"{g['item']} (bought {when(g)}, usually good for about {g['life']} days)" for g in items)
        dish = next((x for x in (self.use_tonight(g["item"]) for g in items) if x), None)
        extra = f" You two have cooked {dish} before and it uses it: suggest that." if dish else ""
        return Moment("groceries", f"From the grocery list you know {{user}} bought: {what}. It's probably about to go "
                                   f"off. Mention it casually and suggest using it tonight.{extra} One line, name the "
                                   "items exactly, don't guess anything else.",
                      key=f"off:{d.date().isoformat()}", part=self.name)

    def used(self, moment, now: float):
        if moment.key.startswith("off:"):
            self.put("told", ([*self.get("told", []), *(str(g["id"]) for g in self.going_off()[:3])])[-100:])
        super().used(moment, now)
        if moment.key.startswith("ask:"):
            self.offer([s["item"] for s in self.suggestions(4) if s["why"].startswith(("you usually", "about every"))])

    def status(self) -> dict:
        return {"items": [{"id": r["id"], "item": r["item"], "qty": r["qty"], "section": r["section"],
                           "done": bool(r["done"]), "who": r["who"]} for r in self.items()],
                "sections": SECTIONS, "ideas": self.suggestions(6), "shopping": self.shopping(),
                "going_off": [{"id": g["id"], "item": g["item"], "age": g["age"], "life": g["life"]} for g in self.going_off()]}
