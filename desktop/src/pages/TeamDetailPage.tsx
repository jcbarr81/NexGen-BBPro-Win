/**
 * Phase 4 port of ui/team_page.py.
 *
 * Read-only deep view for a specific team. Mirrors the owner dashboard's
 * shape (hero + metrics + division + schedule) but works against any
 * team without flipping the user's selected-team context. Reuses every
 * existing sidecar endpoint -- no new server code needed.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BarChart3,
  Calendar,
  CalendarClock,
  CircleDot,
  Flame,
  Loader2,
  TrendingUp,
  Users as UsersIcon,
} from "lucide-react";

import {
  api,
  type DivisionStanding,
  type ScheduleGame,
  type Team,
  type TeamSnapshot,
} from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import { StatCard } from "@/components/StatCard";
import { TeamLogo } from "@/components/TeamLogo";
import { useTeamAccent } from "@/lib/team-colors";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";

export function TeamDetailPage() {
  const { teamId } = useParams<{ teamId: string }>();
  const navigate = useNavigate();
  const setSelectedTeam = useAuthStore((s) => s.setSelectedTeam);
  const userTeamId = useAuthStore((s) => s.teamId);
  const selectedTeamId = useAuthStore((s) => s.selectedTeamId);

  const team = useQuery({
    queryKey: ["team", teamId],
    queryFn: () => api.getTeam(teamId as string),
    enabled: !!teamId,
  });
  const snapshot = useQuery({
    queryKey: ["team-snapshot", teamId],
    queryFn: () => api.teamSnapshot(teamId as string),
    enabled: !!teamId,
  });
  const division = useQuery({
    queryKey: ["team-division", teamId],
    queryFn: () => api.teamDivision(teamId as string),
    enabled: !!teamId,
  });
  const roster = useQuery({
    queryKey: ["team-roster", teamId],
    queryFn: () => api.teamRoster(teamId as string),
    enabled: !!teamId,
  });
  const schedule = useQuery({
    queryKey: ["schedule", "team", teamId],
    queryFn: () => api.schedule({ teamId }),
    enabled: !!teamId,
  });

  const { upcoming, recent } = useMemo(() => {
    const games = schedule.data?.games ?? [];
    const up: ScheduleGame[] = [];
    const done: ScheduleGame[] = [];
    for (const g of games) {
      (g.played ? done : up).push(g);
    }
    done.reverse();
    return { upcoming: up.slice(0, 5), recent: done.slice(0, 5) };
  }, [schedule.data]);

  if (!teamId) {
    return (
      <AppShell title="Team">
        <ErrorCard message="No team id in URL." />
      </AppShell>
    );
  }

  const isMine = teamId === userTeamId || teamId === selectedTeamId;

  return (
    <AppShell
      title={team.data ? `${team.data.city} ${team.data.name}` : "Team"}
      subtitle={
        team.data
          ? `${team.data.division} · ${team.data.stadium}`
          : "Loading…"
      }
    >
      <div className="mb-4 flex items-center justify-between">
        <Button variant="ghost" onClick={() => navigate(-1)}>
          <ArrowLeft className="h-4 w-4" /> Back
        </Button>
        {!isMine && team.data && (
          <Button
            variant="outline"
            onClick={() => {
              setSelectedTeam(teamId);
              navigate("/home");
            }}
          >
            Set as my team & open dashboard
          </Button>
        )}
      </div>

      {team.isLoading ? (
        <LoadingCard />
      ) : team.isError ? (
        <ErrorCard message={(team.error as Error).message} />
      ) : team.data ? (
        <TeamDetailBody
          team={team.data}
          snapshot={snapshot.data}
          division={division.data}
          roster={roster.data}
          upcoming={upcoming}
          recent={recent}
          schedule={schedule}
          divisionQuery={division}
          teamId={teamId}
        />
      ) : null}
    </AppShell>
  );
}

function TeamDetailBody({
  team,
  snapshot,
  division,
  roster,
  upcoming,
  recent,
  divisionQuery,
  teamId,
}: {
  team: Team;
  snapshot: TeamSnapshot | undefined;
  division: DivisionStandings | undefined;
  roster: { active_size: number; levels: Record<string, unknown[]> } | undefined;
  upcoming: ScheduleGame[];
  recent: ScheduleGame[];
  schedule: { isLoading: boolean };
  divisionQuery: {
    isLoading: boolean;
    isError: boolean;
    error: unknown;
  };
  teamId: string;
}) {
  const accent = useTeamAccent(team);
  return (
    <div className="space-y-6 animate-fade-in">
      <HeroCard team={team} snapshot={snapshot} />

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Run Diff"
          value={snapshot?.run_diff ?? "--"}
          sub="Runs scored vs. allowed"
          Icon={TrendingUp}
          tone={parseRunDiff(snapshot?.run_diff) >= 0 ? "success" : "danger"}
          accentColor={accent.stripe}
        />
        <StatCard
          label="Streak"
          value={snapshot?.streak ?? "--"}
          sub={`Last 10: ${snapshot?.last10 ?? "--"}`}
          Icon={Flame}
          tone="amber"
          accentColor={accent.stripe}
        />
        <StatCard
          label="Active Roster"
          value={roster?.active_size ?? "—"}
          sub={`${(roster?.levels.AAA?.length ?? 0) + (roster?.levels.LOW?.length ?? 0)} in minors`}
          Icon={UsersIcon}
          accentColor={accent.stripe}
        />
        <StatCard
          label="Next Game"
          value={snapshot?.next_opponent ?? "--"}
          sub={snapshot?.next_date ?? "—"}
          Icon={Calendar}
          scoreboard={false}
          accentColor={accent.stripe}
        />
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <DivisionStandingsCard
            teamId={teamId}
            division={division?.division}
            rows={division?.teams}
            isLoading={divisionQuery.isLoading}
            isError={divisionQuery.isError}
            error={divisionQuery.error}
            activeTeamColor={team.primary_color}
          />
        </div>
        <div className="lg:col-span-2 space-y-6">
          <ScheduleSlice
            title="Upcoming"
            icon={<CalendarClock className="h-3 w-3" />}
            games={upcoming}
            teamId={teamId}
            empty="No upcoming games."
          />
          <ScheduleSlice
            title="Recent results"
            icon={<Calendar className="h-3 w-3" />}
            games={recent}
            teamId={teamId}
            empty="No games played yet."
          />
        </div>
      </div>

      <TeamStatsPanel teamId={teamId} />
    </div>
  );
}

function TeamStatsPanel({ teamId }: { teamId: string }) {
  const stats = useQuery({
    queryKey: ["team-stats", teamId],
    queryFn: () => api.teamStats(teamId),
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-amber" /> Team stats
            </CardTitle>
            <CardDescription>
              Season batting, pitching, and team totals for players currently
              on this roster.
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {stats.isLoading && (
          <div className="flex items-center gap-2 py-6 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading stats…
          </div>
        )}
        {stats.isError && (
          <div className="py-4 text-sm text-danger">
            {(stats.error as Error).message}
          </div>
        )}
        {stats.data && (
          <Tabs defaultValue="batting">
            <TabsList>
              <TabsTrigger value="batting">Batting</TabsTrigger>
              <TabsTrigger value="pitching">Pitching</TabsTrigger>
              <TabsTrigger value="team">Team Totals</TabsTrigger>
            </TabsList>
            <TabsContent value="batting">
              <PlayerStatsTable
                columns={stats.data.columns.batters}
                rows={stats.data.batters}
              />
            </TabsContent>
            <TabsContent value="pitching">
              <PlayerStatsTable
                columns={stats.data.columns.pitchers}
                rows={stats.data.pitchers}
              />
            </TabsContent>
            <TabsContent value="team">
              <TeamTotalsTable
                columns={stats.data.columns.team}
                totals={stats.data.team_totals}
              />
            </TabsContent>
          </Tabs>
        )}
      </CardContent>
    </Card>
  );
}

function PlayerStatsTable({
  columns,
  rows,
}: {
  columns: string[];
  rows: Array<{
    player_id: string;
    first_name: string;
    last_name: string;
    primary_position: string;
    stats: Record<string, number | string | null>;
  }>;
}) {
  if (rows.length === 0) {
    return <div className="py-3 text-sm italic text-muted">No data yet.</div>;
  }
  return (
    <div className="mt-2 max-h-[420px] overflow-auto">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-surface">
          <tr className="border-b border-border text-left text-muted">
            <th className="px-2 py-1 font-medium">Player</th>
            <th className="px-2 py-1 font-medium">Pos</th>
            {columns.map((c) => (
              <th key={c} className="px-2 py-1 text-right font-medium uppercase">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.player_id} className="border-b border-border/50">
              <td className="px-2 py-1">
                <Link
                  to={`/player/${encodeURIComponent(r.player_id)}`}
                  className="hover:text-amber-text"
                >
                  {r.first_name} {r.last_name}
                </Link>
              </td>
              <td className="px-2 py-1 text-muted">{r.primary_position}</td>
              {columns.map((c) => (
                <td key={c} className="px-2 py-1 text-right tabular-nums">
                  {formatStat(r.stats[c], c)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TeamTotalsTable({
  columns,
  totals,
}: {
  columns: string[];
  totals: Record<string, number | string | null>;
}) {
  return (
    <div className="mt-2 grid grid-cols-3 gap-2 md:grid-cols-6">
      {columns.map((c) => (
        <div
          key={c}
          className="rounded-md border border-border bg-surface p-2 text-center"
        >
          <div className="text-[10px] uppercase tracking-wide text-muted">
            {c}
          </div>
          <div className="mt-0.5 font-display text-lg tabular-nums">
            {formatStat(totals[c], c)}
          </div>
        </div>
      ))}
    </div>
  );
}

function formatStat(v: number | string | null | undefined, col: string): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") {
    if (["avg", "obp", "slg"].includes(col)) return v.toFixed(3);
    if (["era", "whip", "ip"].includes(col)) return v.toFixed(2);
    if (Number.isInteger(v)) return String(v);
    return v.toFixed(2);
  }
  return String(v);
}

function HeroCard({
  team,
  snapshot,
}: {
  team: Team;
  snapshot: TeamSnapshot | undefined;
}) {
  const logoVersion = useAuthStore((s) => s.logoVersion);
  return (
    <Card
      className="seam-accent relative overflow-hidden p-6"
      style={{
        backgroundImage: [
          `linear-gradient(135deg, ${team.primary_color}22, transparent 60%)`,
          "radial-gradient(circle at 50% 140%, hsl(var(--clay) / 0.35), transparent 55%)",
          "radial-gradient(circle at 50% 180%, hsl(var(--ballpark-deep) / 0.55), transparent 60%)",
        ].join(","),
      }}
    >
      <div className="relative flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-5">
          <TeamLogo
            teamId={team.team_id}
            abbreviation={team.abbreviation}
            primaryColor={team.primary_color}
            secondaryColor={team.secondary_color}
            className="h-20 w-20 shrink-0 rounded-2xl text-3xl shadow-panel"
            version={logoVersion}
          />
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
              {team.division}
            </div>
            <h2 className="font-display text-3xl font-bold">
              {team.city} {team.name}
            </h2>
            <div className="text-sm text-muted">{team.stadium}</div>
          </div>
        </div>

        <div className="flex items-center gap-6 md:gap-8">
          <HeroStat label="Record" value={snapshot?.record ?? "--"} accent />
          <HeroStat label="Run Diff" value={snapshot?.run_diff ?? "--"} />
          <HeroStat label="Streak" value={snapshot?.streak ?? "--"} />
        </div>
      </div>
    </Card>
  );
}

function HeroStat({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string | number;
  accent?: boolean;
}) {
  return (
    <div className="text-right">
      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
        {label}
      </div>
      <div
        className={cn(
          "font-display text-3xl font-bold leading-none",
          accent ? "text-amber-text" : "text-ink",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function DivisionStandingsCard({
  teamId,
  division,
  rows,
  isLoading,
  isError,
  error,
  activeTeamColor,
}: {
  teamId: string;
  division: string | undefined;
  rows: DivisionStanding[] | undefined;
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  activeTeamColor?: string;
}) {
  const accent = useTeamAccent(
    activeTeamColor
      ? ({ primary_color: activeTeamColor, secondary_color: "" } as Team)
      : null,
  );
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Division Standings</CardTitle>
          <CardDescription>{division ?? "--"}</CardDescription>
        </div>
        <Badge tone="amber">{rows?.length ?? 0} teams</Badge>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading ? (
          <div className="flex items-center gap-2 px-6 py-8 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : isError ? (
          <div className="px-6 py-6 text-sm text-danger">
            {(error as Error)?.message}
          </div>
        ) : !rows || rows.length === 0 ? (
          <div className="px-6 py-6 text-sm text-muted">No data.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
                <th className="px-6 py-2 text-left font-semibold">Team</th>
                <th className="px-2 py-2 text-right font-semibold">W</th>
                <th className="px-2 py-2 text-right font-semibold">L</th>
                <th className="px-2 py-2 text-right font-semibold">PCT</th>
                <th className="px-2 py-2 text-right font-semibold">GB</th>
                <th className="px-6 py-2 text-right font-semibold">L10</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const isActive = row.team_id === teamId;
                return (
                <tr
                  key={row.team_id}
                  className={cn(
                    "border-b border-border/40 transition last:border-b-0 hover:bg-surfaceAlt/40",
                  )}
                  style={
                    isActive && activeTeamColor
                      ? {
                          backgroundColor: accent.softTint,
                          boxShadow: `inset 3px 0 0 0 ${accent.stripe}`,
                        }
                      : undefined
                  }
                >
                  <td className="px-6 py-2">
                    <Link
                      to={`/team/${encodeURIComponent(row.team_id)}`}
                      className="flex items-center gap-2 font-semibold hover:text-amber"
                    >
                      {row.is_current && (
                        <CircleDot className="h-3 w-3 text-amber" />
                      )}
                      {row.label}
                    </Link>
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums">{row.wins}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{row.losses}</td>
                  <td className="px-2 py-2 text-right tabular-nums">
                    {row.pct.toFixed(3).replace(/^0/, "")}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums">{row.gb}</td>
                  <td className="px-6 py-2 text-right tabular-nums">{row.last10}</td>
                </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

function ScheduleSlice({
  title,
  icon,
  games,
  teamId,
  empty,
}: {
  title: string;
  icon: React.ReactNode;
  games: ScheduleGame[];
  teamId: string;
  empty: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <Badge tone="amber">
          {icon} {games.length}
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        {games.length === 0 ? (
          <div className="px-6 py-6 text-sm text-muted">{empty}</div>
        ) : (
          <ul className="divide-y divide-border/60">
            {games.map((game, i) => {
              const isHome = game.is_home ?? game.home === teamId;
              const opponent =
                game.opponent ?? (isHome ? game.away : game.home);
              return (
                <li
                  key={`${game.date}-${i}`}
                  className="flex items-center justify-between gap-3 px-6 py-2 text-sm"
                >
                  <div className="flex items-center gap-3">
                    <span className="w-16 shrink-0 text-xs font-semibold uppercase tracking-wider text-muted">
                      {formatDate(game.date)}
                    </span>
                    <span className="text-xs uppercase text-muted">
                      {isHome ? "vs" : "@"}
                    </span>
                    <Link
                      to={`/team/${encodeURIComponent(opponent)}`}
                      className="font-semibold hover:text-amber"
                    >
                      {opponent}
                    </Link>
                  </div>
                  {game.played ? (
                    game.boxscore ? (
                      <Link
                        to={`/boxscore?path=${encodeURIComponent(game.boxscore)}`}
                      >
                        <Badge tone="neutral" className="hover:border-amber/60 hover:text-amber-text">
                          {game.result || "Final"}
                        </Badge>
                      </Link>
                    ) : (
                      <Badge tone="neutral">{game.result || "Final"}</Badge>
                    )
                  ) : (
                    <ArrowRight className="h-3 w-3 text-muted" />
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function parseRunDiff(raw: string | undefined): number {
  if (!raw || raw === "--") return 0;
  const n = parseInt(raw.replace("+", ""), 10);
  return Number.isFinite(n) ? n : 0;
}

function formatDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading team…</span>
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
