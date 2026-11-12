"""Extract a model-defined pit path and painted boxes; local assets only."""
# ruff: noqa: E402 -- Disable bytecode before imports to keep writes in venue/.
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import hashlib
import io
import json
from pathlib import Path
import runpy

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import interpolate
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
REG = runpy.run_path(str(HERE / "register_venue.py"))


def to_data(v, transform):
    rot = REG["matrix2"](np.deg2rad(transform["yawDeg"]), transform["mirrorX"])
    xz = v[..., [0, 2]] @ rot.T * transform["scale"] + np.array(transform["translate"])[[0, 2]]
    y = v[..., 1] * transform["scale"] + transform["translate"][1]
    return np.stack([xz[..., 0], -xz[..., 1], y], axis=-1)


def texture_for(doc, binary, material):
    tex = doc["materials"][material].get("pbrMetallicRoughness", {}).get("baseColorTexture")
    if tex is None:
        return None
    source = doc["textures"][tex["index"]]["source"]
    view = doc["bufferViews"][doc["images"][source]["bufferView"]]
    start = view.get("byteOffset", 0)
    return np.asarray(Image.open(io.BytesIO(binary[start:start + view["byteLength"]])).convert("RGBA"))


def intervals_at_y(edges, y):
    a, b = edges[:, 0, :2], edges[:, 1, :2]
    valid = ((a[:, 1] <= y) & (b[:, 1] > y)) | ((b[:, 1] <= y) & (a[:, 1] > y))
    x = np.sort(a[valid, 0] + (y-a[valid, 1])*(b[valid, 0]-a[valid, 0])/(b[valid, 1]-a[valid, 1]))
    if len(x) % 2:
        raise ValueError(f"Odd boundary crossings at y={y}")
    return x.reshape(-1, 2)


def components(triangles):
    vertices, inv = np.unique(np.rint(triangles.reshape(-1, 3)/.003).astype(np.int64), axis=0, return_inverse=True)
    ids = inv.reshape(-1, 3)
    edges = np.concatenate([ids[:, [0, 1]], ids[:, [1, 2]], ids[:, [2, 0]]])
    graph = coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(len(vertices), len(vertices))).tocsr()
    count, labels = connected_components(graph, directed=False)
    return [vertices[labels == i]*.003 for i in range(count)]


def painted_boxes(doc, binary, parts, transform):
    part = next(p for p in parts if p["material"] == 77)
    uv = part["uv"][part["indices"]].mean(1)
    texture = texture_for(doc, binary, 77)
    color = texture[(np.mod(uv[:, 1], 1)*texture.shape[0]).astype(int), (np.mod(uv[:, 0], 1)*texture.shape[1]).astype(int)].astype(float)
    yellow = (color[:, 0] > color[:, 2]*1.5) & (color[:, 1] > color[:, 2]*1.4) & (color[:, 0] > 80) & (color[:, 1] > 60)
    triangles = to_data(part["triangles"], transform)
    keep = yellow & (part["horizontal"] > .97) & (triangles[:, :, 2].mean(1) > -17) & (triangles[:, :, 2].mean(1) < -14)
    groups = components(triangles[keep])
    # Each stopping rectangle is the pair of ~5.36 m brackets 2.08 m apart.
    # The longer ~12.87 m garage-side stripe is a guide, not a car-box side.
    short = [g for g in groups if 4.5 < np.ptp(g[:, 1]) < 6.5 and np.ptp(g[:, 0]) < 1.5]
    short.sort(key=lambda g: g[:, 1].mean())
    rows = []
    for g in short:
        centre = (g.min(0)+g.max(0))/2
        if not rows or abs(centre[1]-rows[-1][0][1]) > 1.:
            rows.append([])
        rows[-1].append(centre)
    if not all(len(row) == 2 for row in rows):
        raise ValueError("Paint brackets did not form unique pairs")
    boxes = np.array([np.mean(row, axis=0) for row in rows])
    if len(boxes) != 15:
        raise ValueError("Expected 15 stopping rectangles in this model; inspect changed asset")
    return boxes, dict(yellowTriangles=int(keep.sum()), yellowComponents=len(groups), pairedBracketComponents=len(short), rows=len(rows))


def project(query, path):
    """Exact horizontal projection onto polyline segments; distances are metres."""
    query = np.atleast_2d(query)
    a, v = path[:-1, :2], np.diff(path[:, :2], axis=0)
    lengths = np.linalg.norm(v, axis=1)
    arc = np.r_[0., np.cumsum(lengths)]
    result = []
    for q in query[:, :2]:
        u = np.clip(np.sum((q-a)*v, axis=1)/np.maximum(lengths**2, 1e-20), 0, 1)
        near = a+u[:, None]*v
        i = int(np.argmin(np.sum((q-near)**2, axis=1)))
        point = path[i] + u[i]*(path[i+1]-path[i])
        result.append((arc[i]+u[i]*lengths[i], point, v[i]/lengths[i], i, u[i]))
    return result


def gp_point(s, gp):
    arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(gp[:, :2], axis=0), axis=1))]
    s = np.atleast_1d(s) % arc[-1]
    return np.stack([np.interp(s, arc, gp[:, i]) for i in range(gp.shape[1])], axis=-1)


def extract_corridor(edges):
    """Trace the narrow strip adjacent to the main straight from an interior seed.

    The visual seed and ROI identify this venue's pit lane, not other layouts.
    Stop when its separate asphalt cross-section joins the main-track section.
    """
    ys = np.arange(-125., 810.01, .5)
    rows = []
    for y in ys:
        intervals = intervals_at_y(edges, y)
        intervals = intervals[(intervals[:, 0] > -80) & (intervals[:, 1] < 35)]
        intervals = intervals[np.diff(intervals, axis=1)[:, 0] > 2]
        if len(intervals) == 2 and intervals[1, 0]-intervals[0, 1] < 15:
            rows.append(intervals[1])
        else:
            rows.append(None)
    seed = int(np.argmin(abs(ys-300)))
    if rows[seed] is None:
        raise ValueError("Pit-lane interior seed is not a separate road corridor")
    accepted = {seed: rows[seed]}
    for direction in (-1, 1):
        history = [seed]
        missed = 0
        for i in range(seed+direction, len(ys) if direction > 0 else -1, direction):
            previous = history[-1]
            prior = history[-min(10,len(history))]
            slope = (accepted[previous].mean()-accepted[prior].mean())/(ys[previous]-ys[prior]) if previous != prior else .038
            expected = accepted[previous].mean()+slope*(ys[i]-ys[previous])
            row = rows[i]
            if row is not None and abs(row.mean()-expected) < .55:
                accepted[i] = row
                history.append(i)
                missed = 0
            else:
                missed += 1
                if missed > 6:  # Bridge only thin transverse paint cuts, not islands.
                    break
    indices = sorted(accepted)
    values = np.array([accepted[i] for i in indices])
    y = ys[indices]
    midpoint = values.mean(1)
    # Remove centimetre-scale triangulation jitter, preserving corridor geometry.
    fit = interpolate.UnivariateSpline(y, midpoint, s=len(y)*.015**2)
    dense_y = np.arange(y[0], y[-1]+.01, .25)
    xy = np.c_[fit(dense_y), dense_y]
    return xy, dict(firstSeparateY=float(y[0]), lastSeparateY=float(y[-1]),
                    seedY=300.,minWidthM=float(np.diff(values, axis=1).min()),
                    medianWidthM=float(np.median(np.diff(values, axis=1))),
                    maxWidthM=float(np.diff(values, axis=1).max()),
                    midpointFitMaxDeviationM=float(np.max(abs(fit(y)-midpoint))))


def build_lane(corridor, data):
    gp = np.r_[np.array(data["centre"], float), np.array(data["centre"][:1], float)]
    joins = project(corridor[[0, -1]], gp)
    lead_s, tail_s = joins[0][0], joins[1][0]
    # Hold the GP line until the model's broad entry fan has opened. Steering
    # earlier would cut the triangular access-road kerb beside the straight.
    p0, p1 = gp_point(lead_s-30, gp)[0, :2], corridor[0]
    start_tangent = (gp_point(lead_s-29.9, gp)[0, :2]-gp_point(lead_s-30.1, gp)[0, :2])/.2
    first_tangent = np.array([np.polyfit(corridor[:40,1],corridor[:40,0],1)[0],1.])
    first_tangent /= np.linalg.norm(first_tangent)
    lead = gp_point(np.arange(lead_s-90,lead_s-30,.25),gp)[:,:2]
    turn = interpolate.CubicHermiteSpline([0., 30.], [p0, p1], [start_tangent, first_tangent])(np.arange(0., 30.01, .25))
    before = np.r_[lead,turn]
    p0, p1 = corridor[-1], gp_point(tail_s+60, gp)[0, :2]
    last_tangent = np.array([np.polyfit(corridor[-40:,1],corridor[-40:,0],1)[0],1.])
    last_tangent /= np.linalg.norm(last_tangent)
    end_tangent = (gp_point(tail_s+60.1, gp)[0, :2]-gp_point(tail_s+59.9, gp)[0, :2])/.2
    after = interpolate.CubicHermiteSpline([0., 60.], [p0, p1], [last_tangent, end_tangent])(np.arange(0., 60.01, .25))
    dense = np.r_[before[:-1], corridor, after[1:]]
    arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(dense, axis=0), axis=1))]
    s = np.r_[np.arange(0., arc[-1], 1.), arc[-1]]
    xy = np.c_[np.interp(s, arc, dense[:, 0]), np.interp(s, arc, dense[:, 1])]
    divergence_s = float(arc[len(lead)])
    separate_start_s = float(arc[len(before)-1])
    corridor_end_s = float(arc[len(before)+len(corridor)-2])
    return xy, s, dict(divergenceS=divergence_s, separateStartS=separate_start_s,corridorEndS=corridor_end_s,
                       divergenceIdx=int(np.argmin(abs(s-divergence_s))), corridorEndIdx=int(np.argmin(abs(s-corridor_end_s)))), gp


def strict_heights(xy, surface):
    heights = []
    for p in xy:
        h, _ = surface.hits(p)
        if not len(h):
            heights.append(np.nan)
        elif np.ptp(h) > .15:
            raise ValueError(f"Ambiguous road levels at {p.tolist()}: {h.tolist()}")
        else:
            heights.append(float(np.median(h)))
    return np.array(heights)


def painted_gap_heights(xy, heights, road_edges, parts, transform):
    """A paint cutout can replace asphalt triangles; never use its raised top."""
    missing = np.flatnonzero(~np.isfinite(heights))
    if not len(missing):
        return heights, []
    e = road_edges[:, :, [0, 2, 1]]
    samples, ids = REG["sample_edges"](e)
    near, seg, u = REG["nearest_on_edges"](xy[missing], e, cKDTree(samples), ids, True)
    distance = np.linalg.norm(near-xy[missing], axis=1)
    paint_surfaces = {}
    for material in (69, 103):
        p = next(p for p in parts if p["material"] == material)
        t = to_data(p["triangles"][p["horizontal"] > .90], transform)
        paint_surfaces[material] = REG["Surface"](t[:, :, [0, 2, 1]])
    bridged = []
    for j, i in enumerate(missing):
        hits = [mat for mat, surf in paint_surfaces.items() if len(surf.hits(xy[i])[0])]
        if distance[j] > .30 or (not hits and distance[j] > .05):
            continue
        z = road_edges[seg[j], 0, 2]+u[j]*(road_edges[seg[j], 1, 2]-road_edges[seg[j], 0, 2])
        heights[i] = z
        bridged.append(dict(index=int(i),paintMaterials=hits,nearestAsphaltDistanceM=float(distance[j]),
                            z=float(z),method="nearest asphalt edge height across <=0.30m classified paint cutout" if hits else "nearest asphalt edge height across <=0.05m unfilled CAD seam"))
    return heights, bridged


def transverse_markings(parts, transform, lane, lane_s):
    """Find broad paint crossings, without assigning timing/limiter semantics."""
    tree = cKDTree(lane[:, :2])
    candidates = []
    for part in parts:
        if part["material"] not in (69,71,96,103):
            continue
        ts = to_data(part["triangles"], transform)
        centre = ts.mean(1)
        distance, nearest = tree.query(centre[:, :2])
        keep = (part["horizontal"]>.95)&(distance<5)&(abs(centre[:,2]-lane[nearest,2])<.25)
        for i in np.flatnonzero(keep):
            j=int(np.clip(nearest[i],1,len(lane)-2))
            tangent=lane[j+1,:2]-lane[j-1,:2]
            tangent/=np.linalg.norm(tangent)
            normal=np.array([-tangent[1],tangent[0]])
            delta=ts[i,:,:2]-lane[j,:2]
            along=delta@tangent+lane_s[j]
            across=delta@normal
            if np.ptp(along)<1.5 and np.ptp(across)>1 and abs(across.mean())<3.5:
                candidates.append((float(along.mean()),float(across.min()),float(across.max()),part["material"]))
    candidates.sort()
    clusters=[]
    for row in candidates:
        if not clusters or row[0]-clusters[-1][-1][0]>1.5:
            clusters.append([])
        clusters[-1].append(row)
    result=[]
    for cluster in clusters:
        if max(v[2] for v in cluster)-min(v[1] for v in cluster)<4.5:
            continue
        s=float(np.median([v[0] for v in cluster]))
        xyz=np.array([np.interp(s,lane_s,lane[:,k]) for k in range(3)])
        result.append(dict(s=s,x=float(xyz[0]),y=float(xyz[1]),z=float(xyz[2]),
                           materials=sorted(set(v[3] for v in cluster)),
                           status="transverse floor marking candidate; limiter identity UNVERIFIED"))
    return result


def validate_lane(output, report, data, road_data, edges, parts, transform):
    lane=np.array(output["lane"])
    s=np.array(output["s"])
    spacing=np.linalg.norm(np.diff(lane[:,:2],axis=0),axis=1)
    if not np.isfinite(lane).all() or not np.all(np.diff(s)>0):
        raise ValueError("Nonfinite lane or nonmonotone arc lengths")
    if np.max(abs(spacing[:-1]-1))>.005:
        raise ValueError("Lane does not have 1m horizontal spacing")
    report["spacing"]=dict(maxDeviationFrom1M=float(np.max(abs(spacing[:-1]-1))),lastIntervalM=float(spacing[-1]),maxHeightStepM=float(np.max(abs(np.diff(lane[:,2])))))
    # Test a 2m-wide car footprint as well as the centre; classified thin paint
    # cuts may bridge the asphalt mesh, but islands and walls may not.
    tangent=np.gradient(lane[:,:2],axis=0)
    tangent/=np.linalg.norm(tangent,axis=1)[:,None]
    normal=np.c_[-tangent[:,1],tangent[:,0]]
    surface=REG["Surface"](road_data[:,:,[0,2,1]])
    footprint=[]
    for side in (-1,1):
        xy=lane[:,:2]+side*normal
        height=strict_heights(xy,surface)
        height,bridges=painted_gap_heights(xy,height,edges,parts,transform)
        missing=np.flatnonzero(~np.isfinite(height)).tolist()
        footprint.append(dict(side=side,unsupportedIndices=missing,paintBridges=bridges))
    report["footprint"]=footprint
    if any(v["unsupportedIndices"] for v in footprint):
        (HERE/"pitlane-footprint-debug.json").write_text(json.dumps(footprint,indent=2))
        for row in footprint:
            ids=row["unsupportedIndices"]
            print("unsupported rail",row["side"],ids,(lane[ids,:2]+row["side"]*normal[ids]).tolist(),flush=True)
        raise ValueError("The 2m-wide car footprint leaves asphalt; inspect footprint metrics")
    a,b=REG["target_edges"](data)
    a,b=a*[1,-1],b*[1,-1]
    seg=np.r_[np.stack([a,np.roll(a,-1,axis=0)],axis=1),np.stack([b,np.roll(b,-1,axis=0)],axis=1)]
    e=np.zeros((len(seg),2,3))
    e[:,:,0]=seg[:,:,0]
    e[:,:,2]=seg[:,:,1]
    sample,ids=REG["sample_edges"](e)
    band_tree=cKDTree(sample)
    main=(lane[:,1]>=175)&(lane[:,1]<=435)
    q=lane[main,:2]
    near=REG["nearest_on_edges"](q,e,band_tree,ids)
    distance=np.linalg.norm(q-near,axis=1)
    model_edge=[]
    for y in np.arange(50,541,1):
        intervals=intervals_at_y(edges,y)
        intervals=intervals[(intervals[:,0]>-80)&(intervals[:,1]<35)]
        model_edge.append([intervals[0,1],y,0.])
    projections=project(q,np.array(model_edge))
    model_distance=np.array([np.linalg.norm(point-near[:2]) for point,(_,near,_,_,_) in zip(q,projections)])
    report["mainStraightGPEdgeDistance"]=dict(yRange=[175,435],sourceBandMedianM=float(np.median(distance)),sourceBandMinM=float(distance.min()),sourceBandMaxM=float(distance.max()),
                                               modelEdgeMedianM=float(np.median(model_distance)),modelEdgeMinM=float(model_distance.min()),modelEdgeMaxM=float(model_distance.max()))
    markers=transverse_markings(parts,transform,lane,s)
    output["speedLimitLines"]["paintCandidates"]=markers
    report["paintCrossingCandidates"]=markers
    entry=[m for m in markers if 90<m["y"]<100 and 71 in m["materials"]]
    exit_marks=[m for m in markers if 490<m["y"]<500 and 103 in m["materials"]]
    if len(entry)==1 and len(exit_marks)==1:
        pair=dict(first=entry[0],second=exit_marks[0],distanceM=exit_marks[0]["s"]-entry[0]["s"],
                  status="UNVERIFIED candidate interval only; first stripe may be timing/grid paint, not a limiter gate")
        output["speedLimitLines"]["candidateInterval"]=pair
        report["candidateMarkedInterval"]=pair
    report["workingSide"]=output["workingSide"]
    report["workingOffset"]=output["workingOffset"]
    report["leaveIdx"]=output["leaveIdx"]
    report["rejoinIdx"]=output["rejoinIdx"]
    report["leaveXYZ"]=output["lane"][output["leaveIdx"]]
    report["rejoinXYZ"]=output["lane"][output["rejoinIdx"]]
    assert 0 <= output["entryDivergenceIdx"] < output["leaveIdx"] < output["gpBandRejoinIdx"] < output["rejoinIdx"] < len(lane)
    assert np.all(np.diff([b["s"] for b in output["boxes"]])>0)
    return report


def self_check():
    p=np.array([[0.,0.,1.],[0.,10.,3.],[10.,10.,5.]])
    rows=project(np.array([[2.,4.],[4.,12.]]),p)
    np.testing.assert_allclose([r[0] for r in rows],[4.,14.])
    np.testing.assert_allclose(rows[0][1],[0.,4.,1.8])
    t=dict(scale=1.,mirrorX=False,yawDeg=90.,translate=[5.,6.,7.])
    np.testing.assert_allclose(to_data(np.array([[2.,3.,4.]]),t),[[9.,-5.,9.]],atol=1e-12)


def overlay(parts, doc, binary, transform, data, output):
    image,low,pixel=render_floor(doc,binary,parts,transform)
    image=image.convert("RGBA")
    ink=Image.new("RGBA",image.size)
    draw=ImageDraw.Draw(ink)
    a,b=REG["target_edges"](data)
    def pts(xy):
        return [tuple(v) for v in (np.asarray(xy)*[1,-1]-low)/pixel]
    a,b=a*[1,-1],b*[1,-1]
    for i in range(len(a)):
        j=(i+1)%len(a)
        draw.polygon(pts([a[i],a[j],b[j],b[i]]),fill=(71,132,255,43))
    for edge in (a,b):
        draw.line(pts(np.r_[edge,edge[:1]]),fill=(100,158,255,230),width=2)
    draw.line(pts(np.array(data["pitlane"])[:,:2]),fill=(255,65,159,255),width=4)
    draw.line(pts(np.array(output["lane"])[:,:2]),fill=(20,255,178,255),width=4)
    font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf",16) if Path("C:/Windows/Fonts/arial.ttf").exists() else ImageFont.load_default()
    for i,box in enumerate(output["boxes"]):
        x,y=pts([[box["x"],box["y"]]])[0]
        draw.ellipse((x-5,y-5,x+5,y+5),fill=(255,211,35,255),outline="black",width=1)
        draw.text((x+8,y-10),f"{i}: s {box['s']:.1f}",fill="white",font=font)
    for driver,row in output["stationaryProjections"].items():
        x,y=pts([row["projectionXYZ"][:2]])[0]
        draw.ellipse((x-7,y-7,x+7,y+7),fill="white",outline="black",width=2)
        draw.text((10,y-10),f"{driver} s {row['s']:.1f}",fill="white",font=font)
    for key,label in (("entryDivergenceIdx","ENTRY FAN"),("leaveIdx","LEAVE GP BAND"),("gpBandRejoinIdx","ENTER GP BAND"),("rejoinIdx","EXIT CORRIDOR END")):
        x,y=pts([output["lane"][output[key]][:2]])[0]
        draw.rectangle((x-5,y-5,x+5,y+5),fill="white",outline="black",width=1)
        draw.text((10,y+8),label,fill="white",font=font)
    for label,mark in zip(("A?","B?"),(output["speedLimitLines"].get("candidateInterval",{}).get("first"),output["speedLimitLines"].get("candidateInterval",{}).get("second"))):
        if mark is None:
            continue
        x,y=pts([[mark["x"],mark["y"]]])[0]
        draw.ellipse((x-6,y-6,x+6,y+6),outline="#ffa12a",width=3)
        draw.text((x+10,y-10),label,font=font,fill="#ffa12a")
    for i in (0,len(output["lane"])-1):
        x,y=pts([output["lane"][i][:2]])[0]
        draw.ellipse((x-6,y-6,x+6,y+6),outline="white",width=2)
    image=Image.alpha_composite(image,ink)
    draw=ImageDraw.Draw(image)
    draw.rectangle((0,0,image.width,150),fill=(8,16,24,240))
    for i,(text,color) in enumerate((("MODEL PIT LANE / data x right, y up","white"),("Green: new lane  |  Pink: old lane","#20ffb2"),("Blue: GP band  |  Yellow: boxes (0-based)","#8cb5ff"),("White dots: stationary projections, not team boxes","white"),("Exit corridor ends after earlier GP-band entry","white"),("Paint crossings are not verified limiter gates","#ffd323"))):
        draw.text((8,8+i*23),text,font=font,fill=color)
    image.convert("RGB").save(HERE/"pitlane-overlay.png")
    best=dict(yaw=np.deg2rad(transform["yawDeg"]),mirror=transform["mirrorX"],scale=transform["scale"],tc=np.array(transform["translate"])[[0,2]])
    overview,origin,px=REG["overview_image"](parts,data,np.zeros(2),best)
    draw=ImageDraw.Draw(overview)
    def overview_pts(xy):
        return [tuple(v) for v in (np.asarray(xy)*[1,-1]-origin)/px]
    draw.line(overview_pts(np.array(output["lane"])[:,:2]),fill="#20ffb2",width=4)
    draw.line(overview_pts(np.array(data["pitlane"])[:,:2]),fill="#ff419f",width=2)
    for box in output["boxes"]:
        x,y=overview_pts([[box["x"],box["y"]]])[0]
        draw.ellipse((x-3,y-3,x+3,y+3),fill="#ffd323")
    overview.save(HERE/"pitlane-overview.png")


def save_report(output, report):
    d=report["drivers"]
    edge=report["mainStraightGPEdgeDistance"]
    lines=["# Model-defined Bahrain pit lane","", "## Coordinates and construction","",
           "All outputs are local. The source GLB, transform, registration outputs and gs3d-data.json are unchanged. Model vertices pass through their complete glTF hierarchy and the existing venue Group transform, then inverse W: data = (worldX, -worldZ, worldY). The venue transform is NOT inverted a second time.",
           "", "Fast lane: material79/node82 asphalt. Horizontal cross-sections of actual welded road boundaries are traced from a visual interior seed y=300 in the pit corridor beside the main straight (ROI x=-80..35). Midpoints of the narrow strip define its centre. Thin transverse paint cuts are bridged while tracking, but road islands are not. A smoothing spline removes centimetre-scale tessellation noise; full path/2m footprint checks reject unsupported surfaces.",
           "", "Entry: ~60m of registered GP centreline before turning through the model's broad entry fan. The turn waits until the triangular access-road island ends, then follows the pit corridor. Exit: preserve the separated corridor through the earlier GP-band crossing, then blend to the registered GP centreline over ~60m after the divider ends. GP centreline is used only for the leads, on the racing surface; old pit coordinates are used only for comparison and stationary projection.",
           "", "## Length and marker definitions", "",
           f"- Total lane length including leads: {report['lengthM']:.3f}m; {len(output['lane'])} points. Horizontal 1m arc spacing; final interval {report['spacing']['lastIntervalM']:.3f}m. Largest other spacing deviation from 1m: {report['spacing']['maxDeviationFrom1M']:.6f}m.",
           f"- Lead before entry fan: {report['entryLeadM']:.3f}m; lead after separated exit corridor: {report['exitLeadM']:.3f}m.",
           f"- Entry fan to exit-corridor end: {report['entryDivergenceToExitEndM']:.3f}m; narrow/separated strip alone: {report['separatedCorridorLengthM']:.3f}m.",
           f"- GP-band leave to first GP-band return: {report['gpBandLeaveToRejoinM']:.3f}m. This earlier return is NOT the end of the separated painted exit corridor.",
           f"- entryDivergenceIdx={output['entryDivergenceIdx']}, leaveIdx={output['leaveIdx']}, gpBandRejoinIdx={output['gpBandRejoinIdx']}, rejoinIdx={output['rejoinIdx']}. Indices are zero-based, each marker rounded to the closest 1m lane sample.",
           f"- leave position: {np.round(report['leaveXYZ'],4).tolist()}; exit-corridor rejoin: {np.round(report['rejoinXYZ'],4).tolist()}.",
           "", "The model does NOT give a 400-450m full geometric entry-to-exit route under these definitions. That estimate may describe a restricted timing/speed-limit interval, not the full approach and long exit corridor. No length was forced to match it. Do not stretch the recorded ~24s PitInTime/PitOutTime interval over this entire route; those feed gates and the model's geometric endpoints are different.",
           "", "## Heights and footprint", "",
           "Lane z is a strict vertical barycentric hit on model asphalt79, in data Z-up metres. Working-box z comes from asphalt99/node102 underneath the paint, NOT the paint's top. Walls/roofs/terrain are not accepted.",
           f"There are {len(report['heightBridges'])} lane samples where a classified thin road-paint cutout replaces asphalt triangles. Their height is explicitly bridged from the nearest asphalt boundary, only within 0.30m. They are recorded in pitlane-model.json heightBridges; no raised kerb/paint height is substituted. This does not bridge the old path's 2.386m island error.",
           f"All centre samples and both +/-1m footprint rails have asphalt/explicit thin-paint or <=0.05m CAD-seam support. Maximum consecutive model height change: {report['spacing']['maxHeightStepM']:.4f}m. Footprint exceptions are recorded in pitlane-metrics.json, including a ~0.029m unfilled seam near the exit. This is geometric road support, not a suspension/vehicle-dynamics simulation.",
           "", "## Working side and painted stopping boxes", "",
           f"workingSide={output['workingSide']} (garages on the RIGHT in driving direction). workingOffset={output['workingOffset']:.3f}m, median signed-normal distance to the painted car-rectangle centres. Individual offsets span {report['workingOffsetMinM']:.3f}-{report['workingOffsetMaxM']:.3f}m; use boxes coordinates for exact stops rather than adding one constant offset everywhere.",
           "Material77 yellow paint yields 45 connected components: 15 groups of one long garage guide plus two short car brackets. Each stopping-box centre is the midpoint between the two ~5.36m brackets, not the mean of all three components. The separate ~12.87m garage guide is excluded. Thus 15 painted stopping boxes, not 45/30. Their allocations to actual 2024 teams are unknown.",
           "", "| Box (0-based) | s m | x m | y m | asphalt z m |", "|---:|---:|---:|---:|---:|"]
    for i,b in enumerate(output["boxes"]):
        lines.append(f"| {i} | {b['s']:.3f} | {b['x']:.3f} | {b['y']:.3f} | {b['z']:.4f} |")
    lines += ["", "## Main-straight separation and markings", "",
              f"Over the box-lined main straight (data y=175..435m), fast-lane centre to nearest supplied GP-band edge: min/median/max {edge['sourceBandMinM']:.3f}/{edge['sourceBandMedianM']:.3f}/{edge['sourceBandMaxM']:.3f}m. To the model's actual GP asphalt edge: {edge['modelEdgeMinM']:.3f}/{edge['modelEdgeMedianM']:.3f}/{edge['modelEdgeMaxM']:.3f}m.",
              f"Fast-lane asphalt width: median {report['corridor']['medianWidthM']:.3f}m across the traced strip, including entry/exit widening. Geometry-fit maximum midpoint deviation {report['corridor']['midpointFitMaxDeviationM']:.3f}m.",
              "", "Speed-limit gate identities are UNVERIFIED: entry and exit remain null. Anonymous transverse floor markings do not establish limiter gates, timing lines, or current 2024 rules. Geometric corridor endpoints are not speed-limit markers. Detected broad transverse marking candidates:"]
    for mark in report["paintCrossingCandidates"]:
        lines.append(f"- s={mark['s']:.3f}m, data XYZ=({mark['x']:.3f},{mark['y']:.3f},{mark['z']:.3f}), materials {mark['materials']}; semantics unverified.")
    if not report["paintCrossingCandidates"]:
        lines.append("- No broad marking could be identified reliably by the geometric classifier.")
    if "candidateMarkedInterval" in report:
        pair=report["candidateMarkedInterval"]
        lines += ["",f"A pair of visible markings (A?/B? in the overlay) bounds {pair['distanceM']:.3f}m: data y={pair['first']['y']:.3f} to {pair['second']['y']:.3f}. This is compatible with the rough400-450m expectation, but is NOT an authenticated speed-limit interval. The first stripe may be grid/timing paint; neither boundary is promoted to a limiter gate."]
    lines += ["", "## Stationary projections", "", "Frames are resampled 20Hz output arrays satisfying v<0.5km/h inside each supplied pit interval; resampling does not add source timing/position precision. Mean horizontal stationary positions are projected onto lane segments; nearest box is selected by absolute longitudinal s difference. This does not assign a team garage.", "", "| Driver | Frames | Projected s m | Nearest box | Box s m | Driver s - box s m | Lateral projection m |", "|---|---:|---:|---:|---:|---:|---:|"]
    for driver,row in d.items():
        lines.append(f"| {driver} | {row['stationaryFrames']} | {row['s']:.3f} | {row['nearestBoxIdx']} | {row['nearestBoxS']:.3f} | {row['longitudinalOffsetFromBoxM']:+.3f} | {row['lateralDistanceM']:.3f} |")
    lines += ["", f"HAM precedes PIA in driving direction. Projected stationary separation: {report['stationarySeparationM']:.3f}m. Nearest painted-box separation: {report['nearestBoxSeparationM']:.3f}m. ORDER agrees; the old ~56m SPACING does not. The input feed cannot justify moving either driver to a supposedly authentic 2024 team stall without additional evidence.",
              "", "## Files and reproducibility", "", "pitlane-model.json includes the 1m lane, s array, join indices, working side/offset, painted-box positions, explicit height bridges, unverified marking candidates and stationary projections. pitlane-overlay.png is the detailed textured comparison (new green, old pink, GP blue, boxes yellow); pitlane-overview.png shows the whole GP context. All measurements are also in pitlane-metrics.json.",
              "", "Run with the requested project interpreter:", "", "```powershell", "& 'apps/api/.venv/Scripts/python.exe' -I '.superpowers/gridstory3d/venue/build_pitlane.py'", "```", "", "That launcher's Microsoft Store base cannot start in this environment. Actual execution used the existing standalone CPython3.11 and project NumPy/SciPy/Pillow, without installs or environment edits:", "", "```powershell", "& 'python' -I -B -c \"import sys,runpy; sys.path.insert(0,r'apps/api/.venv/Lib/site-packages'); runpy.run_path(r'.superpowers/gridstory3d/venue/build_pitlane.py',run_name='__main__')\"", "```", "", "Assertions check transform conventions, exact segment projection, finite heights, 1m sampling, ordered boxes and a supported 2m-wide footprint. No files outside this venue directory are written. Source hashes are recorded in pitlane-model.json."]
    text="\n".join(lines)+"\n"
    (HERE/"pitlane-report.md").write_text(text,encoding="utf-8")
    print(text,flush=True)


def assemble(doc, binary, parts, transform, data):
    road = next(p for p in parts if p["material"] == 79)
    road_triangles = road["triangles"][road["horizontal"] > .90]
    edges = to_data(REG["road_edges"](road_triangles), transform)
    corridor, corridor_stats = extract_corridor(edges)
    xy, s, joins, gp = build_lane(corridor, data)
    road_data = to_data(road_triangles, transform)
    road_surface = REG["Surface"](road_data[:, :, [0, 2, 1]])
    heights = strict_heights(xy, road_surface)
    heights, bridges = painted_gap_heights(xy, heights, edges, parts, transform)
    for bridge in bridges:
        i=bridge["index"]
        bridge.update(s=float(s[i]),x=float(xy[i,0]),y=float(xy[i,1]))
    missing = np.flatnonzero(~np.isfinite(heights))
    print("lane preliminary", len(xy), "length", s[-1], "joins", joins, "corridor", corridor_stats, "missing", missing.tolist(), flush=True)
    if len(missing):
        np.savez(HERE/"pitlane-debug.npz", xy=xy, s=s, missing=missing, edges=edges)
        raise ValueError("Lane leaves asphalt: inspect pitlane-debug.npz before publishing")
    lane = np.c_[xy, heights]
    boxes, paint_stats = painted_boxes(doc, binary, parts, transform)
    apron = next(p for p in parts if p["material"] == 99)
    apron_data = to_data(apron["triangles"][apron["horizontal"] > .90], transform)
    apron_surface = REG["Surface"](apron_data[:, :, [0, 2, 1]])
    box_heights = strict_heights(boxes[:, :2], apron_surface)
    if not np.isfinite(box_heights).all():
        raise ValueError("A painted stopping rectangle has no working-apron asphalt below")
    boxes[:, 2] = box_heights
    projected_boxes = project(boxes, lane)
    record_boxes, offsets = [], []
    for box, projection in zip(boxes, projected_boxes):
        box_s, near, tangent, _, _ = projection
        left = np.array([-tangent[1], tangent[0]])
        lateral = float((box[:2]-near[:2])@left)
        offsets.append(lateral)
        record_boxes.append(dict(s=float(box_s), x=float(box[0]), y=float(box[1]), z=float(box[2])))
    record_boxes.sort(key=lambda box: box["s"])
    working_side = int(np.sign(np.median(offsets)))
    if not all(np.sign(v) == working_side for v in offsets):
        raise ValueError("Stopping boxes disagree about working side")
    working_offset = float(np.median(abs(np.array(offsets))))
    gp_proj = project(lane, gp)
    gp_arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(gp[:, :2], axis=0), axis=1))]
    wl = np.r_[data["wl"], data["wl"][:1]]
    wr = np.r_[data["wr"], data["wr"][:1]]
    signed = np.array([(point[:2]-near[:2])@np.array([-tan[1], tan[0]]) for point, (_, near, tan, _, _) in zip(lane, gp_proj)])
    gps = np.array([p[0] for p in gp_proj])
    outside = (signed > np.interp(gps, gp_arc, wl)) | (signed < -np.interp(gps, gp_arc, wr))
    outside_idx = np.flatnonzero(outside)
    if not len(outside_idx):
        raise ValueError("The extracted lane never leaves the GP band")
    leave_idx, geometric_rejoin = int(outside_idx[0]), int(outside_idx[-1]+1)
    report = dict(corridor=corridor_stats, paint=paint_stats, heightBridges=bridges, lengthM=float(s[-1]),
                  entryLeadM=joins["divergenceS"], exitLeadM=float(s[-1]-joins["corridorEndS"]),
                  entryDivergenceToExitEndM=joins["corridorEndS"]-joins["divergenceS"],
                  separatedCorridorLengthM=joins["corridorEndS"]-joins["separateStartS"],
                  gpBandLeaveIdx=leave_idx, gpBandRejoinIdx=geometric_rejoin,
                  gpBandLeaveToRejoinM=float(s[geometric_rejoin]-s[leave_idx]),
                  workingOffsetMinM=float(min(abs(np.array(offsets)))),workingOffsetMaxM=float(max(abs(np.array(offsets)))))
    output = dict(coordinates="data metres: x,y horizontal; z up. Model -> registered Three world -> (worldX,-worldZ,worldY).",
                  lane=lane.tolist(), s=s.tolist(), leaveIdx=leave_idx, rejoinIdx=joins["corridorEndIdx"],
                  entryDivergenceIdx=joins["divergenceIdx"], gpBandRejoinIdx=geometric_rejoin,
                  joinDefinitions="leaveIdx is first departure from supplied GP band. rejoinIdx is end of the model's separated exit corridor; GP band is entered earlier at gpBandRejoinIdx. Leads span ~60m before entry divergence and ~60m after separated exit corridor ends. These are geometric markers, NOT authenticated limiter gates.",
                  workingSide=working_side, workingOffset=working_offset, boxes=record_boxes,
                  heightBridges=bridges,
                  speedLimitLines=dict(entry=None,exit=None,status="Not authenticated in anonymous model markings; corridor tips are not limiter gates."))
    drivers = {}
    for driver in ("HAM", "PIA"):
        car = data["cars"][driver]
        times = data["t0"]+np.arange(len(car["v"]))/data["hz"]
        pit = data["ev"]["pit"][driver]
        mask = (times >= pit["t0"]) & (times <= pit["t1"]) & (np.array(car["v"]) < .5)
        point = np.array([np.mean(np.array(car[key])[mask]) for key in ("x", "y", "z")])
        driver_s, near, _, _, _ = project(point[None], lane)[0]
        nearest = int(np.argmin(abs(np.array([b["s"] for b in record_boxes])-driver_s)))
        drivers[driver] = dict(stationaryFrames=int(mask.sum()),stationaryMean=point.tolist(),s=float(driver_s),
                               projectionXYZ=near.tolist(),lateralDistanceM=float(np.linalg.norm(point[:2]-near[:2])),
                               nearestBoxIdx=nearest,nearestBoxS=record_boxes[nearest]["s"],
                               longitudinalOffsetFromBoxM=float(driver_s-record_boxes[nearest]["s"]))
    report["drivers"] = drivers
    report["stationarySeparationM"] = float(drivers["PIA"]["s"]-drivers["HAM"]["s"])
    report["nearestBoxSeparationM"] = float(drivers["PIA"]["nearestBoxS"]-drivers["HAM"]["nearestBoxS"])
    output["stationaryProjections"] = drivers
    return output, report, road_data, edges


def render_floor(doc, binary, parts, transform):
    """Orthographic floor render, including the model's original paint textures."""
    low = np.array([-75., -900.])  # World X,Z = data x,-y.
    pixel = .30
    size = np.ceil((np.array([55., 230.]) - low) / pixel).astype(int)
    canvas = np.full((size[1], size[0], 3), [29, 33, 38], np.uint8)
    depth = np.full((size[1], size[0]), -np.inf)
    for part in parts:
        if part["uv"] is None:
            continue
        texture = texture_for(doc, binary, part["material"])
        if texture is None:
            continue
        mat = doc["materials"][part["material"]]
        factor = np.array(mat.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1., 1., 1., 1.]))
        if mat.get("alphaMode") == "BLEND" and factor[3] < .01:
            continue
        ts = to_data(part["triangles"], transform)
        xy = (ts[:, :, :2] * [1, -1] - low) / pixel
        keep = (part["horizontal"] > .90) & (ts[:, :, 2].mean(1) > -18) & (ts[:, :, 2].mean(1) < -12)
        keep &= (xy[:, :, 0].min(1) < size[0]) & (xy[:, :, 0].max(1) >= 0) & (xy[:, :, 1].min(1) < size[1]) & (xy[:, :, 1].max(1) >= 0)
        for i in np.flatnonzero(keep):
            t = xy[i]
            lo = np.maximum(np.floor(t.min(0)).astype(int), 0)
            hi = np.minimum(np.ceil(t.max(0)).astype(int) + 1, size)
            if np.any(hi <= lo):
                continue
            xx, yy = np.meshgrid(np.arange(lo[0], hi[0]) + .5, np.arange(lo[1], hi[1]) + .5)
            a, b = t[1] - t[0], t[2] - t[0]
            det = a[0]*b[1] - a[1]*b[0]
            if abs(det) < 1e-8:
                continue
            dx, dy = xx - t[0, 0], yy - t[0, 1]
            u = (dx*b[1] - dy*b[0])/det
            v = (a[0]*dy - a[1]*dx)/det
            h = ts[i, 0, 2] + u*(ts[i, 1, 2]-ts[i, 0, 2]) + v*(ts[i, 2, 2]-ts[i, 0, 2])
            uv = part["uv"][part["indices"][i]]
            uv = uv[0] + u[:, :, None]*(uv[1]-uv[0]) + v[:, :, None]*(uv[2]-uv[0])
            rgba = texture[(np.mod(uv[:, :, 1], 1)*texture.shape[0]).astype(int).clip(0, texture.shape[0]-1), (np.mod(uv[:, :, 0], 1)*texture.shape[1]).astype(int).clip(0, texture.shape[1]-1)].astype(float)/255*factor
            alpha = rgba[:, :, 3] if mat.get("alphaMode") in ("BLEND", "MASK") else np.ones_like(u)
            if mat.get("alphaMode") == "MASK":
                alpha = (alpha >= mat.get("alphaCutoff", .5)).astype(float)
            region = np.s_[lo[1]:hi[1], lo[0]:hi[0]]
            mask = (u >= 0) & (v >= 0) & (u+v <= 1) & (h >= depth[region]-.008) & (alpha > .05)
            blend = alpha[:, :, None]*rgba[:, :, :3]*255 + (1-alpha[:, :, None])*canvas[region]
            canvas[region][mask] = blend[mask].clip(0, 255).astype(np.uint8)
            depth[region][mask] = h[mask]
    image = Image.fromarray(canvas)
    image.save(HERE/"pitlane-textured.png")
    return image, low, pixel


def inspect(doc, binary, parts, transform):
    render_floor(doc, binary, parts, transform)
    for material in (69, 71, 77, 96):
        image = texture_for(doc, binary, material)
        Image.fromarray(image).save(HERE/f"pit-material-{material}.png")
        p = next(p for p in parts if p["material"] == material)
        data = to_data(p["triangles"], transform)
        keep = (p["horizontal"] > .95) & (data[:, :, 2].mean(1) > -17) & (data[:, :, 2].mean(1) < -14)
        print("mark", material, "flat near road", keep.sum(), "bbox", np.round([data[keep].reshape(-1, 3).min(0), data[keep].reshape(-1, 3).max(0)], 3).tolist())
    road = next(p for p in parts if p["material"] == 79)
    edges = to_data(REG["road_edges"](road["triangles"][road["horizontal"] > .90]), transform)
    for y in list(range(-180, 31, 10)) + list(range(530, 811, 10)):
        values = intervals_at_y(edges, y)
        values = values[(values[:, 0] > -80) & (values[:, 1] < 35)]
        print("cross", y, np.round(values, 3).tolist())
    print("boxes", painted_boxes(doc, binary, parts, transform))


def main():
    self_check()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", action="store_true")
    args = parser.parse_args()
    transform = json.loads((HERE/"venue-transform.json").read_text())
    doc, binary, parts = REG["load_glb"](HERE/"bahrain.glb")
    if args.inspect:
        inspect(doc, binary, parts, transform)
        return
    data = json.loads((HERE/"gs3d-data.json").read_text())
    output, report, road, edges = assemble(doc, binary, parts, transform, data)
    validate_lane(output,report,data,road,edges,parts,transform)
    output["inputSHA256"]={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in ("bahrain.glb","gs3d-data.json","venue-transform.json")}
    overlay(parts,doc,binary,transform,data,output)
    (HERE/"pitlane-model.json").write_text(json.dumps(output, indent=2, allow_nan=False)+"\n")
    (HERE/"pitlane-metrics.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    save_report(output,report)
    for name in ("pitlane-debug.npz","pitlane-footprint-debug.json"):
        (HERE/name).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
