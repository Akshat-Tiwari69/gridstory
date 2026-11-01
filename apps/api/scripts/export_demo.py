"""Export API responses for a few sessions as static JSON for the online demo.

The demo (GitHub Pages) has no API, so it serves a snapshot of sessions already in the
local FastF1 cache. Cached sessions are also all FastF1 can load right now: F1's timing
archive has required an F1 TV login since Oct 2026 (theOehrly/Fast-F1#978). The web app
reads these files when built with VITE_STATIC_DATA=true (see apps/web/src/services/api.ts).

Usage (from apps/api):  .venv/Scripts/python -m scripts.export_demo <output dir>
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

# (year, event name, session) — must already be in app/f1_cache to export offline.
DEMO_SESSIONS = [
    (2024, "Bahrain Grand Prix", "Q"),
    (2024, "Bahrain Grand Prix", "R"),
    (2024, "Saudi Arabian Grand Prix", "R"),
    (2025, "Australian Grand Prix", "R"),
]
# Comparisons are Python-computed (analysis/compare.py) fastest-lap pairs: every ordered pair of
# the quickest drivers plus every teammate pair, so the demo's "fastest" and "teammates"
# shortcuts always resolve. ~100 kB each, listed in compare/index.json.
COMPARE_TOP_DRIVERS = 5
SESSION_FILES = ["results", "laps", "weather", "race-control", "track-outline", "circuit"]

client = TestClient(app)


def slug(name: str) -> str:
    """Must match slug() in apps/web/src/services/api.ts."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def fetch(path: str):
    r = client.get("/api/v1" + path)
    r.raise_for_status()
    return r.json()


def write(out: Path, rel: str, data) -> None:
    path = out / f"{rel}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


def comparison_pairs(laps: list[dict], results: dict) -> list[tuple[str, str]]:
    best: dict[str, float] = {}
    for lap in laps:
        if lap["lap_time"] is not None:
            best[lap["driver"]] = min(best.get(lap["driver"], float("inf")), lap["lap_time"])
    fastest = sorted(best, key=best.__getitem__)[:COMPARE_TOP_DRIVERS]
    pairs = {(a, b) for a in fastest for b in fastest if a != b}
    teams = defaultdict(list)
    for d in results["drivers"]:
        if d["driver"]["abbreviation"] in best:
            teams[d["driver"]["team"]].append(d["driver"]["abbreviation"])
    for members in teams.values():
        pairs |= {(a, b) for a in members for b in members if a != b}
    # Fastest driver first, so the manifest order doubles as the "fastest" shortcut.
    return sorted(pairs, key=lambda p: (best[p[0]], best[p[1]]))


def main(out: Path) -> None:
    wanted = defaultdict(set)  # year -> {(event, session type)}
    for year, event, stype in DEMO_SESSIONS:
        wanted[year].add((event, stype))
        base = f"/sessions/{year}/{event}/{stype}"
        dest = f"sessions/{year}/{slug(event)}/{stype}"
        for name in SESSION_FILES:
            write(out, f"{dest}/{name}", fetch(f"{base}/{name}"))

        # Fastest lap per driver only; every lap of every driver would be ~60 MB a race.
        drivers = [d["driver"]["abbreviation"] for d in fetch(f"{base}/results")["drivers"]]
        for drv in drivers:
            r = client.get(f"/api/v1{base}/telemetry/{drv}/0")
            if r.status_code == 200:  # drivers without a timed lap have nothing to show
                write(out, f"{dest}/telemetry/{drv}", r.json())
        pairs = []
        for a, b in comparison_pairs(fetch(f"{base}/laps"), fetch(f"{base}/results")):
            query = {"driver_a": a, "lap_a": 0, "driver_b": b, "lap_b": 0}
            r = client.get(f"/api/v1{base}/compare", params=query)
            if r.status_code == 200:
                write(out, f"{dest}/compare/{a}-{b}", r.json())
                pairs.append([a, b])
        write(out, f"{dest}/compare/index", {"pairs": pairs})
        print(f"exported {year} {event} {stype} ({len(drivers)} drivers, {len(pairs)} comparisons)")

    # Seasons trimmed to the exported sessions, so the selector only offers what exists.
    for year, pairs in wanted.items():
        seasons = fetch(f"/seasons?year={year}")
        for season in seasons:
            season["events"] = [
                {**ev, "sessions": [s for s in ev["sessions"] if (ev["name"], s["type"]) in pairs]}
                for ev in season["events"]
                if any(ev["name"] == e for e, _ in pairs)
            ]
        write(out, f"seasons/{year}", seasons)
    write(out, "years", sorted(wanted, reverse=True))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
