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
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  Award,
  Calendar,
  CircleDot,
  Flame,
  Loader2,
  TrendingUp,
} from "lucide-react";

import { api, type DivisionStanding, type Team, type TeamSnapshot } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import { StatCard } from "@/components/StatCard";
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

        <section className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Run Diff"
            value={snapshot.data?.run_diff ?? "--"}
            sub="Runs scored vs. allowed"
            Icon={TrendingUp}
            tone={parseRunDiff(snapshot.data?.run_diff) >= 0 ? "success" : "danger"}
          />
          <StatCard
            label="Streak"
            value={snapshot.data?.streak ?? "--"}
            sub={`Last 10: ${snapshot.data?.last10 ?? "--"}`}
            Icon={Flame}
            tone="amber"
          />
          <StatCard
            label="Next Game"
            value={snapshot.data?.next_opponent ?? "--"}
            sub={snapshot.data?.next_date ?? "—"}
            Icon={Calendar}
          />
          <StatCard
            label="Injuries"
            value={snapshot.data?.injuries ?? 0}
            sub={`Probable SP: ${snapshot.data?.prob_sp ?? "—"}`}
            Icon={AlertTriangle}
            tone={(snapshot.data?.injuries ?? 0) > 0 ? "danger" : "neutral"}
          />
        </section>

        <section className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <div className="lg:col-span-3">
            <DivisionStandingsCard
              division={division.data?.division}
              rows={division.data?.teams}
              isLoading={division.isLoading}
              isError={division.isError}
              error={division.error}
              activeTeamId={activeTeamId}
              onTeamClick={(id) => {
                setSelectedTeam(id);
              }}
            />
          </div>
          <div className="lg:col-span-2">
            <QuickActionsCard onNavigate={(to) => navigate(to)} />
          </div>
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

interface HeroProps {
  team: Team | undefined;
  snapshot: TeamSnapshot | undefined;
  isLoading: boolean;
}

function TeamHeroCard({ team, snapshot, isLoading }: HeroProps) {
  return (
    <Card
      className="p-6"
      style={
        team
          ? {
              backgroundImage: `linear-gradient(135deg, ${team.primary_color}22, transparent 60%)`,
            }
          : undefined
      }
    >
      <div className="relative flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-5">
          <div
            className="flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl border border-border font-display text-3xl font-bold text-ink shadow-panel"
            style={{
              backgroundColor: team?.primary_color ?? "hsl(var(--surface-alt))",
              color: team?.secondary_color ?? "hsl(var(--ink))",
            }}
          >
            {team?.abbreviation ?? "—"}
          </div>
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
          "font-display text-3xl font-bold leading-none",
          accent ? "text-amber-text" : "text-ink",
        )}
      >
        {value}
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
  onTeamClick: (teamId: string) => void;
}

function DivisionStandingsCard({
  division,
  rows,
  isLoading,
  isError,
  error,
  activeTeamId,
  onTeamClick,
}: DivisionCardProps) {
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
              {rows.map((row) => (
                <tr
                  key={row.team_id}
                  onClick={() => onTeamClick(row.team_id)}
                  className={cn(
                    "cursor-pointer border-b border-border/40 transition last:border-b-0 hover:bg-surfaceAlt/40",
                    row.team_id === activeTeamId && "bg-amber/10 hover:bg-amber/15",
                  )}
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
              ))}
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
