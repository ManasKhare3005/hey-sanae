"""Doing things together: a study session with breaks, games by voice, and what song is playing."""
from __future__ import annotations

from .registry import ToolRegistry


def register(reg: ToolRegistry):
    ctx = reg.context

    history = getattr(ctx, "league_history", None) if ctx else None
    if history is not None:
        @reg.tool(
            "How the user's recent League of Legends games went (result, KDA, CS), from the games you "
            "watched: 'how did my last game go?', 'how have I been doing in league?'.",
            params={"games": {"type": "integer", "description": "How many recent games; 1 if they said 'last game'"}},
            required=[],
            direct=True,
        )
        def league_games(games: int = 1):
            return history.spoken(max(1, min(int(games or 1), 20)))

    matches = getattr(ctx, "valorant_history", None) if ctx else None
    if matches is not None:
        @reg.tool(
            "How the user's recent Valorant matches went (score, map, result, rank), from the matches you kept "
            "score of: 'how did my last game go?', 'how have I been doing in valorant?', 'what's my rank?'.",
            params={"games": {"type": "integer", "description": "How many recent matches; 1 if they said 'last game'"}},
            required=[],
            direct=True,
        )
        def valorant_games(games: int = 1):
            return matches.spoken(max(1, min(int(games or 1), 20)))

    def buddy():
        return getattr(ctx, "study", None)

    @reg.tool(
        "Start a study session together (pomodoro: focus rounds with short breaks; she stays quiet while they "
        "focus and checks in at breaks), when the user says 'study with me', 'let's study for an hour', "
        "'pomodoro', 'help me focus'.",
        params={"minutes": {"type": "number", "description": "Total length; 60 if they didn't say"},
                "topic": {"type": "string", "description": "What they're studying, if they said (e.g. 'networks')"}},
        required=[],
        direct=True,
    )
    def start_study(minutes: float = 60, topic: str = ""):
        b = buddy()
        return b.start(minutes, topic) if b is not None else "I can only study with you on the laptop with voice on."

    @reg.tool("Stop the study session early, when the user says 'stop studying', 'end the session', 'I'm done studying'.",
              params={}, direct=True)
    def stop_study():
        b = buddy()
        return b.stop() if b is not None else "We're not studying right now."

    @reg.tool("How much of the study session is left, when the user asks 'how long left', 'when's the break'.",
              params={}, direct=True)
    def study_status():
        b = buddy()
        return b.status() if b is not None else "We're not studying right now."

    @reg.tool(
        "Start a game by voice: twenty_questions (you think of something, they ask yes/no questions), trivia "
        "(you ask questions; a course name or topic makes it about that, e.g. 'quiz me on networks'), or "
        "would_you_rather.",
        params={"kind": {"type": "string", "enum": ["twenty_questions", "trivia", "would_you_rather"]},
                "topic": {"type": "string", "description": "Trivia topic or course, if any"}},
        required=["kind"],
        direct=True,
    )
    def play_game(kind: str, topic: str = ""):
        g = getattr(ctx, "games", None)
        return g.start(kind, topic) if g is not None else "Games aren't available right now."

    @reg.tool("End the game, when the user says 'stop the game', 'let's stop playing', 'end game'.", params={}, direct=True)
    def end_game():
        g = getattr(ctx, "games", None)
        return g.stop() if g is not None else "We're not playing anything right now."

    @reg.tool("Say what song is playing right now (title and artist), when the user asks 'what song is this', "
              "'who sings this', 'what am I listening to'.", params={})
    def what_song():
        from ..music import now_playing

        t = now_playing()
        if t is None:
            return "Nothing seems to be playing (or the app doesn't share what it's playing)."
        return f"Playing now: {t.clean().spoken()}" + ("" if t.playing else " (paused)")
