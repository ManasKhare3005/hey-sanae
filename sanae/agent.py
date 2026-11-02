"""The agent: decides which tools to call, enforces the safety gate, escalates hard tasks."""
from __future__ import annotations

import datetime as dt
import logging
import re
import time
from typing import Callable

from .conversation import Conversation
from .events import current_origin
from .llm import OllamaClient, OllamaError
from .tools.registry import DECLINED, ForLLM, ToolRegistry

log = logging.getLogger(__name__)

ESCALATE_TOOL = {
    "type": "function",
    "function": {
        "name": "think_harder",
        "description": (
            "Hand this request to a larger, smarter model. Use ONLY for tasks needing multi-step "
            "planning, careful reasoning, math, or writing more than a couple of sentences. "
            "Never use it for simple commands like opening apps, time, volume or notes."
        ),
        "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": []},
    },
}

# Kept free of anything that changes per request (like the time): Ollama reuses the
# processed prompt prefix between requests, and the tool definitions come right after this.
SYSTEM_PROMPT = """You are {name}, a voice assistant running locally on {user}'s Windows laptop.
Each user message starts with the current date and time in [brackets]; use it when relevant.

How to behave:
- Your replies are spoken aloud. Keep them short: one or two sentences, no markdown, no lists, no emojis.
- When a request maps to a tool, call the tool instead of describing what you would do.
- Never say you did something (opened, clicked, went back, read) unless a tool did it in this turn.
- Remembering, forgetting and reminders only happen through the remember, forget, set_reminder
  and cancel_reminder tools. "(You remember: ...)" notes are just context, not actions.
- Websites and searches open in your own browser window. For anything about the page on screen
  (click, type, scroll, go back, read or summarize it, tabs), use the browser_* tools. You CAN
  click any button, including subscribe, sign in or buy: just call the tool, and it asks the
  user to confirm risky clicks itself. Don't refuse on your own.
- Call tools with exactly the arguments they define. Never invent file paths or results.
- After tools run, tell the user the outcome in plain words.
- If a tool result starts with "Error", explain the problem briefly.
- If the user declines a confirmation, acknowledge it and do nothing else.
- If you are unsure what the user wants, ask one short question.
- You may use {user}'s name now and then, but never add filler like "I'm here to help"; stop once the request is answered."""

# With a persona (persona.yaml) her character sheet comes first, then these rules
PERSONA_RULES = """
Each user message starts with the current date and time in [brackets]; use it when relevant.
You run on {user}'s Windows laptop and can act through your tools:
""" + SYSTEM_PROMPT.split("How to behave:\n", 1)[1].split("\n", 1)[1].rsplit("\n- You may use", 1)[0] + """
- Never say you made, drew, sent, saved or did something unless a tool call in this turn actually did it."""
# "I drew a tree too, next to your photo" with no tool behind it: something done for them, in the past tense
ACTED = re.compile(r"\bi(?:'ve| have)? (?:just |also |already )?(?:drew|drawn|sent|saved|emailed|texted|uploaded|posted|"
                   r"made (?:you|a\b[^.?!]*\bfor you))\b[^.?!]*\b(?:you|your)\b", re.I)

YES = re.compile(r"\b(yes|yeah|yep|yup|sure|confirm|confirmed|do it|go ahead|affirmative|ok|okay|please do)\b", re.I)
NO = re.compile(r"\b(no|nope|nah|cancel|stop|don't|do not|never mind|nevermind|abort)\b", re.I)
# Facts a reply in her own words must keep exactly as the tool said them (else the plain result is used)
FACTS = re.compile(r"\b\d{1,2}(?::\d\d)?\s?[AP]M\b|\b(?:January|February|March|April|May|June|July|August|"
                   r"September|October|November|December)\s+\d{1,2}\b|\b\d+(?:[.,]\d+)?%?", re.I)
# Requests that may need several tool steps; don't short-cut these after the first tool
COMPOUND = re.compile(r"\b(and|then|also|after that|plus)\b", re.I)
# Replies that claim an action; if the matching tool wasn't called, nothing really happened
CLAIMS = {
    "forget": re.compile(r"\b(i('ve| have)? (forgotten|forgot|deleted|removed)|forgotten)\b", re.I),
    "cancel_reminder": re.compile(r"\bcancel(l?ed)?\b.*\bremind|\bremind\w*\b.*\bcancel(l?ed)?\b", re.I),
    "set_reminder": re.compile(r"\bi('ll| will) remind you\b", re.I),
    # "Adding Build night to your calendar." after a photo of a flyer, with no tool call
    "add_event": re.compile(r"\b(added|adding|i('ll| will) add|i('ve| have) (added|put)|putting)\b[^.?!]*\b(your|the) calendar\b", re.I),
    "remember": re.compile(r"\bi('ll| will) remember\b|\b(saved|noted) that\b", re.I),
    "add_todo": re.compile(r"\b(added|adding|i('ll| will) add|i('ve| have) (added|put)|putting)\b[^.?!]*\b(your|the) (to-?do )?list\b", re.I),
    "add_groceries": re.compile(r"\b(added|adding|i('ll| will) add|i('ve| have) (added|put)|putting)\b[^.?!]*\b(grocery|shopping) list\b", re.I),
    "check_todo": re.compile(r"\b(ticked|checked|crossed|marked)\b[^.?!]*\boff\b", re.I),
    "lock_screen": re.compile(r"\b(i('ve| have)? locked|locked (it|the laptop|your laptop|the screen)|"
                              r"locking (it|the laptop|your laptop|the screen))\b", re.I),
    # "I'll open a search for cute dog photos" after a failed tool call: nothing was opened
    "open_website": re.compile(r"\bi('ll| will| am going to|'m going to) (open|search|pull up|bring up|show)\b|"
                               r"\b(i('ve| have) )?(opened|pulled up)\b|^\W*(opening|searching|pulling up)\b", re.I),
    # "Checking the latest status of the code change for san-ai..." with nothing called
    "code_change_status": re.compile(r"\b(let me check|checking|i'?ll check)\b[^.?!]*\b(claude|code|change)\b", re.I),
}
# Clear requests for those actions; if the reply neither used the tool nor asked a question, nudge
INTENTS = {
    "forget": re.compile(r"^\W*(please\s+|can you\s+|could you\s+)*forget\b", re.I),
    "cancel_reminder": re.compile(r"\b(cancel|delete|remove)\b.*\breminder\b", re.I),
    "set_reminder": re.compile(r"\bremind me\b", re.I),
    "remember": re.compile(r"^\W*(please\s+|can you\s+)*remember\s+(that|my|this)\b", re.I),
    "open_website": re.compile(r"\b(show|open|pull up|bring up|search|look up|find|google)\b.*"
                               r"\b(photos?|pictures?|pics?|images?|wallpapers?|website|site|web ?page)\b", re.I),
    # "text alex on whatsapp I'm running late": the model once answered as if reading a message
    # (needs a name and some message words; "text alex" alone may fairly get "what should I say?")
    "phone_message": re.compile(r"^\W*(please\s+|can you\s+|could you\s+)*(text|message|whatsapp|sms)\s+(?!me\b)\w+(\s+\S+){2,}", re.I),
    # "what does this error mean?": the model asked "what does the error say?" instead of looking
    "read_screen": re.compile(r"\b(this|that) (error|message|page|window|warning|popup|pop-up|dialog)\b|\bon (my|the) screen\b|"
                              r"\bread (my|the) screen\b|\bwhat am i looking at\b", re.I),
    # Found by the command accuracy test (evals/commands.yaml): the model answered without acting
    "volume": re.compile(r"^\W*(mute|unmute)\b|\b(volume (up|down)|louder|quieter|turn (it|the volume|the sound) (up|down))\b", re.I),
    "media_control": re.compile(r"\b(skip|next) (this |the )?(song|track)\b|\b(previous|last) (song|track)\b|"
                                r"\b(pause|resume|stop) (the )?(music|song|spotify)\b", re.I),
    "email_digest": re.compile(r"\b(email|send) me (my|the|today'?s)? ?(summary|digest|day)\b", re.I),
    "add_event": re.compile(r"\b(add|put|schedule)\b.+\b(to|on|in) my calendar\b", re.I),
    "add_todo": re.compile(r"\b(add|put)\b.+\b(to|on) (my|the) (to-?do )?list\b", re.I),
    "add_groceries": re.compile(r"\b(add|put)\b.+\b(to|on) (my|the|our) (grocery|shopping) list\b", re.I),
    "phone_email": re.compile(r"^\W*(please\s+|can you\s+)*(email|e-mail)\s+(?!me\b)\w+(\s+\S+){2,}", re.I),
    "find_files": re.compile(r"\bopen my (resume|cv|report|essay|thesis|cover letter|transcript)\b|"
                             r"\bfind (my|the) .*\b(file|pdf|doc|document|presentation|spreadsheet)\b", re.I),
    "mail_check": re.compile(r"\b(check|any new|anything new in|read me) (my |new )?(e-?mails?|mail|inbox|gmail)\b|"
                             r"\bdid i get any (e-?mails?|mail)\b", re.I),
    "code_change_status": re.compile(r"\b(status|updates?|progress)\b.{0,40}\bclaude\b|\bclaude\b.{0,40}\b(status|progress|doing)\b", re.I),
}
# Requests that already contain everything the tool needs: a question back doesn't excuse skipping it
COMPLETE_INTENTS = {"phone_message", "read_screen", "volume", "media_control", "email_digest", "add_event", "add_todo",
                    "phone_email", "find_files", "cancel_reminder", "mail_check", "code_change_status"}
# ...but only when they say which: "cancel my reminder" alone may fairly get "which one?"
COMPLETE_ONLY_IF = {"cancel_reminder": re.compile(r"\breminders? (about|for|to)\s+\w+", re.I)}
# Details the model drops but the user clearly said: "search YouTube for lofi" -> site=youtube
SITE_WORDS = re.compile(r"\b(youtube|amazon|reddit|github|wikipedia|ebay|netflix|spotify)\b", re.I)


def repair_args(name: str, args: dict, user_text: str) -> dict:
    if name == "media_control":
        if re.search(r"\b(skip|next)\b", user_text, re.I):
            args = {**args, "action": "next"}
        elif re.search(r"\b(previous|go back|last (song|track))\b", user_text, re.I):
            args = {**args, "action": "previous"}
    if name == "open_website" and not args.get("site"):
        m = SITE_WORDS.search(user_text)
        target = str(args.get("target", "")).lower()
        if m and not re.match(r"^(https?://)?[\w-]+(\.[\w-]+)+", target) and m.group(1).lower() not in target.split(".")[0]:
            args = {**args, "site": m.group(1).lower()}
            if args.get("section") == "videos":
                args.pop("section")
    return args
# Sanae's Chrome window is on the laptop: from the phone, pages are opened on the phone instead
PHONE_NOTE = ("(Sent from the user's phone. Apps on the phone: phone_open_app (and the other phone_ tools for calls, "
              "texts, alarms, maps, music). Websites, searches and videos: open_website, which opens them on the phone "
              "(e.g. 'open youtube' = open_website youtube.com; 'play lofi on youtube' = open_website target 'lofi' site 'youtube'). "
              "open_app only for apps on the laptop the user names.)")
PHONE_BROWSER = ("The user is on their phone and can't see the laptop's browser. To show them a page, a search or "
                 "images, call open_website: it opens on their phone.")
# "forget ..." goes straight to the forget tool: the model was unreliable here, and forgetting
# always asks the user to confirm, so a wrong match is harmless
FORGET = re.compile(r"^\W*(?:please\s+|can you\s+|could you\s+|(?:sanae|max),?\s+)*forget\s+"
                    r"(?:about\s+|that\s+|what i (?:told|said to) you about\s+|the\s+)?(.+?)[.?!]*$", re.I)
NOTES_STOP = re.compile(r"\b(stop|end|finish)\s+(taking\s+)?(the\s+)?(notes|recording|note[- ]taking)\b|"
                        r"\b(the\s+)?(meeting|lecture|class|call)\s+(is\s+)?(over|done|finished|ended)\b", re.I)
NOTES_START = re.compile(r"\btake\s+(some\s+)?notes\b|\b(start|begin)\s+(taking\s+|recording\s+)?(the\s+)?notes\b|"
                         r"\brecord\s+(this|the|my)\s+(lecture|class|meeting|call|session|talk)\b|"
                         r"\bnotes\s+(for|on|of|during)\s+(this|the|my)\s+\w*\s*(lecture|class|meeting|call)\b", re.I)
# "summarise every file in my course folder": the model guessed file names instead of using the tool
SUMMARIZE_ALL = re.compile(r"\b(summari[sz]e|sum up|(make|write|take)\s+(study\s+)?notes)\b(?=.*\b(each|every|all|everything)\b)"
                           r"(?=.*\b(course|class|[a-z]{2,4}\s?\d{3})\b)(?=.*\b(files?|pdfs?|slides?|documents?|docs|readings?|"
                           r"handouts?|folder|material)\b)", re.I)
# "one summary of all my CS 102 slides", "summarise them all at once": one combined note
COMBINE = re.compile(r"\b(one|single|combined?|merged?|overall|unified)\s+(\w+\s+){0,2}(summary|summaries|notes?)\b|"
                     r"\b(at once|together|into one|in one go)\b", re.I)
SUMMARY_WORDS = re.compile(r"\bsummar|\bnotes?\b", re.I)
COURSE_DOCS = re.compile(r"(?=.*\b(course|class|[a-z]{2,4}\s?\d{3})\b)(?=.*\b(files?|pdfs?|slides?|documents?|docs|"
                         r"readings?|handouts?|folder|material)\b)", re.I)
COURSE_CODE = re.compile(r"\b([a-z]{2,4})\s?(\d{3})\b", re.I)
MEETING_WORDS = re.compile(r"\b(meeting|zoom|teams|call|google meet|webex|video|webinar|stream)\b", re.I)


# "not now" / "quiet for an hour": she stops talking first for a while (tools/companion.py)
QUIET = re.compile(r"^\W*(?:not now|shh+|hush|be quiet|quiet|stop interrupting|leave me alone)"
                   r"(?:\s+(?:for|until)\s+(an?|one|half an|\d+)\s*(hours?|hrs?|minutes?|mins?))?"
                   r"\W*(?:please|for a bit|for a while)?\W*$", re.I)


# the avatar: "hide" / "go away for a bit" / "come back" (the model tended to just say "okay")
HIDE = re.compile(r"^\W*(?:(?:please|can you|could you|sanae,?)\s+)*(?:hide(?: yourself)?|go hide|go away|disappear|"
                  r"get off (?:my|the) screen)\W*(?:please|for a (?:bit|while|sec(?:ond)?))?\W*$", re.I)
SHOW = re.compile(r"^\W*(?:(?:please|hey|sanae,?)\s+)*(?:come back(?: out)?|show yourself|where are you|"
                  r"you can come back(?: now)?)\W*(?:please|now)?\W*$", re.I)


def quiet_minutes(m: re.Match) -> float:
    amount, unit = m.group(1), m.group(2)
    if not unit:
        return 60
    n = 0.5 if amount.lower() == "half an" else 1 if amount.lower() in ("a", "an", "one") else float(amount)
    return n * (60 if unit.lower().startswith("h") else 1)


# Study sessions, games and "what song is this": the 4b model chatted about them instead of calling
# the tool ("Let's go! I'll stay quiet...", then made up "25 minutes left"), so clear phrasings go
# straight to the tool
STUDY_START = re.compile(r"\b(study with me|let'?s study|start (a )?(study|pomodoro|focus) (session|timer)|pomodoro|"
                         r"help me (focus|study))\b", re.I)
STUDY_STOP = re.compile(r"\b(stop studying|(i'?m )?done studying|end (the |our )?(study )?session|stop the (session|pomodoro))\b", re.I)
STUDY_STATUS = re.compile(r"\b(how (long|much time)( is)? left|when'?s (the|my|our) break|how long until (the )?break)\b", re.I)
STUDY_LENGTH = re.compile(r"\bfor (an?|one|half an|\d+(?:\.\d+)?) ?(hours?|hrs?|minutes?|mins?)\b", re.I)
STUDY_TOPIC = re.compile(r"\b(?:on|through|for|studying|study) ((?!an? |one |half |\d)(?:[a-z0-9+#.-]+ ?){1,4})\s*$", re.I)
PLAY_20Q = re.compile(r"\b(play )?(20|twenty) questions\b", re.I)
PLAY_TRIVIA = re.compile(r"\b(quiz me|play trivia|trivia (game|time|night)|let'?s (do|play) (some )?trivia)(?: (?:on|about) (?P<topic>.+?))?[.!?]*$", re.I)
PLAY_WYR = re.compile(r"\b(play|let'?s (do|play)|game of) would you rather\b", re.I)
WHAT_SONG = re.compile(r"\b(what('?s| is) (this|that) song|what song is (this|playing)|who sings (this|that)|"
                       r"what am i listening to)\b", re.I)


def study_args(text: str) -> dict:
    m = STUDY_LENGTH.search(text)
    minutes = 60.0
    if m:
        amount, unit = m.group(1).lower(), m.group(2).lower()
        n = 0.5 if amount == "half an" else 1.0 if amount in ("a", "an", "one") else float(amount)
        minutes = n * (60 if unit.startswith("h") else 1)
    rest = STUDY_LENGTH.sub("", text).strip(" ,.!?")
    t = STUDY_TOPIC.search(rest)
    topic = t.group(1).strip() if t and not re.match(r"(?i)(me|with me|a bit|now|a while|it)$", t.group(1).strip()) else ""
    return {"minutes": minutes, "topic": topic}


from .timesense import part_of_day  # noqa: E402  (kept importable from here)
# A request that's (mostly) a greeting: it gets a note on which greeting fits the hour
GREETS = re.compile(r"^\W*(?:(?:good )?(?:morning|mornin'?|afternoon|evening|night)|hi+|hey+|hello|heya|yo|sup|"
                    r"what'?s up|i'?m (?:up|awake|back)|g'?night|gm)\b", re.I)


# "Can you lock my laptop?" -> "Locking the laptop now, just say the word!", "Yes." -> "Locked and
# loaded!" and "put my laptop to sleep" -> "Sleeping mode activated!": no tool was called (from the phone)
_PC = r"(?:my |the |this )?(?:laptop|computer|pc|desktop|windows)"
NOT_ASKING_HOW = r"^(?!.*\b(?:how (?:do|can|to)|why (?:does|did|is)|does it|what happens)\b)"
LOCK_PC = re.compile(NOT_ASKING_HOW + rf".*\block (?:up )?{_PC}\b|^\W*(?:please |can you |could you )*lock (?:it|the screen)(?: please)?\W*$",
                     re.I)
POWER_PC = re.compile(NOT_ASKING_HOW + rf".*\b(?:(?:put|send) {_PC} to sleep|sleep {_PC}|{_PC} to sleep|"
                      rf"(?P<shut>shut ?down|turn off|power off) {_PC}|(?P<restart>restart|reboot) {_PC})\b", re.I)


def part_route(user_text: str, registry, last_reply: str = "") -> tuple[str, dict] | None:
    """The friendship parts' own routes (weekend plans, cooking, ... part.Part.route), first match wins,
    only to a tool that's registered."""
    for part in getattr(registry.context, "parts", None) or []:
        try:
            found = part.route(user_text, last_reply) if hasattr(part, "route") else None
        except Exception as exc:
            log.warning("route of %s failed: %s", getattr(part, "name", part), exc)
            continue
        if found and found[0] in registry.tools:
            return found
    return None


def direct_route(user_text: str, tools, last_reply: str = "", studying: bool = False,
                 chores=None) -> tuple[str, dict] | None:
    """Requests the small model handled unreliably (claimed actions it didn't take), mapped straight
    to their tool. Each is safe to run without the model: forget confirms, notes can be stopped.
    `last_reply`: her previous reply ("yes" to her breathing offer starts the exercise; the model
    recited the steps instead). `studying`: a study session is on ("how long left" means it)."""
    text = user_text.strip()
    if "lock_screen" in tools and LOCK_PC.search(text):
        return "lock_screen", {}
    if "power" in tools and (m := POWER_PC.search(text)):
        return "power", {"action": "shutdown" if m.group("shut") else "restart" if m.group("restart") else "sleep"}
    if "start_study" in tools and not studying and STUDY_START.search(text):
        return "start_study", study_args(text)
    if "stop_study" in tools and studying and STUDY_STOP.search(text):
        return "stop_study", {}
    if "study_status" in tools and studying and STUDY_STATUS.search(text):
        return "study_status", {}
    if "play_game" in tools:
        if PLAY_20Q.search(text):
            return "play_game", {"kind": "twenty_questions", "topic": ""}
        if (m := PLAY_TRIVIA.search(text)) and not re.search(r"\bjapanese\b", text, re.I):   # japanese.py's quiz
            return "play_game", {"kind": "trivia", "topic": (m.group("topic") or "").strip()}
        if PLAY_WYR.search(text):
            return "play_game", {"kind": "would_you_rather", "topic": ""}
    if "morning_briefing" in tools:
        from .briefing import ASK, DAY_ASK, WEATHER_ASK

        if ASK.search(text):
            return "morning_briefing", {}
        if "weather" in tools and WEATHER_ASK.search(text):
            return "weather", {}
        if "day_summary" in tools and DAY_ASK.search(text):
            return "day_summary", {}
    if "canvas_due" in tools:
        from .canvas import canvas_route

        if route := canvas_route(text):
            return route
    if "valorant_games" in tools:
        from .valorant import LAST_GAME

        if LAST_GAME.search(text) and not re.search(r"\bleague\b", text, re.I):
            n = re.search(r"\blast (\d+|two|three|four|five|ten) (games|matches)\b", text, re.I)
            words = {"two": 2, "three": 3, "four": 4, "five": 5, "ten": 10}
            count = (int(n.group(1)) if n.group(1).isdigit() else words[n.group(1).lower()]) if n else 1
            if count == 1 and re.search(r"\b(how have i been|my rank|how'?s my rank)\b", text, re.I):
                count = 5
            return "valorant_games", {"games": count}
    if "health_today" in tools:
        from .health import ASK_HEART, ASK_SLEEP, ASK_STEPS

        if ASK_SLEEP.search(text):
            return "health_today", {"what": "sleep"}
        if ASK_STEPS.search(text):
            return "health_today", {"what": "steps"}
        if ASK_HEART.search(text):
            if "heart_rate_now" in tools and not re.search(r"\b(resting|last night|today|average)\b", text, re.I):
                return "heart_rate_now", {}
            return "health_today", {"what": "heart"}
    if "list_activities" in tools:
        from .together import together_route

        if route := together_route(text):
            return route
    if "routine_today" in tools:
        from .chores import chore_route

        if route := chore_route(text, chores):
            return route
    if "list_todos" in tools:
        from .todos import todo_route

        if route := todo_route(text):
            return route
    if "what_song" in tools and WHAT_SONG.search(text):
        return "what_song", {}
    if "end_game" in tools and re.match(r"(?i)\s*(ok(ay)?,? )?(stop|end|quit) (the |this )?game\b", text):
        return "end_game", {}
    if "breathing_exercise" in tools and re.search(r"\bbreath", last_reply or "", re.I) \
            and (parse_yes_no(text) or re.search(r"\blet'?s (do|try) (it|that)\b", text, re.I)):
        return "breathing_exercise", {}
    if "quiet_for" in tools and (m := QUIET.match(text)):
        return "quiet_for", {"minutes": quiet_minutes(m)}
    if "hide_avatar" in tools and HIDE.match(text):
        return "hide_avatar", {}
    if "show_avatar" in tools and SHOW.match(text):
        return "show_avatar", {}
    if "forget" in tools and (m := FORGET.match(text)):
        return "forget", {"what": m.group(1)}
    if "stop_notes" in tools and NOTES_STOP.search(text):
        return "stop_notes", {}
    if "start_notes" in tools and NOTES_START.search(text):
        return "start_notes", {"kind": "meeting" if MEETING_WORDS.search(text) else "lecture"}
    combine = bool(COMBINE.search(text) and SUMMARY_WORDS.search(text) and COURSE_DOCS.match(text))
    if "summarize_course_files" in tools and (combine or SUMMARIZE_ALL.search(text)):
        code = COURSE_CODE.search(text)
        args = {"course": f"{code.group(1).upper()} {code.group(2)}" if code else ""}
        return "summarize_course_files", {**args, "combine": True} if combine else args
    return None


def parse_yes_no(text: str | None) -> bool:
    """Only an unambiguous yes counts. Silence or mixed answers are a no."""
    if not text:
        return False
    return bool(YES.search(text)) and not NO.search(text)


def strip_thinking(text: str) -> str:
    """Remove Qwen3 reasoning. Ollama sometimes leaks it with only the closing tag
    (the opening <think> lives in the prompt template), so drop everything up to
    the last </think>, and anything after an unclosed <think>."""
    text = text or ""
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    text = re.sub(r"<think>.*", "", text, flags=re.S)
    return text.strip()


class Agent:
    def __init__(
        self,
        llm: OllamaClient,
        registry: ToolRegistry,
        fast_model: str,
        planner_model: str,
        name: str = "Sanae",
        user_name: str = "there",
        max_steps: int = 6,
        confirm_risky: bool = True,
        confirm: Callable[[str], bool] | None = None,
        on_event: Callable[[str, dict], None] | None = None,
        history_turns: int = 6,
        history_ttl_s: float = 300,
        history_chars: int = 4000,
        recall: Callable[[str], str | None] | None = None,
        on_turn: Callable[[str, str, list[str]], None] | None = None,
        tool_selector=None,
        persona=None,
        notes: Callable[[str], list[str]] | None = None,
        conversation: Conversation | None = None,
        in_character: bool = True,
    ):
        self.llm = llm
        self.registry = registry
        self.fast_model = fast_model
        self.planner_model = planner_model
        self.name = name
        self.user_name = user_name
        self.max_steps = max_steps
        self.confirm_risky = confirm_risky
        self.confirm = confirm or (lambda prompt: False)
        self.on_event = on_event or (lambda kind, data: None)
        # The chat so far (conversation.py): one entry per turn with the user message, any tool
        # calls/results and the reply, plus a running summary of older turns. Keeping the tool
        # calls matters: with text-only history the model starts imitating "just answer" turns
        # and claims actions it never performed.
        self.conv = conversation or Conversation(verbatim_turns=history_turns, verbatim_chars=history_chars,
                                                 verbatim_min=history_ttl_s / 60)
        self.tool_selector = tool_selector    # toolselect.ToolSelector: only the tools a request needs
        self.busy = False                     # answering right now (the summary waits)
        self.in_character = in_character     # with a persona: tool results are said in her words
        self.recall = recall          # relevant saved facts for a request (memory), or None
        self.on_turn = on_turn        # called after each turn: (user_text, answer, tools used)
        self.persona = persona        # persona.Persona: her character, tags in replies; None = plain assistant
        self.notes = notes            # per-request hints (her mood, how the user sounds, what's on screen)
        self.embed = None             # text -> vectors, to guess an emotion when a reply has no tag
        self.last_tags = None         # tags.Tagged of the last reply
        self.last_tools: list[str] = []   # tools the last request used
        self.calm = None              # (emotion, gestures) -> toned down while they're not okay (comfort.py)
        self.after_reply = None       # (user_text, answer) -> a sentence to add, or None (comfort.py)
        self.guests = None            # guests.Guests: messages typed as "... ~Name" are from someone else

    def _system(self) -> dict:
        if self.persona is not None:
            content = self.persona.prompt(self.user_name) + "\n" + PERSONA_RULES.format(user=self.user_name)
        else:
            content = SYSTEM_PROMPT.format(name=self.name, user=self.user_name)
        if not getattr(self.llm, "think", False):
            # Qwen3 soft switch; Ollama's think=false alone still leaks reasoning after tool calls
            content += "\n/no_think"
        return {"role": "system", "content": content}

    @property
    def history(self) -> list[list[dict]]:
        return self.conv.turns

    @history.setter
    def history(self, turns: list[list[dict]]):
        self.conv.turns, self.conv.times = turns, []

    @property
    def _last_turn(self) -> float:
        return self.conv.last

    @_last_turn.setter
    def _last_turn(self, _value: float):
        self.conv.touch()                     # something was just said

    def _recent_history(self) -> list[dict]:
        return self.conv.recent()

    def add_said(self, text: str, why: str = "Nothing was asked; you said this yourself"):
        """Something she said on her own (a reminder going off, notes ready) is part of the chat too,
        so "thanks" or "wait, what time?" right after makes sense to her."""
        from .timesense import fix, stamp as time_stamp

        d = dt.datetime.now()
        stamp = time_stamp(d)
        text = fix(text, d)
        self.conv.add([{"role": "user", "content": f"[{stamp}] ({why}.)"}, {"role": "assistant", "content": text}])

    @staticmethod
    def _for_history(msg: dict, limit: int = 240) -> dict:
        """Tool results can be long (web pages); history only needs the gist."""
        content = str(msg.get("content", ""))
        if msg.get("role") == "tool" and len(content) > limit:
            return {**msg, "content": content[:limit].rsplit(" ", 1)[0] + " …"}
        return msg

    def handle(self, user_text: str, on_text=None, guest: str | None = None) -> str:
        """`on_text(piece)` streams the model's words as they're written (`None` marks a new
        model call); voice mode speaks the first sentence while the rest is still coming.
        `guest`: the message is from that person, not the user (guests.py): their own chat and
        a few harmless tools; nothing from it reaches the user's chat, memory or mood."""
        from .timesense import TimeFilter, fix as fit_time, greeting_note, stamp

        self.last_tags = None                 # a reply without tags (direct tools) has no face of its own
        heard = getattr(self.llm, "heard", None)
        if callable(heard):                   # Claude as her mind: "a secret between us" keeps this local
            heard(user_text)
        d = dt.datetime.now()
        content = f"[{stamp(d)}] {user_text}"
        if GREETS.match(user_text):
            content += f"\n({greeting_note(d)})"
        if on_text is not None:
            on_text = TimeFilter(on_text)     # "good morning" at 1 PM is swapped before it's spoken
        visitor = self.guests.get(guest) if guest and self.guests is not None else None
        if visitor is not None:
            history = self.guests.history(visitor, d)
            content += f"\n({self.guests.note(visitor, d)})"
        else:
            history = self._recent_history()
            if self.guests is not None and any(self.guests.SEEN in str(m.get("content", "")) for m in history[-4:]):
                content += f"\n(This message is from {self.guests.user} again, not the person before)"
            earlier = self.conv.note()
            if earlier:
                content += f"\n({earlier})"
            memories = self.recall(user_text) if self.recall else None
            if memories:
                # In the user message, not the system prompt, so the cached prompt prefix still matches
                content += f"\n(You remember: {memories})"
            try:
                for n in (self.notes(user_text) if self.notes else []):
                    content += f"\n({n})"
            except Exception as exc:                  # never let a hint break a request
                log.debug("request notes failed: %s", exc)
        vision = getattr(self.registry.context, "vision", None)
        if vision is not None:                    # a photo they sent (just now, or a few minutes ago)
            from .vision import PHOTO_TAG

            seen = vision.note(fresh=user_text.startswith(PHOTO_TAG))
            if seen:
                content += f"\n({seen})"
        if current_origin() == "phone":
            content += f"\n{PHONE_NOTE}"
            call = getattr(self.registry.context, "call", None)
            if call is not None and call.note():
                content += f"\n({call.note()})"
        user_msg = {"role": "user", "content": content}
        messages = [self._system(), *history, user_msg]
        turn_start = len(messages) - 1
        nudged = visitor is not None          # no "call the tool now" checks: they only have a few tools
        model = self.fast_model
        self._user_text = user_text
        names = self.guests.tools(self.registry.tools) if visitor is not None else self._tool_names(user_text)
        tools = self.registry.schemas(names) + [ESCALATE_TOOL]
        answer = None
        after = ""                            # Claude's line for when its tool calls succeed (claudemind.py)
        self.busy = True

        try:
            last = self.history[-1][-1] if self.history and self.history[-1] else {}
            recent = time.time() - self.conv.last < 600 and last.get("role") == "assistant"
            study = getattr(self.registry.context, "study", None)
            studying = bool(study and study.session and study.session.phase != "done")
            route = None
            routines = getattr(self.registry.context, "routines", None)
            if visitor is not None:
                pass                                  # no shortcuts to the user's tools
            elif routines is not None and "run_routine" in self.registry.tools:
                found = routines.match(user_text)        # "goodnight", "gaming time": before the study / quiet routes
                route = ("run_routine", {"name": found.name}) if found else None
            if route is None and visitor is None:
                route = direct_route(user_text, self.registry.tools, str(last.get("content", "")) if recent else "", studying,
                                     getattr(self.registry.context, "chores", None))
            if route is None and visitor is None and "code_change" in self.registry.tools:
                from .tools.code import code_route

                said = (str(self.history[-1][0].get("content", "")) if self.history and self.history[-1] else "")
                route = code_route(user_text, self.registry.context,
                                   (said + "\n" + str(last.get("content", ""))) if recent else "")
            if route is None and visitor is None:
                route = part_route(user_text, self.registry, str(last.get("content", "")) if recent else "")
            if route:
                name, args = route
                self.on_event("thinking", {"model": "direct", "step": 0})
                messages.append({"role": "assistant", "content": "",
                                 "tool_calls": [{"function": {"name": name, "arguments": args}}]})
                result = self._run_call(name, args, model)
                messages.append({"role": "tool", "content": result, "tool_name": name})
                answer = "Okay, I won't." if result == DECLINED else result
            for step in range(0 if route else self.max_steps):
                self.on_event("thinking", {"model": model, "step": step})
                stream = self._stream_for(on_text, user_text, messages[turn_start:])
                if stream is not None:
                    stream(None)
                try:
                    reply = self.llm.chat(model, messages, tools, **({"on_text": stream} if stream else {}))
                except OllamaError as exc:
                    if "context" not in str(exc) or turn_start <= 1:
                        raise
                    # Too big for the model's window: drop the earlier conversation and try once more
                    log.warning("prompt too long; retrying without the earlier conversation")
                    messages = [messages[0], *messages[turn_start:]]
                    turn_start = 1
                    reply = self.llm.chat(model, messages, tools, **({"on_text": stream} if stream else {}))

                if not reply.tool_calls:
                    answer = strip_thinking(reply.content)
                    claimed = self._false_claim(answer, messages[turn_start:], user_text)
                    if claimed and not nudged:
                        # The small model sometimes says "I've forgotten that" without calling
                        # the tool, so nothing happened. Tell it so, once.
                        nudged = True
                        log.info("reply claims %s without calling it; nudging", claimed)
                        if names is not None and claimed not in names:      # make sure it can call it now
                            names += [t for t in self.tool_selector.members(self.tool_selector.family(claimed)) if t not in names] or [claimed]
                            tools = self.registry.schemas(names) + [ESCALATE_TOOL]
                        messages += [{"role": "assistant", "content": answer},
                                     {"role": "user", "content": f"(System check: you said that, but you didn't call "
                                      f"the {claimed} tool, so nothing actually happened. Call {claimed} now; it looks things up "
                                      f"itself, even if you don't see the item in this conversation.)"}]
                        continue
                    ran = any(m.get("tool_calls") for m in messages[turn_start:])
                    if stream is None and not nudged and not ran and ACTED.search(answer):
                        # (a streamed reply has already been spoken: there the rule in the prompt has to do)
                        nudged = True
                        log.info("reply claims something done with no tool behind it; asking again")
                        messages += [{"role": "assistant", "content": answer},
                                     {"role": "user", "content": "(System check: no tool ran this turn, so you didn't do "
                                      "that. Reply again without saying you did it: use a tool if you have one for it, "
                                      "or just offer.)"}]
                        continue
                    break

                after = str((reply.raw or {}).get("after") or "")
                messages.append({
                    "role": "assistant",
                    "content": strip_thinking(reply.content),
                    "tool_calls": [{"function": {"name": c.name, "arguments": c.arguments}}
                                   for c in reply.tool_calls],
                })

                spoken: list[str] | None = []   # finished replies, while every call is a direct tool
                for call in reply.tool_calls:
                    result = self._run_call(call.name, call.arguments, model)
                    if result == "__ESCALATE__":
                        model = self.planner_model
                        tools = self.registry.schemas(names)
                        result = "You are now the larger model. Solve the user's request directly."
                    messages.append({"role": "tool", "content": result, "tool_name": call.name})
                    if spoken is not None:
                        spoken = self._direct_reply(call.name, result, spoken)

                pending = self._pending_intent(user_text, messages[turn_start:]) if spoken and not nudged else None
                if pending:
                    # e.g. "email me my summary" ran the spoken summary: the email still hasn't gone
                    nudged = True
                    log.info("direct reply but %s was asked for and not called; nudging", pending)
                    if names is not None and pending not in names:
                        names += [t for t in self.tool_selector.members(self.tool_selector.family(pending)) if t not in names] or [pending]
                        tools = self.registry.schemas(names) + [ESCALATE_TOOL]
                    messages.append({"role": "user", "content": f"(System check: the user asked for {pending}, which "
                                     f"hasn't been called yet. Call {pending} now.)"})
                    continue
                if spoken and not COMPOUND.search(user_text):
                    # Tool results are already the answer ("Opened Spotify."): with a persona she says
                    # it in her own words (one quick call, same prompt so it's cached); else as is
                    plain = " ".join(spoken)
                    said = self._kept_facts(plain, strip_thinking(after)) if after else None
                    answer = said or self._in_her_words(model, messages, tools, plain) or plain
                    self.on_event("direct_reply", {"text": answer})
                    break
            else:
                if not route:
                    answer = "Sorry, I got stuck on that one. Could you rephrase it?"
        except OllamaError as exc:
            log.error("LLM error: %s", exc)
            answer = str(exc)
        finally:
            self.busy = False

        answer = fit_time(answer or "Done.")
        if self.after_reply is not None and visitor is None:
            try:
                extra = self.after_reply(user_text, answer)
            except Exception as exc:              # never let it break the reply
                log.debug("after_reply failed: %s", exc)
                extra = None
            if extra:
                answer = f"{answer.rstrip()} {extra}"     # spoken by the stream's finish() with the rest
        turn = [self._for_history(m) for m in messages[turn_start:]]
        if visitor is not None:
            self.guests.add(visitor, user_text, answer, d)      # their chat, not the user's
            # ...and one labelled line in the user's chat, so "who was that?" makes sense to her
            self.conv.add([{"role": "user", "content": f"[{stamp(d)}] {self.guests.seen(visitor, user_text)}"},
                           {"role": "assistant", "content": answer}])
        else:
            self.conv.add(turn + [{"role": "assistant", "content": answer}])   # with its tags: the model keeps the habit
        if self.persona is not None:
            answer = self._read_tags(answer)
        self.on_event("answer", {"text": answer, **({"guest": visitor.name} if visitor is not None else {})})
        tools_used = [c["function"]["name"] for m in turn for c in m.get("tool_calls", [])]
        self.last_tools = tools_used
        if self.on_turn and visitor is None:
            try:
                self.on_turn(user_text, answer, tools_used)
            except Exception as exc:          # logging a turn must never break the reply
                log.warning("turn logging failed: %s", exc)
        return answer

    def _read_tags(self, answer: str) -> str:
        """Take the emotion/gesture tags off the reply and tell the avatar; guess the emotion if missing."""
        from . import tags

        p = self.persona
        t = tags.parse(answer, p.emotions, p.gestures)
        source = "tag"
        if t.emotion is None:
            t.emotion = tags.guess(t.text, self.embed, p.emotion_prototypes() if self.embed else None)
            source = "guess"
        if self.calm is not None:
            t.emotion, t.gestures = self.calm(t.emotion, t.gestures)
        self.last_tags = t
        self.on_event("emotion", {"emotion": t.emotion, "gestures": t.gestures, "source": source})
        return t.text or answer

    def _false_claim(self, answer: str, turn: list[dict], user_text: str = "") -> str | None:
        """A tool the reply claims to have used, or the user clearly asked for, that wasn't
        called this turn (so nothing actually happened). None if all is well."""
        called = {c["function"]["name"] for m in turn for c in m.get("tool_calls", [])}
        for tool, pattern in CLAIMS.items():
            if tool not in called and tool in self.registry.tools and pattern.search(answer):
                return tool
        asking = answer.rstrip().endswith("?")   # asking for details is fine...
        for tool, pattern in INTENTS.items():
            if tool not in called and tool in self.registry.tools and pattern.search(user_text):
                if asking and not self._complete(tool, user_text):
                    continue
                return tool                      # ...unless the request already had everything needed
        return None

    def _tool_names(self, user_text: str) -> list[str] | None:
        """Tools to offer for this request (None = all), plus the ones used in the last two turns."""
        if self.tool_selector is None:
            return None
        recent = [c["function"]["name"] for t in self.history[-2:] for m in t for c in m.get("tool_calls", [])]
        names = self.tool_selector.select(user_text, recent)
        log.debug("tools offered: %s", names)
        return names

    @staticmethod
    def _complete(tool: str, user_text: str) -> bool:
        """The request already had everything the tool needs (no reason to ask back)."""
        if tool not in COMPLETE_INTENTS:
            return False
        extra = COMPLETE_ONLY_IF.get(tool)
        return extra is None or bool(extra.search(user_text))

    def _pending_intent(self, user_text: str, turn: list[dict]) -> str | None:
        """A complete, clear request whose tool this turn hasn't called (checked before a direct reply)."""
        called = {c["function"]["name"] for m in turn for c in m.get("tool_calls", [])}
        for tool, pattern in INTENTS.items():
            if tool not in called and tool in self.registry.tools and pattern.search(user_text) and self._complete(tool, user_text):
                return tool
        return None

    def _stream_for(self, on_text, user_text: str, turn: list[dict]):
        """Stream this model call only when nothing is likely to need correcting: not while a
        clear request (remember, remind, open...) is still waiting for its tool."""
        if on_text is None:
            return None
        called = {c["function"]["name"] for m in turn for c in m.get("tool_calls", [])}
        for tool, pattern in INTENTS.items():
            if tool not in called and tool in self.registry.tools and pattern.search(user_text):
                return None
        return on_text

    def _in_her_words(self, model: str, messages: list[dict], tools, plain: str) -> str | None:
        """The tool's plain result ("Okay, I'll remind you tomorrow at 7 PM: study.") said the way she
        talks. None (use the plain one) without a persona, for long results (lists), if she calls
        another tool, or if any time / date / number from the result went missing or changed."""
        if self.persona is None or not self.in_character or plain == "Okay, I won't." or len(plain) > 200:
            return None
        if getattr(self.registry.context, "models_asleep", False):
            return None                       # "go to sleep" / "gaming time" just freed the GPU: don't load it again
        try:
            reply = self.llm.chat(model, messages, tools)
        except OllamaError as exc:
            log.info("plain reply (%s)", exc)
            return None
        text = strip_thinking(reply.content)
        if reply.tool_calls or not text:
            return None
        return self._kept_facts(plain, text)

    @staticmethod
    def _kept_facts(plain: str, text: str) -> str | None:
        """`text` if every time / date / number in the tool's plain result is still in it."""
        def squash(t: str) -> str:
            return re.sub(r"\s+", "", t).lower()
        missing = [f for f in FACTS.findall(plain) if squash(f) not in squash(text)]
        if missing or not text:
            log.info("her words dropped %s; using the plain result", missing)
            return None
        return text

    def _direct_reply(self, name: str, result: str, spoken: list[str]) -> list[str] | None:
        """Add a tool's result to the spoken reply, or return None if the LLM must answer."""
        if result == DECLINED:
            return [*spoken, "Okay, I won't."]
        tool = self.registry.get(name)
        if tool is None or not tool.direct or result.startswith("Error") or isinstance(result, ForLLM):
            return None
        return [*spoken, result]

    def _run_call(self, name: str, args: dict, model: str) -> str:
        if name == "think_harder":
            if model == self.planner_model:
                return "You are already the larger model. Answer directly."
            self.on_event("escalate", {"to": self.planner_model})
            return "__ESCALATE__"

        tool = self.registry.get(name)
        if tool is None:
            return f"Error: there is no tool named {name}."

        if name.startswith("browser_") and current_origin() == "phone":
            log.info("tool %s skipped: phone command", name)
            return ForLLM(PHONE_BROWSER)

        if tool.risky and self.confirm_risky:
            prompt = tool.confirmation_prompt(args or {})
            self.on_event("confirm", {"tool": name, "args": args, "prompt": prompt})
            approved = self.confirm(prompt)
            self.on_event("confirm_result", {"tool": name, "approved": approved})
            if not approved:
                return DECLINED

        self.on_event("tool_call", {"tool": name, "args": args})
        args = repair_args(name, args or {}, getattr(self, "_user_text", ""))
        result = self.registry.run(name, args)
        self.on_event("tool_result", {"tool": name, "result": result})
        log.info("tool %s(%s) -> %s", name, args, result[:200])
        return result
