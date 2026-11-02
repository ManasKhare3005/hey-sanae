"""Render Sanae for the phone app: a transparent upper-body portrait and a head crop per emotion
(android/app/src/main/res/drawable-nodpi/sanae_<emotion>.webp and face_<emotion>.webp).

Same way as scripts/watch_faces.py: the 3D avatar page from dashboard/dist in a headless browser
(never the real screen), with a fake link so she's awake. Re-run after changing her look:
    npm run build (in dashboard)  then  .venv\\Scripts\\python scripts\\phone_faces.py
"""
from __future__ import annotations

import functools
import http.server
import io
import json
import threading
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dashboard" / "dist"
OUT = ROOT / "android" / "app" / "src" / "main" / "res" / "drawable-nodpi"
EMOTIONS = ["neutral", "happy", "shy", "laugh", "thinking", "sad", "surprised", "sleepy"]
HEAD = (105, 25, 295, 215)      # css px of the 400x420 upper-body frame
PORTRAIT_W = 900                # the Sanae screen shows her large; sharp on 3x screens
FACE = 384


def main(model: str = "avatar/sanae.vrm"):
    OUT.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    hello = json.dumps({"id": 1, "ts": 0, "kind": "hello", "data": {"state": {"stage": {"stage": "idle"}}, "recent": []}})
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 400, "height": 420}, device_scale_factor=3)
        page.route_web_socket("**/api/ws**", lambda ws: ws.send(hello))
        page.goto(f"http://127.0.0.1:{server.server_address[1]}/avatar.html?standalone=1&cursor=0"
                  f"&frame=upper&scale=2&bubble=0&season=0&model={model.replace('/', '%2F')}")
        page.wait_for_function("() => window.sanaeAvatar && window.sanaeAvatar.state().loaded", timeout=60000)
        page.wait_for_timeout(3000)
        for emotion in EMOTIONS:
            page.evaluate("() => window.sanaeAvatar.look(0, 0)")
            page.evaluate(f"() => window.sanaeAvatar.emotion('{emotion}', 600000)")
            page.wait_for_timeout(2500)
            if emotion != "sleepy":                       # no blink caught mid-shot (sleepy's eyes are half shut)
                page.evaluate("() => window.sanaeAvatar.morph('EYE_Close', 0)")
                page.wait_for_timeout(100)
            full = Image.open(io.BytesIO(page.screenshot(omit_background=True))).convert("RGBA")
            box = full.getbbox() or (0, 0, *full.size)
            body = full.crop((0, 0, full.width, box[3]))
            h = round(body.height * PORTRAIT_W / body.width)
            body.resize((PORTRAIT_W, h), Image.LANCZOS).save(OUT / f"sanae_{emotion}.webp", quality=88, method=6)
            x0, y0, x1, y1 = (v * 3 for v in HEAD)
            full.crop((x0, y0, x1, y1)).resize((FACE, FACE), Image.LANCZOS).save(OUT / f"face_{emotion}.webp", quality=88, method=6)
            page.evaluate("() => window.sanaeAvatar.morph(null)")
            print("saved", emotion)
        browser.close()
    server.shutdown()


if __name__ == "__main__":
    main()
