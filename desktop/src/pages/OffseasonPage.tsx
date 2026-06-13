/**
 * Port of ui/offseason_finance_dialog.py — the admin-facing offseason
 * finance workflow with checklist + per-stage review tabs (contract
 * expirations, arbitration details, budget deltas, GM finance queue with
 * filtering and inline approve/reject actions).
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  ExternalLink,
  Loader2,
  Play,
  Settings2,
  Snowflake,
  Users,
  Wallet,
} from "lucide-react";

import { api } from "@/lib/api";
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
  Input,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";

interface ChecklistStage {
  id: string;
  label: string;
  description: string;
  done: boolean;
  done_at: string | null;
}

export function OffseasonPage() {
  return (
    <AppShell
      title="Offseason Flow"
      subtitle="Admin: end-of-season finance rollover checklist"
    >
      <OffseasonFlowBody />
    </AppShell>
  );
}

function OffseasonFlowBody() {
  const queryClient = useQueryClient();

  const checklist = useQuery({
    queryKey: ["offseason-checklist"],
    queryFn: () => api.offseasonChecklist(),
  });
  const overview = useQuery({
    queryKey: ["offseason-overview"],
    queryFn: () => api.offseasonOverview(),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["offseason-checklist"] });
    queryClient.invalidateQueries({ queryKey: ["offseason-overview"] });
    queryClient.invalidateQueries({ queryKey: ["offseason-details"] });
  };

  const runMut = useMutation({
    mutationFn: () => api.offseasonRun(),
    onSuccess: invalidate,
  });
  const markMut = useMutation({
    mutationFn: (stageId: string) => api.offseasonMark(stageId),
    onSuccess: invalidate,
  });

  if (checklist.isLoading || overview.isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-10">
          <Loader2 className="h-5 w-5 animate-spin text-amber" />
          <span className="text-sm text-muted">Loading checklist…</span>
        </CardContent>
      </Card>
    );
  }

  if (checklist.isError || !checklist.data) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-10">
          <AlertTriangle className="h-5 w-5 text-warning" />
          <span className="text-sm">
            {(checklist.error as Error)?.message || "Failed to load checklist."}
          </span>
        </CardContent>
      </Card>
    );
  }

  const stages = (checklist.data.stages ?? []) as ChecklistStage[];
  const currentStageId = checklist.data.current_stage ?? null;
  const allDone = !!checklist.data.all_done;
  const ov = (overview.data ?? {}) as Record<string, unknown>;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Snowflake className="h-4 w-4 text-amber" /> Offseason Status
          </CardTitle>
          <CardDescription>
            Year {String(ov.ended_season_year ?? "—")} → {String(ov.next_season_year ?? "—")} ·
            preset {String(ov.preset ?? "—")} · phase {String(ov.phase ?? "—")}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
          <Metric label="Contracts" value={String(ov.contracts_total ?? 0)} />
          <Metric label="Expiring" value={String(ov.contracts_expiring ?? 0)} />
          <Metric
            label="Arb candidates"
            value={String(ov.arbitration_candidates ?? 0)}
          />
          <Metric label="Unsigned" value={String(ov.unsigned_players ?? 0)} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2 flex flex-row items-start justify-between">
          <div>
            <CardTitle className="text-base">Checklist</CardTitle>
            <CardDescription>
              Run the pipeline to execute all stages, or mark individual
              stages complete as you handle them manually.
            </CardDescription>
          </div>
          <Button
            onClick={() => runMut.mutate()}
            disabled={runMut.isPending || allDone}
            size="sm"
          >
            {runMut.isPending ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Play className="mr-1 h-4 w-4" />
            )}
            Run pipeline
          </Button>
        </CardHeader>
        <CardContent className="space-y-2">
          {stages.map((stage) => {
            const isCurrent = stage.id === currentStageId && !stage.done;
            return (
              <div
                key={stage.id}
                className="flex items-start gap-3 rounded-md border border-border bg-surface p-3"
              >
                <div className="mt-0.5">
                  {stage.done ? (
                    <CheckCircle2 className="h-5 w-5 text-success" />
                  ) : (
                    <Circle
                      className={
                        isCurrent ? "h-5 w-5 text-amber" : "h-5 w-5 text-muted"
                      }
                    />
                  )}
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    {stage.label}
                    {isCurrent && <Badge>Current</Badge>}
                  </div>
                  <div className="mt-0.5 text-xs text-muted">
                    {stage.description}
                  </div>
                  {stage.done && stage.done_at && (
                    <div className="mt-0.5 text-[10px] text-muted">
                      Completed {stage.done_at}
                    </div>
                  )}
                </div>
                {!stage.done && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => markMut.mutate(stage.id)}
                    disabled={markMut.isPending || !isCurrent}
                  >
                    Mark done
                  </Button>
                )}
              </div>
            );
          })}
          {stages.length === 0 && (
            <div className="py-4 text-center text-xs text-muted">
              No checklist stages available.
            </div>
          )}
        </CardContent>
      </Card>

      {(runMut.isError || markMut.isError) && (
        <Card>
          <CardContent className="flex items-center gap-3 py-3">
            <AlertTriangle className="h-5 w-5 text-warning" />
            <span className="text-sm">
              {(runMut.error as Error)?.message ||
                (markMut.error as Error)?.message ||
                "Operation failed."}
            </span>
          </CardContent>
        </Card>
      )}

      <ReviewTabsCard />
      <FinanceQueueInline />
      <QuickLinksCard />
    </div>
  );
}

function QuickLinksCard() {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Related workflows</CardTitle>
        <CardDescription>
          Jump to the workflows the PyQt offseason dialog launched inline.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-2 md:grid-cols-3">
        <Link
          to="/free-agency"
          className="flex items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm hover:border-amber/60"
        >
          <span className="inline-flex items-center gap-2">
            <Users className="h-4 w-4 text-amber" /> Free Agency Hub
          </span>
          <ExternalLink className="h-3 w-3 text-muted" />
        </Link>
        <Link
          to="/finance-queue"
          className="flex items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm hover:border-amber/60"
        >
          <span className="inline-flex items-center gap-2">
            <Wallet className="h-4 w-4 text-amber" /> Finance Queue
          </span>
          <ExternalLink className="h-3 w-3 text-muted" />
        </Link>
        <Link
          to="/commissioner"
          className="flex items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm hover:border-amber/60"
        >
          <span className="inline-flex items-center gap-2">
            <Settings2 className="h-4 w-4 text-amber" /> Commissioner Settings
          </span>
          <ExternalLink className="h-3 w-3 text-muted" />
        </Link>
      </CardContent>
    </Card>
  );
}

/**
 * Inline preview of the GM finance queue. Pulls the same data as the
 * standalone Finance Queue page but keeps the offseason admin focused in
 * one place. Deep-links to the full page for inline review/apply.
 */
function FinanceQueueInline() {
  const { confirm, dialog: confirmDialog } = useConfirmDialog();
  const queue = useQuery({
    queryKey: ["finance-queue", "all"],
    queryFn: () => api.financeQueue(),
  });
  const apply = useMutation({
    mutationFn: () => api.applyFinanceQueue(),
  });
  const rows = (queue.data?.rows ?? []) as Array<Record<string, unknown>>;
  const pending = rows.filter(
    (r) => String(r.review_status ?? "").toLowerCase() === "pending",
  );
  return (
    <Card>
      <CardHeader className="pb-2 flex flex-row items-start justify-between">
        <div>
          <CardTitle className="text-base">Finance Queue</CardTitle>
          <CardDescription>
            Pending GM decisions (contracts, arbitration). Head to the full
            Finance Queue page to approve individual rows; use Apply below to
            run every approved row in one pass.
          </CardDescription>
        </div>
        <Badge tone={pending.length ? "warning" : "success"}>
          {pending.length} pending · {rows.length} total
        </Badge>
      </CardHeader>
      <CardContent className="flex items-center gap-2">
        <Button
          size="sm"
          onClick={async () => {
            if (
              await confirm({
                title: "Apply approved rows?",
                description:
                  "Commits every approved row in the finance queue in one pass.",
                confirmLabel: "Apply",
              })
            ) {
              apply.mutate();
            }
          }}
          disabled={apply.isPending}
        >
          {apply.isPending ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin" />
          ) : (
            <Play className="mr-1 h-4 w-4" />
          )}
          Apply approved
        </Button>
        <a
          href="#/finance-queue"
          className="text-xs text-amber underline-offset-2 hover:underline"
        >
          Open full queue →
        </a>
        {apply.isSuccess && (
          <span className="text-xs text-success">Applied.</span>
        )}
        {apply.isError && (
          <span className="text-xs text-danger">
            {(apply.error as Error)?.message ?? "Apply failed."}
          </span>
        )}
      </CardContent>
      {confirmDialog}
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-surface p-2">
      <div className="text-[10px] uppercase tracking-wide text-muted">
        {label}
      </div>
      <div className="mt-0.5 text-sm font-semibold">{value}</div>
    </div>
  );
}

function fmtCurrency(value: unknown): string {
  const num = Number(value);
  if (!Number.isFinite(num)) return "$0";
  const sign = num < 0 ? "-" : "";
  return `${sign}$${Math.abs(Math.round(num)).toLocaleString()}`;
}

/**
 * Per-stage review tabs the PyQt offseason dialog rendered: contract
 * expirations about to roll over, arbitration awards, year-over-year
 * budget deltas, and the GM finance queue with team/queue/status filters
 * + inline approve/reject for pending rows.
 */
function ReviewTabsCard() {
  const details = useQuery({
    queryKey: ["offseason-details"],
    queryFn: () => api.offseasonDetails(),
  });

  if (details.isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-6">
          <Loader2 className="h-4 w-4 animate-spin text-amber" />
          <span className="text-sm text-muted">Loading review details…</span>
        </CardContent>
      </Card>
    );
  }
  if (details.isError || !details.data) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-6">
          <AlertTriangle className="h-5 w-5 text-warning" />
          <span className="text-sm">
            {(details.error as Error)?.message ||
              "Failed to load review details."}
          </span>
        </CardContent>
      </Card>
    );
  }

  const data = details.data;
  const contracts = data.contract_expirations ?? [];
  const arbitration = data.arbitration_details ?? [];
  const budgets = data.budget_deltas ?? [];
  const gmQueue = data.gm_finance_queue ?? [];

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Review</CardTitle>
        <CardDescription>
          Per-stage review rows the PyQt offseason dialog showed in tabs.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="contracts">
          <TabsList>
            <TabsTrigger value="contracts">
              Contracts ({contracts.length})
            </TabsTrigger>
            <TabsTrigger value="arbitration">
              Arbitration ({arbitration.length})
            </TabsTrigger>
            <TabsTrigger value="budgets">
              Budgets ({budgets.length})
            </TabsTrigger>
            <TabsTrigger value="gm-queue">
              GM Queue ({gmQueue.length})
            </TabsTrigger>
          </TabsList>

          <TabsContent value="contracts">
            <ContractExpirationsTable rows={contracts} />
          </TabsContent>
          <TabsContent value="arbitration">
            <ArbitrationTable rows={arbitration} />
          </TabsContent>
          <TabsContent value="budgets">
            <BudgetDeltasTable rows={budgets} />
          </TabsContent>
          <TabsContent value="gm-queue">
            <GmQueueTable rows={gmQueue} />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

function ContractExpirationsTable({
  rows,
}: {
  rows: Array<Record<string, unknown>>;
}) {
  if (rows.length === 0) {
    return (
      <p className="py-6 text-center text-xs text-muted">
        No contracts are expiring this offseason.
      </p>
    );
  }
  return (
    <div className="max-h-80 overflow-y-auto rounded-md border border-border bg-canvas/30">
      <div className="overflow-x-auto"><table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border/60 text-[10px] uppercase tracking-wider text-muted">
            <th className="px-3 py-2 text-left">Player</th>
            <th className="px-3 py-2 text-left">Team</th>
            <th className="px-3 py-2 text-right">Years left</th>
            <th className="px-3 py-2 text-right">Salary</th>
            <th className="px-3 py-2 text-right">Service days</th>
            <th className="px-3 py-2 text-left">Arb eligible</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr
              key={`${String(row.player_id ?? idx)}`}
              className="border-b border-border/30 last:border-b-0 hover:bg-surfaceAlt/30"
            >
              <td className="px-3 py-1.5">
                {String(row.player_name ?? row.player_id ?? "")}
              </td>
              <td className="px-3 py-1.5">{String(row.team_id ?? "")}</td>
              <td className="px-3 py-1.5 text-right">
                {String(row.years_left ?? 0)}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {fmtCurrency(row.annual_salary)}
              </td>
              <td className="px-3 py-1.5 text-right">
                {String(row.service_time_days ?? 0)}
              </td>
              <td className="px-3 py-1.5">
                {row.arb_eligible ? "Yes" : "No"}
              </td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </div>
  );
}

function ArbitrationTable({
  rows,
}: {
  rows: Array<Record<string, unknown>>;
}) {
  if (rows.length === 0) {
    return (
      <p className="py-6 text-center text-xs text-muted">
        No arbitration awards recorded for the most recent offseason.
      </p>
    );
  }
  return (
    <div className="max-h-80 overflow-y-auto rounded-md border border-border bg-canvas/30">
      <div className="overflow-x-auto"><table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border/60 text-[10px] uppercase tracking-wider text-muted">
            <th className="px-3 py-2 text-left">Player</th>
            <th className="px-3 py-2 text-left">Team</th>
            <th className="px-3 py-2 text-right">Old salary</th>
            <th className="px-3 py-2 text-right">New salary</th>
            <th className="px-3 py-2 text-right">Delta</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr
              key={`${String(row.player_id ?? idx)}`}
              className="border-b border-border/30 last:border-b-0 hover:bg-surfaceAlt/30"
            >
              <td className="px-3 py-1.5">
                {String(row.player_name ?? row.player_id ?? "")}
              </td>
              <td className="px-3 py-1.5">{String(row.team_id ?? "")}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {fmtCurrency(row.old_salary)}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {fmtCurrency(row.new_salary)}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {fmtCurrency(row.delta)}
              </td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </div>
  );
}

function BudgetDeltasTable({
  rows,
}: {
  rows: Array<Record<string, unknown>>;
}) {
  if (rows.length === 0) {
    return (
      <p className="py-6 text-center text-xs text-muted">
        No budget deltas recorded for this offseason transition.
      </p>
    );
  }
  return (
    <div className="max-h-80 overflow-y-auto rounded-md border border-border bg-canvas/30">
      <div className="overflow-x-auto"><table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border/60 text-[10px] uppercase tracking-wider text-muted">
            <th className="px-3 py-2 text-left">Team</th>
            <th className="px-3 py-2 text-right">Prev total</th>
            <th className="px-3 py-2 text-right">Curr total</th>
            <th className="px-3 py-2 text-right">Δ Total</th>
            <th className="px-3 py-2 text-right">Δ Training</th>
            <th className="px-3 py-2 text-right">Δ Scouting</th>
            <th className="px-3 py-2 text-right">Δ Development</th>
            <th className="px-3 py-2 text-right">Δ Facilities</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr
              key={`${String(row.team_id ?? idx)}`}
              className="border-b border-border/30 last:border-b-0 hover:bg-surfaceAlt/30"
            >
              <td className="px-3 py-1.5 font-semibold">
                {String(row.team_id ?? "")}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {fmtCurrency(row.previous_total)}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {fmtCurrency(row.current_total)}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {fmtCurrency(row.delta)}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {fmtCurrency(row.training_delta)}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {fmtCurrency(row.scouting_delta)}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {fmtCurrency(row.development_delta)}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {fmtCurrency(row.facilities_delta)}
              </td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </div>
  );
}

const STATUS_FILTER_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "All statuses" },
  { value: "pending_commissioner", label: "Pending review" },
  { value: "approved_unapplied", label: "Approved (not applied)" },
  { value: "approved_applied", label: "Approved (applied)" },
  { value: "approved_any", label: "Approved (any)" },
  { value: "rejected_commissioner", label: "Rejected" },
];

const QUEUE_FILTER_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "All queues" },
  { value: "arbitration", label: "Arbitration" },
  { value: "free_agency", label: "Free agency" },
];

function GmQueueTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  const queryClient = useQueryClient();
  const [teamFilter, setTeamFilter] = useState("");
  const [queueFilter, setQueueFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");

  const review = useMutation({
    mutationFn: (payload: {
      team_id: string;
      queue_type: string;
      item_id: string;
      review_status: string;
      notes?: string;
    }) => api.reviewFinanceQueue(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["offseason-details"] });
      queryClient.invalidateQueries({ queryKey: ["finance-queue", "all"] });
      queryClient.invalidateQueries({ queryKey: ["offseason-overview"] });
    },
  });

  const teams = useMemo(() => {
    const set = new Set<string>();
    for (const row of rows) {
      const id = String(row.team_id ?? "").trim();
      if (id) set.add(id);
    }
    return Array.from(set).sort();
  }, [rows]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((row) => {
      if (teamFilter && String(row.team_id ?? "") !== teamFilter) return false;
      if (queueFilter && String(row.queue_type ?? "") !== queueFilter)
        return false;
      const status = String(row.review_status ?? "").toLowerCase();
      const applied = !!row.applied;
      if (statusFilter === "approved_unapplied") {
        if (
          (status !== "approved_local" && status !== "approved_commissioner") ||
          applied
        )
          return false;
      } else if (statusFilter === "approved_applied") {
        if (
          (status !== "approved_local" && status !== "approved_commissioner") ||
          !applied
        )
          return false;
      } else if (statusFilter === "approved_any") {
        if (status !== "approved_local" && status !== "approved_commissioner")
          return false;
      } else if (statusFilter && status !== statusFilter) {
        return false;
      }
      if (q) {
        const hay = [
          row.team_id,
          row.queue_type,
          row.item_id,
          row.action,
          row.review_status,
          row.notes,
        ]
          .map((v) => String(v ?? "").toLowerCase())
          .join(" ");
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [rows, teamFilter, queueFilter, statusFilter, search]);

  function clearFilters() {
    setTeamFilter("");
    setQueueFilter("");
    setStatusFilter("");
    setSearch("");
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-2 md:grid-cols-[160px_160px_200px_minmax(0,1fr)_auto]">
        <select
          value={teamFilter}
          onChange={(e) => setTeamFilter(e.target.value)}
          className="h-8 rounded-md border border-border bg-canvas/60 px-2 text-xs text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
        >
          <option value="">All teams</option>
          {teams.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select
          value={queueFilter}
          onChange={(e) => setQueueFilter(e.target.value)}
          className="h-8 rounded-md border border-border bg-canvas/60 px-2 text-xs text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
        >
          {QUEUE_FILTER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="h-8 rounded-md border border-border bg-canvas/60 px-2 text-xs text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
        >
          {STATUS_FILTER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search team / item / action / notes…"
          className="h-8"
        />
        <Button variant="outline" size="sm" onClick={clearFilters}>
          Clear
        </Button>
      </div>

      {review.isError && (
        <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
          {(review.error as Error).message}
        </div>
      )}

      {filtered.length === 0 ? (
        <p className="py-6 text-center text-xs text-muted">
          No rows match the current filters.
        </p>
      ) : (
        <div className="max-h-80 overflow-y-auto rounded-md border border-border bg-canvas/30">
          <div className="overflow-x-auto"><table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border/60 text-[10px] uppercase tracking-wider text-muted">
                <th className="px-3 py-2 text-left">Team</th>
                <th className="px-3 py-2 text-left">Queue</th>
                <th className="px-3 py-2 text-left">Item</th>
                <th className="px-3 py-2 text-left">Action</th>
                <th className="px-3 py-2 text-left">Status</th>
                <th className="px-3 py-2 text-left">Applied</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row, idx) => {
                const status = String(row.review_status ?? "").toLowerCase();
                const isPending = status === "pending_commissioner";
                const teamId = String(row.team_id ?? "");
                const queueType = String(row.queue_type ?? "");
                const itemId = String(row.item_id ?? "");
                return (
                  <tr
                    key={`${teamId}-${queueType}-${itemId}-${idx}`}
                    className="border-b border-border/30 last:border-b-0 hover:bg-surfaceAlt/30"
                  >
                    <td className="px-3 py-1.5">{teamId}</td>
                    <td className="px-3 py-1.5">{queueType}</td>
                    <td className="px-3 py-1.5">{itemId}</td>
                    <td className="px-3 py-1.5">{String(row.action ?? "")}</td>
                    <td className="px-3 py-1.5">{String(row.review_status ?? "")}</td>
                    <td className="px-3 py-1.5">
                      {row.applied ? "Yes" : "No"}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={!isPending || review.isPending}
                          onClick={() =>
                            review.mutate({
                              team_id: teamId,
                              queue_type: queueType,
                              item_id: itemId,
                              review_status: "approved_commissioner",
                              notes: "Approved from offseason workflow",
                            })
                          }
                        >
                          Approve
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={!isPending || review.isPending}
                          onClick={() =>
                            review.mutate({
                              team_id: teamId,
                              queue_type: queueType,
                              item_id: itemId,
                              review_status: "rejected_commissioner",
                              notes: "Rejected from offseason workflow",
                            })
                          }
                        >
                          Reject
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table></div>
        </div>
      )}
    </div>
  );
}
