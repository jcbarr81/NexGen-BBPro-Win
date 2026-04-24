/**
 * Port of ui/offseason_flow_dialog.py — the admin-facing offseason
 * finance rollover checklist. Walks the commissioner through contract
 * rollover, arbitration, free agency, and snapshot generation stages.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  Loader2,
  Play,
  Snowflake,
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

      <FinanceQueueInline />
    </div>
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
