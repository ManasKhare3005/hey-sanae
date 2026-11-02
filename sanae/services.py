"""The programs Sanae leans on but doesn't own: Ollama (secrets, comfort mode, the fallback when
Claude fails) and SearXNG (private web search).

`note(name, up, why)` is called by whoever just used one, and by the watcher here. A service going
down is logged once, and once when it comes back, however many calls hit it in between (933 copies
of "Can't reach Ollama" in one log). `Services` checks them on start-up and every minute, starts
what's down, and tells the dashboard.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

import requests

from .config import ROOT

log = logging.getLogger(__name__)
NO_WINDOW = 0x08000000
DETACHED = 0x00000008

_lock = threading.Lock()
_state: dict[str, dict] = {}
_listeners: list[Callable[[dict], None]] = []


def note(name: str, up: bool, why: str = "") -> bool:
    """What a caller just saw. True if that's a change (and so was logged)."""
    with _lock:
        was = _state.get(name)
        _state[name] = {"up": bool(up), "why": "" if up else str(why)[:200], "since": was["since"] if was and was["up"] == bool(up) else time.time()}
        changed = was is None and not up or was is not None and was["up"] != bool(up)
        listeners = list(_listeners)
    if changed:
        if up:
            log.warning("%s is back", name)
        else:
            log.warning("%s is down: %s", name, why)
        for listen in listeners:
            try:
                listen(snapshot())
            except Exception as exc:
                log.debug("service listener failed: %s", exc)
    return changed


def is_down(name: str) -> bool:
    with _lock:
        s = _state.get(name)
        return bool(s and not s["up"])


def snapshot() -> dict:
    with _lock:
        return {k: dict(v) for k, v in _state.items()}


def reset():
    """Forget everything (tests)."""
    with _lock:
        _state.clear()
        _listeners.clear()


def listen(fn: Callable[[dict], None]):
    with _lock:
        _listeners.append(fn)


def ollama_up(host: str) -> bool:
    try:
        return requests.get(f"{host.rstrip('/')}/api/tags", timeout=3).ok
    except requests.RequestException:
        return False


def searxng_up(url: str) -> bool:
    try:
        return requests.get(url.rstrip("/") + "/", timeout=3).status_code < 500
    except requests.RequestException:
        return False


def start_ollama() -> str:
    """The Ollama app if it's installed (it keeps the server alive), else `ollama serve`. Returns
    what was started, or "" if Ollama isn't on this machine."""
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama"
    app = base / "ollama app.exe"
    flags = (NO_WINDOW | DETACHED) if os.name == "nt" else 0
    if app.exists():
        cmd = [str(app)]
    else:
        exe = shutil.which("ollama") or (str(base / "ollama.exe") if (base / "ollama.exe").exists() else None)
        if not exe:
            return ""
        cmd = [exe, "serve"]
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags)
    return cmd[0]


def start_searxng(root: Path = ROOT, timeout: float = 180) -> str:
    """`docker compose up -d searxng`, if Docker is here and its engine is running. Returns what
    went wrong, "" if it started."""
    docker = shutil.which("docker")
    if not docker:
        return "Docker isn't installed"
    flags = NO_WINDOW if os.name == "nt" else 0
    try:
        done = subprocess.run([docker, "compose", "up", "-d", "searxng"], cwd=str(root), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, creationflags=flags)
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    return "" if done.returncode == 0 else (done.stderr or done.stdout or "docker compose failed").strip()[:200]


class Services:
    """Checks each service, starts it if it's down (at most every `retry_s`)."""

    def __init__(self, checks: dict[str, Callable[[], bool]], starters: dict[str, Callable[[], str | None]] | None = None,
                 retry_s: float = 600, clock=time.monotonic):
        self.checks = checks
        self.starters = starters or {}
        self.retry_s = retry_s
        self.clock = clock
        self._tried: dict[str, float] = {}
        self._stop = threading.Event()

    def check(self, name: str) -> bool:
        try:
            up = bool(self.checks[name]())
        except Exception as exc:
            log.debug("checking %s failed: %s", name, exc)
            up = False
        note(name, up, "not answering")
        if not up:
            self._start(name)
        return up

    def _start(self, name: str):
        start = self.starters.get(name)
        now = self.clock()
        if start is None or now - self._tried.get(name, -self.retry_s) < self.retry_s:
            return
        self._tried[name] = now
        try:
            log.info("starting %s: %s", name, start() or "done")
        except Exception as exc:
            log.info("couldn't start %s: %s", name, exc)

    def run_once(self):
        for name in self.checks:
            self.check(name)

    def start(self, every_s: float = 60):
        def run():
            while True:
                try:
                    self.run_once()
                except Exception as exc:
                    log.debug("service check failed: %s", exc)
                if self._stop.wait(every_s):
                    return
        threading.Thread(target=run, name="services", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()


def make_services(cfg) -> Services:
    """From config: llm.host, web.searxng_url; `services.autostart: false` only watches."""
    host = cfg.llm.host
    url = (cfg.get("web", {}) or {}).get("searxng_url") or ""
    auto = (cfg.get("services", {}) or {}).get("autostart", True)
    checks: dict[str, Callable[[], bool]] = {"ollama": lambda: ollama_up(host)}
    starters: dict[str, Callable[[], str | None]] = {"ollama": start_ollama} if auto else {}
    if url:
        checks["searxng"] = lambda: searxng_up(url)
        if auto:
            starters["searxng"] = start_searxng
    return Services(checks, starters, float((cfg.get("services", {}) or {}).get("retry_min", 10)) * 60)
