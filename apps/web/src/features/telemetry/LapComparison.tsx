import { useEffect, useMemo, useRef } from 'react';
import ReactECharts from 'echarts-for-react';
import { useSessionStore } from '../../stores/sessionStore';
import { useCursorStore } from '../../stores/cursorStore';
import { IS_DEMO } from '../../services/api';
import {
  nearestIndex, useCircuit, useDemoComparisons, useLapComparison, useLaps, useResults,
} from '../../hooks/useSessionQueries';
import { ErrorState, Skeleton } from '../../components/PanelState';
import { formatTime } from '../../utils/format';
import { ComparisonMap } from './ComparisonMap';
import { SIDE_COLORS } from './comparisonColors';
import type { LapComparison as Comparison, LapData, LapSelection } from '../../types/f1';
import '../../components/PanelState.css';
import './LapComparison.css';

const AXIS = { nameTextStyle: { color: '#9090a8' }, axisLabel: { color: '#9090a8' }, splitLine: { lineStyle: { color: '#1e1e30' } } };
const gain = (s: number) => `${s > 0 ? '+' : ''}${s.toFixed(3)}`;
const same = (a: LapSelection | null, b: LapSelection | null) => a?.driver === b?.driver && a?.lap === b?.lap;

function bestLaps(laps: LapData[] | undefined): [string, number][] {
  const best = new Map<string, number>();
  for (const l of laps ?? []) {
    if (l.lapTime != null) best.set(l.driver, Math.min(best.get(l.driver) ?? Infinity, l.lapTime));
  }
  return [...best].sort((a, b) => a[1] - b[1]);
}

function chartOption(c: Comparison, corners: { number: number; letter?: string; distance?: number }[]) {
  const d = c.channels.distance;
  const xy = (ys: (number | null)[]) => ys.map((y, i) => [d[i], y]);
  const rows = [
    { name: 'Speed km/h', a: c.channels.speedA, b: c.channels.speedB },
    { name: 'Gap s  ▲A ▼B', delta: c.deltaS },
    ...(c.channels.throttleA && c.channels.throttleB ? [{ name: 'Throttle %', a: c.channels.throttleA, b: c.channels.throttleB }] : []),
    ...(c.channels.brakeA && c.channels.brakeB ? [{ name: 'Brake', a: c.channels.brakeA, b: c.channels.brakeB, step: true }] : []),
  ];
  // Leaves room below the last row for the distance axis and the zoom slider.
  const heights = rows.length === 2 ? [50, 32] : rows.length === 3 ? [40, 26, 14] : [34, 22, 12, 8];
  let top = 3;
  const grids = rows.map((_, i) => {
    const g = { top: `${top}%`, height: `${heights[i]}%`, left: 56, right: 16 };
    top += heights[i] + 3;
    return g;
  });

  const cornerLines = (labels: boolean) => ({
    silent: true, symbol: 'none',
    lineStyle: { color: '#3a3a55', type: 'dashed', width: 1 },
    label: labels
      ? { show: true, position: 'end', color: '#9090a8', fontSize: 9, formatter: (p: { name: string }) => p.name }
      : { show: false },
    data: corners.filter((k) => k.distance != null).map((k) => ({ name: `T${k.number}${k.letter ?? ''}`, xAxis: k.distance })),
  });

  // Brake-on points from the API's corner metrics, drawn on the speed trace.
  const brakePoints = (side: 'a' | 'b') => c.segments.flatMap((s) => {
    const m = s.corner?.[side].brakeOnM;
    if (m == null) return [];
    const speed = (side === 'a' ? c.channels.speedA : c.channels.speedB)[nearestIndex(d, m)];
    return [{ value: [m, speed], name: s.label }];
  });

  const series: object[] = [];
  rows.forEach((r, i) => {
    const common = { xAxisIndex: i, yAxisIndex: i, showSymbol: false };
    if ('delta' in r && r.delta) {
      series.push({
        ...common, name: 'Gap', type: 'line', data: xy(r.delta), lineStyle: { width: 1.5, color: '#d8d8ea' }, itemStyle: { color: '#d8d8ea' },
        areaStyle: { opacity: 0.12, origin: 0, color: '#d8d8ea' },
      });
    } else if ('a' in r) {
      const step = 'step' in r ? 'end' : undefined;
      series.push(
        { ...common, name: `${c.lapA.label} ${r.name.split(' ')[0]}`, type: 'line', step, data: xy(r.a!), itemStyle: { color: SIDE_COLORS.a }, lineStyle: { width: 1.5, color: SIDE_COLORS.a } },
        { ...common, name: `${c.lapB.label} ${r.name.split(' ')[0]}`, type: 'line', step, data: xy(r.b!), itemStyle: { color: SIDE_COLORS.b }, lineStyle: { width: 1.5, color: SIDE_COLORS.b } },
      );
    }
  });
  // Corner guides once per row (on the first series of that row).
  let k = 0;
  rows.forEach((r, i) => {
    const s = series[k] as { markLine?: unknown };
    s.markLine = cornerLines(i === 0);
    k += 'delta' in r ? 1 : 2;
  });
  series.push(
    { name: `${c.lapA.label} brake on`, type: 'scatter', xAxisIndex: 0, yAxisIndex: 0, symbol: 'triangle', symbolSize: 10, itemStyle: { color: SIDE_COLORS.a, borderColor: '#0b0b14', borderWidth: 1 }, data: brakePoints('a'), z: 5 },
    { name: `${c.lapB.label} brake on`, type: 'scatter', xAxisIndex: 0, yAxisIndex: 0, symbol: 'triangle', symbolRotate: 180, symbolSize: 10, itemStyle: { color: SIDE_COLORS.b, borderColor: '#0b0b14', borderWidth: 1 }, data: brakePoints('b'), z: 5 },
  );

  const deltaMax = Math.max(0.05, ...c.deltaS.map(Math.abs));
  const axisIdx = rows.map((_, i) => i);
  return {
    animation: false,
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'line' }, backgroundColor: '#1c1c2e', borderColor: '#3a3a55', textStyle: { color: '#eaeaf0' },
      // One distance header; markers (scatter) and corner lines would only add noise.
      formatter: (ps: { axisValue: number; marker: string; seriesName: string; seriesType: string; value: number[]; axisIndex: number }[]) => {
        const lines = ps.filter((p) => p.seriesType === 'line').map((p) => {
          const v = p.value[1];
          return `${p.marker}${p.seriesName} <b>${p.seriesName === 'Gap' ? gain(v) + ' s' : Math.round(v)}</b>`;
        });
        return `${Math.round(ps[0]?.axisValue ?? 0).toLocaleString()} m<br/>${lines.join('<br/>')}`;
      },
    },
    grid: grids,
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    dataZoom: [
      { type: 'inside', xAxisIndex: axisIdx, filterMode: 'none' },
      { type: 'slider', xAxisIndex: axisIdx, filterMode: 'none', bottom: 4, height: 14, borderColor: '#2a2a3e', textStyle: { color: '#606078' } },
    ],
    xAxis: rows.map((_, i) => ({
      type: 'value', gridIndex: i, min: 0, max: c.alignment.commonLengthM, show: i === rows.length - 1,
      name: i === rows.length - 1 ? 'Distance (m)' : undefined, nameTextStyle: { color: '#606078' }, axisLabel: { color: '#606078' }, splitLine: { show: false },
    })),
    yAxis: rows.map((r, i) => ({
      type: 'value', gridIndex: i, name: r.name, nameGap: 6, ...AXIS,
      ...('delta' in r ? { min: -deltaMax, max: deltaMax, inverse: false } : {}),
      ...(r.name === 'Brake' ? { min: 0, max: 1, splitNumber: 1, axisLabel: { show: false } } : {}),
      ...(r.name === 'Throttle %' ? { min: 0, max: 100, splitNumber: 2 } : {}),
      ...(r.name === 'Speed km/h' ? { min: 0, max: 360 } : {}),
    })),
    series,
  };
}

function Picker({ label, color, value, drivers, laps, onChange, lapsDisabled }: {
  label: string; color: string; value: LapSelection | null; drivers: string[]; laps: LapData[];
  onChange: (v: LapSelection) => void; lapsDisabled: boolean;
}) {
  const timed = laps.filter((l) => l.driver === value?.driver && l.lapTime != null);
  const fastest = Math.min(...timed.map((l) => l.lapTime!));
  return (
    <div className="cmp-picker" style={{ borderColor: color }}>
      <span className="cmp-side" style={{ color }}>{label}</span>
      <select aria-label={`Driver ${label}`} value={value?.driver ?? ''} onChange={(e) => onChange({ driver: e.target.value, lap: 0 })}>
        <option value="" disabled>Driver</option>
        {(value && !drivers.includes(value.driver) ? [value.driver, ...drivers] : drivers).map((d) => <option key={d} value={d}>{d}</option>)}
      </select>
      <select aria-label={`Lap ${label}`} value={value?.lap ?? 0} disabled={!value || lapsDisabled}
        onChange={(e) => value && onChange({ driver: value.driver, lap: Number(e.target.value) })}>
        <option value={0}>Fastest{timed.length ? ` (${formatTime(fastest)})` : ''}</option>
        {timed.map((l) => <option key={l.lapNumber} value={l.lapNumber}>Lap {l.lapNumber} · {formatTime(l.lapTime)}</option>)}
      </select>
    </div>
  );
}

export function LapComparison() {
  const { selectedEvent, selectedSessionType, compareA, compareB, setCompare } = useSessionStore();
  const setCursor = useCursorStore((s) => s.setCursor);
  const { data: results } = useResults();
  const { data: laps } = useLaps();
  const { data: circuit } = useCircuit();
  const { data: demo, isLoading: demoLoading, error: demoError } = useDemoComparisons();
  const { data, isFetching, error } = useLapComparison();
  const chartRef = useRef<ReactECharts>(null);

  useEffect(() => () => setCursor(null), [setCursor]);

  const best = useMemo(() => bestLaps(laps), [laps]);
  const teamOf = useMemo(() => new Map((results?.drivers ?? []).map((r) => [r.driver.abbreviation, r.driver.team])), [results]);
  const pairs = IS_DEMO ? demo?.pairs ?? [] : null; // null = every pair is available (API)
  const allDrivers = best.map(([d]) => d);
  const driversA = pairs ? [...new Set(pairs.map((p) => p[0]))] : allDrivers;
  const driversB = pairs
    ? [...new Set(pairs.filter((p) => p[0] === compareA?.driver).map((p) => p[1]))]
    : allDrivers;
  const supported = !pairs || !compareA || !compareB || pairs.some((p) => p[0] === compareA.driver && p[1] === compareB.driver);

  const pick = (a: LapSelection | null, b: LapSelection | null) => { if (!same(a, compareA) || !same(b, compareB)) setCompare(a, b); };
  const changeA = (a: LapSelection) => {
    // Demo: keep B only if that exact pair was exported, else fall back to A's first partner.
    if (pairs && !pairs.some((p) => p[0] === a.driver && p[1] === compareB?.driver)) {
      const first = pairs.find((p) => p[0] === a.driver);
      return pick(a, first ? { driver: first[1], lap: 0 } : null);
    }
    pick(a, compareB);
  };

  const fastestVs = () => {
    const [a, b] = pairs ? [pairs[0]?.[0], pairs[0]?.[1]] : [best[0]?.[0], best[1]?.[0]];
    if (a && b) pick({ driver: a, lap: 0 }, { driver: b, lap: 0 });
  };
  const teammateOf = (d: string, allowed: string[]) => allowed.find((o) => o !== d && teamOf.get(o) === teamOf.get(d));
  const teammates = () => {
    // A defaults to the fastest driver who has a teammate available.
    const candidates = compareA ? [compareA.driver, ...allDrivers] : allDrivers;
    for (const a of candidates) {
      const b = teammateOf(a, pairs ? pairs.filter((p) => p[0] === a).map((p) => p[1]) : allDrivers);
      if (b) return pick({ driver: a, lap: 0 }, { driver: b, lap: 0 });
    }
  };

  const option = useMemo(
    () => (data ? chartOption(data, circuit?.corners ?? []) : null),
    [data, circuit],
  );

  // Map hover → chart crosshair.
  useEffect(() => {
    const distance = data?.channels.distance;
    return useCursorStore.subscribe(({ cursor }, prev) => {
      const chart = chartRef.current?.getEchartsInstance();
      if (!chart || !distance || cursor === prev.cursor) return;
      if (!cursor) chart.dispatchAction({ type: 'hideTip' });
      else if (cursor.source === 'map') chart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: nearestIndex(distance, cursor.distance) });
    });
  }, [data]);

  const swap = () => compareA && compareB && setCompare(compareB, compareA);
  const ready = !!selectedEvent && !!selectedSessionType;

  return (
    <div className="cmp-wrapper">
      <div className="cmp-toolbar">
        <span className="cmp-title">Lap comparison</span>
        <Picker label="A" color={SIDE_COLORS.a} value={compareA} drivers={driversA} laps={laps ?? []} lapsDisabled={IS_DEMO}
          onChange={changeA} />
        <button className="cmp-btn" onClick={swap} disabled={!compareA || !compareB || (IS_DEMO && !pairs?.some((p) => p[0] === compareB?.driver && p[1] === compareA?.driver))}
          title="Swap A and B">⇄</button>
        <Picker label="B" color={SIDE_COLORS.b} value={compareB} drivers={driversB} laps={laps ?? []} lapsDisabled={IS_DEMO}
          onChange={(b) => pick(compareA ?? null, b)} />
        <span className="cmp-shortcuts">
          <button className="cmp-btn" onClick={fastestVs} disabled={!ready || (IS_DEMO ? !pairs?.length : best.length < 2)}>Fastest vs fastest</button>
          <button className="cmp-btn" onClick={teammates} disabled={!ready || !laps}>Teammates</button>
        </span>
      </div>
      {IS_DEMO && <div className="cmp-note">Online demo: fastest laps of the quickest drivers and teammates only. Run GridStory locally to compare any two laps.</div>}

      {!ready && <div className="cmp-empty">Pick a year, event and session above.</div>}
      {ready && IS_DEMO && demoLoading && <Skeleton rows={4} />}
      {ready && IS_DEMO && demoError && <ErrorState error={demoError} />}
      {ready && !(compareA && compareB) && !demoLoading && (
        <div className="cmp-empty">Choose lap A and lap B, or use a shortcut.</div>
      )}
      {ready && compareA && compareB && !supported && (
        <div className="panel-state panel-state--error" role="alert">
          {compareA.driver} vs {compareB.driver} is not included in the online demo. Pick another pair.
        </div>
      )}
      {ready && compareA && compareB && supported && isFetching && !data && <Skeleton rows={12} />}
      {ready && compareA && compareB && supported && error && <ErrorState error={error} />}

      {data && supported && !error && (
        <div className="cmp-body" aria-busy={isFetching}>
          <Summary c={data} />
          <div className="cmp-main">
            <div className="cmp-chart">
              <ReactECharts
                ref={chartRef}
                option={option!}
                notMerge
                style={{ height: '100%', width: '100%' }}
                theme="dark"
                opts={{ renderer: 'canvas' }}
                onEvents={{
                  updateAxisPointer: (e: { axesInfo?: { value: number }[] }) => {
                    const v = e.axesInfo?.[0]?.value;
                    if (typeof v === 'number') setCursor({ distance: v, source: 'chart' });
                  },
                  globalout: () => setCursor(null),
                }}
              />
            </div>
            <ComparisonMap comparison={data} />
          </div>
          <Findings c={data} />
          <CornerTable c={data} />
          <Caveats c={data} />
        </div>
      )}
    </div>
  );
}

function Summary({ c }: { c: Comparison }) {
  const f = c.finish;
  return (
    <div className="cmp-summary">
      {[['a', c.lapA], ['b', c.lapB]].map(([k, l]) => {
        const lap = l as Comparison['lapA'];
        return (
          <span key={k as string} className="cmp-lap" style={{ color: SIDE_COLORS[k as 'a' | 'b'] }}>
            {lap.label} <b>{formatTime(lap.lapTime)}</b>{lap.compound ? ` · ${lap.compound}` : ''}
          </span>
        );
      })}
      <span className="cmp-finish">
        {f.deltaS == null
          ? 'Telemetry does not reach the finish line, so no finish gap is claimed.'
          : <>B {f.deltaS >= 0 ? 'behind' : 'ahead of'} A by <b>{Math.abs(f.deltaS).toFixed(3)} s</b> (official {Math.abs(f.officialDeltaS).toFixed(3)} s)</>}
      </span>
    </div>
  );
}

function Findings({ c }: { c: Comparison }) {
  if (!c.findings.length) {
    return <section className="cmp-section"><h3>Findings</h3><p className="cmp-muted">No segment differs by more than the sampling resolution, so there is nothing reliable to report.</p></section>;
  }
  return (
    <section className="cmp-section">
      <h3>Findings</h3>
      <ol className="cmp-findings">
        {c.findings.map((f) => (
          <li key={f.rank}><span className="cmp-dot" style={{ background: SIDE_COLORS[f.winner === 'A' ? 'a' : 'b'] }} />{f.text}</li>
        ))}
      </ol>
    </section>
  );
}

function CornerTable({ c }: { c: Comparison }) {
  const setCursor = useCursorStore((s) => s.setCursor);
  const spd = (v?: number | null) => (v == null ? '—' : Math.round(v));
  const diff = (v: number | null | undefined, sig: boolean) => (v == null || !sig ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(0)} m`);
  return (
    <section className="cmp-section">
      <h3>Corner by corner</h3>
      <table className="cmp-table">
        <thead>
          <tr><th>Segment</th><th>Gain</th><th>Min speed A / B</th><th>Exit A / B</th><th>Brake B vs A</th><th>Throttle B vs A</th></tr>
        </thead>
        <tbody>
          {c.segments.map((s) => {
            const k = s.corner;
            const win = Math.abs(s.gainAS) < 0.0005 ? null : s.gainAS > 0 ? 'a' : 'b';
            return (
              <tr key={s.id} className={s.kind === 'corner' ? '' : 'cmp-row-dim'}
                onMouseEnter={() => setCursor({ distance: (s.startM + s.endM) / 2, source: 'chart' })}
                onMouseLeave={() => setCursor(null)}>
                <td>{s.label}</td>
                <td style={{ color: win ? SIDE_COLORS[win] : undefined }}>{win ? `${win.toUpperCase()} ${gain(Math.abs(s.gainAS))}` : '0.000'}</td>
                <td>{k ? `${spd(k.a.minSpeed)} / ${spd(k.b.minSpeed)}` : '—'}</td>
                <td>{k ? `${spd(k.a.exitSpeed)} / ${spd(k.b.exitSpeed)}` : '—'}</td>
                <td>{k ? diff(k.brakeDiffM, k.brakeDiffSignificant) : '—'}</td>
                <td>{k ? diff(k.throttleDiffM, k.throttleDiffSignificant) : '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="cmp-muted">Gain = time that side won in the segment (A + / B +). Brake and throttle differences are shown only when larger than the telemetry sample spacing; positive = B later.</p>
    </section>
  );
}

function Caveats({ c }: { c: Comparison }) {
  const al = c.alignment;
  return (
    <section className="cmp-section">
      <h3>Data caveats</h3>
      <ul className="cmp-caveats">
        <li>Telemetry is sampled roughly every {al.resolutionAM.toFixed(0)} m (A) and {al.resolutionBM.toFixed(0)} m (B) and resampled to a {al.gridStepM.toFixed(0)} m grid. Differences smaller than that are not reported.</li>
        {c.warnings.map((w, i) => <li key={i} className="cmp-warn">{w.lap ? `Lap ${w.lap}: ` : ''}{w.message}</li>)}
      </ul>
    </section>
  );
}
