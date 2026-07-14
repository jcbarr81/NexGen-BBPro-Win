/**
 * Phase 4 port of ui/gm_finance_queue_dialog.py.
 *
 * Admin-only review surface for owner-submitted GM queue decisions
 * (arbitration + free agency). Approve / reject rows individually, then
 * "Apply Approved" to commit them through services.gm_finance_queue.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  ListChecks,
  Loader2,
  PlayCircle,
  RefreshCw,
  XCircle,
} from "lucide-react";

import { api, type FinanceQueueRow } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { formatMoneyCompact } from "@/lib/format";
import { useConfirmDialog } from "@/lib/use-confirm";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";

const TYPES: Array<{ key: string; label: string }> = [
  { key: "", label: "All" },
  { key: "arbitration", label: "Arbitration" },
  { key: "free_agency", label: "Free Agency" },
];

export function FinanceQueuePage() {
  const role = useAuthStore((s) => s.role);
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("");

  const queue = useQuery({
    queryKey: ["finance-queue", filter],
    queryFn: () => api.financeQueue(filter || undefined),
    enabled: role === "admin",
  });

  const review = useMutation({
    mutationFn: (payload: {
      team_id: string;
      queue_type: string;
      item_id: string;
      review_status: string;
    }) => api.reviewFinanceQueue(payload),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["finance-queue"] }),
  });
  const apply = useMutation({
    mutationFn: () => api.applyFinanceQueue(),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["finance-queue"] }),
  });
  const { confirm, dialog: confirmDialog } = useConfirmDialog();

  // "Apply approved" is irreversible (writes contracts/rosters), so show
  // exactly what will be committed before pulling the trigger.
  async function confirmAndApply() {
    const rows = queue.data?.rows ?? [];
    const approved = rows.filter(
      (r) => r.review_status === "approved_commissioner",
    );
    const ok = await confirm({
      title: `Apply ${approved.length} approved decision${approved.length === 1 ? "" : "s"}?`,
      description:
        approved.length === 0 ? (
          <span>
            No decisions are approved yet — applying will commit nothing.
            Approve rows first, then apply.
          </span>
        ) : (
          <div className="space-y-1 text-left">
            <p>This writes contracts and rosters and can&apos;t be undone:</p>
            <ul className="max-h-48 list-disc space-y-0.5 overflow-y-auto pl-5">
              {approved.map((r, i) => (
                <li key={i}>
                  <span className="font-semibold">
                    {r.player_name || r.item_id}
                  </span>{" "}
                  ({r.team_id}) — {r.action_label || r.action}
                  {r.projected_salary != null && r.current_salary != null
                    ? ` (${formatMoneyCompact(r.current_salary)} → ${formatMoneyCompact(r.projected_salary)})`
                    : ""}
                </li>
              ))}
            </ul>
          </div>
        ),
      confirmLabel: "Apply",
      danger: true,
    });
    if (ok) apply.mutate();
  }

  const grouped = useMemo(() => {
    const rows = queue.data?.rows ?? [];
    const map = new Map<string, typeof rows>();
    for (const row of rows) {
      const team = String(row.team_id ?? "—");
      const arr = map.get(team) ?? [];
      arr.push(row);
      map.set(team, arr);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [queue.data]);

  if (role !== "admin") return <Navigate to="/home" replace />;

  return (
    <AppShell
      title="Finance Queue"
      subtitle="Pending arbitration + free-agency decisions awaiting commissioner review"
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
          {TYPES.map((t) => (
            <button
              key={t.key || "all"}
              type="button"
              onClick={() => setFilter(t.key)}
              className={cn(
                "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
                filter === t.key
                  ? "bg-amber text-espresso"
                  : "text-muted hover:bg-surface hover:text-ink",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {queue.data && (
            <span className="text-xs text-muted">{queue.data.count} pending</span>
          )}
          <Button
            variant="ghost"
            size="icon"
            aria-label="Refresh"
            onClick={() => queue.refetch()}
          >
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button
            onClick={() => void confirmAndApply()}
            disabled={apply.isPending || (queue.data?.count ?? 0) === 0}
          >
            {apply.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <PlayCircle className="h-4 w-4" />
            )}
            Apply approved
          </Button>
        </div>
      </div>
      {confirmDialog}

      {apply.isError && (
        <div className="mb-4 flex items-center gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          <AlertTriangle className="h-4 w-4" />
          {(apply.error as Error).message}
        </div>
      )}

      {queue.isLoading ? (
        <LoadingCard />
      ) : queue.isError ? (
        <ErrorCard message={(queue.error as Error).message} />
      ) : grouped.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <ListChecks className="h-10 w-10 text-amber" />
            <h2 className="font-display text-xl">Queue is clear</h2>
            <p className="max-w-sm text-sm text-muted">
              No owner decisions waiting for commissioner review.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {grouped.map(([teamId, rows]) => (
            <Card key={teamId}>
              <CardHeader>
                <div>
                  <CardTitle>{teamId}</CardTitle>
                  <CardDescription>
                    {rows.length} decision{rows.length === 1 ? "" : "s"}
                  </CardDescription>
                </div>
                <Badge tone="amber">{rows.length}</Badge>
              </CardHeader>
              <CardContent className="p-0">
                <div className="overflow-x-auto"><table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
                      <th className="px-6 py-2 text-left font-semibold">Queue</th>
                      <th className="px-3 py-2 text-left font-semibold">Player</th>
                      <th className="px-3 py-2 text-left font-semibold">Decision</th>
                      <th className="px-3 py-2 text-left font-semibold">Status</th>
                      <th className="px-6 py-2 text-right font-semibold">Review</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, i) => {
                      const itemId = String(row.item_id ?? "");
                      const queueType = String(row.queue_type ?? "");
                      return (
                        <tr
                          key={`${itemId}-${i}`}
                          className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
                        >
                          <td className="px-6 py-2 text-xs uppercase tracking-wider text-muted">
                            {queueType.replace(/_/g, " ")}
                          </td>
                          <td className="px-3 py-2">
                            <Link
                              to={`/player/${encodeURIComponent(itemId)}`}
                              className="font-semibold hover:text-amber"
                            >
                              {row.player_name || itemId}
                            </Link>
                            {row.player_name && (
                              <span className="ml-1.5 font-mono text-[10px] text-subtle">
                                {itemId}
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2">
                            <div>{row.action_label || String(row.action ?? "")}</div>
                            {row.current_salary != null &&
                              row.projected_salary != null && (
                                <div className="text-[11px] tabular-nums text-muted">
                                  {formatMoneyCompact(row.current_salary)} →{" "}
                                  {formatMoneyCompact(row.projected_salary)}
                                </div>
                              )}
                          </td>
                          <td className="px-3 py-2">
                            <StatusBadge status={String(row.review_status ?? "pending")} />
                          </td>
                          <td className="px-6 py-2 text-right">
                            <div className="inline-flex items-center gap-1">
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={review.isPending}
                                onClick={() =>
                                  review.mutate({
                                    team_id: teamId,
                                    queue_type: queueType,
                                    item_id: itemId,
                                    review_status: "approved_commissioner",
                                  })
                                }
                              >
                                <CheckCircle2 className="h-3 w-3 text-success" />
                                Approve
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={review.isPending}
                                onClick={() =>
                                  review.mutate({
                                    team_id: teamId,
                                    queue_type: queueType,
                                    item_id: itemId,
                                    review_status: "rejected_commissioner",
                                  })
                                }
                              >
                                <XCircle className="h-3 w-3 text-danger" />
                                Reject
                              </Button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table></div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </AppShell>
  );
}

function StatusBadge({ status }: { status: string }) {
  const label = status.replace(/_commissioner$/, "").replace(/_/g, " ");
  const tone = status.startsWith("approved")
    ? ("success" as const)
    : status.startsWith("rejected")
      ? ("danger" as const)
      : ("amber" as const);
  return <Badge tone={tone}>{label || "pending"}</Badge>;
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading queue…</span>
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
