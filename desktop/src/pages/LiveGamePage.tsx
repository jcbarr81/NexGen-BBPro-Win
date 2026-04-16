/**
 * Phase 5 iteration 1: Live game simulation.
 *
 * Pre-game: user picks home + away teams. Start opens a WebSocket to
 * /ws/sim/<gameId>, which runs the sim server-side and streams pitches at a
 * configurable pace. During play we render a scoreboard, the current
 * matchup, and a scrolling pitch feed. A pause/resume/skip/speed control
 * strip lets the user pace the game to taste.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  FastForward,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  SkipForward,
} from "lucide-react";

import { api, type SimEvent, type SimPitchEvent, type Team } from "@/lib/api";
import { openSimSocket, type SimConnection } from "@/lib/sim-socket";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";

type Status = "idle" | "running" | "paused" | "finished" | "error";

interface SimState {
  status: Status;
  seq: number;
  total: number;
  gameMeta: {
    away: string;
    home: string;
    park: string | null;
  } | null;
  lastPitch: SimPitchEvent | null;
  feed: SimPitchEvent[];
  totals: Record<string, number> | null;
  error: string | null;
}

const INITIAL_STATE: SimState = {
  status: "idle",
  seq: 0,
  total: 0,
  gameMeta: null,
  lastPitch: null,
  feed: [],
  totals: null,
  error: null,
};

const SPEED_OPTIONS: Array<{ label: string; ms: number }> = [
  { label: "Fast", ms: 80 },
  { label: "Normal", ms: 250 },
  { label: "Slow", ms: 600 },
];

// Keep the in-memory feed bounded so a 300-pitch game doesn't balloon the
// DOM. We still stream through each one, just drop the oldest in the buffer.
const FEED_WINDOW = 40;

export function LiveGamePage() {
  const user = useAuthStore();
  const myTeamId = user.selectedTeamId ?? user.teamId ?? null;

  const teams = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
  });

  const [away, setAway] = useState<string>("");
  const [home, setHome] = useState<string>("");
  const [speedMs, setSpeedMs] = useState<number>(250);
  const [sim, setSim] = useState<SimState>(INITIAL_STATE);
  const connRef = useRef<SimConnection | null>(null);

  // Bootstrap defaults once teams are loaded.
  useEffect(() => {
    if (!teams.data || teams.data.length < 2) return;
    if (!home) setHome(myTeamId ?? teams.data[0]!.team_id);
    if (!away) {
      const other = teams.data.find((t) => t.team_id !== (myTeamId ?? teams.data![0]!.team_id));
      if (other) setAway(other.team_id);
    }
  }, [teams.data, myTeamId, home, away]);

  useEffect(() => {
    return () => {
      connRef.current?.close();
    };
  }, []);

  function handleEvent(event: SimEvent) {
    setSim((prev) => {
      switch (event.type) {
        case "start":
          return {
            ...prev,
            status: "running",
            seq: 0,
            total: event.total_pitches,
            gameMeta: {
              away: event.away,
              home: event.home,
              park: event.park,
            },
            lastPitch: null,
            feed: [],
            totals: null,
            error: null,
          };
        case "pitch": {
          const nextFeed = [...prev.feed, event];
          if (nextFeed.length > FEED_WINDOW) nextFeed.splice(0, nextFeed.length - FEED_WINDOW);
          return {
            ...prev,
            seq: event.seq,
            total: event.total,
            lastPitch: event,
            feed: nextFeed,
          };
        }
        case "final":
          return {
            ...prev,
            status: "finished",
            totals: event.totals,
          };
        case "error":
          return {
            ...prev,
            status: "error",
            error: event.message,
          };
        default:
          return prev;
      }
    });
  }

  function startGame() {
    if (!away || !home || away === home) return;
    connRef.current?.close();
    setSim({ ...INITIAL_STATE, status: "running" });
    connRef.current = openSimSocket(
      { away, home, speedMs },
      {
        onEvent: handleEvent,
        onClose: () =>
          setSim((prev) =>
            prev.status === "running" || prev.status === "paused"
              ? { ...prev, status: prev.totals ? "finished" : "idle" }
              : prev,
          ),
        onError: () =>
          setSim((prev) => ({
            ...prev,
            status: "error",
            error: prev.error ?? "WebSocket error",
          })),
      },
    );
  }

  function pauseGame() {
    connRef.current?.pause();
    setSim((prev) => ({ ...prev, status: "paused" }));
  }
  function resumeGame() {
    connRef.current?.resume();
    setSim((prev) => ({ ...prev, status: "running" }));
  }
  function skipGame() {
    connRef.current?.skip();
  }
  function changeSpeed(ms: number) {
    setSpeedMs(ms);
    connRef.current?.setSpeed(ms);
  }
  function resetGame() {
    connRef.current?.close();
    connRef.current = null;
    setSim(INITIAL_STATE);
  }

  return (
    <AppShell
      title="Live Game"
      subtitle="Run a matchup and watch the pitch-by-pitch stream."
    >
      <div className="space-y-6 animate-fade-in">
        <MatchupCard
          teams={teams.data ?? []}
          away={away}
          home={home}
          onPickAway={setAway}
          onPickHome={setHome}
          disabled={sim.status === "running" || sim.status === "paused"}
        />

        <ScoreboardCard sim={sim} teams={teams.data ?? []} />

        <ControlsStrip
          status={sim.status}
          canStart={!!away && !!home && away !== home}
          speedMs={speedMs}
          onStart={startGame}
          onPause={pauseGame}
          onResume={resumeGame}
          onSkip={skipGame}
          onReset={resetGame}
          onSpeed={changeSpeed}
        />

        <PitchFeedCard sim={sim} />

        {sim.status === "finished" && sim.totals && (
          <TotalsCard totals={sim.totals} />
        )}
      </div>
    </AppShell>
  );
}

function MatchupCard({
  teams,
  away,
  home,
  onPickAway,
  onPickHome,
  disabled,
}: {
  teams: Team[];
  away: string;
  home: string;
  onPickAway: (id: string) => void;
  onPickHome: (id: string) => void;
  disabled: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Matchup</CardTitle>
          <CardDescription>
            Pick the away team and the home team. Same team twice is not allowed.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-4 md:grid-cols-[1fr_auto_1fr] md:items-end">
        <TeamPicker
          label="Away"
          value={away}
          teams={teams}
          onChange={onPickAway}
          disabled={disabled}
          exclude={home}
        />
        <div className="text-center font-display text-2xl text-muted">@</div>
        <TeamPicker
          label="Home"
          value={home}
          teams={teams}
          onChange={onPickHome}
          disabled={disabled}
          exclude={away}
        />
      </CardContent>
    </Card>
  );
}

function TeamPicker({
  label,
  value,
  teams,
  onChange,
  disabled,
  exclude,
}: {
  label: string;
  value: string;
  teams: Team[];
  onChange: (id: string) => void;
  disabled: boolean;
  exclude?: string;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
        {label}
      </span>
      <select
        value={value}
        disabled={disabled || teams.length === 0}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 rounded-lg border border-border bg-canvas/60 px-3 text-sm text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
      >
        <option value="">— select —</option>
        {teams
          .filter((t) => t.team_id !== exclude)
          .map((t) => (
            <option key={t.team_id} value={t.team_id}>
              {t.city} {t.name} ({t.abbreviation})
            </option>
          ))}
      </select>
    </label>
  );
}

function ScoreboardCard({ sim, teams }: { sim: SimState; teams: Team[] }) {
  const awayMeta = useMemo(
    () => teams.find((t) => t.team_id === sim.gameMeta?.away) ?? null,
    [teams, sim.gameMeta?.away],
  );
  const homeMeta = useMemo(
    () => teams.find((t) => t.team_id === sim.gameMeta?.home) ?? null,
    [teams, sim.gameMeta?.home],
  );

  const progress = sim.total > 0 ? Math.round((sim.seq / sim.total) * 100) : 0;

  return (
    <Card className="p-6">
      <div className="relative flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-6">
          <TeamBadge team={awayMeta} fallback={sim.gameMeta?.away ?? "Away"} />
          <div className="text-center">
            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
              {sim.status === "idle" ? "Ready" : sim.status === "error" ? "Error" : sim.status}
            </div>
            <div className="font-display text-2xl font-bold text-amber-text">@</div>
          </div>
          <TeamBadge team={homeMeta} fallback={sim.gameMeta?.home ?? "Home"} />
        </div>

        <div className="min-w-[220px] space-y-2">
          <div className="flex items-center justify-between text-xs text-muted">
            <span>Pitch {sim.seq}</span>
            <span>{sim.total || "—"}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-surfaceAlt">
            <div
              className="h-full bg-amber transition-[width] duration-150"
              style={{ width: `${progress}%` }}
            />
          </div>
          {sim.lastPitch?.data.count && (
            <div className="flex items-center justify-between text-xs text-muted">
              <span>Count</span>
              <span className="font-mono font-semibold text-ink">
                {sim.lastPitch.data.count}
              </span>
            </div>
          )}
        </div>
      </div>

      {sim.error && (
        <div className="mt-4 flex items-center gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          <AlertTriangle className="h-4 w-4" /> {sim.error}
        </div>
      )}
    </Card>
  );
}

function TeamBadge({ team, fallback }: { team: Team | null; fallback: string }) {
  return (
    <div className="flex items-center gap-3">
      <div
        className="flex h-12 w-12 items-center justify-center rounded-xl border border-border font-display text-lg font-bold"
        style={{
          backgroundColor: team?.primary_color ?? "hsl(var(--surface-alt))",
          color: team?.secondary_color ?? "hsl(var(--ink))",
        }}
      >
        {team?.abbreviation ?? fallback.slice(0, 3).toUpperCase()}
      </div>
      <div className="min-w-0">
        <div className="font-display text-base font-bold">
          {team ? `${team.city} ${team.name}` : fallback}
        </div>
        {team && (
          <div className="text-xs text-muted">{team.division}</div>
        )}
      </div>
    </div>
  );
}

interface ControlsProps {
  status: Status;
  canStart: boolean;
  speedMs: number;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onSkip: () => void;
  onReset: () => void;
  onSpeed: (ms: number) => void;
}

function ControlsStrip({
  status,
  canStart,
  speedMs,
  onStart,
  onPause,
  onResume,
  onSkip,
  onReset,
  onSpeed,
}: ControlsProps) {
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
        <div className="flex items-center gap-2">
          {status === "idle" || status === "finished" || status === "error" ? (
            <Button onClick={onStart} disabled={!canStart}>
              <Play className="h-4 w-4" />
              {status === "finished" ? "Replay" : "Play"}
            </Button>
          ) : status === "paused" ? (
            <Button onClick={onResume}>
              <Play className="h-4 w-4" /> Resume
            </Button>
          ) : (
            <Button variant="secondary" onClick={onPause}>
              <Pause className="h-4 w-4" /> Pause
            </Button>
          )}

          <Button
            variant="outline"
            onClick={onSkip}
            disabled={status !== "running" && status !== "paused"}
          >
            <SkipForward className="h-4 w-4" /> Skip
          </Button>

          <Button variant="ghost" onClick={onReset}>
            <RefreshCw className="h-4 w-4" /> Reset
          </Button>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
            Speed
          </span>
          <div className="flex rounded-lg border border-border bg-surfaceAlt p-1">
            {SPEED_OPTIONS.map((opt) => (
              <button
                key={opt.ms}
                type="button"
                onClick={() => onSpeed(opt.ms)}
                className={cn(
                  "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
                  speedMs === opt.ms
                    ? "bg-amber text-espresso"
                    : "text-muted hover:bg-surface hover:text-ink",
                )}
              >
                <FastForward className="inline h-3 w-3" /> {opt.label}
              </button>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function PitchFeedCard({ sim }: { sim: SimState }) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = scrollerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [sim.feed.length]);

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Pitch Feed</CardTitle>
          <CardDescription>Most recent {FEED_WINDOW} pitches</CardDescription>
        </div>
        <Badge tone="amber">
          {sim.status === "running" && (
            <Loader2 className="h-3 w-3 animate-spin" />
          )}
          {sim.status.toUpperCase()}
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        <div
          ref={scrollerRef}
          className="max-h-[360px] overflow-y-auto font-mono text-xs"
        >
          {sim.feed.length === 0 ? (
            <div className="px-6 py-6 text-muted">
              {sim.status === "idle"
                ? "Waiting for game to start…"
                : "Buffering…"}
            </div>
          ) : (
            <ul className="divide-y divide-border/50">
              {sim.feed.map((p) => (
                <PitchRow key={p.seq} pitch={p} />
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function PitchRow({ pitch }: { pitch: SimPitchEvent }) {
  const d = pitch.data;
  const outcome = String(d.outcome ?? "pitch");
  const tone =
    outcome.includes("out") || outcome === "k"
      ? "text-danger"
      : outcome.includes("hit") || outcome === "bb" || outcome === "hbp"
        ? "text-success"
        : "text-ink";
  return (
    <li className="flex items-center gap-4 px-6 py-2">
      <span className="w-10 text-right tabular-nums text-muted">
        #{pitch.seq}
      </span>
      <span className="w-14 text-muted">{d.count ?? ""}</span>
      <span className={cn("min-w-24 font-semibold", tone)}>{outcome}</span>
      <span className="text-muted">
        {String(d.pitch_type ?? "")}
        {d.zone ? ` · z${d.zone}` : ""}
      </span>
      <span className="ml-auto text-muted">
        {d.runner_event ? `→ ${d.runner_event}` : ""}
      </span>
    </li>
  );
}

function TotalsCard({ totals }: { totals: Record<string, number> }) {
  // Headline numbers first; the rest collapse into a compact grid.
  const headline: Array<{ key: string; label: string }> = [
    { key: "r_away", label: "R (Away)" },
    { key: "r_home", label: "R (Home)" },
    { key: "h", label: "Hits" },
    { key: "hr", label: "HR" },
    { key: "k", label: "Strikeouts" },
    { key: "bb", label: "Walks" },
    { key: "pitches", label: "Pitches" },
  ];
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Final</CardTitle>
          <CardDescription>Totals from the simulated game</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {headline.map((item) => (
            <div key={item.key} className="rounded-xl border border-border bg-surfaceAlt/50 p-3">
              <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
                {item.label}
              </div>
              <div className="font-display text-2xl font-bold text-amber-text">
                {totals[item.key] ?? 0}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
