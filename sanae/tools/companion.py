"""Talking first: "not now" / "be quiet for an hour" (she stops starting conversations for a while)
and "you can talk again". Answering when spoken to is never affected. Also "hide" / "come back"
for the avatar on the screen, and a guided one-minute breathing exercise."""
from __future__ import annotations

import datetime as dt
import time

from .registry import ToolRegistry


def register(reg: ToolRegistry):
    ctx = reg.context

    @reg.tool(
        "Stop talking first (no unprompted remarks, check-ins or nudges) for a while, when the user "
        "says 'not now', 'be quiet', 'stop interrupting', 'quiet for an hour', 'leave me alone for a bit'. "
        "You still answer when spoken to.",
        params={"minutes": {"type": "number", "description": "How long; 60 if they didn't say"}},
        direct=True,
    )
    def quiet_for(minutes: float = 60):
        dnd = getattr(ctx, "dnd", None)
        if dnd is None:
            return "Okay."
        minutes = max(1.0, min(float(minutes or 60), 24 * 60))
        dnd.quiet_for(minutes)
        until = dt.datetime.now() + dt.timedelta(minutes=minutes)
        when = f"{until.hour % 12 or 12}:{until:%M} {'AM' if until.hour < 12 else 'PM'}"
        return f"Okay, I'll stay quiet until {when}. Just call me if you need me."

    @reg.tool(
        "Allow talking first again after quiet_for, when the user says 'you can talk again', "
        "'I'm free now', 'stop being quiet'.",
        params={},
        direct=True,
    )
    def chat_again():
        dnd = getattr(ctx, "dnd", None)
        if dnd is not None:
            dnd.resume()
        return "Yay, I'm back!"

    def avatar(action: str) -> bool:
        control = getattr(ctx, "avatar_control", None)
        if control is None:
            return False
        control(action)
        return True

    @reg.tool(
        "Hide the avatar (the character in the corner of the screen) when the user says 'hide', "
        "'go away for a bit', 'get off my screen'. She still listens and answers.",
        params={},
        direct=True,
    )
    def hide_avatar():
        return "Okay, I'll hide. Say come back when you miss me." if avatar("hide") else "I'm not on your screen right now."

    @reg.tool(
        "Show the avatar again after hide_avatar, when the user says 'come back', 'show yourself', 'where are you'.",
        params={},
        direct=True,
    )
    def show_avatar():
        return "I'm back!" if avatar("show") else "I can't show up on this screen right now."

    # In, hold, out (seconds): a slow exhale calms; four rounds is about a minute with the words
    BREATH = [("Breathe in slowly through your nose", 4), ("and hold it", 4), ("now breathe out, slow and long", 6)]

    @reg.tool(
        "Guide a calming one-minute breathing exercise, spoken step by step, when the user agrees to one or asks "
        "to breathe, calm down or relax.",
        params={},
        direct=True,
    )
    def breathing_exercise():
        from ..events import current_origin

        speak = getattr(ctx, "speak", None)
        if speak is None or current_origin() in ("phone", "dashboard"):
            return ("Okay: breathe in through your nose for 4, hold for 4, then out slowly for 6. "
                    "Do that four times. I'll be right here.")
        voice = getattr(ctx, "set_voice", None)
        if voice is not None:
            voice("sleepy")                                    # slow and soft
        try:
            if speak("Okay, let's do this together. Get comfy."):
                return "Okay, we'll stop there."
            time.sleep(1.5)
            for n in range(4):
                for words, hold in BREATH:
                    if speak(words + ("..." if n else ", two, three, four...")):
                        return "Okay, we'll stop there."
                    time.sleep(hold - 1.5 if n else hold - 2.5)
        finally:
            if voice is not None:
                voice("neutral")
        return "There you go. How do you feel now?"
