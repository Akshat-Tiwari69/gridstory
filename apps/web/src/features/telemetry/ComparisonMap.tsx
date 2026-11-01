import { useMemo, useRef } from 'react';
import { useCursorStore } from '../../stores/cursorStore';
import { useSessionStore } from '../../stores/sessionStore';
import { nearestIndex, useCircuit, useComparisonTrace } from '../../hooks/useSessionQueries';
import { rotate } from './trackGeometry';
import { NEUTRAL_COLOR, SIDE_COLORS } from './comparisonColors';
import type { LapComparison } from '../../types/f1';
import './AnalysisTrackMap.css';

// The API reports no gain below this (docs/lap-comparison-api.md); show those segments neutral.
const MIN_GAIN_S = 0.02;

/**
 * Track map coloured by which lap won each segment. Segment gains come straight from the API;
 * positions come from lap A's telemetry, whose distance is mapped onto the comparison grid by
 * alignment.scaleA, so map and charts share one distance axis.
 */
export function ComparisonMap({ comparison: c }: { comparison: LapComparison }) {
  const { cursor, setCursor } = useCursorStore();
  const { data: tel, isLoading, error } = useComparisonTrace(c.lapA.driver, c.lapA.lapNumber);
  const { data: circuit } = useCircuit();
  const { selectedEvent } = useSessionStore();
  const svgRef = useRef<SVGSVGElement>(null);

  const geo = useMemo(() => {
    if (!tel || tel.x.length < 2) return null;
    const rad = ((circuit?.rotation ?? 0) * Math.PI) / 180;
    const pts = tel.x.map((x, i) => {
      const [rx, ry] = rotate(x, tel.y[i], rad);
      return [rx, -ry] as [number, number];
    });
    const grid = tel.distance.map((d) => d * c.alignment.scaleA); // metres on the comparison grid
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const size = Math.max(maxX - minX, maxY - minY);
    const pad = size * 0.08;

    // One polyline run per segment, coloured by its winner.
    const runs = c.segments.map((s) => {
      const from = Math.max(0, nearestIndex(grid, s.startM));
      const to = Math.min(pts.length - 1, nearestIndex(grid, s.endM));
      const color = Math.abs(s.gainAS) < MIN_GAIN_S ? NEUTRAL_COLOR : s.gainAS > 0 ? SIDE_COLORS.a : SIDE_COLORS.b;
      return { id: s.id, color, points: pts.slice(from, to + 1).map((p) => p.join(',')).join(' ') };
    });

    const corners = (circuit?.corners ?? []).map((k) => {
      const [ox, oy] = rotate(size * 0.04, 0, (k.angle * Math.PI) / 180);
      const [lx, ly] = rotate(k.x + ox, k.y + oy, rad);
      return { label: `${k.number}${k.letter ?? ''}`, x: lx, y: -ly };
    });

    const brake = c.segments.flatMap((s) =>
      (['a', 'b'] as const).flatMap((side) => {
        const m = s.corner?.[side].brakeOnM;
        if (m == null) return [];
        const p = pts[nearestIndex(grid, m)];
        return [{ key: `${s.id}${side}`, side, x: p[0], y: p[1] }];
      }));

    return { pts, grid, runs, corners, brake, fontSize: size / 34, viewBox: `${minX - pad} ${minY - pad} ${maxX - minX + 2 * pad} ${maxY - minY + 2 * pad}` };
  }, [tel, circuit, c]);

  if (isLoading) return <div className="analysis-map analysis-map--empty" role="status">Loading track…</div>;
  if (error || !geo) return <div className="analysis-map analysis-map--empty">No position data for lap A, so the map is unavailable.</div>;

  const idx = cursor ? nearestIndex(geo.grid, cursor.distance) : null;
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const ctm = svgRef.current?.getScreenCTM();
    if (!ctm) return;
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse());
    let best = 0, bestD = Infinity;
    geo.pts.forEach(([x, y], i) => {
      const d = (x - p.x) ** 2 + (y - p.y) ** 2;
      if (d < bestD) { bestD = d; best = i; }
    });
    setCursor({ distance: geo.grid[best], source: 'map' });
  };

  return (
    <div className="analysis-map">
      <div className="analysis-map-head">
        <span className="analysis-map-title">Who was faster</span>
        <span className="cmp-legend">
          <i style={{ background: SIDE_COLORS.a }} />A <i style={{ background: SIDE_COLORS.b }} />B <i style={{ background: NEUTRAL_COLOR }} />level
        </span>
      </div>
      <svg ref={svgRef} className="analysis-map-svg" viewBox={geo.viewBox} role="img"
        aria-label={`Track map of ${selectedEvent ?? 'the circuit'} coloured by which lap was faster in each segment`}
        onMouseMove={onMove} onMouseLeave={() => setCursor(null)}>
        {geo.runs.map((r) => <polyline key={r.id} points={r.points} stroke={r.color} className="track-line" />)}
        {geo.corners.map((k) => <text key={k.label} x={k.x} y={k.y} fontSize={geo.fontSize} className="corner-label">{k.label}</text>)}
        {geo.brake.map((b) => (
          <circle key={b.key} cx={b.x} cy={b.y} r={geo.fontSize * 0.28} fill={SIDE_COLORS[b.side]} className="brake-marker" />
        ))}
        {idx != null && <circle cx={geo.pts[idx][0]} cy={geo.pts[idx][1]} r={geo.fontSize * 0.45} className="cursor-dot" />}
      </svg>
      <div className="analysis-map-foot">
        <span>● brake-on point (A / B)</span>
        <span className="cursor-readout">{idx != null ? `${Math.round(geo.grid[idx]).toLocaleString()} m` : 'Hover the track'}</span>
      </div>
    </div>
  );
}
