"""Valorant: a short recap after each match ("Nice, 13 to 9 on Ascent!"), and "how did my last game go?".

Valorant has no live-game API like League's, but the Riot Client on this laptop keeps your own
presence (what friends see): whether you're in a match, the map, the queue, both teams' scores and
your rank. It's read from the Riot Client's local API (127.0.0.1, password from its lockfile), the
same place the client's friend list gets it. Nothing leaves the laptop and nothing is sent to Riot.

Nothing is said during a match (sound matters in Valorant): one line after it ends, back in the
menus, plus a rank change after competitive. Template lines only, no language model.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import random
import re
import threading
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

LOCKFILE = os.path.expandvars(r"%LOCALAPPDATA%\Riot Games\Riot Client\Config\lockfile")
# Map paths use code names: /Game/Maps/Triad/Triad = Haven
MAPS = {"ascent": "Ascent", "bonsai": "Split", "duality": "Bind", "triad": "Haven", "port": "Icebox",
        "foxtrot": "Breeze", "canyon": "Fracture", "pitt": "Pearl", "jam": "Lotus", "juliett": "Sunset",
        "infinity": "Abyss", "rook": "Corrode", "range": "the Range", "poveglia": "the Range",
        "hurm_alley": "District", "hurm_yard": "Piazza", "hurm_bowl": "Kasbah", "hurm_helix": "Drift",
        "hurm_hightide": "Glitch"}
QUEUES = {"competitive": "competitive", "unrated": "unrated", "swiftplay": "Swiftplay", "spikerush": "Spike Rush",
          "deathmatch": "Deathmatch", "hurm": "Team Deathmatch", "ggteam": "Escalation", "premier": "Premier",
          "onefa": "Replication", "snowball": "Snowball Fight", "newmap": "unrated", "": "a custom game"}
NO_RECAP = {"deathmatch", "ggteam", "snowball"}      # no team score worth saying
TIERS = ["Unranked", "Unused", "Unused", "Iron 1", "Iron 2", "Iron 3", "Bronze 1", "Bronze 2", "Bronze 3",
         "Silver 1", "Silver 2", "Silver 3", "Gold 1", "Gold 2", "Gold 3", "Platinum 1", "Platinum 2", "Platinum 3",
         "Diamond 1", "Diamond 2", "Diamond 3", "Ascendant 1", "Ascendant 2", "Ascendant 3",
         "Immortal 1", "Immortal 2", "Immortal 3", "Radiant"]
LAST_GAME = re.compile(r"\b(how did (my|the) last (game|match) go|how did i do( in| last)|my last (game|match)|"
                       r"how('s| is| have) (my )?(valorant|ranked|rank)|how have i been (doing|playing)|"
                       r"(what'?s|what is) my rank|my last \d+ (games|matches))\b", re.I)

WIN = {"close": ["GG! {a} to {e} on {where}, that was close.", "Phew, {a} to {e} on {where}. Clutch."],
       "big": ["{a} to {e} on {where}? You stomped them.", "Easy one: {a} to {e} on {where}."],
       "": ["Nice, a win on {where}, {a} to {e}.", "GG, {a} to {e} on {where}!"]}
LOSS = {"close": ["Ugh, {a} to {e} on {where}. So close.", "{a} to {e} on {where}... that one hurt."],
        "big": ["{a} to {e} on {where}. Let's forget that one.", "Rough one, {a} to {e} on {where}. Water break?"],
        "": ["Lost {a} to {e} on {where}. Next one's yours.", "{a} to {e} on {where}. Shake it off."]}


def map_name(path: str) -> str:
    code = path.rstrip("/").rsplit("/", 1)[-1].lower()
    return MAPS.get(code, code.replace("_", " ").title()) if code else ""


@dataclass
class Presence:
    loop: str = ""          # MENUS / PREGAME (agent select) / INGAME
    map: str = ""
    queue: str = ""
    ally: int = 0
    enemy: int = 0
    tier: int = 0


def read_presence(private: dict) -> Presence:
    """The decoded `private` blob. Newer clients nest it (matchPresenceData...); older ones were flat."""
    flat: dict = {}
    for k, v in private.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                flat.setdefault(k2, v2)
        else:
            flat.setdefault(k, v)

    def num(*keys) -> int:
        for k in keys:
            try:
                return int(flat[k])
            except (KeyError, TypeError, ValueError):
                continue
        return 0

    return Presence(loop=str(flat.get("sessionLoopState") or ""),
                    map=map_name(str(flat.get("matchMap") or flat.get("partyOwnerMatchMap") or "")),
                    queue=str(flat.get("queueId") or "").lower(),
                    ally=num("partyOwnerMatchScoreAllyTeam"), enemy=num("partyOwnerMatchScoreEnemyTeam"),
                    tier=num("competitiveTier"))


class RiotClient:
    """The Riot Client's local API. The lockfile (port, password) changes every time it starts."""

    def __init__(self, lockfile: str = LOCKFILE, timeout: float = 2):
        self.lockfile, self.timeout = lockfile, timeout
        self._puuid = ""

    def _get(self, path: str):
        import requests
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        try:
            _, _, port, password, proto = open(self.lockfile, encoding="utf-8").read().strip().split(":")
        except (OSError, ValueError):
            return None                                   # Riot Client not running
        try:
            r = requests.get(f"{proto}://127.0.0.1:{port}{path}", auth=("riot", password),
                             verify=False, timeout=self.timeout)      # its own self-signed certificate
            return r.json() if r.ok else None
        except (requests.RequestException, ValueError):
            return None

    def presence(self) -> Presence | None:
        if not self._puuid:
            me = self._get("/chat/v1/session") or {}
            self._puuid = me.get("puuid", "")
            if not self._puuid:
                return None
        data = self._get("/chat/v4/presences") or {}
        for p in data.get("presences", []):
            if p.get("puuid") == self._puuid and p.get("product") == "valorant" and p.get("private"):
                try:
                    return read_presence(json.loads(base64.b64decode(p["private"])))
                except ValueError:
                    return None
        return None


@dataclass
class Match:
    queue: str = ""
    map: str = ""
    ally: int = 0
    enemy: int = 0
    tier_before: int = 0
    tier_after: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def result(self) -> str:
        return "Win" if self.ally > self.enemy else "Loss" if self.ally < self.enemy else "Draw"

    @property
    def where(self) -> str:
        mode = QUEUES.get(self.queue, self.queue)
        place = self.map or "that map"
        return place if self.queue in ("competitive", "unrated", "newmap") else f"{place} in {mode}"


def tier_name(t: int) -> str:
    return TIERS[t] if 0 <= t < len(TIERS) else ""


def recap(m: Match, rng=random) -> str | None:
    if m.queue in NO_RECAP or m.ally + m.enemy == 0:
        return None
    diff = abs(m.ally - m.enemy)
    big = 50 if m.queue == "hurm" else 7                 # Team Deathmatch counts kills to 100
    close = 10 if m.queue == "hurm" else 2
    size = "close" if diff <= close else "big" if diff >= big else ""
    if m.result == "Draw":
        text = f"{m.ally} to {m.enemy} on {m.where}, a draw."
    else:
        text = rng.choice((WIN if m.result == "Win" else LOSS)[size]).format(a=m.ally, e=m.enemy, where=m.where)
    if m.queue == "competitive" and m.tier_before >= 3 and m.tier_after >= 3 and m.tier_after != m.tier_before:
        new = tier_name(m.tier_after)
        text += f" And you ranked up to {new}!" if m.tier_after > m.tier_before else f" You dropped to {new}, you'll get it back."
    return text


class ValorantWatch:
    """Polls the presence: a match is INGAME; when it goes back to the menus (seen twice, so the rank
    has caught up) or the client goes away, the recap is said and kept."""

    def __init__(self, on_recap, client=None, poll_s: float = 4, idle_poll_s: float = 15, rng=None):
        self.on_recap, self.client = on_recap, client or RiotClient()
        self.poll_s, self.idle_poll_s = poll_s, idle_poll_s
        self.rng = rng or random.Random()
        self.match: Match | None = None
        self.tier = 0                        # last rank seen outside a match
        self._after = 0                      # checks since the match left INGAME
        self._stop = threading.Event()

    def tick(self) -> bool:
        """One check; True while a match is going (poll faster)."""
        p = self.client.presence()
        if p is not None and p.loop == "INGAME":
            if self.match is None:
                self.match = Match(tier_before=self.tier)
                log.info("valorant: match started")
            m, self._after = self.match, 0
            m.queue, m.map = p.queue or m.queue, p.map or m.map
            if p.ally + p.enemy >= m.ally + m.enemy:      # never go back to a lower score (a stale read)
                m.ally, m.enemy = p.ally, p.enemy
            return True
        if self.match is not None:
            self._after += 1
            if p is None or self._after >= 2:
                self.match.tier_after = p.tier if p is not None else 0
                self._finish()
            return self.match is not None
        if p is not None and p.tier:
            self.tier = p.tier
        return False

    def _finish(self):
        m, self.match, self._after = self.match, None, 0
        if m.tier_after:
            self.tier = m.tier_after
        text = recap(m, self.rng)
        log.info("valorant: match over %s %d-%d on %s (%s)", m.result, m.ally, m.enemy, m.map, m.queue)
        if text:
            try:
                self.on_recap(text, m)
            except Exception:
                log.exception("valorant recap failed")

    def start(self) -> "ValorantWatch":
        threading.Thread(target=self._run, name="valorant", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                playing = self.tick()
            except Exception:
                log.exception("valorant poll failed")
                playing = self.match is not None
            self._stop.wait(self.poll_s if playing else self.idle_poll_s)


class ValorantHistory:
    """The last matches' recaps, kept in the kv table ("valorant:games") for "how did my last game go?"."""

    KEY = "valorant:games"

    def __init__(self, store, keep: int = 50):
        self.store, self.keep = store, keep

    def all(self) -> list[dict]:
        with self.store.lock:
            row = self.store.db.execute("SELECT value FROM kv WHERE key = ?", (self.KEY,)).fetchone()
        try:
            return json.loads(row["value"]) if row else []
        except ValueError:
            return []

    def add(self, m: Match, text: str, when: str):
        games = (self.all() + [{"when": when, "queue": m.queue, "map": m.map, "result": m.result, "ally": m.ally,
                                "enemy": m.enemy, "tier": tier_name(m.tier_after or m.tier_before),
                                "recap": text}])[-self.keep:]
        with self.store.lock:
            self.store.db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                                  (self.KEY, json.dumps(games)))
            self.store.db.commit()

    def spoken(self, n: int = 1) -> str:
        games = self.all()
        if not games:
            return "I haven't caught a Valorant match yet. I'll keep score next time you play."
        last = games[-1]
        if n <= 1:
            text = f"Your last match ({last['when']}): {last['recap']}"
        else:
            recent = games[-n:]
            wins = sum(1 for g in recent if g.get("result") == "Win")
            text = (f"Your last {len(recent)} matches: {wins} win{'s' if wins != 1 else ''}, "
                    f"{sum(1 for g in recent if g.get('result') == 'Loss')} lost. Last one: {last['recap']}")
        rank = next((g["tier"] for g in reversed(games) if g.get("tier") and g["tier"] != "Unranked"), "")
        return text + (f" You're {rank}." if rank and n > 1 else "")
