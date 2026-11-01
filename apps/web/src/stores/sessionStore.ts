import { create } from 'zustand';
import type { LapSelection } from '../types/f1';

interface SessionState {
  selectedYear: number;
  selectedEvent: string | null;
  selectedSessionType: string | null;
  selectedDrivers: string[];
  selectedLap: number; // 0 = best lap (fastest), >0 = specific lap number
  focusedDriver: string | null; // drives the team-themed dashboard; null = standard view
  compareA: LapSelection | null; // lap comparison sides, lap 0 = that driver's fastest
  compareB: LapSelection | null;

  setYear: (year: number) => void;
  setEvent: (event: string) => void;
  setSessionType: (type: string) => void;
  setSelectedDrivers: (drivers: string[]) => void;
  toggleDriver: (driver: string) => void;
  setSelectedLap: (lap: number) => void;
  focusDriver: (driver: string) => void;
  clearFocus: () => void;
  setCompare: (a: LapSelection | null, b: LapSelection | null) => void;
}

type UrlState = Pick<
  SessionState,
  'selectedYear' | 'selectedEvent' | 'selectedSessionType' | 'selectedDrivers' | 'selectedLap' | 'focusedDriver' | 'compareA' | 'compareB'
>;

// "VER" = VER's fastest lap, "VER:12" = lap 12. Anything else is ignored.
function parseSide(raw: string | null): LapSelection | null {
  const m = /^([A-Za-z]{2,3})(?::(\d+))?$/.exec(raw ?? '');
  return m ? { driver: m[1].toUpperCase(), lap: Number(m[2] ?? 0) } : null;
}
const formatSide = (s: LapSelection) => (s.lap ? `${s.driver}:${s.lap}` : s.driver);

// The URL is the source of truth on load, so any view can be reloaded or shared, e.g.
// /telemetry?year=2024&event=Bahrain+Grand+Prix&session=R&drivers=VER,LEC&lap=12
function readUrl(): UrlState {
  const q = new URLSearchParams(window.location.search);
  const lap = Number(q.get('lap'));
  const focus = q.get('focus');
  const drivers = (q.get('drivers') ?? '').split(',').filter(Boolean).slice(0, 3);
  return {
    selectedYear: Number(q.get('year')) || 2024,
    selectedEvent: q.get('event'),
    selectedSessionType: q.get('session'),
    selectedDrivers: drivers.length || !focus ? drivers : [focus],
    selectedLap: Number.isInteger(lap) && lap > 0 ? lap : 0,
    focusedDriver: focus,
    compareA: parseSide(q.get('a')),
    compareB: parseSide(q.get('b')),
  };
}

/** Query string for the current selection; the sidebar links carry it between pages. */
export function toQuery(s: UrlState): string {
  const q = new URLSearchParams({ year: String(s.selectedYear) });
  if (s.selectedEvent) q.set('event', s.selectedEvent);
  if (s.selectedSessionType) q.set('session', s.selectedSessionType);
  if (s.selectedDrivers.length) q.set('drivers', s.selectedDrivers.join(','));
  if (s.selectedLap) q.set('lap', String(s.selectedLap));
  if (s.focusedDriver) q.set('focus', s.focusedDriver);
  if (s.compareA) q.set('a', formatSide(s.compareA));
  if (s.compareB) q.set('b', formatSide(s.compareB));
  return q.toString().replace(/%2C/g, ','); // readable driver lists
}

export const useSessionStore = create<SessionState>((set) => ({
  ...readUrl(),

  setYear: (year) => set({
    selectedYear: year,
    selectedEvent: null,
    selectedSessionType: null,
    selectedDrivers: [],
    selectedLap: 0,
    focusedDriver: null,
    compareA: null,
    compareB: null,
  }),
  setEvent: (event) => set({
    selectedEvent: event,
    selectedSessionType: null,
    selectedDrivers: [],
    selectedLap: 0,
    focusedDriver: null,
    compareA: null,
    compareB: null,
  }),
  setSessionType: (type) => set({
    selectedSessionType: type,
    selectedDrivers: [],
    selectedLap: 0,
    focusedDriver: null,
    compareA: null,
    compareB: null,
  }),
  setSelectedDrivers: (drivers) => set({ selectedDrivers: drivers }),
  toggleDriver: (driver) => set((state) => {
    if (state.selectedDrivers.includes(driver)) {
      return { selectedDrivers: state.selectedDrivers.filter(d => d !== driver) };
    }
    // Max 3 drivers for comparison
    if (state.selectedDrivers.length >= 3) {
      return { selectedDrivers: [...state.selectedDrivers.slice(1), driver] };
    }
    return { selectedDrivers: [...state.selectedDrivers, driver] };
  }),
  setSelectedLap: (lap) => set({ selectedLap: lap }),
  // Focusing a driver replaces the dashboard with their team-themed view and
  // resets the telemetry comparison to that single driver.
  focusDriver: (driver) => set({ focusedDriver: driver, selectedDrivers: [driver] }),
  clearFocus: () => set({ focusedDriver: null }),
  setCompare: (compareA, compareB) => set({ compareA, compareB }),
}));

// Mirror the selection into the URL. replaceState (not router navigation) so every click
// doesn't add a history entry; router's own history.state is kept so back/forward still work.
useSessionStore.subscribe((s) => {
  const query = toQuery(s);
  if (query !== window.location.search.slice(1)) {
    window.history.replaceState(window.history.state, '', `${window.location.pathname}?${query}`);
  }
});
