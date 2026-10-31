"""Fallback data source: the TracingInsights telemetry archive.

https://github.com/TracingInsights-Archive (Apache-2.0, by TracingInsights). One repo per
season holding, for every session, lap times and per-lap telemetry for every driver,
captured from F1's feed before its timing archive started requiring an F1 TV login
(theOehrly/Fast-F1#978). Pitwall falls back to it when FastF1 has no timing data.

Layout: {year}/{EventName}/{session name}/
    drivers.json  corners.json  rcm.json  weather.json
    {DRV}/laptimes.json  {DRV}/{lap}_tel.json
Folder names match FastF1's EventName and Session.name. Values are column lists, with the
string "None" for missing values. Files are cached on disk after the first download.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

import httpx

from app.core.config import get_settings
from app.models.f1 import (
    CircuitInfo,
    Corner,
    LapData,
    RaceControlMessage,
    TelemetryDataset,
    WeatherData,
)

log = logging.getLogger(__name__)

BASE_URL = "https://raw.githubusercontent.com/TracingInsights-Archive/{year}/main/"
CACHE_DIR = Path(get_settings().fastf1_cache_dir) / "tracinginsights"


def _clean(value):
    """The archive writes missing values as the string "None"."""
    return None if value == "None" else value


def _fetch(year: int, event: str, session: str, path: str) -> Optional[dict]:
    """One archive file as JSON, from the disk cache or GitHub; None if it doesn't exist."""
    rel = Path(str(year), event, session, path)
    cached = CACHE_DIR / rel
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))

    url = BASE_URL.format(year=year) + quote(rel.as_posix().split("/", 1)[1])
    try:
        r = httpx.get(url, timeout=30)
    except httpx.HTTPError as e:
        log.warning("TracingInsights unreachable for %s: %s", url, e)
        return None
    if r.status_code != 200:
        return None  # not archived (e.g. 2026 after May): the caller reports no data
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(r.text, encoding="utf-8")
    return r.json()


def _columns(data: dict) -> List[dict]:
    """Column lists → one dict per row, with "None" strings cleaned."""
    keys = list(data)
    if not keys:
        return []
    return [{k: _clean(data[k][i]) for k in keys} for i in range(len(data[keys[0]]))]


def drivers(year: int, event: str, session: str) -> Optional[List[dict]]:
    data = _fetch(year, event, session, "drivers.json")
    return data["drivers"] if data else None


def team_colors(year: int, event: str, session: str) -> Dict[str, str]:
    """Driver abbreviation → "#RRGGBB"; fills the gap when results come from Jolpica/Ergast."""
    return {d["driver"]: f"#{d['tc']}" for d in drivers(year, event, session) or [] if d.get("tc")}


def _laptimes(year: int, event: str, session: str, drv: str) -> List[dict]:
    data = _fetch(year, event, session, f"{drv}/laptimes.json")
    return _columns(data) if data else []


def laps(year: int, event: str, session: str) -> Optional[List[LapData]]:
    entries = drivers(year, event, session)
    if entries is None:
        return None
    abbrs = [d["driver"] for d in entries]
    # ponytail: 20 small downloads on first use, in parallel; disk-cached afterwards.
    with ThreadPoolExecutor(8) as pool:
        per_driver = list(pool.map(lambda d: _laptimes(year, event, session, d), abbrs))

    result = []
    for rows in per_driver:
        for r in rows:
            result.append(LapData(
                lap_number=int(r["lap"]),
                driver=r["drv"],
                lap_time=r["time"],
                sector1_time=r["s1"],
                sector2_time=r["s2"],
                sector3_time=r["s3"],
                compound=r["compound"] or "",
                tyre_life=r["life"] or 0.0,
                position=r["pos"] or 0.0,
                is_personal_best=bool(r["pb"]),
                # FastF1's accuracy flag isn't archived; a timed lap without pit stops is close.
                is_accurate=r["time"] is not None and r["pin"] is None and r["pout"] is None,
                stint=int(r["stint"] or 0),
                speed_trap=r["vst"],
                pit_out_time=r["pout"],
                pit_in_time=r["pin"],
            ))
    return result


def _lap_number(year: int, event: str, session: str, drv: str, lap: int) -> Optional[int]:
    """lap 0 → the driver's fastest timed lap; otherwise the lap itself if it exists."""
    rows = _laptimes(year, event, session, drv)
    if lap:
        return lap if any(r["lap"] == lap for r in rows) else None
    timed = [r for r in rows if r["time"] is not None]
    return int(min(timed, key=lambda r: r["time"])["lap"]) if timed else None


def telemetry(
    year: int, event: str, session: str, drv: str, lap: int
) -> Optional[TelemetryDataset]:
    number = _lap_number(year, event, session, drv, lap)
    if number is None:
        return None
    data = _fetch(year, event, session, f"{drv}/{number}_tel.json")
    if not data:
        return None
    t = data["tel"]

    def col(name, cast=float):
        return [cast(_clean(v) or 0) for v in t.get(name, [])]

    return TelemetryDataset(
        distance=col("distance"), time=col("time"), speed=col("speed"),
        throttle=col("throttle"), brake=col("brake", lambda v: int(bool(v))),
        gear=col("gear", int), rpm=col("rpm"), drs=col("drs", int),
        x=col("x"), y=col("y"),
    )


def weather(year: int, event: str, session: str) -> Optional[List[WeatherData]]:
    data = _fetch(year, event, session, "weather.json")
    if not data:
        return None
    return [
        WeatherData(
            time=r["wT"] or 0.0, air_temp=r["wAT"] or 0.0, track_temp=r["wTT"] or 0.0,
            humidity=r["wH"] or 0.0, pressure=r["wP"] or 0.0, rainfall=bool(r["wR"]),
            wind_speed=r["wWS"] or 0.0, wind_direction=r["wWD"] or 0.0,
        )
        for r in _columns(data)
    ]


def race_control(
    year: int, event: str, session: str, session_start: datetime
) -> Optional[List[RaceControlMessage]]:
    data = _fetch(year, event, session, "rcm.json")
    if not data:
        return None
    result = []
    for r in _columns(data):
        # ISO wall-clock (UTC), nanosecond precision; seconds are enough here.
        sent = datetime.fromisoformat(r["time"][:19])
        result.append(RaceControlMessage(
            time=(sent - session_start).total_seconds(),
            lap=int(r["lap"]) if r["lap"] is not None else None,
            category=r["cat"] or "",
            message=r["msg"] or "",
            flag=r["flag"],
            scope=r["scope"],
            sector=int(r["sector"]) if r["sector"] is not None else None,
            driver_number=r["dNum"],
        ))
    return result


def circuit(year: int, event: str, session: str) -> Optional[CircuitInfo]:
    data = _fetch(year, event, session, "corners.json")
    if not data:
        return None
    rotation = data.pop("Rotation", 0.0)
    corners = [
        Corner(number=int(r["CornerNumber"]), x=r["X"], y=r["Y"], angle=r["Angle"],
               letter=r.get("Letter") or None, distance=r["Distance"])
        for r in _columns(data)
    ]
    return CircuitInfo(corners=corners, rotation=rotation)
