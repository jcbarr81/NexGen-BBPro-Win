/**
 * Phase 4 port of ui/trade_dialog.py.
 *
 * Renders every trade in ``data/trades_pending.csv`` grouped by status with
 * inline Accept / Reject / Withdraw actions on pending offers, plus a
 * "Propose Trade" dialog that POSTs through utils.trade_utils.save_trade
 * (validates pick ownership, deadline, etc., on the server).
 */

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeftRight,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  Clock,
  Loader2,
  Plus,
  RotateCcw,
  Search,
  Trash2,
  XCircle,
} from "lucide-react";

import {
  api,
  type RosterLevel,
  type RosterPlayer,
  type Team,
  type TeamRoster,
  type TeamTradablePicks,
  type TradablePick,
  type TradeCpuEvaluation,
  type TradeEvaluation,
  type TradePlayer,
  type TradeRecord,
} from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { useConfirmDialog } from "@/lib/use-confirm";
import { usePersistedState } from "@/lib/use-persisted-state";
import { useTeams } from "@/lib/use-teams";
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
  { key: "reversed", label: "Reversed" },
  { key: "rejected", label: "Rejected" },
  { key: "vetoed", label: "Vetoed" },
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
  const [reverseTarget, setReverseTarget] = useState<string | null>(null);
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
  const teams = useTeams();

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
  const reverseMutation = useMutation({
    meta: { suppressToast: true },
    mutationFn: ({ id, note }: { id: string; note: string }) =>
      api.reverseTrade(id, note),
    onSuccess: () => {
      setActionError(null);
      refresh();
      toast.info("Trade reversed");
    },
    onError: (err) => {
      // The 409 blocker payload arrives as a JSON string in the message.
      const raw = err instanceof Error ? err.message : "Reverse failed.";
      let msg = raw;
      try {
        const parsed = JSON.parse(raw);
        if (parsed?.message) {
          msg = parsed.message;
          if (Array.isArray(parsed.blockers) && parsed.blockers.length) {
            msg += " " + parsed.blockers.join("; ");
          }
        }
      } catch {
        /* not JSON — use raw */
      }
      setActionError(msg);
    },
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
    reverse: (id: string) => {
      setReverseTarget(id);
    },
    pending:
      acceptMutation.isPending ||
      rejectMutation.isPending ||
      withdrawMutation.isPending ||
      adminApproveMutation.isPending ||
      adminVetoMutation.isPending ||
      reverseMutation.isPending,
  };

  // Stable ordered list of (status, rows) so the tab row doesn't reshuffle
  // when counts change. We also pull pending CPU offers into a dedicated
  // first tab so the owner can find their inbox without scrolling.
  const statusGroups = useMemo(() => {
    if (!trades.data)
      return [] as Array<{ key: string; label: string; rows: TradeRecord[] }>;
    const groups = trades.data.grouped ?? {};

    // Synthetic tab: every pending offer addressed to the user that needs
    // a response right now — CPU offers AND human owner-to-owner proposals.
    // These get top billing so an incoming trade never hides in the general
    // Pending list.
    const inbox = (groups["pending"] ?? []).filter(
      (t) => !!teamId && t.to_team === teamId,
    );

    const known: Array<{ key: string; label: string; rows: TradeRecord[] }> = [];
    if (teamId) {
      known.push({ key: "inbox", label: "Offers to you", rows: inbox });
    }
    for (const { key, label } of STATUS_ORDER) {
      let rows = groups[key] ?? [];
      // Don't double-list the inbox offers in the regular Pending tab —
      // they're already surfaced in "Offers to you".
      if (key === "pending" && inbox.length > 0) {
        const inboxIds = new Set(inbox.map((t) => t.trade_id));
        rows = rows.filter((t) => !inboxIds.has(t.trade_id));
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
      <ReverseDialog
        tradeId={reverseTarget}
        onOpenChange={(open) => !open && setReverseTarget(null)}
        onConfirm={(note) => {
          if (!reverseTarget) return;
          reverseMutation.mutate({ id: reverseTarget, note });
          setReverseTarget(null);
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

function ReverseDialog({
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
          <DialogTitle>Reverse trade</DialogTitle>
          <DialogDescription>
            Undo this committed trade, swapping the players and picks back to
            their original teams. Both owners are notified. Use this for a
            lopsided deal — it only works while the traded assets are still
            where the trade left them.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="reverse-note">Reason (shown to owners)</Label>
          <textarea
            id="reverse-note"
            className="h-24 w-full rounded-md border border-border bg-surface px-2 py-1 text-sm"
            placeholder="e.g. Clearly lopsided — reversing per league policy"
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
            Confirm reverse
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
  reverse: (id: string) => void;
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
  // Commissioner can undo a lopsided deal after it commits.
  const canReverse = status === "accepted" && actions.isAdmin;
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
      {status === "reversed" && (
        <div className="flex items-center gap-2 border-t border-border/60 bg-surfaceAlt/40 px-6 py-2 text-xs text-muted">
          <RotateCcw className="h-3 w-3" />
          <span>
            Reversed by the commissioner
            {trade.reversal?.note ? ` — ${trade.reversal.note}` : ""}
          </span>
        </div>
      )}
      {canReverse && (
        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border/60 bg-surfaceAlt/40 px-6 py-3">
          <span className="mr-auto text-[10px] uppercase tracking-wider text-amber">
            Admin
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => actions.reverse(trade.trade_id)}
            disabled={actions.pending}
            title="Undo this committed trade, swapping the assets back"
          >
            <RotateCcw className="h-3 w-3" /> Reverse
          </Button>
        </div>
      )}
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
  if (key === "inbox") return "amber";
  if (key === "pending" || key === "owner_accepted") return "amber";
  if (key === "accepted") return "success";
  if (key === "rejected" || key === "vetoed") return "danger";
  if (key === "reversed") return "neutral";
  return "neutral";
}

function iconFor(status: string) {
  const key = status.toLowerCase();
  if (key === "accepted") return CheckCircle2;
  if (key === "reversed") return RotateCcw;
  if (key === "rejected" || key === "vetoed") return XCircle;
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
  const [giveIds, setGiveIds] = useState<string[]>(defaultGivePlayers);
  const [receiveIds, setReceiveIds] = useState<string[]>(defaultReceivePlayers);
  const [givePickIds, setGivePickIds] = useState<string[]>([]);
  const [receivePickIds, setReceivePickIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Re-sync the local form state when the dialog re-opens with new defaults
  // (e.g. a "Trade for Player" deep-link), so a later open doesn't keep the
  // previous values.
  useEffect(() => {
    if (open) {
      setFromTeam(defaultFromTeam);
      setToTeam(defaultToTeam);
      setGiveIds(defaultGivePlayers);
      setReceiveIds(defaultReceivePlayers);
      setGivePickIds([]);
      setReceivePickIds([]);
      setError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    open,
    defaultFromTeam,
    defaultToTeam,
    defaultGivePlayers.join(","),
    defaultReceivePlayers.join(","),
  ]);

  // Each side's roster feeds a checklist of real players (name/pos/overall) —
  // owners never type raw ids.
  const fromRosterQ = useQuery({
    queryKey: ["team-roster", fromTeam, "trade"],
    queryFn: () => api.teamRoster(fromTeam),
    enabled: open && !!fromTeam,
    staleTime: 30_000,
  });
  const toRosterQ = useQuery({
    queryKey: ["team-roster", toTeam, "trade"],
    queryFn: () => api.teamRoster(toTeam),
    enabled: open && !!toTeam,
    staleTime: 30_000,
  });
  // Draft picks each team can trade, for the pick dropdowns.
  const fromPicksQ = useQuery({
    queryKey: ["team-picks", fromTeam],
    queryFn: () => api.teamTradablePicks(fromTeam),
    enabled: open && !!fromTeam,
    staleTime: 30_000,
  });
  const toPicksQ = useQuery({
    queryKey: ["team-picks", toTeam],
    queryFn: () => api.teamTradablePicks(toTeam),
    enabled: open && !!toTeam,
    staleTime: 30_000,
  });

  // Switching a team clears only that side's picks/players. We do this on the
  // explicit user action (not in a load effect) so a pre-loaded selection from
  // the "Trade for Player" deep-link is never wiped by load timing.
  const changeFromTeam = (value: string) => {
    setFromTeam(value);
    setGiveIds([]);
    setGivePickIds([]);
  };
  const changeToTeam = (value: string) => {
    setToTeam(value);
    setReceiveIds([]);
    setReceivePickIds([]);
  };

  // Debounce the offer so the live CPU-acceptance preview doesn't fire on every
  // single click/keystroke.
  const evalKey = JSON.stringify({
    fromTeam,
    toTeam,
    giveIds,
    receiveIds,
    givePickIds,
    receivePickIds,
  });
  const [debouncedKey, setDebouncedKey] = useState(evalKey);
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedKey(evalKey), 350);
    return () => clearTimeout(timer);
  }, [evalKey]);
  const evalQ = useQuery({
    queryKey: ["trade-eval", debouncedKey],
    queryFn: () =>
      api.evaluateTrade({
        from_team: fromTeam,
        to_team: toTeam,
        give_player_ids: giveIds,
        receive_player_ids: receiveIds,
        give_pick_ids: givePickIds,
        receive_pick_ids: receivePickIds,
      }),
    enabled: open && !!fromTeam && !!toTeam && fromTeam !== toTeam,
    staleTime: 5_000,
  });

  const mutation = useMutation({
    mutationFn: () =>
      api.proposeTrade({
        from_team: fromTeam,
        to_team: toTeam,
        give_player_ids: giveIds,
        receive_player_ids: receiveIds,
        give_pick_ids: givePickIds,
        receive_pick_ids: receivePickIds,
      }),
    onSuccess: () => {
      setError(null);
      onProposed();
      setGiveIds([]);
      setReceiveIds([]);
      setGivePickIds([]);
      setReceivePickIds([]);
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
    if (
      giveIds.length === 0 &&
      receiveIds.length === 0 &&
      givePickIds.length === 0 &&
      receivePickIds.length === 0
    ) {
      setError("Add at least one player or pick to the offer.");
      return;
    }
    mutation.mutate();
  }

  const toggle = (side: "give" | "receive", id: string) => {
    const setter = side === "give" ? setGiveIds : setReceiveIds;
    setter((cur) =>
      cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id],
    );
  };
  const togglePick = (side: "give" | "receive", id: string) => {
    const setter = side === "give" ? setGivePickIds : setReceivePickIds;
    setter((cur) =>
      cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id],
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Propose Trade</DialogTitle>
          <DialogDescription>
            Pick players from each roster. Offers to a CPU team show how likely
            they are to accept.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <TeamPicker
              label="From"
              value={fromTeam}
              teams={teams}
              exclude={toTeam}
              onChange={changeFromTeam}
            />
            <TeamPicker
              label="To"
              value={toTeam}
              teams={teams}
              exclude={fromTeam}
              onChange={changeToTeam}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <RosterMultiSelect
              label={`You give${fromTeam ? ` — ${fromTeam}` : ""}`}
              teamId={fromTeam}
              roster={fromRosterQ.data}
              loading={fromRosterQ.isLoading}
              selectedIds={giveIds}
              onToggle={(id) => toggle("give", id)}
            />
            <RosterMultiSelect
              label={`You receive${toTeam ? ` — ${toTeam}` : ""}`}
              teamId={toTeam}
              roster={toRosterQ.data}
              loading={toRosterQ.isLoading}
              selectedIds={receiveIds}
              onToggle={(id) => toggle("receive", id)}
            />
          </div>

          <AcceptanceMeter
            toTeam={toTeam}
            evaluation={evalQ.data}
            loading={evalQ.isFetching}
          />

          <div className="grid grid-cols-2 gap-4">
            <PickMultiSelect
              label="Give picks (optional)"
              teamId={fromTeam}
              data={fromPicksQ.data}
              loading={fromPicksQ.isLoading}
              selectedIds={givePickIds}
              onToggle={(id) => togglePick("give", id)}
            />
            <PickMultiSelect
              label="Receive picks (optional)"
              teamId={toTeam}
              data={toPicksQ.data}
              loading={toPicksQ.isLoading}
              selectedIds={receivePickIds}
              onToggle={(id) => togglePick("receive", id)}
            />
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

// Levels whose players can be included in a trade (whole org, injured included).
const TRADE_LEVELS: RosterLevel[] = ["ACT", "AAA", "LOW", "DL", "IR"];

function flattenRoster(roster: TeamRoster): RosterPlayer[] {
  return TRADE_LEVELS.flatMap((lvl) => roster.levels[lvl] ?? []);
}

/** Searchable, multi-select checklist of a team's players for a trade side. */
function RosterMultiSelect({
  label,
  teamId,
  roster,
  loading,
  selectedIds,
  onToggle,
}: {
  label: string;
  teamId: string;
  roster?: TeamRoster;
  loading: boolean;
  selectedIds: string[];
  onToggle: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const players = roster ? flattenRoster(roster) : [];
  const needle = query.trim().toLowerCase();
  const selectedSet = new Set(selectedIds);
  const matched = needle
    ? players.filter((p) =>
        `${p.first_name} ${p.last_name} ${p.primary_position}`
          .toLowerCase()
          .includes(needle),
      )
    : players;
  // Selected players float to the top so a pre-loaded pick is immediately
  // visible without scrolling; order is otherwise stable.
  const filtered = [...matched].sort((a, b) => {
    const sa = selectedSet.has(a.player_id) ? 0 : 1;
    const sb = selectedSet.has(b.player_id) ? 0 : 1;
    return sa - sb;
  });

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
          {label}
        </span>
        {selectedIds.length > 0 && (
          <span className="text-[11px] font-semibold text-amber">
            {selectedIds.length} selected
          </span>
        )}
      </div>
      {!teamId ? (
        <div className="rounded-lg border border-border bg-canvas/40 px-3 py-6 text-center text-xs text-muted">
          Pick a team first.
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-canvas/40">
          <div className="border-b border-border/60 p-1.5">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search players…"
                className="h-8 w-full rounded-md border border-border bg-surface pl-7 pr-2 text-xs text-ink focus:border-amber focus:outline-none"
              />
            </div>
          </div>
          <div className="max-h-52 overflow-y-auto p-1">
            {loading ? (
              <div className="flex items-center justify-center gap-2 py-6 text-xs text-muted">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading roster…
              </div>
            ) : filtered.length === 0 ? (
              <div className="py-6 text-center text-xs text-muted">
                {players.length === 0 ? "No players." : "No matches."}
              </div>
            ) : (
              filtered.map((p) => {
                const sel = selectedSet.has(p.player_id);
                return (
                  <button
                    type="button"
                    key={p.player_id}
                    onClick={() => onToggle(p.player_id)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs",
                      sel
                        ? "bg-amber/15 text-ink"
                        : "text-ink/90 hover:bg-surfaceAlt/60",
                    )}
                  >
                    <input
                      type="checkbox"
                      readOnly
                      checked={sel}
                      className="pointer-events-none h-3.5 w-3.5 accent-amber"
                    />
                    <span className="w-9 shrink-0 font-medium text-muted">
                      {p.primary_position}
                    </span>
                    <span className="flex-1 truncate">
                      {p.first_name} {p.last_name}
                    </span>
                    {p.overall_stars_text && (
                      <span className="shrink-0 text-amber">
                        ★{p.overall_stars_text}
                      </span>
                    )}
                    {typeof p.age === "number" && (
                      <span className="w-8 shrink-0 text-right text-muted">
                        {p.age}y
                      </span>
                    )}
                    {p.injured && (
                      <Badge tone="warning" className="shrink-0">
                        {p.level === "DL" || p.level === "IR" ? p.level : "INJ"}
                      </Badge>
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** Dropdown that lets an owner pick multiple of a team's tradable draft picks. */
function PickMultiSelect({
  label,
  teamId,
  data,
  loading,
  selectedIds,
  onToggle,
}: {
  label: string;
  teamId: string;
  data?: TeamTradablePicks;
  loading: boolean;
  selectedIds: string[];
  onToggle: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const picks: TradablePick[] = data?.picks ?? [];
  const enabled = data?.enabled ?? true;
  const selectedSet = new Set(selectedIds);
  const selectedLabels = picks
    .filter((p) => selectedSet.has(p.pick_id))
    .map((p) => p.label);
  const disabled = !teamId || !enabled || (!loading && picks.length === 0);

  const summary = !teamId
    ? "Pick a team first"
    : loading
      ? "Loading picks…"
      : !enabled
        ? "Pick trading is off"
        : picks.length === 0
          ? "No tradable picks"
          : selectedLabels.length === 0
            ? "None selected"
            : selectedLabels.length <= 2
              ? selectedLabels.join(", ")
              : `${selectedLabels.length} picks selected`;

  return (
    <div className="space-y-1.5" ref={ref}>
      <Label>{label}</Label>
      <div className="relative">
        <button
          type="button"
          disabled={disabled}
          onClick={() => setOpen((o) => !o)}
          className={cn(
            "flex h-10 w-full items-center justify-between gap-2 rounded-lg border border-border bg-canvas/60 px-3 text-sm focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40",
            disabled ? "cursor-not-allowed text-muted" : "text-ink",
          )}
        >
          <span className="truncate">{summary}</span>
          <ChevronDown className="h-4 w-4 shrink-0 text-muted" />
        </button>
        {open && picks.length > 0 && (
          <div className="absolute z-20 mt-1 max-h-52 w-full overflow-y-auto rounded-lg border border-border bg-surface p-1 shadow-lg">
            {picks.map((p) => {
              const sel = selectedSet.has(p.pick_id);
              return (
                <button
                  type="button"
                  key={p.pick_id}
                  onClick={() => onToggle(p.pick_id)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs",
                    sel
                      ? "bg-amber/15 text-ink"
                      : "text-ink/90 hover:bg-surfaceAlt/60",
                  )}
                >
                  <input
                    type="checkbox"
                    readOnly
                    checked={sel}
                    className="pointer-events-none h-3.5 w-3.5 accent-amber"
                  />
                  <span className="flex-1 truncate">{p.label}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

const BAND_COLOR: Record<string, string> = {
  red: "#ef4444",
  orange: "#f97316",
  yellow: "#eab308",
  green: "#22c55e",
};

function acceptanceLabel(ev: TradeEvaluation): string {
  if (ev.will_counter) return "Likely to reject as-is — but may counter";
  const pct = ev.likelihood ?? 0;
  if (ev.predicted_action === "accept") {
    return pct >= 80 ? "Very likely to accept" : "Likely to accept";
  }
  return pct >= 20 ? "Unlikely to accept" : "Very unlikely to accept";
}

/** Red→orange→yellow→green bar showing how likely a CPU team is to accept. */
function AcceptanceMeter({
  toTeam,
  evaluation,
  loading,
}: {
  toTeam: string;
  evaluation?: TradeEvaluation;
  loading: boolean;
}) {
  if (!toTeam) return null;
  if (!evaluation) {
    return loading ? (
      <div className="flex items-center gap-2 rounded-lg border border-border bg-canvas/40 px-3 py-2 text-xs text-muted">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Sizing up the deal…
      </div>
    ) : null;
  }
  if (!evaluation.is_cpu) {
    return (
      <div className="rounded-lg border border-border bg-canvas/40 px-3 py-2 text-xs text-muted">
        {toTeam} is owner-controlled — they’ll review your offer in their inbox.
      </div>
    );
  }
  if (evaluation.empty || typeof evaluation.likelihood !== "number") {
    return (
      <div className="rounded-lg border border-border bg-canvas/40 px-3 py-2 text-xs text-muted">
        Add players to see how likely {toTeam} is to accept.
      </div>
    );
  }
  const pct = Math.max(0, Math.min(100, evaluation.likelihood));
  const color = BAND_COLOR[evaluation.band ?? "red"] ?? BAND_COLOR.red;
  return (
    <div className="space-y-1.5 rounded-lg border border-border bg-canvas/40 px-3 py-2.5">
      <div className="flex items-center justify-between text-xs">
        <span className="font-semibold text-ink">
          Chance {toTeam} accepts
        </span>
        <span className="font-semibold" style={{ color }}>
          {pct}%{loading ? " …" : ""}
        </span>
      </div>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-surfaceAlt">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <div className="text-xs font-medium" style={{ color }}>
        {acceptanceLabel(evaluation)}
      </div>
      {evaluation.reasons && evaluation.reasons.length > 0 && (
        <ul className="space-y-0.5 pt-0.5 text-[11px] text-muted">
          {evaluation.reasons.slice(0, 3).map((r, i) => (
            <li key={i}>• {r}</li>
          ))}
        </ul>
      )}
    </div>
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
