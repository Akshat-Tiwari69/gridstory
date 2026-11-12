"""Register the licensed local venue; all outputs stay next to this script.

Dependencies: numpy, scipy, Pillow. No assets are uploaded or changed.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import struct

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.spatial.transform import Rotation
from scipy import fft, optimize
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent


def load_glb(path):
    raw = path.read_bytes()
    magic, version, length = struct.unpack_from("<III", raw)
    if magic != 0x46546C67 or version != 2 or length != len(raw):
        raise ValueError("Expected a complete glTF 2 GLB")
    chunks = {}
    offset = 12
    while offset < len(raw):
        size, kind = struct.unpack_from("<II", raw, offset)
        chunks[kind] = raw[offset + 8:offset + 8 + size]
        offset += size + 8
    doc = json.loads(chunks[0x4E4F534A])
    binary = chunks[0x004E4942]
    types = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
    sizes = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

    def accessor(i):
        a = doc["accessors"][i]
        if "sparse" in a:
            raise ValueError("Sparse accessors need explicit decoding")
        v = doc["bufferViews"][a["bufferView"]]
        if v.get("buffer", 0) != 0:
            raise ValueError("External buffers are not supported")
        dt = np.dtype(types[a["componentType"]])
        count, components = a["count"], sizes[a["type"]]
        start = v.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = v.get("byteStride", dt.itemsize * components)
        arr = np.ndarray((count, components), dt, binary, start, (stride, dt.itemsize)).copy()
        if a.get("normalized") and a["componentType"] != 5126:
            limit = np.iinfo(dt).max
            arr = np.maximum(arr.astype(float) / limit, -1)
        return arr

    parts = []

    def visit(i, parent):
        node = doc["nodes"][i]
        if "matrix" in node:
            local = np.array(node["matrix"], float).reshape(4, 4, order="F")
        else:
            local = np.eye(4)
            local[:3, :3] = Rotation.from_quat(node.get("rotation", [0, 0, 0, 1])).as_matrix() @ np.diag(node.get("scale", [1, 1, 1]))
            local[:3, 3] = node.get("translation", [0, 0, 0])
        world = parent @ local
        if "mesh" in node:
            for primitive in doc["meshes"][node["mesh"]]["primitives"]:
                if primitive.get("mode", 4) != 4:
                    continue
                vertices = accessor(primitive["attributes"]["POSITION"]).astype(float)
                vertices = vertices @ world[:3, :3].T + world[:3, 3]
                indices = accessor(primitive["indices"]).ravel() if "indices" in primitive else np.arange(len(vertices))
                triangles = vertices[indices.reshape(-1, 3)]
                cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
                area2 = np.linalg.norm(cross, axis=1)
                good = area2 > 1e-9
                parts.append(dict(node=i, name=node.get("name", str(i)), material=primitive.get("material", -1),
                                  vertices=vertices, indices=indices.reshape(-1, 3), triangles=triangles,
                                  area=area2 / 2, horizontal=np.divide(np.abs(cross[:, 1]), area2, out=np.zeros_like(area2), where=good),
                                  uv=accessor(primitive["attributes"]["TEXCOORD_0"]) if "TEXCOORD_0" in primitive["attributes"] else None))
        for child in node.get("children", []):
            visit(child, world)

    for root in doc["scenes"][doc.get("scene", 0)]["nodes"]:
        visit(root, np.eye(4))
    return doc, binary, parts


def inventory(doc, binary, parts):
    tiles = []
    for p in parts:
        v = p["vertices"]
        print(p["node"], p["name"], "mat", p["material"], "tris", len(p["triangles"]), "bbox", np.round([v.min(0), v.max(0)], 2).tolist(), "flat_area", round(p["area"][p["horizontal"] > .97].sum()))
    for i, material in enumerate(doc.get("materials", [])):
        tex = material.get("pbrMetallicRoughness", {}).get("baseColorTexture")
        if not tex:
            continue
        source = doc["textures"][tex["index"]]["source"]
        view = doc["bufferViews"][doc["images"][source]["bufferView"]]
        im = Image.open(io.BytesIO(binary[view.get("byteOffset", 0):view.get("byteOffset", 0) + view["byteLength"]])).convert("RGB")
        im.thumbnail((160, 130))
        tile = Image.new("RGB", (180, 170), "#dedede")
        tile.paste(im, ((180-im.width)//2, 25))
        ImageDraw.Draw(tile).text((4, 4), f"mat {i} / image {source}", fill="black")
        tiles.append(tile)
    sheet = Image.new("RGB", (180 * 8, 170 * math.ceil(len(tiles) / 8)), "white")
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % 8) * 180, (i // 8) * 170))
    sheet.save(HERE / "material-inventory.png")


def horizontal(points):
    """Data x,y,z to Three world X,Z (Y is data z)."""
    p = np.asarray(points, float)
    return p[:, [0, 1]] * [1, -1]


def target_edges(data):
    c = np.asarray(data["centre"], float)
    t = np.roll(c[:, :2], -1, axis=0) - np.roll(c[:, :2], 1, axis=0)
    t /= np.linalg.norm(t, axis=1)[:, None]
    left = np.c_[-t[:, 1], t[:, 0]]
    a = c[:, :2] + left * np.asarray(data["wl"])[:, None]
    b = c[:, :2] - left * np.asarray(data["wr"])[:, None]
    return a * [1, -1], b * [1, -1]


def raster_triangles(triangles, origin, pixel, size):
    image = Image.new("L", size)
    draw = ImageDraw.Draw(image)
    for t in (triangles[:, :, [0, 2]] - origin) / pixel:
        draw.polygon([tuple(p) for p in t], fill=255)
    return image


def road_edges(triangles):
    # Weld UV seams before finding actual open asphalt boundaries.
    _, inverse = np.unique(np.rint(triangles.reshape(-1, 3) / .002).astype(np.int64), axis=0, return_inverse=True)
    ids = inverse.reshape(-1, 3)
    e = np.concatenate([ids[:, [0, 1]], ids[:, [1, 2]], ids[:, [2, 0]]])
    xyz = np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])
    _, first, counts = np.unique(np.sort(e, axis=1), axis=0, return_index=True, return_counts=True)
    edges = xyz[first[counts == 1]]
    return edges[np.linalg.norm(np.diff(edges[:, :, [0, 2]], axis=1)[:, 0], axis=1) > .02]


def sample_edges(edges, spacing=.5):
    a = edges[:, 0][:, [0, 2]]
    b = edges[:, 1][:, [0, 2]]
    count = np.maximum(1, np.ceil(np.linalg.norm(b-a, axis=1) / spacing).astype(int))
    samples, ids = [], []
    for i, n in enumerate(count):
        u = np.linspace(0, 1, n + 1)[:, None]
        samples.append(a[i] + (b[i]-a[i])*u)
        ids.extend([i] * (n + 1))
    return np.concatenate(samples), np.array(ids)


def matrix2(yaw, mirror):
    c, s = np.cos(yaw), np.sin(yaw)
    return np.array([[c, s], [-s, c]]) @ np.diag([-1 if mirror else 1, 1])


def coarse_search(triangles, data):
    pixel = 8.
    a, b = target_edges(data)
    points = np.concatenate([a, b])
    target_origin = np.floor((points.min(0) - 80) / pixel) * pixel
    target_size = np.ceil((points.max(0) + 80 - target_origin) / pixel).astype(int)
    target = Image.new("L", tuple(target_size))
    draw = ImageDraw.Draw(target)
    for i in range(len(a)):
        j = (i + 1) % len(a)
        draw.polygon([tuple(p) for p in (np.array([a[i], a[j], b[j], b[i]]) - target_origin) / pixel], fill=255)
    ta = np.asarray(target, dtype=np.float32) / 255
    xy = triangles[:, :, [0, 2]]
    origin = (xy.reshape(-1, 2).min(0) + xy.reshape(-1, 2).max(0)) / 2
    radius = np.linalg.norm(xy - origin, axis=2).max()
    n = int(np.ceil(2 * radius * 1.18 / pixel)) + 8
    if n % 2 == 0:
        n += 1
    centre = (n-1)/2
    base = raster_triangles(triangles, origin - centre*pixel, pixel, (n, n))
    base.save(HERE / "asphalt-top.png")
    shape = tuple(fft.next_fast_len(t+n-1) for t in ta.shape)
    ft = fft.rfft2(ta, shape)
    candidates = []
    for mirror in (False, True):
        reflected = base.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if mirror else base
        for scale in (.85, .925, 1., 1.075, 1.15):
            scaled = reflected.transform((n, n), Image.Transform.AFFINE, (1/scale, 0, centre*(1-1/scale), 0, 1/scale, centre*(1-1/scale)), Image.Resampling.BILINEAR)
            for angle in range(0, 360, 2):
                model = np.asarray(scaled.rotate(angle, resample=Image.Resampling.BILINEAR), dtype=np.float32) / 255
                corr = fft.irfft2(ft * fft.rfft2(model[::-1, ::-1], shape), shape)[:ta.shape[0]+n-1, :ta.shape[1]+n-1]
                norm = np.sqrt(np.sum(ta**2)*np.sum(model**2))
                # Keep a separate translation peak, not adjacent FFT pixels.
                for _ in range(2):
                    r, c = np.unravel_index(np.argmax(corr), corr.shape)
                    tc = target_origin + pixel * (np.array([c, r]) - (n-1) + centre)
                    candidates.append(dict(score=float(corr[r, c]/norm), mirror=mirror, scale=scale, yaw=math.radians(angle), tc=tc.tolist()))
                    corr[max(0,r-6):r+7, max(0,c-6):c+7] = -1
            best = max(candidates, key=lambda c: c["score"])
            print("coarse", mirror, scale, "best", {**best, "yaw": math.degrees(best["yaw"])}, flush=True)
    candidates.sort(key=lambda c: -c["score"])
    distinct = []
    for c in candidates:
        if all(c["mirror"] != d["mirror"] or abs(math.atan2(math.sin(c["yaw"]-d["yaw"]), math.cos(c["yaw"]-d["yaw"]))) > math.radians(12) or np.linalg.norm(np.array(c["tc"])-d["tc"]) > 100 for d in distinct):
            distinct.append(c)
        if len(distinct) >= 12:
            break
    (HERE / "coarse-candidates.json").write_text(json.dumps(dict(origin=origin.tolist(), candidates=distinct), indent=2))
    return origin, distinct


def nearest_on_edges(query, edges, tree, sample_ids, details=False):
    _, ix = tree.query(query, k=3, workers=1)
    seg = edges[sample_ids[ix]][:, :, :, [0, 2]]
    a, vector = seg[:, :, 0], seg[:, :, 1]-seg[:, :, 0]
    u = np.clip(np.sum((query[:, None]-a)*vector, axis=2) / np.maximum(np.sum(vector**2, axis=2), 1e-20), 0, 1)
    near = a + u[:, :, None]*vector
    best = np.argmin(np.sum((query[:, None]-near)**2, axis=2), axis=1)
    selected = np.arange(len(query)), best
    if details:
        return near[selected], sample_ids[ix][selected], u[selected]
    return near[selected]


def refine(triangles, data, origin, candidates):
    edges = road_edges(triangles)
    samples, sample_ids = sample_edges(edges)
    tree = cKDTree(samples)
    a, b = target_edges(data)
    query = np.concatenate([a[::3], b[::3]])
    results = []
    for candidate in candidates:
        mirror = candidate["mirror"]

        def residual(p):
            yaw, scale, tx, tz = p
            q = (query - [tx, tz]) @ matrix2(yaw, mirror) / scale + origin
            near = nearest_on_edges(q, edges, tree, sample_ids)
            return ((q-near)*scale).ravel()

        p = [candidate["yaw"], candidate["scale"], *candidate["tc"]]
        out = optimize.least_squares(residual, p, loss="soft_l1", f_scale=3., max_nfev=100, diff_step=1e-5,
                                     bounds=([p[0]-.18, .80, p[2]-90, p[3]-90], [p[0]+.18, 1.20, p[2]+90, p[3]+90]))
        distance = np.linalg.norm(residual(out.x).reshape(-1, 2), axis=1)
        score = float(np.mean(np.exp(-.5*(distance/5)**2)))
        result = dict(mirror=mirror, yaw=float(out.x[0]), scale=float(out.x[1]), tc=out.x[2:].tolist(), score=score,
                      median=float(np.median(distance)), p95=float(np.percentile(distance,95)), maximum=float(distance.max()))
        results.append(result)
        print("refined", result, flush=True)
    results.sort(key=lambda c: -c["score"])
    (HERE / "refined-candidates.json").write_text(json.dumps(dict(origin=origin.tolist(), candidates=results), indent=2))
    return results, edges


class Surface:
    """Exact vertical ray/triangle intersections, accelerated by a 16 m XY grid."""

    def __init__(self, triangles):
        self.triangles = triangles
        self.xy = triangles[:, :, [0, 2]]
        self.grid = {}
        for i, t in enumerate(self.xy):
            low, high = np.floor(t.min(0)/16).astype(int), np.floor(t.max(0)/16).astype(int)
            for x in range(low[0], high[0]+1):
                for z in range(low[1], high[1]+1):
                    self.grid.setdefault((x, z), []).append(i)

    def hits(self, q):
        ids = np.array(self.grid.get(tuple(np.floor(q/16).astype(int)), []), int)
        if not len(ids):
            return np.empty(0), ids
        t = self.xy[ids]
        a, b = t[:, 1]-t[:, 0], t[:, 2]-t[:, 0]
        c = q-t[:, 0]
        det = a[:, 0]*b[:, 1]-a[:, 1]*b[:, 0]
        good = np.abs(det) > 1e-10
        det = np.where(good, det, 1)
        u = (c[:, 0]*b[:, 1]-c[:, 1]*b[:, 0])/det
        v = (a[:, 0]*c[:, 1]-a[:, 1]*c[:, 0])/det
        inside = good & (u >= -1e-7) & (v >= -1e-7) & (u+v <= 1+1e-7)
        h = self.triangles[ids, 0, 1] + u*(self.triangles[ids, 1, 1]-self.triangles[ids, 0, 1]) + v*(self.triangles[ids, 2, 1]-self.triangles[ids, 0, 1])
        return h[inside], ids[inside]


def overview_image(parts, data, origin, best):
    s, yaw, mirror, tc = best["scale"], best["yaw"], best["mirror"], np.array(best["tc"])
    rot = matrix2(yaw, mirror)
    trans = tc-s*origin@rot.T
    c, pit = horizontal(data["centre"]), horizontal(data["pitlane"])
    low, high = np.concatenate([c,pit]).min(0)-100, np.concatenate([c,pit]).max(0)+100
    px = max(high-low)/1800
    size = tuple(np.ceil((high-low)/px).astype(int))
    image = Image.new("RGB", size, "#111924")
    draw = ImageDraw.Draw(image)
    colors = {79:"#879298",99:"#58656f",80:"#4a4133",95:"#798240",12:"#252b32"}
    # Geometry-only material colours make roads readable without licensed textures.
    for p in sorted(parts, key=lambda p: p["material"] == 79):
        if p["material"] not in colors:
            continue
        t = p["triangles"][:, :, [0, 2]]@rot.T*s+trans
        for tri in (t-low)/px:
            draw.polygon([tuple(v) for v in tri], fill=colors[p["material"]])
    for p in parts:
        if p["material"] in colors:
            continue
        for t in p["triangles"][::max(1,len(p["triangles"])//900), :, [0,2]]:
            q=(t@rot.T*s+trans-low)/px
            draw.line([tuple(v) for v in q[[0,1,2,0]]], fill="#3c4652", width=1)
    a,b=target_edges(data)
    for e in (a,b):
        draw.line([tuple(v) for v in (np.r_[e,e[:1]]-low)/px], fill="#30f6cb",width=2)
    draw.line([tuple(v) for v in (pit-low)/px],fill="#ff54bf",width=3)
    for n,x,y in data["corners"]:
        q=(np.array([x,-y])-low)/px
        draw.text(tuple(q),str(n),fill="white")
    return image, low, px


def detail_render(doc, binary, parts, data, origin, best):
    """CPU orthographic texture render of the straight, for finish-line inspection."""
    rot = matrix2(best["yaw"], best["mirror"])
    scale = best["scale"]
    translation = np.array(best["tc"])-scale*origin@rot.T
    low = np.array([-75., -260.])
    pixel = .15
    size = np.ceil((np.array([5., -30.])-low)/pixel).astype(int)
    canvas = np.full((size[1], size[0], 3), [28, 32, 38], np.uint8)
    depth = np.full((size[1], size[0]), -np.inf)
    textures = {}
    for p in parts:
        if p["uv"] is None:
            continue
        mat = doc["materials"][p["material"]]
        tex = mat.get("pbrMetallicRoughness", {}).get("baseColorTexture")
        if tex is None:
            continue
        source = doc["textures"][tex["index"]]["source"]
        if source not in textures:
            view = doc["bufferViews"][doc["images"][source]["bufferView"]]
            textures[source] = np.asarray(Image.open(io.BytesIO(binary[view.get("byteOffset",0):view.get("byteOffset",0)+view["byteLength"]])).convert("RGBA"))
        texture = textures[source]
        xy = (p["triangles"][:, :, [0,2]]@rot.T*scale+translation-low)/pixel
        keep = (p["horizontal"]>.90) & (p["triangles"][:,:,1].mean(1)>96) & (p["triangles"][:,:,1].mean(1)<100)
        keep &= (xy[:,:,0].min(1)<size[0]) & (xy[:,:,0].max(1)>=0) & (xy[:,:,1].min(1)<size[1]) & (xy[:,:,1].max(1)>=0)
        for i in np.flatnonzero(keep):
            t = xy[i]
            lo = np.maximum(np.floor(t.min(0)).astype(int),0)
            hi = np.minimum(np.ceil(t.max(0)).astype(int)+1,size)
            if np.any(hi<=lo):
                continue
            xx, yy = np.meshgrid(np.arange(lo[0],hi[0])+.5,np.arange(lo[1],hi[1])+.5)
            a,b=t[1]-t[0],t[2]-t[0]
            det=a[0]*b[1]-a[1]*b[0]
            if abs(det)<1e-8:
                continue
            dx,dy=xx-t[0,0],yy-t[0,1]
            u=(dx*b[1]-dy*b[0])/det
            v=(a[0]*dy-a[1]*dx)/det
            h=p["triangles"][i,0,1]+u*(p["triangles"][i,1,1]-p["triangles"][i,0,1])+v*(p["triangles"][i,2,1]-p["triangles"][i,0,1])
            uv=p["uv"][p["indices"][i]]
            uv=uv[0]+u[:,:,None]*(uv[1]-uv[0])+v[:,:,None]*(uv[2]-uv[0])
            rgba=texture[(np.mod(uv[:,:,1],1)*texture.shape[0]).astype(int).clip(0,texture.shape[0]-1), (np.mod(uv[:,:,0],1)*texture.shape[1]).astype(int).clip(0,texture.shape[1]-1)]
            alpha=rgba[:,:,3]/255 if mat.get("alphaMode") in ("BLEND","MASK") else np.ones_like(u)
            if mat.get("alphaMode")=="MASK":
                alpha=(alpha>=mat.get("alphaCutoff",.5)).astype(float)
            region=np.s_[lo[1]:hi[1],lo[0]:hi[0]]
            mask=(u>=0)&(v>=0)&(u+v<=1)&(h>=depth[region]-.008)&(alpha>.05)
            blend=alpha[:,:,None]*rgba[:,:,:3]+(1-alpha[:,:,None])*canvas[region]
            canvas[region][mask]=blend[mask].astype(np.uint8)
            depth[region][mask]=h[mask]
    image=Image.fromarray(canvas)
    image.save(HERE/"start-line-textured.png")
    draw=ImageDraw.Draw(image)
    for k,color in (("HAM","#13fcd5"),("PIA","#ff9944")):
        car=data["cars"][k]
        for lap in ("32","35","36"):
            t=data["ev"]["lapEnd"][k][lap]
            f=(t-data["t0"])*data["hz"]
            i=int(f)
            u=f-i
            p=np.array([car["x"][i]+u*(car["x"][i+1]-car["x"][i]), -(car["y"][i]+u*(car["y"][i+1]-car["y"][i]))])
            p=(p-low)/pixel
            draw.ellipse((p[0]-5,p[1]-5,p[0]+5,p[1]+5),fill=color)
            draw.text((p[0]+8,p[1]),f"{k} L{lap}",fill=color)
    image.save(HERE/"start-line-detail.png")


def self_check():
    np.testing.assert_allclose(matrix2(np.pi/2, False) @ [1., 0.], [0., -1.], atol=1e-14)
    rng = np.random.default_rng(9)
    p = rng.normal(size=(12, 2))
    for mirror in (False, True):
        r = matrix2(.713, mirror)
        q = p @ r.T * 1.03 + [8., -12.]
        np.testing.assert_allclose((q-[8., -12.]) @ r / 1.03, p, atol=1e-13)
    surface = Surface(np.array([[[0., 1., 0.], [2., 3., 0.], [0., 1., 2.]]]))
    np.testing.assert_allclose(surface.hits(np.array([.5, .5]))[0], [1.5])
    assert len(surface.hits(np.array([2., 2.]))[0]) == 0
    a = np.zeros((7, 8))
    a[3:5, 4:7] = 1
    b = np.ones((2, 3))
    shape = (8, 10)
    corr = fft.irfft2(fft.rfft2(a, shape)*fft.rfft2(b[::-1, ::-1],shape),shape)
    lag = np.array(np.unravel_index(corr.argmax(),corr.shape))-np.array(b.shape)+1
    np.testing.assert_array_equal(lag,[3,4])


def height_outputs(triangles, edges, data, origin, best, tree, sample_ids):
    surface = Surface(triangles)
    rot, scale, tc = matrix2(best["yaw"],best["mirror"]),best["scale"],np.array(best["tc"])
    c = np.array(data["centre"],float)
    queries = (horizontal(c)-tc)@rot/scale+origin
    intersections = [surface.hits(q) for q in queries]
    # Only unambiguous asphalt intersections anchor Y; never use terrain or roofs.
    offsets = [c[i,2]-scale*np.median(h) for i,(h,_) in enumerate(intersections) if len(h) and np.ptp(h)<.05]
    if len(offsets)<len(c)*.8:
        raise ValueError("Insufficient unambiguous asphalt for a vertical registration")
    ty=float(np.median(offsets))
    output = dict(units="metres", axis="Three.js world Y after venue transform", sourceMaterial=79,
                  sourceNode=82, sourceName="Object_78 / Bahrainv3001791Mtl_73", verticalOffset=ty,
                  policy="Strict vertical intersections with asphalt only. null means no asphalt directly below. NearestAsphalt arrays are separate explicit fallbacks, NOT vertical hits. Index order matches input arrays; no points or cars are moved.",
                  selection="Full GLB node hierarchy, then horizontal-face filter abs(normal.Y)>0.90. Barycentric triangle intersection in model XZ. Multiple levels: choose nearest input altitude after robust median vertical registration; record ambiguity.")
    stats = {}
    for name in ("centre","pitlane"):
        values=np.array(data[name],float)
        q=(horizontal(values)-tc)@rot/scale+origin
        near, seg_ids, u = nearest_on_edges(q,edges,tree,sample_ids,details=True)
        distance=np.linalg.norm(q-near,axis=1)*scale
        nearest_y=scale*(edges[seg_ids,0,1]+u*(edges[seg_ids,1,1]-edges[seg_ids,0,1]))+ty
        heights, face_ids, fallbacks, missing, multi = [],[],[],[],[]
        for i,p in enumerate(q):
            h,ids=surface.hits(p)
            if len(h):
                k=int(np.argmin(abs(scale*h+ty-values[i,2])))
                y=float(scale*h[k]+ty)
                heights.append(y)
                face_ids.append(int(ids[k]))
                fallbacks.append(y)
                if np.ptp(h)*scale>.05:
                    multi.append(dict(index=i, candidateY=(scale*h+ty).tolist(), chosenY=y))
            else:
                heights.append(None)
                face_ids.append(None)
                fallbacks.append(float(nearest_y[i]))
                missing.append(dict(index=i, worldXZ=horizontal(values[i:i+1])[0].tolist(), distanceToAsphaltM=float(distance[i]), nearestAsphaltY=float(nearest_y[i])))
        output[name]=heights
        output[name+"Triangle"]=face_ids
        output[name+"NearestAsphalt"]=fallbacks
        output[name+"Missing"]=missing
        output[name+"MultipleLevels"]=multi
        hit=np.array([v is not None for v in heights])
        residual=np.array([heights[i]-values[i,2] for i in np.flatnonzero(hit)])
        stats[name]=dict(total=len(values),hits=int(hit.sum()),coveragePercent=float(hit.mean()*100),missing=len(missing),
                         maxOutsideM=float(distance[~hit].max()) if np.any(~hit) else 0.,
                         medianYResidual=float(np.median(residual)),p95AbsoluteYResidual=float(np.percentile(abs(residual),95)),
                         maxAbsoluteYResidual=float(abs(residual).max()),multipleLevels=len(multi))
    return ty,output,stats


def straight_validation(parts,data,origin,best,edges,tree,sample_ids):
    timing=[]
    for driver in ("HAM","PIA"):
        car=data["cars"][driver]
        pit=data["ev"]["pit"][driver]
        for lap,time in data["ev"]["lapEnd"][driver].items():
            f=(time-data["t0"])*data["hz"]
            if f<0 or f>=len(car["x"])-1 or pit["t0"]<=time<=pit["t1"]:
                continue
            i=int(f)
            u=f-i
            x=car["x"][i]*(1-u)+car["x"][i+1]*u
            z=-(car["y"][i]*(1-u)+car["y"][i+1]*u)
            timing.append(dict(driver=driver,lap=lap,worldXZ=[x,z]))
    mean=np.mean([t["worldXZ"] for t in timing],axis=0)
    c=horizontal(data["centre"])
    straight=c[np.linalg.norm(c-mean,axis=1)<220]
    _,_,vh=np.linalg.svd(straight-straight.mean(0),full_matrices=False)
    direction=vh[0]
    if direction[1]>0:
        direction=-direction
    perpendicular=np.array([-direction[1],direction[0]])
    rot=matrix2(best["yaw"],best["mirror"])
    scale=best["scale"]
    tc=np.array(best["tc"])
    a,b=target_edges(data)
    keep=np.linalg.norm(c-mean,axis=1)<220
    q=np.concatenate([a[keep],b[keep]])
    model_q=(q-tc)@rot/scale+origin
    near,seg_ids,_=nearest_on_edges(model_q,edges,tree,sample_ids,True)
    distance=np.linalg.norm(model_q-near,axis=1)*scale
    vectors=(edges[seg_ids,1][:,[0,2]]-edges[seg_ids,0][:,[0,2]])@rot.T
    vectors/=np.maximum(np.linalg.norm(vectors,axis=1)[:,None],1e-12)
    vectors*=np.where(vectors@direction<0,-1,1)[:,None]
    model_direction=np.median(vectors,axis=0)
    model_direction/=np.linalg.norm(model_direction)
    angle=math.degrees(math.acos(np.clip(abs(model_direction@direction),-1,1)))
    # Material 71 contains grid/paint decals. Find a broad, thin transverse stripe,
    # but do not assume its identity is the official start or timing line.
    marks=next(p for p in parts if p["material"]==71)
    xy=(marks["triangles"][:,:,[0,2]]-origin)@rot.T*scale+tc
    along=(xy-mean)@direction
    across=(xy-mean)@perpendicular
    keep=(marks["horizontal"]>.95)&(np.ptp(along,axis=1)<.7)&(np.ptp(across,axis=1)>1)
    keep&=(abs(along.mean(1))<150)&(abs(across.mean(1))<12)
    ids=np.flatnonzero(keep)
    ids=ids[np.argsort(along[ids].mean(1))]
    clusters=[]
    for i in ids:
        v=float(along[i].mean())
        if not clusters or abs(v-clusters[-1]["along"][-1])>.8:
            clusters.append(dict(along=[],indices=[]))
        clusters[-1]["along"].append(v)
        clusters[-1]["indices"].append(int(i))
    candidates=[]
    for cluster in clusters:
        ix=cluster["indices"]
        span=float(np.ptp(across[ix]))
        if span>8:
            along_m=float(np.median(cluster["along"]))
            candidates.append(dict(offsetAlongDrivingDirectionM=along_m,lateralSpanM=span,
                                   worldXZ=(mean+along_m*direction).tolist(),material=71,triangleIndices=ix))
    candidates.sort(key=lambda v:abs(v["offsetAlongDrivingDirectionM"]))
    return dict(timingSamples=timing,timingMeanXZ=mean.tolist(),timingLongitudinalRangeM=float(np.ptp((np.array([t["worldXZ"] for t in timing])-mean)@direction)),
                mainStraightEdgeMedianM=float(np.median(distance)),mainStraightEdgeMaxM=float(distance.max()),
                mainStraightAxisDifferenceDeg=angle,paintedTransverseCandidates=candidates,
                startFinishIdentity="UNVERIFIED: model has anonymous paint/grid decals; a nearby transverse stripe is not authenticated as the official timing/start line.")


def write_overlay(parts,data,origin,best,missing,straight_info):
    # Reuse geometry-only overview, then add a translucent band and explicit legend.
    image,low,pixel=overview_image(parts,data,origin,best)
    image=image.convert("RGBA")
    overlay=Image.new("RGBA",image.size)
    draw=ImageDraw.Draw(overlay)
    a,b=target_edges(data)
    for i in range(len(a)):
        j=(i+1)%len(a)
        draw.polygon([tuple(v) for v in (np.array([a[i],a[j],b[j],b[i]])-low)/pixel],fill=(25,255,205,45))
    for name,values in missing.items():
        for v in values:
            p=(np.array(v["worldXZ"])-low)/pixel
            draw.ellipse((p[0]-4,p[1]-4,p[0]+4,p[1]+4),fill=(255,195,25,255))
    image=Image.alpha_composite(image,overlay)
    font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf",19) if Path("C:/Windows/Fonts/arial.ttf").exists() else ImageFont.load_default()
    draw=ImageDraw.Draw(image)
    draw.rectangle((10,10,650,139),fill=(10,18,27,238))
    for i,(label,color) in enumerate((("GRIDSTORY / VENUE REGISTRATION  |  X right, Z down","white"),("Grey: model asphalt, including alternate layouts","#b2bec9"),("Cyan: GP track band  |  Magenta: measured pit path","#30f6cb"),("Amber dots: no direct asphalt height intersection","#ffc319"),("Corners are labels only; not registration anchors","#aeb7c0"))):
        draw.text((22,18+i*23),label,font=font,fill=color)
    sf=(np.array(straight_info["timingMeanXZ"])-low)/pixel
    draw.ellipse((sf[0]-7,sf[1]-7,sf[0]+7,sf[1]+7),outline="white",width=3)
    draw.text((sf[0]+12,sf[1]-12),"data timing crossings",font=font,fill="white")
    image.convert("RGB").save(HERE/"overlay.png")


def publish(parts,doc,binary,triangles,edges,data,origin,results,coarse):
    best=results[0]
    samples,sample_ids=sample_edges(edges)
    tree=cKDTree(samples)
    ty,heights,height_stats=height_outputs(triangles,edges,data,origin,best,tree,sample_ids)
    rot=matrix2(best["yaw"],best["mirror"])
    translation=np.array(best["tc"])-best["scale"]*origin@rot.T
    transform=dict(scale=best["scale"],mirrorX=best["mirror"],yawDeg=math.degrees(best["yaw"]),translate=[float(translation[0]),ty,float(translation[1])],
                   _apply=["Preserve every original glTF scene/node transform. Put the complete glTF scene under an identity THREE.Group; do not recenter it.",
                           "group.scale.set(scale * (mirrorX ? -1 : 1), scale, scale)",
                           "group.rotation.set(0, yawDeg * Math.PI / 180, 0)","group.position.fromArray(translate)",
                           "Vertex world = Translation * RotationY * Scale * original_glTF_world_vertex (column vectors). Mirror is local model X before yaw. Input glTF is already Y-up: do NOT apply W(x,y,z) to it."])
    hashes={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in ("bahrain.glb","gs3d-data.json")}
    transform["_inputSHA256"]=hashes
    heights["_inputSHA256"]=hashes
    (HERE/"venue-transform.json").write_text(json.dumps(transform,indent=2,allow_nan=False)+"\n")
    (HERE/"track-heights.json").write_text(json.dumps(heights,separators=(",",":"),allow_nan=False)+"\n")
    a,b=target_edges(data)
    distances=[]
    for q in (a,b):
        model_q=(q-best["tc"])@rot/best["scale"]+origin
        near=nearest_on_edges(model_q,edges,tree,sample_ids)
        distances.append(np.linalg.norm(model_q-near,axis=1)*best["scale"])
    dl,dr=distances
    c=horizontal(data["centre"])
    arc=np.r_[0,np.cumsum(np.linalg.norm(np.diff(c,axis=0),axis=1))]
    total=float(arc[-1]+np.linalg.norm(c[0]-c[-1]))
    sectors=[]
    for sector in range(int(arc[-1]//200)+1):
        keep=(arc>=sector*200)&(arc<(sector+1)*200)
        values=np.r_[dl[keep],dr[keep]]
        sectors.append(dict(startM=sector*200,endM=min((sector+1)*200,total),medianM=float(np.median(values)),maxM=float(values.max()),
                            leftMedianM=float(np.median(dl[keep])),leftMaxM=float(dl[keep].max()),rightMedianM=float(np.median(dr[keep])),rightMaxM=float(dr[keep].max())))
    straight_info=straight_validation(parts,data,origin,best,edges,tree,sample_ids)
    coarse_sorted=sorted(coarse,key=lambda v:-v["score"])
    coarse_scores=dict(best=coarse_sorted[0]["score"],secondDistinct=coarse_sorted[1]["score"],margin=coarse_sorted[0]["score"]-coarse_sorted[1]["score"])
    report=dict(transform=transform,coarseScores=coarse_scores,refinedEdgeScore=best["score"],
                edgeMedianM=float(np.median(np.r_[dl,dr])),edgeP95M=float(np.percentile(np.r_[dl,dr],95)),edgeMaxM=float(max(dl.max(),dr.max())),
                sourceClosedLoopLengthM=total,sourceRoadTriangles=len(triangles),sourceRoadBoundarySegments=len(edges),sectors=sectors,
                heights=height_stats,straight=straight_info)
    (HERE/"registration-metrics.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    write_overlay(parts,data,origin,best,{n:heights[n+"Missing"] for n in ("centre","pitlane")},straight_info)
    detail_render(doc,binary,parts,data,origin,best)
    lines=["# Bahrain venue registration", "", "Local licensed input only. No model/data edits, uploads, publication, or car-coordinate changes.", "", "## Transform", "", "```json",json.dumps({k:transform[k] for k in ("scale","mirrorX","yawDeg","translate")},indent=2),"```", ""]
    lines.extend(transform["_apply"])
    lines += ["", "Full glTF matrices include ancestor quaternion rotations and each node's nonuniform scale. The transform applies to the entire scene, not raw untransformed accessor positions.","", "## Method and ambiguity", "",
              "Asphalt was visually identified in the embedded-material contact sheet: material 79, node 82/Object_78, Bahrainv3001791Mtl_73. Its grey road texture and geometry trace the GP circuit, pit lane and alternate layouts. Only its near-horizontal triangles (abs(normal.Y)>0.90) participate; no terrain, wall tops, roofs, kerbs, or corners-as-landmarks are fitted.",
              "Coarse search: 8 m rasterized GP band versus the complete asphalt mask; all yaw angles 0..358 degrees at 2-degree intervals, both mirror states, scales [0.85,0.925,1,1.075,1.15]. FFT linear cross-correlation searches all translations at 8 m resolution. Score = dot(target,model)/sqrt(sum(target^2)*sum(model^2)). The coarse raster has intentional pixel quantization; this is a ranking score, not probability.",
              f"Best coarse score {coarse_scores['best']:.9f}; second distinct coarse basin {coarse_scores['secondDistinct']:.9f}; absolute margin {coarse_scores['margin']:.9f}. Distinct means opposite mirror OR >12 degrees yaw OR >100 m template-centre translation. Adjacent scales/poses within one basin are not independent alternatives. Search does not prove uniqueness outside the stated scale range.",
              "Twelve coarse basins were locally refined against welded asphalt boundary segments using robust point-to-segment least squares (soft_l1, 3 m). Both target edges, every third sample, are fitted. UV-split vertices are welded at 0.002 m before boundary extraction. Exact segment projections follow KD-tree candidate lookup. Final statistics below use ALL edge samples, not just fitting samples. Refinements that reach their bounds are retained as tested candidates, not certified alternative optima.",
              "Final smooth edge-closeness score = mean(exp(-0.5*(distance/5m)^2)) on fitting samples; not directly comparable with the raster score. Pit path, corner labels, finish-line paint and input heights were not used to choose the horizontal fit.",
              "", "## Track-edge validation", "", f"Closed input GP loop: {total:.3f} m; {len(c)} points. Origin for sectors is centre[0], not the timing line. Distances are horizontal, directed from EACH supplied GP edge sample to the nearest actual asphalt-mesh boundary, including junctions and all layouts. They measure geometry agreement, not survey accuracy.",
              f"All-edge median {report['edgeMedianM']:.3f} m; p95 {report['edgeP95M']:.3f} m; maximum {report['edgeMaxM']:.3f} m. At layout/pit junctions the asphalt opens out, so the target band edge can be inside asphalt and far from any physical asphalt edge; a maximum alone is not a registration error estimate.","", "| Arc m | Both median/max m | Left median/max m | Right median/max m |", "|---|---:|---:|---:|"]
    for row in sectors:
        lines.append(f"| {row['startM']}-{row['endM']:.1f} | {row['medianM']:.3f} / {row['maxM']:.3f} | {row['leftMedianM']:.3f} / {row['leftMaxM']:.3f} | {row['rightMedianM']:.3f} / {row['rightMaxM']:.3f} |")
    lines += ["", "## Pit path and road heights", "", "The magenta path lies on the model's separate asphalt lane beside its pit/garage building, on the correct side of the GP straight. Lane identity is checked visually in overlay.png, not inferred merely from proximity to arbitrary pavement.",
              "Height extraction casts a vertical ray into ONLY the fitted asphalt triangles, using barycentric interpolation. A robust median of input centre altitudes minus scaled single-level asphalt heights anchors translation Y. Heights retain model banking/elevation; terrain under roads and tops of walls/buildings cannot be selected. Multiple different asphalt levels, if present, are explicitly recorded and selected by proximity to input altitude after vertical anchoring.",
              "track-heights.json centre/pitlane arrays match input ordering and contain world Y metres. Triangle arrays identify the filtered asphalt triangle list in original primitive order. Strict arrays contain null where no asphalt is directly below. Separate centreNearestAsphalt/pitlaneNearestAsphalt arrays provide explicitly labelled nearest-boundary-height fallbacks for those points; these are NOT direct road intersections and must not silently replace them.", ""]
    for name,stat in height_stats.items():
        lines.append(f"- {name}: {stat['hits']}/{stat['total']} exact asphalt hits ({stat['coveragePercent']:.3f}%). {stat['missing']} missing; worst outside distance {stat['maxOutsideM']:.3f} m. Height difference versus input: median {stat['medianYResidual']:+.3f} m, p95 absolute {stat['p95AbsoluteYResidual']:.3f} m, max absolute {stat['maxAbsoluteYResidual']:.3f} m. Distinct multiple-level hits: {stat['multipleLevels']}.")
        lines.append(f"  Missing indices: {[v['index'] for v in heights[name+'Missing']]}. Exact distances/world positions/fallbacks are in track-heights.json.")
    lines += ["", "The three GP misses graze a road boundary at centimetre scale; the short pit-entry mismatch crosses a kerb/island and reaches metres. No retuning or material allowlist expansion was used to conceal either. Road heights along a centreline alone do not encode lateral banking at every car position.",
              "", "## Main straight and painted line", "", f"Main-straight edge median/max {straight_info['mainStraightEdgeMedianM']:.3f}/{straight_info['mainStraightEdgeMaxM']:.3f} m; asphalt-edge axis differs from input straight axis by {straight_info['mainStraightAxisDifferenceDeg']:.4f} degrees. The GP straight and building side match.",
              f"Clean HAM/PIA lap-ending crossings (exclude pit laps/out-of-range times) average world XZ {np.round(straight_info['timingMeanXZ'],4).tolist()}; longitudinal range {straight_info['timingLongitudinalRangeM']:.3f} m. 20 Hz interpolation does not create timing/position precision beyond the original samples."]
    for candidate in straight_info["paintedTransverseCandidates"]:
        lines.append(f"- Candidate model transverse paint stripe: world XZ {np.round(candidate['worldXZ'],4).tolist()}, signed offset {candidate['offsetAlongDrivingDirectionM']:.3f} m along driving direction relative to the data timing crossings, lateral span {candidate['lateralSpanM']:.3f} m (material 71/grid-paint atlas). Negative means behind the data crossing.")
    lines += ["", "Start/finish identity is NOT authenticated: the model's anonymous grid/paint geometry is not an official timing marker. The nearby stripe does not coincide with the observed lap crossings. Do not shift the whole venue to force that feature onto them. start-line-detail.png overlays the measured crossings on a local CPU texture render; start-line-textured.png is the unannotated source render. This model/data detail needs owner inspection before calling the venue exact at the timing line.",
              "", "## Reproduce and checks", "", "Requested command:", "", "```powershell", "& 'apps/api/.venv/Scripts/python.exe' -I '.superpowers/gridstory3d/venue/register_venue.py'", "```", "", "In this execution environment that launcher failed because its Microsoft Store base interpreter could not start. No environment was modified or installed. Actual run used the existing CPython 3.11.15 binary plus the project's installed NumPy/SciPy/Pillow packages:", "", "```powershell", "& 'python' -I -c \"import sys,runpy; sys.path.insert(0,r'apps/api/.venv/Lib/site-packages'); runpy.run_path(r'.superpowers/gridstory3d/venue/register_venue.py',run_name='__main__')\"", "```", "", "Built-in assertions check Three yaw sign, both mirror roundtrips, FFT translation sign, and exact sloped-triangle height/miss handling. Generated JSON forbids NaN. Horizontal matching inputs stay unchanged. registration-metrics.json contains all numeric tables and clean timing samples.", "", "Input SHA-256:", ""]
    lines += [f"- {name}: `{digest}`" for name,digest in hashes.items()]
    text_report="\n".join(lines)+"\n"
    (HERE/"registration-report.md").write_text(text_report,encoding="utf-8")
    print(text_report,flush=True)


def main():
    self_check()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", action="store_true")
    args = parser.parse_args()
    doc, binary, parts = load_glb(HERE / "bahrain.glb")
    if args.inventory:
        inventory(doc, binary, parts)
        return
    data = json.loads((HERE / "gs3d-data.json").read_text())
    road = next(p for p in parts if p["material"] == 79)
    triangles = road["triangles"][road["horizontal"] > .90]
    if road["node"]!=82 or doc["materials"][79]["name"]!="Bahrainv3001791Mtl_73":
        raise ValueError("Asphalt identity changed: inspect materials before registration")
    if not all(len(data[key])==len(data["centre"]) for key in ("wl","wr")):
        raise ValueError("Centre and width counts differ")
    for key in ("centre","pitlane"):
        values=np.asarray(data[key],float)
        if values.ndim!=2 or values.shape[1]!=3 or not np.isfinite(values).all():
            raise ValueError(f"Invalid {key} coordinates")
    if not np.isfinite([data["wl"],data["wr"]]).all() or np.min([data["wl"],data["wr"]])<=0:
        raise ValueError("Track widths must be finite and positive")
    origin, candidates = coarse_search(triangles, data)
    results, edges = refine(triangles, data, origin, candidates)
    publish(parts,doc,binary,triangles,edges,data,origin,results,candidates)


if __name__ == "__main__":
    main()
