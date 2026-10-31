# Resources

External data sources, references and inspiration for GridStory, and how each one is (or could be) used. Mostly picked from [awesome-f1](https://github.com/subinium/awesome-f1). Licences, activity and links were checked on 2026-10-17 (BoardF1 from that list is gone; f1-dash moved to f1-dash.com).

**Rules for using anything here:**
- Check the licence before copying code or data. "None" means all rights reserved: look and learn, don't copy.
- Credit data sources in the README and the app.
- Never re-host F1's video, audio or images; link to or play them from F1's own servers.

Status legend: ✅ in use · 🎯 planned (roadmap milestone) · 💡 idea / reference only

---

## Data sources

| Resource | Licence | Status | What it gives GridStory |
|---|---|---|---|
| [FastF1](https://github.com/theOehrly/Fast-F1) · [docs](https://docs.fastf1.dev/) | MIT | ✅ | Primary source: timing, telemetry, weather, race control, circuit info. Locked out of F1's archive since ~15 Oct 2026 ([#978](https://github.com/theOehrly/Fast-F1/issues/978)), so only cached sessions load through it |
| [TracingInsights Archive](https://github.com/TracingInsights-Archive) · [data hub](https://tracinginsights.com/data/) · [HuggingFace mirror](https://huggingface.co/datasets/tracinginsights/RaceData) | Apache-2.0 | ✅ | **Fallback when FastF1 has no timing data** (`apps/api/app/services/tracinginsights.py`): every lap's telemetry (incl. x/y/z, g-forces, gap to car ahead), lap times, weather, race control, corners and team colours for 2018 to May 2026. Repos per season; the 2026 one stopped updating in May. Browser-fetchable (CORS), so the online demo could load any lap directly |
| [OpenF1](https://openf1.org/) · [GitHub](https://github.com/br-g/openf1) | custom (see repo) | 🎯 Plan B, 3.6 | Records F1's live feed, so it has 2023 onward **including current 2026 races** (verified 2026-10-17: Singapore car data, positions, laps, stints, race control, weather). `team_radio` lists radio clips for 3.6. Free for historical data |
| [Jolpica-F1](https://github.com/jolpica/jolpica-f1) · [API](https://api.jolpi.ca/ergast/f1/) | Apache-2.0 | ✅ (via FastF1) | Ergast-compatible results, standings, pit stops back to 1950. FastF1 already uses it for results, which is why results still load during the lockout. Phase 6 season view and standings |
| [F1DB](https://github.com/f1db/f1db) | CC-BY-4.0 (credit required) | 🎯 Phase 6 | All-time database (drivers, constructors, circuits and layouts, results, grids, fastest laps, pit stops) in CSV/JSON/SQLite. Driver profiles, history, "first win" facts |
| [fia-doc](https://github.com/harningle/fia-doc) | Apache-2.0 | 🎯 3.4 | Parses official FIA PDFs: classifications, lap times, **pit stop summaries with durations**, tyre compounds. Fixes the safety-car drive-through pit miscount, and gives an official source for Done-when checks |
| [FIA F1 Archives](https://api.fia.com/f1-archives) · [FIA decision documents](https://www.fia.com/documents/championships/fia-formula-one-world-championship-14/season/season-2026-2072) | Official | 🎯 3.4 | The documents fia-doc parses: lap analysis, pit stop summaries, race control, weather, steward decisions |
| [Pirelli F1 press area](https://press.pirelli.com/en/?h=1&t=formula+1) | Official site | 💡 1.4+ | Which compounds (C1–C5) were the soft/medium/hard at each race, tyre previews |
| [TUMFTM racetrack-database](https://github.com/TUMFTM/racetrack-database) | LGPL-3.0 | 🎯 5.3 | Centre lines, **track widths** and race lines for 20+ circuits: real-width asphalt in the 3D replay instead of a tube. Last updated 2021, so some layouts are old |
| [f1-circuits](https://github.com/bacinger/f1-circuits) | MIT | 💡 | GeoJSON layouts with real-world coordinates for 35+ circuits; circuit pages, "where is this track" maps |
| [formula1-datasets](https://github.com/toUpperCase78/formula1-datasets) | GPL-3.0 | 💡 | Season CSVs 2019–2026 and notebooks; handy for cross-checking |
| [f1api.dev](https://f1api.dev/) · [GitHub](https://github.com/rafacv23/f1-api) | MIT | 💡 | Another results/standings API, if Jolpica is ever down |

## Audio and video

| Resource | Status | Notes |
|---|---|---|
| F1 team radio (listed by OpenF1 `team_radio`) | 🎯 3.6 | MP3s on F1's servers still download despite the lockout (checked 2026-10-17). Play from F1's URL; don't copy |
| [undercut-f1](https://github.com/JustAman62/undercut-f1) (licence: none) | 💡 3.6 / Phase 4 | Live-timing TUI that **transcribes team radio**. The idea (speech-to-text on radio clips) would make radio searchable and give the AI engineer radio as context |
| F1 TV / [MultiViewer](https://multiviewer.app) | 💡 | Real onboard video is licensed to F1 TV (paid, DRM). GridStory never scrapes it; at most a "Watch on F1 TV" link. The virtual onboard (5.2) is the telemetry-built alternative |

## Inspiration (look and learn; no licence means no copying)

| Project | Licence | What to learn from it |
|---|---|---|
| [F1 Race Replay](https://github.com/IAmTomShaw/f1-race-replay) | none | Closest to the 3D replay (Phase 5): race-state visualisation, track rendering, playback UX |
| [F1ReplayTiming](https://github.com/adn8naiagent/F1ReplayTiming) | none | Replay synced with timing overlays, telemetry charts and the track map |
| [Armchair Strategist](https://github.com/Casper-Guo/Armchair-Strategist) | none | Strategy visuals: pit windows, pace comparison, race narrative (Phase 3) |
| [f1-dash](https://github.com/slowlydev/f1-dash) · [live](https://f1-dash.com) | AGPL-3.0 (copying would force GridStory to AGPL) | Clean live-timing dashboard UI: leaderboard, tyres, gaps, mini-sectors |
| [f1-live-data](https://github.com/f1stuff/f1-live-data) | MIT | FastF1 live timing into Grafana; a reference for a future live mode |
| [TUMFTM global_racetrajectory_optimization](https://github.com/TUMFTM/global_racetrajectory_optimization) · [race-simulation](https://github.com/TUMFTM/race-simulation) | LGPL-3.0 · LGPL-3.0 | Racing-line and race/pit-strategy simulation research, for the parking-lot "what-if" simulator |
| [fastest-lap](https://github.com/juanmanzanero/fastest-lap) | MIT | Optimal-lap vehicle dynamics; deep background for lap analysis |
| [F1 Manager 2024](https://store.steampowered.com/app/2287220/F1_Manager_2024/) | commercial game | The look and feel the 3D replay (Phase 5) is inspired by; no assets taken |

## Products in the same space (know the competition)

| Product | What it does | Where GridStory should differ |
|---|---|---|
| [Formula Live Pulse](https://www.f1livepulse.com/) | Live timing, telemetry charts, 3D track map, AI assistant, team radio | Closest overall. GridStory's edge: explaining *why* time was won or lost (Phase 2 findings, Phase 4 engineer) |
| [F1 Tempo](https://www.f1-tempo.com/) | Lap time and telemetry comparison | Lap comparison with auto-generated findings |
| [F1 Cosmos](https://f1cosmos.com/) · [F1 The Data](https://f1thedata.com/) · [F1 DataStop](https://f1datastop.com/) · [F1pace](https://f1pace.com/) · [Formula-Timer](https://formula-timer.com/) | Dashboards and analytics | Engineer-style explanations, not more charts |
| [TracingInsights](https://tracinginsights.com/) | Interactive lap and telemetry charts (also our data fallback) | Same data, different job: GridStory explains, they chart |

## Learning

- [Wrangling F1 Data With Python](https://f1datajunkie.github.io/wranglingf1datawithpython/index.html) and [F1 Data Junkie](http://www.f1datajunkie.com/): FastF1 workflows and analysis ideas
- [Towards Formula 1 Analysis](https://medium.com/towards-formula-1-analysis): FastF1 tutorials (telemetry, strategy, mini-sectors)
- [f1metrics](https://f1metrics.wordpress.com/): statistical driver ratings, useful for Phase 6 driver profiles
- [Chain Bear](https://www.youtube.com/@chainbear), [Driver61](https://www.youtube.com/@Driver61), [Kyle Engineers](https://www.youtube.com/@KyleEngineers): clear explanations of the engineering GridStory's findings should echo
- [How to Win a Grand Prix](https://www.quercusbooks.co.uk/titles/bernie-collins/how-to-win-a-grand-prix/9781529437591/) (Bernie Collins): how a strategist actually thinks, for the AI engineer's voice

## Source list

- [awesome-f1](https://github.com/subinium/awesome-f1): the curated list these came from. Re-check it when starting a new phase
