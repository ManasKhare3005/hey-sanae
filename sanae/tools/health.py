"""Health by voice: last night's sleep, steps, heart rate (see health.py; off until turned on in the
phone app)."""
from __future__ import annotations

import datetime as dt
import re

from .registry import ToolRegistry


def register(reg: ToolRegistry):
    ctx = reg.context
    health = getattr(ctx, "health", None) if ctx else None
    if health is None:
        return

    @reg.tool(
        "The user's health numbers from their watch: last night's sleep, steps today, resting and latest "
        "heart rate. For 'how did I sleep?', 'how many steps today?'.",
        params={"what": {"type": "string", "enum": ["sleep", "steps", "heart", "all"]}},
        required=[],
        direct=True,
    )
    def health_today(what: str = "all"):
        return health.answer(what if what in ("sleep", "steps", "heart", "all") else "all")

    phone = getattr(ctx, "phone", None)
    if phone is None:
        return

    @reg.tool(
        "Measure the user's heart rate right now on their Galaxy Watch (takes ~15 s), for 'what's my heart "
        "rate?', 'check my pulse'.",
        params={},
        direct=True,
    )
    def heart_rate_now():
        r = phone.request("heart_rate", {}, timeout=45)
        bpm = int(r.get("bpm") or 0) if str(r.get("bpm") or "").isdigit() else 0
        if not bpm:
            m = re.search(r"\b(\d{2,3}) ?bpm\b", str(r.get("message") or ""))
            bpm = int(m.group(1)) if m else 0
        if r.get("ok") and bpm:
            now = dt.datetime.now()
            health.save({"day": now.date().isoformat(), "hr": bpm, "hr_at": now.isoformat(timespec="seconds")})
            return f"Your heart rate is {bpm} bpm right now."
        fallback = health.answer("heart")
        why = r.get("message") or "The watch didn't answer."
        return f"{why} {fallback}" if "No heart rate" not in fallback else why
