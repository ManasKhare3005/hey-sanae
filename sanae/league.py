"""League of Legends companion: reacts to your game and sums it up afterwards.

Reads Riot's Live Client Data API (https://127.0.0.1:2999, only up while you're in a game;
read-only, the same data the in-game scoreboard shows, allowed by Riot). Lines are picked
from templates in code, never the language model, so the GPU stays free for the game.

Rules: at most one line a minute (big moments like a pentakill or Baron may come sooner), never
while a fight is going on (a kill in the last few seconds or your health dropping fast), and
lines that waited too long are dropped. When the game ends she gives a short recap (result,
KDA, CS, the champion) and remembers it for "how did my last game go?".
"""
from __future__ import annotations

import json
import logging
import random
import ssl
import threading
import time
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger(__name__)
API = "https://127.0.0.1:2999/liveclientdata"

LINES = {
    "first_blood_me": ["First blood! Nice.", "First blood, look at you!", "Ooh, first blood. Good start."],
    "kill": ["Nice kill!", "Got 'em!", "Clean.", "That was a good one.", "Nice!"],
    "death": ["Oof. You'll get them back.", "Ouch. Shake it off.", "Unlucky. Next fight's yours.",
              "That one hurt. Breathe."],
    "deaths_many": ["Rough game. Play it safe for a bit?", "Hey, it's just one game. Farm up and stay calm."],
    "double": ["Double kill!", "Double! Nice."],
    "triple": ["Triple kill!", "Triple! Okay, you're cooking."],
    "quadra": ["Quadra kill!", "QUADRA! Go go go!"],
    "penta": ["PENTAKILL! Oh my god!", "Pentakill!! That's insane!"],
    "ace_us": ["Ace! Go take something.", "Ace! The map's yours."],
    "ace_them": ["They aced you. Regroup.", "Ouch, ace. Reset and group up."],
    "baron_us": ["Baron's yours! Push.", "You got Baron! Go end it."],
    "baron_them": ["They got Baron. Play safe.", "Enemy Baron. Defend and wait it out."],
    "dragon_us": ["Dragon secured.", "Nice, dragon's yours."],
    "dragon_them": ["They took dragon.", "Enemy dragon. Next one's yours."],
    "herald_us": ["Herald's yours.", "Got the Herald."],
    "inhib_us": ["Inhib down! Nice push.", "You took an inhibitor!"],
    "inhib_them": ["They took an inhib. Careful.", "Inhib down on your side. Defend."],
}
# priority: higher = said first; >= BIG may skip the one-a-minute rule (still not mid-fight)
PRIORITY = {"penta": 10, "quadra": 9, "baron_us": 8, "baron_them": 8, "ace_us": 7, "ace_them": 7, "triple": 7,
            "inhib_them": 6, "inhib_us": 5, "first_blood_me": 5, "double": 4, "dragon_us": 3, "dragon_them": 3,
            "herald_us": 2, "deaths_many": 4, "kill": 2, "death": 2}
BIG = 7


def names_of(player: dict) -> set[str]:
    """All the ways the API may spell a player: summoner name, Riot ID, Riot ID without the tag."""
    out = set()
    for key in ("summonerName", "riotId", "riotIdGameName"):
        v = str(player.get(key) or "").strip()
        if v:
            out |= {v.lower(), v.split("#")[0].lower()}
    return out


@dataclass
class GameState:
    me: set[str] = field(default_factory=set)
    my_team: set[str] = field(default_factory=set)          # every name of every ally (me too)
    champion: str = ""
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    cs: int = 0
    game_time: float = 0.0
    result: str = ""                                          # "Win" / "Lose" once GameEnd arrives

    @classmethod
    def read(cls, data: dict) -> "GameState":
        active = data.get("activePlayer") or {}
        me = names_of(active)
        players = data.get("allPlayers") or []
        mine = next((p for p in players if names_of(p) & me), None)
        team = (mine or {}).get("team")
        allies = set()
        for p in players:
            if team and p.get("team") == team:
                allies |= names_of(p)
        s = (mine or {}).get("scores") or {}
        return cls(me, allies | me, (mine or {}).get("championName", ""), int(s.get("kills", 0)), int(s.get("deaths", 0)),
                   int(s.get("assists", 0)), int(s.get("creepScore", 0)),
                   float((data.get("gameData") or {}).get("gameTime", 0.0)))


def react(event: dict, game: GameState) -> str | None:
    """An event from /eventdata -> which kind of line it deserves (a LINES key), or None."""
    name = event.get("EventName", "")
    lower = lambda k: str(event.get(k) or "").split("#")[0].lower()
    is_me = lambda k: lower(k) in game.me
    ally = lambda k: lower(k) in game.my_team
    if name == "FirstBlood" and is_me("Recipient"):
        return "first_blood_me"
    if name == "Multikill" and is_me("KillerName"):
        return {2: "double", 3: "triple", 4: "quadra", 5: "penta"}.get(int(event.get("KillStreak", 0)))
    if name == "ChampionKill":
        if is_me("KillerName"):
            return "kill"
        if is_me("VictimName"):
            return "deaths_many" if game.deaths in (6, 10) else "death"
        return None
    if name == "Ace":
        return "ace_us" if ally("Acer") else "ace_them"
    if name in ("BaronKill", "DragonKill", "HeraldKill"):
        obj = {"BaronKill": "baron", "DragonKill": "dragon", "HeraldKill": "herald"}[name]
        us = ally("KillerName")
        if obj == "herald" and not us:
            return None
        return f"{obj}_{'us' if us else 'them'}"
    if name == "InhibKilled":
        return "inhib_us" if ally("KillerName") else "inhib_them"
    return None


def recap(game: GameState) -> str:
    result = {"Win": "GG, you won!", "Lose": "GG. That one didn't go your way."}.get(game.result, "Game over.")
    minutes = int(game.game_time // 60)
    champ = f" on {game.champion}" if game.champion else ""
    cs = f", {game.cs} CS" if game.cs else ""
    per_min = f" ({game.cs / minutes:.1f} a minute)" if game.cs and minutes >= 10 else ""
    line = f"{result} You went {game.kills}/{game.deaths}/{game.assists}{champ}{cs}{per_min} in {minutes} minutes."
    if game.result == "Lose" and game.deaths >= 8:
        line += " Maybe take a short break before the next one?"
    elif game.kills + game.assists >= 20 and game.deaths <= 3:
        line += " That was a really clean game."
    return line


class LiveClient:
    """GET the Live Client Data API (self-signed certificate on localhost)."""

    def __init__(self, base: str = API, timeout: float = 1.5):
        self.base = base
        self.timeout = timeout
        self._ssl = ssl.create_default_context()
        self._ssl.check_hostname = False
        self._ssl.verify_mode = ssl.CERT_NONE        # Riot's local certificate; never leaves this laptop

    def all(self) -> dict | None:
        try:
            with urllib.request.urlopen(f"{self.base}/allgamedata", timeout=self.timeout, context=self._ssl) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            return None                              # not in a game (the API only exists during one)


class LeagueCompanion:
    def __init__(self, say, on_recap=lambda text, game: None, client=None, clock=time.monotonic,
                 quiet=lambda: False, min_gap_s: float = 60, big_gap_s: float = 20, fight_s: float = 8,
                 max_wait_s: float = 25, poll_s: float = 2.0, idle_poll_s: float = 6.0, chatter: bool = True, rng=None):
        self.say, self.on_recap, self.client = say, on_recap, client or LiveClient()
        self.clock, self.quiet = clock, quiet
        self.min_gap_s, self.big_gap_s, self.fight_s, self.max_wait_s = min_gap_s, big_gap_s, fight_s, max_wait_s
        self.poll_s, self.idle_poll_s, self.chatter = poll_s, idle_poll_s, chatter
        self.rng = rng or random.Random()
        self.game: GameState | None = None
        self.last_event_id = -1
        self.last_said = -1e9
        self.last_fight = -1e9
        self.health: list[tuple[float, float]] = []   # (time, health fraction) for the last few seconds
        self.pending: list[tuple[int, float, str]] = []   # (priority, queued at, kind)
        self.used: dict[str, int] = {}
        self.ended = False                            # GameEnd seen: wait for the API to go away
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ----- one poll -----
    def tick(self) -> bool:
        """Read the game once; returns True while a game is on."""
        data = self.client.all()
        now = self.clock()
        if data is None or not data.get("activePlayer"):
            self.ended = False
            if self.game is not None:
                self._finish()                       # the client closed without a GameEnd we saw
            return False
        if self.ended:                               # the end screen: the API stays up for a while
            return False
        game = GameState.read(data)
        events = (data.get("events") or {}).get("Events") or []
        if self.game is None:
            log.info("league: game found (%s)", game.champion or "?")
            # joined mid-game (Sanae started late): don't cheer for kills from ten minutes ago
            self.last_event_id = max((int(e.get("EventID", -1)) for e in events
                                      if e.get("EventName") not in ("GameStart", "MinionsSpawning")), default=-1)
            self.pending.clear()
            self.used.clear()
        game.result = self.game.result if self.game is not None else ""
        self.game = game
        self._track_health(data, now)
        for ev in events:
            eid = int(ev.get("EventID", -1))
            if eid <= self.last_event_id:
                continue
            self.last_event_id = eid
            name = ev.get("EventName")
            if name in ("ChampionKill", "Multikill", "Ace", "FirstBlood"):
                self.last_fight = now
            if name == "GameEnd":
                game.result = str(ev.get("Result") or "")
                self.ended = True
                self._finish()
                return False
            kind = react(ev, game)
            if kind and self.chatter:
                self.pending.append((PRIORITY.get(kind, 1), now, kind))
        self._maybe_speak(now)
        return True

    def _track_health(self, data: dict, now: float):
        stats = (data.get("activePlayer") or {}).get("championStats") or {}
        cur, top = stats.get("currentHealth"), stats.get("maxHealth")
        if cur is None or not top:
            return
        self.health = [(t, h) for t, h in self.health if now - t <= 4] + [(now, float(cur) / float(top))]
        if self.health and max(h for _, h in self.health) - self.health[-1][1] >= 0.15 and self.health[-1][1] > 0:
            self.last_fight = now                    # losing health fast: something's hitting you

    def in_fight(self, now: float) -> bool:
        return now - self.last_fight < self.fight_s

    def _maybe_speak(self, now: float):
        self.pending = [p for p in self.pending if now - p[1] <= self.max_wait_s]
        if not self.pending or self.in_fight(now) or self.quiet():
            return
        priority, _, kind = max(self.pending, key=lambda p: (p[0], p[1]))
        gap = self.big_gap_s if priority >= BIG else self.min_gap_s
        if now - self.last_said < gap:
            return
        self.pending.clear()                         # one line covers the moment; older small ones are stale
        options = LINES[kind]
        n = self.used.get(kind, 0)
        self.used[kind] = n + 1
        line = options[n % len(options)] if n < len(options) else self.rng.choice(options)
        self.last_said = now
        log.info("league: %s -> %s", kind, line)
        self.say(line)

    def _finish(self):
        game, self.game = self.game, None
        self.pending.clear()
        if game is None or game.game_time < 60:
            return
        text = recap(game)
        log.info("league: recap: %s", text)
        try:
            self.on_recap(text, game)
        except Exception:
            log.exception("league recap failed")

    # ----- background -----
    def start(self) -> "LeagueCompanion":
        self._thread = threading.Thread(target=self._run, name="league", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                playing = self.tick()
            except Exception:
                log.exception("league poll failed")
                playing = self.game is not None
            self._stop.wait(self.poll_s if playing else self.idle_poll_s)


class LeagueHistory:
    """The last games' recaps, kept in the kv table ("league:games") for "how did my last game go?"."""

    KEY = "league:games"

    def __init__(self, store, keep: int = 30):
        self.store, self.keep = store, keep

    def all(self) -> list[dict]:
        with self.store.lock:
            row = self.store.db.execute("SELECT value FROM kv WHERE key = ?", (self.KEY,)).fetchone()
        try:
            return json.loads(row["value"]) if row else []
        except ValueError:
            return []

    def add(self, game: GameState, text: str, when: str):
        games = (self.all() + [{"when": when, "champion": game.champion, "result": game.result, "kills": game.kills,
                                "deaths": game.deaths, "assists": game.assists, "cs": game.cs,
                                "minutes": int(game.game_time // 60), "recap": text}])[-self.keep:]
        with self.store.lock:
            self.store.db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                                  (self.KEY, json.dumps(games)))
            self.store.db.commit()

    def spoken(self, n: int = 1) -> str:
        games = self.all()
        if not games:
            return "I haven't watched you play a League game yet."
        last = games[-1]
        if n <= 1:
            return f"Your last game ({last['when']}): {last['recap']}"
        recent = games[-n:]
        wins = sum(1 for g in recent if g.get("result") == "Win")
        known = sum(1 for g in recent if g.get("result") in ("Win", "Lose"))
        k, d, a = (sum(g.get(x, 0) for g in recent) for x in ("kills", "deaths", "assists"))
        return (f"Your last {len(recent)} games: {wins} win{'s' if wins != 1 else ''} out of {known}, "
                f"{k}/{d}/{a} in total. Last one: {last['recap']}")
