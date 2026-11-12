"""World-space survey of the circuit GLB: per-part bounds/flatness, and a top-down map (PNG) to find the road."""
import json
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

src, out_png, out_json = sys.argv[1], sys.argv[2], sys.argv[3]
b = open(src, "rb").read()
clen = struct.unpack("<I", b[12:16])[0]
j = json.loads(b[20:20 + clen])
blen = struct.unpack("<I", b[20 + clen:24 + clen])[0]
bin_ = memoryview(b)[28 + clen:28 + clen + blen]


def acc(i, n=3):
    a = j["accessors"][i]; bv = j["bufferViews"][a["bufferView"]]
    stride = bv.get("byteStride"); off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    dt = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}[a["componentType"]]
    k = {"VEC3": 3, "VEC2": 2, "SCALAR": 1}[a["type"]]
    if stride and stride != k * np.dtype(dt).itemsize:
        raw = np.frombuffer(bin_, np.uint8, a["count"] * stride, off).reshape(-1, stride)
        return raw[:, :k * np.dtype(dt).itemsize].copy().view(dt).reshape(-1, k)
    arr = np.frombuffer(bin_, dt, a["count"] * k, off)
    return arr.reshape(-1, k) if k > 1 else arr


def trs(n):
    if "matrix" in n:
        return np.array(n["matrix"]).reshape(4, 4).T
    t = np.array(n.get("translation", [0, 0, 0])); s = np.array(n.get("scale", [1, 1, 1])); x, y, z, w = n.get("rotation", [0, 0, 0, 1])
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    M = np.eye(4); M[:3, :3] = R * s; M[:3, 3] = t; return M


world = {}
def walk(i, P):
    M = P @ trs(j["nodes"][i]); world[i] = M
    for c in j["nodes"][i].get("children", []): walk(c, M)
for r in j["scenes"][0]["nodes"]: walk(r, np.eye(4))

parts = []
allpts = []
for ni, M in world.items():
    n = j["nodes"][ni]
    if "mesh" not in n: continue
    for pr in j["meshes"][n["mesh"]]["primitives"]:
        P = acc(pr["attributes"]["POSITION"]).astype(np.float64)
        W = P @ M[:3, :3].T + M[:3, 3]
        tri = j["accessors"][pr["indices"]]["count"] // 3 if "indices" in pr else len(P) // 3
        mat = j["materials"][pr["material"]] if "material" in pr else {}
        lo, hi = W.min(0), W.max(0)
        parts.append({"node": ni, "name": n.get("name"), "mat": mat.get("name"), "tris": tri, "lo": lo.round(1).tolist(), "hi": hi.round(1).tolist(),
                      "tex": "baseColorTexture" in mat.get("pbrMetallicRoughness", {})})
        allpts.append((len(parts) - 1, W[:: max(1, len(W) // 4000)]))

lo = np.min([p["lo"] for p in parts], 0); hi = np.max([p["hi"] for p in parts], 0)
print("world extents (glTF, Y up):", lo.round(1), hi.round(1), "size", (hi - lo).round(1))
for p in sorted(parts, key=lambda p: -p["tris"])[:20]:
    sz = np.array(p["hi"]) - np.array(p["lo"])
    print(f"  node {p['node']:3d} {p['name']:22s} {p['mat']!s:28s} tris {p['tris']:6d} size x{sz[0]:7.1f} y{sz[1]:6.1f} z{sz[2]:7.1f} tex={p['tex']}")

# top-down map: X right, Z down (glTF top view), colour by part
S = 1600; pad = 20; span = max(hi[0] - lo[0], hi[2] - lo[2])
img = Image.new("RGB", (S, S), "white"); dr = ImageDraw.Draw(img)
rng = np.random.default_rng(1)
for k, W in allpts:
    col = tuple(int(c) for c in rng.integers(0, 200, 3))
    for x, _, z in W:
        u = pad + (x - lo[0]) / span * (S - 2 * pad); v = pad + (z - lo[2]) / span * (S - 2 * pad)
        dr.point((u, v), fill=col)
img.save(out_png)
json.dump({"lo": lo.tolist(), "hi": hi.tolist(), "parts": parts}, open(out_json, "w"))
print("wrote", out_png)
