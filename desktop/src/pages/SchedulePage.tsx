/**
 * Phase 4 port of ui/schedule_page.py.
 *
 * Two-column layout: Upcoming games on the left, Played results on the
 * right. A header lets the user flip between "My team" (default -- uses the
 * selected or signed-in team) and "All teams" (league-wide).
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Home,
  Loader2,
  Plane,
} from "lucide-react";

import { api, type ScheduleGame, type Team } from "@/lib/api";
import { TeamLogo } from "@/components/TeamLogo";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";

type Scope = "team" | "league";

export function SchedulePage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;
  const [scope, setScope] = useState<Scope>(teamId ? "team" : "league");

  const effectiveScope: Scope = teamId ? scope : "league";

  const schedule = useQuery({
    queryKey: ["schedule", effectiveScope, teamId],
    queryFn: () =>
      api.schedule(
        effectiveScope === "team" && teamId ? { teamId } : { limit: 1000 },
      ),
  });

  // Shared teams query (other pages populate the same cache). Used to
  // hydrate TeamLogo colors alongside each game row.
  const teamsQ = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
  });
  const teamById = useMemo(() => {
    const m = new Map<string, Team>();
    for (const t of teamsQ.data ?? []) m.set(t.team_id, t);
    return m;
  }, [teamsQ.data]);

  const { upcoming, results } = useMemo(() => {
    const up: ScheduleGame[] = [];
    const done: ScheduleGame[] = [];
    for (const g of schedule.data?.games ?? []) {
      (g.played ? done : up).push(g);
    }
    done.reverse(); // most recent first
    return { upcoming: up, results: done };
  }, [schedule.data]);

  return (
    <AppShell
      title="Schedule"
      subtitle={
        effectiveScope === "team" && teamId
          ? `${teamId} · upcoming and played games`
          : "League-wide schedule"
      }
    >
      <div className="mb-4 flex items-center justify-between">
        <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
          <ScopePill
            active={effectiveScope === "team"}
            disabled={!teamId}
            onClick={() => setScope("team")}
          >
            My team
          </ScopePill>
          <ScopePill
            active={effectiveScope === "league"}
            onClick={() => setScope("league")}
          >
            All teams
          </ScopePill>
        </div>
        {schedule.data && (
          <div className="text-xs text-muted">
            {schedule.data.count} games
          </div>
        )}
      </div>

      {schedule.isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <Loader2 className="h-5 w-5 animate-spin text-amber" />
            <span className="text-sm text-muted">Loading schedule…</span>
          </CardContent>
        </Card>
      ) : schedule.isError ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-danger">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm">{(schedule.error as Error).message}</span>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <ScheduleCard
            title="Upcoming"
            description={`${upcoming.length} scheduled`}
            icon={<CalendarClock className="h-3 w-3" />}
            empty="No upcoming games."
            games={upcoming}
            teamId={effectiveScope === "team" ? teamId : null}
            teamById={teamById}
          />
          <ScheduleCard
            title="Results"
            description={`${results.length} played`}
            icon={<CheckCircle2 className="h-3 w-3" />}
            empty="No games played yet."
            games={results}
            teamId={effectiveScope === "team" ? teamId : null}
            teamById={teamById}
            reverseChrono
          />
        </div>
      )}
    </AppShell>
  );
}

function ScopePill({
  active,
  disabled,
  onClick,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
        active
          ? "bg-amber text-espresso"
          : "text-muted hover:bg-surface hover:text-ink",
        disabled && "pointer-events-none opacity-50",
      )}
    >
      {children}
    </button>
  );
}

interface ScheduleCardProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  empty: string;
  games: ScheduleGame[];
  teamId: string | null;
  teamById: Map<string, Team>;
  reverseChrono?: boolean;
}

function ScheduleCard({
  title,
  description,
  icon,
  empty,
  games,
  teamId,
  teamById,
}: ScheduleCardProps) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
        <Badge tone="amber">
          {icon} {games.length}
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        {games.length === 0 ? (
          <div className="px-6 py-6 text-sm text-muted">{empty}</div>
        ) : (
          <ul className="divide-y divide-border/60">
            {games.map((game, idx) => (
              <GameRow
                key={`${game.date}-${game.home}-${game.away}-${idx}`}
                game={game}
                teamId={teamId}
                teamById={teamById}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function GameRow({
  game,
  teamId,
  teamById,
}: {
  game: ScheduleGame;
  teamId: string | null;
  teamById: Map<string, Team>;
}) {
  const isTeamView = !!teamId;
  const isHome = game.is_home ?? game.home === teamId;
  const opponent = game.opponent ?? (isHome ? game.away : game.home);

  const logoFor = (tid: string | undefined, size = "h-5 w-5") => {
    if (!tid) return null;
    const t = teamById.get(tid);
    return (
      <TeamLogo
        teamId={tid}
        abbreviation={t?.abbreviation || tid}
        primaryColor={t?.primary_color}
        secondaryColor={t?.secondary_color}
        className={`${size} shrink-0 rounded text-[9px]`}
      />
    );
  };

  return (
    <li className="flex items-center justify-between gap-4 px-6 py-3 text-sm transition hover:bg-surfaceAlt/40">
      <div className="flex min-w-0 items-center gap-3">
        <div className="w-20 shrink-0 text-xs font-semibold uppercase tracking-wider text-muted">
          {formatDate(game.date)}
        </div>
        {isTeamView ? (
          <div className="flex items-center gap-2">
            {isHome ? (
              <Home className="h-4 w-4 text-amber" aria-label="Home" />
            ) : (
              <Plane className="h-4 w-4 text-muted" aria-label="Away" />
            )}
            <span className="text-xs font-semibold uppercase tracking-wider text-muted">
              {isHome ? "vs" : "@"}
            </span>
            {logoFor(opponent, "h-5 w-5")}
            <span className="font-semibold">{opponent}</span>
          </div>
        ) : (
          <div className="flex items-center gap-2 font-semibold">
            {logoFor(game.away, "h-5 w-5")}
            <span>{game.away}</span>
            <span className="text-muted">@</span>
            {logoFor(game.home, "h-5 w-5")}
            <span>{game.home}</span>
          </div>
        )}
      </div>
      <div className="flex items-center gap-2">
        {game.played ? (
          game.boxscore ? (
            <Link
              to={`/boxscore?path=${encodeURIComponent(game.boxscore)}`}
              title="View boxscore"
            >
              <Badge tone="neutral" className="cursor-pointer hover:border-amber/60 hover:text-amber-text">
                {game.result || "Final"}
              </Badge>
            </Link>
          ) : (
            <Badge tone="neutral">{game.result || "Final"}</Badge>
          )
        ) : (
          <Badge tone="amber">Scheduled</Badge>
        )}
      </div>
    </li>
  );
}

function formatDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}
