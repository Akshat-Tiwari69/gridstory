"""FastAPI routes for GridStory.

Errors are mapped centrally in app.main: NotFoundError → 404, anything unexpected → 500.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.analysis.compare import ComparisonError
from app.models.f1 import (
    CircuitInfo,
    LapComparison,
    LapData,
    MultiDriverTelemetry,
    RaceControlMessage,
    Season,
    SessionResults,
    TelemetryDataset,
    TrackPoint,
    WeatherData,
)
from app.services.f1_data import F1DataService

router = APIRouter(prefix="/api/v1", tags=["f1_data"])
SESSION = "/sessions/{year}/{event}/{session_type}"


def get_f1_service():
    return F1DataService()


Service = Depends(get_f1_service)


@router.get("/seasons", response_model=List[Season])
def get_seasons(
    year: Optional[int] = Query(default=None, description="Season year; default: current"),
    service: F1DataService = Service,
):
    return service.get_seasons(year or date.today().year)


@router.get(SESSION + "/laps", response_model=List[LapData])
def get_laps(year: int, event: str, session_type: str, service: F1DataService = Service):
    return service.get_laps(year, event, session_type)


@router.get(SESSION + "/telemetry/compare", response_model=MultiDriverTelemetry)
def get_telemetry_compare(
    year: int,
    event: str,
    session_type: str,
    drivers: str = Query(..., description="Comma-separated driver abbreviations, e.g. VER,HAM"),
    lap: int = Query(default=0, ge=0, description="Lap number; 0 = each driver's fastest lap"),
    service: F1DataService = Service,
):
    """Fetch telemetry for multiple drivers in a single session load."""
    driver_list = [d.strip().upper() for d in drivers.split(',') if d.strip()]
    if not driver_list:
        raise HTTPException(status_code=422, detail="Provide at least one driver abbreviation")
    return service.get_multi_telemetry(year, event, session_type, driver_list, lap)


@router.get(SESSION + "/compare", response_model=LapComparison)
def get_lap_comparison(
    year: int,
    event: str,
    session_type: str,
    driver_a: str = Query(..., min_length=2, max_length=3, description="Driver A, e.g. VER"),
    lap_a: int = Query(default=0, ge=0, description="Lap number for A; 0 = A's fastest lap"),
    driver_b: str = Query(..., min_length=2, max_length=3, description="Driver B, e.g. LEC"),
    lap_b: int = Query(default=0, ge=0, description="Lap number for B; 0 = B's fastest lap"),
    service: F1DataService = Service,
):
    """Two independent laps compared on distance. delta = time_B - time_A (positive: B behind).

    Unlike /telemetry/compare the laps are chosen per side, so one driver's lap 12 can be
    compared with the same driver's lap 16.
    """
    try:
        return service.compare_laps(
            year, event, session_type,
            driver_a.strip().upper(), lap_a, driver_b.strip().upper(), lap_b,
        )
    except ComparisonError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get(SESSION + "/telemetry/{driver}/{lap_number}", response_model=TelemetryDataset)
def get_telemetry(
    year: int,
    event: str,
    session_type: str,
    driver: str,
    lap_number: int,
    service: F1DataService = Service,
):
    """Column-oriented telemetry for one driver and lap. Use lap_number=0 for the fastest lap."""
    return service.get_telemetry(year, event, session_type, driver.upper(), lap_number)


@router.get(SESSION + "/weather", response_model=List[WeatherData])
def get_weather(year: int, event: str, session_type: str, service: F1DataService = Service):
    return service.get_weather(year, event, session_type)


@router.get(SESSION + "/race-control", response_model=List[RaceControlMessage])
def get_race_control(year: int, event: str, session_type: str, service: F1DataService = Service):
    return service.get_race_control(year, event, session_type)


@router.get(SESSION + "/results", response_model=SessionResults)
def get_results(year: int, event: str, session_type: str, service: F1DataService = Service):
    return service.get_results(year, event, session_type)


@router.get(SESSION + "/circuit", response_model=CircuitInfo)
def get_circuit_info(year: int, event: str, session_type: str, service: F1DataService = Service):
    return service.get_circuit_info(year, event, session_type)


@router.get(SESSION + "/track-outline", response_model=List[TrackPoint])
def get_track_outline(year: int, event: str, session_type: str, service: F1DataService = Service):
    data = service.get_track_outline(year, event, session_type)
    if not data:
        raise HTTPException(status_code=404, detail="Track outline not available for this session")
    return data
