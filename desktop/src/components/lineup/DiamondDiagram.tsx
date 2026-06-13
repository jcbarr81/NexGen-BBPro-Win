/**
 * SVG baseball diamond with position labels — port of the field diagram
 * from ui/lineup_editor.py. Pure SVG so it scales, picks up theme colors,
 * and doesn't need a bundled PNG.
 *
 * Coordinate system: a 400-wide × 400-tall viewBox with home plate at
 * the bottom and the outfield arc at the top. Labels are absolutely
 * positioned as HTML over the SVG so text antialiases cleanly and we
 * can hover/click through to the roster.
 */

import { useMemo } from "react";
import { useDraggable, useDroppable } from "@dnd-kit/core";

import { cn } from "@/lib/cn";

export interface DiamondPosition {
  code: string;
  /** Short label shown on the field; falls back to the position code. */
  label?: string;
  /** Optional secondary line (usually a rating or number). */
  sub?: string;
  /** Player id backing this spot — used as the drag payload. */
  playerId?: string;
  empty?: boolean;
}

interface Props {
  /** Map of position code → player info to render. Keys we understand:
   *  P, C, 1B, 2B, 3B, SS, LF, CF, RF, DH. Anything else is ignored. */
  positions: Partial<Record<string, DiamondPosition>>;
  /** Accent color for the field stripe + labels. Defaults to amber. */
  accentColor?: string;
  /** When true, each spot becomes a drop target (id `field-<code>`) and
   *  filled spots become draggable (id `fieldsrc-<code>`). Must be rendered
   *  inside a dnd-kit DndContext for the handlers to fire. */
  interactive?: boolean;
  className?: string;
}

/** Position codes that can be assigned via the field (no pitcher slot). */
const DROP_CODES = new Set([
  "C",
  "1B",
  "2B",
  "3B",
  "SS",
  "LF",
  "CF",
  "RF",
  "DH",
]);

interface Spot {
  x: number;
  y: number;
  align: "left" | "center" | "right";
  /** Optional vertical offset used to lift a label above / below its dot. */
  labelOffsetY?: number;
}

/**
 * Position anchors in SVG units. These are tuned against a 400×400 viewBox
 * with home at (200, 320). Adjust the constants only — labels and dots
 * re-use them so they always stay aligned.
 */
const SPOTS: Record<string, Spot> = {
  CF: { x: 200, y: 70, align: "center", labelOffsetY: -8 },
  LF: { x: 80, y: 110, align: "center", labelOffsetY: -8 },
  RF: { x: 320, y: 110, align: "center", labelOffsetY: -8 },
  SS: { x: 140, y: 195, align: "right", labelOffsetY: -12 },
  "2B": { x: 260, y: 195, align: "left", labelOffsetY: -12 },
  "3B": { x: 95, y: 245, align: "right" },
  "1B": { x: 305, y: 245, align: "left" },
  P: { x: 200, y: 220, align: "center", labelOffsetY: 24 },
  C: { x: 200, y: 348, align: "center", labelOffsetY: 18 },
  DH: { x: 352, y: 345, align: "left" },
};

const DIAMOND_POINTS = {
  home: [200, 320],
  first: [290, 230],
  second: [200, 140],
  third: [110, 230],
} as const;

export function DiamondDiagram({
  positions,
  accentColor,
  interactive = false,
  className,
}: Props) {
  // Precompute the infield polyline once so we don't rebuild on every render.
  const diamondPath = useMemo(() => {
    const { home, first, second, third } = DIAMOND_POINTS;
    return `M ${home[0]} ${home[1]} L ${first[0]} ${first[1]} L ${second[0]} ${second[1]} L ${third[0]} ${third[1]} Z`;
  }, []);

  return (
    <div className={cn("relative w-full", className)}>
      <svg
        viewBox="0 0 400 400"
        className="block h-auto w-full"
        preserveAspectRatio="xMidYMid meet"
        aria-label="Baseball diamond with fielders"
      >
        <defs>
          <radialGradient id="grassOutfield" cx="50%" cy="100%" r="90%">
            <stop offset="0%" stopColor="hsl(var(--ballpark))" stopOpacity="0.95" />
            <stop offset="70%" stopColor="hsl(var(--ballpark-deep))" stopOpacity="1" />
            <stop offset="100%" stopColor="hsl(var(--ballpark-deep))" stopOpacity="1" />
          </radialGradient>
          <radialGradient id="grassInfield" cx="50%" cy="50%" r="70%">
            <stop offset="0%" stopColor="hsl(var(--ballpark))" stopOpacity="0.85" />
            <stop offset="100%" stopColor="hsl(var(--ballpark-deep))" stopOpacity="0.95" />
          </radialGradient>
        </defs>

        {/* Outfield wedge — foul line to foul line. */}
        <path
          d="M 200 320 L 10 130 A 260 260 0 0 1 390 130 Z"
          fill="url(#grassOutfield)"
        />

        {/* Warning track ring just inside the outfield wall. */}
        <path
          d="M 22 142 A 250 250 0 0 1 378 142"
          fill="none"
          stroke="hsl(var(--clay))"
          strokeWidth="10"
          strokeOpacity="0.85"
        />

        {/* Infield dirt (larger diamond behind the grass infield). */}
        <path
          d={diamondPath}
          fill="hsl(var(--clay))"
          fillOpacity="0.9"
        />

        {/* Inner grass infield — shaves the dirt back so the bases sit on clay. */}
        <path
          d="M 200 300 L 270 230 L 200 160 L 130 230 Z"
          fill="url(#grassInfield)"
        />

        {/* Foul lines (chalk). */}
        <line
          x1={DIAMOND_POINTS.home[0]}
          y1={DIAMOND_POINTS.home[1]}
          x2="20"
          y2="140"
          stroke="hsl(var(--chalk))"
          strokeOpacity="0.8"
          strokeWidth="1.5"
        />
        <line
          x1={DIAMOND_POINTS.home[0]}
          y1={DIAMOND_POINTS.home[1]}
          x2="380"
          y2="140"
          stroke="hsl(var(--chalk))"
          strokeOpacity="0.8"
          strokeWidth="1.5"
        />

        {/* Base paths along the diamond edges. */}
        <path
          d={diamondPath}
          fill="none"
          stroke="hsl(var(--chalk))"
          strokeOpacity="0.7"
          strokeWidth="2"
        />

        {/* Pitcher's mound. */}
        <circle
          cx="200"
          cy="220"
          r="16"
          fill="hsl(var(--clay))"
          stroke="hsl(var(--chalk))"
          strokeOpacity="0.6"
          strokeWidth="1"
        />
        <line
          x1="188"
          y1="220"
          x2="212"
          y2="220"
          stroke="hsl(var(--chalk))"
          strokeOpacity="0.85"
          strokeWidth="1.5"
        />

        {/* Bases as rotated squares (first/second/third). */}
        {(
          [
            [DIAMOND_POINTS.first, "1B"],
            [DIAMOND_POINTS.second, "2B"],
            [DIAMOND_POINTS.third, "3B"],
          ] as const
        ).map(([[cx, cy], id]) => (
          <rect
            key={id}
            x={cx - 6}
            y={cy - 6}
            width="12"
            height="12"
            fill="hsl(var(--chalk))"
            stroke="hsl(var(--walnut))"
            strokeWidth="1"
            transform={`rotate(45 ${cx} ${cy})`}
          />
        ))}

        {/* Home plate (pentagon). */}
        <polygon
          points="192,316 208,316 212,324 200,332 188,324"
          fill="hsl(var(--chalk))"
          stroke="hsl(var(--walnut))"
          strokeWidth="1"
        />
      </svg>

      {/* HTML overlay labels — positioned with percentage coords so they
          scale with the SVG. Using div/span here rather than SVG text so
          we get word-wrapping, proper antialiasing, and hover states. */}
      <div className="pointer-events-none absolute inset-0">
        {Object.entries(SPOTS).map(([code, spot]) => (
          <DiamondSpot
            key={code}
            code={code}
            spot={spot}
            entry={positions[code]}
            accentColor={accentColor}
            interactive={interactive && DROP_CODES.has(code)}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * A single labeled field position. When `interactive`, it registers as a
 * dnd-kit drop target (`field-<code>`) and, if filled, as a draggable source
 * (`fieldsrc-<code>`) so fielders can be swapped by dragging one onto another.
 * The dnd-kit hooks are always called (Rules of Hooks); they're inert outside
 * a DndContext, and we only wire their refs/listeners when interactive.
 */
function DiamondSpot({
  code,
  spot,
  entry,
  accentColor,
  interactive,
}: {
  code: string;
  spot: Spot;
  entry?: DiamondPosition;
  accentColor?: string;
  interactive: boolean;
}) {
  const filled = !!(entry && !entry.empty && entry.label);

  const { setNodeRef: setDropRef, isOver } = useDroppable({
    id: `field-${code}`,
    data: { code },
    disabled: !interactive,
  });
  const {
    setNodeRef: setDragRef,
    attributes,
    listeners,
    isDragging,
  } = useDraggable({
    id: `fieldsrc-${code}`,
    data: { kind: "field", code, playerId: entry?.playerId },
    disabled: !interactive || !filled,
  });

  const left = (spot.x / 400) * 100;
  const top = ((spot.y + (spot.labelOffsetY ?? 0)) / 400) * 100;
  const transform =
    spot.align === "center"
      ? "translate(-50%, -50%)"
      : spot.align === "left"
        ? "translate(0, -50%)"
        : "translate(-100%, -50%)";

  return (
    <div
      ref={interactive ? setDropRef : undefined}
      className={cn(
        "absolute flex max-w-[90px] flex-col items-center gap-0.5 rounded-md p-0.5 text-center",
        interactive && "pointer-events-auto",
        interactive && isOver && "ring-2 ring-amber",
        isDragging && "opacity-40",
      )}
      style={{
        left: `${left}%`,
        top: `${top}%`,
        transform,
      }}
    >
      <span
        className="rounded-sm border px-1 text-[9px] font-bold uppercase tracking-wider shadow-sm"
        style={{
          backgroundColor: "hsl(var(--espresso) / 0.9)",
          color: accentColor ?? "hsl(var(--amber))",
          borderColor: accentColor ?? "hsl(var(--amber) / 0.6)",
        }}
      >
        {code}
      </span>
      <span
        ref={interactive && filled ? setDragRef : undefined}
        className={cn(
          "rounded-md px-1.5 py-0.5 text-[10px] font-semibold leading-tight",
          filled
            ? "bg-chalk/95 text-espresso shadow-sm"
            : "bg-espresso/70 text-cream/60 italic",
          interactive && filled && "cursor-grab touch-none",
        )}
        title={
          interactive && filled ? `Drag to swap — ${entry?.label}` : entry?.label
        }
        {...(interactive && filled ? attributes : {})}
        {...(interactive && filled ? listeners : {})}
      >
        {filled ? entry!.label : "—"}
      </span>
      {filled && entry!.sub && (
        <span
          className="rounded bg-espresso/80 px-1 text-[9px] text-amber"
          style={{ color: accentColor ?? undefined }}
        >
          {entry!.sub}
        </span>
      )}
    </div>
  );
}
