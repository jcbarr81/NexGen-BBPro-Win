/**
 * Phase 4 port of ui/owner_home_page.py + ui/owner_dashboard.py.
 *
 * First iteration scope: hero header (team identity + record), key metrics
 * (run diff, next game, streak, last10, injuries, probable SP), and division
 * standings table. Bullpen readiness, hot/cold performers, finance snapshot
 * and leaders land in follow-up iterations using the same shell.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  Award,
  Calendar,
  CircleDot,
  Flame,
  Loader2,
  Snowflake,
  Sparkles,
  Stethoscope,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

import {
  api,
  type BullpenReadiness,
  type DashboardLeader,
  type DivisionStanding,
  type MatchupScout,
  type PerformerRow,
  type Performers,
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
} from "@/components/ui";

export function OwnerDashboardPage() {
  const navigate = useNavigate();
  const user = useAuthStore();
  const selectedTeamId = useAuthStore((s) => s.selectedTeamId);
  const setSelectedTeam = useAuthStore((s) => s.setSelectedTeam);

  const teams = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
  });

  // Resolve the team we should render for. Owner users have a team_id pinned
  // on login; admins (no team_id) fall back to the first team in the list.
  const activeTeamId = useMemo(() => {
    if (selectedTeamId) return selectedTeamId;
    if (user.teamId) return user.teamId;
    return teams.data?.[0]?.team_id ?? null;
  }, [selectedTeamId, user.teamId, teams.data]);

  const team = useQuery({
    queryKey: ["team", activeTeamId],
    queryFn: () => api.getTeam(activeTeamId as string),
    enabled: !!activeTeamId,
  });
  const snapshot = useQuery({
    queryKey: ["team-snapshot", activeTeamId],
    queryFn: () => api.teamSnapshot(activeTeamId as string),
    enabled: !!activeTeamId,
  });
  const division = useQuery({
    queryKey: ["team-division", activeTeamId],
    queryFn: () => api.teamDivision(activeTeamId as string),
    enabled: !!activeTeamId,
  });
  const widgets = useQuery({
    queryKey: ["team-widgets", activeTeamId],
    queryFn: () => api.teamWidgets(activeTeamId as string),
    enabled: !!activeTeamId,
  });

  if (!activeTeamId) {
    return (
      <AppShell title="Dashboard">
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            {teams.isLoading ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin text-amber" />
                <span className="text-sm text-muted">Loading teams…</span>
              </>
            ) : (
              <>
                <AlertTriangle className="h-5 w-5 text-warning" />
                <span className="text-sm">
                  No team is available yet. Create a team in the legacy app or
                  switch leagues.
                </span>
              </>
            )}
          </CardContent>
        </Card>
      </AppShell>
    );
  }

  return (
    <AppShell
      title={team.data ? `${team.data.city} ${team.data.name}` : "Dashboard"}
      subtitle={
        team.data
          ? `${team.data.division} · ${team.data.stadium}`
          : "Loading team…"
      }
    >
      <div className="space-y-6 animate-fade-in">
        <TeamHeroCard
          team={team.data}
          snapshot={snapshot.data}
          isLoading={team.isLoading || snapshot.isLoading}
        />

        <DashboardStats
          team={team.data}
          snapshot={snapshot.data}
        />

        <section className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <div className="lg:col-span-3">
            <DivisionStandingsCard
              division={division.data?.division}
              rows={division.data?.teams}
              isLoading={division.isLoading}
              isError={division.isError}
              error={division.error}
              activeTeamId={activeTeamId}
              activeTeamColor={team.data?.primary_color}
              onTeamClick={(id) => {
                setSelectedTeam(id);
              }}
            />
          </div>
          <div className="lg:col-span-2">
            <QuickActionsCard onNavigate={(to) => navigate(to)} />
          </div>
        </section>

        <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <BullpenCard bullpen={widgets.data?.bullpen} />
          <MatchupCard matchup={widgets.data?.matchup} />
        </section>

        <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <PerformersCard performers={widgets.data?.performers} />
          <LeadersCard
            batting={widgets.data?.batting_leaders ?? []}
            pitching={widgets.data?.pitching_leaders ?? []}
          />
        </section>

        {teams.data && teams.data.length > 1 && !user.teamId && (
          <TeamSwitcher
            teams={teams.data}
            activeTeamId={activeTeamId}
            onPick={setSelectedTeam}
          />
        )}
      </div>
    </AppShell>
  );
}

function parseRunDiff(raw: string | undefined): number {
  if (!raw || raw === "--") return 0;
  const n = parseInt(raw.replace("+", ""), 10);
  return Number.isFinite(n) ? n : 0;
}

function DashboardStats({
  team,
  snapshot,
}: {
  team: Team | undefined;
  snapshot: TeamSnapshot | undefined;
}) {
  const accent = useTeamAccent(team);
  return (
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
        label="Next Game"
        value={snapshot?.next_opponent ?? "--"}
        sub={snapshot?.next_date ?? "—"}
        Icon={Calendar}
        scoreboard={false}
        accentColor={accent.stripe}
      />
      <StatCard
        label="Injuries"
        value={snapshot?.injuries ?? 0}
        sub={`Probable SP: ${snapshot?.prob_sp ?? "—"}`}
        Icon={AlertTriangle}
        tone={(snapshot?.injuries ?? 0) > 0 ? "danger" : "neutral"}
        accentColor={accent.stripe}
      />
    </section>
  );
}

interface HeroProps {
  team: Team | undefined;
  snapshot: TeamSnapshot | undefined;
  isLoading: boolean;
}

function TeamHeroCard({ team, snapshot, isLoading }: HeroProps) {
  const logoVersion = useAuthStore((s) => s.logoVersion);
  const accent = useTeamAccent(team);
  return (
    <Card
      className="relative overflow-hidden p-6"
      style={
        team
          ? {
              backgroundImage: accent.heroGradient,
              // Solid team-color stripe at the top — replaces the generic
              // red-seam line with the team's own colors.
              boxShadow: `inset 0 4px 0 0 ${accent.primary}, inset 0 10px 0 -6px ${accent.secondary}`,
            }
          : undefined
      }
    >
      <div className="relative flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-5">
          {team ? (
            <TeamLogo
              teamId={team.team_id}
              abbreviation={team.abbreviation}
              primaryColor={team.primary_color}
              secondaryColor={team.secondary_color}
              className="h-20 w-20 shrink-0 rounded-2xl text-3xl shadow-panel"
              version={logoVersion}
            />
          ) : (
            <div
              className="flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl border border-border font-display text-3xl font-bold text-ink shadow-panel"
              style={{
                backgroundColor: "hsl(var(--surface-alt))",
                color: "hsl(var(--ink))",
              }}
            >
              —
            </div>
          )}
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
              {team?.division ?? "Division"}
            </div>
            <h2 className="font-display text-3xl font-bold">
              {team ? `${team.city} ${team.name}` : isLoading ? "Loading…" : "—"}
            </h2>
            <div className="text-sm text-muted">
              {team?.stadium ?? ""}
            </div>
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
          "mt-1 inline-flex items-center justify-center rounded-md border border-border-strong/40 bg-espresso/70 px-3 py-1 shadow-inset",
        )}
      >
        <span
          className={cn(
            "scoreboard-digits text-2xl font-bold leading-none",
            accent && "drop-shadow-[0_0_10px_hsl(var(--scoreboard-glow)/0.6)]",
          )}
        >
          {value}
        </span>
      </div>
    </div>
  );
}

interface DivisionCardProps {
  division: string | undefined;
  rows: DivisionStanding[] | undefined;
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  activeTeamId: string;
  activeTeamColor?: string;
  onTeamClick: (teamId: string) => void;
}

function DivisionStandingsCard({
  division,
  rows,
  isLoading,
  isError,
  error,
  activeTeamId,
  activeTeamColor,
  onTeamClick,
}: DivisionCardProps) {
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
        <Badge tone="amber">
          <Award className="h-3 w-3" /> {rows?.length ?? 0} teams
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading ? (
          <div className="flex items-center gap-2 px-6 py-8 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : isError ? (
          <div className="px-6 py-6 text-sm text-danger">
            {(error as Error)?.message ?? "Request failed."}
          </div>
        ) : !rows || rows.length === 0 ? (
          <div className="px-6 py-6 text-sm text-muted">
            Division data not available yet.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
                <th className="px-6 py-2 text-left font-semibold">Team</th>
                <th className="px-2 py-2 text-right font-semibold">W</th>
                <th className="px-2 py-2 text-right font-semibold">L</th>
                <th className="px-2 py-2 text-right font-semibold">PCT</th>
                <th className="px-2 py-2 text-right font-semibold">GB</th>
                <th className="px-2 py-2 text-right font-semibold">Strk</th>
                <th className="px-6 py-2 text-right font-semibold">L10</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const isActive = row.team_id === activeTeamId;
                return (
                <tr
                  key={row.team_id}
                  onClick={() => onTeamClick(row.team_id)}
                  className={cn(
                    "cursor-pointer border-b border-border/40 transition last:border-b-0 hover:bg-surfaceAlt/40",
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
                  <td className="px-6 py-2 font-semibold">
                    <div className="flex items-center gap-2">
                      {row.is_current && (
                        <CircleDot className="h-3 w-3 text-amber" aria-hidden />
                      )}
                      {row.label}
                    </div>
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums">{row.wins}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{row.losses}</td>
                  <td className="px-2 py-2 text-right tabular-nums">
                    {row.pct.toFixed(3).replace(/^0/, "")}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums">{row.gb}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{row.streak}</td>
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

function QuickActionsCard({ onNavigate }: { onNavigate: (to: string) => void }) {
  const actions: Array<{ label: string; to: string }> = [
    { label: "Full Roster", to: "/roster" },
    { label: "Transactions", to: "/transactions" },
    { label: "Draft Console", to: "/draft" },
    { label: "League Standings", to: "/league" },
    { label: "Team List", to: "/teams" },
    { label: "Utilities", to: "/utilities" },
  ];
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Quick Actions</CardTitle>
          <CardDescription>Jump into common workflows.</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-2">
        {actions.map((action) => (
          <Button
            key={action.to}
            variant="secondary"
            size="sm"
            onClick={() => onNavigate(action.to)}
          >
            {action.label}
          </Button>
        ))}
      </CardContent>
    </Card>
  );
}

function TeamSwitcher({
  teams,
  activeTeamId,
  onPick,
}: {
  teams: Team[];
  activeTeamId: string;
  onPick: (id: string) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="text-base">Team context</CardTitle>
          <CardDescription>
            You're signed in without a dedicated team. Pick one to view its dashboard.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2">
        {teams.map((t) => (
          <Button
            key={t.team_id}
            variant={t.team_id === activeTeamId ? "primary" : "outline"}
            size="sm"
            onClick={() => onPick(t.team_id)}
          >
            {t.abbreviation} · {t.name}
          </Button>
        ))}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Secondary dashboard widgets (bullpen, matchup, performers, leaders)

function BullpenCard({ bullpen }: { bullpen: BullpenReadiness | undefined }) {
  const detail = Array.isArray(bullpen?.detail) ? bullpen?.detail ?? [] : [];
  const avg = Number(bullpen?.avg_available_pct ?? 0);
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Bullpen Readiness</CardTitle>
          <CardDescription>
            {bullpen?.probable_starter
              ? `Probable SP: ${bullpen.probable_starter}`
              : "Arm availability across the staff"}
          </CardDescription>
        </div>
        <Badge tone="amber">
          <Stethoscope className="h-3 w-3" />{" "}
          {Number.isFinite(avg) ? `${Math.round(avg)}%` : "—"}
        </Badge>
      </CardHeader>
      <CardContent>
        <div className="mb-3 grid grid-cols-3 gap-2 text-center">
          <ReadinessChip label="Ready" value={Number(bullpen?.ready ?? 0)} tone="success" />
          <ReadinessChip label="Limited" value={Number(bullpen?.limited ?? 0)} tone="warning" />
          <ReadinessChip label="Resting" value={Number(bullpen?.rest ?? 0)} tone="danger" />
        </div>
        {detail.length === 0 ? (
          <div className="py-2 text-sm text-muted">
            {bullpen?.note || "No bullpen detail available."}
          </div>
        ) : (
          <ul className="divide-y divide-border/60">
            {detail.slice(0, 6).map((arm, i) => (
              <li
                key={`${arm.name}-${i}`}
                className="flex items-center justify-between py-1.5 text-sm"
              >
                <div className="min-w-0 truncate">
                  <span className="font-semibold">{arm.name || "—"}</span>
                  {arm.role && (
                    <span className="ml-2 text-xs uppercase tracking-wider text-muted">
                      {arm.role}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {typeof arm.days === "number" && (
                    <span className="text-xs text-muted">{arm.days}d</span>
                  )}
                  <Badge tone={readinessTone(arm.status)}>
                    {arm.status || "—"}
                  </Badge>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function ReadinessChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "success" | "warning" | "danger";
}) {
  const toneClass =
    tone === "success"
      ? "text-success border-success/40 bg-success/10"
      : tone === "warning"
        ? "text-warning border-warning/40 bg-warning/10"
        : "text-danger border-danger/40 bg-danger/10";
  return (
    <div className={cn("rounded-xl border p-2", toneClass)}>
      <div className="font-display text-xl font-bold tabular-nums">
        {value}
      </div>
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em]">
        {label}
      </div>
    </div>
  );
}

function readinessTone(
  status: string | undefined,
): "success" | "warning" | "danger" | "neutral" {
  const s = (status || "").toLowerCase();
  if (s.includes("ready") || s === "fresh") return "success";
  if (s.includes("limited") || s.includes("caution")) return "warning";
  if (s.includes("rest") || s.includes("unavailable")) return "danger";
  return "neutral";
}

function MatchupCard({ matchup }: { matchup: MatchupScout | undefined }) {
  const hasData =
    matchup && Object.values(matchup).some((v) => v != null && v !== "");
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Matchup Scout</CardTitle>
          <CardDescription>
            {matchup?.date
              ? `Next: ${matchup.date}`
              : "Scouting report for the next game"}
          </CardDescription>
        </div>
        {matchup?.opponent && (
          <Link
            to={`/team/${encodeURIComponent(matchup.opponent)}`}
            className="text-sm font-semibold hover:text-amber"
          >
            <Badge tone="amber">
              {matchup.venue === "Home" ? "vs" : "@"} {matchup.opponent}
            </Badge>
          </Link>
        )}
      </CardHeader>
      <CardContent>
        {!hasData ? (
          <div className="py-2 text-sm text-muted">No upcoming game.</div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <KV label="Opp Record" value={matchup?.opp_record ?? "—"} />
              <KV label="Opp Run Diff" value={matchup?.opp_run_diff ?? "—"} />
              <KV label="Opp Streak" value={matchup?.opp_streak ?? "—"} />
              <KV label="Venue" value={matchup?.venue ?? "—"} />
              <KV label="Our SP" value={matchup?.team_probable ?? "—"} />
              <KV label="Their SP" value={matchup?.opp_probable ?? "—"} />
            </div>
            {matchup?.note && (
              <p className="mt-3 border-t border-border/60 pt-3 text-sm text-muted">
                {matchup.note}
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function KV({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-border bg-surfaceAlt/40 p-2">
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
        {label}
      </div>
      <div className="mt-0.5 text-sm font-semibold">{value || "—"}</div>
    </div>
  );
}

function PerformersCard({
  performers,
}: {
  performers: Performers | undefined;
}) {
  const hitterHot = performers?.hitters?.hot ?? [];
  const hitterCold = performers?.hitters?.cold ?? [];
  const pitcherHot = performers?.pitchers?.hot ?? [];
  const pitcherCold = performers?.pitchers?.cold ?? [];
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Hot &amp; Cold</CardTitle>
          <CardDescription>
            {performers?.range
              ? `Window: ${performers.range}`
              : "Trending performers over the last week"}
          </CardDescription>
        </div>
        <Badge tone="amber">
          <Sparkles className="h-3 w-3" />{" "}
          {hitterHot.length +
            hitterCold.length +
            pitcherHot.length +
            pitcherCold.length}
        </Badge>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <PerformerList title="Hot Hitters" tone="success" rows={hitterHot} />
        <PerformerList title="Cold Hitters" tone="danger" rows={hitterCold} />
        <PerformerList title="Hot Pitchers" tone="success" rows={pitcherHot} />
        <PerformerList title="Cold Pitchers" tone="danger" rows={pitcherCold} />
      </CardContent>
    </Card>
  );
}

function PerformerList({
  title,
  tone,
  rows,
}: {
  title: string;
  tone: "success" | "danger";
  rows: PerformerRow[];
}) {
  const Icon = tone === "success" ? Flame : Snowflake;
  const TrendIcon = tone === "success" ? TrendingUp : TrendingDown;
  return (
    <div className="rounded-xl border border-border bg-surfaceAlt/40 p-3">
      <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
        <Icon
          className={cn(
            "h-3 w-3",
            tone === "success" ? "text-success" : "text-danger",
          )}
        />
        {title}
      </div>
      {rows.length === 0 ? (
        <div className="text-xs text-muted">—</div>
      ) : (
        <ul className="space-y-1">
          {rows.slice(0, 3).map((row, i) => (
            <li
              key={`${row.player_id ?? row.name}-${i}`}
              className="flex items-center justify-between gap-2 text-sm"
            >
              {row.player_id ? (
                <Link
                  to={`/player/${encodeURIComponent(String(row.player_id))}`}
                  className="truncate font-semibold hover:text-amber"
                >
                  {row.name ?? row.player_id}
                </Link>
              ) : (
                <span className="truncate font-semibold">{row.name ?? "—"}</span>
              )}
              <span
                className={cn(
                  "flex items-center gap-1 whitespace-nowrap font-mono text-xs",
                  tone === "success" ? "text-success" : "text-danger",
                )}
              >
                <TrendIcon className="h-3 w-3" />
                {row.delta_text || row.summary || "—"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function LeadersCard({
  batting,
  pitching,
}: {
  batting: DashboardLeader[];
  pitching: DashboardLeader[];
}) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Team Leaders</CardTitle>
          <CardDescription>Headline stats across the roster</CardDescription>
        </div>
        <Badge tone="amber">
          <Award className="h-3 w-3" /> {batting.length + pitching.length}
        </Badge>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <LeaderList title="Batting" rows={batting} />
        <LeaderList title="Pitching" rows={pitching} />
      </CardContent>
    </Card>
  );
}

function LeaderList({
  title,
  rows,
}: {
  title: string;
  rows: DashboardLeader[];
}) {
  return (
    <div className="rounded-xl border border-border bg-surfaceAlt/40 p-3">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
        {title}
      </div>
      {rows.length === 0 ? (
        <div className="text-xs text-muted">—</div>
      ) : (
        <ul className="space-y-1">
          {rows.slice(0, 3).map((row, i) => (
            <li
              key={`${row.label}-${i}`}
              className="flex items-center justify-between gap-2 text-sm"
            >
              <span className="text-xs uppercase tracking-wider text-muted">
                {row.label ?? "—"}
              </span>
              {row.player_id ? (
                <Link
                  to={`/player/${encodeURIComponent(String(row.player_id))}`}
                  className="truncate font-semibold hover:text-amber"
                >
                  {row.value_text ?? String(row.value ?? "—")}
                </Link>
              ) : (
                <span className="truncate font-semibold">
                  {row.value_text ?? String(row.value ?? "—")}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
