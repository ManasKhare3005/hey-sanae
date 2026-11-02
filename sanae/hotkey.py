"""A global hotkey (default Ctrl+Alt+Y, config `hotkey.combo`), working whichever app is in front:
tap it and Sanae listens, as after the wake word; hold it (~0.6 s) to hide or show her avatar.

RegisterHotKey on a thread of its own with a message loop: no admin rights, no keyboard hook,
nothing sees other keystrokes. Ignored while a fullscreen game is in front (`blocked`).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

MODS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
HOLD_S = 0.6
NAMED_KEYS = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, **{f"f{i}": 0x6F + i for i in range(1, 13)}}


def parse_combo(combo: str) -> tuple[int, int]:
    """'ctrl+alt+y' -> (modifier flags, virtual-key code). Raises ValueError if it can't be used."""
    parts = [p.strip().lower() for p in combo.replace("-", "+").split("+") if p.strip()]
    if not parts:
        raise ValueError("empty hotkey")
    *mods, key = parts
    flags = 0
    for m in mods:
        if m not in MODS:
            raise ValueError(f"unknown modifier {m!r}")
        flags |= MODS[m]
    if key in NAMED_KEYS:
        vk = NAMED_KEYS[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        raise ValueError(f"unknown key {key!r}")
    if not flags:
        raise ValueError("a hotkey needs at least one of ctrl / alt / shift / win")
    return flags, vk


class Hotkey:
    def __init__(self, combo: str, on_tap: Callable[[], None], on_hold: Callable[[], None],
                 blocked: Callable[[], bool] = lambda: False):
        self.combo = combo
        self.mods, self.vk = parse_combo(combo)
        self.on_tap, self.on_hold, self.blocked = on_tap, on_hold, blocked
        self._thread_id = 0
        self._ready = threading.Event()
        self.ok = False

    def start(self) -> "Hotkey":
        threading.Thread(target=self._run, name="hotkey", daemon=True).start()
        self._ready.wait(2)
        return self

    def stop(self):
        if self._thread_id:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _held(self) -> bool:
        """After the press: still holding the key at HOLD_S?"""
        import ctypes

        end = time.monotonic() + HOLD_S
        while time.monotonic() < end:
            if not ctypes.windll.user32.GetAsyncKeyState(self.vk) & 0x8000:
                return False
            time.sleep(0.02)
        return True

    def _run(self):
        import ctypes
        from ctypes import wintypes

        u = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        self.ok = bool(u.RegisterHotKey(None, 1, self.mods | MOD_NOREPEAT, self.vk))
        self._ready.set()
        if not self.ok:
            log.warning("hotkey %s is taken by another app", self.combo)
            return
        log.info("hotkey %s: tap = listen, hold = hide / show the avatar", self.combo)
        msg = wintypes.MSG()
        try:
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message != WM_HOTKEY:
                    continue
                try:
                    if self.blocked():
                        continue
                    (self.on_hold if self._held() else self.on_tap)()
                except Exception as exc:
                    log.warning("hotkey action failed: %s", exc)
        finally:
            u.UnregisterHotKey(None, 1)
