"""Routines: one phrase, several steps ("goodnight" stops the music, reads tomorrow's calendar,
goes quiet for the night and locks the laptop).

Defined in config.yaml (routines.list): a name, the phrases that start it, and steps. A step
says a line ({say: ...}) or calls a tool ({tool: ..., args: {...}}). Risky tools still ask
first, exactly like when asked directly; a "no" skips that step and the rest still run.
Step options: `quiet: true` leaves the tool's answer out of what she says, `if_running: <exe>`
runs the step only while that program is open (no "close Discord?" when it isn't).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Words around a trigger that don't change it: "okay, gaming time!", "it's study time now"
_BEFORE = r"(?:(?:ok(?:ay)?|alright|right|so|well|hey|yo|sanae|sanai)[\s,!.]+)*(?:(?:it'?s|it is|time for)\s+)?"
_AFTER = r"(?:[\s,!.]+(?:now|then|sanae|sanai|everyone|guys))*"


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", text.lower())).strip()


@dataclass
class Step:
    say: str = ""
    tool: str = ""
    args: dict = field(default_factory=dict)
    quiet: bool = False
    if_running: str = ""


@dataclass
class Routine:
    name: str
    triggers: list[str]
    steps: list[Step]

    def __post_init__(self):
        alts = "|".join(re.escape(norm(t)) for t in sorted(self.triggers, key=len, reverse=True) if norm(t))
        self._pattern = re.compile(rf"^{_BEFORE}(?:{alts}){_AFTER}$") if alts else None

    def matches(self, text: str) -> bool:
        return bool(self._pattern and self._pattern.match(norm(text)))


def parse(items) -> list[Routine]:
    """config routines.list -> Routine objects (bad entries are logged and skipped)."""
    out = []
    for item in items or []:
        try:
            steps = []
            for s in item.get("steps") or []:
                if isinstance(s, str):
                    steps.append(Step(say=s))
                else:
                    steps.append(Step(say=str(s.get("say") or ""), tool=str(s.get("tool") or ""),
                                      args=dict(s.get("args") or {}), quiet=bool(s.get("quiet")),
                                      if_running=str(s.get("if_running") or "")))
            triggers = item.get("say") or item.get("triggers") or [item["name"]]
            out.append(Routine(str(item["name"]), [str(t) for t in triggers], steps))
        except Exception as exc:
            log.warning("routine %r skipped: %s", item, exc)
    return out


def is_running(exe: str) -> bool:
    try:
        import psutil
    except ImportError:
        return True
    want = exe.lower().removesuffix(".exe")
    for proc in psutil.process_iter(["name"]):
        if (proc.info.get("name") or "").lower().removesuffix(".exe") == want:
            return True
    return False


class Routines:
    def __init__(self, routines: list[Routine], running=is_running):
        self.items = routines
        self.running = running

    def names(self) -> list[str]:
        return [r.name for r in self.items]

    def match(self, text: str) -> Routine | None:
        for r in self.items:
            if r.matches(text):
                return r
        return None

    def find(self, name: str) -> Routine | None:
        n = norm(name)
        for r in self.items:
            if norm(r.name) == n or r.matches(name):
                return r
        return None

    def run(self, routine: Routine, registry, confirm, on_event=lambda kind, data: None) -> str:
        """Run every step; returns what she says (her lines plus the tools' answers)."""
        from .tools.registry import DECLINED

        said: list[str] = []
        on_event("routine", {"name": routine.name, "action": "started"})
        for step in routine.steps:
            if step.say:
                said.append(step.say)
            if not step.tool:
                continue
            if step.if_running and not self.running(step.if_running):
                continue
            tool = registry.get(step.tool)
            if tool is None:
                log.warning("routine %s: no tool %s", routine.name, step.tool)
                continue
            if tool.risky:
                prompt = tool.confirmation_prompt(step.args)
                if confirm is None or not confirm(prompt):
                    said.append(f"Skipped: {prompt.split('?')[0].lower()}.")
                    continue
            on_event("tool_call", {"tool": step.tool, "args": step.args, "routine": routine.name})
            try:
                result = str(registry.run(step.tool, dict(step.args)))
            except Exception as exc:
                log.warning("routine %s: %s failed: %s", routine.name, step.tool, exc)
                result = f"Error: {exc}"
            on_event("tool_result", {"tool": step.tool, "result": result[:200], "routine": routine.name})
            if result == DECLINED:
                continue
            if result.startswith("Error"):
                log.info("routine %s: %s -> %s", routine.name, step.tool, result[:200])
                continue
            if not step.quiet:
                said.append(result)
        on_event("routine", {"name": routine.name, "action": "done"})
        return " ".join(s.strip() for s in said if s.strip()) or "Done."
