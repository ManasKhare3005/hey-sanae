"""Morning briefing (briefing.py): when it's due, what she says, and "skip"."""
import datetime as dt

from sanae.briefing import ASK, GREETING, Briefing, Weather
from sanae.canvas import CanvasItem
from sanae.speech import interrupt_label
from test_sanae import api_client

DAY = dt.datetime.combine(dt.date.today(), dt.time())
OPEN_METEO = {"current": {"temperature_2m": 68.6, "weather_code": 0},
              "daily": {"temperature_2m_max": [91.2], "temperature_2m_min": [64.0],
                        "precipitation_probability_max": [40], "weather_code": [61]}}


class FakeCanvas:
    def between(self, start, end, kind):
        items = [CanvasItem("class", "CS 101 lecture", "CS 101", DAY.replace(hour=10, minute=30), False),
                 CanvasItem("assignment", "HW 5", "CS 104", DAY.replace(hour=23, minute=59), False),
                 CanvasItem("assignment", "Lab report", "CS 105", DAY + dt.timedelta(days=2, hours=23, minutes=59), False)]
        return [i for i in items if i.kind == kind and start <= i.start < end]


def make(hour=7, weather=True):
    client, rt = api_client()
    clock = {"t": DAY.replace(hour=hour).timestamp()}
    w = Weather(0, 0, fetch=lambda: OPEN_METEO) if weather else None
    b = Briefing(rt.ctx, {"from_hour": 5, "until_hour": 12}, clock=lambda: clock["t"], weather=w)
    rt.ctx.briefing = b
    return b, rt, clock


def test_weather_sentence():
    assert Weather(0, 0, fetch=lambda: OPEN_METEO).sentence() == \
        "It's 69 degrees and clear now, with a high of 91 and a 40% chance of rain."
    dry = {"current": {"temperature_2m": 50, "weather_code": 3},
           "daily": {"temperature_2m_max": [60], "precipitation_probability_max": [10], "weather_code": [95]}}
    assert Weather(0, 0, fetch=lambda: dry).sentence() == "It's 50 degrees and cloudy now, with a high of 60, thunderstorms later."

    def offline():
        raise OSError("no network")
    assert Weather(0, 0, fetch=offline).sentence() == ""


def test_due_once_a_morning():
    b, rt, clock = make(hour=4)
    assert not b.due()                         # before 5 AM
    clock["t"] = DAY.replace(hour=7).timestamp()
    assert b.due()
    b.mark()
    assert not b.due()                         # once a day
    clock["t"] = (DAY + dt.timedelta(days=1, hours=13)).timestamp()
    assert not b.due()                         # afternoon: too late for a morning briefing
    clock["t"] = (DAY + dt.timedelta(days=1, hours=6)).timestamp()
    assert b.due()


def test_what_she_says_and_skip():
    b, rt, clock = make(hour=7)
    rt.ctx.canvas = FakeCanvas()
    rt.ctx.events.add("Study group", DAY.replace(hour=15))
    rt.ctx.events.add("Mom's birthday", DAY, all_day=True)
    rt.ctx.reminders.add("pay rent", DAY.replace(hour=17))
    for t in ("milk", "laundry", "call the landlord", "pay the bill"):
        rt.ctx.todos.add(t)
    said = b.sentences()
    assert said == [
        "It's 69 degrees and clear now, with a high of 91 and a 40% chance of rain.",
        "Class: CS 101 at 10:30 AM.",
        "Due today: HW 5 for CS 104 at 11:59 PM.",
        "First on your calendar: Mom's birthday today, plus 1 more.",
        "Reminders: pay rent at 5 PM.",
        "On your list: milk, laundry, call the landlord and 1 more.",
    ]
    spoken, kept = [], []
    assert b.deliver(lambda s: spoken.append(s), add_said=kept.append) is True
    assert len(spoken) == 7 and not b.due() and kept[0].endswith("and 1 more.")
    spoken.clear()
    cut = lambda s: spoken.append(s) or ("stop" if len(spoken) == 3 else None)
    assert b.deliver(cut, add_said=kept.append) is False and len(spoken) == 3      # "skip" after the class
    assert kept[-1].endswith("(cut short)")
    assert interrupt_label("SKIP") == "stop" and interrupt_label("SKIP_IT") == "stop"


def test_quiet_day_and_no_weather():
    b, rt, clock = make(hour=8, weather=False)
    assert b.sentences() == ["Nothing on the schedule today. A free day!"]
    b, rt, clock = make(hour=8)
    rt.ctx.canvas = FakeCanvas()
    clock["t"] = DAY.replace(hour=11, minute=30).timestamp()       # the 10:30 class is over
    assert not any(s.startswith("Class") for s in b.sentences())


def test_greetings_and_asks():
    for text in ("good morning", "Morning!", "hey", "hey sanae", "what's up", "I'm up"):
        assert GREETING.match(text), text
    for text in ("good morning, what's the weather?", "open spotify", "hey can you open youtube"):
        assert not GREETING.match(text), text
    assert ASK.search("brief me") and ASK.search("give me my morning rundown")
    from sanae.agent import direct_route

    assert direct_route("brief me", {"morning_briefing": 1}) == ("morning_briefing", {})


def test_briefing_and_weather_tools():
    from sanae.tools import digest as digest_tools
    from sanae.tools.registry import ToolRegistry

    b, rt, clock = make(hour=9)
    reg = ToolRegistry(context=rt.ctx)
    digest_tools.register(reg)
    assert reg.run("weather", {}).startswith("It's 69 degrees")
    assert reg.run("morning_briefing", {}).startswith("It's 69 degrees")
    assert not b.due()                        # asked for it: no second one at the next wake


def test_weather_and_day_questions_skip_the_model():
    from sanae.agent import direct_route

    tools = {"morning_briefing": 1, "weather": 1, "day_summary": 1}
    for text in ("what's the weather like?", "is it going to rain today?", "how hot is it outside?", "do I need a jacket?"):
        assert direct_route(text, tools) == ("weather", {}), text
    assert direct_route("what does my day look like?", tools) == ("day_summary", {})
    assert direct_route("what's the weather in Tokyo?", {"day_summary": 1}) is None     # no local weather tool
    assert direct_route("how cold is it in space?", tools) == ("weather", {})           # known: still local


def test_day_summary_mail_wording():
    from types import SimpleNamespace as M

    from sanae.digest import mail_line

    assert mail_line(M(sender="Maya", address="p@x", subject="the trip")) == "Maya about the trip"
    assert mail_line(M(sender="", address="p@x", subject="(no subject)")) == "p@x"
    assert mail_line(M(sender="", address="", subject="Grades posted")) == "one about Grades posted"
    assert mail_line(M(sender="", address="", subject="")) == ""          # was read out as "Important email: ,,."
