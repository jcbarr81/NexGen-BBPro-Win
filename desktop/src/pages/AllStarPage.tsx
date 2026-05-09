/**
 * All-Star Game browser.
 *
 * Year tabs across the league's All-Star history. For each year shows
 * the score, the MVP, and both squads' rosters (hitters by position +
 * top pitchers). Games are produced automatically when the sim crosses
 * the All-Star break midpoint.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Loader2,
  Sparkles,
  Star,
  Trophy,
} from "lucide-react";

import { api, type AllStarGame, type AllStarSquad } from "@/lib/api";
import { AppShell } from "@/components/layout/AppShell";
import { usePersistedState } from "@/lib/use-persisted-state";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Tabs,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { cn } from "@/lib/cn";

export function AllStarPage() {
  const historyQ = useQuery({
    queryKey: ["all-star-history"],
    queryFn: () => api.listAllStarGames(),
  });

  const games = historyQ.data?.games ?? [];
  const yearOptions = useMemo(
    () => games.map((g) => g.year).filter((y): y is number => typeof y === "number"),
    [games],
  );
  const [selectedYear, setSelectedYear] = usePersistedState<string>(
    "all-star:year",
    "",
  );
  const activeYear =
    selectedYear && yearOptions.includes(Number(selectedYear))
      ? Number(selectedYear)
      : yearOptions[0] ?? null;
  const visible = activeYear != null ? games.find((g) => g.year === activeYear) : undefined;

  return (
    <AppShell
      title="All-Star Game"
      subtitle={
        games.length > 0
          ? `${games.length} season${games.length === 1 ? "" : "s"} on file`
          : "Mid-season exhibition + MVP"
      }
    >
      {historyQ.isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <Loader2 className="h-5 w-5 animate-spin text-amber" />
            <span className="text-sm text-muted">Loading All-Star history…</span>
          </CardContent>
        </Card>
      ) : historyQ.isError ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-danger">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm">{(historyQ.error as Error).message}</span>
          </CardContent>
        </Card>
      ) : games.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <Star className="h-10 w-10 text-amber" />
            <h2 className="font-display text-xl">No All-Star Games yet</h2>
            <p className="max-w-sm text-sm text-muted">
              The All-Star Game runs automatically when the sim crosses the
              mid-season break. Once your league hits July, check back here.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {yearOptions.length > 1 && (
            <Tabs
              value={String(activeYear ?? "")}
              onValueChange={(v) => setSelectedYear(v)}
            >
              <TabsList>
                {yearOptions.map((y) => (
                  <TabsTrigger key={y} value={String(y)}>
                    {y}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          )}

          {visible ? <GameCard game={visible} /> : null}
        </div>
      )}
    </AppShell>
  );
}

function GameCard({ game }: { game: AllStarGame }) {
  if (game.skipped) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-6 text-sm text-muted">
          <AlertTriangle className="h-4 w-4 text-warning" />
          {game.year} game skipped — {game.reason ?? "unknown reason"}.
        </CardContent>
      </Card>
    );
  }
  const homeWon = game.home_runs > game.away_runs;
  const awayWon = game.away_runs > game.home_runs;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              <Star className="h-4 w-4 text-amber" />
              {game.year} All-Star Game
            </CardTitle>
            <CardDescription>
              Mid-season exhibition between the league's top stars.
            </CardDescription>
          </div>
          <Badge tone="amber">
            <Trophy className="h-3 w-3" /> {game.winner}
          </Badge>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <ScoreBox
              squad={game.away_squad}
              runs={game.away_runs}
              winning={awayWon}
              label="Away"
            />
            <ScoreBox
              squad={game.home_squad}
              runs={game.home_runs}
              winning={homeWon}
              label="Home"
            />
          </div>
          {game.mvp && (
            <div className="mt-4 rounded-md border border-amber/60 bg-amber/10 px-4 py-3">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-amber" />
                <span className="text-xs font-semibold uppercase tracking-wider text-muted">
                  Game MVP
                </span>
              </div>
              <Link
                to={`/player/${encodeURIComponent(game.mvp.player_id)}`}
                className="mt-1 block font-display text-lg font-bold leading-tight hover:text-amber"
              >
                {game.mvp.name}
              </Link>
              <div className="text-xs text-muted">
                {game.mvp.team_id} · {game.mvp.position} · {game.mvp.line}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <SquadCard squadName={game.away_squad} squad={game.squads[game.away_squad]} />
        <SquadCard squadName={game.home_squad} squad={game.squads[game.home_squad]} />
      </div>
    </div>
  );
}

function ScoreBox({
  squad,
  runs,
  winning,
  label,
}: {
  squad: string;
  runs: number;
  winning: boolean;
  label: string;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border p-4 text-center",
        winning
          ? "border-amber/60 bg-amber/10"
          : "border-border bg-surfaceAlt/40",
      )}
    >
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-1 text-sm font-semibold">{squad}</div>
      <div className="mt-1 font-display text-4xl font-bold tabular-nums">
        {runs}
      </div>
    </div>
  );
}

function SquadCard({
  squadName,
  squad,
}: {
  squadName: string;
  squad: AllStarSquad | undefined;
}) {
  if (!squad) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted">
          No roster data for {squadName}.
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{squadName}</CardTitle>
        <Badge tone="neutral">
          {squad.team_ids.length} team{squad.team_ids.length === 1 ? "" : "s"}
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        <div className="px-6 pb-2 pt-1 text-[11px] font-semibold uppercase tracking-wider text-muted">
          Position players
        </div>
        <ul className="divide-y divide-border/40">
          {squad.hitters.length === 0 ? (
            <li className="px-6 py-2 text-sm italic text-muted">No hitters.</li>
          ) : (
            squad.hitters.map((p) => (
              <li
                key={p.player_id}
                className="flex items-center justify-between gap-3 px-6 py-2 text-sm"
              >
                <div className="flex items-center gap-3">
                  <span className="w-8 text-right text-xs font-semibold uppercase text-muted">
                    {p.position}
                  </span>
                  <Link
                    to={`/player/${encodeURIComponent(p.player_id)}`}
                    className="font-semibold hover:text-amber"
                  >
                    {p.last_name}, {p.first_name}
                  </Link>
                  <span className="text-xs text-muted">{p.team_id}</span>
                </div>
                <div className="text-xs tabular-nums text-muted">
                  {fmtHitterStats(p.stats)}
                </div>
              </li>
            ))
          )}
        </ul>
        <div className="px-6 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-muted">
          Pitching staff
        </div>
        <ul className="divide-y divide-border/40">
          {squad.pitchers.length === 0 ? (
            <li className="px-6 py-2 text-sm italic text-muted">No pitchers.</li>
          ) : (
            squad.pitchers.map((p) => (
              <li
                key={p.player_id}
                className="flex items-center justify-between gap-3 px-6 py-2 text-sm"
              >
                <div className="flex items-center gap-3">
                  <span className="w-8 text-right text-xs font-semibold uppercase text-muted">
                    P
                  </span>
                  <Link
                    to={`/player/${encodeURIComponent(p.player_id)}`}
                    className="font-semibold hover:text-amber"
                  >
                    {p.last_name}, {p.first_name}
                  </Link>
                  <span className="text-xs text-muted">{p.team_id}</span>
                </div>
                <div className="text-xs tabular-nums text-muted">
                  {fmtPitcherStats(p.stats)}
                </div>
              </li>
            ))
          )}
        </ul>
      </CardContent>
    </Card>
  );
}

function fmtHitterStats(stats: Record<string, unknown>): string {
  const parts: string[] = [];
  const ops = stats.ops;
  if (typeof ops === "number") parts.push(`${ops.toFixed(3)} OPS`);
  const hr = stats.hr;
  if (typeof hr === "number") parts.push(`${hr} HR`);
  return parts.join(" · ") || "—";
}

function fmtPitcherStats(stats: Record<string, unknown>): string {
  const parts: string[] = [];
  const era = stats.era;
  if (typeof era === "number") parts.push(`${era.toFixed(2)} ERA`);
  const ip = stats.ip;
  if (typeof ip === "number") parts.push(`${ip.toFixed(1)} IP`);
  return parts.join(" · ") || "—";
}
