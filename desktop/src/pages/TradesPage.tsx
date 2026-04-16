/**
 * Phase 4 port of ui/trade_dialog.py.
 *
 * Renders every trade in ``data/trades_pending.csv`` grouped by status with
 * inline Accept / Reject / Withdraw actions on pending offers, plus a
 * "Propose Trade" dialog that POSTs through utils.trade_utils.save_trade
 * (validates pick ownership, deadline, etc., on the server).
 */

import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Loader2,
  Plus,
  Trash2,
  XCircle,
} from "lucide-react";

import { api, type Team, type TradePlayer, type TradeRecord } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
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

export function TradesPage() {
  const user = useAuthStore();
  const queryClient = useQueryClient();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;
  const [scope, setScope] = useState<Scope>(teamId ? "team" : "all");
  const [proposing, setProposing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const effectiveScope: Scope = teamId ? scope : "all";

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

  const acceptMutation = useMutation({
    mutationFn: (id: string) => api.acceptTrade(id),
    onSuccess: () => {
      setActionError(null);
      refresh();
    },
    onError: (err) =>
      setActionError(err instanceof Error ? err.message : "Accept failed."),
  });
  const rejectMutation = useMutation({
    mutationFn: (id: string) => api.rejectTrade(id),
    onSuccess: () => {
      setActionError(null);
      refresh();
    },
    onError: (err) =>
      setActionError(err instanceof Error ? err.message : "Reject failed."),
  });
  const withdrawMutation = useMutation({
    mutationFn: (id: string) => api.withdrawTrade(id),
    onSuccess: () => {
      setActionError(null);
      refresh();
    },
    onError: (err) =>
      setActionError(err instanceof Error ? err.message : "Withdraw failed."),
  });

  const actions = {
    teamId,
    accept: (id: string) => acceptMutation.mutate(id),
    reject: (id: string) => rejectMutation.mutate(id),
    withdraw: (id: string) => {
      if (window.confirm("Withdraw this pending trade?")) {
        withdrawMutation.mutate(id);
      }
    },
    pending:
      acceptMutation.isPending ||
      rejectMutation.isPending ||
      withdrawMutation.isPending,
  };

  // Stable ordered list of (status, rows) so the tab row doesn't reshuffle
  // when counts change.
  const statusGroups = useMemo(() => {
    if (!trades.data) return [] as Array<{ key: string; label: string; rows: TradeRecord[] }>;
    const groups = trades.data.grouped ?? {};
    const known = STATUS_ORDER.map(({ key, label }) => ({
      key,
      label,
      rows: groups[key] ?? [],
    }));
    // Append any unknown statuses the data happens to have.
    const unknown = Object.keys(groups).filter(
      (k) => !STATUS_ORDER.some((s) => s.key === k),
    );
    for (const key of unknown) {
      known.push({ key, label: key, rows: groups[key] ?? [] });
    }
    return known;
  }, [trades.data]);

  const firstWithRows =
    statusGroups.find((g) => g.rows.length > 0)?.key ??
    statusGroups[0]?.key ??
    "pending";

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
          <Button onClick={() => setProposing(true)}>
            <Plus className="h-4 w-4" /> Propose Trade
          </Button>
        </div>
      </div>

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
        <Tabs defaultValue={firstWithRows}>
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

      <ProposeTradeDialog
        open={proposing}
        onOpenChange={setProposing}
        defaultFromTeam={teamId ?? ""}
        teams={teams.data ?? []}
        onProposed={refresh}
      />
    </AppShell>
  );
}

interface RowActions {
  teamId: string | null;
  accept: (id: string) => void;
  reject: (id: string) => void;
  withdraw: (id: string) => void;
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
        <StatusBadge status={trade.status} />
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
      {(canRespond || canWithdraw) && (
        <div className="flex items-center justify-end gap-2 border-t border-border/60 bg-surfaceAlt/40 px-6 py-3">
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
              <Button
                size="sm"
                onClick={() => actions.accept(trade.trade_id)}
                disabled={actions.pending}
              >
                <CheckCircle2 className="h-3 w-3" /> Accept
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
  teams,
  onProposed,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultFromTeam: string;
  teams: Team[];
  onProposed: () => void;
}) {
  const [fromTeam, setFromTeam] = useState(defaultFromTeam);
  const [toTeam, setToTeam] = useState("");
  const [givePlayers, setGivePlayers] = useState("");
  const [receivePlayers, setReceivePlayers] = useState("");
  const [givePicks, setGivePicks] = useState("");
  const [receivePicks, setReceivePicks] = useState("");
  const [error, setError] = useState<string | null>(null);

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
            <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
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
