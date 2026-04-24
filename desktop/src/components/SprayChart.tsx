/**
 * Synthetic spray chart, ported from SprayChartWidget in
 * ui/player_profile_dialog.py. Not actual batted-ball coordinates —
 * dots are placed in plausible field locations based on hit counts
 * (1B / 2B / 3B / HR) and the batter's handedness. Deterministic via a
 * ``(player_id, kind, idx)`` hash so re-renders stay stable.
 */

import { useMemo } from "react";

interface SprayPoint {
  x: number; // normalized -1..1 (left foul line to right foul line)
  y: number; // normalized 0..1  (home plate to fence)
  kind: "1B" | "2B" | "3B" | "HR";
}

interface SprayChartProps {
  playerId: string;
  /** "L" / "R" / "S" — switch hitters spray both ways. */
  bats: string;
  singles: number;
  doubles: number;
  triples: number;
  homers: number;
  className?: string;
}

const KIND_COLOR: Record<SprayPoint["kind"], string> = {
  "1B": "#51cf66",
  "2B": "#339af0",
  "3B": "#fcc419",
  HR: "#fa5252",
};

/** Same hash that PyQt ``_compute_spray_points`` uses: ``hash(tuple)``
 *  — but JS doesn't have Python's hash, so fall back to a small string
 *  hash. Output just needs to be deterministic per ``(id, kind, idx)``. */
function seed(pid: string, kind: string, idx: number): number {
  const s = `${pid}|${kind}|${idx}`;
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h * 31 + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

function computePoints({
  playerId,
  bats,
  singles,
  doubles,
  triples,
  homers,
}: SprayChartProps): SprayPoint[] {
  const total = singles + doubles + triples + homers;
  if (total <= 0) return [];

  const handed = (bats || "R").toUpperCase();
  const side = handed.startsWith("L") ? 1 : handed.startsWith("S") ? 0 : -1;
  const points: SprayPoint[] = [];

  const addPoints = (
    count: number,
    baseX: number,
    depth: number,
    spread: number,
    kind: SprayPoint["kind"],
  ) => {
    for (let idx = 0; idx < count; idx++) {
      const s = seed(playerId, kind, idx);
      const offset = ((s % 1000) / 999) - 0.5;
      let x: number;
      if (side === 0) {
        x = baseX + offset * spread;
        if (idx % 2 === 0) x *= -1;
      } else {
        x = baseX * side + offset * spread;
      }
      x = Math.max(-0.95, Math.min(0.95, x));
      const depthVariation = ((Math.floor(s / 1000) % 200) / 1000) - 0.1;
      const y = Math.max(0.1, Math.min(1.0, depth + depthVariation));
      points.push({ x, y, kind });
    }
  };

  addPoints(singles, 0.45, 0.35, 0.25, "1B");
  addPoints(doubles, 0.25, 0.6, 0.2, "2B");
  addPoints(triples, 0.05, 0.8, 0.2, "3B");
  addPoints(homers, 0.0, 1.0, 0.15, "HR");
  return points;
}

export function SprayChart(props: SprayChartProps) {
  const points = useMemo(() => computePoints(props), [props]);
  const width = 320;
  const height = 240;
  const pad = 16;
  const plotW = width - pad * 2;
  const plotH = height - pad * 2;
  const homeX = pad + plotW / 2;
  const homeY = height - pad;
  const fenceY = pad;

  if (points.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-xl border border-border bg-canvas/40 text-sm text-muted">
        No batted-ball data yet.
      </div>
    );
  }

  return (
    <div className={props.className}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full overflow-visible"
        aria-label="Spray chart"
      >
        {/* Infield grass shading for a tiny bit of baseball flavor. */}
        <path
          d={`
            M ${homeX} ${homeY}
            L ${pad} ${fenceY}
            A ${plotW / 2} ${plotH} 0 0 1 ${width - pad} ${fenceY}
            L ${homeX} ${homeY}
            Z
          `}
          fill="hsl(var(--ballpark) / 0.15)"
          stroke="hsl(var(--border))"
          strokeWidth={1.5}
        />
        {/* Foul lines. */}
        <line
          x1={homeX}
          y1={homeY}
          x2={pad}
          y2={fenceY}
          stroke="hsl(var(--border))"
          strokeWidth={1.5}
        />
        <line
          x1={homeX}
          y1={homeY}
          x2={width - pad}
          y2={fenceY}
          stroke="hsl(var(--border))"
          strokeWidth={1.5}
        />
        {/* Hit markers. */}
        {points.map((p, i) => {
          const cx = homeX + p.x * (plotW / 2);
          const cy = homeY - p.y * plotH;
          return (
            <circle
              key={i}
              cx={cx}
              cy={cy}
              r={4}
              fill={KIND_COLOR[p.kind]}
              opacity={0.85}
            />
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap items-center justify-center gap-3 text-[11px] text-muted">
        {(Object.keys(KIND_COLOR) as Array<SprayPoint["kind"]>).map((kind) => (
          <span key={kind} className="inline-flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: KIND_COLOR[kind] }}
            />
            {kind}
          </span>
        ))}
      </div>
    </div>
  );
}
