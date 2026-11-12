"""Register the TUM Sakhir centreline + widths onto the FastF1 frame, anchored by corner shape, and validate.

Not blind ICP against the cars' average path (a racing line is systematically offset from the centreline):
1. curvature-profile cross-correlation gives point correspondence + direction (independent of position);
2. rigid Kabsch fit on those correspondences (scale held at 1; a free-scale fit is reported as a check);
3. validation: residuals per corner, official corner points, and every clean-lap car position vs the TUM edges.
"""
import json
import sys

import fastf1
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.spatial import cKDTree

TUM_CSV, CACHE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, ".")
from app.services import tracinginsights as ti  # noqa: E402

STEP = 2.0


def resample(P, step, closed=True):
    Q = np.vstack([P, P[:1]]) if closed else P
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(Q, axis=0), axis=1))]
    q = np.arange(0, s[-1], step)
    return np.stack([np.interp(q, s, Q[:, i]) for i in range(P.shape[1])], 1), s[-1]


def curvature(P):
    t = np.gradient(P, axis=0); a = np.gradient(t, axis=0)
    k = (t[:, 0] * a[:, 1] - t[:, 1] * a[:, 0]) / (np.linalg.norm(t, axis=1) ** 3 + 1e-9)
    return gaussian_filter1d(k, 8, mode="wrap")


tum = np.loadtxt(TUM_CSV, delimiter=",", comments="#")
T_raw, W_raw = tum[:, :2], tum[:, 2:4]                        # w_right, w_left (TUM's direction)
T, LT = resample(np.c_[T_raw, W_raw], STEP)
fastf1.Cache.enable_cache(CACHE); fastf1.set_log_level("ERROR")
ses = fastf1.get_session(2024, "Bahrain", "R"); ses.load(laps=True, telemetry=True, weather=False, messages=False)
ref = ses.laps.pick_drivers("HAM").pick_wo_box().pick_fastest().get_pos_data()[["X", "Y"]].to_numpy() / 10
F, LF = resample(gaussian_filter1d(resample(ref, 2.0)[0], 3, axis=0, mode="wrap"), STEP)
print(f"lap length: TUM {LT:.0f} m, FastF1 fastest-lap path {LF:.0f} m  (ratio {LF / LT:.4f})")

# 1. correspondence from curvature shape, both directions (a mirrored frame flips curvature sign too)
kF = curvature(F)
best = None
for rev in (False, True):
    TT = T[::-1] if rev else T
    kT = curvature(TT[:, :2])
    kT = np.interp(np.linspace(0, len(kT), len(kF), endpoint=False), np.arange(len(kT)), kT)   # same sample count
    for sign in (1, -1):
        corr = np.real(np.fft.ifft(np.fft.fft(kF) * np.conj(np.fft.fft(sign * kT))))
        sh = int(np.argmax(corr)); score = corr[sh] / (np.linalg.norm(kF) * np.linalg.norm(kT))
        if best is None or score > best[0]:
            best = (score, rev, sign, sh)
score, rev, sign, sh = best
print(f"shape match: correlation {score:.3f}, TUM reversed={rev}, mirrored={sign < 0}, shift {sh} samples")
assert sign > 0, "frames are mirrored; a rigid fit can't map one onto the other"
TT = T[::-1].copy() if rev else T.copy()
if rev:
    TT[:, 2], TT[:, 3] = TT[:, 3].copy(), TT[:, 2].copy()        # reversing travel swaps left and right
idx = (np.arange(len(F)) - sh) % len(F)
corrT = np.stack([np.interp(np.linspace(0, len(TT), len(F), endpoint=False), np.arange(len(TT)), TT[:, i]) for i in range(4)], 1)[idx]


# 2. rigid fit (Kabsch) on corresponding points; free-scale fit only as a sanity check
def kabsch(A, B, scale=False):
    ca, cb = A.mean(0), B.mean(0); H = (A - ca).T @ (B - cb)
    U, S, Vt = np.linalg.svd(H); d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1, d]) @ U.T
    s = (S * [1, d]).sum() / ((A - ca) ** 2).sum() if scale else 1.0
    return R, s, cb - s * R @ ca


R, s1, t = kabsch(corrT[:, :2], F)
_, s_free, _ = kabsch(corrT[:, :2], F, scale=True)
X = corrT[:, :2] @ R.T + t
print(f"rigid fit: rotation {np.degrees(np.arctan2(R[1, 0], R[0, 0])):+.2f} deg; free-scale fit would use scale {s_free:.4f}")
res = np.linalg.norm(X - F, axis=1)
print(f"centreline vs HAM's fastest-lap path: median {np.median(res):.1f} m, p95 {np.percentile(res, 95):.1f} m, max {res.max():.1f} m (a racing line sits off-centre by design)")

# 3a. official corner points (FastF1/TracingInsights) against the registered track
Xfull = TT[:, :2] @ R.T + t
tree = cKDTree(Xfull)
tan = np.gradient(Xfull, axis=0); tan /= np.linalg.norm(tan, axis=1, keepdims=True); nrm = np.stack([-tan[:, 1], tan[:, 0]], 1)
corners = [[c.number, c.x / 10, c.y / 10] for c in ti.circuit(2024, "Bahrain Grand Prix", "Race").corners]
rows = []
for n, x, y in corners:
    d, i = tree.query([x, y]); lat = float(np.dot([x, y] - Xfull[i], nrm[i]))
    w = TT[i, 3] if lat > 0 else TT[i, 2]
    rows.append((n, d, lat, w))
print("corner markers (official positions): " + ", ".join(f"T{n} {lat:+.1f}/{w:.1f} m" for n, d, lat, w in rows))
print(f"  all corner markers within the TUM edges: {all(abs(l) <= w + 1 for _, _, l, w in rows)}")

# 3b. held-out: every clean-lap position of every car must fall inside the edges (+1 m for car half-width slop)
clean = ses.laps.pick_wo_box().pick_quicklaps(1.07).pick_track_status("1")
pts = []
for _, lap in clean.iterlaps():
    try:
        pts.append(lap.get_pos_data()[["X", "Y"]].to_numpy() / 10)
    except Exception:
        pass
pts = np.vstack(pts)
d, i = tree.query(pts)
lat = np.einsum("ij,ij->i", pts - Xfull[i], nrm[i])
edge = np.where(lat > 0, TT[i, 3], TT[i, 2])
over = np.abs(lat) - edge
inside = (over <= 1.0).mean()
print(f"car positions: {len(pts)} samples; inside TUM edges (+1 m) {inside * 100:.2f}%; worst overshoot {over.max():.1f} m; p99.9 {np.percentile(over, 99.9):.1f} m")
# per-region overshoot, to spot a local misfit
bins = (i // 100)
bad = {int(b): float(over[bins == b].max()) for b in np.unique(bins) if over[bins == b].max() > 2}
print(f"  regions (200 m) with any sample >2 m outside: {bad or 'none'}")

# 4. local correction: where real cars run outside TUM's satellite-derived edge, shift the centreline sideways
#    (smooth, capped) so the road contains them. The cars never move; only the drawn road does.
n = len(Xfull)
lo_p, hi_p = np.zeros(n), np.zeros(n)
for k in range(n):
    sel = lat[np.abs(((i - k + n // 2) % n) - n // 2) <= 4]        # cars within ±8 m along the lap
    lo_p[k], hi_p[k] = np.percentile(sel, [0.5, 99.5]) if len(sel) > 20 else (0, 0)
need_left = np.maximum(0, hi_p - TT[:, 3] + 0.8)                   # cars beyond the left edge
need_right = np.maximum(0, -lo_p - TT[:, 2] + 0.8)
shift = np.clip(gaussian_filter1d(need_left - need_right, 12, mode="wrap"), -4, 4)
X2 = Xfull + nrm * shift[:, None]
d2, i2 = cKDTree(X2).query(pts)
tan2 = np.gradient(X2, axis=0); tan2 /= np.linalg.norm(tan2, axis=1, keepdims=True); nrm2 = np.stack([-tan2[:, 1], tan2[:, 0]], 1)
lat2 = np.einsum("ij,ij->i", pts - X2[i2], nrm2[i2])
over2 = np.abs(lat2) - np.where(lat2 > 0, TT[i2, 3], TT[i2, 2])
print(f"local correction: |shift| > 0.5 m on {np.mean(np.abs(shift) > .5) * 100:.0f}% of the lap, max {np.abs(shift).max():.1f} m")
print(f"after correction: inside (+1 m) {(over2 <= 1).mean() * 100:.2f}%, worst overshoot {over2.max():.1f} m, p99.9 {np.percentile(over2, 99.9):.1f} m")
rl = np.array([np.median(lat2[i2 == k]) if np.any(i2 == k) else np.nan for k in range(n)])
rl = gaussian_filter1d(np.interp(np.arange(n), np.flatnonzero(~np.isnan(rl)), rl[~np.isnan(rl)]), 4, mode="wrap")
print(f"average racing line now swings {rl.min():+.1f} to {rl.max():+.1f} m across the track")

json.dump({"R": R.tolist(), "t": t.tolist(), "reversed": bool(rev), "points": np.c_[X2, TT[:, 2:4]].round(3).tolist(), "rl": rl.round(2).tolist(),
           "valid": {"corr": score, "scale_free": s_free, "inside_rigid": inside, "inside_corrected": float((over2 <= 1).mean()),
                     "max_shift": float(np.abs(shift).max()), "corners": rows}}, open(OUT, "w"))
print("wrote", OUT)
