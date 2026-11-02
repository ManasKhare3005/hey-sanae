"""Valorant recaps (valorant.py): presence -> match -> one line after it, and the history tool."""
import random

from sanae.tools.registry import ToolRegistry
from sanae.valorant import Match, Presence, ValorantHistory, ValorantWatch, map_name, read_presence, recap
from test_sanae import memory_store

# The shape the Riot Client sends now (release-13.08): nested, partly duplicated at the top
NESTED = {
    "isValid": True,
    "matchPresenceData": {"sessionLoopState": "INGAME", "provisioningFlow": "Matchmaking",
                          "matchMap": "/Game/Maps/Triad/Triad", "queueId": "competitive"},
    "partyPresenceData": {"partyOwnerMatchScoreAllyTeam": 7, "partyOwnerMatchScoreEnemyTeam": 5},
    "playerPresenceData": {"competitiveTier": 10},
    "partyOwnerMatchScoreAllyTeam": 7, "partyOwnerMatchScoreEnemyTeam": 5,
}


def test_presence_both_shapes():
    p = read_presence(NESTED)
    assert (p.loop, p.map, p.queue, p.ally, p.enemy, p.tier) == ("INGAME", "Haven", "competitive", 7, 5, 10)
    old = {"sessionLoopState": "MENUS", "matchMap": "", "queueId": "unrated", "partyOwnerMatchScoreAllyTeam": "0",
           "competitiveTier": 12}
    p = read_presence(old)
    assert (p.loop, p.map, p.tier) == ("MENUS", "", 12)
    assert map_name("/Game/Maps/Bonsai/Bonsai") == "Split" and map_name("/Game/Maps/NewOne/NewOne") == "Newone"


class FakeClient:
    def __init__(self):
        self.p = Presence(loop="MENUS", tier=10)

    def presence(self):
        return self.p


def test_a_match_then_a_recap_with_rank_up():
    c = FakeClient()
    said = []
    w = ValorantWatch(lambda text, m: said.append((text, m)), client=c, rng=random.Random(2))
    assert w.tick() is False and w.tier == 10
    c.p = Presence(loop="PREGAME", tier=10)
    w.tick()
    for a, e in [(0, 0), (5, 3), (12, 9), (11, 9)]:            # a stale lower read is ignored
        c.p = Presence(loop="INGAME", map="Ascent", queue="competitive", ally=a, enemy=e, tier=10)
        assert w.tick() is True
    c.p = Presence(loop="INGAME", map="Ascent", queue="competitive", ally=13, enemy=9, tier=10)
    w.tick()
    c.p = Presence(loop="MENUS", tier=10)
    w.tick()
    assert said == []                                           # waits one more check for the new rank
    c.p = Presence(loop="MENUS", tier=11)
    w.tick()
    text, m = said[0]
    assert m.result == "Win" and (m.ally, m.enemy) == (13, 9) and "13 to 9" in text and "Ascent" in text
    assert text.endswith("And you ranked up to Silver 3!")
    assert w.match is None and w.tier == 11


def test_client_gone_mid_match_still_recaps():
    c = FakeClient()
    said = []
    w = ValorantWatch(lambda text, m: said.append(text), client=c)
    c.p = Presence(loop="INGAME", map="Lotus", queue="swiftplay", ally=2, enemy=5)
    w.tick()
    c.p = None
    w.tick()
    assert said and "Lotus in Swiftplay" in said[0] and "2 to 5" in said[0]


def test_recap_lines():
    rng = random.Random(0)
    assert recap(Match("deathmatch", "Bind", 40, 0), rng) is None
    assert recap(Match("unrated", "Bind", 0, 0), rng) is None
    assert "a draw" in recap(Match("unrated", "Bind", 12, 12), rng)
    assert "13 to 2" in recap(Match("unrated", "Bind", 13, 2), rng)
    down = recap(Match("competitive", "Bind", 8, 13, tier_before=12, tier_after=11), rng)
    assert down.endswith("You dropped to Silver 3, you'll get it back.")


def test_history_tool_and_route():
    h = ValorantHistory(memory_store())
    reg = ToolRegistry(context=type("C", (), {"valorant_history": h})())
    from sanae.tools import fun

    fun.register(reg)
    assert reg.run("valorant_games", {}).startswith("I haven't caught a Valorant match yet")
    h.add(Match("competitive", "Ascent", 13, 9, 10, 11), "GG, 13 to 9 on Ascent!", "Sun Oct 18, 2:10 PM")
    h.add(Match("competitive", "Bind", 7, 13, 11, 11), "Lost 7 to 13 on Bind.", "Sun Oct 18, 2:55 PM")
    assert reg.run("valorant_games", {}) == "Your last match (Sun Oct 18, 2:55 PM): Lost 7 to 13 on Bind."
    assert reg.run("valorant_games", {"games": 5}) == ("Your last 2 matches: 1 win, 1 lost. Last one: Lost 7 to 13 on Bind. "
                                                       "You're Silver 3.")
    from sanae.agent import direct_route

    tools = {"valorant_games": 1}
    assert direct_route("how did my last game go?", tools) == ("valorant_games", {"games": 1})
    assert direct_route("how did my last 3 matches go", tools) == ("valorant_games", {"games": 3})
    assert direct_route("what's my rank?", tools) == ("valorant_games", {"games": 5})
    assert direct_route("how did my last league game go?", tools) is None
    assert direct_route("play valorant music", tools) is None
