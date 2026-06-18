/**
 * Always-visible status strip pinned below the AppShell header.
 *
 * Shows the current sim date, league phase, the user's team W-L record,
 * and their place in the division. Far right hosts compact Sim Day /
 * Week / Month buttons so the owner can advance the season from any
 * page without bouncing to /season.
 *
 * Mounted by AppShell once per signed-in route, so this is the single
 * source of truth for "where are we right now" affordances.
 */

import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  CalendarDays,
  ChevronsRight,
  Clock,
  FastForward,
  Forward,
  Inbox,
  Loader2,
  Trophy,
} from "lucide-react";

import { api, type SeasonState, type LeagueStandings } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { toast } from "@/lib/toast-store";
import { Badge, Button } from "@/components/ui";
import { cn } from "@/lib/cn";

// Keys MUST match the SeasonPhase enum values the backend sends (uppercase).
// They were previously lowercase ("regular", "postseason"), so every lookup
// missed and the ribbon rendered raw strings like "REGULAR_SEASON".
const PHASE_LABELS: Record<string, string> = {
  PRESEASON: "Preseason",
  REGULAR_SEASON: "Regular Season",
  AMATEUR_DRAFT: "Amateur Draft",
  PLAYOFFS: "Playoffs",
  OFFSEASON: "Offseason",
};

export function StatusRibbon() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const auth = useAuthStore();
  const teamId = auth.selectedTeamId ?? auth.teamId ?? null;

  const seasonQ = useQuery({
    queryKey: ["season-state"],
    queryFn: () => api.seasonState(),
    enabled: !!auth.token,
    refetchOnWindowFocus: false,
  });
  const standingsQ = useQuery({
    queryKey: ["league-standings"],
    queryFn: () => api.leagueStandings(),
    enabled: !!auth.token,
    refetchOnWindowFocus: false,
  });
  // Pull pending trades scoped to the user's team so we can flash a
  // "you have CPU offers waiting" badge on every page.
  const tradesQ = useQuery({
    queryKey: ["trades", { teamId, status: "pending" }],
    queryFn: () =>
      api.trades({ teamId: teamId ?? undefined, status: "pending" }),
    enabled: !!auth.token && !!teamId,
    refetchOnWindowFocus: false,
  });
  // Surface the trade deadline once it's within ~14 sim days so owners
  // get nudged before the window slams shut.
  const deadlineQ = useQuery({
    queryKey: ["trades-deadline"],
    queryFn: () => api.tradeDeadline(),
    enabled: !!auth.token,
    refetchOnWindowFocus: false,
  });

  const myStanding = useMemo(
    () => findStanding(standingsQ.data, teamId),
    [standingsQ.data, teamId],
  );
  const cpuOfferCount = useMemo(() => {
    if (!tradesQ.data || !teamId) return 0;
    return tradesQ.data.trades.filter(
      (t) => t.initiated_by === "cpu" && t.to_team === teamId,
    ).length;
  }, [tradesQ.data, teamId]);

  function refreshAll() {
    queryClient.invalidateQueries();
  }

  /** Surface CPU activity from a sim batch as a toast — DL activations,
   *  trade offers, etc. Otherwise the data sits silently in the response. */
  function announceSimResult(data: SeasonState) {
    const cpuTrades = data.automations?.cpu_trades as
      | { offers_created?: number }
      | undefined;
    const offersCreated = Number(cpuTrades?.offers_created ?? 0);
    if (offersCreated > 0) {
      toast.info(
        `${offersCreated} new CPU trade offer${offersCreated === 1 ? "" : "s"}`,
        { description: "Check the Trades page → Offers from CPU." },
      );
    }
    const dl = data.automations?.dl_updates;
    if (dl && Number(dl.activated ?? 0) > 0) {
      toast.info(
        `${dl.activated} player${dl.activated === 1 ? "" : "s"} returned from DL`,
      );
    }
  }

  const simDayMut = useMutation({
    mutationFn: () => api.seasonSimulateDay(),
    onSuccess: (data) => {
      refreshAll();
      announceSimResult(data);
    },
  });
  const simWeekMut = useMutation({
    mutationFn: () => api.seasonSimulateWeek(),
    onSuccess: (data) => {
      refreshAll();
      announceSimResult(data);
    },
  });
  const simMonthMut = useMutation({
    mutationFn: () => api.seasonSimulateMonth(),
    onSuccess: (data) => {
      refreshAll();
      announceSimResult(data);
    },
  });

  if (!auth.token) return null;

  const date = seasonQ.data?.current_date ?? null;
  const phase = seasonQ.data?.phase ?? null;
  const phaseLabel = phase ? (PHASE_LABELS[phase] ?? phase) : "—";
  const anySimming =
    simDayMut.isPending || simWeekMut.isPending || simMonthMut.isPending;

  // Sim buttons stay clickable in any phase the season simulator
  // accepts; the backend gates with proper errors when out of range
  // (e.g. preseason). Visually we only soften them when an active sim
  // is in flight.

  return (
    <div className="sticky top-[140px] z-10 flex items-center justify-between gap-3 border-b border-border/70 bg-surfaceAlt/80 px-6 py-1.5 text-xs backdrop-blur">
      {/* Left: date + phase */}
      <button
        type="button"
        onClick={() => navigate("/season")}
        className="flex items-center gap-2 rounded-md px-2 py-1 transition hover:bg-surface"
        title="Open Season hub"
      >
        <CalendarDays className="h-3.5 w-3.5 text-amber" />
        <span className="font-mono tabular-nums">{date ?? "—"}</span>
        <span className="text-muted">·</span>
        <span className="font-semibold">{phaseLabel}</span>
        {seasonQ.data?.draft_blocked && (
          <Badge tone="warning" className="ml-1 text-[10px]">
            Draft due
          </Badge>
        )}
      </button>

      {/* Middle: my team W-L + division place */}
      {myStanding ? (
        <button
          type="button"
          onClick={() => navigate("/standings")}
          className="flex items-center gap-2 rounded-md px-2 py-1 transition hover:bg-surface"
          title="Open standings"
        >
          <Trophy className="h-3.5 w-3.5 text-amber" />
          <span className="font-semibold">
            {myStanding.team.abbreviation || myStanding.team.team_id}
          </span>
          <span className="font-mono tabular-nums">
            {myStanding.team.wins}-{myStanding.team.losses}
          </span>
          <span className="text-muted">·</span>
          <span className="text-muted">
            {ordinal(myStanding.rank)} in {myStanding.division}
          </span>
          {myStanding.team.gb && myStanding.team.gb !== "—" && (
            <span className="text-muted">({myStanding.team.gb} GB)</span>
          )}
        </button>
      ) : (
        <span className="text-muted">No team selected</span>
      )}

      {/* CPU trade-offer indicator. Only shows when there are pending
          offers waiting on the user — kept compact so it doesn't crowd
          the ribbon when there's nothing to act on. */}
      {cpuOfferCount > 0 && (
        <button
          type="button"
          onClick={() => navigate("/trades")}
          className="flex items-center gap-1.5 rounded-md border border-amber/60 bg-amber/10 px-2 py-1 text-amber-text transition hover:bg-amber/20"
          title="Pending trade offers from the CPU"
        >
          <Inbox className="h-3.5 w-3.5" />
          <span className="text-xs font-semibold">
            {cpuOfferCount} CPU offer{cpuOfferCount === 1 ? "" : "s"}
          </span>
        </button>
      )}

      {/* Trade deadline nudge — only shows close-in (≤14 days) or
          right after the deadline so the ribbon stays clean most of
          the season. */}
      {deadlineQ.data &&
        (deadlineQ.data.is_past ||
          (deadlineQ.data.days_remaining >= 0 &&
            deadlineQ.data.days_remaining <= 14)) && (
          <button
            type="button"
            onClick={() => navigate("/trades")}
            className={cn(
              "flex items-center gap-1.5 rounded-md border px-2 py-1 transition",
              deadlineQ.data.is_past
                ? "border-danger/50 bg-danger/10 text-danger hover:bg-danger/20"
                : "border-amber/60 bg-amber/10 text-amber-text hover:bg-amber/20",
            )}
            title="Open Trades"
          >
            <Clock className="h-3.5 w-3.5" />
            <span className="text-xs font-semibold">
              {deadlineQ.data.is_past
                ? "Trade deadline closed"
                : `Deadline in ${deadlineQ.data.days_remaining}d`}
            </span>
          </button>
        )}

      {/* Right: sim buttons */}
      <div className="flex items-center gap-1">
        <SimButton
          label="+1 day"
          icon={<Forward className="h-3 w-3" />}
          pending={simDayMut.isPending}
          disabled={anySimming}
          onClick={() => simDayMut.mutate()}
        />
        <SimButton
          label="+1 wk"
          icon={<FastForward className="h-3 w-3" />}
          pending={simWeekMut.isPending}
          disabled={anySimming}
          onClick={() => simWeekMut.mutate()}
        />
        <SimButton
          label="+1 mo"
          icon={<ChevronsRight className="h-3 w-3" />}
          pending={simMonthMut.isPending}
          disabled={anySimming}
          onClick={() => simMonthMut.mutate()}
        />
      </div>
    </div>
  );
}

function SimButton({
  label,
  icon,
  pending,
  disabled,
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  pending: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      size="sm"
      variant="outline"
      onClick={onClick}
      disabled={disabled}
      className={cn("h-7 gap-1 px-2 text-[11px]", pending && "opacity-70")}
      title={`Simulate ${label.replace("+", "")}`}
    >
      {pending ? <Loader2 className="h-3 w-3 animate-spin" /> : icon}
      {label}
    </Button>
  );
}

interface MyStanding {
  team: LeagueStandings["divisions"][number]["teams"][number];
  division: string;
  rank: number;
}

function findStanding(
  standings: LeagueStandings | undefined,
  teamId: string | null,
): MyStanding | null {
  if (!standings || !teamId) return null;
  for (const div of standings.divisions) {
    const idx = div.teams.findIndex((t) => t.team_id === teamId);
    if (idx >= 0) {
      return {
        team: div.teams[idx]!,
        division: div.division || "Division",
        rank: idx + 1,
      };
    }
  }
  return null;
}

function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
}

// Re-export for any consumer that might want to react to season state.
export type { SeasonState };
