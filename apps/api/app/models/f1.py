"""Pydantic schemas for F1 data."""

from typing import Dict, List, Optional

from pydantic import BaseModel


class Driver(BaseModel):
    """Driver information."""
    abbreviation: str
    number: str
    full_name: str
    team: str
    team_color: str
    headshot_url: Optional[str] = None


class DriverResult(BaseModel):
    """Result for a specific driver in a session."""
    position: Optional[float] = None
    grid_position: Optional[float] = None
    driver: Driver
    status: str
    points: float
    q1: Optional[float] = None  # seconds
    q2: Optional[float] = None
    q3: Optional[float] = None
    gap: Optional[str] = None  # "Leader", "+1.234s", "Pole", "DNF", "N/A"


class SessionResults(BaseModel):
    """Overall results for a session."""
    drivers: List[DriverResult]


class SessionInfo(BaseModel):
    """Information about a specific session within an event."""
    type: str  # 'FP1', 'FP2', 'FP3', 'Q', 'S', 'SQ', 'R'
    name: str
    date: str


class Event(BaseModel):
    """Information about a race weekend (event)."""
    round: int
    name: str
    country: str
    location: str
    date: str
    sessions: List[SessionInfo]


class Season(BaseModel):
    """Information about a full F1 season."""
    year: int
    events: List[Event]


class LapData(BaseModel):
    """Data for a single lap by a specific driver."""
    lap_number: int
    driver: str
    lap_time: Optional[float] = None  # in seconds
    sector1_time: Optional[float] = None
    sector2_time: Optional[float] = None
    sector3_time: Optional[float] = None
    compound: str
    tyre_life: float
    position: float
    is_personal_best: bool
    is_accurate: bool
    stint: int
    speed_trap: Optional[float] = None
    pit_out_time: Optional[float] = None  # non-null = car left pit on this lap (outlap)
    pit_in_time: Optional[float] = None   # non-null = car entered pit on this lap (inlap)


class TelemetryPoint(BaseModel):
    """A single point of telemetry data."""
    distance: float
    time: float  # seconds from session start or lap start
    speed: float
    throttle: float
    brake: bool
    gear: int
    rpm: float
    drs: int
    x: float
    y: float
    z: float


class TelemetryDataset(BaseModel):
    """Column-oriented telemetry payload — one array per channel."""
    distance: List[float]
    time: List[float]
    speed: List[float]
    throttle: List[float]
    brake: List[int]
    gear: List[int]
    rpm: List[float]
    drs: List[int]
    x: List[float]
    y: List[float]


class MultiDriverTelemetry(BaseModel):
    """Telemetry for multiple drivers in a single response."""
    drivers: Dict[str, TelemetryDataset]


class WeatherData(BaseModel):
    """Weather data point."""
    time: float  # seconds
    air_temp: float
    track_temp: float
    humidity: float
    pressure: float
    rainfall: bool
    wind_speed: float
    wind_direction: float


class RaceControlMessage(BaseModel):
    """A message from race control."""
    time: float  # seconds
    lap: Optional[int] = None
    category: str
    message: str
    flag: Optional[str] = None
    scope: Optional[str] = None
    sector: Optional[int] = None
    driver_number: Optional[str] = None


class Corner(BaseModel):
    """Information about a track corner."""
    number: int
    x: float
    y: float
    angle: float
    letter: Optional[str] = None
    distance: Optional[float] = None  # metres along the fastest lap; for chart corner markers


class CircuitInfo(BaseModel):
    """Information about the circuit."""
    corners: List[Corner]
    rotation: float


class TrackPoint(BaseModel):
    """A single XY coordinate point of the track outline."""
    x: float
    y: float


# --- Lap comparison -------------------------------------------------------------------------


class LapRef(BaseModel):
    """A resolved lap: which driver's lap was actually compared, and its official time."""
    driver: str
    lap_number: int
    requested_lap: int  # what the caller asked for; 0 = fastest timed lap
    lap_time: float  # official seconds
    compound: str = ""
    tyre_life: float = 0.0
    is_accurate: bool = True
    is_out_lap: bool = False
    is_in_lap: bool = False
    label: str  # "VER L16"


class ComparisonWarning(BaseModel):
    code: str
    message: str
    lap: Optional[str] = None  # "A", "B" or None for both/neither


class ComparisonChannels(BaseModel):
    """Both laps on one shared distance grid. A channel is None when that lap lacks it."""
    distance: List[float]  # metres from the start line, on the common length (see alignment)
    time_a: List[float]  # seconds since lap start
    time_b: List[float]
    speed_a: List[float]
    speed_b: List[float]
    throttle_a: Optional[List[float]] = None
    throttle_b: Optional[List[float]] = None
    brake_a: Optional[List[int]] = None
    brake_b: Optional[List[int]] = None
    gear_a: Optional[List[int]] = None
    gear_b: Optional[List[int]] = None


class ComparisonAlignment(BaseModel):
    grid_step_m: float
    common_length_m: float
    length_a_m: float  # integrated telemetry distance of each lap before alignment
    length_b_m: float
    scale_a: float  # factor applied to lap A's distance (1.0 = untouched)
    scale_b: float
    method: str  # "scaled_to_mean_length" or "truncated_to_common_coverage"
    resolution_a_m: float  # median native sample spacing
    resolution_b_m: float


class ComparisonFinish(BaseModel):
    """Delta at the finish line vs the official lap-time difference (B minus A)."""
    delta_s: Optional[float] = None  # None when coverage differs too much to reach a finish
    official_delta_s: float
    error_s: Optional[float] = None  # delta_s - official_delta_s
    within_tolerance: Optional[bool] = None
    tolerance_s: float


class CornerSide(BaseModel):
    entry_speed: Optional[float] = None
    min_speed: Optional[float] = None
    min_speed_distance: Optional[float] = None
    exit_speed: Optional[float] = None
    brake_on_m: Optional[float] = None  # None: no brake application detected / no brake channel
    throttle_on_m: Optional[float] = None


class CornerMetrics(BaseModel):
    a: CornerSide
    b: CornerSide
    brake_diff_m: Optional[float] = None  # b - a; positive = B brakes later
    brake_diff_significant: bool = False  # False when under the native sample spacing
    throttle_diff_m: Optional[float] = None  # b - a; positive = B gets on the throttle later
    throttle_diff_significant: bool = False


class ComparisonSegment(BaseModel):
    id: str
    kind: str  # "corner" | "straight" | "distance"
    label: str
    corner_number: Optional[int] = None
    start_m: float
    end_m: float
    delta_start_s: float
    delta_end_s: float
    gain_a_s: float  # delta_end - delta_start; positive = lap A gained time on lap B here
    corner: Optional[CornerMetrics] = None


class ComparisonFinding(BaseModel):
    rank: int
    segment_id: str
    winner: str  # "A" or "B"
    gain_s: float  # always positive: time the winner gained in this segment
    text: str


class LapComparison(BaseModel):
    """Lap A vs lap B. delta = time_b - time_a at equal distance: positive = B is behind A."""
    lap_a: LapRef
    lap_b: LapRef
    alignment: ComparisonAlignment
    channels: ComparisonChannels
    delta_s: List[float]  # cumulative, same grid as channels.distance
    finish: ComparisonFinish
    segments: List[ComparisonSegment]
    findings: List[ComparisonFinding]
    warnings: List[ComparisonWarning]
