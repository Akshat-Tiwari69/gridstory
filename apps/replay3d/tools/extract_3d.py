"""High-rate, smoothed, non-overlapping HAM/PIA paths + track model for the 3D pit-window scene.

Raw FastF1 position data is ~4 Hz and noisy (±1 m). We fit a smoothing spline through each car's
path in space, drive it with integrated car speed (anchored to the position samples so it can't
drift), resample at 20 Hz, then push the two cars apart sideways wherever their footprints overlap.
"""
import json
import sys

import fastf1
import numpy as np
from scipy.interpolate import PchipInterpolator, make_smoothing_spline
from scipy.ndimage import gaussian_filter1d, maximum_filter1d
from scipy.spatial import cKDTree

CACHE, OUT = sys.argv[1], sys.argv[2]
HZ, CAR_LEN, CAR_W, GAP = 20, 5.7, 2.0, 0.45   # footprint (m) and the minimum side-by-side clearance
fastf1.Cache.enable_cache(CACHE)
fastf1.set_log_level("ERROR")
ses = fastf1.get_session(2024, "Bahrain", "R")
ses.load(laps=True, telemetry=True, weather=False, messages=False)
laps = ses.laps
T0 = laps[laps.LapNumber == 1].LapStartTime.min().total_seconds()   # t = 0 at the start
sec = lambda td: td.total_seconds() - T0
NUM = {d: ses.get_driver(d)["DriverNumber"] for d in ("HAM", "PIA")}


# ---------- track centre and width from every clean lap of every car ----------
def periodic_smooth(pts, sigma):
    return np.stack([gaussian_filter1d(pts[:, i], sigma, mode="wrap") for i in range(pts.shape[1])], 1)


def resample_closed(pts, step):
    seg = np.r_[np.linalg.norm(np.diff(pts[:, :2], axis=0), axis=1), np.linalg.norm(pts[0, :2] - pts[-1, :2])]
    s = np.r_[0, np.cumsum(seg)]
    loop = np.vstack([pts, pts[:1]])
    n = int(s[-1] // step)
    q = np.linspace(0, s[-1], n, endpoint=False)
    return np.stack([np.interp(q, s, loop[:, i]) for i in range(pts.shape[1])], 1)


clean = laps.pick_wo_box().pick_quicklaps(1.07).pick_track_status("1")
ref_lap = laps.pick_drivers("HAM").pick_wo_box().pick_fastest()
ref = ref_lap.get_pos_data()[["X", "Y", "Z"]].to_numpy() / 10
ref = resample_closed(periodic_smooth(resample_closed(ref, 2.0), 3), 1.0)
tan = np.gradient(ref[:, :2], axis=0); tan /= np.linalg.norm(tan, axis=1, keepdims=True)
nrm = np.stack([-tan[:, 1], tan[:, 0]], 1)   # left of travel
tree = cKDTree(ref[:, :2])
lat_by_bin = [[] for _ in ref]
z_by_bin = [[] for _ in ref]
for _, lap in clean.iterlaps():
    try:
        p = lap.get_pos_data()[["X", "Y", "Z"]].to_numpy() / 10
    except Exception:
        continue
    _, idx = tree.query(p[:, :2])
    lat = np.einsum("ij,ij->i", p[:, :2] - ref[idx, :2], nrm[idx])
    for i, l, z in zip(idx, lat, p[:, 2]):
        lat_by_bin[i].append(l); z_by_bin[i].append(z)
n = len(ref)
lo, hi, zc, med = np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)
for i in range(n):   # pool ±4 m of bins so every bin has data
    pool = [v for j in range(i - 4, i + 5) for v in lat_by_bin[j % n]]
    zp = [v for j in range(i - 4, i + 5) for v in z_by_bin[j % n]]
    lo[i], hi[i] = np.percentile(pool, [2, 98]) if pool else (-4, 4)
    med[i] = np.median(pool) if pool else 0
    zc[i] = np.median(zp) if zp else ref[i, 2]
mid = gaussian_filter1d((lo + hi) / 2, 12, mode="wrap")
half = np.full(n, 7.5)   # ponytail: Bahrain is ~15 m wide; pos data is too coarse to measure width per corner
centre = np.c_[ref[:, :2] + nrm * mid[:, None], gaussian_filter1d(zc, 15, mode="wrap")]
ctree = cKDTree(centre[:, :2])
print(f"centre {len(centre)} pts, half-width {half.min():.1f}-{half.max():.1f} m, z {centre[:,2].min():.1f}..{centre[:,2].max():.1f} m")


# ---------- one car: smooth path, speed-driven progress, 20 Hz ----------
def car_track(drv, ta, tb):
    pos = ses.pos_data[NUM[drv]]
    car = ses.car_data[NUM[drv]]
    pt = pos.SessionTime.dt.total_seconds().to_numpy() - T0
    pm = (pt > ta - 5) & (pt < tb + 5)
    pt, P = pt[pm], pos[["X", "Y"]].to_numpy()[pm] / 10
    ct = car.SessionTime.dt.total_seconds().to_numpy() - T0
    cm = (ct > ta - 5) & (ct < tb + 5)
    ct, v, brk = ct[cm], car.Speed.to_numpy()[cm] / 3.6, car.Brake.to_numpy()[cm].astype(float)
    gear, thr = car.nGear.to_numpy()[cm], car.Throttle.to_numpy()[cm]
    rpm, drs = car.RPM.to_numpy()[cm].astype(float), car.DRS.to_numpy()[cm]
    s_v_full = np.r_[0, np.cumsum(np.diff(ct) * (v[1:] + v[:-1]) / 2)]

    # drop samples that moved further than the car's own speed allows (time-shifted glitches at pit entry)
    sv = np.interp(pt, ct, s_v_full)
    good, last, run = [0], 0, 0
    for j in range(1, len(pt)):
        if np.linalg.norm(P[j] - P[last]) <= 1.25 * (sv[j] - sv[last]) + 3 or run > 15:
            good.append(j); last, run = j, 0
        else:
            run += 1
    print(f"  {drv}: dropped {len(pt) - len(good)} of {len(pt)} position samples as inconsistent with speed")
    pt, P = pt[good], P[good]

    # arc length along the raw samples, ignoring sub-0.6 m jitter (stationary noise)
    step = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s_raw = np.r_[0, np.cumsum(np.where(step < 0.6, 0, step))]
    keep = np.r_[True, np.diff(s_raw) > 0]
    sx = make_smoothing_spline(s_raw[keep], P[keep, 0], lam=40)
    sy = make_smoothing_spline(s_raw[keep], P[keep, 1], lam=40)

    # progress = integrated speed, corrected to the position samples every ~2 s
    s_v = np.r_[0, np.cumsum(np.diff(ct) * (v[1:] + v[:-1]) / 2)]
    s_v_at_p = np.interp(pt, ct, s_v)
    anchors = np.arange(0, len(pt), 8)
    corr = PchipInterpolator(pt[anchors], gaussian_filter1d(s_raw - s_v_at_p, 4)[anchors], extrapolate=True)
    t = np.arange(ta, tb, 1 / HZ)
    s = np.maximum.accumulate(np.interp(t, ct, s_v) + corr(t))
    x, y = sx(s), sy(s)
    h = np.unwrap(np.arctan2(sy.derivative()(s), sx.derivative()(s)))   # path tangent: defined even at walking pace
    h = gaussian_filter1d(h, 3)
    spd = np.interp(t, ct, v * 3.6)
    ds = np.gradient(s) + 1e-6
    steer = np.clip(np.arctan(3.6 * np.gradient(h) / ds), -0.35, 0.35) * (spd > 3)
    return {"t": t, "x": x, "y": y, "h": h, "v": spd, "b": np.interp(t, ct, brk), "g": gear[np.clip(np.searchsorted(ct, t), 0, len(ct) - 1)], "thr": np.interp(t, ct, thr), "rpm": np.interp(t, ct, rpm), "drs": (drs[np.clip(np.searchsorted(ct, t), 0, len(ct) - 1)] >= 10).astype(int), "glat": gaussian_filter1d((spd / 3.6) ** 2 * np.gradient(h) / ds / 9.81, 6), "glon": gaussian_filter1d(np.gradient(spd / 3.6) * HZ / 9.81, 6), "steer": gaussian_filter1d(steer, 3)}


lap = lambda d, n: laps.pick_drivers(d).pick_laps(n).iloc[0]
TA, TB = sec(lap("HAM", 32).LapStartTime), sec(lap("PIA", 36).Time) + 1
C = {d: car_track(d, TA, TB) for d in ("HAM", "PIA")}


# ---------- pit lane: one road for both cars ----------
# Position samples in the pit lane are the worst in the feed (time-shifted at entry, ~4 Hz at walking pace), and
# Piastri's raw path cut across the sand. The pit lane is a fixed road, so both cars drive one lane centreline
# (Hamilton's clean pass, heavily smoothed), progressing by their own measured speed, pulling into their own box
# where the data shows them stationary, and blending back onto their own track path at entry and exit.
PITS = {"HAM": (sec(lap("HAM", 33).PitInTime), sec(lap("HAM", 34).PitOutTime)),
        "PIA": (sec(lap("PIA", 34).PitInTime), sec(lap("PIA", 35).PitOutTime))}
_h = C["HAM"]; _m = (_h["t"] > PITS["HAM"][0] - 3) & (_h["t"] < PITS["HAM"][1] + 3)
_l = np.c_[_h["x"][_m], _h["y"][_m]]
_l = _l[np.r_[True, np.linalg.norm(np.diff(_l, axis=0), axis=1) > 0.3]]
_sl = np.r_[0, np.cumsum(np.linalg.norm(np.diff(_l, axis=0), axis=1))]
LS = np.arange(0, _sl[-1], 1.0)
LANE = np.stack([gaussian_filter1d(np.interp(LS, _sl, _l[:, i]), 14, mode="nearest") for i in range(2)], 1)
LZ, PM_BOXES = None, None
if len(sys.argv) > 4:   # the venue model's real pit lane: entry ~60 m before divergence to ~60 m after the exit corridor
    _pm = json.load(open(sys.argv[4]))
    _ml = np.array(_pm["lane"]); _ms = np.r_[0, np.cumsum(np.linalg.norm(np.diff(_ml[:, :2], axis=0), axis=1))]
    LS = np.arange(0, _ms[-1], 1.0)
    # the extracted centreline wiggles where the asphalt fans out at entry/exit; a road bends smoothly
    LANE = gaussian_filter1d(np.stack([np.interp(LS, _ms, _ml[:, i]) for i in range(2)], 1), 14, axis=0, mode="nearest")
    LZ = np.interp(LS, _ms, _ml[:, 2])
    PM_BOXES = np.array([[b["x"], b["y"]] for b in _pm["boxes"]])
    print(f"  pit lane from the venue model: {LS[-1]:.0f} m, {len(PM_BOXES)} painted boxes")
_lt = np.gradient(LANE, axis=0); _lt /= np.linalg.norm(_lt, axis=1, keepdims=True)
LN = np.stack([-_lt[:, 1], _lt[:, 0]], 1)          # left normal
LTREE = cKDTree(LANE)
lane_at = lambda q: np.stack([np.interp(q, LS, LANE[:, i]) for i in range(2)], 1)
norm_at = lambda q: np.stack([np.interp(q, LS, LN[:, i]) for i in range(2)], 1)


def snap_to_lane(c, k):
    t0, t1 = PITS[k]
    def nearest(tlo, thi, pt):
        idx = np.flatnonzero((c["t"] >= tlo) & (c["t"] <= thi))
        return idx[np.argmin(np.hypot(c["x"][idx] - pt[0], c["y"][idx] - pt[1]))]
    ia, ib = nearest(t0 - 12, t0 + 4, LANE[0]), nearest(t1 - 4, t1 + 12, LANE[-1])
    still = np.flatnonzero((c["t"] > t0) & (c["t"] < t1) & (c["v"] < 0.5))
    is0, is1 = still[0], still[-1]
    box = np.array([c["x"][still].mean(), c["y"][still].mean()])
    if PM_BOXES is not None:
        _, bi = LTREE.query(box); s_meas = LS[bi]
        cand = [(abs(LS[LTREE.query(b)[1]] - s_meas), b) for b in PM_BOXES]
        gap, box = min(cand, key=lambda q: q[0])
        print(f"  {k}: measured stop at {s_meas:.0f} m along the lane -> painted box {gap:.1f} m away")
    _, bi = LTREE.query(box); s_box = LS[bi]; lat_box = float((box - LANE[bi]) @ LN[bi])
    before = max(LTREE.query(np.c_[c["x"][ia:ib], c["y"][ia:ib]])[0])
    sv = np.r_[0, np.cumsum(c["v"][1:] / 3.6 / HZ)]                      # distance from measured speed
    i = np.arange(ia, ib + 1); s_ = np.empty(len(i), float)
    a1, a3 = i <= is0, i >= is1
    s_[a1] = s_box * (sv[i[a1]] - sv[ia]) / (sv[is0] - sv[ia])
    s_[~a1 & ~a3] = s_box
    s_[a3] = s_box + (LS[-1] - s_box) * (sv[i[a3]] - sv[is1]) / (sv[ib] - sv[is1])
    d = np.abs(s_ - s_box)                                               # ease into the box from the fast lane
    w = np.where(d < 6, 1.0, np.where(d > 40, 0.0, 0.5 + 0.5 * np.cos(np.pi * (d - 6) / 34)))
    xy = lane_at(s_) + norm_at(s_) * (lat_box * w)[:, None]
    # remove the step at both ends: carry the car's own offset from the lane, fading out along a smooth S-curve
    # (a linear fade has a corner at each end, which is a heading snap at racing speed)
    da = np.array([c["x"][ia], c["y"][ia]]) - LANE[0]; db = np.array([c["x"][ib], c["y"][ib]]) - LANE[-1]
    smooth = lambda u: 1 - (3 * u ** 2 - 2 * u ** 3)
    fa = smooth(np.clip(s_ / 90, 0, 1)); fb = smooth(np.clip((LS[-1] - s_) / 90, 0, 1))
    xy += fa[:, None] * da + fb[:, None] * db
    c["x"][ia:ib + 1], c["y"][ia:ib + 1] = xy[:, 0], xy[:, 1]
    # heading and steer from the new path (held while parked)
    lo, hi = max(ia - 20, 0), min(ib + 20, len(c["x"]) - 1)
    hx, hy = np.gradient(c["x"][lo:hi + 1]), np.gradient(c["y"][lo:hi + 1])
    hh = np.arctan2(hy, hx); moving = c["v"][lo:hi + 1] > 2
    hh = np.unwrap(np.interp(np.arange(len(hh)), np.flatnonzero(moving), np.unwrap(hh[moving])))
    hh += np.round((c["h"][lo] - hh[0]) / (2 * np.pi)) * 2 * np.pi          # stay on the same unwrapped branch
    c["h"][lo:hi + 1] = gaussian_filter1d(hh, 1)   # light: at 250 km/h heavier smoothing makes the nose lag the path
    ds = np.hypot(np.gradient(c["x"]), np.gradient(c["y"])) + 1e-6
    c["steer"] = gaussian_filter1d(np.clip(np.arctan(3.6 * np.gradient(c["h"]) / ds), -0.35, 0.35) * (c["v"] > 3), 3)
    after = max(LTREE.query(np.c_[c["x"][ia:ib], c["y"][ia:ib]])[0])
    print(f"  {k}: pit lane {c['t'][ia]:.1f}-{c['t'][ib]:.1f} s, box at {s_box:.0f} m along the lane ({lat_box:+.1f} m), "
          f"furthest from the lane {before:.1f} m -> {after:.1f} m, end offsets {np.linalg.norm(da):.1f} / {np.linalg.norm(db):.1f} m")


for _k in ("HAM", "PIA"):
    snap_to_lane(C[_k], _k)

# ---------- keep the two footprints apart ----------
a, b = C["HAM"], C["PIA"]
fx, fy = np.cos(a["h"]), np.sin(a["h"])
total = np.zeros_like(fx)
lat0 = -(b["x"] - a["x"]) * fy + (b["y"] - a["y"]) * fx
lon0 = (b["x"] - a["x"]) * fx + (b["y"] - a["y"]) * fy
# Raw positions are noisy enough (±2 m) that the sideways order flips frame to frame while the cars are
# alongside. Pick one side per wheel-to-wheel episode (median over it) so nobody swaps sides mid-corner.
side = np.ones_like(lat0)
close = maximum_filter1d((np.abs(lon0) < CAR_LEN + 10).astype(int), 41) > 0
for run in np.split(np.flatnonzero(close), np.flatnonzero(np.diff(np.flatnonzero(close)) > 1) + 1):
    if len(run):
        side[run] = np.sign(np.median(lat0[run])) or 1
        print(f"  alongside {TA + run[0] / HZ:.1f}-{TA + run[-1] / HZ:.1f} s: Piastri on Hamilton's {'left' if side[run[0]] > 0 else 'right'}")
for _ in range(6):   # smoothing the push softens its peak, so repeat until nothing overlaps
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    lon, lat = dx * fx + dy * fy, -dx * fy + dy * fx
    need = np.where(np.abs(lon) < CAR_LEN, np.maximum(0, CAR_W + GAP - side * lat), 0)
    if not need.any():
        break
    push = gaussian_filter1d(maximum_filter1d(need, 41), 8) / 2 * 1.15
    total += push
    for car, sgn in ((a, -1), (b, 1)):
        car["x"] = car["x"] + sgn * side * push * -fy
        car["y"] = car["y"] + sgn * side * push * fx
over = (np.abs(lon) < CAR_LEN) & (side * lat < CAR_W)
print(f"overlap frames after fix: {over.sum()} | push max {total.max():.2f} m over {np.count_nonzero(total > .01) / HZ:.1f} s | closest centres {np.min(np.hypot(dx, dy)):.1f} m")
assert over.sum() == 0, "cars still intersect"
# the push moved the cars sideways; turn their noses to match so they steer apart instead of crabbing
moved = maximum_filter1d((total > 0.005).astype(int), 61) > 0
for c in (a, b):
    hn = np.unwrap(np.arctan2(np.gradient(c["y"]), np.gradient(c["x"])))
    hn += np.round((c["h"] - hn) / (2 * np.pi)) * 2 * np.pi
    c["h"] = np.where(moved & (c["v"] > 20), gaussian_filter1d(hn, 2), c["h"])
for k, c in C.items():   # no car may slide sideways faster than a real one can
    vx, vy = np.gradient(c["x"]) * HZ, np.gradient(c["y"]) * HZ
    slide = np.abs(-vx * np.sin(c["h"]) + vy * np.cos(c["h"]))[c["v"] > 20]
    _t = c["t"][c["v"] > 20]; print(f"  {k}: max sideways speed {slide.max():.1f} m/s at {_t[np.argmax(slide)]:.1f} s")
    assert slide.max() < 3, f"{k} slides sideways"

# car height from the track surface under it
for car in C.values():
    _, idx = ctree.query(np.c_[car["x"], car["y"]])
    car["z"] = gaussian_filter1d(centre[idx, 2], 6)


# ---------- live interval (s) from distance travelled along the lap ----------
LAPLEN = 2.0 * (len(centre[::2]))
def race_dist(car, d):
    _, idx = ctree.query(np.c_[car["x"], car["y"]])
    raw = np.unwrap(idx * (2 * np.pi / len(centre))) * len(centre) / (2 * np.pi)   # bins, continuous across the line
    raw = raw * (LAPLEN / len(centre))
    t32 = sec(lap(d, 32).Time)
    return gaussian_filter1d(raw - np.interp(t32, car["t"], raw) + 32 * LAPLEN, 10)
RD = {d: race_dist(C[d], d) for d in C}
for d in RD:
    assert np.all(np.diff(RD[d]) > -0.5), f"{d} race distance goes backwards"
tt = C["HAM"]["t"]
# + = Hamilton behind Piastri by this many seconds
interval = tt - np.interp(RD["HAM"], np.maximum.accumulate(RD["PIA"]), tt)
ahead = RD["HAM"] > RD["PIA"]
interval[ahead] = -(tt[ahead] - np.interp(RD["PIA"][ahead], np.maximum.accumulate(RD["HAM"]), tt))
for n in ("32", "33", "34", "35"):
    i = int(round((sec(lap("HAM", int(n)).Time) - TA) * HZ))
    print(f"  interval at HAM lap {n} end: {interval[i]:+.1f} s")

# ---------- events, all from the timing data ----------
def pit(d, n):
    inl, out = lap(d, n), lap(d, n + 1)
    t0, t1 = sec(inl.PitInTime), sec(out.PitOutTime)
    c = C[d]; m = (c["t"] > t0) & (c["t"] < t1) & (c["v"] < 0.5)
    return {"t0": t0, "t1": t1, "still0": float(c["t"][m].min()), "still1": float(c["t"][m].max()), "lane": t1 - t0}


ev = {"pit": {"HAM": pit("HAM", 33), "PIA": pit("PIA", 34)},
      "lapEnd": {d: {str(n): sec(lap(d, n).Time) for n in range(31, 37)} for d in ("HAM", "PIA")},
      "pos": {d: {str(n): int(lap(d, n).Position) for n in range(31, 37)} for d in ("HAM", "PIA")}}
ev["gap"] = {str(n): ev["lapEnd"]["HAM"][str(n)] - ev["lapEnd"]["PIA"][str(n)] for n in range(31, 37)}
print("pit", {d: {k: round(v, 2) for k, v in p.items()} for d, p in ev["pit"].items()})
print("pos", ev["pos"], "gap", {k: round(v, 1) for k, v in ev["gap"].items()})

# pit lane surface: Hamilton's own smoothed path through the pit lane, plus 60 m either side
pl = np.c_[LANE, LZ if LZ is not None else gaussian_filter1d(centre[ctree.query(LANE)[1], 2], 6)]   # the same lane the cars drive

# terrain: 10 m heightfield that never rises above the track surface near it
from scipy.ndimage import gaussian_filter
mn, mx = centre[:, :2].min(0) - 450, centre[:, :2].max(0) + 450
gx, gy = np.arange(mn[0], mx[0], 10.0), np.arange(mn[1], mx[1], 10.0)
G = np.stack(np.meshgrid(gx, gy), -1).reshape(-1, 2)
dist, idx = ctree.query(G)
zt = centre[idx, 2]
hf = gaussian_filter(zt.reshape(len(gy), len(gx)), 4, mode="nearest").ravel()
hf = np.where(dist < 45, np.minimum(hf, zt - 0.6), hf)
terrain = {"x0": float(gx[0]), "y0": float(gy[0]), "step": 10.0, "nx": len(gx), "ny": len(gy), "h": np.round(hf, 1).tolist()}

# running order snapshots (every car, end of each lap) and corners
sys.path.insert(0, ".")
from app.services import tracinginsights as ti
order = {str(n): [[r.Driver, int(r.Position)] for r in laps.pick_laps(n).dropna(subset=["Position"]).sort_values("Position").itertuples()] for n in range(31, 37)}
colors = {r.Abbreviation: "#" + str(r.TeamColor) for r in ses.results.itertuples()}
corners = [[c.number, round(c.x / 10, 1), round(c.y / 10, 1)] for c in ti.circuit(2024, "Bahrain Grand Prix", "Race").corners]

R = lambda arr, k=2: np.round(np.asarray(arr, float), k).tolist()
# the drawn road: TUM centreline + widths, registered onto this frame by register_tum.py (cars are never moved)
_reg = json.load(open(sys.argv[3]))
_tp = np.array(_reg["points"])                          # x, y, w_right, w_left
TUMC = np.c_[_tp[:, :2], gaussian_filter1d(centre[ctree.query(_tp[:, :2])[1], 2], 6, mode="wrap")]
TUMW, TUMRL = _tp[:, 2:4], np.array(_reg["rl"])
out = {"hz": HZ, "t0": TA,
       "centre": R(TUMC, 2), "wl": R(TUMW[:, 1], 2), "wr": R(TUMW[:, 0], 2), "rl": R(TUMRL, 2),
       "pitlane": R(pl[::2], 2),
       "cars": {d: {k: R(c[k], 3 if k in ("h", "steer") else 2) for k in ("x", "y", "z", "h", "v", "b", "steer", "g", "thr", "rpm", "drs", "glat", "glon")} for d, c in C.items()},
       "interval": R(interval, 2),
       "ev": ev, "terrain": terrain, "order": order, "colors": colors, "corners": corners}
json.dump(out, open(OUT, "w"), separators=(",", ":"))
print("wrote", OUT, f"{len(C['HAM']['x'])} frames/car")
