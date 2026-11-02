"""Claude as her whole mind (an experiment Alex asked for on 2026-10-29: "link it to my Claude as
much as possible and see how that leads us").

`ClaudeMind` stands in for the Ollama client: every llm.chat() Sanae makes (live chat with her
tools, chat summaries, friend memory, diary, her own lines, recipes, stories...) goes to Claude
through Claude Code (`claude -p`, your Claude plan, no API key). The agent loop, tools, safety
checks and approvals don't change: Claude answers with {reply, tool_calls, after} as JSON and the
agent runs the tools exactly as it did for the local model.

The local model (Ollama) is still there, loaded only when needed and put away after a few minutes:
  - "let this be a secret between us" / "between you and me" / "off the record": that message
    and the next `secret_min` minutes stay local ("secret's over" / "you can tell Claude" ends it);
  - comfort mode (a hard moment, comfort.py);
  - any call that contains words from an earlier private moment (kept in kv "private:texts" for
    30 days), so a diary or a chat summary written about a secret stays local too; what the local
    model writes in those calls is marked private in turn;
  - photos with images in the request, when Claude fails or isn't set up, or past `daily_calls`.

Speed: Claude Code takes ~1.7 s to start, so one process is started ahead for the next chat turn
(same system prompt and schema): a turn is ~2 s instead of ~3.4 s. Tool results that are already
the answer ("Okay, I'll remind you at 8") are said with Claude's own `after` line from the same call
(when every time and number is still in it), so a reminder is one call, not two.
"""
from __future__ import annotations

import atexit
import datetime as dt
import json
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .config import ROOT
from .llm import ChatReply, OllamaError, ToolCall

log = logging.getLogger(__name__)
NO_WINDOW = 0x08000000
DIR = ROOT / "data" / "brain"

SECRET = re.compile(r"\b(secret between us|between (us|you and me|the two of us)|(just|only) between us|"
                    r"keep (this|it|that) (private|between us|to yourself|secret|local)|off the record|"
                    r"don'?t tell claude)\b", re.I)
OPEN = re.compile(r"\b(secret'?s over|(it'?s|we'?re) (fine|okay|ok|good) now,? (you can|tell)|"
                  r"you can tell claude|back to claude|not a secret any ?more)\b", re.I)
PRIVATE_DAYS = 30
PRIVATE_MAX = 300
MIN_PRIVATE_CHARS = 12
STAMP = re.compile(r"^\[[^\]]{3,40}\]\s*")
WORD = re.compile(r"[a-z0-9']+")
TAG = re.compile(r"\[[a-z_]+\]")
GRAM = 6


def grams(text: str) -> set[str]:
    """Every run of GRAM words (lowercase, emotion tags and punctuation left out)."""
    w = WORD.findall(TAG.sub(" ", str(text).lower()))
    return {" ".join(w[i:i + GRAM]) for i in range(len(w) - GRAM + 1)}

CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "tool_calls": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "arguments": {"type": "object"}},
            "required": ["name", "arguments"]}},
        "after": {"type": "string"},
    },
    "required": ["reply", "tool_calls"],
}
PROTOCOL = """

How this chat works (you answer as JSON):
- "reply": what you say right now, spoken out loud, in your own voice with your emotion tag first. Leave it empty when you only call tools.
- "tool_calls": tools to run now, each {"name", "arguments"} with the exact argument names from the tool list. Their results come back to you as RESULT lines and you answer after that. Call a tool whenever the request needs one: you can't set, add, check, open or remember anything without it, so never say you made, drew, sent, saved or did something unless a RESULT in this turn says so.
- "after": only when you call tools that DO something (set, add, open, play, save): the one short line you'll say if they succeed (your tag first, keep every time, date and number exactly). Leave it empty for tools that look something up: you answer once you've seen the RESULT.
Lines in brackets or parentheses in their messages are notes for you (time, memories, mood); never read them out."""


class Privacy:
    """What must not leave the laptop: a secret said just now, a hard moment, or anything that
    contains words from one."""

    def __init__(self, memory=None, comfort_now: Callable[[], bool] = lambda: False, secret_s: float = 1800,
                 clock=time.time):
        self.memory = memory
        self.comfort_now = comfort_now
        self.secret_s = secret_s
        self.clock = clock
        self.secret_until = 0.0
        self._texts: list[dict] | None = None
        self._grams: set[str] | None = None
        self._lock = threading.Lock()

    @property
    def secret(self) -> bool:
        return self.clock() < self.secret_until

    @property
    def active(self) -> bool:
        if self.secret:
            return True
        try:
            return bool(self.comfort_now())
        except Exception:
            return True

    def heard(self, user_text: str):
        """Their message, before anything is sent: starts or ends a secret."""
        if OPEN.search(user_text or ""):
            if self.secret_until:
                log.info("mind: secret over, Claude again")
            self.secret_until = 0.0
            return
        if SECRET.search(user_text or ""):
            log.info("mind: a secret, local for %d min", self.secret_s // 60)
            self.secret_until = self.clock() + self.secret_s
        if self.active:
            self.keep(user_text)

    def _load(self) -> list[dict]:
        if self._texts is None:
            raw = self.memory.get("private:texts") if self.memory is not None else None
            self._texts = list(json.loads(raw)) if raw else []
        return self._texts

    def keep(self, *texts: str):
        now = self.clock()
        with self._lock:
            items = [x for x in self._load() if now - x.get("t", 0) < PRIVATE_DAYS * 86400]
            for t in texts:
                for line in str(t or "").splitlines():
                    line = STAMP.sub("", line).strip()
                    if len(line) >= MIN_PRIVATE_CHARS and line not in {x["x"] for x in items}:
                        items.append({"t": now, "x": line})
            self._texts = items[-PRIVATE_MAX:]
            self._grams = None
            if self.memory is not None:
                self.memory.set("private:texts", json.dumps(self._texts, ensure_ascii=False))

    def touches(self, payload: str) -> bool:
        """Any run of GRAM words from a private line appears in `payload` (so a diary quoting half a
        secret sentence counts; lines shorter than GRAM words never match, so "what should I do"
        can't make everything local)."""
        with self._lock:
            if self._grams is None:
                self._grams = set().union(*(grams(x["x"]) for x in self._load()))
            mine = self._grams
        return bool(mine) and not mine.isdisjoint(grams(payload))

    def forget(self):
        with self._lock:
            self._texts = []
            self._grams = None
            if self.memory is not None:
                self.memory.set("private:texts", "[]")


class ClaudeRunner:
    """`claude -p` with no tools, settings, MCP servers or session, in an empty folder. One process
    can be started ahead of time for the next call with the same system prompt and schema."""

    MAX_WARM_S = 900

    def __init__(self, exe: str, model: str = "sonnet", folder: Path = DIR, timeout: float = 90):
        self.exe, self.model, self.timeout = exe, model, timeout
        self.work = Path(folder) / "work"
        self._warm: tuple[str, subprocess.Popen, float] | None = None
        self._lock = threading.Lock()
        atexit.register(self.close)

    def _spawn(self, system: str, schema: dict) -> subprocess.Popen:
        self.work.mkdir(parents=True, exist_ok=True)
        cmd = [self.exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--tools", "", "--model", self.model, "--no-session-persistence", "--strict-mcp-config",
               "--setting-sources", "", "--system-prompt", system, "--json-schema", json.dumps(schema)]
        return subprocess.Popen(cmd, cwd=str(self.work), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                creationflags=NO_WINDOW)

    @staticmethod
    def _key(system: str, schema: dict) -> str:
        return system + "\x00" + json.dumps(schema, sort_keys=True)

    def _take(self, key: str) -> subprocess.Popen | None:
        with self._lock:
            warm, self._warm = self._warm, None
        if warm is None:
            return None
        k, p, started = warm
        if k == key and p.poll() is None and time.monotonic() - started < self.MAX_WARM_S:
            return p
        p.kill()
        return None

    def prewarm(self, system: str, schema: dict):
        key = self._key(system, schema)
        with self._lock:
            if self._warm is not None and self._warm[0] == key and self._warm[1].poll() is None:
                return
        p = self._spawn(system, schema)
        with self._lock:
            old, self._warm = self._warm, (key, p, time.monotonic())
        if old is not None:
            old[1].kill()

    def run(self, system: str, prompt: str, schema: dict, keep_warm: bool = False) -> dict:
        key = self._key(system, schema)
        p = self._take(key) or self._spawn(system, schema)
        if keep_warm:
            threading.Thread(target=self.prewarm, args=(system, schema), name="claude-warm", daemon=True).start()
        msg = {"type": "user", "message": {"role": "user", "content": prompt}}
        try:
            out, _ = p.communicate(json.dumps(msg) + "\n", timeout=self.timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            raise RuntimeError(f"Claude took over {self.timeout:.0f} s")
        for line in reversed(out.splitlines()):
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if data.get("type") != "result":
                continue
            if data.get("is_error"):
                raise RuntimeError(str(data.get("result"))[:200])
            got = data.get("structured_output")
            if got is None:
                got = json.loads(data.get("result") or "null")
            if not isinstance(got, dict):
                raise RuntimeError("Claude's answer wasn't JSON")
            return got
        raise RuntimeError(f"no answer from Claude: {out[-200:]!r}")

    def close(self):
        with self._lock:
            warm, self._warm = self._warm, None
        if warm is not None:
            warm[1].kill()


def split(messages: list[dict]) -> tuple[str, list[dict]]:
    system = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")
    return system.replace("/no_think", "").strip(), [m for m in messages if m.get("role") != "system"]


def transcript(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        role, text = m.get("role"), str(m.get("content") or "").strip()
        if role == "user":
            lines.append(f"THEM: {text}")
        elif role == "assistant":
            if text:
                lines.append(f"YOU: {text}")
            for call in m.get("tool_calls") or []:
                f = call.get("function", call)
                lines.append(f"YOU CALLED {f.get('name')} {json.dumps(f.get('arguments') or {}, ensure_ascii=False)}")
        elif role == "tool":
            lines.append(f"RESULT of {m.get('tool_name') or 'the tool'}: {text}")
    return "\n\n".join(lines)


def tool_lines(tools: list[dict]) -> str:
    out = []
    for t in tools:
        f = t.get("function", t)
        if f.get("name") == "think_harder":          # the local model's way up to the bigger one
            continue
        params = f.get("parameters") or {}
        args = {k: " ".join(filter(None, [v.get("description") or v.get("type", ""),
                                          f"One of: {', '.join(map(str, v['enum']))}." if v.get("enum") else ""]))
                for k, v in (params.get("properties") or {}).items()}
        need = params.get("required") or []
        out.append(f"- {f.get('name')}: {f.get('description', '')} Arguments: {json.dumps(args, ensure_ascii=False)}"
                   + (f" (required: {', '.join(need)})" if need else ""))
    return "\n".join(out)


def chat_prompt(rest: list[dict], tools: list[dict] | None) -> str:
    parts = []
    if tools:
        parts.append("Tools you can call now:\n" + tool_lines(tools))
    parts.append("The conversation (THEM = the person you talk with, YOU = you; the last line is what you answer):\n\n"
                 + transcript(rest))
    return "\n\n".join(parts)


class ClaudeMind:
    """Same calls as llm.OllamaClient (chat / preload / unload / ...): Claude first, the local
    model for anything private and as the fallback."""

    def __init__(self, local, cfg: dict | None = None, exe: str | None = None, runner: ClaudeRunner | None = None,
                 privacy: Privacy | None = None, clock=time.time, folder: Path = DIR):
        cfg = cfg or {}
        self.local = local
        self.daily_calls = int(cfg.get("chat_daily_calls", 600))
        self.local_keep_alive = cfg.get("local_keep_alive", "5m")
        self.clock = clock
        self.folder = Path(folder)
        if runner is None and exe:
            runner = ClaudeRunner(exe, cfg.get("model", "sonnet"), folder, float(cfg.get("chat_timeout_s", 90)))
        self.runner = runner
        self.privacy = privacy or Privacy(secret_s=float(cfg.get("secret_min", 30)) * 60, clock=clock)
        self.calls: dict[str, int] = {}
        self.fails = 0
        self.paused_until = 0.0
        self.last_error = ""
        self.last_route = ""

    def __getattr__(self, name):                       # think, keep_alive, host, gpu_layers...
        return getattr(self.local, name)

    @property
    def available(self) -> bool:
        return self.runner is not None

    def _today(self) -> str:
        return dt.datetime.fromtimestamp(self.clock()).date().isoformat()

    def calls_today(self) -> int:
        return self.calls.get(self._today(), 0)

    def heard(self, user_text: str):
        self.privacy.heard(user_text)

    @property
    def private_active(self) -> bool:
        return self.privacy.active

    def without_secrets(self, messages: list[dict]) -> list[dict] | None:
        """A live chat request with the earlier secret left out, so the chat goes on with Claude once
        the secret is over: messages that touch it are dropped, and so are note lines in the new
        message (a chat summary written about it). None if their new words themselves touch it."""
        if not messages:
            return messages
        *before, last = messages
        out = [m for m in before if m.get("role") == "system"
               or not self.privacy.touches(json.dumps(m, ensure_ascii=False))]
        first, *notes = str(last.get("content") or "").split("\n")
        if self.privacy.touches(first):
            return None
        kept = [n for n in notes if not self.privacy.touches(n)]
        return out + [{**last, "content": "\n".join([first, *kept])}]

    def why_local(self, messages: list[dict]) -> str | None:
        """Why this call must stay on the laptop (None = Claude may answer)."""
        if self.runner is None:
            return "no Claude Code"
        if any(m.get("images") for m in messages):
            return "photo"
        if self.privacy.active:
            return "private moment"
        if self.privacy.touches(json.dumps(messages, ensure_ascii=False)):
            return "touches a secret"
        if self.clock() < self.paused_until:
            return "Claude failing"
        if self.calls_today() >= self.daily_calls:
            return "daily limit"
        return None

    def chat(self, model: str, messages: list[dict], tools: list[dict] | None = None,
             options: dict[str, Any] | None = None, on_text: Callable[[str], None] | None = None,
             fmt: str | dict | None = None, keep_alive: str | int | None = None) -> ChatReply:
        why = self.why_local(messages)
        if why == "touches a secret" and tools and not self.privacy.active:
            cleaned = self.without_secrets(messages)          # live chat after a secret: Claude, minus the secret
            if cleaned is not None and not self.privacy.touches(json.dumps(cleaned, ensure_ascii=False)):
                messages, why = cleaned, self.why_local(cleaned)
        if why is None:
            try:
                reply = self._claude(messages, tools, fmt)
            except Exception as exc:
                self.fails += 1
                self.last_error = str(exc)[:200]
                if self.fails >= 3:
                    self.paused_until = self.clock() + 300
                    log.warning("mind: Claude failed 3 times in a row, local for 5 min (%s)", exc)
                why = f"Claude failed: {exc}"
            else:
                self.fails = 0
                self.last_route = "claude"
                if on_text is not None and reply.content and not reply.tool_calls:
                    on_text(reply.content)
                return reply
        private = why in ("private moment", "touches a secret")
        log.info("mind: local (%s)", why)
        self.last_route = "local"
        reply = self.local.chat(model, messages, tools, options=options, on_text=on_text, fmt=fmt,
                                keep_alive=self.local_keep_alive if keep_alive is None else keep_alive)
        if private:
            self.privacy.keep(reply.content)          # what it wrote about a secret is private too
        return reply

    def _claude(self, messages: list[dict], tools: list[dict] | None, fmt) -> ChatReply:
        system, rest = split(messages)
        with_count = self.calls_today() + 1
        self.calls = {self._today(): with_count}
        started = time.monotonic()
        if isinstance(fmt, dict):
            prompt = rest[-1]["content"] if len(rest) == 1 and rest[0].get("role") == "user" else transcript(rest)
            got = self.runner.run(system or "Answer as JSON.", str(prompt), fmt)
            log.info("mind: Claude (json) in %.1f s", time.monotonic() - started)
            return ChatReply(content=json.dumps(got, ensure_ascii=False), raw={"cloud": True})
        single = len(rest) == 1 and rest[0].get("role") == "user" and not tools
        prompt = str(rest[0]["content"]) if single else chat_prompt(rest, tools)
        live = bool(tools)
        got = self.runner.run((system or "You are a helpful assistant.") + PROTOCOL, prompt, CHAT_SCHEMA, keep_warm=live)
        calls = [ToolCall(str(c.get("name") or ""), c.get("arguments") if isinstance(c.get("arguments"), dict) else {})
                 for c in got.get("tool_calls") or [] if isinstance(c, dict) and c.get("name")]
        if tools:
            offered = {t.get("function", t).get("name") for t in tools}
            calls = [c for c in calls if c.name in offered]
        log.info("mind: Claude in %.1f s (%d tool calls)", time.monotonic() - started, len(calls))
        return ChatReply(content=str(got.get("reply") or "").strip(), tool_calls=calls,
                         raw={"cloud": True, "after": str(got.get("after") or "").strip()})

    def prewarm(self, system: str):
        """Start Claude for the next chat turn ahead of time (main calls this once at start)."""
        if self.runner is not None:
            s, _ = split([{"role": "system", "content": system}])
            threading.Thread(target=self.runner.prewarm, args=(s + PROTOCOL, CHAT_SCHEMA), daemon=True).start()

    def preload(self, model: str, keep_alive: str | int | None = None):
        """The local model loads only when something needs it (a secret, a fallback)."""
        if self.runner is None:
            self.local.preload(model, keep_alive)

    def unload(self, model: str):
        self.local.unload(model)

    def status(self) -> dict:
        return {"enabled": True, "available": self.available, "calls_today": self.calls_today(),
                "daily_calls": self.daily_calls, "secret": self.privacy.secret, "private": self.privacy.active,
                "last": self.last_route, "error": self.last_error}


def make_mind(local, cfg: dict) -> ClaudeMind | None:
    """A ClaudeMind when config brain.chat is on and Claude Code is installed, else None."""
    if not cfg.get("chat") or not cfg.get("cloud", True):
        return None
    if os.environ.get("PYTEST_CURRENT_TEST"):         # tests never talk to the real Claude
        return None
    from .cloudbrain import find_claude

    exe = find_claude()
    if not exe:
        log.warning("brain.chat is on but Claude Code isn't installed; the local model answers")
        return None
    return ClaudeMind(local, cfg, exe=exe)
