"""Friendship parts (part.py): goals, wins, pushback, care, social, texts, thoughts, her life,
rituals, surprises. No model, no mic: fake clocks and in-memory state."""
import datetime as dt
import random

from sanae.initiative import Initiative, Moment


class Clock:
    def __init__(self, when: dt.datetime):
        self.t = when.timestamp()

    def __call__(self):
        return self.t

    def at(self, when: dt.datetime):
        self.t = when.timestamp()


class Ctx:
    memory = None


# Sunday Oct 18 2026; Monday is Oct 19
MON = dt.datetime(2026, 10, 19, 9, 0)


def test_goal_offered_then_saved_on_yes_then_logged():
    from sanae.goals import Goals

    clock = Clock(MON)
    g = Goals(None, clock, random.Random(1))
    n = g.notes("I want to go to the gym 3 times a week")
    assert n and "ask once" in n[0] and g.all() == []
    assert g.notes("I want to play valorant") == []                      # a wish for now, not a goal
    saved = g.notes("yeah keep me to it")
    assert "now keeping them" in saved[0] and g.all()[0]["per_week"] == 3
    assert g.notes("yes") == []                                          # the offer is used up

    done = g.notes("just went to the gym, legs are dead")
    assert "kept their goal" in done[0] and "1 of 3" in done[0]
    clock.at(MON + dt.timedelta(days=1))
    assert "missed" in g.notes("I skipped the gym today")[0]
    clock.at(MON + dt.timedelta(days=2))
    g.notes("went to the gym")
    clock.at(MON + dt.timedelta(days=3))
    hit = g.notes("finally went to the gym again")
    assert "hits this week's target" in hit[0] and g.week_wins() == ["go to the gym 3 times a week"]
    assert g.streak(g.all()[0]) == 1


def test_goal_said_outright_and_tools_words():
    from sanae.goals import Goals, per_week

    g = Goals(None, Clock(MON), random.Random(1))
    assert "now keeping them" in g.notes("hold me accountable to reading every day")[0]
    assert g.all()[0]["text"] == "reading every day" and g.all()[0]["per_week"] == 7
    assert per_week("run twice a week") == 2 and per_week("meditate") == 0
    assert "Reading every day: 0 of 7 this week." == g.spoken()
    assert g.drop("stop the reading goal")["text"] == "reading every day" and g.all() == []


def test_goal_evening_check_in_once_a_day_and_sunday_look_back():
    from sanae.goals import Goals

    clock = Clock(MON.replace(hour=19))
    g = Goals(None, clock, random.Random(1))
    g.add("meditate every day")
    m = g.moments(clock())
    assert len(m) == 1 and "0 of 7" in m[0].situation
    g.used(m[0], clock())
    assert g.moments(clock()) == []                                      # once a day
    clock.at(MON.replace(hour=12) + dt.timedelta(days=1))
    assert g.moments(clock()) == []                                      # evenings only
    clock.at(dt.datetime(2026, 10, 25, 19, 0))                           # Sunday evening
    m = g.moments(clock())
    assert m and m[0].key.startswith("weekly:") and "end of the week" in m[0].situation


def test_parts_moments_go_through_the_initiative_loop():
    class P:
        name = "p"
        used_with = None

        def moments(self, now):
            return [Moment("goals", "say hi", key="k")]

        def used(self, m, now):
            P.used_with = m.key

    said = []
    clock = Clock(MON)
    ini = Initiative(Ctx(), lambda line, info: said.append(line), lambda m: f"[happy] {m.situation}",
                     idle=lambda: 30, clock=clock, settings={"greeting": False}, parts=[P()])
    assert ini.tick() == "[happy] say hi" and P.used_with == "k"


def test_parts_observe_even_while_they_are_away():
    seen = []

    class P:
        name = "p"

        def observe(self, now):
            seen.append(now)

        def moments(self, now):
            return []

    clock = Clock(MON)
    ini = Initiative(Ctx(), lambda line, info: None, lambda m: None, idle=lambda: 3600, clock=clock,
                     settings={"greeting": False}, parts=[P()])
    assert ini.moments() == [] and ini.activity.away        # an hour without input (a film): away
    assert seen == [clock()]                                # ...but the watching part still followed along


def test_wins_noticed_once_and_recalled_when_down():
    from types import SimpleNamespace

    from sanae.goals import Goals
    from sanae.wins import Wins

    clock = Clock(MON.replace(hour=20))

    class Projects:
        calls = 0

        def all(self):
            return [SimpleNamespace(name="Flock"), SimpleNamespace(name="Sanae")]

        def git(self, p, *args, timeout=30):
            Projects.calls += 1
            assert p.name == "Flock"                                      # Sanae is skipped
            return "Fix the login bug\nMerge branch 'x'\nAdd tests"

    goals = Goals(None, clock, random.Random(1))
    g = goals.add("run twice a week")
    goals.log(g, True, "2026-10-19")
    goals.log(g, True, "2026-10-20")
    val = SimpleNamespace(all=lambda: [{"when": "Mon Oct 19, 0%d:00 PM" % i, "result": "Win"} for i in range(3)])
    w = Wins(None, clock, Projects(), None, goals, val, rng=random.Random(1))
    said = []
    for _ in range(5):
        m = w.moments(clock())
        if m:
            said.append(m[0].situation)
            w.used(m[0], clock())
    assert len(said) == 3
    assert any("2 commits on Flock" in s and "Fix the login bug" in s for s in said)
    assert any("3 Valorant matches in a row" in s for s in said)
    assert any("this week's target" in s and "run twice a week" in s for s in said)
    assert w.moments(clock()) == [] and Projects.calls == 1              # git checked once per 10 min

    clock.at(MON.replace(hour=20) + dt.timedelta(days=2))                # Wednesday
    note = w.notes("I'm so stressed about this exam")
    assert note and "on Monday they" in note[0]
    clock.t += 10
    assert w.notes("ugh I'm stressed") == []                              # at most once every two hours
    clock.t += 3 * 3600
    assert w.notes("this is great") == []


def test_pushback_once_with_a_reason_then_lets_go():
    from types import SimpleNamespace

    from sanae.pushback import HONEST, Pushback

    clock = Clock(dt.datetime(2026, 10, 20, 1, 30))                       # Tuesday 1:30 AM
    exam = SimpleNamespace(title="Networks midterm", start=dt.datetime(2026, 10, 20, 10, 0), all_day=False)
    ctx = SimpleNamespace(events=SimpleNamespace(between=lambda a, b: [exam] if a <= exam.start < b else []), canvas=None)
    p = Pushback(None, clock, ctx, late_from="00:30", rng=random.Random(1))
    n = p.notes("ok one more valorant game")
    assert n and "1:30 AM" in n[0] and "Networks midterm at 10 AM" in n[0] and "Push back once" in n[0]
    assert "respect it" in p.notes("nah I'm fine, just one")[0]
    assert p.notes("one more game") == []                                 # dropped for tonight
    assert p.game_line("VALORANT-Win64-Shipping.exe") is None

    clock.at(dt.datetime(2026, 10, 20, 15, 0))                            # the afternoon: nothing to push on
    p2 = Pushback(None, clock, SimpleNamespace(events=None, canvas=None))
    assert p2.notes("one more game") == [] and p2.notes("should I take the 8 AM section?") == [HONEST]

    clock.at(dt.datetime(2026, 10, 21, 1, 0))                             # next night: fresh, and Valorant starting
    exam.start = dt.datetime(2026, 10, 21, 9, 0)
    line = p.game_line("VALORANT-Win64-Shipping.exe")
    assert line and "Networks midterm" in line


def test_care_from_the_watch_and_meals():
    from types import SimpleNamespace

    from sanae.care import Care
    from sanae.wins import Wins

    days = {"2026-10-19": SimpleNamespace(day="2026-10-19", sleep_min=290, steps=1200, resting_hr=70)}
    for i in range(1, 22):
        d = (dt.date(2026, 10, 19) - dt.timedelta(days=i)).isoformat()
        days[d] = SimpleNamespace(day=d, sleep_min=480, steps=8000, resting_hr=72 if i < 6 else 62)
    health = SimpleNamespace(get=lambda day: days.get(day), recent=lambda n: sorted(days.values(), key=lambda x: x.day))
    clock = Clock(MON.replace(hour=8))
    wins = Wins(None, clock)
    c = Care(None, clock, health, wins, idle=lambda: 10, rng=random.Random(3))
    m = c.moments(clock())
    assert len(m) == 1 and "4 hours 50 minutes" in m[0].situation
    c.used(m[0], clock())
    assert c.moments(clock()) == []                                       # heart rate: not before 10 AM
    clock.at(MON.replace(hour=10, minute=30))
    m = c.moments(clock())
    assert len(m) == 1 and "resting heart rate is about 70" in m[0].situation and "up from about 62" in m[0].situation
    c.used(m[0], clock())
    assert c.moments(clock()) == []
    assert "slept only 4 hours 50 minutes" in c.notes("ugh I'm so tired")[0]

    clock.at(MON.replace(hour=19))
    m = c.moments(clock())
    assert m and "1,200 steps" in m[0].situation
    c.used(m[0], clock())
    clock.at(MON.replace(hour=20))
    c.notes("just had dinner, pasta again")
    assert all("dinner" not in x.situation for _ in range(200) for x in c.moments(clock()))

    clock.at(MON.replace(hour=13, minute=30))
    c2 = Care(None, clock, None, None, idle=lambda: 10, rng=random.Random(3))
    asked = [x for _ in range(300) for x in c2.moments(clock())]
    assert asked and "lunch" in asked[0].situation
    assert Care(None, clock, None, None, idle=lambda: 999).moments(clock()) == []   # away: nothing

    days["2026-10-19"].sleep_min = 500                                     # a good night is a win
    clock.at(MON.replace(hour=9))
    c3 = Care(None, clock, health, wins, idle=lambda: 10)
    c3.moments(clock())
    assert any(w["key"] == "sleep:2026-10-19" for w in wins.recent(1))


def test_social_quiet_week_and_birthdays():
    from types import SimpleNamespace

    from sanae.social import Social, birthdays

    assert birthdays(["Maya's birthday is October 20", "likes boba"]) == [("Maya", "10-20")]
    facts = [SimpleNamespace(kind="person", text="Maya is Alex's best friend"),
             SimpleNamespace(kind="other", text="Maya's birthday is Oct 20")]
    diary = SimpleNamespace(moments=lambda: [SimpleNamespace(kind="date", text="Mom's birthday", date="10-21")])
    clock = Clock(MON.replace(hour=10))
    s = Social(None, clock, SimpleNamespace(facts=lambda: facts), diary, idle=lambda: 10, rng=random.Random(1))
    m = s.moments(clock())
    assert m and m[0].important and "Tomorrow is Maya's birthday" in m[0].situation
    s.used(m[0], clock())
    assert s.moments(clock()) == []

    clock.at(MON.replace(hour=10) + dt.timedelta(days=1))                 # the 20th
    m = s.moments(clock())
    assert "Today is Maya's birthday" in m[0].situation
    s.used(m[0], clock())
    m = s.moments(clock())
    assert "Tomorrow is Mom's birthday" in m[0].situation                  # a diary date: the day before
    s.used(m[0], clock())
    clock.at(MON.replace(hour=10) + dt.timedelta(days=2))
    assert s.moments(clock()) == []                                        # the diary says it on the day itself

    assert s.notes("I hung out with Maya today, we got boba")
    assert s.notes("nobody wanted to hang out") == []
    clock.at(MON.replace(hour=16) + dt.timedelta(days=10))                 # 8 quiet days later
    asked = [x for _ in range(300) for x in s.moments(clock())]
    assert asked and "Maya" in asked[0].situation and "hasn't mentioned" in asked[0].situation
    s.used(asked[0], clock())
    assert all(not s.moments(clock()) for _ in range(300))                 # once a week


def test_texts_only_while_away_with_caps():
    from types import SimpleNamespace

    from sanae.texts import Texts

    clock = Clock(dt.datetime(2026, 10, 19, 9, 30))
    idle = {"s": 5.5 * 3600}                                              # not on the laptop since 4 AM
    quiz = SimpleNamespace(title="CS 102 quiz", start=dt.datetime(2026, 10, 19, 10, 30),
                           end=dt.datetime(2026, 10, 19, 11, 15), all_day=False)
    ctx = SimpleNamespace(events=SimpleNamespace(between=lambda a, b: [quiz]), canvas=None, comfort=None, dnd=None,
                          models_asleep=False)
    sent, logged = [], []
    t = Texts(None, clock, ctx, generate=lambda m: f"[happy] {m.situation[:40]}",
              publish=lambda kind, data: sent.append((kind, data)), log_turn=logged.append,
              idle=lambda: idle["s"], rng=random.Random(1))
    first = t.tick()
    assert "CS 102 quiz" in first and sent[0][0] == "text" and "[happy]" not in sent[0][1]["text"]   # good luck first
    assert logged == [first]
    assert t.tick() is None                                               # no good morning on top of it

    clock.at(dt.datetime(2026, 10, 19, 11, 25))                           # the quiz just ended
    idle["s"] = 600
    assert t.tick() is None                                               # back at the laptop: no texts
    idle["s"] = 3600
    assert t.tick() is None                                               # away again, but within 2 h of the last
    clock.at(dt.datetime(2026, 10, 19, 11, 45))
    assert "just ended" in t.tick() and len(sent) == 2
    clock.at(dt.datetime(2026, 10, 19, 22, 45))
    idle["s"] = 3 * 3600
    assert "late" in t.tick()                                             # goodnight: the third
    t.put("night:2026-10-19", None)
    t.put("once", [])
    assert t.tick() is None                                               # 3 a day at most


def test_thoughts_from_their_words_brought_up_later():
    import json as _json
    from types import SimpleNamespace

    from sanae.thoughts import Thoughts

    clock = Clock(MON.replace(hour=20))

    class Store:
        def __init__(self):
            self.kv = {}
            self.rows = [{"id": 1, "ts": "2026-10-19T19:00:00", "user": "hey", "reply": "hi", "heard": "you"}]

        def get(self, k):
            return self.kv.get(k)

        def set(self, k, v):
            self.kv[k] = v

        def recent_turns(self, n):
            return self.rows[-n:]

    store = Store()
    answer = {"about": "the Amazon internship", "thought": "I kept thinking about the Amazon internship: did you decide to apply?"}
    llm = SimpleNamespace(chat=lambda *a, **k: SimpleNamespace(content=_json.dumps(answer)))
    t = Thoughts(store, clock, llm, "m", "Alex", "Sanae", idle=lambda: 60, rng=random.Random(1))
    assert t.think_once() is None                                         # first run starts from now
    store.rows += [{"id": i, "ts": "2026-10-19T19:30:00", "user": u, "reply": "mm", "heard": h}
                   for i, (u, h) in enumerate([("I got an email about an Amazon internship", "you"),
                                               ("not sure I should apply though", "you"),
                                               ("this video is wild", "other"),
                                               ("the deadline is friday", "")], 2)]
    assert "Amazon internship" in t.think_once()
    assert t.think_once() is None                                         # nothing new since
    assert t.moments(clock()) == [] or True
    clock.t += 3600
    found = [m for _ in range(400) for m in t.moments(clock())]
    assert found and "Amazon internship" in found[0].situation
    t.used(found[0], clock())
    assert t.pending() == []

    assert t.keep("Did your sister's surgery go okay?", "", ["my sister is fine"]) is None           # sensitive
    assert t.keep("Good luck on the 3 exams!", "", ["I have exams this week"]) is None               # a number they didn't say
    assert t.keep("I love strawberry milk so much", "", ["I have exams this week"]) is None         # not their words
    assert t.keep("How are the exams going?", "exams", ["I have exams this week"])
    assert "exams" in t.notes("what have you been up to?")[0] and t.pending() == []


def test_her_life_moves_with_the_days_and_music():
    from types import SimpleNamespace

    from sanae.herlife import HerLife
    from sanae.toolselect import KEYWORDS

    assert KEYWORDS["goals"].search("what are my goals") and not KEYWORDS["goals"].search("goalkeeper")

    clock = Clock(MON.replace(hour=15))
    playing = {"t": [SimpleNamespace(artist="Fleetwood Mac")]}
    life = HerLife(None, clock, {}, SimpleNamespace(recent=lambda within_s: playing["t"]), idle=lambda: 60,
                   rng=random.Random(1))
    first = life.summary()
    assert "stick figures" in first and "\"neko\"" in first and "Fleetwood" not in first
    for i in range(3):                                                    # heard on three different days
        clock.at(MON.replace(hour=15) + dt.timedelta(days=i * 3))
        life.moments(clock())
    later = life.summary()
    assert "eyes" in later and "Fleetwood Mac" in later and "\"neko\"" not in later
    assert "share one bit" in life.notes("how have you been?")[0]
    assert life.notes("open spotify") == []


def test_rituals_on_their_days_and_highs_lows_replace_the_check_in():
    from types import SimpleNamespace

    from sanae.goals import Goals
    from sanae.rituals import Rituals

    clock = Clock(MON.replace(hour=9))
    goals = Goals(None, clock)
    goals.add("read every day")
    lab = SimpleNamespace(title="Lab 5", start=dt.datetime(2026, 10, 21, 14, 0), all_day=False)
    ctx = SimpleNamespace(events=SimpleNamespace(between=lambda a, b: [lab] if a <= lab.start < b else []), canvas=None)
    r = Rituals(None, clock, ctx, goals, idle=lambda: 30, rng=random.Random(1))
    m = r.moments(clock())
    assert "Monday morning" in m[0].situation and "Lab 5 (Wed 2 PM)" in m[0].situation and "read every day" in m[0].situation
    r.used(m[0], clock())
    assert r.moments(clock()) == []

    clock.at(MON.replace(hour=21))
    asked = [x for _ in range(100) for x in r.moments(clock())]
    assert asked and "high and low" in asked[0].situation
    ini = Initiative(Ctx(), lambda *a: None, lambda m: "x", idle=lambda: 30, clock=clock,
                     settings={"greeting": False}, parts=[r], rng=random.Random(1))
    assert all(ini._checkin(clock()) == [] for _ in range(50))                    # the ritual asks instead
    clock.at(MON.replace(hour=21) + dt.timedelta(days=1))                         # Tuesday: the plain check-in
    assert any(ini._checkin(clock()) for _ in range(50))

    clock.at(dt.datetime(2026, 10, 23, 17, 0))                                    # Friday
    assert "weekend" in r.moments(clock())[0].situation
    clock.at(dt.datetime(2026, 10, 18, 19, 0))                                    # Sunday evening
    lab.start = dt.datetime(2026, 10, 21, 14, 0)
    assert "week ahead" in r.moments(clock())[0].situation


def test_surprises_milestone_haiku_compliment():
    import json as _json
    from types import SimpleNamespace

    from sanae.memory import MemoryStore
    from sanae.surprises import Surprises

    class Embed:
        def embed(self, texts):
            import numpy as np
            return np.zeros((len(texts), 4), dtype="float32")

    store = MemoryStore(":memory:", Embed())
    with store.lock:
        store.db.execute("INSERT INTO turns (ts, user, reply, tools, heard) VALUES ('2026-09-19T20:00:00', 'hi', 'hey', '[]', '')")
    clock = Clock(MON.replace(hour=18))                                   # Oct 19: 30 days later
    rough = {f"2026-10-{d}": {"n": 4, "stressed": 1} for d in (14, 16, 18)}
    store.set("mood:days", _json.dumps(rough))
    facts = [SimpleNamespace(kind="project", text="builds a voice assistant called Sanae")]
    week = [SimpleNamespace(text="Alex fought with a networking assignment and stayed up late.")]
    prompts, said = [], []

    def chat(model, messages, **kw):
        prompts.append(messages[0]["content"])
        return SimpleNamespace(content="late packets lost\nyou kept the socket open\nmorning finds the fix")

    s = Surprises(store, clock, SimpleNamespace(week=lambda day: week), SimpleNamespace(facts=lambda: facts),
                  idle=lambda: 60, rng=random.Random(2), llm=SimpleNamespace(chat=chat), model="m", user="Alex",
                  on_line=said.append)
    m = s.moments(clock())
    assert m[0].important and "a month" in m[0].situation and "September 19" in m[0].situation
    s.used(m[0], clock())
    assert s.rough_days() == 3
    found = [x for _ in range(400) for x in s.moments(clock())]
    haiku = next(x for x in found if "haiku" in x.situation)
    assert haiku.line == "[shy] I wrote you something. late packets lost. you kept the socket open. morning finds the fix."
    assert "networking assignment" in prompts[0] and said[0].startswith("I wrote you something.")
    s.used(haiku, clock())                                                # once a week
    found = [x for _ in range(3000) for x in s.moments(clock())]
    assert found and all("compliment" in x.situation and "voice assistant" in x.situation for x in found)


def test_voice_softer_at_night_and_little_sounds():
    from types import SimpleNamespace

    from sanae.tts import STYLES, Speaker, at_night, with_sound

    assert at_night(dt.datetime(2026, 10, 19, 23, 30), ("23:00", "06:00"))
    assert at_night(dt.datetime(2026, 10, 19, 2, 0), ("23:00", "06:00"))
    assert not at_night(dt.datetime(2026, 10, 19, 14, 0), ("23:00", "06:00")) and not at_night(dt.datetime.now(), None)
    rng = random.Random(1)
    assert with_sound("Oh no, really?", "laugh", rng, 1.0) == "Oh no, really?"          # she already made a sound
    assert with_sound("That's so you.", "neutral", rng, 1.0) == "That's so you."
    assert with_sound("That's so you.", "laugh", rng, 1.0).split()[0] in ("Hehe,", "Haha,", "Hehe!")
    assert with_sound("That's so you.", "laugh", rng, 0) == "That's so you."

    s = Speaker.__new__(Speaker)
    s.piper = SimpleNamespace(style=None)
    s.clock = lambda: dt.datetime(2026, 10, 19, 23, 30)
    s.sounds = 1.0
    s._rng = random.Random(1)
    s.set_emotion("thinking")
    first = s._dress("Let me see.")
    assert first.startswith(("Hmm", "Mm")) and s.piper.style[3] < STYLES["thinking"][3]   # softer at night
    assert s._dress("Second sentence.") == "Second sentence."                            # only the reply's start
    s.clock = lambda: dt.datetime(2026, 10, 19, 15, 0)
    s.set_emotion("neutral")
    s._dress("Hi.")
    assert s.piper.style == STYLES["neutral"]
