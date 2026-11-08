/**
 * Game viewer (backlog #74 step 3): watch a played game on a 2D field.
 *
 * Two modes (the owner's choice): "Key plays" shows the pitch each plate
 * appearance's result happened on (plus steals, wild pitches, pickoffs);
 * "Every pitch" shows every pitch and every play. Both read the same
 * timed plays from `GET /boxscore/replay/plays` (services/replay_plays.py);
 * the engine decided every outcome, the viewer only shows it.
 *
 * Opened from a box score's "Watch game" button: /game-viewer?path=<box score>.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  FileText,
  Loader2,
  Pause,
  Play,
  RotateCcw,
  SkipBack,
  SkipForward,
} from "lucide-react";

import { api } from "@/lib/api";
import { AppShell } from "@/components/layout/AppShell";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { FieldCanvas, type FieldCanvasHandle } from "@/components/game-viewer/FieldCanvas";
import {
  halfLabel,
  lineScore,
  ordinal,
  playEnd,
  playerName,
  playsForMode,
  type GamePlay,
  type GamePlaysDoc,
  type ViewMode,
} from "@/lib/game-viewer";
import { cn } from "@/lib/cn";

const SPEEDS = [0.5, 1, 2, 4] as const;
const PREF_KEY = "nexgen.gameViewer";

const PITCH_NAMES: Record<string, string> = {
  fb: "Fastball",
  si: "Sinker",
  sl: "Slider",
  cu: "Changeup",
  cb: "Curveball",
  scb: "Screwball",
  kn: "Knuckleball",
};

const CALL_WORDS: Record<string, string> = {
  ball: "Ball",
  strike: "Called strike",
  swinging_strike: "Swinging strike",
  foul: "Foul",
  in_play: "In play",
  hbp: "Hit by pitch",
  interference: "Interference",
};

function readPrefs(): { mode: ViewMode; speed: number } {
  try {
    const raw = window.localStorage.getItem(PREF_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as { mode?: string; speed?: number };
      return {
        mode: parsed.mode === "all" ? "all" : "key",
        speed: SPEEDS.includes(parsed.speed as (typeof SPEEDS)[number]) ? (parsed.speed as number) : 1,
      };
    }
  } catch {
    /* storage unavailable: defaults */
  }
  return { mode: "key", speed: 1 };
}

function writePrefs(mode: ViewMode, speed: number) {
  try {
    window.localStorage.setItem(PREF_KEY, JSON.stringify({ mode, speed }));
  } catch {
    /* storage unavailable */
  }
}

export function GameViewerPage() {
  const [params] = useSearchParams();
  const path = params.get("path") ?? "";
  const navigate = useNavigate();
  const plays = useQuery({
    queryKey: ["game-plays", path],
    queryFn: () => api.gamePlays(path),
    enabled: !!path,
    staleTime: Infinity,
    retry: false,
  });
  const doc = plays.data;
  const subtitle = doc
    ? `${doc.game.away_name || doc.game.away} at ${doc.game.home_name || doc.game.home}${
        doc.game.date ? ` · ${doc.game.date}` : ""
      }${doc.game.postseason ? " · Postseason" : ""}`
    : "Watch a played game";

  return (
    <AppShell title="Game Viewer" subtitle={subtitle}>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Button variant="ghost" onClick={() => navigate(-1)}>
          <ArrowLeft className="h-4 w-4" /> Back
        </Button>
        {path ? (
          <Button variant="outline" size="sm" asChild>
            <Link to={`/boxscore?path=${encodeURIComponent(path)}`}>
              <FileText className="h-4 w-4" /> Box score
            </Link>
          </Button>
        ) : null}
      </div>
      {!path ? (
        <Notice icon="warn" text="No game was chosen. Open a box score and press Watch game." />
      ) : plays.isLoading ? (
        <Notice icon="load" text="Loading the game…" />
      ) : plays.isError ? (
        <Notice icon="warn" text={(plays.error as Error).message} />
      ) : doc && doc.plays.length > 0 ? (
        <Viewer doc={doc} />
      ) : doc ? (
        <Notice icon="warn" text="This game has no plays to show." />
      ) : null}
    </AppShell>
  );
}

function Notice({ icon, text }: { icon: "warn" | "load"; text: string }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        {icon === "load" ? (
          <Loader2 className="h-5 w-5 animate-spin text-amber" />
        ) : (
          <AlertTriangle className="h-5 w-5 text-warning" />
        )}
        <span className="text-sm text-muted">{text}</span>
      </CardContent>
    </Card>
  );
}

function Viewer({ doc }: { doc: GamePlaysDoc }) {
  const initial = useMemo(readPrefs, []);
  const [mode, setMode] = useState<ViewMode>(initial.mode);
  const [speed, setSpeed] = useState<number>(initial.speed);
  const [playing, setPlaying] = useState(false);
  const order = useMemo(() => playsForMode(doc.plays, mode), [doc, mode]);
  const [idx, setIdx] = useState<number>(() => order[0] ?? 0);
  // 0: before the pitch reaches the plate, 1: after, 2: the play is over.
  const [phase, setPhase] = useState(0);

  const field = useRef<FieldCanvasHandle | null>(null);
  const tRef = useRef(0);
  const idxRef = useRef(idx);
  const phaseRef = useRef(0);
  const playingRef = useRef(playing);
  const speedRef = useRef(speed);
  const orderRef = useRef(order);
  const modeRef = useRef(mode);

  playingRef.current = playing;
  speedRef.current = speed;
  orderRef.current = order;
  modeRef.current = mode;

  useEffect(() => writePrefs(mode, speed), [mode, speed]);

  const goTo = useCallback((next: number) => {
    idxRef.current = next;
    tRef.current = 0;
    phaseRef.current = 0;
    setIdx(next);
    setPhase(0);
  }, []);

  // A mode change keeps your place: the first shown play at or after it.
  useEffect(() => {
    if (order.length === 0 || order.includes(idxRef.current)) return;
    const next = order.find((i) => i >= idxRef.current) ?? order[order.length - 1];
    if (next !== undefined) goTo(next);
  }, [order, goTo]);

  const step = useCallback(
    (delta: number) => {
      const list = orderRef.current;
      const pos = list.indexOf(idxRef.current);
      const target = list[Math.max(0, Math.min(list.length - 1, (pos < 0 ? 0 : pos) + delta))];
      if (target !== undefined) goTo(target);
    },
    [goTo],
  );

  // The clock: one animation frame loop for the whole viewer.
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const play = doc.plays[idxRef.current];
      if (play && playingRef.current) {
        tRef.current += dt * speedRef.current;
        const plateT = play.ball[1]?.[0] ?? 0;
        const nextPhase = tRef.current >= playEnd(play) ? 2 : tRef.current >= plateT ? 1 : 0;
        if (nextPhase !== phaseRef.current) {
          phaseRef.current = nextPhase;
          setPhase(nextPhase);
        }
        const hold = modeRef.current === "all" && !play.key ? 0.15 : 0.7;
        if (tRef.current >= play.dur + hold) {
          const list = orderRef.current;
          const next = list[list.indexOf(idxRef.current) + 1];
          if (next === undefined) {
            setPlaying(false);
          } else {
            goTo(next);
          }
        }
      }
      field.current?.draw(play ?? null, tRef.current);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [doc, goTo]);

  // Keyboard: space plays/pauses, arrows step.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|SELECT|TEXTAREA|BUTTON)$/.test(target.tagName)) return;
      if (event.key === " ") {
        event.preventDefault();
        setPlaying((p) => !p);
      } else if (event.key === "ArrowRight") {
        step(1);
      } else if (event.key === "ArrowLeft") {
        step(-1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step]);

  const play = (doc.plays[idx] ?? doc.plays[0])!;
  const done = phase === 2;
  const prev = idx > 0 ? doc.plays[idx - 1] : null;
  const score = done ? play.score : prev?.score ?? { away: 0, home: 0 };
  const line = useMemo(() => lineScore(doc.plays, done ? idx : idx - 1), [doc, idx, done]);
  const atEnd = order.length > 0 && idx === order[order.length - 1] && done;
  const innings = useMemo(() => {
    const seen = new Map<string, number>();
    doc.plays.forEach((p, i) => {
      const key = `${p.inning}-${p.half}`;
      if (!seen.has(key)) seen.set(key, i);
    });
    return Array.from(seen.entries()).map(([key, i]) => ({ key, i, play: doc.plays[i]! }));
  }, [doc]);

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="min-w-0">
        <Card className="xl:sticky xl:top-4">
          <CardContent className="p-2 sm:p-3">
            <FieldCanvas ref={field} doc={doc} />
          </CardContent>
        </Card>
      </div>
      <div className="flex min-w-0 flex-col gap-4">
        <Scoreboard doc={doc} line={line} play={play} done={done} score={score} />
        <Card>
          <CardContent className="space-y-3 py-4">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">
              {halfLabel(play)} · {playerName(doc, play.batter)} vs{" "}
              {playerName(doc, play.pitcher)}
            </div>
            <div className="min-h-[3rem] text-base font-semibold text-ink" aria-live="polite">
              {done || (phase === 1 && !play.pa_end && !play.key) ? play.text : "…"}
            </div>
            <PitchInset play={play} shown={phase >= 1} />
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="icon"
                variant="outline"
                onClick={() => step(-1)}
                aria-label="Previous play"
                title="Previous play (←)"
              >
                <SkipBack className="h-4 w-4" />
              </Button>
              <Button
                onClick={() => {
                  if (atEnd) goTo(order[0] ?? 0);
                  setPlaying((p) => !p || atEnd);
                }}
                aria-label={playing ? "Pause" : "Play"}
                title="Play / pause (space)"
              >
                {playing && !atEnd ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                {playing && !atEnd ? "Pause" : atEnd ? "Watch again" : "Play"}
              </Button>
              <Button
                size="icon"
                variant="outline"
                onClick={() => step(1)}
                aria-label="Next play"
                title="Next play (→)"
              >
                <SkipForward className="h-4 w-4" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                onClick={() => {
                  tRef.current = 0;
                  phaseRef.current = 0;
                  setPhase(0);
                }}
                aria-label="Replay this play"
                title="Replay this play"
              >
                <RotateCcw className="h-4 w-4" />
              </Button>
            </div>
            <Segmented
              label="Show"
              value={mode}
              options={[
                { value: "key", label: "Key plays" },
                { value: "all", label: "Every pitch" },
              ]}
              onChange={(v) => setMode(v as ViewMode)}
            />
            <Segmented
              label="Speed"
              value={String(speed)}
              options={SPEEDS.map((s) => ({ value: String(s), label: `${s}×` }))}
              onChange={(v) => setSpeed(Number(v))}
            />
            <label className="flex items-center gap-2 text-xs text-muted">
              Jump to
              <select
                className="rounded-md border border-border bg-surface px-2 py-1 text-xs text-ink"
                value=""
                onChange={(event) => {
                  const start = Number(event.target.value);
                  if (Number.isNaN(start)) return;
                  const target = order.find((i) => i >= start);
                  if (target !== undefined) goTo(target);
                }}
              >
                <option value="">an inning…</option>
                {innings.map((inn) => (
                  <option key={inn.key} value={inn.i}>
                    {halfLabel(inn.play)}
                  </option>
                ))}
              </select>
            </label>
          </CardContent>
        </Card>
        <PlayLog doc={doc} order={order} idx={idx} done={done} onPick={goTo} />
      </div>
    </div>
  );
}

function Segmented({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-12 text-xs text-muted">{label}</span>
      <div className="inline-flex rounded-lg border border-border p-0.5" role="radiogroup" aria-label={label}>
        {options.map((opt) => (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={value === opt.value}
            onClick={() => onChange(opt.value)}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition",
              value === opt.value ? "bg-amber text-espresso" : "text-muted hover:text-ink",
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function Scoreboard({
  doc,
  line,
  play,
  done,
  score,
}: {
  doc: GamePlaysDoc;
  line: ReturnType<typeof lineScore>;
  play: GamePlay;
  done: boolean;
  score: { away: number; home: number };
}) {
  const outs = done ? play.outs_after : play.outs;
  const bases = done ? play.bases_after : play.bases_before;
  const count = done ? play.count_after : play.count;
  const cols = Array.from({ length: line.innings }, (_, i) => i + 1);
  const rows: { side: "away" | "home"; name: string; runs: (number | null)[]; r: number; h: number }[] = [
    {
      side: "away",
      name: doc.game.away_name || doc.game.away || "Away",
      runs: line.away,
      r: score.away,
      h: line.awayHits,
    },
    {
      side: "home",
      name: doc.game.home_name || doc.game.home || "Home",
      runs: line.home,
      r: score.home,
      h: line.homeHits,
    },
  ];
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex flex-wrap items-center gap-3 text-sm">
          <span>{halfLabel(play)}</span>
          <span className="text-muted">·</span>
          <span>
            {outs} out{outs === 1 ? "" : "s"}
          </span>
          {outs < 3 ? (
            <>
              <span className="text-muted">·</span>
              <span>Count {count}</span>
            </>
          ) : null}
          <BasesDiamond bases={bases} />
        </CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto pt-0">
        <table className="w-full text-[11px] tabular-nums">
          <thead>
            <tr className="text-muted">
              <th className="py-1 pr-2 text-left font-medium">Team</th>
              {cols.map((c) => (
                <th key={c} className="py-1 text-center font-medium">
                  {c}
                </th>
              ))}
              <th className="w-6 py-1 text-center font-semibold">R</th>
              <th className="w-6 py-1 text-center font-semibold">H</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.side}
                className={cn("border-t border-border", play.batting === row.side && "text-amber-text")}
              >
                <td className="max-w-[6.5rem] truncate py-1 pr-2 font-semibold">{row.name}</td>
                {cols.map((c) => (
                  <td key={c} className="py-1 text-center">
                    {row.runs[c - 1] ?? ""}
                  </td>
                ))}
                <td className="py-1 text-center font-bold">{row.r}</td>
                <td className="py-1 text-center">{row.h}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function BasesDiamond({ bases }: { bases: (string | null)[] }) {
  const on = (i: number) => Boolean(bases[i]);
  const square = (x: number, y: number, filled: boolean, key: string) => (
    <rect
      key={key}
      x={x - 4}
      y={y - 4}
      width={8}
      height={8}
      transform={`rotate(45 ${x} ${y})`}
      className={filled ? "fill-amber stroke-amber" : "fill-transparent stroke-muted"}
      strokeWidth={1.5}
    />
  );
  return (
    <svg width={34} height={24} viewBox="0 0 34 24" role="img" aria-label={`Runners: ${
      [0, 1, 2].filter(on).map((i) => ordinal(i + 1)).join(", ") || "none"
    }`}>
      {square(17, 6, on(1), "2")}
      {square(27, 15, on(0), "1")}
      {square(7, 15, on(2), "3")}
    </svg>
  );
}

function PitchInset({ play, shown }: { play: GamePlay; shown: boolean }) {
  const pitch = play.pitch;
  if (!pitch) return null;
  // Catcher's view: the zone 17 in wide (±0.71 ft), 1.6 to 3.5 ft high.
  const W = 96;
  const H = 104;
  const sx = (x: number) => W / 2 + x * 26;
  const sz = (z: number) => H - 10 - z * 22;
  const name = PITCH_NAMES[pitch.type ?? ""] ?? (pitch.type ?? "Pitch").toUpperCase();
  const call = CALL_WORDS[pitch.call ?? ""] ?? pitch.call ?? "";
  return (
    <div className="flex items-center gap-3">
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="shrink-0 rounded-md bg-surfaceAlt">
        <rect
          x={sx(-0.71)}
          y={sz(3.5)}
          width={sx(0.71) - sx(-0.71)}
          height={sz(1.6) - sz(3.5)}
          className="fill-transparent stroke-muted"
          strokeWidth={1.5}
        />
        {shown ? (
          <circle
            cx={Math.max(6, Math.min(W - 6, sx(pitch.x)))}
            cy={Math.max(6, Math.min(H - 6, sz(pitch.z)))}
            r={5}
            className={cn(
              pitch.call === "ball" ? "fill-success" : pitch.call === "in_play" ? "fill-amber" : "fill-danger",
            )}
          />
        ) : null}
      </svg>
      <div className="text-xs">
        <div className="font-semibold text-ink">
          {pitch.mph ? `${Math.round(pitch.mph)} mph ` : ""}
          {name}
        </div>
        <div className="text-muted">{shown ? call : "Count " + play.count}</div>
      </div>
    </div>
  );
}

function PlayLog({
  doc,
  order,
  idx,
  done,
  onPick,
}: {
  doc: GamePlaysDoc;
  order: number[];
  idx: number;
  done: boolean;
  onPick: (i: number) => void;
}) {
  // Only what has happened so far: no spoilers.
  const seen = order.filter((i) => i < idx || (i === idx && done));
  const shown = seen.filter((i) => doc.plays[i]?.key).reverse().slice(0, 80);
  return (
    <Card className="min-h-0">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Play by play</CardTitle>
      </CardHeader>
      <CardContent className="max-h-[420px] space-y-1 overflow-y-auto pt-0">
        {shown.length === 0 ? (
          <p className="text-xs text-muted">Plays appear here as you watch.</p>
        ) : (
          shown.map((i, k) => {
            const play = doc.plays[i]!;
            const prevIdx = shown[k - 1];
            const prevShown = prevIdx !== undefined ? doc.plays[prevIdx] : undefined;
            const newHalf =
              !prevShown || prevShown.inning !== play.inning || prevShown.half !== play.half;
            return (
              <div key={i}>
                {newHalf ? (
                  <div className="pt-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
                    {halfLabel(play)}
                  </div>
                ) : null}
                <button
                  type="button"
                  onClick={() => onPick(i)}
                  className={cn(
                    "w-full rounded-md px-2 py-1 text-left text-xs transition hover:bg-surfaceAlt",
                    i === idx ? "bg-amber/10 text-ink" : "text-ink/85",
                  )}
                >
                  {play.text}
                  {play.scored.length ? (
                    <span className="ml-1 font-semibold text-amber-text">
                      ({play.score.away}–{play.score.home})
                    </span>
                  ) : null}
                </button>
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}
