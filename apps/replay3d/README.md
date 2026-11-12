# 3D race replay (prototype)

A directed, broadcast-style 3D replay of one real moment: the 2024 Bahrain GP pit window where Hamilton stopped
first, rejoined, and came out ahead of Piastri side by side into Turn 1 (laps 33–35). About 90 seconds, 12 shots:
helicopter, trackside telephoto, onboard T-cam, pit lane, Turn 1 slow motion, rear onboard, finish line.

Everything the cars do comes from the race data: positions, speed, RPM, gear, throttle, brake, DRS, pit-lane
times and the live interval. Lighting, camera direction, crowds and models are illustration.

## Run it

It's a static page (three.js from a CDN), so any static server works:

```bash
cd apps/replay3d && python -m http.server 5180
```

Then open <http://localhost:5180>. `?venue=0` forces the built-in circuit even when a venue model is present;
`?fps` shows a frame-time readout.

## Local-only models

The page runs as-is with built-in models: procedural ground-effect cars (`f1car.js`), a pit crew (`pitcrew.js`),
and a circuit built from the data with landmark scenery (`scenery.js`). If you own licensed models, drop them in
and they're used instead; these folders are git-ignored and must never be committed or published:

| Folder | Contents | Used for |
|---|---|---|
| `cars/w15/w15.glb`, `cars/mcl38/mcl38.glb` (+ `textures/`) | glTF car models | Hamilton / Piastri |
| `venue/bahrain.glb`, `venue/venue-transform.json`, `venue/track-heights.json` | a venue model and its registration | the circuit |

Car models need their axle positions, tyre radius and camera mounts measured: `tools/fit_wheels.py` reports
them, and they go in the `REAL` table in `index.html`. A venue is registered onto the race data with
`tools/venue/register_venue.py`, and its pit lane extracted with `tools/venue/build_pitlane.py`. Both read and
write next to themselves, so copy them into `venue/` beside `bahrain.glb` and `gs3d-data.json` and run them
there (register first). They write `venue-transform.json`, `track-heights.json`, `pitlane-model.json` and a
validation report.

## Regenerating `gs3d-data.json`

Run from `apps/api` (the scripts use its virtualenv, FastF1 cache and TracingInsights client):

```bash
python ../replay3d/tools/register_tum.py Sakhir.csv app/f1_cache tum-registered.json
python ../replay3d/tools/extract_3d.py app/f1_cache ../replay3d/gs3d-data.json tum-registered.json [pitlane-model.json]
```

`Sakhir.csv` is the Sakhir centreline + track widths from the
[TUMFTM racetrack-database](https://github.com/TUMFTM/racetrack-database) (LGPL-3.0). `pitlane-model.json` is
optional: without it the pit lane comes from Hamilton's own pass, which drifts toward the track edge.

What the extraction does, and the checks it enforces:

- Smooths each car's ~4 Hz position feed onto a 20 Hz path driven by its measured speed, dropping samples that
  moved further than the car's speed allows (the feed time-shifts at pit entry).
- Keeps the two cars from overlapping when they're side by side, choosing one side per episode so nobody swaps
  sides; asserts no car ever slides sideways faster than 3 m/s.
- Builds the road from the TUM centreline and widths, aligned by corner shape (not fitted to where cars drive),
  with a capped local shift where real cars run outside the satellite-measured edges (99.7 % of 364 k clean-lap
  positions end up inside).
- Computes the live interval from distance travelled, which matches official timing at the lap lines
  (+2.2 s after lap 32, −3.7 s after lap 35).

Data credits are in [`docs/RESOURCES.md`](../../docs/RESOURCES.md).
