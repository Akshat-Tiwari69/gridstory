# Lap comparison API

`GET /api/v1/sessions/{year}/{event}/{session_type}/compare?driver_a=VER&lap_a=0&driver_b=LEC&lap_b=0`

Lap A and lap B are chosen independently (`0` = that driver's fastest timed lap), so the same
driver can be compared with themselves on two laps. The multi-driver
`/telemetry/compare` route is unchanged. Implementation: `apps/api/app/analysis/compare.py`
(pure functions); `F1DataService.compare_laps` resolves laps, telemetry and corners through the
same FastF1 → TracingInsights fallback as the other routes.

## Conventions

- **Delta:** `delta(d) = time_B(d) - time_A(d)` at equal distance. Positive = B is behind A.
  Finish delta = `B.lap_time - A.lap_time`. Swapping A and B negates every number.
- **Segment gain:** `gain_a_s = delta(end) - delta(start)`; positive = A gained time there.
  Segments tile the lap exactly, so their gains sum to the finish delta.
- **Segment boundaries:** corner segment = 200 m before to 120 m after the corner distance
  (shrunk to the midpoint between close corners); the rest is `straight`. No corner distances →
  equal ~500 m `distance` segments and a `corners_missing` warning. Fastest lap = minimum
  official lap time in the lap table (same rule on both data sources).
- **Grid:** channels are linearly interpolated every 5 m. Brake and gear use the nearest value.

## Endpoint treatment (why the curve ends where it does)

Distance is integrated from speed, so two laps end 5 to 20 m apart (Bahrain Q VER 5366 m,
LEC 5380 m). Both laps are therefore **scaled to their mean length** (factors in
`alignment.scale_a/b`, warning `distance_scaled` above 0.5 %), making the last grid point the
line for both. The finish delta then equals the official difference (Bahrain 2024 Q VER L16 vs
LEC L12: -0.014 s, error 0.000 s). Time is never rescaled; a telemetry duration that disagrees
with the official lap time raises `telemetry_duration`, and a finish error above 0.05 s raises
`finish_delta_mismatch`. If lengths differ by more than 2 % (incomplete telemetry) nothing is
scaled, laps are cut at the shorter coverage (`truncated_to_common_coverage`), and
`finish.delta_s` is `null`: no finish claim is made.

## Honesty rules

- Bad samples (non-finite, repeated, out-of-order) are dropped and counted in warnings.
- An all-zero brake or throttle channel is treated as **missing** (loaders write 0 for absent
  data); nothing is derived from it and the channel is `null` in the response.
- Brake-on = last 0→1 brake edge before the minimum-speed point, searched back to the previous
  exit; if the brake is already on there, no point is reported. Throttle-on = first ≥50 %
  throttle after the minimum-speed point, only if the throttle was lifted at the apex.
- Brake/throttle point differences smaller than the native sample spacing
  (`alignment.resolution_*_m`) are flagged `*_significant: false` and not mentioned in findings.
  Segment gains under 0.02 s and speed differences under 2 km/h are likewise not reported.
- Findings are the top 5 segments by |gain| (ties: earlier segment); each cites the same
  `segment_id` and gain as `segments`, so findings always match the visible delta trace.
- Other warning codes: `pit_lap`, `inaccurate_lap`, `same_lap`, `corners_partial`,
  `nonfinite_samples`, `duplicate_samples`, `brake_missing`, `throttle_missing`.

Errors: unknown driver/lap or a lap with no official time → 404; negative lap, bad driver
length or unusable telemetry → 422.
