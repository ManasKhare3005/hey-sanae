"""League companion (league.py): reactions, the one-a-minute and not-mid-fight rules, the recap."""
from sanae.league import GameState, LeagueCompanion, LeagueHistory, react, recap
from test_sanae import memory_store

ME = {"summonerName": "Alex", "riotId": "Alex#NA1", "riotIdGameName": "Alex"}


def game_data(events, kills=0, deaths=0, assists=0, cs=0, t=600.0, health=1000.0):
    return {
        "activePlayer": {**ME, "championStats": {"currentHealth": health, "maxHealth": 1000.0}},
        "allPlayers": [
            {**ME, "team": "ORDER", "championName": "Ahri",
             "scores": {"kills": kills, "deaths": deaths, "assists": assists, "creepScore": cs}},
            {"summonerName": "Buddy", "riotIdGameName": "Buddy", "team": "ORDER", "championName": "Lee Sin", "scores": {}},
            {"summonerName": "Enemy", "riotIdGameName": "Enemy", "team": "CHAOS", "championName": "Zed", "scores": {}},
        ],
        "events": {"Events": events},
        "gameData": {"gameTime": t},
    }


def ev(i, name, **kw):
    return {"EventID": i, "EventName": name, **kw}


class Feed:
    def __init__(self):
        self.data = None

    def all(self):
        return self.data


def make():
    feed, said, recaps, clock = Feed(), [], [], {"t": 1000.0}
    c = LeagueCompanion(said.append, lambda text, game: recaps.append((text, game)), client=feed,
                        clock=lambda: clock["t"])
    return c, feed, said, recaps, clock


def test_reactions():
    g = GameState.read(game_data([], deaths=5))
    assert g.me >= {"alex"} and "buddy" in g.my_team and "enemy" not in g.my_team and g.champion == "Ahri"
    assert react(ev(1, "ChampionKill", KillerName="Alex", VictimName="Enemy"), g) == "kill"
    assert react(ev(1, "ChampionKill", KillerName="Enemy", VictimName="Alex#NA1"), g) == "death"
    assert react(ev(1, "ChampionKill", KillerName="Buddy", VictimName="Enemy"), g) is None      # not about you
    assert react(ev(1, "Multikill", KillerName="Alex", KillStreak=5), g) == "penta"
    assert react(ev(1, "BaronKill", KillerName="Buddy"), g) == "baron_us"
    assert react(ev(1, "DragonKill", KillerName="Enemy"), g) == "dragon_them"
    assert react(ev(1, "HeraldKill", KillerName="Enemy"), g) is None
    assert react(ev(1, "Ace", Acer="Enemy", AcingTeam="CHAOS"), g) == "ace_them"
    assert react(ev(1, "FirstBlood", Recipient="Alex"), g) == "first_blood_me"
    g.deaths = 6
    assert react(ev(1, "ChampionKill", KillerName="Enemy", VictimName="Alex"), g) == "deaths_many"


def test_one_line_a_minute_and_never_mid_fight():
    c, feed, said, recaps, clock = make()
    feed.data = game_data([ev(0, "GameStart")])
    assert c.tick() and said == []
    feed.data = game_data([ev(0, "GameStart"), ev(1, "ChampionKill", KillerName="Alex", VictimName="Enemy")])
    c.tick()
    assert said == []                                   # the kill just happened: still a fight
    clock["t"] += 9
    c.tick()
    assert said == ["Nice kill!"]
    feed.data["events"]["Events"].append(ev(2, "ChampionKill", KillerName="Alex", VictimName="Enemy"))
    clock["t"] += 10
    c.tick()
    clock["t"] += 10
    c.tick()
    assert said == ["Nice kill!"]                       # a minute hasn't passed
    clock["t"] += 30
    c.tick()
    assert len(said) == 1                               # waited more than 25 s: that one was dropped
    feed.data["events"]["Events"].append(ev(3, "BaronKill", KillerName="Buddy"))
    clock["t"] += 9                                     # baron counts as big: 20 s gap is enough
    c.tick()
    clock["t"] += 1
    c.tick()
    assert said[-1] == "Baron's yours! Push."


def test_losing_health_fast_counts_as_a_fight():
    c, feed, said, recaps, clock = make()
    feed.data = game_data([ev(0, "GameStart")], health=1000)
    c.tick()
    feed.data = game_data([ev(0, "GameStart"), ev(1, "FirstBlood", Recipient="Alex")], health=700)
    clock["t"] += 1
    c.tick()
    for hp in (600, 500, 400, 250):                      # polled every 2 s, still losing health
        clock["t"] += 2
        feed.data["activePlayer"]["championStats"]["currentHealth"] = hp
        c.tick()
    clock["t"] += 1                                     # the kill is 10 s old, but you were just being hit
    c.tick()
    assert said == []
    clock["t"] += 8
    c.tick()
    assert said == ["First blood! Nice."]


def test_joining_mid_game_and_the_recap():
    c, feed, said, recaps, clock = make()
    old = [ev(0, "GameStart"), ev(1, "ChampionKill", KillerName="Alex", VictimName="Enemy")]
    feed.data = game_data(old, kills=1)
    c.tick()
    clock["t"] += 100
    c.tick()
    assert said == []                                   # Sanae started late: no cheering for old kills
    end = old + [ev(2, "GameEnd", Result="Win")]
    feed.data = game_data(end, kills=9, deaths=2, assists=14, cs=210, t=1830)
    assert c.tick() is False
    assert recaps[0][0] == "GG, you won! You went 9/2/14 on Ahri, 210 CS (7.0 a minute) in 30 minutes. That was a really clean game."
    clock["t"] += 5
    assert c.tick() is False and len(recaps) == 1       # the end screen is still up: not a new game
    feed.data = None
    c.tick()
    feed.data = game_data([ev(0, "GameStart")], t=900, deaths=9)
    c.tick()
    feed.data = None                                    # client closed with no GameEnd seen
    c.tick()
    assert recaps[1][0].startswith("Game over. You went 0/9/0 on Ahri")


def test_quiet_and_recap_wording():
    c, feed, said, recaps, clock = make()
    c.quiet = lambda: True
    feed.data = game_data([ev(0, "GameStart"), ev(1, "Multikill", KillerName="Alex", KillStreak=5)])
    c.tick()
    clock["t"] += 20
    c.tick()
    assert said == []                                   # "not now" silences the reactions
    lose = GameState(champion="Yasuo", kills=2, deaths=11, assists=3, cs=90, game_time=1500, result="Lose")
    assert recap(lose).endswith("Maybe take a short break before the next one?")


def test_history_and_tool():
    from types import SimpleNamespace

    from sanae.tools import fun as fun_tools
    from sanae.tools.registry import ToolRegistry

    h = LeagueHistory(memory_store())
    reg = ToolRegistry(context=SimpleNamespace(league_history=h))
    fun_tools.register(reg)
    assert reg.run("league_games", {}) == "I haven't watched you play a League game yet."
    h.add(GameState(champion="Ahri", kills=9, deaths=2, assists=14, game_time=1830, result="Win"), "GG, you won!", "Sun Oct 18, 9:40 PM")
    h.add(GameState(champion="Zed", kills=3, deaths=7, assists=2, game_time=1500, result="Lose"), "GG. Rough one.", "Sun Oct 18, 10:20 PM")
    assert reg.run("league_games", {}) == "Your last game (Sun Oct 18, 10:20 PM): GG. Rough one."
    assert reg.run("league_games", {"games": 5}).startswith("Your last 2 games: 1 win out of 2, 12/9/16 in total.")
