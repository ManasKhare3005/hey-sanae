"""Dashboard backend: REST API + WebSocket event stream, served from a background thread.

Bound to 127.0.0.1 only. The phone app reaches it through `tailscale serve` (see
remote.py): requests from this laptop are trusted, anything proxied needs the phone token.
The React dashboard (dashboard/dist) is served at "/".
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import ROOT
from .events import ApprovalBroker, EventBus
from . import remote, services

log = logging.getLogger(__name__)
DIST = ROOT / "dashboard" / "dist"


@dataclass
class Runtime:
    """Everything the API needs from the running assistant."""
    ctx: Any
    bus: EventBus
    approvals: ApprovalBroker
    run_command: Callable[..., str]             # (text, source=) -> reply (serialised with voice)
    info: dict = field(default_factory=dict)    # static facts: name, wake phrase, models...
    controls: Any = None                        # events.Controls (voice mode only)
    token: str = ""                             # phone token; "" = only this laptop may connect


class Text(BaseModel):
    text: str


class NewReminder(BaseModel):
    text: str
    when: str


def todo_json(t) -> dict:
    return {"uid": t.uid, "text": t.text, "done": t.done, "created": t.created}


class NewEvent(BaseModel):
    title: str
    when: str
    minutes: int = 60
    location: str = ""


class SyncBody(BaseModel):
    reminders: list[dict] = []     # the phone's changes since its last sync (see sync.py)
    events: list[dict] = []
    todos: list[dict] = []
    routine: list[dict] = []


class HealthBody(BaseModel):
    days: list[dict] = []          # {day, sleep_min, sleep_start, sleep_end, steps, resting_hr, hr, hr_at}


class NewTodo(BaseModel):
    text: str


class TodoChange(BaseModel):
    done: bool


class NewChore(BaseModel):
    text: str
    freq: str          # "daily", "weekdays", "weekly:<0-6>", "monthly:<1-31>", or words ("every Sunday")


def chore_json(c, day) -> dict:
    from .chores import due_on, label

    return {"uid": c.uid, "text": c.text, "freq": c.freq, "label": label(c.freq), "due_today": due_on(c.freq, day),
            "done": c.done_on(day), "created": c.created}


class Answer(BaseModel):
    approved: bool


class NotesStart(BaseModel):
    kind: str = "lecture"
    title: str = ""


class DocsSummarize(BaseModel):
    paths: list[str] = []          # exact files; empty = every course file (or those matching course)
    course: str = ""
    redo: bool = False
    combine: bool = False          # also one combined summary of all the chosen files


class DevRequest(BaseModel):
    text: str
    project: str = ""        # a project name; empty = Sanae herself


class Speak(BaseModel):
    text: str


class Confirm(BaseModel):
    confirm: str = ""


class PhoneResult(BaseModel):
    id: int
    ok: bool = True
    message: str = ""


class _Cached:
    """Slow status probes (nvidia-smi, SearXNG, Ollama) cached for a few seconds."""

    def __init__(self, fn: Callable[[], Any], ttl: float):
        self.fn, self.ttl, self.value, self.at = fn, ttl, None, 0.0
        self.lock = threading.Lock()

    def get(self):
        with self.lock:
            if time.monotonic() - self.at > self.ttl:
                try:
                    self.value = self.fn()
                except Exception as exc:
                    self.value = {"error": str(exc)[:120]}
                self.at = time.monotonic()
            return self.value


def _gpu():
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
                          "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
    used, total, util = (float(x) for x in out.split(",")[:3])
    return {"vram_used_mb": used, "vram_total_mb": total, "util": util}


def create_app(rt: Runtime) -> FastAPI:
    app = FastAPI(title="Sanae", docs_url="/api/docs", openapi_url="/api/openapi.json")
    cfg = rt.ctx.cfg
    host = cfg.llm.host.rstrip("/")
    searx = (cfg.get("web", {}) or {}).get("searxng_url", "")

    def ollama():
        models = requests.get(f"{host}/api/ps", timeout=2).json().get("models", [])
        return [{"name": m["name"], "vram_mb": round(m.get("size_vram", 0) / 2**20),
                 "size_mb": round(m.get("size", 0) / 2**20)} for m in models]

    def searxng_up():
        if not searx:
            return False
        return requests.get(f"{searx}/search", params={"q": "ping", "format": "json"}, timeout=2).ok

    probes = {"gpu": _Cached(_gpu, 5), "models": _Cached(ollama, 5), "searxng": _Cached(searxng_up, 30)}
    speech = {"tts": None, "lock": threading.Lock()}

    def local(request) -> bool:
        return remote.is_local(request.client.host if request.client else None, request.headers)

    def allowed(request) -> bool:
        return local(request) or bool(rt.token) and remote.token_ok(rt.token, request.headers,
                                                                     request.query_params)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # The dashboard's static files hold nothing private; every API call does
        if request.url.path.startswith("/api") and not allowed(request):
            return JSONResponse({"detail": "pair this device first (missing or wrong token)"}, 401)
        return await call_next(request)

    def source(request) -> str:
        if local(request):
            return "dashboard"
        # the watch talks through the phone app, which marks its requests
        return "watch" if request.headers.get("x-sanae-device", "").lower() == "watch" else "phone"

    def with_mood(res: dict) -> dict:
        """Her face for the reply (the watch shows it); the tags were taken off the text."""
        t = getattr(getattr(rt.ctx, "agent", None), "last_tags", None)
        return {**res, "emotion": t.emotion} if t is not None and t.emotion else res

    def local_only(request):
        if not local(request):
            raise HTTPException(403, "only from the laptop itself")

    # ----- phone: pairing, voice in, voice out -----
    @app.get("/api/ping")
    def ping(request: Request):
        return {"ok": True, "name": rt.info.get("name", "Sanae"), "mode": rt.info.get("mode"),
                "local": local(request)}

    @app.get("/api/pair")
    def pair(request: Request):
        local_only(request)                  # never hand the token to a remote caller
        phone = cfg.get("phone", {}) or {}
        url = (phone.get("public_url") or remote.tailscale_url() or "").rstrip("/")
        link = remote.pairing_link(url, rt.token) if url and rt.token else ""
        return {"enabled": bool(rt.token), "url": url, "token": rt.token, "link": link,
                "qr_svg": remote.qr_svg(link) if link else "", "tailscale": bool(remote.tailscale_url())}

    def stt():
        ctx = rt.ctx
        if ctx.stt is None:                  # text mode: load Whisper on first use
            from .stt import SpeechToText

            ctx.stt = SpeechToText(cfg.stt.model, cfg.stt.device, cfg.stt.compute_type,
                                   prompt=cfg.stt.get("prompt"), cpu_threads=cfg.stt.get("cpu_threads", 0))
        return ctx.stt

    @app.post("/api/voice")
    async def voice(request: Request):
        """Phone push-to-talk: WAV body (16-bit PCM) -> transcript -> agent -> reply text."""
        from starlette.concurrency import run_in_threadpool

        from .listen import strip_wake_word

        body = await request.body()
        if not body or len(body) > 20 * 2**20:
            raise HTTPException(400, "send a WAV recording (up to 20 MB)")
        try:
            audio = remote.decode_wav(body)
        except Exception as exc:
            raise HTTPException(400, f"couldn't read the audio: {exc}")
        text = await run_in_threadpool(lambda: stt().whisper(audio))
        text = strip_wake_word(text) if text else ""
        if not text or text.lower().strip(" .!?,") in ("thank you", "thanks", "you", "bye", "uh", "um"):
            return {"heard": "", "reply": ""}
        reply = await run_in_threadpool(rt.run_command, text, source(request))
        return with_mood({"heard": text, "reply": reply})

    def voice_wav(text: str) -> bytes:
        """Her voice as WAV bytes (Piper, same voice as the laptop); b"" if there's nothing to say."""
        from .tts import clean_for_speech, make_voice

        text = clean_for_speech(text)[:1500]
        if not text:
            return b""
        with speech["lock"]:
            if speech["tts"] is None:
                speech["tts"] = make_voice(cfg.tts)              # same voice as the laptop (Ava or Piper)
                if speech["tts"] is None:
                    raise HTTPException(503, "no voice available")
            audio, sr = speech["tts"].synthesize(text)
        return remote.encode_wav(audio, sr)

    @app.post("/api/speak")
    def speak(body: Speak):
        """Sanae's voice for the phone: text -> WAV."""
        wav = voice_wav(body.text)
        if not wav:
            raise HTTPException(400, "nothing to say")
        return Response(wav, media_type="audio/wav")

    # ----- state & events -----
    @app.get("/api/state")
    def state():
        ctx = rt.ctx
        reminders = ctx.reminders.pending() if ctx.reminders else []
        return {
            **rt.info,
            "stage": rt.bus.state.get("stage", {}),
            "heartbeat": rt.bus.state.get("heartbeat", {}),
            "approvals": rt.approvals.pending(),
            "next_reminder": ({"id": reminders[0].id, "text": reminders[0].text, "due": reminders[0].due.isoformat()}
                              if reminders else None),
            "services": {
                "models": probes["models"].get(),
                "gpu": probes["gpu"].get(),
                "searxng": probes["searxng"].get(),
                "down": {k: v["why"] for k, v in services.snapshot().items() if not v["up"]},
                "browser": bool(ctx.browser and ctx.browser.running),
                "memory": ctx.memory is not None,
            },
        }

    @app.get("/api/events/recent")
    def recent():
        return list(rt.bus.recent)

    @app.websocket("/api/ws")
    async def ws(socket: WebSocket):
        if not allowed(socket):
            await socket.close(code=4401)
            return
        await socket.accept()
        q = rt.bus.subscribe(asyncio.get_running_loop())
        phone = getattr(rt.ctx, "phone", None) if not local(socket) else None
        if phone is not None:
            phone.connected(+1)
        try:
            await socket.send_json({"kind": "hello", "data": {"recent": list(rt.bus.recent)[-80:],
                                                              "state": rt.bus.state}})
            while True:
                await socket.send_json(await q.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            rt.bus.unsubscribe(q)
            if phone is not None:
                phone.connected(-1)

    # ----- command accuracy test results (evals.py) -----
    @app.get("/api/evals")
    def evals_results():
        from . import evals

        return {"runs": evals.runs(), "latest": evals.latest()}

    # ----- privacy page: what Sanae keeps, export, delete (laptop only) -----
    @app.get("/api/privacy")
    def privacy(request: Request):
        local_only(request)
        from .privacy import Privacy

        return Privacy(rt.ctx).categories()

    @app.get("/api/privacy/export")
    def privacy_export(request: Request):
        local_only(request)
        from .privacy import Privacy

        name = f"sanae-data-{time.strftime('%Y-%m-%d')}.zip"
        return Response(Privacy(rt.ctx).export(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/api/privacy/delete/{category}")
    def privacy_delete(category: str, body: Confirm, request: Request):
        local_only(request)
        from .privacy import Privacy

        if body.confirm != category:                 # the page sends the category name again to confirm
            raise HTTPException(400, "confirm by sending the category name")
        try:
            message = Privacy(rt.ctx).delete(category)
        except KeyError:
            raise HTTPException(404, f"unknown category {category}")
        rt.bus.publish("privacy", {"deleted": category})
        return {"ok": True, "message": message}

    # ----- the phone carrying out Sanae's actions (phone.py) -----
    def bridge():
        phone = getattr(rt.ctx, "phone", None)
        if phone is None:
            raise HTTPException(503, "phone actions are disabled")
        return phone

    @app.post("/api/phone/result")
    def phone_result(body: PhoneResult):
        if not bridge().resolve(body.id, {"ok": body.ok, "message": body.message}):
            raise HTTPException(404, "no such pending phone action (it may have timed out)")
        return {"ok": True}

    @app.post("/api/phone/state")
    async def phone_state(request: Request):
        state = await request.json()
        apps = [a for a in state.get("apps", []) if isinstance(a, dict)][:600]
        bridge().set_state({**state, "apps": apps})
        return {"ok": True, "apps": len(apps)}

    # ----- commands & approvals -----
    @app.post("/api/command")
    def command(body: Text, request: Request):   # runs in FastAPI's thread pool
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "empty command")
        return with_mood({"reply": rt.run_command(text, source(request))})

    @app.post("/api/photo/{action}")
    def photo_ready(action: str):
        """The phone opened the camera / share sheet ("ready": swap the vision model in now) or
        dropped the photo ("cancel": swap the chat model back)."""
        vision = getattr(rt.ctx, "vision", None)
        if action not in ("ready", "cancel"):
            raise HTTPException(404, "ready or cancel")
        if vision is not None:
            vision.warm() if action == "ready" else threading.Thread(target=vision.cool, daemon=True).start()
        return {"ok": vision is not None}

    @app.post("/api/photo")
    async def photo(request: Request, q: str = "", keep: bool = False):
        """A photo from the phone (raw image body; ?q=what plant is this?) -> Sanae's reply.
        The photo is only kept in memory (vision.py) and never saved, unless `keep` (the phone's
        Keep toggle): then it goes in your scrapbook (scrapbook.py)."""
        from starlette.concurrency import run_in_threadpool

        from .vision import MAX_BYTES

        body = await request.body()
        if not body or len(body) > MAX_BYTES:
            raise HTTPException(400, "send a photo (up to 15 MB)")
        question = " ".join(q.split())[:500]
        try:
            reply = await run_in_threadpool(lambda: rt.run_command(question, source(request), photo=body))
        except Exception:
            log.exception("photo request failed")
            reply = "Sorry, something went wrong while I was looking at it. Try sending it again?"
        del body
        kept = None
        book = getattr(rt.ctx, "scrapbook", None)
        if keep and book is not None:
            kept = await run_in_threadpool(book.keep)
        return {"reply": reply, "kept": kept["id"] if kept else None}

    @app.post("/api/approvals/{approval_id}")
    def approve(approval_id: int, body: Answer, request: Request):
        if not rt.approvals.answer(approval_id, body.approved, source(request)):
            raise HTTPException(404, "no such pending approval")
        return {"ok": True}

    # ----- remote control (desktop overlay, later the phone) -----
    @app.post("/api/control/{action}")
    def control(action: str):
        c = rt.controls
        if c is None:
            raise HTTPException(409, "remote control needs voice mode")
        if action == "listen":
            c.paused.clear()
            c.listen_now.set()
        elif action == "pause":
            c.paused.set()
        elif action == "resume":
            c.paused.clear()
        elif action == "quit":
            c.quit.set()
        else:
            raise HTTPException(404, f"unknown action {action}")
        rt.bus.publish("control", {"action": action})
        return {"ok": True, "paused": c.paused.is_set()}

    @app.get("/api/today")
    def today():
        from .digest import gather

        plan = gather(rt.ctx, mail=False)              # the page shows no mail; checking Gmail took 12-16 s
        item = lambda i: {"title": i.title, "course": i.course, "when": i.when, "due": i.start.isoformat(),
                          "link": i.link or i.url}
        return {
            "date": plan.day.isoformat(),
            "due_today": [item(i) for i in plan.due_today],
            "due_soon": [item(i) for i in plan.due_soon],
            "classes": [item(i) for i in plan.classes],
            "reminders": [{"id": r.id, "uid": r.uid, "text": r.text, "due": r.due.isoformat()} for r in plan.reminders],
            "events": [{"uid": e.uid, "title": e.title, "start": e.start.isoformat(), "end": e.end.isoformat(),
                        "all_day": e.all_day, "location": e.location} for e in plan.events],
            "todos": [todo_json(t) for t in rt.ctx.todos.shown()] if rt.ctx.todos is not None else [],
            "routine": [chore_json(c, rt.ctx.chores.today()) for c in rt.ctx.chores.due()] if getattr(rt.ctx, "chores", None) is not None else [],
            "canvas_error": plan.canvas_error,
            "canvas_stale": plan.canvas_stale,
            "paused": bool(rt.controls and rt.controls.paused.is_set()),
        }

    # ----- meeting / lecture notes -----
    def notes_mgr():
        if rt.ctx.notes is None:
            raise HTTPException(503, "notes are disabled")
        return rt.ctx.notes

    @app.get("/api/notes/status")
    def notes_status():
        return notes_mgr().status()

    @app.get("/api/notes/live")
    def notes_live():
        """Live transcript while recording: recent Whisper text + live captions after it."""
        return notes_mgr().live_view()

    @app.post("/api/notes/start")
    def notes_start(body: NotesStart):
        try:
            s = notes_mgr().start(body.kind, body.title)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        return {"ok": True, "title": s.title, "kind": s.kind}

    @app.post("/api/notes/stop")
    def notes_stop():
        try:
            notes_mgr().stop()
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        return {"ok": True}

    @app.get("/api/notes")
    def notes_list():
        return rt.ctx.memory.notes(50) if rt.ctx.memory else []

    @app.get("/api/notes/{note_id}")
    def notes_get(note_id: int):
        from pathlib import Path

        n = rt.ctx.memory.note(note_id) if rt.ctx.memory else None
        if n is None:
            raise HTTPException(404, "no such notes")
        folder = Path(n["folder"])
        read = lambda name: (folder / name).read_text(encoding="utf-8") if (folder / name).exists() else ""
        from .docnotes import TEXT_FILE

        text = read(TEXT_FILE) if n.get("kind") == "document" else read("transcript.md")
        return {**n, "notes_md": read("notes.md"), "transcript_md": text,
                "summary_md": read("summary.md")}

    @app.post("/api/notes/{note_id}/summary")
    def notes_summary(note_id: int, refresh: bool = False):
        """Short study summary (TL;DR, takeaways, to-dos); made by the local model on first ask."""
        from pathlib import Path

        n = rt.ctx.memory.note(note_id) if rt.ctx.memory else None
        if n is None or not (Path(n["folder"]) / "notes.md").exists():
            raise HTTPException(404, "no such notes")
        try:
            text = notes_mgr().summary(Path(n["folder"]), n.get("kind") or "lecture", refresh)
        except Exception as exc:
            raise HTTPException(503, f"couldn't write the summary: {exc}")
        return {"summary_md": text}

    # ----- nightly backup (backup.py) -----
    @app.get("/api/backup")
    def backup_status():
        b = getattr(rt.ctx, "backup", None)
        return b.status() if b is not None else {"enabled": False}

    @app.post("/api/backup")
    def backup_now():
        b = getattr(rt.ctx, "backup", None)
        if b is None:
            raise HTTPException(503, "backups are off (backup.enabled in config.yaml)")
        return b.run()

    # ----- change Sanae from the phone (Claude Code on this laptop) + phone app updates -----
    @app.post("/api/dev/notify")
    def dev_notify(body: dict, request: Request):
        """A note to the phone from work done on this laptop (e.g. Claude Code: "the new features are in")."""
        local_only(request)
        text = str(body.get("text") or "").strip()[:300]
        if not text:
            raise HTTPException(400, "text")
        rt.bus.publish("nudge", {"kind": "dev", "text": text})
        return {"ok": True}

    def dev():
        if getattr(rt.ctx, "dev", None) is None:
            raise HTTPException(503, "changing Sanae from the phone is turned off (dev.enabled in config.yaml)")
        return rt.ctx.dev

    @app.post("/api/dev/request")
    def dev_request(body: DevRequest):
        try:
            proj = None
            if body.project and getattr(rt.ctx, "projects", None) is not None:
                proj = rt.ctx.projects.resolve(body.project)
                if isinstance(proj, str):
                    raise HTTPException(404, proj)
            job = dev().submit(body.text, proj.name, proj.path) if proj is not None else dev().submit(body.text)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc))
        return {"id": job.id, "status": job.status}

    @app.get("/api/dev/jobs")
    def dev_jobs():
        return dev().list()

    @app.post("/api/dev/jobs/{job_id}/{action}")
    def dev_decide(job_id: int, action: str):
        if action not in ("approve", "reject", "push"):
            raise HTTPException(404, "approve, reject or push")
        try:
            job = {"approve": dev().approve, "reject": dev().reject, "push": dev().push}[action](job_id)
        except KeyError:
            raise HTTPException(404, "no such change")
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        return {"id": job.id, "status": job.status}

    @app.get("/api/dev/jobs/{job_id}/diff")
    def dev_diff(job_id: int):
        from .devloop import run as git_run

        try:
            job = dev().get(job_id)
        except KeyError:
            raise HTTPException(404, "no such change")
        if job.status != "ready":
            raise HTTPException(409, f"that change is {job.status}")
        code, out = git_run(["git", "diff", "--stat", "--patch", f"{job.base}...{job.branch}"], job.path, timeout=60)
        if code != 0:
            raise HTTPException(500, out[-300:])
        return {"diff": out[:60000], "cut": len(out) > 60000}

    @app.get("/api/projects")
    def project_list():
        p = getattr(rt.ctx, "projects", None)
        if p is None:
            return []
        cur = p.current()
        return [{"name": x.name, "current": bool(cur and cur.path == x.path)} for x in p.all()]

    @app.get("/api/app/info")
    def app_info():
        from .devloop import apk_info

        return apk_info()

    @app.post("/api/phone/crash")
    async def phone_crash(request: Request):
        """The phone app's crash / freeze reports (CrashLog.kt), kept in logs/phone-crash.log."""
        text = (await request.body())[:400_000].decode("utf-8", "replace")
        if not text.strip():
            raise HTTPException(400, "empty report")
        path = ROOT / "logs" / "phone-crash.log"
        path.parent.mkdir(exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(f"===== received {time.strftime('%Y-%m-%d %H:%M:%S')}\n{text.rstrip()}\n\n")
        log.warning("phone app crash report saved to logs/phone-crash.log")
        return {"ok": True}

    @app.get("/api/app/apk")
    def app_apk():
        from fastapi.responses import FileResponse

        from .devloop import APK

        if not APK.exists():
            raise HTTPException(404, "no phone app build yet")
        return FileResponse(APK, media_type="application/vnd.android.package-archive", filename="sanae.apk")

    # ----- notes from course documents -----
    def docs_mgr():
        if getattr(rt.ctx, "docnotes", None) is None:
            raise HTTPException(503, "course files are disabled")
        return rt.ctx.docnotes

    @app.get("/api/documents")
    def docs_list():
        """Course files, whether each already has notes, and what's being summarized now."""
        d = docs_mgr()
        files = [{"path": str(p), "name": p.name, "course": c, "done": d.is_done(p)} for p, c in d.files()]
        return {"folder": str(d.library.folders[0]), "files": files, "status": d.status()}

    @app.post("/api/documents/summarize")
    def docs_summarize(body: DocsSummarize):
        from pathlib import Path

        d = docs_mgr()
        items = d.match(body.course)
        if body.paths:
            want = {str(Path(p)) for p in body.paths}
            items = [(p, c) for p, c in items if str(p) in want]
        if not items:
            raise HTTPException(404, "no matching course files")
        from .docnotes import combined_title

        title = combined_title(items, body.course) if body.combine and len(items) > 1 else ""
        queued, skipped = d.enqueue(items, redo=body.redo, combine=title)
        return {"queued": [p.name for p in queued], "skipped": [p.name for p in skipped], "combined": title}

    @app.post("/api/documents/upload")
    async def docs_upload(request: Request, name: str, course: str = "", summarize: bool = True):
        """Add a document (raw file body; ?name=lecture3.pdf&course=CS 103) to the course folder,
        then write its notes in the background."""
        from pathlib import Path

        from starlette.concurrency import run_in_threadpool

        from .course import TYPES
        from .notes import safe_name

        d = docs_mgr()
        name = Path(name).name
        ext = Path(name).suffix.lower()
        if ext not in TYPES:
            raise HTTPException(400, f"Sanae can read {', '.join(sorted(TYPES))} files")
        body = await request.body()
        if not body or len(body) > 50 * 2**20:
            raise HTTPException(400, "send the file (up to 50 MB)")
        folder = d.library.folders[0] / safe_name(course) if course.strip() else d.library.folders[0]
        folder.mkdir(parents=True, exist_ok=True)
        stem = safe_name(Path(name).stem)
        target, n = folder / f"{stem}{ext}", 2
        while target.exists():
            target, n = folder / f"{stem} ({n}){ext}", n + 1
        target.write_bytes(body)
        threading.Thread(target=d.library.scan, name="course-scan-upload", daemon=True).start()
        queued = []
        if summarize:
            course_name = d.library._course_of(target, d.library.folders[0])
            queued, _ = await run_in_threadpool(d.enqueue, [(target, course_name)])
        return {"saved": str(target), "name": target.name, "summarizing": bool(queued)}

    @app.post("/api/notes/{note_id}/open")
    def notes_open(note_id: int, request: Request):
        import os

        local_only(request)                            # opens Explorer on the laptop

        n = rt.ctx.memory.note(note_id) if rt.ctx.memory else None
        if n is None:
            raise HTTPException(404, "no such notes")
        os.startfile(n["folder"])                      # opens the folder in Explorer
        return {"ok": True}

    # ----- history -----
    @app.get("/api/turns")
    def turns(limit: int = 50):
        return rt.ctx.memory.recent_turns(limit) if rt.ctx.memory else []

    @app.get("/api/actions")
    def actions(limit: int = 200):
        return rt.ctx.memory.actions(limit) if rt.ctx.memory else []

    # ----- memory -----
    def memory():
        if rt.ctx.memory is None:
            raise HTTPException(503, "memory is disabled")
        return rt.ctx.memory

    @app.get("/api/facts")
    def facts(q: str = ""):
        hits = memory().search_facts(q, k=50, min_score=0.3) if q else memory().facts()
        return [{"id": h.id, "text": h.text, "created": h.ts, "score": round(h.score, 3)} for h in hits]

    @app.post("/api/facts")
    def add_fact(body: Text):
        fid, old = memory().add_fact(body.text)
        rt.bus.publish("memory", {"action": "added", "id": fid, "text": body.text})
        return {"id": fid, "updated": old is not None}

    @app.delete("/api/facts/{fact_id}")
    def delete_fact(fact_id: int):
        if not memory().delete_fact(fact_id):
            raise HTTPException(404, "no such fact")
        rt.bus.publish("memory", {"action": "deleted", "id": fact_id})
        return {"ok": True}

    # ----- about you (friend memory), her mood -----
    def friend():
        f = getattr(rt.ctx, "friend", None)
        if f is None:
            raise HTTPException(503, "friend memory is off")
        return f

    @app.get("/api/about")
    def about():
        f = getattr(rt.ctx, "friend", None)
        mood = getattr(rt.ctx, "mood", None)
        return {
            "enabled": f is not None,
            "facts": [{"id": x.id, "text": x.text, "kind": x.kind, "updated": x.updated, "mentions": x.mentions}
                      for x in (f.facts() if f else [])],
            "threads": [{"id": t.id, "about": t.about, "ask_after": t.ask_after, "status": t.status}
                        for t in (f.threads("open") if f else [])],
            "pending": [{"id": p.id, "text": p.text, "kind": p.kind} for p in (f.pending() if f else [])],
            "mood": ({"resting": mood.mood.resting_emotion, "energy": round(mood.mood.energy, 2),
                      "cheer": round(mood.mood.cheer, 2)} if mood else None),
        }

    @app.post("/api/about/pending/{pending_id}/confirm")
    def confirm_pending(pending_id: int):
        if not friend().confirm(pending_id):
            raise HTTPException(404, "no such note")
        rt.bus.publish("about", {"action": "confirmed", "id": pending_id})
        return {"ok": True}

    @app.delete("/api/about/pending/{pending_id}")
    def reject_pending(pending_id: int):
        if not friend().reject(pending_id):
            raise HTTPException(404, "no such note")
        rt.bus.publish("about", {"action": "rejected", "id": pending_id})
        return {"ok": True}

    @app.put("/api/about/{fact_id}")
    def edit_about(fact_id: int, body: Text):
        if not friend().edit(fact_id, body.text):
            raise HTTPException(404, "no such entry")
        rt.bus.publish("about", {"action": "edited", "id": fact_id})
        return {"ok": True}

    @app.delete("/api/about/{fact_id}")
    def delete_about(fact_id: int):
        if not friend().delete(fact_id):
            raise HTTPException(404, "no such entry")
        rt.bus.publish("about", {"action": "deleted", "id": fact_id})
        return {"ok": True}

    @app.delete("/api/about/threads/{thread_id}")
    def drop_thread(thread_id: int):
        if not friend().set_thread(thread_id, "dropped"):
            raise HTTPException(404, "no such thread")
        rt.bus.publish("about", {"action": "thread_dropped", "id": thread_id})
        return {"ok": True}

    # ----- her diary, shared moments, how she talks to you -----
    def diary():
        d = getattr(rt.ctx, "diary", None)
        if d is None:
            raise HTTPException(503, "the diary is off")
        return d

    @app.get("/api/diary")
    def get_diary():
        d = getattr(rt.ctx, "diary", None)
        taste = getattr(rt.ctx, "taste", None)
        return {
            "enabled": d is not None,
            "entries": [{"day": e.day, "text": e.text, "tone": e.tone, "mood": e.mood, "updated": e.updated}
                        for e in (d.entries() if d else [])],
            "moments": [{"id": m.id, "kind": m.kind, "text": m.text, "date": m.date, "day": m.day, "uses": m.uses}
                        for m in (d.moments() if d else [])],
            "taste": taste.dials if taste is not None else None,
        }

    @app.put("/api/diary/{day}")
    def edit_diary(day: str, body: Text):
        d = diary()
        e = d.get(day)
        if e is None:
            raise HTTPException(404, "no entry for that day")
        if body.text.strip():
            d.put(day, body.text, e.tone, e.mood)
        else:
            d.delete(day)
        rt.bus.publish("diary", {"action": "edited", "day": day})
        return {"ok": True}

    @app.delete("/api/diary/{day}")
    def delete_diary(day: str):
        if not diary().delete(day):
            raise HTTPException(404, "no entry for that day")
        rt.bus.publish("diary", {"action": "deleted", "day": day})
        return {"ok": True}

    @app.delete("/api/moments/{moment_id}")
    def delete_moment(moment_id: int):
        if not diary().delete_moment(moment_id):
            raise HTTPException(404, "no such moment")
        rt.bus.publish("diary", {"action": "moment_deleted", "id": moment_id})
        return {"ok": True}

    @app.delete("/api/taste")
    def reset_taste():
        taste = getattr(rt.ctx, "taste", None)
        if taste is None:
            raise HTTPException(503, "taste learning is off")
        taste.reset()
        return {"ok": True, "taste": taste.dials}

    # ----- reminders -----
    @app.get("/api/reminders")
    def reminders():
        if rt.ctx.reminders is None:
            return []
        return [{"id": r.id, "uid": r.uid, "text": r.text, "due": r.due.isoformat(), "repeat": r.repeat,
                 "spoken": r.spoken()} for r in rt.ctx.reminders.pending()]

    @app.post("/api/reminders")
    def add_reminder(body: NewReminder):
        from .reminders import parse_repeating, parse_when

        found = parse_repeating(body.when)
        due, rule = found if found else (parse_when(body.when), "")
        if due is None:
            raise HTTPException(400, f"couldn't understand the time '{body.when}'")
        r = rt.ctx.reminders.add(body.text, due, repeat=rule)
        rt.bus.publish("reminder", {"action": "added", "id": r.id, "uid": r.uid, "text": r.text, "due": due.isoformat(),
                                    "repeat": rule})
        return {"id": r.id, "uid": r.uid, "due": due.isoformat(), "repeat": rule, "spoken": r.spoken()}

    @app.delete("/api/reminders/{reminder_id}")
    def cancel_reminder(reminder_id: int):
        rt.ctx.reminders.set_status(reminder_id, "cancelled")
        rt.bus.publish("reminder", {"action": "cancelled", "id": reminder_id})
        return {"ok": True}

    # ----- events (Sanae's calendar; the phone shows them in its "Sanae" calendar) -----
    def events_store():
        if rt.ctx.events is None:
            raise HTTPException(503, "events need memory turned on")
        return rt.ctx.events

    def event_json(e):
        return {"uid": e.uid, "title": e.title, "start": e.start.isoformat(), "end": e.end.isoformat(),
                "all_day": e.all_day, "location": e.location}

    @app.get("/api/events")
    def events_list(days: int = 14):
        return [event_json(e) for e in events_store().upcoming(days)]

    @app.post("/api/events")
    def events_add(body: NewEvent):
        from .reminders import has_time, parse_when

        start = parse_when(body.when)
        if start is None:
            raise HTTPException(400, f"couldn't understand the time '{body.when}'")
        e = events_store().add(body.title, start, body.minutes, body.location, all_day=not has_time(body.when))
        rt.bus.publish("event", {"action": "added", **event_json(e)})
        return {**event_json(e), "spoken": e.spoken()}

    @app.delete("/api/events/{uid}")
    def events_cancel(uid: str):
        if not events_store().cancel(uid):
            raise HTTPException(404, "no such event")
        rt.bus.publish("event", {"action": "cancelled", "uid": uid})
        return {"ok": True}

    # ----- health from the watch (the phone sends it; off until turned on there) -----
    @app.post("/api/health")
    def health_upload(body: HealthBody):
        if rt.ctx.health is None:
            raise HTTPException(503, "health is turned off in config.yaml")
        saved = [d.day for d in (rt.ctx.health.save(x) for x in body.days[:14]) if d]
        return {"saved": saved}

    @app.get("/api/health")
    def health_list(days: int = 7):
        if rt.ctx.health is None:
            return []
        return [vars(d) for d in rt.ctx.health.recent(max(1, min(days, 60)))]

    # ----- the phone's "Us" tab: the daily list together, the exchange diary... (us_api.py) -----
    from . import us_api

    us_api.register(app, rt, stt, voice_wav)

    # ----- todo list (the phone and its widget keep a copy) -----
    def todos_store():
        if rt.ctx.todos is None:
            raise HTTPException(503, "the todo list needs memory turned on")
        return rt.ctx.todos

    @app.get("/api/todos")
    def todos_list():
        return [todo_json(t) for t in todos_store().shown()]

    @app.post("/api/todos")
    def todos_add(body: NewTodo):
        from .todos import split_items

        added = [todos_store().add(text) for text in split_items(body.text)]
        if not added:
            raise HTTPException(400, "nothing to add")
        rt.bus.publish("todo", {"action": "added", "uids": [t.uid for t in added]})
        return [todo_json(t) for t in added]

    @app.post("/api/todos/{uid}")
    def todos_tick(uid: str, body: TodoChange):
        t = todos_store().set_status(uid, "done" if body.done else "open")
        if t is None:
            raise HTTPException(404, "no such todo")
        rt.bus.publish("todo", {"action": "done" if body.done else "reopened", "uid": uid})
        return todo_json(t)

    @app.delete("/api/todos/{uid}")
    def todos_delete(uid: str):
        if todos_store().set_status(uid, "deleted") is None:
            raise HTTPException(404, "no such todo")
        rt.bus.publish("todo", {"action": "deleted", "uid": uid})
        return {"ok": True}

    @app.post("/api/todos/clear/done")
    def todos_clear_done():
        n = todos_store().clear("done")
        rt.bus.publish("todo", {"action": "cleared", "count": n})
        return {"cleared": n}

    # ----- routine: tasks every day / week / month (chores.py; the phone keeps a copy) -----
    def chores_store():
        if getattr(rt.ctx, "chores", None) is None:
            raise HTTPException(503, "the routine needs memory turned on")
        return rt.ctx.chores

    @app.get("/api/routine")
    def routine_list():
        return [chore_json(c, chores_store().today()) for c in chores_store().active()]

    @app.post("/api/routine")
    def routine_add(body: NewChore):
        from .chores import parse_freq, valid

        text = body.text.strip()
        freq = body.freq.strip() if valid(body.freq.strip()) else parse_freq(body.freq)
        if not text or not freq:
            raise HTTPException(400, "give the task and how often (daily, weekly:<0-6>, monthly:<1-31>)")
        c = chores_store().add(text, freq)
        rt.bus.publish("routine", {"action": "added", "uid": c.uid})
        return chore_json(c, chores_store().today())

    @app.post("/api/routine/{uid}")
    def routine_tick(uid: str, body: TodoChange):
        c = chores_store().tick(uid, body.done)
        if c is None:
            raise HTTPException(404, "no such task")
        rt.bus.publish("routine", {"action": "done" if body.done else "reopened", "uid": uid})
        return chore_json(c, chores_store().today())

    @app.delete("/api/routine/{uid}")
    def routine_delete(uid: str):
        if chores_store().delete(uid) is None:
            raise HTTPException(404, "no such task")
        rt.bus.publish("routine", {"action": "deleted", "uid": uid})
        return {"ok": True}

    # ----- phone sync: reminders and events made on the phone while the laptop was away -----
    @app.post("/api/sync")
    def sync_with_phone(body: SyncBody):
        from .sync import sync

        out = sync(rt.ctx, body.model_dump())
        persona = getattr(rt.ctx, "persona", None)
        if persona is not None:          # her name and notification lines, for the phone app
            out["persona"] = {"name": persona.name, "notify": persona.notify}
        if body.reminders or body.events or body.todos or body.routine:
            rt.bus.publish("sync", {"reminders": len(body.reminders), "events": len(body.events), "todos": len(body.todos),
                                    "routine": len(body.routine)})
        return out

    # ----- lectures / meetings recorded on the phone -----
    def phone_notes():
        if rt.ctx.phone_notes is None:
            raise HTTPException(503, "notes are disabled")
        return rt.ctx.phone_notes

    @app.post("/api/notes/upload")
    async def notes_upload(request: Request, uid: str, kind: str = "lecture", title: str = "", started_ms: int = 0):
        """A recording from the phone (raw audio body). Queued; its notes are written in the background."""
        from starlette.concurrency import run_in_threadpool

        pn = phone_notes()
        body = await request.body()
        try:
            return await run_in_threadpool(pn.receive, uid, [body], kind, title, started_ms)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/notes/upload/{uid}")
    def notes_upload_status(uid: str):
        try:
            st = phone_notes().state(phone_notes().safe_uid(uid))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if st is None:
            raise HTTPException(404, "no such recording")
        return st

    # ----- the React app -----
    if (DIST / "index.html").exists():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="dashboard")
    else:
        @app.get("/", response_class=HTMLResponse)
        def placeholder():
            return ("<h2 style='font-family:sans-serif'>Sanae API is running.</h2>"
                    "<p style='font-family:sans-serif'>Build the dashboard: <code>cd dashboard && npm install "
                    "&& npm run build</code>. API docs: <a href='/api/docs'>/api/docs</a></p>")

    return app


def serve(rt: Runtime, host: str = "127.0.0.1", port: int = 8765):
    """Start the server in a daemon thread. Returns the uvicorn Server (or None on failure)."""
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(create_app(rt), host=host, port=port, log_level="warning",
                                           access_log=False))
    threading.Thread(target=server.run, name="dashboard", daemon=True).start()
    log.info("dashboard at http://%s:%d", host, port)
    return server
