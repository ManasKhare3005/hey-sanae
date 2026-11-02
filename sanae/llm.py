"""Minimal Ollama client over HTTP (chat with tool calling, load/unload)."""
from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from . import services

log = logging.getLogger(__name__)

# Reading the prompt slower than this (tokens/s, on prompts of SLOW_MIN_TOKENS+) means the model
# loaded badly: when VRAM was short at load time, Windows quietly puts part of it in shared
# memory, `ollama ps` still says "100% GPU" and prompts are read ~10x slower (158 vs 1670 tok/s
# measured on the 3050). A reload with the VRAM free again fixes it.
SLOW_TOK_S = 450
SLOW_MIN_TOKENS = 800
RELOAD_GAP_S = 600


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatReply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


class OllamaError(RuntimeError):
    pass


def nvidia_free_mb() -> int | None:
    """Free VRAM right now, None if it can't be read."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=3,
                             creationflags=0x08000000 if os.name == "nt" else 0)
        return int(out.stdout.split()[0]) if out.returncode == 0 else None
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def _calls(msg: dict) -> list[ToolCall]:
    calls = []
    for c in msg.get("tool_calls") or []:
        fn = c.get("function", {})
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        calls.append(ToolCall(fn.get("name", ""), args))
    return calls


class OllamaClient:
    def __init__(self, host: str, keep_alive: str = "15m", temperature: float = 0.3,
                 think: bool = False, timeout: float = 180, num_ctx: int | None = None,
                 num_predict: int | None = None, gpu_layers: dict[str, int] | None = None,
                 stream_deadline_s: float = 120, vram_free: Callable[[], int | None] | None = None,
                 tight_free_mb: int = 2800, tight_num_ctx: int = 2048):
        self.host = host.rstrip("/")
        self.stream_deadline_s = stream_deadline_s   # the whole streamed reply, start to finish
        self.keep_alive = keep_alive
        self.temperature = temperature
        self.think = think
        self.timeout = timeout
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        # model -> layers to force onto the GPU (Ollama's num_gpu). Dropped for a model if
        # loading fails, e.g. when a game is holding VRAM.
        self.gpu_layers = dict(gpu_layers or {})
        # VRAM too short for a forced model (a game, a crowded GPU): see _prepare. None = never check.
        self.vram_free = vram_free
        self.tight_free_mb = tight_free_mb
        self.tight_num_ctx = tight_num_ctx
        self._tight: set[str] = set()            # models to load the gentle way for now
        self._slow: dict[str, int] = {}          # model -> slow prompts in a row
        self._reloaded: dict[str, float] = {}    # model -> when it was last reloaded for being slow

    def _loaded(self) -> dict[str, int] | None:
        """Models in memory -> their VRAM in MB; None if Ollama can't say."""
        try:
            models = requests.get(f"{self.host}/api/ps", timeout=2).json().get("models", [])
            return {m.get("name", ""): int(m.get("size_vram") or 0) // 2**20 for m in models}
        except (requests.RequestException, ValueError, AttributeError):
            return None

    def _prepare(self, model: str):
        """Just before a model is used: if it has to be loaded and VRAM is short right now, load it with
        Ollama's own split and a smaller context instead of forcing it all on the GPU, which spills
        into shared memory. The choice only changes at a load: a different num_ctx mid-way would
        make Ollama reload the model."""
        if self.vram_free is None or model not in self.gpu_layers:
            return
        loaded = self._loaded()
        if loaded is None or model in loaded:
            return
        free = self.vram_free()
        tight = free is not None and free < self.tight_free_mb
        if tight and model not in self._tight:
            log.info("VRAM is tight (%d MB free): loading %s without forcing it onto the GPU", free, model)
        elif not tight and model in self._tight:
            log.info("VRAM is free again (%s MB): %s goes fully on the GPU", free, model)
        (self._tight.add if tight else self._tight.discard)(model)

    def _check_speed(self, model: str, data: dict):
        """Two badly slow prompts in a row: reload the model in the background (at most every 10 min).
        If other programs hold the VRAM a reload lands in the same place, so it's loaded gently instead,
        and from then on left alone."""
        if model in self._tight:
            return
        n, ns = data.get("prompt_eval_count") or 0, data.get("prompt_eval_duration") or 0
        if n < SLOW_MIN_TOKENS or not ns:
            return
        rate = n / (ns / 1e9)
        if rate >= SLOW_TOK_S:
            self._slow[model] = 0
            return
        self._slow[model] = self._slow.get(model, 0) + 1
        log.info("slow prompt: %d tokens at %.0f tok/s on %s", n, rate, model)
        if self._slow[model] < 2 or time.monotonic() - self._reloaded.get(model, -RELOAD_GAP_S) < RELOAD_GAP_S:
            return
        self._slow[model] = 0
        self._reloaded[model] = time.monotonic()
        if self.vram_free is not None and model in self.gpu_layers:
            free = self.vram_free()
            own = (self._loaded() or {}).get(model, 0)
            if free is not None and free + own < self.tight_free_mb:
                log.info("%s reads prompts at %.0f tok/s and only %d MB of VRAM would be free for it; loading it "
                         "without forcing it onto the GPU", model, rate, free + own)
                self._tight.add(model)
                threading.Thread(target=self.unload, args=(model,), name="llm-reload", daemon=True).start()
                return
        log.warning("%s reads prompts at %.0f tok/s (part of it is probably in shared memory); reloading it", model, rate)

        def reload():
            self.unload(model)
            self.preload(model)
        threading.Thread(target=reload, name="llm-reload", daemon=True).start()

    def chat(self, model: str, messages: list[dict], tools: list[dict] | None = None,
             options: dict[str, Any] | None = None, on_text: Callable[[str], None] | None = None,
             fmt: str | dict | None = None, keep_alive: str | int | None = None) -> ChatReply:
        """`options` overrides per call, e.g. {"num_predict": 1000} for long notes.
        `on_text` streams the reply: called with each piece of text as the model writes it
        (voice mode starts speaking the first sentence before the rest exists). `fmt`: structured output.
        `keep_alive`: override how long the model stays loaded (0 = unload right after)."""
        self._prepare(model)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": on_text is not None,
            "keep_alive": self.keep_alive if keep_alive is None else keep_alive,
            "think": self.think,
            "options": {**self._options(model), **(options or {})},
        }
        if tools:
            payload["tools"] = tools
        if fmt:
            payload["format"] = fmt              # "json" or a JSON schema: Ollama constrains the output to it
        extra = {"stream": True} if payload["stream"] else {}
        started = time.monotonic()
        wait = min(self.timeout, self.stream_deadline_s) if on_text is not None else self.timeout
        post = lambda: requests.post(f"{self.host}/api/chat", json=payload, timeout=wait, **extra)
        try:
            r = post()
        except requests.ConnectionError as exc:
            services.note("ollama", False, "can't connect")
            raise OllamaError("Can't reach Ollama. Is it running? Start the Ollama app.") from exc
        except requests.Timeout as exc:          # a cold model load from disk can take this long
            raise OllamaError(f"The model took over {wait:.0f} s to answer.") from exc
        services.note("ollama", True)
        if r.status_code == 404:
            raise OllamaError(f"Model '{model}' isn't downloaded. Run: ollama pull {model}")
        if r.status_code >= 400 and "think" in r.text and payload.pop("think", None) is not None:
            # Older Ollama or a model without thinking support: retry without the flag
            r = post()
        if r.status_code >= 500 and self.gpu_layers.pop(model, None) is not None:
            log.warning("Loading %s with all layers on the GPU failed (%s); retrying with Ollama's default split",
                        model, r.text[:200])
            payload["options"] = self._options(model)
            r = post()
        if r.status_code >= 400:
            raise OllamaError(f"Ollama error {r.status_code}: {r.text[:300]}")
        if on_text is None:
            data = r.json()
            msg = data.get("message", {})
            self._check_speed(model, data)
            return ChatReply(content=(msg.get("content") or "").strip(), tool_calls=_calls(msg), raw=data)
        # Streamed: one JSON object per line; text arrives in pieces, tool calls whole
        parts: list[str] = []
        calls: list[ToolCall] = []
        data: dict = {}
        for line in self._lines_until(r, started + self.stream_deadline_s):
            if not line:
                continue
            chunk = json.loads(line)
            msg = chunk.get("message") or {}
            piece = msg.get("content") or ""
            if piece:
                parts.append(piece)
                on_text(piece)
            calls += _calls(msg)
            if chunk.get("done"):
                data = chunk
                break
        self._check_speed(model, data)
        return ChatReply(content="".join(parts).strip(), tool_calls=calls, raw=data)

    def _lines_until(self, r, deadline: float):
        """The response's lines, until the wall clock says stop. requests' timeout only limits each
        read, so a slow trickle (or a stuck socket) could hold her in "thinking" for ever; the reads
        happen on their own thread so that even a blocked one can't hold up the deadline."""
        lines: queue.Queue = queue.Queue()

        def pump():
            try:
                for line in r.iter_lines():
                    lines.put(("line", line))
                lines.put(("end", None))
            except Exception as exc:
                lines.put(("error", exc))

        threading.Thread(target=pump, name="llm-stream", daemon=True).start()
        while True:
            try:
                kind, value = lines.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                log.warning("streamed reply passed its %.0f s limit; giving up on it", self.stream_deadline_s)
                threading.Thread(target=r.close, name="llm-close", daemon=True).start()   # closing can block too
                raise OllamaError("Sorry, I got stuck thinking about that one. Could you ask me again?") from None
            if kind == "end":
                return
            if kind == "error":
                if isinstance(value, requests.RequestException):
                    raise OllamaError("Sorry, I lost my train of thought there. Could you ask me again?") from value
                raise value
            yield value

    def _options(self, model: str | None = None) -> dict[str, Any]:
        opts: dict[str, Any] = {"temperature": self.temperature}
        tight = model in self._tight
        if model in self.gpu_layers and not tight:
            opts["num_gpu"] = self.gpu_layers[model]
            # Read the file once instead of mapping it: a model that lives on the GPU kept a 2 GB
            # mapped copy in RAM (llama-server 3.7 GB -> 1.7 GB resident, same VRAM, loads no slower)
            opts["use_mmap"] = False
        if self.num_ctx:
            # fixed size so the model's VRAM use is predictable
            opts["num_ctx"] = min(self.num_ctx, self.tight_num_ctx) if tight else self.num_ctx
        if self.num_predict:
            opts["num_predict"] = self.num_predict  # hard cap on reply length
        return opts

    def unload(self, model: str):
        """Free the model's VRAM immediately."""
        try:
            requests.post(f"{self.host}/api/generate", json={"model": model, "keep_alive": 0}, timeout=30)
        except requests.RequestException as exc:
            log.warning("unload failed: %s", exc)

    def preload(self, model: str, keep_alive: str | int | None = None):
        """Load a model into memory ahead of time so the first answer is fast."""
        self._prepare(model)
        try:
            requests.post(f"{self.host}/api/generate",
                          json={"model": model, "keep_alive": self.keep_alive if keep_alive is None else keep_alive,
                                "options": self._options(model)},
                          timeout=self.timeout)
        except requests.RequestException as exc:
            log.warning("preload failed: %s", exc)

    def available_models(self) -> list[str]:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=5)
            return [m["name"] for m in r.json().get("models", [])]
        except requests.RequestException:
            return []
