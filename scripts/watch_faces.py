"""Render Sanae's face in each emotion for the Galaxy Watch app (android/wear/.../face_<emotion>.png).

Loads the 3D avatar page from dashboard/dist in a headless browser (never the real screen), with a
fake link so she's awake, sets each emotion and crops her head. Re-run after changing her look:
    npm run build (in dashboard)  then  .venv\\Scripts\\python scripts\\watch_faces.py
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
OUT = ROOT / "android" / "wear" / "src" / "main" / "res" / "drawable-nodpi"
EMOTIONS = ["neutral", "happy", "shy", "laugh", "thinking", "sad", "surprised", "sleepy"]
HEAD = (105, 25, 295, 215)     # css px of the 400x420 upper-body frame
SIZE = 192


def main(model: str = "avatar/sanae.vrm"):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    hello = json.dumps({"id": 1, "ts": 0, "kind": "hello", "data": {"state": {"stage": {"stage": "idle"}}, "recent": []}})
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 400, "height": 420}, device_scale_factor=2)
        page.route_web_socket("**/api/ws**", lambda ws: ws.send(hello))
        page.goto(f"http://127.0.0.1:{server.server_address[1]}/avatar.html?standalone=1&cursor=0"
                  f"&frame=upper&scale=2&bubble=0&model={model.replace('/', '%2F')}")
        page.wait_for_function("() => window.sanaeAvatar && window.sanaeAvatar.state().loaded", timeout=60000)
        page.wait_for_timeout(3000)
        for emotion in EMOTIONS:
            page.evaluate("() => window.sanaeAvatar.look(0, 0)")
            page.evaluate(f"() => window.sanaeAvatar.emotion('{emotion}', 600000)")
            page.wait_for_timeout(2500)
            if emotion != "sleepy":                       # no blink caught mid-shot (sleepy's eyes are half shut)
                page.evaluate("() => window.sanaeAvatar.morph('EYE_Close', 0)")
                page.wait_for_timeout(100)
            x0, y0, x1, y1 = HEAD
            shot = page.screenshot(clip={"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}, omit_background=True)
            face = Image.open(io.BytesIO(shot)).convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS)
            bg = Image.new("RGBA", face.size, (15, 23, 42, 255))          # the watch's face circle colour
            bg.alpha_composite(face)
            bg.convert("RGB").save(OUT / f"face_{emotion}.png", optimize=True)
            page.evaluate("() => window.sanaeAvatar.morph(null)")
            print("saved", f"face_{emotion}.png")
        browser.close()
    server.shutdown()


if __name__ == "__main__":
    main()
