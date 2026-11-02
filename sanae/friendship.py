"""Builds the friendship parts (part.py) from persona.yaml's `friend:` section: goals, wins, care..."""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)
# kv prefixes the parts keep; the privacy page's "what she learned about you" deletes them too
KV_PREFIXES = ("goals", "wins", "pushback", "care", "social", "texts", "thoughts", "life", "rituals", "surprises", "together", "journal", "roommate", "promises", "weekend", "cooking", "watching", "japanese", "bucket", "scrapbook", "stories", "asks", "place", "winddown", "groceries", "meals", "playlist", "dailyphoto", "gooddays", "reflect", "aims", "factcheck")


def forget_all(memory):
    with memory.lock:
        for p in KV_PREFIXES:
            memory.db.execute("DELETE FROM kv WHERE key LIKE ?", (f"{p}:%",))
        try:                                 # kept scrapbook photos: the files go too
            from pathlib import Path

            for (f,) in memory.db.execute("SELECT file FROM scrapbook").fetchall():
                Path(f).unlink(missing_ok=True)
        except Exception:
            pass
        for table in ("activity_log", "activities", "journal", "voicenotes", "promises", "weekly", "wrapped", "weekend_plans", "drawings",
                      "watched", "jp_deck", "bucket", "scrapbook", "stories", "gifts", "groceries", "recipes", "meal_plan", "playlist", "watchlist", "movie_log", "daily_photos",
                      "grocery_bought", "lessons", "about_pending"):
            try:
                memory.db.execute(f"DELETE FROM {table}")
            except Exception:
                pass                         # not made yet
        memory.db.commit()


def make_parts(ctx, persona) -> list:
    f = (getattr(persona, "friend", None) or {}) if persona is not None else {}
    mem = ctx.memory
    parts = []

    def on(key: str) -> bool:
        v = f.get(key, True)
        return v is not False and not (isinstance(v, dict) and v.get("enabled") is False)

    if on("goals"):
        from .goals import Goals

        ctx.goals = Goals(mem)
        parts.append(ctx.goals)
    if on("wins"):
        from .wins import Wins

        w = f.get("wins") if isinstance(f.get("wins"), dict) else {}
        ctx.wins = Wins(mem, projects=ctx.projects, todos=ctx.todos, goals=getattr(ctx, "goals", None),
                        valorant=ctx.valorant_history, skip_projects=w.get("skip_projects", ["Sanae"]))
        parts.append(ctx.wins)
    if on("pushback"):
        from .pushback import Pushback

        bed = (getattr(persona, "initiative", None) or {}).get("bedtime") or {}
        ctx.pushback = Pushback(mem, ctx=ctx, goals=getattr(ctx, "goals", None), late_from=bed.get("from", "00:30"))
        parts.append(ctx.pushback)
    if on("care"):
        from .care import Care
        from .initiative import idle_seconds

        ctx.care = Care(mem, health=ctx.health, wins=getattr(ctx, "wins", None), idle=idle_seconds)
        parts.append(ctx.care)
    if on("social"):
        from .initiative import idle_seconds
        from .social import Social

        ctx.social = Social(mem, friend=ctx.friend, diary=getattr(ctx, "diary", None), idle=idle_seconds)
        parts.append(ctx.social)
    if on("life"):
        import os

        from .herlife import HerLife
        from .initiative import idle_seconds

        recent = None
        if os.name == "nt":
            from .music import RECENT as recent
        ctx.life = HerLife(mem, settings=f.get("life") if isinstance(f.get("life"), dict) else {},
                           recent_tracks=recent, idle=idle_seconds)
        parts.append(ctx.life)
    if on("japanese"):
        from .initiative import idle_seconds
        from .japanese import Japanese

        ctx.japanese = Japanese(mem, life=getattr(ctx, "life", None), idle=idle_seconds)
        parts.append(ctx.japanese)
    if on("drawings"):
        from .drawings import Drawings

        ctx.drawings = Drawings(mem, life=getattr(ctx, "life", None))
        parts.append(ctx.drawings)
    if on("bucket"):
        from .bucket import Bucket
        from .initiative import idle_seconds

        ctx.bucket = Bucket(mem, drawings=getattr(ctx, "drawings", None), idle=idle_seconds)
        parts.append(ctx.bucket)
    if on("scrapbook") and getattr(ctx, "vision", None) is not None:
        from .scrapbook import Scrapbook

        bus = getattr(ctx, "bus", None)
        ctx.scrapbook = Scrapbook(mem, vision=ctx.vision, drawings=getattr(ctx, "drawings", None),
                                  bucket=getattr(ctx, "bucket", None), llm=ctx.llm, model=ctx.cfg.llm.fast_model,
                                  user=ctx.cfg.assistant.user_name, her=getattr(persona, "name", "Sanae"),
                                  publish=bus.publish if bus is not None else (lambda k, d: None))
        parts.append(ctx.scrapbook)
    if on("dailyphoto"):
        from .dailyphoto import DailyPhoto
        from .initiative import idle_seconds

        bus = getattr(ctx, "bus", None)
        briefing = getattr(ctx, "briefing", None)
        ctx.dailyphoto = DailyPhoto(mem, health=getattr(ctx, "health", None), weather=getattr(briefing, "weather", None),
                                    scrapbook=getattr(ctx, "scrapbook", None), idle=idle_seconds,
                                    publish=bus.publish if bus is not None else (lambda k, d: None),
                                    drawings=getattr(ctx, "drawings", None))
        if getattr(ctx, "scrapbook", None) is not None:
            ctx.scrapbook.daily = ctx.dailyphoto
        parts.append(ctx.dailyphoto)
    if on("reflect") and getattr(ctx, "brain", None) is not None and ctx.brain.enabled:
        from .reflect import Reflection

        def can_reflect() -> bool:
            agent = getattr(ctx, "agent", None)
            return not (agent is not None and agent.busy)

        ctx.reflect = Reflection(mem, brain=ctx.brain, user=ctx.cfg.assistant.user_name,
                                 her=getattr(persona, "name", "Sanae"), can_run=can_reflect).start()
        parts.append(ctx.reflect)
    if on("aims") and getattr(ctx, "brain", None) is not None and ctx.brain.enabled:
        from .aims import Aims
        from .initiative import idle_seconds

        def can_aim() -> bool:
            agent = getattr(ctx, "agent", None)
            return not (agent is not None and agent.busy)

        ctx.aims = Aims(mem, brain=ctx.brain, user=ctx.cfg.assistant.user_name, her=getattr(persona, "name", "Sanae"),
                        goals=getattr(ctx, "goals", None), reflect=getattr(ctx, "reflect", None),
                        idle=idle_seconds, can_run=can_aim).start()
        parts.append(ctx.aims)
    if on("gooddays"):
        from .gooddays import GoodDays
        from .initiative import idle_seconds

        ctx.gooddays = GoodDays(mem, idle=idle_seconds)
        parts.append(ctx.gooddays)
    if on("stories"):
        from .stories import Stories

        ctx.stories = Stories(mem, llm=ctx.llm, model=ctx.cfg.llm.fast_model, user=ctx.cfg.assistant.user_name,
                              her=getattr(persona, "name", "Sanae"), diary=getattr(ctx, "diary", None))
        parts.append(ctx.stories)
    if on("asks"):
        from .asks import Asks
        from .initiative import idle_seconds

        ctx.asks = Asks(mem, idle=idle_seconds, life=getattr(ctx, "life", None), drawings=getattr(ctx, "drawings", None),
                        vision=getattr(ctx, "vision", None))
        parts.append(ctx.asks)
    if on("together"):
        from .initiative import idle_seconds
        from .together import Together

        t = f.get("together") if isinstance(f.get("together"), dict) else {}
        ctx.together = Together(mem, life=getattr(ctx, "life", None), goals=getattr(ctx, "goals", None),
                                idle=idle_seconds, settings=t)
        ctx.together.drawings = getattr(ctx, "drawings", None)
        parts.append(ctx.together)
    if on("cooking"):
        from .cooking import Cooking
        from .initiative import idle_seconds

        bus = getattr(ctx, "bus", None)
        ctx.cooking = Cooking(mem, llm=ctx.llm, model=ctx.cfg.llm.fast_model, reminders=ctx.reminders,
                              vision=getattr(ctx, "vision", None), idle=idle_seconds,
                              publish=bus.publish if bus is not None else (lambda k, d: None))
        parts.append(ctx.cooking)
    if on("groceries"):
        from .groceries import Groceries
        from .initiative import idle_seconds

        ctx.groceries = Groceries(mem, idle=idle_seconds, cooking=getattr(ctx, "cooking", None))
        parts.append(ctx.groceries)
    if on("meals") and getattr(ctx, "cooking", None) is not None:
        from .initiative import idle_seconds
        from .meals import Meals

        bus = getattr(ctx, "bus", None)
        ctx.meals = Meals(mem, llm=ctx.llm, model=ctx.cfg.llm.fast_model, cooking=ctx.cooking,
                          groceries=getattr(ctx, "groceries", None), friend=ctx.friend, user=ctx.cfg.assistant.user_name,
                          idle=idle_seconds, publish=bus.publish if bus is not None else (lambda k, d: None))
        parts.append(ctx.meals)
    if on("watching") and os.name == "nt":
        from .initiative import idle_seconds
        from .watching import Watching

        bed = (getattr(persona, "initiative", None) or {}).get("bedtime") or {}
        ctx.watching = Watching(mem, idle=idle_seconds, bedtime=bed.get("from", "00:30"))
        parts.append(ctx.watching)
    if on("weekend"):
        from .initiative import idle_seconds
        from .weekend import Weekend

        w = f.get("weekend") if isinstance(f.get("weekend"), dict) else {}
        ctx.weekend = Weekend(mem, idle=idle_seconds, bucket=getattr(ctx, "bucket", None), settings=w)
        parts.append(ctx.weekend)
    if on("winddown"):
        from .initiative import idle_seconds
        from .winddown import WindDown

        w = f.get("winddown") if isinstance(f.get("winddown"), dict) else {}
        ctx.winddown = WindDown(mem, ctx=ctx, idle=idle_seconds, settings=w, user=ctx.cfg.assistant.user_name)
        parts.append(ctx.winddown)
    if on("place"):
        from .initiative import idle_seconds
        from .place import Place

        ctx.place = Place(mem, ctx=ctx, idle=idle_seconds)
        parts.append(ctx.place)
    if on("playlist"):
        from .initiative import idle_seconds
        from .playlist import Playlist

        playing = None
        if os.name == "nt":
            from .music import now_playing as playing
        bus = getattr(ctx, "bus", None)
        ctx.playlist = Playlist(mem, now_playing=playing, idle=idle_seconds,
                                publish=bus.publish if bus is not None else (lambda k, d: None))
        parts.append(ctx.playlist)
    if on("roommate"):
        from .roommate import Roommate

        r = f.get("roommate") if isinstance(f.get("roommate"), dict) else {}
        briefing = getattr(ctx, "briefing", None)
        ctx.roommate = Roommate(mem, together=getattr(ctx, "together", None), life=getattr(ctx, "life", None),
                                weather=getattr(briefing, "weather", None), settings=r)
        ctx.roommate.playlist = getattr(ctx, "playlist", None)
        ctx.roommate.watching = getattr(ctx, "watching", None)
        parts.append(ctx.roommate)
    if on("journal"):
        from .journal import Journal

        def can_write() -> bool:
            agent = getattr(ctx, "agent", None)
            return not ctx.models_asleep and not (agent is not None and agent.busy)

        bus = getattr(ctx, "bus", None)
        ctx.journal = Journal(mem, llm=ctx.llm, model=ctx.cfg.llm.fast_model, user=ctx.cfg.assistant.user_name,
                              her=getattr(persona, "name", "Sanae"), life=getattr(ctx, "life", None), friend=ctx.friend,
                              can_run=can_write, publish=bus.publish if bus is not None else (lambda k, d: None))
        ctx.journal.drawings = getattr(ctx, "drawings", None)
        ctx.journal.start()
        parts.append(ctx.journal)
    if on("voicenotes"):
        from .voicenotes import VoiceNotes

        cached: dict = {}

        def voice():
            if "v" not in cached:
                from .tts import make_voice

                cached["v"] = make_voice(ctx.cfg.tts)
            return cached["v"]

        def can_make() -> bool:
            agent = getattr(ctx, "agent", None)
            return not ctx.models_asleep and not (agent is not None and agent.busy)

        v = f.get("voicenotes") if isinstance(f.get("voicenotes"), dict) else {}
        bus = getattr(ctx, "bus", None)
        ctx.voicenotes = VoiceNotes(mem, llm=ctx.llm, model=ctx.cfg.llm.fast_model, user=ctx.cfg.assistant.user_name,
                                    her=getattr(persona, "name", "Sanae"), ctx=ctx, voice=voice, can_run=can_make,
                                    publish=bus.publish if bus is not None else (lambda k, d: None), settings=v).start()
        parts.append(ctx.voicenotes)
    if on("promises"):
        from .initiative import idle_seconds
        from .promises import Promises

        bus = getattr(ctx, "bus", None)
        ctx.promises = Promises(mem, reminders=ctx.reminders, idle=idle_seconds,
                                publish=bus.publish if bus is not None else (lambda k, d: None))
        parts.append(ctx.promises)
    if on("weekly"):
        from .weekly import Weekly

        def can_review() -> bool:
            agent = getattr(ctx, "agent", None)
            return not ctx.models_asleep and not (agent is not None and agent.busy)

        bus = getattr(ctx, "bus", None)
        ctx.weekly = Weekly(mem, ctx=ctx, llm=ctx.llm, model=ctx.cfg.llm.fast_model, user=ctx.cfg.assistant.user_name,
                            her=getattr(persona, "name", "Sanae"), can_run=can_review,
                            publish=bus.publish if bus is not None else (lambda k, d: None)).start()
        parts.append(ctx.weekly)
    if on("wrapped"):
        from .wrapped import Wrapped

        def can_wrap() -> bool:
            agent = getattr(ctx, "agent", None)
            return not ctx.models_asleep and not (agent is not None and agent.busy)

        bus = getattr(ctx, "bus", None)
        ctx.wrapped = Wrapped(mem, ctx=ctx, llm=ctx.llm, model=ctx.cfg.llm.fast_model, user=ctx.cfg.assistant.user_name,
                              her=getattr(persona, "name", "Sanae"), can_run=can_wrap,
                              publish=bus.publish if bus is not None else (lambda k, d: None)).start()
        parts.append(ctx.wrapped)
    if on("rituals"):
        from .initiative import idle_seconds
        from .rituals import Rituals

        r = dict(f.get("rituals")) if isinstance(f.get("rituals"), dict) else {}
        c = (getattr(persona, "initiative", None) or {}).get("checkin") or {}
        r.setdefault("checkin", [c.get("from", "20:00"), c.get("until", "23:00")])
        ctx.rituals = Rituals(mem, ctx=ctx, goals=getattr(ctx, "goals", None), settings=r, idle=idle_seconds)
        parts.append(ctx.rituals)
    if on("surprises"):
        from .initiative import idle_seconds
        from .surprises import Surprises

        def said(text: str):
            agent = getattr(ctx, "agent", None)
            if agent is not None:
                agent.add_said(text)

        ctx.surprises = Surprises(mem, diary=getattr(ctx, "diary", None), friend=ctx.friend, idle=idle_seconds,
                                  llm=ctx.llm, model=ctx.cfg.llm.fast_model, user=ctx.cfg.assistant.user_name,
                                  on_line=said)
        parts.append(ctx.surprises)
    if on("factcheck") and getattr(ctx, "friend", None) is not None:
        from .factcheck import FactCheck

        parts.append(FactCheck(mem, friend=ctx.friend))
    return parts
