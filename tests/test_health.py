"""Watch health (health.py) and screen-time nudges (screentime.py)."""
import datetime as dt
import random
from types import SimpleNamespace

from sanae.health import Health
from sanae.screentime import ScreenTime, hours
from sanae.tools import health as health_tools
from sanae.tools.registry import ToolRegistry
from test_sanae import api_client, memory_store

NOW = dt.datetime(2026, 10, 18, 8, 30)


def make_health():
    return Health(memory_store(), clock=lambda: NOW)


def test_rows_merge_and_sleep_in_words():
    h = make_health()
    for i, mins in enumerate([450, 470, 440, 460]):
        h.save({"day": (NOW.date() - dt.timedelta(days=4 - i)).isoformat(), "sleep_min": mins})
    h.save({"day": "2026-10-18", "sleep_min": 340, "sleep_start": "2026-10-18T02:10:00", "sleep_end": "2026-10-18T07:50:00"})
    h.save({"day": "2026-10-18", "steps": 2400})                      # steps later: the sleep stays
    assert h.today().sleep_min == 340 and h.today().steps == 2400
    assert h.sleep_sentence() == "You slept 5 hours 40 minutes, 2:10 AM to 7:50 AM (less than your usual 7 hours 35 minutes)."
    assert h.save({"day": "not a day"}) is None
    assert h.answer("steps") == "2,400 steps today so far."
    h.save({"day": "2026-10-18", "resting_hr": 58, "hr": 72, "hr_at": "2026-10-18T08:12:00"})
    assert h.answer("heart") == "Resting heart rate 58. Last heart rate reading: 72 bpm at 08:12."
    h.save({"day": "2026-10-18", "resting_hr": 54, "resting_est": True})       # the phone's estimate
    assert h.answer("heart").startswith("Resting heart rate about 54 (worked out from your readings).")
    h.save({"day": "2026-10-18", "steps": 2600})                                # other fields later: still estimated
    assert h.today().resting_est == 1
    h.save({"day": "2026-10-18", "resting_hr": 57})                             # a measured one replaces it
    assert h.today().resting_est == 0 and h.answer("heart").startswith("Resting heart rate 57.")


def test_nothing_yet():
    h = make_health()
    assert h.sleep_sentence() == ""
    assert h.answer("sleep").startswith("I don't have last night's sleep yet")
    assert h.answer("heart") == "No heart rate readings yet."


def test_api_privacy_and_briefing():
    client, rt = api_client()
    rt.ctx.health = Health(rt.ctx.memory)
    today = dt.date.today().isoformat()
    out = client.post("/api/health", json={"days": [{"day": today, "sleep_min": 420, "steps": 5000}, {"day": "x"}]}).json()
    assert out == {"saved": [today]}
    assert client.get("/api/health").json()[0]["steps"] == 5000
    from sanae.briefing import Briefing

    assert "You slept 7 hours." in Briefing(rt.ctx, {}).sentences()
    from sanae.privacy import Privacy

    p = Privacy(rt.ctx) if "ctx" in Privacy.__init__.__code__.co_varnames else None
    if p is not None:
        assert any(c["id"] == "health" for c in p.categories())
        p.delete("health")
        assert client.get("/api/health").json() == []


def test_heart_rate_from_the_watch():
    h = make_health()
    answers = {"r": {"ok": True, "message": "73 bpm", "bpm": 73}}
    phone = SimpleNamespace(request=lambda action, params, timeout=None: answers["r"])
    reg = ToolRegistry(context=SimpleNamespace(health=h, phone=phone))
    health_tools.register(reg)
    assert reg.run("heart_rate_now", {}) == "Your heart rate is 73 bpm right now."
    answers["r"] = {"ok": False, "message": "The watch didn't answer."}
    assert reg.run("heart_rate_now", {}).startswith("The watch didn't answer. Last heart rate reading: 73 bpm")
    from sanae.agent import direct_route

    tools = {"health_today": 1, "heart_rate_now": 1}
    assert direct_route("what's my heart rate?", tools) == ("heart_rate_now", {})
    assert direct_route("what was my resting heart rate today?", tools) == ("health_today", {"what": "heart"})
    assert direct_route("how did I sleep?", tools) == ("health_today", {"what": "sleep"})
    assert direct_route("how many steps today?", tools) == ("health_today", {"what": "steps"})
    assert direct_route("go to sleep", tools) is None


def test_screen_time_nudges():
    clock = {"t": 0.0}
    state = {"idle": 0.0, "game": False}
    said = []
    st = ScreenTime(lambda: state["idle"], lambda: state["game"], lambda kind, m, text: said.append((kind, m, text)),
                    clock=lambda: clock["t"], rng=random.Random(1))

    def run(minutes):
        for _ in range(int(minutes * 2)):
            clock["t"] += 30
            st.tick()

    state["game"] = True
    run(119)
    assert said == []
    run(2)
    assert said[0][0] == "gaming" and said[0][1] == 120 and "2 hours" in said[0][2]
    run(50)
    assert len(said) == 1                                    # next one an hour later
    run(11)
    assert len(said) == 2 and said[1][0] == "gaming"
    state["game"] = False                                     # stopped gaming, still on the laptop (3h+ total)
    run(1)
    assert said[-1][0] == "laptop" and said[-1][1] >= 180
    state["idle"] = 3600                                      # away for 15 min: the stretch resets
    run(15)
    state["idle"] = 0
    run(170)
    assert said[-1][0] == "laptop" and len([s for s in said if s[0] == "laptop"]) == 1
    run(15)
    assert said[-1][0] == "laptop" and said[-1][1] == 180
    assert hours(200) == "3 hours and 20 minutes" and hours(60) == "an hour" and hours(45) == "45 minutes"
