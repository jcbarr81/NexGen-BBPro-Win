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

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  Banknote,
  Bell,
  Calendar,
  CalendarClock,
  CalendarDays,
  CalendarRange,
  Dumbbell,
  FastForward,
  Flag,
  GraduationCap,
  Loader2,
  Play,
  Sparkles,
  Trophy,
  UserMinus,
  X,
} from "lucide-react";

import { useAuthStore } from "@/lib/auth-store";

import {
  api,
  type FaWindowSchedule,
  type FaWindowScheduleInput,
  type FaWindowStatus,
  type NotificationEvent,
  type SeasonActionItem,
  type SeasonPhase,
  type SeasonReadiness,
  type SeasonScheduleInput,
  type SeasonScheduleRunKind,
  type SeasonState,
} from "@/lib/api";
import { toast } from "@/lib/toast-store";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import { LeagueTrainingDialog } from "@/components/LeagueTrainingDialog";
import { SimProgressOverlay } from "@/components/SimProgressOverlay";
import { StatCard } from "@/components/StatCard";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
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
  const [lastNotifications, setLastNotifications] = useState<NotificationEvent[]>([]);
  const [stopReason, setStopReason] = useState<string | null>(null);

  const state = useQuery({
    queryKey: ["season-state"],
    queryFn: () => api.seasonState(),
  });

  // Multi-owner: season progression is commissioner-driven. Fetch the league
  // readiness so the commissioner can see who's holding things up, and so we can
  // hide the progression controls from non-commissioner owners.
  const role = useAuthStore((s) => s.role);
  const isCommish = role === "admin";
  const readiness = useQuery({
    queryKey: ["season-readiness"],
    queryFn: () => api.seasonReadiness(),
  });
  const teamId = useAuthStore((s) => s.selectedTeamId ?? s.teamId ?? null);
  const multiOwner = (readiness.data?.human_team_count ?? 0) >= 2;
  const canProgress = isCommish || !multiOwner;

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
    setLastNotifications(result.notifications ?? []);
    setStopReason(result.sim_stopped_reason ?? null);
  }

  function useSimMutation(
    label: string,
    fn: () => Promise<SeasonState>,
  ) {
    return useMutation({
      mutationFn: fn,
      onError: (err) => {
        // Surface progression blocks (e.g. "teams not ready", commissioner-only)
        // and refresh the readiness board so it reflects the reason.
        const body = (err as { body?: { detail?: unknown } }).body;
        const detail = body?.detail;
        const msg =
          detail && typeof detail === "object" && "message" in detail
            ? String((detail as { message?: unknown }).message)
            : (err as Error).message;
        toast.error(msg);
        queryClient.invalidateQueries({ queryKey: ["season-readiness"] });
      },
      onSuccess: (result) => {
        recordJump(label, result);
        queryClient.setQueryData(["season-state"], result);
        // A sim batch touches almost every cached query (standings,
        // stats, leaders, news, finance, rosters, lineups, dashboard
        // widgets, history, …). Rather than enumerate every key —
        // which is brittle as new pages get added — invalidate
        // everything. React Query refetches lazily, so only the
        // queries the user has open actually re-fire.
        queryClient.invalidateQueries();
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
      <SimProgressOverlay open={anyPending} label={activeLabel} />
      {state.isLoading ? (
        <LoadingCard />
      ) : state.isError ? (
        <ErrorCard message={(state.error as Error).message} />
      ) : state.data ? (
        <div className="space-y-6 animate-fade-in">
          {state.data.days_total === 0 && (
            <NoScheduleBanner phase={state.data.phase} />
          )}
          {(state.data.draft_blocked ||
            state.data.phase === "AMATEUR_DRAFT") && <DraftReadyBanner />}
          {(lastNotifications.length > 0 || stopReason) && (
            <NotificationsBanner
              events={lastNotifications}
              stopReason={stopReason}
              onDismiss={() => {
                setLastNotifications([]);
                setStopReason(null);
              }}
            />
          )}
          <NextStepBanner state={state.data} />
          <FinanceTodoBanner />
          <PhaseHeader state={state.data} />
          <MetricsRow state={state.data} />
          {teamId && <ActionItemsCard />}
          {multiOwner && isCommish && (
            <ReadinessBoard
              readiness={readiness.data}
              phase={state.data.phase}
            />
          )}
          {canProgress ? (
            <ActionsCard
              state={state.data}
              disabled={
                anyPending ||
                state.data.days_total === 0 ||
                !!state.data.draft_blocked ||
                state.data.phase === "AMATEUR_DRAFT"
              }
              simBlocked={state.data.phase !== "REGULAR_SEASON"}
              // Advance Phase mirrors the backend's advance gates: it's only
              // enabled once the current phase is actually ready to move on
              // (regular season finished, draft committed, champion crowned).
              // PRESEASON/OFFSEASON have no gate and stay enabled.
              advanceDisabled={
                anyPending || !isPhaseReadyToAdvance(state.data)
              }
              activeLabel={activeLabel}
              onSimDay={() => simDay.mutate()}
              onSimWeek={() => simWeek.mutate()}
              onSimMonth={() => simMonth.mutate()}
              onSimToDraft={() => simToDraft.mutate()}
              onSimToPlayoffs={() => simToPlayoffs.mutate()}
              onAdvancePhase={() => advancePhase.mutate()}
            />
          ) : (
            <OwnerWaitingCard teamId={teamId} readiness={readiness.data} />
          )}
          {state.data.phase === "OFFSEASON" && <FreeAgencyWindowCard />}
          {state.data.phase === "PRESEASON" && (
            <PreseasonActionsCard state={state.data} />
          )}
          <RecentCard recent={recent} />
        </div>
      ) : null}
    </AppShell>
  );
}

function NextStepBanner({ state }: { state: SeasonState }) {
  // Draft-ready and no-schedule each have their own richer banner — don't
  // double-prompt.
  if (state.draft_blocked || state.phase === "AMATEUR_DRAFT") return null;
  if (state.days_total === 0) return null;

  const guidance = buildNextStep(state);
  if (!guidance) return null;

  return (
    <Card className="border-amber/30 bg-amber/5">
      <CardContent className="flex items-start gap-3 py-4">
        <Sparkles className="mt-0.5 h-5 w-5 shrink-0 text-amber" />
        <div className="flex-1 text-sm">
          <div className="font-semibold text-amber-text">
            {guidance.title}
          </div>
          <p className="mt-1 text-muted">{guidance.body}</p>
          {guidance.cta && (
            <p className="mt-2 text-xs">
              <Link
                to={guidance.cta.to}
                className="font-semibold text-amber underline-offset-2 hover:underline"
              >
                {guidance.cta.label} →
              </Link>
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

interface NextStep {
  title: string;
  body: string;
  cta?: { label: string; to: string };
}

const TODO_DOT_TONE: Record<string, string> = {
  critical: "bg-danger",
  warning: "bg-amber",
  info: "bg-muted",
};

/** Phase-aware "what finance step do I need to take" list for the owner's
 *  team. Hidden entirely when finance is off or there's nothing pending. */
function FinanceTodoBanner() {
  const teamId = useAuthStore((s) => s.selectedTeamId ?? s.teamId ?? null);
  const todo = useQuery({
    queryKey: ["finance-todo", teamId],
    queryFn: () => api.financeTodo(teamId as string),
    enabled: !!teamId,
    refetchOnWindowFocus: false,
  });

  const items = todo.data?.items ?? [];
  if (!todo.data?.finance_enabled || items.length === 0) return null;

  return (
    <Card className="border-amber/30 bg-amber/5">
      <CardContent className="py-4">
        <div className="flex items-center gap-2">
          <Banknote className="h-5 w-5 shrink-0 text-amber" />
          <div className="font-semibold text-amber-text">
            Finance — actions for your team
          </div>
        </div>
        <ul className="mt-2 space-y-1.5">
          {items.map((item) => (
            <li key={item.id} className="flex items-start gap-2 text-sm">
              <span
                className={cn(
                  "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                  TODO_DOT_TONE[item.severity] ?? "bg-muted",
                )}
              />
              <span className="flex-1 text-muted">{item.label}</span>
              <Link
                to={item.to}
                className="shrink-0 text-xs font-semibold text-amber underline-offset-2 hover:underline"
              >
                Open →
              </Link>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

/** True once the amateur draft is behind us. Prefer the backend's
 *  authoritative `draft_completed` flag; fall back to the date heuristic so
 *  the UI is still correct against an older backend. (The date-only check
 *  failed at season end, where `current_date` is null — that's exactly why
 *  the milestone banner wrongly pointed at the draft.) */
function isDraftDone(state: SeasonState): boolean {
  if (state.draft_completed) return true;
  if (state.draft_triggered) return true;
  if (state.draft_date && state.current_date) {
    return state.current_date > state.draft_date;
  }
  return false;
}

/** True when the regular-season schedule is fully played. Prefer the backend
 *  flag; fall back to "no days remaining while in the regular season." */
function isSeasonComplete(state: SeasonState): boolean {
  if (state.season_complete) return true;
  return state.phase === "REGULAR_SEASON" && (state.days_remaining ?? 0) === 0;
}

/** Whether the current phase is actually ready to advance — mirrors the
 *  backend's advance-phase gates so the button isn't clickable when the
 *  click would just bounce with an error (e.g. unfinished playoffs). */
function isPhaseReadyToAdvance(state: SeasonState): boolean {
  switch (state.phase) {
    case "REGULAR_SEASON":
      return isSeasonComplete(state);
    case "AMATEUR_DRAFT":
      return isDraftDone(state);
    case "PLAYOFFS":
      return !!state.playoffs_complete;
    case "PRESEASON":
      // Spring training must be run before Opening Day (#13) — the backend
      // refuses the advance until it is, so mirror that gate here.
      return !!state.preseason_done?.training_camp;
    // OFFSEASON has no backend gate — always ready.
    default:
      return true;
  }
}

/** Hover/disabled hint explaining why Advance Phase isn't available yet. */
function advanceBlockedReason(state: SeasonState): string | undefined {
  switch (state.phase) {
    case "REGULAR_SEASON":
      return "Finish the regular season (play all scheduled games) before advancing to the Playoffs.";
    case "AMATEUR_DRAFT":
      return "Commit the amateur draft before advancing.";
    case "PLAYOFFS":
      return "Resolve the playoff bracket and crown a champion (Playoffs page) before advancing to the Offseason.";
    case "PRESEASON":
      return "Run Spring Training first — open Preseason Actions below and click 'Run Training Camp' before starting the Regular Season.";
    default:
      return undefined;
  }
}

function buildNextStep(state: SeasonState): NextStep | null {
  switch (state.phase) {
    case "PRESEASON":
      return {
        title: "Preseason — get the league ready to play",
        body:
          "Run spring training to mark every player as ready, review free agents, and confirm league-wide training focus. When you're done, click Advance Phase to start the Regular Season.",
      };
    case "REGULAR_SEASON": {
      // Season's done — title and body must agree (the old code left the
      // title pointing at the long-past draft while the body said "all games
      // played"). Send the user straight to Advance Phase → Playoffs.
      if (isSeasonComplete(state)) {
        return {
          title: "Regular Season complete — time for the Playoffs",
          body: "All regular-season games are played. Click Advance Phase to seed the bracket and start the Playoffs.",
        };
      }
      const remaining = state.days_remaining ?? 0;
      const draftDate = isDraftDone(state) ? null : state.draft_date;
      const nextLabel = draftDate
        ? `Amateur Draft on ${formatDate(draftDate)}`
        : "the end of the schedule";
      return {
        title: `Regular Season — next milestone is ${nextLabel}`,
        body: `${remaining} scheduled day${remaining === 1 ? "" : "s"} remain. Use Sim Day/Week/Month to advance incrementally, or ${draftDate ? "'To Draft' to fast-forward to draft day" : "'To Playoffs' to finish the regular season"}.`,
      };
    }
    case "PLAYOFFS":
      if (state.playoffs_complete) {
        return {
          title: "Playoffs complete — champion crowned",
          body:
            "The postseason is finished. Click Advance Phase to close out the season and start the Offseason tasks (arbitration, contract rollover, GM finance queue, free agency).",
          cta: { label: "View Playoffs", to: "/playoffs" },
        };
      }
      return {
        title: "Playoffs — resolve the bracket",
        body:
          "Play out the playoff rounds on the Playoffs page. Once a champion is crowned, Advance Phase will move the league into the Offseason.",
        cta: { label: "Open Playoffs", to: "/playoffs" },
      };
    case "OFFSEASON":
      return {
        title: "Offseason — run the finance rollover",
        body:
          "Work through the offseason checklist (arbitration, contract rollover, GM finance queue, free agency kickoff). When the checklist is complete, Advance Phase begins the next Preseason.",
        cta: { label: "Open Offseason", to: "/offseason" },
      };
    default:
      return null;
  }
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

function NoScheduleBanner({ phase }: { phase: SeasonPhase }) {
  const role = useAuthStore((s) => s.role);
  const isAdmin = role === "admin";

  // Between seasons, the next schedule is generated automatically when the
  // owner advances into the new season — no manual regenerate needed.
  if (phase === "OFFSEASON") {
    return (
      <Card className="border-amber/30 bg-amber/5">
        <CardContent className="flex items-start gap-3 py-4">
          <Sparkles className="mt-0.5 h-5 w-5 shrink-0 text-amber" />
          <div className="flex-1 text-sm">
            <div className="font-semibold text-amber-text">
              Offseason — next season not scheduled yet
            </div>
            <p className="mt-1 text-muted">
              That's expected between seasons. When you click{" "}
              <span className="font-semibold">Advance Phase</span> to start the
              new season, a fresh schedule is generated automatically — no
              manual step needed.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

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
                to="/league-admin"
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
          isDraftDone(state)
            ? "Complete"
            : state.draft_date
              ? "Scheduled"
              : undefined
        }
        Icon={GraduationCap}
        tone={isDraftDone(state) ? "success" : "neutral"}
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
  simBlocked: boolean;
  advanceDisabled: boolean;
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
  simBlocked,
  advanceDisabled,
  activeLabel,
  onSimDay,
  onSimWeek,
  onSimMonth,
  onSimToDraft,
  onSimToPlayoffs,
  onAdvancePhase,
}: ActionsProps) {
  const noDaysLeft = state.days_remaining === 0;
  const simDisabled = disabled || noDaysLeft || simBlocked;
  // When the sim buttons are structurally locked (phase boundary or the
  // schedule is exhausted), Advance Phase is the only way forward — make it
  // the prominent CTA instead of a greyed-out "Sim Day" stealing focus.
  const advancePrimary = simBlocked || noDaysLeft;
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Advance the Season</CardTitle>
          <CardDescription>
            {simBlocked
              ? `Sim is locked during ${PHASE_LABEL[state.phase] ?? state.phase} — Advance Phase to start the regular season.`
              : (activeLabel ??
                "Each action runs the real SeasonSimulator in the Python sidecar.")}
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
          disabled={simDisabled}
          className="w-full"
        >
          <Play className="h-4 w-4" /> Sim Day
        </Button>
        <Button
          variant="secondary"
          onClick={onSimWeek}
          disabled={simDisabled}
          className="w-full"
        >
          <FastForward className="h-4 w-4" /> Sim Week
        </Button>
        <Button
          variant="secondary"
          onClick={onSimMonth}
          disabled={simDisabled}
          className="w-full"
        >
          <FastForward className="h-4 w-4" /> Sim Month
        </Button>
        <Button
          variant="outline"
          onClick={onSimToDraft}
          disabled={simDisabled || !state.draft_date || isDraftDone(state)}
          className="w-full"
        >
          <GraduationCap className="h-4 w-4" /> To Draft
        </Button>
        <Button
          variant="outline"
          onClick={onSimToPlayoffs}
          disabled={simDisabled}
          className="w-full"
        >
          <Trophy className="h-4 w-4" /> To Playoffs
        </Button>
        <Button
          variant={advancePrimary ? "primary" : "ghost"}
          onClick={onAdvancePhase}
          disabled={advanceDisabled}
          title={
            !isPhaseReadyToAdvance(state) ? advanceBlockedReason(state) : undefined
          }
          className="w-full"
        >
          <Flag className="h-4 w-4" /> Advance Phase
        </Button>
      </CardContent>
    </Card>
  );
}

function PreseasonActionsCard({ state }: { state: SeasonState }) {
  const queryClient = useQueryClient();
  const [leagueTrainingOpen, setLeagueTrainingOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const teamId = useAuthStore((s) => s.selectedTeamId ?? s.teamId ?? null);

  const freeAgencyDone = !!state.preseason_done?.free_agency;
  const trainingCampDone = !!state.preseason_done?.training_camp;

  const refreshSeasonState = () => {
    queryClient.invalidateQueries({ queryKey: ["season-state"] });
  };

  // Preseason FA bidding window (finance leagues only). Opens lazily on the
  // server the first time this is polled in the preseason.
  const faWindow = useQuery({
    queryKey: ["fa-window"],
    queryFn: () => api.faWindowState(),
  });
  const win = faWindow.data;
  const windowActive = !!win?.finance_enabled && !!win?.exists;
  const windowOpen = windowActive && win?.status !== "closed";
  const sweepLocked = !!win?.sweep_locked;

  const advanceFaDay = useMutation({
    mutationFn: () => api.faWindowAdvanceDay(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["fa-window"] });
      refreshSeasonState();
      const signed = data.result?.signed ?? [];
      const msg = signed.length
        ? `Day advanced — ${signed.length} signing${signed.length === 1 ? "" : "s"}: ${signed
            .slice(0, 4)
            .map((s) => s.player_name)
            .join(", ")}${signed.length > 4 ? "…" : ""}.`
        : "Day advanced — no signings.";
      if (data.window?.status === "closed") {
        toast.success("Free-agency window closed — you can now let CPU teams fill their rosters.");
      } else {
        toast.info(msg);
      }
    },
    onError: (err) => toast.error((err as Error).message),
  });

  const listUnsigned = useMutation({
    mutationFn: () => api.preseasonListUnsigned(true),
    onSuccess: (data) => {
      refreshSeasonState();
      const count = data?.unsigned_count ?? 0;
      const names = data?.unsigned_names ?? [];
      const cpuMsg = data?.cpu_running
        ? "CPU teams are signing free agents in the background — refresh in a moment to see updates. "
        : "";
      const msg =
        count === 0
          ? `${cpuMsg}No unsigned players available.`
          : `${cpuMsg}${count} unsigned player${count === 1 ? "" : "s"} available${names.length ? `: ${names.slice(0, 5).join(", ")}${names.length > 5 ? "…" : ""}` : ""}.`;
      setNotice(msg);
      toast.info(msg);
    },
    onError: (err) => toast.error((err as Error).message),
  });

  const trainingCamp = useMutation({
    mutationFn: () => api.preseasonTrainingCamp(),
    onSuccess: (data) => {
      refreshSeasonState();
      const topNames = data.top_gainers
        .map((g) => `${g.name} (+${g.total_gain})`)
        .join(", ");
      const msg = `Training camp completed for ${data.players_processed} players.${topNames ? ` Top gainers: ${topNames}.` : ""}`;
      setNotice(msg);
      toast.success(msg);
    },
    onError: (err) => toast.error((err as Error).message),
  });

  return (
    <>
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Preseason Actions</CardTitle>
            <CardDescription>
              Run spring training, review unsigned free agents, and set the
              league-wide training focus split.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {windowActive && (
            <FaBiddingWindowPanel
              win={win!}
              teamId={teamId}
              onAdvance={() => advanceFaDay.mutate()}
              advancing={advanceFaDay.isPending}
              canAdvance={windowOpen}
            />
          )}
          <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
            <Button
              variant="ghost"
              onClick={() => listUnsigned.mutate()}
              disabled={listUnsigned.isPending || freeAgencyDone || sweepLocked}
              className="justify-start"
              title={
                sweepLocked
                  ? `Locked until the free-agency bidding window closes (day ${win?.day} of ${win?.total_days})`
                  : freeAgencyDone
                    ? "Free agency review already completed for this preseason"
                    : "Let CPU teams fill their rosters from the remaining free agents"
              }
            >
              {listUnsigned.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <UserMinus className="h-4 w-4" />
              )}
              {freeAgencyDone ? "List Unsigned Players ✓" : "List Unsigned Players"}
            </Button>
            <Button
              variant="ghost"
              onClick={() => trainingCamp.mutate()}
              disabled={trainingCamp.isPending || trainingCampDone}
              className="justify-start"
              title={
                trainingCampDone
                  ? "Training camp already completed for this preseason"
                  : "Runs spring training for every player"
              }
            >
              {trainingCamp.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Dumbbell className="h-4 w-4" />
              )}
              {trainingCampDone ? "Run Training Camp ✓" : "Run Training Camp"}
            </Button>
            <Button
              variant="ghost"
              onClick={() => setLeagueTrainingOpen(true)}
              className="justify-start"
              title="Edit league-wide default training split"
            >
              <GraduationCap className="h-4 w-4" />
              Training Focus…
            </Button>
          </div>
          {notice && (
            <div className="rounded-md border border-border bg-surfaceAlt/40 px-3 py-2 text-xs text-muted">
              {notice}
            </div>
          )}
        </CardContent>
      </Card>
      <LeagueTrainingDialog
        open={leagueTrainingOpen}
        onOpenChange={setLeagueTrainingOpen}
      />
    </>
  );
}

function FreeAgencyWindowCard() {
  const queryClient = useQueryClient();
  const teamId = useAuthStore((s) => s.selectedTeamId ?? s.teamId ?? null);
  const role = useAuthStore((s) => s.role);
  const isCommish = role === "admin";

  // Free agency runs in the offseason. Polling opens the window lazily on the
  // server (finance leagues only) the first time it's hit in the offseason.
  const faWindow = useQuery({
    queryKey: ["fa-window"],
    queryFn: () => api.faWindowState(),
  });
  const win = faWindow.data;
  const windowActive = !!win?.finance_enabled && !!win?.exists;
  const windowOpen = windowActive && win?.status !== "closed";
  const humanTeams = win?.human_teams ?? [];
  const multiOwner = humanTeams.length >= 2;
  // Commissioner-driven: only the commissioner advances the FA day in a
  // multi-owner league (the lone owner does in solo).
  const canProgress = isCommish || !multiOwner;

  const advanceFaDay = useMutation({
    mutationFn: () => api.faWindowAdvanceDay(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["fa-window"] });
      queryClient.invalidateQueries({ queryKey: ["season-state"] });
      const signed = data.result?.signed ?? [];
      const msg = signed.length
        ? `Day advanced — ${signed.length} signing${signed.length === 1 ? "" : "s"}: ${signed
            .slice(0, 4)
            .map((s) => s.player_name)
            .join(", ")}${signed.length > 4 ? "…" : ""}.`
        : "Day advanced — no signings.";
      if (data.window?.status === "closed") {
        toast.success(
          "Free-agency window closed — CPU teams fill their rosters in the preseason.",
        );
      } else {
        toast.info(msg);
      }
    },
    onError: (err) => toast.error((err as Error).message),
  });

  if (!windowActive) return null;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Free Agency</CardTitle>
          <CardDescription>
            Bid on free agents (Free Agency page), then advance the window one day
            at a time until it closes.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {multiOwner && (
          <div className="rounded-lg border border-border bg-surfaceAlt/40 px-3 py-2 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-muted">
                Owners bidding:{" "}
                <span className="font-semibold text-ink">
                  {(win?.participants ?? []).length}/{humanTeams.length}
                </span>
              </span>
              {win?.schedule?.is_scheduled && (
                <span className="text-muted">
                  Bids due:{" "}
                  <span className="font-semibold text-ink">
                    {formatDeadlineLocal(win.schedule.deadline_utc)}
                  </span>
                  <span
                    className={
                      win.schedule.past_due ? "ml-1.5 text-danger" : "ml-1.5"
                    }
                  >
                    (
                    {win.schedule.past_due
                      ? "passed"
                      : formatCountdown(win.schedule.deadline_utc)}
                    )
                  </span>
                </span>
              )}
            </div>
            {(win?.waiting ?? []).length > 0 && (
              <div className="mt-1 text-[11px] text-muted">
                Yet to bid: {(win?.waiting ?? []).join(", ")}
              </div>
            )}
          </div>
        )}
        {windowOpen && (
          <FaDeadlinePanel sched={win?.schedule} canEdit={canProgress} />
        )}
        <FaBiddingWindowPanel
          win={win!}
          teamId={teamId}
          onAdvance={() => advanceFaDay.mutate()}
          advancing={advanceFaDay.isPending}
          canAdvance={windowOpen && canProgress}
          showAdvance={canProgress}
        />
      </CardContent>
    </Card>
  );
}

/** The FA window's per-day clock: when this day's bids are due, and whether the
 *  day rolls on its own. Commissioners configure it; owners see the countdown.
 *
 *  Unlike the season deadline this never CPU-fills or blocks — choosing not to
 *  bid is a legitimate move, so a passed deadline just advances the day. */
function FaDeadlinePanel({
  sched,
  canEdit,
}: {
  sched?: FaWindowSchedule;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<FaWindowScheduleInput | null>(null);
  const seededRef = useRef(false);

  useEffect(() => {
    if (sched && !seededRef.current) {
      seededRef.current = true;
      setForm({
        deadline: sched.deadline_utc,
        auto_advance: sched.auto_advance,
        advance_hours: sched.advance_hours,
      });
    }
  }, [sched]);

  const save = useMutation({
    mutationFn: (payload: FaWindowScheduleInput) =>
      api.setFaWindowSchedule({ ...payload, deadline: payload.deadline ?? "" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["fa-window"] });
      toast.success("Free-agency deadline saved.");
    },
    onError: (err) => toast.error((err as Error).message),
  });

  if (!sched) return null;

  // Owners just need to know when to bid by; no deadline set means nothing to say.
  if (!canEdit) {
    if (!sched.is_scheduled) return null;
    return (
      <div className="rounded-md border border-border bg-surfaceAlt/40 px-3 py-2 text-xs">
        <span className="text-muted">Bids for this day are due: </span>
        <span className="font-semibold text-ink">
          {formatDeadlineLocal(sched.deadline_utc)}
        </span>
        <span className={sched.past_due ? "ml-2 text-danger" : "ml-2 text-muted"}>
          ({sched.past_due ? "passed" : formatCountdown(sched.deadline_utc)})
        </span>
        {sched.will_auto_advance && (
          <span className="ml-2 text-muted">— the day advances automatically.</span>
        )}
      </div>
    );
  }

  const patch = (p: Partial<FaWindowScheduleInput>) =>
    setForm((f) => (f ? { ...f, ...p } : f));

  return (
    <div className="space-y-2 rounded-md border border-border bg-surfaceAlt/30 p-3">
      <div className="flex flex-wrap items-end gap-2 text-xs">
        <label className="flex flex-col gap-1">
          <span className="text-muted">Bids due (your local time)</span>
          <Input
            type="datetime-local"
            className="h-8 w-56"
            value={form ? isoToLocalInput(form.deadline) : ""}
            onChange={(e) =>
              patch({
                deadline: e.target.value
                  ? new Date(e.target.value).toISOString()
                  : null,
              })
            }
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-muted">Each day lasts</span>
          <div className="flex items-center gap-1.5">
            <Input
              type="number"
              min={1}
              className="h-8 w-20"
              value={form?.advance_hours ?? 24}
              onChange={(e) =>
                patch({ advance_hours: Math.max(1, Number(e.target.value) || 24) })
              }
            />
            <span className="text-muted">hours</span>
          </div>
        </label>
        <label className="flex items-center gap-1.5 pb-1.5">
          <input
            type="checkbox"
            checked={form?.auto_advance ?? false}
            onChange={(e) => patch({ auto_advance: e.target.checked })}
          />
          <span>Advance automatically (no click)</span>
        </label>
        <Button
          size="sm"
          variant="outline"
          className="mb-0.5"
          disabled={!form || save.isPending}
          onClick={() => form && save.mutate(form)}
        >
          Save deadline
        </Button>
      </div>
      {form?.auto_advance ? (
        <div className="text-[11px] text-muted">
          Once the deadline passes, the window moves to the next day on its own
          within a few minutes and the clock resets for the following day.
          Owners who haven’t bid simply don’t bid — nothing is filled in for
          them.
        </div>
      ) : (
        <div className="text-[11px] text-muted">
          The deadline tells owners when to bid by; you still click “Advance FA
          day.” Turn on automatic advancing so the window doesn’t stall.
        </div>
      )}
      {sched.is_scheduled && (
        <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
          <span className="text-muted">Current deadline:</span>
          <span className="font-semibold text-ink">
            {formatDeadlineLocal(sched.deadline_utc)}
          </span>
          <span className={sched.past_due ? "text-danger" : "text-muted"}>
            ({sched.past_due ? "passed" : formatCountdown(sched.deadline_utc)})
          </span>
        </div>
      )}
    </div>
  );
}

function _faMoney(n: number): string {
  if (!n) return "$0";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${Math.round(n / 1_000)}K`;
  return `$${n}`;
}

function FaBiddingWindowPanel({
  win,
  teamId,
  onAdvance,
  advancing,
  canAdvance,
  showAdvance = true,
}: {
  win: FaWindowStatus;
  teamId: string | null;
  onAdvance: () => void;
  advancing: boolean;
  canAdvance: boolean;
  showAdvance?: boolean;
}) {
  const closed = win.status === "closed";
  const latest = win.latest;
  const signedToday = latest?.signed ?? [];
  const leaders = latest?.leaders ?? [];
  // Players you're bidding on but no longer leading — you need to counter.
  const counter = teamId
    ? leaders.filter(
        (l) => l.teams_offering.includes(teamId) && l.leader_team !== teamId,
      )
    : [];
  const leading = teamId
    ? leaders.filter((l) => l.leader_team === teamId)
    : [];

  return (
    <div className="rounded-xl border border-amber/40 bg-amber/5 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-amber">
            Free Agency Bidding
          </span>
          <Badge tone={closed ? "neutral" : "amber"}>
            {closed ? "Closed" : `Day ${win.day} of ${win.total_days}`}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to="/free-agency"
            className="rounded-md border border-border px-2.5 py-1 text-xs text-muted hover:text-fg"
          >
            Bid / counter →
          </Link>
          {!closed && showAdvance && (
            <Button size="sm" onClick={onAdvance} disabled={advancing || !canAdvance}>
              {advancing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <CalendarClock className="h-3.5 w-3.5" />
              )}
              Advance FA day
            </Button>
          )}
          {!closed && !showAdvance && (
            <span className="text-[11px] text-muted">
              The commissioner advances the day
            </span>
          )}
        </div>
      </div>

      {latest?.message && (
        <p className="mt-2 text-xs text-muted">{latest.message}</p>
      )}
      {!closed && (
        <p className="mt-1 text-[11px] text-muted">
          Any free agent stays biddable all window — pivot onto anyone as the
          market thins; a new bid gets a day before they can sign. CPU teams
          re-target the remaining pool each day.
        </p>
      )}

      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">
            {closed ? "Final signings" : `Signed on day ${latest?.day ?? win.day}`}
          </div>
          {signedToday.length === 0 ? (
            <p className="text-xs text-muted">— none —</p>
          ) : (
            <ul className="mt-1 space-y-0.5 text-xs">
              {signedToday.slice(0, 8).map((s) => (
                <li key={s.player_id}>
                  <span className="font-medium">{s.player_name}</span> →{" "}
                  {s.team_id} ({_faMoney(s.annual_salary)}/yr × {s.years})
                </li>
              ))}
              {signedToday.length > 8 && (
                <li className="text-muted">+{signedToday.length - 8} more…</li>
              )}
            </ul>
          )}
        </div>
        {!closed && (
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">
              You need to counter
            </div>
            {counter.length === 0 ? (
              <p className="text-xs text-muted">
                {leading.length
                  ? `Leading ${leading.length} bid${leading.length === 1 ? "" : "s"}.`
                  : "No active bids being outbid."}
              </p>
            ) : (
              <ul className="mt-1 space-y-0.5 text-xs">
                {counter.slice(0, 8).map((l) => (
                  <li key={l.player_id}>
                    <span className="font-medium">{l.player_name}</span> — leader{" "}
                    {l.leader_team} at {_faMoney(l.leader_salary)}/yr
                  </li>
                ))}
                {counter.length > 8 && (
                  <li className="text-muted">+{counter.length - 8} more…</li>
                )}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function _issueText(teamId: string, issue: string): string {
  return issue.startsWith(`${teamId}: `) ? issue.slice(teamId.length + 2) : issue;
}

/** Per-owner "turn feed": the things waiting on THIS owner right now (incoming
 *  trade offers, an open FA window they haven't bid in, a preseason roster
 *  that's blocking advancement). Computed live from current state. */
function ActionItemsCard() {
  const items = useQuery({
    queryKey: ["season-action-items"],
    queryFn: () => api.seasonActionItems(),
    refetchOnWindowFocus: true,
  });

  const data = items.data;
  // Nothing to nag about — stay quiet rather than render an empty card.
  if (!data || data.count === 0) return null;

  return (
    <Card className="border-amber/40">
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Bell className="h-4 w-4 text-amber" />
            Needs your attention
          </CardTitle>
          <CardDescription>
            {data.count} item{data.count === 1 ? "" : "s"} waiting on you
            {data.deadline
              ? ` · deadline ${formatDeadlineLocal(data.deadline)}`
              : ""}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        <ProgressionSchedulePanel />
        {data.items.map((item) => (
          <ActionItemRow key={item.kind} item={item} />
        ))}
      </CardContent>
    </Card>
  );
}

function ActionItemRow({ item }: { item: SeasonActionItem }) {
  return (
    <Link
      to={item.href}
      className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surfaceAlt/40 px-3 py-2 transition hover:border-amber/60 hover:bg-amber/10"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle
          className={cn(
            "mt-0.5 h-4 w-4 shrink-0",
            item.severity === "action" ? "text-amber" : "text-muted",
          )}
        />
        <div>
          <div className="text-sm font-semibold">{item.title}</div>
          {item.detail && (
            <div className="text-xs text-muted">{item.detail}</div>
          )}
        </div>
      </div>
      <ArrowRight className="h-4 w-4 shrink-0 text-muted" />
    </Link>
  );
}

const RUN_KIND_OPTIONS: { value: SeasonScheduleRunKind; label: string }[] = [
  { value: "", label: "Just get every team ready (no sim)" },
  { value: "days", label: "Simulate N days" },
  { value: "week", label: "Simulate 1 week" },
  { value: "month", label: "Simulate 1 month" },
  { value: "to-draft", label: "Simulate to the draft" },
  { value: "to-playoffs", label: "Simulate to the playoffs" },
];

/** ISO (UTC) → the value a <input type="datetime-local"> expects (local time). */
function isoToLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatCountdown(iso: string | null): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime() - Date.now();
  const abs = Math.abs(ms);
  const mins = Math.round(abs / 60000);
  const h = Math.floor(mins / 60);
  const d = Math.floor(h / 24);
  let rel: string;
  if (d >= 1) rel = `${d}d ${h % 24}h`;
  else if (h >= 1) rel = `${h}h ${mins % 60}m`;
  else rel = `${mins}m`;
  return ms >= 0 ? `in ${rel}` : `${rel} ago`;
}

/** Format a stored deadline (ISO) as local time; a legacy free-form label is
 *  shown as-is. */
function formatDeadlineLocal(s: string | null | undefined): string {
  if (!s) return "";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString();
}

/** Commissioner-configurable progression schedule: a real deadline + what runs
 *  when it passes. Owners see a read-only countdown (canEdit=false). */
function ProgressionSchedulePanel({ canEdit = false }: { canEdit?: boolean }) {
  const queryClient = useQueryClient();
  const scheduleQ = useQuery({
    queryKey: ["season-schedule"],
    queryFn: () => api.getSeasonSchedule(),
    refetchInterval: 30_000,
  });
  const sched = scheduleQ.data;

  const [form, setForm] = useState<SeasonScheduleInput | null>(null);
  // Seed the editable form from the server once (and when identity changes),
  // without clobbering in-progress edits on every refetch.
  const seededRef = useRef(false);
  useEffect(() => {
    if (sched && !seededRef.current) {
      seededRef.current = true;
      setForm({
        deadline: sched.deadline_utc,
        run_kind: sched.run_kind,
        run_n: sched.run_n,
        cpu_fill: sched.cpu_fill,
        recurring: sched.recurring,
        recur_days: sched.recur_days,
        auto_run: sched.auto_run,
      });
    }
  }, [sched]);

  const save = useMutation({
    mutationFn: (payload: SeasonScheduleInput) => api.setSeasonSchedule(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["season-schedule"] });
      toast.success("Progression schedule saved.");
    },
    onError: (err) => toast.error((err as Error).message),
  });
  const run = useMutation({
    mutationFn: () => api.runSeasonSchedule(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["season-schedule"] });
      queryClient.invalidateQueries({ queryKey: ["season-readiness"] });
      queryClient.invalidateQueries({ queryKey: ["sim-progress"] });
      const filled = data.filled?.length ?? 0;
      toast.success(
        `Ran scheduled progression${filled ? ` — CPU-filled ${filled} team${filled === 1 ? "" : "s"}` : ""}${data.run_label ? `, ${data.run_label} started` : ""}.`,
      );
    },
    onError: (err) => toast.error((err as Error).message),
  });

  if (!sched) return null;

  // Read-only (owner) view: just the deadline + countdown.
  if (!canEdit) {
    if (!sched.is_scheduled) return null;
    return (
      <div className="rounded-md border border-border bg-surfaceAlt/40 px-3 py-2 text-xs">
        <span className="text-muted">Next deadline: </span>
        <span className="font-semibold text-ink">
          {sched.deadline_utc ? new Date(sched.deadline_utc).toLocaleString() : "—"}
        </span>
        {sched.deadline_utc && (
          <span className={sched.past_due ? "ml-2 text-danger" : "ml-2 text-muted"}>
            ({sched.past_due ? "passed" : formatCountdown(sched.deadline_utc)})
          </span>
        )}
      </div>
    );
  }

  const patch = (p: Partial<SeasonScheduleInput>) =>
    setForm((f) => (f ? { ...f, ...p } : f));

  return (
    <div className="space-y-2 rounded-md border border-border bg-surfaceAlt/30 p-3">
      <div className="flex flex-wrap items-end gap-2 text-xs">
        <label className="flex flex-col gap-1">
          <span className="text-muted">Owner deadline (your local time)</span>
          <Input
            type="datetime-local"
            className="h-8 w-56"
            value={form ? isoToLocalInput(form.deadline) : ""}
            onChange={(e) =>
              patch({
                deadline: e.target.value
                  ? new Date(e.target.value).toISOString()
                  : null,
              })
            }
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-muted">When it passes</span>
          <select
            className="h-8 rounded-md border border-border bg-surface px-2"
            value={form?.run_kind ?? ""}
            onChange={(e) =>
              patch({ run_kind: e.target.value as SeasonScheduleRunKind })
            }
          >
            {RUN_KIND_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        {form?.run_kind === "days" && (
          <label className="flex flex-col gap-1">
            <span className="text-muted"># days</span>
            <Input
              type="number"
              min={1}
              className="h-8 w-20"
              value={form.run_n}
              onChange={(e) => patch({ run_n: Math.max(1, Number(e.target.value) || 1) })}
            />
          </label>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-4 text-xs">
        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={form?.cpu_fill ?? true}
            onChange={(e) => patch({ cpu_fill: e.target.checked })}
          />
          <span>CPU-fill unready teams first</span>
        </label>
        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={form?.recurring ?? false}
            onChange={(e) => patch({ recurring: e.target.checked })}
          />
          <span>Repeat every</span>
          <Input
            type="number"
            min={1}
            className="h-7 w-16"
            disabled={!form?.recurring}
            value={form?.recur_days ?? 7}
            onChange={(e) => patch({ recur_days: Math.max(1, Number(e.target.value) || 1) })}
          />
          <span>days</span>
        </label>
        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={form?.auto_run ?? false}
            onChange={(e) => patch({ auto_run: e.target.checked })}
          />
          <span>Run automatically (no click)</span>
        </label>
        <Button
          size="sm"
          variant="outline"
          disabled={!form || save.isPending}
          onClick={() => form && save.mutate(form)}
        >
          Save schedule
        </Button>
      </div>
      {form?.auto_run && (
        <div className="text-[11px] text-muted">
          The league will sim on its own within a few minutes of the deadline
          passing — no need to click “Run now.” Leave this off to review and run
          each deadline manually.
        </div>
      )}
      {sched.is_scheduled && (
        <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
          <span className="text-muted">Deadline:</span>
          <span className="font-semibold text-ink">
            {sched.deadline_utc ? new Date(sched.deadline_utc).toLocaleString() : "—"}
          </span>
          <span className={sched.past_due ? "text-danger" : "text-muted"}>
            ({sched.past_due ? "passed" : formatCountdown(sched.deadline_utc)})
          </span>
          {sched.past_due && (
            <Button
              size="sm"
              disabled={run.isPending || sched.sim_running}
              onClick={() => run.mutate()}
            >
              {sched.sim_running
                ? "Sim running…"
                : `Run now${sched.unready_count ? ` (CPU-fill ${sched.unready_count})` : ""} — ${sched.run_label}`}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

/** Commissioner view: every human team's readiness, a deadline setter, and a
 *  per-team "CPU handle it" button so an inactive owner can't stall the league. */
function ReadinessBoard({
  readiness,
  phase,
}: {
  readiness?: SeasonReadiness;
  phase?: string;
}) {
  const queryClient = useQueryClient();

  const cpuFill = useMutation({
    mutationFn: (tid: string) => api.seasonReadinessCpuFill(tid),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["season-readiness"] });
      queryClient.invalidateQueries({ queryKey: ["team-roster"] });
      if (data.ready) {
        toast.success(`${data.team_id} is ready now (CPU-filled).`);
      } else {
        toast.info(
          `${data.team_id} still has issues: ${data.issues[0] ? _issueText(data.team_id, data.issues[0]) : "see readiness"}`,
        );
      }
    },
    onError: (err) => toast.error((err as Error).message),
  });
  if (!readiness) return null;
  const teams = readiness.teams ?? [];
  // The readiness gate only guards the PRESEASON -> REGULAR advance (see the
  // multi-owner check in advance_phase). Once the season is under way an
  // unready team isn't blocking anything, so don't keep claiming Opening Day
  // is held up months after it happened — say what's actually true.
  const blocksOpeningDay = String(phase ?? "").toUpperCase() === "PRESEASON";
  const n = readiness.unready.length;
  const plural = n === 1 ? "" : "s";

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Owner readiness</CardTitle>
          <CardDescription>
            {readiness.all_ready
              ? "All owners are ready — you can advance the season."
              : blocksOpeningDay
                ? `${n} team${plural} not ready — Opening Day is blocked until fixed.`
                : `${n} team${plural} still have roster or lineup problems to clean up.`}
          </CardDescription>
        </div>
        <Badge
          tone={
            readiness.all_ready ? "success" : blocksOpeningDay ? "danger" : "amber"
          }
        >
          {readiness.all_ready
            ? "All ready"
            : blocksOpeningDay
              ? `${n} blocking`
              : `${n} need${n === 1 ? "s" : ""} attention`}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-3">
        <ProgressionSchedulePanel canEdit />
        <div className="space-y-1.5">
          {teams.map((t) => (
            <div
              key={t.team_id}
              className="flex items-start justify-between gap-3 rounded-lg border border-border bg-surfaceAlt/40 px-3 py-2"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  {t.team_id}
                  <Badge tone={t.ready ? "success" : "danger"}>
                    {t.ready ? "ready" : "not ready"}
                  </Badge>
                </div>
                {!t.ready && (
                  <ul className="mt-1 space-y-0.5 text-[11px] text-danger">
                    {t.issues.slice(0, 5).map((iss, i) => (
                      <li key={i}>• {_issueText(t.team_id, iss)}</li>
                    ))}
                  </ul>
                )}
              </div>
              {!t.ready && (
                <Button
                  size="sm"
                  variant="outline"
                  className="shrink-0"
                  disabled={cpuFill.isPending}
                  onClick={() => cpuFill.mutate(t.team_id)}
                >
                  CPU handle it
                </Button>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

/** Non-commissioner owner view: the season is commissioner-driven, so show the
 *  deadline and this owner's own readiness instead of the progression controls. */
function OwnerWaitingCard({
  teamId,
  readiness,
}: {
  teamId: string | null;
  readiness?: SeasonReadiness;
}) {
  const deadlineQ = useQuery({
    queryKey: ["season-deadline"],
    queryFn: () => api.getSeasonDeadline(),
  });
  const mine = readiness?.teams.find((t) => t.team_id === teamId);
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>The commissioner runs the clock</CardTitle>
          <CardDescription>
            Only the commissioner advances the season. Make your roster, lineup,
            and free-agent moves before the deadline.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted">Deadline:</span>
          <span className="font-semibold text-ink">
            {deadlineQ.data?.deadline ?? "none set"}
          </span>
        </div>
        {mine && (
          <div className="rounded-lg border border-border bg-surfaceAlt/40 px-3 py-2">
            <div className="flex items-center gap-2 text-sm font-semibold">
              Your team ({mine.team_id})
              <Badge tone={mine.ready ? "success" : "danger"}>
                {mine.ready ? "ready" : "not ready"}
              </Badge>
            </div>
            {!mine.ready && (
              <ul className="mt-1 space-y-0.5 text-[11px] text-danger">
                {mine.issues.slice(0, 5).map((iss, i) => (
                  <li key={i}>• {_issueText(mine.team_id, iss)}</li>
                ))}
              </ul>
            )}
          </div>
        )}
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

/**
 * Banner that surfaces notification events from the most recent sim
 * batch. When ``stopReason`` is set the multi-day sim broke early
 * because a stop_sim rule fired — we make that obvious so the owner
 * understands why fewer days advanced than expected.
 */
function NotificationsBanner({
  events,
  stopReason,
  onDismiss,
}: {
  events: NotificationEvent[];
  stopReason: string | null;
  onDismiss: () => void;
}) {
  const tone = stopReason
    ? "border-warning/40 bg-warning/5"
    : "border-amber/30 bg-amber/5";
  return (
    <Card className={tone}>
      <CardHeader className="flex-row items-start justify-between gap-2 pb-2">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Bell className="h-4 w-4 text-amber" />
            {stopReason
              ? `Sim paused: ${stopReason}`
              : `${events.length} new notification${events.length === 1 ? "" : "s"}`}
          </CardTitle>
          <CardDescription>
            {stopReason
              ? "The sim stopped on this event because you marked it 'stop sim' on the Notifications page. Review and resume when ready."
              : "Events from your latest sim batch — review on the Notifications page for the full history."}
          </CardDescription>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="rounded-md p-1 text-muted hover:bg-surfaceAlt hover:text-ink"
          aria-label="Dismiss"
        >
          <X className="h-4 w-4" />
        </button>
      </CardHeader>
      {events.length > 0 && (
        <CardContent className="space-y-1.5">
          {events.slice(0, 6).map((ev, idx) => (
            <div
              key={`${ev.timestamp}-${idx}`}
              className="flex items-start gap-2 rounded-md border border-border bg-surface px-2 py-1.5 text-xs"
            >
              <Badge tone={severityTone(ev.severity)}>{ev.severity}</Badge>
              <div className="min-w-0 flex-1">
                <div className="font-semibold">{ev.title}</div>
                <div className="text-muted">{ev.message}</div>
                {ev.sim_date && (
                  <div className="mt-0.5 text-[10px] text-muted">
                    {ev.sim_date}
                  </div>
                )}
              </div>
            </div>
          ))}
          {events.length > 6 && (
            <Link
              to="/notifications"
              className="inline-block text-xs font-semibold text-amber underline-offset-2 hover:underline"
            >
              + {events.length - 6} more — view full history →
            </Link>
          )}
        </CardContent>
      )}
    </Card>
  );
}

function severityTone(
  severity: string,
): "amber" | "warning" | "danger" | "neutral" | "success" {
  if (severity === "critical") return "danger";
  if (severity === "warning") return "warning";
  return "amber";
}

