"""Report a glTF car's parts and fit each tyre's exact centre (the mesh that reaches the ground and the car's full width)."""
import json
import struct
import sys

import numpy as np

b = open(sys.argv[1], "rb").read()
clen = struct.unpack("<I", b[12:16])[0]
j = json.loads(b[20:20 + clen])
blen = struct.unpack("<I", b[20 + clen:24 + clen])[0]
bin_ = b[28 + clen:28 + clen + blen]
print("root matrix:", [n.get("matrix") for n in j["nodes"] if "matrix" in n])
print("node TRS:", [(n.get("name"), n.get("translation"), n.get("rotation"), n.get("scale")) for n in j["nodes"] if any(k in n for k in ("translation", "rotation", "scale"))])


def pos(mi):
    a = j["accessors"][j["meshes"][mi]["primitives"][0]["attributes"]["POSITION"]]
    bv = j["bufferViews"][a["bufferView"]]
    assert not bv.get("byteStride") or bv["byteStride"] == 12
    return np.frombuffer(bin_, np.float32, a["count"] * 3, bv.get("byteOffset", 0) + a.get("byteOffset", 0)).reshape(-1, 3)


P = {mi: pos(mi) for mi in range(len(j["meshes"]))}
allp = np.vstack(list(P.values()))
lo, hi = allp.min(0), allp.max(0)
print("extents", lo.round(2), hi.round(2))
for mi, p in P.items():
    print(f"  mesh {mi} ({j['nodes'][mi].get('name') if mi < len(j['nodes']) else ''}): {len(p)} v, min {p.min(0).round(2)} max {p.max(0).round(2)}")

# tyre mesh: touches the ground and spans the full width
ground = lo[2]
cands = [mi for mi, p in P.items() if p[:, 2].min() < ground + 0.05 and np.abs(p[:, 0]).max() > 0.95 * np.abs(allp[:, 0]).max()]
print("tyre mesh candidates:", cands)
ymid = (lo[1] + hi[1]) / 2
for mi in cands:
    p = P[mi]
    out = p[np.abs(p[:, 0]) > np.abs(p[:, 0]).max() - 3.0]
    for sx in (1, -1):
        for half in ("lowY", "highY"):
            q = out[(np.sign(out[:, 0]) == sx) & ((out[:, 1] < ymid) if half == "lowY" else (out[:, 1] >= ymid))]
            if len(q) < 50:
                continue
            # tyre = the cluster touching the ground: keep vertices within the tallest-z band around the lowest point's y
            low = q[q[:, 2] < ground + 0.3]
            yc0 = np.median(low[:, 1])
            t = q[np.abs(q[:, 1] - yc0) < 3.2]
            yc, zc = (t[:, 1].min() + t[:, 1].max()) / 2, (t[:, 2].min() + t[:, 2].max()) / 2
            r = np.hypot(t[:, 1] - yc, t[:, 2] - zc)
            print(f"  mesh {mi} x{'+' if sx > 0 else '-'} {half}: centre y {yc:.3f} z {zc:.3f} | radius max {r.max():.3f} | y span {t[:,1].min():.2f}..{t[:,1].max():.2f} z span {t[:,2].min():.2f}..{t[:,2].max():.2f} | |x| {np.abs(t[:,0]).min():.2f}..{np.abs(t[:,0]).max():.2f}")
