# Pitwall — Roadmap

> Last updated: 2026-10-16 · Status legend: ✅ done · 🟡 partial · ⬜ not started

## How this roadmap works

**Assumptions** (change these and the plan changes): solo developer · showcase-quality project with a public demo · historical sessions first, live data later · one LLM provider.

**Principles**

1. **Vertical slices.** Every milestone ends in something a user can open and use. No phase of "all the charts", then "all the analysis", then "all the AI".
2. **Insight ships with the view.** Each analysis view comes with plain-language findings from day one. They're deterministic templates first; the LLM rewrites them later. "Why, not just what" starts in Phase 2, not Phase 4.
3. **Real data only.** No mock panels in the product. If FastF1 can't provide it (fuel, brake temps, ERS, tyre temps), we don't show it.
4. **Compute in Python, render in React.** Analysis lives in pure, tested functions in `apps/api/app/analysis/`. The web app only draws results.
5. **Every milestone has a "Done when".** It's a concrete check, ideally against a known race, not "feels polished".

Sizes: **S** ≈ a few evenings · **M** ≈ 1–2 weeks · **L** ≈ 3+ weeks (split it).

Data sources, references and inspiration (with licences) live in **[RESOURCES.md](RESOURCES.md)**; milestones below link the ones they use.

---

## Now / Next / Later

| | |
|---|---|
| **Now** | Phase 1 is complete. Next: Phase 2, lap comparison, once the data question below is settled |
| **Data** | F1's timing archive has needed an F1 TV login since ~15 Oct 2026 ([Fast-F1#978](https://github.com/theOehrly/Fast-F1/issues/978)). ✅ **Workaround in place:** when FastF1 has nothing, the API falls back to the [TracingInsights archive](https://github.com/TracingInsights-Archive), so **2018 to May 2026** works (checked: 2025 China, 2026 Japan). ⏸ Still missing: 2026 races after May. **Plan B for those:** [OpenF1](https://openf1.org) (has current 2026 telemetry, verified 2026-10-17), if FastF1 is still locked out when Phase 2 starts. |
| **Name** | ⚠ "Pitwall" clashes with three live F1 products ([pitwall.app](https://pitwall.app/), [f1pitwall.fun](https://f1pitwall.fun/), [f1pitwall.dev](https://f1pitwall.dev/)), one of them a replay and telemetry dashboard. Rename before v0.1 |
| **Next** | Phase 2: lap comparison with auto-generated findings → **v0.1 public demo** |
| **Then** | Phase 3: race story (incl. team radio) → Phase 4: AI race engineer → **v0.2** → Phase 5: 3D race replay, F1 Manager-style → **v1.0** |
| **Later** | Driver profiles & season view, live timing, strategy simulator |

---

## Architecture

```
apps/web  React + Vite + TS · TanStack Query · Zustand · ECharts · Three.js
   │  REST (JSON)
apps/api  FastAPI
   ├── api/         routes, error mapping
   ├── services/    FastF1 loading + in-memory session cache        ✅
   │                TracingInsights fallback (2018 to May 2026)     ✅
   ├── analysis/    pure functions: compare, stints, degradation…   ⬜ (Phase 2+)
   ├── engineer/    LLM tool-calling over analysis/                 ⬜ (Phase 4)
   └── storage      FastF1 + TracingInsights disk caches ✅ · computed results as files ⬜
```

No database, Redis or WebSocket until a feature actually needs one. Historical data is immutable, so computed results are cached as files keyed by session.

---

## Phase 1 — Foundation & Session Explorer *(in progress)*

**Goal:** someone can pick any session from 2018 to today, trust everything on screen, and share a link to it.

### ✅ Already done
- Monorepo (`apps/api`, `apps/web`, `docs/`), git, Makefile, README
- FastF1 data service: seasons, results, laps, telemetry (single + multi-driver), weather, race control, circuit info, track outline
- Session cache: one load per session shared across requests, upgraded in place when telemetry is needed
- Dashboard shell, design tokens, Year → Event → Session selector, sidebar navigation
- Timing tower (position, team, gap), lap table, telemetry charts (speed/throttle/brake/gear, up to 3 drivers, linked crosshair)
- 3D track view, team-themed driver dashboard, tyre strategy for one driver, weather strip, race control feed
- API smoke tests (`apps/api/tests`)

### 1.1 API hardening — S ✅
*Shipped 2026-10-16. CI is green. Also fixed: race gaps were negative (`+-5482s`), and lapped cars now show "+1 Lap". Note: 2026 sessions are selectable, but since F1's archive lockout only their results load (see Data above).*
- Typed errors: unknown event / driver / lap → 404; bad params → 422; never return raw exception text
- Resolve the event name through the FastF1 schedule, so "bahrain", "Bahrain" and "Bahrain Grand Prix" share one cache entry
- Season range from 2018 to the current year, derived from the date instead of hardcoded (2026 is currently unreachable)
- Replace the deprecated `pick_driver` with `pick_drivers`; add request logging
- Web: API base URL from `VITE_API_URL`
- CI (GitHub Actions): ruff, pytest, `tsc`, eslint, build

**Done when:** CI is green; `GET …/2024/Atlantis/R/results` returns 404; 2026 sessions are selectable.

### 1.2 Honest UI — S ✅
*Shipped 2026-10-16, finished 2026-10-17. Initial JS is 108 kB gzipped; ECharts and Three.js load as separate chunks. Also removed: the fake account avatar, the Strategy/AI Engineer "coming soon" pages, and panel titles that promised more than they showed ("Track positions", "Lap comparison").*
- Remove the Car Status gauges (FastF1 has no fuel, brake temp or ERS data) and hide the mock AI Engineer panel until Phase 4
- Remove or label the 3D car dots (they're evenly spaced, not real positions) until replay exists
- Skeleton loaders and real error states instead of blank panels
- Lazy-load routes so Three.js and ECharts aren't in the first bundle

**Done when:** no mock or placeholder data anywhere in the UI (the only "demo" in the code is the GitHub Pages online-demo mode); initial JS is under 250 kB gzipped (was ~600 kB).

### 1.3 URL state — S ✅
*Shipped 2026-10-17. The selection lives in query parameters (`/telemetry?year=2024&event=Bahrain+Grand+Prix&session=R&drivers=VER,LEC&lap=12`, plus `focus=` for the driver view), so links also work on the GitHub Pages demo. Verified: a pasted link restores page, session, drivers and lap; clicks update the URL; the sidebar keeps the selection between pages.*
- Session, selected drivers and lap live in the URL, e.g. `/2024/bahrain/R/telemetry?d=VER,LEC&lap=fastest`
- Reloading restores the view, and links are shareable. This covers most of the old "community sharing" idea for free.

**Done when:** copying the URL into a fresh tab reproduces the exact view.

### 1.4 Session explorer completion — M ✅
*Shipped 2026-10-17. Verified against [OpenF1](https://openf1.org) as an independent source for Bahrain 2024 R: fastest lap (VER 1:32.608, lap 39), 0 SC / 0 VSC, and all 20 drivers' pit counts match.*
- Timing tower: current tyre and its age, pit stop count, fastest lap in purple
- Lap table: sortable and filterable, personal bests in green, overall fastest in purple, pit in/out laps marked
- Session summary card: winner/pole, fastest lap, laps completed, SC/VSC count, weather range
- Telemetry: add RPM and DRS traces (the API already sends them), corner markers from circuit info, zoom

**Done when:** for Bahrain 2024 R, the fastest lap, pit counts and SC periods shown match the official results.

### 1.5 Analysis track map — M ✅
*Shipped 2026-10-17, on the Telemetry page next to the charts. The speed heatmap uses a single-hue blue ramp (dark = slow, light = fast) rather than blue→red, which keeps it colour-blind safe. Verified: hovering the T1 label snaps to 712 m (FastF1's T1 distance is 712.3 m), and the chart crosshair lands on the T1 braking minimum (73 km/h, 3rd gear).*
- A 2D SVG map for analysis: crisp labels and hover. Three.js stays for the showcase and replay view.
- Circuit rotation, corner numbers, sector colours, speed heatmap for the selected lap
- Shared distance cursor: hovering the map moves the telemetry crosshair, and the reverse

**Done when:** hovering Turn 1 on the map highlights the braking zone in the speed trace.

### 1.6 Cold-load experience — S ✅
*Shipped 2026-10-17. Measured on a fresh API process with a warm disk cache: the dashboard's requests take under 1 s in total. ⚠ The **first** telemetry view of a session takes ~3.3 s (car and position data processed once), then ~0.01 s. Panels loading for more than 4 s now explain why. Under the archive lockout, the command can only re-warm already-cached sessions; others are reported and skipped.*
- `python -m app.precompute 2024` warms the FastF1 cache for a season
- The first-load state says what's happening: a cold race download takes tens of seconds

**Done when:** demo sessions open in under 2 s on a warm cache.

---

## Phase 2 — Lap Comparison *(first "intelligence" slice)* → v0.1

**Goal:** pick two laps and get told *where* and *how* the time was won or lost.

### 2.1 Comparison engine — M ⬜
- `analysis/compare.py`: resample both laps onto a common distance grid (e.g. every 5 m), compute the cumulative delta, and split into corner-based segments using the `Distance` of each corner in circuit info
- Per corner: entry speed, minimum speed, exit speed, brake-on point, throttle-on point
- Golden tests against cached sessions

**Done when:** the delta at the finish line equals the real lap time difference within 0.05 s (this is a built-in correctness check).

### 2.2 Comparison view — M ⬜
- Driver A/lap vs driver B/lap pickers with "fastest vs fastest" and "teammates" shortcuts
- Delta trace under the speed traces, a corner-by-corner table, the track map coloured by who's faster, and brake-point markers

### 2.3 Findings v1 (deterministic) — S ⬜
- Rank segments by time gained or lost, then template the top findings, e.g. *"Biggest gain: T10, +0.14 s. Brakes 11 m later and carries 6 km/h more minimum speed."*
- Suppress differences below sampling resolution (see Data caveats) instead of reporting noise

**Done when:** on Bahrain 2024 Q (VER vs LEC fastest laps), the top 3 findings agree with what the delta trace visibly shows.

### 2.4 Release v0.1 — S ⬜
- Deploy: API in a Docker container with a persistent volume for the FastF1 cache; web as a static site
- The cache must be warmed locally and shipped, since nothing can download new sessions while F1's archive needs a login (see Data caveats).
- README with screenshots and a demo link; 3–5 preloaded showcase sessions

**Done when:** a stranger can open the public URL and compare two laps without instructions.

---

## Phase 3 — Race Story

**Goal:** understand a whole race: strategy, pace, pit stops and safety cars, with findings.

### 3.1 Race data layer — M ⬜
- Stints, pit stops (time in the pit lane from PitIn/PitOut; stationary time isn't in the data), track status (SC/VSC/red flag), position and gap to the leader per lap

### 3.2 Race views — M 🟡
- Strategy chart for the whole field (today it exists for one driver), gap-to-leader race trace, position chart, SC/VSC shading on all of them

### 3.3 Tyre degradation — M ⬜
- **Fuel correction (correct sign):** normalise every lap to an empty tank, `corrected = lap_time − laps_remaining × k`, with k ≈ 0.03–0.06 s/lap as a configurable value. Heavy early laps get *faster* after correction, not slower.
- Clean laps only: exclude in-laps, out-laps, SC/VSC laps and lap 1
- A linear fit per stint gives the degradation rate in s/lap with a confidence range. Only call a "cliff" when a two-segment fit beats the linear one by a clear margin.

**Done when:** degradation rates are stable (±20%) when one lap is removed from a stint.

### 3.4 Pit-stop outcomes — M ⬜
- For each stop, find the rivals within a pit-window gap. Undercut/overcut verdict = gap before the first car stopped vs gap after both stopped. Also track positions gained or lost through the stops.
- Real stops and stop times from the **official FIA pit-stop summaries**, parsed with [fia-doc](https://github.com/harningle/fia-doc) ([FIA F1 Archives](https://api.fia.com/f1-archives)). That also settles safety-car pit-lane drive-throughs, which the timing data counts as stops (see Data caveats)

### 3.5 Race summary v1 (deterministic) — S ⬜
- Start (lap 1 gains and losses), stops, SC periods, decisive moves, result, all generated from 3.1–3.4

**Done when:** the Bahrain 2024 summary lists every pit stop and SC period, matching the official data.

### 3.6 Team radio — S ⬜
- Each driver's radio clips (listed by [OpenF1](https://openf1.org) `team_radio`, timestamped), placed on the lap they happened and playable in the driver dashboard and on the race timeline
- Audio plays straight from F1's servers rather than being copied into Pitwall. Checked 2026-10-17: the clips still download (HTTP 200) despite the timing-archive lockout, for 2024 and 2026 races
- Real radio fills the driver-dashboard slot the fake "AI Engineer" radio left in 1.2
- Stretch: transcribe the clips (speech-to-text) so radio is searchable and readable, an idea from [undercut-f1](https://github.com/JustAman62/undercut-f1); the transcripts also become context for the AI engineer (Phase 4)

**Done when:** in 2024 Bahrain, Verstappen's clips each sit on the right lap and play.

---

## Phase 4 — AI Race Engineer → v0.2

**Goal:** ask questions in plain English and get answers grounded in computed data.

### 4.1 Tool layer — S ⬜
- Expose the analysis functions as LLM tools (`compare_laps`, `get_stints`, `get_degradation`, `get_race_events`, …)
- Rule: the model only states numbers that came back from a tool call

### 4.2 Chat panel — M ⬜
- Docked panel that knows the current view from the URL state (session, drivers, lap)
- Streaming responses, suggested questions for each view
- Answers link to evidence: links that open the relevant chart with the right drivers and laps

### 4.3 Evals & guardrails — S ⬜
- 30–50 question eval set, each with required facts and forbidden claims; run it before any prompt or model change
- No invented causes: if the data can't show *why* (setup, driver feedback), say so
- Per-session token cap, response cache for repeated questions

### 4.4 Prose findings — S ⬜
- Optional: the LLM rewrites the Phase 2/3 deterministic findings into engineer-style prose, constrained to the same facts

**Done when:** at least 90% of eval questions pass, with zero fabricated numbers.

---

## Phase 5 — 3D Race Replay → v1.0

**Goal:** replay any race in 3D, *F1 Manager*-style: all 20 cars on the track in team colours, with broadcast and follow cameras, live timing, the driver's HUD and their radio, and a timeline to jump to the moments that mattered.

**Inspiration, not assets:** the look is inspired by the F1 Manager games, but nothing is taken from them. Cars are a generic low-poly open-wheel model built in code (or a CC0 model), coloured by team, with no real liveries, logos or game assets.

### 5.1 Replay data — M ⬜
*Sources: FastF1 position data, or the [TracingInsights archive](https://github.com/TracingInsights-Archive)'s per-lap x/y/z for sessions FastF1 can't load. Reference for playback UX: [F1 Race Replay](https://github.com/IAmTomShaw/f1-race-replay), [F1ReplayTiming](https://github.com/adn8naiagent/F1ReplayTiming) (look only; no licence).*
- Every car's x/y/**z** position, resampled to a fixed ~4 Hz (the source rate; smoothing happens client-side), stored as columnar float32 chunks per 10 laps and served as static cached files over HTTP
- Budget: 20 cars × 2 h × 4 Hz × (x, y, z) ≈ 7 MB raw per race, so no WebSocket is needed, and it can ship with the online demo
- Heading for each car is derived from its direction of travel (the data has no steering or car angle)

### 5.2 Virtual onboard (one car) — M ⬜
*The first slice, and the closest honest thing to a driver cam: real onboard video is F1 TV only.*
- Play back one driver's lap or race: a cockpit-style HUD (speed, gear, rev lights, throttle and brake bars, DRS light) with a dot moving round the 2D analysis map
- Play/pause, 0.5–20× speed, scrub, jump to lap; synced with the telemetry charts' crosshair
- Their team radio (3.6) plays at the moment it was sent

**Done when:** following Verstappen's 2024 Bahrain fastest lap, the HUD's speed and gear match the telemetry chart at every point (±1 sample).

### 5.3 3D race replay — L ⬜ *(split when started)*
*Track geometry: [TUMFTM racetrack-database](https://github.com/TUMFTM/racetrack-database) centre lines and **track widths** (LGPL-3.0, 2021 layouts) so the asphalt has real width. Look and feel: [F1 Manager 2024](https://store.steampowered.com/app/2287220/F1_Manager_2024/), as inspiration only.*
- The existing Three.js track with real elevation from z (Spa, COTA), and all 20 cars as instanced low-poly models in team colours with driver labels
- Smooth interpolation between samples; play/pause, speed, scrub, jump to lap; timing tower synced to replay time
- Cameras: broadcast orbit, top-down, follow-a-car chase cam, and a "TV director" mode that cuts to the closest battle. Following a car shows its 5.2 HUD

**Done when:** a full race plays at 60 fps with all 20 cars on a mid-range laptop, and the replay's running order matches the timing tower at the end of every lap.

### 5.4 Event timeline — S ⬜
- Overtakes (position swaps not caused by pit stops), stops, SC periods and radio messages from Phase 3 shown on a timeline; click to jump the replay there

### 5.5 Overlays — S ⬜
- Flag states and safety car on track, close-gap (< 1 s) highlight, pit-lane timer, telemetry strip for the followed driver

**Done when:** every Phase 3 event is reachable from the timeline, and jumping to one shows the right cars in the right place.

---

## Phase 6 — Driver Profiles & Season *(later)*

*Sources: [F1DB](https://github.com/f1db/f1db) (CC-BY-4.0, credit required) and [Jolpica](https://github.com/jolpica/jolpica-f1) for history and standings; TracingInsights' **g-force** channels (acc_x/y/z) as an extra driving-style metric; [f1metrics](https://f1metrics.wordpress.com/) for how to rate drivers statistically.*

- **Transparent metrics, no black-box ML:** qualifying gap to teammate, race pace vs teammate (clean, fuel-corrected laps), degradation vs the field on the same compound, consistency (spread of clean lap times), lap-1 gains, overtakes made and lost. Each is shown as a percentile against the field.
- Labels like "Tyre whisperer" only when a percentile rule backs them, never from clustering about 20 drivers
- Teammate head-to-head across the season; standings evolution; multi-race context for the AI engineer
- **Research spike first:** test whether telemetry style metrics (braking aggression, throttle smoothness) are stable across laps at ~4 Hz *before* building them into the product

---

## Parking lot (only if something pulls for it)

Live timing via [OpenF1](https://openf1.org) (references: [f1-dash](https://github.com/slowlydev/f1-dash), [f1-live-data](https://github.com/f1stuff/f1-live-data)) · strategy what-if simulator ([TUMFTM race-simulation](https://github.com/TUMFTM/race-simulation), [racing-line optimisation](https://github.com/TUMFTM/global_racetrajectory_optimization)) · circuit pages on a real map ([f1-circuits](https://github.com/bacinger/f1-circuits) GeoJSON) · compound mapping C1–C5 per race ([Pirelli press](https://press.pirelli.com/en/?h=1&t=formula+1)) · image/video export · voice interface · mobile PWA

## Cut from the previous roadmap

| Item | Why |
|---|---|
| Redis, SQLite → Postgres | Historical data never changes; file caches cover it |
| WebSocket replay streaming | About 5 MB per race; static chunked files are simpler and cacheable |
| LLM provider abstraction | One provider; swap it if needed, since it's one module |
| K-means driver archetypes | About 20 samples, and unlabelled clusters don't come out as "Smooth Operator" |
| Pressure index / mistake detection | Not supportable at ~4 Hz without a research spike first |
| ECharts WebGL, telemetry pagination | A lap is around 800 points per channel |
| Week-based estimates | Replaced by S/M/L sizes and "Done when" checks |

---

## Data caveats (read before designing a feature)

| Limitation | Consequence |
|---|---|
| Car telemetry is ~4 Hz, interpolated | At 300 km/h that's ~20 m between samples, so brake-point differences under ~20 m are noise |
| `Brake` is on/off | No brake pressure; "braking aggression" can only mean timing, not force |
| X/Y position isn't a precise racing line, and is only ~4 Hz | Don't compare driving lines; compare speeds and timings. In the 3D replay, cars fighting wheel to wheel can visually overlap or swap sides; car heading is inferred from movement |
| Real onboard video is licensed to F1 TV (paid, DRM-protected); there's no public API | Never scrape or re-host it. The virtual onboard (5.2) is built from telemetry instead; at most, link out to F1 TV for subscribers |
| No fuel, tyre temperature, ERS or brake temperature data | Never display them; fuel load is modelled, not measured |
| 2026 rules replace DRS with active aero and an overtake mode | DRS-based features apply to ≤ 2025; check what the DRS channel means for 2026 sessions |
| Cold session loads download a lot of data | Precompute or warm the demo sessions; show progress |
| When the safety car leads the field through the pit lane, FastF1 and OpenF1 both record each pass as a pit stop, and their tyre ages for those laps disagree | Pitwall counts a stop only when tyre age resets. That fixes most drivers, but one can still be over-counted (Stroll shows 5 in 2025 Australia; really 2) |
| **Since ~15 Oct 2026, F1's timing archive returns 401 without an F1 TV login** ([Fast-F1#978](https://github.com/theOehrly/Fast-F1/issues/978)); FastF1's mirror has no 2023–2026 data | FastF1 serves only cached sessions (2024 Bahrain Q/R, 2024 Saudi R, 2025 Australia R); everything else from 2018 to May 2026 comes from the TracingInsights fallback, and later 2026 races get results only. CI skips `livedata` tests. **Never clear `app/f1_cache`**: a backup is at `F:\Code\Backups\pitwall-f1-cache-2026-10-17` |

## Engineering standards

- **Tests:** analysis functions get golden tests against cached real sessions; API routes get smoke tests; CI blocks merges on red
- **Performance budgets:** warm API responses < 300 ms; initial web JS < 250 kB gz; replay at 60 fps
- **Docs:** this roadmap's checkboxes are updated in the same PR that ships the work
