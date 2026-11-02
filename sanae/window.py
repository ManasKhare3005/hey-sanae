"""What's in front: the active window's app and title, for a little context ("still on that LeetCode
problem?" / "what do you think of this?").

Read on demand, kept in memory only: never written to the database, the logs, the conversation log
or the phone. Titles that may hold private things are never read at all: password managers, banking,
private / incognito windows, sign-in pages, secrets files, plus anything in `context.blocklist`.
"""
from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass

BLOCKED_APPS = {"keepass.exe", "keepassxc.exe", "1password.exe", "bitwarden.exe", "lastpass.exe", "dashlane.exe",
                "enpass.exe", "proton pass.exe", "keeper.exe", "credentialuibroker.exe", "consent.exe", "lockapp.exe",
                "logonui.exe", "authy desktop.exe"}
BLOCKED_TITLE = re.compile(
    r"\b(password|passcode|passkey|sign[ -]?in|log[ -]?in|2fa|two-factor|verification code|one-time|otp|"
    r"incognito|inprivate|private browsing|bank\w*|paypal|venmo|zelle|credit card|checkout|payment|"
    r"secret\w*|\.env\b|credentials?|token|api key|private key|\.pem\b|id_rsa|wallet|seed phrase|"
    r"medical|patient portal|mychart|health)\b", re.I)
BROWSER_SUFFIX = re.compile(r"\s+[-–—]\s+(Google Chrome|Microsoft Edge|Mozilla Firefox|Brave|Opera|Vivaldi|Arc)\s*$")
APP_NAMES = {"chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox", "code.exe": "VS Code",
             "windowsterminal.exe": "Terminal", "explorer.exe": "File Explorer", "spotify.exe": "Spotify",
             "discord.exe": "Discord", "winword.exe": "Word", "excel.exe": "Excel", "powerpnt.exe": "PowerPoint",
             "notepad.exe": "Notepad", "idea64.exe": "IntelliJ", "pycharm64.exe": "PyCharm", "obsidian.exe": "Obsidian",
             "notion.exe": "Notion", "slack.exe": "Slack", "teams.exe": "Teams", "ms-teams.exe": "Teams", "zoom.exe": "Zoom"}
OWN = re.compile(r"\b(Sanae|Max)\b.*\b(avatar|Mission Control|overlay)\b|^Sanae$", re.I)


@dataclass(frozen=True)
class Window:
    app: str           # "VS Code"
    title: str         # "main.py - jarvis" (browser name removed)

    def describe(self) -> str:
        return f"{self.app}: {self.title}" if self.title else self.app


def clean(exe: str, title: str, blocklist: list[str] | tuple = ()) -> Window | None:
    """Raw foreground window -> Window, or None if it must not be read (or there's nothing useful)."""
    exe_l = os.path.basename(exe or "").lower()
    title = " ".join((title or "").split())
    if not exe_l or exe_l in BLOCKED_APPS:
        return None
    if BLOCKED_TITLE.search(title) or OWN.search(title):
        return None
    for word in blocklist or ():
        w = str(word).strip().lower()
        if w and (w in title.lower() or w == exe_l):
            return None
    title = BROWSER_SUFFIX.sub("", title)[:120]
    app = APP_NAMES.get(exe_l) or exe_l.removesuffix(".exe").replace("_", " ").title()
    if not title and app == "File Explorer":
        return None
    return Window(app, title)


def foreground_raw() -> tuple[str, str]:
    """(exe path, title) of the window in front, or ("", "")."""
    if sys.platform != "win32":
        return "", ""
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    hwnd = u.GetForegroundWindow()
    if not hwnd:
        return "", ""
    n = u.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(hwnd, buf, n + 1)
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        import psutil

        exe = psutil.Process(pid.value).name()
    except Exception:
        exe = ""
    return exe, buf.value


class WindowWatch:
    """The current window and how long it's been in front (for "noticing" lines)."""

    def __init__(self, blocklist=(), read=foreground_raw, clock=time.monotonic):
        self.blocklist = list(blocklist or [])
        self.read = read
        self.clock = clock
        self.current: Window | None = None
        self.since = clock()

    def now(self) -> Window | None:
        try:
            w = clean(*self.read(), self.blocklist)
        except Exception:
            w = None
        if w != self.current:
            self.current = w
            self.since = self.clock()
        return w

    def steady_s(self) -> float:
        """How long the same window has been in front (call now() first)."""
        return self.clock() - self.since if self.current else 0.0


# "what do you think of this?", "help me with this", "what am I looking at" -> add the window to the request
ABOUT_SCREEN = re.compile(r"\b(this|these|that one|in front of me|what i'?m (doing|working on|looking at|watching|reading|"
                          r"listening to|playing)|my screen|this (page|tab|window|video|song|code|error|file|doc))\b", re.I)


def wants_context(text: str) -> bool:
    return bool(ABOUT_SCREEN.search(text or ""))
