/**
 * Rolling metric line chart for the player profile. Ports the
 * ``RollingStatsWidget`` from ``ui/player_profile_dialog.py``: one line
 * per metric (hitter → AVG/OPS, pitcher → ERA/WHIP) plotted over the
 * last ~12 season_history snapshots. Data lives in the profile payload
 * as ``{dates, series}`` — this component is presentation only.
 */

import { useMemo } from "react";

interface RollingStatsChartProps {
  dates: string[];
  series: Record<string, number[]>;
  className?: string;
}

const PALETTE = ["#228be6", "#f76707", "#12b886", "#fa5252"];

export function RollingStatsChart({
  dates,
  series,
  className,
}: RollingStatsChartProps) {
  const { min, max } = useMemo(() => {
    const all: number[] = [];
    for (const values of Object.values(series)) {
      for (const v of values) if (Number.isFinite(v)) all.push(v);
    }
    if (all.length === 0) return { min: 0, max: 1 };
    let lo = Math.min(...all);
    let hi = Math.max(...all);
    if (Math.abs(hi - lo) < 0.001) {
      hi += 0.5;
      lo -= 0.5;
    }
    return { min: lo, max: hi };
  }, [series]);

  if (dates.length === 0 || Object.values(series).every((s) => s.length === 0)) {
    return (
      <div className="flex h-48 items-center justify-center rounded-xl border border-border bg-canvas/40 text-sm text-muted">
        No rolling history yet.
      </div>
    );
  }

  const width = 640;
  const height = 220;
  const padL = 36;
  const padR = 12;
  const padT = 12;
  const padB = 28;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  const xFor = (idx: number) => {
    if (dates.length <= 1) return padL + plotW / 2;
    return padL + (idx / (dates.length - 1)) * plotW;
  };
  const yFor = (value: number) => {
    if (max === min) return padT + plotH / 2;
    const ratio = (value - min) / (max - min);
    return padT + (1 - ratio) * plotH;
  };

  const seriesEntries = Object.entries(series);

  return (
    <div className={className}>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full">
        {/* Axes. */}
        <line
          x1={padL}
          y1={padT}
          x2={padL}
          y2={padT + plotH}
          stroke="hsl(var(--border))"
          strokeWidth={1}
        />
        <line
          x1={padL}
          y1={padT + plotH}
          x2={padL + plotW}
          y2={padT + plotH}
          stroke="hsl(var(--border))"
          strokeWidth={1}
        />
        {/* Y-axis ticks — min, midpoint, max. */}
        {[min, (min + max) / 2, max].map((v, i) => {
          const y = yFor(v);
          return (
            <g key={i}>
              <line
                x1={padL - 3}
                y1={y}
                x2={padL}
                y2={y}
                stroke="hsl(var(--border))"
              />
              <text
                x={padL - 6}
                y={y + 3}
                fontSize="9"
                textAnchor="end"
                fill="hsl(var(--muted))"
              >
                {v.toFixed(3)}
              </text>
            </g>
          );
        })}
        {/* X labels: first + last only to avoid clutter. */}
        {dates.length > 0 && (
          <>
            <text
              x={padL}
              y={padT + plotH + 16}
              fontSize="9"
              textAnchor="start"
              fill="hsl(var(--muted))"
            >
              {dates[0]}
            </text>
            {dates.length > 1 && (
              <text
                x={padL + plotW}
                y={padT + plotH + 16}
                fontSize="9"
                textAnchor="end"
                fill="hsl(var(--muted))"
              >
                {dates[dates.length - 1]}
              </text>
            )}
          </>
        )}
        {/* Lines. */}
        {seriesEntries.map(([label, values], idx) => {
          if (values.length === 0) return null;
          const color = PALETTE[idx % PALETTE.length];
          const d = values
            .map((v, i) => `${i === 0 ? "M" : "L"} ${xFor(i)} ${yFor(v)}`)
            .join(" ");
          return (
            <g key={label}>
              <path d={d} stroke={color} strokeWidth={2} fill="none" />
              {values.map((v, i) => (
                <circle
                  key={i}
                  cx={xFor(i)}
                  cy={yFor(v)}
                  r={2.5}
                  fill={color}
                />
              ))}
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap items-center justify-center gap-3 text-[11px] text-muted">
        {seriesEntries.map(([label], idx) => (
          <span key={label} className="inline-flex items-center gap-1">
            <span
              className="inline-block h-2 w-3 rounded-sm"
              style={{ backgroundColor: PALETTE[idx % PALETTE.length] }}
            />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}
