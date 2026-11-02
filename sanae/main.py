"""Sanae entry point: voice loop (default) or typed chat (--text)."""
from __future__ import annotations

import argparse
import logging
import os
import queue
import re
import sys
import threading
from pathlib import Path
import time
from logging.handlers import RotatingFileHandler

from .agent import Agent, parse_yes_no
from .events import current_origin, set_origin
from .speech import SentenceSpeaker
from .toolselect import ToolSelector
from .config import load_config, resolve_path
from .llm import OllamaClient, nvidia_free_mb
from .tools import system as system_tools
from .tools import browser as browser_tools
from .tools import canvas as canvas_tools
from .tools import code as code_tools
from .tools import health as health_tools
from .tools import routine as routine_tools
from .tools import companion as companion_tools
from .tools import fun as fun_tools
from .tools import friend as friend_tools
from .tools import us as us_tools
from .tools import digest as digest_tools
from .tools import notes as notes_tools
from .tools import phone as phone_tools
from .tools import course as course_tools
from .tools import screen as screen_tools
from .tools import mail as mail_tools
from .tools import memory as memory_tools
from .tools import web as web_tools
from .tools.registry import ToolRegistry

log = logging.getLogger("sanae")

CANCEL_PHRASES = ("never mind", "nevermind", "cancel", "forget it", "nothing")
# What speech-to-text tends to "hear" in near-silence or in the tail of Sanae's own voice
PHANTOM_PHRASES = {"thank you", "thanks", "thanks for watching", "you", "bye", "okay", "uh", "um", "hmm"}


def wake_phrase(cfg) -> str:
    phrase = (cfg.get("wake_word", {}) or {}).get("phrase") or f"Hey {cfg.assistant.name}"
    return phrase.split("|")[0].strip()


def is_question(reply: str) -> bool:
    """Does Sanae's reply end by asking the user something?"""
    return reply.rstrip().endswith("?")


def converse(first_text: str, respond, listen_again, follow_up: bool = True,
             on_heard=lambda t: None, on_idle=lambda: None,
             interrupted=lambda: None, listen_new=None, keep_listening=None, accept=lambda: True) -> int:
    """Run one exchange, then keep going while Sanae's reply is a question.

    respond(text) -> reply (after speaking it); listen_again() -> transcript or ''.
    keep_listening() (conversation mode): after any reply, listen for a while longer without the
    wake word -> transcript or ''. accept() -> False drops what keep_listening heard (not the user's
    voice: a video, someone else in the room) and goes back to the wake word. Returns how many
    requests were handled.
    """
    text, handled = first_text, 0
    while True:
        if not text:
            on_idle()
            return handled
        if text.lower().strip(" .!?") in CANCEL_PHRASES:
            respond(None)
            return handled
        on_heard(text)
        reply = respond(text)
        handled += 1
        cut = interrupted()                # the user said "stop" or "Hey Sanae" while Sanae was talking
        if cut == "stop":
            return handled
        if cut == "wake" and listen_new is not None:
            text = listen_new()            # a fresh request, no wake word needed
            continue
        if keep_listening is not None and reply:
            text = keep_listening()
            if text and not accept():
                text = ""
        elif not (follow_up and reply and is_question(reply)):
            return handled
        else:
            text = listen_again()
        if text.lower().strip(" .!?,") in PHANTOM_PHRASES:
            text = ""      # not a real answer: go back to waiting for the wake word


class Context:
    """Shared state that tools can read (config, LLM client, last search results...)."""

    def __init__(self, cfg, llm):
        self.cfg = cfg
        self.llm = llm
        self.last_files: list[str] = []
        self.heard = ""   # whose voice the current request was in (voiceid.judge); "" = typed
        self.tone = None  # how the current request sounded (tone.py): "low" / "high" / None
        self._models_asleep = False
        self.web = None   # WebSearch, set by tools.web
        self.browser = None   # BrowserSession, set by tools.browser
        self.memory = None    # MemoryStore (facts, conversation log, actions)
        self.reminders = None
        self.health = None     # health.Health: sleep / steps / heart rate the phone sends (off until enabled there)
        self.league_history = None   # league.LeagueHistory: recaps of the games she watched
        self.game_mode = None  # gamemode.GameMode: Valorant etc. running -> models unloaded, quiet
        self.services = None   # services.Services: keeps Ollama and SearXNG running
        self.valorant_history = None   # valorant.ValorantHistory: recaps of the matches she kept score of
        self.routines = None   # routines.Routines: "goodnight", "study time", ... from config.yaml
        self.briefing = None   # briefing.Briefing: the morning rundown on the first wake after 5 AM
        self.todos = None      # todos.Todos: the todo list (synced to the phone and its widget)
        self.chores = None     # chores.Chores: the routine (tasks every day / week / month, synced to the phone)
        self.events = None     # agenda.Events: Sanae's calendar (synced to the phone's "Sanae" calendar)
        self.canvas = None     # CanvasFeed, when secrets.yaml has the feed link
        self.notes = None      # NotesManager (meeting / lecture notes)
        self.stt = None        # SpeechToText, shared with notes (voice mode creates it)
        self.confirm = lambda prompt: False   # spoken yes/no, set by build()
        self.bus = None        # events.EventBus, set by build()
        self.phone = None      # phone.PhoneBridge: actions on the user's phone
        self.phone_notes = None  # phone_notes.PhoneRecordings: lectures recorded on the phone, written up here
        self.course = None     # course.CourseLibrary: slides, PDFs and lecture notes to answer from
        self.docnotes = None   # docnotes.DocNotes: study notes written from course files
        self.dev = None        # devloop.DevLoop: changes to Sanae or a project, made by Claude Code on a branch
        self.projects = None   # projects.Projects: the user's git repos, GitHub, what's running
        self.mail = None       # mail.GmailClient: the user's Gmail (app password in secrets.yaml)
        self.persona = None    # persona.Persona (persona.yaml): her name, character, notification lines
        self.dnd = None        # dnd.DoNotDisturb: when she shouldn't talk first
        self.friend = None     # friend.FriendMemory: what she's learned about the user, things to ask about later
        self.mood = None       # mood.MoodKeeper: her mood (resting face, a hint in requests)
        self.window = None     # window.WindowWatch: the window in front (memory only, never stored)
        self.avatar_control = None  # "hide" / "show" / "toggle" the avatar (voice mode with the avatar on)
        self.parts: list = []  # part.Part: goals, wins, care... (friendship.py)
        self.brain = None      # cloudbrain.CloudBrain: Claude for background thinking (redacted)
        self.mind = None       # claudemind.ClaudeMind when Claude answers everything (brain.chat)
        self.goals = None      # goals.Goals: goals she keeps them to
        self.wins = None       # wins.Wins: things they pulled off (said once; recalled when they're down)
        self.care = None       # care.Care: sleep / steps / resting heart rate from the watch; "did you eat?"
        self.surprises = None  # surprises.Surprises: milestones, a haiku after a rough week, a compliment
        self.rituals = None    # rituals.Rituals: highs and lows, Monday kickoff, weekend plans, Sunday planning
        self.life = None       # herlife.HerLife: what she's learning lately, music she got into
        self.thoughts = None   # thoughts.Thoughts: what she kept thinking about after a chat
        self.texts = None      # texts.Texts: messages to the phone while they're away from the laptop
        self.social = None     # social.Social: seeing people, birthdays the day before
        self.pushback = None   # pushback.Pushback: honest "one more and then bed?" when it clashes with tomorrow
        self.together = None   # together.Together: the daily list you do together, the shared room
        self.journal = None    # journal.Journal: the exchange diary you take turns writing in
        self.roommate = None   # roommate.Roommate: workouts, Duolingo, late scrolling, songs on repeat (from the phone)
        self.call = None       # call.Call: a voice call with her from the phone, while it's on
        self.voicenotes = None  # voicenotes.VoiceNotes: a morning voice message from her, made overnight
        self.promises = None   # promises.Promises: pinky promises, both ways
        self.weekly = None     # weekly.Weekly: her story-style recap of your week, Sunday evening
        self.weekend = None    # weekend.Weekend: weekend plans made together, "how was the hike?"
        self.drawings = None   # drawings.Drawings: her sketchbook (real pen-stroke sketches)
        self.cooking = None    # cooking.Cooking: a recipe step by step, timers, "what can I make with this?"
        self.watching = None   # watching.Watching: shows / movies watched on the laptop, quiet while they're on
        self.japanese = None   # japanese.Japanese: learning her words together, quizzes both ways
        self.bucket = None     # bucket.Bucket: the shared bucket list
        self.scrapbook = None  # scrapbook.Scrapbook: photos kept on their say-so, with her captions
        self.stories = None    # stories.Stories: the bedtime story serial
        self.asks = None       # asks.Asks: small things she asks you for (the sky, a song...)
        self.place = None      # place.Place: home or out, from the phone joining the home Wi-Fi
        self.winddown = None   # winddown.WindDown: midnight goodnight, tomorrow's alarm time

    @property
    def models_asleep(self) -> bool:
        return self._models_asleep

    @models_asleep.setter
    def models_asleep(self, value: bool):
        """Models unloaded ("go to sleep") or back. Published so the avatar can doze off (with
        avatar.close_when_asleep it then closes, freeing its memory) and wake up; back awake, a
        closed avatar is started again."""
        changed = bool(value) != self._models_asleep
        self._models_asleep = bool(value)
        if changed and getattr(self, "bus", None) is not None:
            self.bus.publish("gpu", {"asleep": self._models_asleep})
        if changed and not value and self.avatar_control is not None:
            self.avatar_control("launch")


def setup_logging(cfg, verbose: bool):
    path = resolve_path(cfg.logging.file)
    path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")]
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.WARNING)
    handlers.append(console)
    logging.basicConfig(
        level=getattr(logging, str(cfg.logging.level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def build(cfg, confirm, on_event, bus=None, approvals=None):
    vis = cfg.get("vision", {}) or {}
    layers = {cfg.llm.fast_model: cfg.llm.get("fast_model_gpu_layers"), vis.get("model"): vis.get("gpu_layers")}
    llm = OllamaClient(cfg.llm.host, cfg.llm.keep_alive, cfg.llm.temperature,
                       cfg.llm.get("think", False), cfg.llm.request_timeout_s,
                       num_ctx=cfg.llm.get("num_ctx"), num_predict=cfg.llm.get("num_predict"),
                       gpu_layers={m: n for m, n in layers.items() if m and n} or None,
                       stream_deadline_s=float(cfg.llm.get("stream_deadline_s", 120)),
                       vram_free=nvidia_free_mb if cfg.llm.get("tight_free_mb") else None,
                       tight_free_mb=int(cfg.llm.get("tight_free_mb") or 0),
                       tight_num_ctx=int(cfg.llm.get("tight_num_ctx", 2048)))
    local_llm = llm
    from .claudemind import make_mind

    mind = make_mind(local_llm, cfg.get("brain", {}) or {})
    if mind is not None:
        llm = mind                              # Claude answers; the local model for secrets (claudemind.py)
    ctx = Context(cfg, llm)
    ctx.mind = mind
    if vis.get("enabled", True):
        from .vision import Vision

        ctx.vision = Vision(local_llm, vis.get("model", "gemma3:4b"), cfg.llm.fast_model, vis.get("max_side", 896),
                            vis.get("remember_min", 10) * 60)
    ctx.bus = bus                              # tools can publish events (e.g. open a link on the phone)
    if bus is not None and (cfg.get("phone", {}) or {}).get("enabled", True):
        from .phone import PhoneBridge

        ctx.phone = PhoneBridge(bus)            # Sanae acts on the phone through the phone app
    if approvals is not None:
        local_confirm = confirm

        def confirm(prompt: str) -> bool:
            # A phone command is approved on the phone (a tap), never by the laptop's mic
            if current_origin() == "phone":
                return approvals.wait(prompt, (cfg.get("phone", {}) or {}).get("approval_timeout_s", 90))
            return local_confirm(prompt)
    ctx.confirm = confirm
    mem_cfg = cfg.get("memory", {})
    if mem_cfg.get("enabled", True):
        from .memory import MemoryStore
        from .reminders import Reminders

        ctx.memory = MemoryStore(mem_cfg.get("db", "data/sanae.db"))
        ctx.reminders = Reminders(ctx.memory)
        from .agenda import Events

        ctx.events = Events(ctx.memory)
        from .todos import Todos

        ctx.todos = Todos(ctx.memory)
        from .chores import Chores

        ctx.chores = Chores(ctx.memory)
        on_event = _logging_events(ctx.memory, on_event)
    if bus is not None:
        inner = on_event

        def on_event(kind, data, inner=inner):
            bus.publish(kind, data)
            inner(kind, data)
    notes_cfg = cfg.get("notes", {}) or {}
    if notes_cfg.get("enabled", True):
        from .notes import NotesManager

        def transcriber():
            if ctx.stt is None:                        # text mode: load Whisper on first use
                from .stt import SpeechToText

                ctx.stt = SpeechToText(cfg.stt.model, cfg.stt.device, cfg.stt.compute_type,
                                       prompt=cfg.stt.get("prompt"), cpu_threads=cfg.stt.get("cpu_threads", 0))
            return ctx.stt.whisper

        folder = Path(os.path.expanduser(notes_cfg.get("folder", "~/Documents/Sanae Notes")))
        ctx.notes = NotesManager(ctx, transcriber, folder, on_event=on_event,
                                 include_mic_in_meetings=notes_cfg.get("include_mic_in_meetings", True),
                                 live_model_dir=resolve_path(notes_cfg["live_model"])
                                 if notes_cfg.get("live_captions", True) and notes_cfg.get("live_model") else None)
        if ctx.memory is not None:
            from .phone_notes import PhoneRecordings

            ctx.phone_notes = PhoneRecordings(ctx, on_event=on_event)
    course_cfg = cfg.get("course", {}) or {}
    if course_cfg.get("enabled", True) and ctx.memory is not None:
        from .course import CourseLibrary

        folders = [Path(os.path.expanduser(f)) for f in course_cfg.get("folders", ["~/Documents/Sanae Course Material"])]
        if course_cfg.get("include_lecture_notes", True):
            folders.append(Path(os.path.expanduser(notes_cfg.get("folder", "~/Documents/Sanae Notes"))))
        folders[0].mkdir(parents=True, exist_ok=True)          # so there's an obvious place to drop files
        ctx.course = CourseLibrary(folders, ctx.memory.embedder, course_cfg.get("index", "data/course.db"))
        if ctx.notes is not None:
            from .docnotes import DocNotes

            ctx.docnotes = DocNotes(ctx, ctx.course, ctx.notes.folder, ctx.notes.summarize, on_event=on_event)
    if (cfg.get("mail", {}) or {}).get("enabled", True):
        from .mail import accounts_from_secrets

        ctx.mail = accounts_from_secrets((cfg.get("secrets", {}) or {}).get("gmail", {}) or {})   # None until set up
    dev_cfg = cfg.get("dev", {}) or {}
    if dev_cfg.get("enabled", False):
        from .devloop import DevLoop

        ctx.dev = DevLoop(on_event=on_event, model=dev_cfg.get("model", ""), timeout_min=dev_cfg.get("timeout_minutes", 40))
    proj_cfg = cfg.get("projects", {}) or {}
    if proj_cfg.get("enabled", True):
        from .projects import Projects
        from .window import foreground_raw

        ctx.projects = Projects([Path(os.path.expanduser(f)) for f in proj_cfg.get("folders", ["~/Desktop/My Projects"])],
                                aliases=proj_cfg.get("aliases", {}), run_commands=proj_cfg.get("run", {}),
                                foreground=foreground_raw)
    if (cfg.get("league", {}) or {}).get("enabled", True) and ctx.memory is not None:
        from .league import LeagueHistory

        ctx.league_history = LeagueHistory(ctx.memory)
    if (cfg.get("valorant", {}) or {}).get("enabled", True) and ctx.memory is not None:
        from .valorant import ValorantHistory

        ctx.valorant_history = ValorantHistory(ctx.memory)
    if (cfg.get("health", {}) or {}).get("enabled", True) and ctx.memory is not None:
        from .health import Health

        ctx.health = Health(ctx.memory)       # empty until the phone app's health sharing is turned on
    routines_cfg = cfg.get("routines", {}) or {}
    if routines_cfg.get("enabled", True):
        from .routines import Routines, parse

        ctx.routines = Routines(parse(routines_cfg.get("list")))
    brief_cfg = cfg.get("briefing", {}) or {}
    if brief_cfg.get("enabled", True):
        from .briefing import Briefing

        ctx.briefing = Briefing(ctx, dict(brief_cfg))
    registry = ToolRegistry(context=ctx)
    system_tools.register(registry)
    web_tools.register(registry)
    browser_tools.register(registry)
    memory_tools.register(registry)
    canvas_tools.register(registry)
    digest_tools.register(registry)
    notes_tools.register(registry)
    phone_tools.register(registry)
    course_tools.register(registry)
    screen_tools.register(registry)
    mail_tools.register(registry)
    companion_tools.register(registry)
    fun_tools.register(registry)
    friend_tools.register(registry)
    us_tools.register(registry)
    code_tools.register(registry)
    health_tools.register(registry)
    routine_tools.register(registry)          # last: its steps call the tools above
    from .games import Games

    ctx.games = Games(ctx)
    from .persona import load_persona

    persona = load_persona() if cfg.get("persona", True) else None
    ctx.persona = persona
    recall, on_turn, notes = companion_mind(ctx, persona, bus, llm, cfg.llm.fast_model)
    conversation = make_conversation(cfg, ctx, llm)
    agent = Agent(
        llm, registry,
        fast_model=cfg.llm.fast_model,
        planner_model=cfg.llm.planner_model,
        name=cfg.assistant.name,
        user_name=cfg.assistant.user_name,
        max_steps=cfg.assistant.max_steps,
        confirm_risky=cfg.safety.confirm_risky,
        confirm=confirm,
        on_event=on_event,
        recall=recall,
        on_turn=on_turn,
        tool_selector=ToolSelector(registry, ctx.memory.embedder if ctx.memory else None),
        persona=persona,
        notes=notes,
        conversation=conversation,
        in_character=(cfg.get("conversation", {}) or {}).get("in_character", True),
    )
    if ctx.memory is not None:
        agent.embed = ctx.memory.embedder.embed
        if persona is not None:                   # "... ~Nina": a message from someone else (guests.py)
            from .guests import Guests

            agent.guests = Guests(ctx.memory, persona.people, cfg.assistant.user_name, persona.name)
    comfort = getattr(ctx, "comfort", None)
    if comfort is not None:                       # when they're not okay: softer tags, "someone with you?"
        agent.calm = comfort.calm
        agent.after_reply = comfort.after_reply
    if ctx.projects is not None and agent.tool_selector is not None:     # "is Flock up?" -> the code tools
        agent.tool_selector.hints = lambda text: ["code"] if ctx.projects.mentioned(text) else []
    ctx.agent = agent
    if ctx.mind is not None:
        ctx.mind.prewarm(agent._system()["content"])     # Claude Code starting up for the first turn
    conversation.start(busy=lambda: agent.busy or photo_coming(ctx))
    return ctx, llm, agent


def photo_coming(ctx) -> bool:
    """A photo is on its way or being looked at (vision.py): background model work waits."""
    vision = getattr(ctx, "vision", None)
    return bool(vision is not None and vision.holding)


def make_conversation(cfg, ctx, llm):
    """The running chat (conversation.py): recent turns word for word, older ones as a summary the
    fast model keeps up to date while Sanae is idle; kept in the memory database across restarts."""
    from .agent import strip_thinking
    from .conversation import Conversation

    c = cfg.get("conversation", {}) or {}

    def summarize(prompt: str) -> str:
        reply = llm.chat(cfg.llm.fast_model, [{"role": "user", "content": prompt}],
                         options={"temperature": 0.2, "num_predict": 220})
        return strip_thinking(reply.content)

    return Conversation(ctx.memory, summarize if c.get("summary", True) else None,
                        verbatim_turns=c.get("recent_turns", 6), verbatim_chars=c.get("recent_chars", 4000),
                        verbatim_min=c.get("recent_min", 30), new_after_h=c.get("new_chat_after_h", 4),
                        user=cfg.assistant.user_name, name=cfg.assistant.name)


def _logging_events(memory, on_event):
    """Also record what Sanae did (tool calls, approvals) in the action log for the dashboard."""
    def handler(kind, data):
        if kind == "tool_result":
            memory.log_action("tool", {"tool": data["tool"], "result": str(data["result"])[:300]})
        elif kind == "confirm_result":
            memory.log_action("approval", {"tool": data["tool"], "approved": data["approved"]})
        on_event(kind, data)
    return handler


def check_models(llm: OllamaClient, cfg) -> bool:
    have = llm.available_models()
    if not have:
        print("⚠  Can't reach Ollama at", cfg.llm.host, "- start the Ollama app and try again.")
        return False
    ok = True
    for m in (cfg.llm.fast_model, cfg.llm.planner_model):
        if m not in have and f"{m}:latest" not in have:
            print(f"⚠  Model {m} isn't downloaded. Run:  ollama pull {m}")
            ok = False
    vis = cfg.get("vision", {}) or {}
    m = vis.get("model")
    if vis.get("enabled", True) and m and m not in have and f"{m}:latest" not in have:
        print(f"⚠  Model {m} (photos) isn't downloaded. Run:  ollama pull {m}")
    return ok


# Said while a slow tool runs, so there's no dead air (voice mode only)
FILLERS = {
    "web_search": "Let me look that up.",
    "browser_read": "Reading the page.",
    "__escalate__": "Let me think about that one.",
    "bedtime_story": "Okay... get comfy.",
    "start_cooking": "Ooh, okay, let me think of a recipe.",
}


def reminder_text(reminder, missed: bool) -> str:
    return (f"While you were away, you had a reminder: {reminder.text}." if missed
            else f"Reminder: {reminder.text}.")


def start_backup(ctx):
    """Nightly backup of the databases, photos and voice notes (backup.py)."""
    if ctx.memory is None or os.environ.get("SANAE_LAB"):
        return None
    from .backup import make

    ctx.backup = make(ctx.cfg)
    return ctx.backup.start() if ctx.backup is not None else None


def start_digest(ctx, bus=None):
    """Daily digest email at the configured time (needs memory for its "already sent" state)."""
    d = ctx.cfg.get("digest", {}) or {}
    if not d.get("enabled", False) or ctx.memory is None:
        return None
    from .digest import DigestScheduler
    from .reminders import toast

    def on_sent(subject, error):
        if bus is not None:
            bus.publish("digest", {"subject": subject, "error": error})
        if error:
            toast(f"{ctx.cfg.assistant.name}: daily digest not sent", error)

    return DigestScheduler(ctx, d.get("time", "07:00"), d.get("weekends", True),
                           d.get("catch_up_until", "18:00"), on_sent).start()


def start_mail_alerts(ctx, bus):
    """Phone alerts for mail from chosen senders (mail.alert_senders in config.yaml)."""
    senders = (ctx.cfg.get("mail", {}) or {}).get("alert_senders") or []
    if getattr(ctx, "mail", None) is None or ctx.memory is None or bus is None or not senders:
        return None
    from .alerts import MailAlerts

    return MailAlerts(ctx, bus.publish, senders).start()


def start_course(ctx):
    """Index course files in the background now and every 10 minutes."""
    if getattr(ctx, "course", None) is not None:
        ctx.course.start((ctx.cfg.get("course", {}) or {}).get("rescan_minutes", 10) * 60)


def start_hotkey(cfg, controls, avatar_control):
    """Ctrl+Alt+Y (config hotkey.combo): tap = listen now, hold = hide / show the avatar."""
    h = cfg.get("hotkey", {}) or {}
    if not h.get("enabled", True) or os.name != "nt":
        return None
    try:
        from .avatar import foreground_state, should_hide
        from .hotkey import Hotkey

        games = (cfg.get("avatar", {}) or {}).get("games", []) or []

        def in_game() -> bool:
            try:
                return should_hide(*foreground_state(), extra_games=games)
            except Exception:
                return False

        return Hotkey(h.get("combo", "ctrl+alt+y"), on_tap=controls.listen_now.set,
                      on_hold=(lambda: avatar_control("toggle")) if avatar_control else (lambda: None),
                      blocked=in_game).start()
    except Exception as exc:
        log.warning("hotkey unavailable: %s", exc)
        return None


def look_at_photo(ctx, photo: bytes, text: str) -> tuple[str, str | None]:
    """A photo from the phone: (the user's message for the agent, None), or ("", what went wrong)."""
    from .llm import OllamaError
    from .vision import PhotoError, photo_text

    if getattr(ctx, "vision", None) is None:
        return "", "I can't look at photos right now (vision is turned off in config.yaml)."
    question = text
    if getattr(ctx, "cooking", None) is not None:
        from .cooking import COOK_Q, INGREDIENTS_Q

        if COOK_Q.search(text or ""):                 # a fridge photo: what's in it, so she can suggest dishes
            question = INGREDIENTS_Q.format(q=text)
    started = time.monotonic()
    log.info("photo: %d KB, question %r", len(photo) // 1024, text[:80])
    try:
        ctx.vision.look(photo, question)
    except PhotoError as exc:
        log.warning("photo: %s", exc)
        return "", f"Hmm, {exc}."
    except OllamaError as exc:
        log.warning("photo: %s", exc)
        return "", f"I couldn't look at it: {exc}"
    except Exception:                                # never a bare HTTP 500 on the phone
        log.exception("photo: looking failed")
        return "", "Sorry, something went wrong while I was looking at it. Try sending it again?"
    log.info("photo: looked in %.1f s (%s)", time.monotonic() - started, ctx.vision.last.by if ctx.vision.last else "?")
    return photo_text(text), None


# "I said suggest me some ideas": she missed what they asked the first time
REPEATED = re.compile(r"^\W*(no,?\s+)?(i (said|asked|told you)|like i said|i already (said|told you|asked)|"
                      r"as i said|i just said)\b", re.I)
HINT_REPEATED = ("They're repeating themselves because your last reply missed what they asked. Do exactly what "
                 "they're asking now, directly; don't steer to something else")

UP_TO = re.compile(r"\b(what (have|did) you (been )?(do|doing|up to)|what'?s new|what did you do|"
                   r"how was your (day|time)|miss me|what'?ve you been up to)\b", re.I)


def companion_mind(ctx, persona, bus, llm=None, model: str | None = None):
    """Friend memory, her mood and the window in front (with a persona and memory), as the agent's
    recall / on_turn / notes. Without them: plain memory recall and the conversation log."""
    mem = ctx.memory
    if persona is None or mem is None:
        return (mem.context_for if mem else None), (mem.log_turn if mem else None), None
    from .friend import FriendMemory
    from .mood import MoodKeeper, user_mood
    from .window import WindowWatch, wants_context

    ctx.friend = FriendMemory(mem)
    ctx.mood = MoodKeeper(mem, bus.publish if bus is not None else (lambda kind, data: None))
    from .diary import Diary
    from .support import Listener, Taste, likes_note

    sup = persona.support or {}
    ctx.diary = Diary(mem) if sup.get("diary", True) else None
    ctx.listener = Listener() if sup.get("venting", True) else None
    ctx.taste = Taste(mem) if sup.get("taste", True) else None
    ctx.comfort = None
    com = sup.get("comfort", {}) if isinstance(sup.get("comfort", {}), dict) else {}
    if sup.get("comfort", True) is not False and com.get("enabled", True):
        from .comfort import Comfort, model_classifier

        ctx.comfort = Comfort(mem, ctx.cfg.assistant.user_name, com, set_face=ctx.mood.hold_face,
                              classify=model_classifier(llm, model, ctx.cfg.assistant.user_name) if llm and model else None,
                              knows_them=lambda: bool(ctx.friend.facts()[:1]))
    likes = list(sup.get("likes", []))
    from .cloudbrain import CloudBrain, private_now
    from .reading import people_names

    ctx.brain = CloudBrain(ctx.cfg.get("brain", {}) or {}, ctx.cfg.assistant.user_name, persona.name,
                           people=lambda: people_names(ctx.friend.facts()), private_now=lambda: private_now(ctx))
    if getattr(ctx, "mind", None) is not None:          # what stays local: secrets, hard moments (claudemind.py)
        ctx.mind.privacy.memory = mem
        ctx.mind.privacy.comfort_now = lambda: getattr(ctx, "comfort", None) is not None and ctx.comfort.serious
    if getattr(ctx, "vision", None) is not None and (ctx.cfg.get("vision", {}) or {}).get("cloud", True):
        ctx.vision.cloud = ctx.brain            # Claude looks at photos; secret ones stay local (vision.py)
    from .friendship import make_parts

    ctx.parts = make_parts(ctx, persona)
    c = persona.context or {}
    if c.get("window", True):
        ctx.window = WindowWatch(c.get("blocklist", []))

    def recall(text: str) -> str | None:
        diary = ctx.diary.recall(text) if ctx.diary is not None else []
        parts = [p for p in [mem.context_for(text), *ctx.friend.relevant(text), *diary] if p]
        return "; ".join(parts) or None

    def her_recent(n: int = 4, within_s: float = 1800) -> list[str]:
        """Her last few replies in this chat (for taste and the likes check)."""
        agent = getattr(ctx, "agent", None)
        if agent is None or time.time() - agent.conv.last > within_s:
            return []
        return [str(t[-1].get("content", "")) for t in agent.history[-n:] if t and t[-1].get("role") == "assistant"]

    def on_turn(user_text: str, answer: str, tools: list[str]):
        tid = mem.log_turn(user_text, answer, tools, heard=getattr(ctx, "heard", ""))   # whose voice (voice ID)
        if ctx.comfort is not None:
            ctx.comfort.private_turn(tid)                 # not learned from while they're not okay

    def notes(user_text: str) -> list[str]:
        ctx.mood.heard(user_text)
        theirs = user_mood(user_text)
        if getattr(ctx, "heard", "") in ("you", ""):
            from .mood import tally_day

            tally_day(mem, user_text)                         # daily counts only: how the day felt, for the diary
        comfort = ctx.comfort.hear(user_text, theirs[0] if theirs else None) if ctx.comfort is not None else []
        if ctx.comfort is not None and ctx.comfort.serious:
            # They're not okay: only comfort (no teasing dials, games, her mood, venting or breathing scripts)
            if ctx.games is not None and getattr(ctx.games, "game", None) is not None:
                ctx.games.stop()
            out = comfort
            if ctx.window is not None and wants_context(user_text):
                w = ctx.window.now()
                if w is not None:
                    out.append(f"On their screen right now: {w.describe()}. Use it only if it's what they mean")
            return out
        out = [n for n in [ctx.mood.mood.note()] if n and not comfort] + comfort
        wrong = ctx.friend.denied(user_text, names=(ctx.cfg.assistant.user_name, ctx.cfg.assistant.name))
        if wrong:
            out.append(f"You had that wrong: there was no {wrong}, and you've now forgotten it. "
                       "Say sorry briefly and move on")
        if theirs:
            out.append(theirs[1])
        from .tone import hint as tone_hint

        sounds = tone_hint(getattr(ctx, "tone", None), user_text, theirs[0] if theirs else None)
        if sounds:
            out.append(sounds)
        offered = getattr(ctx, "breath_offered", 0.0)
        if theirs and theirs[0] == "stressed" and sup.get("breathing", True) and time.time() - offered > 1800:
            from .support import HINT_BREATHE

            ctx.breath_offered = time.time()                  # once per half hour at most
            out.append(HINT_BREATHE)                          # instead of the venting note: one ask at a time
        elif REPEATED.search(user_text):
            out.append(HINT_REPEATED)                         # instead of the venting note: do what they asked
            if ctx.listener is not None:
                ctx.listener.listen_until = ctx.listener.vented_at = 0.0
        elif ctx.listener is not None:                # venting: listen first, no fixes
            vent = ctx.listener.hint(user_text, theirs[0] if theirs else None, getattr(ctx, "tone", None))
            if vent:
                out.append(vent)
        games = getattr(ctx, "games", None)
        rules = games.note(user_text) if games is not None else None
        if rules:
            out.append(rules)
        reader = getattr(ctx, "reader", None)
        if reader is not None and UP_TO.search(user_text):
            read = reader.pending()
            if read:
                out.append(f"What you did while they were away: you read this: {read['note']}")
                reader.used()
        if os.name == "nt":
            from .music import song_note

            song = song_note(user_text, web=ctx.web)   # "how is the song?": what's playing + about it (never stored)
            if song:
                out.append(song)
        recent = her_recent()
        if ctx.taste is not None:                     # their reaction to her last reply tunes how she talks
            ctx.taste.react(user_text, recent[-1] if recent else None, getattr(ctx, "was_cut", False))
            out += [n for n in ctx.taste.notes() if not (comfort and "teasing" in n)]   # easing back: no teasing push
        if likes:
            note = likes_note(recent, likes)
            if note:
                out.append(note)
        for part in getattr(ctx, "parts", []):     # goals, wins, care... (part.py)
            try:
                out += part.notes(user_text, recent[-1] if recent else "")
            except Exception as exc:
                log.debug("%s notes failed: %s", part.name, exc)
        if ctx.window is not None and wants_context(user_text):
            w = ctx.window.now()                  # read now, used for this request only
            if w is not None:
                out.append(f"On their screen right now: {w.describe()}. Use it only if it's what they mean")
        return out

    return recall, on_turn, notes


def start_initiative(cfg, ctx, llm, agent, bus, say, busy):
    """She talks first now and then (greeting, welcome back, break nudge, upcoming events, asking how
    things went, small talk, noticing, bedtime), and learns about the user after conversations."""
    outer_busy = busy

    def busy() -> bool:                       # also while a photo is coming: don't push the vision model out
        return outer_busy() or photo_coming(ctx)

    persona = getattr(ctx, "persona", None)
    if persona is None or not (cfg.get("initiative", {}) or {}).get("enabled", True):
        return None
    from .dnd import DoNotDisturb
    from .initiative import Initiative, model_line

    av = cfg.get("avatar", {}) or {}

    def game_in_front() -> bool:
        from .avatar import foreground_state, should_hide

        return should_hide(*foreground_state(), av.get("games", []))

    ctx.dnd = DoNotDisturb(persona.initiative.get("quiet_hours", []), game_in_front, lambda: ctx.models_asleep)
    if getattr(ctx, "watching", None) is not None:
        ctx.dnd.holds.append(ctx.watching.quiet_reason)     # quiet while a show is on
    user = cfg.assistant.user_name
    if ctx.friend is not None and persona.learn:
        from .friend import Learner

        def can_learn() -> bool:
            return not busy() and not ctx.models_asleep and not game_in_front()

        ctx.learner = Learner(ctx, ctx.friend, llm, cfg.llm.fast_model, user, persona.name, can_learn, bus.publish).start()
    if getattr(ctx, "diary", None) is not None:
        from .diary import Writer

        def can_write() -> bool:
            return not busy() and not ctx.models_asleep and not game_in_front()

        ctx.diary_writer = Writer(ctx, ctx.diary, llm, cfg.llm.fast_model, user, persona.name, can_write,
                                  bus.publish).start()
    holder: dict = {}
    if ctx.mood is not None:                      # her mood drifts with the time of day: keep the avatar's face current
        def mood_loop():
            while True:
                time.sleep(300)
                try:
                    ctx.mood.tick()
                except Exception as exc:
                    log.debug("mood: %s", exc)

        threading.Thread(target=mood_loop, name="mood", daemon=True).start()

    def context() -> list[str]:
        comfort = getattr(ctx, "comfort", None)
        tone = comfort.line_note() if comfort is not None else None
        if tone:
            return [tone]                         # easing back / balanced: the same tone in her own lines
        reflect = getattr(ctx, "reflect", None)
        lessons = reflect.note() if reflect is not None else None
        out = [f"({lessons}.)"] if lessons else []
        if ctx.mood is None:
            return out
        ctx.mood.tick()
        n = ctx.mood.mood.note()
        return [n, *out] if n else out

    check = None
    if getattr(ctx, "brain", None) is not None and ctx.brain.enabled and (cfg.get("brain", {}) or {}).get("check_first_lines", True):
        from .firstline import FirstLineCheck

        check = FirstLineCheck(ctx.brain, persona.name)       # a second look before she speaks first
    gen = model_line(agent, llm, cfg.llm.fast_model, user, context=context,
                     recent=lambda: holder["ini"].recent_lines(5) if "ini" in holder else [], check=check)
    from .initiative import Moment, idle_seconds

    ctx.line_for = lambda situation: gen(Moment("study", situation))   # study breaks in her own words
    sup = persona.support or {}
    reader = None
    if sup.get("reading", True) and ctx.memory is not None:
        from .reading import Reader

        def can_read() -> bool:
            return not busy() and not ctx.models_asleep and not game_in_front() and ctx.dnd.reason() is None

        reader = ctx.reader = Reader(ctx, llm, cfg.llm.fast_model, user, persona.name, idle_seconds, can_read).start()
    friend_cfg = persona.friend or {}
    if friend_cfg.get("thoughts", True) is not False and ctx.memory is not None:
        from .thoughts import Thoughts                # after a chat: one thing she keeps thinking about

        def can_think() -> bool:
            return not busy() and not ctx.models_asleep and not game_in_front()

        ctx.thoughts = Thoughts(ctx.memory, llm=llm, model=cfg.llm.fast_model, user=user, her=persona.name,
                                can_run=can_think, idle=idle_seconds).start()
        ctx.parts.append(ctx.thoughts)
    music = None
    if persona.initiative.get("music", True):
        from .music import MusicWatch

        music = MusicWatch()
    holder["ini"] = Initiative(ctx, say, gen, dnd=ctx.dnd, busy=busy, publish=bus.publish, settings=persona.initiative,
                               chattiness=persona.chattiness, friend=ctx.friend, window=ctx.window,
                               topics=persona.topics, embed=ctx.memory.embedder.embed if ctx.memory else None,
                               diary=getattr(ctx, "diary", None), reader=reader, music=music,
                               comfort=getattr(ctx, "comfort", None), parts=getattr(ctx, "parts", []))
    texts = (persona.friend or {}).get("texts", {})
    if texts is not False and not (isinstance(texts, dict) and texts.get("enabled") is False) and ctx.memory is not None:
        from .texts import Texts                  # away from the laptop: a message on the phone now and then

        mem = ctx.memory
        ctx.texts = Texts(mem, ctx=ctx, generate=gen, publish=bus.publish, idle=idle_seconds, busy=busy,
                          log_turn=lambda text: mem.log_turn("", text, heard="she"),
                          settings=texts if isinstance(texts, dict) else {}).start()
        ctx.texts.sources = [p for p in getattr(ctx, "parts", []) if hasattr(p, "phone_moments")]
    return holder["ini"].start()


def start_game_mode(cfg, ctx, llm, bus, announcements):
    """Valorant (or another configured game) starts -> models unloaded, she goes quiet; it closes ->
    the chat model and the avatar come back (gamemode.py)."""
    gm = cfg.get("game_mode", {}) or {}
    if not gm.get("enabled", True):
        return None
    from .gamemode import DEFAULT_GAMES, GameMode, running_game, start_line

    games = gm.get("games") or DEFAULT_GAMES

    def on_start(game: str):
        quiet = ctx.dnd is not None and ctx.dnd.quiet_until > time.time()
        if gm.get("say_hi", True) and not quiet:
            late = ctx.pushback.game_line(game) if ctx.pushback is not None else None   # late, with something tomorrow
            announcements.put(("game", late or start_line(game)))
        for m in {cfg.llm.fast_model, cfg.llm.planner_model}:
            llm.unload(m)
        ctx.models_asleep = True                 # quiet, no background model work; the avatar closes itself
        bus.publish("status", {"models": "asleep", "game": game})

    def on_end(game: str):
        if not gm.get("wake_after", True) or not ctx.models_asleep:
            return
        ctx.models_asleep = False                # the avatar comes back too (a hidden one stays hidden)
        bus.publish("status", {"models": "awake"})
        threading.Thread(target=llm.preload, args=(cfg.llm.fast_model,), daemon=True).start()

    return GameMode(lambda: running_game(games), on_start, on_end).start(float(gm.get("check_every_s", 5)))


def start_screen_time(cfg, ctx, bus, announcements, game_mode=None):
    """Nudges after long gaming (phone + watch notification) or laptop stretches (her voice)."""
    st = cfg.get("screen_time", {}) or {}
    if not st.get("enabled", True):
        return None
    from .avatar import foreground_state, should_hide
    from .initiative import idle_seconds
    from .reminders import toast
    from .screentime import ScreenTime

    games = (cfg.get("avatar", {}) or {}).get("games", [])

    def gaming() -> bool:
        if game_mode is not None and game_mode.active:
            return True
        try:
            return should_hide(*foreground_state(), games)
        except Exception:
            return False

    def notify(kind: str, minutes: int, text: str):
        quiet = ctx.dnd is not None and ctx.dnd.quiet_until > time.time()
        if kind == "gaming":
            bus.publish("nudge", {"kind": kind, "minutes": minutes, "text": text})    # phone; the watch mirrors it
            if not quiet:
                announcements.put(("game", text))
        else:
            toast(cfg.assistant.name, text)
            if not quiet:
                announcements.put(("chat", text))

    return ScreenTime(idle_seconds, gaming, notify, gaming_min=float(st.get("gaming_minutes", 120)),
                      laptop_min=float(st.get("laptop_minutes", 180)), repeat_min=float(st.get("repeat_minutes", 60)),
                      break_min=float(st.get("break_minutes", 10))).start()


def start_league(cfg, ctx, announcements):
    """In-game reactions and a recap after each League game (league.py). Template lines only: the
    language model stays unloaded while you play."""
    lc = cfg.get("league", {}) or {}
    if not lc.get("enabled", True):
        return None
    import datetime as dt

    from .league import LeagueCompanion

    def on_recap(text, game):
        if ctx.league_history is not None:
            ctx.league_history.add(game, text, f"{dt.datetime.now():%a %b %d, %I:%M %p}".replace(" 0", " "))
        if ctx.bus is not None:
            ctx.bus.publish("league", {"action": "recap", "text": text, "result": game.result})
        if lc.get("recap", True):
            announcements.put(text)            # spoken, and part of the chat ("ugh, that jungler...")

    def quiet() -> bool:
        return ctx.dnd is not None and ctx.dnd.quiet_until > time.time()

    return LeagueCompanion(lambda line: announcements.put(("game", line)), on_recap, quiet=quiet,
                           min_gap_s=float(lc.get("min_gap_s", 60)), chatter=bool(lc.get("chatter", True))).start()


def start_valorant(cfg, ctx, announcements):
    """A recap after each Valorant match, from the Riot Client's own presence (valorant.py). Nothing
    during the match; template lines only."""
    vc = cfg.get("valorant", {}) or {}
    if not vc.get("enabled", True) or os.name != "nt":
        return None
    import datetime as dt

    from .valorant import ValorantWatch

    def on_recap(text, match):
        if ctx.valorant_history is not None:
            ctx.valorant_history.add(match, text, f"{dt.datetime.now():%a %b %d, %I:%M %p}".replace(" 0", " "))
        if ctx.bus is not None:
            ctx.bus.publish("valorant", {"action": "recap", "text": text, "result": match.result})
        quiet = ctx.dnd is not None and ctx.dnd.quiet_until > time.time()
        if vc.get("recap", True) and not quiet:
            announcements.put(text)            # spoken, and part of the chat ("ugh, our duelist...")

    return ValorantWatch(on_recap).start()


def start_alerts(ctx, bus):
    """Phone notifications 24 h / 3 h before Canvas deadlines and 10 min before classes."""
    al = ctx.cfg.get("alerts", {}) or {}
    if not al.get("enabled", True) or ctx.memory is None or bus is None or getattr(ctx, "canvas", None) is None:
        return None
    from .alerts import DeadlineAlerts

    return DeadlineAlerts(ctx, bus.publish, al.get("hours_before_due", [24, 3]), al.get("minutes_before_class", 10)).start()


def documents_done_text(done: list[str], failed: list[str], combined: list[str] = ()) -> str:
    n = len(done)
    text = (f"Your notes for {done[0]} are ready in the Notes tab." if n == 1 else
            f"Notes for all {n} files are ready in the Notes tab." if n and not failed else
            f"Notes for {n} files are ready in the Notes tab." if n else "")
    for title in combined:
        text += f" The {title} is ready too." if n else f" Your {title} is ready in the Notes tab."
    if failed:
        text += f" I couldn't read {', '.join(f.split(' (')[0] for f in failed)}."
    return text.strip()


def start_reminders(ctx, announce):
    """Run the reminder scheduler; `announce(text, reminder)` delivers the spoken/printed part."""
    if ctx.reminders is None:
        return None
    from .reminders import ReminderScheduler, toast

    def fire(reminder, missed):
        text = reminder_text(reminder, missed)
        toast(f"{ctx.cfg.assistant.name} reminder", reminder.text)
        announce(text, reminder)

    return ReminderScheduler(ctx.reminders, fire).start()


def event_printer(verbose: bool):
    def on_event(kind, data):
        if kind == "tool_call":
            print(f"   ⚙  {data['tool']}({data['args']})")
        elif kind == "escalate":
            print(f"   🧠 handing off to {data['to']}")
        elif verbose and kind == "tool_result":
            print(f"   ↳ {data['result'][:200]}")
    return on_event


def start_dashboard(cfg, ctx, bus, approvals, run_command, info, controls=None):
    d = cfg.get("dashboard", {}) or {}
    if not d.get("enabled", True):
        return None
    try:
        from .server import Runtime, serve

        host, port = d.get("host", "127.0.0.1"), int(d.get("port", 8765))
        phone = cfg.get("phone", {}) or {}
        token = ""
        if phone.get("enabled", True):
            from .remote import load_token

            token = load_token(phone.get("token_file", "data/phone_token.txt"))
        server = serve(Runtime(ctx, bus, approvals, run_command, info, controls, token), host, port)
        print(f"🖥  Dashboard: http://{host}:{port}")
        if ctx.phone_notes is not None and ctx.phone_notes.pending():
            ctx.phone_notes.start()               # recordings uploaded before a restart: carry on
        return server
    except Exception as exc:                   # the assistant works without it
        log.warning("dashboard failed to start: %s", exc)
        return None


def static_info(cfg, phrase: str, mode: str) -> dict:
    return {"name": cfg.assistant.name, "user": cfg.assistant.user_name, "wake_phrase": phrase, "mode": mode,
            "fast_model": cfg.llm.fast_model, "planner_model": cfg.llm.planner_model,
            "stt": cfg.stt.model, "started": time.time()}


# ---------------- text mode ----------------

def run_text(cfg, verbose: bool):
    def confirm(prompt: str) -> bool:
        return parse_yes_no(input(f"   ⚠  {prompt} (yes/no) > "))

    from .events import ApprovalBroker, EventBus

    bus = EventBus()
    approvals = ApprovalBroker(bus)
    agent_lock = threading.Lock()
    ctx, llm, agent = build(cfg, confirm, event_printer(verbose), bus=bus, approvals=approvals)
    check_models(llm, cfg)

    def run_command(text: str, source: str = "dashboard", photo: bytes | None = None) -> str:
        with agent_lock:
            if photo is not None:
                text, failed = look_at_photo(ctx, photo, text)
                if failed:
                    return failed
            guest = None
            if agent.guests is not None:          # "... ~Nina": from Nina, not the user
                from .guests import split as split_guest

                text, guest = split_guest(text, cfg.assistant.user_name)
            bus.publish("heard", {"text": text, "source": source, **({"guest": guest} if guest else {})})
            set_origin("phone" if source in ("watch", "call") else source)   # the watch / a call: through the phone
            try:
                reply = agent.handle(text, guest=guest)
            finally:
                set_origin("local")
            print(f"\n({source}) you > {text}\n{cfg.assistant.name.lower()} > {reply}\nyou > ", end="")
            return reply

    start_dashboard(cfg, ctx, bus, approvals, run_command, static_info(cfg, "(text mode)", "text"))
    start_digest(ctx, bus)
    start_backup(ctx)
    start_alerts(ctx, bus)
    start_mail_alerts(ctx, bus)
    start_course(ctx)
    bus.publish("stage", {"stage": "text mode"})
    start_reminders(ctx, lambda text, r: (bus.publish("reminder", {"action": "fired", "text": text, "uid": r.uid, "due_ms": int(r.due.timestamp() * 1000)}),
                                          print(f"\n⏰ {text}\nyou > ", end="")))
    print(f"{cfg.assistant.name} text mode. Type 'quit' to exit.\n")
    while True:
        try:
            text = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text.lower() in ("quit", "exit", "bye"):
            break
        if text:
            with agent_lock:
                bus.publish("heard", {"text": text, "source": "keyboard"})
                print(f"{cfg.assistant.name.lower()} > {agent.handle(text)}\n")


# ---------------- voice mode ----------------

def make_wake_detector(cfg):
    from .wakeword import make_detector

    return make_detector(cfg.wake_word)


def make_hearing(cfg, ctx):
    """Tone of voice (tone.ToneReader) and end-of-turn check (turn.completer), each optional."""
    from .listen import looks_complete

    h = cfg.get("hearing", {}) or {}
    tone = complete = None
    if h.get("tone", True):
        try:
            from .tone import Baseline, ToneModel, ToneReader

            tone = ToneReader(ToneModel(h.get("tone_model", "models/tone/ser.mm8.onnx"), h.get("tone_threads", 4)),
                              Baseline(ctx.memory))
        except Exception as exc:
            log.warning("tone of voice unavailable (%s)", exc)
    if h.get("turn_detector", True):
        try:
            from .turn import TurnDetector, completer

            complete = completer(TurnDetector(h.get("turn_model", "models/turn")))
        except Exception as exc:
            log.warning("turn detector unavailable (%s)", exc)
    return tone, complete or looks_complete


def make_voice_id(cfg):
    """Voice ID when it's enabled and you've enrolled (run.bat --enroll-voice)."""
    v = cfg.get("voice_id", {}) or {}
    if not v.get("enabled", True):
        return None
    try:
        from .voiceid import VoiceID

        vid = VoiceID(v.get("model", "models/voiceid/eres2net_en_voxceleb.onnx"), v.get("profile", "data/voice_profile.npy"),
                      v.get("threshold", 0.42))
        vid.chat_threshold = v.get("conversation_threshold", vid.chat_threshold)
    except Exception as exc:
        log.warning("voice ID unavailable (%s)", exc)
        return None
    if not vid.enrolled:
        log.info("voice ID: not enrolled yet (run.bat --enroll-voice)")
        return None
    log.info("voice ID on: risky requests in other voices need a tap on your phone")
    return vid


ENROLL_LINES = ["What's due on Canvas this week?", "Remind me to call my mom tomorrow at six.",
                "Open Spotify and play something relaxing.", "Take notes for this lecture, please.",
                "What's the weather going to be like in Austin today?", "Set a timer for ten minutes on my phone."]


def _as_float(audio):
    import numpy as np

    return audio.astype(np.float32) / 32768.0 if audio.dtype != np.float32 else audio


def run_enroll_voice(cfg):
    """Record a few sentences and save the user's voiceprint (no audio is kept)."""
    from .audio import Microphone, NoiseFloor, record_utterance
    from .voiceid import VoiceID

    v = cfg.get("voice_id", {}) or {}
    vid = VoiceID(v.get("model", "models/voiceid/eres2net_en_voxceleb.onnx"), v.get("profile", "data/voice_profile.npy"),
                  v.get("threshold", 0.42))
    a = cfg.audio
    mic = Microphone(a.sample_rate, a.input_device)
    noise = NoiseFloor()
    mic.start()
    print("Voice ID enrolment. Read each sentence out loud in your normal voice, at your usual distance.\n")
    for _ in range(12):                                  # learn the room's background noise first
        frame = mic.read(timeout=0.5)
        if frame is not None:
            noise.update(frame)
    clips = []
    for i, line in enumerate(ENROLL_LINES, 1):
        print(f"  {i}/{len(ENROLL_LINES)}  \"{line}\"")
        audio = record_utterance(mic, noise, a.vad_sensitivity, 1.0, 6.0, 12.0)
        if audio is None or len(audio) < 16000:
            print("     (didn't catch that; skipping)")
            continue
        clips.append(_as_float(audio))
    vid.enroll(clips)
    print("\nNow say anything else, to check it recognises you:")
    test = record_utterance(mic, noise, a.vad_sensitivity, 1.0, 6.0, 12.0)
    mic.stop()
    if test is not None:
        s = vid.score(_as_float(test))
        if s is not None:
            print(f"     similarity {s:.2f} (threshold {vid.threshold}): {'recognised' if s >= vid.threshold else 'NOT recognised'}")
    print(f"\nSaved your voiceprint to {vid.profile_path}. Restart Sanae to use it.")


def run_wake_test(cfg):
    """Live wake-word detections (and scores for openWakeWord), for tuning the threshold."""
    from .audio import Microphone, chime

    a = cfg.audio
    mic = Microphone(a.sample_rate, a.input_device)
    wake = make_wake_detector(cfg)
    scored = wake.last_score is not None
    print(f"Wake word: {wake.describe()}")
    print(f"Say \"{wake.phrase}\" 10 times, then talk normally / play a video to check for false "
          "triggers. Ctrl+C to stop.\n")
    mic.start()
    hits, peak, window_start, started = 0, 0.0, time.monotonic(), time.monotonic()
    try:
        while True:
            frame = mic.read(timeout=1.0)
            if frame is None:
                continue
            if wake.process(frame):
                hits += 1
                score = f" (score {wake.last_score:.2f})" if scored else ""
                print(f"  🔔 DETECTED #{hits} at {time.monotonic() - started:.0f}s{score}", flush=True)
                chime("wake", a.output_device)
            if scored:
                peak = max(peak, wake.last_score)
                if time.monotonic() - window_start >= 1.0:
                    print(f"  peak {peak:.2f} |{'#' * int(peak * 40):<40}|", flush=True)
                    peak, window_start = 0.0, time.monotonic()
    except KeyboardInterrupt:
        print(f"\n{hits} detections. Missed some? Lower the threshold. False triggers? Raise it.")
    finally:
        mic.stop()


def run_voice(cfg, verbose: bool, tray: bool = False):
    from .audio import Microphone, NoiseFloor, chime, rms
    from .listen import listen_for_command
    from .diagnostics import Heartbeat, foreground_window
    from .stt import SpeechToText
    from .tts import Speaker

    a = cfg.audio
    print("Loading speech models (first run downloads them)...")
    mic = Microphone(a.sample_rate, a.input_device)
    stt = SpeechToText(cfg.stt.model, cfg.stt.device, cfg.stt.compute_type,
                       cfg.stt.get("fast_model_dir"), cfg.stt.get("fast_min_snr_db", 12.0),
                       cfg.stt.get("prompt"), cfg.stt.get("cpu_threads", 0))
    speaker = Speaker(cfg.tts.engine, cfg.tts.piper_voice, cfg.tts.speed, a.output_device, mic=mic,
                      natural_voice=cfg.tts.get("natural_voice", "Microsoft Ava Online"), cfg_tts=dict(cfg.tts))
    speaker.on_speech = lambda action, data: bus.publish("speech", {"action": action, **data})
    night = cfg.tts.get("night", {"from": "23:00", "until": "06:00"})
    speaker.night = (night.get("from", "23:00"), night.get("until", "06:00")) if night else None
    speaker.sounds = float(cfg.tts.get("sounds", 0.35) or 0)
    heard_audio = {"last": None}              # the last recording, for voice ID
    voice_check = {"owner": None}             # did the current request sound like the user? (None = unknown)
    voice_id = make_voice_id(cfg)
    if a.get("barge_in", True) and speaker.piper is not None:
        try:
            from .wakeword import InterruptSpotter

            # "stop" alone is short and common, so it needs a clearer match than two-word phrases
            name = cfg.assistant.name
            speaker.interrupts = InterruptSpotter({wake_phrase(cfg): 0.2, f"{name} stop": 0.2, "Stop it": 0.25,
                                                   "Okay stop": 0.25, "Stop": 0.35, "Skip it": 0.25, "Skip": 0.35},
                                                  (cfg.wake_word.get("sherpa") or {}).get("model_dir", "models/kws/gigaspeech-3.3M"))
            log.info("interrupting enabled: say 'stop' or '%s' while %s is talking", wake_phrase(cfg), name)
        except Exception as exc:
            log.warning("interrupting unavailable (%s)", exc)
    wake = make_wake_detector(cfg)
    noise = NoiseFloor()

    from .events import ApprovalBroker, EventBus

    bus = EventBus()
    approvals = ApprovalBroker(bus)
    agent_lock = threading.Lock()         # a typed (dashboard) and a spoken command never overlap
    beat = Heartbeat(mic, publish=bus.publish)
    level_tick = {"n": 0}

    def on_level(mean_square: float):     # ~6 updates/s for the dashboard orb
        level_tick["n"] += 1
        if level_tick["n"] % 2 == 0:
            bus.publish("level", {"rms": round(mean_square ** 0.5, 1)})

    mic.on_level = on_level

    def ring():
        mic.muted.set()           # don't record our own beep (it would count as speech)
        try:
            chime("wake", a.output_device)
        finally:
            mic.muted.clear()

    def listen(timeout: float, should_stop=None, quiet: bool = False) -> str:
        # No mic.flush() here: audio right after "Hey Sanae" is kept, so "Hey Sanae, open
        # YouTube" works in one breath. (Speaker.say already drops Sanae's own voice.)
        if a.chime and not quiet:
            threading.Thread(target=ring, daemon=True).start()
        beat.set("listening to command")

        def transcribe(audio):                 # keep the recording: voice ID checks who said it
            heard_audio["last"] = audio
            if tone is not None:
                tone.start(audio)              # how it sounded, scored next to Whisper
            bus.publish("stt", {"busy": True})  # the avatar slows down so Whisper gets the CPU
            try:
                return stt.transcribe(audio)
            finally:
                bus.publish("stt", {"busy": False})

        heard_audio["last"] = None
        text = listen_for_command(mic, noise, transcribe, a.vad_sensitivity, a.silence_s, timeout,
                                  a.max_record_s, a.get("early_s", 0.4), a.get("max_silence_s", 1.8),
                                  should_stop=should_stop, is_complete=is_complete,
                                  backchannel=None if should_stop else nod)   # not while waiting for a yes/no
        if text:
            bus.publish("heard", {"text": text, "source": "voice"})
        return text

    def phone_only(prompt: str) -> bool:
        """A voice that isn't the user's asked for something risky: only a tap on the phone counts."""
        phone = getattr(ctx, "phone", None)
        if phone is None or not phone.online:
            say("I didn't recognise your voice, and your phone isn't connected, so I won't do that.")
            return False
        say("I didn't recognise your voice. Approve it on your phone if it was you.")
        return approvals.wait(prompt + " (Sanae didn't recognise the voice.)",
                              (cfg.get("phone", {}) or {}).get("approval_timeout_s", 90))

    def confirm(prompt: str) -> bool:
        if voice_check["owner"] is False:          # the request itself came from an unknown voice
            return phone_only(prompt)
        # Voice and dashboard race: a click stops the listening early
        request = approvals.open(prompt)
        say(prompt + " Say yes or no.")
        answer = "" if request.done.is_set() else listen(cfg.safety.confirm_timeout_s, request.done.is_set)
        if request.done.is_set():
            approved, by = bool(request.approved), "dashboard"
        else:
            approved, by = parse_yes_no(answer), "voice"
            print(f"   you: {answer or '(silence)'}")
            if approved and voice_id is not None and heard_audio["last"] is not None \
                    and voice_id.is_owner(heard_audio["last"]) is False:
                approvals.close(request, False, "voice not recognised")
                return phone_only(prompt)           # someone else said "yes"
        approvals.close(request, approved, by)
        return approved

    speak_lock = threading.Lock()

    cut = {"kind": None}          # "stop" / "wake" when the user interrupted Sanae's last reply

    def say(text: str):
        with speak_lock:          # one voice at a time: a filler never overlaps the answer
            result = speaker.say(text)
        if result:
            cut["kind"] = result
        return result

    def say_main(text: str):      # the main loop's own speech, tracked by the heartbeat
        beat.set("speaking")
        return say(text)

    printer = event_printer(verbose)
    turn = {"filler": False}

    def on_event(kind, data):
        printer(kind, data)
        if kind == "thinking" and data.get("step") == 0:
            turn["filler"] = False
        key = data.get("tool") if kind == "tool_call" else "__escalate__" if kind == "escalate" else None
        if key in FILLERS and not turn["filler"] and current_origin() != "phone":
            turn["filler"] = True
            threading.Thread(target=say, args=(FILLERS[key],), daemon=True).start()

    ctx, llm, agent = build(cfg, confirm, on_event, bus=bus, approvals=approvals)
    tone, is_complete = make_hearing(cfg, ctx)
    nod = speaker.backchannel if (cfg.get("hearing", {}) or {}).get("backchannel", True) else None
    expressive = cfg.tts.get("expressive", True)
    ctx.stt = stt
    ctx.speak = say                                   # the breathing exercise talks step by step
    ctx.set_voice = speaker.set_emotion if expressive else None
    announcements: queue.Queue[str] = queue.Queue()   # spoken reminders wait until Sanae is idle
    if ctx.notes is not None:
        def notes_done(result, error):
            from .reminders import toast

            if error:
                announcements.put("Sorry, writing up the notes failed. The transcript may still be saved.")
                return
            announcements.put(f"Your notes for {result.title} are ready.")
            toast(f"{cfg.assistant.name}: notes ready", f"{result.title}: saved to {result.folder}")

        ctx.notes.on_done = notes_done
    if ctx.docnotes is not None:
        def docnotes_done(done, failed):
            from .reminders import toast

            text = documents_done_text(done, failed, list(ctx.docnotes.combined))
            announcements.put(text)
            toast(f"{cfg.assistant.name}: document notes", text)

        ctx.docnotes.on_done = docnotes_done

    def run_command(text: str, source: str = "dashboard", photo: bytes | None = None) -> str:
        with agent_lock:
            voice_check["owner"] = None           # typed or from the phone: no voice to check
            ctx.heard, ctx.tone, ctx.was_cut = "", None, False
            if photo is not None:                 # gemma looks first (swaps out the chat model; ~20 s)
                text, failed = look_at_photo(ctx, photo, text)
                if failed:
                    return failed
            guest = None
            if agent.guests is not None:          # "... ~Nina": from Nina, not the user
                from .guests import split as split_guest

                text, guest = split_guest(text, cfg.assistant.user_name)
            bus.publish("heard", {"text": text, "source": source, **({"guest": guest} if guest else {})})
            set_origin("phone" if source in ("watch", "call") else source)   # the watch / a call: through the phone
            try:
                reply = agent.handle(text, guest=guest)
            finally:
                set_origin("local")
            print(f"⌨  ({source}) you: {text}\n🤖 {cfg.assistant.name.lower()}: {reply}\n")
            if source == "dashboard" and cfg.get("dashboard", {}).get("speak_typed_replies", False):
                announcements.put(reply)
            return reply

    def respond(text):
        if text is None:              # "never mind"
            say_main("Okay.")
            return None
        ctx.models_asleep = False
        ctx.was_cut = cut["kind"] == "stop"           # they cut her last reply short (taste: shorter)
        cut["kind"] = None
        last = heard_audio["last"]
        voice_check["owner"], ctx.heard = voice_id.judge(last) if voice_id is not None and last is not None else (None, "")
        ctx.tone = tone.result(ctx.heard) if tone is not None and last is not None else None
        if tone is not None and ctx.heard in ("you", ""):
            from .tone import tally

            tally(ctx.memory, ctx.tone)                # daily counts only, for the diary
        beat.set("thinking")
        # Speak each sentence as soon as the model has written it, instead of after the whole reply
        stream = SentenceSpeaker(say) if a.get("stream_replies", True) else None
        on_text = stream.feed if stream else None
        if on_text is not None and agent.persona is not None:
            from .tags import TagFilter

            # tags come off before the words are spoken; the face changes as soon as one is complete
            def feel(t):
                if agent.calm is not None:
                    t.emotion, t.gestures = agent.calm(t.emotion, t.gestures)
                bus.publish("emotion", {"emotion": t.emotion, "gestures": t.gestures, "source": "tag", "early": True})
                if expressive:
                    speaker.set_emotion(t.emotion)     # she sounds the way she feels

            on_text = TagFilter(on_text, feel, agent.persona.emotions, agent.persona.gestures)
        with agent_lock:
            answer = agent.handle(text, on_text=on_text)
        print(f"🤖 {cfg.assistant.name.lower()}: {answer}\n")
        beat.set("speaking")
        if stream is not None:
            cut["kind"] = stream.finish(answer) or cut["kind"]
        else:
            say_main(answer)
        speaker.set_emotion("neutral")
        return answer

    def listen_follow_up() -> str:
        # Sanae just asked something: listen again without the wake word. Let the room echo
        # of Sanae's own voice die down first so it isn't recorded as an answer.
        time.sleep(0.3)
        mic.flush()
        print("👂 Listening (reply to Sanae, no need to say the wake word)...")
        return listen(a.get("follow_up_timeout_s", 5.0))

    conversation_s = float(a.get("conversation_s", 0) or 0)

    def on_a_call() -> bool:
        """Another app (a call, a recorder) is using the mic: what's said there isn't for her."""
        try:
            from .dnd import devices_in_use

            return bool(devices_in_use("microphone", ctx.dnd.ignore_apps if ctx.dnd else ("python",)))
        except Exception:
            return False

    def keep_listening() -> str:
        # Conversation mode: after her reply, follow-ups need no wake word for a while
        if on_a_call():
            log.info("conversation mode: skipped (mic in use by another app)")
            return ""
        time.sleep(0.3)
        mic.flush()
        until = time.time() + conversation_s
        bus.publish("listen", {"mode": "conversation", "until_ms": int(until * 1000)})
        print(f"👂 Still listening for {conversation_s:.0f} s (no wake word needed)...")
        try:
            return listen(conversation_s, quiet=True)
        finally:
            bus.publish("listen", {"mode": "wake"})

    def your_voice() -> bool:
        """Without the wake word, only the user's own voice counts (voice ID): a video, a call or
        someone else in the room would otherwise keep the conversation going on its own."""
        last = heard_audio["last"]
        if voice_id is None or last is None:
            return True
        owner = voice_id.in_conversation(last)
        if owner is False:
            log.info("conversation mode: not your voice, back to the wake word")
            print("🙉 That wasn't your voice; say the wake word if it was for me.")
            bus.publish("listen", {"mode": "wake"})
        return owner is not False

    def answer_from_you() -> str:
        """After she spoke first (or the briefing): a reply without the wake word, only in your voice."""
        text = keep_listening()
        return text if text and your_voice() else ""

    def spoken_line(line: str) -> str:
        """Her own line (with tags): tags off, face on."""
        if agent.persona is None:
            return line
        from .tags import parse

        t = parse(line, agent.persona.emotions, agent.persona.gestures)
        if agent.calm is not None:
            t.emotion, t.gestures = agent.calm(t.emotion or "happy", t.gestures)
        bus.publish("emotion", {"emotion": t.emotion or "happy", "gestures": t.gestures, "source": "tag"})
        if expressive:
            speaker.set_emotion(t.emotion or "happy")
        bus.publish("answer", {"text": t.text, "initiative": True})
        return t.text

    def briefing_first(first: str) -> bool:
        from .briefing import GREETING

        return not first or bool(GREETING.match(first))

    def briefing_after() -> bool:
        """After their first request: not if it put her to sleep / asked for quiet, or they cut her off."""
        from .briefing import NOT_NOW

        if cut["kind"] == "stop" or ctx.models_asleep or (ctx.dnd is not None and ctx.dnd.quiet_until > time.time()):
            return False
        return not (set(agent.last_tools) & NOT_NOW)

    def brief(briefing, after_request: bool = False, heard: str = "") -> bool:
        beat.set("speaking")
        print("☀  morning briefing")
        why = (f'They said "{heard}", the first thing this morning' if heard else
               "They woke you for the first time this morning") + "; you gave the morning briefing"
        try:
            done = briefing.deliver(say_main, spoken_line, lambda text: agent.add_said(text, why), after_request=after_request)
        except Exception:
            log.exception("morning briefing failed")
            return False
        finally:
            speaker.set_emotion("neutral")
        if not done:
            say_main("Okay, skipping it.")
        return done

    def idle():
        if a.chime:
            chime("done", a.output_device)
        print("   (didn't catch anything)")
    models_ok = check_models(llm, cfg)
    if models_ok:
        threading.Thread(target=llm.preload, args=(cfg.llm.fast_model,), daemon=True).start()

    from .winutil import keep_awake_in_background

    tweaks = keep_awake_in_background()
    if tweaks:
        log.info("background listening: %s", ", ".join(tweaks))
    scheduler = start_reminders(ctx, lambda text, r: (bus.publish("reminder", {"action": "fired", "text": text, "uid": r.uid, "due_ms": int(r.due.timestamp() * 1000)}),
                                                      announcements.put(text)))
    from .events import Controls

    controls = Controls()
    if ctx.dev is not None:
        from .devloop import restart_sanae_detached

        def restart():                           # a change approved on the phone: come back with the new code
            restart_sanae_detached()
            controls.quit.set()

        ctx.dev.restart = restart

        def code_done(job):                      # Claude finished (or failed) a change: tell them when idle
            from .reminders import toast
            from .tools.code import describe

            line = describe(job)
            announcements.put(line)
            toast(f"{cfg.assistant.name}: {job.project}", line[:200])

        ctx.dev.on_done = code_done
    start_dashboard(cfg, ctx, bus, approvals, run_command, static_info(cfg, wake.phrase, "voice"), controls)
    from .avatar import launch_with_sanae

    avatar_on = bool((cfg.get("avatar", {}) or {}).get("enabled"))

    def avatar_control(action: str):
        """"hide" (she waves first) / "show" / "toggle"; showing starts the avatar if it isn't running.
        "launch" only starts it if it isn't running (closed while the models slept)."""
        if action != "launch":
            bus.publish("avatar", {"action": action})
        if action != "hide":
            launch_with_sanae(cfg)                 # not running (closed while asleep...): start it; else a no-op

    if avatar_on:
        ctx.avatar_control = avatar_control
    launch_with_sanae(cfg)
    hotkey = start_hotkey(cfg, controls, avatar_control if avatar_on else None)  # noqa: F841
    digest = start_digest(ctx, bus)
    start_backup(ctx)
    alerts = start_alerts(ctx, bus)  # noqa: F841
    start_mail_alerts(ctx, bus)
    start_course(ctx)
    initiative = start_initiative(cfg, ctx, llm, agent, bus,
                                  say=lambda line, info: announcements.put(("chat", line)),
                                  busy=lambda: agent_lock.locked() or beat.stage != "waiting for wake word" or not announcements.empty())
    from .study import StudyBuddy

    st = (getattr(ctx, "persona", None) and ctx.persona.support.get("study")) or {}
    ctx.study = StudyBuddy(ctx, lambda text, chat: announcements.put(("chat", text) if chat else text),
                           getattr(ctx, "line_for", None), st.get("focus_min", 25), st.get("break_min", 5))
    league = start_league(cfg, ctx, announcements)
    valorant = start_valorant(cfg, ctx, announcements)
    ctx.game_mode = start_game_mode(cfg, ctx, llm, bus, announcements)
    from . import services

    services.listen(lambda state: bus.publish("services", state))
    ctx.services = services.make_services(cfg).start()     # Ollama and SearXNG, in the background
    if os.name == "nt":
        from .music import RECENT

        RECENT.start()                           # last few tracks (memory only) for "I'm listening to X"
    screen_time = start_screen_time(cfg, ctx, bus, announcements, ctx.game_mode)
    mic.start()
    beat.start()
    print(f"\n✅ Ready. Say \"{wake.phrase}\". Press Ctrl+C to quit.\n")
    tray_icon = None
    if tray:
        from .tray import Tray

        d = cfg.get("dashboard", {}) or {}

        def sleep_models():
            for m in (cfg.llm.fast_model, cfg.llm.planner_model):
                llm.unload(m)
            ctx.models_asleep = True                 # also tells the avatar (event "gpu")
            bus.publish("status", {"models": "asleep"})

        def toggle_avatar():
            avatar_control("toggle")

        def reset_avatar():
            bus.publish("avatar", {"action": "reset"})      # back above the clock

        tray_icon = Tray(cfg.assistant.name, f"http://{d.get('host', '127.0.0.1')}:{d.get('port', 8765)}",
                         sleep_models, controls, *((toggle_avatar, reset_avatar) if (cfg.get("avatar", {}) or {}).get("enabled")
                                                   else (None, None))).start()
    say_main(f"{cfg.assistant.name} online.")

    try:
        beat.set("waiting for wake word")
        while True:
            if controls.quit.is_set():               # tray, overlay or API asked Sanae to stop
                break
            manual = controls.listen_now.is_set()    # push-to-talk from the overlay/dashboard
            if manual:
                controls.listen_now.clear()
                mic.flush()                          # start fresh: only what's said after the click
            else:
                if controls.paused.is_set():         # paused: ignore the mic
                    if beat.stage != "paused":
                        beat.set("paused")
                    mic.read(timeout=0.3)
                    continue
                if beat.stage == "paused":
                    beat.set("waiting for wake word")
                if not announcements.empty():
                    item = announcements.get()
                    kind = item[0] if isinstance(item, tuple) else ""
                    chat = kind == "chat"                  # ("chat", line): she's starting a conversation
                    game = kind == "game"                  # ("game", line): a quick in-game reaction, nothing more
                    text = spoken_line(item[1]) if chat else item[1] if game else item
                    print(f"{'💬' if chat else '🎮' if game else '⏰'} {text}")
                    if not chat and not game:               # part of the chat too ("thanks", "wait, when?")
                        agent.add_said(text)
                    heard = say_main(text)
                    speaker.set_emotion("neutral")
                    if heard == "wake":                     # "Hey Sanae" during an announcement
                        controls.listen_now.set()
                    elif chat and conversation_s > 0 and heard is None:
                        # she said something first: a reply needs no wake word
                        converse(answer_from_you(), respond, listen_follow_up, follow_up=a.get("follow_up", True),
                                 on_heard=lambda t: print(f"🗣  you: {t}"), on_idle=lambda: None,
                                 interrupted=lambda: cut["kind"], listen_new=lambda: listen(a.no_speech_timeout_s),
                                 keep_listening=keep_listening, accept=your_voice)
                    wake.reset()
                    mic.flush()
                    beat.set("waiting for wake word")
                frame = mic.read(timeout=0.3)
                if frame is None:
                    continue
                if not wake.process(frame):
                    if rms(frame) < noise.level * 2:
                        noise.update(frame)  # learn the room's background noise while idle
                    continue

            log.info("app in front at wake: %s", foreground_window())
            bus.publish("wake", {"phrase": wake.phrase, "manual": manual})
            print("👂 Listening...")
            first = listen(a.no_speech_timeout_s)
            briefing = ctx.briefing if ctx.briefing is not None and ctx.briefing.due() else None
            if briefing is not None and briefing_first(first):
                # first wake of the morning with just "hey" / "good morning": the rundown is the answer
                if brief(briefing, heard=first) and conversation_s > 0:
                    converse(answer_from_you(), respond, listen_follow_up, follow_up=a.get("follow_up", True),
                             on_heard=lambda t: print(f"🗣  you: {t}"), on_idle=lambda: None,
                             interrupted=lambda: cut["kind"], listen_new=lambda: listen(a.no_speech_timeout_s),
                             keep_listening=keep_listening, accept=your_voice)
            else:
                handled = converse(first, respond, listen_follow_up,
                                   follow_up=a.get("follow_up", True),
                                   on_heard=lambda t: print(f"🗣  you: {t}"), on_idle=idle,
                                   interrupted=lambda: cut["kind"], listen_new=lambda: listen(a.no_speech_timeout_s),
                                   keep_listening=keep_listening if conversation_s > 0 else None, accept=your_voice)
                if briefing is not None and handled and briefing_after():
                    brief(briefing, after_request=True)        # answered their request; now the rundown
            wake.reset()
            mic.flush()
            beat.set("waiting for wake word")
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        bus.publish("stage", {"stage": "stopped"})
        if tray_icon is not None and tray_icon.icon is not None:
            tray_icon.icon.stop()
        beat.stop()
        if scheduler:
            scheduler.stop()
        if digest:
            digest.stop()
        if initiative:
            initiative.stop()
        if league:
            league.stop()
        if valorant:
            valorant.stop()
        if screen_time:
            screen_time.stop()
        mic.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sanae", description="Local voice assistant")
    parser.add_argument("--text", action="store_true", help="Type instead of talking (no mic needed)")
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument("--list-devices", action="store_true", help="Show audio devices and exit")
    parser.add_argument("--wake-test", action="store_true", help="Show live wake word scores to tune the threshold")
    parser.add_argument("--tray", action="store_true",
                        help="Background mode: no console needed, tray icon (used by install_autostart.ps1)")
    parser.add_argument("--enroll-voice", action="store_true", help="Record your voice for voice ID (a few sentences)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.list_devices:
        from .audio import list_devices

        print(list_devices())
        return

    cfg = load_config(args.config)
    from . import reminders as _reminders
    from .rename import migrate

    migrate(cfg)                          # data/max.db, Max Notes... -> Sanae's names (once)

    _reminders.APP_NAME = cfg.assistant.name
    if not args.text:
        # Before logging binds to stdout: a stalled console must never freeze the listener
        from .winutil import unblock_console

        unblock_console()
    setup_logging(cfg, args.verbose)
    if not (args.text or args.wake_test or args.enroll_voice):
        from .winutil import single_instance

        instance = single_instance()               # noqa: F841 (held for the process lifetime)
        if instance is None:
            d = cfg.get("dashboard", {}) or {}
            print(f"{cfg.assistant.name} is already running; opening the dashboard.")
            import webbrowser

            webbrowser.open(f"http://{d.get('host', '127.0.0.1')}:{d.get('port', 8765)}")
            return
    if args.enroll_voice:
        run_enroll_voice(cfg)
    elif args.wake_test:
        run_wake_test(cfg)
    elif args.text:
        run_text(cfg, args.verbose)
    else:
        run_voice(cfg, args.verbose, tray=args.tray)


if __name__ == "__main__":
    main()
