"""Routines (routines.py): matching the phrase, running the steps, risky steps still ask."""
from types import SimpleNamespace

import yaml

from sanae.routines import Routines, parse
from sanae.tools import routine as routine_tools
from sanae.tools.registry import DECLINED, ToolRegistry

CONFIG = """
- name: goodnight
  say: ["goodnight", "good night", "i'm going to bed"]
  steps:
    - say: "Goodnight! Tucking everything in."
    - {tool: media_control, args: {action: stop}, quiet: true}
    - {tool: list_events, args: {day: tomorrow}}
    - {tool: broken}
    - {tool: lock_screen, quiet: true}
    - "Sleep well."
- name: study time
  say: ["study time", "time to study"]
  steps:
    - {tool: close_app, args: {name: discord}, if_running: Discord.exe}
    - {tool: start_study, args: {minutes: 50}}
- {name: nameless}
- "not a routine"
"""


def make(running=False, answer=True):
    calls, asked = [], []
    ctx = SimpleNamespace(confirm=lambda p: asked.append(p) or answer, bus=None)
    ctx.routines = Routines(parse(yaml.safe_load(CONFIG)), running=lambda exe: running)
    reg = ToolRegistry(context=ctx)

    @reg.tool("stop music", params={"action": {"type": "string"}})
    def media_control(action: str):
        calls.append(("media", action))
        return "Stopped."

    @reg.tool("events", params={"day": {"type": "string"}})
    def list_events(day: str = ""):
        calls.append(("events", day))
        return "On your calendar tomorrow: Study group, tomorrow at 3 PM."

    @reg.tool("broken", params={})
    def broken():
        raise RuntimeError("boom")

    @reg.tool("lock", params={})
    def lock_screen():
        calls.append(("lock",))
        return "Locked."

    @reg.tool("close", params={"name": {"type": "string"}}, risky=True, confirm="Close {name}?")
    def close_app(name: str):
        calls.append(("close", name))
        return f"Closed {name}."

    @reg.tool("study", params={"minutes": {"type": "number"}})
    def start_study(minutes: float = 60):
        calls.append(("study", minutes))
        return f"Okay, {int(minutes)} minutes. Let's go."

    routine_tools.register(reg)
    return reg, ctx, calls, asked


def test_phrases_match_on_their_own():
    _, ctx, _, _ = make()
    r = ctx.routines
    assert [x.name for x in r.items] == ["goodnight", "study time", "nameless"]     # bad entries skipped
    for text in ("Goodnight!", "good night", "okay, goodnight Sanae", "I'm going to bed now.", "alright, study time!",
                 "it's study time", "Time to study."):
        assert r.match(text), text
    for text in ("say goodnight to mom", "what time is study time?", "i'm going to bed late tonight", "study"):
        assert r.match(text) is None, text


def test_goodnight_runs_every_step_and_skips_failures():
    reg, ctx, calls, asked = make()
    said = reg.run("run_routine", {"name": "goodnight"})
    assert calls == [("media", "stop"), ("events", "tomorrow"), ("lock",)]          # the broken step didn't stop it
    assert said == ("Goodnight! Tucking everything in. On your calendar tomorrow: Study group, tomorrow at 3 PM. "
                    "Sleep well.")
    assert asked == []


def test_risky_steps_still_ask():
    reg, ctx, calls, asked = make(running=True, answer=False)
    said = reg.run("run_routine", {"name": "study time"})
    assert asked == ["Close discord?"] and ("close", "discord") not in calls
    assert said == "Skipped: close discord. Okay, 50 minutes. Let's go."
    reg, ctx, calls, asked = make(running=False)
    reg.run("run_routine", {"name": "study time"})
    assert asked == [] and calls == [("study", 50)]                 # Discord not open: no question at all
    assert reg.run("run_routine", {"name": "dance party"}).startswith("Error")


def test_routines_skip_the_model():
    from sanae.agent import Agent

    reg, ctx, calls, asked = make()

    class NoLLM:
        def chat(self, *a, **k):
            raise AssertionError("the model shouldn't be asked")

    agent = Agent(NoLLM(), reg, "fast", "planner")
    reply = agent.handle("okay, goodnight!")
    assert reply.startswith("Goodnight! Tucking everything in.") and ("lock",) in calls
    assert agent.last_tools == ["run_routine"]


def test_starter_routines_in_config_are_valid():
    from sanae.config import load_config

    cfg = load_config()
    items = parse((cfg.get("routines") or {}).get("list"))
    assert [r.name for r in items] == ["goodnight", "study time", "gaming time"]
    tools = {s.tool for r in items for s in r.steps if s.tool}
    assert tools <= {"media_control", "list_events", "quiet_for", "lock_screen", "close_app", "start_study",
                     "open_app", "free_gpu"}
