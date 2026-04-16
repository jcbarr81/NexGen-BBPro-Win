/**
 * Phase 4 port of ui/draft_console.py (read-only).
 *
 * Surfaces two views of draft data via ``services.draft_state``:
 *
 * - **Now**: the active draft state (round, overall pick, team-on-the-clock,
 *   recent picks, remaining order).
 * - **History**: finalized picks from ``draft_results_<year>.csv``.
 *
 * If no draft has ever been started for the current league year the page
 * shows an empty state rather than failing.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  GraduationCap,
  Hourglass,
  Loader2,
  Timer,
  Trophy,
} from "lucide-react";

import { api, type DraftSelection, type DraftState } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import { StatCard } from "@/components/StatCard";
import {
  Badge,
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

type Scope = "now" | "history";

export function DraftPage() {
  const user = useAuthStore();
  const myTeamId = user.selectedTeamId ?? user.teamId ?? null;
  const [scope, setScope] = useState<Scope>("now");

  const state = useQuery({
    queryKey: ["draft-state"],
    queryFn: () => api.draftState(),
  });
  const results = useQuery({
    queryKey: ["draft-results", state.data?.year],
    queryFn: () => api.draftResults(state.data?.year),
    enabled: !!state.data?.year,
  });

  return (
    <AppShell
      title="Draft"
      subtitle={
        state.data
          ? `${state.data.year} · ${state.data.exists ? "In progress" : "No active draft"}`
          : "Loading…"
      }
    >
      {state.isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <Loader2 className="h-5 w-5 animate-spin text-amber" />
            <span className="text-sm text-muted">Loading draft…</span>
          </CardContent>
        </Card>
      ) : state.isError ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-danger">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm">{(state.error as Error).message}</span>
          </CardContent>
        </Card>
      ) : (
        <Tabs value={scope} onValueChange={(v) => setScope(v as Scope)}>
          <TabsList>
            <TabsTrigger value="now">Now</TabsTrigger>
            <TabsTrigger value="history">History</TabsTrigger>
          </TabsList>

          <TabsContent value="now">
            <LiveDraftView state={state.data!} myTeamId={myTeamId} />
          </TabsContent>

          <TabsContent value="history">
            <HistoryView
              year={state.data?.year ?? null}
              picks={results.data?.picks ?? []}
              isLoading={results.isLoading}
              isError={results.isError}
              error={results.error}
              myTeamId={myTeamId}
            />
          </TabsContent>
        </Tabs>
      )}
    </AppShell>
  );
}

function LiveDraftView({
  state,
  myTeamId,
}: {
  state: DraftState;
  myTeamId: string | null;
}) {
  const onClock = useMemo(() => {
    if (!state.exists || state.order.length === 0) return null;
    // Order typically lists one team per slot in round-robin. We pick the
    // next team by (overall_pick - 1) % len(order).
    const idx = (state.overall_pick - 1) % state.order.length;
    return state.order[idx] ?? null;
  }, [state]);

  const remaining = useMemo(() => {
    if (!state.exists) return [] as string[];
    const start = Math.max(0, (state.overall_pick - 1) % state.order.length);
    // Show the next 10 spots in the order starting with "on clock".
    const rotated: string[] = [];
    for (let i = 0; i < Math.min(10, state.order.length); i++) {
      const entry = state.order[(start + i) % state.order.length];
      if (entry) rotated.push(entry);
    }
    return rotated;
  }, [state]);

  const recentPicks = useMemo(() => {
    if (!state.selected.length) return [];
    const copy = [...state.selected];
    copy.sort((a, b) => b.overall - a.overall);
    return copy.slice(0, 10);
  }, [state.selected]);

  if (!state.exists) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
          <GraduationCap className="h-10 w-10 text-amber" />
          <h2 className="font-display text-xl">No active draft</h2>
          <p className="max-w-sm text-sm text-muted">
            The draft for {state.year} hasn't been started yet. Switch to the
            History tab to review past drafts.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatCard
          label="Round"
          value={state.round}
          sub={`Overall pick #${state.overall_pick}`}
          Icon={Trophy}
          tone="amber"
        />
        <StatCard
          label="On The Clock"
          value={onClock ?? "—"}
          sub={onClock === myTeamId ? "You're up" : undefined}
          Icon={Timer}
          tone={onClock === myTeamId ? "success" : "neutral"}
        />
        <StatCard
          label="Picks Made"
          value={state.selected.length}
          sub={`Order size: ${state.order.length}`}
          Icon={Hourglass}
        />
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Up Next</CardTitle>
              <CardDescription>Next 10 slots in the order</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <ol className="divide-y divide-border/60">
              {remaining.map((teamId, idx) => {
                const overall = state.overall_pick + idx;
                return (
                  <li
                    key={`${teamId}-${overall}`}
                    className={cn(
                      "flex items-center justify-between gap-4 px-6 py-3 text-sm",
                      idx === 0 && "bg-amber/10",
                      teamId === myTeamId && "border-l-4 border-amber",
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <span className="w-10 text-right font-mono text-xs text-muted">
                        #{overall}
                      </span>
                      <span className="font-semibold">{teamId}</span>
                      {idx === 0 && <Badge tone="amber">On Clock</Badge>}
                      {teamId === myTeamId && idx !== 0 && (
                        <Badge tone="neutral">You</Badge>
                      )}
                    </div>
                    <ArrowRight className="h-4 w-4 text-muted" />
                  </li>
                );
              })}
            </ol>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Recent Picks</CardTitle>
              <CardDescription>Last 10 selections</CardDescription>
            </div>
            <Badge tone="amber">
              <Trophy className="h-3 w-3" /> {state.selected.length}
            </Badge>
          </CardHeader>
          <CardContent className="p-0">
            {recentPicks.length === 0 ? (
              <div className="px-6 py-8 text-sm text-muted">
                No picks yet.
              </div>
            ) : (
              <PicksTable picks={recentPicks} myTeamId={myTeamId} />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function HistoryView({
  year,
  picks,
  isLoading,
  isError,
  error,
  myTeamId,
}: {
  year: number | null;
  picks: DraftSelection[];
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  myTeamId: string | null;
}) {
  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-10">
          <Loader2 className="h-5 w-5 animate-spin text-amber" />
          <span className="text-sm text-muted">Loading history…</span>
        </CardContent>
      </Card>
    );
  }
  if (isError) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-10 text-danger">
          <AlertTriangle className="h-5 w-5" />
          <span className="text-sm">{(error as Error).message}</span>
        </CardContent>
      </Card>
    );
  }
  if (!picks || picks.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
          <Trophy className="h-10 w-10 text-amber" />
          <h2 className="font-display text-xl">No draft results</h2>
          <p className="max-w-sm text-sm text-muted">
            No draft results have been finalized for {year ?? "this year"} yet.
          </p>
        </CardContent>
      </Card>
    );
  }

  // Group by round for the history view.
  const byRound = new Map<number, DraftSelection[]>();
  for (const p of picks) {
    const arr = byRound.get(p.round) ?? [];
    arr.push(p);
    byRound.set(p.round, arr);
  }
  const rounds = [...byRound.entries()].sort((a, b) => a[0] - b[0]);

  return (
    <div className="space-y-6">
      {rounds.map(([round, roundPicks]) => (
        <Card key={round}>
          <CardHeader>
            <div>
              <CardTitle>Round {round}</CardTitle>
              <CardDescription>
                {roundPicks.length} pick{roundPicks.length === 1 ? "" : "s"}
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <PicksTable picks={roundPicks} myTeamId={myTeamId} />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function PicksTable({
  picks,
  myTeamId,
}: {
  picks: DraftSelection[];
  myTeamId: string | null;
}) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
          <th className="px-6 py-2 text-left font-semibold">Pick</th>
          <th className="px-3 py-2 text-left font-semibold">Team</th>
          <th className="px-3 py-2 text-left font-semibold">Player</th>
          <th className="px-6 py-2 text-right font-semibold">Rd</th>
        </tr>
      </thead>
      <tbody>
        {picks.map((pick) => (
          <tr
            key={`${pick.round}-${pick.overall}`}
            className={cn(
              "border-b border-border/40 transition last:border-b-0 hover:bg-surfaceAlt/40",
              pick.team_id === myTeamId && "bg-amber/10 hover:bg-amber/15",
            )}
          >
            <td className="px-6 py-2 font-mono text-xs text-muted">
              #{pick.overall}
            </td>
            <td className="px-3 py-2 font-semibold">{pick.team_id}</td>
            <td className="px-3 py-2 font-mono text-xs">{pick.player_id}</td>
            <td className="px-6 py-2 text-right tabular-nums">{pick.round}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
