"""Watching together: she knows what you're watching on the laptop and keeps you company like a friend
on the couch.

  - What: the window in front and the media session (Windows), read for a show, season and episode
    ("Frieren S1E5", "The Bear - S2:E3", "Show.Name.S02E05.1080p.mkv - VLC"), a movie on a streaming
    site, or a long YouTube video. Window titles go through window.clean() first (the same blocklist
    as noticing: incognito, banking, passwords... are never read).
  - While it's on she stays quiet (do-not-disturb: "watching X").
  - When you stop: "how was it?" (no spoilers: she only knows the title).
  - The next evening: "watching the next one tonight?" after a show you've been following.
  - She remembers what you've watched (table watched): "what have I been watching?", and when you
    bring up a show she knows where you're at.
  - On the phone too: videos playing in YouTube / YouTube ReVanced, Netflix... come in with the
    phone's reports (roommate.py -> phone_seen), every few minutes while they play.
  - Movie night: a watchlist ("add Dune to my watchlist", "we should watch Arcane", the phone), and
    "what should we watch tonight?" picks in code from the time left before bed and the day's mood:
    short on time or worn out -> the next episode of a show you're into; a free evening -> a movie
    off the watchlist. Something from the watchlist that shows up as watched gets ticked.
  - Our movie log: every movie watched (seen on screen, or "rate Dune 4 stars") is kept with your
    stars, your words and her take. After a movie she asks how it was and for stars out of 5; your
    answer sets them ("so good", "8/10", "4 stars"), and her reply to it is kept as her take.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from dataclasses import dataclass

from .initiative import Moment
from .part import Part

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'movie', who TEXT NOT NULL DEFAULT 'you',
    added TEXT NOT NULL, done TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS watched (
    id INTEGER PRIMARY KEY, show TEXT NOT NULL, kind TEXT NOT NULL, season INTEGER NOT NULL DEFAULT 0,
    episode INTEGER NOT NULL DEFAULT 0, ep_title TEXT NOT NULL DEFAULT '', service TEXT NOT NULL DEFAULT '',
    day TEXT NOT NULL, started TEXT NOT NULL, minutes INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS movie_log (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, day TEXT NOT NULL, stars INTEGER NOT NULL DEFAULT 0,
    your_take TEXT NOT NULL DEFAULT '', her_take TEXT NOT NULL DEFAULT '', how TEXT NOT NULL DEFAULT 'seen', created TEXT NOT NULL);
"""
SERVICES = [("netflix", "Netflix"), ("youtube", "YouTube"), ("crunchyroll", "Crunchyroll"), ("prime video", "Prime Video"),
            ("disney+", "Disney+"), ("disney plus", "Disney+"), ("hulu", "Hulu"), ("hbo max", "Max"), ("apple tv", "Apple TV"),
            ("plex", "Plex"), ("jellyfin", "Jellyfin"), ("peacock", "Peacock"), ("paramount+", "Paramount+"),
            ("twitch", "Twitch")]
PLAYERS = {"vlc.exe": "VLC", "mpv.exe": "mpv", "potplayermini64.exe": "PotPlayer", "potplayermini.exe": "PotPlayer",
           "mpc-hc64.exe": "MPC", "mpc-be64.exe": "MPC", "netflix.exe": "Netflix", "wwahost.exe": "Netflix",
           "video.ui.exe": "Movies & TV", "microsoft.media.player.exe": "Media Player", "stremio.exe": "Stremio"}
SXE = re.compile(r"\b[Ss](?:eason)?\s?(\d{1,2})\s?[.:,·\-xX ]?\s?[Ee](?:p(?:isode)?)?\.?\s?(\d{1,3})\b|\b(\d{1,2})x(\d{1,3})\b")
SEASON_EP = re.compile(r"\bseason\s+(\d{1,2})\b.*?\bepisode\s+(\d{1,3})\b", re.I)
EPISODE = re.compile(r"\b(?:episode|ep\.?)\s*(\d{1,4})\b", re.I)
JUNK = re.compile(r"\b(1080p|720p|2160p|4k|x26[45]|hevc|web-?dl|webrip|bluray|brrip|hdtv|aac|ddp?5\.1|h\.?26[45]|"
                  r"\[[^\]]*\]|mkv|mp4|avi|10bit)\b", re.I)
PHONE_GAP_S = 10 * 60               # the phone reports every ~4 minutes
PHONE_STEP_S = 4 * 60
MIN_SHOW_S = 6 * 60
MIN_MOVIE_S = 25 * 60
MIN_VIDEO_S = 15 * 60
GAP_S = 3 * 60                      # nothing for this long: they stopped watching
# "we should watch Arcane": the title must be capitalised (typed or from Whisper), so "we should watch out" isn't one
WL_ADD = re.compile(r"(?i:\b(?:add|put)\s+)(?P<what>.+?)(?i:\s+(?:to|on)\s+(?:my|our|the)\s+watch ?list\b)"
                    r"|(?i:\b(?:we|i)\s+(?:should|gotta|have to|need to|want to|wanna)\s+(?:watch|see)\s+)"
                    r"(?P<what2>[A-Z0-9][^,.!?]{1,40}?)"
                    r"(?i:\s+(?:sometime|some time|together|one day|soon|next|at some point))?\s*[.!?]*$")
WL_DROP = re.compile(r"\b(?:take|remove|drop|delete)\s+(?P<what>.+?)\s+(?:off|from)\s+(?:my|our|the)\s+watch ?list\b", re.I)
WL_SHOW = re.compile(r"\b(?:what'?s on |show (?:me )?|read (?:me )?)(?:my|our|the) watch ?list\b", re.I)
PICK = re.compile(r"\b(?:what should (?:we|i) watch|movie night|what (?:can|could) (?:we|i) watch|pick (?:something|a movie|a show) "
                  r"(?:for us )?to watch|something to watch|what to watch)\b", re.I)
SHOWISH = re.compile(r"\b(season|series|show|anime|episodes?)\b", re.I)
TIRED_MOODS = ("tired", "down", "sad", "stressed", "frustrated", "low")
LOG_SHOW = re.compile(r"\b(?:our|my|the) movie (?:log|list|diary)\b|\bwhat movies (?:have|did) (?:we|i) (?:watch(?:ed)?|seen?)\b|"
                      r"\bmovies (?:we'?ve|i'?ve) (?:watched|seen)\b", re.I)
LOG_ADD = re.compile(r"\b(?:add|put|log)\s+(?P<what>.+?)\s+(?:to|in|on)\s+(?:our|my|the) movie (?:log|list|diary)\b", re.I)
MOVIE_RATE = re.compile(r"\b(?:rate|give)\s+(?:the movie\s+)?(?P<what>.+?)\s+(?:a\s+)?(?P<n>10|[1-9](?:\.5)?|one|two|three|four|five)"
                        r"\s*(?:/\s*(?:5|10)|out of (?:5|10|five|ten)|stars?)", re.I)
TEN = re.compile(r"\b(?P<n>10|[1-9](?:\.5)?)\s*(?:/\s*10|out of (?:10|ten))\b", re.I)
ASK_RATING = re.compile(r"\b(rate|stars?|out of (5|five)|how was|how'?d you like|any good|thoughts on)\b", re.I)
ASK = re.compile(r"\b(what (have i|did i|was i|am i) (been )?watch\w*|what'?s on my watch ?list|where (am i|was i|did i leave off) (in|on|with))\b", re.I)


def movie_stars(text: str) -> int:
    """'8/10' -> 4, '4 stars' / 'so good' / 'meh' -> 1-5 (recipes.stars_in), 0 if it doesn't say."""
    from .recipes import stars_in

    if m := TEN.search(text):
        return max(1, min(5, round(float(m.group("n")) / 2 + 0.01)))
    return stars_in(text)


def her_words(reply: str) -> str:
    """Her reply as a take for the log: no tags or asides, the first two sentences."""
    from .tags import ASIDE, EMOJI, TAG

    text = " ".join(EMOJI.sub("", ASIDE.sub("", TAG.sub("", reply or ""))).split())
    parts = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(parts[:2])[:220].strip()


@dataclass
class Watch:
    show: str
    kind: str              # show / movie / video
    season: int = 0
    episode: int = 0
    ep_title: str = ""
    service: str = ""

    def key(self) -> str:
        return f"{self.show.lower()}|{self.season}|{self.episode}" if self.kind == "show" else f"{self.kind}|{self.show.lower()}"

    def words(self) -> str:
        if self.kind == "show" and self.episode:
            s = f"season {self.season} episode {self.episode}" if self.season else f"episode {self.episode}"
            return f"{self.show}, {s}" + (f" (\"{self.ep_title}\")" if self.ep_title else "")
        return self.show


def _same(a: str, b: str) -> bool:
    """'Dune: Part Two' ~ 'dune part two'; 'Arcane' ~ 'Arcane (2021)'."""
    def norm(s):
        return re.sub(r"\s+", " ", re.sub(r"\(\d{4}\)|[^a-z0-9 ]+", " ", s.lower())).strip()

    x, y = norm(a), norm(b)
    return bool(x and y) and (x == y or (min(len(x), len(y)) >= 4 and (x.startswith(y) or y.startswith(x))))


def _tidy(name: str) -> str:
    name = JUNK.sub(" ", name)
    name = re.sub(r"[._]+", " ", name)
    name = re.sub(r"^\s*(watch|now playing|▶|►)\s*[:\-]?\s*", "", name, flags=re.I)
    name = re.sub(r"\s*[|\-–—:·(]+\s*$", "", name)
    name = re.sub(r"\(\d{4}\)", "", name)
    return re.sub(r"\s+", " ", name).strip(" -–—:|·")[:60]


def _service(app: str, text: str) -> str:
    low = text.lower()
    for word, name in SERVICES:
        if word in low:
            return name
    return PLAYERS.get(app.lower(), "")


def _strip_service(text: str) -> str:
    for word, _ in SERVICES:
        text = re.sub(rf"\s*[|\-–—:]\s*(watch on |on )?{re.escape(word)}\b.*$", "", text, flags=re.I)
        text = re.sub(rf"^{re.escape(word)}\s*[:|\-–—]\s*", "", text, flags=re.I)
    return re.sub(r"\s*[-–—]\s*(VLC media player|mpv|PotPlayer|MPC-HC|Media Player)\s*$", "", text, flags=re.I)


def parse(exe: str, title: str, media_title: str = "", media_artist: str = "") -> Watch | None:
    """What's being watched, from the window (exe name + title) and the media session; None if it
    isn't something to watch (a code editor, a song...)."""
    service = _service(exe, " ".join([title, media_title]))
    if not service:
        return None
    texts = [t for t in (f"{media_title} {media_artist}".strip(), title) if t]
    for text in texts:
        text = _strip_service(text)
        m = SXE.search(text) or SEASON_EP.search(text)
        if m:
            g = [x for x in m.groups() if x is not None]
            season, episode = int(g[0]), int(g[1])
            show = _tidy(text[:m.start()]) or _tidy(media_title)
            rest = _tidy(re.sub(r"^\W+", "", text[m.end():]))
            if show:
                return Watch(show, "show", season, episode, rest if rest.lower() != show.lower() else "", service)
        m = EPISODE.search(text)
        if m and service != "YouTube":
            show = _tidy(text[:m.start()])
            if show:
                return Watch(show, "show", 0, int(m.group(1)), _tidy(text[m.end():]), service)
    name = _tidy(_strip_service(media_title or title))
    if not name or name.lower() in {s.lower() for _, s in SERVICES} or name.lower() in ("home", "browse", "search"):
        return None
    if service == "YouTube":
        return Watch(name, "video", service=service)
    if service == "Twitch":
        return Watch(name, "video", service=service)
    return Watch(name, "movie", service=service)


def read_now() -> tuple[str, str, str, str]:
    """(exe, title, media title, media artist): the window in front (after the blocklist) and the
    media session."""
    from .window import clean, foreground_raw

    exe, title = foreground_raw()
    w = clean(exe, title)
    if w is None:
        return "", "", "", ""
    mt = ma = ""
    try:
        from .music import now_playing

        t = now_playing()
        if t is not None and t.playing:
            mt, ma = t.title, t.artist
    except Exception:
        pass
    return exe, w.title, mt, ma


class Watching(Part):
    name = "watching"

    def __init__(self, store=None, clock=time.time, read=read_now, idle=lambda: 0.0, bedtime: str = "00:30"):
        super().__init__(store, clock)
        self.read, self.idle, self.bedtime = read, idle, bedtime
        self._schema(SCHEMA)

    # ----- following along -----
    def sample(self, now: float | None = None) -> Watch | None:
        now = self.clock() if now is None else now
        try:
            w = parse(*self.read())
        except Exception:
            w = None
        cur = self.get("current")
        if cur and (w is None or Watch(**cur["w"]).key() != w.key()) and now - cur["last"] > GAP_S:
            self._close(cur)
            cur = None
        if w is not None:
            if cur and Watch(**cur["w"]).key() == w.key():
                cur["last"] = now
            elif cur is None or now - cur["last"] > 20:
                if cur:
                    self._close(cur)
                cur = {"w": w.__dict__, "start": now, "last": now}
            self.put("current", cur)
        elif cur:
            self.put("current", cur)
        return w

    def phone_seen(self, title: str, channel: str = "", service: str = "YouTube", now: float | None = None) -> Watch | None:
        """A video playing on the phone (one report). Sessions close after PHONE_GAP_S without one."""
        now = self.clock() if now is None else now
        w = parse("", f"{title} - {service}", title, "" if service == "YouTube" else channel)
        if w is None:
            return None
        cur = self.get("phone")
        if cur and (Watch(**cur["w"]).key() != w.key() or now - cur["last"] > PHONE_GAP_S):
            self._close(cur, "phone", slack=PHONE_STEP_S)
            cur = None
        cur = cur or {"w": w.__dict__, "start": now, "last": now, "phone": True}
        cur["last"] = now
        self.put("phone", cur)
        return w

    def _close(self, cur: dict, slot: str = "current", slack: float = 0):
        w = Watch(**cur["w"])
        secs = cur["last"] - cur["start"] + slack
        need = {"show": MIN_SHOW_S, "movie": MIN_MOVIE_S, "video": MIN_VIDEO_S}[w.kind]
        self.put(slot, None)
        if secs < need:
            return
        start = dt.datetime.fromtimestamp(cur["start"])
        self._exec("INSERT INTO watched (show, kind, season, episode, ep_title, service, day, started, minutes) "
                   "VALUES (?,?,?,?,?,?,?,?,?)", (w.show, w.kind, w.season, w.episode, w.ep_title, w.service,
                                                  (start - dt.timedelta(hours=4)).date().isoformat(),
                                                  start.isoformat(timespec="minutes"), int(secs // 60)))
        logged = self.log_movie(w.show) if w.kind == "movie" else None
        self.put("ended", {"t": cur["last"], "show": w.show, "log_id": logged["id"] if logged else 0})
        for item in self.watchlist():                     # off the watchlist once it's been watched
            if _same(item["title"], w.show):
                self._exec("UPDATE watchlist SET done = ? WHERE id = ?", (start.date().isoformat(), item["id"]))

    def watching_now(self) -> Watch | None:
        cur = self.get("current")
        if not cur or self.clock() - cur["last"] > 90:
            return None
        w = Watch(**cur["w"])
        return w if w.kind in ("show", "movie") or self.clock() - cur["start"] > 5 * 60 else None

    def quiet_reason(self) -> str | None:
        """For do-not-disturb: stay quiet while they're watching."""
        w = self.watching_now()
        return f"watching {w.show}" if w is not None else None

    # ----- memory -----
    def history(self, days: int = 14) -> list[dict]:
        since = (self.now() - dt.timedelta(days=days)).date().isoformat()
        return self._rows("SELECT * FROM watched WHERE day >= ? ORDER BY started DESC", (since,))

    def shows(self, days: int = 30) -> list[dict]:
        """Per show / movie: the furthest episode, how many sessions, when last."""
        out: dict[str, dict] = {}
        for r in reversed(self.history(days)):
            k = r["show"].lower()
            e = out.setdefault(k, {"show": r["show"], "kind": r["kind"], "season": 0, "episode": 0, "ep_title": "",
                                   "service": r["service"], "times": 0, "minutes": 0, "last": r["started"]})
            e["times"] += 1
            e["minutes"] += r["minutes"]
            e["last"] = r["started"]
            if (r["season"], r["episode"]) >= (e["season"], e["episode"]):
                e["season"], e["episode"], e["ep_title"] = r["season"], r["episode"], r["ep_title"]
        return sorted(out.values(), key=lambda e: e["last"], reverse=True)

    def where(self, e: dict) -> str:
        if e["kind"] == "show" and e["episode"]:
            return f"{e['show']} (up to season {e['season']} episode {e['episode']})" if e["season"] else \
                f"{e['show']} (up to episode {e['episode']})"
        return f"{e['show']} ({'a movie' if e['kind'] == 'movie' else 'a video'})"

    def spoken(self) -> str:
        shows = self.shows(14)
        if not shows:
            return "I haven't seen you watch anything lately."
        return "Lately you've been watching: " + "; ".join(self.where(e) for e in shows[:5]) + "."

    # ----- movie night -----
    def watchlist(self, done: bool = False) -> list[dict]:
        return self._rows("SELECT * FROM watchlist WHERE " + ("done != ''" if done else "done = ''") + " ORDER BY id")

    def add_watch(self, title: str, who: str = "you") -> dict:
        title = re.sub(r"^(?:the movie|the show|the series|the anime)\s+", "", title.strip(" .!?\"'"), flags=re.I)[:80]
        if not title:
            raise ValueError("what should go on the watchlist?")
        for item in self.watchlist():
            if _same(item["title"], title):
                return item
        kind = "show" if SHOWISH.search(title) or any(_same(e["show"], title) and e["kind"] == "show" for e in self.shows(90)) \
            else "movie"
        cur = self._exec("INSERT INTO watchlist (title, kind, who, added) VALUES (?,?,?,?)",
                         (title, kind, who, self.now().isoformat(timespec="minutes")))
        return self._rows("SELECT * FROM watchlist WHERE id = ?", (cur.lastrowid,))[0]

    def drop_watch(self, which: str) -> dict | None:
        for item in self.watchlist():
            if _same(item["title"], which):
                self._exec("DELETE FROM watchlist WHERE id = ?", (item["id"],))
                return item
        return None

    def remove_watch(self, wid: int) -> bool:
        return self._exec("DELETE FROM watchlist WHERE id = ?", (int(wid),)).rowcount > 0

    def minutes_left(self) -> int:
        """Until bedtime (persona.yaml initiative.bedtime.from), counting past midnight."""
        d = self.now()
        h, m = (int(x) for x in self.bedtime.split(":"))
        bed = d.replace(hour=h, minute=m, second=0, microsecond=0)
        if h < 12 and d.hour >= 12:
            bed += dt.timedelta(days=1)
        elif bed < d and d.hour < 12 and h < 12:
            return 0
        return max(0, int((bed - d).total_seconds() // 60))

    def day_mood(self) -> str:
        from .mood import _day, _days

        today = _days(self.store).get(_day(self.clock()), {}) if self.store is not None else {}
        if today.get("hard"):
            return "low"
        counts = {k: v for k, v in today.items() if k in TIRED_MOODS and isinstance(v, int)}
        return max(counts, key=counts.get) if counts else ""

    def pick(self) -> dict:
        """{pick, why, alt}: what to watch tonight, worked out in code."""
        left, mood = self.minutes_left(), self.day_mood()
        going = [e for e in self.shows(30) if e["kind"] == "show" and e["episode"]]
        movies = [w for w in self.watchlist() if w["kind"] == "movie"]
        shows_wl = [w for w in self.watchlist() if w["kind"] == "show"]

        def next_ep(e):
            return f"{e['show']}, " + (f"season {e['season']} episode {e['episode'] + 1}" if e["season"] else f"episode {e['episode'] + 1}")

        worn = mood in TIRED_MOODS
        options = []
        if going:
            why = ("something familiar, it's been a long day" if worn else
                   f"only about {left} minutes till bed" if left < 100 else "you're in the middle of it")
            options.append({"pick": next_ep(going[0]), "why": why, "kind": "episode"})
        if movies and left >= 110 and not worn:
            added = dt.date.fromisoformat(movies[0]["added"][:10])
            since = "today" if added == self.now().date() else f"{added:%B} {added.day}"
            options.insert(0, {"pick": movies[0]["title"], "why": ("we just put it on our watchlist" if since == "today" else
                                                                    f"it's been on our watchlist since {since}")
                               + (f" and there's time for a whole movie" if left < 600 else ""), "kind": "movie"})
        elif movies:
            options.append({"pick": movies[0]["title"], "why": "off our watchlist, maybe on a night with more time", "kind": "movie"})
        if shows_wl:
            options.append({"pick": shows_wl[0]["title"], "why": "a new show off our watchlist", "kind": "show"})
        if not options:
            return {"pick": None, "why": "", "alt": None, "left": left, "mood": mood}
        return {**options[0], "alt": options[1] if len(options) > 1 else None, "left": left, "mood": mood}

    def pick_words(self) -> str:
        p = self.pick()
        if p["pick"] is None:
            return ("Our watchlist's empty and I haven't seen you start a show lately. Tell me something you've been "
                    "meaning to watch and I'll keep it on the list!")
        out = f"I'd say {p['pick']} ({p['why']})."
        if p["alt"]:
            out += f" Or {p['alt']['pick']} if you're not feeling it."
        return out

    def watchlist_words(self) -> str:
        items = self.watchlist()
        if not items:
            return "Our watchlist is empty. Say \"add Dune to our watchlist\"."
        return "On our watchlist: " + "; ".join(f"{w['title']}" + (" (a show)" if w["kind"] == "show" else "") for w in items) + "."

    # ----- our movie log -----
    def movie_log(self, n: int = 40) -> list[dict]:
        return self._rows("SELECT * FROM movie_log ORDER BY day DESC, id DESC LIMIT ?", (n,))

    def find_logged(self, title: str) -> dict | None:
        return next((r for r in self.movie_log(200) if _same(r["title"], title)), None)

    def log_movie(self, title: str, how: str = "seen") -> dict:
        """A movie watched: in the log (the same one again within 3 days is the same viewing)."""
        title = re.sub(r"^(?:the movie)\s+", "", title.strip(" .!?\"'"), flags=re.I)[:80]
        have = self.find_logged(title)
        if have is not None and (self.now().date() - dt.date.fromisoformat(have["day"])).days <= 3:
            return have
        cur = self._exec("INSERT INTO movie_log (title, day, how, created) VALUES (?,?,?,?)",
                         (title, (self.now() - dt.timedelta(hours=4)).date().isoformat(), how,
                          self.now().isoformat(timespec="minutes")))
        return self._rows("SELECT * FROM movie_log WHERE id = ?", (cur.lastrowid,))[0]

    def rate_movie(self, title: str, stars: int, take: str = "") -> dict:
        """Stars for a movie in the log (added if it isn't there: "rate Dune 4 stars")."""
        r = self.find_logged(title) or self.log_movie(title, how="you")
        self._exec("UPDATE movie_log SET stars = ?, your_take = CASE WHEN ? != '' THEN ? ELSE your_take END WHERE id = ?",
                   (max(0, min(5, int(stars))), take[:200], take[:200], r["id"]))
        return self._rows("SELECT * FROM movie_log WHERE id = ?", (r["id"],))[0]

    def rate_id(self, mid: int, stars: int) -> dict | None:
        if self._exec("UPDATE movie_log SET stars = ? WHERE id = ?", (max(0, min(5, int(stars))), int(mid))).rowcount == 0:
            return None
        return self._rows("SELECT * FROM movie_log WHERE id = ?", (int(mid),))[0]

    def remove_logged(self, mid: int) -> bool:
        return self._exec("DELETE FROM movie_log WHERE id = ?", (int(mid),)).rowcount > 0

    def log_words(self) -> str:
        rows = self.movie_log()
        if not rows:
            return "Our movie log is empty. After a movie I'll ask for your stars, or say \"rate Dune 4 stars\"."
        best = sorted((r for r in rows if r["stars"] >= 4), key=lambda r: -r["stars"])

        def one(r):
            return r["title"] + (f" ({r['stars']} star{'s' if r['stars'] != 1 else ''})" if r["stars"] else "")

        out = f"Our movie log ({len(rows)}): " + "; ".join(one(r) for r in rows[:8]) + "."
        if len(best) >= 2:
            out += f" Favourites so far: {', '.join(r['title'] for r in best[:3])}."
        return out

    def rating_note(self, user_text: str, last_reply: str) -> str | None:
        """Their answer to "how was it? stars?" after a movie sets the stars and keeps their words."""
        pending = self.get("rating")
        if not pending or self.clock() - pending["t"] > 12 * 3600:
            return None
        rows = self._rows("SELECT * FROM movie_log WHERE id = ?", (pending["id"],))
        if not rows:
            return None
        r = rows[0]
        low = (last_reply or "").lower()
        title_words = [w for w in re.findall(r"[a-z]+", r["title"].lower()) if len(w) > 3]
        if not (ASK_RATING.search(low) or any(w in low for w in title_words)):
            return None
        n = movie_stars(user_text)
        if not n:
            return None
        r = self.rate_movie(r["title"], n, user_text.strip())
        self.put("rating", None)
        self.put("take_for", {"id": r["id"], "t": self.clock()})
        return (f"They rated {r['title']} {n} out of 5; it's in your shared movie log now with their words. React like a friend "
                "in one or two lines: your own little take on their rating and what they said. You only know the title, so "
                "no plot details or made-up scenes")

    def keep_her_take(self, last_reply: str):
        """Her reply right after they rated a movie is her take in the log."""
        tf = self.get("take_for")
        if not tf or not last_reply:
            return
        self.put("take_for", None)
        if self.clock() - tf["t"] <= 1800 and (take := her_words(last_reply)):
            self._exec("UPDATE movie_log SET her_take = ? WHERE id = ?", (take, tf["id"]))

    # ----- her side -----
    def observe(self, now: float):
        if self.store is not None:
            self.sample(now)
            cur = self.get("phone")
            if cur and now - cur["last"] > PHONE_GAP_S:
                self._close(cur, "phone", slack=PHONE_STEP_S)

    def moments(self, now: float) -> list[Moment]:
        if self.store is None:
            return []
        out = []
        ended = self.get("ended")
        d = dt.datetime.fromtimestamp(now)
        if ended and 3 * 60 <= now - ended["t"] <= 3600 and self.watching_now() is None and self.idle() < 120:
            key = f"after:{ended['show'].lower()}:{d.date().isoformat()}"
            if not self.done(key):
                rows = [r for r in self.history(1) if r["show"] == ended["show"] and r["started"] >= (d - dt.timedelta(hours=6)).isoformat()]
                last = rows[0] if rows else None
                n = len([r for r in rows if r["kind"] == "show"])
                what = Watch(last["show"], last["kind"], last["season"], last["episode"], last["ep_title"]).words() if last else ended["show"]
                binge = f" ({n} episodes in a row)" if n >= 3 else ""
                stars = " and ask for their stars out of 5 for your shared movie log" if ended.get("log_id") else ""
                out.append(Moment("watching", f"{{user}} just finished watching {what}{binge}. You were keeping them "
                                              f"company but you only know the title, not what happened: ask how it was{stars}, "
                                              "curious, no made-up plot details, no spoilers. One line.",
                                  key=key, part=self.name))
        if 17 <= d.hour < 22 and self.idle() < 120 and self.watching_now() is None:
            yday = (d - dt.timedelta(days=1)).date().isoformat()
            for e in self.shows(3):
                watched_on = (dt.datetime.fromisoformat(e["last"]) - dt.timedelta(hours=4)).date().isoformat()
                if e["kind"] != "show" or watched_on != yday:
                    continue
                key = f"next:{e['show'].lower()}:{d.date().isoformat()}"
                if not self.done(key):
                    out.append(Moment("watching", f"Last night {{user}} watched {self.where(e)}. Ask, lightly, if they're "
                                                  "watching the next one tonight (you'd keep them company). One line, no "
                                                  "spoilers, no invented plot.", key=key, part=self.name))
                break
        return out

    def used(self, moment, now: float):
        super().used(moment, now)
        ended = self.get("ended") or {}
        if moment.key.startswith("after:") and ended.get("log_id"):
            self.put("rating", {"id": ended["log_id"], "t": now})

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        if self.store is None:
            return []
        self.keep_her_take(last_reply)
        if (rated := self.rating_note(user_text, last_reply)) is not None:
            return [rated]
        out = []
        w = self.watching_now()
        if w is not None:
            out.append(f"They're watching {w.words()} right now (you're keeping them company); if they talk about it, "
                       "react to what they tell you, no spoilers or invented plot")
        low = user_text.lower()
        for e in self.shows(60):
            name = e["show"].lower()
            if len(name) >= 3 and re.search(rf"\b{re.escape(name)}\b", low):
                out.append(f"You know they've been watching {self.where(e)}; you only know titles, not what happens in it")
                break
        return out

    def route(self, user_text: str, last_reply: str = "") -> tuple[str, dict] | None:
        t = user_text.strip()
        if ASK.search(t):
            return "watch_history", {}
        if WL_SHOW.search(t):
            return "watchlist", {}
        if LOG_SHOW.search(t) and not LOG_ADD.search(t):
            return "movie_log", {}
        if (m := LOG_ADD.search(t)):
            return "rate_movie", {"title": m.group("what"), "stars": 0}
        if (m := MOVIE_RATE.search(t)):
            what = re.sub(r"^(?:the|that)\s+", "", m.group("what").strip(), flags=re.I)
            known = self.find_logged(what) is not None or any(_same(e["show"], what) for e in self.shows(90)) or \
                any(_same(x["title"], what) for x in self.watchlist(done=True) + self.watchlist())
            if known or re.search(r"\bmovie\b", t, re.I):
                n = movie_stars(m.group(0))
                return "rate_movie", {"title": what, "stars": n}
        if (m := WL_DROP.search(t)):
            return "drop_from_watchlist", {"title": m.group("what")}
        if (m := WL_ADD.search(t)):
            what = (m.group("what") or m.group("what2") or "").strip()
            if what and not re.match(r"(?i)(it|that|this|something|a movie|a show|tv|youtube|the game|you)\b", what):
                return "add_to_watchlist", {"title": what}
        if PICK.search(t):
            return "what_to_watch", {}
        return None

    def status(self) -> dict:
        w = self.watching_now()
        return {"now": w.words() if w else None,
                "shows": [{"show": e["show"], "kind": e["kind"], "where": self.where(e), "last": e["last"],
                           "service": e["service"], "minutes": e["minutes"]} for e in self.shows(30)[:8]],
                "watchlist": [{"id": x["id"], "title": x["title"], "kind": x["kind"], "who": x["who"]} for x in self.watchlist()],
                "tonight": {k: v for k, v in self.pick().items() if k in ("pick", "why")},
                "log": [{"id": r["id"], "title": r["title"], "day": r["day"], "stars": r["stars"], "your_take": r["your_take"],
                         "her_take": r["her_take"]} for r in self.movie_log(30)]}
