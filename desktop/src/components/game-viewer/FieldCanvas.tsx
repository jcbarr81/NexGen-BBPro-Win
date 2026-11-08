/**
 * The 2D field of the game viewer (backlog #74 step 3): the park drawn from
 * its fence, the nine fielders, the batter and runners, and the ball, at
 * one moment of one play. The parent owns the clock; it calls the drawing
 * through `draw(t)` on every animation frame (no React render per frame).
 */

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef } from "react";

import {
  POSITIONS,
  ballAt,
  calloutsAt,
  fenceAt,
  figuresAt,
  lastName,
  pathAt,
  type GamePlay,
  type GamePlaysDoc,
} from "@/lib/game-viewer";

export interface FieldCanvasHandle {
  draw: (play: GamePlay | null, t: number) => void;
}

interface Props {
  doc: GamePlaysDoc;
  className?: string;
}

// A ballpark looks like a ballpark in either theme: fixed field colors.
const COLORS = {
  stands: "#1d2b22",
  grass: "#2f7d3c",
  grassDark: "#2a7236",
  track: "#9c7b52",
  dirt: "#b98a59",
  chalk: "#f4f1e8",
  fence: "#123018",
  fielder: "#f4f1e8",
  fielderEdge: "#1b1b1b",
  batting: "#e8a33a",
  battingEdge: "#3a2408",
  ball: "#ffffff",
  shadow: "rgba(0,0,0,0.35)",
  label: "#ffffff",
  out: "#ff6b5e",
  safe: "#7be08a",
  big: "#ffd25e",
};

interface View {
  scale: number;
  cx: number;
  cy: number;
}

export const FieldCanvas = forwardRef<FieldCanvasHandle, Props>(function FieldCanvas(
  { doc, className },
  ref,
) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<View>({ scale: 1, cx: 0, cy: 0 });
  const lastRef = useRef<{ play: GamePlay | null; t: number }>({ play: null, t: 0 });

  const fit = useCallback(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const dpr = window.devicePixelRatio || 1;
    const width = wrap.clientWidth;
    const deepest = Math.max(...doc.field.fence.distances) + 25;
    const halfWide = Math.max(
      ...[-45, -30, -15, 0, 15, 30, 45].map(
        (a) => Math.abs(Math.sin((a * Math.PI) / 180)) * fenceAt(doc.field.fence, a),
      ),
    ) + 25;
    // The whole field fits the window: never taller than the viewport
    // leaves room for (the page header sits above it).
    const room = Math.max(320, window.innerHeight - 140);
    const height = Math.round(Math.min(width * ((deepest + 45) / (2 * halfWide)), room, 820));
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const scale = Math.min(width / (2 * halfWide), height / (deepest + 45)) * dpr;
    viewRef.current = { scale, cx: (width * dpr) / 2, cy: height * dpr - 30 * scale };
  }, [doc]);

  const draw = useCallback(
    (play: GamePlay | null, t: number) => {
      lastRef.current = { play, t };
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const { scale, cx, cy } = viewRef.current;
      const X = (x: number) => cx + x * scale;
      const Y = (y: number) => cy - y * scale;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = COLORS.stands;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      drawPark(ctx, doc, X, Y, scale);
      if (!play) return;

      // Fielders: where their paths have them, else their standing spots.
      const fontPx = Math.max(11, Math.round(scale * 7));
      const figure = Math.max(9 * (window.devicePixelRatio || 1), scale * 5.5);
      for (const pos of POSITIONS) {
        const path = play.fielders[pos];
        const [x, y] = path ? pathAt(path, t) : doc.field.positions[pos] ?? [0, 0];
        dot(ctx, X(x), Y(y), figure, COLORS.fielder, COLORS.fielderEdge);
        ctx.fillStyle = COLORS.fielderEdge;
        ctx.font = `700 ${Math.round(figure * 0.95)}px system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(pos, X(x), Y(y) + 0.5);
      }

      // Batter and runners.
      for (const fig of figuresAt(doc, play, t)) {
        if (fig.alpha <= 0) continue;
        ctx.globalAlpha = fig.alpha;
        dot(ctx, X(fig.x), Y(fig.y), figure, COLORS.batting, COLORS.battingEdge);
        ctx.font = `600 ${fontPx}px system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "bottom";
        ctx.lineWidth = 3;
        ctx.strokeStyle = "rgba(0,0,0,0.6)";
        const label = lastName(doc, fig.who);
        ctx.strokeText(label, X(fig.x), Y(fig.y) - figure - 2);
        ctx.fillStyle = COLORS.label;
        ctx.fillText(label, X(fig.x), Y(fig.y) - figure - 2);
        ctx.globalAlpha = 1;
      }

      // The ball: its shadow on the ground, the ball lifted by its height.
      const ball = ballAt(play.ball, t);
      if (ball) {
        const [bx, by, bz] = ball;
        const r = Math.max(2.5, scale * (1.6 + Math.min(bz, 120) / 60));
        ctx.fillStyle = COLORS.shadow;
        ctx.beginPath();
        ctx.ellipse(X(bx), Y(by), r * 1.1, r * 0.6, 0, 0, Math.PI * 2);
        ctx.fill();
        dot(ctx, X(bx), Y(by + bz * 0.55), r, COLORS.ball, "rgba(0,0,0,0.5)");
      }

      // Callouts.
      for (const c of calloutsAt(doc, play, t)) {
        ctx.globalAlpha = c.alpha;
        const size = Math.round(fontPx * (c.tone === "big" ? 2.4 : 1.5));
        ctx.font = `800 ${size}px system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.lineWidth = Math.max(3, size / 6);
        ctx.strokeStyle = "rgba(0,0,0,0.75)";
        const px = X(c.x);
        const py = Y(c.y) - scale * 14;
        ctx.strokeText(c.text, px, py);
        ctx.fillStyle =
          c.tone === "out" ? COLORS.out : c.tone === "safe" ? COLORS.safe : c.tone === "big" ? COLORS.big : COLORS.label;
        ctx.fillText(c.text, px, py);
        ctx.globalAlpha = 1;
      }
    },
    [doc],
  );

  useImperativeHandle(ref, () => ({ draw }), [draw]);

  useEffect(() => {
    fit();
    draw(lastRef.current.play, lastRef.current.t);
    const wrap = wrapRef.current;
    if (!wrap || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      fit();
      draw(lastRef.current.play, lastRef.current.t);
    });
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [fit, draw]);

  return (
    <div ref={wrapRef} className={className}>
      <canvas
        ref={canvasRef}
        role="img"
        aria-label="Baseball field showing the current play"
        className="block w-full rounded-lg"
      />
    </div>
  );
});

function dot(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  r: number,
  fill: string,
  edge: string,
) {
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.lineWidth = Math.max(1, r / 4);
  ctx.strokeStyle = edge;
  ctx.stroke();
}

function polar(r: number, angle: number): [number, number] {
  const a = (angle * Math.PI) / 180;
  return [r * Math.sin(a), r * Math.cos(a)];
}

function drawPark(
  ctx: CanvasRenderingContext2D,
  doc: GamePlaysDoc,
  X: (x: number) => number,
  Y: (y: number) => number,
  scale: number,
) {
  const fence = doc.field.fence;
  const fair = (inset: number) => {
    ctx.beginPath();
    ctx.moveTo(X(0), Y(0));
    for (let a = -45; a <= 45; a += 1.5) {
      const [x, y] = polar(fenceAt(fence, a) - inset, a);
      ctx.lineTo(X(x), Y(y));
    }
    ctx.closePath();
  };
  // A sliver of foul territory around home and down the lines.
  ctx.fillStyle = COLORS.grassDark;
  ctx.beginPath();
  ctx.moveTo(X(-40), Y(-30));
  ctx.lineTo(X(40), Y(-30));
  const [rx, ry] = polar(fenceAt(fence, 45) + 6, 50);
  const [lx, ly] = polar(fenceAt(fence, -45) + 6, -50);
  ctx.lineTo(X(rx), Y(ry));
  ctx.lineTo(X(lx), Y(ly));
  ctx.closePath();
  ctx.fill();
  // Warning track, then the outfield grass inside it.
  ctx.fillStyle = COLORS.track;
  fair(0);
  ctx.fill();
  ctx.fillStyle = COLORS.grass;
  fair(14);
  ctx.fill();
  // Mowing stripes.
  ctx.save();
  fair(14);
  ctx.clip();
  ctx.fillStyle = COLORS.grassDark;
  for (let r = 40; r < 460; r += 40) {
    ctx.beginPath();
    ctx.arc(X(0), Y(0), r * scale, 0, Math.PI * 2);
    ctx.arc(X(0), Y(0), (r + 20) * scale, 0, Math.PI * 2, true);
    ctx.fill();
  }
  // The infield dirt: a circle of 95 ft about the rubber.
  ctx.fillStyle = COLORS.dirt;
  ctx.beginPath();
  ctx.arc(X(doc.field.rubber[0]), Y(doc.field.rubber[1]), 95 * scale, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  // The infield grass inside the base paths.
  const base = (key: string): [number, number] => doc.field.bases[key] ?? [0, 0];
  const b = { "1": base("1"), "2": base("2"), "3": base("3") };
  const inset = 11;
  ctx.fillStyle = COLORS.grass;
  ctx.beginPath();
  ctx.moveTo(X(0), Y(inset * 1.2));
  ctx.lineTo(X(b["1"][0] - inset), Y(b["1"][1]));
  ctx.lineTo(X(0), Y(b["2"][1] - inset * 1.2));
  ctx.lineTo(X(b["3"][0] + inset), Y(b["3"][1]));
  ctx.closePath();
  ctx.fill();
  // Dirt circles: home, the mound, the bases.
  ctx.fillStyle = COLORS.dirt;
  for (const [x, y, r] of [
    [0, 0, 13],
    [doc.field.rubber[0], doc.field.rubber[1] - 1.5, 9],
  ] as const) {
    ctx.beginPath();
    ctx.arc(X(x), Y(y), r * scale, 0, Math.PI * 2);
    ctx.fill();
  }
  // Foul lines.
  ctx.strokeStyle = COLORS.chalk;
  ctx.lineWidth = Math.max(1, scale * 0.8);
  for (const a of [-45, 45]) {
    const [x, y] = polar(fenceAt(fence, a), a);
    ctx.beginPath();
    ctx.moveTo(X(0), Y(0));
    ctx.lineTo(X(x), Y(y));
    ctx.stroke();
  }
  // The fence.
  ctx.strokeStyle = COLORS.fence;
  ctx.lineWidth = Math.max(2, scale * 3);
  ctx.beginPath();
  for (let a = -45; a <= 45; a += 1.5) {
    const [x, y] = polar(fenceAt(fence, a), a);
    if (a === -45) ctx.moveTo(X(x), Y(y));
    else ctx.lineTo(X(x), Y(y));
  }
  ctx.stroke();
  // Bases and the plate.
  ctx.fillStyle = COLORS.chalk;
  for (const key of ["1", "2", "3"] as const) {
    const [x, y] = b[key];
    const s = Math.max(3, scale * 2.2);
    ctx.save();
    ctx.translate(X(x), Y(y));
    ctx.rotate(Math.PI / 4);
    ctx.fillRect(-s, -s, s * 2, s * 2);
    ctx.restore();
  }
  const p = Math.max(3, scale * 1.4);
  ctx.beginPath();
  ctx.moveTo(X(0) - p, Y(0) - p);
  ctx.lineTo(X(0) + p, Y(0) - p);
  ctx.lineTo(X(0) + p, Y(0));
  ctx.lineTo(X(0), Y(0) + p);
  ctx.lineTo(X(0) - p, Y(0));
  ctx.closePath();
  ctx.fill();
  ctx.fillRect(X(doc.field.rubber[0]) - scale * 1, Y(doc.field.rubber[1]) - scale * 0.3, scale * 2, scale * 0.6);
}
