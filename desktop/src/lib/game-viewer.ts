/**
 * Game viewer (backlog #74): types for the server's timed plays
 * (`GET /boxscore/replay/plays`, services/replay_plays.py, schema
 * "nexgen.plays/1") and the pure helpers the 2D field and the page share.
 *
 * Frame: feet, home plate at the origin, +y toward center field through
 * second base, +x toward first base / right field.
 */

export type BallPoint = [number, number, number, number]; // t, x, y, z
export type PathPoint = [number, number, number]; // t, x, y

export interface RunnerTrack {
  who: string;
  role: "batter" | "runner";
  from: number;
  to: number; // 1-3 safe at, 4 scored, 0 out
  out_at?: number;
  replaced?: string;
  path: PathPoint[];
}

export interface PlayCue {
  t: number;
  type: string;
  who?: string | null;
  by?: string;
  to?: string;
  base?: number | null;
  kind?: string;
  foul?: boolean;
}

export interface PitchInfo {
  type?: string | null;
  mph?: number | null;
  x: number;
  z: number;
  call?: string | null;
  swing?: boolean;
  in_zone?: boolean;
}

export interface GamePlay {
  i: number;
  inning: number;
  half: "top" | "bottom";
  batting: "away" | "home";
  outs: number;
  outs_after: number;
  count: string;
  count_after: string;
  batter?: string | null;
  pitcher?: string | null;
  bases_before: (string | null)[];
  bases_after: (string | null)[];
  scored: string[];
  score: { away: number; home: number };
  pa_end: boolean;
  key: boolean;
  result?: string | null;
  text: string;
  dur: number;
  ball: BallPoint[];
  fielders: Record<string, PathPoint[]>;
  runners: RunnerTrack[];
  cues: PlayCue[];
  pitch?: PitchInfo;
}

export interface PlayerInfo {
  name?: string;
  bats?: string;
  throws?: string;
  pos?: string;
}

export interface GamePlaysDoc {
  schema: string;
  game: {
    date?: string;
    home?: string;
    away?: string;
    home_name?: string;
    away_name?: string;
    park?: string;
    postseason?: boolean;
  };
  players: Record<string, PlayerInfo>;
  final: { score?: { away: number; home: number }; innings?: number };
  field: {
    fence: { distances: number[]; heights: number[]; angles: number[] };
    bases: Record<string, [number, number]>;
    rubber: [number, number];
    positions: Record<string, [number, number]>;
  };
  plays: GamePlay[];
}

export type ViewMode = "key" | "all";

export const POSITIONS = ["P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"] as const;

/** Linear position on a timed path; holds its ends outside them. */
export function pathAt(path: PathPoint[], t: number): [number, number] {
  const first = path[0];
  if (!first) return [0, 0];
  if (t <= first[0]) return [first[1], first[2]];
  let prev: PathPoint = first;
  for (let k = 1; k < path.length; k += 1) {
    const point = path[k]!;
    const [t1, x1, y1] = point;
    if (t <= t1) {
      const [t0, x0, y0] = prev;
      const f = t1 <= t0 ? 1 : (t - t0) / (t1 - t0);
      return [x0 + (x1 - x0) * f, y0 + (y1 - y0) * f];
    }
    prev = point;
  }
  return [prev[1], prev[2]];
}

/** The ball at ``t``; null before its first point. */
export function ballAt(ball: BallPoint[], t: number): [number, number, number] | null {
  const first = ball[0];
  if (!first || t < first[0]) return null;
  let prev: BallPoint = first;
  for (let k = 1; k < ball.length; k += 1) {
    const point = ball[k]!;
    const [t1, x1, y1, z1] = point;
    if (t <= t1) {
      const [t0, x0, y0, z0] = prev;
      const f = t1 <= t0 ? 1 : (t - t0) / (t1 - t0);
      return [x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, z0 + (z1 - z0) * f];
    }
    prev = point;
  }
  return [prev[1], prev[2], prev[3]];
}

/** The fence distance at a spray angle (degrees, + toward right field). */
export function fenceAt(fence: GamePlaysDoc["field"]["fence"], angle: number): number {
  const a = Math.max(-45, Math.min(45, angle));
  const pos = (a + 45) / 22.5;
  const idx = Math.min(3, Math.floor(pos));
  const frac = pos - idx;
  const d = fence.distances;
  return (d[idx] ?? 400) * (1 - frac) + (d[idx + 1] ?? 400) * frac;
}

/** Indexes of the plays a mode shows: every play, or the key ones (the
 *  pitch each plate appearance's result happened on, plus steals, wild
 *  pitches and anything else that moved a runner). */
export function playsForMode(plays: GamePlay[], mode: ViewMode): number[] {
  const out: number[] = [];
  plays.forEach((play, idx) => {
    if (mode === "all" || play.key) out.push(idx);
  });
  return out;
}

export interface LineScore {
  innings: number;
  away: (number | null)[];
  home: (number | null)[];
  awayRuns: number;
  homeRuns: number;
  awayHits: number;
  homeHits: number;
}

const HIT_RESULTS = new Set(["1b", "2b", "3b", "hr"]);

/** The line score through play ``upTo`` (inclusive; all plays when
 *  omitted). An inning not yet reached is null. */
export function lineScore(plays: GamePlay[], upTo?: number): LineScore {
  const last = upTo === undefined ? plays.length - 1 : upTo;
  const innings = Math.max(9, ...plays.map((p) => p.inning));
  const away: (number | null)[] = Array(innings).fill(null);
  const home: (number | null)[] = Array(innings).fill(null);
  let awayHits = 0;
  let homeHits = 0;
  for (let k = 0; k <= last && k < plays.length; k += 1) {
    const play = plays[k]!;
    const row = play.batting === "away" ? away : home;
    const idx = play.inning - 1;
    row[idx] = (row[idx] ?? 0) + play.scored.length;
    if (play.pa_end && play.result && HIT_RESULTS.has(play.result)) {
      if (play.batting === "away") awayHits += 1;
      else homeHits += 1;
    }
  }
  const sum = (row: (number | null)[]) => row.reduce<number>((acc, v) => acc + (v ?? 0), 0);
  return {
    innings,
    away,
    home,
    awayRuns: sum(away),
    homeRuns: sum(home),
    awayHits,
    homeHits,
  };
}

export function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
}

export function halfLabel(play: Pick<GamePlay, "half" | "inning">): string {
  return `${play.half === "top" ? "Top" : "Bottom"} ${ordinal(play.inning)}`;
}

export function playerName(doc: GamePlaysDoc, pid?: string | null): string {
  if (!pid) return "";
  return doc.players[pid]?.name || pid;
}

export function lastName(doc: GamePlaysDoc, pid?: string | null): string {
  const name = playerName(doc, pid);
  const parts = name.split(" ");
  return parts[parts.length - 1] || name;
}

/** When a play has finished moving (its last cue or path end), before the
 *  hold the server leaves at the end. */
export function playEnd(play: GamePlay): number {
  return Math.max(0, play.dur - 0.6);
}

export interface FigureState {
  who: string;
  x: number;
  y: number;
  alpha: number;
  role: "batter" | "runner";
}

const FADE = 0.7;

/** Where the batter and the runners are at ``t``: from the play's tracks,
 *  else standing on their bases (and the batter at the plate). A runner
 *  put out, or one who scored, fades after it happens. */
export function figuresAt(doc: GamePlaysDoc, play: GamePlay, t: number): FigureState[] {
  const out: FigureState[] = [];
  const tracked = new Set<string>();
  const outTimes = new Map<string, number>();
  for (const cue of play.cues) {
    if (cue.type === "out" && cue.who) outTimes.set(cue.who, cue.t);
  }
  for (const rec of play.runners) {
    tracked.add(rec.who);
    if (rec.replaced) tracked.add(rec.replaced);
    const [x, y] = pathAt(rec.path, t);
    let alpha = 1;
    const endT = rec.path[rec.path.length - 1]?.[0] ?? 0;
    if (rec.to === 0) {
      const when = outTimes.get(rec.who) ?? endT;
      if (t > when) alpha = Math.max(0, 1 - (t - when) / (FADE * 1.6));
    } else if (rec.to === 4 && t > endT) {
      alpha = Math.max(0, 1 - (t - endT) / FADE);
    }
    out.push({ who: rec.who, x, y, alpha, role: rec.role });
  }
  play.bases_before.forEach((pid, idx) => {
    if (!pid || tracked.has(pid)) return;
    const [x, y] = doc.field.bases[String(idx + 1)] ?? [0, 0];
    out.push({ who: pid, x, y, alpha: 1, role: "runner" });
  });
  if (play.batter && !tracked.has(play.batter)) {
    const bats = doc.players[play.batter]?.bats ?? "R";
    const pitcherThrows = play.pitcher ? doc.players[play.pitcher]?.throws ?? "R" : "R";
    const side = bats === "L" || (bats === "S" && pitcherThrows === "R") ? 3 : -3;
    let alpha = 1;
    const when = outTimes.get(play.batter);
    if (when !== undefined && t > when) alpha = Math.max(0, 1 - (t - when) / (FADE * 1.6));
    out.push({ who: play.batter, x: side, y: 0.5, alpha, role: "batter" });
  }
  return out;
}

/** The cues worth a word on the field ("OUT", "SAFE", ...), with where
 *  to show them, active at ``t``. */
export interface Callout {
  text: string;
  x: number;
  y: number;
  alpha: number;
  tone: "out" | "safe" | "big" | "info";
}

export function calloutsAt(doc: GamePlaysDoc, play: GamePlay, t: number): Callout[] {
  const out: Callout[] = [];
  const life = 1.1;
  for (const cue of play.cues) {
    const age = t - cue.t;
    if (age < 0 || age > life) continue;
    const alpha = age < 0.15 ? age / 0.15 : Math.max(0, 1 - (age - 0.6) / 0.5);
    let text = "";
    let tone: Callout["tone"] = "info";
    let at: [number, number] | null = null;
    if (cue.type === "out") {
      text = "OUT";
      tone = "out";
      if (cue.base) {
        at = doc.field.bases[String(cue.base === 4 ? 0 : cue.base)] ?? null;
      } else {
        // Out on a catch: over the fielder who caught it.
        const caught = play.cues.find(
          (c) => c.type === "catch" && c.by && Math.abs(c.t - cue.t) < 0.01,
        );
        const path = caught?.by ? play.fielders[caught.by] : undefined;
        at = path ? pathAt(path, cue.t) : [0, 8];
      }
    } else if (cue.type === "safe") {
      text = "SAFE";
      tone = "safe";
      at = cue.base ? doc.field.bases[String(cue.base === 4 ? 0 : cue.base)] ?? null : null;
    } else if (cue.type === "score") {
      text = "RUN";
      tone = "safe";
      at = [0, -10];
    } else if (cue.type === "home_run") {
      text = "HOME RUN!";
      tone = "big";
      at = [0, 200];
    } else if (cue.type === "error") {
      text = "ERROR";
      tone = "out";
      at = cue.by ? doc.field.positions[cue.by] ?? null : null;
    } else if (cue.type === "strikeout") {
      text = cue.kind === "called" ? "CALLED STRIKE 3" : "STRIKE 3";
      tone = "out";
      at = [0, 20];
    } else if (cue.type === "past") {
      text = (cue.kind || "wild pitch").toUpperCase();
      tone = "info";
      at = [0, -18];
    } else if (cue.type === "balk") {
      text = "BALK";
      at = [0, 75];
    }
    if (text && at) out.push({ text, x: at[0], y: at[1], alpha, tone });
  }
  return out;
}
