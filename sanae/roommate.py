"""She notices your life through your phone, the way a roommate would (all opt-in on the phone,
Settings -> She notices; the phone sends only what's listed here, never a full app list):

  - a workout logged on the phone (Strava / Samsung Health through Health Connect) -> "5k in this
    heat?? drink water";
  - Duolingo done today -> she tries her Japanese word of the day on you;
  - an activity on your daily list linked to an app (together.py) ticks itself when you've used
    that app long enough today;
  - 30+ minutes on Instagram / TikTok / Reddit... after midnight -> a text from her: "I'm bored,
    talk to me instead?" (a friend pulling you away, once a night);
  - a song on repeat on your phone (playing on 3+ different days this week) -> "you've had that
    song on repeat all week, what happened 👀"; artists you play a lot get into her life too
    (herlife.py).

The phone POSTs /api/phone/life every few minutes while something changed (Noticing.kt).
"""
from __future__ import annotations

import datetime as dt
import re
import time

from .initiative import Moment
from .part import Part

SOCIAL = {"com.instagram.android": "Instagram", "com.zhiliaoapp.musically": "TikTok", "com.ss.android.ugc.trill": "TikTok",
          "com.reddit.frontpage": "Reddit", "com.twitter.android": "X", "com.google.android.youtube": "YouTube",
          "com.snapchat.android": "Snapchat", "com.facebook.katana": "Facebook"}
DUOLINGO = "com.duolingo"
# Video apps: what plays there is watching (watching.py), not a song, unless it's a music video
VIDEO_APPS = {"com.google.android.youtube": "YouTube", "app.revanced.android.youtube": "YouTube",
              "com.netflix.mediaclient": "Netflix", "com.crunchyroll.crunchyroid": "Crunchyroll",
              "com.amazon.avod.thirdpartyclient": "Prime Video", "com.disney.disneyplus": "Disney+",
              "com.hulu.plus": "Hulu", "com.wbd.stream": "Max"}
MUSIC_VIDEO = re.compile(r"(official (music )?(video|audio)|lyrics?|lyric video|visuali[sz]er|\bmv\b|\(audio\)|- topic$|vevo$)", re.I)
NIGHT_MIN = 30                    # minutes of scrolling after midnight before she says something
APP_MIN = 3                       # an app-linked activity counts after this many minutes (or its own minutes)
PENDING_H = 2                     # a noticed thing is worth saying for this long
KINDS = {"running": "run", "run": "run", "walking": "walk", "walk": "walk", "biking": "ride", "cycling": "ride",
         "swimming": "swim", "hiking": "hike", "strength_training": "workout", "weightlifting": "workout",
         "yoga": "yoga session", "workout": "workout"}


def workout_words(w: dict) -> str:
    kind = KINDS.get(str(w.get("type", "")).lower().replace(" ", "_"), str(w.get("type") or "workout").replace("_", " "))
    km = w.get("km")
    mins = w.get("minutes")
    bits = []
    if km and float(km) >= 0.5:
        bits.append(f"{float(km):.1f} km".replace(".0 km", " km"))
    if mins:
        bits.append(f"{int(mins)} minutes")
    return f"a {kind}" + (f" ({', '.join(bits)})" if bits else "")


class Roommate(Part):
    name = "roommate"

    def __init__(self, store=None, clock=time.time, together=None, life=None, weather=None, settings: dict | None = None):
        super().__init__(store, clock)
        s = settings or {}
        self.together, self.life, self.weather = together, life, weather
        self.night_min = int(s.get("night_min", NIGHT_MIN))
        self.playlist = self.watching = None          # set by friendship.make_parts

    # ----- what the phone saw -----
    def report(self, data: dict) -> list[str]:
        """One report from the phone. Returns what was noticed (for the log / tests)."""
        now = self.clock()
        d = self.now()
        today = d.date().isoformat()
        seen = []
        apps = {str(k): float(v) for k, v in (data.get("apps") or {}).items()}
        if apps:
            self.put("apps", {"day": str(data.get("day") or today), "apps": apps, "at": now})
        if self.together is not None and apps:
            for a in self.together.all():
                need = max(APP_MIN, int(a.get("minutes") or 0))
                if a.get("app") and apps.get(a["app"], 0) >= need and self.together.due(a, d.date()) \
                        and self.together.how(a, today) is None:
                    self.together.log(a, today, "app")
                    seen.append(f"ticked:{a['title']}")
                    self._pending(Moment("roommate", f"{{user}} just did \"{a['title']}\" (you saw them use the app; it's "
                                                     "ticked on your shared list). A short, happy line, like noticing it "
                                                     "from across the room.", key=f"app:{a['id']}:{today}", part=self.name))
        if apps.get(DUOLINGO, 0) >= APP_MIN and not self.done(f"duo:{today}"):
            word = self.life.word_today() if self.life is not None else None
            seen.append("duolingo")
            self._pending(Moment("roommate", "{user} just did their Duolingo today. Playfully notice it, and since you're "
                                             "learning Japanese too, try your word of the day on them as a tiny quiz"
                                             + (f" ({word})" if word else "") + ". One or two short lines.",
                                 key=f"duo:{today}", part=self.name))
        night = {str(k): float(v) for k, v in (data.get("night") or {}).items() if str(k) in SOCIAL}
        scroll = sum(night.values())
        if 0 <= d.hour < 4 and scroll >= self.night_min and not self.done(f"night:{today}"):
            top = max(night, key=night.get)
            seen.append("doomscroll")
            self._pending(Moment("roommate", f"It's {d.hour % 12 or 12}:{d:%M} AM and {{user}} has been on "
                                             f"{SOCIAL[top]} for {int(scroll)} minutes since midnight. Text them like a "
                                             "friend pulling them away, not a parent: you're bored, talk to you instead? "
                                             "One playful line, no lecture about sleep or screens.",
                                 True, f"night:{today}", part=self.name))
        for w in data.get("workouts") or []:
            key = f"workout:{w.get('start')}"
            try:
                end = dt.datetime.fromisoformat(str(w.get("end")))
            except ValueError:
                continue
            if self.done(key) or (d - end).total_seconds() > 6 * 3600 or end > d:
                continue
            heat = self._heat(w)
            seen.append(key)
            self._pending(Moment("roommate", f"{{user}} just logged {workout_words(w)} on their phone{heat}. React like a "
                                             "friend who saw it: impressed, teasing a little, maybe tell them to drink "
                                             "water. One line.", key=key, part=self.name))
        playing = data.get("playing") or {}
        if playing.get("title"):
            title, artist, pkg = str(playing["title"]), str(playing.get("artist") or ""), str(playing.get("package") or "")
            service = VIDEO_APPS.get(pkg)
            if service and not (service == "YouTube" and MUSIC_VIDEO.search(f"{title} {artist}")):
                if self.watching is not None and self.watching.phone_seen(title, artist, service) is not None:
                    seen.append(f"watching:{title}")
            else:
                seen += self._song(title, artist, today)
        return seen

    def _heat(self, w: dict) -> str:
        if self.weather is None or str(w.get("type", "")).lower() in ("strength_training", "weightlifting", "yoga", "swimming"):
            return ""
        try:
            now = (self.weather.today() or {}).get("now")
        except Exception:
            return ""
        if now is None:
            return ""
        unit = "°F" if getattr(self.weather, "units", "fahrenheit") == "fahrenheit" else "°C"
        hot = now >= (90 if unit == "°F" else 32)
        return f" (it's {round(now)}{unit} out{', hot' if hot else ''})"

    def _song(self, title: str, artist: str, today: str) -> list[str]:
        key = f"{title.lower()}|{artist.lower()}"
        songs = self.get("songs", {})
        days = [x for x in songs.get(key, []) if x >= (self.now().date() - dt.timedelta(days=7)).isoformat()]
        out = []
        if today not in days:
            days.append(today)
            if self.life is not None and artist and hasattr(self.life, "heard_artist"):
                self.life.heard_artist(artist)
        songs[key] = days[-7:]
        self.put("songs", dict(sorted(songs.items(), key=lambda kv: kv[1][-1] if kv[1] else "")[-60:]))
        added = self.playlist.heard(title, artist, "phone") if self.playlist is not None else None
        month = f"{self.now():%Y-%m}"
        if len(days) >= 3 and not self.done(f"repeat:{key}:{month}"):
            out.append(f"repeat:{title}")
            also = ""
            if added is not None:
                self.playlist.told(added["id"])
                also = " You also just put it on your shared playlist (it's 'our song' now): say so."
            self._pending(Moment("roommate", f"{{user}} has had \"{title}\"{' by ' + artist if artist else ''} playing on "
                                             f"their phone on {len(days)} different days this week. Tease them about having "
                                             f"it on repeat and ask what happened (curious, playful).{also} One line.",
                                 key=f"repeat:{key}:{month}", part=self.name))
        return out

    # ----- saying it (laptop or phone, whichever comes first) -----
    def _pending(self, m: Moment):
        if self.done(m.key):
            return
        items = [x for x in self.get("pending", []) if x["until"] > self.clock() and x["key"] != m.key]
        items.append({"kind": m.kind, "situation": m.situation, "important": m.important, "key": m.key,
                      "until": self.clock() + PENDING_H * 3600})
        self.put("pending", items[-10:])

    def _waiting(self) -> list[Moment]:
        now = self.clock()
        return [Moment(x["kind"], x["situation"], x["important"], x["key"], part=self.name)
                for x in self.get("pending", []) if x["until"] > now and not self.done(x["key"])]

    def moments(self, now: float) -> list[Moment]:
        # the night text is for the phone (they're in bed); everything else can be said at the laptop too
        return [m for m in self._waiting() if not m.key.startswith("night:")][:1]

    def phone_moments(self, now: float) -> list[Moment]:
        return self._waiting()[:1]

    def used(self, moment, now: float):
        if moment.key:
            self.once(moment.key)
        self.put("pending", [x for x in self.get("pending", []) if x["key"] != moment.key])

    def status(self) -> dict:
        apps = self.get("apps") or {}
        return {"apps_day": apps.get("day"), "songs": len(self.get("songs", {}))}
