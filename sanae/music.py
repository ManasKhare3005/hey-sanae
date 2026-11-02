"""What's playing: the title and artist Windows' media controls show (Spotify, YouTube in a browser,
anything that puts up the media overlay). She can say what song this is, and now and then
comment on what you're listening to.

Only the title, artist and whether it's playing are read, on demand, and kept in memory:
never saved, logged or sent to the phone (like window titles, window.py).
"""
from __future__ import annotations

import asyncio
import difflib
import logging
import re
import sys
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

# "how is the song?", "do you like this track?", "what do you think of what I'm listening to?"
SONG_TALK = re.compile(r"\b((this|that|the|current) (song|track|tune|music|beat|album)|"
                       r"what i'?m (listening to|playing)|(song|track|music) (i'?m|that'?s|is) playing)\b", re.I)
# They name it: "but I'm listening to X by Y", "no, it's X", "this is X by Y" (often misheard by Whisper)
SONG_NAMED = re.compile(r"\b(?:i'?m|i am) (?:actually |really )?(?:listening to|hearing) (?P<a>.+)|"
                        r"\b(?:i'?m|i am) (?:actually |really )?playing (?P<c>.+? by .+)|"
                        r"^(?:no,? |nope,? |actually,? )?(?:it'?s|this is|that'?s) (?:actually )?(?P<b>.+? by .+)", re.I)
NOT_A_SONG = re.compile(r"^(this|that|it|the|a|some|my|music|something|songs?|the song|this song|this track|"
                        r"what i'?m|you)\b", re.I)
CORRECTED_FOR_S = 600          # a correction sticks to that track this long
FOLLOW_UP_S = 300              # "who played guitar on it?" this soon after talking about a song = that song
SONG_FOLLOW = re.compile(r"\b(who (wrote|sang|sings|played|plays|produced|made)|when (was|did|came)|what album|"
                         r"which album|the (lyrics?|solo|guitar|guitarist|drums?|band|singer|album|chorus|meaning|story)|"
                         r"(about|on|in|behind) it|it about|its (lyrics|meaning|story)|was it|is it about)\b", re.I)


def named_song(user_text: str) -> tuple[str, str] | None:
    """(title, artist) they said, or None. 'Wildman guitars and cleaves by Beatles' -> ('Wildman guitars
    and cleaves', 'Beatles')."""
    m = SONG_NAMED.search(user_text.strip())
    if not m:
        return None
    said = (m.group("a") or m.group("b") or m.group("c") or "").strip(" .!?\"'")
    if not said or NOT_A_SONG.match(said):
        return None
    title, _, artist = said.partition(" by ")
    artist = re.sub(r"^the ", "", artist.strip(), flags=re.I)
    return title.strip(" \"'"), artist.strip()


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def sounds_like(said: str, title: str) -> float:
    """How well a misheard title matches a real one: spelling without spaces ('wildman guitars' vs
    'while my guitar') plus shared longer words."""
    ratio = difflib.SequenceMatcher(None, _squash(said), _squash(title)).ratio()
    words = lambda s: {w[:5] for w in re.findall(r"[a-z]{4,}", s.lower())}
    shared = len(words(said) & words(title))
    return ratio + 0.15 * shared


class RecentTracks:
    """The last few tracks Windows reported (memory only), polled every 20 s: the player may already
    show the next song, and Whisper mishears titles, so 'I'm listening to X' is matched against these."""

    def __init__(self, read=None, keep: int = 6, clock=time.time):
        self.read, self.keep, self.clock = read, keep, clock
        self.tracks: list[tuple[Track, float]] = []       # (cleaned track, last seen)
        self.corrected: dict[str, tuple[Track, float]] = {}   # what the player says -> what they said it is
        self.talked: tuple[Track, float] | None = None        # the song she was last asked about, and when
        self._stop = threading.Event()

    def seen(self, t: "Track | None"):
        if t is None:
            return
        t = t.clean()
        now = self.clock()
        self.tracks = [(x, s) for x, s in self.tracks if (x.title, x.artist) != (t.title, t.artist)]
        self.tracks = (self.tracks + [(t, now)])[-self.keep:]

    def recent(self, within_s: float = 1800) -> list["Track"]:
        now = self.clock()
        return [t for t, s in reversed(self.tracks) if now - s <= within_s]

    def match(self, title: str, artist: str = "") -> "Track | None":
        best, score = None, 0.0
        for t in self.recent():
            s = sounds_like(title, t.title) + (0.1 if artist and _squash(artist) in _squash(t.artist) else 0)
            if not artist and t.artist and sounds_like(title, t.artist) >= 0.8:
                s = max(s, 0.8)                            # "I'm listening to Linkin Park": the artist
            if s > score:
                best, score = t, s
        return best if score >= 0.55 else None

    def correct(self, shown: "Track", actual: "Track"):
        self.corrected = {k: v for k, v in self.corrected.items() if self.clock() - v[1] < CORRECTED_FOR_S}
        self.corrected[shown.clean().title] = (actual, self.clock())

    def actual(self, shown: "Track") -> "Track":
        hit = self.corrected.get(shown.clean().title)
        return hit[0] if hit and self.clock() - hit[1] < CORRECTED_FOR_S else shown

    def start(self, every_s: float = 20) -> "RecentTracks":
        def run():
            while not self._stop.wait(every_s):
                try:
                    self.seen((self.read or now_playing)())
                except Exception as exc:
                    log.debug("recent tracks: %s", exc)
        threading.Thread(target=run, name="recent-tracks", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()


RECENT = RecentTracks()


def song_note(user_text: str, track_now=None, web=None, facts=None, recent: RecentTracks | None = None) -> str | None:
    """A note for this one request when they talk about the song: what's actually playing and what's
    known about it, so she gives a real opinion instead of making one up (she once called a rock song
    'a rainy day anime theme') or answering every time with 'what do you like about it?'.
    When they name the song themselves, that wins over the player (it may show the next one early)."""
    recent = recent or RECENT
    named = named_song(user_text)
    if not named and not SONG_TALK.search(user_text):
        last = recent.talked
        if last and recent.clock() - last[1] < FOLLOW_UP_S and SONG_FOLLOW.search(user_text):
            known = (facts or song_facts)(last[0], web)     # "who played guitar on it?": still that song
            recent.talked = (last[0], recent.clock())
            if known:
                return (f"If this is about the song you were just discussing, {last[0].spoken()}, answer from "
                        f"what's known about it: {known} Don't guess beyond that")
        return None
    shown = (track_now or now_playing)()
    recent.seen(shown)
    facts = facts or song_facts
    if named:
        title, artist = named
        hit = recent.match(title, artist)
        if hit is None:
            guess = Track(title, artist or (shown.clean().artist if shown else ""), True)
            if facts(guess, web):
                hit = guess
        if hit is None:
            return (f"They say they're listening to \"{title}\"{' by ' + artist if artist else ''}, but speech "
                    "recognition often mishears song names and you can't find a song called that. Don't react to "
                    "that title or make anything up: say you didn't catch the name and ask them to say it again")
        if shown is not None:
            recent.correct(shown, hit)
        t, lead = hit, f"They corrected you: the song is {hit.spoken()} (your last reply was about the wrong song; " \
                       "own it in a few words, then answer about this one). "
    else:
        if shown is None:
            return ("You can't see anything playing on the laptop, so you don't know which song they mean: ask "
                    "what it is instead of guessing or describing it")
        t = recent.actual(shown.clean())
        lead = f"The song playing on their laptop right now: {t.spoken()}. "
    recent.talked = (t, recent.clock())
    known = facts(t, web)
    if known:
        return (f"{lead}What's known about it: {known} "
                "They want YOUR take, like a friend who knows this song: say what you honestly love (or don't) about "
                "it, such as the story behind it, an idea or line in it, and how it makes you feel, in 2-4 sentences, "
                "using only what's above. You can't hear this recording: don't describe its sound (builds, drops, "
                "riffs, tempo) unless it's written above. No rain, storms, weather or anime imagery. Say the song's "
                "name at most once. Vary how you end: no 'makes me think of...', no 'do you feel that too?', no "
                "'what does it remind you of'; a question back only if it comes naturally, often none")
    return (f"{lead}You don't know this one and found nothing "
            "about it. Say honestly it's new to you, react to the title or artist with some personality, and ask "
            "them to sell you on it. Don't invent how it sounds or what it's like (no 'vibe', no rain or weather "
            "imagery). Say the song's name at most once")


# ----- what's known about a song -----

_FACTS: dict[tuple[str, str], str] = {}
# Wikimedia rate-limits anonymous-looking clients hard: their policy asks for a name + contact URL
UA = {"User-Agent": "Sanae/1.0 (personal voice assistant; https://github.com/ManasKhare3005/Sanae) python-requests"}


def song_facts(t: "Track", web=None, timeout: float = 4.0) -> str:
    """A few sentences about the song: Wikipedia's summary of its page (written by, album, year, what
    it's about), else passages from a web search. Cached per song; "" when nothing is found."""
    key = (t.title.lower(), t.artist.lower())
    if key in _FACTS:
        return _FACTS[key]
    text = ""
    try:
        text = _wikipedia(t, timeout)
    except Exception as exc:
        log.info("song facts: wikipedia failed: %s", exc)
    if not text and web is not None:
        try:
            results, passages = web.research(f"{t.title} {t.artist} song meaning".strip(), pages=2, passages_per_page=2)
            title = t.title.lower()
            # only passages that name the song: a search for an unknown song returns other songs' pages
            text = " ".join(p for r in results for p in passages.get(r.url, []) if title in p.lower())
        except Exception as exc:
            log.info("song facts: web search failed: %s", exc)
    text = " ".join(text.split())[:1400]
    if len(_FACTS) > 50:
        _FACTS.clear()
    _FACTS[key] = text
    return text


def _wikipedia(t: "Track", timeout: float) -> str:
    import requests

    def api(**params) -> dict:
        r = requests.get("https://en.wikipedia.org/w/api.php", headers=UA, timeout=timeout,
                         params={**params, "action": "query", "format": "json"})
        r.raise_for_status()                               # 429 (rate limit) -> the web search instead
        return r.json().get("query", {})

    hits = api(list="search", srsearch=f"{t.title} {t.artist} song".strip(), srlimit=3).get("search", [])
    for hit in hits:
        base = re.sub(r"\s*\(.*\)$", "", hit["title"])     # "Numb (Linkin Park song)" -> "Numb"
        if sounds_like(t.title, base) < 0.75:
            continue                                       # a different song, an album or the artist's page
        pages = api(prop="extracts|description", explaintext=1, exsectionformat="plain", titles=hit["title"]).get("pages", {})
        page = next(iter(pages.values()), {})
        text = re.split(r"\n(Track listing|Personnel|Charts|Certifications|References|External links|See also)\n",
                        page.get("extract", ""))[0]           # the intro, background, lyrics and reception
        if re.search(r"\b(song|single|track|composition|ballad)\b", page.get("description", "") + text[:200], re.I):
            return f"{page.get('description', '')}. {text}".strip(" .")
    return ""


# YouTube / Spotify decorations: "(Remastered 2010)", "(Official Video)", "[Lyrics]", "Artist - Topic"
_DECOR = re.compile(r"\s*[\(\[][^)\]]*\b(remaster\w*|official|video|audio|lyrics?|visuali[sz]er|live|hd|hq|4k|"
                    r"explicit|clean|version|edit|mono|stereo|mv)\b[^)\]]*[\)\]]", re.I)


@dataclass
class Track:
    title: str
    artist: str
    playing: bool

    def spoken(self) -> str:
        return f'"{self.title}" by {self.artist}' if self.artist else f'"{self.title}"'

    def clean(self) -> "Track":
        """'Oh My Love (Remastered 2010)' by 'John Lennon - Topic' -> 'Oh My Love' by 'John Lennon'."""
        artist = re.sub(r"\s*(- Topic|VEVO|Official)$", "", self.artist.strip(), flags=re.I).strip()
        title = _DECOR.sub("", self.title).strip()
        if artist and title.lower().startswith(artist.lower() + " - "):
            title = title[len(artist) + 3:].strip()      # "John Lennon - Oh My Love" (a music video's title)
        elif not artist and " - " in title:
            artist, title = (x.strip() for x in title.split(" - ", 1))
        return Track(title or self.title, artist, self.playing)


def now_playing() -> Track | None:
    """The current media session's track, or None (nothing open, not Windows, or no binding)."""
    if sys.platform != "win32":
        return None
    try:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
    except ImportError:
        return None

    async def read() -> Track | None:
        mgr = await Manager.request_async()
        s = mgr.get_current_session()
        if s is None:
            return None
        p = await s.try_get_media_properties_async()
        if not p or not (p.title or "").strip():
            return None
        playing = int(s.get_playback_info().playback_status) == 4     # 4 = Playing
        return Track(p.title.strip(), (p.artist or "").strip(), playing)

    try:
        return asyncio.run(read())
    except Exception as exc:
        log.debug("now playing unavailable: %s", exc)
        return None


class MusicWatch:
    """Notices a new track that's been playing a while (for a comment now and then)."""

    def __init__(self, read=now_playing, clock=None):
        import time

        self.read = read
        self.clock = clock or time.time
        self.key = None
        self.since = 0.0

    def steady(self, min_s: float = 60) -> Track | None:
        """The track if it's playing and has been for `min_s`; resets on a new track."""
        t = self.read()
        now = self.clock()
        if t is None or not t.playing:
            self.key = None
            return None
        key = (t.title, t.artist)
        if key != self.key:
            self.key, self.since = key, now
            return None
        return t if now - self.since >= min_s else None
