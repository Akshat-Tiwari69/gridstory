export interface Season {
  year: number;
  events: Event[];
}

export interface Event {
  round: number;
  name: string;
  country: string;
  location: string;
  date: string;
  sessions: SessionInfo[];
}

export interface SessionInfo {
  type: 'FP1' | 'FP2' | 'FP3' | 'Q' | 'S' | 'SQ' | 'R' | string;
  date: string;
  name: string;
}

export interface Driver {
  abbreviation: string;
  number: string;
  fullName: string;
  team: string;
  teamColor: string;
  headshotUrl?: string;
}

export interface LapData {
  lapNumber: number;
  driver: string;
  lapTime: number | null;
  sector1Time: number | null;
  sector2Time: number | null;
  sector3Time: number | null;
  compound: string;
  tyreLife: number;
  position: number;
  isPersonalBest: boolean;
  isAccurate: boolean;
  stint: number;
  speedTrap: number | null;
  pitOutTime?: number | null;
  pitInTime?: number | null;
}

export interface TelemetryPoint {
  distance: number;
  time: number;
  speed: number;
  throttle: number;
  brake: boolean;
  gear: number;
  rpm: number;
  drs: number;
  x: number;
  y: number;
}

export interface TelemetryDataset {
  distance: number[];
  time: number[];
  speed: number[];
  throttle: number[];
  brake: number[];
  gear: number[];
  rpm: number[];
  drs: number[];
  x: number[];
  y: number[];
}

export interface MultiDriverTelemetry {
  drivers: Record<string, TelemetryDataset>;
}

export interface WeatherData {
  time: number;
  airTemp: number;
  trackTemp: number;
  humidity: number;
  pressure: number;
  rainfall: boolean;
  windSpeed: number;
  windDirection: number;
}

export interface RaceControlMessage {
  time: number;
  lap?: number;
  category: string;
  message: string;
  flag?: string;
  scope?: string;
  sector?: number;
  driverNumber?: string;
}

export interface Corner {
  distance?: number;
  number: number;
  x: number;
  y: number;
  angle: number;
  letter?: string;
}

export interface CircuitInfo {
  corners: Corner[];
  rotation: number;
}

export interface TrackPoint {
  x: number;
  y: number;
}

export interface SessionResults {
  drivers: DriverResult[];
}

export interface DriverResult {
  position: number | null;
  gridPosition: number | null;
  driver: Driver;
  status: string;
  points: number;
  q1?: number;
  q2?: number;
  q3?: number;
  gap?: string;
}

// --- Lap comparison (GET /compare, computed in apps/api/app/analysis/compare.py) ---

export interface LapRef {
  driver: string;
  lapNumber: number;
  requestedLap: number;
  lapTime: number;
  compound: string;
  tyreLife: number;
  isAccurate: boolean;
  isOutLap: boolean;
  isInLap: boolean;
  label: string;
}

export interface ComparisonWarning {
  code: string;
  message: string;
  lap?: 'A' | 'B' | null;
}

export interface ComparisonChannels {
  distance: number[];
  timeA: number[];
  timeB: number[];
  speedA: number[];
  speedB: number[];
  throttleA?: number[] | null;
  throttleB?: number[] | null;
  brakeA?: number[] | null;
  brakeB?: number[] | null;
  gearA?: number[] | null;
  gearB?: number[] | null;
}

export interface ComparisonAlignment {
  gridStepM: number;
  commonLengthM: number;
  lengthAM: number;
  lengthBM: number;
  scaleA: number;
  scaleB: number;
  method: string;
  resolutionAM: number;
  resolutionBM: number;
}

export interface ComparisonFinish {
  deltaS?: number | null;
  officialDeltaS: number;
  errorS?: number | null;
  withinTolerance?: boolean | null;
  toleranceS: number;
}

export interface CornerSide {
  entrySpeed?: number | null;
  minSpeed?: number | null;
  minSpeedDistance?: number | null;
  exitSpeed?: number | null;
  brakeOnM?: number | null;
  throttleOnM?: number | null;
}

export interface CornerMetrics {
  a: CornerSide;
  b: CornerSide;
  brakeDiffM?: number | null;
  brakeDiffSignificant: boolean;
  throttleDiffM?: number | null;
  throttleDiffSignificant: boolean;
}

export interface ComparisonSegment {
  id: string;
  kind: 'corner' | 'straight' | 'distance' | string;
  label: string;
  cornerNumber?: number | null;
  startM: number;
  endM: number;
  deltaStartS: number;
  deltaEndS: number;
  gainAS: number; // positive: lap A gained time on lap B in this segment
  corner?: CornerMetrics | null;
}

export interface ComparisonFinding {
  rank: number;
  segmentId: string;
  winner: 'A' | 'B';
  gainS: number;
  text: string;
}

export interface LapComparison {
  lapA: LapRef;
  lapB: LapRef;
  alignment: ComparisonAlignment;
  channels: ComparisonChannels;
  deltaS: number[]; // time_B - time_A: positive = B is behind
  finish: ComparisonFinish;
  segments: ComparisonSegment[];
  findings: ComparisonFinding[];
  warnings: ComparisonWarning[];
}

/** One side of a comparison; lap 0 = that driver's fastest timed lap. */
export interface LapSelection {
  driver: string;
  lap: number;
}

/** Demo only: the fastest-lap pairs that were exported (compare/index.json). */
export interface DemoCompareIndex {
  pairs: [string, string][];
}
