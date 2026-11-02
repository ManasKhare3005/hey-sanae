"""Her slow brain (cloudbrain.py): what may leave the laptop, the log, the daily limit."""
import json

from sanae.cloudbrain import CloudBrain, Redactor


def test_private_things_stay_private():
    r = Redactor("Alex", "Sanae", people=lambda: ["Maya"])
    text = ("Alex started his new job today and loved it. His doctor changed his medication. "
            "He had dinner with Maya and texted Nina. Call me at +1 480 555 0199 or alex@example.com. "
            "My card ends 4111222233334444. See https://liveten01.com/lease?id=9")
    out = r.clean(text)
    assert "doctor" not in out and "medication" not in out                  # health sentence dropped
    assert "Maya" not in out and "Nina" not in out and out.count("a friend") == 2
    assert "Alex" not in out and out.startswith("the user started")
    assert "555" not in out and "@" not in out and "4111" not in out and "liveten01" not in out
    assert r.clean("My bank password is hunter2.") is None                  # nothing safe left
    assert r.back("Ask the user's plans; the user likes short replies") == "Ask Alex's plans; Alex likes short replies"
    assert "Monday" in r.clean("I met Monday with the team.")               # not a name


def test_ask_logs_limits_and_stays_quiet_in_hard_moments(tmp_path):
    calls, hard = [], [False]

    def run(system, prompt, schema):
        calls.append(prompt)
        return {"ok": True}

    b = CloudBrain({"cloud": True, "daily_calls": 2}, "Alex", run=run, folder=tmp_path,
                   private_now=lambda: hard[0], clock=lambda: 1793170000.0)
    assert b.available
    assert b.ask("reflect", "sys", "hello", {}) == {"ok": True}
    hard[0] = True
    assert b.ask("reflect", "sys", "hello", {}) is None and len(calls) == 1   # comfort mode: nothing goes out
    hard[0] = False
    b.ask("reflect", "sys", "two", {})
    assert b.ask("reflect", "sys", "three", {}) is None and len(calls) == 2  # daily limit
    logged = [json.loads(l) for l in next(tmp_path.glob("sent-*.jsonl")).read_text(encoding="utf-8").splitlines()]
    assert [e["sent"]["prompt"] for e in logged] == ["hello", "two"] and logged[0]["got"] == {"ok": True}
    assert b.recent(1)[0]["sent"]["prompt"] == "two"
    off = CloudBrain({"cloud": False}, run=run, folder=tmp_path)
    assert not off.available and off.ask("reflect", "s", "p", {}) is None


def test_a_failing_claude_is_just_local(tmp_path):
    def run(system, prompt, schema):
        raise RuntimeError("not logged in")

    b = CloudBrain({"cloud": True}, run=run, folder=tmp_path)
    assert b.ask("check", "s", "p", {}) is None and "not logged in" in b.status()["error"]
