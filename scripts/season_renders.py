"""Render Sanae in each seasonal look (season.ts) to check how they sit: one PNG per look in an
output folder. Uses the built avatar page in a headless browser (never the real screen).

    npm run build (in dashboard)  then  .venv\\Scripts\\python scripts\\season_renders.py [out_dir]
"""
from __future__ import annotations

import functools
import http.server
import json
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dashboard" / "dist"
LOOKS = {
    "halloween": "2026-10-31T20:00", "christmas": "2026-12-24T20:00", "new_year": "2026-12-31T20:00",
    "valentine": "2027-02-14T20:00", "spring": "2027-04-10T15:00", "summer": "2027-07-10T15:00",
    "autumn": "2026-09-20T15:00", "winter": "2027-01-20T15:00", "late_night": "2026-09-20T23:30",
    "after_midnight": "2026-09-21T01:30", "halloween_night": "2026-10-31T23:30",
}


def main(out: Path, model: str = "avatar/sanae.vrm", only: list[str] | None = None):
    out.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    hello = json.dumps({"id": 1, "ts": 0, "kind": "hello", "data": {"state": {"stage": {"stage": "idle"}}, "recent": []}})
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 400, "height": 420}, device_scale_factor=1)
        page.route_web_socket("**/api/ws**", lambda ws: ws.send(hello))
        page.goto(f"http://127.0.0.1:{server.server_address[1]}/avatar.html?standalone=1&cursor=0"
                  f"&frame=upper&scale=1&bubble=0&model={model.replace('/', '%2F')}")
        page.wait_for_function("() => window.sanaeAvatar && window.sanaeAvatar.state().loaded", timeout=90000)
        page.wait_for_timeout(2000)
        for name, when in LOOKS.items():
            if only and name not in only:
                continue
            look = page.evaluate(f"() => window.sanaeAvatar.season('{when}')")
            page.evaluate("() => window.sanaeAvatar.look(0, 0)")
            page.wait_for_timeout(2500)
            if "night" not in name and "midnight" not in name:
                page.evaluate("() => window.sanaeAvatar.morph('EYE_Close', 0)")
                page.wait_for_timeout(100)
            page.screenshot(path=str(out / f"{name}.png"), omit_background=False)
            page.evaluate("() => window.sanaeAvatar.morph(null)")
            print(name, look)
        browser.close()
    server.shutdown()


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "season-renders", only=sys.argv[2:] or None)
