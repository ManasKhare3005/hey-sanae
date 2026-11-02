"""Her slow brain: Claude (through Claude Code on this laptop) for thinking that isn't live chat.

Live talk stays on the local model. Claude only gets background jobs where a stronger mind
helps and a few seconds don't matter: the nightly look back (reflect.py), her own aims for the
week, and checking a line she wants to say first before she says it. Photos from the phone go to
Claude too (vision.py; the local vision model needs ~4 GB of RAM the laptop doesn't have), unless
you say it's a secret: then the local model looks.

Private stays private. Everything goes through `Redactor` first:
  - never sent at all: hard-moment turns (comfort.py), private notebook pages, health numbers,
    turns that weren't your voice; and nothing goes out while comfort mode is on;
  - sentences about health, money, credentials, religion, politics, sexuality, addresses
    (friend.SENSITIVE) are dropped; emails, phone numbers, links and long numbers are masked;
  - your name becomes "the user" and people you mention become "a friend" (put back on the
    way in, so a lesson can still say "Alex").
Claude Code runs with no tools, no MCP servers, no settings or hooks, in an empty folder, and
nothing is kept as a session. Every call is logged, exactly as sent, to data/brain/sent-YYYY-MM.jsonl.
At most `daily_calls` a day (it uses your Claude plan's limits). Without Claude Code, or when it
fails, every caller keeps its local behaviour.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from .config import ROOT

log = logging.getLogger(__name__)
NO_WINDOW = 0x08000000
DIR = ROOT / "data" / "brain"

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
LINK = re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.I)
LONG_NUMBER = re.compile(r"\b\d{6,}\b")
SECRET = re.compile(r"\b(?:sk|pk|ghp|gho|xox[bp])[-_][\w-]{8,}\b|\b[A-Za-z0-9_-]{32,}\b")
NAME_CUE = re.compile(r"\b(?:with|friend|sister|brother|mom|mum|dad|cousin|roommate|girlfriend|boyfriend|partner|"
                      r"wife|husband|boss|professor|reminded me of|texted|called|met|and)\s+([A-Z][a-z]{2,})\b")
NOT_NAMES = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "January", "February",
             "March", "April", "May", "June", "July", "August", "September", "October", "November", "December",
             "The", "This", "That", "What", "When", "Then", "And", "But", "Not", "Yes", "Okay", "Today", "Tomorrow",
             "Yesterday", "Christmas", "Halloween", "English", "Japanese", "Hindi", "Python", "Java", "Google",
             "YouTube", "Spotify", "Netflix", "Discord", "Valorant", "League", "Claude", "Windows", "Android"}
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


class Redactor:
    """Text -> what may leave the laptop (or None when nothing safe is left)."""

    def __init__(self, user: str = "", her: str = "Sanae", people: Callable[[], list[str]] = lambda: []):
        self.user, self.her, self.people = user, her, people

    def names(self, text: str = "") -> list[str]:
        found = set(self.people())
        found.update(m for m in NAME_CUE.findall(text) if m not in NOT_NAMES)
        return sorted(n for n in found if n and n not in (self.user, self.her) and n not in NOT_NAMES)

    def clean_all(self, texts: list[str]) -> list[str | None]:
        """Several texts that belong together (a day's chat): a name seen in any of them is hidden in
        all of them (she repeats names you said without the cue that gave them away)."""
        names = self.names(" ".join(t or "" for t in texts))
        return [self.clean(t, names) for t in texts]

    def clean(self, text: str, names: list[str] | None = None) -> str | None:
        from .friend import sensitive

        if not text or not text.strip():
            return None
        kept = [s for s in SENTENCE.split(text) if s.strip() and not sensitive(s)]
        if not kept:
            return None
        known = set(self.names(text)) | set(names or []) | {self.user, self.her}
        out = " ".join(self._other_names(s, known) for s in kept)
        out = EMAIL.sub("[email]", out)
        out = LINK.sub("[link]", out)
        out = SECRET.sub("[hidden]", out)
        out = PHONE.sub("[number]", out)
        out = LONG_NUMBER.sub("[number]", out)
        for n in sorted(set(self.names(text)) | set(names or [])):
            out = re.sub(rf"\b{re.escape(n)}\b", "a friend", out)
        if self.user:
            out = re.sub(rf"\b{re.escape(self.user)}\b", "the user", out)
        return out

    @staticmethod
    def _other_names(sentence: str, known: set[str]) -> str:
        """Capitalised words inside a sentence (not its first word) that aren't days, months or apps
        are probably people or places: "[name]". Known names are swapped later, as "a friend"."""
        words = sentence.split(" ")
        for i in range(1, len(words)):
            m = re.match(r"^([\W]*)([A-Z][a-z]{2,})('s|s')?(\W*)$", words[i])
            if m and m.group(2) not in NOT_NAMES and m.group(2) not in known and not words[i - 1].endswith((".", "!", "?", ":")):
                words[i] = f"{m.group(1)}[name]{m.group(3) or ''}{m.group(4)}"
        return " ".join(words)

    def back(self, text: str) -> str:
        """Claude's words -> hers: "the user" is your name again."""
        if not self.user:
            return text
        out = re.sub(r"\b[Tt]he user's\b", f"{self.user}'s", text)
        return re.sub(r"\b[Tt]he user\b", self.user, out)


def find_claude() -> str | None:
    from .devloop import find_claude as find

    exe = find()
    return exe if exe and (Path(exe).exists() or exe == "claude") else None


class CloudBrain:
    """ask(task, system, prompt, schema) -> dict | None, logged and limited."""

    def __init__(self, cfg: dict | None = None, user: str = "", her: str = "Sanae",
                 people: Callable[[], list[str]] = lambda: [], private_now: Callable[[], bool] = lambda: False,
                 run: Callable | None = None, clock=time.time, folder: Path = DIR, see: Callable | None = None):
        cfg = cfg or {}
        self.enabled = bool(cfg.get("cloud", False))
        self.model = cfg.get("model", "sonnet")
        self.daily_calls = int(cfg.get("daily_calls", 30))
        self.daily_photos = int(cfg.get("daily_photos", 40))
        self.timeout = float(cfg.get("timeout_s", 120))
        self.redactor = Redactor(user, her, people)
        self.private_now = private_now
        self.clock = clock
        self.folder = Path(folder)
        self._run = run or self._claude
        self._see = see or self._claude_see
        self._lock = threading.Lock()
        self._calls: dict[str, int] = {}
        self.claude = find_claude() if run is None and self.enabled else None
        self.last_error = ""

    @property
    def available(self) -> bool:
        return self.enabled and (self.claude is not None or self._run != self._claude)

    def clean(self, text: str) -> str | None:
        return self.redactor.clean(text)

    def clean_all(self, texts: list[str]) -> list[str | None]:
        return self.redactor.clean_all(texts)

    def _today(self) -> str:
        return dt.datetime.fromtimestamp(self.clock()).date().isoformat()

    def calls_today(self) -> int:
        return self._calls.get(self._today(), 0)

    def photos_today(self) -> int:
        return self._calls.get("photo:" + self._today(), 0)

    def ask(self, task: str, system: str, prompt: str, schema: dict) -> dict | None:
        """`prompt` must already be cleaned (clean()). Returns Claude's JSON, or None."""
        if not self.available or self.private_now():
            return None
        with self._lock:
            if self.calls_today() >= self.daily_calls:
                log.info("brain: daily limit reached (%d), %s stays local", self.daily_calls, task)
                return None
            self._calls[self._today()] = self.calls_today() + 1
        started = time.monotonic()
        try:
            got = self._run(system, prompt, schema)
            self.last_error = ""
        except Exception as exc:
            got, self.last_error = None, str(exc)[:200]
            log.info("brain: %s failed: %s", task, exc)
        self._log(task, system, prompt, got, time.monotonic() - started)
        return got

    def see(self, system: str, prompt: str, jpeg: bytes, schema: dict) -> dict | None:
        """Claude looks at a photo (vision.py): no GPU or RAM on the laptop. Photos have their own
        daily limit (`daily_photos`); the log keeps the question, never the photo. None = look locally."""
        if not self.available or self.private_now():
            return None
        key = "photo:" + self._today()
        with self._lock:
            if self._calls.get(key, 0) >= self.daily_photos:
                log.info("brain: photo limit reached (%d), this one stays local", self.daily_photos)
                return None
            self._calls[key] = self._calls.get(key, 0) + 1
        started = time.monotonic()
        try:
            got = self._see(system, prompt, jpeg, schema)
            self.last_error = ""
        except Exception as exc:
            got, self.last_error = None, str(exc)[:200]
            log.info("brain: photo failed: %s", exc)
        self._log("photo", system, f"[a photo, {len(jpeg) // 1024} KB]\n{prompt}", got, time.monotonic() - started)
        return got

    def _log(self, task: str, system: str, prompt: str, got, seconds: float):
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            d = dt.datetime.fromtimestamp(self.clock())
            entry = {"t": d.isoformat(timespec="seconds"), "task": task, "seconds": round(seconds, 1),
                     "sent": {"system": system, "prompt": prompt}, "got": got}
            with open(self.folder / f"sent-{d:%Y-%m}.jsonl", "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.debug("brain log: %s", exc)

    def recent(self, n: int = 10) -> list[dict]:
        """The last calls as logged (for the phone's "what was sent")."""
        files = sorted(self.folder.glob("sent-*.jsonl"))[-2:]
        lines: list[str] = []
        for p in files:
            try:
                lines += p.read_text(encoding="utf-8").splitlines()
            except OSError:
                pass
        out = []
        for line in lines[-n:][::-1]:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    def _claude(self, system: str, prompt: str, schema: dict) -> dict | None:
        self.folder.mkdir(parents=True, exist_ok=True)
        empty = self.folder / "work"                     # no CLAUDE.md or project files to read
        empty.mkdir(exist_ok=True)
        cmd = [self.claude, "-p", "--output-format", "json", "--tools", "", "--model", self.model,
               "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "",
               "--system-prompt", system, "--json-schema", json.dumps(schema)]
        p = subprocess.run(cmd, cwd=str(empty), input=prompt, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=self.timeout, creationflags=NO_WINDOW)
        try:
            data = json.loads(p.stdout)
        except ValueError:
            raise RuntimeError(f"claude said: {(p.stdout or p.stderr)[:200]}")
        if data.get("is_error"):
            raise RuntimeError(str(data.get("result"))[:200])
        out = data.get("structured_output")
        if out is None:
            out = json.loads(data.get("result") or "null")
        return out if isinstance(out, dict) else None

    def _claude_see(self, system: str, prompt: str, jpeg: bytes, schema: dict) -> dict | None:
        """The same locked-down `claude -p`, with the photo as an image block (stream-json input)."""
        self.folder.mkdir(parents=True, exist_ok=True)
        empty = self.folder / "work"
        empty.mkdir(exist_ok=True)
        msg = {"type": "user", "message": {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(jpeg).decode()}},
            {"type": "text", "text": prompt}]}}
        cmd = [self.claude, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--tools", "", "--model", self.model, "--no-session-persistence", "--strict-mcp-config",
               "--setting-sources", "", "--system-prompt", system, "--json-schema", json.dumps(schema)]
        p = subprocess.run(cmd, cwd=str(empty), input=json.dumps(msg) + "\n", capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=self.timeout, creationflags=NO_WINDOW)
        for line in reversed(p.stdout.splitlines()):
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if data.get("type") != "result":
                continue
            if data.get("is_error"):
                raise RuntimeError(str(data.get("result"))[:200])
            out = data.get("structured_output")
            if out is None:
                out = json.loads(data.get("result") or "null")
            return out if isinstance(out, dict) else None
        raise RuntimeError(f"claude said: {(p.stdout or p.stderr)[-200:]}")

    def status(self) -> dict:
        return {"enabled": self.enabled, "available": self.available, "model": self.model,
                "calls_today": self.calls_today(), "daily_calls": self.daily_calls, "error": self.last_error,
                "photos_today": self.photos_today(), "daily_photos": self.daily_photos}


def private_now(ctx) -> bool:
    """True while nothing should leave the laptop (a hard moment, or a secret they just told her)."""
    comfort = getattr(ctx, "comfort", None)
    mind = getattr(ctx, "mind", None)
    try:
        return bool((comfort is not None and comfort.serious) or (mind is not None and mind.privacy.secret))
    except Exception:
        return True
