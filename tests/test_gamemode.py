"""Game mode on its own (gamemode.py): a game starts -> models off and quiet; it closes -> back."""
import random
from types import SimpleNamespace

from sanae.gamemode import GameMode, game_name, running_game, start_line


def test_on_and_off_need_two_checks():
    state = {"game": None}
    events = []
    gm = GameMode(lambda: state["game"], lambda g: events.append(("on", g)), lambda g: events.append(("off", g)))
    gm.tick()
    assert events == [] and not gm.active
    state["game"] = "VALORANT-Win64-Shipping.exe"
    gm.tick()
    assert events == []                                       # one sighting isn't enough
    gm.tick()
    assert events == [("on", "VALORANT-Win64-Shipping.exe")] and gm.active
    gm.tick()
    assert len(events) == 1                                   # no repeats while it runs
    state["game"] = None
    gm.tick()
    state["game"] = "VALORANT-Win64-Shipping.exe"             # a loading hiccup: still in game mode
    gm.tick()
    state["game"] = None
    gm.tick()
    assert gm.active and len(events) == 1
    gm.tick()
    assert events[-1] == ("off", "VALORANT-Win64-Shipping.exe") and not gm.active


def test_a_failing_callback_doesnt_stop_it():
    gm = GameMode(lambda: "x.exe", lambda g: 1 / 0, lambda g: None, confirm=1)
    gm.tick()
    assert gm.active


def test_names_and_lines():
    assert game_name("VALORANT-Win64-Shipping.exe") == "Valorant"
    assert game_name("Minecraft.exe") == "Minecraft"
    assert "Valorant" in start_line("VALORANT-Win64-Shipping.exe", random.Random(1))


def test_running_game_matches_process_names(monkeypatch):
    import psutil

    procs = [SimpleNamespace(info={"name": "RiotClientServices.exe"}), SimpleNamespace(info={"name": "VALORANT-Win64-Shipping.exe"})]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter(procs))
    assert running_game(["valorant-win64-shipping.exe"]) == "valorant-win64-shipping.exe"
    assert running_game(["League of Legends.exe"]) is None
