/**
 * Phase 4 port of ui/playoffs_window.py.
 *
 * Renders each playoffs_<year>.json as a bracket: one column per round,
 * matchup cards showing both seeds, current/final series score, and the
 * game log. Champion banner appears once a winner is recorded.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Crown,
  FastForward,
  Loader2,
  Medal,
  Play,
  RefreshCw,
  Trophy,
} from "lucide-react";

import {
  api,
  type PlayoffGame,
  type PlayoffMatchup,
  type PlayoffRound,
  type Playoffs,
} from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import { Badge, Button, Card, CardContent } from "@/components/ui";

export function PlayoffsPage() {
  const myTeamId = useAuthStore((s) => s.selectedTeamId ?? s.teamId ?? null);
  const [year, setYear] = useState<number | null>(null);

  const years = useQuery({
    queryKey: ["playoff-years"],
    queryFn: () => api.playoffYears(),
  });
  const playoffs = useQuery({
    queryKey: ["playoffs", year],
    queryFn: () => api.playoffs(year ?? undefined),
    enabled: years.isSuccess && (years.data.years.length > 0 || year !== null),
  });

  // Default to latest once the years list lands.
  useEffect(() => {
    if (year === null && years.data?.latest) {
      setYear(years.data.latest);
    }
  }, [years.data, year]);

  if (years.isLoading) {
    return (
      <AppShell title="Playoffs">
        <LoadingCard />
      </AppShell>
    );
  }
  if (years.isError) {
    return (
      <AppShell title="Playoffs">
        <ErrorCard message={(years.error as Error).message} />
      </AppShell>
    );
  }
  if (!years.data || years.data.years.length === 0) {
    return (
      <AppShell title="Playoffs">
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <Trophy className="h-10 w-10 text-amber" />
            <h2 className="font-display text-xl">No playoff data</h2>
            <p className="max-w-sm text-sm text-muted">
              No ``playoffs_&lt;year&gt;.json`` files have been written yet.
              Finish a postseason in the legacy app and check back here.
            </p>
          </CardContent>
        </Card>
      </AppShell>
    );
  }

  return (
    <AppShell
      title="Playoffs"
      subtitle={playoffs.data ? `${playoffs.data.year} postseason` : "Loading…"}
    >
      <div className="mb-4 flex items-center justify-between gap-4">
        <YearPicker
          years={years.data.years}
          value={year}
          onChange={setYear}
        />
        {playoffs.data?.champion && (
          <Badge tone="amber">
            <Crown className="h-3 w-3" /> {playoffs.data.champion} champions
          </Badge>
        )}
      </div>

      {playoffs.isLoading ? (
        <LoadingCard />
      ) : playoffs.isError ? (
        <ErrorCard message={(playoffs.error as Error).message} />
      ) : playoffs.data ? (
        <div className="space-y-6">
          {playoffs.data.champion ? (
            <ChampionBanner playoffs={playoffs.data} />
          ) : (
            // Only the latest, in-progress bracket can be advanced.
            year === years.data.latest && (
              <PlayoffControls playoffs={playoffs.data} />
            )
          )}
          <Bracket rounds={playoffs.data.rounds} myTeamId={myTeamId} />
        </div>
      ) : null}
    </AppShell>
  );
}

/** Friendly bracket-round labels. Backend round names are terse and may carry
 *  a placeholder single-league prefix (e.g. "LEAGUE DS"); show readable names. */
function prettyRoundName(name: string): string {
  const stripped = name.replace(/^league\s+/i, "").trim();
  const map: Record<string, string> = {
    WC: "Wild Card",
    DS: "Division Series",
    CS: "Championship Series",
    WS: "World Series",
    FINAL: "Final",
  };
  return map[stripped.toUpperCase()] ?? stripped;
}

type RoundStage = "WC" | "DS" | "CS" | "WS" | "OTHER";

/** Split a round name into its league (if any) and its stage, so a two-league
 *  postseason ("American League WC", "National League CS", "WS") can be laid out
 *  as a mirrored bracket funnelling into the World Series. */
function classifyRound(name: string): {
  league: string | null;
  stage: RoundStage;
  order: number;
} {
  const n = name.trim();
  if (n.toUpperCase() === "WS" || /world series/i.test(n)) {
    return { league: null, stage: "WS", order: 4 };
  }
  let stage: RoundStage = "OTHER";
  let order = 2;
  if (/\bwc\b|wild ?card/i.test(n)) {
    stage = "WC";
    order = 1;
  } else if (/\bds\b|division series/i.test(n)) {
    stage = "DS";
    order = 2;
  } else if (/\bcs\b|championship series/i.test(n)) {
    stage = "CS";
    order = 3;
  }
  const league =
    n
      .replace(/\b(wc|ds|cs)\b/i, "")
      .replace(/wild ?card|division series|championship series/i, "")
      .replace(/^league\s+/i, "")
      .trim() || null;
  return { league, stage, order };
}

/** Just the stage label (league shown separately in the bracket header). */
function stageLabel(name: string): string {
  const { stage } = classifyRound(name);
  const map: Record<RoundStage, string> = {
    WC: "Wild Card",
    DS: "Division Series",
    CS: "Championship Series",
    WS: "World Series",
    OTHER: prettyRoundName(name),
  };
  return map[stage];
}

function hasPlayedGames(playoffs: Playoffs): boolean {
  return playoffs.rounds.some((r) =>
    r.matchups.some((m) => m.games.some((g) => !!g.result)),
  );
}

function PlayoffControls({ playoffs }: { playoffs: Playoffs }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const onDone = () => {
    setError(null);
    // Refresh the bracket and the season state (so the Season page's Advance
    // Phase button unlocks the instant a champion is crowned).
    queryClient.invalidateQueries({ queryKey: ["playoffs"] });
    queryClient.invalidateQueries({ queryKey: ["playoff-years"] });
    queryClient.invalidateQueries({ queryKey: ["season-state"] });
  };
  const onErr = (e: unknown) => setError((e as Error).message);

  const simGame = useMutation({
    mutationFn: () => api.simulatePlayoffGame(),
    onSuccess: onDone,
    onError: onErr,
  });
  const simRound = useMutation({
    mutationFn: () => api.simulatePlayoffRound(),
    onSuccess: onDone,
    onError: onErr,
  });
  const simAll = useMutation({
    mutationFn: () => api.simulatePlayoffAll(),
    onSuccess: onDone,
    onError: onErr,
  });
  const rebuild = useMutation({
    mutationFn: () => api.rebuildPlayoffs(4),
    onSuccess: onDone,
    onError: onErr,
  });

  const busy =
    simGame.isPending ||
    simRound.isPending ||
    simAll.isPending ||
    rebuild.isPending;
  // Rebuilding regenerates the bracket from standings; only safe before any
  // game is played (the backend enforces this too).
  const canRebuild = !hasPlayedGames(playoffs);

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 py-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h3 className="font-display text-lg">Simulate the postseason</h3>
            <p className="text-sm text-muted">
              Advance the bracket a day, a full round, or straight through to a
              champion. Games use the same physics engine as the regular season.
            </p>
          </div>
          {busy && <Loader2 className="h-5 w-5 shrink-0 animate-spin text-amber" />}
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Button onClick={() => simGame.mutate()} disabled={busy} className="w-full">
            <Play className="h-4 w-4" /> Sim Next Game
          </Button>
          <Button
            variant="secondary"
            onClick={() => simRound.mutate()}
            disabled={busy}
            className="w-full"
          >
            <FastForward className="h-4 w-4" /> Sim Next Round
          </Button>
          <Button
            variant="secondary"
            onClick={() => simAll.mutate()}
            disabled={busy}
            className="w-full"
          >
            <Trophy className="h-4 w-4" /> Sim to Champion
          </Button>
        </div>
        {canRebuild && (
          <div className="flex flex-col gap-2 border-t border-border pt-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-muted">
              Bracket structure look off? Rebuild it as a clean 4-team bracket
              (Division Series → Championship Series) from the final standings.
              Only available before any game is played.
            </p>
            <Button
              variant="outline"
              onClick={() => rebuild.mutate()}
              disabled={busy}
              className="shrink-0"
            >
              <RefreshCw className="h-4 w-4" /> Rebuild as 4-Team Bracket
            </Button>
          </div>
        )}
        {error && (
          <p className="flex items-center gap-2 text-sm text-danger">
            <AlertTriangle className="h-4 w-4 shrink-0" /> {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function YearPicker({
  years,
  value,
  onChange,
}: {
  years: number[];
  value: number | null;
  onChange: (year: number) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
      {years.map((y) => (
        <button
          key={y}
          type="button"
          onClick={() => onChange(y)}
          className={cn(
            "rounded-md px-3 py-1 text-xs font-semibold tabular-nums transition",
            value === y
              ? "bg-amber text-espresso"
              : "text-muted hover:bg-surface hover:text-ink",
          )}
        >
          {y}
        </button>
      ))}
    </div>
  );
}

function ChampionBanner({ playoffs }: { playoffs: Playoffs }) {
  return (
    <Card className="p-6">
      <div className="relative flex flex-col gap-2 text-center">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
          {playoffs.year} Champion
        </div>
        <div className="flex items-center justify-center gap-3 font-display text-4xl font-bold text-amber-text">
          <Crown className="h-8 w-8" />
          {playoffs.champion}
        </div>
        {playoffs.runner_up && (
          <div className="text-sm text-muted">
            <Medal className="inline h-4 w-4" /> Runner-up:{" "}
            <span className="font-semibold text-ink">{playoffs.runner_up}</span>
          </div>
        )}
      </div>
    </Card>
  );
}

function Bracket({
  rounds,
  myTeamId,
}: {
  rounds: PlayoffRound[];
  myTeamId: string | null;
}) {
  // Single-league brackets carry a trailing "Final" round that merely mirrors
  // the Championship Series (the genuine two-league title round is "WS"). Hide
  // it so the bracket doesn't show a duplicate/empty column.
  const visibleRounds = rounds.filter(
    (r) => r.name.trim().toLowerCase() !== "final",
  );
  if (visibleRounds.length === 0) {
    return (
      <Card>
        <CardContent className="py-10 text-sm text-muted">
          No rounds recorded yet.
        </CardContent>
      </Card>
    );
  }

  // Detect a two-league postseason (AL/NL) and lay it out like a real bracket:
  // League 1 funnels inward on the LEFT (Wild Card → Division → Championship),
  // the World Series sits in the MIDDLE, and League 2 mirrors it on the RIGHT.
  const classified = visibleRounds.map((round) => ({
    round,
    ...classifyRound(round.name),
  }));
  const leagues = [
    ...new Set(classified.filter((c) => c.league).map((c) => c.league!)),
  ].sort();
  const ws = classified.find((c) => c.stage === "WS");

  if (leagues.length >= 2 && ws) {
    const [leftLeague, rightLeague] = leagues;
    const byOrder = (a: { order: number }, b: { order: number }) =>
      a.order - b.order;
    const left = classified
      .filter((c) => c.league === leftLeague)
      .sort(byOrder); // WC → DS → CS (outermost → center)
    const right = classified
      .filter((c) => c.league === rightLeague)
      .sort(byOrder);
    const rightMirrored = [...right].reverse(); // CS → DS → WC (center → outermost)
    const colCount = left.length + 1 + rightMirrored.length;

    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between px-1 text-xs font-semibold uppercase tracking-[0.14em]">
          <span className="text-muted">{leftLeague}</span>
          <span className="text-amber">World Series</span>
          <span className="text-muted">{rightLeague}</span>
        </div>
        <div
          className="grid items-start gap-3 overflow-x-auto pb-4"
          style={{
            gridTemplateColumns: `repeat(${colCount}, minmax(240px, 1fr))`,
          }}
        >
          {left.map((c) => (
            <RoundColumn key={c.round.name} round={c.round} myTeamId={myTeamId} />
          ))}
          <RoundColumn round={ws.round} myTeamId={myTeamId} isFinal />
          {rightMirrored.map((c) => (
            <RoundColumn key={c.round.name} round={c.round} myTeamId={myTeamId} />
          ))}
        </div>
      </div>
    );
  }

  // Single-pool league: straightforward left-to-right progression.
  return (
    <div
      className="grid gap-4 overflow-x-auto pb-4"
      style={{ gridTemplateColumns: `repeat(${visibleRounds.length}, minmax(320px, 1fr))` }}
    >
      {visibleRounds.map((round) => (
        <RoundColumn key={round.name} round={round} myTeamId={myTeamId} />
      ))}
    </div>
  );
}

function RoundColumn({
  round,
  myTeamId,
  isFinal = false,
}: {
  round: PlayoffRound;
  myTeamId: string | null;
  isFinal?: boolean;
}) {
  return (
    <div className="space-y-3">
      <div
        className={cn(
          "sticky top-0 z-10 rounded-lg border px-3 py-2 backdrop-blur",
          isFinal
            ? "border-amber/60 bg-amber/10"
            : "border-border bg-surfaceAlt/80",
        )}
      >
        <div
          className={cn(
            "text-[11px] font-semibold uppercase tracking-[0.14em]",
            isFinal ? "text-amber" : "text-muted",
          )}
        >
          {stageLabel(round.name)}
        </div>
        <div className="text-sm">
          {round.matchups.length} series
        </div>
      </div>
      {round.matchups.length === 0 ? (
        <Card>
          <CardContent className="py-6 text-sm text-muted">
            Not played yet.
          </CardContent>
        </Card>
      ) : (
        round.matchups.map((matchup, idx) => (
          <MatchupCard
            key={`${round.name}-${idx}`}
            matchup={matchup}
            myTeamId={myTeamId}
          />
        ))
      )}
    </div>
  );
}

function MatchupCard({
  matchup,
  myTeamId,
}: {
  matchup: PlayoffMatchup;
  myTeamId: string | null;
}) {
  const { highWins, lowWins } = useMemo(
    () => computeSeriesScore(matchup),
    [matchup],
  );
  const needed = Math.ceil(matchup.config.length / 2);
  const highWon = highWins >= needed;
  const lowWon = lowWins >= needed;
  const hasMe =
    matchup.high.team_id === myTeamId || matchup.low.team_id === myTeamId;

  return (
    <Card className={cn("overflow-hidden", hasMe && "border-amber/60")}>
      <SideRow
        seed={matchup.high.seed}
        teamId={matchup.high.team_id}
        wins={highWins}
        winner={highWon}
        myTeamId={myTeamId}
      />
      <div className="relative border-y border-border/60 bg-surfaceAlt/40 px-4 py-1 text-center text-[10px] uppercase tracking-wider text-muted">
        Best of {matchup.config.length}
      </div>
      <SideRow
        seed={matchup.low.seed}
        teamId={matchup.low.team_id}
        wins={lowWins}
        winner={lowWon}
        myTeamId={myTeamId}
      />
      {matchup.games.length > 0 && (
        <GameLog games={matchup.games} matchup={matchup} />
      )}
    </Card>
  );
}

function SideRow({
  seed,
  teamId,
  wins,
  winner,
  myTeamId,
}: {
  seed: number;
  teamId: string;
  wins: number;
  winner: boolean;
  myTeamId: string | null;
}) {
  const isMe = teamId === myTeamId;
  return (
    <div
      className={cn(
        "relative flex items-center justify-between gap-3 px-4 py-3",
        winner && "bg-amber/10",
      )}
    >
      <div className="flex items-center gap-3">
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-border bg-surface text-[11px] font-bold">
          {seed}
        </span>
        <span className={cn("font-semibold", isMe && "text-amber-text")}>
          {teamId}
        </span>
        {isMe && <Badge tone="neutral">You</Badge>}
      </div>
      <div className="flex items-center gap-2">
        {winner && <Trophy className="h-4 w-4 text-amber" />}
        <span className="font-display text-xl font-bold tabular-nums">
          {wins}
        </span>
      </div>
    </div>
  );
}

function GameLog({
  games,
  matchup,
}: {
  games: PlayoffGame[];
  matchup: PlayoffMatchup;
}) {
  return (
    <div className="border-t border-border/60">
      <div className="px-4 pt-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
        Games
      </div>
      <ol className="divide-y divide-border/40">
        {games.map((game, i) => (
          <GameRow key={i} game={game} idx={i + 1} matchup={matchup} />
        ))}
      </ol>
    </div>
  );
}

function GameRow({
  game,
  idx,
  matchup,
}: {
  game: PlayoffGame;
  idx: number;
  matchup: PlayoffMatchup;
}) {
  const highSide = matchup.high.team_id;
  const winnerHigh = computeGameWinner(game) === highSide;
  const winnerLow =
    game.result && computeGameWinner(game) === matchup.low.team_id;
  const result = (
    <span
      className={cn(
        "font-mono tabular-nums",
        winnerHigh ? "text-success" : winnerLow ? "text-danger" : "text-muted",
      )}
    >
      {game.result ?? "—"}
    </span>
  );
  return (
    <li className="flex items-center gap-3 px-4 py-1.5 text-xs">
      <span className="w-6 font-mono text-muted">G{idx}</span>
      <span className={cn("flex-1 truncate", winnerLow && "font-semibold")}>
        {game.away} <span className="text-muted">@</span> {game.home}
      </span>
      {game.boxscore ? (
        <Link
          to={`/boxscore?path=${encodeURIComponent(game.boxscore)}`}
          className="hover:underline"
          title="View boxscore"
        >
          {result}
        </Link>
      ) : (
        result
      )}
    </li>
  );
}

function computeSeriesScore(matchup: PlayoffMatchup): {
  highWins: number;
  lowWins: number;
} {
  let highWins = 0;
  let lowWins = 0;
  for (const game of matchup.games) {
    const winner = computeGameWinner(game);
    if (winner === matchup.high.team_id) highWins++;
    else if (winner === matchup.low.team_id) lowWins++;
  }
  return { highWins, lowWins };
}

function computeGameWinner(game: PlayoffGame): string | null {
  if (!game.result) return null;
  const m = game.result.match(/^(\d+)\s*-\s*(\d+)$/);
  if (!m) return null;
  const home = Number(m[1]);
  const away = Number(m[2]);
  if (home === away) return null;
  return home > away ? game.home : game.away;
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading playoffs…</span>
      </CardContent>
    </Card>
  );
}

function ErrorCard({ message }: { message: string }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10 text-danger">
        <AlertTriangle className="h-5 w-5" />
        <span className="text-sm">{message}</span>
      </CardContent>
    </Card>
  );
}

