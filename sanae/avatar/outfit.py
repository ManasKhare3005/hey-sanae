"""Sanae's outfit, borrowed from VRoid's AvatarSample_B (same VRoid sample terms as A): the varsity
jacket and the pleated skirt, refitted to AvatarSample_A's body.

Both samples are built on VRoid's base body with the same vertices in the same order, only with
different proportions. So each clothing vertex moves by how the body under it changed from B to A
(the average of the nearest body vertices' moves): the clothes keep B's tailoring but sit on A.
Skin weights carry over by bone name; B's extra bones (the skirt's and jacket's spring bones) aren't
in A, so their vertices follow the nearest bone A has.
"""
from __future__ import annotations

import io
import json

import numpy as np
from PIL import Image

from ..config import ROOT
from .edition import png, read_glb

DONOR = ROOT / "data" / "avatar-candidates" / "AvatarSample_B.vrm"
DONOR_URL = "https://raw.githubusercontent.com/madjin/vrm-samples/master/vroid/stable/AvatarSample_B.vrm"
NEAREST = 6                      # body vertices averaged per clothing vertex


def _views(gltf: dict, blob: bytes) -> list[bytes]:
    return [blob[v.get("byteOffset", 0):v.get("byteOffset", 0) + v["byteLength"]] for v in gltf["bufferViews"]]


def _array(gltf: dict, views: list[bytes], index: int) -> np.ndarray:
    acc = gltf["accessors"][index]
    dtype = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}[acc["componentType"]]
    n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
    arr = np.frombuffer(views[acc["bufferView"]], dtype, acc["count"] * n, acc.get("byteOffset", 0))
    return arr.reshape(-1, n).copy() if n > 1 else arr.copy()


def _body(gltf: dict) -> tuple[dict, dict]:
    mesh = next(m for m in gltf["meshes"] if m["name"] == "Body.baked")
    node = next(n for n in gltf["nodes"] if n.get("mesh") is not None and gltf["meshes"][n["mesh"]] is mesh)
    return mesh, node


def _skin_vertices(gltf: dict, views: list[bytes], attr: str = "POSITION") -> np.ndarray:
    mesh, _ = _body(gltf)
    prims = mesh["primitives"]
    values = _array(gltf, views, prims[0]["attributes"][attr])
    used = np.unique(np.concatenate([_array(gltf, views, p["indices"]) for p in prims
                                     if "SKIN" in gltf["materials"][p["material"]]["name"]]))
    return values[used].astype(float)


def nearest(points: np.ndarray, to: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Indices and distances of the k nearest `to` points for each point (chunked brute force)."""
    idx = np.empty((len(points), k), np.int64)
    dist = np.empty((len(points), k))
    for s in range(0, len(points), 512):
        d = ((points[s:s + 512, None, :] - to[None, :, :]) ** 2).sum(-1)
        part = np.argpartition(d, k, axis=1)[:, :k]
        idx[s:s + 512] = part
        dist[s:s + 512] = np.sqrt(np.take_along_axis(d, part, 1))
    return idx, dist


def refit(cloth: np.ndarray, donor_body: np.ndarray, body: np.ndarray) -> np.ndarray:
    """Move clothing made for donor_body onto body (same vertices, other proportions)."""
    idx, dist = nearest(cloth, donor_body, NEAREST)
    w = 1 / np.maximum(dist, 1e-4) ** 2
    w /= w.sum(1, keepdims=True)
    move = body - donor_body
    return cloth + (move[idx] * w[..., None]).sum(1)


def snug(cloth: np.ndarray, body: np.ndarray, normals: np.ndarray, keep: float, least: float = 0.008) -> np.ndarray:
    """Bring loose clothing closer to the body: only the distance straight out from the skin shrinks
    (to `keep` of it, never under `least`), so the shape and the folds stay."""
    idx, dist = nearest(cloth, body, NEAREST)
    w = 1 / np.maximum(dist, 1e-4) ** 2
    w /= w.sum(1, keepdims=True)
    at = (body[idx] * w[..., None]).sum(1)
    n = (normals[idx] * w[..., None]).sum(1)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-6)
    out = ((cloth - at) * n).sum(1)
    want = np.where(out > least, np.maximum(out * keep, least), out)
    return cloth - n * (out - want)[:, None]


def transplant(gltf: dict, views: list[bytes], parts: dict[str, str], drop: tuple[str, ...],
               fit: dict[str, float] | None = None) -> dict[str, int]:
    """Replace the base model's `drop` clothes with the donor's `parts` ({material key: new name}).
    fit: {material key: how much of the gap to the skin to keep} for clothes that hang too loose.
    Returns {new name: image index} so the caller can recolour the textures."""
    if not DONOR.exists():
        import requests
        DONOR.parent.mkdir(parents=True, exist_ok=True)
        DONOR.write_bytes(requests.get(DONOR_URL, timeout=120).content)
    dg, dblob = read_glb(DONOR.read_bytes())
    dviews = _views(dg, dblob)

    body_a, body_b = _skin_vertices(gltf, views), _skin_vertices(dg, dviews)
    normals_a = _skin_vertices(gltf, views, "NORMAL")
    assert len(body_a) == len(body_b), "the two bodies differ: can't refit the clothes"

    mesh_a, node_a = _body(gltf)
    mesh_b, node_b = _body(dg)
    joints_a = [gltf["nodes"][j]["name"] for j in gltf["skins"][node_a["skin"]]["joints"]]
    joints_b = [dg["nodes"][j]["name"] for j in dg["skins"][node_b["skin"]]["joints"]]
    parent_b = {dg["nodes"][c]["name"]: n["name"] for n in dg["nodes"] for c in n.get("children", [])}

    def to_a(name: str) -> int:
        while name not in joints_a:                    # a spring bone A doesn't have: its parent
            name = parent_b[name]
        return joints_a.index(name)

    joint_map = np.array([to_a(n) for n in joints_b], np.uint16)

    def add_view(data: bytes, target: int) -> int:
        gltf["bufferViews"].append({"buffer": 0, "byteOffset": 0, "byteLength": len(data), "target": target})
        views.append(data)
        return len(gltf["bufferViews"]) - 1

    def add_acc(arr: np.ndarray, kind: str, ctype: int, target: int, minmax: bool = False) -> int:
        acc = {"bufferView": add_view(arr.tobytes(), target), "componentType": ctype, "count": len(arr), "type": kind}
        if minmax:
            acc["min"], acc["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        gltf["accessors"].append(acc)
        return len(gltf["accessors"]) - 1

    # textures the donor's materials share with A's (flat normal map, rim matcap, black emission)
    tex_by_image = {gltf["images"][t["source"]]["name"]: i for i, t in enumerate(gltf["textures"])}

    def texture_for(donor_tex: int, rename: str | None) -> int:
        src = dg["images"][dg["textures"][donor_tex]["source"]]
        if rename is None and src["name"] in tex_by_image:
            return tex_by_image[src["name"]]
        data = dviews[src["bufferView"]]
        gltf["images"].append({"name": rename or src["name"], "mimeType": src.get("mimeType", "image/png"),
                               "bufferView": add_view(data, 0)})
        gltf["bufferViews"][-1].pop("target")
        gltf["textures"].append({"sampler": 0, "source": len(gltf["images"]) - 1})
        tex_by_image[rename or src["name"]] = len(gltf["textures"]) - 1
        return len(gltf["textures"]) - 1

    vrm_a, vrm_b = gltf["extensions"]["VRM"], dg["extensions"]["VRM"]
    first = mesh_b["primitives"][0]["attributes"]
    pos_b = _array(dg, dviews, first["POSITION"])
    nor_b = _array(dg, dviews, first["NORMAL"])
    uv_b = _array(dg, dviews, first["TEXCOORD_0"])
    jnt_b = _array(dg, dviews, first["JOINTS_0"])
    wgt_b = _array(dg, dviews, first["WEIGHTS_0"])

    images: dict[str, int] = {}
    new_prims = []
    for key, name in parts.items():
        prim = next(p for p in mesh_b["primitives"] if key in dg["materials"][p["material"]]["name"])
        tris = _array(dg, dviews, prim["indices"])
        used, local = np.unique(tris, return_inverse=True)
        pos = refit(pos_b[used].astype(float), body_b, body_a)
        if fit and key in fit:
            pos = snug(pos, body_a, normals_a, fit[key])
        pos = pos.astype(np.float32)
        jnt = joint_map[jnt_b[used].astype(np.int64)]
        # material: the donor's, its main texture copied under the new name, shared helpers mapped to A's
        mat = json.loads(json.dumps(dg["materials"][prim["material"]]))
        mat["name"] = name
        main = mat["pbrMetallicRoughness"]["baseColorTexture"]["index"]
        new_main = texture_for(main, name)
        images[name] = gltf["textures"][new_main]["source"]
        mat["pbrMetallicRoughness"]["baseColorTexture"]["index"] = new_main
        for slot in ("normalTexture", "emissiveTexture"):
            if slot in mat:
                mat[slot]["index"] = texture_for(mat[slot]["index"], None)
        gltf["materials"].append(mat)
        mp = json.loads(json.dumps(next(m for m in vrm_b["materialProperties"] if m["name"] == dg["materials"][prim["material"]]["name"])))
        mp["name"] = name
        mp["textureProperties"] = {k: (new_main if v == main else texture_for(v, None)) for k, v in mp["textureProperties"].items()}
        vrm_a["materialProperties"].append(mp)
        new_prims.append({
            "attributes": {"POSITION": add_acc(pos, "VEC3", 5126, 34962, True),
                           "NORMAL": add_acc(nor_b[used].astype(np.float32), "VEC3", 5126, 34962),
                           "TEXCOORD_0": add_acc(uv_b[used].astype(np.float32), "VEC2", 5126, 34962),
                           "JOINTS_0": add_acc(jnt.astype(np.uint16), "VEC4", 5123, 34962),
                           "WEIGHTS_0": add_acc(wgt_b[used].astype(np.float32), "VEC4", 5126, 34962)},
            "indices": add_acc(local.astype(np.uint32), "SCALAR", 5125, 34963),
            "material": len(gltf["materials"]) - 1, "mode": 4,
        })

    mesh_a["primitives"] = [p for p in mesh_a["primitives"]
                            if not any(k in gltf["materials"][p["material"]]["name"] for k in drop)] + new_prims
    return images


def load_image(gltf: dict, views: list[bytes], index: int) -> Image.Image:
    return Image.open(io.BytesIO(views[gltf["images"][index]["bufferView"]]))


def save_image(gltf: dict, views: list[bytes], index: int, img: Image.Image):
    views[gltf["images"][index]["bufferView"]] = png(img)
