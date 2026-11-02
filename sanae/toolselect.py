"""Send the model only the tools a request needs.

With 49 tools the definitions alone took ~5,200 tokens, more than the model's whole 4,096-token
window (system prompt and conversation included), so Ollama refused requests. Doubling the
window would not fit the 4 GB GPU. Instead each request gets:

- a small core that is always there (open/search the web, open apps, the time),
- the tool families that match the request by meaning (bge-small embeddings, the same model
  memory uses) or by clear keywords ("my phone", "remind", "lecture slides"...),
- the families used in the last two turns, so follow-ups ("click the second one") still work.

A family travels together (all browser tools, all phone tools), because one step often leads
to the next.
"""
from __future__ import annotations

import logging
import re

import numpy as np

log = logging.getLogger(__name__)
CORE = ["open_website", "web_search", "open_app", "get_datetime"]

FAMILIES: dict[str, list[str]] = {
    "browser": ["browser_click", "browser_type", "browser_navigate", "browser_media", "browser_read", "browser_tabs"],
    "phone": ["phone_open_app", "phone_call", "phone_message", "phone_alarm", "phone_timer", "phone_navigate",
              "phone_play", "phone_email", "phone_notifications", "phone_status"],
    "memory": ["remember", "recall", "forget"],
    "reminders": ["set_reminder", "list_reminders", "cancel_reminder"],
    "events": ["add_event", "list_events", "cancel_event"],
    "todos": ["add_todo", "list_todos", "check_todo", "clear_todos"],
    "chores": ["add_routine_task", "routine_today", "check_routine_task", "remove_routine_task"],
    "canvas": ["canvas_due", "canvas_classes", "day_summary", "email_digest", "morning_briefing"],
    "weather": ["weather"],
    "backup": ["backup_status", "backup_now"],
    "watchlist": ["what_to_watch", "add_to_watchlist", "drop_from_watchlist", "watchlist", "watch_history", "rate_movie",
                  "movie_log"],
    "dailyphoto": ["daily_photo"],
    "gooddays": ["good_days", "month_wrapped"],
    "playlist": ["our_playlist", "add_to_playlist", "play_playlist", "remove_from_playlist", "song_of_the_week"],
    "routines": ["run_routine"],
    "league": ["league_games", "valorant_games"],
    "health": ["health_today", "heart_rate_now"],
    "goals": ["list_goals", "add_goal", "goal_done", "drop_goal", "list_activities", "add_activity", "activity_done",
              "drop_activity", "list_promises"],
    "us": ["weekend_plans", "plan_weekend", "add_weekend_plan", "drop_weekend_plan", "watch_history", "bucket_list",
           "add_to_bucket_list", "drop_from_bucket_list", "keep_photo", "bedtime_story"],
    "groceries": ["grocery_list", "add_groceries", "remove_groceries", "check_groceries", "clear_groceries",
                  "grocery_shopping", "grocery_ideas", "grocery_answer", "done_shopping", "groceries_used"],
    "japanese": ["japanese_lesson", "japanese_answer", "japanese_her_turn", "japanese_corrected", "japanese_stop"],
    "cooking": ["recreate_dish", "start_cooking", "cooking_step", "cooking_how_much", "cooking_timer", "cooking_timer_left", "stop_cooking",
                "list_recipes", "rate_recipe", "remove_recipe", "plan_meals", "meal_plan", "swap_meal",
                "meal_plan_groceries"],
    "notes": ["start_notes", "stop_notes", "meeting_notes"],
    "quick_notes": ["take_note", "read_notes"],
    "course": ["course_search", "course_files", "summarize_course_files"],
    "files": ["find_files", "open_file"],
    "system": ["close_app", "media_control", "volume", "system_status", "screenshot", "lock_screen", "power",
               "cancel_shutdown", "free_gpu"],
    "screen": ["read_screen"],
    "companion": ["quiet_for", "chat_again", "hide_avatar", "show_avatar"],
    "breathing": ["breathing_exercise"],
    "study": ["start_study", "stop_study", "study_status"],
    "games": ["play_game", "end_game"],
    "music": ["what_song"],
    "code": ["list_projects", "project_status", "project_running", "push_project", "code_change", "code_change_status",
             "approve_code_change", "reject_code_change"],
    "code_run": ["run_project", "stop_project", "pull_project"],
    "mail": ["mail_check", "mail_search", "mail_read", "mail_reply", "mail_send", "mail_archive", "mail_mark_read"],
}

KEYWORDS: dict[str, re.Pattern] = {
    "phone": re.compile(r"\b(my phone|on (the |my )?phone|phone'?s|text (him|her|them|mom|dad)|whatsapp|call\s+\w+|alarm|timer|"
                        r"wake me|notifications?|what did i miss|navigate|directions|take me to|battery|spotify|instagram|"
                        r"email \w+)\b", re.I),
    "memory": re.compile(r"\b(remember|forget|what do you know about|do you remember|my (name|birthday|sister|brother|mom|dad))\b", re.I),
    "reminders": re.compile(r"\bremind|reminders?\b", re.I),
    "events": re.compile(r"\b(calendar|events?|appointments?|what'?s on|am i (free|busy)|plans? (for|on)|"
                         r"anything (on|planned))\b", re.I),
    "todos": re.compile(r"\b(to-?dos?|to do list|my list|the list|on (my|the) list|off (my|the) list|shopping list|"
                        r"check (it |that )?off|tick (it |that )?off|cross (it |that )?off|still (need|have) to do|"
                        r"what do i (still )?(need|have) to do)\b", re.I),
    "chores": re.compile(r"\b(routine|chores?|every (day|morning|night|evening|week|month|monday|tuesday|wednesday|thursday|"
                         r"friday|saturday|sunday)|daily|weekly|monthly|week ?days|of (every|each) month|"
                         r"i (did|watered|took out|cleaned|paid|fed|finished)|forgot (to|the))\b", re.I),
    "goals": re.compile(r"\b(goals?|accountable|streaks?|habits?|daily list|our list|every ?day list|promised?|promises)\b", re.I),
    "us": re.compile(r"\b(weekend|saturday|sunday|watch(ed|ing)|episode|tv show|series|season|bucket ?list|scrap ?book|story|chapter)\b", re.I),
    "groceries": re.compile(r"\b(grocer\w*|shopping|supermarket|costco|walmart|trader joe'?s|(the|a) store|out of|"
                            r"running low|run out)\b", re.I),
    "watchlist": re.compile(r"\b(watch ?list|movie (night|log)|movies (we|i)|rate .{1,40} (stars?|/ ?10)|what (should|can) (we|i) watch|something to watch)\b", re.I),
    "dailyphoto": re.compile(r"\b(photo (challenge|of the day|a day)|daily (photo|picture))\b", re.I),
    "gooddays": re.compile(r"\b(good days?|happiest|at my best|patterns? in my|what helps my|wrapped|my month)\b", re.I),
    "playlist": re.compile(r"\bplaylist\b|\bour songs?\b|\bsong of the week\b", re.I),
    "backup": re.compile(r"\b(back ?ups?|backed up|back (it|everything|me) up)\b", re.I),
    "japanese": re.compile(r"\b(japanese|nihongo)\b", re.I),
    "cooking": re.compile(r"\b(cook\w*|recipe|bake|baking|kitchen|timer|next step|ingredients?)\b", re.I),
    "health": re.compile(r"\b(sleep|slept|steps|heart ?rate|pulse|bpm|resting hr|health)\b", re.I),
    "league": re.compile(r"\b(league|valorant|val|last (game|match)|my (games?|matches)|ranked|my rank|"
                         r"how did i (do|play)|kda|win ?rate)\b", re.I),
    "routines": re.compile(r"\b(routine|good ?night|bed ?time|going to bed|study time|gaming time|game time)\b", re.I),
    "weather": re.compile(r"\b(weather|temperature|forecast|rain(ing|y)?|hot|cold|degrees|umbrella|jacket)\b", re.I),
    "canvas": re.compile(r"\b(brief me|briefing|rundown|due|assignments?|homework|canvas|classes?|quiz|exam|deadline|my day|schedule|digest|summary|lab \d)\b", re.I),
    "notes": re.compile(r"\b(take notes|notes (on|for|of)|record (this|the)|lecture notes|meeting notes|stop (taking )?notes|"
                        r"key points|summar\w+ (of )?(the|my|today'?s) (lecture|meeting|class))\b", re.I),
    "quick_notes": re.compile(r"\b(take a note|note that|jot|my notes|read (my |the )?notes)\b", re.I),
    "course": re.compile(r"\b(professor|lecture|slides?|handout|reading|course (material|files|folder)|textbook|midterm|final|"
                         r"pdfs?|summari[sz]e (each|every|all|them|these|those)|notes (of|on|for) (each|every|all|them)|"
                         r"study guide|explain .* (from|in) (the )?(lab|class|lecture))\b", re.I),
    "files": re.compile(r"\b(find|open|where is) (the |my |a )?(file|pdf|document|report|docx|pptx|download|resume|cv|essay)", re.I),
    "system": re.compile(r"\b(volume|louder|quieter|mute|pause|next song|skip|shut ?down|restart|lock|sleep|close|"
                         r"screenshot|cpu|memory usage|free (the )?gpu|go to sleep)\b", re.I),
    "browser": re.compile(r"\b(click|tab|scroll|type|fill|page|video|play (the|it|that)|first (one|result)|second|third|"
                          r"go back|read (the|this) page)\b", re.I),
    "mail": re.compile(r"\b(e-?mails?|mail|inbox|gmail|unread|reply|replied|archive|mark (it|them|that) (as )?read)\b", re.I),
    "companion": re.compile(r"\b(not now|be quiet|quiet (for|until)|stop (interrupting|talking)|leave me alone|"
                            r"talk (to me )?again|you can talk|i'?m free now|hide|go away|come back|show yourself|"
                            r"where are you|off my screen)\b", re.I),
    "study": re.compile(r"\b(study|studying|pomodoro|focus (session|time|with me)|help me focus|how long (is )?left|"
                        r"when'?s (the|my) break)\b", re.I),
    "games": re.compile(r"\b(game|trivia|quiz me|20 questions|twenty questions|would you rather|i give up|"
                        r"play (something|a game))\b", re.I),
    "music": re.compile(r"\b(what('?s| is) (this|that) song|what song|who sings|what am i listening|this track|"
                        r"song (is )?(this|playing))\b", re.I),
    "breathing": re.compile(r"\b(breath\w*|calm (me )?down|relax|let'?s do (it|that)|okay,? sure|sure,? (let'?s|why not))\b", re.I),
    "code": re.compile(r"\b(repos?|repository|github|projects?|commits?|branch|pull requests?|prs?|issues?|ci|"
                       r"build (is )?(passing|failing|broken)|claude|code ?base|my code|dev server|localhost|port \d+|"
                       r"(is|it'?s) (it |\w+ )?(still )?running|crash(ed)?|push (it|that|the|my)|pull (the|my) (latest|repo)|"
                       r"merge (it|that|the change)|approve the change|reject (it|the change)|fix\w* (the |a |my |that )?(\w+ ){0,3}(bugs?|errors?|crash)|"
                       r"refactor|add (a )?feature)\b", re.I),
    "code_run": re.compile(r"\b((start|run|launch|stop|kill|restart) (the |my )?(\w+ )?(server|app|project|dev)|"
                           r"(start|run|stop|kill) [\w-]+ (up|again)|pull (the )?(latest|repo|changes)|"
                           r"(start|run|stop|kill|pull) (it|that))\b", re.I),
    "screen": re.compile(r"\b(on my screen|this (error|window|page|screen)|what am i looking at|read (my|the) screen)\b", re.I),
}


class ToolSelector:
    def __init__(self, registry, embedder=None, top_families: int = 3, min_score: float = 0.55, max_tools: int = 24):
        self.registry = registry
        self.embedder = embedder
        self.top_families = top_families
        self.min_score = min_score
        self.max_tools = max_tools          # ~3k tokens at most: room left for the conversation
        self._family_of = {t: f for f, ts in FAMILIES.items() for t in ts}
        self._names: list[str] = []
        self._vecs = None
        self.hints = None                   # (text) -> extra families, e.g. a project's name -> "code"

    def _ensure_vectors(self):
        names = list(self.registry.tools)
        if self._vecs is not None and names == self._names:
            return
        self._names = names
        if self.embedder is None:
            self._vecs = None
            return
        texts = [f"{n.replace('_', ' ')}: {self.registry.tools[n].description}" for n in names]
        self._vecs = np.asarray(self.embedder.embed(texts), dtype=np.float32)

    def family(self, tool: str) -> str:
        return self._family_of.get(tool, tool)

    def members(self, family: str) -> list[str]:
        return [t for t in FAMILIES.get(family, [family]) if t in self.registry.tools]

    def select(self, user_text: str, recent_tools: list[str] = ()) -> list[str]:
        """Tool names for this request (always a subset of the registry)."""
        available = set(self.registry.tools)
        families: list[str] = []
        families += [f for f, pat in KEYWORDS.items() if pat.search(user_text)]
        families += [self.family(t) for t in recent_tools]
        if self.hints is not None:
            try:
                families += list(self.hints(user_text))
            except Exception:
                log.debug("tool hints failed", exc_info=True)
        self._ensure_vectors()
        if self._vecs is not None and len(self._names):
            q = np.asarray(self.embedder.embed([user_text])[0], dtype=np.float32)
            scores = self._vecs @ q
            best: dict[str, float] = {}
            for name, s in zip(self._names, scores):
                fam = self.family(name)
                best[fam] = max(best.get(fam, -1.0), float(s))
            ranked = sorted(best.items(), key=lambda kv: -kv[1])
            families += [f for f, s in ranked[: self.top_families] if s >= self.min_score]
        chosen: list[str] = [t for t in CORE if t in available]
        for fam in dict.fromkeys(families):           # keep order (keywords, recent, meaning), drop repeats
            new = [t for t in self.members(fam) if t not in chosen]
            if chosen and len(chosen) + len(new) > self.max_tools:
                continue                              # a whole family or none: half a family confuses the model
            chosen += new
        return chosen
