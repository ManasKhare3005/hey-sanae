"""Tests run anywhere: no mic, GPU, Ollama or Windows needed."""
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from sanae.agent import Agent, parse_yes_no, strip_thinking
from sanae.audio import FRAME, NoiseFloor, record_utterance
from sanae.config import Section, load_config
from sanae.llm import ChatReply, ToolCall
from sanae.main import Context
from sanae.tools import system as system_tools
from sanae.tools.registry import DECLINED, ToolRegistry
from sanae.tools.system import best_match
from sanae.tts import clean_for_speech


class FakeLLM:
    """Replays scripted replies and records what it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, model, messages, tools=None):
        self.calls.append({"model": model, "messages": [dict(m) for m in messages],
                           "tools": [t["function"]["name"] for t in tools or []]})
        return self.replies.pop(0)

    def unload(self, model):
        self.unloaded = getattr(self, "unloaded", []) + [model]


def make_registry(tmp_path, llm=None):
    cfg = load_config()
    cfg["notes"] = {"file": str(tmp_path / "notes.md")}
    reg = ToolRegistry(context=Context(Section(cfg), llm))
    system_tools.register(reg)
    return reg


def make_agent(reg, llm, confirm=lambda p: False, events=None):
    return Agent(llm, reg, "fast", "planner", confirm=confirm,
                 on_event=(lambda k, d: events.append((k, d))) if events is not None else None)


# ---------- parsing ----------

@pytest.mark.parametrize("text,expected", [
    ("Yes", True), ("yeah go ahead", True), ("sure.", True), ("okay", True),
    ("no", False), ("yes... no wait, cancel", False), ("", False), (None, False),
    ("what?", False), ("don't do it", False),
])
def test_yes_no(text, expected):
    assert parse_yes_no(text) is expected


def test_strip_thinking():
    assert strip_thinking("<think>hmm\nplan</think> Hello") == "Hello"
    # Leaked reasoning with only the closing tag (seen after tool calls)
    assert strip_thinking("Okay, the user asked...\nSo: done.\n</think>\n\nSettings opened.") == "Settings opened."
    assert strip_thinking("Hi there <think>unfinished") == "Hi there"
    assert strip_thinking("Plain reply.") == "Plain reply."


def test_clean_for_speech():
    out = clean_for_speech("**Done!** See https://x.com\n- item 🎉")
    assert "*" not in out and "http" not in out and "🎉" not in out
    assert "Done!" in out and "a link" in out


def test_best_match():
    names = ["spotify", "google chrome", "visual studio code", "microsoft edge"]
    assert best_match("chrome", names) == "google chrome"
    assert best_match("spotfy", names) == "spotify"
    assert best_match("visual studio", names) == "visual studio code"
    assert best_match("photoshop", names) is None


# ---------- registry ----------

def test_registry_schemas_and_validation(tmp_path):
    reg = make_registry(tmp_path)
    names = {s["function"]["name"] for s in reg.schemas()}
    assert {"get_datetime", "open_app", "close_app", "take_note", "power", "free_gpu"} <= names
    assert reg.get("power").risky and reg.get("close_app").risky
    assert not reg.get("open_app").risky
    assert "missing argument" in reg.run("take_note", {})
    assert "unknown tool" in reg.run("hack_nasa", {})
    # hallucinated extra args are dropped, not passed through
    assert reg.run("get_datetime", {"timezone": "UTC"}).startswith("It's")


def test_notes_roundtrip(tmp_path):
    reg = make_registry(tmp_path)
    assert reg.run("read_notes", {}) == "You don't have any notes yet."
    reg.run("take_note", {"text": "buy milk"})
    reg.run("take_note", {"text": "call mom"})
    out = reg.run("read_notes", {"count": 5})
    assert "buy milk" in out and "call mom" in out


def test_open_website(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(system_tools.webbrowser, "open", opened.append)
    reg = make_registry(tmp_path)
    assert reg.run("open_website", {"target": "youtube.com"}) == "Opened youtube.com."
    assert reg.run("open_website", {"target": "weather in Austin"}) == "Searching Google for weather in Austin."
    assert reg.run("open_website", {"target": "cute dogs", "section": "images"}) ==         "Here are Google Images results for cute dogs."
    reg.run("open_website", {"target": "pizza", "section": "maps"})
    reg.run("open_website", {"target": "cats", "section": "bogus"})
    assert opened == [
        "https://youtube.com",
        "https://www.google.com/search?q=weather+in+Austin",
        "https://www.google.com/search?q=cute+dogs&udm=2",
        "https://www.google.com/maps/search/pizza",
        "https://www.google.com/search?q=cats",            # unknown section -> normal search
    ]


def test_tool_exception_is_reported(tmp_path):
    reg = make_registry(tmp_path)

    @reg.tool("boom", params={})
    def explode():
        raise ValueError("kaboom")

    assert reg.run("explode", {}) == "Error running explode: kaboom"


# ---------- agent ----------

def test_plain_answer(tmp_path):
    llm = FakeLLM([ChatReply("Hello Alex.")])
    agent = make_agent(make_registry(tmp_path), llm)
    assert agent.handle("hi") == "Hello Alex."
    assert "think_harder" in llm.calls[0]["tools"]


def test_tool_call_then_answer(tmp_path):
    """Tools returning raw data (not direct) go back to the LLM to be phrased."""
    llm = FakeLLM([
        ChatReply("", [ToolCall("read_notes", {})]),
        ChatReply("You have no notes yet, Alex."),
    ])
    agent = make_agent(make_registry(tmp_path), llm)
    assert agent.handle("read my notes") == "You have no notes yet, Alex."
    tool_msg = llm.calls[1]["messages"][-1]
    assert tool_msg == {"role": "tool", "content": "You don't have any notes yet.", "tool_name": "read_notes"}


def test_direct_tool_skips_second_llm_call(tmp_path):
    llm = FakeLLM([ChatReply("", [ToolCall("take_note", {"text": "gym at 6"})])])
    agent = make_agent(make_registry(tmp_path), llm)
    assert agent.handle("note gym at 6") == "Noted."
    assert len(llm.calls) == 1
    assert "gym at 6" in (tmp_path / "notes.md").read_text()


def test_direct_tools_in_one_step_are_joined(tmp_path):
    reg = make_registry(tmp_path)
    reg.get("volume").func = lambda action, level=None: "Volume set to about 30 percent."
    llm = FakeLLM([ChatReply("", [ToolCall("take_note", {"text": "x"}),
                                  ToolCall("volume", {"action": "set", "level": 30})])])
    agent = make_agent(reg, llm)
    assert agent.handle("note x, volume 30") == "Noted. Volume set to about 30 percent."
    assert len(llm.calls) == 1


def test_compound_request_keeps_going_after_direct_tool(tmp_path):
    llm = FakeLLM([
        ChatReply("", [ToolCall("take_note", {"text": "gym"})]),
        ChatReply("Noted, and your notes are empty otherwise."),
    ])
    agent = make_agent(make_registry(tmp_path), llm)
    agent.handle("note gym and then read my notes")
    assert len(llm.calls) == 2   # "and"/"then" might need more steps, so the LLM continues


def test_direct_tool_error_goes_to_llm(tmp_path):
    llm = FakeLLM([
        ChatReply("", [ToolCall("volume", {"action": "set"})]),
        ChatReply("What level should I set it to?"),
    ])
    agent = make_agent(make_registry(tmp_path), llm)
    assert agent.handle("set the volume") == "What level should I set it to?"
    assert llm.calls[1]["messages"][-1]["content"].startswith("Error")


def test_system_prompt_is_stable_and_time_goes_in_user_message(tmp_path):
    llm = FakeLLM([ChatReply("Hi."), ChatReply("Sure.")])
    agent = make_agent(make_registry(tmp_path), llm)
    agent.handle("tell me a joke")
    agent.handle("thanks")
    first, second = llm.calls[0]["messages"], llm.calls[1]["messages"]
    assert first[0] == second[0]                       # identical system prompt -> reusable prefix
    assert first[1] == second[1]                       # history holds exactly what was sent
    assert first[-1]["content"].startswith("[") and first[-1]["content"].endswith("] tell me a joke")


def test_risky_tool_declined(tmp_path):
    ran = []
    reg = make_registry(tmp_path)
    reg.get("power").func = lambda action: ran.append(action)
    prompts = []
    llm = FakeLLM([ChatReply("", [ToolCall("power", {"action": "shutdown"})])])
    agent = make_agent(reg, llm, confirm=lambda p: prompts.append(p) or False)
    assert agent.handle("shut down") == "Okay, I won't."
    assert ran == []
    assert prompts == ["Do you really want me to shutdown the laptop?"]
    assert len(llm.calls) == 1   # a declined action needs no LLM phrasing


def test_risky_tool_approved(tmp_path):
    ran = []
    reg = make_registry(tmp_path)
    reg.get("power").func = lambda action: ran.append(action) or "Shutting down."
    llm = FakeLLM([
        ChatReply("", [ToolCall("power", {"action": "restart"})]),
        ChatReply("Restarting now."),
    ])
    events = []
    agent = make_agent(reg, llm, confirm=lambda p: True, events=events)
    agent.handle("restart")
    assert ran == ["restart"]
    kinds = [k for k, _ in events]
    assert kinds.index("confirm") < kinds.index("tool_call")


def test_escalation_switches_model(tmp_path):
    llm = FakeLLM([
        ChatReply("", [ToolCall("think_harder", {"reason": "planning"})]),
        ChatReply("Here's your study plan."),
    ])
    agent = make_agent(make_registry(tmp_path), llm)
    assert agent.handle("plan my week") == "Here's your study plan."
    assert [c["model"] for c in llm.calls] == ["fast", "planner"]
    assert "think_harder" not in llm.calls[1]["tools"]


def test_step_limit(tmp_path):
    llm = FakeLLM([ChatReply("", [ToolCall("read_notes", {})])] * 10)
    agent = make_agent(make_registry(tmp_path), llm)
    agent.max_steps = 3
    assert "stuck" in agent.handle("loop forever")
    assert len(llm.calls) == 3


def test_history_carries_over(tmp_path):
    llm = FakeLLM([ChatReply("It's 5 PM."), ChatReply("Sure.")])
    agent = make_agent(make_registry(tmp_path), llm)
    agent.handle("what time is it")
    agent.handle("and remind me later")
    roles = [m["role"] for m in llm.calls[1]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


def test_free_gpu_unloads_both(tmp_path):
    llm = FakeLLM([])
    reg = make_registry(tmp_path, llm)
    reg.run("free_gpu", {})
    cfg = load_config()
    assert set(llm.unloaded) == {cfg.llm.fast_model, cfg.llm.planner_model}


# ---------- audio ----------

class FakeMic:
    sample_rate = 16000

    def __init__(self, frames):
        self.frames = list(frames)

    def read(self, timeout=1.0):
        return self.frames.pop(0) if self.frames else None


def tone(amp):
    return (np.ones(FRAME) * amp).astype(np.int16)


def test_record_stops_after_silence():
    frames = [tone(10)] * 5 + [tone(5000)] * 10 + [tone(10)] * 20 + [tone(5000)] * 50
    audio = record_utterance(FakeMic(frames), NoiseFloor(100), silence_s=1.0, max_record_s=20)
    # lead-in (<=4) + 10 speech + ~13 silence frames; never reaches the later speech
    assert audio is not None
    assert len(audio) < 30 * FRAME
    assert audio.dtype == np.float32 and np.abs(audio).max() <= 1.0


def test_record_returns_none_when_silent():
    frames = [tone(10)] * 100
    assert record_utterance(FakeMic(frames), NoiseFloor(100), no_speech_timeout_s=2.0) is None


def test_wake_model_builtin():
    from sanae.wakeword import resolve_wake_model

    m = resolve_wake_model("hey_jarvis")
    assert (m.source, m.custom, m.phrase) == ("hey_jarvis", False, "Hey Jarvis")


def test_wake_model_custom_file(tmp_path):
    from sanae.wakeword import resolve_wake_model

    f = tmp_path / "hey_sanae.onnx"
    f.write_bytes(b"fake")
    m = resolve_wake_model(str(f), phrase="Hey Sanae")
    assert (m.source, m.custom, m.phrase) == (str(f), True, "Hey Sanae")
    assert resolve_wake_model(str(f)).phrase == "Hey Sanae"  # derived from the file name


def test_wake_model_missing_file_falls_back(tmp_path):
    from sanae.wakeword import resolve_wake_model

    m = resolve_wake_model(str(tmp_path / "nope.onnx"), phrase="Hey Sanae")
    assert (m.source, m.custom, m.phrase) == ("hey_jarvis", False, "Hey Jarvis")


def test_normalize_phrase():
    from sanae.wakeword import normalize_phrase

    assert normalize_phrase(" Hey, Sanae! ") == "HEY SANAE"
    assert normalize_phrase("okay   max") == "OKAY MAX"


def test_keyword_line():
    from sanae.wakeword import keyword_line

    pieces = {"HEY SANAE": ["▁HE", "Y", "▁SA", "NA", "E"]}
    line = keyword_line("Hey Sanae!", pieces.get, {"▁HE", "Y", "▁SA", "NA", "E"}, 1.0, 0.25)
    assert line == "▁HE Y ▁SA NA E :1.0 #0.25 @HEY_SANAE"
    with pytest.raises(ValueError):
        keyword_line("Hey Sanae", pieces.get, {"▁HE"}, 1.0, 0.25)  # token missing from model
    with pytest.raises(ValueError):
        keyword_line("!!!", pieces.get, set(), 1.0, 0.25)


KWS_DIR = Path(__file__).resolve().parent.parent / "models" / "kws" / "gigaspeech-3.3M"


@pytest.mark.skipif(not (KWS_DIR / "tokens.txt").exists(), reason="keyword spotting model not downloaded")
@pytest.mark.parametrize("phrase,expected", [("lovely child", True), ("Hey Sanae", False)])
def test_sherpa_detector_on_real_audio(phrase, expected):
    """End to end on the model's bundled clip, which contains '...a lovely child...'."""
    pytest.importorskip("sherpa_onnx")
    import wave

    from sanae.wakeword import SherpaKeywordDetector

    det = SherpaKeywordDetector(phrase, str(KWS_DIR))
    with wave.open(str(KWS_DIR / "test_wavs" / "1.wav")) as w:
        assert w.getframerate() == 16000
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    audio = np.concatenate([audio, np.zeros(16000, np.int16)])
    heard = any(det.process(audio[i:i + FRAME]) for i in range(0, len(audio), FRAME))
    assert heard is expected


def test_auto_gain_boosts_quiet_but_not_loud():
    from sanae.wakeword import AutoGain

    agc = AutoGain(max_gain=8.0, target_peak=16000, window_frames=3)
    quiet = np.full(FRAME, 500, np.int16)
    assert agc(quiet).max() == pytest.approx(4000)          # capped at 8x
    loud = np.full(FRAME, 20000, np.int16)
    assert agc(loud).max() == pytest.approx(20000)          # never turned down
    assert agc(quiet).max() == pytest.approx(500)           # loud word still in window: no pumping
    for _ in range(3):
        out = agc(quiet)
    assert out.max() == pytest.approx(4000)                 # window passed: boost returns


class FakeStream:
    def __init__(self, sid):
        self.id, self.samples, self.pending, self.fired = sid, 0, False, False

    def accept_waveform(self, sr, x):
        self.samples += len(x)
        self.pending = True


class FakeSpotter:
    """Stands in for sherpa_onnx.KeywordSpotter: only stream `fire_stream` fires, once it has
    seen `fire_after` samples."""

    def __init__(self, fire_stream=2, fire_after=FRAME):
        self.fire_stream, self.fire_after, self.created = fire_stream, fire_after, []

    def create_stream(self):
        self.created.append(FakeStream(len(self.created)))
        return self.created[-1]

    def is_ready(self, s):
        return s.pending

    def decode_stream(self, s):
        s.pending = False

    def get_result(self, s):
        if s.id == self.fire_stream and not s.fired and s.samples >= self.fire_after:
            s.fired = True
            return "HEY_SANAE"
        return ""

    def reset_stream(self, s):
        pass


def test_sherpa_streams_start_staggered_and_any_can_fire():
    from sanae.wakeword import SherpaKeywordDetector, WakeDetector

    det = SherpaKeywordDetector.__new__(SherpaKeywordDetector)   # skip model loading
    WakeDetector.__init__(det, cooldown_s=1.0)
    det.spotter, det.agc, det.num_streams = FakeSpotter(), None, 4
    det._stagger = int(16000 * det.CHUNK_S / det.num_streams)
    det.reset()

    started = []                      # (frame, streams alive) before any detection
    fired = []
    for i in range(12):
        if det.process(np.zeros(FRAME, np.int16)):
            fired.append(i)
            assert det.streams == [None] * 4   # firing restarts the staggered set
            break
        started.append(sum(s is not None for s in det.streams))
    # 0.64 s chunk / 4 streams = 2560 samples = 2 frames: a new stream every 2 frames
    assert det._stagger == 2560
    assert started == [1, 1, 2, 2]
    assert fired == [4]               # stream #2 starts at frame 4 and fires on its first frame


def test_llm_forces_gpu_layers_and_falls_back_on_load_error(monkeypatch):
    from sanae import llm as llm_mod

    sent = []

    class Resp:
        def __init__(self, code, body):
            self.status_code, self._body, self.text = code, body, str(body)

        def json(self):
            return self._body

    def fake_post(url, json, timeout):
        sent.append(json["options"].copy())
        if "num_gpu" in json["options"]:
            return Resp(500, {"error": "cudaMalloc failed: out of memory"})
        return Resp(200, {"message": {"content": "hi"}})

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    client = llm_mod.OllamaClient("http://x", num_ctx=4096, num_predict=256, gpu_layers={"fast": 99})
    assert client.chat("fast", [{"role": "user", "content": "hey"}]).content == "hi"
    assert sent[0]["num_gpu"] == 99 and sent[0]["num_ctx"] == 4096 and sent[0]["num_predict"] == 256
    assert sent[0]["use_mmap"] is False        # on the GPU: no mapped copy of the file in RAM
    assert "num_gpu" not in sent[1] and "use_mmap" not in sent[1]   # retried with Ollama's own split
    client.chat("fast", [{"role": "user", "content": "again"}])
    assert "num_gpu" not in sent[2]            # and stays off for the session
    client.chat("planner", [])
    assert "num_gpu" not in sent[3]            # never forced for other models


# ---------- web ----------

def test_select_passages_prefers_query_terms():
    from sanae.web import select_passages

    text = ("Paris is the capital of France. It has many museums. " * 3 +
            "The Eiffel Tower is 330 metres tall including antennas. " +
            "Bread is popular. " * 10)
    picked = select_passages(text, "how tall is the Eiffel Tower", n=1, size=120)
    assert len(picked) == 1 and "330 metres" in picked[0]


def test_select_passages_recency_finds_last_table_rows():
    from sanae.web import select_passages

    rows = " ".join(f"| {1967 + i} | Team{i} won the Super Bowl |." for i in range(60))
    picked = select_passages(rows, "most recent Super Bowl winner", n=1, size=200, this_year=2026)
    assert "2026" in picked[0] and "Team59" in picked[0]
    old = select_passages(rows, "first Super Bowl winner", n=1, size=200, this_year=2026)
    assert "1967" in old[0]                      # no recency intent: earliest match wins


def test_web_search_falls_back_to_duckduckgo(monkeypatch):
    import requests

    from sanae import web

    def boom(*a, **k):
        raise requests.ConnectionError("docker is off")

    monkeypatch.setattr(web.requests, "get", boom)
    monkeypatch.setattr(web.WebSearch, "_duckduckgo",
                        lambda self, q, n: [web.SearchResult("DDG hit", "https://example.com/a", "snippet")])
    ws = web.WebSearch("http://127.0.0.1:8888")
    hits = ws.search("anything")
    assert [h.title for h in hits] == ["DDG hit"] and ws.last_backend == "duckduckgo"


def test_web_search_tool_includes_passages_and_guard(tmp_path, monkeypatch):
    from sanae import web
    from sanae.tools import web as web_tools

    monkeypatch.setattr(web.WebSearch, "search", lambda self, q, n=None: [
        web.SearchResult("Super Bowl Winners", "https://www.espn.com/sb", "Every champion since 1967.")])
    monkeypatch.setattr(web, "fetch_text", lambda url, timeout=5.0: "| 2025 | Philadelphia won |. | 2026 | Seattle won |.")
    cfg = load_config()
    reg = ToolRegistry(context=Context(cfg, FakeLLM([])))
    web_tools.register(reg)
    out = reg.run("web_search", {"query": "latest Super Bowl winner"})
    assert "1. Super Bowl Winners (espn.com)" in out
    assert "Seattle won" in out                  # passage read from the page
    assert "don't guess" in out                  # anchored to the results


# ---------- browser (fake page, no Chrome needed) ----------

def el(i, name, role="link", **kw):
    from sanae.browser import Element

    base = dict(tag="a" if role == "link" else "button", type="", in_view=True, top=100 * i, heading=False,
                search=False, left=0, image=False, main=True)
    base.update(kw)
    return Element(i, name, base.pop("tag"), base.pop("type"), role, **base)


def test_pick_exact_ordinal_number_and_ambiguous():
    from sanae.browser import pick

    page = [el(1, "Images", role="tab", main=False), el(2, "Videos", role="tab", main=False),
            el(3, "Cute puppies playing in the snow", heading=True), el(4, "Ten tiny dogs you will love", heading=True),
            el(5, "Privacy", main=False)]
    assert pick(page, "Images")[0].id == 1
    assert pick(page, "first result")[0].id == 3            # nav tabs aren't results
    assert pick(page, "second result")[0].id == 4
    assert pick(page, "#5")[0].id == 5
    chosen, candidates = pick(page, "zzz qqq")
    assert chosen is None and candidates                    # nothing clear: let the LLM choose


def test_pick_thumbnail_becomes_title_link():
    from sanae.browser import pick

    page = [el(1, "Sponsored thing you should buy today", top=50),
            el(2, "11:53:45 Now playing", top=400, image=True),
            el(3, "lofi hip hop radio - beats to relax/study to", top=402),
            el(4, "6:10:58", top=700, image=True),
            el(5, "Best of lofi hip hop 2021 - 6 hour mix", top=703)]
    assert pick(page, "first video")[0].id == 3             # ad has no thumbnail; title beats "11:53:45"
    assert pick(page, "second video")[0].id == 5


class FakeSession:
    running = True

    def __init__(self, elements):
        self.elements, self.clicked, self.typed = elements, [], []

    def scan(self):
        return self.elements

    def settle(self, *a):
        pass

    def click(self, e):
        self.clicked.append(e.id)

    def type_into(self, e, text, submit):
        self.typed.append((e.id if e else None, text, submit))


def browser_registry(confirm_answer=False):
    from sanae.tools import browser as browser_tools

    cfg = load_config()
    ctx = Context(cfg, FakeLLM([]))
    asked = []
    ctx.confirm = lambda p: asked.append(p) or confirm_answer
    reg = ToolRegistry(context=ctx)
    browser_tools.register(reg)              # picks up the FakeSession patched in by patch_session
    return reg, ctx, asked


def patch_session(monkeypatch, fake):
    from sanae.tools import browser as browser_tools

    monkeypatch.setattr(browser_tools, "BrowserSession", lambda *a, **k: fake)


def test_browser_click_risky_needs_yes(tmp_path, monkeypatch):
    fake = FakeSession([el(1, "Subscribe to Lofi Girl.", role="button"), el(2, "Share", role="button")])
    patch_session(monkeypatch, fake)
    reg, ctx, asked = browser_registry(confirm_answer=False)
    assert reg.run("browser_click", {"target": "Share"}) == "Clicked Share."
    assert reg.run("browser_click", {"target": "Subscribe"}) == DECLINED
    assert asked == ["This will click 'Subscribe to Lofi Girl'. Should I?"]
    assert fake.clicked == [2]


def test_browser_type_search_submits_and_refuses_passwords(tmp_path, monkeypatch):
    fake = FakeSession([el(1, "Search", role="searchbox", tag="input", search=True),
                        el(2, "Password", role="textbox", tag="input", type="password"),
                        el(3, "Comment", role="textbox", tag="textarea")])
    patch_session(monkeypatch, fake)
    reg, ctx, asked = browser_registry()
    assert reg.run("browser_type", {"text": "lofi music"}) == "Typed it and submitted."
    assert fake.typed == [(1, "lofi music", True)]           # search box: Enter by default
    assert reg.run("browser_type", {"text": "hunter2", "field": "password"}).startswith("Error: I don't type passwords")
    assert reg.run("browser_type", {"text": "great video", "field": "comment", "submit": True}) == DECLINED
    assert len(fake.typed) == 1 and len(asked) == 1          # posting a comment needed a yes


def test_ambiguous_click_goes_back_to_llm(tmp_path, monkeypatch):
    fake = FakeSession([el(1, "Open settings panel", role="button"), el(2, "Open settings menu", role="button")])
    patch_session(monkeypatch, fake)
    reg, ctx, asked = browser_registry()
    llm = FakeLLM([ChatReply("", [ToolCall("browser_click", {"target": "zzqq"})]),
                   ChatReply("Which one: the settings panel or the settings menu?")])
    agent = make_agent(reg, llm)
    assert agent.handle("click that thing") == "Which one: the settings panel or the settings menu?"
    assert len(llm.calls) == 2                               # list went to the LLM, not read aloud


def test_pick_counts_videos_on_a_video_page():
    from sanae.browser import pick

    page = [el(1, "The Beatles", image=True, href="/channel/UCc4K7"),
            el(2, "Hey Jude (Remastered 2015)", image=True, href="/watch?v=A_MjCqQoLLA"),
            el(3, "Let It Be (Remastered 2009)", image=True, href="/watch?v=QDYfEBY9NM4"),
            el(4, "Come Together", image=True, href="/watch?v=45cYwDMibGo")]
    assert pick(page, "second link")[0].id == 3            # channel card isn't counted
    assert pick(page, "first video")[0].id == 2


def test_open_website_site_search(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(system_tools.webbrowser, "open", opened.append)
    reg = make_registry(tmp_path)
    assert reg.run("open_website", {"target": "Beatles", "site": "youtube"}) == "Searching YouTube for Beatles."
    reg.run("open_website", {"target": "usb c hub", "site": "amazon.com"})
    assert opened == ["https://www.youtube.com/results?search_query=Beatles", "https://www.amazon.com/s?k=usb+c+hub"]


def test_background_writer_never_blocks_the_caller():
    import threading
    import time

    from sanae.winutil import BackgroundWriter

    class StalledConsole:
        """Like a console in 'Select' mode: writes block until released."""
        def __init__(self):
            self.release, self.written = threading.Event(), []

        def write(self, text):
            self.release.wait()
            self.written.append(text)

        def flush(self):
            pass

    console = StalledConsole()
    out = BackgroundWriter(console, max_items=10)
    start = time.perf_counter()
    for i in range(50):
        print(f"line {i}", file=out)       # would hang forever if written directly
    assert time.perf_counter() - start < 0.5
    console.release.set()
    for _ in range(50):
        if console.written:
            break
        time.sleep(0.02)
    assert console.written and console.written[0] == "line 0"


# ---------- listening ----------

def test_looks_complete_and_strip_wake_word():
    from sanae.listen import looks_complete, strip_wake_word

    assert looks_complete("Open YouTube.") and looks_complete("What time is it?")
    assert not looks_complete("Can you search for...") and not looks_complete("Search for")
    assert not looks_complete("open the") and not looks_complete("")
    assert strip_wake_word("Sanae, open YouTube.") == "open YouTube."
    assert strip_wake_word("Hey Sanae what time is it") == "what time is it"
    assert strip_wake_word("Maxwell's equations") == "Maxwell's equations"


def speech(n, amp=5000):
    return [tone(amp)] * n


def test_listen_answers_early_when_the_request_is_complete():
    from sanae.listen import listen_for_command

    calls = []

    def transcribe(audio):
        calls.append(len(audio))
        return "Open YouTube."

    frames = speech(10) + [tone(10)] * 40            # 0.8 s speech, then 3.2 s of silence
    mic = FakeMic(frames)
    assert listen_for_command(mic, NoiseFloor(100), transcribe, silence_s=1.0, early_s=0.4) == "Open YouTube."
    used = 50 - len(mic.frames)
    assert used < 10 + 12 + 4                        # returned at ~0.4-0.5 s of silence, not 1.0 s


def test_listen_waits_when_the_sentence_trails_off():
    from sanae.listen import listen_for_command

    replies = iter(["Can you search for...", "Can you search for arctic monkeys?", "Can you search for arctic monkeys?"])
    frames = speech(10) + [tone(10)] * 15 + speech(8) + [tone(10)] * 40   # 1.2 s pause mid-sentence
    mic = FakeMic(frames)
    text = listen_for_command(mic, NoiseFloor(100), lambda a: next(replies), silence_s=1.0, early_s=0.4,
                              max_silence_s=1.8)
    assert text == "Can you search for arctic monkeys?"   # didn't cut off at the pause


def test_listen_keeps_words_said_right_after_wake():
    from sanae.listen import listen_for_command

    got = []
    frames = speech(6) + [tone(10)] * 30             # talking immediately, no pause for the chime
    listen_for_command(FakeMic(frames), NoiseFloor(100), lambda a: got.append(a) or "Open Spotify.")
    assert got and len(got[0]) >= 6 * FRAME          # all the speech frames were transcribed


def test_stt_routes_clear_speech_to_fast_engine_and_quiet_to_whisper():
    from sanae.stt import SpeechToText, snr_db

    rng = np.random.default_rng(0)
    noise = lambda n, db: rng.normal(0, 10 ** (db / 20), n)
    tone_ = lambda n, db: np.sin(np.arange(n) / 5) * 10 ** (db / 20)
    clear = np.concatenate([noise(8000, -60), tone_(16000, -6) + noise(16000, -60), noise(8000, -60)]).astype(np.float32)
    murky = np.concatenate([noise(8000, -40), tone_(16000, -38) + noise(16000, -40), noise(8000, -40)]).astype(np.float32)
    assert snr_db(clear) > 40 and snr_db(murky) < 12

    stt = SpeechToText.__new__(SpeechToText)       # skip loading real models
    used = []
    stt.fast = type("F", (), {"transcribe": lambda self, a: used.append("fast") or "Open YouTube."})()
    stt.fast_min_snr_db = 12.0
    stt.whisper = lambda a: used.append("whisper") or "open youtube"
    assert stt.transcribe(clear) == "Open YouTube." and used == ["fast"]
    assert stt.transcribe(murky) == "open youtube" and used == ["fast", "whisper"]
    stt.fast = type("F", (), {"transcribe": lambda self, a: ""})()   # fast engine heard nothing
    assert stt.transcribe(clear) == "open youtube"                   # -> Whisper double-checks


def test_listen_retranscribes_everything_when_it_still_sounds_unfinished():
    from sanae.listen import listen_for_command

    seen = []

    def transcribe(audio):
        seen.append(len(audio))
        return "search for arctic monkeys on..." if len(seen) == 1 else "search for arctic monkeys on YouTube"

    frames = speech(10) + [tone(10)] * 40
    text = listen_for_command(FakeMic(frames), NoiseFloor(100), transcribe, silence_s=1.0, early_s=0.4, max_silence_s=1.8)
    assert text == "search for arctic monkeys on YouTube"
    assert len(seen) == 2 and seen[1] > seen[0]      # second pass covered the quiet tail too


# ---------- follow-up conversation ----------

def run_converse(first, replies, follow_ups, follow_up=True):
    from sanae.main import converse

    replies, follow_ups, said, idle = iter(replies), iter(follow_ups), [], []

    def respond(text):
        said.append(text)
        return next(replies) if text is not None else None

    n = converse(first, respond, lambda: next(follow_ups), follow_up=follow_up, on_idle=lambda: idle.append(1))
    return n, said, idle


def test_follow_up_after_a_question_without_wake_word():
    n, said, idle = run_converse("search for something",
                                 ["What should I search for?", "Searching Google for lofi music."],
                                 ["lofi music"])
    assert said == ["search for something", "lofi music"] and n == 2


def test_no_follow_up_after_a_statement():
    n, said, _ = run_converse("open youtube", ["Opened youtube.com."], [])   # follow_ups would raise if used
    assert n == 1


def test_follow_up_ends_on_silence_or_phantom_text():
    n, said, idle = run_converse("play something", ["Which song?"], [""])
    assert n == 1 and idle == [1]                      # silence -> back to waiting for "Hey Sanae"
    n, said, idle = run_converse("play something", ["Which song?"], ["Thank you."])
    assert n == 1 and idle == [1]                      # classic phantom transcript ignored


def test_follow_ups_chain_and_can_be_turned_off():
    n, said, _ = run_converse("set a reminder", ["For when?", "What should it say?", "Noted."],
                              ["tomorrow", "call mom"])
    assert said == ["set a reminder", "tomorrow", "call mom"] and n == 3
    n, said, _ = run_converse("search", ["What for?"], [], follow_up=False)
    assert n == 1


def test_never_mind_in_a_follow_up():
    n, said, _ = run_converse("search", ["What should I search for?"], ["never mind"])
    assert said == ["search", None] and n == 1        # None = the "Okay." path


def test_snr_not_fooled_by_noise_gated_mic():
    from sanae.stt import snr_db

    gated = np.concatenate([np.zeros(8000), np.sin(np.arange(16000) / 5) * 0.3, np.zeros(8000)]).astype(np.float32)
    assert snr_db(gated) < 70            # digital-zero "silence" no longer means a perfect recording


# ---------- memory & reminders ----------

class WordEmbedder:
    """Deterministic stand-in for the real embedder: hashed bag of words, normalised."""

    def embed(self, texts):
        import re as _re
        out = np.zeros((len(texts), 256), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in _re.findall(r"[a-z0-9]+", t.lower()):
                if w not in {"my", "is", "the", "a", "on", "what", "when", "s"}:
                    out[i, hash(w) % 256] += 1
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


def memory_store():
    from sanae.memory import MemoryStore
    return MemoryStore(":memory:", WordEmbedder())


def test_memory_facts_search_dedupe_delete():
    m = memory_store()
    fid, old = m.add_fact("My CS 101 exam is on Friday October 2.")
    assert old is None
    m.add_fact("My sister's name is Maya")
    hits = m.search_facts("when is my CS 101 exam", k=1)
    assert hits[0].text == "My CS 101 exam is on Friday October 2"
    _, old = m.add_fact("My CS 101 exam is on Friday October 2")        # same fact again
    assert old is not None and len(m.facts()) == 2
    assert m.delete_fact(fid) and len(m.facts()) == 1
    assert not m.search_facts("CS 101 exam", min_score=0.5)


def test_memory_turns_and_actions():
    m = memory_store()
    m.log_turn("search for arctic monkeys", "Searching YouTube for arctic monkeys.", ["open_website"])
    m.log_turn("set volume to 30", "Volume set to about 30 percent.", ["volume"])
    assert m.search_turns("arctic monkeys", k=1)[0].text.startswith("you: search for arctic monkeys")
    assert [t["tools"] for t in m.recent_turns()] == [["open_website"], ["volume"]]
    m.log_action("tool", {"tool": "volume", "result": "ok"})
    assert m.actions()[-1]["detail"]["tool"] == "volume"


def test_context_for_only_attaches_relevant_facts():
    m = memory_store()
    m.add_fact("My CS 101 exam is on Friday October 2")
    assert "exam" in (m.context_for("CS 101 exam Friday October") or "")
    assert m.context_for("open youtube") is None


def test_parse_when_phrases():
    import datetime as dt
    from sanae.reminders import parse_when, spoken_time

    now = dt.datetime(2026, 9, 30, 0, 45)          # Wednesday, 12:45 AM
    cases = {"Friday at 9am": (2026, 10, 2, 9, 0), "friday": (2026, 10, 2, 9, 0),
             "tomorrow morning": (2026, 10, 1, 9, 0), "tonight at 9": (2026, 9, 30, 21, 0),
             "next Monday 8am": (2026, 10, 5, 8, 0), "in 2 hours": (2026, 9, 30, 2, 45),
             "Thursday evening": (2026, 10, 1, 18, 0), "2026-10-02T09:00": (2026, 10, 2, 9, 0)}
    for phrase, expect in cases.items():
        assert parse_when(phrase, now) == dt.datetime(*expect), phrase
    assert parse_when("gibberish zzz", now) is None
    assert spoken_time(dt.datetime(2026, 10, 1, 18, 0), now) == "tomorrow at 6 PM"
    assert spoken_time(dt.datetime(2026, 10, 2, 9, 30), now) == "Friday, October 2 at 9:30 AM"


def test_reminder_scheduler_fires_due_and_flags_missed():
    import datetime as dt
    from sanae.reminders import ReminderScheduler, Reminders

    r = Reminders(memory_store())
    now = dt.datetime.now()
    r.add("stretch", now - dt.timedelta(seconds=30))       # just due
    r.add("exam", now - dt.timedelta(hours=3))             # came due while Sanae was off
    r.add("later", now + dt.timedelta(hours=1))
    fired = []
    ReminderScheduler(r, lambda rem, missed: fired.append((rem.text, missed))).check(now)
    assert sorted(fired) == [("exam", True), ("stretch", False)]
    assert [x.text for x in r.pending()] == ["later"]      # fired ones aren't repeated



def test_repeating_reminder_phrases():
    import datetime as dt
    from sanae.reminders import next_due, parse_repeating, parse_when, spoken_repeat

    now = dt.datetime(2026, 10, 12, 10, 40)          # Monday, 10:40 AM
    cases = {
        "the 5th of every month": ((2026, 11, 5, 9, 0), "monthly:5"),
        "every month's 5th day": ((2026, 11, 5, 9, 0), "monthly:5"),
        "every month on the 20th at 6pm": ((2026, 10, 20, 18, 0), "monthly:20"),
        "monthly on the 31st": ((2026, 10, 31, 9, 0), "monthly:31"),
        "every Monday at 8am": ((2026, 10, 19, 8, 0), "weekly"),
        "on Fridays at 5:30 pm": ((2026, 10, 16, 17, 30), "weekly"),
        "daily at 9pm": ((2026, 10, 12, 21, 0), "daily"),
        "every morning": ((2026, 10, 13, 9, 0), "daily"),
        "every weekday at 7am": ((2026, 10, 13, 7, 0), "weekdays"),
        "every year on March 3": ((2027, 3, 3, 9, 0), "yearly:3-3"),
    }
    for phrase, (expect, rule) in cases.items():
        assert parse_repeating(phrase, now=now) == (dt.datetime(*expect), rule), phrase
    # one-time phrases aren't repeating; the tool's repeat="monthly" + when="the 5th" is
    for phrase in ("Friday at 9am", "tomorrow morning", "in 2 hours", "next month", "2026-11-05T09:00"):
        assert parse_repeating(phrase, now=now) is None, phrase
    assert parse_repeating("the 5th", "monthly", now=now) == (dt.datetime(2026, 11, 5, 9, 0), "monthly:5")
    assert parse_when("tomorrow morning", now) == dt.datetime(2026, 10, 13, 9, 0)

    # next occurrences: short months, year end, Friday -> Monday, Feb 29, missed ones skipped
    d = dt.datetime
    assert next_due(d(2026, 10, 31, 9), "monthly:31", d(2026, 10, 31, 9)) == d(2026, 11, 30, 9)
    assert next_due(d(2026, 11, 30, 9), "monthly:31", d(2026, 11, 30, 9)) == d(2026, 12, 31, 9)
    assert next_due(d(2027, 1, 31, 9), "monthly:31", d(2027, 1, 31, 9)) == d(2027, 2, 28, 9)
    assert next_due(d(2026, 12, 5, 9), "monthly:5", d(2026, 12, 5, 9)) == d(2027, 1, 5, 9)
    assert next_due(d(2026, 6, 5, 9), "monthly:5", now) == d(2026, 11, 5, 9)
    assert next_due(d(2026, 10, 16, 7), "weekdays", d(2026, 10, 16, 7)) == d(2026, 10, 19, 7)
    assert next_due(d(2028, 2, 29, 9), "yearly:2-29", d(2028, 2, 29, 9)) == d(2029, 2, 28, 9)
    assert next_due(d(2029, 2, 28, 9), "yearly:2-29", d(2029, 2, 28, 9)) == d(2030, 2, 28, 9)
    assert spoken_repeat("monthly:5", d(2026, 11, 5, 9)) == "on the 5th of every month at 9 AM"
    assert spoken_repeat("weekly", d(2026, 10, 19, 8, 30)) == "every Monday at 8:30 AM"


def test_repeating_reminders_move_on_instead_of_finishing():
    import datetime as dt
    from sanae.reminders import ReminderScheduler, Reminders

    r = Reminders(memory_store())
    now = dt.datetime.now().replace(microsecond=0)
    rent = r.add("rent", now - dt.timedelta(seconds=20), repeat="daily")
    away = r.add("pills", now - dt.timedelta(days=3, seconds=20), repeat="daily")     # missed while off
    shown = r.add("phone had it", now - dt.timedelta(days=1, hours=1), repeat="weekly")
    r.mark_on_phone([shown.uid])
    fired = []
    ReminderScheduler(r, lambda rem, missed: fired.append((rem.text, missed))).check(now)
    assert sorted(fired) == [("pills", True), ("rent", False)]     # once each, not once per missed day
    after = {x.uid: x for x in r.pending()}
    assert len(after) == 3
    assert after[rent.uid].due == rent.due + dt.timedelta(days=1)
    assert after[away.uid].due == away.due + dt.timedelta(days=4) and after[away.uid].due > now
    assert after[shown.uid].due == shown.due + dt.timedelta(days=7)
    assert after[rent.uid].updated >= rent.updated                 # the phone hears about the new time
    assert after[rent.uid].to_sync()["repeat"] == "daily"

def memory_registry(confirm_answer=True):
    from sanae.reminders import Reminders
    from sanae.tools import memory as memory_tools

    ctx = Context(load_config(), FakeLLM([]))
    ctx.memory = memory_store()
    ctx.reminders = Reminders(ctx.memory)
    ctx.confirm = lambda p: confirm_answer
    reg = ToolRegistry(context=ctx)
    memory_tools.register(reg)
    return reg, ctx


def test_memory_tools_end_to_end():
    reg, ctx = memory_registry()
    assert reg.run("remember", {"fact": "My CS 101 exam is on Friday October 2"}) == "Got it, I'll remember that."
    out = reg.run("recall", {"query": "when is my CS 101 exam"})
    assert "Friday October 2" in out
    assert reg.run("forget", {"what": "CS 101 exam"}) == "Forgotten."
    assert reg.run("recall", {"query": "CS 101 exam"}) == "Nothing saved about that."


def test_reminder_tools():
    reg, ctx = memory_registry()
    out = reg.run("set_reminder", {"text": "CS 101 exam", "when": "tomorrow at 9am"})
    assert out.startswith("Okay, I'll remind you tomorrow at 9 AM")
    assert reg.run("set_reminder", {"text": "x", "when": "blorp"}).startswith("Error")
    reg.run("set_reminder", {"text": "call mom", "when": "in 2 hours"})
    assert reg.run("list_reminders", {}).startswith("You have 2 reminders")
    assert reg.run("cancel_reminder", {"which": "the exam"}) == "Cancelled the reminder: CS 101 exam."
    assert [r.text for r in ctx.reminders.pending()] == ["call mom"]


def test_repeating_reminder_tool():
    reg, ctx = memory_registry()
    out = reg.run("set_reminder", {"text": "Pay Insurance", "when": "the 5th of every month"})
    assert out.startswith("Okay, I'll remind you on the 5th of every month at 9 AM, starting "), out
    r = ctx.reminders.pending()[0]
    assert r.repeat == "monthly:5" and r.due.day == 5
    # the model may split it: repeat="monthly", when="the 5th at 6pm"
    out = reg.run("set_reminder", {"text": "rent", "when": "the 1st at 6pm", "repeat": "monthly"})
    assert "1st of every month at 6 PM" in out
    assert "of every month" in reg.run("list_reminders", {})
    # unreadable: the error gives examples to retry with instead of telling her to ask the user
    err = reg.run("set_reminder", {"text": "x", "when": "blorp"})
    assert err.startswith("Error") and "every month" in err and "Ask the user when exactly" not in err
    assert reg.run("cancel_reminder", {"which": "insurance"}) == "Cancelled the repeating reminder: Pay Insurance."


def test_agent_attaches_memories_and_logs_turns(tmp_path):
    logged = []
    llm = FakeLLM([ChatReply("", [ToolCall("take_note", {"text": "x"})])])
    agent = Agent(llm, make_registry(tmp_path), "fast", "planner",
                  recall=lambda t: "Alex's exam is on Friday" if "exam" in t else None,
                  on_turn=lambda u, a, tools: logged.append((u, a, tools)))
    agent.handle("note about my exam")
    assert "(You remember: Alex's exam is on Friday)" in llm.calls[0]["messages"][-1]["content"]
    assert logged == [("note about my exam", "Noted.", ["take_note"])]


# ---------- dashboard API ----------

LOCAL = ("127.0.0.1", 50000)       # requests from the laptop itself (no token needed)

def api_client(run_command=lambda text, source="dashboard": f"echo: {text}", token="", client=LOCAL):
    from fastapi.testclient import TestClient

    from sanae.events import ApprovalBroker, EventBus
    from sanae.reminders import Reminders
    from sanae.server import Runtime, create_app

    ctx = Context(load_config(), FakeLLM([]))
    ctx.memory = memory_store()
    ctx.reminders = Reminders(ctx.memory)
    from sanae.agenda import Events

    ctx.events = Events(ctx.memory)
    from sanae.todos import Todos

    ctx.todos = Todos(ctx.memory)
    from sanae.chores import Chores

    ctx.chores = Chores(ctx.memory)
    bus = EventBus()
    approvals = ApprovalBroker(bus)
    rt = Runtime(ctx, bus, approvals, run_command, {"name": "Sanae"}, token=token)
    return TestClient(create_app(rt), client=client), rt


def test_api_facts_reminders_and_commands():
    client, rt = api_client()
    assert client.post("/api/facts", json={"text": "My sister's name is Maya"}).json()["updated"] is False
    facts = client.get("/api/facts").json()
    assert [f["text"] for f in facts] == ["My sister's name is Maya"]
    assert client.delete(f"/api/facts/{facts[0]['id']}").json() == {"ok": True}
    r = client.post("/api/reminders", json={"text": "exam", "when": "tomorrow at 9am"}).json()
    assert r["spoken"] == "tomorrow at 9 AM"
    assert [x["text"] for x in client.get("/api/reminders").json()] == ["exam"]
    assert client.post("/api/reminders", json={"text": "x", "when": "blorp"}).status_code == 400
    assert client.post("/api/command", json={"text": "open youtube"}).json() == {"reply": "echo: open youtube"}
    assert [e["kind"] for e in rt.bus.recent][-1] == "reminder"


def test_api_approvals_race_and_websocket():
    client, rt = api_client()
    a = rt.approvals.open("Shut down the laptop?", "power")
    assert client.get("/api/state").json()["approvals"] == [{"id": a.id, "prompt": "Shut down the laptop?", "tool": "power"}]
    assert client.post(f"/api/approvals/{a.id}", json={"approved": True}).json() == {"ok": True}
    assert a.done.is_set() and a.approved is True
    rt.approvals.close(a, True, "dashboard")
    assert client.post(f"/api/approvals/{a.id}", json={"approved": False}).status_code == 404
    with client.websocket_connect("/api/ws") as ws:
        hello = ws.receive_json()
        assert hello["kind"] == "hello" and any(e["kind"] == "approval_result" for e in hello["data"]["recent"])
        rt.bus.publish("stage", {"stage": "thinking"})
        assert ws.receive_json()["data"] == {"stage": "thinking"}


def test_forget_requests_skip_the_model_and_still_confirm():
    from sanae.agent import FORGET

    assert FORGET.match("could you forget my exam").group(1) == "my exam"
    assert FORGET.match("can you forget what I told you about lofi").group(1) == "lofi"
    assert FORGET.match("I forgot my keys") is None and FORGET.match("don't forget to call mom") is None
    reg, ctx = memory_registry(confirm_answer=False)
    ctx.memory.add_fact("Alex prefers lofi music when studying")
    llm = FakeLLM([])                                   # would raise if the model were asked
    agent = Agent(llm, reg, "fast", "planner")
    assert agent.handle("forget the lofi music when studying") == "Okay, I won't."
    assert len(ctx.memory.facts()) == 1 and llm.calls == []


def test_false_claim_gets_one_nudge():
    reg, ctx = memory_registry()
    llm = FakeLLM([ChatReply("Okay, I'll remind you tomorrow."),               # claims, no tool
                   ChatReply("", [ToolCall("set_reminder", {"text": "gym", "when": "tomorrow at 7am"})])])
    agent = Agent(llm, reg, "fast", "planner")
    assert agent.handle("remind me about gym tomorrow at 7").startswith("Okay, I'll remind you tomorrow at 7 AM")
    assert "System check" in llm.calls[1]["messages"][-1]["content"]
    assert [r.text for r in ctx.reminders.pending()] == ["gym"]


# ---------- Canvas & daily digest ----------

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:test
BEGIN:VEVENT
UID:event-assignment-1
DTSTART;VALUE=DATE:20261001
SUMMARY:Lab 4 [2026FallC-T-CS101-68549]
END:VEVENT
BEGIN:VEVENT
UID:event-assignment-2
DTSTART;VALUE=DATE:20261004
SUMMARY:Assignment1 [2026FallC-T-CS102-73246]
END:VEVENT
BEGIN:VEVENT
UID:event-calendar-event-10
DTSTART:20261001T120000Z
DTEND:20261001T131500Z
SUMMARY:CS 103: Intro Topics (2026 Fall C) [2026FallC-T-CS103-10001]
DESCRIPTION:[Click here to join Zoom Meeting] (https://school.zoom.us/j/123)
END:VEVENT
BEGIN:VEVENT
UID:event-calendar-event-11
DTSTART:20261001T120000Z
DTEND:20261001T131500Z
SUMMARY:CS 103: Intro Topics (2024 Spring) [2026FallC-T-CS103-10001]
END:VEVENT
END:VCALENDAR
"""


def test_canvas_feed_parsing():
    from sanae.canvas import describe_due, parse_feed

    items = parse_feed(ICS)
    assignments = [i for i in items if i.kind == "assignment"]
    classes = [i for i in items if i.kind == "class"]
    assert [(a.title, a.course, a.all_day) for a in assignments] == [("Lab 4", "CS 101", True), ("Assignment1", "CS 102", True)]
    assert len(classes) == 1                                  # other section's copy dropped
    assert classes[0].course == "CS 103" and classes[0].link == "https://school.zoom.us/j/123"
    assert describe_due(assignments[:1], "today") == "Due today: Lab 4 for CS 101, by end of day."
    assert describe_due([], "tomorrow") == "Nothing due tomorrow on Canvas."


class FakeFeed:
    def __init__(self, items):
        self._items = items

    def between(self, start, end, kind=None):
        return [i for i in self._items if start <= i.start < end and (kind is None or i.kind == kind)]


def digest_ctx(tmp_items=None):
    import datetime as dt
    from sanae.canvas import parse_feed
    from sanae.reminders import Reminders

    ctx = Context(load_config(), FakeLLM([]))
    ctx.memory = memory_store()
    ctx.reminders = Reminders(ctx.memory)
    ctx.canvas = FakeFeed(parse_feed(ICS) if tmp_items is None else tmp_items)
    ctx.reminders.add("stand-up", dt.datetime(2026, 10, 1, 10, 0))
    return ctx


def test_digest_content_and_spoken_summary():
    import datetime as dt
    from sanae.digest import gather, render, spoken

    plan = gather(digest_ctx(), dt.date(2026, 10, 1))
    assert [i.title for i in plan.due_today] == ["Lab 4"] and [i.title for i in plan.due_soon] == ["Assignment1"]
    assert len(plan.classes) == 1 and [r.text for r in plan.reminders] == ["stand-up"]
    subject, text, body = render(plan, "Focus on Lab 4 first.")
    assert subject == "Your day, Thu Oct 1: 1 due today"
    assert "Lab 4 (CS 101) by end of day" in text and "Zoom: https://school.zoom.us/j/123" in text
    assert "Focus on Lab 4 first." in body and "<li" in body
    s = spoken(plan)
    assert s.startswith("Due today: Lab 4 for CS 101.") and "Coming up: Assignment1" in s


def test_digest_schedule_catch_up_and_once_a_day():
    import datetime as dt
    from sanae.digest import DigestScheduler

    ctx = digest_ctx()
    sched = DigestScheduler(ctx, "07:00", weekends=False, catch_up_until="18:00")
    thu = dt.datetime(2026, 10, 1, 6, 59)
    assert not sched.due(thu)                                       # too early
    assert sched.due(thu.replace(hour=9))                           # late start: catch up
    assert not sched.due(thu.replace(hour=19))                      # too late to be useful
    assert not sched.due(dt.datetime(2026, 10, 3, 8, 0))            # Saturday, weekends off
    ctx.memory.set("digest_last_sent", "2026-10-01")
    assert not sched.due(thu.replace(hour=9))                       # already sent today


def test_digest_refuses_placeholder_email_settings():
    from sanae.digest import send_email

    with pytest.raises(RuntimeError, match="isn't set up"):
        send_email({"smtp_user": "your.address@gmail.com", "app_password": "xxxx xxxx xxxx xxxx"}, "s", "t", "<p>h</p>")


def test_api_remote_control_and_today():
    from fastapi.testclient import TestClient

    from sanae.events import ApprovalBroker, Controls, EventBus
    from sanae.server import Runtime, create_app

    ctx = digest_ctx()
    bus = EventBus()
    controls = Controls()
    client = TestClient(create_app(Runtime(ctx, bus, ApprovalBroker(bus), lambda t: t, {}, controls)), client=LOCAL)
    controls.paused.set()
    assert client.post("/api/control/listen").json() == {"ok": True, "paused": False}
    assert controls.listen_now.is_set() and not controls.paused.is_set()     # push-to-talk also unpauses
    assert client.post("/api/control/pause").json()["paused"] is True
    client.post("/api/control/quit")
    assert controls.quit.is_set()
    assert client.post("/api/control/explode").status_code == 404

    def no_mail(*a):
        raise AssertionError("the Today page doesn't show mail, so it mustn't wait on Gmail")
    from types import SimpleNamespace
    ctx.mail = SimpleNamespace(search=no_mail)
    today = client.get("/api/today").json()
    assert set(today) >= {"due_today", "due_soon", "classes", "reminders", "date"}
    no_controls = TestClient(create_app(Runtime(ctx, bus, ApprovalBroker(bus), lambda t: t, {})), client=LOCAL)
    assert no_controls.post("/api/control/listen").status_code == 409        # text mode: no mic to control


# ---------- meeting & lecture notes ----------

def speechy(seconds, amp=0.2, seed=0):
    rng = np.random.default_rng(seed)
    return (rng.normal(0, amp, int(seconds * 16000))).astype(np.float32)


def test_segmenter_cuts_near_pauses():
    from sanae.notes import Segmenter

    seg = Segmenter(min_s=25, max_s=32)
    audio = np.concatenate([speechy(24), np.zeros(8000, np.float32), speechy(12)])     # pause at 24 s
    chunks = seg.push(audio) + seg.flush()
    assert len(chunks) == 2
    assert abs(len(chunks[0][1]) / 16000 - 24.0) < 0.6          # cut inside the pause, not mid-"word"
    assert chunks[1][0] == len(chunks[0][1]) / 16000             # second chunk's timestamp follows on


def test_note_session_map_reduce_and_deadline_quotes(tmp_path):
    from sanae.notes import NoteSession, save

    said = iter(["Today we cover knowledge graphs and RDF triples.",
                 "Assignment two is due next Friday at 11:59 PM on Canvas.",
                 "Also there is a quiz on Monday about SPARQL."])
    calls = []

    def summarize(system, text, max_tokens):
        calls.append(system.split()[0])
        return "## Summary\nKnowledge graphs.\n## Key points\n- RDF" if "Combine" in system else f"- notes on: {text[:30]}"

    session = NoteSession("lecture", lambda audio, prompt: next(said), summarize, title="CS 103", section_words=8)
    for _ in range(3):
        session.push(speechy(26))
        session.push(np.zeros(16000, np.float32))
    result = session.finish()
    assert result.word_count == sum(len(s.split()) for s in ["Today we cover knowledge graphs and RDF triples.",
                                                              "Assignment two is due next Friday at 11:59 PM on Canvas.",
                                                              "Also there is a quiz on Monday about SPARQL."])
    assert calls.count("You") >= 2 and calls[-1] == "Combine"   # section notes, then one final combine
    assert "## Deadlines & dates (exact quotes)" in result.notes_md
    assert "due next Friday at 11:59 PM" in result.notes_md and "quiz on Monday" in result.notes_md
    folder = save(result, tmp_path)
    assert (folder / "notes.md").read_text(encoding="utf-8").startswith("# CS 103")
    assert "[00:" in (folder / "transcript.md").read_text(encoding="utf-8")


def test_note_session_skips_silence():
    from sanae.notes import NoteSession

    heard = []
    session = NoteSession("meeting", lambda a, p: heard.append(1) or "x", lambda s, t, n: "", section_words=100)
    session.push(np.zeros(16000 * 30, np.float32))
    result = session.finish()
    assert heard == [] and "Nothing was transcribed" in result.notes_md


def test_direct_routes_for_notes_and_forget():
    from sanae.agent import direct_route

    tools = {"forget", "start_notes", "stop_notes"}
    assert direct_route("take notes on this lecture", tools) == ("start_notes", {"kind": "lecture"})
    assert direct_route("I'm in a Teams call, can you take notes", tools) == ("start_notes", {"kind": "meeting"})
    assert direct_route("stop taking notes", tools) == ("stop_notes", {})
    assert direct_route("the meeting is over", tools) == ("stop_notes", {})
    assert direct_route("take a note: buy eggs", tools) is None          # quick note: not a recording
    assert direct_route("what were the key points of the lecture", tools) is None
    assert direct_route("take notes", {"forget"}) is None                # tool not available


def test_api_notes_start_stop():
    from fastapi.testclient import TestClient

    from sanae.events import ApprovalBroker, EventBus
    from sanae.server import Runtime, create_app

    class FakeNotes:
        def __init__(self):
            self.started = None

        def start(self, kind, title):
            self.started = (kind, title)
            return type("S", (), {"title": title or "Lecture", "kind": kind})()

        def stop(self):
            pass

        def status(self):
            return {"active": self.started is not None}

    ctx = digest_ctx()
    ctx.notes = FakeNotes()
    bus = EventBus()
    client = TestClient(create_app(Runtime(ctx, bus, ApprovalBroker(bus), lambda t: t, {})), client=LOCAL)
    r = client.post("/api/notes/start", json={"kind": "meeting", "title": "Standup"})
    assert r.status_code == 200 and r.json()["kind"] == "meeting" and ctx.notes.started == ("meeting", "Standup")
    assert client.get("/api/notes/status").json() == {"active": True}
    assert client.post("/api/notes/stop").json() == {"ok": True}


# ---------- phone access (Phase 4) ----------

def test_phone_requests_need_the_token_and_local_ones_dont():
    from sanae.remote import is_local

    assert is_local("127.0.0.1", {}) and is_local("::1", {})
    assert not is_local("127.0.0.1", {"x-forwarded-for": "100.64.0.7"})        # via tailscale serve
    assert not is_local("100.64.0.7", {})
    token = "t" * 40
    phone, rt = api_client(token=token, client=("100.64.0.7", 40000))
    assert phone.get("/api/state").status_code == 401
    assert phone.get("/api/state", headers={"Authorization": "Bearer wrong"}).status_code == 401
    auth = {"Authorization": f"Bearer {token}"}
    assert phone.get("/api/ping", headers=auth).json()["local"] is False
    assert phone.get("/api/pair", headers=auth).status_code == 403            # token never leaves the laptop
    assert phone.get("/api/state", params={"token": token}).status_code == 200
    with pytest.raises(Exception):
        with phone.websocket_connect("/api/ws") as ws:
            ws.receive_json()
    with phone.websocket_connect(f"/api/ws?token={token}") as ws:
        assert ws.receive_json()["kind"] == "hello"
    proxied, _ = api_client(token=token)
    assert proxied.get("/api/facts", headers={"X-Forwarded-For": "100.64.0.7"}).status_code == 401
    no_token, _ = api_client(token="", client=("100.64.0.7", 40000))
    assert no_token.get("/api/state", headers={"Authorization": "Bearer "}).status_code == 401


def test_phone_commands_are_tagged_and_pairing_gives_a_qr(monkeypatch):
    from sanae import remote

    seen = []
    token = "p" * 40
    run = lambda text, source="dashboard": seen.append(source) or "done"
    phone, rt = api_client(run, token=token, client=("100.64.0.7", 40000))
    auth = {"Authorization": f"Bearer {token}"}
    phone.post("/api/command", json={"text": "open youtube"}, headers=auth)
    laptop, _ = api_client(run, token=token)
    laptop.post("/api/command", json={"text": "open youtube"})
    assert seen == ["phone", "dashboard"]
    a = rt.approvals.open("Send it?")
    assert phone.post(f"/api/approvals/{a.id}", json={"approved": True}, headers=auth).json() == {"ok": True}
    assert a.by == "phone"
    monkeypatch.setattr(remote, "tailscale_url", lambda: "https://laptop.tail1234.ts.net")
    laptop, _ = api_client(token=token)
    p = laptop.get("/api/pair").json()
    assert p["url"] == "https://laptop.tail1234.ts.net" and p["token"] == token
    assert p["link"].startswith("max://pair?url=https%3A%2F%2Flaptop") and p["qr_svg"].lstrip().startswith("<")


def test_phone_voice_endpoint_transcribes_and_runs(monkeypatch):
    from sanae.remote import decode_wav, encode_wav

    t = np.arange(0, 1.0, 1 / 44100)
    wav = encode_wav((0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), 44100)
    audio = decode_wav(wav)
    assert abs(len(audio) - 16000) <= 1 and audio.dtype == np.float32
    seen = []
    client, rt = api_client(lambda text, source="dashboard": seen.append((text, source)) or "Opening YouTube.")

    class FakeSTT:
        def whisper(self, a, prompt=None):
            assert abs(len(a) - 16000) <= 1
            return "Hey Sanae, open YouTube."

    rt.ctx.stt = FakeSTT()
    r = client.post("/api/voice", content=wav, headers={"Content-Type": "audio/wav"}).json()
    assert r == {"heard": "open YouTube.", "reply": "Opening YouTube."} and seen == [("open YouTube.", "dashboard")]
    rt.ctx.stt.whisper = lambda a, prompt=None: "Thank you."
    assert client.post("/api/voice", content=wav).json() == {"heard": "", "reply": ""}
    assert client.post("/api/voice", content=b"not audio").status_code == 400


def test_phone_commands_need_a_tap_not_the_laptop_mic():
    import threading as th

    from sanae.events import ApprovalBroker, EventBus, current_origin, set_origin

    bus = EventBus()
    approvals = ApprovalBroker(bus)
    assert approvals.wait("Delete it?", timeout=0.05) is False               # no tap = no
    assert bus.recent[-1]["data"]["by"] == "timeout"
    th.Timer(0.1, lambda: approvals.answer(approvals.pending()[0]["id"], True, "phone")).start()
    assert approvals.wait("Delete it?", timeout=5) is True
    set_origin("phone")
    assert current_origin() == "phone"
    seen = []
    th.Thread(target=lambda: seen.append(current_origin())).start()
    time.sleep(0.05)
    assert seen == ["local"]                                                  # per thread
    set_origin("local")


def test_notes_summary_is_made_once_and_keeps_exact_deadline_quotes(tmp_path):
    from sanae.notes import NotesManager, make_summary, section

    notes_md = ("# Bio 101\n\n## Summary\nCells.\n\n## Key points\n- Mitochondria make ATP\n\n"
                "## Deadlines & dates (exact quotes)\n- [12:03] “Lab report due Friday at 11:59 PM.”\n")
    assert section(notes_md, "Key points") == "- Mitochondria make ATP"
    seen = []

    def summarize(system, text, max_tokens):
        seen.append(text)
        return "## TL;DR\nCells make energy.\n\n## Key takeaways\n- ATP\n\n## To do\n- Lab report due Friday at 5:59 PM"

    out = make_summary(summarize, notes_md)
    assert "exact quotes" not in seen[0]                       # the model never sees (or rewrites) the quotes
    assert out.endswith("## Exact quotes about dates\n- [12:03] “Lab report due Friday at 11:59 PM.”")

    folder = tmp_path / "2026-09-30 Bio 101"
    folder.mkdir()
    (folder / "notes.md").write_text(notes_md, encoding="utf-8")
    ctx = digest_ctx()
    ctx.memory = memory_store()
    mgr = NotesManager(ctx, lambda: None, tmp_path)
    mgr.summarize = summarize
    ctx.notes = mgr
    nid = ctx.memory.add_notes("Bio 101", "lecture", "2026-09-30T10:00", "2026-09-30T11:00", str(folder), "Cells.", 900)
    client, rt = api_client()
    rt.ctx.memory, rt.ctx.notes = ctx.memory, mgr
    assert client.get(f"/api/notes/{nid}").json()["summary_md"] == ""
    first = client.post(f"/api/notes/{nid}/summary").json()["summary_md"]
    assert "## TL;DR" in first and (folder / "summary.md").exists() and len(seen) == 2
    assert client.post(f"/api/notes/{nid}/summary").json()["summary_md"].strip() == first   # cached
    assert len(seen) == 2
    client.post(f"/api/notes/{nid}/summary", params={"refresh": True})
    assert len(seen) == 3
    assert client.get(f"/api/notes/{nid}").json()["summary_md"].startswith("## TL;DR")
    assert client.post("/api/notes/999/summary").status_code == 404


# ---------- live captions ----------

class FakeOnlineRecognizer:
    """Stands in for sherpa_onnx.OnlineRecognizer: 'hears' one word per 0.5 s of loud audio and
    ends a line after 1 s of quiet."""

    def __init__(self):
        self.words = iter("today we cover knowledge graphs and rdf triples assignment two is due friday".split())

    class Stream(dict):
        def accept_waveform(self, sr, x):
            self["last"] = x

    def create_stream(self):
        return self.Stream(text=[], loud=0, quiet=0)

    def is_ready(self, s):
        return False

    def decode_stream(self, s):
        pass

    def get_result(self, s):
        x = s["last"]
        blocks = round(len(x) / 1600)      # 100 ms blocks
        if float(np.sqrt(np.mean(x ** 2))) > 0.01:
            s["loud"] += blocks
            s["quiet"] = 0
            while s["loud"] >= 5:
                s["loud"] -= 5
                s["text"].append(next(self.words, "x"))
        else:
            s["quiet"] += blocks
        return " ".join(s["text"])

    def is_endpoint(self, s):
        return s["quiet"] >= 10 and bool(s["text"])

    def reset(self, s):
        s.update(text=[], loud=0, quiet=0)


def fake_live():
    from sanae.live import LiveModel, LiveTranscriber

    model = LiveModel.__new__(LiveModel)
    model.recognizer = FakeOnlineRecognizer()
    return LiveTranscriber(model)


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        time.sleep(0.02)
    return cond()


def test_live_captions_show_words_then_lines():
    live = fake_live()
    tone = speechy(1.0)
    for i in range(0, len(tone), 1600):
        live.push(tone[i:i + 1600])                      # 100 ms blocks, like the mic
    assert wait_for(lambda: live.view(0)[1] == "today we")
    for _ in range(12):
        live.push(np.zeros(1600, np.float32))            # a pause ends the line
    assert wait_for(lambda: len(live.view(0)[0]) == 1)
    lines, partial = live.view(0)
    assert lines[0].text == "today we" and partial == "" and lines[0].start_s < 0.5
    assert live.view(after_s=lines[0].end_s)[0] == []    # once Whisper has covered it, it's dropped
    live.close()


def test_whisper_text_replaces_live_captions():
    from sanae.notes import NoteSession

    live = fake_live()
    release = threading.Event()

    def transcribe(audio, prompt):
        release.wait(5)                                  # Whisper is slow: hold it back
        return "Today we cover knowledge graphs."

    session = NoteSession("lecture", transcribe, lambda s, t, n: "- notes", title="CS 103", live=live)
    block = speechy(26)
    for i in range(0, len(block), 1600):
        session.push(block[i:i + 1600])
    for _ in range(12):
        session.push(np.zeros(1600, np.float32))
    assert wait_for(lambda: session.live_view()["live"] != [])
    view = session.live_view()
    assert view["final"] == [] and view["captions"] and view["live"][0]["text"].startswith("today we cover")
    assert session.status()["last"].startswith("today we cover")        # overlay/phone see live words
    session.push(np.zeros(16000 * 8, np.float32))         # long enough for the segmenter to cut a chunk
    release.set()
    assert wait_for(lambda: session.live_view()["final"] != [])
    view = session.live_view()
    assert view["final"][0]["text"] == "Today we cover knowledge graphs." and view["live"] == []
    session.finish()


def test_live_captions_real_model():
    from sanae.config import ROOT
    from sanae.live import LiveModel, LiveTranscriber

    d = ROOT / "models/live/sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06"
    wav = d / "test_wavs" / "0.wav"
    if not wav.exists():
        pytest.skip("live caption model not downloaded")
    import wave

    with wave.open(str(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    live = LiveTranscriber(LiveModel(d))
    for i in range(0, len(x), 1600):
        live.push(x[i:i + 1600])
    live.push(np.zeros(16000 * 3, np.float32))
    assert wait_for(lambda: any("country" in l.text.lower() for l in live.view(0)[0]) or "country" in live.view(0)[1].lower())
    live.close()


def test_config_has_no_duplicate_keys():
    """YAML silently keeps only the last of two same-named sections (a second 'notes:' once
    hid every meeting-notes setting)."""
    import yaml

    from sanae.config import ROOT

    class Strict(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        keys = [loader.construct_object(k, deep=deep) for k, _ in node.value]
        dupes = {k for k in keys if keys.count(k) > 1}
        assert not dupes, f"duplicate keys in config.yaml: {dupes}"
        return yaml.SafeLoader.construct_mapping(loader, node, deep)

    Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    cfg = yaml.load((ROOT / "config.yaml").read_text(encoding="utf-8"), Loader=Strict)
    assert cfg["notes"]["file"] and cfg["notes"]["live_model"]


# ---------- commands from the phone open things on the phone ----------

def test_phone_searches_open_on_the_phone_not_the_laptop(tmp_path, monkeypatch):
    from sanae.events import EventBus, set_origin

    opened = []
    monkeypatch.setattr(system_tools.webbrowser, "open", opened.append)
    reg = make_registry(tmp_path)
    reg.context.bus = EventBus()
    set_origin("phone")
    try:
        out = reg.run("open_website", {"target": "cute dog photos", "section": "images"})
    finally:
        set_origin("local")
    assert out == "Here are Google Images results for cute dog photos on your phone."
    assert opened == []                                                       # laptop untouched
    ev = reg.context.bus.recent[-1]
    assert ev["kind"] == "phone_open" and ev["data"]["url"] == "https://www.google.com/search?q=cute+dog+photos&udm=2"
    assert reg.run("open_website", {"target": "youtube.com"}) == "Opened youtube.com."   # laptop commands unchanged
    assert opened == ["https://youtube.com"]


def test_phone_command_redirects_laptop_browser_tools_and_fixes_empty_promises(tmp_path, monkeypatch):
    """The real failure: from the phone Sanae called browser_tabs (no page open), then said
    "I'll open a search for cute dog photos" without opening anything."""
    from sanae.events import EventBus, set_origin

    monkeypatch.setattr(system_tools.webbrowser, "open", lambda url: None)
    reg = make_registry(tmp_path)
    reg.context.bus = EventBus()

    @reg.tool("List or switch the browser's tabs.", params={})
    def browser_tabs():
        raise AssertionError("must not touch the laptop's browser for a phone command")

    llm = FakeLLM([ChatReply("", [ToolCall("browser_tabs", {})]),
                   ChatReply("I'll open a search for cute dog photos right away."),        # empty promise
                   ChatReply("", [ToolCall("open_website", {"target": "cute dog photos", "section": "images"})]),
                   ChatReply("Here are cute dog photos on your phone.")])     # "search ... and show me" = two steps
    agent = Agent(llm, reg, "fast", "planner")
    set_origin("phone")
    try:
        answer = agent.handle("can you search for some cute dog photos and show me?")
    finally:
        set_origin("local")
    assert "on your phone" in answer
    assert "can't see the laptop's browser" in llm.calls[1]["messages"][-1]["content"]
    assert "System check" in llm.calls[2]["messages"][-1]["content"]
    assert reg.context.bus.recent[-1]["kind"] == "phone_open"


# ---------- Sanae acting on the phone (phone.py, tools/phone.py) ----------

def phone_setup(tmp_path, answer=None):
    """A registry with phone tools and a fake phone that answers every action."""
    from sanae.events import EventBus
    from sanae.phone import PhoneBridge
    from sanae.tools import phone as phone_tools

    bus = EventBus()
    reg = make_registry(tmp_path)
    reg.context.phone = bridge = PhoneBridge(bus, timeout=3)
    phone_tools.register(reg)
    sent = []
    if answer is not None:
        bridge.connected(+1)
        real_publish = bus.publish

        def publish(kind, data=None):
            ev = real_publish(kind, data)
            if kind == "phone_action":
                sent.append(data)
                threading.Thread(target=lambda: bridge.resolve(data["id"], answer(data))).start()
            return ev
        bus.publish = publish
    return reg, bridge, sent


def test_phone_tools_send_actions_and_speak_the_phones_answer(tmp_path):
    reg, bridge, sent = phone_setup(tmp_path, lambda d: {"ok": True, "message": f"did {d['action']}"})
    bridge.set_state({"apps": [{"label": "Instagram", "package": "com.instagram.android"},
                               {"label": "WhatsApp", "package": "com.whatsapp"}]})
    assert reg.run("phone_open_app", {"name": "insta"}) == "did open_app"
    assert sent[-1]["params"] == {"name": "insta", "package": "com.instagram.android"}
    assert reg.run("phone_timer", {"duration": "an hour and 30 minutes", "label": "pasta"}) == "did timer"
    assert sent[-1]["params"] == {"seconds": 5400, "label": "pasta"}
    reg.run("phone_alarm", {"time": "tomorrow at 6:45am"})
    assert (sent[-1]["params"]["hour"], sent[-1]["params"]["minute"]) == (6, 45)
    reg.run("phone_message", {"contact": "Mom", "text": "running late", "app": "telegram"})
    assert sent[-1]["params"] == {"contact": "Mom", "text": "running late", "app": "sms"}
    assert "phone_calendar_add" not in reg.tools          # events go to Sanae's calendar (add_event) now
    assert reg.tools["phone_call"].risky and not reg.tools["phone_message"].risky   # texts: the user taps Send
    reg.run("phone_notifications", {"app": "all"})
    assert sent[-1]["params"] == {"app": "", "count": 8}


def test_phone_tools_when_the_phone_is_away(tmp_path):
    from sanae.tools.phone import parse_duration

    reg, bridge, _ = phone_setup(tmp_path)
    assert reg.run("phone_status", {}) == "Your phone isn't connected to Sanae right now."
    bridge.connected(+1)
    bridge.timeout = 0.05
    assert "didn't answer in time" in reg.run("phone_status", {})
    assert reg.run("phone_timer", {"duration": "soon"}).startswith("Error")
    assert parse_duration("10 minutes") == 600 and parse_duration("90s") == 90 and parse_duration("half an hour") == 1800
    assert parse_duration("5") == 300


def test_phone_api_results_state_and_connection_count():
    from sanae.events import EventBus
    from sanae.phone import PhoneBridge

    token = "q" * 40
    phone, rt = api_client(token=token, client=("100.64.0.7", 40000))
    rt.ctx.phone = bridge = PhoneBridge(rt.bus, timeout=3)
    auth = {"Authorization": f"Bearer {token}"}
    with phone.websocket_connect(f"/api/ws?token={token}") as ws:
        ws.receive_json()
        assert bridge.online
        assert phone.post("/api/phone/state", json={"apps": [{"label": "Maps", "package": "com.google.maps"}], "battery": 80},
                          headers=auth).json() == {"ok": True, "apps": 1}
        assert bridge.apps() == {"maps": "com.google.maps"}
        out = {}
        t = threading.Thread(target=lambda: out.update(bridge.request("status")))
        t.start()
        while True:                                               # the phone hears the action over the socket
            ev = ws.receive_json()
            if ev["kind"] == "phone_action":
                break
        assert phone.post("/api/phone/result", json={"id": ev["data"]["id"], "ok": True, "message": "Battery 80%."},
                          headers=auth).json() == {"ok": True}
        t.join(3)
        assert out == {"ok": True, "message": "Battery 80%."}
    assert not bridge.online
    assert phone.post("/api/phone/result", json={"id": 999, "message": "late"}, headers=auth).status_code == 404


# ---------- speaking while thinking, and interrupting (speech.py) ----------

def test_sentences_are_spoken_as_they_arrive_and_the_rest_at_the_end():
    from sanae.speech import SentenceSpeaker

    said = []
    s = SentenceSpeaker(lambda t: said.append(t))
    s.feed(None)
    for piece in ["Two things are due", " this week. The project", " report is Friday at 11:59 PM.", " Also a qu", "iz on Monday"]:
        s.feed(piece)
    s._q.join()
    assert said == ["Two things are due this week.", "The project report is Friday at 11:59 PM."]   # spoken early
    assert s.finish("Two things are due this week. The project report is Friday at 11:59 PM. Also a quiz on Monday") is None
    assert said[-1] == "Also a quiz on Monday"                                            # only the rest


def test_a_claimed_action_halts_streaming_so_the_agent_can_correct_it():
    from sanae.speech import SentenceSpeaker

    said = []
    s = SentenceSpeaker(lambda t: said.append(t))
    s.feed(None)
    s.feed("Sure. I'll remind you tomorrow. Anything else? ")
    s._q.join()
    assert said == ["Sure."]
    s.feed(None)                                     # the nudged second attempt
    s.feed("Okay, I'll remind you tomorrow at 7 AM.")
    s.finish("Okay, I'll remind you tomorrow at 7 AM.")
    assert said[-1] == "Okay, I'll remind you tomorrow at 7 AM."


def test_a_streamed_reply_in_tiny_pieces_is_spoken_once():
    # "How you doing?" (2026-10-20): a lone " " piece was dropped by the tag filter, the spoken
    # words no longer matched the final reply, and finish() said the whole reply again
    import datetime as dt

    from sanae.speech import SentenceSpeaker
    from sanae.tags import TagFilter, parse
    from sanae.timesense import TimeFilter

    raw = "[thinking] I'm doing great, thanks! Just had a quick nap. How about you? Did you eat breakfast? \U0001F60F"
    for size in (1, 2, 3, 5):
        said = []
        s = SentenceSpeaker(lambda t: said.append(t))
        f = TimeFilter(TagFilter(s.feed), clock=lambda: dt.datetime(2026, 10, 20, 8, 39))
        f(None)
        for i in range(0, len(raw), size):
            f(raw[i:i + size])
        s.finish(parse(raw).text)
        assert " ".join(said) == "I'm doing great, thanks! Just had a quick nap. How about you? Did you eat breakfast?", size


def test_emphasis_is_kept_and_a_reply_is_never_said_twice():
    # "You missed me? I was just *thinking* about you!" (2026-10-20): streamed, the stars came in
    # separate pieces and "thinking" was spoken; the final clean-up took it for an aside and dropped
    # it, so the two didn't match and the whole reply was said again
    import datetime as dt

    from sanae.speech import SentenceSpeaker, unspoken
    from sanae.tags import TagFilter, parse
    from sanae.timesense import TimeFilter

    raw = "[happy] You missed me? I was just *thinking* about you! *giggles* What's next? Anime or something fun?"
    clean = "You missed me? I was just thinking about you! What's next? Anime or something fun?"
    assert parse(raw).text == clean
    assert parse("*tilts head* Really?").text == "Really?"
    for size in (1, 2, 3, 5, 8):
        said = []
        s = SentenceSpeaker(lambda t: said.append(t))
        f = TimeFilter(TagFilter(s.feed), clock=lambda: dt.datetime(2026, 10, 20, 18, 29))
        f(None)
        for i in range(0, len(raw), size):
            f(raw[i:i + size])
        s.finish(parse(raw).text)
        assert " ".join(said) == clean, size
    # spoken words that differ a little from the final answer: only the unspoken end
    assert unspoken("You missed me? I was just about you! What's next?", "You missed me? I was just thinking about you!") == "What's next?"
    assert unspoken("Totally different reply here.", "You missed me? I was just thinking about you!") == "Totally different reply here."


def test_interrupting_stops_the_remaining_sentences():
    from sanae.speech import SentenceSpeaker

    said = []
    s = SentenceSpeaker(lambda t: said.append(t) or ("stop" if len(said) == 1 else None))
    s.feed(None)
    s.feed("First sentence. Second sentence. Third ")
    assert s.finish("First sentence. Second sentence. Third sentence.") == "stop"
    assert said == ["First sentence."]


def test_watch_for_interrupt_ignores_sanaes_own_words():
    from sanae.speech import watch_for_interrupt

    frames = iter(["a", "b", "c", "d"])
    heard = iter([None, "STOP", None, "HEY_SANAE"])
    read = lambda timeout: next(frames, None)
    assert watch_for_interrupt(read, lambda f: next(heard), 5, "Take the bus to the next stop.") == "wake"
    frames, heard = iter(["a"]), iter(["SANAE_STOP"])
    assert watch_for_interrupt(lambda t: next(frames, None), lambda f: next(heard), 5, "Here you go.") == "stop"
    assert watch_for_interrupt(lambda t: None, lambda f: None, 0.05, "Quiet.") is None


def test_converse_after_an_interrupt():
    from sanae.main import converse

    replies = iter(["Here's a long answer?", "Sure."])
    cut = iter(["wake", None])
    log = []
    n = converse("tell me about rdf", lambda t: log.append(t) or next(replies), lambda: "should not be used",
                 interrupted=lambda: next(cut), listen_new=lambda: "actually what's the weather")
    assert n == 2 and log == ["tell me about rdf", "actually what's the weather"]
    n = converse("tell me about rdf", lambda t: "Is that all?", lambda: "unused", interrupted=lambda: "stop")
    assert n == 1


def test_llm_streams_text_and_still_returns_tool_calls(monkeypatch):
    import json as _json

    from sanae import llm as L

    lines = [{"message": {"content": "Hello"}}, {"message": {"content": " there."}},
             {"message": {"content": "", "tool_calls": [{"function": {"name": "web_search", "arguments": {"query": "x"}}}]}},
             {"done": True, "message": {"content": ""}}]

    class R:
        status_code = 200
        text = ""
        def iter_lines(self):
            return [_json.dumps(l).encode() for l in lines]

    monkeypatch.setattr(L.requests, "post", lambda url, json, timeout, **kw: R())
    pieces = []
    reply = L.OllamaClient("http://x").chat("m", [], on_text=pieces.append)
    assert pieces == ["Hello", " there."] and reply.content == "Hello there."
    assert reply.tool_calls[0].name == "web_search"


def test_agent_does_not_stream_while_a_requested_tool_is_pending():
    reg, ctx = memory_registry()
    agent = Agent(FakeLLM([]), reg, "fast", "planner")
    assert agent._stream_for(print, "remind me about gym tomorrow", []) is None
    assert agent._stream_for(print, "what is rdf", []) is print
    assert agent._stream_for(None, "what is rdf", []) is None


# ---------- deadline countdown (alerts.py) ----------

def test_deadline_alerts_fire_once_per_window_and_for_classes():
    import datetime as dt

    from sanae.alerts import DeadlineAlerts
    from sanae.canvas import CanvasItem

    now = dt.datetime(2026, 10, 1, 9, 0)
    lab = CanvasItem("assignment", "Lab 4", "CS 101", dt.datetime(2026, 10, 1, 23, 59), True, url="https://canvas/lab4")
    quiz = CanvasItem("assignment", "Quiz 3", "CS 102", dt.datetime(2026, 10, 2, 10, 0), False)
    cls = CanvasItem("class", "Intro Topics", "CS 103", dt.datetime(2026, 10, 1, 9, 8), False, link="https://school.zoom.us/j/1")

    class Feed:
        def between(self, start, end, kind=None):
            return [i for i in (lab, quiz, cls) if start <= i.start < end]

    ctx = Context(load_config(), FakeLLM([]))
    ctx.memory, ctx.canvas = memory_store(), Feed()
    events = []
    alerts = DeadlineAlerts(ctx, lambda kind, data: events.append(data))
    out = alerts.check(now)
    titles = sorted(a["title"] for a in out)
    assert titles == ["Class in 8 minutes: Intro Topics", "Due in 15 hours: Lab 4"]
    cls_alert = next(a for a in out if a["kind"] == "class")
    assert cls_alert["url"] == "https://school.zoom.us/j/1" and "tap to join" in cls_alert["text"]
    assert alerts.check(now + dt.timedelta(minutes=1)) == []                       # once only
    later = alerts.check(dt.datetime(2026, 10, 1, 21, 30))                          # 2.5 h before the lab
    assert sorted(a["title"] for a in later) == ["Due in 12 hours: Quiz 3", "Due in 2 hours: Lab 4"]
    late = DeadlineAlerts(ctx, lambda k, d: None)                                   # laptop was off: only the 3 h alert
    ctx.memory.set("alerts_sent", "[]")
    assert [a["title"] for a in late.check(dt.datetime(2026, 10, 2, 8, 0)) if "Quiz" in a["title"]] == ["Due in 2 hours: Quiz 3"]


# ---------- privacy page ----------

def test_privacy_page_lists_exports_and_deletes(tmp_path):
    import io
    import zipfile

    client, rt = api_client()
    cfg = rt.ctx.cfg
    cfg["notes"] = {**(cfg.get("notes") or {}), "folder": str(tmp_path / "Sanae Notes"), "file": str(tmp_path / "quick.md")}
    cfg["browser"] = {**(cfg.get("browser") or {}), "profile_dir": str(tmp_path / "profile")}
    m = rt.ctx.memory
    m.add_fact("Alex's exam is on Friday")
    m.log_turn("hi", "Hello!")
    folder = tmp_path / "Sanae Notes" / "2026-10-01 Lecture"
    folder.mkdir(parents=True)
    (folder / "notes.md").write_text("# Lecture\n- RDF", encoding="utf-8")
    m.add_notes("Lecture", "lecture", "2026-10-01T10:00", "2026-10-01T11:00", str(folder), "RDF", 10)
    (tmp_path / "quick.md").write_text("- buy milk", encoding="utf-8")
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "Cookies").write_bytes(b"x" * 10)

    cats = {c["id"]: c for c in client.get("/api/privacy").json()}
    assert cats["facts"]["amount"] == "1 facts" and cats["conversations"]["amount"] == "1 turns"
    z = zipfile.ZipFile(io.BytesIO(client.get("/api/privacy/export").content))
    names = z.namelist()
    assert "facts.json" in names and "notes/2026-10-01 Lecture/notes.md" in names and "quick_notes.md" in names
    assert not any("Cookies" in n or "token" in n for n in names)                   # secrets stay out
    assert "Friday" in z.read("facts.json").decode()

    assert client.post("/api/privacy/delete/facts", json={"confirm": "nope"}).status_code == 400
    assert client.post("/api/privacy/delete/facts", json={"confirm": "facts"}).json()["ok"]
    assert m.count("facts") == 0 and m.search_facts("exam") == []
    client.post("/api/privacy/delete/notes", json={"confirm": "notes"})
    assert not folder.exists() and m.count("notes") == 0
    client.post("/api/privacy/delete/browser", json={"confirm": "browser"})
    assert not (tmp_path / "profile").exists()
    assert client.post("/api/privacy/delete/bogus", json={"confirm": "bogus"}).status_code == 404
    phone, _ = api_client(token="t" * 40, client=("100.64.0.7", 40000))
    assert phone.get("/api/privacy", headers={"Authorization": "Bearer " + "t" * 40}).status_code == 403   # never over the phone link


# ---------- ask your course material (course.py) ----------

def make_course_files(root):
    import docx
    import pymupdf
    from pptx import Presentation

    (root / "CS 103").mkdir(parents=True)
    (root / "CS 101").mkdir()
    pdf = pymupdf.open()
    for text in ["Week 1 overview of the semantic web course.",
                 "SPARQL OPTIONAL keeps results even when the optional pattern has no match, leaving the variable unbound."]:
        pdf.new_page().insert_text((72, 72), text)
    pdf.save(str(root / "CS 103" / "Lab 3 handout.pdf"))
    pres = Presentation()
    s = pres.slides.add_slide(pres.slide_layouts[1])
    s.shapes.title.text = "RDF Schema"
    s.placeholders[1].text = "RDFS adds classes, subclasses and domain and range constraints to RDF vocabularies."
    pres.save(str(root / "CS 103" / "Lecture 5.pptx"))
    d = docx.Document()
    d.add_paragraph("The midterm covers decision trees, entropy and information gain, and k-means clustering.")
    d.save(str(root / "CS 101" / "Midterm review.docx"))
    (root / "CS 101" / "~$Midterm review.docx").write_text("lock file", encoding="utf-8")   # Word's temp file: skipped


def test_course_library_indexes_files_and_answers_with_sources(tmp_path):
    from sanae.course import CourseLibrary

    make_course_files(tmp_path / "Course")
    lib = CourseLibrary([tmp_path / "Course"], WordEmbedder(), tmp_path / "course.db")
    assert lib.scan()["indexed"] == 3
    hit = lib.search("what does SPARQL OPTIONAL do when there is no match")[0]
    assert (hit.file, hit.page, hit.course) == ("Lab 3 handout.pdf", "p. 2", "CS 103")
    assert lib.search("rdfs domain range constraints")[0].page == "slide 1"
    assert lib.search("midterm entropy information gain", course="CS 101")[0].file == "Midterm review.docx"
    assert lib.scan()["indexed"] == 0                                  # unchanged files aren't re-read
    (tmp_path / "Course" / "CS 101" / "Midterm review.docx").unlink()
    assert lib.scan()["removed"] == 1
    assert lib.stats()["courses"] == {"CS 103": 2}
    lib.clear()
    assert lib.search("SPARQL") == [] and lib.stats()["passages"] == 0


def test_course_tools_give_the_model_cited_passages(tmp_path):
    from sanae.course import CourseLibrary
    from sanae.tools import course as course_tools

    make_course_files(tmp_path / "Course")
    reg = make_registry(tmp_path)
    reg.context.course = lib = CourseLibrary([tmp_path / "Course"], WordEmbedder(), tmp_path / "course.db")
    course_tools.register(reg)
    assert reg.run("course_files", {}).startswith("No course files yet")
    lib.scan()
    out = reg.run("course_search", {"question": "SPARQL OPTIONAL no match"})
    assert "[Lab 3 handout.pdf, p. 2]" in out and "say where it's from" in out
    assert reg.run("course_files", {}) == "I have 3 files: 1 for CS 101, 2 for CS 103."
    assert reg.run("course_search", {"question": "photosynthesis in plants"}).startswith("Nothing in the course files")


# ---------- only the tools a request needs (toolselect.py) ----------

def test_tool_selection_keeps_requests_small_and_relevant(tmp_path):
    from sanae.events import EventBus
    from sanae.phone import PhoneBridge
    from sanae.tools import phone as phone_tools
    from sanae.tools.memory import register as memory_register
    from sanae.toolselect import CORE, ToolSelector

    reg, ctx = memory_registry()
    system_tools.register(reg)
    ctx.phone = PhoneBridge(EventBus())
    phone_tools.register(reg)
    sel = ToolSelector(reg, WordEmbedder())
    total = len(reg.tools)
    names = sel.select("set a timer for 10 minutes on my phone")
    assert "phone_timer" in names and "phone_call" in names and len(names) < total   # the whole phone family
    assert names[:len([c for c in CORE if c in reg.tools])] == [c for c in CORE if c in reg.tools]
    assert "set_reminder" in sel.select("remind me to call mom at 6")
    assert "browser_click" not in sel.select("what's the weather")
    follow = sel.select("the second one", recent_tools=["phone_message"])
    assert "phone_message" in follow                                                   # follow-ups keep their tools
    assert len(ToolSelector(reg, WordEmbedder(), max_tools=8).select("remind me on my phone to remember things")) <= 15


def test_context_overflow_retries_without_old_conversation():
    from sanae.llm import OllamaError

    class Overflow(FakeLLM):
        def chat(self, model, messages, tools=None, **kw):
            if len(messages) > 3:
                self.calls.append({"messages": list(messages)})
                raise OllamaError("Ollama error 400: request (4315 tokens) exceeds the available context size")
            return super().chat(model, messages, tools)

    reg, ctx = memory_registry()
    llm = Overflow([ChatReply("Hi again.")])
    agent = Agent(llm, reg, "fast", "planner")
    agent.history = [[{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "ok"}]]
    agent._last_turn = time.monotonic()
    assert agent.handle("hello") == "Hi again."


# ---------- read my screen (tools/screen.py) ----------

def test_read_screen_reads_text_and_keeps_nothing(tmp_path, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows OCR")
    from PIL import Image, ImageDraw, ImageFont

    from sanae.tools import screen as screen_tools

    img = Image.new("RGB", (1000, 220), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype("consola.ttf", 26)
    d.text((20, 40), "TypeError: unsupported operand type(s) for +: 'int' and 'str'", fill="black", font=font)
    d.text((20, 110), 'File "app.py", line 12, in total', fill="black", font=font)
    monkeypatch.setattr(screen_tools, "capture", lambda whole=False: (img, "app.py - VS Code"))   # never the real screen
    reg = make_registry(tmp_path)
    screen_tools.register(reg)
    out = reg.run("read_screen", {"question": "what does this error mean?"})
    assert "unsupported operand" in out and "app.py - VS Code" in out and "what does this error mean?" in out
    monkeypatch.setattr(screen_tools, "capture", lambda whole=False: (Image.new("RGB", (400, 200), "white"), "blank"))
    assert reg.run("read_screen", {"question": "?"}) == "I couldn't find any text in that window."


# ---------- command accuracy test (evals.py) ----------

def test_eval_cases_load_and_judging():
    from sanae.evals import judge, load_cases, summarize

    cases = load_cases()
    assert len(cases) >= 80 and all(t["expect"] for c in cases for t in c["turns"])
    turn = {"expect": ["phone_timer"], "args": {"duration": "10"}}
    assert judge(turn, [("phone_timer", {"duration": "10 minutes"})]) == (True, True, "")
    assert judge(turn, [("phone_timer", {"duration": "5 minutes"})])[:2] == (True, False)
    assert judge(turn, [("set_reminder", {})])[0] is False
    assert judge({"expect": ["none"], "args": {}}, []) == (True, True, "")
    s = summarize([{"category": "a", "tool_ok": True, "args_ok": False, "seconds": 1.0, "prompt_tokens": 100},
                   {"category": "a", "tool_ok": True, "args_ok": True, "seconds": 3.0, "prompt_tokens": 300}])
    assert s["tool_accuracy"] == 1.0 and s["full_accuracy"] == 0.5 and s["categories"]["a"] == {"n": 2, "tool": 2, "full": 1}


# ---------- voice ID (voiceid.py) ----------

def test_voice_id_tells_the_user_from_other_voices(tmp_path):
    from sanae.config import ROOT
    from sanae.tts import PiperTTS
    from sanae.voiceid import VoiceID

    model = ROOT / "models/voiceid/eres2net_en_voxceleb.onnx"
    voice = ROOT / "models/piper/en_US-ryan-medium.onnx"
    if not (model.exists() and voice.exists()):
        pytest.skip("voice ID model or Piper voice not downloaded")
    ryan = PiperTTS(str(voice))

    def say(line, pitch=1.0):
        a, sr = ryan.synthesize(line)
        t = np.arange(0, len(a) / sr, 1 / 16000)
        x = np.interp(t * pitch, np.arange(len(a)) / sr, a).astype(np.float32)   # resampled = a different-sounding voice
        return x

    vid = VoiceID(model, tmp_path / "profile.npy")
    assert vid.score(say("hello there")) is None and not vid.enrolled            # nothing enrolled yet
    vid.enroll([say(l) for l in ["What's due this week?", "Remind me to call mom tomorrow.", "Open Spotify please.",
                                 "Take notes for this lecture."]])
    assert vid.enrolled and (tmp_path / "profile.npy").exists()
    assert vid.is_owner(say("Shut down the laptop now.")) is True
    assert vid.score(np.zeros(4000, np.float32)) is None                          # too short to judge
    assert VoiceID(model, tmp_path / "profile.npy").enrolled                      # saved and reloaded
    vid.forget()
    assert not vid.enrolled and not (tmp_path / "profile.npy").exists()


def test_read_screen_drops_the_text_cursor_and_window_furniture():
    from sanae.tools.screen import clean, merge_reads

    # The real report: Notepad said "hey how are you" and Sanae read "hey how are youl"
    first = ["File Edit View", "hey how are youl", "Ln 1, Col 16 100% Windows (CRLF) UTF-8"]
    second = ["File Edit View", "hey how are you", "Ln 1, Col 16 100% Windows (CRLF) UTF-8"]
    assert clean(merge_reads(first, second)) == ["hey how are you"]
    assert clean(merge_reads(second, first)) == ["hey how are you"]        # cursor in the other read
    assert merge_reads(["I love it all"], ["I love it al"]) == ["I love it al"]   # (only one stray char is trimmed)
    assert clean(["Run the file", "Edit View Help"]) == ["Run the file"]   # real sentences with menu words stay


# ---------- natural voice with Piper fallback (tts.py) ----------

def test_natural_voice_trims_padding_and_falls_back_to_piper():
    import concurrent.futures as cf

    from sanae.tts import NaturalVoice, trim_silence

    sr = 24000
    speech = np.concatenate([np.zeros(sr), 0.3 * np.ones(sr // 2, np.float32), np.zeros(sr)]).astype(np.float32)
    trimmed = trim_silence(speech, sr)
    assert abs(len(trimmed) - (sr // 2 + 2 * int(0.06 * sr))) <= 2           # Ava's padding removed
    assert len(trim_silence(np.zeros(sr, np.float32), sr)) == 0

    class Piper:
        def synthesize(self, text):
            return np.ones(10, np.float32), 22050

    v = NaturalVoice.__new__(NaturalVoice)                                  # no real voice or network in tests
    v.name, v.fallback, v.timeout_s = "Microsoft Ava Online", Piper(), 1.0
    v._pool = cf.ThreadPoolExecutor(max_workers=1)
    v._speak = lambda text: (np.full(100, 0.5, np.float32), 24000)
    assert v.synthesize("hi")[1] == 24000                                   # online voice when it works
    v._speak = lambda text: (_ for _ in ()).throw(OSError("no internet"))
    assert v.synthesize("hi")[1] == 22050                                   # Piper when offline
    v._speak = lambda text: (np.zeros(0, np.float32), 24000)
    assert v.synthesize("hi")[1] == 22050                                   # Piper on silence


# ---------- Gmail (mail.py, tools/mail.py) ----------

RAW_MAIL = (b"From: Prof. Jane Smith <jsmith@school.edu>\r\nTo: alex@example.com\r\nSubject: Midterm moved\r\n"
            b"Date: Thu, 01 Oct 2026 09:30:00 -0700\r\nMessage-ID: <abc123@school.edu>\r\n"
            b"Content-Type: multipart/alternative; boundary=b1\r\n\r\n"
            b"--b1\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nHi all,\nThe midterm is moved to Monday at 10am.\n\n"
            b"On Wed, Sep 30, 2026 at 9:00 AM Someone <x@y.com> wrote:\n> old quoted text\n"
            b"--b1\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>Hi all,</p><p>The midterm is moved.</p>\r\n--b1--\r\n")


class FakeGmail:
    def __init__(self, mails):
        self.mails, self.sent, self.archived, self.read, self.queries = mails, [], [], [], []

    def search(self, query="is:unread in:inbox", limit=5, account=None):
        self.queries.append(query)
        return self.mails[:limit]

    def get(self, msgid, account=None):
        return next((m for m in self.mails if m.msgid == msgid), None)

    def send(self, to, subject, body, reply_to=None, account=None):
        self.sent.append((to, subject, body, reply_to.message_id if reply_to else None))

    def archive(self, msgid, account=None):
        self.archived.append(msgid)

    def mark_read(self, msgid, account=None):
        self.read.append(msgid)

    def contacts(self, name, limit=40):
        return [(m.sender, m.address) for m in self.mails if name.lower() in m.sender.lower()]


def test_mail_parsing_prefers_plain_text_and_drops_quotes():
    from sanae.mail import html_to_text, parse

    m = parse(RAW_MAIL, "111", "222", flags="", labels="\\Important \\Inbox")
    assert (m.sender, m.address, m.subject) == ("Prof. Jane Smith", "jsmith@school.edu", "Midterm moved")
    assert "moved to Monday at 10am" in m.body and "old quoted text" not in m.body
    assert m.unread and m.important and m.message_id == "<abc123@school.edu>" and m.link.endswith("/de")
    text = html_to_text("<p>Hi&amp;there</p><script>x()</script><br>Bye")
    assert "Hi&there" in text and "Bye" in text and "x()" not in text


def test_mail_tools_check_read_reply_archive(tmp_path):
    from sanae.mail import parse
    from sanae.tools import mail as mail_tools

    m1 = parse(RAW_MAIL, "111", "222", "", "\Important")
    m2 = parse(RAW_MAIL.replace(b"Prof. Jane Smith <jsmith@school.edu>", b"Canvas <notifications@instructure.com>")
               .replace(b"Midterm moved", b"New grade posted"), "333", "444")
    reg = make_registry(tmp_path)
    reg.context.mail = gmail = FakeGmail([m1, m2])
    mail_tools.register(reg)
    out = reg.run("mail_check", {})
    assert "1. From Prof. Jane Smith" in out and "[important]" in out and "2. From Canvas" in out
    assert "moved to Monday" in reg.run("mail_read", {"which": "the first one"})
    assert "New grade" in reg.run("mail_read", {"which": "canvas"})
    reg.run("mail_reply", {"which": "1", "text": "Thanks, noted!"})
    assert gmail.sent == [("jsmith@school.edu", "Re: Midterm moved", "Thanks, noted!", "<abc123@school.edu>")]
    assert reg.tools["mail_reply"].risky and reg.tools["mail_send"].risky and not reg.tools["mail_archive"].risky
    assert reg.run("mail_archive", {"which": "second"}) == "Archived the email from Canvas." and gmail.archived == ["333"]
    assert reg.run("mail_mark_read", {"which": "all"}) == "Marked 2 emails as read."
    assert reg.run("mail_send", {"to": "jane", "body": "Hi"}) == "Sent your email to jane." and gmail.sent[-1][0] == "jsmith@school.edu"
    gmail.mails = []
    assert reg.run("mail_check", {}) == "No unread email in your inbox."


def test_mail_alerts_for_chosen_senders_and_digest_section():
    from sanae.alerts import MailAlerts
    from sanae.digest import gather, spoken
    from sanae.mail import parse

    m1 = parse(RAW_MAIL, "111", "222", "", "\Important")
    ctx = Context(load_config(), FakeLLM([]))
    ctx.memory = memory_store()
    ctx.mail = FakeGmail([m1])
    events = []
    alerts = MailAlerts(ctx, lambda k, d: events.append(d), ["@school.edu"])
    assert alerts.check() == []                                  # first run: existing mail doesn't alert
    m2 = parse(RAW_MAIL.replace(b"Midterm moved", b"Office hours today"), "555", "666")
    ctx.mail.mails = [m2, m1]
    assert [a["title"] for a in alerts.check()] == ["Email from Prof. Jane Smith"] and events[-1]["text"] == "Office hours today"
    assert alerts.check() == []                                  # once only
    restarted = MailAlerts(ctx, lambda k, d: None, ["@school.edu"])
    ctx.mail.mails = [parse(RAW_MAIL.replace(b"Midterm moved", b"Grades out"), "777", "888"), m2, m1]
    assert len(restarted.check()) == 1                           # mail that came while Sanae was off still alerts
    ctx.mail.mails = [m1]
    plan = gather(ctx)
    assert plan.mail and "Important email: Prof. Jane Smith about Midterm moved." in spoken(plan)


def test_three_mailboxes_merge_and_reply_from_the_right_one():
    from sanae.mail import MailAccounts, accounts_from_secrets, parse

    assert accounts_from_secrets({"personal": {"address": "you@gmail.com", "app_password": "xxxx xxxx xxxx xxxx"}}) is None
    accts = accounts_from_secrets({"personal": {"address": "alex@example.com", "app_password": "abcd efgh ijkl mnop"},
                                   "university": {"address": "you@school.edu", "app_password": "xxxx xxxx xxxx xxxx"},
                                   "max": {"address": "max.helper@example.com", "app_password": "qrst uvwx yzab cdef"}})
    assert accts.names == ["personal", "max"]                     # the untouched placeholder slot is skipped
    assert accounts_from_secrets({"address": "a@b.com", "app_password": "real pass word here"}).names == ["personal"]

    uni = parse(RAW_MAIL, "1", "2")
    home = parse(RAW_MAIL.replace(b"Thu, 01 Oct 2026 09:30", b"Thu, 01 Oct 2026 11:30")
                 .replace(b"Midterm moved", b"Dinner tonight?"), "3", "4")
    clients = {"personal": FakeGmail([home]), "university": FakeGmail([uni])}
    multi = MailAccounts(clients)
    found = multi.search()
    assert [(m.subject, m.account) for m in found] == [("Dinner tonight?", "personal"), ("Midterm moved", "university")]
    assert [m.account for m in multi.search(account="school")] == ["university"]
    multi.send("jsmith@school.edu", "Re: Midterm moved", "Thanks", reply_to=found[1])
    assert clients["university"].sent and not clients["personal"].sent      # replies go out from where the mail came
    multi.send("x@y.com", "Hi", "Hello", account="uni")
    assert len(clients["university"].sent) == 2


# ---------- notes from course documents (docnotes.py) ----------

class FakeSummarizer:
    """Stands in for the model: records each call and returns recognisable notes."""

    def __init__(self):
        self.calls = []

    def __call__(self, system, text, max_tokens):
        self.calls.append((system, text))
        if "Combine" in system:
            return "## Summary\nNotes about " + " ".join(text.split()[:4]) + "\n\n## Key points\n- point"
        return f"- section notes {len(self.calls)}"


def test_document_sections_group_pages_and_split_long_ones():
    from sanae.docnotes import sections

    items = [("p. 1", "a " * 300), ("p. 2", "b " * 300), ("p. 3", "c " * 900)]
    out = sections(items, words=700)
    assert [w for w, _ in out] == ["p. 1-3", "p. 3", "p. 3"]
    assert [len(t.split()) for _, t in out] == [700, 700, 100]
    assert sections([("slide 1", "one two three")]) == [("slide 1", "one two three")]


def test_document_notes_read_the_whole_file_and_quote_deadlines(tmp_path):
    from sanae.docnotes import TEXT_FILE, save, write_notes

    f = tmp_path / "Syllabus.txt"
    f.write_text("# Intro\n" + "Semantic web basics and RDF triples. " * 150 +
                 "\n# Grading\nThe final project is due Friday, December 5 at 11:59 PM.\n", encoding="utf-8")
    fake = FakeSummarizer()
    r = write_notes(f, fake, course="CS 103")
    assert len(fake.calls) >= 3                                    # map per section, then combine
    assert r.notes_md.startswith("## Summary")
    assert "[section 2] “The final project is due Friday, December 5 at 11:59 PM.”" in r.notes_md
    folder = save(r, tmp_path / "Notes", __import__("datetime").datetime(2026, 10, 5, 13, 0))
    assert folder.name == "2026-10-05 1300 Syllabus"
    assert "*Document · CS 103 · Syllabus.txt" in (folder / "notes.md").read_text(encoding="utf-8")
    assert "Semantic web basics" in (folder / TEXT_FILE).read_text(encoding="utf-8")
    assert save(r, tmp_path / "Notes", __import__("datetime").datetime(2026, 10, 5, 13, 0)).name.endswith("(2)")
    (tmp_path / "empty.txt").write_text("   ", encoding="utf-8")
    with pytest.raises(ValueError):
        write_notes(tmp_path / "empty.txt", fake)


def test_summarize_course_files_tool_writes_notes_in_the_background(tmp_path):
    from sanae.course import CourseLibrary
    from sanae.docnotes import DocNotes
    from sanae.tools import course as course_tools

    make_course_files(tmp_path / "Course")
    (tmp_path / "Course" / "Week 1.txt").write_text("Introduction to the course and the grading policy for labs.",
                                                    encoding="utf-8")
    reg, ctx = memory_registry()
    notes_dir = tmp_path / "Sanae Notes"
    lib = CourseLibrary([tmp_path / "Course", notes_dir], WordEmbedder(), tmp_path / "course.db")
    events, finished = [], threading.Event()
    ctx.course = lib
    ctx.docnotes = DocNotes(ctx, lib, notes_dir, FakeSummarizer(), on_event=lambda k, d: events.append((k, d)),
                            on_done=lambda done, failed: finished.set())
    course_tools.register(reg)

    out = reg.run("summarize_course_files", {"file": "pharmacology"})
    assert out.startswith("No course file matches that. The files I have are:") and "Lab 3 handout" in out
    out = reg.run("summarize_course_files", {"course": "CS 103"})
    assert out.startswith("Writing notes for Lab 3 handout and Lecture 5.")
    assert finished.wait(10)
    notes = ctx.memory.notes()
    assert sorted(n["title"] for n in notes) == ["Lab 3 handout", "Lecture 5"] and {n["kind"] for n in notes} == {"document"}
    assert [d["action"] for k, d in events if k == "docnotes"][-1] == "done"
    # Saved notes are never summarized themselves, and finished files aren't redone
    assert all(notes_dir not in p.parents for p, _ in ctx.docnotes.files())
    assert reg.run("summarize_course_files", {"course": "CS 103"}).startswith("I already wrote notes for")
    finished.clear()
    out = reg.run("summarize_course_files", {"file": "every file"})
    assert "Midterm review" in out and "Week 1" in out and "already had notes" in out
    assert finished.wait(10) and len(ctx.memory.notes()) == 4
    lib.scan()                                                     # the extracted text isn't indexed twice
    assert not any(p.endswith("document-text.md") for p, *_ in lib._rows)


def test_summarize_everything_in_the_course_folder_goes_straight_to_the_tool():
    from sanae.agent import direct_route

    tools = {"summarize_course_files": None}
    assert direct_route("can you summarise each and every file you have in the max course folder and make notes "
                        "of them and put that in the notes section pls", tools) == ("summarize_course_files", {"course": ""})
    assert direct_route("summarize all the cs 103 slides", tools) == ("summarize_course_files", {"course": "CS 103"})
    assert direct_route("summarize this web page", tools) is None
    assert direct_route("what did the professor say about all of it", tools) is None


def test_one_combined_summary_of_a_courses_documents(tmp_path):
    from sanae.course import CourseLibrary
    from sanae.docnotes import DocNotes, body_of
    from sanae.main import documents_done_text
    from sanae.tools import course as course_tools

    course = tmp_path / "Course" / "CS 102"
    course.mkdir(parents=True)
    (course / "Week 1.txt").write_text("Knowledge representation and logic programs. Homework 1 is due "
                                       "September 3 at 11:59 PM.", encoding="utf-8")
    (course / "Week 2.txt").write_text("Answer set programming with clingo and stable models.", encoding="utf-8")
    (tmp_path / "Course" / "Other.txt").write_text("A file from another course entirely.", encoding="utf-8")
    reg, ctx = memory_registry()
    notes_dir = tmp_path / "Sanae Notes"
    lib = CourseLibrary([tmp_path / "Course", notes_dir], WordEmbedder(), tmp_path / "course.db")
    fake, finished = FakeSummarizer(), threading.Event()
    ctx.course = lib
    ctx.docnotes = DocNotes(ctx, lib, notes_dir, fake, on_done=lambda d, f: finished.set())
    course_tools.register(reg)

    # Week 1 already has notes: they're reused, only Week 2 is written before combining
    assert reg.run("summarize_course_files", {"file": "week 1"}).startswith("Writing notes for Week 1")
    assert finished.wait(10)
    finished.clear()
    out = reg.run("summarize_course_files", {"course": "CS 102", "combine": True})
    assert out.startswith("Writing notes for Week 2 first, then one combined summary of all 2 files, "
                          "called CS 102 combined summary.")
    assert finished.wait(10)
    notes = {n["title"]: n for n in ctx.memory.notes()}
    assert sorted(notes) == ["CS 102 combined summary", "Week 1", "Week 2"]
    combined = notes["CS 102 combined summary"]
    text = (Path(combined["folder"]) / "notes.md").read_text(encoding="utf-8")
    assert "*Combined summary · CS 102 · 2 documents" in text and "*Files: Week 1, Week 2*" in text
    assert "- [Week 1, section 1] “Homework 1 is due September 3 at 11:59 PM.”" in text   # quoted, with its file
    assert "### Week 1" in fake.calls[-1][1] and "### Week 2" in fake.calls[-1][1]        # built from both files' notes
    assert "exact quotes" not in fake.calls[-1][1] and "Other" not in text
    assert ctx.docnotes.combined == ["CS 102 combined summary"]
    assert documents_done_text(["Week 2"], [], ["CS 102 combined summary"]) == \
        "Your notes for Week 2 are ready in the Notes tab. The CS 102 combined summary is ready too."
    assert documents_done_text([], [], ["CS 102 combined summary"]) == \
        "Your CS 102 combined summary is ready in the Notes tab."
    # Asked again: nothing to redo, so straight to the combined summary
    finished.clear()
    assert reg.run("summarize_course_files", {"course": "CS 102", "combine": True}).startswith(
        "Writing one combined summary of all 2 files")
    assert finished.wait(10) and len(ctx.memory.notes()) == 4
    assert body_of("# T\n\n*Document · x*\n\n## Summary\nS\n\n## Deadlines & dates (exact quotes)\n- q") == "## Summary\nS"


def test_combined_summary_requests_go_straight_to_the_tool():
    from sanae.agent import direct_route

    tools = {"summarize_course_files": None}
    want = ("summarize_course_files", {"course": "CS 102", "combine": True})
    assert direct_route("summarise all the documents from cs 102 at once and create a single summary", tools) == want
    assert direct_route("make one summary of all my CS 102 slides", tools) == want
    assert direct_route("summarize all the cs 103 slides", tools) == ("summarize_course_files", {"course": "CS 103"})
    assert direct_route("give me one summary of this web page", tools) is None


def test_api_adds_a_document_and_writes_its_notes(tmp_path):
    from sanae.course import CourseLibrary
    from sanae.docnotes import DocNotes

    client, rt = api_client()
    ctx = rt.ctx
    ctx.course = lib = CourseLibrary([tmp_path / "Course", tmp_path / "Notes"], WordEmbedder(), tmp_path / "course.db")
    finished = threading.Event()
    ctx.docnotes = DocNotes(ctx, lib, tmp_path / "Notes", FakeSummarizer(), on_done=lambda d, f: finished.set())
    assert client.get("/api/documents").json()["files"] == []
    assert client.post("/api/documents/upload?name=notes.exe", content=b"x").status_code == 400
    r = client.post("/api/documents/upload?name=Week 2.txt&course=CS 103",
                    content=b"Ontologies describe classes and properties. Homework 2 is due October 9 at 5 PM.").json()
    assert r["name"] == "Week 2.txt" and r["summarizing"] and Path(r["saved"]).parent.name == "CS 103"
    assert finished.wait(10)
    files = client.get("/api/documents").json()["files"]
    assert [(f["name"], f["course"], f["done"]) for f in files] == [("Week 2.txt", "CS 103", True)]
    note = client.get(f"/api/notes/{ctx.memory.notes()[0]['id']}").json()
    assert note["kind"] == "document" and "Ontologies" in note["transcript_md"] and "Homework 2" in note["notes_md"]
    assert client.post("/api/documents/summarize", json={"paths": [files[0]["path"]]}).json()["skipped"] == ["Week 2.txt"]
    assert client.post("/api/documents/summarize", json={"combine": True}).json()["combined"] == ""   # one file: nothing to combine


# ---------- change Sanae from the phone (devloop.py) ----------

def test_dev_requests_one_at_a_time_and_need_a_decision(tmp_path, monkeypatch):
    from sanae import devloop

    monkeypatch.setattr(devloop, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(devloop, "DATA", tmp_path)
    monkeypatch.setattr(devloop.DevLoop, "_work", lambda self, job: None)     # no git, no Claude
    loop = devloop.DevLoop()
    with pytest.raises(ValueError):
        loop.submit("hi")
    job = loop.submit("make the orb purple")
    assert job.branch.startswith("phone/1-") and loop.busy is job
    with pytest.raises(RuntimeError, match="still working"):
        loop.submit("another change")
    job.status = "ready"
    with pytest.raises(RuntimeError, match="Approve or reject"):
        loop.submit("another change")
    job.status = "working"
    assert devloop.DevLoop().get(1).status == "failed"            # Sanae restarted mid-job: never left hanging
    assert devloop.describe_tool("Edit", {"file_path": "C:/x/sanae/agent.py"}) == "Editing agent.py"
    assert devloop.describe_tool("Bash", {"command": ".venv/Scripts/python -m pytest -q"}) == "Running the tests"


def test_dev_approve_checks_laptop_edits_and_keeps_the_error(tmp_path, monkeypatch):
    from sanae import devloop

    # Raw porcelain: the first line starts with a space, which used to be stripped (cutting a letter off)
    status = " M sanae/server.py\nM  config.yaml\nR  old.py -> sanae/new.py\n?? tests/new_test.py\n?? data2/\n"
    files = ["sanae/server.py", "sanae/agent.py", "tests/new_test.py", "sanae/new.py",
             "data2/x.txt", "config.yaml"]
    assert devloop.clashes(status, files) == ["config.yaml", "data2/x.txt", "sanae/new.py",
                                              "sanae/server.py", "tests/new_test.py"]
    assert devloop.clashes("", files) == []

    monkeypatch.setattr(devloop, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(devloop, "DATA", tmp_path)
    monkeypatch.setattr(devloop.DevLoop, "_work", lambda self, job: None)
    monkeypatch.setattr(devloop, "run", lambda cmd, cwd, timeout=900, env=None: (0, status))
    loop = devloop.DevLoop()
    job = loop.submit("fix the approve button")
    job.status, job.files = "ready", ["sanae/server.py"]
    with pytest.raises(RuntimeError, match="unsaved edits on the laptop: sanae/server.py"):
        loop.approve(job.id)
    saved = devloop.DevLoop().get(job.id)                          # the phone sees why, after a reload too
    assert saved.status == "ready" and saved.error.startswith("Approve failed: These files have unsaved edits")


def test_dev_api_and_app_update(tmp_path, monkeypatch):
    from sanae import devloop

    client, rt = api_client()
    assert client.get("/api/dev/jobs").status_code == 503                 # off unless dev.enabled
    monkeypatch.setattr(devloop, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(devloop, "DATA", tmp_path)
    monkeypatch.setattr(devloop, "APK", tmp_path / "app" / "sanae.apk")
    monkeypatch.setattr(devloop.DevLoop, "_work", lambda self, job: None)
    rt.ctx.dev = devloop.DevLoop()
    assert client.post("/api/dev/request", json={"text": "add a dark mode toggle"}).json()["id"] == 1
    assert client.post("/api/dev/request", json={"text": "another"}).status_code == 409
    assert client.get("/api/dev/jobs").json()[0]["request"] == "add a dark mode toggle"
    assert client.post("/api/dev/jobs/1/approve").status_code == 409          # not finished yet
    assert client.post("/api/dev/jobs/1/explode").status_code == 404
    assert client.post("/api/dev/jobs/1/reject").json()["status"] == "rejected"
    assert client.get("/api/app/info").json() == {"available": False}
    assert client.get("/api/app/apk").status_code == 404
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "sanae.apk").write_bytes(b"PK fake apk")
    assert client.get("/api/app/info").json()["size"] == 11
    assert client.get("/api/app/apk").content == b"PK fake apk"


def test_api_phone_crash_report_is_logged(tmp_path, monkeypatch):
    from sanae import server

    monkeypatch.setattr(server, "ROOT", tmp_path)
    client, _ = api_client()
    assert client.post("/api/phone/crash", content=b"  ").status_code == 400
    report = "crash at 2026-10-26 07:40\njava.lang.IllegalStateException: boom\n\tat com.manaskhare.sanae.ui.WeekStory"
    assert client.post("/api/phone/crash", content=report.encode()).json() == {"ok": True}
    saved = (tmp_path / "logs" / "phone-crash.log").read_text(encoding="utf-8")
    assert "IllegalStateException: boom" in saved and saved.startswith("===== received ")


# ---------- avatar (sanae/avatar, tts envelope, events) ----------

def test_speech_loudness_envelope_follows_the_voice():
    from sanae.tts import loudness_envelope

    sr = 16000
    t = np.arange(sr) / sr
    voice = np.concatenate([0.5 * np.sin(2 * np.pi * 220 * t), np.zeros(sr // 2)]).astype(np.float32)
    env = loudness_envelope(voice, sr)
    assert len(env) == 90                                      # 1.5 s at 60 values a second
    assert min(env[:59]) > 0.9 and max(env[61:]) == 0          # loud while talking, shut in the pause
    assert loudness_envelope(np.zeros(10, np.float32), sr) == []


def test_speaker_tells_the_avatar_before_and_after_each_sentence(monkeypatch):
    from sanae import audio
    from sanae.tts import Speaker

    class Voice:
        def synthesize(self, text):
            return np.full(16000, 0.3, np.float32), 16000

    played, told = [], []
    monkeypatch.setattr(audio, "play", lambda a, sr, device=None: played.append((len(told), len(a))))
    s = Speaker.__new__(Speaker)
    s.piper, s.sapi, s.mic, s.device = Voice(), None, None, None
    s.on_speech = lambda action, data: told.append((action, data))
    s.say("Hello there.")
    assert [a for a, _ in told] == ["start", "end"]
    assert played == [(1, 16000)]                              # the envelope went out before the audio
    assert told[0][1]["rate"] == 60 and len(told[0][1]["env"]) == 60 and told[0][1]["duration"] == 1.0
    assert len(told[0][1]["vis"]) == 60 and len(told[0][1]["vis"][0]) == 5     # mouth shapes per frame
    assert told[0][1]["text"] == "Hello there."                # the avatar's face and hands follow the words
    s.on_speech = lambda action, data: 1 / 0                   # a broken listener never stops speech
    s.say("Still talking.")


def test_mouth_shapes_follow_the_vowel():
    from sanae.tts import VISEMES, viseme_track

    sr = 16000
    t = np.arange(sr // 2) / sr

    def vowel(f1, f2):        # a buzz at 120 Hz with two formant-ish peaks
        return sum(np.sin(2 * np.pi * f * t) * a for f, a in ((120, 0.3), (f1, 0.5), (f2, 0.4))).astype(np.float32)

    audio = np.concatenate([vowel(800, 1200), vowel(300, 2400), vowel(350, 700), np.zeros(sr // 4, np.float32)])
    track = viseme_track(audio, sr)
    assert len(track) == len(audio) // (sr // 60) and all(len(f) == 5 for f in track)

    def main_shape(a, b):
        avg = np.mean(track[a:b], axis=0)
        return VISEMES[int(np.argmax(avg))]

    assert main_shape(5, 25) == "aa"                    # open: high F1
    assert main_shape(35, 55) in ("ee", "ih")           # front: high F2
    assert main_shape(65, 85) in ("ou", "oh")           # rounded: low F2
    assert max(max(f) for f in track[-10:]) == 0        # silence: mouth shut
    assert viseme_track(np.zeros(0, np.float32), sr) == []


def test_avatar_remembers_where_it_was_dragged(tmp_path):
    import json

    from sanae.avatar import PositionKeeper, saved_position

    path = tmp_path / "pos.json"
    keeper = PositionKeeper(path)
    keeper.check((100, 100, 440, 520))                  # where it started: nothing saved
    keeper.check((100, 100, 440, 520))
    assert not path.exists()
    keeper.check((300, 200, 640, 620))                  # being dragged...
    assert not path.exists()
    keeper.check((300, 200, 640, 620))                  # ...and settled
    assert json.loads(path.read_text()) == {"x": 300, "y": 200, "w": 340, "h": 420}
    keeper.check(None)                                  # hidden: no change
    assert saved_position(path) == (300, 200)
    assert saved_position(path, size=(400, 420)) == (270, 200)   # a wider window: she stays in place
    path.write_text(json.dumps({"x": -99999, "y": -99999}))
    assert saved_position(path) is None                 # that screen is gone
    path.write_text("not json")
    assert saved_position(path) is None


def test_models_asleep_is_published_once_per_change():
    from sanae.events import EventBus

    ctx = Context(load_config(), FakeLLM([]))
    ctx.bus = bus = EventBus()
    ctx.models_asleep = True
    ctx.models_asleep = True
    ctx.models_asleep = False
    assert [e["data"] for e in bus.recent if e["kind"] == "gpu"] == [{"asleep": True}, {"asleep": False}]
    assert bus.state["gpu"] == {"asleep": False}               # sent to the avatar when it connects


def test_avatar_hides_for_fullscreen_games_only():
    from sanae.avatar import should_hide

    assert should_hide(True, False, "")                        # exclusive fullscreen Direct3D
    assert should_hide(False, True, r"C:\Riot Games\VALORANT\live\VALORANT.exe")
    assert should_hide(False, True, r"D:\SteamLibrary\steamapps\common\Elden Ring\eldenring.exe")
    assert not should_hide(False, True, r"C:\Program Files\Google\Chrome\Application\chrome.exe")   # maximised / video
    assert not should_hide(False, True, r"C:\Windows\explorer.exe")
    assert not should_hide(False, False, r"C:\Riot Games\VALORANT\live\VALORANT.exe")              # windowed
    assert not should_hide(False, True, r"C:\Tools\SomeApp.exe")
    assert should_hide(False, True, r"C:\Tools\MyGame.exe", extra_games=["mygame.exe"])


def test_avatar_outline_runs_become_window_rectangles():
    from sanae.avatar import outline_rects

    # 10x10 grid on a 100x200 window: rows 2-4 share a span (one block), row 5 is wider, row 9 has two spans
    runs = [[2, 3, 6], [3, 3, 6], [4, 3, 6], [5, 1, 8], [9, 0, 2], [9, 5, 10]]
    rects = sorted(outline_rects(10, 10, runs, 100, 200))
    assert rects == sorted([(30, 40, 60, 100), (10, 100, 80, 120), (0, 180, 20, 200), (50, 180, 100, 200)])
    assert outline_rects(10, 10, [], 100, 200) == []


# ---------- the phone on its own: reminders / events sync, recordings uploaded later ----------

def test_sync_merge_rule():
    from sanae.sync import wins

    assert wins({"status": "done", "updated_ms": 1}, {"status": "pending", "updated_ms": 9})       # finished beats open
    assert not wins({"status": "pending", "updated_ms": 9}, {"status": "cancelled", "updated_ms": 1})
    assert wins({"status": "pending", "updated_ms": 5}, {"status": "pending", "updated_ms": 4})     # later edit wins
    assert not wins({"status": "pending", "updated_ms": 4}, {"status": "pending", "updated_ms": 4})  # tie keeps ours


def test_reminders_get_uids_on_an_old_database():
    import sqlite3

    from sanae.memory import MemoryStore
    from sanae.reminders import Reminders

    store = MemoryStore(":memory:", WordEmbedder())
    store.db.execute("DROP TABLE reminders")
    store.db.execute("CREATE TABLE reminders (id INTEGER PRIMARY KEY, text TEXT NOT NULL, due TEXT NOT NULL, "
                     "created TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', fired TEXT)")
    store.db.execute("INSERT INTO reminders (text, due, created) VALUES ('old one', '2030-01-01T09:00:00', 'x')")
    r = Reminders(store)
    old = r.pending()[0]
    assert len(old.uid) == 32 and old.updated > 0 and not old.on_phone
    try:
        store.db.execute("INSERT INTO reminders (text, due, created, uid) VALUES ('dup', 'x', 'x', ?)", (old.uid,))
        raise AssertionError("uids must be unique")
    except sqlite3.IntegrityError:
        pass


def test_phone_and_laptop_reminders_sync_both_ways():
    import datetime as dt

    client, rt = api_client()
    laptop = rt.ctx.reminders
    soon = dt.datetime.now().replace(microsecond=0) + dt.timedelta(hours=2)
    ms = lambda d: int(d.timestamp() * 1000)
    mine = laptop.add("set by voice", soon)
    # made on the phone while the laptop was off
    out = client.post("/api/sync", json={"reminders": [
        {"uid": "p1", "text": "buy milk", "due_ms": ms(soon), "status": "pending", "updated_ms": 1000},
        {"uid": mine.uid, "text": "set by voice", "due_ms": ms(mine.due), "status": "done", "updated_ms": 1},
    ]}).json()
    assert laptop.by_uid("p1").text == "buy milk" and laptop.by_uid("p1").due == soon
    assert laptop.by_uid(mine.uid).status == "done"            # the phone fired it: done beats pending
    got = {r["uid"]: r for r in out["reminders"]}
    assert set(got) == {"p1", mine.uid} and got[mine.uid]["status"] == "done"
    assert all(r.on_phone for r in laptop.for_sync())          # the phone holds them all now
    # an older edit from the phone doesn't undo a newer one on the laptop
    laptop.set_status(laptop.by_uid("p1").id, "cancelled")
    client.post("/api/sync", json={"reminders": [
        {"uid": "p1", "text": "buy oat milk", "due_ms": ms(soon), "status": "pending", "updated_ms": 2000}]})
    assert laptop.by_uid("p1").status == "cancelled"
    assert client.post("/api/sync", json={"reminders": [{"uid": "", "text": "x", "due_ms": 0}]}).status_code == 200


def test_repeat_rule_syncs_and_survives_an_old_phone_app():
    client, rt = api_client()
    laptop = rt.ctx.reminders
    out = client.post("/api/sync", json={"reminders": [
        {"uid": "p1", "text": "gym", "due_ms": 1893456000000, "status": "pending", "updated_ms": 100,
         "repeat": "weekly"}]}).json()
    assert {r["uid"]: r["repeat"] for r in out["reminders"]}["p1"] == "weekly"
    # an older phone app sends no "repeat": the laptop keeps the rule
    client.post("/api/sync", json={"reminders": [
        {"uid": "p1", "text": "gym!", "due_ms": 1893456000000, "status": "pending", "updated_ms": 200}]})
    assert laptop.by_uid("p1").repeat == "weekly" and laptop.by_uid("p1").text == "gym!"
    got = client.post("/api/reminders", json={"text": "bills", "when": "the 5th of every month"}).json()
    assert got["repeat"] == "monthly:5" and "every month" in got["spoken"]
    listed = {x["text"]: x for x in client.get("/api/reminders").json()}
    assert listed["bills"]["repeat"] == "monthly:5"


def test_missed_reminders_the_phone_showed_stay_quiet():
    import datetime as dt

    from sanae.reminders import ReminderScheduler, Reminders

    r = Reminders(memory_store())
    now = dt.datetime.now()
    shown = r.add("phone had this", now - dt.timedelta(hours=3))
    r.add("laptop only", now - dt.timedelta(hours=3))
    on_time = r.add("on time", now - dt.timedelta(seconds=20))
    r.mark_on_phone([shown.uid, on_time.uid])
    fired = []
    ReminderScheduler(r, lambda rem, missed: fired.append((rem.text, missed))).check(now)
    assert sorted(fired) == [("laptop only", True), ("on time", False)]   # due right now: both devices ring
    assert r.pending() == []


def test_events_tools_api_and_sync():
    import datetime as dt

    client, rt = api_client()
    from sanae.tools import memory as memory_tools

    reg = ToolRegistry(context=rt.ctx)
    memory_tools.register(reg)
    out = reg.run("add_event", {"title": "Study group", "when": "tomorrow at 3pm", "duration_minutes": 90})
    assert out == "Added to your calendar: Study group, tomorrow at 3 PM."
    assert reg.run("add_event", {"title": "Mom's birthday", "when": "in 3 days"}).startswith("Added")
    picnic_day = f"next {(dt.date.today() + dt.timedelta(days=3)):%A}".lower()   # never tomorrow (was "next saturday": broke on Fridays)
    assert reg.run("add_event", {"title": "Picnic", "when": picnic_day}).endswith("(all day).")
    assert reg.run("add_event", {"title": "x", "when": "blorp"}).startswith("Error")
    upcoming = rt.ctx.events.upcoming(30)
    study = next(x for x in upcoming if x.title == "Study group")
    assert (study.end - study.start) == dt.timedelta(minutes=90) and not study.all_day
    picnic = next(x for x in upcoming if x.title == "Picnic")
    assert picnic.all_day and picnic.start.hour == 0 and picnic.end - picnic.start == dt.timedelta(days=1)
    assert reg.run("list_events", {"day": "tomorrow"}).startswith("On your calendar tomorrow: Study group")
    assert "Study group" in [x["title"] for x in client.get("/api/events").json()]
    # an event made on the phone offline, and the phone deleting one of the laptop's
    start = dt.datetime.now().replace(microsecond=0) + dt.timedelta(days=2)
    ms = lambda d: int(d.timestamp() * 1000)
    out = client.post("/api/sync", json={"events": [
        {"uid": "pe1", "title": "Dentist", "start_ms": ms(start), "end_ms": ms(start) + 1800_000, "all_day": False,
         "location": "Austin", "status": "active", "updated_ms": ms(dt.datetime.now())},
        {**study.to_sync(), "status": "cancelled", "updated_ms": study.updated + 1}]}).json()
    assert rt.ctx.events.by_uid("pe1").location == "Austin"
    assert rt.ctx.events.by_uid(study.uid).status == "cancelled"
    assert {x["uid"] for x in out["events"]} >= {"pe1", study.uid, picnic.uid}   # cancelled sent: the phone drops it
    assert reg.run("cancel_event", {"which": "dentist"}).startswith("Removed from your calendar: Dentist")
    assert "events" in client.get("/api/today").json()


def test_phone_recording_upload_becomes_notes(tmp_path):
    import datetime as dt

    import numpy as np

    from sanae.notes import NotesManager
    from sanae.phone_notes import PhoneRecordings

    client, rt = api_client()
    ctx = rt.ctx
    heard = []

    def transcriber():
        def transcribe(audio, prompt):
            heard.append(len(audio))
            return "The homework is due Friday at 11:59 PM. Today we cover sorting."
        return transcribe

    ctx.notes = NotesManager(ctx, transcriber, tmp_path / "notes")
    ctx.notes.summarize = lambda system, text, n: "## Summary\nSorting lecture."
    events = []
    ctx.phone_notes = pn = PhoneRecordings(ctx, tmp_path / "rec", on_event=lambda k, d: events.append((k, d)),
                                           decoder=lambda path: np.full(16000 * 70, 0.1, np.float32))
    pn.start = lambda: pn                     # no background thread: process() is called below
    started = dt.datetime(2026, 10, 9, 9, 30)
    r = client.post("/api/notes/upload?uid=rec-1&kind=lecture&started_ms=" + str(int(started.timestamp() * 1000)),
                    content=b"fake aac bytes")
    assert r.status_code == 200 and r.json()["state"] == "queued" and r.json()["title"] == "Lecture Oct 9, 9:30 AM"
    assert pn.pending() == ["rec-1"]
    st = pn.process("rec-1")
    assert st["state"] == "done" and heard and sum(heard) == 16000 * 70
    note = ctx.memory.note(st["note_id"])
    assert note["started"] == "2026-10-09T09:30:00"           # dated when it was recorded
    assert "Sorting lecture" in note["summary"]
    assert pn.pending() == [] and not list((tmp_path / "rec").glob("*.audio"))   # no audio kept
    assert client.get("/api/notes/upload/rec-1").json()["note_id"] == st["note_id"]
    assert ("notes", "saved") in [(k, d["action"]) for k, d in events]
    # uploading again (the phone didn't hear back) changes nothing
    again = client.post("/api/notes/upload?uid=rec-1", content=b"fake aac bytes").json()
    assert again["state"] == "done" and pn.pending() == []
    assert client.get("/api/notes/upload/nope").status_code == 404
    assert client.post("/api/notes/upload?uid=..%2F", content=b"x").status_code == 400
    # a broken file: kept (renamed) and reported; a new upload can retry
    def broken(path):
        raise RuntimeError("bad audio")
    pn.decoder = broken
    client.post("/api/notes/upload?uid=rec-2", content=b"junk")
    assert pn.process("rec-2")["state"] == "failed" and (tmp_path / "rec" / "rec-2.failed").exists()
    assert client.post("/api/notes/upload?uid=rec-2", content=b"junk").json()["state"] == "queued"


def test_decoding_an_aac_recording(tmp_path):
    """The phone records AAC (ADTS); PyAV (faster-whisper's decoder) reads it."""
    import av
    import numpy as np

    from sanae.phone_notes import decode

    path = tmp_path / "x.aac"
    with av.open(str(path), "w", format="adts") as out:
        stream = out.add_stream("aac", rate=16000)
        stream.layout = "mono"
        t = np.arange(16000 * 2) / 16000
        pcm = (np.sin(2 * np.pi * 440 * t) * 0.3).astype(np.float32)
        for i in range(0, len(pcm), 1024):
            frame = av.AudioFrame.from_ndarray(pcm[None, i:i + 1024], format="flt", layout="mono")
            frame.sample_rate = 16000
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    audio = decode(path)
    assert abs(len(audio) / 16000 - 2.0) < 0.2 and float(np.abs(audio).max()) > 0.1


# ----- Sanae: persona, tags, initiative -----

def test_tags_parse_and_strip():
    from sanae.tags import TagFilter, guess, parse

    t = parse("[happy][wave] Heyy *giggles* there! 😏 [nod]")
    assert (t.text, t.emotion, t.gestures) == ("Heyy there!", "happy", ["wave", "nod"])
    assert parse("[Excited] wow").emotion == "happy"                   # synonyms
    assert parse("no tags at all").emotion is None
    assert parse("[unknown] hi").text == "hi"                          # unknown tags still removed
    assert guess("haha okay") == "laugh" and guess("oh no, sorry") == "sad" and guess("Fine.") == "neutral"
    out, told = [], []
    f = TagFilter(out.append, told.append)
    for piece in [None, "[hap", "py][w", "ave] Hey", " there", "! how are [", "you]"]:
        f(piece)
    assert "".join(p for p in out if p) == "Hey there! how are "
    assert told[0].emotion == "happy"


def test_persona_prompt_and_config(tmp_path):
    from sanae.config import apply_persona
    from sanae.persona import load_persona

    (tmp_path / "p.yaml").write_text("name: Sanae\nwake_phrase: Hey Sanae\npronounce: {Sanae: Sah-nah-eh}\n"
                                     "character: You are {name}, friend of {user}.\nstyle: be short\n"
                                     "examples: [{user: hi, reply: '[happy] Hey!'}]\n", encoding="utf-8")
    p = load_persona(tmp_path / "p.yaml")
    prompt = p.prompt("Alex")
    assert "You are Sanae, friend of Alex." in prompt and "Sanae: [happy] Hey!" in prompt and "[cover_face]" in prompt
    assert p.emotion_prototypes() == {"happy": "Hey!"}
    data = {"assistant": {"name": "Sanae"}, "wake_word": {"phrase": "Hey Sanae"}, "tts": {}}
    apply_persona(data, tmp_path / "p.yaml")
    assert data["assistant"]["name"] == "Sanae" and data["wake_word"]["phrase"] == "Hey Sanae"
    assert data["tts"]["spellings"] == {"Sanae": "Sah-nah-eh"}


def test_agent_reads_tags(tmp_path):
    from sanae.persona import Persona

    events = []
    reg = make_registry(tmp_path)
    agent = make_agent(reg, FakeLLM([ChatReply(content="[shy][cover_face] W-what?")]), events=events)
    agent.persona = Persona(name="Sanae", character="You are {name}.", style="")
    assert agent.handle("you're cute") == "W-what?"
    assert ("emotion", {"emotion": "shy", "gestures": ["cover_face"], "source": "tag"}) in events
    assert agent.history[-1][-1]["content"].startswith("[shy]")      # kept in history: the habit sticks
    assert "You are Sanae." in agent._system()["content"]


def test_quiet_route_and_tool(tmp_path):
    from sanae.agent import direct_route
    from sanae.dnd import DoNotDisturb
    from sanae.tools import companion

    assert direct_route("not now", {"quiet_for": 1}) == ("quiet_for", {"minutes": 60})
    assert direct_route("be quiet for 20 minutes", {"quiet_for": 1}) == ("quiet_for", {"minutes": 20.0})
    assert direct_route("not now i'm busy with something", {"quiet_for": 1}) is None
    reg = make_registry(tmp_path)
    reg.context.dnd = DoNotDisturb()
    companion.register(reg)
    assert "stay quiet until" in reg.run("quiet_for", {"minutes": 30})
    assert reg.context.dnd.reason().startswith("quiet until")
    reg.run("chat_again", {})
    assert reg.context.dnd.quiet_until == 0


def test_dnd_quiet_hours():
    import datetime as dt

    from sanae.dnd import DoNotDisturb

    d = DoNotDisturb(["23:00", "09:00"])
    assert d._in_quiet_hours(dt.datetime(2026, 10, 11, 23, 30)) and d._in_quiet_hours(dt.datetime(2026, 10, 11, 8, 0))
    assert not d._in_quiet_hours(dt.datetime(2026, 10, 11, 12, 0))
    assert DoNotDisturb(asleep=lambda: True).reason() == "asleep"


def test_initiative_moments(tmp_path):
    import datetime as dt

    from sanae.initiative import Initiative
    from sanae.memory import MemoryStore

    class Embed:
        def embed(self, texts):
            return np.ones((len(texts), 4), dtype=np.float32) / 2

    ctx = Context(Section({}), None)
    ctx.memory = MemoryStore(str(tmp_path / "m.db"), embedder=Embed())
    from sanae.agenda import Events

    ctx.events = Events(ctx.memory)
    t = {"now": dt.datetime(2026, 10, 11, 9, 0).timestamp(), "idle": 0.0}
    said, asked = [], []

    def generate(m):
        asked.append(m)
        return f"[happy] {m.kind}"

    ini = Initiative(ctx, lambda line, info: said.append(line), generate, settings={"break_after_min": 90},
                     chattiness="chatty", idle=lambda: t["idle"], clock=lambda: t["now"])
    assert ini.tick() == "[happy] greeting"                  # first time today
    assert ini.tick() is None                                # greeted once
    t["now"] += 60 * 10                                      # 10 min later: still in the cooldown
    ctx.events.add("Study group", dt.datetime.fromtimestamp(t["now"]) + dt.timedelta(minutes=10))
    assert ini.tick() == "[happy] upcoming"                  # important: skips the cooldown
    assert ini.tick() is None                                # mentioned once
    t["idle"] = 30 * 60                                      # away 30 min: too short to say anything
    t["now"] += 30 * 60
    assert ini.tick() is None
    t["idle"] = 1.0
    t["now"] += 2
    assert ini.tick() is None
    t["idle"] = 50 * 60                                      # away 50 min
    t["now"] += 50 * 60
    assert ini.tick() is None
    t["idle"] = 1.0                                          # back
    t["now"] += 2
    assert ini.tick() == "[happy] welcome_back"
    assert "Don't say they're back" in asked[-1].situation   # carries on the chat, no stock "you're back!"
    t["idle"] = 50 * 60                                      # away again, back within 3 hours: no second one
    t["now"] += 50 * 60
    ini.tick()
    t["idle"] = 1.0
    t["now"] += 2
    assert ini.tick() is None
    t["now"] += 95 * 60                                      # a long stretch since coming back
    assert ini.tick() == "[happy] break"
    ini.dnd = type("D", (), {"reason": lambda self: "a fullscreen game"})()
    t["now"] += 60 * 60
    assert ini.tick() is None                                # do-not-disturb wins


def test_conversation_mode_keeps_listening():
    from sanae.main import converse

    said, follow = [], iter(["and tomorrow?", ""])
    n = converse("what's on today", lambda text: said.append(text) or "Nothing much.", lambda: "",
                 keep_listening=lambda: next(follow))
    assert n == 2 and said == ["what's on today", "and tomorrow?"]


def test_conversation_mode_ignores_other_voices():
    from sanae.main import converse

    said, follow = [], iter(["open the browser", "and tomorrow?"])
    n = converse("what's on today", lambda text: said.append(text) or "Nothing much.", lambda: "",
                 keep_listening=lambda: next(follow), accept=lambda: False)
    assert n == 1 and said == ["what's on today"]                   # a video's voice ends it


def test_soften_and_respell():
    from sanae.tts import respell, soften

    sr = 22050
    x = (np.sin(np.arange(sr) * 2 * np.pi * 220 / sr) * 0.8).astype(np.float32)
    y = soften(x, sr)
    assert len(y) == len(x) and 0.5 < np.abs(y).max() < 0.7          # -3 dB under 0.9 full scale
    assert respell("Hi, I'm Sanae.", {"Sanae": "Sah-nah-eh"}) == "Hi, I'm Sah-nah-eh."


def test_rename_migrates_max_files(tmp_path, monkeypatch):
    import sqlite3
    from sanae import rename

    monkeypatch.setattr(rename, "resolve_path", lambda p: tmp_path / p)
    (tmp_path / "data").mkdir()
    old_notes, old_course = tmp_path / "Max Notes", tmp_path / "Max Course Material"
    (old_notes / "2026-10-01 Lecture").mkdir(parents=True)
    old_course.mkdir()
    from contextlib import closing

    with closing(sqlite3.connect(tmp_path / "data" / "max.db")) as con, con:
        con.execute("CREATE TABLE notes (folder TEXT)")
        con.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT)")
        con.execute("INSERT INTO notes VALUES (?)", (str(old_notes / "2026-10-01 Lecture"),))
        con.execute("INSERT INTO kv VALUES (?, ?)", ("docnote:" + str(old_course / "a.pdf"), "{}"))
    cfg = {"memory": {"db": "data/sanae.db"}, "notes": {"folder": str(tmp_path / "Sanae Notes")},
           "course": {"folders": [str(tmp_path / "Sanae Course Material")]}}
    rename.migrate(cfg)
    assert (tmp_path / "data" / "sanae.db").exists() and not (tmp_path / "data" / "max.db").exists()
    assert (tmp_path / "Sanae Notes" / "2026-10-01 Lecture").is_dir() and (tmp_path / "Sanae Course Material").is_dir()
    with closing(sqlite3.connect(tmp_path / "data" / "sanae.db")) as con:
        assert con.execute("SELECT folder FROM notes").fetchone()[0] == str(tmp_path / "Sanae Notes" / "2026-10-01 Lecture")
        assert con.execute("SELECT key FROM kv").fetchone()[0] == "docnote:" + str(tmp_path / "Sanae Course Material" / "a.pdf")
    rename.migrate(cfg)                                   # second run: nothing to do


def test_edge_peek_docks_slides_out_and_back():
    from sanae.avatar.peek import PeekState, STAY_OUT_S, dock_side, out_x, tucked_x

    work = (0, 0, 1920, 1040)
    assert dock_side((-100, 600, 220, 1064), work) == "left"        # 100 of 320 px past the left edge
    assert dock_side((1700, 600, 2020, 1064), work) == "right"
    assert dock_side((30, 600, 350, 1064), work) is None
    assert tucked_x("left", work, 320) == -173 and out_x("right", work, 320) == 1600

    p, t = PeekState(), 0.0
    rect = (1500, 600, 1820, 1064)
    assert p.step(rect, work, None, False, t) is None               # first look: nothing to do
    rect = (1720, 600, 2040, 1064)                                   # dragged past the right edge...
    assert p.step(rect, work, None, False, t + 0.1) is None          # ...still moving
    x = p.step(rect, work, None, False, t + 0.6)                     # settled: tuck in
    assert p.side == "right" and x == tucked_x("right", work, 320)
    rect = (x, 600, x + 320, 1064)
    assert p.step(rect, work, None, False, t + 0.7) is None          # right after tucking: stays in
    assert p.step(rect, work, None, False, t + 5) is None            # tucked, quiet: stays
    assert p.step(rect, work, (1900, 800), False, t + 6) == out_x("right", work, 320)   # mouse near: out
    rect = (1600, 600, 1920, 1064)
    assert p.step(rect, work, None, False, t + 6.1) is None
    assert p.step(rect, work, None, True, t + 9) is None              # she's talking: stays out
    assert p.step(rect, work, None, False, t + 9 + STAY_OUT_S + 0.1) == x   # calm again: back in
    rect = (x, 600, x + 320, 1064)
    p.step(rect, work, None, False, t + 20)
    moved = (900, 500, 1220, 964)                                    # dragged back onto the screen: undocked
    p.step(moved, work, None, False, t + 21)
    assert p.step(moved, work, None, False, t + 22) is None and p.side is None


def test_hide_and_show_avatar(tmp_path):
    from sanae.agent import direct_route
    from sanae.tools import companion

    tools = {"hide_avatar": 1, "show_avatar": 1}
    assert direct_route("go away for a bit", tools) == ("hide_avatar", {})
    assert direct_route("Sanae, hide please", tools) == ("hide_avatar", {})
    assert direct_route("come back", tools) == ("show_avatar", {})
    assert direct_route("hide my files", tools) is None
    reg = make_registry(tmp_path)
    companion.register(reg)
    assert "not on your screen" in reg.run("hide_avatar", {})          # no avatar (text mode)
    done = []
    reg.context.avatar_control = done.append
    assert "hide" in reg.run("hide_avatar", {}) and reg.run("show_avatar", {}) == "I'm back!"
    assert done == ["hide", "show"]


def test_waking_models_relaunches_avatar():
    ctx = Context(Section({}), None)
    done = []
    ctx.avatar_control = done.append
    ctx.models_asleep = True
    ctx.models_asleep = False
    assert done == ["launch"]                     # only starts it if it was closed; never un-hides


def test_hotkey_combo():
    from sanae.hotkey import parse_combo

    assert parse_combo("ctrl+alt+y") == (0x0002 | 0x0001, ord("Y"))
    assert parse_combo("Ctrl-Shift-F9") == (0x0002 | 0x0004, 0x78)
    for bad in ("y", "ctrl+", "hyper+y", "ctrl+alt+??"):
        with pytest.raises(ValueError):
            parse_combo(bad)


# ----- phase 3: friend memory, mood, window context, more initiative -----

def test_friend_memory_keeps_dedupes_and_filters():
    from sanae.friend import FriendMemory

    m = memory_store()
    f = FriendMemory(m)
    assert f.add("Alex is learning Japanese", "project") == (1, "added")
    assert f.add("Alex is learning japanese.", "project")[1] == "updated"          # same thing again: refreshed
    assert f.facts()[0].mentions == 2 and len(f.facts()) == 1
    assert f.add("Alex takes medication for anxiety", "other") is None           # sensitive: never kept
    assert f.add("Alex's bank password is hunter2", "other") is None
    m.add_fact("My sister Maya lives in Pune")
    assert f.add("My sister Maya lives in Pune", "person") is None               # already an explicit memory
    assert f.relevant("is alex learning japanese") == ["Alex is learning japanese"]
    fid = f.facts()[0].id
    assert f.edit(fid, "Alex is learning Japanese with Duolingo") and "Duolingo" in f.facts()[0].text
    assert f.delete(fid) and f.facts() == []


def test_friend_threads_due_and_expire():
    import datetime as dt

    from sanae.friend import FriendMemory

    f = FriendMemory(memory_store())
    t0 = dt.datetime(2026, 10, 16, 18, 0)
    tid = f.add_thread("the CS 102 exam", t0)
    assert f.add_thread("the CS 102 exam", t0) is None                           # once
    assert f.due_threads(t0 - dt.timedelta(hours=1)) == []
    assert [t.id for t in f.due_threads(t0 + dt.timedelta(hours=2))] == [tid]
    f.add_thread("the job interview", t0)
    assert len(f.due_threads(t0 + dt.timedelta(days=4))) == 0                     # too old: expired, not asked
    assert all(t.status == "expired" for t in f.threads())


def test_parse_extraction_and_learner():
    import datetime as dt
    import json

    from sanae.friend import FriendMemory, Learner, parse_extraction

    now = dt.datetime(2026, 10, 11, 20, 0)
    facts, follow = parse_extraction(json.dumps({
        "facts": [{"text": "Alex loves lo-fi music", "kind": "like"}, {"text": "", "kind": "like"}],
        "followups": [{"about": "the CS 102 exam", "ask_after": "2026-10-16T18:00"},
                      {"about": "something long ago", "ask_after": "2025-01-01T10:00"}, {"about": "x", "ask_after": "soon"}]}), now)
    assert facts == [("Alex loves lo-fi music", "like")] and follow == [("the CS 102 exam", dt.datetime(2026, 10, 16, 18, 0))]
    assert parse_extraction("not json at all", now) == ([], [])

    mem = memory_store()
    ctx = Context(Section({}), None)
    ctx.memory = mem
    friend = FriendMemory(mem)
    reply = json.dumps({"facts": [{"text": "Alex is building a voice assistant called Sanae", "kind": "project"}],
                        # relative to today: the learner drops follow-ups that are already past (was a fixed date)
                        "followups": [{"about": "the hackathon next week",
                                       "ask_after": f"{dt.date.today() + dt.timedelta(days=5)}T20:00"}]})

    class LLM:
        calls = 0

        def chat(self, model, messages, tools=None, options=None, fmt=None):
            if "checks" in fmt["properties"]:              # the sanity pass: all fine here
                return ChatReply(json.dumps({"checks": [{"note": i, "verdict": "keep"} for i in range(1, 9)]}))
            LLM.calls += 1
            assert fmt and "facts" in messages[0]["content"]
            return ChatReply(reply)

    clock = {"t": now.timestamp()}
    learner = Learner(ctx, friend, LLM(), "fast", "Alex", "Sanae", clock=lambda: clock["t"])
    mem.log_turn("old stuff", "ok")
    assert learner.run_once() == []                       # first run: starts from now, old history isn't mined
    mem.log_turn("I'm building you, you know. Hackathon next week!", "Ooh, good luck!")
    clock["t"] = time.time()
    assert learner.run_once() == [] and LLM.calls == 0    # the turn was just now: the conversation may go on
    clock["t"] = time.time() + 600
    assert learner.run_once() == ["Alex is building a voice assistant called Sanae"]
    assert [t.about for t in friend.threads("open")] == ["the hackathon next week"]
    assert learner.run_once() == [] and LLM.calls == 1    # nothing new


def test_mood_drift_and_reactions():
    import datetime as dt

    from sanae.mood import Mood, MoodKeeper, energy_for_hour, user_mood

    assert energy_for_hour(15) > 0.9 and energy_for_hour(3) < 0.2
    night = dt.datetime(2026, 10, 12, 3, 0).timestamp()
    m = Mood(energy=0.8, cheer=0.65, updated=night - 4 * 3600)
    m.drift(night)
    assert m.energy < 0.3 and m.resting_emotion == "sleepy" and "sleepy" in m.note()
    m.heard("thank you, you're the best", night)
    assert m.cheer > 0.7
    m.heard("shut up you're useless", night)
    assert m.cheer < 0.65
    assert user_mood("ugh this build keeps failing")[0] == "frustrated"
    assert user_mood("I passed the exam!!")[0] == "excited"
    assert user_mood("open spotify") is None
    events = []
    MoodKeeper(memory_store(), lambda k, d: events.append((k, d)))
    assert events and events[0][0] == "mood" and "resting" in events[0][1]


def test_window_context_privacy():
    from sanae.window import WindowWatch, clean, wants_context

    assert clean("C:/x/Code.exe", "friend.py - jarvis - Visual Studio Code").app == "VS Code"
    assert clean("chrome.exe", "Two Sum - LeetCode - Google Chrome").title == "Two Sum - LeetCode"
    for exe, title in [("chrome.exe", "Sign in - Google Accounts - Google Chrome"), ("1Password.exe", "Vault"),
                       ("msedge.exe", "New InPrivate tab - Microsoft Edge"), ("chrome.exe", "Chase Bank - Accounts"),
                       ("Code.exe", "secrets.yaml - jarvis - Visual Studio Code"), ("notepad.exe", "my diary.txt")]:
        assert clean(exe, title, ["diary"]) is None, title
    t = {"now": 0.0}
    w = WindowWatch(read=lambda: ("chrome.exe", "Two Sum - LeetCode - Google Chrome"), clock=lambda: t["now"])
    w.now()
    t["now"] = 700
    assert w.now().title == "Two Sum - LeetCode" and w.steady_s() == 700
    assert wants_context("what do you think of this?") and not wants_context("open spotify")


def test_agent_notes_go_into_the_request(tmp_path):
    llm = FakeLLM([ChatReply("[happy] Looks good!")])
    agent = make_agent(make_registry(tmp_path), llm)
    agent.notes = lambda text: ["They sound frustrated: be patient", "On their screen right now: VS Code: main.py"]
    agent.handle("what do you think of this")
    sent = llm.calls[0]["messages"][-1]["content"]
    assert "(They sound frustrated: be patient)" in sent and "VS Code: main.py" in sent


def test_initiative_bedtime_callbacks_cap_and_repeats():
    import datetime as dt
    import random

    from sanae.friend import FriendMemory
    from sanae.initiative import Initiative

    mem = memory_store()
    ctx = Context(Section({}), None)
    ctx.memory = mem
    friend = FriendMemory(mem)
    t = {"now": dt.datetime(2026, 10, 12, 1, 0).timestamp(), "idle": 30.0}
    lines = iter(["[sleepy] It's 1 AM, go to bed!", "[laugh] Still up? Bed. Now.", "[happy] How did the exam go?",
                  "[happy] How did the exam go?"])
    ini = Initiative(ctx, lambda line, info: None, lambda m: next(lines),
                     settings={"bedtime": {"from": "00:30", "until": "05:00", "every_min": [25, 55]}, "greeting": False,
                               "break_after_min": 100000},
                     chattiness="chatty", idle=lambda: t["idle"], clock=lambda: t["now"], friend=friend,
                     embed=WordEmbedder().embed, rng=random.Random(1))
    assert ini.tick() is None                                 # just got late: the first nudge comes a bit later
    t["now"] += 25 * 60
    assert ini.tick() == "[sleepy] It's 1 AM, go to bed!"
    t["now"] += 10 * 60
    assert ini.tick() is None                                 # random gap of 25-55 min
    t["idle"] = 600
    t["now"] += 60 * 60
    assert ini.tick() is None                                 # laptop not in use: no nudge
    t["idle"] = 30
    assert ini.tick() == "[laugh] Still up? Bed. Now."
    # morning: a thread from friend memory is due
    t["now"] = dt.datetime(2026, 10, 12, 10, 0).timestamp()
    friend.add_thread("the CS 102 exam", dt.datetime(2026, 10, 12, 9, 0))
    assert ini.tick() == "[happy] How did the exam go?"
    assert friend.threads("asked")
    friend.add_thread("the quiz", dt.datetime(2026, 10, 12, 9, 30))
    t["now"] += 3600
    assert ini.tick() is None                                 # same line again: dropped as a repeat
    ini.daily_cap = 1                                         # one non-exempt line said today
    friend.add_thread("the lab", dt.datetime(2026, 10, 12, 10, 30))
    t["now"] += 3600
    assert ini.tick() is None                                 # over the daily cap


# ---------- one running chat (conversation.py) ----------

class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def chat_turn(text, reply):
    return [{"role": "user", "content": f"[Mon Oct 12 2026, 9:00 PM] {text}"}, {"role": "assistant", "content": reply}]


def test_conversation_keeps_a_summary_across_pauses_and_restarts():
    from sanae.conversation import Conversation

    store, clock, prompts = memory_store(), Clock(), []

    def summarize(prompt):
        prompts.append(prompt)
        return "Updated summary: Alex has a networking exam on Thursday; a study reminder is set for 7 PM tomorrow."

    conv = Conversation(store, summarize, verbatim_min=30, new_after_h=4, user="Alex", clock=clock)
    conv.add(chat_turn("I have a networking exam thursday\n(On their screen right now: secret.txt - Notepad)", "[sad] Aw, ugh."))
    clock.t += 60
    conv.add(chat_turn("remind me tomorrow at 7pm to study", "[happy] Done, 7 PM tomorrow!"))
    assert conv.note() is None and len(conv.recent()) == 4          # all word for word, nothing older yet
    assert conv.fold() and conv.summary.startswith("Alex has a networking exam")
    assert "secret.txt" not in prompts[0] and "Alex: remind me tomorrow at 7pm to study" in prompts[0]

    clock.t += 40 * 60                                               # 40 min later: out of the word-for-word window
    assert conv.recent() == [] and conv.note().startswith("Earlier in this chat: Alex has a networking exam")

    again = Conversation(store, summarize, user="Alex", clock=clock)   # a restart: still there
    assert again.summary == conv.summary and again.note() == conv.note()
    assert "secret.txt" not in store.get("conversation")             # the window note is never saved

    clock.t += 5 * 3600                                              # the next morning: a new chat
    assert again.recent() == [] and again.summary == ""
    assert again.note().startswith("Last time you two talked (") and "networking exam" in again.note()
    for i in range(3):
        again.add(chat_turn(f"line {i}", "ok"))
    assert again.note() is None                                      # only for the first few turns


def test_her_metaphors_stay_out_of_the_summary_and_wear_out():
    """Her "storm" riff became a fact in the summary ("Alex is in a Beatle-powered storm") and
    she worked it into every reply after, even a reminder."""
    import json

    from sanae.conversation import Conversation, grounded_summary, worn_words

    turns = [chat_turn("what do you think of this song?", "[happy] It's raw, like the Beatles ripping through a storm!"),
             chat_turn("remind me at 11 pm to approve the assignment", "[happy] Done! I'm your 11 PM storm chaser.")]
    turns[1].append({"role": "tool", "tool_name": "set_reminder", "content": "Okay, I'll remind you today at 11 PM: approve the assignment."})
    summary = ("Alex asked about a song. Alex is in the middle of a Beatle-powered storm. "
               "Sanae set a reminder for Alex to approve the assignment at 11 PM.")
    kept = grounded_summary(summary, turns)
    assert "storm" not in kept and "approve the assignment at 11 PM" in kept and "asked about a song" in kept

    replies = [t[1]["content"] for t in turns]
    assert worn_words(replies, ["remind me at 11 pm"]) == ["storm"]
    assert worn_words(replies, ["there's a storm outside"]) == []          # their word: fine to keep using

    clock = Clock()
    conv = Conversation(None, lambda p: summary, verbatim_min=30, user="Alex", clock=clock)
    for t in turns:
        conv.add(t)
    assert '"storm"' in conv.note() and "leave those words" in conv.note()
    conv.fold()
    assert "storm" not in conv.summary

    store = memory_store()                                                   # saved by the old prompt: dropped
    store.set("conversation", json.dumps({"turns": [], "times": [], "summary": "Alex is in a storm.", "folded": 0}))
    assert Conversation(store, lambda p: "x", clock=clock).summary == ""


def test_conversation_keeps_unsummarised_turns_and_budget():
    from sanae.conversation import Conversation

    clock = Clock()
    conv = Conversation(None, lambda p: "s", verbatim_min=30, verbatim_chars=500, clock=clock)
    conv.add(chat_turn("old", "x"))
    clock.t += 3600
    assert len(conv.recent()) == 2                  # not summarised yet: kept word for word
    conv.fold()
    assert conv.recent() == []                      # summarised and old: only the summary now
    for i in range(5):
        conv.add(chat_turn("y" * 150, "z"))
    assert 2 <= len(conv.recent()) < 10             # never more than the budget
    plain = Conversation(None, None, verbatim_min=5, clock=clock)    # no summary (tests, summary off): just ages out
    plain.add(chat_turn("hi", "hey"))
    clock.t += 600
    assert plain.recent() == [] and plain.note() is None


def test_agent_puts_the_summary_and_announcements_in_the_chat(tmp_path):
    from sanae.conversation import Conversation

    clock = Clock()
    conv = Conversation(None, lambda p: "Alex is stressed about a networking exam.", verbatim_min=30, clock=clock)
    llm = FakeLLM([ChatReply("[happy] Start with congestion control!"), ChatReply("[happy] You're welcome!")])
    agent = Agent(llm, make_registry(tmp_path), "fast", "planner", conversation=conv)
    conv.add(chat_turn("I have an exam thursday", "[sad] Aw."))
    conv.fold()
    clock.t += 3600
    agent.handle("ok what should I start with?")
    sent = llm.calls[0]["messages"]
    assert [m["role"] for m in sent] == ["system", "user"]
    assert "(Earlier in this chat: Alex is stressed about a networking exam.)" in sent[-1]["content"]
    agent.add_said("Reminder: study for the exam.")
    agent.handle("thanks!")
    roles = [(m["role"], m["content"]) for m in llm.calls[1]["messages"]][-3:]
    assert roles[0][0] == "user" and "said this yourself" in roles[0][1]
    assert roles[1] == ("assistant", "Reminder: study for the exam.")


def test_tool_results_in_her_own_words_keep_the_facts():
    from sanae.persona import Persona

    def agent_with(replies):
        reg, ctx = memory_registry()
        llm = FakeLLM(replies)
        a = Agent(llm, reg, "fast", "planner")
        a.persona = Persona(name="Sanae", character="You are {name}.", style="")
        return a, llm

    call = ChatReply("", [ToolCall("set_reminder", {"text": "study", "when": "tomorrow at 7pm"})])
    agent, llm = agent_with([call, ChatReply("[happy] Done! 7 PM tomorrow, no excuses.")])
    assert agent.handle("remind me tomorrow at 7pm to study") == "Done! 7 PM tomorrow, no excuses."
    assert len(llm.calls) == 2 and llm.calls[1]["tools"] == llm.calls[0]["tools"]   # same prompt: cached

    agent, _ = agent_with([call, ChatReply("[happy] Done! 8 PM tomorrow.")])          # she got the time wrong
    assert agent.handle("remind me tomorrow at 7pm to study").startswith("Okay, I'll remind you tomorrow at 7 PM")

    agent, llm = agent_with([call])
    agent.in_character = False                                                         # turned off: one call
    assert agent.handle("remind me tomorrow at 7pm to study").startswith("Okay, I'll remind you")
    assert len(llm.calls) == 1


def test_badly_loaded_model_is_reloaded_once():
    from sanae.llm import OllamaClient

    client = OllamaClient("http://x")
    done = []
    client.unload = lambda m: done.append(("unload", m))
    client.preload = lambda m: done.append(("preload", m))
    slow = {"prompt_eval_count": 2700, "prompt_eval_duration": 17e9}      # 158 tok/s
    fast = {"prompt_eval_count": 2700, "prompt_eval_duration": 1.6e9}
    client._check_speed("m", slow)
    client._check_speed("m", fast)
    client._check_speed("m", slow)
    assert done == []                                                    # one slow prompt isn't enough
    client._check_speed("m", slow)
    time.sleep(0.2)
    assert done == [("unload", "m"), ("preload", "m")]
    client._check_speed("m", slow)
    client._check_speed("m", slow)
    time.sleep(0.2)
    assert len(done) == 2                                                # not again within 10 minutes
    client._check_speed("m", {"prompt_eval_count": 50, "prompt_eval_duration": 1e9})   # short prompts don't count


# ----- friend memory: only the user's words, only things still ahead -----

def test_friend_facts_need_the_users_words_and_followups_need_the_future():
    from sanae.friend import DENY, grounded, still_ahead

    names = ("Alex", "Sanae")
    assert grounded("Alex's sister is Maya", ["my sister maya is visiting"], names)
    assert grounded("Alex likes quizzes", ["ugh, another quiz"], names)                  # quiz ~ quizzes
    assert not grounded("Alex stretches regularly", ["So, don't worry about it."], names)  # only she said "stretch"
    assert not grounded("Alex likes Sanae", ["hi Sanae"], names)                          # names don't count
    assert not still_ahead("a quiz", ["i passed my quiz today!"])                         # already over
    assert still_ahead("the exam", ["I have an exam tomorrow"])
    assert still_ahead("the interview", ["the interview was rough, I have another one next week"])
    for no in ["I'm not giving any quiz", "what quiz?", "I didn't have a quiz", "there was no quiz"]:
        assert DENY.search(no), no
    for yes in ["yeah it went fine", "no I passed it", "it was okay"]:
        assert not DENY.search(yes), yes


def test_learner_skips_other_voices_old_turns_and_past_events():
    import datetime as dt
    import json

    from sanae.friend import FriendMemory, Learner

    mem = memory_store()
    ctx = Context(Section({}), None)
    ctx.memory = mem
    friend = FriendMemory(mem)
    replies = []

    class LLM:
        prompts = []

        def chat(self, model, messages, tools=None, options=None, fmt=None):
            if "checks" in fmt["properties"]:              # the sanity pass: all fine here
                return ChatReply(json.dumps({"checks": [{"note": i, "verdict": "keep"} for i in range(1, 9)]}))
            LLM.prompts.append(messages[0]["content"])
            return ChatReply(json.dumps(replies.pop(0)))

    now = {"t": time.time()}
    learner = Learner(ctx, friend, LLM(), "fast", "Alex", "Sanae", clock=lambda: now["t"])
    mem.log_turn("hello", "hi")
    learner.run_once()                                                 # starts from here

    def ts(tid: int, hours_ago: float):
        mem.db.execute("UPDATE turns SET ts = ? WHERE id = ?",
                       ((dt.datetime.now() - dt.timedelta(hours=hours_ago)).isoformat(timespec="seconds"), tid))

    # a video in the background (voice ID: not the user) is never shown to the model
    tid = mem.log_turn("roll it into a log, don't overheat it", "Sounds tasty!", heard="other")
    ts(tid, 1)
    assert learner.run_once() == [] and LLM.prompts == []

    # yesterday's turns (it fell behind): facts yes, follow-ups no
    tid = mem.log_turn("i passed my quiz today! I love lo-fi music", "YAY!", heard="you")
    ts(tid, 20)
    exam_day = f"{(dt.date.today() + dt.timedelta(days=2)):%A}"           # a day still ahead (was "Friday": broke on Fridays)
    tid2 = mem.log_turn(f"I have an exam on {exam_day}", "You've got this!", heard="you")
    ts(tid2, 1)
    replies.append({"facts": [{"text": "Alex loves lo-fi music", "kind": "like"},
                              {"text": "Alex stretches regularly", "kind": "routine"}],
                    "followups": [{"about": "the quiz", "ask_after": (dt.datetime.now() + dt.timedelta(hours=3)).isoformat(timespec="minutes"),
                                   "status": "upcoming"}]})
    assert learner.run_once() == ["Alex loves lo-fi music"]           # "stretches" wasn't in his words
    assert "list no followups" in LLM.prompts[-1] and f"exam on {exam_day}" not in LLM.prompts[-1]
    assert friend.threads() == []

    # today's turn: the exam is ahead; a "done" one and a past-tense one aren't
    soon = (dt.datetime.now() + dt.timedelta(days=2)).isoformat(timespec="minutes")
    replies.append({"facts": [], "followups": [{"about": f"the exam on {exam_day}", "ask_after": soon, "status": "upcoming"},
                                               {"about": "the quiz", "ask_after": soon, "status": "upcoming"},
                                               {"about": "the lab", "ask_after": soon, "status": "done"}]})
    learner.run_once()
    assert [t.about for t in friend.threads("open")] == [f"the exam on {exam_day}"]


def test_wrong_followup_is_forgotten_when_the_user_says_so():
    import datetime as dt

    from sanae.friend import FriendMemory

    f = FriendMemory(memory_store())
    f.add("Alex likes passing quizzes", "like")
    f.add("Alex loves lo-fi music", "like")
    tid = f.add_thread("a quiz", dt.datetime(2026, 10, 12, 18, 0))
    f.asked(tid, now=1000.0)
    assert f.denied("yeah it went great", now=1100.0) is None
    assert f.denied("I'm not giving any quiz", now=1000.0 + 20 * 60) is None   # too long after she asked
    f.asked(tid, now=5000.0)
    assert f.denied("I'm not giving any quiz", now=5060.0, names=("Alex", "Sanae")) == "a quiz"
    assert [x.text for x in f.facts()] == ["Alex loves lo-fi music"]
    assert [t.status for t in f.threads()] == ["wrong"]
    assert f.denied("what quiz?", now=5100.0) is None                          # once


def test_voice_id_judges_how_sure_it_is():
    from sanae.voiceid import VoiceID

    v = VoiceID.__new__(VoiceID)
    v.threshold, v.profile = 0.42, np.ones(3)
    for score, want in [(0.6, (True, "you")), (0.44, (True, "unsure")), (0.3, (False, "other")), (None, (None, "unsure"))]:
        v.score = lambda audio, s=score: s
        assert v.judge(np.zeros(10)) == want
    v.profile = None
    v.score = lambda audio: None
    assert v.judge(np.zeros(10)) == (None, "")                                  # no voice ID set up


def test_lab_runs_cannot_open_the_real_database(monkeypatch, tmp_path):
    from sanae.memory import MemoryStore

    monkeypatch.setenv("SANAE_LAB", "1")
    with pytest.raises(RuntimeError):
        MemoryStore("data/sanae.db", WordEmbedder())
    MemoryStore(str(tmp_path / "lab.db"), WordEmbedder())                        # anything else is fine


def test_followup_day_comes_from_the_users_words():
    import datetime as dt

    from sanae.friend import fix_day

    monday = [{"user": "I've got my CS 102 midterm on Thursday", "ts": "2026-10-12T10:00:00"}]
    wrong = dt.datetime(2026, 10, 16, 18, 0)                                       # the model said Friday
    assert fix_day(wrong, "the CS 102 midterm", monday) == dt.datetime(2026, 10, 15, 18, 0)
    tomorrow = [{"user": "big interview tomorrow", "ts": "2026-10-12T22:00:00"}]
    assert fix_day(wrong, "the interview", tomorrow) == dt.datetime(2026, 10, 13, 18, 0)
    assert fix_day(wrong, "the trip", [{"user": "trip soon", "ts": "2026-10-12T10:00:00"}]) == wrong


def test_chat_history_keeps_what_was_said_not_the_notes():
    from sanae.conversation import Conversation
    from sanae.initiative import Moment, model_line

    conv = Conversation()
    agent = Agent(None, ToolRegistry(), "m", "m", conversation=conv)
    conv.add([{"role": "user", "content": "[Mon Oct 12, 6:05 PM] try it\n(You remember: x)\n(Their mood: tired)"},
              {"role": "assistant", "content": "[happy] Okay!"}])
    assert conv.turns[-1][0]["content"] == "[Mon Oct 12, 6:05 PM] try it"

    class LLM:
        def chat(self, model, messages, tools=None, options=None, fmt=None):
            assert "Oh! You're back!" not in messages[-1]["content"]         # old lines are never listed (copied)
            return ChatReply("[happy] Still on that TCP thing?")

    line = model_line(agent, LLM(), "m", "Alex", recent=lambda: ["Oh! You're back! Did you see that cat video?"])
    assert line(Moment("welcome_back", "{user} is at the laptop again.")) == "[happy] Still on that TCP thing?"
    kept = " ".join(str(m["content"]) for t in conv.turns for m in t)
    assert "(You spoke first.)" in kept and "cat video" not in kept and "Say ONE" not in kept


def test_voice_id_is_gentler_mid_conversation():
    from sanae.voiceid import VoiceID

    v = VoiceID.__new__(VoiceID)
    v.threshold, v.chat_threshold, v.profile = 0.42, 0.32, np.ones(3)
    v.score = lambda audio: 0.38                                                # "can you show me?" (the user, short)
    assert v.in_conversation(np.zeros(10)) is True and v.is_owner(np.zeros(10)) is False
    v.score = lambda audio: 0.28                                                # a YouTube video
    assert v.in_conversation(np.zeros(10)) is False


# ----- hearing and sounding human: tone of voice, end of turn, expressive voice -----

def test_turn_completer_trusts_punctuation_then_the_model():
    from sanae.turn import completer

    class Detector:
        def p_done(self, text):
            return 0.0                                         # always "not yet" (it's overconfident like that)

    done = completer(Detector())
    assert done("Honestly, kinda tired.") and done("What was it again?")      # Whisper closed the sentence
    assert not done("So I was thinking that maybe")                           # open: the model decides
    assert not done("Can you search for")                                     # dangling word: never done
    assert completer(None)("So I was thinking that maybe")                    # no model: the word check only


def test_listen_waits_for_a_mid_thought_pause_and_says_mm_hm_once():
    from sanae.listen import listen_for_command

    replies = iter(["So I was thinking that maybe", "So I was thinking that maybe we go tomorrow."] + ["So I was thinking that maybe we go tomorrow."] * 3)
    nods = []
    frames = speech(40) + [tone(10)] * 15 + speech(8) + [tone(10)] * 40       # 3.2 s talking, 1.2 s pause, more
    text = listen_for_command(FakeMic(frames), NoiseFloor(100), lambda a: next(replies), silence_s=1.0, early_s=0.4,
                              max_silence_s=1.8, is_complete=lambda t: t.endswith("."), backchannel=lambda: nods.append(1))
    assert text == "So I was thinking that maybe we go tomorrow." and nods == [1]

    nods.clear()
    replies = iter(["Can you search for", "Can you search for cats?", "Can you search for cats?"])
    frames = speech(10) + [tone(10)] * 15 + speech(8) + [tone(10)] * 40       # only 0.8 s of talking first
    listen_for_command(FakeMic(frames), NoiseFloor(100), lambda a: next(replies), silence_s=1.0, early_s=0.4,
                       max_silence_s=1.8, backchannel=lambda: nods.append(1))
    assert nods == []                                                          # a short request gets no "mm-hm"


def test_tone_is_relative_to_your_own_voice_and_kept_as_daily_counts():
    import datetime as dt

    from sanae.tone import Baseline, ToneReader, day_summary, hint, tally

    mem = memory_store()
    b = Baseline(mem)
    assert b.label(0.1) is None and b.label(0.8) is None and b.label(0.21) is None   # says nothing before it knows you
    for i in range(40):
        b.learn(0.30 + 0.02 * (i % 3))                                         # a quiet speaker: 0.30-0.34
    assert b.label(0.32) is None and b.label(0.15) == "low" and b.label(0.5) == "high"
    assert Baseline(mem).n == 40                                               # kept across restarts

    assert "fine but sound flat" in hint("low", "I'm fine.", None)
    assert "tired or low" in hint("low", "what's on today", None)
    assert hint("low", "ugh I'm so tired", "tired") is None                    # the words already say it
    assert hint(None, "I'm fine", None) is None

    day = dt.datetime(2026, 10, 14, 20, 0)
    for label in ["low", "low", None, "low", None]:
        tally(mem, label, day)
    assert day_summary(mem, "2026-10-14") == "sounded tired or low a lot of the time"
    assert "low" not in (mem.get("conversation") or "")                        # nothing per message

    class Model:
        def score(self, audio):
            return (0.12, 0.2, 0.4)

    r = ToneReader(Model(), b)
    r.start(np.zeros(16000))
    assert r.result("other") == "low" and b.n == 40                            # someone else: not learned
    r.start(np.zeros(16000))
    r.result("you")
    assert b.n == 41


def test_her_voice_follows_her_emotion():
    from sanae.tts import STYLES, Speaker, pitch_shift

    a = np.ones(1000, dtype=np.float32)
    assert len(pitch_shift(a, 1.04)) < 1000 < len(pitch_shift(a, 0.96)) and len(pitch_shift(a, 1.0)) == 1000

    sp = Speaker.__new__(Speaker)
    sp.piper = type("P", (), {"style": None})()
    sp.set_emotion("sad")
    assert sp.piper.style == STYLES["sad"] and STYLES["sad"][0] > 1 and STYLES["sad"][3] < 1   # slower, softer
    sp.set_emotion("not-a-tag")
    assert sp.emotion == "neutral" and sp.piper.style == STYLES["neutral"]


# ----- phase B: listening, taste, diary, shared moments, check-ins -----

def test_venting_gets_listening_not_fixes():
    from sanae.support import HINT_HELP, HINT_LISTEN, HINT_VENT, Listener

    t = {"now": 1000.0}
    li = Listener(clock=lambda: t["now"])
    assert li.hint("ugh my build keeps failing and I'm so done with this", None, None) == HINT_VENT
    assert li.hint("open spotify", None, None) is None
    assert li.hint("I just need to vent for a sec", None, None) == HINT_LISTEN
    t["now"] += 300
    assert li.hint("and then the TA said it was due yesterday", None, None) == HINT_LISTEN   # still venting
    assert li.hint("ok what should I do about it", None, None) == HINT_HELP                 # asked for help now
    t["now"] += 60
    assert li.hint("and then the TA said it was due yesterday", None, None) is None
    long_flat = "so today was the kind of day where nothing really happened and I just sat there"
    assert li.hint(long_flat, None, "low") is None                     # a quiet voice alone isn't venting
    assert li.hint(long_flat, "down", "low") == HINT_VENT                # long and the words sound down
    from sanae.support import HINT_STILL

    t["now"] += 3600
    li2 = Listener(clock=lambda: t["now"])
    assert li2.hint("ugh the TA marked my whole lab wrong, I'm so done", None, None) == HINT_VENT
    assert li2.hint("like I spent six hours on it and it's one character", None, None) == HINT_STILL   # don't ask again
    assert li2.hint("honestly I'm so stressed about everything", "stressed", None) == HINT_STILL


def test_taste_learns_from_reactions_and_resets():
    from sanae.support import Taste, likes_note

    mem = memory_store()
    t = Taste(mem)
    assert t.notes() == []
    for _ in range(3):
        t.react("too long, get to the point", "Okay so basically TCP slow start works by...")
    assert t.dials["length"] < 0.35 and "very short replies" in " ".join(t.notes())
    t.react("lol", "[laugh] Doing your homework for me again, huh?")                    # laughed at a tease
    assert t.dials["tease"] > 0.5
    t.react("lol", "The meeting is at 3 PM.")                                           # nothing to laugh at: no change
    assert round(t.dials["tease"], 2) == 0.58
    t.react("okay", "Sure thing.", interrupted=True)
    assert Taste(mem).dials["length"] == pytest.approx(t.dials["length"], abs=1e-3)      # kept
    t.reset()
    assert Taste(mem).dials == {"length": 0.5, "tease": 0.5, "questions": 0.5}

    likes = ["cat", "anime", "strawberry milk"]
    assert likes_note(["Like a cat napping on the keyboard!"], likes).startswith("You've brought up cat")
    assert likes_note(["Your midterm is Thursday."], likes) is None


def test_diary_by_date_and_meaning_and_moments():
    import datetime as dt

    from sanae.diary import Diary, mentioned_day, spoken_day

    today = dt.date(2026, 10, 14)                                                        # a Wednesday
    assert mentioned_day("what did I do yesterday?", today) == dt.date(2026, 10, 13)
    assert mentioned_day("how was last tuesday", today) == dt.date(2026, 10, 13)
    assert mentioned_day("what happened on monday", today) == dt.date(2026, 10, 12)
    assert mentioned_day("on wednesday", today) == dt.date(2026, 10, 7)                 # a week back, not today
    assert mentioned_day("remember oct 2nd?", today) == dt.date(2026, 10, 2)
    assert mentioned_day("open spotify", today) is None
    assert spoken_day(dt.date(2026, 10, 13), today) == "yesterday"

    mem = memory_store()
    d = Diary(mem)
    d.put("2026-10-12", "Alex was stressed about the networks midterm and studied TCP congestion control.", "")
    d.put("2026-10-13", "Alex went to the gym and cooked pasta.", "sounded energetic and animated")
    assert d.recall("what did I do yesterday", today) == ["your diary for yesterday: Alex went to the gym and cooked pasta."]
    assert "midterm" in d.recall("was alex stressed about the networks midterm and tcp congestion control", today)[0]
    d.put("2026-10-13", "Alex went to the gym.", "")                                    # rewritten, not duplicated
    assert [e.day for e in d.entries()] == ["2026-10-13", "2026-10-12"] and d.get("2026-10-13").text == "Alex went to the gym."
    assert [e.day for e in d.week(today)] == ["2026-10-13", "2026-10-12"]

    j = d.add_moment("joke", "the cat napping on the keyboard bit", "2026-10-12")
    assert d.add_moment("joke", "the cat napping on the keyboard bit", "2026-10-13") is None   # same one
    assert d.add_moment("date", "Maya's birthday", "2026-10-12", "not a date") is None
    b = d.add_moment("date", "Maya's birthday", "2026-10-12", "10-20")
    assert d.add_moment("memory", "Alex's bank password moment", "2026-10-12") is None       # sensitive
    now = dt.datetime(2026, 10, 14, 15, 0)
    assert d.to_bring_up(now).id == j
    d.used(j, now)
    assert d.to_bring_up(now) is None                                                    # once a week at most
    assert [m.id for m in d.dates_today(dt.date(2026, 10, 20))] == [b]
    assert d.delete("2026-10-12") and d.delete_moment(b) and len(d.moments()) == 1


def test_diary_writer_uses_only_the_users_own_words():
    import datetime as dt
    import json

    from sanae.diary import Diary, Writer

    mem = memory_store()
    ctx = Context(Section({}), None)
    ctx.memory = mem
    d = Diary(mem)
    prompts = []

    class LLM:
        def chat(self, model, messages, tools=None, options=None, fmt=None):
            prompts.append(messages[0]["content"])
            if fmt:
                return ChatReply(json.dumps({"moments": [
                    {"kind": "joke", "text": "the pasta disaster", "date": ""},
                    {"kind": "date", "text": "Maya's birthday", "date": "10-20"},              # never said: dropped
                    {"kind": "memory", "text": "the night the build finally worked", "date": ""}]}))
            return ChatReply("Alex made a pasta disaster and laughed about it. Alex seemed happy.")

    def log(text, reply, heard, ts):
        tid = mem.log_turn(text, reply, heard=heard)
        mem.db.execute("UPDATE turns SET ts = ? WHERE id = ?", (ts, tid))

    log("I made a total pasta disaster lol", "[laugh] A pasta disaster? Iconic.", "you", "2026-10-13T19:00:00")
    log("roll it into a log, don't overheat it", "Sounds tasty!", "other", "2026-10-13T19:05:00")   # a video
    log("night!", "Night night!", "", "2026-10-14T01:30:00")                             # still the 13th (before 4 AM)
    clock = {"t": dt.datetime(2026, 10, 14, 9, 0).timestamp()}
    w = Writer(ctx, d, LLM(), "fast", "Alex", "Sanae", clock=lambda: clock["t"])
    assert w.due_days() == [dt.date(2026, 10, 13)]
    assert w.run_once() == ["2026-10-13"]
    assert "pasta disaster" in prompts[0] and "overheat" not in prompts[0] and "night!" in prompts[0]
    assert d.get("2026-10-13").text.startswith("Alex made a pasta disaster")
    assert sorted(m.text for m in d.moments()) == ["the pasta disaster"]                 # build / birthday not in the chat
    assert w.run_once() == [] and w.due_days() == []                                      # done once


def test_evening_checkin_weekly_look_back_and_birthdays():
    import datetime as dt

    from sanae.diary import Diary
    from sanae.initiative import Initiative
    from sanae.memory import MemoryStore

    ctx = Context(Section({}), None)
    ctx.memory = MemoryStore(":memory:", WordEmbedder())
    d = Diary(ctx.memory)
    d.put("2026-10-17", "Alex finished the networks lab.", "")
    d.put("2026-10-16", "Alex had the midterm and felt okay about it.", "")
    d.add_moment("date", "Maya's birthday", "2026-10-10", "10-18")
    t = {"now": dt.datetime(2026, 10, 18, 18, 0).timestamp(), "idle": 5.0}             # a Sunday evening

    class Rng:
        def random(self):
            return 0.0

        def choice(self, xs):
            return xs[0]

        def sample(self, xs, k):
            return list(xs)[:k]

        def uniform(self, a, b):
            return a

    ini = Initiative(ctx, lambda line, info: None, lambda m: f"[happy] {m.kind}", settings={"greeting": False},
                     chattiness="chatty", idle=lambda: t["idle"], clock=lambda: t["now"], diary=d, rng=Rng())
    kinds = [m.kind for m in ini.moments()]
    assert "date" in kinds and "weekly" in kinds and "checkin" not in kinds              # check-in is 8-11 PM
    assert ini.tick() == "[happy] date"                                                  # birthdays skip the cooldown
    assert not any(m.kind == "date" for m in ini.moments())                              # once
    weekly = next(m for m in ini.moments() if m.kind == "weekly")
    assert "networks lab" in weekly.situation and "midterm" in weekly.situation
    t["now"] = dt.datetime(2026, 10, 18, 21, 0).timestamp()
    m = next(m for m in ini.moments() if m.kind == "checkin")
    ini._used(m, t["now"])
    assert not any(x.kind == "checkin" for x in ini.moments())                           # once an evening


def test_breathing_exercise_talks_step_by_step(monkeypatch):
    from sanae.tools import companion

    monkeypatch.setattr(companion.time, "sleep", lambda s: None)
    reg = ToolRegistry()
    ctx = Context(Section({}), None)
    reg.context = ctx
    companion.register(reg)
    said, voices = [], []
    ctx.speak = lambda text: said.append(text) or None
    ctx.set_voice = voices.append
    result = reg.tools["breathing_exercise"].func()
    assert said[0].startswith("Okay, let's do this") and len(said) == 1 + 4 * 3
    assert voices == ["sleepy", "neutral"] and "How do you feel" in result
    said.clear()
    ctx.speak = lambda text: said.append(text) or ("stop" if len(said) == 3 else None)  # "stop" mid-way
    assert reg.tools["breathing_exercise"].func() == "Okay, we'll stop there." and len(said) == 3


def test_yes_to_her_breathing_offer_starts_it():
    from sanae.agent import direct_route

    tools = {"breathing_exercise": None}
    offer = "[happy] I get it. Want to do a one-minute breathing exercise together?"
    assert direct_route("okay sure, let's do it", tools, offer) == ("breathing_exercise", {})
    assert direct_route("yeah", tools, offer) == ("breathing_exercise", {})
    assert direct_route("no thanks", tools, offer) is None
    assert direct_route("yeah", tools, "Want me to draft the email?") is None              # a yes to something else


# ----- phase C: her own reading, study buddy, games, music -----

def test_reading_queries_are_safe_and_notes_keep_their_numbers():
    import json

    from sanae.friend import AboutFact
    from sanae.reading import Reader, people_names, safe_query
    from sanae.web import SearchResult

    people = people_names([AboutFact(1, "Alex's sister is Maya", "person", ""), AboutFact(2, "Alex likes lo-fi", "like", "")])
    assert people == ["Alex", "Maya"]
    assert safe_query('"QUIC protocol latest developments"', people) == "QUIC protocol latest developments"
    assert safe_query("Maya birthday gift ideas", people) is None             # a person they know
    assert safe_query("anxiety medication side effects", people) is None       # sensitive
    assert safe_query("a very long query that goes on and on forever", people) is None
    assert safe_query("Query: lo-fi music history", people) == "lo-fi music history"

    mem = memory_store()
    ctx = Context(Section({}), None)
    ctx.memory = mem
    from sanae.friend import FriendMemory

    ctx.friend = FriendMemory(mem)
    ctx.friend.add("Alex is into networking and TCP", "like")
    text = "QUIC runs over UDP and cuts connection setup to 1 round trip, compared with 3 for TCP plus TLS. " * 3

    class Web:
        def research(self, query, pages=2, passages_per_page=2):
            return [SearchResult("QUIC", "https://example.org/quic", "")], {"https://example.org/quic": [text]}

    ctx.web = Web()
    replies = iter(["QUIC protocol latest developments", "I read that QUIC needs just 1 round trip to connect, vs 3 for TCP with TLS!"])

    class LLM:
        def chat(self, model, messages, tools=None, options=None, fmt=None):
            return ChatReply(next(replies))

    t = {"now": 100000.0, "idle": 40 * 60}
    r = Reader(ctx, LLM(), "fast", "Alex", "Sanae", idle=lambda: t["idle"], clock=lambda: t["now"])
    assert r.due()
    note = r.read_once()
    assert note["query"] == "QUIC protocol latest developments" and "1 round trip" in r.pending()["note"]
    assert not r.due()                                                          # one note waits at a time
    r.used()
    assert r.pending() is None and not r.due()                                  # and at most every 3 hours
    t["now"] += 3 * 3600 + 1
    assert r.due()

    replies = iter(["QUIC protocol news", "I read that QUIC is 50% faster!"])  # 50% isn't in what she read
    assert r.read_once() is None and r.pending() is None
    mem.set("reading:pending", json.dumps({"query": "x", "note": "old", "t": t["now"] - 13 * 3600}))
    assert r.pending() is None                                                  # stale after 12 h


def test_study_buddy_rounds_breaks_and_tally():
    from sanae.study import StudyBuddy, day_summary

    mem = memory_store()
    ctx = Context(Section({}), None)
    ctx.memory = mem
    quiet = []
    ctx.dnd = type("D", (), {"quiet_for": lambda self, m: quiet.append(m), "resume": lambda self: quiet.append(0)})()
    said = []
    clock = {"t": 1_800_000_000.0}

    def sleep(seconds):
        clock["t"] += seconds
        return False

    b = StudyBuddy(ctx, lambda text, chat: said.append((text, chat)), lambda situation: "[happy] Break! How's TCP?",
                   clock=lambda: clock["t"], sleep=sleep)
    reply = b.start(60, "networks")
    assert "2 rounds of 25 minutes" in reply
    import time as _t

    for _ in range(50):
        if b.session.phase == "done":
            break
        _t.sleep(0.01)
    assert b.session.phase == "done"
    assert said[0] == ("[happy] Break! How's TCP?", True) and said[1] == ("Okay, back to it: round 2 of 2.", False)
    assert said[-1][1] is True and 25.5 in quiet and quiet[-1] == 0               # quiet while focusing, then not
    import datetime as dt

    day = dt.date.fromtimestamp(clock["t"]).isoformat()
    assert day_summary(mem, day) == "studied networks for 50 minutes"
    assert b.stop() == "We're not studying right now."


def test_games_keep_the_secret_and_the_count():
    from sanae.games import Games

    class Rng:
        def choice(self, xs):
            return xs[0]

        def sample(self, xs, k):
            return list(xs)[:k]

    t = {"now": 0.0}
    g = Games(Context(Section({}), None), clock=lambda: t["now"], rng=Rng())
    assert g.note("hi") is None
    assert "I'm thinking of an animal" in g.start("twenty_questions")
    n = g.note("Is it bigger than a cat?")
    assert "secret is: penguin" in n and "used: 1" in n
    g.note("it's not a dog")                                                    # not a question: not counted
    assert "used: 2, left: 18" in g.note("Can it swim?")
    assert "answer was penguin" in g.note("I give up") and g.game is None
    g.start("trivia", "networks")
    assert "general" not in g.note("ready") and "networks" in g.note("ok")
    t["now"] += 16 * 60
    assert g.note("hello?") is None and g.game is None                          # ended after 15 quiet minutes
    assert g.start("would_you_rather").startswith("Would you rather, let's go! Okay: would you rather")
    assert g.stop() == "Good game! That was fun." and g.stop().startswith("We're not")

    from sanae.agent import direct_route

    assert direct_route("stop the game", {"end_game": None}) == ("end_game", {})


def test_song_note_says_what_is_really_playing():
    from sanae.music import Track, song_note

    rock = lambda: Track("Everlong (Official HD Video)", "Foo Fighters - Topic", True)
    known = lambda t, web: "1997 single by Foo Fighters, their signature song." if t.title == "Everlong" else ""
    note = song_note("how is the song?", rock, facts=known)
    assert note.startswith('The song playing on their laptop right now: "Everlong" by Foo Fighters. '
                           "What's known about it: 1997 single") and "YOUR take" in note
    unknown = song_note("what do you think of this track", lambda: Track("Midnight Static", "Glass Harbor", True), facts=known)
    assert "new to you" in unknown
    assert "ask what it is" in song_note("do you like this track", lambda: None)
    assert song_note("what do you think of what I'm listening to", rock, facts=known)
    assert song_note("how was your day", rock, facts=known) is None
    assert Track("Oh My Love (Remastered 2010)", "John Lennon - Topic", True).clean().spoken() == '"Oh My Love" by John Lennon'
    assert Track("Linkin Park - Numb (Official Music Video) [4K]", "Linkin Park", True).clean().title == "Numb"
    assert Track("Daft Punk - Get Lucky", "", True).clean().spoken() == '"Get Lucky" by Daft Punk'


def test_song_correction_matches_a_misheard_title():
    from sanae.music import RecentTracks, Track, named_song, song_note

    clock = {"t": 1000.0}
    recent = RecentTracks(clock=lambda: clock["t"])
    recent.seen(Track("While My Guitar Gently Weeps (Remastered 2009)", "The Beatles - Topic", True))
    clock["t"] += 200
    julia = lambda: Track("Julia (Remastered 2009)", "The Beatles - Topic", True)    # the player shows the next song
    facts = lambda t, web: f"facts about {t.title}" if t.title in ("While My Guitar Gently Weeps", "Julia") else ""
    note = song_note("But I'm listening to Wildman guitars and cleaves by Beatles.", julia, facts=facts, recent=recent)
    assert note.startswith('They corrected you: the song is "While My Guitar Gently Weeps" by The Beatles')
    assert "facts about While My Guitar Gently Weeps" in note
    later = song_note("what's the story behind this song?", julia, facts=facts, recent=recent)       # the correction sticks
    assert '"While My Guitar Gently Weeps"' in later and "Julia" not in later
    follow = song_note("who played guitar on it?", julia, facts=facts, recent=recent)               # a follow-up keeps the facts
    assert '"While My Guitar Gently Weeps"' in follow and "facts about While My Guitar Gently Weeps" in follow
    assert song_note("who played guitar on it?", julia, facts=facts,
                     recent=RecentTracks(clock=lambda: clock["t"])) is None                          # no song talk before
    clock["t"] += 700
    assert song_note("who played guitar on it?", julia, facts=facts, recent=recent) is None          # too long ago
    assert '"Julia"' in song_note("how is this song?", julia, facts=facts, recent=recent)            # ...for 10 minutes
    lost = song_note("I'm listening to Blorp Snazzle", julia, facts=facts, recent=recent)
    assert "ask them to say it again" in lost
    assert named_song("I'm playing valorant") is None and named_song("I'm listening to you") is None
    assert named_song("no, it's Numb by Linkin Park") == ("Numb", "Linkin Park")


def test_music_comment_once_per_song_and_gap():
    import datetime as dt

    from sanae.initiative import Initiative
    from sanae.music import MusicWatch, Track

    playing = {"t": Track("Bohemian Rhapsody", "Queen", True)}
    clock = {"t": dt.datetime(2026, 10, 14, 15, 0).timestamp()}
    watch = MusicWatch(read=lambda: playing["t"], clock=lambda: clock["t"])
    assert watch.steady() is None                                               # just started
    clock["t"] += 90
    assert watch.steady().title == "Bohemian Rhapsody"

    class Rng:
        def random(self):
            return 0.0

        def choice(self, xs):
            return xs[0]

        def sample(self, xs, k):
            return list(xs)[:k]

    ctx = Context(Section({}), None)
    ctx.memory = memory_store()
    ini = Initiative(ctx, lambda line, info: None, lambda m: f"[happy] {m.kind}", settings={"greeting": False},
                     chattiness="chatty", idle=lambda: 5.0, clock=lambda: clock["t"], rng=Rng(), music=watch)
    m = next(x for x in ini.moments() if x.kind == "music")
    assert '"Bohemian Rhapsody" by Queen' in m.situation
    ini._used(m, clock["t"])
    clock["t"] += 2 * 3600
    assert not any(x.kind == "music" for x in ini.moments())                    # same song: never twice
    playing["t"] = Track("Paper Planes", "M.I.A.", True)
    watch.steady()
    clock["t"] += 90
    assert any(x.kind == "music" for x in ini.moments())
    playing["t"] = Track("Paper Planes", "M.I.A.", False)
    assert watch.steady() is None                                               # paused


def test_study_games_and_song_requests_go_straight_to_their_tools():
    from sanae.agent import direct_route

    tools = {k: None for k in ["start_study", "stop_study", "study_status", "play_game", "end_game", "what_song"]}
    assert direct_route("study with me for an hour, I need to get through networks", tools) ==         ("start_study", {"minutes": 60.0, "topic": "networks"})
    assert direct_route("let's study for 90 minutes", tools) == ("start_study", {"minutes": 90.0, "topic": ""})
    assert direct_route("pomodoro on operating systems", tools)[1]["topic"] == "operating systems"
    assert direct_route("how long until the break?", tools) is None                    # no session: not ours
    assert direct_route("how long until the break?", tools, studying=True) == ("study_status", {})
    assert direct_route("ok I'm done studying", tools, studying=True) == ("stop_study", {})
    assert direct_route("study with me", tools, studying=True) is None                 # already studying
    assert direct_route("I'm studying for my exam tomorrow", tools) is None
    assert direct_route("let's play twenty questions", tools) == ("play_game", {"kind": "twenty_questions", "topic": ""})
    assert direct_route("quiz me on computer networks", tools) == ("play_game", {"kind": "trivia", "topic": "computer networks"})
    assert direct_route("let's play would you rather", tools)[1]["kind"] == "would_you_rather"
    assert direct_route("what song is this?", tools) == ("what_song", {})


# ---------- photos (vision.py) ----------

def _photo(size=(1600, 1200), gps=True) -> bytes:
    import io

    from PIL import Image

    img = Image.new("RGB", size, (200, 120, 40))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"                     # camera make
    if gps:
        exif[0x8825] = {1: "N", 2: (33.0, 25.0, 0.0)}   # GPS
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif)
    return out.getvalue()


def test_photo_is_shrunk_and_loses_its_metadata():
    import io

    from PIL import Image

    from sanae.vision import PhotoError, prepare

    raw = _photo()
    assert Image.open(io.BytesIO(raw)).getexif()          # the test photo really has EXIF
    img = Image.open(io.BytesIO(prepare(raw, 896)))
    assert max(img.size) == 896 and img.format == "JPEG"
    assert not img.getexif() and "exif" not in img.info
    for bad in (b"", b"not an image at all"):
        with pytest.raises(PhotoError):
            prepare(bad)


class FakeSeer:
    def __init__(self, text="A red mug with 'My university' printed on it, on a wooden desk."):
        self.text, self.calls, self.unloaded = text, [], []

    def chat(self, model, messages, tools=None, options=None, keep_alive=None):
        self.calls.append({"model": model, "messages": messages, "keep_alive": keep_alive, "options": options})
        return ChatReply(content=self.text)

    def unload(self, model):
        self.unloaded.append(model)

    def preload(self, model, keep_alive=None):
        self.preloaded = getattr(self, "preloaded", []) + [(model, keep_alive)]


def test_vision_warms_up_when_the_camera_opens():
    from sanae.vision import Vision

    llm = FakeSeer()
    v = Vision(llm, "gemma3:4b", "qwen", warm_s=60)
    v.warm(background=False)                      # camera opened: swap now, while they frame the shot
    assert llm.unloaded == ["qwen"] and llm.preloaded == [("gemma3:4b", "90s")]
    v.warm(background=False)                      # opened again: no second load
    assert llm.preloaded == [("gemma3:4b", "90s")]
    v.look(_photo(), "")
    assert v.warm_at == 0 and v._timer is None and llm.calls[0]["keep_alive"] == 0
    v.cool()                                      # nothing warm any more: no-op
    assert llm.unloaded == ["qwen", "qwen"]
    assert not v.holding
    v.warm(background=False)
    assert v.holding                              # background model work waits while a photo is coming
    v.cool()                                      # photo dropped: gemma out, chat model back
    assert not v.holding
    assert llm.unloaded[-1] == "gemma3:4b" and llm.preloaded[-1] == ("qwen", None) and v.warm_at == 0


def test_vision_swaps_models_and_remembers_briefly():
    from sanae.vision import Vision

    clock = [1000.0]
    llm = FakeSeer()
    v = Vision(llm, "gemma3:4b", "qwen3:4b-instruct", remember_s=600, clock=lambda: clock[0])
    assert v.look(_photo(), "what is this?").startswith("A red mug")
    assert llm.unloaded == ["qwen3:4b-instruct"]           # chat model out first: both don't fit
    call = llm.calls[0]
    assert call["model"] == "gemma3:4b" and call["keep_alive"] == 0     # gemma leaves right after
    msg = call["messages"][0]
    assert "what is this?" in msg["content"] and len(msg["images"]) == 1
    assert "just sent you a photo" in v.note(fresh=True) and "red mug" in v.note(fresh=True)
    clock[0] += 180
    assert "3 min ago" in v.note(fresh=False)
    clock[0] += 600
    assert v.note(fresh=False) is None and v.last is None   # dropped after remember_s


def test_agent_gets_photo_note_and_keeps_only_the_tag(tmp_path):
    from sanae.vision import Vision, photo_text

    reg = make_registry(tmp_path)
    reg.context.vision = Vision(FakeSeer(), "gemma3:4b", "fast", clock=time.time)
    reg.context.vision.look(_photo(), "is this mine?")
    llm = FakeLLM([ChatReply(content="Cute mug! Looks like your My university one.")])
    agent = make_agent(reg, llm)
    text = photo_text("is this mine?")
    assert text == "(Sent a photo) is this mine?" and photo_text("  ") == "(Sent a photo)"
    assert agent.handle(text) == "Cute mug! Looks like your My university one."
    sent = llm.calls[0]["messages"][-1]["content"]
    assert "just sent you a photo" in sent and "red mug" in sent
    kept = agent.history[-1][0]["content"]
    assert "red mug" not in kept and kept.endswith("(Sent a photo) is this mine?")   # description not kept


def test_look_at_photo_errors_are_friendly():
    from sanae.main import look_at_photo
    from sanae.vision import Vision

    ctx = Context(load_config(), None)
    ctx.vision = None
    assert "turned off" in look_at_photo(ctx, b"x", "")[1]
    ctx.vision = Vision(FakeSeer(), "gemma3:4b", "fast")
    text, failed = look_at_photo(ctx, b"garbage", "hi")
    assert text == "" and "photo I can open" in failed
    assert look_at_photo(ctx, _photo(), "what's this") == ("(Sent a photo) what's this", None)

    class Broken(FakeSeer):
        def chat(self, *a, **kw):
            raise KeyError("message")
    ctx.vision = Vision(Broken(), "gemma3:4b", "fast")
    text, failed = look_at_photo(ctx, _photo(), "hi")
    assert text == "" and "went wrong" in failed          # an odd error is a reply, not an HTTP 500


def test_claude_looks_first_and_secrets_stay_local(tmp_path):
    import tempfile

    from sanae.cloudbrain import CloudBrain
    from sanae.vision import Vision, is_secret

    seen = []

    def see(system, prompt, jpeg, schema):
        seen.append((prompt, jpeg))
        return {"description": "A flyer: BAKE SALE Fri Nov 6, 3:30 PM, Room 204. The user would like it."}

    folder = tempfile.mkdtemp()
    brain = CloudBrain({"cloud": True, "daily_photos": 2}, "Alex", "Sanae", run=lambda *a: None, see=see,
                       folder=folder)
    llm = FakeSeer()
    v = Vision(llm, "gemma3:4b", "qwen")
    v.cloud = brain
    v.warm(background=False)                                  # Claude looks: nothing to swap in
    assert not getattr(llm, "preloaded", None) and not v.holding
    assert v.look(_photo(), "when is this?").endswith("Alex would like it.")   # name put back
    assert llm.calls == [] and llm.unloaded == [] and v.last.by == "claude"     # the chat model stayed
    assert "when is this?" in seen[0][0] and seen[0][1][:2] == b"\xff\xd8"     # a JPEG, EXIF already gone
    log = (brain.recent(1)[0])
    assert log["task"] == "photo" and log["sent"]["prompt"].startswith("[a photo,")   # the photo isn't logged

    assert is_secret("let this be a secret between us") and is_secret("keep this private please")
    assert is_secret("just between you and me, what do you think?") and not is_secret("what plant is this?")
    v.look(_photo(), "let this be a secret between us, how do I look?")
    assert len(seen) == 1 and llm.calls[-1]["model"] == "gemma3:4b" and v.last.by == "local"
    v.look(_photo(), "my doctor gave me these pills, what are they?")   # a sensitive question stays local too
    assert len(seen) == 1 and v.last.by == "local"
    v.look(_photo(), "and this?")
    v.look(_photo(), "and this one?")                         # past daily_photos: local
    assert len(seen) == 2 and v.last.by == "local"
    hard = CloudBrain({"cloud": True}, "Alex", "Sanae", run=lambda *a: None, see=see, folder=folder,
                      private_now=lambda: True)
    v.cloud = hard
    v.look(_photo(), "look")                                  # comfort mode: nothing leaves
    assert len(seen) == 2 and v.last.by == "local"
    v.cloud = CloudBrain({"cloud": True}, "Alex", "Sanae", run=lambda *a: None, folder=folder,
                         see=lambda *a: (_ for _ in ()).throw(RuntimeError("offline")))
    assert v.look(_photo(), "look").startswith("A red mug") and v.last.by == "local"   # Claude failed: local


def test_vision_drops_gemmas_image_markers():
    from sanae.vision import clean

    said = ("A cartoon girl with brown hair. The text \"start_of_image\" and \"end_of_image\" are present. "
            "The picture looks cute.")
    assert clean(said) == "A cartoon girl with brown hair. The picture looks cute."


def test_llm_timeout_is_an_ollama_error(monkeypatch):
    import requests

    from sanae import llm as llm_mod

    def slow(*a, **kw):
        raise requests.ReadTimeout("read timed out")

    monkeypatch.setattr(llm_mod.requests, "post", slow)
    with pytest.raises(llm_mod.OllamaError, match="180 s"):
        llm_mod.OllamaClient("http://x", timeout=180).chat("gemma3:4b", [])


def test_api_photo_failure_is_still_a_reply():
    def run_command(text, source="dashboard", photo=None):
        raise RuntimeError("boom")

    client, _ = api_client(run_command)
    r = client.post("/api/photo", content=_photo(gps=False))
    assert r.status_code == 200 and "went wrong" in r.json()["reply"]


def test_api_photo_passes_bytes_to_the_command():
    got = {}

    def run_command(text, source="dashboard", photo=None):
        got.update(text=text, source=source, size=len(photo or b""))
        return "A sunflower!"

    client, _ = api_client(run_command)
    raw = _photo(gps=False)
    r = client.post("/api/photo?q=what%20flower%20is%20this", content=raw)
    assert r.json() == {"reply": "A sunflower!", "kept": None}         # not kept unless the phone asks
    assert got == {"text": "what flower is this", "source": "dashboard", "size": len(raw)}
    assert client.post("/api/photo", content=b"").status_code == 400
    assert client.post("/api/photo/ready").json() == {"ok": False}     # vision off in this test runtime
    assert client.post("/api/photo/nope").status_code == 404


def test_calendar_claim_without_the_tool_is_caught():
    from sanae.agent import CLAIMS

    assert CLAIMS["add_event"].search("Adding Build night #3 to your calendar.")
    assert CLAIMS["add_event"].search("I've added it to your calendar!")
    assert not CLAIMS["add_event"].search("Want me to add it? Your calendar is free Friday.")


def test_the_ideas_or_vent_chat_from_oct_15():
    """Replays the evening chat that went wrong: busy coding (not venting), then asking for ideas twice."""
    from sanae.support import HINT_HELP, HINT_LISTEN, HINT_VENT, Listener

    t = {"now": 1000.0}
    li = Listener(clock=lambda: t["now"])
    assert li.hint("Well, it's evening for me, so I don't think so. I've been at it all night.", None, "low") is None
    assert li.hint("ugh this bug has eaten my whole evening and I'm so done", None, None) == HINT_VENT   # asks once
    t["now"] += 20
    assert li.hint("So let me just make some ideas.", None, None) == HINT_HELP        # answered "ideas"
    assert li.hint("I said suggest me some plans or ideas.", None, None) == HINT_HELP
    li2 = Listener(clock=lambda: t["now"])
    assert li2.hint("ugh the TA marked my whole lab wrong, I'm so done", None, None) == HINT_VENT
    assert li2.hint("honestly I just need to vent", None, None) == HINT_LISTEN       # answered "vent"


def test_repeating_themselves_and_time_of_day():
    from sanae.agent import part_of_day
    from sanae.main import REPEATED

    assert REPEATED.search("I said suggest me some plans or ideas.")
    assert REPEATED.search("no, like I said, the networks one")
    assert not REPEATED.search("my professor said the exam is friday")
    assert [part_of_day(h) for h in (2, 9, 14, 19, 22)] == ["late night", "morning", "afternoon", "evening", "night"]


def test_openers_that_start_like_a_recent_one_are_redone():
    from sanae.conversation import Conversation
    from sanae.initiative import Moment, model_line, starts_like

    old = "[laugh] Alex, you've been gone three hours—did you eat or just stare at the sky?"
    assert starts_like("[happy] Alex, you've been gone three hours—did you try the strawberry milk?", [old], "Alex")
    assert not starts_like("[happy] Hey, how's the TCP homework going?", [old], "Alex")

    replies = ["[laugh] You've been gone three hours, huh?", "[happy] Hey! How's the networking homework going?"]

    class LLM:
        def __init__(self):
            self.notes = []

        def chat(self, model, messages, tools=None, options=None, fmt=None):
            self.notes.append(messages[-1]["content"])
            return ChatReply(replies.pop(0))

    llm = LLM()
    agent = Agent(None, ToolRegistry(), "m", "m", conversation=Conversation())
    line = model_line(agent, llm, "m", "Alex", recent=lambda: [old])
    assert line(Moment("greeting", "First time today. Say hello.")) == "[happy] Hey! How's the networking homework going?"
    assert len(llm.notes) == 2 and "Don't bring up your own likes" in llm.notes[0] and "three hours" not in llm.notes[0]


# ----- comfort mode (comfort.py) -----
def test_comfort_notices_not_okay_and_ignores_everyday_phrases():
    from sanae.comfort import level_of

    for text in ["I'm not okay", "honestly i'm really not doing well", "I feel so empty lately",
                 "I can't do this anymore", "nobody cares about me", "what's the point of anything"]:
        assert level_of(text) == "low", text
    for text in ["I want to die", "sometimes I think about hurting myself", "I don't want to be here anymore",
                 "everyone would be better off without me"]:
        assert level_of(text) == "dark", text
    for text in ["this homework is killing me", "I'm dead tired", "I give up", "I could die of embarrassment",
                 "that's not okay, the build is broken again", "what's the point of this function?",
                 "I'm dying of laughter", "lol I want to die laughing", "have you seen Suicide Squad?",
                 "I'm not sure", "I'm fine"]:
        assert level_of(text) is None, text
    from sanae.comfort import BETTER

    assert not BETTER.search("yeah... talking helps a bit") and BETTER.search("thanks, that really helped")
    from sanae.comfort import Comfort

    lonely = Comfort(None, "Alex", knows_them=lambda: False)
    lonely.hear("I'm not okay")
    assert "something real and good" not in lonely.note() and "someone they care" not in lonely.note()


def comfort_with_clock(start=None):
    import datetime as dt

    from sanae.comfort import Comfort

    t = {"now": start or dt.datetime(2026, 10, 16, 21, 0).timestamp()}
    faces = []

    class Rng:
        def sample(self, xs, k):
            return list(xs)[:k]

        def uniform(self, a, b):
            return 45 * 60

    mem = memory_store()
    c = Comfort(mem, "Alex", {}, set_face=faces.append, clock=lambda: t["now"], rng=Rng())
    return c, t, faces, mem


def test_comfort_stays_then_eases_back_gradually():
    c, t, faces, mem = comfort_with_clock()
    assert c.hear("hey what's up") == [] and c.state == "off"
    notes = c.hear("I'm not okay, everything feels heavy")
    t["now"] += 4 * 3600
    assert not c.serious and c.state == "balanced"                                  # silent for hours: balanced
    notes = c.hear("I'm not okay, everything feels heavy")
    assert c.serious and "isn't okay" in notes[0] and "helplines" in notes[0] and faces[-1] == "sad"
    assert c.calm("laugh", ["cheer", "nod", "wave"]) == ("sad", ["nod"])         # no laughing or cheering
    assert c.after_reply("...", "[sad] I'm right here.") is None                  # low level: no extra line
    t["now"] += 120
    assert c.hear("thanks, that really helped. I feel a bit better") and c.state == "easing"
    assert "said they feel better" in c.note() and c.calm("laugh", ["cheer"]) == ("happy", [])
    c.after_reply("", "[happy] I'm so glad.")
    c.after_reply("", "[happy] Want some tea?")
    t["now"] += 20 * 60
    assert "small smile" in c.note()                                                # warmth coming back
    t["now"] += 30 * 60                                                             # past the 45 min
    assert not c.holding_back() and c.state == "off" and faces[-1] is None and c.note() is None
    from sanae.mood import day_label

    assert day_label(mem, "2026-10-16") == "a hard day, felt better by the end"


def test_comfort_dark_level_asks_about_someone_once_and_relapse_goes_back():
    c, t, faces, mem = comfort_with_clock()
    notes = c.hear("I don't want to be here anymore")
    assert c.level == "dark" and "someone they could be with" in notes[0]
    extra = c.after_reply("", "[sad] I'm here. I'm not going anywhere.")
    assert extra and "someone with you" in extra
    assert c.after_reply("", "[sad] Tell me more.") is None                         # once
    c2, *_ = comfort_with_clock()
    c2.hear("I want to die")
    assert c2.after_reply("", "[sad] Is there someone you could text tonight?") is None   # she asked herself
    c.hear("I feel better now")
    assert c.state == "easing"
    c.hear("actually no, I'm not okay again")
    assert c.state == "comfort"


def test_comfort_next_day_check_in_once():
    import datetime as dt

    c, t, faces, mem = comfort_with_clock()
    c.hear("i feel so alone")
    assert not c.care_due()                                                        # not the same day
    t["now"] = dt.datetime(2026, 10, 17, 2, 0).timestamp()                          # 2 AM: still that day
    assert not c.care_due()
    t["now"] = dt.datetime(2026, 10, 17, 11, 0).timestamp()
    assert c.care_due() and c.state == "off"                                        # a new day: herself, then asks
    notes = c.hear("morning")                                                      # they talk first: ask in the reply
    assert any("how they're doing today" in n for n in notes) and not c.care_due()
    notes = c.hear("much better today honestly")
    assert c.state == "off" and any("glad" in n for n in notes)
    # not better -> balanced; and never asked twice
    c, t, faces, mem = comfort_with_clock()
    c.hear("I'm not okay")
    t["now"] = dt.datetime(2026, 10, 17, 18, 0).timestamp()
    c.care_asked()
    c.hear("not really, still kinda rough")
    assert c.state == "balanced" and "not too cheerful" in c.note() and not c.care_due()
    t["now"] = dt.datetime(2026, 10, 18, 18, 0).timestamp()
    assert not c.care_due() and (c.hear("hey") == [] or c.state == "off")          # the day after: nothing


def test_comfort_survives_restart_and_initiative_stays_quiet():
    import datetime as dt

    from sanae.comfort import Comfort
    from sanae.initiative import Initiative

    c, t, faces, mem = comfort_with_clock()
    c.hear("i'm not okay")
    again = Comfort(mem, "Alex", {}, clock=lambda: t["now"])
    assert again.serious                                                            # a restart doesn't flip her back
    ctx = Context(Section({}), None)
    ctx.memory = mem
    ini = Initiative(ctx, lambda line, info: None, lambda m: f"[happy] {m.kind}", settings={"greeting": False},
                     chattiness="chatty", idle=lambda: 5.0, clock=lambda: t["now"], comfort=again)
    assert ini.moments() == []
    t["now"] = dt.datetime(2026, 10, 17, 12, 0).timestamp()
    assert [m.kind for m in ini.moments()] == ["care"]
    assert ini.tick() == "[happy] care" and again.care_asked_at and not again.care_due()


def test_daily_mood_label_for_every_day():
    import datetime as dt

    from sanae.mood import day_label, tally_day

    mem = memory_store()
    day = lambda d, h=15: dt.datetime(2026, 10, d, h).timestamp()
    for text in ["ugh I'm so stressed about the exam", "so stressed, deadline tomorrow", "ok"]:
        tally_day(mem, text, day(10))
    for text in ["yay I aced it!", "haha thanks", "let's go!"]:
        tally_day(mem, text, day(11))
    for text in ["open spotify", "what time is it"]:
        tally_day(mem, text, day(12))
    tally_day(mem, "lol thanks", day(13, 2))                                       # 2 AM counts for the 12th
    assert day_label(mem, "2026-10-10") == "stressed"
    assert day_label(mem, "2026-10-11") == "great"
    assert day_label(mem, "2026-10-12") == "okay"
    assert day_label(mem, "2026-10-09") == ""                                      # didn't talk


def test_diary_saves_how_the_day_felt():
    import datetime as dt

    from sanae.diary import Diary, Writer
    from sanae.mood import mark_day, tally_day

    mem = memory_store()
    ctx = Context(Section({}), None)
    ctx.memory = mem
    d = Diary(mem)
    prompts = []

    class LLM:
        def chat(self, model, messages, tools=None, options=None, fmt=None):
            prompts.append(messages[0]["content"])
            return ChatReply('{"moments": []}' if fmt else "Alex had a rough evening and they talked it through.")

    tid = mem.log_turn("i'm not okay", "[sad] I'm here.", heard="you")
    mem.db.execute("UPDATE turns SET ts = ? WHERE id = ?", ("2026-10-13T21:00:00", tid))
    tally_day(mem, "i'm not okay", dt.datetime(2026, 10, 13, 21).timestamp())
    mark_day(mem, "hard", dt.datetime(2026, 10, 13, 21).timestamp())
    w = Writer(ctx, d, LLM(), "fast", "Alex", "Sanae", clock=lambda: dt.datetime(2026, 10, 14, 9).timestamp())
    assert w.run_once() == ["2026-10-13"]
    assert "How the day felt for Alex: a hard day." in prompts[0] and "talked it through" in prompts[0]
    assert d.get("2026-10-13").mood == "a hard day" and d.entries()[0].mood == "a hard day"


def test_comfort_turns_are_never_learned_from():
    c, t, faces, mem = comfort_with_clock()
    c.private_turn(5)                                                               # off: nothing kept
    c.hear("i'm not okay")
    c.private_turn(6)
    import json

    assert json.loads(mem.get("comfort:turns")) == [6]


def test_agent_adds_the_someone_line_and_calms_tags():
    from sanae.comfort import Comfort
    from sanae.persona import load_persona

    persona = load_persona()

    class LLM:
        def chat(self, model, messages, tools=None, on_text=None, **kw):
            return ChatReply("[laugh][cheer] I'm here with you.")

    events = []
    agent = Agent(LLM(), ToolRegistry(), "m", "m", persona=persona, on_event=lambda k, d: events.append((k, d)))
    c = Comfort(None, "Alex")
    agent.notes = lambda text: c.hear(text)
    agent.calm, agent.after_reply = c.calm, c.after_reply
    answer = agent.handle("I want to die")
    assert answer.startswith("I'm here with you.") and "someone with you tonight" in answer
    emo = [d for k, d in events if k == "emotion"][-1]
    assert emo["emotion"] == "sad" and emo["gestures"] == []


def test_watch_commands_are_tagged_and_carry_her_face():
    from types import SimpleNamespace

    seen = []
    token = "w" * 40
    phone, rt = api_client(lambda text, source="dashboard": seen.append(source) or "Done!", token=token,
                           client=("100.64.0.7", 40000))
    auth = {"Authorization": f"Bearer {token}"}
    assert phone.post("/api/command", json={"text": "hi"}, headers=auth).json() == {"reply": "Done!"}
    rt.ctx.agent = SimpleNamespace(last_tags=SimpleNamespace(emotion="happy"))
    r = phone.post("/api/command", json={"text": "hi"}, headers={**auth, "X-Sanae-Device": "watch"}).json()
    assert r == {"reply": "Done!", "emotion": "happy"} and seen == ["phone", "watch"]
    rt.ctx.agent.last_tags = None                 # a direct tool reply: no face
    assert phone.post("/api/command", json={"text": "hi"}, headers=auth).json() == {"reply": "Done!"}


def test_canvas_weekend_and_other_named_periods():
    import datetime as dt

    from sanae.agent import direct_route
    from sanae.canvas import CanvasItem, canvas_route, describe_due, period_range
    from sanae.claudemind import tool_lines

    saturday = dt.datetime(2026, 10, 31, 15)
    sunday = dt.datetime(2026, 11, 1, 9)
    wednesday = dt.datetime(2026, 10, 28, 9)
    monday = dt.datetime(2026, 11, 2)
    assert period_range("this_weekend", saturday) == (dt.datetime(2026, 10, 31), monday)
    assert period_range("this_weekend", sunday) == (dt.datetime(2026, 11, 1), monday)
    assert period_range("this_weekend", wednesday) == (dt.datetime(2026, 10, 31), monday)
    assert period_range("next_week", saturday) == (monday, dt.datetime(2026, 11, 9))

    tools = {"canvas_due": 1, "canvas_classes": 1}
    for text, period in [("what do I have due this weekend?", "this_weekend"),
                         ("anything due tonight", "today"),
                         ("what assignments do I have next week", "next_week"),
                         ("what's due tomorrow", "tomorrow")]:
        assert direct_route(text, tools) == ("canvas_due", {"period": period})
    assert canvas_route("do I have class this weekend") == ("canvas_classes", {"period": "this_weekend"})
    for text in ["remind me about the assignment due this weekend", "I have an exam next week, ugh",
                 "what's due next weekend", "what's due this weekend and email it to me"]:
        assert canvas_route(text) is None

    item = CanvasItem("assignment", "Assignment 2", "CS 102", dt.datetime(2026, 11, 1, 23, 59), True)
    assert describe_due([item], "this_weekend").startswith("Due this weekend: Assignment 2 for CS 102, Sunday")
    assert describe_due([], "this_weekend") == "Nothing due this weekend on Canvas."
    line = tool_lines([{"function": {"name": "canvas_due", "description": "d", "parameters": {"properties": {
        "period": {"type": "string", "enum": ["today", "this_weekend"], "description": "Default: today"}}}}}])
    assert "this_weekend" in line        # Claude has to see the choices too


def _sanity_llm(checks):
    import json

    from sanae.llm import ChatReply

    class LLM:
        def chat(self, model, messages, tools=None, options=None, fmt=None):
            if checks is None:
                raise RuntimeError("no model")
            return ChatReply(json.dumps({"checks": checks}))
    return LLM()


def test_sanity_pass_keeps_repairs_drops_and_holds():
    from sanae.friend import sanity_check

    facts = [("Alex likes hiking", "like"), ("Alex has a black guy", "other"),
             ("Alex plans to play Valorant in game mode", "plan"), ("Alex plans to go to the gym downwards", "plan"),
             ("Alex has a pet dragon", "other")]
    said = ["I went hiking, my black cat came along", "gym tomorrow I think"]
    keep, ask, dropped = sanity_check(_sanity_llm([
        {"note": 1, "verdict": "keep"},
        {"note": 2, "verdict": "fix", "text": "Alex has a black cat"},
        {"note": 3, "verdict": "drop"},
        {"note": 4, "verdict": "unsure"},
        {"note": 5, "verdict": "fix", "text": "Zzzz qqqq"},       # a repair not from their words: ask instead
    ]), "m", facts, said, "Alex", "Sanae")
    assert keep == [("Alex likes hiking", "like"), ("Alex has a black cat", "other")]
    assert dropped == ["Alex plans to play Valorant in game mode"]
    assert [t for t, _ in ask] == ["Alex plans to go to the gym downwards", "Alex has a pet dragon"]


def test_sanity_pass_failing_means_ask_never_save():
    from sanae.friend import sanity_check

    facts = [("Alex likes hiking", "like")]
    assert sanity_check(_sanity_llm(None), "m", facts, ["hiking"], "Alex", "Sanae") == ([], facts, [])
    assert sanity_check(_sanity_llm([]), "m", facts, ["hiking"], "Alex", "Sanae") == ([], facts, [])   # skipped it


def test_held_notes_stay_out_of_memory_until_confirmed():
    from sanae.factcheck import FactCheck
    from sanae.friend import FriendMemory

    mem = memory_store()
    f = FriendMemory(mem)
    f.hold("Alex plans to go to the gym downwards", "plan")
    assert f.hold("Alex plans to go to the gym downwards", "plan") is None
    assert f.hold("Alex gave me a bank password") is None
    assert f.facts() == [] and f.relevant("gym") == []

    now = {"t": 1000.0}
    part = FactCheck(mem, friend=f, clock=lambda: now["t"])
    moment = part.moments(1000.0)[0]
    assert "gym downwards" in moment.line and moment.part == "factcheck"
    part.used(moment, 1000.0)
    assert part.moments(1000.0) == []                       # one question a day
    assert part.notes("what time is it") == []              # not an answer: still waiting
    assert part.notes("yeah that's right")
    assert [x.text for x in f.facts()] == ["Alex plans to go to the gym downwards"] and f.pending() == []
    assert part.notes("yes") == []                          # answered already

    b = f.hold("Alex owns a black guy", "other")
    part.put("waiting", {"id": b, "t": 1000.0})
    assert part.notes("no, I said cat")
    assert f.pending() == [] and len(f.facts()) == 1

    c = f.hold("Alex has a boat", "other")
    part.put("waiting", {"id": c, "t": 1000.0})
    now["t"] += 16 * 60
    assert part.notes("yes") == [] and [p.id for p in f.pending()] == [c]   # that "yes" was about something else
    f.clear()
    assert f.pending() == []


def test_no_claiming_something_done_without_a_tool(tmp_path):
    from sanae.agent import ACTED, PERSONA_RULES
    from sanae.claudemind import PROTOCOL
    from sanae.llm import ChatReply

    assert "tool call in this turn" in PERSONA_RULES and "RESULT in this turn" in PROTOCOL
    assert ACTED.search("I drew a tree too, next to your photo")
    assert ACTED.search("I've sent you the link")
    for fine in ["I drew a cat today, wobbly as ever", "You sent me a photo", "I can draw you one", "did I make you laugh"]:
        assert not ACTED.search(fine), fine

    reg = make_registry(tmp_path)
    llm = FakeLLM([ChatReply("I drew a tree too, next to your photo."), ChatReply("Want me to sketch a tree?")])
    agent = make_agent(reg, llm)
    assert agent.handle("nice photo right") == "Want me to sketch a tree?"
    assert "no tool ran" in llm.calls[1]["messages"][-1]["content"]
