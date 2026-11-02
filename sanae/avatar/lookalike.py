"""Build Sanae's 3D look from VRoid's sample AvatarSample_A (VRoid's sample terms: personal and
commercial use and edits allowed; https://vroid.pixiv.help/hc/en-us/articles/4402394424089), matched to
Alex's reference picture: long dark-brown wavy hair, warm skin, dark brown eyes and thick brows, a
charcoal top with a dark red collar, plus over-ear headphones (graphite, a thin sakura-pink ring on
each cup). Her outfit over it is AvatarSample_B's varsity jacket (charcoal, cream sleeves, a blue
"NOW" down one sleeve) and pleated skirt, refitted to A's body (outfit.py).

Everything is done on the file: textures are recoloured and the hair mesh is lengthened (stretched
downward below the ears, pushed out so it falls over the shoulders and chest instead of through them,
with a gentle wave). The result stays out of git (dashboard/public/avatar is ignored). Rebuild any time:

    .venv\\Scripts\\python -m sanae.avatar.lookalike
"""
from __future__ import annotations

import colorsys
import io
import json
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import ROOT
from . import outfit
from .edition import png, ramp, read_glb, write_glb

BASE_URL = "https://raw.githubusercontent.com/madjin/vrm-samples/master/vroid/stable/AvatarSample_A.vrm"
BASE = ROOT / "data" / "avatar-candidates" / "AvatarSample_A.vrm"
OUT = ROOT / "dashboard" / "public" / "avatar" / "sanae.vrm"

HAIR_DARK, HAIR_LIGHT = (14, 9, 7), (88, 62, 48)           # dark brown, from shadow to sheen
SWEATER_DARK, SWEATER_LIGHT = (24, 24, 26), (84, 84, 88)   # charcoal (the top under the jacket)
JACKET_DARK, JACKET_LIGHT = (24, 24, 27), (236, 228, 218)  # charcoal body, cream sleeves and stripes
SKIRT_TINT = (255, 170, 190)                               # sakura pink
COLLAR_DARK, COLLAR_LIGHT = (40, 10, 12), (120, 34, 34)    # the dark red top under the sweater
SKIN_TINT = (0.97, 0.86, 0.76)                             # warmer, a little tanned
NOW_BLUE = (122, 158, 222, 255)

# Hair: below STRETCH_FROM (just under the eyes) the strands are stretched down to about the chest
STRETCH_FROM, HAIR_BOTTOM = 1.385, 1.07
MARGIN = 0.010                                            # how far the hair stays off the body
WAVE = 0.007                                              # wave depth (m)

# Texture regions (fractions of the texture), found from the layouts
INNER_TOP = (0.23, 0.14, 0.77, 0.47)                      # Body_00: the top under the cardigan
COLLAR = (0.28, 0.13, 0.72, 0.215)                         # ...its lace neckline: the dark red collar
NOW_AT = (0.225, 0.134)                                   # the jacket's texture: the outer side of one sleeve


def lum_of(rgb: np.ndarray) -> np.ndarray:
    return (rgb @ np.array([0.299, 0.587, 0.114], np.float32)) / 255


def recolor_ramp(img: Image.Image, dark, light, lo: float, hi: float, gamma: float = 1.0,
                 mask: np.ndarray | None = None) -> Image.Image:
    """Map the brightness (lo..hi) onto a dark->light ramp, keeping the painted shading."""
    rgba = np.asarray(img.convert("RGBA")).astype(np.float32)
    t = np.clip((lum_of(rgba[..., :3]) - lo) / (hi - lo), 0, 1) ** gamma
    rgb = ramp(t, dark, light)
    if mask is not None:
        rgb = rgb * mask[..., None] + rgba[..., :3] * (1 - mask[..., None])
    return Image.fromarray(np.dstack([rgb, rgba[..., 3:]]).clip(0, 255).astype(np.uint8), "RGBA")


def box_mask(w: int, h: int, box, blur: float = 2.0) -> Image.Image:
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rectangle([box[0] * w, box[1] * h, box[2] * w, box[3] * h], fill=255)
    return m.filter(ImageFilter.GaussianBlur(blur))


def skin(img: Image.Image) -> Image.Image:
    """Warm the light, skin-coloured pixels only (leaves clothes, lace and eyes alone)."""
    rgba = np.asarray(img.convert("RGBA")).astype(np.float32)
    rgb = rgba[..., :3] / 255
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = (mx - mn) / np.maximum(mx, 1e-6)
    warm = (rgb[..., 0] >= rgb[..., 1]) & (rgb[..., 1] >= rgb[..., 2] - 0.02)
    w = (warm & (mx > 0.55) & (sat < 0.45)).astype(np.float32)
    w = np.asarray(Image.fromarray((w * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.5)), np.float32) / 255
    tinted = rgba[..., :3] * np.array(SKIN_TINT, np.float32)
    rgba[..., :3] = tinted * w[..., None] + rgba[..., :3] * (1 - w[..., None])
    return Image.fromarray(rgba.clip(0, 255).astype(np.uint8), "RGBA")


def body(img: Image.Image) -> Image.Image:
    """Skin warmer; the dark top under the cardigan becomes more sweater, its lace neckline a dark red collar."""
    out = skin(img)
    rgba = np.asarray(out).astype(np.float32)
    dark = np.clip((0.42 - lum_of(rgba[..., :3])) / 0.12, 0, 1)        # only the dark fabric and lace
    collar = np.asarray(box_mask(out.width, out.height, COLLAR, 3), np.float32) / 255
    top = np.asarray(box_mask(out.width, out.height, INNER_TOP, 4), np.float32) / 255 * (1 - collar)
    out = recolor_ramp(out, SWEATER_DARK, SWEATER_LIGHT, 0.05, 0.40, mask=top * dark)
    return recolor_ramp(out, COLLAR_DARK, COLLAR_LIGHT, 0.0, 0.35, mask=collar * dark)


def jacket(img: Image.Image) -> Image.Image:
    """Sample B's navy-and-white varsity jacket -> charcoal body with cream sleeves, "NOW" down a sleeve."""
    out = recolor_ramp(img, JACKET_DARK, JACKET_LIGHT, 0.06, 0.92)
    return draw_now(out, NOW_AT, 180, 0.042)


def skirt(img: Image.Image) -> Image.Image:
    """The pleated skirt: B's pink, a little softer (towards her sakura accent)."""
    rgba = np.asarray(img.convert("RGBA")).astype(np.float32)
    rgba[..., :3] = rgba[..., :3] * 0.85 + np.array(SKIRT_TINT, np.float32) * 0.15
    return Image.fromarray(rgba.clip(0, 255).astype(np.uint8), "RGBA")


def draw_now(img: Image.Image, at: tuple[float, float], angle: float, height: float) -> Image.Image:
    """"NOW" down the sleeve in soft blue, read from the shoulder down (as in the picture). at = centre
    (texture fractions), angle = rotation so it runs from shoulder to cuff, height = letter size."""
    w, h = img.size
    size = int(h * height)
    try:
        font = ImageFont.truetype("arialbd.ttf", size)
    except OSError:
        font = ImageFont.load_default()
    text = Image.new("RGBA", (int(size * 2.6), int(size * 1.25)), (0, 0, 0, 0))
    ImageDraw.Draw(text).text((text.width / 2, text.height / 2), "NOW", font=font, fill=NOW_BLUE, anchor="mm")
    text = text.rotate(angle, expand=True)
    x, y = int(at[0] * w - text.width / 2), int(at[1] * h - text.height / 2)
    img.alpha_composite(text, (x, y))
    return img


def brows(img: Image.Image) -> Image.Image:
    """Darker, thicker brows (as in the picture)."""
    rgba = img.convert("RGBA")
    alpha = rgba.split()[3].filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(1))
    solid = Image.new("RGBA", rgba.size, (34, 22, 17, 255))
    solid.putalpha(alpha)
    return solid


def iris(img: Image.Image) -> Image.Image:
    rgba = np.asarray(img.convert("RGBA")).astype(np.float32) / 255
    flat = rgba[..., :3].reshape(-1, 3)
    hsv = np.array([colorsys.rgb_to_hsv(*p) for p in flat])
    hsv[:, 0] = np.where(hsv[:, 1] > 0.12, 0.07, hsv[:, 0])          # dark brown
    hsv[:, 1] = np.minimum(hsv[:, 1], 0.55)
    hsv[:, 2] *= 0.72
    rgb = np.array([colorsys.hsv_to_rgb(*p) for p in hsv]).reshape(rgba.shape[0], rgba.shape[1], 3)
    rgba[..., :3] = rgb
    return Image.fromarray((rgba * 255).astype(np.uint8), "RGBA")


# ----- geometry -----

def accessor_array(gltf: dict, views: list[bytes], index: int) -> np.ndarray:
    acc = gltf["accessors"][index]
    assert acc["componentType"] == 5126 and "byteStride" not in gltf["bufferViews"][acc["bufferView"]]
    data = views[acc["bufferView"]]
    n = {"VEC3": 3, "VEC2": 2, "VEC4": 4}[acc["type"]]
    return np.frombuffer(data, np.float32, acc["count"] * n, acc.get("byteOffset", 0)).reshape(-1, n).copy()


def index_array(gltf: dict, views: list[bytes], index: int) -> np.ndarray:
    acc = gltf["accessors"][index]
    dtype = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32}[acc["componentType"]]
    return np.frombuffer(views[acc["bufferView"]], dtype, acc["count"], acc.get("byteOffset", 0)).astype(np.int64)


def strands(tris: np.ndarray, n: int) -> np.ndarray:
    """Connected pieces of the hair mesh (one label per vertex): each lock is moved as one."""
    labels = np.arange(n)
    while True:
        low = labels[tris].min(1)
        before = labels.copy()
        for c in range(3):
            np.minimum.at(labels, tris[:, c], low)
        labels = labels[labels]                                         # follow chains faster
        if np.array_equal(labels, before):
            return labels


def body_extent(body_pos: np.ndarray, heights: np.ndarray, xs: np.ndarray):
    """The body's front (max z) and back (min z) per height band and sideways (x) slice; nan = no body.
    In the bind pose the arms stick straight out (T-pose), so only the torso counts."""
    torso = body_pos[np.abs(body_pos[:, 0]) < 0.17]
    front = np.full((len(heights), len(xs)), np.nan, np.float32)
    back = front.copy()
    dx = xs[1] - xs[0]
    for k, y in enumerate(heights):
        band = torso[np.abs(torso[:, 1] - y) < 0.025]
        for j, x in enumerate(xs):
            s = band[np.abs(band[:, 0] - x) < dx]                       # overlapping slices: no gaps
            if len(s):
                front[k, j], back[k, j] = s[:, 2].max(), s[:, 2].min()
    return front, back


def lengthen_hair(pos: np.ndarray, body_pos: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Stretch the hair below the eyes down to the chest, then let each lock fall in front of or behind
    the shoulders (whichever side it's on), clear of the body, with a gentle wave."""
    y0 = STRETCH_FROM
    low = pos[:, 1].min()
    k = (y0 - HAIR_BOTTOM) / (y0 - low)
    # leave the fringe over the face alone (smooth falloff, so no strand tears at the edge). Her face is
    # at -z in this model: keeping +z (as before) left the back of the hair short, ending at the nape
    keep = np.clip((-pos[:, 2] - 0.02) / 0.03, 0, 1) * np.clip((0.075 - np.abs(pos[:, 0])) / 0.02, 0, 1)
    drop = np.maximum(y0 - pos[:, 1], 0)
    new = pos.copy()
    new[:, 1] = pos[:, 1] - drop * (k - 1) * (1 - keep)
    moved = (1 - keep) * np.clip(drop / 0.03, 0, 1)                    # nothing changes above y0

    heights = np.linspace(HAIR_BOTTOM - 0.05, y0, 40)
    xs = np.linspace(-0.2, 0.2, 41)
    front, back = body_extent(body_pos, heights, xs)
    hi = np.clip(np.searchsorted(heights, new[:, 1]), 0, len(heights) - 1)
    xi = np.clip(np.round((new[:, 0] - xs[0]) / (xs[1] - xs[0])).astype(int), 0, len(xs) - 1)
    f, b = front[hi, xi], back[hi, xi]
    body_here = ~np.isnan(f)
    # which side each lock falls on: where most of its moved part already is (vs the body's middle)
    labels = strands(tris, len(pos))
    mid = np.where(body_here, (np.nan_to_num(f) + np.nan_to_num(b)) / 2, 0.0)
    side = np.where(new[:, 2] >= mid, 1.0, -1.0) * (moved > 0)
    votes = np.bincount(labels, weights=side, minlength=len(pos))
    in_front = votes[labels] >= 0
    target = np.where(in_front, np.nan_to_num(f) + MARGIN, np.nan_to_num(b) - MARGIN)
    push = np.where(in_front, np.maximum(target - new[:, 2], 0), np.minimum(target - new[:, 2], 0))
    push = np.where(body_here, push, 0.0)
    # move whole locks together (the deepest push in each lock, per height band), so they keep their shape.
    # The bands are smoothed and blended (not stepped): a step between bands showed as a kink across the hair
    new_drop = np.maximum(y0 - new[:, 1], 0)
    nb = 64
    pos_b = np.clip(new_drop / 0.02, 0, nb - 1.001)
    band = pos_b.astype(int)
    uniq, lock = np.unique(labels, return_inverse=True)
    deep = np.zeros((len(uniq), nb))
    np.maximum.at(deep, (lock, band), np.abs(push))
    kernel = np.ones(5) / 5
    deep = np.array([np.convolve(np.pad(r, 2, mode="edge"), kernel, mode="valid") for r in deep])
    frac = pos_b - band
    amount = deep[lock, band] * (1 - frac) + deep[lock, np.minimum(band + 1, nb - 1)] * frac
    new[:, 2] += np.where(in_front, 1.0, -1.0) * amount * moved
    # a gentle wave, one phase and direction per lock (per-vertex angles tore the locks into zig-zags)
    ang = np.arctan2(new[:, 0], new[:, 2])
    lock_ang = np.arctan2(np.bincount(lock, np.sin(ang)), np.bincount(lock, np.cos(ang)))[lock]
    phase = (uniq[lock] % 7) * 0.9
    wave = WAVE * np.sin(new_drop * 38 + phase) * np.clip(new_drop / 0.08, 0, 1) * moved
    new[:, 0] += wave * np.sin(lock_ang)
    new[:, 2] += wave * np.cos(lock_ang)
    return new


# ----- headphones -----
# Cat-ear headphones in cream (like her jacket's sleeves): charcoal cushions, a slim sakura-pink ring on
# each cup's face (her accent colour on the phone and dashboard; seasons recolour it) and two cat ears on
# the band with pink insides. Made here from simple shapes: a band lying on the top of her hair, two cups
# with cushions, the ears. They hang off the head bone, so they turn with her head.

HP_SHELL, HP_CUSHION, HP_ACCENT, HP_EAR = (0.93, 0.89, 0.84), (0.20, 0.19, 0.21), (1.0, 0.62, 0.72), (1.0, 0.70, 0.78)
EAR_AT, EAR_H = 0.62, 0.05                                 # cat ears: angle from the top (rad), height (m)
EAR_Y = 1.415                                              # ear height (the cups' centre)


def tube(points: np.ndarray, radius: float, sides: int = 14, flat: float = 1.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A tube along a curve: positions, normals, triangles. flat < 1 squashes it in the curve's plane
    (a headband: thin over the hair, wide front to back)."""
    n = len(points)
    tang = np.gradient(points, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True)
    # the curve's plane normal (both curves here are flat): a frame that never lines up with the tangent
    centred = points - points.mean(0)
    ref = np.linalg.svd(centred, full_matrices=False)[2][-1]
    pos, nor = [], []
    for i in range(n):
        u = np.cross(tang[i], ref)
        u /= np.linalg.norm(u)
        v = np.cross(tang[i], u)
        for k in range(sides):
            a = 2 * np.pi * k / sides
            d = np.cos(a) * u * flat + np.sin(a) * v
            pos.append(points[i] + d * radius)
            nor.append(np.cos(a) * u / flat + np.sin(a) * v)
    tris = []
    for i in range(n - 1):
        for k in range(sides):
            a, b = i * sides + k, i * sides + (k + 1) % sides
            c, d = a + sides, b + sides
            tris += [(a, c, b), (b, c, d)]
    return np.array(pos), np.array(nor), np.array(tris)


def disc_cylinder(centre, axis, radius: float, length: float, sides: int = 28, bevel: float = 0.25):
    """A short cylinder along `axis` (x: +1 / -1) with rounded-off outer edge and closed ends."""
    cx, cy, cz = centre
    # profile from the inner face (towards the head) to the outer face: (offset along axis, radius)
    prof = [(0.0, 0.0), (0.0, radius * 0.92), (length * 0.08, radius), (length * (1 - bevel), radius),
            (length, radius * (1 - bevel * 0.6)), (length, 0.0)]
    pos, nor, tris = [], [], []
    rings = []
    for j, (off, r) in enumerate(prof):
        ring = []
        for k in range(sides):
            a = 2 * np.pi * k / sides
            y, z = np.cos(a), np.sin(a)
            pos.append((cx + axis * off, cy + y * r, cz + z * r))
            if r == 0.0 or (j in (0, len(prof) - 1)):
                nor.append((axis * (1 if j else -1), 0, 0))
            else:
                nor.append((0, y, z))
            ring.append(len(pos) - 1)
        rings.append(ring)
    for j in range(len(rings) - 1):
        for k in range(sides):
            a, b = rings[j][k], rings[j][(k + 1) % sides]
            c, d = rings[j + 1][k], rings[j + 1][(k + 1) % sides]
            tris += [(a, c, b), (b, c, d)] if axis > 0 else [(a, b, c), (b, d, c)]
    return np.array(pos, float), np.array(nor, float), np.array(tris)


def ring(centre, axis, radius: float, thickness: float, sides: int = 40):
    """A thin torus facing along `axis` (the accent ring on a cup's outer face)."""
    cx, cy, cz = centre
    pts = np.array([(cx, cy + np.cos(a) * radius, cz + np.sin(a) * radius)
                    for a in np.linspace(0, 2 * np.pi, sides + 1)])
    return tube(pts, thickness, 8)


def cone(base, up, across, depth, rw: float, rd: float, h: float, sides: int = 16):
    """A cone with an oval base (rw across, rd deep) pointing along `up`: a cat ear."""
    base, up, across, depth = (np.asarray(v, float) for v in (base, up, across, depth))
    pos, nor, tris = [], [], []
    for k in range(sides):
        a = 2 * np.pi * k / sides
        out = np.cos(a) * across * rw + np.sin(a) * depth * rd
        radial = np.cos(a) * across / rw + np.sin(a) * depth / rd
        radial /= np.linalg.norm(radial)
        pos.append(base + out)
        n = radial + up * (np.linalg.norm(out) / h)
        nor.append(n / np.linalg.norm(n))
    pos.append(base + up * h)
    nor.append(up)
    apex = sides
    pos.append(base)
    nor.append(-up)
    centre = sides + 1
    for k in range(sides):
        j = (k + 1) % sides
        tris += [(k, j, apex), (k, centre, j)]
    return np.array(pos), np.array(nor), np.array(tris)


def headphones(hair: np.ndarray) -> dict[str, list[tuple[np.ndarray, np.ndarray, np.ndarray]]]:
    """Pieces by material, in model space (metres), sized from the hair around the head."""
    near = hair[np.abs(hair[:, 1] - EAR_Y) < 0.02]
    side = np.abs(near[:, 0]).max()                       # the hair's width at ear height
    zc = float(np.median(near[np.abs(near[:, 0]) > side - 0.02][:, 2]))
    cup_r, cup_len, pad = 0.038, 0.016, 0.009         # slim cups: at 3 cm + a 1.4 cm cushion they stuck out like earmuffs
    inner = side - 0.004                                  # cushions press into the hair a little
    parts: dict[str, list] = {"shell": [], "cushion": [], "accent": [], "ear": []}
    for sgn in (-1, 1):
        parts["cushion"].append(disc_cylinder((sgn * inner, EAR_Y, zc), sgn, cup_r * 0.93, pad + 0.002, bevel=0.45))
        cup = disc_cylinder((sgn * (inner + pad), EAR_Y, zc), sgn, cup_r, cup_len, bevel=0.35)
        parts["shell"].append(cup)
        # on the outer face, inside the bevel (a halo round the rim looked like a toy)
        parts["accent"].append(ring((sgn * (inner + pad + cup_len + 0.0005), EAR_Y, zc), sgn, cup_r * 0.62, 0.0022))
    # the band: over the top of the hair, in the plane of the cups, a little off the surface
    slab = hair[np.abs(hair[:, 2] - zc) < 0.02]
    cy = EAR_Y
    angles = np.linspace(-np.pi / 2 * 0.98, np.pi / 2 * 0.98, 61)          # from one ear, over, to the other
    rel = slab[:, :2] - np.array([0.0, cy])
    ang = np.arctan2(rel[:, 0], rel[:, 1])
    rad = np.hypot(rel[:, 0], rel[:, 1])
    # the hair's surface, not its stray tips: with the max, single strands lifted the band off the head
    reach = np.array([np.percentile(rad[np.abs(ang - a) < 0.06], 85) if (np.abs(ang - a) < 0.06).any() else 0.1
                      for a in angles])
    reach = np.convolve(np.pad(reach, 4, mode="edge"), np.ones(9) / 9, mode="valid") + 0.003   # lying on the hair
    pts = np.stack([np.sin(angles) * reach, cy + np.cos(angles) * reach, np.full_like(angles, zc)], 1)
    # ends come down onto the top of the cups
    pts[0, 1] = pts[-1, 1] = EAR_Y + cup_r * 0.7
    pts[0, 0], pts[-1, 0] = -(inner + pad + cup_len * 0.5), inner + pad + cup_len * 0.5
    band = tube(pts, 0.009, 16, flat=0.55)              # ~10 mm thick, 18 mm wide
    parts["shell"].append(band)
    # cat ears standing on the band, leaning out a little; the pink inside faces forward (her face is -z)
    for sgn in (-1, 1):
        a = sgn * EAR_AT
        r = float(np.interp(a, angles, reach))
        at = np.array([np.sin(a) * r, cy + np.cos(a) * r, zc])
        up = np.array([np.sin(a * 1.25), np.cos(a * 1.25), 0.0])
        across = np.array([np.cos(a * 1.25), -np.sin(a * 1.25), 0.0])
        parts["shell"].append(cone(at, up, across, (0, 0, 1), 0.024, 0.011, EAR_H))
        parts["ear"].append(cone(at + up * 0.006 + np.array([0, 0, -0.0045]), up, across, (0, 0, 1),
                                 0.014, 0.006, EAR_H * 0.66))
    return parts


def outward(p: np.ndarray, n: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Triangles wound to face along their normals. Inward-wound ones were culled, so the dark outline
    pass (drawn on back faces) was all that showed and the headphones looked flat black."""
    t = np.asarray(t)
    face = np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]])
    flip = (face * (n[t[:, 0]] + n[t[:, 1]] + n[t[:, 2]])).sum(1) < 0
    t = t.copy()
    t[flip] = t[flip][:, [0, 2, 1]]
    return t


def add_headphones(gltf: dict, views: list[bytes], hair: np.ndarray):
    """New meshes + materials (glTF and MToon), on a node under the head bone."""
    nodes = gltf["nodes"]
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    head = next(i for i, n in enumerate(nodes) if n.get("name") == "J_Bip_C_Head")
    head_at, i = np.zeros(3), head
    while i is not None:
        n = nodes[i]
        assert n.get("rotation", [0, 0, 0, 1]) in ([0, 0, 0, 1], [0.0, 0.0, 0.0, 1.0]) and n.get("scale", [1, 1, 1]) in ([1, 1, 1], [1.0, 1.0, 1.0])
        head_at += np.array(n.get("translation", [0, 0, 0]))
        i = parent.get(i)

    def add_view(data: bytes, target: int | None = None) -> int:
        view = {"buffer": 0, "byteOffset": 0, "byteLength": len(data)}
        if target:
            view["target"] = target
        gltf["bufferViews"].append(view)
        views.append(data)
        return len(gltf["bufferViews"]) - 1

    def add_acc(arr: np.ndarray, kind: str, ctype: int, target: int, minmax: bool = False) -> int:
        acc = {"bufferView": add_view(arr.tobytes(), target), "componentType": ctype, "count": len(arr), "type": kind}
        if minmax:
            acc["min"], acc["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        gltf["accessors"].append(acc)
        return len(gltf["accessors"]) - 1

    vrm = gltf["extensions"]["VRM"]
    template_mat = next(m for m in gltf["materials"] if "Tops" in m["name"])
    template_mp = next(m for m in vrm["materialProperties"] if "Tops" in m["name"])
    colours = {"shell": HP_SHELL, "cushion": HP_CUSHION, "accent": HP_ACCENT, "ear": HP_EAR}
    mat_index = {}
    for key, rgb in colours.items():
        name = f"Sanae_Headphones_{key}"
        m = json.loads(json.dumps(template_mat))
        m["name"] = name
        m["pbrMetallicRoughness"] = {"baseColorFactor": [*rgb, 1], "metallicFactor": 0, "roughnessFactor": 0.6}
        for k in ("normalTexture", "emissiveTexture"):
            m.pop(k, None)
        m["alphaMode"] = "OPAQUE"
        m["doubleSided"] = False
        m["emissiveFactor"] = list(rgb) if key == "accent" else [0, 0, 0]
        gltf["materials"].append(m)
        mp = json.loads(json.dumps(template_mp))
        mp["name"] = name
        mp["renderQueue"] = 2000
        shade = [c * 0.62 for c in rgb] if key != "accent" else list(rgb)     # shaded, not a black cut-out
        mp["vectorProperties"].update({"_Color": [*rgb, 1], "_ShadeColor": [*shade, 1],
                                       "_EmissionColor": [*(c * 0.9 for c in rgb), 1] if key == "accent" else [0, 0, 0, 1],
                                       "_RimColor": [0.30, 0.22, 0.26, 1] if key != "accent" else [0, 0, 0, 1],
                                       "_OutlineColor": [0.06, 0.05, 0.07, 1]})
        mp["floatProperties"].update({"_BlendMode": 0, "_CullMode": 2, "_ShadeShift": -0.15, "_ShadeToony": 0.7,
                                      "_RimFresnelPower": 3.0, "_RimLift": 0.1,
                                      "_OutlineWidth": 0.02 if key != "accent" else 0.0})
        mp["textureProperties"] = {k: v for k, v in mp["textureProperties"].items() if k == "_SphereAdd"}
        mp["keywordMap"] = {"MTOON_OUTLINE_COLOR_FIXED": True, "MTOON_OUTLINE_WIDTH_WORLD": True}
        vrm["materialProperties"].append(mp)
        mat_index[key] = len(gltf["materials"]) - 1

    primitives = []
    for key, pieces in headphones(hair).items():
        pos, nor, tri, base = [], [], [], 0
        for p, n, t in pieces:
            t = outward(p, n, t)
            pos.append(p)
            nor.append(n)
            tri.append(t + base)
            base += len(p)
        P = (np.concatenate(pos) - head_at).astype(np.float32)        # relative to the head bone
        N = np.concatenate(nor).astype(np.float32)
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-6)
        T = np.concatenate(tri).astype(np.uint32).reshape(-1)
        primitives.append({
            "attributes": {"POSITION": add_acc(P, "VEC3", 5126, 34962, True), "NORMAL": add_acc(N, "VEC3", 5126, 34962),
                           "TEXCOORD_0": add_acc(np.zeros((len(P), 2), np.float32), "VEC2", 5126, 34962)},
            "indices": add_acc(T, "SCALAR", 5125, 34963), "material": mat_index[key], "mode": 4,
        })
    gltf["meshes"].append({"name": "Headphones", "primitives": primitives})
    nodes.append({"name": "Headphones", "mesh": len(gltf["meshes"]) - 1})
    nodes[head].setdefault("children", []).append(len(nodes) - 1)


def build(base: Path = BASE, out: Path = OUT) -> Path:
    if not base.exists():
        base.parent.mkdir(parents=True, exist_ok=True)
        base.write_bytes(requests.get(BASE_URL, timeout=120).content)
    gltf, blob = read_glb(base.read_bytes())
    views = [blob[v.get("byteOffset", 0):v.get("byteOffset", 0) + v["byteLength"]] for v in gltf["bufferViews"]]
    images = gltf["images"]
    by_name = {img["name"]: i for i, img in enumerate(images)}

    def load(name):
        return Image.open(io.BytesIO(views[images[by_name[name]]["bufferView"]]))

    def replace(name, img):
        views[images[by_name[name]]["bufferView"]] = png(img)

    for name in ("F00_000_Hair_00_01", "F00_000_Hair_00_02", "F00_000_Hair_00_03", "F00_000_Hair_00_04"):
        replace(name, recolor_ramp(load(name), HAIR_DARK, HAIR_LIGHT, 0.08, 0.85, gamma=1.15))
    replace("F00_000_00_Face_00", skin(load("F00_000_00_Face_00")))
    replace("F00_000_00_Body_00", body(load("F00_000_00_Body_00")))
    # her outfit: sample B's varsity jacket and pleated skirt instead of A's cardigan and shorts
    new = outfit.transplant(gltf, views, {"Tops": "Sanae_Jacket", "Bottoms": "Sanae_Skirt"}, drop=("Tops", "Bottoms"),
                           fit={"Tops": 0.6})                # B's jacket hangs loose: she looked lost in it
    for name, fix in (("Sanae_Jacket", jacket), ("Sanae_Skirt", skirt)):
        outfit.save_image(gltf, views, new[name], fix(outfit.load_image(gltf, views, new[name])))
    replace("F00_000_00_FaceBrow_00", brows(load("F00_000_00_FaceBrow_00")))
    replace("F00_000_00_EyeIris_00", iris(load("F00_000_00_EyeIris_00")))

    # longer hair (all hair primitives share one vertex buffer)
    meshes = {m["name"]: m for m in gltf["meshes"]}
    hair_acc = meshes["Hair001.baked"]["primitives"][0]["attributes"]["POSITION"]
    body_acc = meshes["Body.baked"]["primitives"][0]["attributes"]["POSITION"]
    tris = np.concatenate([index_array(gltf, views, p["indices"]) for p in meshes["Hair001.baked"]["primitives"]])
    pos = lengthen_hair(accessor_array(gltf, views, hair_acc), accessor_array(gltf, views, body_acc), tris.reshape(-1, 3))
    acc = gltf["accessors"][hair_acc]
    view = bytearray(views[acc["bufferView"]])
    off = acc.get("byteOffset", 0)
    view[off:off + pos.nbytes] = pos.astype(np.float32).tobytes()
    views[acc["bufferView"]] = bytes(view)
    acc["min"], acc["max"] = pos.min(0).tolist(), pos.max(0).tolist()
    add_headphones(gltf, views, pos)

    vrm = gltf["extensions"]["VRM"]
    for mp in vrm["materialProperties"]:
        vec, flt = mp["vectorProperties"], mp["floatProperties"]
        if mp["name"].startswith("Sanae_"):
            continue
        if "HAIR" in mp["name"]:
            vec["_ShadeColor"] = [0.55, 0.45, 0.42, 1]
            vec["_RimColor"] = [0.30, 0.20, 0.20, 1]              # a warm rim so dark hair still has a shape
            flt.update({"_RimFresnelPower": 3.5, "_RimLift": 0.05})
        elif "Tops" in mp["name"]:
            vec["_ShadeColor"] = [0.66, 0.64, 0.70, 1]
            vec["_OutlineColor"] = [0.08, 0.07, 0.09, 1]          # softer than black: less of a drawn line
            vec["_RimColor"] = [0.20, 0.15, 0.18, 1]
            flt.update({"_RimFresnelPower": 4.0, "_RimLift": 0.0})
            flt["_OutlineWidth"] = flt.get("_OutlineWidth", 0.1) * 0.55
        elif "Bottoms" in mp["name"]:
            vec["_OutlineColor"] = [0.08, 0.07, 0.09, 1]
            flt["_OutlineWidth"] = flt.get("_OutlineWidth", 0.1) * 0.6
        elif "SKIN" in mp["name"]:
            vec["_ShadeColor"] = [0.93, 0.74, 0.66, 1]           # (no rim: the tights share this material)
    vrm["meta"].update({"title": "Sanae", "author": "Sanae assistant (from VRoid AvatarSample_A)", "version": "1.0"})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(write_glb(gltf, views))
    return out


if __name__ == "__main__":
    print(f"Sanae written to {build()}")
