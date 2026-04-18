/**
 * Port of the finance-stability scenario tester (services/finance_stability.py).
 *
 * Admin-facing harness that runs the multi-season finance cycle against
 * a temp copy of the data tree, then reports guardrail pass/fail and the
 * per-season metrics. Useful before applying a new preset on a live league.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  LineChart,
  Play,
  XCircle,
} from "lucide-react";

import { api } from "@/lib/api";
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

const PRESETS = [
  { id: "simple", label: "Simple" },
  { id: "standard", label: "Standard" },
  { id: "mlb_like", label: "MLB-like" },
];

export function FinanceStabilityPage() {
  return (
    <AppShell
      title="Finance Stability"
      subtitle="Admin: multi-season guardrail scenario tester"
    >
      <FinanceStabilityBody />
    </AppShell>
  );
}

function FinanceStabilityBody() {
  const [seasons, setSeasons] = useState(3);
  const [seed, setSeed] = useState("");
  const [preset, setPreset] = useState("standard");
  const [comparePresets, setComparePresets] = useState<string[]>([
    "simple",
    "standard",
    "mlb_like",
  ]);

  const runMut = useMutation({
    mutationFn: () =>
      api.financeStabilityRun({
        seasons,
        seed: seed ? Number(seed) : undefined,
        preset,
      }),
  });
  const compareMut = useMutation({
    mutationFn: () =>
      api.financeStabilityCompare({
        seasons,
        seed: seed ? Number(seed) : undefined,
        presets: comparePresets,
      }),
  });

  function togglePreset(id: string) {
    setComparePresets((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id],
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <LineChart className="h-4 w-4 text-amber" /> Scenario inputs
          </CardTitle>
          <CardDescription>
            Runs in an isolated sandbox — your live league is not modified.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-4">
          <label className="flex flex-col gap-1 text-xs">
            <span className="uppercase tracking-wide text-muted">Seasons</span>
            <input
              type="number"
              min={1}
              max={20}
              value={seasons}
              onChange={(e) => setSeasons(Math.max(1, Number(e.target.value) || 1))}
              className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="uppercase tracking-wide text-muted">Seed (optional)</span>
            <input
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              placeholder="e.g. 42"
              className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs md:col-span-2">
            <span className="uppercase tracking-wide text-muted">Preset</span>
            <select
              value={preset}
              onChange={(e) => setPreset(e.target.value)}
              className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
            >
              {PRESETS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
        </CardContent>
        <CardContent className="flex flex-wrap items-center gap-2 pt-0">
          <Button
            onClick={() => runMut.mutate()}
            disabled={runMut.isPending}
            size="sm"
          >
            {runMut.isPending ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Play className="mr-1 h-4 w-4" />
            )}
            Run single preset
          </Button>
          <div className="ml-4 flex items-center gap-2 text-xs text-muted">
            Compare:
            {PRESETS.map((p) => (
              <label key={p.id} className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={comparePresets.includes(p.id)}
                  onChange={() => togglePreset(p.id)}
                />
                {p.label}
              </label>
            ))}
          </div>
          <Button
            onClick={() => compareMut.mutate()}
            disabled={compareMut.isPending || comparePresets.length === 0}
            size="sm"
            variant="secondary"
          >
            {compareMut.isPending ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Play className="mr-1 h-4 w-4" />
            )}
            Compare presets
          </Button>
        </CardContent>
      </Card>

      {runMut.isError && <ErrorCard message={(runMut.error as Error).message} />}
      {compareMut.isError && (
        <ErrorCard message={(compareMut.error as Error).message} />
      )}

      {runMut.data && <SingleResultCard result={runMut.data} />}
      {compareMut.data && <CompareResultCard result={compareMut.data} />}
    </div>
  );
}

function ErrorCard({ message }: { message: string }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-2 py-3 text-sm">
        <AlertTriangle className="h-4 w-4 text-warning" />
        {message || "Run failed."}
      </CardContent>
    </Card>
  );
}

function SingleResultCard({ result }: { result: Record<string, unknown> }) {
  const guardrails = (result.guardrails ?? {}) as Record<string, unknown>;
  const passed = !!guardrails.passed;
  const metrics = (result.season_metrics ?? []) as Array<Record<string, unknown>>;
  return (
    <Card>
      <CardHeader className="pb-2 flex flex-row items-center justify-between">
        <div>
          <CardTitle className="text-base">
            {String(result.preset ?? "—")} · {String(result.seasons_run ?? 0)} seasons
          </CardTitle>
          <CardDescription>
            Start year {String(result.start_year ?? "—")} · league {String(result.league_id ?? "—")}
          </CardDescription>
        </div>
        <Badge tone={passed ? "success" : "danger"}>
          {passed ? (
            <span className="flex items-center gap-1">
              <CheckCircle2 className="h-3 w-3" /> Guardrails pass
            </span>
          ) : (
            <span className="flex items-center gap-1">
              <XCircle className="h-3 w-3" /> Guardrails fail
            </span>
          )}
        </Badge>
      </CardHeader>
      <CardContent>
        <MetricsTable rows={metrics} />
        {Array.isArray(guardrails.failures) && (guardrails.failures as unknown[]).length > 0 && (
          <div className="mt-3 space-y-1 text-xs">
            <div className="uppercase tracking-wide text-muted">Failures</div>
            {(guardrails.failures as Array<Record<string, unknown>>).map((f, i) => (
              <div key={i} className="rounded-md border border-danger/30 bg-danger/10 p-2">
                <span className="font-semibold">{String(f.metric ?? "")}</span>
                {" — "}
                {String(f.detail ?? f.message ?? "")}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function CompareResultCard({ result }: { result: Record<string, unknown> }) {
  const runs = (result.presets ?? result.results ?? []) as Array<Record<string, unknown>>;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Preset comparison</CardTitle>
        <CardDescription>
          {runs.length} preset{runs.length === 1 ? "" : "s"} evaluated in parallel sandboxes.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {runs.map((run, i) => {
          const gr = (run.guardrails ?? {}) as Record<string, unknown>;
          const passed = !!gr.passed;
          const metrics = (run.season_metrics ?? []) as Array<Record<string, unknown>>;
          return (
            <div key={i} className="rounded-md border border-border bg-surface p-3">
              <div className="mb-2 flex items-center justify-between">
                <div className="text-sm font-semibold">
                  {String(run.preset ?? `preset ${i + 1}`)}
                </div>
                <Badge tone={passed ? "success" : "danger"}>
                  {passed ? "Pass" : "Fail"}
                </Badge>
              </div>
              <MetricsTable rows={metrics} />
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function MetricsTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (rows.length === 0) {
    return <div className="text-xs italic text-muted">No season metrics.</div>;
  }
  const columns = Array.from(
    rows.reduce((set, row) => {
      Object.keys(row).forEach((k) => set.add(k));
      return set;
    }, new Set<string>()),
  );
  const primary = [
    "season_year",
    "distressed_debt_ratio",
    "negative_cash_ratio",
    "unsigned_ratio",
    "payroll_spread_ratio",
    "star_retention_rate",
  ].filter((c) => columns.includes(c));
  const display = primary.length ? primary : columns.slice(0, 6);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border text-left text-muted">
            {display.map((c) => (
              <th key={c} className="px-2 py-1 font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-border/50">
              {display.map((c) => (
                <td key={c} className="px-2 py-1 tabular-nums">
                  {formatCell(row[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (Number.isInteger(v)) return String(v);
    return v.toFixed(3);
  }
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
