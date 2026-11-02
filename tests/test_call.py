import base64
from types import SimpleNamespace

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sanae import remote, us_api
from sanae.call import ENDS, Call


def test_call_state_and_goodbyes():
    t = {"now": 1000.0}
    c = Call(clock=lambda: t["now"])
    assert not c.active() and c.note() is None
    c.start()
    assert c.active() and "voice call" in c.note()
    t["now"] += 200
    assert not c.active()                       # 3 quiet minutes
    assert ENDS.search("okay bye!") and ENDS.search("I gotta go") and ENDS.search("talk to you later")
    assert not ENDS.search("bye the way, did you see that") and not ENDS.search("goodbye to my old phone was hard")


def make_app(heard: str):
    said = []
    agent = SimpleNamespace(add_said=lambda text, why="": said.append(text), last_tags=SimpleNamespace(emotion="happy"))
    ctx = SimpleNamespace(agent=agent, persona=SimpleNamespace(name="Sanae"), call=None)
    rt = SimpleNamespace(ctx=ctx, bus=SimpleNamespace(publish=lambda *a: None),
                         run_command=lambda text, source: f"(reply to {text} via {source})")
    app = FastAPI()
    us_api.register(app, rt, stt=lambda: SimpleNamespace(whisper=lambda audio, prompt=None: heard),
                    voice_wav=lambda text: b"WAV:" + text.encode())
    return TestClient(app), ctx, said


def test_call_endpoints():
    client, ctx, said = make_app("how was your day")
    r = client.post("/api/call/start").json()
    assert r["reply"] and "[" not in r["reply"] and base64.b64decode(r["audio"]).startswith(b"WAV:")
    assert said and ctx.call.active()
    wav = remote.encode_wav(np.zeros(8000, dtype=np.float32), 16000)
    r = client.post("/api/call/turn", content=wav).json()
    assert r["heard"] == "how was your day" and r["reply"] == "(reply to how was your day via call)"
    assert r["emotion"] == "happy" and not r["end"]
    client2, ctx2, _ = make_app("okay bye")
    r = client2.post("/api/call/turn", content=wav).json()
    assert r["end"] and not ctx2.call.active()
