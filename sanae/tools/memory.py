"""Memory, reminder and calendar tools: remember / recall / forget, set / list / cancel reminders,
add / list / cancel events (Sanae's calendar, which the phone shows as its "Sanae" calendar)."""
from __future__ import annotations

import datetime as dt
import re
import time

from ..reminders import Reminders, has_time, parse_repeating, parse_when, spoken_time
from .registry import DECLINED, ToolRegistry

DAY_WORDS = {"today": 0, "yesterday": 1}


def register(reg: ToolRegistry):
    ctx = reg.context
    store = getattr(ctx, "memory", None)
    if store is None:
        return
    reminders: Reminders = ctx.reminders

    def tell_phone(kind: str, **data):            # the phone copies the change on its next sync
        bus = getattr(ctx, "bus", None)
        if bus is not None:
            bus.publish(kind, data)

    @reg.tool(
        "Save a fact about the user for later, when they say 'remember ...' (e.g. 'my exam is on "
        "Friday', 'my sister's name is Maya'). Write it as a short standalone sentence.",
        params={"fact": {"type": "string", "description": "e.g. 'Alex's CS 101 exam is on Friday, October 2'"}},
        direct=True,
    )
    def remember(fact: str):
        _, old = store.add_fact(fact)
        return "Got it, I've updated that." if old else "Got it, I'll remember that."

    @reg.tool(
        "Look up what you know or what was said before: saved facts, past conversations and "
        "reminders. Use for 'when is my exam', 'what did I ask you yesterday', 'what's my sister's name'.",
        params={"query": {"type": "string", "description": "What to look up"}},
    )
    def recall(query: str):
        lines = []
        facts = store.search_facts(query, k=5, min_score=0.5)
        if facts:
            lines.append("Saved facts: " + "; ".join(f.text for f in facts))
        day = next((d for w, d in DAY_WORDS.items() if re.search(rf"\b{w}\b", query, re.I)), None)
        if day is not None:
            start = (dt.date.today() - dt.timedelta(days=day)).isoformat()
            end = (dt.date.today() - dt.timedelta(days=day - 1)).isoformat()
            turns = store.turns_between(start, end)[-8:]
            if turns:
                lines.append("Conversations that day: " + " | ".join(f"{t['ts'][11:16]} you: {t['user']}" for t in turns))
        else:
            past = store.search_turns(query, k=4, min_score=0.6)
            if past:
                lines.append("Past conversations: " + " | ".join(f"{h.ts[:16].replace('T', ' ')} {h.text}" for h in past))
        rems = [r for r in reminders.pending()]
        if rems:
            lines.append("Pending reminders: " + "; ".join(f"{r.text} ({r.spoken()})" for r in rems[:5]))
        if not lines:
            return "Nothing saved about that."
        return "\n".join(lines) + "\n\nAnswer in one or two short sentences from this."

    @reg.tool(
        "Delete a saved fact when the user asks you to forget something. This tool is the only way "
        "to forget; it asks the user to confirm first.",
        params={"what": {"type": "string", "description": "Which fact, e.g. 'my exam date'"}},
        direct=True,
    )
    def forget(what: str):
        hits = store.search_facts(what, k=1, min_score=0.5)
        if not hits:
            return "I don't have anything saved about that."
        fact = hits[0]
        if not ctx.confirm(f"Forget that {fact.text}?"):
            return DECLINED
        store.delete_fact(fact.id)
        return "Forgotten."

    @reg.tool(
        "Set a reminder. You will say it out loud and show a notification at that time. It can repeat "
        "('every month on the 5th', 'every Monday at 8am', 'daily at 9pm'). For 'the day before X' or "
        "similar, work out the actual date yourself.",
        params={
            "text": {"type": "string", "description": "What to remind about, e.g. 'CS 101 exam'"},
            "when": {"type": "string", "description": "e.g. 'Friday 9am', 'tomorrow morning', 'in 2 hours', "
                     "'2026-10-02T09:00', or for a repeating one 'the 5th of every month', 'every Monday at 8am'"},
            "repeat": {"type": "string", "enum": ["", "daily", "weekdays", "weekly", "monthly", "yearly"],
                       "description": "How often it repeats; leave empty for a one-time reminder"},
        },
        required=["text", "when"],
        direct=True,
    )
    def set_reminder(text: str, when: str, repeat: str = ""):
        rule = ""
        found = parse_repeating(when, repeat or "")
        if found:
            due, rule = found
        else:
            due = parse_when(when)
        if due is None:
            return (f"Error: '{when}' isn't a time I can read. Call set_reminder again with a form like "
                    "'Friday 9am', 'November 5 at 9am', '2026-11-05T09:00', or for a repeating reminder "
                    "'the 5th of every month', 'every Monday at 8am'. Only ask the user if you don't know the day.")
        if due <= dt.datetime.now():
            return f"Error: {spoken_time(due)} is in the past. Ask the user for a future time."
        r = reminders.add(text, due, repeat=rule)
        tell_phone("reminder", action="added", uid=r.uid, text=r.text, due=due.isoformat(), repeat=rule)
        if rule:
            return f"Okay, I'll remind you {r.spoken()}: {text}."
        return f"Okay, I'll remind you {spoken_time(due)}: {text}."

    @reg.tool("List the pending reminders.", params={}, direct=True)
    def list_reminders():
        items = reminders.pending()
        if not items:
            return "You don't have any reminders."
        parts = [f"{r.text}, {r.spoken()}" for r in items[:5]]
        more = f", and {len(items) - 5} more" if len(items) > 5 else ""
        return f"You have {len(items)} reminder{'s' if len(items) != 1 else ''}: " + "; ".join(parts) + more + "."

    @reg.tool(
        "Cancel a pending reminder.",
        params={"which": {"type": "string", "description": "Which reminder, e.g. 'the exam one'"}},
        direct=True,
    )
    def cancel_reminder(which: str):
        r = reminders.find(which)
        if r is None:
            return "You don't have any reminders."
        reminders.set_status(r.id, "cancelled")
        tell_phone("reminder", action="cancelled", uid=r.uid)
        return f"Cancelled the {'repeating ' if r.repeat else ''}reminder: {r.text}."

    todos = getattr(ctx, "todos", None)
    if todos is not None:
        from ..todos import split_items

        @reg.tool(
            "Add things to the user's todo list (no time, no alarm: 'add milk to my list', 'put finish the "
            "lab report on my todo list'). Several items can be comma-separated. (Something to say at a "
            "time is set_reminder.)",
            params={"items": {"type": "string", "description": "e.g. 'milk, eggs, call the landlord'"}},
            direct=True,
        )
        def add_todo(items: str):
            added = [todos.add(text) for text in split_items(items)]
            if not added:
                return "Error: nothing to add. Pass the items."
            tell_phone("todo", action="added", uids=[t.uid for t in added])
            names = [t.text for t in added]
            listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
            return f"Added to your list: {listed}. That's {len(todos.open())} open."

        @reg.tool(
            "Read the user's todo list ('what's on my list?', 'what do I still need to do?').",
            params={},
            required=[],
            direct=True,
        )
        def list_todos():
            return todos.spoken()

        @reg.tool(
            "Tick off an item on the todo list when the user says it's done ('I bought the milk', 'check off laundry').",
            params={"which": {"type": "string", "description": "Which item, e.g. 'milk'"}},
            direct=True,
        )
        def check_todo(which: str):
            t = todos.find(which)
            if t is None:
                return "Your todo list is empty."
            todos.set_status(t.uid, "done")
            tell_phone("todo", action="done", uid=t.uid)
            left = len(todos.open())
            return f"Ticked off: {t.text}. " + (f"{left} left." if left else "That was the last one!")

        @reg.tool(
            "Remove items from the todo list: the ticked ones ('clear the done ones'), one item "
            "('take milk off my list'), or everything ('clear my whole list').",
            params={"which": {"type": "string", "description": "'done', 'all', or the item, e.g. 'milk'"}},
            direct=True,
        )
        def clear_todos(which: str = "done"):
            w = which.strip().lower()
            if w in ("", "done", "ticked", "finished", "completed", "checked"):
                n = todos.clear("done")
                tell_phone("todo", action="cleared", count=n)
                return f"Cleared {n} finished item{'s' if n != 1 else ''}." if n else "Nothing ticked off to clear."
            if w in ("all", "everything", "whole list", "the whole list", "list"):
                n = len(todos.shown())
                if not n:
                    return "Your todo list is already empty."
                confirm = getattr(ctx, "confirm", None)
                if confirm is None or not confirm(f"Clear all {n} item{'s' if n != 1 else ''} from your todo list?"):
                    return DECLINED
                todos.clear("all")
                tell_phone("todo", action="cleared", count=n)
                return f"Cleared your whole list ({n} item{'s' if n != 1 else ''})."
            t = todos.find(which) or todos.find(which, status="done")
            if t is None:
                return "Your todo list is empty."
            todos.set_status(t.uid, "deleted")
            tell_phone("todo", action="deleted", uid=t.uid)
            return f"Took it off your list: {t.text}."

    chores = getattr(ctx, "chores", None)
    if chores is not None:
        _routine_tools(reg, chores, tell_phone)

    events = getattr(ctx, "events", None)
    if events is None:
        return

    @reg.tool(
        "Add an event to the user's calendar (your calendar, also on their phone), e.g. 'add a study "
        "group tomorrow at 3pm', 'put the dentist on my calendar Friday at 10'. No time of day = all day. "
        "(Something you should say out loud at a time is set_reminder instead.)",
        params={"title": {"type": "string"},
                "when": {"type": "string", "description": "Start, e.g. 'tomorrow at 3pm', 'Friday', '2026-10-02T15:00'"},
                "duration_minutes": {"type": "integer", "description": "Default 60"},
                "location": {"type": "string"}},
        required=["title", "when"],
        direct=True,
    )
    def add_event(title: str, when: str, duration_minutes: int = 60, location: str = ""):
        start = parse_when(when)
        if start is None:
            return f"Error: I couldn't understand the time '{when}'. Ask the user when exactly."
        all_day = not has_time(when)
        if (start.date() if all_day else start) < (dt.date.today() if all_day else dt.datetime.now()):
            return f"Error: {when} is in the past. Ask the user for a future time."
        e = events.add(title, start, duration_minutes or 60, location or "", all_day=all_day)
        tell_phone("event", action="added", uid=e.uid)
        return f"Added to your calendar: {e.spoken()}."

    @reg.tool(
        "List calendar events: on a day ('today', 'tomorrow', 'Friday') or, without a day, the next week.",
        params={"day": {"type": "string", "description": "Optional, e.g. 'tomorrow'"}},
        required=[],
        direct=True,
    )
    def list_events(day: str = ""):
        if day.strip():
            when = parse_when(day)
            if when is None:
                return f"Error: I couldn't understand the day '{day}'."
            items, span = events.on(when.date()), ("today" if when.date() == dt.date.today() else
                                                    "tomorrow" if when.date() == dt.date.today() + dt.timedelta(days=1)
                                                    else f"on {when:%A}")
        else:
            items, span = events.upcoming(7), "this coming week"
        if not items:
            return f"Nothing on your calendar {span}."
        return f"On your calendar {span}: " + "; ".join(e.spoken() for e in items[:6]) + (
            f", and {len(items) - 6} more" if len(items) > 6 else "") + "."

    @reg.tool(
        "Remove an event from the user's calendar.",
        params={"which": {"type": "string", "description": "Which event, e.g. 'the dentist'"}},
        direct=True,
    )
    def cancel_event(which: str):
        e = events.find(which)
        if e is None:
            return "There's nothing coming up on your calendar."
        events.cancel(e.uid)
        tell_phone("event", action="cancelled", uid=e.uid)
        return f"Removed from your calendar: {e.spoken()}."


def _routine_tools(reg: ToolRegistry, chores, tell_phone):
    from ..chores import label, parse_freq, valid

    @reg.tool(
        "Add a task to the user's routine: something to do again and again ('water the plants every day', "
        "'laundry every Sunday', 'pay rent on the 1st of every month'). It shows in the morning briefing on the "
        "days it's due, and the phone nags in the evening if it isn't ticked. (A one-off thing is add_todo; "
        "something to say at a time is set_reminder.)",
        params={"task": {"type": "string", "description": "e.g. 'water the plants'"},
                "how_often": {"type": "string", "description": "e.g. 'every day', 'weekdays', 'every Sunday', "
                                                               "'weekly', 'monthly', 'on the 5th of every month'"}},
        direct=True,
    )
    def add_routine_task(task: str, how_often: str):
        freq = how_often.strip() if valid(how_often.strip()) else parse_freq(how_often)
        if not task.strip():
            return "Error: pass the task."
        if not how_often.strip():
            chores.asking = (task.strip(), time.time())
            return (f'How often should I put "{task.strip()}" on your routine: every day, weekdays, a day of the week, '
                    "or once a month?")
        if freq is None:
            return ("Error: I couldn't tell how often from '" + how_often + "'. Retry with one of: 'every day', "
                    "'weekdays', 'every Monday', 'weekly', 'monthly', 'on the 5th of every month'.")
        chores.asking = None
        c = chores.add(task, freq)
        tell_phone("routine", action="added", uid=c.uid)
        return f"Added to your routine: {c.text}, {label(c.freq)}."

    @reg.tool(
        "Read the user's routine: what's due today and what's still left ('what's on my routine today?'), "
        "or every routine task with how often ('what's my whole routine?').",
        params={"which": {"type": "string", "enum": ["today", "all"]}},
        required=[],
        direct=True,
    )
    def routine_today(which: str = "today"):
        return chores.spoken_all() if which == "all" else chores.spoken_today()

    @reg.tool(
        "Tick off (or untick) a routine task for today when the user says they did it ('I watered the plants', "
        "'check off laundry on my routine').",
        params={"which": {"type": "string", "description": "Which task, e.g. 'plants'"},
                "done": {"type": "boolean", "description": "false to untick. Default true"}},
        required=["which"],
        direct=True,
    )
    def check_routine_task(which: str, done: bool = True):
        c = chores.find(which, chores.due()) or chores.find(which)
        if c is None:
            return "Your routine is empty."
        chores.tick(c.uid, done)
        tell_phone("routine", action="done" if done else "reopened", uid=c.uid)
        left = len(chores.left())
        if not done:
            return f"Unticked: {c.text}."
        return f"Ticked off for today: {c.text}. " + (f"{left} left today." if left else "That's everything for today!")

    @reg.tool(
        "Remove a task from the user's routine for good ('take laundry off my routine').",
        params={"which": {"type": "string", "description": "Which task, e.g. 'laundry'"}},
        direct=True,
    )
    def remove_routine_task(which: str):
        c = chores.find(which)
        if c is None:
            return "Your routine is empty."
        chores.delete(c.uid)
        tell_phone("routine", action="deleted", uid=c.uid)
        return f"Took it off your routine: {c.text} ({label(c.freq)})."
