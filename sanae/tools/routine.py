"""Routines by voice: "goodnight", "study time", "gaming time" (see routines.py and config.yaml)."""
from __future__ import annotations

from .registry import ToolRegistry


def register(reg: ToolRegistry):
    ctx = reg.context
    routines = getattr(ctx, "routines", None) if ctx else None
    if routines is None or not routines.items:
        return
    names = routines.names()

    @reg.tool(
        "Run one of the user's routines (several steps from one phrase): " + ", ".join(names) + ".",
        params={"name": {"type": "string", "enum": names}},
        direct=True,
    )
    def run_routine(name: str):
        routine = routines.find(name)
        if routine is None:
            return f"Error: there's no routine called {name}. Routines: {', '.join(names)}."
        bus = getattr(ctx, "bus", None)
        publish = bus.publish if bus is not None else (lambda kind, data: None)
        return routines.run(routine, reg, getattr(ctx, "confirm", None), publish)
