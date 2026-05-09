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

import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  ArrowUpDown,
  Bot,
  FastForward,
  GraduationCap,
  Hourglass,
  Loader2,
  Sparkles,
  Timer,
  Trophy,
} from "lucide-react";

import { usePersistedState } from "@/lib/use-persisted-state";

import {
  api,
  type DraftProspect,
  type DraftSelection,
  type DraftState,
  type Team,
} from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import { StatCard } from "@/components/StatCard";
import { StarRating } from "@/components/StarRating";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { TeamLogo } from "@/components/TeamLogo";
import { useConfirmDialog } from "@/lib/use-confirm";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";

type Scope = "now" | "history";

export function DraftPage() {
  const user = useAuthStore();
  const myTeamId = user.selectedTeamId ?? user.teamId ?? null;
  const isAdmin = user.role === "admin";
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
  const teamsQ = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
  });
  const teamById = useMemo(() => {
    const m = new Map<string, Team>();
    for (const t of teamsQ.data ?? []) m.set(t.team_id, t);
    return m;
  }, [teamsQ.data]);

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
            {isAdmin && <TabsTrigger value="admin">Admin</TabsTrigger>}
          </TabsList>

          <TabsContent value="now">
            <LiveDraftView
              state={state.data!}
              myTeamId={myTeamId}
              teamById={teamById}
            />
          </TabsContent>

          <TabsContent value="history">
            <HistoryView
              year={state.data?.year ?? null}
              picks={results.data?.picks ?? []}
              isLoading={results.isLoading}
              isError={results.isError}
              error={results.error}
              myTeamId={myTeamId}
              teamById={teamById}
            />
          </TabsContent>

          {isAdmin && (
            <TabsContent value="admin">
              <AdminDraftPanel currentYear={state.data?.year ?? null} />
            </TabsContent>
          )}
        </Tabs>
      )}
    </AppShell>
  );
}

function LiveDraftView({
  state,
  myTeamId,
  teamById,
}: {
  state: DraftState;
  myTeamId: string | null;
  teamById: Map<string, Team>;
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

      <DraftControlsPanel
        year={state.year}
        myTeamId={myTeamId}
        onClockTeamId={onClock}
      />

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
              <PicksTable
                picks={recentPicks}
                myTeamId={myTeamId}
                teamById={teamById}
              />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Live draft controls — pick selector + auto-advance buttons.

type DraftKind = "all" | "hitters" | "pitchers";
type DraftSortKey = "name" | "pos" | "age" | "overall" | "bats" | string;
type DraftSortDir = "asc" | "desc";

const DRAFT_HITTER_COLS: Array<{ key: string; label: string }> = [
  { key: "ch", label: "CH" },
  { key: "ph", label: "PH" },
  { key: "sp", label: "SP" },
  { key: "eye", label: "EYE" },
  { key: "fa", label: "FA" },
  { key: "arm", label: "ARM" },
];
const DRAFT_PITCHER_COLS: Array<{ key: string; label: string }> = [
  { key: "endurance", label: "EN" },
  { key: "control", label: "CTRL" },
  { key: "movement", label: "MOV" },
  { key: "fb", label: "FB" },
  { key: "sl", label: "SL" },
  { key: "cu", label: "CU" },
  { key: "cb", label: "CB" },
  { key: "si", label: "SI" },
];

function DraftControlsPanel({
  year,
  myTeamId,
  onClockTeamId,
}: {
  year: number;
  myTeamId: string | null;
  onClockTeamId: string | null;
}) {
  const queryClient = useQueryClient();
  const isMyTurn = !!myTeamId && myTeamId === onClockTeamId;
  const [selectedPid, setSelectedPid] = useState<string>("");
  const [filter, setFilter] = usePersistedState("draft:pool:filter", "");
  const [kind, setKind] = usePersistedState<DraftKind>(
    "draft:pool:kind",
    "all",
  );
  const [sortKey, setSortKey] = usePersistedState<DraftSortKey>(
    "draft:pool:sortKey",
    "overall",
  );
  const [sortDir, setSortDir] = usePersistedState<DraftSortDir>(
    "draft:pool:sortDir",
    "desc",
  );

  const poolQ = useQuery({
    queryKey: ["draft-pool", year],
    queryFn: () => api.draftPool(year, { available_only: true, limit: 1000 }),
    enabled: !!year,
  });

  function refreshAll() {
    queryClient.invalidateQueries({ queryKey: ["draft-state"] });
    queryClient.invalidateQueries({ queryKey: ["draft-results"] });
    queryClient.invalidateQueries({ queryKey: ["draft-pool", year] });
    queryClient.invalidateQueries({ queryKey: ["team-roster"] });
  }

  const pickMut = useMutation({
    mutationFn: (pid: string) => api.draftMakePick(pid, year),
    onSuccess: () => {
      setSelectedPid("");
      refreshAll();
    },
  });
  const autoPickMut = useMutation({
    mutationFn: () => api.draftAutoPick(year),
    onSuccess: refreshAll,
  });
  const advanceToMyMut = useMutation({
    mutationFn: () => api.draftAutoAdvance("my_pick", { year }),
    onSuccess: refreshAll,
  });
  const advanceRoundMut = useMutation({
    mutationFn: () => api.draftAutoAdvance("end_of_round", { year }),
    onSuccess: refreshAll,
  });
  const advanceDraftMut = useMutation({
    mutationFn: () => api.draftAutoAdvance("end_of_draft", { year }),
    onSuccess: refreshAll,
  });

  const anyPending =
    pickMut.isPending ||
    autoPickMut.isPending ||
    advanceToMyMut.isPending ||
    advanceRoundMut.isPending ||
    advanceDraftMut.isPending;

  const filteredProspects: DraftProspect[] = useMemo(() => {
    const all = poolQ.data?.prospects ?? [];
    const needle = filter.trim().toLowerCase();
    let rows = all.filter((p) => {
      if (kind === "hitters" && p.is_pitcher) return false;
      if (kind === "pitchers" && !p.is_pitcher) return false;
      if (!needle) return true;
      return `${p.first_name} ${p.last_name} ${p.primary_position} ${p.player_id}`
        .toLowerCase()
        .includes(needle);
    });
    rows = [...rows].sort((a, b) => {
      const av = sortValueProspect(a, sortKey);
      const bv = sortValueProspect(b, sortKey);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "asc" ? av - bv : bv - av;
      }
      const as = String(av).toLowerCase();
      const bs = String(bv).toLowerCase();
      if (as < bs) return sortDir === "asc" ? -1 : 1;
      if (as > bs) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return rows.slice(0, 300);
  }, [poolQ.data, filter, kind, sortKey, sortDir]);

  const ratingCols = kind === "pitchers" ? DRAFT_PITCHER_COLS : DRAFT_HITTER_COLS;

  function toggleSort(key: DraftSortKey) {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "name" || key === "pos" || key === "bats" ? "asc" : "desc");
    }
  }

  const lastError =
    pickMut.error ||
    autoPickMut.error ||
    advanceToMyMut.error ||
    advanceRoundMut.error ||
    advanceDraftMut.error;

  const selectedProspect =
    filteredProspects.find((p) => p.player_id === selectedPid) ??
    poolQ.data?.prospects.find((p) => p.player_id === selectedPid) ??
    null;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="h-4 w-4 text-amber" /> Draft controls
          </CardTitle>
          <CardDescription>
            {isMyTurn
              ? "Your pick — click a prospect below and choose a column to sort by, then Make pick."
              : onClockTeamId
                ? `${onClockTeamId} is on the clock. Auto-advance through CPU picks until your turn or the round ends.`
                : "Draft idle."}
          </CardDescription>
        </div>
        {isMyTurn && <Badge tone="success">Your turn</Badge>}
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Action row */}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            onClick={() => selectedPid && pickMut.mutate(selectedPid)}
            disabled={!isMyTurn || !selectedPid || anyPending}
            title={
              !isMyTurn
                ? "You can only submit a pick when your team is on the clock."
                : !selectedPid
                  ? "Click a prospect row first."
                  : ""
            }
          >
            {pickMut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : null}
            Make pick
            {selectedProspect ? (
              <span className="ml-1 text-[11px] text-muted">
                {selectedProspect.last_name}, {selectedProspect.first_name}
              </span>
            ) : null}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => autoPickMut.mutate()}
            disabled={!isMyTurn || anyPending}
            title="Auto-pick best available for the team on the clock"
          >
            {autoPickMut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Bot className="h-4 w-4" />
            )}
            Auto-pick (best avail)
          </Button>
          <span className="mx-1 text-muted">|</span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => advanceToMyMut.mutate()}
            disabled={!myTeamId || isMyTurn || anyPending}
            title={
              !myTeamId
                ? "No team associated with your user."
                : isMyTurn
                  ? "It's already your pick."
                  : "Run CPU picks until your team is back on the clock"
            }
          >
            {advanceToMyMut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FastForward className="h-4 w-4" />
            )}
            Advance to my next pick
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => advanceRoundMut.mutate()}
            disabled={anyPending}
            title="Run CPU picks to the end of the current round"
          >
            {advanceRoundMut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FastForward className="h-4 w-4" />
            )}
            Finish round
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => advanceDraftMut.mutate()}
            disabled={anyPending}
            title="Auto-pick the rest of the entire draft (CPU picks for everyone)"
          >
            {advanceDraftMut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FastForward className="h-4 w-4" />
            )}
            Auto-finish draft
          </Button>
        </div>

        {/* Filter row */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-[220px] flex-1 space-y-1">
            <Input
              placeholder="Filter by name, position, id…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </div>
          <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
            {(["all", "hitters", "pitchers"] as DraftKind[]).map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => setKind(k)}
                className={cn(
                  "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
                  kind === k
                    ? "bg-amber text-espresso"
                    : "text-muted hover:bg-surface hover:text-ink",
                )}
              >
                {k}
              </button>
            ))}
          </div>
          <div className="text-xs text-muted">
            {poolQ.data
              ? `${poolQ.data.count} available · ${filteredProspects.length} shown`
              : poolQ.isLoading
                ? "Loading…"
                : ""}
          </div>
        </div>

        {/* Roster-style table */}
        {poolQ.isLoading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading pool…
          </div>
        ) : filteredProspects.length === 0 ? (
          <div className="rounded-md border border-border bg-surfaceAlt/40 px-4 py-6 text-sm text-muted">
            No prospects match — try clearing the filter or generating a pool
            from the Admin tab.
          </div>
        ) : (
          <div className="max-h-[520px] overflow-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10 bg-surface">
                <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
                  <th className="w-8 px-2 py-2"></th>
                  <DraftHeader
                    label="Player"
                    keyId="name"
                    sortKey={sortKey}
                    sortDir={sortDir}
                    onClick={toggleSort}
                    align="left"
                  />
                  <DraftHeader
                    label="Pos"
                    keyId="pos"
                    sortKey={sortKey}
                    sortDir={sortDir}
                    onClick={toggleSort}
                  />
                  <DraftHeader
                    label="Age"
                    keyId="age"
                    sortKey={sortKey}
                    sortDir={sortDir}
                    onClick={toggleSort}
                  />
                  <DraftHeader
                    label="B/T"
                    keyId="bats"
                    sortKey={sortKey}
                    sortDir={sortDir}
                    onClick={toggleSort}
                  />
                  <DraftHeader
                    label="OVR"
                    keyId="overall"
                    sortKey={sortKey}
                    sortDir={sortDir}
                    onClick={toggleSort}
                  />
                  {ratingCols.map((c) => (
                    <DraftHeader
                      key={c.key}
                      label={c.label}
                      keyId={c.key}
                      sortKey={sortKey}
                      sortDir={sortDir}
                      onClick={toggleSort}
                    />
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredProspects.map((p) => {
                  const isSelected = selectedPid === p.player_id;
                  return (
                    <tr
                      key={p.player_id}
                      onClick={() => setSelectedPid(p.player_id)}
                      className={cn(
                        "cursor-pointer border-b border-border/40 transition last:border-b-0 hover:bg-surfaceAlt/40",
                        isSelected && "bg-amber/10 hover:bg-amber/15",
                      )}
                    >
                      <td className="px-2 py-2 text-center">
                        <input
                          type="radio"
                          name="draft-prospect"
                          checked={isSelected}
                          onChange={() => setSelectedPid(p.player_id)}
                          className="h-3 w-3 accent-amber"
                          aria-label={`Select ${p.last_name}, ${p.first_name}`}
                        />
                      </td>
                      <td className="px-3 py-2 font-semibold">
                        {p.last_name}, {p.first_name}
                      </td>
                      <td className="px-3 py-2 text-right text-xs uppercase tracking-wider text-muted">
                        {p.primary_position || "—"}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {p.age ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-right text-xs">
                        {p.bats || "—"}/{p.throws || "—"}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums font-semibold">
                        {p.overall ?? "—"}
                      </td>
                      {ratingCols.map((c) => {
                        const raw = p.ratings[c.key];
                        const display =
                          raw == null || raw === ""
                            ? "—"
                            : typeof raw === "number"
                              ? Math.round(raw)
                              : Number.isFinite(Number(raw))
                                ? Math.round(Number(raw))
                                : String(raw);
                        return (
                          <td
                            key={c.key}
                            className="px-3 py-2 text-right tabular-nums"
                          >
                            {display}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {advanceToMyMut.data && advanceToMyMut.data.picks_made > 0 && (
          <div className="rounded-md border border-border bg-surfaceAlt/40 px-3 py-2 text-xs text-muted">
            Auto-advanced {advanceToMyMut.data.picks_made} CPU pick(s).
          </div>
        )}
        {advanceRoundMut.data && advanceRoundMut.data.picks_made > 0 && (
          <div className="rounded-md border border-border bg-surfaceAlt/40 px-3 py-2 text-xs text-muted">
            Finished round with {advanceRoundMut.data.picks_made} CPU pick(s).
          </div>
        )}
        {advanceDraftMut.data && advanceDraftMut.data.picks_made > 0 && (
          <div className="rounded-md border border-border bg-surfaceAlt/40 px-3 py-2 text-xs text-muted">
            Auto-finished {advanceDraftMut.data.picks_made} pick(s).
          </div>
        )}
        {lastError && (
          <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            {(lastError as Error).message}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function sortValueProspect(p: DraftProspect, key: DraftSortKey): string | number | null {
  switch (key) {
    case "name":
      return `${p.last_name}, ${p.first_name}`;
    case "pos":
      return p.primary_position ?? "";
    case "age":
      return p.age ?? null;
    case "bats":
      return p.bats ?? "";
    case "overall":
      return p.overall ?? null;
    default: {
      const raw = p.ratings[key];
      if (raw == null) return null;
      const n = typeof raw === "number" ? raw : Number(raw);
      return Number.isFinite(n) ? n : String(raw);
    }
  }
}

function DraftHeader({
  label,
  keyId,
  sortKey,
  sortDir,
  onClick,
  align = "right",
}: {
  label: string;
  keyId: DraftSortKey;
  sortKey: DraftSortKey;
  sortDir: DraftSortDir;
  onClick: (key: DraftSortKey) => void;
  align?: "left" | "right";
}) {
  const active = sortKey === keyId;
  const Arrow = !active ? ArrowUpDown : sortDir === "asc" ? ArrowUp : ArrowDown;
  return (
    <th
      className={cn(
        "select-none px-3 py-2 font-semibold",
        align === "left" ? "text-left" : "text-right",
      )}
    >
      <button
        type="button"
        onClick={() => onClick(keyId)}
        className={cn(
          "inline-flex items-center gap-1 transition",
          active ? "text-ink" : "hover:text-ink",
        )}
      >
        {label}
        <Arrow className="h-3 w-3 opacity-60" />
      </button>
    </th>
  );
}

function HistoryView({
  year,
  picks,
  isLoading,
  isError,
  error,
  myTeamId,
  teamById,
}: {
  year: number | null;
  picks: DraftSelection[];
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  myTeamId: string | null;
  teamById: Map<string, Team>;
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
            <PicksTable
              picks={roundPicks}
              myTeamId={myTeamId}
              teamById={teamById}
            />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function PicksTable({
  picks,
  myTeamId,
  teamById,
}: {
  picks: DraftSelection[];
  myTeamId: string | null;
  teamById: Map<string, Team>;
}) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
          <th className="px-6 py-2 text-left font-semibold">Pick</th>
          <th className="px-3 py-2 text-left font-semibold">Team</th>
          <th className="px-3 py-2 text-left font-semibold">Player</th>
          <th className="px-3 py-2 text-right font-semibold">OVR</th>
          <th className="px-6 py-2 text-right font-semibold">Rd</th>
        </tr>
      </thead>
      <tbody>
        {picks.map((pick) => {
          const playerName =
            pick.last_name
              ? `${pick.last_name}${pick.first_name ? `, ${pick.first_name}` : ""}`
              : pick.player_id;
          const stars = parseFloat(pick.overall_stars_text ?? "");
          const display = pick.overall_display ?? pick.overall_raw ?? null;
          return (
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
              <td className="px-3 py-2">
                {(() => {
                  const t = teamById.get(pick.team_id);
                  return (
                    <div className="flex items-center gap-2 font-semibold">
                      <TeamLogo
                        teamId={pick.team_id}
                        abbreviation={t?.abbreviation || pick.team_id}
                        primaryColor={t?.primary_color}
                        secondaryColor={t?.secondary_color}
                        className="h-6 w-6 shrink-0 rounded text-[10px]"
                      />
                      <span>{pick.team_id}</span>
                    </div>
                  );
                })()}
              </td>
              <td className="px-3 py-2">
                <div className="flex items-center gap-2">
                  <PlayerAvatar
                    playerId={pick.player_id}
                    initials={`${pick.first_name?.[0] ?? ""}${pick.last_name?.[0] ?? ""}`}
                    className="h-6 w-6 shrink-0 overflow-hidden rounded-md text-[9px]"
                  />
                  <Link
                    to={`/player/${encodeURIComponent(pick.player_id)}`}
                    className="font-semibold hover:text-amber"
                  >
                    {playerName}
                  </Link>
                  {pick.primary_position && (
                    <span className="ml-1 text-[10px] uppercase tracking-wider text-muted">
                      {pick.primary_position}
                    </span>
                  )}
                </div>
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {display == null ? (
                  <span className="text-subtle">—</span>
                ) : (
                  <div className="inline-flex flex-col items-end gap-0.5">
                    <span className="font-display font-semibold">
                      {Math.round(display)}
                    </span>
                    {Number.isFinite(stars) && stars > 0 && (
                      <StarRating value={stars} size="h-2.5 w-2.5" />
                    )}
                  </div>
                )}
              </td>
              <td className="px-6 py-2 text-right tabular-nums">{pick.round}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function AdminDraftPanel({ currentYear }: { currentYear: number | null }) {
  const [year, setYear] = useState<string>(
    currentYear ? String(currentYear) : "",
  );
  const [seed, setSeed] = useState<string>("");
  const [manualPlayerId, setManualPlayerId] = useState("");

  return (
    <div className="space-y-4">
      <DraftSettingsCard />
      <AdminDraftPanelInner
        year={year}
        setYear={setYear}
        seed={seed}
        setSeed={setSeed}
        manualPlayerId={manualPlayerId}
        setManualPlayerId={setManualPlayerId}
        currentYear={currentYear}
      />
    </div>
  );
}

function DraftSettingsCard() {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ["draft-settings"],
    queryFn: () => api.draftSettings(),
  });
  const [rounds, setRounds] = useState<string>("");
  const [pool, setPool] = useState<string>("");

  useEffect(() => {
    if (settings.data) {
      setRounds(String(settings.data.rounds));
      setPool(String(settings.data.pool_size));
    }
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () =>
      api.saveDraftSettings(
        Number(rounds) || 10,
        Number(pool) || 200,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["draft-settings"] });
      queryClient.invalidateQueries({ queryKey: ["draft-state"] });
    },
  });

  const limits = settings.data?.limits;
  const dirty =
    settings.data &&
    (Number(rounds) !== settings.data.rounds ||
      Number(pool) !== settings.data.pool_size);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Draft configuration</CardTitle>
        <CardDescription>
          How many rounds the amateur draft runs and how many prospects to
          generate for the pool. Saved per league, re-usable every season.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-[auto_auto_1fr]">
        <div>
          <Label htmlFor="draft-rounds">Rounds</Label>
          <Input
            id="draft-rounds"
            type="number"
            min={limits?.rounds.min ?? 1}
            max={limits?.rounds.max ?? 50}
            value={rounds}
            onChange={(e) => setRounds(e.target.value)}
            className="w-28"
          />
        </div>
        <div>
          <Label htmlFor="draft-pool">Pool size</Label>
          <Input
            id="draft-pool"
            type="number"
            min={limits?.pool_size.min ?? 20}
            max={limits?.pool_size.max ?? 2000}
            step={10}
            value={pool}
            onChange={(e) => setPool(e.target.value)}
            className="w-32"
          />
        </div>
        <div className="flex items-end gap-2">
          <Button
            size="sm"
            onClick={() => save.mutate()}
            disabled={!dirty || save.isPending}
          >
            {save.isPending && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
            Save
          </Button>
          {save.isSuccess && (
            <span className="text-xs text-success">Saved.</span>
          )}
          {save.isError && (
            <span className="text-xs text-danger">
              {(save.error as Error).message}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function AdminDraftPanelInner({
  year,
  setYear,
  seed,
  setSeed,
  manualPlayerId,
  setManualPlayerId,
  currentYear,
}: {
  year: string;
  setYear: (v: string) => void;
  seed: string;
  setSeed: (v: string) => void;
  manualPlayerId: string;
  setManualPlayerId: (v: string) => void;
  currentYear: number | null;
}) {
  const { confirm, dialog: confirmDialog } = useConfirmDialog();

  const toYear = () => {
    const n = Number(year);
    return Number.isFinite(n) && n > 0 ? n : undefined;
  };

  const initialize = useMutation({
    mutationFn: () =>
      api.adminDraftInitialize(toYear(), seed ? Number(seed) : undefined),
  });
  const reset = useMutation({
    mutationFn: () => api.adminDraftReset(toYear()),
  });
  const generatePool = useMutation({
    mutationFn: () => api.adminDraftGeneratePool(toYear()),
  });
  const manualPick = useMutation({
    mutationFn: () => api.adminDraftManualPick(manualPlayerId.trim(), toYear()),
  });

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Initialize draft</CardTitle>
          <CardDescription>
            Computes order from season stats (worst-first) and writes the
            initial draft state file. Overwrites anything in progress.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label htmlFor="year">Year</Label>
              <Input
                id="year"
                value={year}
                onChange={(e) => setYear(e.target.value)}
                placeholder={String(currentYear ?? "")}
              />
            </div>
            <div>
              <Label htmlFor="seed">Seed (optional)</Label>
              <Input
                id="seed"
                value={seed}
                onChange={(e) => setSeed(e.target.value)}
                placeholder="42"
              />
            </div>
          </div>
          <Button
            size="sm"
            onClick={async () => {
              if (
                await confirm({
                  title: "Initialize draft state?",
                  description:
                    "Discards any in-progress draft state for this year.",
                  confirmLabel: "Initialize",
                  danger: true,
                })
              ) {
                initialize.mutate();
              }
            }}
            disabled={initialize.isPending}
          >
            Initialize
          </Button>
          <AdminResult mut={initialize} okText="Draft state initialized." />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Generate pool</CardTitle>
          <CardDescription>
            Writes a fresh amateur draft pool for the year.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <Button
            size="sm"
            onClick={() => generatePool.mutate()}
            disabled={generatePool.isPending}
          >
            Generate pool
          </Button>
          <AdminResult
            mut={generatePool}
            okText={
              generatePool.data
                ? `Pool of ${generatePool.data.pool_size} players generated.`
                : ""
            }
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Manual pick</CardTitle>
          <CardDescription>
            Assigns a player to the current pick on behalf of the team on
            the clock. Advances the draft state.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <Label htmlFor="pick-pid">Player ID</Label>
          <Input
            id="pick-pid"
            value={manualPlayerId}
            onChange={(e) => setManualPlayerId(e.target.value)}
            placeholder="PLR00042"
          />
          <Button
            size="sm"
            onClick={() => manualPick.mutate()}
            disabled={!manualPlayerId.trim() || manualPick.isPending}
          >
            Submit pick
          </Button>
          <AdminResult
            mut={manualPick}
            okText={
              manualPick.data
                ? `${manualPick.data.team_id} selected ${manualPick.data.player_id} (overall #${manualPick.data.overall}).`
                : ""
            }
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Reset draft</CardTitle>
          <CardDescription>
            Deletes draft state + results CSV for the year. Does not touch
            the player pool.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <Button
            size="sm"
            variant="outline"
            onClick={async () => {
              if (
                await confirm({
                  title: "Reset draft?",
                  description:
                    "Delete draft state and results for this year. This cannot be undone.",
                  confirmLabel: "Reset draft",
                  danger: true,
                })
              ) {
                reset.mutate();
              }
            }}
            disabled={reset.isPending}
          >
            Reset draft
          </Button>
          <AdminResult mut={reset} okText="Draft state and results cleared." />
        </CardContent>
      </Card>
      {confirmDialog}
    </div>
  );
}

function AdminResult({
  mut,
  okText,
}: {
  mut: { isSuccess: boolean; isError: boolean; error: unknown };
  okText?: string;
}) {
  if (mut.isSuccess && okText) {
    return <div className="text-xs text-success">{okText}</div>;
  }
  if (mut.isError) {
    return (
      <div className="whitespace-pre-line text-xs text-danger">
        {(mut.error as Error)?.message ?? "Failed."}
      </div>
    );
  }
  return null;
}
