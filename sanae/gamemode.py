"""Game mode on its own: when a game starts (Valorant by default), she gets out of the way.

  - game starts -> the language models are unloaded (the GPU is the game's), she stays quiet
    (no small talk, no learning, the avatar closes), one short "have fun" line first
  - game ends   -> the chat model is loaded back in the background and the avatar comes back,
    so she's quick again when you talk to her

Detected by the game's process (config game_mode.games), checked every few seconds; a game has to
be seen twice in a row to start game mode and gone twice in a row to end it, so a crash-restart or
a short loading hiccup doesn't flip it back and forth. "Hey Sanae" still works mid-game (the wake
word and Whisper run on the CPU); asking her something then loads the model as usual.
"""
from __future__ import annotations

import logging
import random
import threading
from typing import Callable, Iterable

log = logging.getLogger(__name__)

# The game itself, not its launcher: the Riot Client being open isn't a game
DEFAULT_GAMES = ["VALORANT-Win64-Shipping.exe"]
NAMES = {"valorant-win64-shipping": "Valorant", "league of legends": "League"}
START_LINES = [
    "{game}? Have fun! I'll be quiet till you're done.",
    "Ooh, {game}. Go win one. I'll stay out of the way.",
    "Good luck in {game}! I'll free up the GPU for you.",
]


def stem(exe: str) -> str:
    return exe.lower().removesuffix(".exe")


def game_name(exe: str) -> str:
    return NAMES.get(stem(exe), exe.removesuffix(".exe"))


def running_game(games: Iterable[str]) -> str | None:
    """The first configured game whose process is running, else None."""
    import psutil

    want = {stem(g): g for g in games}
    for proc in psutil.process_iter(["name"]):
        name = stem(proc.info.get("name") or "")
        if name in want:
            return want[name]
    return None


class GameMode:
    def __init__(self, find: Callable[[], str | None], on_start: Callable[[str], None],
                 on_end: Callable[[str], None], confirm: int = 2):
        self.find, self.on_start, self.on_end, self.confirm = find, on_start, on_end, confirm
        self.game: str | None = None          # the game we're in game mode for
        self._seen, self._gone = 0, 0
        self._stop = threading.Event()

    @property
    def active(self) -> bool:
        return self.game is not None

    def tick(self):
        found = self.find()
        if self.game is None:
            self._seen = self._seen + 1 if found else 0
            if found and self._seen >= self.confirm:
                self.game, self._seen = found, 0
                log.info("game mode on: %s", found)
                self._call(self.on_start, found)
        else:
            self._gone = 0 if found else self._gone + 1
            if self._gone >= self.confirm:
                game, self.game, self._gone = self.game, None, 0
                log.info("game mode off: %s closed", game)
                self._call(self.on_end, game)

    @staticmethod
    def _call(fn, game):
        try:
            fn(game)
        except Exception:
            log.exception("game mode callback failed")

    def start(self, every_s: float = 5) -> "GameMode":
        def run():
            while not self._stop.wait(every_s):
                try:
                    self.tick()
                except Exception:
                    log.exception("game mode tick failed")
        threading.Thread(target=run, name="gamemode", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()


def start_line(game: str, rng=random) -> str:
    return rng.choice(START_LINES).format(game=game_name(game))
