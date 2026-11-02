"""Our recipe box: every dish you two cooked together, kept with how it turned out.

  - Finishing a cooking walkthrough (cooking.py), or stopping after most of the steps, saves the
    recipe (the same dish again just counts another time).
  - "Make that pasta again" / "let's cook the fried rice again" uses the saved recipe (no new one
    written), so it comes out the way you liked it.
  - Stars: when she asks how it turned out, your answer ("so good", "kinda burnt") sets them; or
    "give the fried rice 5 stars"; or tap the stars on the phone (Us -> Kitchen).
  - "What have we cooked?" lists them, favourites first. The meal plan (meals.py) picks from here.
  - A photo of a restaurant meal ("can we make this at home?") becomes her home version, saved here
    uncooked with where it came from (cooking.py recreate()).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, dish TEXT NOT NULL DEFAULT '', ingredients TEXT NOT NULL,
    steps TEXT NOT NULL, cooked INTEGER NOT NULL DEFAULT 0, stars INTEGER NOT NULL DEFAULT 0,
    last_cooked TEXT NOT NULL DEFAULT '', added TEXT NOT NULL);
"""
STOP_WORDS = {"a", "an", "the", "easy", "simple", "quick", "homemade", "classic", "my", "our", "style", "with", "and",
              "recipe", "again", "that", "this", "same", "one", "some", "of"}
LOVED = re.compile(r"\b(so good|amazing|loved it|love(d)? (it|this)|delicious|perfect|incredible|best|fire|bomb|"
                   r"10/10|chef'?s kiss|banger|really good|super good|yum+y?)\b", re.I)
GOOD = re.compile(r"\b(good|great|nice|tasty|pretty good|not bad|turned out (well|fine|good)|it worked|worked out)\b", re.I)
MEH = re.compile(r"\b(okay|ok|fine|meh|alright|decent|edible|could be better|so[- ]so)\b", re.I)
BAD = re.compile(r"\b(bad|burn(t|ed)|gross|awful|terrible|disaster|ruined|didn'?t (turn out|work)|inedible|too salty|"
                 r"bland|raw|undercooked|overcooked|failed)\b", re.I)
STARS = re.compile(r"\b(?P<n>[1-5]|one|two|three|four|five)\s*(?:/\s*5|out of 5|out of five|stars?)\b", re.I)
NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def words(title: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z]+", title.lower()):
        if w in STOP_WORDS:
            continue
        out.add(w[:-1] if w.endswith("s") and len(w) > 3 and not w.endswith("ss") else w)
    return out


def stars_in(text: str) -> int:
    """'5 stars' / 'so good' / 'kinda burnt' -> 1-5, or 0 if it doesn't say."""
    if m := STARS.search(text):
        n = m.group("n").lower()
        return int(n) if n.isdigit() else NUM[n]
    if BAD.search(text) and not re.search(r"\bnot (that |too )?bad\b", text, re.I):
        return 2
    if LOVED.search(text):
        return 5
    if MEH.search(text):
        return 3
    if GOOD.search(text):
        return 4
    return 0


class RecipeBox:
    def __init__(self, store=None, clock=time.time):
        self.store, self.clock = store, clock
        if store is not None and hasattr(store, "db"):
            with store.lock:
                store.db.executescript(SCHEMA)
                store.db.commit()

        if store is not None and hasattr(store, "db"):
            with store.lock:
                if "source" not in {r[1] for r in store.db.execute("PRAGMA table_info(recipes)")}:
                    store.db.execute("ALTER TABLE recipes ADD COLUMN source TEXT NOT NULL DEFAULT ''")
                    store.db.commit()

    def _rows(self, sql: str, args=()) -> list[dict]:
        if self.store is None:
            return []
        with self.store.lock:
            return [dict(r) for r in self.store.db.execute(sql, args).fetchall()]

    def _exec(self, sql: str, args=()):
        with self.store.lock:
            cur = self.store.db.execute(sql, args)
            self.store.db.commit()
            return cur

    @staticmethod
    def _out(r: dict) -> dict:
        return {**r, "ingredients": json.loads(r["ingredients"]), "steps": json.loads(r["steps"])}

    def all(self) -> list[dict]:
        rows = self._rows("SELECT * FROM recipes")
        return [self._out(r) for r in sorted(rows, key=lambda r: (-r["stars"], -r["cooked"], r["title"].lower()))]

    def get_one(self, rid) -> dict | None:
        rows = self._rows("SELECT * FROM recipes WHERE id = ?", (int(rid),))
        return self._out(rows[0]) if rows else None

    def find(self, text: str) -> dict | None:
        """The saved recipe this names ('the fried rice', 'pancakes'), or None."""
        want = words(text)
        if not want:
            return None
        best, score = None, 0.0
        for r in self.all():
            have = words(r["title"]) | words(r["dish"])
            if not have:
                continue
            s = len(want & have) / len(want)
            if s > score or (s == score and best is not None and r["last_cooked"] > best["last_cooked"]):
                best, score = r, s
        return best if score >= 0.6 else None

    def last(self) -> dict | None:
        rows = self._rows("SELECT * FROM recipes WHERE last_cooked != '' ORDER BY last_cooked DESC, id DESC LIMIT 1")
        return self._out(rows[0]) if rows else None

    def save(self, session: dict) -> dict | None:
        """A walkthrough that's done (or mostly done): kept, or counted again."""
        if self.store is None or not session.get("steps"):
            return None
        now = dt.datetime.fromtimestamp(self.clock()).isoformat(timespec="minutes")
        same = self.get_one(session["recipe_id"]) if session.get("recipe_id") else None
        if same is None:
            mine = words(session["title"])
            same = next((r for r in self.all() if words(r["title"]) == mine and mine), None)
        if same is not None:
            self._exec("UPDATE recipes SET cooked = cooked + 1, last_cooked = ? WHERE id = ?", (now, same["id"]))
            return self.get_one(same["id"])
        cur = self._exec("INSERT INTO recipes (title, dish, ingredients, steps, cooked, last_cooked, added) VALUES (?,?,?,?,1,?,?)",
                         (session["title"], session.get("dish", ""), json.dumps(session.get("ingredients", [])),
                          json.dumps(session["steps"]), now, now))
        return self.get_one(cur.lastrowid)

    def add(self, recipe: dict, source: str = "") -> dict | None:
        """A recipe not cooked yet (her home version of a restaurant dish)."""
        if self.store is None or not recipe.get("steps"):
            return None
        mine = words(recipe["title"])
        same = next((r for r in self.all() if words(r["title"]) == mine and mine), None)
        if same is not None:
            return same
        now = dt.datetime.fromtimestamp(self.clock()).isoformat(timespec="minutes")
        cur = self._exec("INSERT INTO recipes (title, dish, ingredients, steps, cooked, last_cooked, added, source) "
                         "VALUES (?,?,?,?,0,'',?,?)", (recipe["title"], recipe.get("dish", ""), json.dumps(recipe.get("ingredients", [])),
                                                       json.dumps(recipe["steps"]), now, source[:80]))
        return self.get_one(cur.lastrowid)

    def rate(self, rid, stars: int) -> dict | None:
        r = self.get_one(rid)
        if r is None:
            return None
        self._exec("UPDATE recipes SET stars = ? WHERE id = ?", (max(0, min(5, int(stars))), r["id"]))
        return self.get_one(r["id"])

    def remove(self, rid) -> dict | None:
        r = self.get_one(rid)
        if r is not None:
            self._exec("DELETE FROM recipes WHERE id = ?", (r["id"],))
        return r

    def spoken(self) -> str:
        rs = self.all()
        if not rs:
            return "Our recipe box is empty. Let's cook something together and it'll be the first one!"

        def one(r):
            bits = [f"{r['stars']} stars"] if r["stars"] else []
            if r["cooked"] > 1:
                bits.append(f"made {r['cooked']} times")
            elif not r["cooked"] and r.get("source"):
                bits.append(f"not made yet, {r['source']}")
            return r["title"] + (f" ({', '.join(bits)})" if bits else "")

        return f"In our recipe box ({len(rs)}): " + "; ".join(one(r) for r in rs[:8]) + "."

    def status(self) -> list[dict]:
        return [{"id": r["id"], "title": r["title"], "stars": r["stars"], "cooked": r["cooked"],
                 "last": r["last_cooked"][:10], "ingredients": r["ingredients"], "source": r.get("source", "")}
                for r in self.all()[:40]]
