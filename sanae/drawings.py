"""Her drawings, for real: what she's "practising" (herlife.py) becomes an actual little sketch.

Each one is drawn in code as pen strokes (no image model: the GPU is full), wobbly while she's a
beginner and steadier as her learning arc moves on (stick figures -> eyes -> hands -> a sleeping
cat -> ...). A sketch is made when:
  - she writes her page in your shared notebook (journal.py): it sits under her page;
  - a "doing it together" session ends (together.py): what she drew while you did your thing;
  - something asks for one by subject (her asks, the scrapbook: "a mug", "ramen", "the sky"...);
  - every afternoon on her own: a practice sketch of the step she's on (practice()).
They're kept in her sketchbook (table drawings); the phone draws the strokes (Us tab), so nothing
but numbers travels.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import random
import re
import time

from .part import Part

SCHEMA = """
CREATE TABLE IF NOT EXISTS drawings (
    id INTEGER PRIMARY KEY, day TEXT NOT NULL, subject TEXT NOT NULL, title TEXT NOT NULL, caption TEXT NOT NULL,
    strokes TEXT NOT NULL, why TEXT NOT NULL DEFAULT '', skill REAL NOT NULL DEFAULT 0.5, created TEXT NOT NULL);
"""
SIZE = 200
PRACTICE_HOUR = 14                  # her own daily practice sketch, from the afternoon on
SHOW = re.compile(r"\b(show me|can i see|let me see|what (did|are) you|how'?s|how is|how was)\b.{0,30}\b(draw|drawing|drew|sketch\w*)\b", re.I)


# ----- the pen -----
def _resample(pts: list[tuple[float, float]], step: float = 4.0) -> list[tuple[float, float]]:
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        d = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(d / step))
        out += [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(1, n + 1)]
    return out


class Pen:
    """Strokes with a hand-drawn wobble: smooth noise along each stroke, a little overshoot at the
    ends of lines, and (while she's learning) the odd stroke drawn twice."""

    def __init__(self, rng: random.Random, skill: float):
        self.rng, self.skill = rng, max(0.0, min(1.0, skill))
        self.strokes: list[list[int]] = []

    @property
    def amp(self) -> float:
        return 0.5 + 3.2 * (1 - self.skill)

    def _wobble(self, pts, amp):
        n = len(pts)
        k = max(2, n // 7)
        ctrl = [(self.rng.uniform(-1, 1), self.rng.uniform(-1, 1)) for _ in range(k + 2)]
        out = []
        for i, (x, y) in enumerate(pts):
            t = i / max(1, n - 1) * k
            j = int(t)
            f = t - j
            f = f * f * (3 - 2 * f)
            a, b = ctrl[j], ctrl[j + 1]
            out.append((x + amp * (a[0] + (b[0] - a[0]) * f), y + amp * (a[1] + (b[1] - a[1]) * f)))
        return out

    def path(self, pts, closed: bool = False, retrace: bool = True):
        pts = [(float(x), float(y)) for x, y in pts]
        if len(pts) < 2:
            return
        if closed:
            pts = pts + [pts[0]]
        pts = _resample(pts)
        self._add(self._wobble(pts, self.amp))
        if retrace and self.rng.random() < 0.35 * (1 - self.skill):
            self._add(self._wobble(pts, self.amp * 0.8))           # a nervous second pass

    def _add(self, pts):
        flat = []
        for x, y in pts:
            flat += [int(round(min(SIZE, max(0, x)))), int(round(min(SIZE, max(0, y))))]
        self.strokes.append(flat)

    def line(self, a, b):
        over = self.rng.uniform(0, 3.5) * (1 - self.skill)
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = math.hypot(dx, dy) or 1
        ux, uy = dx / d, dy / d
        self.path([(a[0] - ux * over * 0.5, a[1] - uy * over * 0.5), (b[0] + ux * over, b[1] + uy * over)])

    def ellipse(self, cx, cy, rx, ry, a0=0.0, a1=2 * math.pi, rot=0.0, closed_gap=True):
        full = abs(a1 - a0) >= 2 * math.pi - 1e-6
        start = self.rng.uniform(0, 2 * math.pi) if full else a0
        sweep = (2 * math.pi + (self.rng.uniform(0.05, 0.35) if closed_gap else 0)) if full else (a1 - a0)
        n = max(12, int(abs(sweep) * max(rx, ry) / 3))
        cr, sr = math.cos(rot), math.sin(rot)
        pts = []
        for i in range(n + 1):
            t = start + sweep * i / n
            x, y = rx * math.cos(t), ry * math.sin(t)
            pts.append((cx + x * cr - y * sr, cy + x * sr + y * cr))
        self.path(pts)

    def circle(self, cx, cy, r):
        self.ellipse(cx, cy, r, r)

    def arc(self, cx, cy, r, a0, a1):
        self.ellipse(cx, cy, r, r, a0, a1)

    def curve(self, p0, p1, p2, p3, n: int = 24):
        pts = []
        for i in range(n + 1):
            t = i / n
            u = 1 - t
            pts.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                        u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
        self.path(pts)

    def poly(self, pts, closed: bool = True):
        self.path(pts, closed=closed)

    def fill_circle(self, cx, cy, r):
        """A filled dot (a pupil): a tight spiral."""
        pts, turns = [], max(2, int(r / 1.6))
        for i in range(turns * 16 + 1):
            t = i / 16 * 2 * math.pi
            rr = r * i / (turns * 16)
            pts.append((cx + rr * math.cos(t), cy + rr * math.sin(t)))
        self.path(pts, retrace=False)

    def hatch(self, inside, x0, y0, x1, y1, gap: float = 6, angle: float = -0.8):
        """Parallel shading lines, kept where `inside(x, y)` holds."""
        ca, sa = math.cos(angle), math.sin(angle)
        span = int(math.hypot(x1 - x0, y1 - y0))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        for k in range(-span // 2, span // 2, int(gap)):
            run = []
            for s in range(-span // 2, span // 2, 2):
                x = cx + k * -sa + s * ca
                y = cy + k * ca + s * sa
                if inside(x, y):
                    run.append((x, y))
                elif run:
                    if len(run) > 2:
                        self.path(run, retrace=False)
                    run = []
            if len(run) > 2:
                self.path(run, retrace=False)

    def z(self, x, y, s):
        self.poly([(x, y), (x + s, y), (x, y + s), (x + s, y + s)], closed=False)


# ----- what she can draw -----
def _stick(p: Pen, x, y, s=1.0, wave=False):
    p.circle(x, y, 11 * s)
    p.line((x, y + 11 * s), (x, y + 52 * s))
    p.line((x, y + 24 * s), (x - 20 * s, y + (8 if wave else 40) * s))
    p.line((x, y + 24 * s), (x + 20 * s, y + 40 * s))
    p.line((x, y + 52 * s), (x - 14 * s, y + 88 * s))
    p.line((x, y + 52 * s), (x + 14 * s, y + 88 * s))


def stick_figures(p: Pen, rng):
    _stick(p, 70, 50, 1.0, wave=True)
    _stick(p, 132, 56, 0.92)
    p.line((20, 142), (180, 140))


def shapes(p: Pen, rng):
    p.circle(55, 55, 30)
    p.poly([(115, 28), (172, 28), (172, 84), (115, 84)])
    p.poly([(55, 112), (88, 170), (22, 170)])
    a = [(118, 118), (162, 118), (162, 162), (118, 162)]
    b = [(x + 16, y - 14) for x, y in a]
    p.poly(a)
    p.poly(b)
    for (x0, y0), (x1, y1) in zip(a, b):
        p.line((x0, y0), (x1, y1))


def eye(p: Pen, rng):
    p.curve((32, 104), (70, 58), (130, 58), (168, 104))
    p.curve((32, 104), (72, 134), (128, 134), (168, 104))
    p.circle(100, 100, 24)
    p.fill_circle(100, 100, 9)
    p.circle(91, 92, 4)
    for i in range(6):
        t = 0.18 + i * 0.13
        x = (1 - t) ** 3 * 32 + 3 * (1 - t) ** 2 * t * 70 + 3 * (1 - t) * t * t * 130 + t ** 3 * 168
        y = (1 - t) ** 3 * 104 + 3 * (1 - t) ** 2 * t * 58 + 3 * (1 - t) * t * t * 58 + t ** 3 * 104
        p.line((x, y), (x - 6 + i * 2.4, y - 12))
    p.curve((40, 58), (80, 30), (130, 32), (166, 54))


def hand(p: Pen, rng):
    fingers = [(70, 40, -0.12), (92, 30, -0.03), (114, 34, 0.06), (134, 50, 0.16)]
    for x, top, lean in fingers:
        w = 10
        bx = x + lean * 60
        p.poly([(bx - w, 110), (x - w, top + w), ], closed=False)
        p.arc(x, top + w, w, math.pi, 2 * math.pi)
        p.poly([(x + w, top + w), (bx + w, 110)], closed=False)
        p.line((x - w * 0.8, top + 34), (x + w * 0.8, top + 34))           # knuckle crease
    p.curve((60, 110), (54, 140), (68, 178), (100, 182))
    p.curve((100, 182), (136, 182), (148, 150), (144, 110))
    p.curve((60, 128), (40, 118), (26, 96), (34, 84))                       # thumb
    p.curve((34, 84), (44, 76), (58, 96), (70, 112))


def cat_sleeping(p: Pen, rng):
    p.ellipse(108, 128, 62, 34)
    p.circle(62, 116, 25)
    p.poly([(44, 100), (42, 76), (58, 92)], closed=False)
    p.poly([(66, 91), (80, 74), (84, 98)], closed=False)
    p.arc(52, 118, 6, 0.2, math.pi - 0.2)
    p.arc(72, 118, 6, 0.2, math.pi - 0.2)
    p.poly([(60, 128), (64, 128), (62, 131)])
    p.curve((168, 132), (196, 150), (150, 178), (92, 164))
    for i, (x, y, s) in enumerate([(120, 70, 10), (140, 52, 13), (164, 30, 16)]):
        p.z(x, y, s)


def face_side(p: Pen, rng):
    p.poly([(112, 34), (100, 62), (99, 78), (84, 102), (97, 107), (93, 114), (98, 119), (93, 125), (100, 141),
            (128, 152), (134, 182)], closed=False)
    p.curve((112, 34), (150, 18), (186, 60), (168, 112))
    p.curve((168, 112), (160, 132), (150, 140), (146, 156))
    p.ellipse(140, 102, 9, 14)
    p.line((99, 86), (110, 86))
    p.arc(106, 86, 5, 0.1, math.pi - 0.3)
    p.curve((100, 74), (106, 70), (114, 71), (118, 74))


def light_shadow(p: Pen, rng):
    cx, cy, r = 96, 92, 46
    p.ellipse(124, 150, 52, 11)
    p.circle(cx, cy, r)
    p.arc(cx - 14, cy - 16, 13, math.pi * 1.05, math.pi * 1.6)
    p.hatch(lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 < (r - 2) ** 2 and (x - cx) + (y - cy) > r * 0.45,
            cx - r, cy - r, cx + r, cy + r, gap=5)
    p.hatch(lambda x, y: ((x - 124) / 50) ** 2 + ((y - 150) / 9) ** 2 < 1 and x > 112, 70, 138, 178, 162, gap=5, angle=-0.4)


def comic(p: Pen, rng):
    for x0, x1 in ((8, 64), (72, 128), (136, 192)):
        p.poly([(x0, 46), (x1, 46), (x1, 160), (x0, 160)])
    _stick(p, 36, 92, 0.6)
    p.ellipse(42, 66, 16, 10)
    p.line((36, 75), (34, 84))
    _stick(p, 88, 96, 0.55)
    _stick(p, 112, 96, 0.55, wave=True)
    _stick(p, 164, 92, 0.6, wave=True)
    p.line((178, 60), (178, 74))
    p.circle(178, 80, 1.5)


def background(p: Pen, rng):
    p.curve((0, 120), (40, 96), (80, 104), (110, 116))
    p.curve((90, 118), (130, 90), (170, 96), (200, 112))
    p.circle(160, 44, 16)
    for i in range(8):
        a = i * math.pi / 4 + 0.2
        p.line((160 + 22 * math.cos(a), 44 + 22 * math.sin(a)), (160 + 30 * math.cos(a), 44 + 30 * math.sin(a)))
    p.poly([(40, 120), (82, 120), (82, 160), (40, 160)])
    p.poly([(34, 122), (61, 96), (88, 122)], closed=False)
    p.poly([(55, 160), (55, 140), (67, 140), (67, 160)], closed=False)
    p.line((138, 168), (140, 128))
    p.line((148, 168), (146, 128))
    for x, y, r in ((130, 118, 14), (156, 116, 15), (143, 100, 16)):
        p.circle(x, y, r)
    p.line((0, 172), (200, 170))


def cat(p: Pen, rng):
    p.ellipse(100, 138, 34, 36)
    p.circle(100, 82, 24)
    p.poly([(82, 70), (80, 46), (96, 60)], closed=False)
    p.poly([(104, 60), (120, 46), (118, 70)], closed=False)
    p.circle(91, 80, 3)
    p.circle(109, 80, 3)
    p.poly([(98, 90), (102, 90), (100, 93)])
    for s in (-1, 1):
        p.line((100 + s * 8, 92), (100 + s * 26, 88))
        p.line((100 + s * 8, 94), (100 + s * 26, 98))
    p.curve((132, 156), (168, 160), (170, 120), (150, 112))


def memory(p: Pen, rng):
    p.poly([(28, 24), (172, 24), (172, 110), (28, 110)])
    p.line((100, 24), (100, 110))
    p.arc(140, 60, 18, 0.9, 2 * math.pi - 0.9)
    p.arc(148, 56, 15, 1.2, 2 * math.pi - 1.2)
    sub = Pen(p.rng, p.skill)
    cat(sub, rng)
    p.strokes += [[int(v * 0.62 + (38 if i % 2 == 0 else 72)) for i, v in enumerate(s)] for s in sub.strokes]
    p.line((10, 176), (190, 176))


def mug(p: Pen, rng):
    p.ellipse(92, 72, 42, 11)
    p.line((50, 72), (56, 160))
    p.line((134, 72), (128, 160))
    p.curve((56, 160), (70, 172), (114, 172), (128, 160))
    p.curve((132, 92), (168, 88), (168, 138), (130, 134))
    for x in (78, 96, 114):
        p.curve((x, 56), (x - 8, 44), (x + 8, 34), (x, 20))


def plant(p: Pen, rng):
    p.poly([(66, 120), (134, 120), (124, 176), (76, 176)])
    p.line((62, 120), (138, 120))
    p.line((100, 120), (100, 64))
    for side, y in ((-1, 104), (1, 90), (-1, 76), (1, 64)):
        tip = (100 + side * 44, y - 18)
        p.curve((100, y), (100 + side * 10, y - 26), (tip[0] - side * 6, tip[1] - 6), tip)
        p.curve((100, y), (100 + side * 24, y + 4), (tip[0], tip[1] + 14), tip)


def flower(p: Pen, rng):
    p.curve((100, 186), (96, 150), (106, 120), (100, 96))
    p.curve((100, 150), (120, 136), (140, 140), (146, 150))
    p.curve((100, 150), (120, 162), (138, 160), (146, 150))
    for i in range(6):
        a = i * math.pi / 3
        p.ellipse(100 + 22 * math.cos(a), 72 + 22 * math.sin(a), 16, 9, rot=a)
    p.circle(100, 72, 10)


def sky(p: Pen, rng):
    p.circle(146, 60, 22)
    for x, y in ((40, 60), (88, 110)):
        p.arc(x, y, 14, math.pi, 2 * math.pi)
        p.arc(x + 20, y - 8, 18, math.pi, 2 * math.pi)
        p.arc(x + 42, y, 14, math.pi, 2 * math.pi)
        p.line((x - 14, y), (x + 56, y))
    for x in (30, 60, 150):
        p.curve((x, 160), (x + 6, 154), (x + 12, 154), (x + 18, 160))
        p.curve((x + 18, 160), (x + 24, 154), (x + 30, 154), (x + 36, 160))


def mountain(p: Pen, rng):
    p.poly([(4, 168), (70, 52), (110, 120), (140, 80), (196, 168)], closed=False)
    p.poly([(52, 84), (70, 52), (88, 84), (78, 78), (70, 88), (62, 78)], closed=False)
    p.line((4, 168), (196, 168))
    p.circle(160, 36, 12)
    p.curve((40, 168), (70, 150), (90, 160), (110, 140))


def bowl(p: Pen, rng):
    p.ellipse(100, 104, 66, 14)
    p.curve((34, 104), (40, 160), (160, 160), (166, 104))
    p.line((80, 156), (120, 156))
    p.curve((52, 106), (80, 96), (110, 116), (146, 102))
    p.line((128, 40), (78, 110))
    p.line((140, 46), (90, 114))
    for x in (66, 100, 126):
        p.curve((x, 84), (x - 8, 70), (x + 8, 60), (x, 44))


def moon(p: Pen, rng):
    p.arc(100, 96, 46, 0.7, 2 * math.pi - 0.7)
    p.arc(140, 96, 30, 1.73, 4.55)                      # the inner edge of the crescent
    for x, y in ((40, 40), (164, 150), (156, 36), (46, 160)):
        p.line((x - 6, y), (x + 6, y))
        p.line((x, y - 6), (x, y + 6))


def star(p: Pen, rng):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        r = 70 if i % 2 == 0 else 30
        pts.append((100 + r * math.cos(a), 104 + r * math.sin(a)))
    p.poly(pts)


def heart(p: Pen, rng):
    p.curve((100, 170), (40, 120), (30, 60), (72, 52))
    p.curve((72, 52), (92, 50), (100, 66), (100, 78))
    p.curve((100, 78), (100, 66), (108, 50), (128, 52))
    p.curve((128, 52), (170, 60), (160, 120), (100, 170))


def tree(p: Pen, rng):
    p.line((94, 180), (96, 112))
    p.line((108, 180), (106, 112))
    p.line((100, 140), (78, 118))
    for x, y, r in ((74, 96, 24), (100, 74, 30), (128, 96, 24), (100, 108, 22)):
        p.circle(x, y, r)
    p.line((20, 180), (180, 180))


def book(p: Pen, rng):
    p.poly([(100, 60), (40, 50), (36, 150), (100, 160)], closed=False)
    p.poly([(100, 60), (160, 50), (164, 150), (100, 160)], closed=False)
    p.line((100, 60), (100, 160))
    for i in range(5):
        y = 76 + i * 15
        p.line((50, y - 2), (90, y + 2))
        p.line((110, y + 2), (152, y - 2))


def shoes(p: Pen, rng):
    for ox, oy in ((22, 64), (72, 108)):
        p.curve((ox, oy + 40), (ox - 6, oy + 20), (ox + 10, oy + 6), (ox + 30, oy + 4))
        p.curve((ox + 30, oy + 4), (ox + 46, oy + 2), (ox + 50, oy + 14), (ox + 62, oy + 18))
        p.curve((ox + 62, oy + 18), (ox + 86, oy + 20), (ox + 104, oy + 28), (ox + 100, oy + 40))
        p.line((ox, oy + 40), (ox + 100, oy + 40))
        p.line((ox + 2, oy + 34), (ox + 98, oy + 34))
        for k in range(3):
            p.line((ox + 38 + k * 8, oy + 8 + k * 2), (ox + 44 + k * 8, oy + 18 + k * 2))
    p.line((4, 192), (196, 192))


def stairs(p: Pen, rng):
    pts, x, y = [(20, 180)], 20, 180
    for _ in range(5):
        y -= 28
        pts.append((x, y))
        x += 32
        pts.append((x, y))
    p.poly(pts, closed=False)
    p.line((20, 180), (x, 180))
    p.line((x, y), (x, 180))
    p.line((36, 122), (164, 10))
    for i in range(5):
        p.line((36 + 32 * i, 152 - 28 * i), (36 + 32 * i, 122 - 28 * i))


def bench(p: Pen, rng):
    p.line((30, 110), (170, 106))
    p.line((36, 96), (168, 92))
    p.line((40, 60), (160, 56))
    p.line((40, 76), (160, 72))
    for x, top, seat in ((44, 60, 110), (156, 56, 106)):
        p.line((x, top), (x, seat - 14))
        p.line((x, seat), (x, 150))
    p.line((10, 152), (190, 152))
    p.circle(170, 26, 12)


def door(p: Pen, rng):
    p.poly([(60, 180), (60, 50), (140, 50), (140, 180)], closed=False)
    p.arc(100, 50, 40, math.pi, 2 * math.pi)
    p.poly([(72, 66), (128, 66), (128, 112), (72, 112)])
    p.poly([(72, 124), (128, 124), (128, 168), (72, 168)])
    p.circle(130, 118, 4)
    p.line((40, 180), (160, 180))
    p.poly([(24, 180), (28, 156), (48, 156), (52, 180)], closed=False)
    for dx in (-8, 0, 8):
        p.curve((38, 156), (38 + dx, 140), (38 + dx * 2, 132), (38 + dx * 2.4, 124))


def dog(p: Pen, rng):
    p.circle(100, 70, 26)
    p.curve((78, 58), (62, 62), (62, 96), (76, 92))
    p.curve((122, 58), (138, 62), (138, 96), (124, 92))
    p.fill_circle(91, 68, 3)
    p.fill_circle(109, 68, 3)
    p.fill_circle(100, 80, 4)
    p.arc(100, 84, 8, 0.3, math.pi - 0.3)
    p.curve((84, 94), (64, 120), (66, 170), (80, 176))
    p.curve((116, 94), (136, 120), (134, 170), (120, 176))
    p.line((90, 130), (88, 176))
    p.line((110, 130), (112, 176))
    p.line((78, 176), (96, 176))
    p.line((104, 176), (122, 176))
    p.curve((132, 164), (156, 160), (166, 140), (160, 128))


def bottle(p: Pen, rng):
    p.line((76, 70), (76, 172))
    p.line((124, 70), (124, 172))
    p.curve((76, 172), (80, 182), (120, 182), (124, 172))
    p.curve((76, 70), (76, 56), (88, 52), (88, 40))
    p.curve((124, 70), (124, 56), (112, 52), (112, 40))
    p.poly([(86, 40), (114, 40), (114, 22), (86, 22)])
    p.curve((76, 110), (90, 104), (110, 116), (124, 110))
    for i in range(3):
        p.line((130, 96 + i * 26), (140, 96 + i * 26))
    for x, y in ((40, 120), (160, 60)):
        p.curve((x, y - 12), (x - 7, y), (x - 5, y + 8), (x, y + 8))
        p.curve((x, y + 8), (x + 5, y + 8), (x + 7, y), (x, y - 12))


def sunset(p: Pen, rng):
    p.line((0, 120), (200, 120))
    p.arc(100, 120, 34, math.pi, 2 * math.pi)
    for i in range(1, 8):
        a = math.pi + i * math.pi / 8
        p.line((100 + 42 * math.cos(a), 120 + 42 * math.sin(a)), (100 + 54 * math.cos(a), 120 + 54 * math.sin(a)))
    for half, y in ((30, 134), (20, 146), (10, 158)):
        p.line((100 - half, y), (100 + half, y))
    for x, y in ((40, 40), (62, 30)):
        p.curve((x - 8, y), (x - 4, y - 5), (x - 1, y - 4), (x, y))
        p.curve((x, y), (x + 1, y - 4), (x + 4, y - 5), (x + 8, y))


def long_shadow(p: Pen, rng):
    _stick(p, 70, 36, 0.9)
    p.poly([(62, 116), (78, 115), (180, 150), (156, 160)])
    for t in (0.25, 0.5, 0.75):
        a = (62 + (156 - 62) * t, 116 + (160 - 116) * t)
        b = (78 + (180 - 78) * t, 115 + (150 - 115) * t)
        p.line(a, b)
    p.circle(24, 24, 12)
    p.line((0, 170), (200, 172))


def street(p: Pen, rng):
    p.line((0, 190), (92, 64))
    p.line((200, 190), (108, 64))
    y, h = 180, 22
    while y > 70:
        p.line((100, y), (100, y - h))
        y -= h * 1.9
        h *= 0.68
    p.poly([(8, 96), (52, 96), (52, 144), (8, 144)])
    p.poly([(2, 98), (30, 72), (58, 98)], closed=False)
    p.poly([(24, 144), (24, 122), (36, 122), (36, 144)], closed=False)
    p.line((166, 160), (168, 110))
    p.circle(166, 94, 20)
    p.line((0, 64), (200, 64))


def water(p: Pen, rng):
    p.ellipse(100, 134, 84, 30)
    for x, y in ((60, 128), (104, 140), (128, 124)):
        p.curve((x, y), (x + 6, y - 5), (x + 12, y - 5), (x + 18, y))
        p.curve((x + 18, y), (x + 24, y - 5), (x + 30, y - 5), (x + 36, y))
    for i, x in enumerate((20, 28, 36)):
        p.line((x, 150), (x - 2 + i * 2, 96 + i * 6))
        p.ellipse(x - 2 + i * 2, 92 + i * 6, 3, 8)
    p.circle(150, 46, 16)
    p.curve((20, 104), (60, 84), (120, 90), (180, 104))


SUBJECTS = {
    "stick figures": stick_figures, "shapes": shapes, "an eye": eye, "a hand": hand, "a sleeping cat": cat_sleeping,
    "a face from the side": face_side, "a ball and its shadow": light_shadow, "a little comic": comic,
    "a little landscape": background, "her window at night": memory,
    "a mug": mug, "a plant": plant, "a flower": flower, "the sky": sky, "mountains": mountain, "a bowl of noodles": bowl,
    "the moon": moon, "a star": star, "a heart": heart, "a tree": tree, "a book": book, "a cat": cat,
    "some shoes": shoes, "stairs": stairs, "a bench": bench, "a door": door, "a dog": dog, "a water bottle": bottle,
    "a sunset": sunset, "a long shadow": long_shadow, "a street": street, "water": water,
}
STEP_SUBJECTS = [("stick", "stick figures"), ("circle", "shapes"), ("box", "shapes"), ("eye", "an eye"),
                 ("hand", "a hand"), ("cat sleeping", "a sleeping cat"), ("sleeping", "a sleeping cat"),
                 ("face", "a face from the side"), ("light", "a ball and its shadow"), ("shadow", "a ball and its shadow"),
                 ("comic", "a little comic"), ("background", "a little landscape"), ("memory", "her window at night")]
THINGS = [(("coffee", "mug", "tea", "latte", "cup", "boba"), "a mug"),
          (("ramen", "noodle", "soup", "bowl", "rice", "pho", "pasta", "food", "dinner", "lunch", "breakfast", "meal",
            "cook", "cooking", "curry"), "a bowl of noodles"),
          (("plant", "succulent", "cactus", "leaf", "leaves", "garden"), "a plant"),
          (("flower", "rose", "tulip", "bouquet", "bloom"), "a flower"),
          (("sky", "cloud", "sunset", "sunrise", "sunny", "beach", "sea", "ocean", "lake"), "the sky"),
          (("mountain", "hike", "hiking", "trail", "hill", "climb"), "mountains"),
          (("moon", "night", "stars", "midnight"), "the moon"),
          (("cat", "kitten", "kitty"), "a cat"),
          (("tree", "park", "forest", "woods", "autumn", "fall"), "a tree"),
          (("book", "read", "reading", "library", "novel", "study", "studying"), "a book"),
          (("love", "date", "heart", "crush", "valentine"), "a heart"),
          (("star", "win", "won", "proud", "award", "passed", "aced", "goal"), "a star")]
CAPTIONS = {
    "stick figures": ["stick people. one of them is you, guess which", "don't laugh. everyone starts with stick figures"],
    "shapes": ["circles and boxes, over and over. the cube almost looks 3D", "boxes. so many boxes"],
    "an eye": ["an eye. it's staring at you, sorry", "eyes are harder than they look"],
    "a hand": ["hands. why do they have so many fingers", "a hand that mostly looks like a hand"],
    "a sleeping cat": ["a cat, asleep. it's the only pose they hold still for", "sleepy cat. I'm jealous of it"],
    "a face from the side": ["a face from the side. the nose went its own way", "profile practice. it looks a bit smug"],
    "a ball and its shadow": ["light and shadow. it's a ball, I promise", "shading practice. the light comes from the top left"],
    "a little comic": ["a three-panel comic. you can guess the plot", "my first comic. it's a masterpiece of stick acting"],
    "a little landscape": ["practising backgrounds. a tiny house I'd like to live in", "a little hill and a sun"],
    "her window at night": ["from memory: a cat by a window at night", "drawn from memory, no looking"],
}
THING_CAPTIONS = ["{what}, the way I imagine it", "{what}. I drew it for you", "{what}, from what you told me"]


def subject_for_step(step: str) -> str:
    s = (step or "").lower()
    for word, subject in STEP_SUBJECTS:
        if word in s:
            return subject
    return "shapes"


def subject_for(text: str) -> str | None:
    """'ramen with Maya tonight' -> 'a bowl of noodles'; None if nothing she can draw comes up."""
    words = set(re.findall(r"[a-z]+", (text or "").lower()))
    for keys, subject in THINGS:
        if words & set(keys):
            return subject
    return None


def render(subject: str, skill: float, seed: int) -> list[list[int]]:
    rng = random.Random(seed)
    pen = Pen(rng, skill)
    SUBJECTS[subject](pen, rng)
    return pen.strokes


class Drawings(Part):
    name = "drawings"

    def __init__(self, store=None, clock=time.time, life=None, rng=None):
        super().__init__(store, clock)
        self.life = life
        self.rng = rng or random.Random()
        self._schema(SCHEMA)

    def skill(self) -> tuple[str, float]:
        """(the step she's on, how steady her hand is 0-1) from her learning arc."""
        learning = getattr(self.life, "learning", None) or {}
        steps = learning.get("steps") or []
        if not steps or self.life is None:
            return "", 0.5
        n = min(self.life.day() // max(1, int(learning.get("every_days", 3))), len(steps) - 1)
        return steps[n], 0.12 + 0.8 * n / max(1, len(steps) - 1)

    def draw(self, subject: str | None = None, why: str = "", title: str = "", caption: str = "") -> dict:
        step, skill = self.skill()
        practice = subject is None
        subject = subject if subject in SUBJECTS else subject_for_step(step)
        attempt = 1 + (self._rows("SELECT COUNT(*) AS n FROM drawings WHERE subject = ?", (subject,))[0]["n"]
                       if self.store is not None else 0)
        seed = self.rng.randrange(1 << 30)
        strokes = render(subject, max(0.05, min(0.95, skill + self.rng.uniform(-0.06, 0.06))), seed)
        if caption:
            pass
        elif subject in CAPTIONS:
            caption = self.rng.choice(CAPTIONS[subject])
            if practice and attempt > 1:
                caption = f"attempt #{attempt}: {caption}"
        else:
            caption = self.rng.choice(THING_CAPTIONS).format(what=(title or subject)).capitalize()
        row = {"day": self.today(), "subject": subject, "title": title or subject, "caption": caption,
               "strokes": strokes, "why": why, "skill": round(skill, 2)}
        if self.store is None:
            return {"id": 0, **row}
        cur = self._exec("INSERT INTO drawings (day, subject, title, caption, strokes, why, skill, created) VALUES (?,?,?,?,?,?,?,?)",
                         (row["day"], subject, row["title"], caption, json.dumps(strokes, separators=(",", ":")), why,
                          row["skill"], self.now().isoformat(timespec="seconds")))
        return self.get_one(cur.lastrowid)

    def get_one(self, did: int) -> dict | None:
        rows = self._rows("SELECT * FROM drawings WHERE id = ?", (int(did),))
        return self._show(rows[0]) if rows else None

    def for_why(self, why: str) -> dict | None:
        rows = self._rows("SELECT * FROM drawings WHERE why = ? ORDER BY id DESC LIMIT 1", (why,))
        return self._show(rows[0]) if rows else None

    def latest(self, n: int = 12) -> list[dict]:
        return [self._show(r) for r in self._rows("SELECT * FROM drawings ORDER BY id DESC LIMIT ?", (n,))]

    @staticmethod
    def _show(r: dict) -> dict:
        strokes = r["strokes"] if isinstance(r["strokes"], list) else json.loads(r["strokes"])
        return {"id": r["id"], "day": r["day"], "subject": r["subject"], "title": r["title"], "caption": r["caption"],
                "why": r.get("why", ""), "size": SIZE, "strokes": strokes}

    def practice(self, now: float | None = None) -> dict | None:
        """Her own daily practice sketch of what she's learning, so the sketchbook grows on its own
        (journal pages and sessions together were the only other way, and many days have neither).
        One a day from PRACTICE_HOUR; the very first one right away."""
        if self.store is None:
            return None
        d = dt.datetime.fromtimestamp(self.clock() if now is None else now)
        first = not self._rows("SELECT id FROM drawings LIMIT 1")
        if not first and (d.hour < PRACTICE_HOUR or self.get("practiced") == d.date().isoformat()):
            return None
        self.put("practiced", d.date().isoformat())
        return self.draw(why="practice")

    def observe(self, now: float):
        self.practice(now)

    def status(self) -> dict:
        try:
            self.practice()                       # opening the sketchbook never shows it empty
        except Exception:
            pass
        return {"drawings": self.latest(12), "learning": self.skill()[0]}

    def notes(self, user_text: str, last_reply: str = "") -> list[str]:
        if self.store is None or not SHOW.search(user_text):
            return []
        last = self.latest(1)
        if not last:
            return []
        d = last[0]
        when = "today" if d["day"] == self.today() else dt.date.fromisoformat(d["day"]).strftime("on %A")
        return [f"Your latest drawing, from {when}: {d['title']} (\"{d['caption']}\"). It's in your sketchbook on "
                "their phone (the Us tab); tell them to look, a little shy or proud"]
