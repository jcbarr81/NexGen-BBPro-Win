/**
 * Phase 4 port of ui/trade_dialog.py.
 *
 * Renders every trade in ``data/trades_pending.csv`` grouped by status with
 * inline Accept / Reject / Withdraw actions on pending offers, plus a
 * "Propose Trade" dialog that POSTs through utils.trade_utils.save_trade
 * (validates pick ownership, deadline, etc., on the server).
 */

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeftRight,
  ArrowRight,
  CheckCircle2,
  Clock,
  Loader2,
  Plus,
  Trash2,
  XCircle,
} from "lucide-react";

import {
  api,
  type Team,
  type TradeCpuEvaluation,
  type TradePlayer,
  type TradeRecord,
} from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { useConfirmDialog } from "@/lib/use-confirm";
import { usePersistedState } from "@/lib/use-persisted-state";
import { toast } from "@/lib/toast-store";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";

type Scope = "team" | "all";

// Preferred display order + labels for statuses we know about.
const STATUS_ORDER: Array<{ key: string; label: string }> = [
  { key: "pending", label: "Pending" },
  { key: "owner_accepted", label: "Owner Accepted" },
  { key: "accepted", label: "Accepted" },
  { key: "rejected", label: "Rejected" },
];

interface ProposeTradePrefill {
  fromTeam?: string;
  toTeam?: string;
  givePlayers?: string[];
  receivePlayers?: string[];
}

export function TradesPage() {
  const user = useAuthStore();
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;
  const [scope, setScope] = useState<Scope>(teamId ? "team" : "all");
  const [proposing, setProposing] = useState(false);
  const [prefill, setPrefill] = useState<ProposeTradePrefill | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [vetoTarget, setVetoTarget] = useState<string | null>(null);
  const { confirm, dialog: confirmDialog } = useConfirmDialog();
  const effectiveScope: Scope = teamId ? scope : "all";

  // Honor location.state.proposeTrade so flows like the player-profile
  // "Trade for Player" button can deep-link straight into a pre-filled
  // ProposeTradeDialog. We clear the state via replace() so a manual
  // reload doesn't keep popping the dialog.
  useEffect(() => {
    const state = location.state as
      | { proposeTrade?: ProposeTradePrefill }
      | null;
    const pre = state?.proposeTrade;
    if (pre) {
      setPrefill(pre);
      setProposing(true);
      navigate(location.pathname, { replace: true, state: null });
    }
  }, [location.state, location.pathname, navigate]);

  const trades = useQuery({
    queryKey: ["trades", effectiveScope, teamId],
    queryFn: () =>
      api.trades(effectiveScope === "team" && teamId ? { teamId } : {}),
  });
  const teams = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
  });

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["trades"] });
    queryClient.invalidateQueries({ queryKey: ["team-roster"] });
  }

  // ``actionError`` still renders the inline banner with the full
  // (often multi-line) error — suppressToast avoids firing the default
  // toast alongside it. Success is new: toast for the happy path.
  const acceptMutation = useMutation({
    meta: { suppressToast: true },
    mutationFn: (id: string) => api.acceptTrade(id),
    onSuccess: () => {
      setActionError(null);
      refresh();
      toast.success("Trade accepted");
    },
    onError: (err) =>
      setActionError(err instanceof Error ? err.message : "Accept failed."),
  });
  const rejectMutation = useMutation({
    meta: { suppressToast: true },
    mutationFn: (id: string) => api.rejectTrade(id),
    onSuccess: () => {
      setActionError(null);
      refresh();
      toast.info("Trade rejected");
    },
    onError: (err) =>
      setActionError(err instanceof Error ? err.message : "Reject failed."),
  });
  const withdrawMutation = useMutation({
    meta: { suppressToast: true },
    mutationFn: (id: string) => api.withdrawTrade(id),
    onSuccess: () => {
      setActionError(null);
      refresh();
      toast.info("Trade withdrawn");
    },
    onError: (err) =>
      setActionError(err instanceof Error ? err.message : "Withdraw failed."),
  });
  const adminApproveMutation = useMutation({
    meta: { suppressToast: true },
    mutationFn: ({ id, force }: { id: string; force: boolean }) =>
      api.adminApproveTrade(id, force),
    onSuccess: () => {
      setActionError(null);
      refresh();
      toast.success("Trade approved");
    },
    onError: (err) =>
      setActionError(
        err instanceof Error ? err.message : "Admin approve failed.",
      ),
  });
  const adminVetoMutation = useMutation({
    meta: { suppressToast: true },
    mutationFn: ({ id, note }: { id: string; note: string }) =>
      api.adminVetoTrade(id, note),
    onSuccess: () => {
      setActionError(null);
      refresh();
      toast.info("Trade vetoed");
    },
    onError: (err) =>
      setActionError(err instanceof Error ? err.message : "Veto failed."),
  });

  const isAdmin = useAuthStore((s) => s.role) === "admin";
  const [counterTarget, setCounterTarget] = useState<TradeRecord | null>(null);
  const actions = {
    teamId,
    isAdmin,
    accept: (id: string) => acceptMutation.mutate(id),
    reject: (id: string) => rejectMutation.mutate(id),
    counter: (trade: TradeRecord) => setCounterTarget(trade),
    withdraw: async (id: string) => {
      if (
        await confirm({
          title: "Withdraw trade?",
          description: "The proposal is removed from both teams' inboxes.",
          confirmLabel: "Withdraw",
        })
      ) {
        withdrawMutation.mutate(id);
      }
    },
    adminApprove: async (id: string) => {
      if (
        await confirm({
          title: "Approve trade?",
          description: "Commissioner approval commits this trade.",
          confirmLabel: "Approve",
        })
      ) {
        adminApproveMutation.mutate({ id, force: false });
      }
    },
    adminForceApprove: async (id: string) => {
      if (
        await confirm({
          title: "Force-approve trade?",
          description:
            "Overrides all validation errors. This cannot be undone.",
          confirmLabel: "Force-approve",
          danger: true,
        })
      ) {
        adminApproveMutation.mutate({ id, force: true });
      }
    },
    adminVeto: (id: string) => {
      setVetoTarget(id);
    },
    pending:
      acceptMutation.isPending ||
      rejectMutation.isPending ||
      withdrawMutation.isPending ||
      adminApproveMutation.isPending ||
      adminVetoMutation.isPending,
  };

  // Stable ordered list of (status, rows) so the tab row doesn't reshuffle
  // when counts change. We also pull pending CPU offers into a dedicated
  // first tab so the owner can find their inbox without scrolling.
  const statusGroups = useMemo(() => {
    if (!trades.data)
      return [] as Array<{ key: string; label: string; rows: TradeRecord[] }>;
    const groups = trades.data.grouped ?? {};

    // Synthetic tab: pending offers from the CPU addressed to the user.
    // These are the ones that need a response right now, so they get
    // top billing.
    const cpuInbox = (groups["pending"] ?? []).filter(
      (t) =>
        t.initiated_by === "cpu" && !!teamId && t.to_team === teamId,
    );

    const known: Array<{ key: string; label: string; rows: TradeRecord[] }> = [];
    if (teamId) {
      known.push({ key: "from_cpu", label: "Offers from CPU", rows: cpuInbox });
    }
    for (const { key, label } of STATUS_ORDER) {
      let rows = groups[key] ?? [];
      // Don't double-list the CPU offers in the regular Pending tab —
      // they're already visible in From CPU.
      if (key === "pending" && cpuInbox.length > 0) {
        const cpuIds = new Set(cpuInbox.map((t) => t.trade_id));
        rows = rows.filter((t) => !cpuIds.has(t.trade_id));
      }
      known.push({ key, label, rows });
    }
    // Append any unknown statuses the data happens to have.
    const unknown = Object.keys(groups).filter(
      (k) => !STATUS_ORDER.some((s) => s.key === k),
    );
    for (const key of unknown) {
      known.push({ key, label: key, rows: groups[key] ?? [] });
    }
    return known;
  }, [trades.data, teamId]);

  const firstWithRows =
    statusGroups.find((g) => g.rows.length > 0)?.key ??
    statusGroups[0]?.key ??
    "pending";
  const [tradesTab, setTradesTab] = usePersistedState<string>(
    "trades:tab",
    "",
  );

  const deadlineQ = useQuery({
    queryKey: ["trades-deadline"],
    queryFn: () => api.tradeDeadline(),
    refetchOnWindowFocus: false,
  });

  return (
    <AppShell
      title="Transactions"
      subtitle={
        effectiveScope === "team" && teamId
          ? `Trades involving ${teamId}`
          : "League-wide trade log"
      }
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
          <ScopePill
            active={effectiveScope === "team"}
            disabled={!teamId}
            onClick={() => setScope("team")}
          >
            My team
          </ScopePill>
          <ScopePill
            active={effectiveScope === "all"}
            onClick={() => setScope("all")}
          >
            All teams
          </ScopePill>
        </div>
        <div className="flex items-center gap-3">
          {trades.data && (
            <div className="text-xs text-muted">{trades.data.count} trades</div>
          )}
          <Button
            onClick={() => setProposing(true)}
            disabled={deadlineQ.data?.is_past === true}
            title={
              deadlineQ.data?.is_past
                ? "Trade deadline has passed"
                : "Propose a new trade"
            }
          >
            <Plus className="h-4 w-4" /> Propose Trade
          </Button>
        </div>
      </div>

      {/* Deadline banner. Tone tightens as the date approaches: amber
          inside ~30 days, red on/past the deadline, neutral when
          there's plenty of time. */}
      {deadlineQ.data && (
        <div
          className={cn(
            "mb-4 flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm",
            deadlineQ.data.is_past
              ? "border-danger/50 bg-danger/10 text-danger"
              : deadlineQ.data.days_remaining <= 30
                ? "border-amber/60 bg-amber/10 text-amber-text"
                : "border-border bg-surfaceAlt/40 text-muted",
          )}
        >
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4" />
            <span className="font-semibold">
              Trade deadline: {deadlineQ.data.deadline_date}
            </span>
          </div>
          <div className="text-xs">
            {deadlineQ.data.is_past
              ? "Closed for the season — pending offers can no longer be saved."
              : `${deadlineQ.data.days_remaining} day${deadlineQ.data.days_remaining === 1 ? "" : "s"} remaining (sim date ${deadlineQ.data.current_sim_date})`}
          </div>
        </div>
      )}

      {actionError && (
        <div className="mb-4 flex items-center gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          <AlertTriangle className="h-4 w-4" />
          {actionError}
        </div>
      )}

      {trades.isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <Loader2 className="h-5 w-5 animate-spin text-amber" />
            <span className="text-sm text-muted">Loading trades…</span>
          </CardContent>
        </Card>
      ) : trades.isError ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-danger">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm">{(trades.error as Error).message}</span>
          </CardContent>
        </Card>
      ) : !trades.data || trades.data.count === 0 ? (
        <Card>
          <CardContent className="py-10 text-sm text-muted">
            No trades have been recorded yet.
          </CardContent>
        </Card>
      ) : (
        <Tabs
          value={tradesTab || firstWithRows}
          onValueChange={(v) => setTradesTab(v)}
        >
          <TabsList>
            {statusGroups.map((group) => (
              <TabsTrigger key={group.key} value={group.key}>
                <span>{group.label}</span>
                <Badge tone={toneFor(group.key)} className="ml-2">
                  {group.rows.length}
                </Badge>
              </TabsTrigger>
            ))}
          </TabsList>
          {statusGroups.map((group) => (
            <TabsContent key={group.key} value={group.key}>
              {group.rows.length === 0 ? (
                <Card>
                  <CardContent className="py-8 text-sm text-muted">
                    No {group.label.toLowerCase()} trades.
                  </CardContent>
                </Card>
              ) : (
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  {group.rows.map((trade) => (
                    <TradeCard
                      key={trade.trade_id}
                      trade={trade}
                      activeTeamId={teamId}
                      actions={actions}
                    />
                  ))}
                </div>
              )}
            </TabsContent>
          ))}
        </Tabs>
      )}

      <CounterTradeDialog
        trade={counterTarget}
        teamId={teamId}
        onClose={() => setCounterTarget(null)}
      />

      <ProposeTradeDialog
        open={proposing}
        onOpenChange={(open) => {
          setProposing(open);
          if (!open) setPrefill(null);
        }}
        defaultFromTeam={prefill?.fromTeam || teamId || ""}
        defaultToTeam={prefill?.toTeam || ""}
        defaultGivePlayers={prefill?.givePlayers || []}
        defaultReceivePlayers={prefill?.receivePlayers || []}
        teams={teams.data ?? []}
        onProposed={refresh}
      />
      <VetoDialog
        tradeId={vetoTarget}
        onOpenChange={(open) => !open && setVetoTarget(null)}
        onConfirm={(note) => {
          if (!vetoTarget) return;
          adminVetoMutation.mutate({ id: vetoTarget, note });
          setVetoTarget(null);
        }}
      />
      {confirmDialog}
    </AppShell>
  );
}

function VetoDialog({
  tradeId,
  onOpenChange,
  onConfirm,
}: {
  tradeId: string | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: (note: string) => void;
}) {
  const [note, setNote] = useState("");
  return (
    <Dialog open={!!tradeId} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Veto trade</DialogTitle>
          <DialogDescription>
            Vetoing marks the trade rejected as commissioner and notifies
            both owners. The note appears in the trade's audit entry.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="veto-note">Note (shown to owners)</Label>
          <textarea
            id="veto-note"
            className="h-28 w-full rounded-md border border-border bg-surface px-2 py-1 text-sm"
            placeholder="e.g. Payroll impact too severe for both sides"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
        <div className="mt-3 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              onConfirm(note);
              setNote("");
            }}
          >
            Confirm veto
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

interface RowActions {
  teamId: string | null;
  isAdmin: boolean;
  accept: (id: string) => void;
  reject: (id: string) => void;
  counter: (trade: TradeRecord) => void;
  withdraw: (id: string) => void;
  adminApprove: (id: string) => void;
  adminForceApprove: (id: string) => void;
  adminVeto: (id: string) => void;
  pending: boolean;
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

function TradeCard({
  trade,
  activeTeamId,
  actions,
}: {
  trade: TradeRecord;
  activeTeamId: string | null;
  actions: RowActions;
}) {
  const fromActive = trade.from_team === activeTeamId;
  const toActive = trade.to_team === activeTeamId;
  const status = trade.status.toLowerCase();
  const isPending = status === "pending" || status === "owner_accepted";
  // Owner of the receiving team accepts/rejects; owner of the proposing team
  // can withdraw. Admin (no team) sees both.
  const canRespond = isPending && (!activeTeamId || toActive);
  const canWithdraw = isPending && (!activeTeamId || fromActive);
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="text-base">
            {trade.from_team} <span className="text-muted">⇄</span> {trade.to_team}
          </CardTitle>
          <CardDescription>id: {trade.trade_id}</CardDescription>
        </div>
        <div className="flex items-center gap-2">
          {trade.initiated_by === "cpu" && (
            <Badge tone="amber" className="text-[10px]">
              CPU offer
            </Badge>
          )}
          <StatusBadge status={trade.status} />
        </div>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-4 md:grid-cols-[1fr_auto_1fr]">
        <TradeSide
          teamId={trade.from_team}
          players={trade.give_players}
          picks={trade.give_picks}
          label="Gives"
          highlight={fromActive}
        />
        <div className="flex items-center justify-center">
          <ArrowRight className="h-4 w-4 text-amber" />
        </div>
        <TradeSide
          teamId={trade.to_team}
          players={trade.receive_players}
          picks={trade.receive_picks}
          label="Receives"
          highlight={toActive}
        />
      </CardContent>
      {trade.cpu_eval && <CpuEvalBlock evaluation={trade.cpu_eval} />}
      {(canRespond || canWithdraw || (isPending && actions.isAdmin)) && (
        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border/60 bg-surfaceAlt/40 px-6 py-3">
          {canWithdraw && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => actions.withdraw(trade.trade_id)}
              disabled={actions.pending}
            >
              <Trash2 className="h-3 w-3" /> Withdraw
            </Button>
          )}
          {canRespond && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => actions.reject(trade.trade_id)}
                disabled={actions.pending}
              >
                <XCircle className="h-3 w-3" /> Reject
              </Button>
              {/* Counter only makes sense on CPU offers — owner-to-owner
                  trades have a different back-and-forth (the recipient
                  can withdraw and submit their own from scratch). */}
              {trade.initiated_by === "cpu" && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => actions.counter(trade)}
                  disabled={actions.pending}
                  title="Send back a modified offer"
                >
                  <ArrowLeftRight className="h-3 w-3" /> Counter
                </Button>
              )}
              <Button
                size="sm"
                onClick={() => actions.accept(trade.trade_id)}
                disabled={actions.pending}
              >
                <CheckCircle2 className="h-3 w-3" /> Accept
              </Button>
            </>
          )}
          {actions.isAdmin && isPending && (
            <>
              <div className="mx-2 h-4 w-px bg-border" aria-hidden />
              <span className="text-[10px] uppercase tracking-wider text-amber">
                Admin
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => actions.adminVeto(trade.trade_id)}
                disabled={actions.pending}
              >
                <XCircle className="h-3 w-3" /> Veto
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => actions.adminForceApprove(trade.trade_id)}
                disabled={actions.pending}
                title="Force-approve, overriding validation errors"
              >
                Force approve
              </Button>
              <Button
                size="sm"
                onClick={() => actions.adminApprove(trade.trade_id)}
                disabled={actions.pending}
              >
                <CheckCircle2 className="h-3 w-3" /> Approve
              </Button>
            </>
          )}
        </div>
      )}
    </Card>
  );
}

function TradeSide({
  teamId,
  players,
  picks,
  label,
  highlight,
}: {
  teamId: string;
  players: TradePlayer[];
  picks: string[];
  label: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-surfaceAlt/40 p-3",
        highlight && "border-amber/60 bg-amber/10",
      )}
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
          {label}
        </span>
        <span className="font-display text-sm font-bold">{teamId}</span>
      </div>
      {players.length === 0 && picks.length === 0 ? (
        <div className="text-xs text-muted">—</div>
      ) : (
        <>
          {players.length > 0 && (
            <ul className="space-y-1">
              {players.map((p) => (
                <li
                  key={p.player_id}
                  className="flex items-center justify-between gap-2 text-sm"
                >
                  <span className="truncate font-semibold">{p.name}</span>
                  <span className="text-[11px] uppercase tracking-wider text-muted">
                    {p.position || (p.is_pitcher ? "PIT" : "POS")}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {picks.length > 0 && (
            <div className="mt-2 border-t border-border/60 pt-2">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                Picks
              </div>
              <ul className="mt-1 space-y-0.5 font-mono text-xs">
                {picks.map((pick) => (
                  <li key={pick}>{pick}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const tone = toneFor(status);
  const Icon = iconFor(status);
  const label = STATUS_ORDER.find((s) => s.key === status)?.label ?? status;
  return (
    <Badge tone={tone}>
      <Icon className="h-3 w-3" /> {label}
    </Badge>
  );
}

function toneFor(status: string): "amber" | "success" | "danger" | "neutral" {
  const key = status.toLowerCase();
  if (key === "from_cpu") return "amber";
  if (key === "pending" || key === "owner_accepted") return "amber";
  if (key === "accepted") return "success";
  if (key === "rejected") return "danger";
  return "neutral";
}

function iconFor(status: string) {
  const key = status.toLowerCase();
  if (key === "accepted") return CheckCircle2;
  if (key === "rejected") return XCircle;
  return Clock;
}

function CpuEvalBlock({ evaluation }: { evaluation: TradeCpuEvaluation }) {
  const action = evaluation.action;
  const tone =
    action === "accept"
      ? "border-success/50 bg-success/10 text-success"
      : action === "reject"
        ? "border-danger/50 bg-danger/10 text-danger"
        : "border-amber/50 bg-amber/10 text-amber-text";
  const verb =
    action === "accept"
      ? "accepted"
      : action === "reject"
        ? "rejected the offer"
        : "countered with their own offer";
  return (
    <div className={cn("border-t px-6 py-3 text-xs", tone)}>
      <div className="flex items-center justify-between gap-3">
        <div className="font-semibold uppercase tracking-wider">
          {evaluation.team_id} {verb}
        </div>
        <div className="font-mono tabular-nums text-[10px] opacity-80">
          score {evaluation.total_score.toFixed(1)} / threshold{" "}
          {evaluation.threshold.toFixed(1)} ·{" "}
          {evaluation.strategy_profile} / {evaluation.competitive_window}
        </div>
      </div>
      {evaluation.reasons.length > 0 && (
        <ul className="mt-1 list-disc space-y-0.5 pl-5 leading-snug">
          {evaluation.reasons.slice(0, 4).map((reason, i) => (
            <li key={i}>{reason}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Counter Trade dialog — owner sends back a modified version of a CPU offer.
//
// Pre-fills with the CPU's terms but flipped to the OWNER's perspective:
// "Give" = the players the owner is now offering up (originally the CPU's
// "Receive" list); "Receive" = what the owner wants back (originally the
// CPU's "Give" list). Owner edits, submits, backend rejects the original
// and runs the counter through the same CPU evaluation as a fresh
// proposal.

function CounterTradeDialog({
  trade,
  teamId,
  onClose,
}: {
  trade: TradeRecord | null;
  teamId: string | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  // Initialize from the original trade (if any) flipped to owner POV.
  const [give, setGive] = useState("");
  const [receive, setReceive] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Refresh the form when the target trade changes.
  useEffect(() => {
    if (!trade) {
      setGive("");
      setReceive("");
      setError(null);
      return;
    }
    // Original trade is CPU → owner. From the owner's POV, what they
    // would "give" up = the CPU's "receive_players"; what they get =
    // CPU's "give_players". So just swap.
    setGive(trade.receive_players.map((p) => p.player_id).join(", "));
    setReceive(trade.give_players.map((p) => p.player_id).join(", "));
    setError(null);
  }, [trade]);

  const counter = useMutation({
    meta: { suppressToast: true },
    mutationFn: () => {
      if (!trade) return Promise.reject(new Error("No trade selected"));
      return api.counterTrade(trade.trade_id, {
        give_player_ids: parseIds(give),
        receive_player_ids: parseIds(receive),
      });
    },
    onSuccess: (data) => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["trades"] });
      const action = data.cpu_response?.action;
      if (action === "accept") {
        toast.success("Counter accepted", {
          description: "Trade committed.",
        });
      } else if (action === "counter") {
        toast.info("CPU re-countered your offer");
      } else if (action === "reject") {
        toast.info("CPU rejected your counter");
      } else {
        toast.info("Counter submitted");
      }
      onClose();
    },
    onError: (err) =>
      setError(err instanceof Error ? err.message : "Counter failed."),
  });

  function handleSubmit(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    counter.mutate();
  }

  if (!trade) return null;
  return (
    <Dialog open={!!trade} onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            Counter {trade.from_team}'s offer
          </DialogTitle>
          <DialogDescription>
            Edit the terms below. The CPU will re-evaluate and may
            accept, reject, or counter again.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="counter-give">
              You give ({teamId ?? "your team"} → {trade.from_team})
            </Label>
            <Input
              id="counter-give"
              value={give}
              onChange={(e) => setGive(e.target.value)}
              placeholder="player_id, player_id, …"
            />
            <p className="text-[11px] text-muted">
              Comma- or pipe-separated player IDs from {teamId ?? "your"}{" "}
              roster.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="counter-receive">
              You receive ({trade.from_team} → {teamId ?? "your team"})
            </Label>
            <Input
              id="counter-receive"
              value={receive}
              onChange={(e) => setReceive(e.target.value)}
              placeholder="player_id, player_id, …"
            />
            <p className="text-[11px] text-muted">
              Comma- or pipe-separated player IDs from {trade.from_team}'s
              roster.
            </p>
          </div>
          {error && (
            <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={counter.isPending}>
              {counter.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Submit counter
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Propose Trade dialog
//
// Phase 4 keeps this lightweight: pick from team / to team and enter pipe-
// or comma-separated player ids. Roster + draft-pick pickers come in a
// follow-up that wires this dialog into the roster page.

function ProposeTradeDialog({
  open,
  onOpenChange,
  defaultFromTeam,
  defaultToTeam = "",
  defaultGivePlayers = [],
  defaultReceivePlayers = [],
  teams,
  onProposed,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultFromTeam: string;
  defaultToTeam?: string;
  defaultGivePlayers?: string[];
  defaultReceivePlayers?: string[];
  teams: Team[];
  onProposed: () => void;
}) {
  const [fromTeam, setFromTeam] = useState(defaultFromTeam);
  const [toTeam, setToTeam] = useState(defaultToTeam);
  const [givePlayers, setGivePlayers] = useState(defaultGivePlayers.join(", "));
  const [receivePlayers, setReceivePlayers] = useState(
    defaultReceivePlayers.join(", "),
  );
  const [givePicks, setGivePicks] = useState("");
  const [receivePicks, setReceivePicks] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Re-sync the local form state when the dialog re-opens with new
  // defaults. Without this useEffect the prefill from a "Trade for
  // Player" deep-link only applies on the very first open, and a later
  // open from a different player would keep the previous values.
  useEffect(() => {
    if (open) {
      setFromTeam(defaultFromTeam);
      setToTeam(defaultToTeam);
      setGivePlayers(defaultGivePlayers.join(", "));
      setReceivePlayers(defaultReceivePlayers.join(", "));
      setError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    open,
    defaultFromTeam,
    defaultToTeam,
    // Stringify list defaults so the dep-comparison is by content, not
    // by array identity (a parent might pass a fresh array each render).
    defaultGivePlayers.join(","),
    defaultReceivePlayers.join(","),
  ]);

  const mutation = useMutation({
    mutationFn: () =>
      api.proposeTrade({
        from_team: fromTeam,
        to_team: toTeam,
        give_player_ids: parseIds(givePlayers),
        receive_player_ids: parseIds(receivePlayers),
        give_pick_ids: parseIds(givePicks),
        receive_pick_ids: parseIds(receivePicks),
      }),
    onSuccess: () => {
      setError(null);
      onProposed();
      setGivePlayers("");
      setReceivePlayers("");
      setGivePicks("");
      setReceivePicks("");
      onOpenChange(false);
    },
    onError: (err) =>
      setError(err instanceof Error ? err.message : "Proposal failed."),
  });

  function handleSubmit(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    if (!fromTeam || !toTeam || fromTeam === toTeam) {
      setError("Pick two different teams.");
      return;
    }
    mutation.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Propose Trade</DialogTitle>
          <DialogDescription>
            Player + pick lists accept comma- or space-separated IDs.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <TeamPicker
              label="From"
              value={fromTeam}
              teams={teams}
              exclude={toTeam}
              onChange={setFromTeam}
            />
            <TeamPicker
              label="To"
              value={toTeam}
              teams={teams}
              exclude={fromTeam}
              onChange={setToTeam}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="give-players">Give players</Label>
              <Input
                id="give-players"
                placeholder="e.g. P1234, P5678"
                value={givePlayers}
                onChange={(e) => setGivePlayers(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="receive-players">Receive players</Label>
              <Input
                id="receive-players"
                placeholder="e.g. P9999"
                value={receivePlayers}
                onChange={(e) => setReceivePlayers(e.target.value)}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="give-picks">Give picks (optional)</Label>
              <Input
                id="give-picks"
                placeholder="2027|1|CHI"
                value={givePicks}
                onChange={(e) => setGivePicks(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="receive-picks">Receive picks (optional)</Label>
              <Input
                id="receive-picks"
                placeholder="2027|2|DAL"
                value={receivePicks}
                onChange={(e) => setReceivePicks(e.target.value)}
              />
            </div>
          </div>

          {error && (
            <p className="whitespace-pre-line rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Propose
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function TeamPicker({
  label,
  value,
  teams,
  exclude,
  onChange,
}: {
  label: string;
  value: string;
  teams: Team[];
  exclude?: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
        {label}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 rounded-lg border border-border bg-canvas/60 px-3 text-sm text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
      >
        <option value="">— select —</option>
        {teams
          .filter((t) => t.team_id !== exclude)
          .map((t) => (
            <option key={t.team_id} value={t.team_id}>
              {t.city} {t.name} ({t.abbreviation})
            </option>
          ))}
      </select>
    </label>
  );
}

function parseIds(raw: string): string[] {
  return raw
    .split(/[,\s]+/)
    .map((x) => x.trim())
    .filter(Boolean);
}
