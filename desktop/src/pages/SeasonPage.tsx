/**
 * Phase 4 port of ui/season_progress_window.py.
 *
 * This is the hub users actually drive the app from. The workflow is:
 *   1. Check the current phase + date
 *   2. Click "Sim Day" / "Sim Week" / "Sim to Draft" / "Sim to Playoffs"
 *   3. Review progress, then repeat
 *
 * Each "sim" action is a POST to the sidecar that runs the same
 * ``SeasonSimulator.simulate_next_day()`` the PyQt window uses, so the
 * two UIs stay in sync against shared ``season_state.json`` +
 * ``schedule.csv``. Phase transitions (preseason -> regular -> draft ->
 * playoffs -> offseason) are advanced explicitly via "Advance Phase".
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  Calendar,
  CalendarDays,
  CalendarRange,
  FastForward,
  Flag,
  GraduationCap,
  Loader2,
  Play,
  Sparkles,
  Trophy,
} from "lucide-react";

import { useAuthStore } from "@/lib/auth-store";

import { api, type SeasonPhase, type SeasonState } from "@/lib/api";
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

interface RecentJump {
  label: string;
  at: string;
  played: string[];
  errors?: string[];
}

const PHASE_LABEL: Record<SeasonPhase, string> = {
  PRESEASON: "Preseason",
  REGULAR_SEASON: "Regular Season",
  AMATEUR_DRAFT: "Amateur Draft",
  PLAYOFFS: "Playoffs",
  OFFSEASON: "Offseason",
};

const PHASE_ORDER: SeasonPhase[] = [
  "PRESEASON",
  "REGULAR_SEASON",
  "AMATEUR_DRAFT",
  "PLAYOFFS",
  "OFFSEASON",
];

export function SeasonPage() {
  const queryClient = useQueryClient();
  const [recent, setRecent] = useState<RecentJump[]>([]);

  const state = useQuery({
    queryKey: ["season-state"],
    queryFn: () => api.seasonState(),
  });

  function recordJump(label: string, result: SeasonState) {
    setRecent((prev) => {
      const entry: RecentJump = {
        label,
        at: new Date().toLocaleTimeString(),
        played: result.played_dates ?? [],
        errors: result.errors && result.errors.length > 0 ? result.errors : undefined,
      };
      return [entry, ...prev].slice(0, 8);
    });
  }

  function useSimMutation(
    label: string,
    fn: () => Promise<SeasonState>,
  ) {
    return useMutation({
      mutationFn: fn,
      onSuccess: (result) => {
        recordJump(label, result);
        queryClient.setQueryData(["season-state"], result);
        // Side-effect queries that depend on schedule / standings state.
        queryClient.invalidateQueries({ queryKey: ["league-standings"] });
        queryClient.invalidateQueries({ queryKey: ["schedule"] });
        queryClient.invalidateQueries({ queryKey: ["team-snapshot"] });
        queryClient.invalidateQueries({ queryKey: ["team-division"] });
      },
    });
  }

  const simDay = useSimMutation("Sim Day", () => api.seasonSimulateDay());
  const simWeek = useSimMutation("Sim Week", () => api.seasonSimulateWeek());
  const simMonth = useSimMutation("Sim Month", () => api.seasonSimulateMonth());
  const simToDraft = useSimMutation("Sim to Draft", () => api.seasonSimulateToDraft());
  const simToPlayoffs = useSimMutation(
    "Sim to Playoffs",
    () => api.seasonSimulateToPlayoffs(),
  );
  const advancePhase = useSimMutation(
    "Advance Phase",
    () => api.seasonAdvancePhase(),
  );

  const anyPending =
    simDay.isPending ||
    simWeek.isPending ||
    simMonth.isPending ||
    simToDraft.isPending ||
    simToPlayoffs.isPending ||
    advancePhase.isPending;

  const activeLabel = useMemo(() => {
    if (simDay.isPending) return "Simulating a day…";
    if (simWeek.isPending) return "Simulating a week…";
    if (simMonth.isPending) return "Simulating a month…";
    if (simToDraft.isPending) return "Simulating to draft day…";
    if (simToPlayoffs.isPending) return "Simulating to end of regular season…";
    if (advancePhase.isPending) return "Advancing phase…";
    return null;
  }, [
    simDay.isPending,
    simWeek.isPending,
    simMonth.isPending,
    simToDraft.isPending,
    simToPlayoffs.isPending,
    advancePhase.isPending,
  ]);

  return (
    <AppShell
      title="Season"
      subtitle="Advance the calendar a day, a week, a month, or to a milestone."
    >
      {state.isLoading ? (
        <LoadingCard />
      ) : state.isError ? (
        <ErrorCard message={(state.error as Error).message} />
      ) : state.data ? (
        <div className="space-y-6 animate-fade-in">
          {state.data.days_total === 0 && <NoScheduleBanner />}
          {(state.data.draft_blocked ||
            state.data.phase === "AMATEUR_DRAFT") && <DraftReadyBanner />}
          <PhaseHeader state={state.data} />
          <MetricsRow state={state.data} />
          <ActionsCard
            state={state.data}
            disabled={
              anyPending ||
              state.data.days_total === 0 ||
              !!state.data.draft_blocked ||
              state.data.phase === "AMATEUR_DRAFT"
            }
            activeLabel={activeLabel}
            onSimDay={() => simDay.mutate()}
            onSimWeek={() => simWeek.mutate()}
            onSimMonth={() => simMonth.mutate()}
            onSimToDraft={() => simToDraft.mutate()}
            onSimToPlayoffs={() => simToPlayoffs.mutate()}
            onAdvancePhase={() => advancePhase.mutate()}
          />
          <RecentCard recent={recent} />
        </div>
      ) : null}
    </AppShell>
  );
}

function DraftReadyBanner() {
  return (
    <Card className="border-amber/50 bg-amber/10">
      <CardContent className="flex items-start gap-3 py-4">
        <GraduationCap className="mt-0.5 h-5 w-5 shrink-0 text-amber" />
        <div className="flex-1 text-sm">
          <div className="font-semibold text-amber-text">
            Amateur draft is ready
          </div>
          <p className="mt-1 text-muted">
            The calendar reached draft day. Sim actions are paused until the
            commissioner commits the draft — head to the Draft page to
            generate the pool and run the selections.
          </p>
          <p className="mt-2 text-xs">
            <Link
              to="/draft"
              className="font-semibold text-amber underline-offset-2 hover:underline"
            >
              Open Draft →
            </Link>
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function NoScheduleBanner() {
  const role = useAuthStore((s) => s.role);
  const isAdmin = role === "admin";
  return (
    <Card className="border-warning/40 bg-warning/10">
      <CardContent className="flex items-start gap-3 py-4">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning" />
        <div className="flex-1 text-sm">
          <div className="font-semibold text-warning">No schedule loaded</div>
          <p className="mt-1 text-muted">
            The league has no <code>schedule.csv</code>, so "Sim Day",
            "Sim Week", and the milestone jumps have nothing to play. If
            you advance the phase anyway the calendar ticks over without
            any games being simulated.
          </p>
          {isAdmin ? (
            <p className="mt-2 text-xs text-muted">
              Generate one now:{" "}
              <Link
                to="/admin-league"
                className="font-semibold text-amber underline-offset-2 hover:underline"
              >
                Admin → Regenerate schedule
              </Link>
              .
            </p>
          ) : (
            <p className="mt-2 text-xs text-muted">
              Ask the commissioner to regenerate the schedule from{" "}
              <span className="font-semibold">Admin → Regenerate schedule</span>.
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function PhaseHeader({ state }: { state: SeasonState }) {
  return (
    <Card className="p-6">
      <div className="relative flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
            Current Phase
          </div>
          <div className="font-display text-3xl font-bold">
            {PHASE_LABEL[state.phase] ?? state.phase}
          </div>
          <div className="mt-1 text-sm text-muted">
            {state.current_date
              ? `Next date: ${formatDate(state.current_date)}`
              : "No scheduled dates remaining."}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {PHASE_ORDER.map((p, i) => {
            const active = p === state.phase;
            return (
              <div key={p} className="flex items-center gap-2">
                <div
                  className={cn(
                    "flex h-7 items-center rounded-full border px-3 text-[11px] font-semibold uppercase tracking-wider",
                    active
                      ? "border-amber bg-amber/20 text-amber-text"
                      : "border-border text-muted",
                  )}
                >
                  {PHASE_LABEL[p]}
                </div>
                {i < PHASE_ORDER.length - 1 && (
                  <ArrowRight className="h-3 w-3 text-muted" />
                )}
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}

function MetricsRow({ state }: { state: SeasonState }) {
  const progress = state.days_total > 0
    ? Math.round((state.days_played / state.days_total) * 100)
    : 0;
  return (
    <section className="grid grid-cols-1 gap-4 md:grid-cols-4">
      <StatCard
        label="Progress"
        value={`${progress}%`}
        sub={`${state.days_played}/${state.days_total} days`}
        Icon={CalendarDays}
        tone="amber"
      />
      <StatCard
        label="Days Remaining"
        value={state.days_remaining}
        sub={
          state.mid_remaining > 0
            ? `${state.mid_remaining} until midseason`
            : state.all_star_played
              ? "Past All-Star Break"
              : "—"
        }
        Icon={CalendarRange}
      />
      <StatCard
        label="Draft Day"
        value={state.draft_date ? formatDate(state.draft_date) : "—"}
        sub={
          state.draft_triggered
            ? "Draft already triggered"
            : state.draft_date
              ? "Scheduled"
              : undefined
        }
        Icon={GraduationCap}
        tone={state.draft_triggered ? "success" : "neutral"}
      />
      <StatCard
        label="Next Date"
        value={state.current_date ? formatDate(state.current_date) : "—"}
        sub={state.current_date ? formatWeekday(state.current_date) : undefined}
        Icon={Calendar}
      />
    </section>
  );
}

interface ActionsProps {
  state: SeasonState;
  disabled: boolean;
  activeLabel: string | null;
  onSimDay: () => void;
  onSimWeek: () => void;
  onSimMonth: () => void;
  onSimToDraft: () => void;
  onSimToPlayoffs: () => void;
  onAdvancePhase: () => void;
}

function ActionsCard({
  state,
  disabled,
  activeLabel,
  onSimDay,
  onSimWeek,
  onSimMonth,
  onSimToDraft,
  onSimToPlayoffs,
  onAdvancePhase,
}: ActionsProps) {
  const noDaysLeft = state.days_remaining === 0;
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Advance the Season</CardTitle>
          <CardDescription>
            {activeLabel ??
              "Each action runs the real SeasonSimulator in the Python sidecar."}
          </CardDescription>
        </div>
        {disabled && (
          <Badge tone="amber">
            <Loader2 className="h-3 w-3 animate-spin" /> Working
          </Badge>
        )}
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Button
          onClick={onSimDay}
          disabled={disabled || noDaysLeft}
          className="w-full"
        >
          <Play className="h-4 w-4" /> Sim Day
        </Button>
        <Button
          variant="secondary"
          onClick={onSimWeek}
          disabled={disabled || noDaysLeft}
          className="w-full"
        >
          <FastForward className="h-4 w-4" /> Sim Week
        </Button>
        <Button
          variant="secondary"
          onClick={onSimMonth}
          disabled={disabled || noDaysLeft}
          className="w-full"
        >
          <FastForward className="h-4 w-4" /> Sim Month
        </Button>
        <Button
          variant="outline"
          onClick={onSimToDraft}
          disabled={disabled || noDaysLeft || !state.draft_date || state.draft_triggered}
          className="w-full"
        >
          <GraduationCap className="h-4 w-4" /> To Draft
        </Button>
        <Button
          variant="outline"
          onClick={onSimToPlayoffs}
          disabled={disabled || noDaysLeft}
          className="w-full"
        >
          <Trophy className="h-4 w-4" /> To Playoffs
        </Button>
        <Button
          variant="ghost"
          onClick={onAdvancePhase}
          disabled={disabled}
          className="w-full"
        >
          <Flag className="h-4 w-4" /> Advance Phase
        </Button>
      </CardContent>
    </Card>
  );
}

function RecentCard({ recent }: { recent: RecentJump[] }) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Recent Jumps</CardTitle>
          <CardDescription>
            Last few actions taken from this window in this session.
          </CardDescription>
        </div>
        <Badge tone="neutral">{recent.length}</Badge>
      </CardHeader>
      <CardContent className="p-0">
        {recent.length === 0 ? (
          <div className="flex items-center gap-2 px-6 py-8 text-sm text-muted">
            <Sparkles className="h-4 w-4" />
            No jumps yet — hit a button above to advance the calendar.
          </div>
        ) : (
          <ul className="divide-y divide-border/60">
            {recent.map((entry, i) => (
              <li key={i} className="px-6 py-3 text-sm">
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">{entry.label}</span>
                    <span className="text-xs text-muted">{entry.at}</span>
                  </div>
                  <Badge tone={entry.errors ? "danger" : "success"}>
                    {entry.errors ? "Partial" : `${entry.played.length} days`}
                  </Badge>
                </div>
                {entry.played.length > 0 && (
                  <div className="mt-1 font-mono text-[11px] text-muted">
                    {entry.played[0]}
                    {entry.played.length > 1 &&
                      ` → ${entry.played[entry.played.length - 1]}`}{" "}
                    ({entry.played.length} total)
                  </div>
                )}
                {entry.errors && (
                  <div className="mt-1 flex items-start gap-2 text-xs text-danger">
                    <AlertTriangle className="mt-0.5 h-3 w-3" />
                    <div>{entry.errors.join("; ")}</div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function formatDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatWeekday(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { weekday: "long" });
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading season state…</span>
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

