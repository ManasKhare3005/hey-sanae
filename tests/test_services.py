"""Ollama / SearXNG: started when down, logged once, summaries queued instead of lost."""
import logging

import pytest

from sanae import services
from sanae.conversation import Conversation
from sanae.services import Services


@pytest.fixture(autouse=True)
def clean():
    services.reset()
    yield
    services.reset()


def test_down_is_logged_once_and_once_when_back(caplog):
    caplog.set_level(logging.WARNING, logger="sanae.services")
    for _ in range(50):
        services.note("ollama", False, "can't connect")
    services.note("ollama", True)
    services.note("ollama", True)
    assert len(caplog.records) == 2
    assert "down" in caplog.records[0].getMessage() and "back" in caplog.records[1].getMessage()
    assert not services.is_down("ollama")


def test_first_contact_up_is_not_news(caplog):
    caplog.set_level(logging.WARNING, logger="sanae.services")
    services.note("searxng", True)
    assert not caplog.records


def test_starts_what_is_down_at_most_every_retry():
    now = {"t": 0.0}
    up = {"ollama": False}
    started = []
    s = Services({"ollama": lambda: up["ollama"]}, {"ollama": lambda: started.append(1)}, retry_s=600, clock=lambda: now["t"])
    s.run_once()
    now["t"] = 60
    s.run_once()
    assert len(started) == 1 and services.is_down("ollama")
    now["t"] = 700
    s.run_once()
    assert len(started) == 2
    up["ollama"] = True
    now["t"] = 2000
    s.run_once()
    assert len(started) == 2 and not services.is_down("ollama")


def test_a_failing_starter_or_check_never_raises():
    def boom():
        raise OSError("nope")
    s = Services({"a": boom}, {"a": boom})
    s.run_once()
    assert services.is_down("a")


def test_docker_missing_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(services.shutil, "which", lambda name: None)
    assert "Docker" in services.start_searxng()


def _turn(text):
    return [{"role": "user", "content": text}, {"role": "assistant", "content": "ok"}]


def test_failed_summary_waits_logs_once_and_retries(caplog):
    caplog.set_level(logging.WARNING, logger="sanae.conversation")
    now = {"t": 1000.0}
    calls = []

    def down(prompt):
        calls.append(prompt)
        raise RuntimeError("Can't reach Ollama")
    c = Conversation(None, down, clock=lambda: now["t"])
    c.add(_turn("my exam is on friday"))
    now["t"] += 100
    c.tick()
    c.tick()                      # still waiting: no second call
    assert len(calls) == 1 and c.pending() == 1
    now["t"] += 61
    c.tick()
    assert len(calls) == 2
    assert len(caplog.records) == 1

    c.summarize = lambda prompt: "Alex has an exam on friday."
    now["t"] += 121
    c.tick()
    assert c.pending() == 0 and "exam" in c.summary


def test_a_chat_that_ends_unsummarised_is_written_up_later():
    now = {"t": 1000.0}

    def down(prompt):
        raise RuntimeError("down")
    c = Conversation(None, down, clock=lambda: now["t"])
    c.add(_turn("my exam is on friday"))
    now["t"] += 5 * 3600          # over new_after_h: a new chat starts
    assert c.recent() == []
    assert len(c.backlog) == 1

    c.summarize = lambda prompt: "Alex has an exam on friday."
    c.tick()
    assert c.backlog == [] and "exam" in c.previous


def test_the_backlog_survives_a_restart():
    class KV(dict):
        def set(self, k, v):
            self[k] = v

    kv, now = KV(), {"t": 1000.0}

    def down(prompt):
        raise RuntimeError("down")
    c = Conversation(kv, down, clock=lambda: now["t"])
    c.add(_turn("my exam is on friday"))
    now["t"] += 5 * 3600
    c.recent()
    again = Conversation(kv, lambda p: "Alex has an exam on friday.", clock=lambda: now["t"])
    assert len(again.backlog) == 1
    assert again.fold_backlog() and "exam" in again.previous


class _Trickle:
    """A stream that keeps sending a little, for ever (each read succeeds: no read timeout fires)."""
    status_code = 200
    text = ""
    closed = False

    def iter_lines(self):
        import json
        import time
        while not self.closed:
            time.sleep(0.02)
            yield json.dumps({"message": {"content": "a"}, "done": False}).encode()

    def close(self):
        self.closed = True


def test_a_trickling_stream_hits_the_deadline(monkeypatch):
    import time

    from sanae.llm import OllamaClient, OllamaError

    stream = _Trickle()
    monkeypatch.setattr("sanae.llm.requests.post", lambda *a, **k: stream)
    llm = OllamaClient("http://x", stream_deadline_s=0.2)
    started = time.monotonic()
    with pytest.raises(OllamaError, match="stuck"):
        llm.chat("m", [], on_text=lambda piece: None)
    assert time.monotonic() - started < 2
    time.sleep(0.1)
    assert stream.closed


def test_a_blocked_read_hits_the_deadline_too(monkeypatch):
    import threading
    import time

    from sanae.llm import OllamaClient, OllamaError

    release = threading.Event()

    class Stuck(_Trickle):
        def iter_lines(self):
            release.wait(5)
            return iter(())

    monkeypatch.setattr("sanae.llm.requests.post", lambda *a, **k: Stuck())
    started = time.monotonic()
    with pytest.raises(OllamaError, match="stuck"):
        OllamaClient("http://x", stream_deadline_s=0.2).chat("m", [], on_text=lambda piece: None)
    release.set()
    assert time.monotonic() - started < 2


def test_canvas_says_how_old_its_copy_is(monkeypatch):
    import datetime as dt

    import requests

    from sanae.canvas import CanvasFeed

    now = {"t": dt.datetime(2026, 10, 29, 12).timestamp()}   # a Thursday
    url = "https://canvas.example/feeds/calendars/user_SECRET.ics"
    feed = CanvasFeed(url, cache_s=-1, clock=lambda: now["t"])

    class Fine:
        content = b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"

        def raise_for_status(self):
            pass

    monkeypatch.setattr("sanae.canvas.requests.get", lambda *a, **k: Fine())
    feed.items()
    assert feed.stale_note() == ""

    def down(*a, **k):
        raise requests.ConnectionError(f"can't reach {url}")
    monkeypatch.setattr("sanae.canvas.requests.get", down)
    now["t"] += 3600
    feed.items()                                              # a recent copy: answers carry no note...
    assert feed.stale_note() == "" and services.is_down("canvas")
    assert "SECRET" not in feed.last_error and "SECRET" not in services.snapshot()["canvas"]["why"]

    now["t"] += 2 * 86400
    feed.items()
    assert "copy from Thursday" in feed.stale_note()
    assert "Thursday" in services.snapshot()["canvas"]["why"]  # ...and the dashboard shows it

    monkeypatch.setattr("sanae.canvas.requests.get", lambda *a, **k: Fine())
    feed.items()
    assert feed.stale_note() == "" and not services.is_down("canvas")


def test_a_stale_copy_is_mentioned_in_the_answer():
    from types import SimpleNamespace

    from sanae.tools import canvas as canvas_tools
    from sanae.tools.registry import ToolRegistry

    ctx = SimpleNamespace(cfg={"secrets": {"canvas": {"ics_url": "http://x"}}})
    reg = ToolRegistry(context=ctx)
    canvas_tools.register(reg)
    ctx.canvas.between = lambda *a: []
    ctx.canvas.stale_note = lambda: "That's from my Canvas copy from Thursday, I can't reach Canvas right now."
    assert reg.run("canvas_due", {"period": "this_weekend"}).endswith("from Thursday, I can't reach Canvas right now.")
    assert "Thursday" in reg.run("canvas_classes", {"period": "today"})


class _FakeOllama:
    """/api/chat records the options; /api/ps says what's loaded."""

    def __init__(self, monkeypatch, loaded=()):
        self.sent, self.unloaded, self.loaded = [], [], dict(loaded)
        monkeypatch.setattr("sanae.llm.requests.post", self.post)
        monkeypatch.setattr("sanae.llm.requests.get", self.get)

    def post(self, url, json, timeout, **kw):
        fake = self

        class R:
            status_code, text = 200, ""

            def json(self):
                return {"message": {"content": "hi"}}
        if url.endswith("/api/generate"):
            if json.get("keep_alive") == 0:
                fake.unloaded.append(json["model"])
                fake.loaded.pop(json["model"], None)
        else:
            fake.sent.append(json["options"])
            fake.loaded[json["model"]] = 2600 * 2**20
        return R()

    def get(self, url, timeout):
        fake = self

        class R:
            def json(self):
                return {"models": [{"name": k, "size_vram": v} for k, v in fake.loaded.items()]}
        return R()


def _client(free):
    from sanae.llm import OllamaClient

    return OllamaClient("http://x", num_ctx=4096, gpu_layers={"fast": 99}, vram_free=lambda: free["mb"],
                        tight_free_mb=2800, tight_num_ctx=2048)


def test_free_vram_keeps_the_forced_load(monkeypatch):
    fake = _FakeOllama(monkeypatch)
    _client({"mb": 3000}).chat("fast", [])
    assert fake.sent[0]["num_gpu"] == 99 and fake.sent[0]["num_ctx"] == 4096 and fake.sent[0]["use_mmap"] is False


def test_tight_vram_loads_gently_and_comes_back_when_free(monkeypatch):
    fake = _FakeOllama(monkeypatch)
    free = {"mb": 900}
    client = _client(free)
    client.chat("fast", [])
    assert "num_gpu" not in fake.sent[0] and "use_mmap" not in fake.sent[0] and fake.sent[0]["num_ctx"] == 2048

    free["mb"] = 3500                      # still loaded: changing num_ctx now would force a reload
    client.chat("fast", [])
    assert fake.sent[1]["num_ctx"] == 2048

    client.unload("fast")
    client.chat("fast", [])                # the next load
    assert fake.sent[2]["num_gpu"] == 99 and fake.sent[2]["num_ctx"] == 4096


def test_slow_prompts_with_crowded_vram_do_not_reload_loop(monkeypatch):
    import time

    fake = _FakeOllama(monkeypatch, {"fast": 2600 * 2**20})
    preloads = []
    client = _client({"mb": 100})          # 100 free + its own 2600 < 2800: others hold the rest
    monkeypatch.setattr(client, "preload", lambda *a: preloads.append(a))
    slow = {"prompt_eval_count": 2000, "prompt_eval_duration": 20e9}
    client._check_speed("fast", slow)
    client._check_speed("fast", slow)
    time.sleep(0.1)
    assert fake.unloaded == ["fast"] and preloads == []     # put away, next load is the gentle one
    assert "fast" in client._tight
    for _ in range(6):
        client._check_speed("fast", slow)
    time.sleep(0.1)
    assert fake.unloaded == ["fast"]                        # and never again


def test_slow_prompts_with_free_vram_still_reload(monkeypatch):
    import time

    fake = _FakeOllama(monkeypatch, {"fast": 2600 * 2**20})
    preloads = []
    client = _client({"mb": 1000})         # 1000 + 2600 is plenty: it just loaded badly
    monkeypatch.setattr(client, "preload", lambda *a: preloads.append(a))
    slow = {"prompt_eval_count": 2000, "prompt_eval_duration": 20e9}
    client._check_speed("fast", slow)
    client._check_speed("fast", slow)
    time.sleep(0.1)
    assert fake.unloaded == ["fast"] and preloads == [("fast",)] and "fast" not in client._tight


def test_a_normal_stream_still_works(monkeypatch):
    import json

    from sanae.llm import OllamaClient

    class Fine(_Trickle):
        def iter_lines(self):
            yield json.dumps({"message": {"content": "hi "}}).encode()
            yield b""
            yield json.dumps({"message": {"content": "there"}, "done": True}).encode()

    monkeypatch.setattr("sanae.llm.requests.post", lambda *a, **k: Fine())
    pieces = []
    assert OllamaClient("http://x").chat("m", [], on_text=pieces.append).content == "hi there"
    assert pieces == ["hi ", "there"]
