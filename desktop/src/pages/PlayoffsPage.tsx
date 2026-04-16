/**
 * Phase 4 port of ui/playoffs_window.py.
 *
 * Renders each playoffs_<year>.json as a bracket: one column per round,
 * matchup cards showing both seeds, current/final series score, and the
 * game log. Champion banner appears once a winner is recorded.
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Crown,
  Loader2,
  Medal,
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
import { Badge, Card, CardContent } from "@/components/ui";

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
          {playoffs.data.champion && <ChampionBanner playoffs={playoffs.data} />}
          <Bracket rounds={playoffs.data.rounds} myTeamId={myTeamId} />
        </div>
      ) : null}
    </AppShell>
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
  if (rounds.length === 0) {
    return (
      <Card>
        <CardContent className="py-10 text-sm text-muted">
          No rounds recorded yet.
        </CardContent>
      </Card>
    );
  }
  return (
    <div
      className="grid gap-4 overflow-x-auto pb-4"
      style={{ gridTemplateColumns: `repeat(${rounds.length}, minmax(320px, 1fr))` }}
    >
      {rounds.map((round) => (
        <RoundColumn key={round.name} round={round} myTeamId={myTeamId} />
      ))}
    </div>
  );
}

function RoundColumn({
  round,
  myTeamId,
}: {
  round: PlayoffRound;
  myTeamId: string | null;
}) {
  return (
    <div className="space-y-3">
      <div className="sticky top-0 z-10 rounded-lg border border-border bg-surfaceAlt/80 px-3 py-2 backdrop-blur">
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
          {round.name}
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

