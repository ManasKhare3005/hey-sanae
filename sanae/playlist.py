"""Our playlist: songs that became "ours", each with why it's there.

  - A song you play on 3+ different days within two weeks (on the laptop's media session, or on
    the phone: Spotify, YouTube Music, YouTube / YouTube ReVanced music videos...) goes on it by
    itself, with the why worked out in code ("on repeat for 4 days in late October"); she tells you.
  - "Add this song to our playlist" (what's playing now, laptop or phone) adds it by hand.
  - Each song gets a YouTube link found once by search (ddgs), so "play our playlist" opens it as a
    YouTube playlist: in Chrome on the laptop, or on the phone (where the link opens in YouTube /
    YouTube ReVanced, whichever handles youtube.com links). Without a link: a YouTube search.
  - Song of the week: every Sunday she picks one from the playlist and says why, worked out in code
    (the one you played most this week, else one that hasn't had its week yet). It stays up top on
    the phone's playlist page until next Sunday.
  - Plays are also counted per month (kv playlist:month:<YYYY-MM>) for the monthly recap (wrapped.py).
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import threading
import time
import urllib.parse

from .initiative import Moment
from .part import Part

log = logging.getLogger(__name__)
SCHEMA = """
CREATE TABLE IF NOT EXISTS playlist (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, artist TEXT NOT NULL DEFAULT '', why TEXT NOT NULL DEFAULT '',
    video_id TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '', added TEXT NOT NULL);
"""
DAYS_NEEDED = 3
WINDOW_DAYS = 14
ADD = re.compile(r"\b(?:add|put|save|stick)\s+(?:this|that|the|this song|that song|it)(?:\s+song)?\s+(?:on|to|in(?:to)?)\s+"
                 r"(?:our|the|my)\s+playlist\b|\b(?:this|that) (?:one|song) (?:is|should be) (?:on )?our (?:song|playlist)\b", re.I)
SHOW = re.compile(r"\b(?:what'?s (?:on|in) )?(?:our|the|my) (?:shared )?playlist\b|\bour songs?\b", re.I)
PLAY = re.compile(r"\b(?:play|put on|open|start)\s+(?:our|the|my)\s+(?:shared\s+)?(?:playlist|songs)\b", re.I)
DROP = re.compile(r"\b(?:take|remove|drop|delete)\s+(?P<what>.+?)\s+(?:off|from)\s+(?:our|the|my)\s+playlist\b", re.I)
WEEK_ASK = re.compile(r"\b(?:our |the |this week'?s |what'?s (?:our |the )?)song of the week\b|\bweek'?s song\b", re.I)
WEEK_FROM, WEEK_UNTIL = 11, 21          # Sunday, hours she brings it up
VIDEO_JUNK = re.compile(r"\s*[\(\[](?:official\s+)?(?:music\s+)?(?:video|audio|lyrics?|lyric video|visuali[sz]er|mv|hd|4k)"
                        r"[^\)\]]*[\)\]]", re.I)


def tidy(title: str, artist: str) -> tuple[str, str]:
    """'Artist - Song (Official Video)' from YouTube -> ('Song', 'Artist'); 'Artist - Topic' -> 'Artist'."""
    title = VIDEO_JUNK.sub("", title).strip()
    artist = re.sub(r"\s*-\s*Topic$|VEVO$", "", artist or "").strip()
    if " - " in title and (not artist or title.lower().startswith(artist.lower()[:6])):
        a, t = title.split(" - ", 1)
        return t.strip(), a.strip()
    return title, artist


def song_key(title: str, artist: str) -> str:
    t = re.sub(r"[^a-z0-9 ]+", "", title.lower())
    t = re.sub(r"\s+(feat|ft)\s.*$", "", t).strip()
    return f"{t}|{re.sub(r'[^a-z0-9]+', '', artist.lower())}"


def find_video(title: str, artist: str) -> str:
    """A YouTube video id for the song, by search; '' if none."""
    try:
        from ddgs import DDGS

        results = DDGS().videos(f"{title} {artist}".strip(), max_results=6)
    except Exception as exc:
        log.info("playlist: video search failed: %s", exc)
        return ""
    words = set(re.findall(r"[a-z0-9]+", title.lower()))
    best, score = "", -1.0
    for r in results or []:
        m = re.search(r"youtube\.com/watch\?v=([\w-]{11})", str(r.get("content") or ""))
        if not m:
            continue
        name = str(r.get("title") or "").lower()
        s = len(words & set(re.findall(r"[a-z0-9]+", name))) / max(1, len(words))
        if s > score:
            best, score = m.group(1), s
    return best if score >= 0.5 else ""


class Playlist(Part):
    name = "playlist"

    def __init__(self, store=None, clock=time.time, now_playing=None, find=find_video, publish=lambda k, d: None,
                 open_url=None, idle=lambda: 0.0):
        super().__init__(store, clock)
        self.now_playing, self.find, self.publish, self.open_url, self.idle = now_playing, find, publish, open_url, idle
        self._schema(SCHEMA)
        self._last_look = 0.0

    # ----- hearing songs -----
    def heard(self, title: str, artist: str = "", source: str = "laptop") -> dict | None:
        """A song playing now (called every few minutes while it plays). Returns the playlist row if
        this made it "ours"."""
        title, artist = tidy(title, artist)
        if not title or self.store is None:
            return None
        k = song_key(title, artist)
        today = self.today()
        since = (self.now().date() - dt.timedelta(days=WINDOW_DAYS)).isoformat()
        plays = self.get("plays", {})
        days = [d for d in plays.get(k, []) if d >= since]
        if today not in days:
            days.append(today)
        plays[k] = days
        self.put("plays", dict(sorted(plays.items(), key=lambda kv: kv[1][-1])[-200:]))
        self.put("last", {"title": title, "artist": artist, "t": self.clock(), "source": source})
        month_key = f"month:{self.now():%Y-%m}"
        month = self.get(month_key, {})
        e = month.setdefault(k, {"title": title, "artist": artist, "days": []})
        if today not in e["days"]:
            e["days"].append(today)
            self.put(month_key, month)
        if len(days) >= DAYS_NEEDED and self.find_one(title, artist) is None:
            first = dt.date.fromisoformat(min(days))
            part = "early" if first.day <= 10 else "mid" if first.day <= 20 else "late"
            return self.add(title, artist, f"on repeat for {len(days)} days in {part} {first:%B}", source, auto=True)
        return None

    def observe(self, now: float):
        """The laptop's media session, once a minute."""
        if self.now_playing is None or now - self._last_look < 60:
            return
        self._last_look = now
        try:
            t = self.now_playing()
        except Exception:
            t = None
        if t is not None and getattr(t, "playing", False) and t.title:
            self.heard(t.title, t.artist, "laptop")

    # ----- the list -----
    def items(self) -> list[dict]:
        return self._rows("SELECT * FROM playlist ORDER BY id")

    def find_one(self, title: str, artist: str = "") -> dict | None:
        k = song_key(*tidy(title, artist))
        t = k.split("|")[0]
        for r in self.items():
            rk = song_key(r["title"], r["artist"])
            if rk == k or (t and rk.split("|")[0] == t):
                return r
        return None

    def search(self, words: str) -> dict | None:
        w = set(re.findall(r"[a-z0-9]+", words.lower())) - {"the", "a", "song", "by", "that", "this", "one"}
        best = max(self.items(), key=lambda r: len(w & set(re.findall(r"[a-z0-9]+", f"{r['title']} {r['artist']}".lower()))),
                   default=None)
        if best is None or not w & set(re.findall(r"[a-z0-9]+", f"{best['title']} {best['artist']}".lower())):
            return None
        return best

    def add(self, title: str, artist: str, why: str, source: str = "", auto: bool = False) -> dict:
        have = self.find_one(title, artist)
        if have is not None:
            return have
        cur = self._exec("INSERT INTO playlist (title, artist, why, source, added) VALUES (?,?,?,?,?)",
                         (title[:100], artist[:80], why[:120], source, self.now().isoformat(timespec="minutes")))
        row = self._rows("SELECT * FROM playlist WHERE id = ?", (cur.lastrowid,))[0]
        if auto:
            self.put("fresh", [*self.get("fresh", []), row["id"]][-10:])
        threading.Thread(target=self._link, args=(row["id"],), daemon=True).start()
        self.publish("us", {"what": "playlist", "action": "added"})
        return row

    def _link(self, pid: int):
        r = self._rows("SELECT * FROM playlist WHERE id = ?", (pid,))
        if not r or r[0]["video_id"]:
            return
        vid = self.find(r[0]["title"], r[0]["artist"])
        if vid:
            self._exec("UPDATE playlist SET video_id = ? WHERE id = ?", (vid, pid))

    def add_now(self) -> dict | None:
        """"Add this song": what's playing on the laptop, else what the phone played in the last 10 minutes."""
        t = None
        if self.now_playing is not None:
            try:
                t = self.now_playing()
            except Exception:
                t = None
        if t is not None and getattr(t, "playing", False) and t.title:
            title, artist = tidy(t.title, t.artist)
            return self.add(title, artist, f"you added it on {self.now():%B} {self.now().day}", "laptop")
        last = self.get("last")
        if last and self.clock() - last["t"] < 600:
            return self.add(last["title"], last["artist"], f"you added it on {self.now():%B} {self.now().day}", last["source"])
        return None

    def remove(self, pid: int) -> bool:
        return self._exec("DELETE FROM playlist WHERE id = ?", (int(pid),)).rowcount > 0

    @staticmethod
    def link(r: dict) -> str:
        if r["video_id"]:
            return f"https://www.youtube.com/watch?v={r['video_id']}"
        return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(f"{r['title']} {r['artist']}".strip())

    def play_url(self) -> str | None:
        ids = [r["video_id"] for r in self.items() if r["video_id"]]
        if ids:
            return "https://www.youtube.com/watch_videos?video_ids=" + ",".join(ids[-50:])
        rows = self.items()
        return self.link(rows[-1]) if rows else None

    def spoken(self) -> str:
        rows = self.items()
        if not rows:
            return "Our playlist is empty so far. Songs you keep playing end up on it, or say \"add this song to our playlist\"."
        return f"Our playlist ({len(rows)}): " + "; ".join(
            f"{r['title']}" + (f" by {r['artist']}" if r["artist"] else "") for r in rows[-8:]) + "."

    # ----- song of the week -----
    def week_id(self) -> str:
        return f"{self.now():%G-W%V}"

    def week_song(self, pick: bool = False) -> dict | None:
        """This week's song ({id, title, artist, why, url, week}); picked (once) if `pick` and it's due."""
        history = self.get("weeks", [])
        week = self.week_id()
        have = next((h for h in history if h["week"] == week), None)
        if have is None and pick:
            have = self._pick_week(week, history)
        if have is None and history:
            have = history[-1]                         # last Sunday's stays up all week
        if have is None:
            return None
        rows = self._rows("SELECT * FROM playlist WHERE id = ?", (have["id"],)) if self.store is not None else []
        if not rows:
            return None
        r = rows[0]
        return {"id": r["id"], "title": r["title"], "artist": r["artist"], "why": have["why"], "url": self.link(r),
                "week": have["week"]}

    def _pick_week(self, week: str, history: list[dict]) -> dict | None:
        songs = self.items()
        if len(songs) < 2:
            return None
        since = (self.now().date() - dt.timedelta(days=6)).isoformat()
        plays = self.get("plays", {})

        def this_week(r):
            return len([d for d in plays.get(song_key(r["title"], r["artist"]), []) if d >= since])

        had = [h["id"] for h in history]
        last = had[-1] if had else None
        ranked = sorted((r for r in songs if r["id"] != last), key=lambda r: (-this_week(r), r["id"] in had, r["id"]))
        r = ranked[0]
        n = this_week(r)
        if n >= 2:
            why = f"you played it on {n} days this week"
        elif r["id"] not in had:
            added = dt.date.fromisoformat(r["added"][:10])
            part = "early" if added.day <= 10 else "mid" if added.day <= 20 else "late"
            why = ("it's the newest one on our playlist" if r["id"] == max(s["id"] for s in songs) else
                   f"it's been ours since {part} {added:%B} and never had its week")
        else:
            why = "it's been a while since it had its week"
        entry = {"week": week, "id": r["id"], "why": why}
        self.put("weeks", [*history, entry][-60:])
        self.publish("us", {"what": "playlist", "action": "week"})
        return entry

    def week_words(self) -> str:
        w = self.week_song(pick=self.now().weekday() == 6 and self.now().hour >= WEEK_FROM)
        if w is None:
            return ("No song of the week yet: I pick one from our playlist on Sundays." if len(self.items()) >= 2 else
                    "Our playlist needs a couple more songs before I can pick a song of the week.")
        return f"Our song of the week: {w['title']}" + (f" by {w['artist']}" if w["artist"] else "") + f", because {w['why']}."

    def month_top(self, month: str, n: int = 3) -> list[dict]:
        """Most-played songs of a month (YYYY-MM): [{title, artist, days}]."""
        m = self.get(f"month:{month}", {})
        top = sorted(m.values(), key=lambda e: (-len(e["days"]), e["title"].lower()))
        return [{"title": e["title"], "artist": e["artist"], "days": len(e["days"])} for e in top[:n] if len(e["days"]) >= 2]

    # ----- in conversation / on her own -----
    def route(self, user_text: str, last_reply: str = "") -> tuple[str, dict] | None:
        t = user_text.strip()
        if ADD.search(t):
            return "add_to_playlist", {}
        if (m := DROP.search(t)) and self.search(m.group("what")) is not None:
            return "remove_from_playlist", {"which": m.group("what")}
        if WEEK_ASK.search(t):
            return "song_of_the_week", {}
        if PLAY.search(t):
            return "play_playlist", {}
        if SHOW.search(t) and re.search(r"\b(what|show|read|list|tell)\b", t, re.I):
            return "our_playlist", {}
        return None

    def _week_moment(self, now: float, phone: bool) -> list[Moment]:
        d = dt.datetime.fromtimestamp(now)
        if self.store is None or d.weekday() != 6 or not WEEK_FROM <= d.hour < WEEK_UNTIL or (not phone and self.idle() > 300):
            return []
        w = self.week_song(pick=True)
        if w is None or w["week"] != self.week_id() or self.done(f"week:{w['week']}"):
            return []
        by = f" by {w['artist']}" if w["artist"] else ""
        return [Moment("playlist", f"It's Sunday: you picked your song of the week from your shared playlist with {{user}}: "
                                   f"\"{w['title']}\"{by}, because {w['why']}. Tell them, warm and playful, like it's a "
                                   "little ritual; they can play it from the Us tab. One or two short lines.",
                       key=f"week:{w['week']}", part=self.name)]

    def phone_moments(self, now: float) -> list[Moment]:
        return self._week_moment(now, phone=True)

    def moments(self, now: float) -> list[Moment]:
        week = self._week_moment(now, phone=False)
        if week:
            return week
        fresh = [r for r in self.items() if r["id"] in set(self.get("fresh", []))]
        if not fresh or self.idle() > 300:
            return []
        r = fresh[-1]
        return [Moment("playlist", f"You just put \"{r['title']}\"{' by ' + r['artist'] if r['artist'] else ''} on your shared "
                                   f"playlist with {{user}}, because they've had it {r['why']}. Tell them, playful and "
                                   "warm (it's 'our song' now). One line.", key=f"added:{r['id']}", part=self.name)]

    def used(self, moment, now: float):
        super().used(moment, now)
        if moment.key.startswith("added:"):
            pid = int(moment.key.split(":")[1])
            self.put("fresh", [x for x in self.get("fresh", []) if x != pid])

    def told(self, pid: int):
        """Already mentioned elsewhere (the phone's "on repeat" tease): no separate line."""
        self.once(f"added:{pid}")
        self.put("fresh", [x for x in self.get("fresh", []) if x != pid])

    def status(self) -> dict:
        rows = self.items()
        return {"songs": [{"id": r["id"], "title": r["title"], "artist": r["artist"], "why": r["why"],
                           "url": self.link(r), "added": r["added"][:10]} for r in reversed(rows)],
                "play_url": self.play_url(), "week_song": self.week_song()}
