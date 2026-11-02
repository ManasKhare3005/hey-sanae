import datetime as dt

from sanae.conversation import grounded_summary
from sanae.timesense import TimeFilter, fix, greeting_note, part_of_day, stamp

AT = dt.datetime(2026, 10, 19, 13, 10)


def test_wrong_greetings_are_swapped():
    assert fix("[happy][wave] Good morning, Alex!", AT) == "[happy][wave] Good afternoon, Alex!"
    assert fix("Morning, Alex! How's it going?", AT.replace(hour=20)) == "Hey, Alex! How's it going?"
    assert fix("Good morning!", AT.replace(hour=1)) == "Hey!"
    assert fix("Rise and shine!", AT.replace(hour=15)) == "Hey there!"
    assert fix("Good night!", AT) == "See you later!"
    assert fix("Have a good night, okay?", AT) == "Have a good day, okay?"


def test_fitting_greetings_and_other_uses_stay():
    assert fix("Good morning!", AT.replace(hour=9)) == "Good morning!"
    assert fix("Have a good night, okay?", AT.replace(hour=19)) == "Have a good night, okay?"
    assert fix("Good night!", AT.replace(hour=23)) == "Good night!"
    assert fix("You said this morning was rough.", AT) == "You said this morning was rough."
    assert fix("Morning classes are the worst.", AT) == "Morning classes are the worst."


def test_stream_never_speaks_a_wrong_greeting():
    out = []
    f = TimeFilter(out.append, lambda: AT)
    for piece in ["[happy] Go", "od mor", "ning, Al", "ex! This mor", "ning was fun. Mor", "ning!"]:
        f(piece)
    f(None)
    text = "".join(p for p in out if p)
    assert text == "[happy] Good afternoon, Alex! This morning was fun. Hey!"
    assert out[-1] is None


def test_stamp_and_note():
    assert stamp(AT) == "Mon Oct 19 2026, 1:10 PM (afternoon)"
    assert part_of_day(6) == "early morning" and part_of_day(22) == "night"
    note = greeting_note(AT)
    assert "good afternoon" in note and "never good morning" in note


def test_summary_drops_made_up_clock_times():
    turns = [[{"role": "user", "content": "[Mon Oct 19 2026, 11:20 AM (morning)] remind me at 9 pm to call mom"},
              {"role": "assistant", "content": "[happy] Done, 9 PM it is."}]]
    summary = "Sanae checks in at 8:15 AM. Alex wants a reminder at 9 PM to call his mom."
    assert grounded_summary(summary, turns) == "Alex wants a reminder at 9 PM to call his mom."


def test_lock_and_sleep_go_straight_to_their_tools():
    # from the phone the model answered "Locked and loaded!" / "Sleeping mode activated!" without calling anything
    from sanae.agent import direct_route

    tools = {"lock_screen": 1, "power": 1, "free_gpu": 1}
    assert direct_route("Can you lock my laptop?", tools) == ("lock_screen", {})
    assert direct_route("can you put my laptop to sleep please", tools) == ("power", {"action": "sleep"})
    assert direct_route("shut down my computer", tools) == ("power", {"action": "shutdown"})
    assert direct_route("how do I lock my laptop?", tools) is None
    assert direct_route("go to sleep", tools) is None                  # that's free_gpu (the model decides)
    assert direct_route("put my phone to sleep", tools) is None
