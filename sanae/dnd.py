"""Do-not-disturb: when she shouldn't talk first. Answering when spoken to is never blocked.

- a fullscreen game, video or presentation is in front (Windows' own "busy" state, or a game window)
- another app is using the microphone or camera (a call or a meeting)
- "not now" / "quiet for an hour" (quiet_for), and quiet hours from persona.yaml
- the models are asleep ("go to sleep" / free_gpu): she's off duty until woken
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys
import time

log = logging.getLogger(__name__)

# SHQueryUserNotificationState: 2 busy (fullscreen app), 3 Direct3D fullscreen, 4 presentation mode
BUSY_STATES = {2: "a fullscreen app", 3: "a fullscreen game", 4: "presentation mode"}


def notification_state() -> int:
    if sys.platform != "win32":
        return 0
    import ctypes

    state = ctypes.c_int(0)
    try:
        ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
    except Exception:
        return 0
    return state.value


def devices_in_use(kind: str, ignore: tuple[str, ...] = ()) -> list[str]:
    """Apps using the microphone or webcam right now (kind "microphone" / "webcam"), from Windows'
    privacy records: an entry whose LastUsedTimeStop is 0 is still recording. Entries go stale when
    an app crashes mid-call, so a desktop app must also be running right now (a store app: started
    within the last 6 hours). Our own Python (the always-on wake word listener) is ignored."""
    import psutil

    if sys.platform != "win32":
        return []
    import winreg

    base = rf"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\{kind}"
    ours = {os.path.normcase(p) for p in (sys.executable, sys.executable.replace("pythonw", "python"),
                                          sys.executable.replace("python.exe", "pythonw.exe"))}
    using: list[str] = []
    running: set[str] | None = None
    recent = (time.time() + 11644473600 - 6 * 3600) * 10_000_000          # 6 h ago as a FILETIME

    def walk(key, name, desktop):
        nonlocal running
        try:
            stop, _ = winreg.QueryValueEx(key, "LastUsedTimeStop")
            start, _ = winreg.QueryValueEx(key, "LastUsedTimeStart")
        except OSError:
            return
        if stop != 0 or not start:
            return
        path = os.path.normcase(name.replace("#", "\\"))
        if path in ours or any(i in path for i in ignore):
            return
        if desktop:
            if running is None:
                running = set()
                for proc in psutil.process_iter(["exe"]):
                    if proc.info.get("exe"):
                        running.add(os.path.normcase(proc.info["exe"]))
            if path not in running:
                return
        elif start < recent:
            return
        using.append(path.rsplit("\\", 1)[-1])

    for hive in (winreg.HKEY_CURRENT_USER,):
        try:
            root = winreg.OpenKey(hive, base)
        except OSError:
            continue
        with root:
            for i in range(512):
                try:
                    sub = winreg.EnumKeyEx(root, i) if hasattr(winreg, "EnumKeyEx") else winreg.EnumKey(root, i)
                except OSError:
                    break
                with winreg.OpenKey(root, sub) as k:
                    if sub == "NonPackaged":
                        for j in range(512):
                            try:
                                app = winreg.EnumKey(k, j)
                            except OSError:
                                break
                            with winreg.OpenKey(k, app) as ak:
                                walk(ak, app, True)
                    else:
                        walk(k, sub, False)
    return using


class DoNotDisturb:
    def __init__(self, quiet_hours=(), games_check=None, asleep=lambda: False, ignore_apps=("python",)):
        self.quiet_until = 0.0
        self.quiet_hours = list(quiet_hours or [])
        self.games_check = games_check          # () -> bool: a fullscreen game in front (avatar's check)
        self.asleep = asleep
        self.ignore_apps = tuple(ignore_apps)
        self.holds = []                         # () -> reason or None: e.g. watching.py while a show is on

    def quiet_for(self, minutes: float):
        self.quiet_until = time.time() + minutes * 60

    def resume(self):
        self.quiet_until = 0.0

    def _in_quiet_hours(self, now: dt.datetime) -> bool:
        if len(self.quiet_hours) != 2:
            return False
        start, end = (dt.time.fromisoformat(t) for t in self.quiet_hours)
        t = now.time()
        return start <= t < end if start < end else (t >= start or t < end)

    def reason(self, now: dt.datetime | None = None) -> str | None:
        """Why she should stay quiet right now, or None."""
        if self.asleep():
            return "asleep"
        if time.time() < self.quiet_until:
            return f"quiet until {dt.datetime.fromtimestamp(self.quiet_until):%H:%M}"
        if self._in_quiet_hours(now or dt.datetime.now()):
            return "quiet hours"
        for hold in self.holds:
            try:
                why = hold()
            except Exception as exc:
                log.debug("dnd hold failed: %s", exc)
                why = None
            if why:
                return why
        state = notification_state()
        if state in BUSY_STATES:
            return BUSY_STATES[state]
        try:
            if self.games_check is not None and self.games_check():
                return "a game"
        except Exception as exc:
            log.debug("game check failed: %s", exc)
        try:
            for kind, what in (("microphone", "the mic"), ("webcam", "the camera")):
                apps = devices_in_use(kind, self.ignore_apps)
                if apps:
                    return f"{apps[0]} is using {what}"
        except Exception as exc:
            log.debug("device check failed: %s", exc)
        return None
