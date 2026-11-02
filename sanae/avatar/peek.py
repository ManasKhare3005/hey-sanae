"""Edge-peek: drag her past the left or right edge of the screen and she tucks in there, about
half hidden, peeking out. She slides out when the mouse comes near or when something happens
(she talks, listens, thinks, shows a bubble or a gesture) and slides back a few seconds after.
Dragging her away from the edge undocks her.

`PeekState` is the pure logic (window and screen rectangles in, where the window should go
out); `Peeker` runs it ten times a second against the real window with Win32 calls.
All rectangles are (left, top, right, bottom) in screen pixels.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)
Rect = tuple[int, int, int, int]

SHOWN = 0.46          # share of the window left on screen while tucked in
DOCK_PAST = 0.2       # dropped with more than this share past an edge -> dock there
NEAR_PX = 24          # the mouse this close to the window slides her out
STAY_OUT_S = 2.5      # out this long after the mouse leaves / things calm down
SETTLE_S = 0.35       # a drag counts as finished after the window sits still this long


def dock_side(rect: Rect, work: Rect) -> str | None:
    """Which edge she was dropped past ("left" / "right"), or None if she's on the screen."""
    w = rect[2] - rect[0]
    if work[0] - rect[0] > DOCK_PAST * w:
        return "left"
    if rect[2] - work[2] > DOCK_PAST * w:
        return "right"
    return None


def tucked_x(side: str, work: Rect, width: int) -> int:
    return work[0] - round(width * (1 - SHOWN)) if side == "left" else work[2] - round(width * SHOWN)


def out_x(side: str, work: Rect, width: int) -> int:
    return work[0] if side == "left" else work[2] - width


def near(cursor: tuple[int, int] | None, rect: Rect, pad: int = NEAR_PX) -> bool:
    return cursor is not None and rect[0] - pad <= cursor[0] <= rect[2] + pad and rect[1] - pad <= cursor[1] <= rect[3] + pad


class PeekState:
    """Feed it the window each tick; it says where the window should be (x) or None to leave it."""

    def __init__(self, side: str | None = None):
        self.side = side
        self.out = False
        self.expected: Rect | None = None      # where we last put the window (anything else = a drag)
        self.moved_at = 0.0                   # a drag: when the window last changed
        self.dragging = False
        self.last_reason = 0.0                # last time something wanted her out

    def step(self, rect: Rect, work: Rect, cursor: tuple[int, int] | None, active: bool, now: float) -> int | None:
        width = rect[2] - rect[0]
        if self.expected is not None and rect != self.expected:       # the user is moving her
            self.dragging = True
            self.moved_at = now
            self.expected = rect
            return None
        if self.expected is None:
            self.expected = rect
        if self.dragging:
            if now - self.moved_at < SETTLE_S:
                return None
            self.dragging = False
            self.side = dock_side(rect, work)
            self.out = False
            self.last_reason = -1e9                 # just dropped there: stay tucked until there's a reason
            if self.side is None:
                return None
            return self._go(tucked_x(self.side, work, width), rect)
        if self.side is None:
            return None
        if near(cursor, rect) or active:
            self.last_reason = now
        want_out = now - self.last_reason < STAY_OUT_S
        if want_out != self.out:
            self.out = want_out
        target = out_x(self.side, work, width) if self.out else tucked_x(self.side, work, width)
        return None if rect[0] == target else self._go(target, rect)

    def _go(self, x: int, rect: Rect) -> int:
        self.expected = (x, rect[1], x + rect[2] - rect[0], rect[3])
        return x


# ----- the real window -----

def work_area(rect: Rect) -> Rect | None:
    """The work area (screen minus taskbar) of the monitor the window is mostly on."""
    try:
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        r = wintypes.RECT(*rect)
        mon = ctypes.windll.user32.MonitorFromRect(ctypes.byref(r), 2)        # MONITOR_DEFAULTTONEAREST
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            return None
        w = info.rcWork
        return w.left, w.top, w.right, w.bottom
    except Exception:
        return None


def cursor_pos() -> tuple[int, int] | None:
    try:
        import ctypes
        from ctypes import wintypes

        pt = wintypes.POINT()
        return (pt.x, pt.y) if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)) else None
    except Exception:
        return None


class Peeker:
    """Runs PeekState against the window: slides it (a short eased move) and tells the page which
    side she's tucked into, so she leans in toward the screen."""

    def __init__(self, title: str, path: Path, active: Callable[[], bool], tell_page: Callable[[str], None]):
        self.title = title
        self.path = path
        self.active = active
        self.tell_page = tell_page
        self.state = PeekState(self._saved_side())
        self._told_at = 0.0

    @property
    def docked(self) -> bool:
        return self.state.side is not None

    def _saved_side(self) -> str | None:
        try:
            side = json.loads(self.path.read_text(encoding="utf-8")).get("dock")
            return side if side in ("left", "right") else None
        except (OSError, ValueError, AttributeError):
            return None

    def _hwnd(self):
        import ctypes

        return ctypes.windll.user32.FindWindowW(None, self.title)

    def _rect(self) -> Rect | None:
        import ctypes
        from ctypes import wintypes

        hwnd = self._hwnd()
        r = wintypes.RECT()
        if not hwnd or not ctypes.windll.user32.IsWindowVisible(hwnd) or not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        return r.left, r.top, r.right, r.bottom

    def _slide(self, x0: int, x1: int, y: int, seconds: float = 0.22):
        import ctypes

        hwnd = self._hwnd()
        steps = max(1, int(seconds * 60))
        for i in range(1, steps + 1):
            t = i / steps
            e = 1 - (1 - t) ** 3                                       # ease out
            x = round(x0 + (x1 - x0) * e)
            ctypes.windll.user32.SetWindowPos(hwnd, 0, x, y, 0, 0, 0x0001 | 0x0004 | 0x0010)   # NOSIZE|NOZORDER|NOACTIVATE
            time.sleep(seconds / steps)

    def _save(self, rect: Rect):
        try:
            self.path.write_text(json.dumps({"x": rect[0], "y": rect[1], "w": rect[2] - rect[0], "h": rect[3] - rect[1],
                                             "dock": self.state.side}), encoding="utf-8")
        except OSError:
            pass

    def tick(self):
        rect = self._rect()
        if rect is None:
            return
        work = work_area(rect)
        if work is None:
            return
        was = self.state.side
        x = self.state.step(rect, work, cursor_pos(), self.active(), time.monotonic())
        if x is not None:
            self._slide(rect[0], x, rect[1])
            if self.state.side is not None and not self.state.out:
                self._save(self.state.expected)          # remember the tucked spot (and the side)
        if self.state.side != was or time.monotonic() - self._told_at > 3:      # again now and then: the page may have reloaded
            self._told_at = time.monotonic()
            self.tell_page(self.state.side or "")

    def run(self, stop: threading.Event):
        while not stop.wait(0.1):
            try:
                self.tick()
            except Exception as exc:
                log.debug("edge peek: %s", exc)
