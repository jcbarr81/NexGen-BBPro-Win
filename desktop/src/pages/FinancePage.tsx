/**
 * Phase 4 port of ui/owner_finance_page.py.
 *
 * Top stat cards summarize cash, debt, and projected monthly net. Below,
 * two columns break down revenue and expenses (actual vs projected), and a
 * transactions table shows the most recent ledger entries.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CreditCard,
  DollarSign,
  Loader2,
  PiggyBank,
  Receipt,
  TrendingDown,
  TrendingUp,
  Wallet,
} from "lucide-react";

import {
  api,
  type FinanceSnapshot,
  type FinanceTransaction,
} from "@/lib/api";
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
} from "@/components/ui";

export function FinancePage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;

  const teams = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
    enabled: !teamId,
  });
  const fallbackTeamId = teamId ?? teams.data?.[0]?.team_id ?? null;

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
            actual={snapshot.data.budgets}
            projected={snapshot.data.projected_budgets}
          />
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
  actual,
  projected,
}: {
  actual: Record<string, number>;
  projected: Record<string, number>;
}) {
  const keys = useMemo(() => {
    const all = Array.from(
      new Set([...Object.keys(actual), ...Object.keys(projected)]),
    );
    all.sort();
    return all;
  }, [actual, projected]);

  if (keys.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Budgets</CardTitle>
          <CardDescription>
            Allocated vs projected based on revenue
          </CardDescription>
        </div>
        <Badge tone="amber">
          <DollarSign className="h-3 w-3" /> {keys.length}
        </Badge>
      </CardHeader>
      <CardContent>
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
                  <div className="font-display text-lg font-bold text-amber-text">
                    {formatMoney(a)}
                  </div>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-canvas">
                  <div
                    className="h-full bg-amber transition-[width]"
                    style={{ width: `${ratio * 100}%` }}
                  />
                </div>
                <div className="mt-1 text-[11px] text-muted">
                  of {formatMoney(p)} projected
                </div>
              </div>
            );
          })}
        </div>
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
                      <TxCell key={col} col={col} value={tx[col]} />
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
