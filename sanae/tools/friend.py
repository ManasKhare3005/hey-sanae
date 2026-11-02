"""Goals she keeps the user to (goals.py). Talking about a goal in passing works without these
(she offers, a yes saves it); the tools are for asking outright."""
from __future__ import annotations

from .registry import ToolRegistry


def register(reg: ToolRegistry):
    ctx = reg.context

    def goals():
        return getattr(ctx, "goals", None)

    @reg.tool("The user's goals that you keep them to, with this week's progress: 'what are my goals?', "
              "'how am I doing on my goals?'.", params={}, direct=True)
    def list_goals():
        g = goals()
        return g.spoken() if g is not None else "Goals are turned off."

    @reg.tool("Save a goal to keep the user to, when they ask you to hold them accountable ('my goal is to read "
              "every day, keep me to it').",
              params={"goal": {"type": "string", "description": "The goal in a few words, e.g. 'go to the gym 3 times a week'"},
                      "times_per_week": {"type": "integer", "description": "7 for every day; 0 if no rhythm"}},
              required=["goal"], direct=True)
    def add_goal(goal: str, times_per_week: int | None = None):
        g = goals()
        if g is None:
            return "Goals are turned off."
        saved = g.add(goal, times_per_week)
        return f"Okay, I'll keep you to it: {saved['text']}."

    @reg.tool("Mark a goal done for today, when the user says they did it ('I went to the gym').",
              params={"goal": {"type": "string", "description": "Which goal, in their words"}},
              required=["goal"], direct=True)
    def goal_done(goal: str):
        g = goals()
        found = g.find(goal) if g is not None else None
        if found is None:
            return "I couldn't tell which goal that was."
        found = g.log(found, True)
        return f"Nice, {found['text']}: {g.progress(found)}."

    @reg.tool("Stop keeping the user to a goal, when they say 'drop my reading goal', 'I'm done with that goal'.",
              params={"goal": {"type": "string", "description": "Which goal, in their words"}},
              required=["goal"], direct=True)
    def drop_goal(goal: str):
        g = goals()
        found = g.drop(goal) if g is not None else None
        return f"Okay, I've let go of {found['text']}." if found else "I couldn't tell which goal that was."

    # ----- the daily list you do together (together.py) -----
    def together():
        return getattr(ctx, "together", None)

    @reg.tool("The user's daily list that you do together (things they want to do each day, e.g. reading, water, "
              "Duolingo), with what's done today: 'what's on my daily list?', 'what's left today?'.",
              params={}, direct=True)
    def list_activities():
        t = together()
        if t is None:
            return "The daily list is turned off."
        items = t.all()
        if not items:
            return "Your daily list is empty. Tell me something you want to do every day and I'll add it."
        d = t.now().date()
        left = [a["title"] for a in items if t.due(a, d) and t.how(a, d.isoformat()) is None]
        done = [a["title"] for a in items if t.how(a, d.isoformat()) not in (None,)]
        parts = []
        if done:
            parts.append(f"Done today: {', '.join(done)}.")
        parts.append(f"Still to do: {', '.join(left)}." if left else "Everything for today is done.")
        return " ".join(parts)

    @reg.tool("Add something to the user's daily list that you do together ('add reading 20 minutes to my daily list', "
              "'I want to drink 2 litres of water every day, add it').",
              params={"title": {"type": "string", "description": "What, in a few words, e.g. 'read 20 minutes'"},
                      "days": {"type": "string", "description": "'every day', 'weekdays', 'mon wed fri' or '3 times a week'"},
                      "time": {"type": "string", "description": "Optional time of day, 24h HH:MM, e.g. '21:00'"},
                      "why": {"type": "string", "description": "Why it matters to them, if they said"}},
              required=["title"], direct=True)
    def add_activity(title: str, days: str = "every day", time: str = "", why: str = ""):
        t = together()
        if t is None:
            return "The daily list is turned off."
        from ..together import days_words, parse_days

        a = t.add(title, why=why, days=parse_days(days), at=time)
        return f"Added {a['title']} to our daily list, {days_words(a['days'])}."

    @reg.tool("Tick something on the daily list as done today ('did my reading', 'mark water done').",
              params={"title": {"type": "string", "description": "Which one, in their words"}},
              required=["title"], direct=True)
    def activity_done(title: str):
        t = together()
        a = t.find(title) if t is not None else None
        if a is None:
            return "I couldn't tell which one that was."
        t.log(a, how="said")
        st = t.streak(a)
        return f"Ticked {a['title']}" + (f", that's {st} days in a row." if st >= 2 else ".")

    @reg.tool("Take something off the daily list ('remove water from my daily list').",
              params={"title": {"type": "string", "description": "Which one, in their words"}},
              required=["title"], direct=True)
    def drop_activity(title: str):
        t = together()
        a = t.find(title) if t is not None else None
        if a is None:
            return "I couldn't tell which one that was."
        t.remove(a["id"])
        return f"Okay, {a['title']} is off our list."

    # ----- pinky promises (promises.py) -----
    @reg.tool("Open pinky promises between you and the user (theirs and yours): 'what did I promise you?', "
              "'any promises?'.", params={}, direct=True)
    def list_promises():
        p = getattr(ctx, "promises", None)
        if p is None:
            return "Promises are turned off."
        items = p.open()
        if not items:
            return "No open pinky promises right now."
        mine = [x["text"] for x in items if x["who"] == "her"]
        theirs = [x["text"] for x in items if x["who"] == "you"]
        parts = []
        if theirs:
            parts.append("You promised to " + "; ".join(theirs) + ".")
        if mine:
            parts.append("I promised to " + "; ".join(mine) + ".")
        return " ".join(parts)
