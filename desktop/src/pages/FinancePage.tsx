/**
 * Phase 4 port of ui/owner_finance_page.py.
 *
 * Top stat cards summarize cash, debt, and projected monthly net. Below,
 * two columns break down revenue and expenses (actual vs projected), and a
 * transactions table shows the most recent ledger entries.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  CreditCard,
  DollarSign,
  Gavel,
  Loader2,
  Pencil,
  PiggyBank,
  Receipt,
  TrendingDown,
  TrendingUp,
  Wallet,
  X,
} from "lucide-react";

import {
  api,
  type ArbitrationPlayer,
  type FinanceSnapshot,
  type FinanceTransaction,
  type PayrollOutlook,
} from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { formatMoneyCompact } from "@/lib/format";
import { useActiveTeamColor } from "@/lib/team-colors";
import { useTeams } from "@/lib/use-teams";
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
  Input,
} from "@/components/ui";

export function FinancePage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;

  const teams = useTeams({ enabled: !teamId });
  const fallbackTeamId = teamId ?? teams.data?.[0]?.team_id ?? null;
  const teamAccentColor = useActiveTeamColor(fallbackTeamId ?? undefined);

  const snapshot = useQuery({
    queryKey: ["finance-snapshot", fallbackTeamId],
    queryFn: () => api.financeSnapshot(fallbackTeamId as string),
    enabled: !!fallbackTeamId,
  });
  const transactions = useQuery({
    queryKey: ["finance-transactions", fallbackTeamId],
    queryFn: () => api.financeTransactions(fallbackTeamId as string),
    enabled: !!fallbackTeamId,
  });
  const payrollContext = useQuery({
    queryKey: ["payroll-context", fallbackTeamId],
    queryFn: () => api.payrollContext(fallbackTeamId as string),
    enabled: !!fallbackTeamId,
  });
  const arbitrationOn =
    (snapshot.data?.modules?.gm_arbitration ?? "off") !== "off";
  const arbitration = useQuery({
    queryKey: ["arbitration", fallbackTeamId],
    queryFn: () => api.teamArbitration(fallbackTeamId as string),
    enabled: !!fallbackTeamId && arbitrationOn,
  });

  if (!fallbackTeamId) {
    return (
      <AppShell title="Finance">
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            {teams.isLoading ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin text-amber" />
                <span className="text-sm text-muted">Loading teams…</span>
              </>
            ) : (
              <>
                <AlertTriangle className="h-5 w-5 text-warning" />
                <span className="text-sm">No team available.</span>
              </>
            )}
          </CardContent>
        </Card>
      </AppShell>
    );
  }

  return (
    <AppShell
      title="Finance"
      subtitle={
        snapshot.data
          ? `${fallbackTeamId} · ${snapshot.data.preset}${snapshot.data.financials_enabled ? "" : " (disabled)"}`
          : `Team ${fallbackTeamId}`
      }
      teamAccentColor={teamAccentColor}
    >
      {snapshot.isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <Loader2 className="h-5 w-5 animate-spin text-amber" />
            <span className="text-sm text-muted">Loading finance…</span>
          </CardContent>
        </Card>
      ) : snapshot.isError ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-danger">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm">
              {(snapshot.error as Error).message}
            </span>
          </CardContent>
        </Card>
      ) : snapshot.data ? (
        <div className="space-y-6 animate-fade-in">
          <HeadlineStats snapshot={snapshot.data} />
          {payrollContext.data?.active ? (
            <PayrollHeadroomCard outlook={payrollContext.data} />
          ) : null}
          <PayrollAlertCard snapshot={snapshot.data} />
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <BreakdownCard
              title="Revenue"
              description="Monthly actual vs projection"
              tone="success"
              actual={snapshot.data.revenue_totals}
              projected={snapshot.data.projected_revenue}
            />
            <BreakdownCard
              title="Expenses"
              description="Monthly actual vs projection"
              tone="danger"
              actual={snapshot.data.expense_totals}
              projected={snapshot.data.projected_expenses}
            />
          </div>
          <BudgetCard
            teamId={fallbackTeamId}
            actual={snapshot.data.budgets}
            projected={snapshot.data.projected_budgets}
            editable={
              !!snapshot.data.financials_enabled &&
              (snapshot.data.modules?.owner_budgets ?? "off") !== "off"
            }
          />
          {arbitrationOn ? (
            <ArbitrationCard
              teamId={fallbackTeamId}
              isLoading={arbitration.isLoading}
              players={arbitration.data?.players ?? []}
            />
          ) : null}
          <TransactionsCard
            isLoading={transactions.isLoading}
            isError={transactions.isError}
            error={transactions.error}
            transactions={transactions.data?.transactions ?? []}
          />
        </div>
      ) : null}
    </AppShell>
  );
}

function HeadlineStats({ snapshot }: { snapshot: FinanceSnapshot }) {
  const net = snapshot.projected_net;
  return (
    <section className="grid grid-cols-1 gap-4 md:grid-cols-4">
      <StatCard
        label="Cash on Hand"
        value={formatMoney(snapshot.cash_on_hand)}
        Icon={Wallet}
        tone={snapshot.cash_on_hand < 0 ? "danger" : "amber"}
      />
      <StatCard
        label="Debt"
        value={formatMoney(snapshot.debt)}
        Icon={CreditCard}
        tone={snapshot.debt > 0 ? "danger" : "success"}
      />
      <StatCard
        label="Projected Monthly Net"
        value={formatMoney(net)}
        sub={net >= 0 ? "Net gain" : "Net loss"}
        Icon={net >= 0 ? TrendingUp : TrendingDown}
        tone={net >= 0 ? "success" : "danger"}
      />
      <StatCard
        label="Preset"
        value={snapshot.preset || "—"}
        sub={snapshot.financials_enabled ? "Enabled" : "Disabled"}
        Icon={PiggyBank}
      />
    </section>
  );
}

interface BreakdownProps {
  title: string;
  description: string;
  tone: "success" | "danger";
  actual: Record<string, number>;
  projected: Record<string, number>;
}

function BreakdownCard({
  title,
  description,
  tone,
  actual,
  projected,
}: BreakdownProps) {
  const rows = useMemo(() => {
    // Union of keys so we don't drop categories that are only in one side.
    const keys = Array.from(
      new Set([...Object.keys(actual), ...Object.keys(projected)]),
    );
    keys.sort();
    return keys.map((key) => ({
      key,
      actual: actual[key] ?? 0,
      projected: projected[key] ?? 0,
    }));
  }, [actual, projected]);

  const actualTotal = sumValues(actual);
  const projectedTotal = sumValues(projected);

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
        <Badge tone={tone === "success" ? "success" : "danger"}>
          <Receipt className="h-3 w-3" /> {rows.length} categories
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
              <th className="px-6 py-2 text-left font-semibold">Category</th>
              <th className="px-3 py-2 text-right font-semibold">Actual</th>
              <th className="px-6 py-2 text-right font-semibold">Projected</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.key}
                className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
              >
                <td className="px-6 py-2 capitalize">{row.key.replace(/_/g, " ")}</td>
                <td
                  className={cn(
                    "px-3 py-2 text-right tabular-nums",
                    tone === "success" ? "text-success" : "text-danger",
                  )}
                >
                  {formatMoney(row.actual)}
                </td>
                <td className="px-6 py-2 text-right tabular-nums text-muted">
                  {formatMoney(row.projected)}
                </td>
              </tr>
            ))}
            <tr className="border-t border-border/60 font-semibold">
              <td className="px-6 py-2">Total</td>
              <td
                className={cn(
                  "px-3 py-2 text-right tabular-nums",
                  tone === "success" ? "text-success" : "text-danger",
                )}
              >
                {formatMoney(actualTotal)}
              </td>
              <td className="px-6 py-2 text-right tabular-nums">
                {formatMoney(projectedTotal)}
              </td>
            </tr>
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function BudgetCard({
  teamId,
  actual,
  projected,
  editable,
}: {
  teamId: string;
  actual: Record<string, number>;
  projected: Record<string, number>;
  editable: boolean;
}) {
  const queryClient = useQueryClient();
  const keys = useMemo(() => {
    const all = Array.from(
      new Set([...Object.keys(actual), ...Object.keys(projected)]),
    );
    all.sort();
    return all;
  }, [actual, projected]);

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});

  const save = useMutation({
    mutationFn: () => {
      const budgets: Record<string, number> = {};
      for (const k of keys) {
        const n = Number(draft[k]);
        budgets[k] = Number.isFinite(n) && n > 0 ? Math.round(n) : 0;
      }
      return api.updateTeamBudgets(teamId, budgets);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["finance-snapshot", teamId] });
      setEditing(false);
    },
  });

  if (keys.length === 0) return null;

  const startEdit = () => {
    const d: Record<string, string> = {};
    for (const k of keys) d[k] = String(actual[k] ?? 0);
    setDraft(d);
    save.reset();
    setEditing(true);
  };

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Budgets</CardTitle>
          <CardDescription>
            {editable
              ? "Set your allocation per category — projected is your revenue-based ceiling"
              : "Allocated vs projected based on revenue"}
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone="amber">
            <DollarSign className="h-3 w-3" /> {keys.length}
          </Badge>
          {editable && !editing ? (
            <Button size="sm" variant="secondary" onClick={startEdit}>
              <Pencil className="h-3.5 w-3.5" /> Edit
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent>
        {save.isError ? (
          <div className="mb-3 flex items-center gap-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            {(save.error as Error)?.message ?? "Failed to save budgets."}
          </div>
        ) : null}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          {keys.map((key) => {
            const a = actual[key] ?? 0;
            const p = projected[key] ?? 0;
            const ratio = p > 0 ? Math.min(1, a / p) : 0;
            return (
              <div
                key={key}
                className="rounded-xl border border-border bg-surfaceAlt/40 p-3"
              >
                <div className="flex items-baseline justify-between">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted capitalize">
                    {key.replace(/_/g, " ")}
                  </div>
                  {editing ? null : (
                    <div className="font-display text-lg font-bold text-amber-text">
                      {formatMoney(a)}
                    </div>
                  )}
                </div>
                {editing ? (
                  <Input
                    type="number"
                    min={0}
                    className="mt-2"
                    value={draft[key] ?? ""}
                    onChange={(e) =>
                      setDraft((d) => ({ ...d, [key]: e.target.value }))
                    }
                  />
                ) : (
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-canvas">
                    <div
                      className="h-full bg-amber transition-[width]"
                      style={{ width: `${ratio * 100}%` }}
                    />
                  </div>
                )}
                <div className="mt-1 text-[11px] text-muted">
                  of {formatMoney(p)} projected
                </div>
              </div>
            );
          })}
        </div>
        {editing ? (
          <div className="mt-4 flex items-center justify-end gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setEditing(false)}
              disabled={save.isPending}
            >
              <X className="h-3.5 w-3.5" /> Cancel
            </Button>
            <Button
              size="sm"
              onClick={() => save.mutate()}
              disabled={save.isPending}
            >
              {save.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Check className="h-3.5 w-3.5" />
              )}
              Save budgets
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ArbitrationCard({
  teamId,
  isLoading,
  players,
}: {
  teamId: string;
  isLoading: boolean;
  players: ArbitrationPlayer[];
}) {
  const queryClient = useQueryClient();
  const submit = useMutation({
    mutationFn: (vars: {
      playerId: string;
      action: "offer_raise" | "hold" | "non_tender";
      projected?: number;
    }) =>
      api.submitArbitrationDecision(teamId, vars.playerId, vars.action, vars.projected),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["arbitration", teamId] }),
  });

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Arbitration</CardTitle>
          <CardDescription>
            Decide each arbitration-eligible player: offer the raise, hold, or non-tender
          </CardDescription>
        </div>
        <Badge tone="amber">
          <Gavel className="h-3 w-3" /> {players.length}
        </Badge>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : players.length === 0 ? (
          <div className="py-6 text-sm text-muted">
            No arbitration-eligible players right now. Players become arb-eligible
            after roughly three seasons of service.
          </div>
        ) : (
          <div className="space-y-2">
            {players.map((p) => {
              const decided = p.queued_action;
              return (
                <div
                  key={p.player_id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-surfaceAlt/40 p-3"
                >
                  <div>
                    <div className="font-semibold">
                      {p.player_name || p.player_id}
                    </div>
                    <div className="text-[11px] text-muted">
                      {formatMoney(p.current_salary)} → proj{" "}
                      {formatMoney(p.projected_salary)} · rec:{" "}
                      {(p.recommended_action || "").replace(/_/g, " ")}
                    </div>
                  </div>
                  {decided ? (
                    <Badge tone="neutral">
                      decided: {String(decided).replace(/_/g, " ")}
                      {p.queued_status ? ` (${p.queued_status})` : ""}
                    </Badge>
                  ) : (
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={submit.isPending}
                        onClick={() =>
                          submit.mutate({
                            playerId: p.player_id,
                            action: "offer_raise",
                            projected: p.projected_salary,
                          })
                        }
                      >
                        Offer raise
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={submit.isPending}
                        onClick={() =>
                          submit.mutate({ playerId: p.player_id, action: "hold" })
                        }
                      >
                        Hold
                      </Button>
                      <Button
                        size="sm"
                        variant="danger"
                        disabled={submit.isPending}
                        onClick={() =>
                          submit.mutate({
                            playerId: p.player_id,
                            action: "non_tender",
                          })
                        }
                      >
                        Non-tender
                      </Button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
        {submit.isError ? (
          <div className="mt-3 text-xs text-danger">
            {(submit.error as Error)?.message ?? "Failed to save decision."}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function TransactionsCard({
  isLoading,
  isError,
  error,
  transactions,
}: {
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  transactions: FinanceTransaction[];
}) {
  const columns = useMemo(() => {
    if (transactions.length === 0) return [];
    // Pick a stable column order using the first row, preferring common
    // ledger fields when present.
    const preferred = ["date", "category", "description", "amount", "balance"];
    const keys = new Set<string>();
    for (const tx of transactions) {
      for (const k of Object.keys(tx)) keys.add(k);
    }
    const ordered: string[] = [];
    for (const p of preferred) if (keys.has(p)) ordered.push(p);
    for (const k of keys) if (!ordered.includes(k)) ordered.push(k);
    return ordered;
  }, [transactions]);

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Recent Transactions</CardTitle>
          <CardDescription>Latest ledger entries</CardDescription>
        </div>
        <Badge tone="neutral">{transactions.length}</Badge>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading ? (
          <div className="flex items-center gap-2 px-6 py-8 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : isError ? (
          <div className="px-6 py-6 text-sm text-danger">
            {(error as Error)?.message ?? "Request failed."}
          </div>
        ) : transactions.length === 0 ? (
          <div className="px-6 py-6 text-sm text-muted">
            No transactions recorded.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
                  {columns.map((col) => (
                    <th
                      key={col}
                      className={cn(
                        "px-3 py-2 font-semibold",
                        col === "amount" || col === "balance"
                          ? "text-right"
                          : "text-left",
                      )}
                    >
                      {col.replace(/_/g, " ")}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {transactions.map((tx, i) => (
                  <tr
                    key={i}
                    className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
                  >
                    {columns.map((col) => (
                      <TxCell key={col} col={col} value={tx[col] ?? null} />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function TxCell({
  col,
  value,
}: {
  col: string;
  value: FinanceTransaction[string];
}) {
  const isMoney = col === "amount" || col === "balance";
  const n = typeof value === "number" ? value : Number(value);
  if (isMoney && Number.isFinite(n)) {
    return (
      <td
        className={cn(
          "px-3 py-2 text-right tabular-nums",
          n > 0 ? "text-success" : n < 0 ? "text-danger" : "text-muted",
        )}
      >
        {formatMoney(n)}
      </td>
    );
  }
  return (
    <td className="px-3 py-2">
      {value == null || value === "" ? (
        <span className="text-subtle">—</span>
      ) : (
        String(value)
      )}
    </td>
  );
}

/**
 * The "am I over the luxury threshold?" card. Renders a floor→payroll→
 * threshold meter plus plain-language consequences (est. tax / floor fee,
 * Opening Day solvency) using the same numbers settlement charges.
 * Hidden entirely when payroll rules are off (`outlook.active === false`).
 */
function PayrollHeadroomCard({ outlook }: { outlook: PayrollOutlook }) {
  const payroll = outlook.payroll ?? 0;
  const threshold = outlook.threshold ?? 0;
  const floor = outlook.floor ?? 0;
  const zone = outlook.zone ?? "safe";
  const headroom = outlook.headroom ?? 0;
  const overBy = outlook.over_threshold ?? 0;
  const underBy = outlook.under_floor ?? 0;
  const tax = outlook.estimated_tax ?? 0;
  const floorFee = outlook.estimated_floor_fee ?? 0;
  const solvent = outlook.opening_day_solvent ?? true;
  const debt = outlook.debt ?? 0;
  const debtCap = outlook.debt_cap ?? 0;

  // Scale the meter so the threshold marker sits at ~78% width, leaving
  // visible "taxed" territory to its right even when payroll is safe.
  const scale = Math.max(threshold / 0.78, payroll * 1.05, 1);
  const pct = (v: number) => `${Math.min(100, (v / scale) * 100)}%`;

  const zoneBadge =
    zone === "over_threshold" ? (
      <Badge tone="danger">Over threshold</Badge>
    ) : zone === "under_floor" ? (
      <Badge tone="warning">Under floor</Badge>
    ) : (
      <Badge tone="success">Safe zone</Badge>
    );

  return (
    <Card>
      <CardHeader className="pb-3">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <DollarSign className="h-4 w-4 text-amber" /> Payroll vs Luxury
            Threshold
          </CardTitle>
          <CardDescription>
            Going over isn&apos;t blocked in-season — it&apos;s taxed at
            settlement. Opening Day only requires solvency (debt within the
            cap).
          </CardDescription>
        </div>
        {zoneBadge}
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Meter */}
        <div>
          <div className="relative h-3 overflow-hidden rounded-full bg-canvas">
            {/* Taxed territory beyond the threshold */}
            <div
              className="absolute inset-y-0 right-0 bg-danger/15"
              style={{ left: pct(threshold) }}
            />
            {/* Payroll fill */}
            <div
              className={cn(
                "absolute inset-y-0 left-0 rounded-full transition-[width]",
                zone === "over_threshold"
                  ? "bg-danger"
                  : zone === "under_floor"
                    ? "bg-warning"
                    : "bg-success",
              )}
              style={{ width: pct(payroll) }}
            />
            {/* Floor + threshold markers */}
            {floor > 0 ? (
              <div
                className="absolute inset-y-0 w-0.5 bg-warning"
                style={{ left: pct(floor) }}
                title={`Payroll floor: ${formatMoneyCompact(floor)}`}
              />
            ) : null}
            <div
              className="absolute inset-y-0 w-0.5 bg-danger"
              style={{ left: pct(threshold) }}
              title={`Luxury threshold: ${formatMoneyCompact(threshold)}`}
            />
          </div>
          <div className="mt-1.5 flex justify-between text-[11px] text-muted">
            <span>
              Payroll{" "}
              <span className="font-semibold text-ink">
                {formatMoneyCompact(payroll)}
              </span>
            </span>
            {floor > 0 ? (
              <span>
                Floor{" "}
                <span className="font-semibold text-warning">
                  {formatMoneyCompact(floor)}
                </span>
              </span>
            ) : null}
            <span>
              Threshold{" "}
              <span className="font-semibold text-danger">
                {formatMoneyCompact(threshold)}
              </span>
            </span>
          </div>
        </div>

        {/* Plain-language consequences */}
        <div className="grid grid-cols-1 gap-2 text-sm md:grid-cols-2">
          <div className="rounded-md border border-border bg-surfaceAlt/40 p-2.5">
            {zone === "over_threshold" ? (
              <span>
                <span className="font-semibold text-danger">
                  {formatMoneyCompact(overBy)} over
                </span>{" "}
                the threshold — est.{" "}
                <span className="font-semibold text-danger">
                  {formatMoneyCompact(tax)}
                </span>{" "}
                {outlook.level === "mlb_like" ? "luxury tax" : "overage fee"} at
                settlement.
              </span>
            ) : zone === "under_floor" ? (
              <span>
                <span className="font-semibold text-warning">
                  {formatMoneyCompact(underBy)} under
                </span>{" "}
                the payroll floor — est.{" "}
                <span className="font-semibold text-warning">
                  {formatMoneyCompact(floorFee)}
                </span>{" "}
                shortfall fee at settlement.
              </span>
            ) : (
              <span>
                <span className="font-semibold text-success">
                  {formatMoneyCompact(headroom)}
                </span>{" "}
                of headroom before the luxury tax kicks in.
              </span>
            )}
          </div>
          <div
            className={cn(
              "rounded-md border p-2.5",
              solvent
                ? "border-border bg-surfaceAlt/40"
                : "border-danger/40 bg-danger/10",
            )}
          >
            {solvent ? (
              <span>
                <span className="font-semibold text-success">✓ Solvent</span>{" "}
                for Opening Day — debt {formatMoneyCompact(debt)} of a{" "}
                {formatMoneyCompact(debtCap)} cap.
              </span>
            ) : (
              <span className="text-danger">
                <span className="font-semibold">✗ Opening Day risk</span> —
                projected debt {formatMoneyCompact(outlook.projected_debt ?? 0)}{" "}
                exceeds the {formatMoneyCompact(debtCap)} cap. The season
                can&apos;t start until this is resolved.
              </span>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function formatMoney(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const sign = value < 0 ? "-" : "";
  return `${sign}$${Math.abs(Math.round(value)).toLocaleString()}`;
}

function sumValues(map: Record<string, number>): number {
  let total = 0;
  for (const v of Object.values(map)) total += v || 0;
  return total;
}

/**
 * Proactive payroll alerts. Reads the snapshot and surfaces warnings
 * when any of these hit:
 *   - Cash on hand is negative or approaching zero (< $1M runway vs
 *     projected net).
 *   - Debt is high relative to projected revenue.
 *   - Projected monthly net is negative for two categories combined.
 *
 * The ports payroll-policy-messaging gap from the parity audit — PyQt
 * ran these checks during roster / free-agency moves; here we keep them
 * front-and-center on the Finance page instead of waiting for stability
 * sim to catch them.
 */
function PayrollAlertCard({ snapshot }: { snapshot: FinanceSnapshot }) {
  const alerts: Array<{ tone: "danger" | "warning"; text: string }> = [];
  if (snapshot.cash_on_hand < 0) {
    alerts.push({
      tone: "danger",
      text: `Cash on hand is negative (${formatMoney(snapshot.cash_on_hand)}). Any new commitment risks breaking the ledger.`,
    });
  } else if (
    snapshot.projected_net < 0 &&
    snapshot.cash_on_hand + snapshot.projected_net * 3 < 0
  ) {
    alerts.push({
      tone: "warning",
      text: `At the current monthly burn (${formatMoney(snapshot.projected_net)}), cash runs out in under 3 months. Cut expenses or renegotiate contracts.`,
    });
  }
  if (snapshot.debt > 0) {
    const revenue = sumValues(snapshot.projected_revenue);
    if (revenue > 0 && snapshot.debt > revenue * 12) {
      alerts.push({
        tone: "warning",
        text: `Debt (${formatMoney(snapshot.debt)}) exceeds a year of projected revenue. Consider debt service before new signings.`,
      });
    }
  }
  if (snapshot.projected_net < 0) {
    alerts.push({
      tone: "warning",
      text: `Projected monthly net is negative (${formatMoney(snapshot.projected_net)}). Review budgets below.`,
    });
  }
  if (!snapshot.financials_enabled) {
    alerts.push({
      tone: "warning",
      text: "Financial simulation is disabled for this league. Budgets and cash numbers won't drift with play.",
    });
  }
  if (alerts.length === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <AlertTriangle className="h-4 w-4 text-warning" /> Payroll alerts
        </CardTitle>
        <CardDescription>
          Proactive warnings surfaced from the current snapshot. Act before
          these become blockers in Finance Stability.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {alerts.map((a, i) => (
          <div
            key={i}
            className={cn(
              "flex items-start gap-2 rounded-md border p-2",
              a.tone === "danger"
                ? "border-danger/40 bg-danger/10 text-danger"
                : "border-warning/40 bg-warning/10 text-warning",
            )}
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{a.text}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
