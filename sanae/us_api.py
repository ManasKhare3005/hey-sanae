"""The phone's "Us" tab: the daily list you do together (together.py) and, as they're added, the
exchange diary, promises, her voice notes and the week in review.

GET /api/us gives everything the tab shows in one go (the phone caches it for offline); the
other routes change one thing. Phone edits made offline are queued on the phone and replayed.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel


class NewActivity(BaseModel):
    title: str
    why: str = ""
    days: str = "daily"
    at: str = ""
    app: str = ""
    minutes: int = 0


class ActivityChange(BaseModel):
    title: str | None = None
    why: str | None = None
    days: str | None = None
    at: str | None = None
    app: str | None = None
    minutes: int | None = None


class ActivityDay(BaseModel):
    day: str = ""          # YYYY-MM-DD, "" = today
    done: bool = True
    how: str = "tap"       # tap / app / pass


class StartBody(BaseModel):
    minutes: int = 0


class NewPage(BaseModel):
    text: str
    mood: str = ""
    private: bool = False
    letter_months: int = 0     # > 0: a sealed letter to future you, handed back after this many months


class PageChange(BaseModel):
    private: bool


class NewPromise(BaseModel):
    who: str = "you"                     # you / her
    text: str
    when: str = ""                       # "tonight", "tomorrow", "this week", "before 1"...


class PromiseChange(BaseModel):
    status: str                          # kept / broken / dropped / open


class NewPlan(BaseModel):
    text: str
    day: str = ""                        # sat / sun / "" (either)
    at: str = ""                         # HH:MM


class PlanChange(BaseModel):
    done: bool


class PlaceEvent(BaseModel):
    place: str = "home"
    event: str                           # arrived / left
    at_ms: int = 0


class NewBucket(BaseModel):
    text: str


class GroceryClear(BaseModel):
    which: str = "done"                  # done (ticked) / all


class MealCount(BaseModel):
    count: int = 5


class Stars(BaseModel):
    stars: int


class Review(BaseModel):
    word: str
    right: bool
    day: str = ""


class Reviews(BaseModel):
    results: list[Review]


class PhoneLife(BaseModel):
    day: str = ""
    apps: dict[str, float] = {}          # package -> minutes in the foreground today (known apps only)
    night: dict[str, float] = {}         # package -> minutes since midnight (only sent before 5 AM)
    workouts: list[dict] = []            # {start, end, type, minutes, km} from Health Connect
    playing: dict = {}                   # {title, artist}


def register(app: FastAPI, rt, stt=None, voice_wav=None):
    """`stt()`: the speech-to-text (server.py loads Whisper on first use), for spoken diary pages and
    calls; `voice_wav(text)`: her voice as WAV bytes."""
    ctx = rt.ctx

    def together():
        t = getattr(ctx, "together", None)
        if t is None:
            raise HTTPException(503, "the daily list is off (persona.yaml friend.together) or memory is off")
        return t

    def changed(what: str, **data):
        rt.bus.publish("us", {"what": what, **data})

    @app.get("/api/us")
    def us():
        out = {}
        t = getattr(ctx, "together", None)
        if t is not None:
            out["together"] = t.status()
        for name in ("journal", "promises", "voicenotes", "weekly", "wrapped", "weekend", "drawings", "cooking", "watching", "japanese", "bucket", "groceries", "meals", "playlist", "dailyphoto", "gooddays", "scrapbook", "stories", "asks"):
            part = getattr(ctx, name, None)
            if part is not None and hasattr(part, "status"):
                try:
                    out[name] = part.status()
                except Exception as exc:          # one broken section must not hide the others
                    out[name] = {"error": str(exc)}
        return out

    # ----- her brain (cloudbrain.py + reflect.py) -----
    @app.get("/api/brain")
    def brain():
        b = getattr(ctx, "brain", None)
        r = getattr(ctx, "reflect", None)
        return {"brain": b.status() if b is not None else {"enabled": False, "available": False},
                "lessons": r.status()["lessons"] if r is not None else [],
                "aims": ctx.aims.status() if getattr(ctx, "aims", None) is not None else None,
                "sent": b.recent(10) if b is not None else [],
                "mind": ctx.mind.status() if getattr(ctx, "mind", None) is not None else {"enabled": False}}

    @app.delete("/api/brain/lessons/{lid}")
    def brain_forget_lesson(lid: int):
        r = getattr(ctx, "reflect", None)
        if r is None or not r.remove(lid):
            raise HTTPException(404, "no such lesson")
        changed("brain")
        return {"ok": True}

    # ----- the daily list -----
    @app.post("/api/together")
    def together_add(body: NewActivity):
        try:
            a = together().add(body.title, why=body.why, days=body.days, at=body.at, app=body.app, minutes=body.minutes)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        changed("together", action="added", id=a["id"])
        return together().status()

    @app.put("/api/together/{ident}")
    def together_edit(ident: str, body: ActivityChange):
        if together().update(ident, **body.model_dump()) is None:
            raise HTTPException(404, "no such activity")
        changed("together", action="edited", id=ident)
        return together().status()

    @app.delete("/api/together/{ident}")
    def together_remove(ident: str):
        if together().remove(ident) is None:
            raise HTTPException(404, "no such activity")
        changed("together", action="removed", id=ident)
        return together().status()

    @app.post("/api/together/{ident}/day")
    def together_day(ident: str, body: ActivityDay):
        t = together()
        a = t.get_one(ident)
        if a is None:
            raise HTTPException(404, "no such activity")
        day = body.day or t.today()
        if not body.done:
            t.unlog(a, day)
        elif body.how == "pass":
            if not t.use_pass(a, day):
                raise HTTPException(409, "the pass for this week is used")
        else:
            t.log(a, day, body.how if body.how in ("tap", "app") else "tap")
        changed("together", action="day", id=a["id"], done=body.done)
        return t.status()

    @app.post("/api/together/{ident}/start")
    def together_start(ident: str, body: StartBody):
        t = together()
        a = t.get_one(ident)
        if a is None:
            raise HTTPException(404, "no such activity")
        s = t.start(a, body.minutes or None, origin="phone")
        changed("together", action="started", id=a["id"])
        return {**t.status(), "started": s}

    # ----- what the phone noticed (roommate.py): workouts, app minutes, what's playing -----
    @app.post("/api/phone/life")
    def phone_life(body: PhoneLife):
        r = getattr(ctx, "roommate", None)
        if r is None:
            raise HTTPException(503, "noticing is off (persona.yaml friend.roommate) or memory is off")
        seen = r.report(body.model_dump())
        if any(s.startswith("ticked:") for s in seen):
            changed("together", action="app")
        return {"noticed": seen}

    # ----- the exchange diary (journal.py) -----
    def journal():
        j = getattr(ctx, "journal", None)
        if j is None:
            raise HTTPException(503, "the notebook is off (persona.yaml friend.journal) or memory is off")
        return j

    @app.post("/api/journal")
    def journal_write(body: NewPage):
        try:
            journal().write(body.text, body.mood, body.private, letter_months=body.letter_months)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        changed("journal", action="written")
        return journal().status()

    @app.post("/api/journal/voice")
    async def journal_voice(request: Request, mood: str = "", private: bool = False):
        """A page said out loud: WAV (16 kHz) in, transcribed here, saved as a page."""
        from starlette.concurrency import run_in_threadpool

        from . import remote

        body = await request.body()
        if not body or len(body) > 20 * 2**20:
            raise HTTPException(400, "send a WAV recording (up to 20 MB)")
        try:
            audio = remote.decode_wav(body)
        except Exception as exc:
            raise HTTPException(400, f"couldn't read the audio: {exc}")
        # not the command vocabulary hint: a diary page is ordinary talk
        text = await run_in_threadpool(lambda: stt().whisper(audio, prompt="A personal diary entry, spoken casually."))
        if not text or len(text.split()) < 3:
            raise HTTPException(400, "I couldn't hear a page in that recording")
        journal().write(text, mood, private, voice=True)
        changed("journal", action="written")
        return journal().status()

    @app.put("/api/journal/{pid}")
    def journal_private(pid: int, body: PageChange):
        if journal().set_private(pid, body.private) is None:
            raise HTTPException(404, "no such page")
        return journal().status()

    @app.delete("/api/journal/{pid}")
    def journal_delete(pid: int):
        if not journal().delete(pid):
            raise HTTPException(404, "no such page of yours")
        changed("journal", action="deleted")
        return journal().status()

    # ----- pinky promises (promises.py) -----
    def promises():
        p = getattr(ctx, "promises", None)
        if p is None:
            raise HTTPException(503, "promises are off (persona.yaml friend.promises) or memory is off")
        return p

    @app.post("/api/promises")
    def promise_make(body: NewPromise):
        if body.who not in ("you", "her") or not body.text.strip():
            raise HTTPException(400, "who is 'you' or 'her', and say what")
        promises().make(body.who, body.text, when_words=body.when)
        return promises().status()

    @app.post("/api/promises/{pid}")
    def promise_settle(pid: int, body: PromiseChange):
        if promises().settle(pid, body.status) is None:
            raise HTTPException(400, "status is kept, broken, dropped or open")
        return promises().status()

    # ----- the bedtime story serial (stories.py): her voice, made on first play -----
    @app.get("/api/stories/{sid}.wav")
    async def story_audio(sid: int):
        from fastapi.responses import FileResponse
        from starlette.concurrency import run_in_threadpool

        s = getattr(ctx, "stories", None)
        c = s.get_one(sid) if s is not None else None
        if c is None:
            raise HTTPException(404, "no such chapter")
        path = s.audio_file(sid)
        if not path.exists():
            if voice_wav is None:
                raise HTTPException(503, "no voice")
            wav = await run_in_threadpool(voice_wav, f"Chapter {c['n']}: {c['title']}. {c['text']}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(wav)
        return FileResponse(path, media_type="audio/wav")

    # ----- wind-down at midnight (winddown.py): the phone asks for tomorrow's alarm + her goodnight -----
    @app.get("/api/winddown")
    def winddown(wake: str = ""):
        """`wake`: the usual wake time set on the phone (HH:MM), if any."""
        import re as _re

        w = getattr(ctx, "winddown", None)
        if w is None:
            raise HTTPException(503, "wind-down is off (persona.yaml friend.winddown) or memory is off")
        return w.plan(usual=wake if _re.fullmatch(r"\d{2}:\d{2}", wake) else None)

    # ----- home or out (place.py): the phone joined / left the home Wi-Fi -----
    @app.post("/api/phone/place")
    def phone_place(body: PlaceEvent):
        p = getattr(ctx, "place", None)
        if p is None:
            raise HTTPException(503, "home arrival is off (persona.yaml friend.place) or memory is off")
        if body.event not in ("arrived", "left"):
            raise HTTPException(400, "event is arrived or left")
        what = p.report(body.event, body.at_ms / 1000 if body.at_ms else None)
        return {"noticed": what, **p.status()}

    # ----- the scrapbook (scrapbook.py) -----
    @app.get("/api/scrapbook/{pid}.jpg")
    def scrapbook_photo(pid: int):
        from pathlib import Path

        from fastapi.responses import FileResponse

        s = getattr(ctx, "scrapbook", None)
        p = s.get_one(pid) if s is not None else None
        if p is None or not Path(p["file"]).exists():
            raise HTTPException(404, "no such photo")
        return FileResponse(p["file"], media_type="image/jpeg")

    @app.delete("/api/scrapbook/{pid}")
    def scrapbook_delete(pid: int):
        s = getattr(ctx, "scrapbook", None)
        if s is None or not s.delete(pid):
            raise HTTPException(404, "no such photo")
        changed("scrapbook", action="deleted")
        return s.status()

    # ----- the shared bucket list (bucket.py) -----
    def bucket():
        b = getattr(ctx, "bucket", None)
        if b is None:
            raise HTTPException(503, "the bucket list is off (persona.yaml friend.bucket) or memory is off")
        return b

    @app.post("/api/bucket")
    def bucket_add(body: NewBucket):
        try:
            bucket().add(body.text)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        changed("bucket", action="added")
        return bucket().status()

    @app.post("/api/bucket/{bid}")
    def bucket_done(bid: int, body: PlanChange):
        b = bucket()
        if (b.mark_done(bid) if body.done else b.undo(bid)) is None:
            raise HTTPException(404, "no such item")
        changed("bucket", action="done" if body.done else "undone")
        return b.status()

    @app.delete("/api/bucket/{bid}")
    def bucket_remove(bid: int):
        if bucket().remove(bid) is None:
            raise HTTPException(404, "no such item")
        return bucket().status()

    # ----- the grocery list (groceries.py) -----
    def groceries():
        g = getattr(ctx, "groceries", None)
        if g is None:
            raise HTTPException(503, "the grocery list is off (persona.yaml friend.groceries) or memory is off")
        return g

    @app.post("/api/groceries")
    def groceries_add(body: NewBucket):
        try:
            groceries().add(body.text)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        changed("groceries", action="added")
        return groceries().status()

    @app.post("/api/groceries/clear")
    def groceries_clear(body: GroceryClear):
        groceries().clear("all" if body.which == "all" else "done")
        changed("groceries", action="cleared")
        return groceries().status()

    @app.post("/api/groceries/skip")
    def groceries_skip(body: NewBucket):
        """One of her ideas isn't needed: it stays away for two weeks."""
        groceries().skip([body.text])
        return groceries().status()

    @app.post("/api/groceries/used")
    def groceries_used(body: NewBucket):
        """Fresh food that's finished / thrown out / still fine: no more "it's going off" for it."""
        groceries().used_up(body.text)
        return groceries().status()

    @app.post("/api/groceries/{gid}")
    def groceries_check(gid: int, body: PlanChange):
        if groceries().check(gid, body.done) is None:
            raise HTTPException(404, "no such item")
        changed("groceries", action="done" if body.done else "undone")
        return groceries().status()

    @app.delete("/api/groceries/{gid}")
    def groceries_remove(gid: int):
        if groceries().remove(gid) is None:
            raise HTTPException(404, "no such item")
        return groceries().status()

    # ----- Japanese flashcards from the phone (japanese.py) -----
    @app.post("/api/japanese/review")
    def japanese_review(body: Reviews):
        j = getattr(ctx, "japanese", None)
        if j is None:
            raise HTTPException(503, "Japanese practice is off (persona.yaml friend.japanese) or memory is off")
        j.review([r.model_dump() for r in body.results])
        return j.status()

    # ----- cooking together (cooking.py): the phone's Back / Next / Done -----
    @app.post("/api/cooking/{action}")
    def cooking_action(action: str):
        c = getattr(ctx, "cooking", None)
        if c is None:
            raise HTTPException(503, "cooking together is off (persona.yaml friend.cooking) or memory is off")
        if action not in ("next", "back", "repeat", "stop"):
            raise HTTPException(404, "next, back, repeat or stop")
        said = c.stop() and "Okay, I've put the recipe away." if action == "stop" else c.step(action)
        return {**c.status(), "said": said}

    # ----- the recipe box (recipes.py): stars, cook it again, take it out -----
    def cook():
        c = getattr(ctx, "cooking", None)
        if c is None:
            raise HTTPException(503, "cooking together is off (persona.yaml friend.cooking) or memory is off")
        return c

    @app.post("/api/recipes/{rid}/stars")
    def recipe_stars(rid: int, body: Stars):
        if cook().box.rate(rid, body.stars) is None:
            raise HTTPException(404, "no such recipe")
        return cook().status()

    @app.post("/api/recipes/{rid}/cook")
    def recipe_cook(rid: int):
        if cook().box.get_one(rid) is None:
            raise HTTPException(404, "no such recipe")
        cook().start("", recipe_id=rid)
        changed("cooking", action="started")
        return cook().status()

    @app.delete("/api/recipes/{rid}")
    def recipe_remove(rid: int):
        if cook().box.remove(rid) is None:
            raise HTTPException(404, "no such recipe")
        return cook().status()

    # ----- photo a day (dailyphoto.py) -----
    @app.post("/api/dailyphoto/{action}")
    def dailyphoto_action(action: str):
        d = getattr(ctx, "dailyphoto", None)
        if d is None:
            raise HTTPException(503, "photo a day is off (persona.yaml friend.dailyphoto) or memory is off")
        if action == "skip":
            d.skip()
        elif action == "reroll":
            d.reroll()
        else:
            raise HTTPException(404, "skip or reroll")
        return d.status()

    # ----- the watchlist (watching.py) -----
    def watching():
        w = getattr(ctx, "watching", None)
        if w is None:
            raise HTTPException(503, "watching together is off (persona.yaml friend.watching) or memory is off")
        return w

    @app.post("/api/watchlist")
    def watchlist_add(body: NewBucket):
        try:
            watching().add_watch(body.text)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        changed("watching", action="added")
        return watching().status()

    @app.delete("/api/watchlist/{wid}")
    def watchlist_remove(wid: int):
        if not watching().remove_watch(wid):
            raise HTTPException(404, "no such title")
        return watching().status()

    @app.post("/api/movies/{mid}/stars")
    def movie_stars(mid: int, body: Stars):
        if watching().rate_id(mid, body.stars) is None:
            raise HTTPException(404, "no such movie")
        return watching().status()

    @app.delete("/api/movies/{mid}")
    def movie_remove(mid: int):
        if not watching().remove_logged(mid):
            raise HTTPException(404, "no such movie")
        return watching().status()

    # ----- our playlist (playlist.py) -----
    @app.delete("/api/playlist/{pid}")
    def playlist_remove(pid: int):
        p = getattr(ctx, "playlist", None)
        if p is None:
            raise HTTPException(503, "the playlist is off (persona.yaml friend.playlist) or memory is off")
        if not p.remove(pid):
            raise HTTPException(404, "no such song")
        return p.status()

    # ----- the week's dinners (meals.py) -----
    def meals():
        m = getattr(ctx, "meals", None)
        if m is None:
            raise HTTPException(503, "meal planning is off (persona.yaml friend.meals) or memory is off")
        return m

    @app.post("/api/meals/plan")
    def meals_plan(body: MealCount):
        meals().plan(body.count)
        return meals().status()

    @app.post("/api/meals/groceries")
    def meals_groceries():
        meals().to_groceries()
        return meals().status()

    @app.post("/api/meals/{mid}/swap")
    def meals_swap(mid: int):
        r = next((r for r in meals().week() if r["id"] == mid), None)
        if r is None:
            raise HTTPException(404, "no such dinner")
        import datetime as _dt

        meals().swap(_dt.date.fromisoformat(r["day"]))
        return meals().status()

    @app.delete("/api/meals/{mid}")
    def meals_remove(mid: int):
        if not meals().remove(mid):
            raise HTTPException(404, "no such dinner")
        return meals().status()

    # ----- weekend plans (weekend.py) -----
    def weekend():
        w = getattr(ctx, "weekend", None)
        if w is None:
            raise HTTPException(503, "weekend plans are off (persona.yaml friend.weekend) or memory is off")
        return w

    @app.post("/api/weekend")
    def weekend_add(body: NewPlan):
        try:
            weekend().add(body.text, body.day, body.at)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        changed("weekend", action="added")
        return weekend().status()

    @app.post("/api/weekend/{pid}")
    def weekend_done(pid: int, body: PlanChange):
        if weekend().set_done(pid, int(body.done)) is None:
            raise HTTPException(404, "no such plan")
        return weekend().status()

    @app.delete("/api/weekend/{pid}")
    def weekend_remove(pid: int):
        if weekend().remove(pid) is None:
            raise HTTPException(404, "no such plan")
        changed("weekend", action="removed")
        return weekend().status()

    # ----- her morning voice notes (voicenotes.py) -----
    @app.get("/api/voicenotes/{nid}.wav")
    def voicenote_audio(nid: int):
        from pathlib import Path

        from fastapi.responses import FileResponse

        v = getattr(ctx, "voicenotes", None)
        note = v.get(nid) if v is not None else None
        if note is None or not Path(note["file"]).exists():
            raise HTTPException(404, "no such voice note")
        return FileResponse(note["file"], media_type="audio/wav")

    # ----- a call with her (the phone's Call screen; call.py) -----
    @app.post("/api/call/{action}")
    async def call_turn(action: str, request: Request):
        """start / turn (WAV in: what they said) / end. A turn answers with what she heard, her reply,
        her face and her voice (base64 WAV) in one go, so the phone can play it straight away."""
        import base64

        from starlette.concurrency import run_in_threadpool

        from . import remote
        from .call import ENDS, Call
        from .tags import parse

        call = getattr(ctx, "call", None)
        if call is None:
            call = ctx.call = Call()
        if action == "end":
            call.end()
            return {"ok": True}
        if action == "start":
            call.start()
            line = call.opener(getattr(getattr(ctx, "persona", None), "name", "Sanae"))
            agent = getattr(ctx, "agent", None)
            if agent is not None:
                agent.add_said(line, "They called you from their phone; you picked up")
            said = parse(line)
            wav = await run_in_threadpool(voice_wav, said.text) if voice_wav else b""
            return {"reply": said.text, "emotion": said.emotion or "", "audio": base64.b64encode(wav).decode(), "end": False}
        if action != "turn":
            raise HTTPException(404, "start, turn or end")
        body = await request.body()
        if not body or len(body) > 20 * 2**20:
            raise HTTPException(400, "send a WAV recording")
        try:
            audio = remote.decode_wav(body)
        except Exception as exc:
            raise HTTPException(400, f"couldn't read the audio: {exc}")
        from .listen import strip_wake_word

        text = await run_in_threadpool(lambda: stt().whisper(audio))
        text = strip_wake_word(text) if text else ""
        if not text or text.lower().strip(" .!?,") in ("", "you", "uh", "um", "hmm", "thank you."):
            return {"heard": "", "reply": "", "audio": "", "end": False}
        call.touch()
        reply = await run_in_threadpool(rt.run_command, text, "call")
        t = getattr(getattr(ctx, "agent", None), "last_tags", None)
        wav = await run_in_threadpool(voice_wav, reply) if voice_wav and reply else b""
        end = bool(ENDS.search(text))
        if end:
            call.end()
        return {"heard": text, "reply": reply, "emotion": t.emotion if t is not None and t.emotion else "",
                "audio": base64.b64encode(wav).decode(), "end": end}
