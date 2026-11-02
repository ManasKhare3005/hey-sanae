"""A second look before she speaks first (firstline.py)."""
import datetime as dt
import tempfile
from types import SimpleNamespace

from sanae.cloudbrain import CloudBrain
from sanae.firstline import FirstLineCheck
from sanae.initiative import Moment, model_line

NOW = dt.datetime(2026, 10, 27, 16, 11)


def checker(answer, hard=False):
    sent = []

    def run(system, prompt, schema):
        sent.append(prompt)
        return answer

    brain = CloudBrain({"cloud": True}, "Alex", "Sanae", run=run, folder=tempfile.mkdtemp(), private_now=lambda: hard)
    return FirstLineCheck(brain), sent


def test_keep_rewrite_drop():
    line = "[happy] Hey there! 21 hours? That's a record, how'd you manage that?"
    sit = "Alex just got home (their phone joined the home Wi-Fi) after being out since yesterday."
    keep, sent = checker({"verdict": "keep", "line": "", "reason": "fine"})
    assert keep(line, sit, "", [], NOW) == line
    assert "Now: Tue Oct 27, 4:11 PM (afternoon)" in sent[0] and "the user just got home" in sent[0]
    fix, _ = checker({"verdict": "rewrite", "line": "Welcome home! Long day? Tell the user I missed them.", "reason": "invented 21 hours"})
    assert fix(line, sit, "", [], NOW) == "[happy] Welcome home! Long day? Tell Alex I missed them."    # tag kept, name back
    drop, _ = checker({"verdict": "drop", "line": "", "reason": "nothing real"})
    assert drop(line, sit, "", [], NOW) is None
    hidden, _ = checker({"verdict": "rewrite", "line": "[happy] Did you text a friend about the cat?", "reason": "x"})
    assert hidden(line, sit, "", [], NOW) is None                                   # would need a hidden name back
    long, _ = checker({"verdict": "rewrite", "line": "[happy] " + "word " * 40, "reason": "x"})
    assert long(line, sit, "", [], NOW) is None


def test_private_or_offline_lines_go_out_as_before():
    quiet, sent = checker({"verdict": "drop", "line": "", "reason": ""}, hard=True)
    assert quiet("[sad] I'm here.", "They had a hard night.", "", [], NOW) == "[sad] I'm here." and sent == []
    private, sent = checker({"verdict": "drop", "line": "", "reason": ""})
    assert private("[happy] How was the doctor?", "Their doctor visit was today.", "", [], NOW) == "[happy] How was the doctor?"
    assert sent == []                                                                # too private to send for a check
    assert FirstLineCheck(None)("[happy] hi", "x") == "[happy] hi"


def test_model_line_uses_the_check():
    said = []
    llm = SimpleNamespace(chat=lambda model, messages, **kw: SimpleNamespace(content="[happy] 21 hours? That's a record!"))
    agent = SimpleNamespace(history=[], _system=lambda: {"role": "system", "content": "s"},
                            _recent_history=lambda: [{"role": "user", "content": "good night"},
                                                     {"role": "assistant", "content": "Night!"}])

    def check(line, situation, notes, chat, now):
        said.append((line, chat))
        return "[happy] Welcome home!"

    gen = model_line(agent, llm, "m", "Alex", check=check)
    assert gen(Moment("place", "{user} just got home.")) == "[happy] Welcome home!"
    assert said[0] == ("[happy] 21 hours? That's a record!", ["Them: good night", "Her: Night!"])
    assert agent.history[-1][1]["content"] == "[happy] Welcome home!"               # the checked line is what she said
    gen2 = model_line(agent, llm, "m", "Alex", check=lambda *a: None)
    assert gen2(Moment("place", "{user} just got home.")) is None
