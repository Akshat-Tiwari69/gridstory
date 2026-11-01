"""Lap comparison: two independent laps (A, B) aligned on distance.

Conventions (all of them are returned to the client, nothing is implicit):

* ``delta(d) = time_B(d) - time_A(d)`` at equal distance ``d``. Positive means B is behind A.
  At the finish this is ``B.lap_time - A.lap_time``. Swapping A and B negates the whole curve.
* A segment's ``gain_a_s = delta(end) - delta(start)``; positive means A gained on B there.
  Segments partition ``[0, common_length]`` exactly, so their gains sum to the finish delta.
* Segment boundaries come from the circuit's corner distances: a corner segment spans
  ``CORNER_BEFORE_M`` before to ``CORNER_AFTER_M`` after the corner (shrunk to the midpoint when
  corners are closer), and what is left between corners is a straight segment. Without corner
  distances the lap is cut into equal distance segments instead.

Endpoint treatment: each lap's distance is integrated from speed, so two laps on the same
track end 5 to 20 m apart. Comparing raw distance would put the "finish" of one lap at a
different place on the other. Instead both laps are scaled to their mean length (the factors
are reported in ``alignment``), so the last grid point is the line for both and the finish
delta is the real lap-time difference. If the lengths differ by more than
``MAX_LENGTH_MISMATCH`` the data is incomplete, not drifted: nothing is scaled, the laps are
cut at the shorter coverage, and no finish delta is claimed. Time is never rescaled; if the
telemetry duration disagrees with the official lap time that is reported as a warning.
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np

from app.models.f1 import (
    ComparisonAlignment,
    ComparisonChannels,
    ComparisonFinding,
    ComparisonFinish,
    ComparisonSegment,
    ComparisonWarning,
    Corner,
    CornerMetrics,
    CornerSide,
    LapComparison,
    LapRef,
    TelemetryDataset,
)

GRID_STEP_M = 5.0
MAX_LENGTH_MISMATCH = 0.02  # fraction of lap length
SCALE_WARN = 0.005  # warn when distance had to be scaled by more than this
OFFICIAL_TOLERANCE_S = 0.05  # finish delta vs official lap-time difference
CORNER_BEFORE_M = 200.0  # braking zone included in a corner segment
CORNER_AFTER_M = 120.0  # exit included in a corner segment
FALLBACK_SEGMENT_M = 500.0
MIN_SAMPLES = 20
THROTTLE_ON_PCT = 50.0
# Smallest segment gain worth reporting. Well under the 0.05 s finish tolerance, but above
# the interpolation noise between ~4 Hz samples; anything below is not called a finding.
MIN_GAIN_S = 0.02
MIN_SPEED_DIFF = 2.0  # km/h; speed is reported in whole km/h
MAX_FINDINGS = 5


class ComparisonError(ValueError):
    """The selection can't be compared (→ HTTP 422)."""


@dataclass
class Trace:
    """One lap's telemetry, cleaned: strictly increasing distance, lap-local zero origin."""
    distance: np.ndarray
    time: np.ndarray
    speed: np.ndarray
    throttle: Optional[np.ndarray]
    brake: Optional[np.ndarray]
    gear: Optional[np.ndarray]

    @property
    def length(self) -> float:
        return float(self.distance[-1])

    @property
    def step(self) -> float:
        return float(np.median(np.diff(self.distance)))


def _warn(out: List[ComparisonWarning], code: str, message: str, lap: Optional[str] = None):
    out.append(ComparisonWarning(code=code, message=message, lap=lap))


def clean_trace(tel: TelemetryDataset, side: str, warnings: List[ComparisonWarning]) -> Trace:
    """Validate one lap's channels. Never invents samples; bad rows are dropped and reported."""
    n = len(tel.distance)

    def arr(values) -> Optional[np.ndarray]:
        a = np.asarray(values, dtype=float)
        return a if len(a) == n else None

    dist, time, speed = arr(tel.distance), arr(tel.time), arr(tel.speed)
    if dist is None or time is None or speed is None or n < MIN_SAMPLES:
        raise ComparisonError(f"Lap {side} has no usable telemetry ({n} samples)")

    # The loaders write 0 for a channel the source lacks. A real lap always brakes at least
    # once and always has throttle, so an all-zero channel means missing, not "never used".
    channels = {"throttle": arr(tel.throttle), "brake": arr(tel.brake), "gear": arr(tel.gear)}
    for name in list(channels):
        c = channels[name]
        if c is None or not np.isfinite(c).any() or not np.any(np.nan_to_num(c) != 0):
            if name != "gear":
                _warn(warnings, f"{name}_missing",
                      f"Lap {side} has no {name} data; {name} points are not reported", side)
            channels[name] = None

    keep = np.isfinite(dist) & np.isfinite(time) & np.isfinite(speed)
    for c in channels.values():
        if c is not None:
            keep &= np.isfinite(c)
    nonfinite = int(n - keep.sum())

    d, t = dist[keep], time[keep]
    order = np.arange(len(d))
    # Keep a sample only if distance and time both advance past everything before it.
    # (Stationary or repeated rows would break interpolation and invent zero-length steps.)
    run_d = np.maximum.accumulate(np.concatenate(([-np.inf], d[:-1])))
    run_t = np.maximum.accumulate(np.concatenate(([-np.inf], t[:-1])))
    ok = (d > run_d) & (t >= run_t)
    duplicates = int(len(d) - ok.sum())
    order = order[ok]

    if nonfinite:
        _warn(warnings, "nonfinite_samples",
              f"Lap {side}: dropped {nonfinite} samples with non-finite values", side)
    if duplicates:
        _warn(warnings, "duplicate_samples",
              f"Lap {side}: dropped {duplicates} repeated or out-of-order samples", side)
    if len(order) < MIN_SAMPLES:
        raise ComparisonError(f"Lap {side} has too few valid telemetry samples ({len(order)})")

    def take(a: Optional[np.ndarray]) -> Optional[np.ndarray]:
        return None if a is None else a[keep][order]

    d, t = d[order], t[order]
    return Trace(
        distance=d - d[0], time=t - t[0], speed=speed[keep][order],
        throttle=take(channels["throttle"]), brake=take(channels["brake"]),
        gear=take(channels["gear"]),
    )


def _interp(grid, x, y):
    return None if y is None else np.interp(grid, x, y)


def _nearest(grid, x, y):
    return None if y is None else np.rint(np.interp(grid, x, y)).astype(int)


def _speed_at(trace: Trace, d: float) -> float:
    return float(np.interp(d, trace.distance, trace.speed))


# --- segments -----------------------------------------------------------------------------


@dataclass
class _Span:
    id: str
    kind: str
    label: str
    start: float
    end: float
    corner: Optional[Corner] = None
    prev_end: float = 0.0  # where the straight before this corner starts


def _corner_label(c: Corner) -> str:
    return f"T{c.number}{c.letter or ''}"


def build_spans(length: float, corners: Sequence[Corner]) -> List[_Span]:
    usable = sorted(
        (c for c in corners if c.distance is not None and 0.0 < c.distance < length),
        key=lambda c: c.distance,
    )
    if not usable:
        count = max(1, round(length / FALLBACK_SEGMENT_M))
        edges = np.linspace(0.0, length, count + 1)
        return [
            _Span(f"d{i + 1}", "distance", f"{edges[i]:.0f}-{edges[i + 1]:.0f} m",
                  float(edges[i]), float(edges[i + 1]))
            for i in range(count)
        ]

    dist = [c.distance for c in usable]
    windows = []
    for i, c in enumerate(usable):
        before = min(CORNER_BEFORE_M, (dist[i] - dist[i - 1]) / 2 if i else dist[i])
        after = min(CORNER_AFTER_M, (dist[i + 1] - dist[i]) / 2 if i + 1 < len(dist)
                    else length - dist[i])
        windows.append((dist[i] - before, dist[i] + after))

    spans: List[_Span] = []
    cursor = 0.0
    for i, (c, (lo, hi)) in enumerate(zip(usable, windows)):
        if lo - cursor >= GRID_STEP_M:
            name = (f"Start to {_corner_label(c)}" if i == 0
                    else f"{_corner_label(usable[i - 1])}-{_corner_label(c)} straight")
            spans.append(_Span(f"s{len(spans) + 1}", "straight", name, cursor, lo))
        spans.append(_Span(f"c{c.number}{c.letter or ''}", "corner", _corner_label(c), lo, hi,
                           corner=c, prev_end=cursor))
        cursor = hi
    if length - cursor >= GRID_STEP_M:
        spans.append(_Span(f"s{len(spans) + 1}", "straight",
                           f"{_corner_label(usable[-1])} to finish", cursor, length))
    # Absorb sub-grid slivers so the spans still tile [0, length] exactly.
    spans[0].start = 0.0
    spans[-1].end = length
    return spans


# --- corner metrics -----------------------------------------------------------------------


def _side_metrics(tr: Trace, span: _Span) -> CornerSide:
    in_win = (tr.distance >= span.start) & (tr.distance <= span.end)
    if in_win.sum() < 2:
        return CornerSide()
    idx = np.flatnonzero(in_win)
    apex = int(idx[np.argmin(tr.speed[idx])])

    brake_on = None
    if tr.brake is not None:
        # Last 0 -> 1 edge before the apex, searched back to the previous exit. If the brake is
        # already on there, braking started earlier than we can see and no point is claimed.
        lo = int(np.searchsorted(tr.distance, span.prev_end))
        seg = tr.brake[lo:apex + 1] >= 0.5
        edges = np.flatnonzero(~seg[:-1] & seg[1:]) if len(seg) > 1 else []
        if len(edges):
            brake_on = float(tr.distance[lo + int(edges[-1]) + 1])

    throttle_on = None
    if tr.throttle is not None and tr.throttle[apex] < THROTTLE_ON_PCT:
        after = np.flatnonzero(tr.throttle[apex:idx[-1] + 1] >= THROTTLE_ON_PCT)
        if len(after):
            throttle_on = float(tr.distance[apex + int(after[0])])

    return CornerSide(
        entry_speed=round(_speed_at(tr, span.start), 1),
        min_speed=round(float(tr.speed[apex]), 1),
        min_speed_distance=round(float(tr.distance[apex]), 1),
        exit_speed=round(_speed_at(tr, span.end), 1),
        brake_on_m=None if brake_on is None else round(brake_on, 1),
        throttle_on_m=None if throttle_on is None else round(throttle_on, 1),
    )


def _diff(a: Optional[float], b: Optional[float], resolution: float):
    if a is None or b is None:
        return None, False
    d = b - a
    return round(d, 1), abs(d) >= resolution


def corner_metrics(a: Trace, b: Trace, span: _Span) -> CornerMetrics:
    sa, sb = _side_metrics(a, span), _side_metrics(b, span)
    # Brake and throttle points are only as good as the sample spacing (~20 m at speed).
    res = max(a.step, b.step)
    bd, bs = _diff(sa.brake_on_m, sb.brake_on_m, res)
    td, ts = _diff(sa.throttle_on_m, sb.throttle_on_m, res)
    return CornerMetrics(a=sa, b=sb, brake_diff_m=bd, brake_diff_significant=bs,
                         throttle_diff_m=td, throttle_diff_significant=ts)


# --- findings -----------------------------------------------------------------------------


def _explain(seg: ComparisonSegment, win: str, aa: Trace, bb: Trace) -> str:
    """Why the winner gained, from channels that exist. Nothing is said without evidence."""
    parts: List[str] = []
    cm = seg.corner
    if cm is not None:
        w, lo = (cm.a, cm.b) if win == "A" else (cm.b, cm.a)
        if cm.brake_diff_significant:
            later = w.brake_on_m - lo.brake_on_m
            parts.append(f"brakes {abs(later):.0f} m {'later' if later > 0 else 'earlier'}")
        if w.min_speed is not None and lo.min_speed is not None:
            dv = w.min_speed - lo.min_speed
            if abs(dv) >= MIN_SPEED_DIFF:
                parts.append(f"carries {abs(dv):.0f} km/h {'more' if dv > 0 else 'less'} "
                             "minimum speed")
        if cm.throttle_diff_significant:
            earlier = lo.throttle_on_m - w.throttle_on_m
            parts.append(f"gets on the throttle {abs(earlier):.0f} m "
                         f"{'earlier' if earlier > 0 else 'later'}")
        if w.exit_speed is not None and lo.exit_speed is not None:
            dv = w.exit_speed - lo.exit_speed
            if abs(dv) >= MIN_SPEED_DIFF:
                parts.append(f"exits {abs(dv):.0f} km/h {'faster' if dv > 0 else 'slower'}")
    elif seg.kind == "straight":
        wt, lt = (aa, bb) if win == "A" else (bb, aa)
        mw = (wt.distance >= seg.start_m) & (wt.distance <= seg.end_m)
        ml = (lt.distance >= seg.start_m) & (lt.distance <= seg.end_m)
        if mw.any() and ml.any():
            dv = float(wt.speed[mw].max()) - float(lt.speed[ml].max())
            if abs(dv) >= MIN_SPEED_DIFF:
                parts.append(f"reaches {abs(dv):.0f} km/h {'higher' if dv > 0 else 'lower'} "
                             "top speed")
    if not parts:
        return " No clear difference in the recorded channels."
    text = ", ".join(parts[:3])
    return f" {text[0].upper()}{text[1:]}."


def make_findings(
    segments: List[ComparisonSegment], lap_a: LapRef, lap_b: LapRef, aa: Trace, bb: Trace,
) -> List[ComparisonFinding]:
    """Rank segments by absolute gain; the findings are exactly the biggest visible segments."""
    ranked = sorted(
        (s for s in segments if abs(s.gain_a_s) >= MIN_GAIN_S),
        key=lambda s: (-abs(s.gain_a_s), s.start_m),
    )[:MAX_FINDINGS]
    out = []
    for rank, s in enumerate(ranked, 1):
        win = "A" if s.gain_a_s > 0 else "B"
        w, loser = (lap_a, lap_b) if win == "A" else (lap_b, lap_a)
        lead = "Biggest gain" if rank == 1 else f"Gain #{rank}"
        text = (f"{lead}: {s.label}, +{abs(s.gain_a_s):.2f} s for {w.label} over {loser.label}."
                + _explain(s, win, aa, bb))
        out.append(ComparisonFinding(rank=rank, segment_id=s.id, winner=win,
                                     gain_s=round(abs(s.gain_a_s), 4), text=text))
    return out


# --- main entry ---------------------------------------------------------------------------


def compare_laps(
    lap_a: LapRef, tel_a: TelemetryDataset,
    lap_b: LapRef, tel_b: TelemetryDataset,
    corners: Optional[Sequence[Corner]] = None,
) -> LapComparison:
    warnings: List[ComparisonWarning] = []
    ta = clean_trace(tel_a, "A", warnings)
    tb = clean_trace(tel_b, "B", warnings)

    for side, ref, tr in (("A", lap_a, ta), ("B", lap_b, tb)):
        if ref.is_out_lap or ref.is_in_lap:
            _warn(warnings, "pit_lap", f"{ref.label} is {'an out' if ref.is_out_lap else 'an in'}"
                  " lap; it is not a representative flying lap", side)
        elif not ref.is_accurate:
            _warn(warnings, "inaccurate_lap", f"{ref.label} is flagged as not accurate", side)
        if abs(tr.time[-1] - ref.lap_time) > OFFICIAL_TOLERANCE_S:
            _warn(warnings, "telemetry_duration",
                  f"{ref.label}: telemetry spans {tr.time[-1]:.3f} s but the official lap time is "
                  f"{ref.lap_time:.3f} s", side)
    if lap_a.driver == lap_b.driver and lap_a.lap_number == lap_b.lap_number:
        _warn(warnings, "same_lap", "Both selections are the same lap; the delta is zero")

    mismatch = abs(ta.length - tb.length) / max(ta.length, tb.length)
    if mismatch <= MAX_LENGTH_MISMATCH:
        length = (ta.length + tb.length) / 2
        sa, sb = length / ta.length, length / tb.length
        method = "scaled_to_mean_length"
        if max(abs(sa - 1), abs(sb - 1)) > SCALE_WARN:
            _warn(warnings, "distance_scaled",
                  f"Lap distance scaled by {sa:.4f} (A) and {sb:.4f} (B) to a common length")
    else:
        length = min(ta.length, tb.length)
        sa = sb = 1.0
        method = "truncated_to_common_coverage"
        _warn(warnings, "unequal_coverage",
              f"Telemetry covers {ta.length:.0f} m (A) and {tb.length:.0f} m (B); compared up to "
              f"{length:.0f} m only, so there is no finish delta")

    da, db = ta.distance * sa, tb.distance * sb
    grid = np.append(np.arange(0.0, length, GRID_STEP_M), length)
    time_a, time_b = np.interp(grid, da, ta.time), np.interp(grid, db, tb.time)
    delta = time_b - time_a

    # Aligned copies of the traces (distance on the common scale) for corner analysis.
    aa = Trace(da, ta.time, ta.speed, ta.throttle, ta.brake, ta.gear)
    bb = Trace(db, tb.time, tb.speed, tb.throttle, tb.brake, tb.gear)

    corner_list = list(corners or [])
    if not any(c.distance is not None for c in corner_list):
        _warn(warnings, "corners_missing",
              "No corner distances for this circuit; segments are equal distance slices and "
              "corner metrics are not reported")
    elif any(c.distance is None for c in corner_list):
        _warn(warnings, "corners_partial", "Some corners have no distance and were skipped")

    segments: List[ComparisonSegment] = []
    for span in build_spans(length, corner_list):
        d0, d1 = float(np.interp(span.start, grid, delta)), float(np.interp(span.end, grid, delta))
        segments.append(ComparisonSegment(
            id=span.id, kind=span.kind, label=span.label,
            corner_number=span.corner.number if span.corner else None,
            start_m=round(span.start, 1), end_m=round(span.end, 1),
            delta_start_s=round(d0, 4), delta_end_s=round(d1, 4), gain_a_s=round(d1 - d0, 4),
            corner=corner_metrics(aa, bb, span) if span.kind == "corner" else None,
        ))
    findings = make_findings(segments, lap_a, lap_b, aa, bb)

    official = lap_b.lap_time - lap_a.lap_time
    if method == "scaled_to_mean_length":
        finish_delta = float(delta[-1])
        err = finish_delta - official
        ok = abs(err) <= OFFICIAL_TOLERANCE_S
        if not ok:
            _warn(warnings, "finish_delta_mismatch",
                  f"Finish delta {finish_delta:.3f} s differs from the official lap-time "
                  f"difference {official:.3f} s by {err:+.3f} s")
        finish = ComparisonFinish(delta_s=round(finish_delta, 4),
                                  official_delta_s=round(official, 4), error_s=round(err, 4),
                                  within_tolerance=ok, tolerance_s=OFFICIAL_TOLERANCE_S)
    else:
        finish = ComparisonFinish(official_delta_s=round(official, 4),
                                  tolerance_s=OFFICIAL_TOLERANCE_S)

    def rl(x, nd=1):
        return None if x is None else np.round(x, nd).tolist()

    channels = ComparisonChannels(
        distance=rl(grid), time_a=rl(time_a, 4), time_b=rl(time_b, 4),
        speed_a=rl(np.interp(grid, da, ta.speed)), speed_b=rl(np.interp(grid, db, tb.speed)),
        throttle_a=rl(_interp(grid, da, ta.throttle)),
        throttle_b=rl(_interp(grid, db, tb.throttle)),
        brake_a=_ints(_nearest(grid, da, ta.brake)), brake_b=_ints(_nearest(grid, db, tb.brake)),
        gear_a=_ints(_nearest(grid, da, ta.gear)), gear_b=_ints(_nearest(grid, db, tb.gear)),
    )
    return LapComparison(
        lap_a=lap_a, lap_b=lap_b,
        alignment=ComparisonAlignment(
            grid_step_m=GRID_STEP_M, common_length_m=round(length, 1),
            length_a_m=round(ta.length, 1), length_b_m=round(tb.length, 1),
            scale_a=round(sa, 5), scale_b=round(sb, 5), method=method,
            resolution_a_m=round(ta.step, 1), resolution_b_m=round(tb.step, 1),
        ),
        channels=channels, delta_s=rl(delta, 4), finish=finish, segments=segments,
        findings=findings, warnings=warnings,
    )


def _ints(a):
    return None if a is None else a.tolist()

