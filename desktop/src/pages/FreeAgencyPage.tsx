/**
 * Phase 4 port of ui/free_agency_window.py.
 *
 * Lists every player not on a team's roster and lets the active team sign
 * them at any roster level. Sorting + filter + position picker keep the
 * scan manageable; signing immediately invalidates roster + activity
 * caches so the rest of the UI stays in sync.
 */

import { FormEvent, useMemo, useState } from "react";

import { usePersistedState } from "@/lib/use-persisted-state";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Loader2,
  Search,
  UserPlus,
  Users,
} from "lucide-react";

import {
  api,
  ApiError,
  type ExtensionEvaluation,
  type FreeAgentSignRejection,
  type RatingContextEntry,
} from "@/lib/api";
import { toast } from "@/lib/toast-store";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { StarRating } from "@/components/StarRating";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
} from "@/components/ui";

type SortKey = "name" | "pos" | "role" | "bats" | string;
type SortDir = "asc" | "desc";
type Filter = "all" | "hitters" | "pitchers";

const HITTER_COLUMNS: Array<{ key: string; label: string }> = [
  { key: "ch", label: "CH" },
  { key: "ph", label: "PH" },
  { key: "sp", label: "SP" },
  { key: "eye", label: "EYE" },
  { key: "fa", label: "FA" },
];
const PITCHER_COLUMNS: Array<{ key: string; label: string }> = [
  { key: "fb", label: "FB" },
  { key: "control", label: "CTRL" },
  { key: "movement", label: "MOV" },
  { key: "endurance", label: "END" },
];

type FreeAgent = NonNullable<
  Awaited<ReturnType<typeof api.freeAgents>>
>["free_agents"][number];

const POSITION_CONTEXT_KEY = "nexgen:free-agency:position-context";

function readPositionContextPref(): boolean {
  try {
    const raw = window.localStorage.getItem(POSITION_CONTEXT_KEY);
    if (raw === null) return true; // default on — matches PyQt
    return raw === "1";
  } catch {
    return true;
  }
}

function writePositionContextPref(value: boolean) {
  try {
    window.localStorage.setItem(POSITION_CONTEXT_KEY, value ? "1" : "0");
  } catch {
    /* ignore */
  }
}

function QualifyingOffersCard({ teamId }: { teamId: string | null }) {
  const queryClient = useQueryClient();
  const qo = useQuery({
    queryKey: ["qualifying-offers", teamId],
    queryFn: () => api.teamQualifyingOffers(teamId as string),
    enabled: !!teamId,
    refetchOnWindowFocus: false,
  });
  const resolve = useMutation({
    mutationFn: ({ playerId, tender }: { playerId: string; tender: boolean }) =>
      api.resolveQualifyingOffer(teamId as string, playerId, tender),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["qualifying-offers", teamId] }),
    onError: (e) => toast.error((e as Error).message),
  });

  const pending = (qo.data?.offers ?? []).filter((o) => o.decision === "pending");
  if (pending.length === 0) return null;
  const qoValue = pending[0]?.qo_value ?? 0;

  return (
    <Card className="mb-4 border-amber/30 bg-amber/5">
      <CardContent className="py-4">
        <div className="font-semibold text-amber-text">
          Qualifying offers — your decision
        </div>
        <p className="mt-1 text-sm text-muted">
          Tender a one-year ${qoValue.toLocaleString()} qualifying offer
          to a departing free agent (he may accept, or decline and test the market —
          declining and signing elsewhere earns you a draft compensation pick), or let
          him walk for nothing.
        </p>
        <ul className="mt-3 space-y-2">
          {pending.map((o) => (
            <li
              key={o.player_id}
              className="flex items-center justify-between gap-3 text-sm"
            >
              <span className="font-mono">{o.player_id}</span>
              <span className="flex gap-2">
                <Button
                  size="sm"
                  disabled={resolve.isPending}
                  onClick={() =>
                    resolve.mutate({ playerId: o.player_id, tender: true })
                  }
                >
                  Tender QO
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={resolve.isPending}
                  onClick={() =>
                    resolve.mutate({ playerId: o.player_id, tender: false })
                  }
                >
                  Let walk
                </Button>
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function FreeAgencyPage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;
  const [search, setSearch] = usePersistedState("free-agency:search", "");
  const [filter, setFilter] = usePersistedState<Filter>(
    "free-agency:filter",
    "all",
  );
  const [position, setPosition] = usePersistedState<string>(
    "free-agency:position",
    "",
  );
  const [signing, setSigning] = useState<FreeAgent | null>(null);
  const [sortKey, setSortKey] = usePersistedState<SortKey>(
    "free-agency:sortKey",
    "name",
  );
  const [sortDir, setSortDir] = usePersistedState<SortDir>(
    "free-agency:sortDir",
    "asc",
  );
  const [positionContext, setPositionContextState] = useState(readPositionContextPref);
  const setPositionContext = (value: boolean) => {
    setPositionContextState(value);
    writePositionContextPref(value);
  };

  const list = useQuery({
    queryKey: ["free-agents"],
    queryFn: () => api.freeAgents(2000),
  });

  const positions = useMemo(() => {
    const s = new Set<string>();
    for (const fa of list.data?.free_agents ?? []) {
      if (fa.primary_position) s.add(fa.primary_position);
    }
    return [...s].sort();
  }, [list.data]);

  const filtered = useMemo(() => {
    let rows = list.data?.free_agents ?? [];
    if (filter === "hitters") rows = rows.filter((r) => !r.is_pitcher);
    if (filter === "pitchers") rows = rows.filter((r) => r.is_pitcher);
    if (position)
      rows = rows.filter((r) => r.primary_position === position);
    if (search.trim()) {
      const needle = search.trim().toLowerCase();
      rows = rows.filter((r) =>
        `${r.first_name} ${r.last_name} ${r.player_id}`
          .toLowerCase()
          .includes(needle),
      );
    }
    const sorted = [...rows];
    sorted.sort((a, b) => {
      const av = sortValue(a, sortKey);
      const bv = sortValue(b, sortKey);
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
    return sorted;
  }, [list.data, filter, position, search, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "name" || key === "pos" ? "asc" : "desc");
    }
  }

  const pitcherHeavy =
    filter === "pitchers" ||
    (filter === "all" &&
      filtered.length > 0 &&
      filtered.filter((p) => p.is_pitcher).length / filtered.length > 0.5);
  const columns = pitcherHeavy ? PITCHER_COLUMNS : HITTER_COLUMNS;

  return (
    <AppShell
      title="Free Agency"
      subtitle={`${list.data?.count ?? 0} unsigned players`}
    >
      <QualifyingOffersCard teamId={teamId} />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-1 flex-wrap items-center gap-2">
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <Input
              className="pl-9"
              placeholder="Search by name or id…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
            {(["all", "hitters", "pitchers"] as const).map((opt) => (
              <Pill
                key={opt}
                active={filter === opt}
                onClick={() => setFilter(opt)}
              >
                {opt}
              </Pill>
            ))}
          </div>
          <select
            value={position}
            onChange={(e) => setPosition(e.target.value)}
            className="h-9 rounded-md border border-border bg-canvas/60 px-2 text-xs font-semibold uppercase tracking-wider text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
          >
            <option value="">All positions</option>
            {positions.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <label
          className="flex cursor-pointer items-center gap-2 rounded-md border border-border bg-surfaceAlt/50 px-3 py-1.5 text-xs uppercase tracking-wider text-muted hover:text-ink"
          title="Show each hitter's percentile against other players at the same position (C/1B/2B/3B/SS/OF). Pitchers compare against the full pitcher pool."
        >
          <input
            type="checkbox"
            checked={positionContext}
            onChange={(e) => setPositionContext(e.target.checked)}
            className="h-3 w-3 accent-amber"
          />
          Position context
        </label>
        <span className="text-xs text-muted">{filtered.length} shown</span>
      </div>

      {list.isLoading ? (
        <LoadingCard />
      ) : list.isError ? (
        <ErrorCard message={(list.error as Error).message} />
      ) : filtered.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <Users className="h-10 w-10 text-amber" />
            <h2 className="font-display text-xl">No free agents</h2>
            <p className="max-w-sm text-sm text-muted">
              Either every player is signed or your filter is too tight.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Available</CardTitle>
            <Badge tone="amber">
              <Users className="h-3 w-3" /> {filtered.length}
            </Badge>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
                    <HeaderCell label="Player" keyId="name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} align="left" />
                    <HeaderCell label="Pos" keyId="pos" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                    <HeaderCell label="B" keyId="bats" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                    <HeaderCell label="Role" keyId="role" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                    <HeaderCell label="OVR" keyId="overall" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                    {columns.map((c) => (
                      <HeaderCell
                        key={c.key}
                        label={c.label}
                        keyId={c.key}
                        sortKey={sortKey}
                        sortDir={sortDir}
                        onClick={toggleSort}
                      />
                    ))}
                    <th className="px-4 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((fa) => (
                    <tr
                      key={fa.player_id}
                      className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
                    >
                      <td className="px-6 py-2">
                        <div className="flex items-center gap-2">
                          <PlayerAvatar
                            playerId={fa.player_id}
                            initials={`${fa.first_name?.[0] ?? ""}${fa.last_name?.[0] ?? ""}`}
                            className="h-7 w-7 shrink-0 overflow-hidden rounded-md text-[10px]"
                          />
                          <Link
                            to={`/player/${encodeURIComponent(fa.player_id)}`}
                            className="font-semibold hover:text-amber"
                          >
                            {fa.last_name}
                            {fa.first_name ? `, ${fa.first_name}` : ""}
                          </Link>
                        </div>
                      </td>
                      <td className="px-3 py-2 text-right text-xs uppercase tracking-wider text-muted">
                        {fa.primary_position || "—"}
                      </td>
                      <td className="px-3 py-2 text-right">{fa.bats || "—"}</td>
                      <td className="px-3 py-2 text-right text-xs uppercase tracking-wider text-muted">
                        {fa.role || (fa.is_pitcher ? "PIT" : "POS")}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        <OverallCell
                          display={fa.overall_display ?? fa.overall_raw ?? null}
                          starsText={fa.overall_stars_text ?? null}
                        />
                      </td>
                      {columns.map((col) => (
                        <td key={col.key} className="px-3 py-2 text-right tabular-nums">
                          <RatingCell
                            value={fa.ratings[col.key]}
                            context={
                              positionContext
                                ? fa.ratings_context?.[col.key]
                                : undefined
                            }
                          />
                        </td>
                      ))}
                      <td className="px-4 py-2 text-right">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setSigning(fa)}
                          disabled={!teamId}
                          title={teamId ? "Sign to your team" : "No active team"}
                        >
                          <UserPlus className="h-3 w-3" /> Sign
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      <SignDialog
        player={signing}
        teamId={teamId}
        onClose={() => setSigning(null)}
      />
    </AppShell>
  );
}

function SignDialog({
  player,
  teamId,
  onClose,
}: {
  player: FreeAgent | null;
  teamId: string | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [level, setLevel] = useState<"ACT" | "AAA" | "LOW">("ACT");
  const [years, setYears] = useState("3");
  const [salary, setSalary] = useState("");
  const [signingBonus, setSigningBonus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<ExtensionEvaluation | null>(null);
  const [windowClosed, setWindowClosed] = useState<string | null>(null);

  // Live preview: fair-market estimate + competing CPU bids. Refreshes
  // when the user edits years/salary so they can see how their offer
  // stacks up before submitting.
  const previewQ = useQuery({
    queryKey: ["fa-offer-preview", player?.player_id, years, salary],
    queryFn: () =>
      api.evaluateFreeAgentOffer(player!.player_id, {
        years: Number(years) || 1,
        annual_salary: salary ? Number(salary) : undefined,
      }),
    enabled: !!player,
  });

  const sign = useMutation({
    // The in-dialog response handles success + failure inline.
    meta: { suppressToast: true },
    mutationFn: () => {
      if (!player || !teamId) return Promise.reject(new Error("No team"));
      return api.signFreeAgent(teamId, {
        player_id: player.player_id,
        level,
        years: Number(years) || 1,
        annual_salary: salary ? Number(salary) : undefined,
        signing_bonus: signingBonus ? Number(signingBonus) : undefined,
      });
    },
    onSuccess: (data) => {
      setError(null);
      setResponse(null);
      queryClient.invalidateQueries({ queryKey: ["free-agents"] });
      queryClient.invalidateQueries({ queryKey: ["team-roster"] });
      queryClient.invalidateQueries({ queryKey: ["activity"] });
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
      const name = player
        ? `${player.first_name} ${player.last_name}`.trim() || player.player_id
        : "Player";
      toast.success(`Signed ${name}`, {
        description: `${data.years}yr × $${data.annual_salary.toLocaleString()} → ${level}.`,
      });
      onClose();
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        const body = err.body as { detail?: FreeAgentSignRejection } | undefined;
        const detail = body?.detail;
        if (detail?.code === "fa_window_closed") {
          setWindowClosed(detail.message);
          setResponse(null);
          setError(null);
          return;
        }
        if (detail?.negotiation) {
          setResponse(detail.negotiation);
          setError(null);
          setWindowClosed(null);
          return;
        }
      }
      setResponse(null);
      setWindowClosed(null);
      setError(err instanceof Error ? err.message : "Sign failed.");
    },
  });

  function handleSubmit(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    setResponse(null);
    sign.mutate();
  }

  function acceptCounter() {
    if (!response) return;
    if (response.counter_salary != null) {
      setSalary(String(response.counter_salary));
    }
    if (response.counter_years != null) {
      setYears(String(response.counter_years));
    }
    setResponse(null);
  }

  return (
    <Dialog open={!!player} onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            Negotiate with {player?.last_name}
            {player?.first_name ? `, ${player.first_name}` : ""}
          </DialogTitle>
          <DialogDescription>
            Make an offer. The player evaluates it against market value
            and competing bids before deciding.
          </DialogDescription>
        </DialogHeader>

        {/* Phase-gate banner — replaces the rest of the form when the
            FA window is closed. */}
        {(windowClosed || previewQ.data?.phase_gate) && (
          <div className="rounded-md border border-warning/50 bg-warning/10 px-3 py-2 text-xs text-warning">
            <div className="font-semibold uppercase tracking-wider">
              FA market closed
            </div>
            <div className="mt-1 leading-snug">
              {windowClosed ?? previewQ.data?.phase_gate?.message}
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          {previewQ.data && !previewQ.data.phase_gate && (
            <div className="rounded-md border border-border bg-surfaceAlt/40 px-3 py-2 text-xs">
              <div className="font-semibold uppercase tracking-wider text-muted">
                Market estimate
              </div>
              <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1">
                <span className="text-muted">Fair salary</span>
                <span className="text-right tabular-nums font-semibold">
                  ${previewQ.data.fair_market_salary.toLocaleString()}/yr
                </span>
                <span className="text-muted">Fair length</span>
                <span className="text-right tabular-nums font-semibold">
                  {previewQ.data.fair_market_years} yrs
                </span>
                <span className="text-muted">Service tier</span>
                <span className="text-right text-xs uppercase">
                  {previewQ.data.service_tier.replace("_", " ")}
                </span>
              </div>
              {previewQ.data.competing_bids.length > 0 && (
                <div className="mt-2 border-t border-border/60 pt-2">
                  <div className="font-semibold uppercase tracking-wider text-muted">
                    Competing bids
                  </div>
                  <ul className="mt-1 space-y-0.5">
                    {previewQ.data.competing_bids.map((b) => (
                      <li
                        key={b.team_id}
                        className="flex items-center justify-between"
                      >
                        <span className="font-mono text-xs">{b.team_id}</span>
                        <span className="tabular-nums">
                          ${b.salary.toLocaleString()}/yr
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="fa-years">Years</Label>
              <Input
                id="fa-years"
                type="number"
                min={1}
                max={10}
                value={years}
                onChange={(e) => setYears(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="fa-salary">Annual salary</Label>
              <Input
                id="fa-salary"
                type="number"
                min={0}
                step={50000}
                value={salary}
                onChange={(e) => setSalary(e.target.value)}
                placeholder={
                  previewQ.data
                    ? `Defaults to fair market`
                    : "$"
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="fa-bonus">Signing bonus</Label>
              <Input
                id="fa-bonus"
                type="number"
                min={0}
                step={100000}
                value={signingBonus}
                onChange={(e) => setSigningBonus(e.target.value)}
                placeholder="Optional — debits cash now"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>Roster level</Label>
            <div className="flex rounded-lg border border-border bg-surfaceAlt p-1">
              {(["ACT", "AAA", "LOW"] as const).map((opt) => (
                <button
                  key={opt}
                  type="button"
                  onClick={() => setLevel(opt)}
                  className={cn(
                    "flex-1 rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
                    level === opt
                      ? "bg-amber text-espresso"
                      : "text-muted hover:bg-surface hover:text-ink",
                  )}
                >
                  {opt}
                </button>
              ))}
            </div>
          </div>

          {/* Player's response — counter-offer or rejection. */}
          {response && (
            <div
              className={cn(
                "rounded-md border px-3 py-2 text-xs",
                response.decision === "rejected"
                  ? "border-danger/40 bg-danger/10 text-danger"
                  : "border-amber/60 bg-amber/10 text-amber-text",
              )}
            >
              <div className="font-semibold uppercase tracking-wider">
                {response.decision === "rejected"
                  ? "Player rejected the offer"
                  : "Player countered"}
              </div>
              <div className="mt-1 leading-snug">{response.reason}</div>
              {response.decision === "countered" && response.counter_salary && (
                <button
                  type="button"
                  onClick={acceptCounter}
                  className="mt-2 inline-flex items-center gap-1 rounded border border-amber/60 bg-amber/20 px-2 py-1 text-xs font-semibold uppercase tracking-wider text-amber-text hover:bg-amber/30"
                >
                  Use ${response.counter_salary.toLocaleString()}/yr ×{" "}
                  {response.counter_years} yrs
                </button>
              )}
            </div>
          )}

          {error && (
            <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={
                sign.isPending ||
                !teamId ||
                !!windowClosed ||
                !!previewQ.data?.phase_gate
              }
            >
              {sign.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Submit offer
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function sortValue(p: FreeAgent, key: SortKey): string | number | null {
  switch (key) {
    case "name":
      return `${p.last_name}, ${p.first_name}`;
    case "pos":
      return p.primary_position;
    case "bats":
      return p.bats;
    case "role":
      return p.role;
    case "overall":
      return p.overall_display ?? p.overall_raw ?? null;
    default: {
      const raw = p.ratings[key];
      if (raw == null) return null;
      const n = typeof raw === "number" ? raw : Number(raw);
      return Number.isFinite(n) ? n : String(raw);
    }
  }
}

function HeaderCell({
  label,
  keyId,
  sortKey,
  sortDir,
  onClick,
  align = "right",
}: {
  label: string;
  keyId: SortKey;
  sortKey: SortKey;
  sortDir: SortDir;
  onClick: (k: SortKey) => void;
  align?: "left" | "right";
}) {
  const active = sortKey === keyId;
  const Arrow = !active ? ArrowUpDown : sortDir === "asc" ? ArrowUp : ArrowDown;
  return (
    <th
      className={cn(
        "select-none px-3 py-2 font-semibold",
        align === "left" ? "pl-6 text-left" : "text-right",
      )}
    >
      <button
        type="button"
        onClick={() => onClick(keyId)}
        className={cn(
          "inline-flex items-center gap-1 hover:text-ink",
          active ? "text-ink" : "text-muted",
          align === "right" && "flex-row-reverse",
        )}
      >
        <Arrow className="h-3 w-3" />
        {label}
      </button>
    </th>
  );
}

function RatingCell({
  value,
  context,
}: {
  value: number | string | null | undefined;
  context?: RatingContextEntry;
}) {
  if (value == null || value === "") return <span className="text-subtle">—</span>;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return <>{String(value)}</>;
  const tone =
    n >= 85 ? "text-success" : n >= 70 ? "text-amber-text" : n >= 50 ? "text-ink" : "text-subtle";
  if (!context) {
    return <span className={tone}>{Math.round(n)}</span>;
  }
  const bucket = context.bucket ?? "pool";
  const avgText = context.avg == null ? "--" : String(context.avg);
  return (
    <span
      className="inline-flex items-baseline justify-end gap-1"
      title={`Top ${context.top_pct}% of ${bucket} (avg ${avgText})`}
    >
      <span className={tone}>{Math.round(n)}</span>
      <span className="text-[10px] text-muted">({context.top_pct}%)</span>
    </span>
  );
}

function OverallCell({
  display,
  starsText,
}: {
  display: number | null;
  starsText: string | null;
}) {
  if (display == null) return <span className="text-subtle">—</span>;
  const stars = parseFloat(starsText ?? "");
  const tone =
    display >= 85
      ? "text-success"
      : display >= 70
      ? "text-amber-text"
      : display >= 50
      ? "text-ink"
      : "text-subtle";
  return (
    <div className="inline-flex flex-col items-end gap-0.5">
      <span className={cn("font-display font-semibold tabular-nums", tone)}>
        {Math.round(display)}
      </span>
      {Number.isFinite(stars) && stars > 0 && (
        <StarRating value={stars} size="h-2.5 w-2.5" />
      )}
    </div>
  );
}

function Pill({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
        active
          ? "bg-amber text-espresso"
          : "text-muted hover:bg-surface hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading free agents…</span>
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
