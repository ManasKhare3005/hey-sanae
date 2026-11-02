"""Her own little life, so she has something to share that isn't about you.

Small ongoing arcs that move forward with real days (persona.yaml friend.life), told the same way
every time so she stays consistent:
  - something she's learning, one step every few days (default: teaching herself to draw);
  - a Japanese word a day she's picking up;
  - music she got into from what you play (the artists that came up on 3+ different days, from
    music.RECENT, titles and artists only, memory of counts per artist).
Shared when you ask how she's been / what she's into / what's new, and now and then as small talk
(about every other day).
"""
from __future__ import annotations

import datetime as dt
import random
import re
import time

from .initiative import Moment
from .part import Part

ASK = re.compile(r"\b(how (are|have) you( been)?|how('?re| are)? (you|ya|u) doing|how'?s it going|how are things|"
                 r"how'?s (life|everything)|you good|how'?s your (day|night|week)|how was your (day|night|week)|"
                 r"what (have|did) you (been )?(do|doing|up to)|what'?s new( with you)?|what are you (into|up to)|"
                 r"what'?ve you been up to|tell me about (you|yourself)|anything new)\b", re.I)
WORDS = [("neko", "cat"), ("ame", "rain"), ("sora", "sky"), ("hoshi", "star"), ("tsuki", "moon"), ("hana", "flower"),
         ("yume", "dream"), ("tomodachi", "friend"), ("kaze", "wind"), ("umi", "sea"), ("yuki", "snow"),
         ("natsu", "summer"), ("fuyu", "winter"), ("aki", "autumn"), ("haru", "spring"), ("ongaku", "music"),
         ("kokoro", "heart"), ("asa", "morning"), ("yoru", "night"), ("mizu", "water"), ("hikari", "light"),
         ("kumo", "cloud"), ("ganbatte", "do your best"), ("daijoubu", "it's okay"), ("otsukare", "good work today"),
         ("oyasumi", "good night"), ("ohayou", "good morning"), ("arigatou", "thank you"), ("tanoshii", "fun"),
         ("natsukashii", "nostalgic"), ("ikigai", "a reason to get up in the morning"), ("komorebi", "sunlight through leaves")]
DEFAULT_LEARNING = {
    "what": "teaching herself to draw",
    "steps": ["stick figures (embarrassing)", "circles and boxes, over and over", "eyes", "hands (they're so hard)",
              "a cat sleeping", "faces from the side", "light and shadow", "a little comic", "backgrounds",
              "drawing from memory"],
    "every_days": 3,
}


class HerLife(Part):
    name = "life"

    def __init__(self, store=None, clock=time.time, settings: dict | None = None, recent_tracks=None,
                 idle=lambda: 0.0, rng=None):
        super().__init__(store, clock)
        s = settings or {}
        self.learning = s.get("learning", DEFAULT_LEARNING) or None
        self.words = bool(s.get("japanese", True))
        self.recent_tracks = recent_tracks          # music.RecentTracks (what's been playing), or None
        self.idle = idle
        self.rng = rng or random.Random()
        if self.get("started") is None:
            self.put("started", self.today())

    def day(self) -> int:
        start = dt.date.fromisoformat(self.get("started", self.today()))
        return max(0, (self.now().date() - start).days)

    # ----- the arcs -----
    def learning_now(self) -> str | None:
        if not self.learning:
            return None
        steps = self.learning.get("steps") or []
        if not steps:
            return None
        n = min(self.day() // max(1, int(self.learning.get("every_days", 3))), len(steps) - 1)
        before = f" (before that: {steps[n - 1]})" if n else " (just started)"
        return f"{self.learning['what']}: working on {steps[n]} lately{before}"

    def word_today(self) -> str | None:
        if not self.words:
            return None
        w, meaning = WORDS[self.day() % len(WORDS)]
        return f"picking up a Japanese word a day; today's is \"{w}\" ({meaning})"

    def hear_music(self):
        """Count the artist that's playing, once per day per artist."""
        if self.recent_tracks is None:
            return
        try:
            tracks = self.recent_tracks.recent(within_s=120)
        except Exception:
            return
        if not tracks:
            return
        self.heard_artist(tracks[0].artist or "")      # newest first

    def heard_artist(self, artist: str):
        """An artist playing (on the laptop, or the phone: roommate.py), counted once per day."""
        artist = artist.strip()
        if not artist:
            return
        days = self.get("artists", {})
        seen = days.get(artist, [])
        if self.today() not in seen:
            days[artist] = [*seen, self.today()][-10:]
            self.put("artists", dict(sorted(days.items(), key=lambda kv: -len(kv[1]))[:30]))

    def music_taste(self) -> str | None:
        days = self.get("artists", {})
        liked = [a for a, d in days.items() if len(d) >= 3]
        if not liked:
            return None
        return f"you got into {', '.join(liked[:2])} because they kept playing them"

    def summary(self) -> str:
        parts = [p for p in [self.learning_now(), self.word_today(), self.music_taste()] if p]
        return "; ".join(parts)

    # ----- sharing -----
    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        if not ASK.search(user_text):
            return []
        life = self.summary()
        made_up = ("Don't invent anything else you did: you live on the laptop, so no naps, meals, walks, "
                   "trips or chores")
        if not life:
            # "How you doing?" got "Just had a quick nap and now I'm all energy" with nothing to go on
            return [f"Nothing special happened to you lately. Say how you feel right now, then ask about them. {made_up}"]
        return [f"Your own life lately (true for you; share one bit, keep it consistent, don't list it all): {life}. "
                f"Then ask about them. {made_up}"]

    def moments(self, now: float) -> list[Moment]:
        self.hear_music()
        idle = self.idle()
        if idle < 20 or idle > 300 or self.rng.random() > 30 / (2 * 86400 / 8):   # ~every other day of laptop time
            return []
        bits = [b for b in [self.learning_now(), self.word_today(), self.music_taste()] if b]
        if not bits:
            return []
        bit = self.rng.choice(bits)
        return [Moment("life", f"Share a small update from your own life, like a friend would: {bit}. One or two short "
                               "lines, casual; it's about you this time, not them.")]
