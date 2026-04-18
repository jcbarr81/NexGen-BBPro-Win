/**
 * Commissioner-only league settings page.
 *
 * Consolidates the PyQt trade_settings_dialog / injury_settings_dialog /
 * financial_settings_dialog into a single screen. Non-admin users are
 * bounced to /home.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeftRight,
  DollarSign,
  HeartPulse,
  Loader2,
  Save,
} from "lucide-react";

import { api, type CommissionerSettings } from "@/lib/api";
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
  Label,
} from "@/components/ui";

export function CommissionerPage() {
  const role = useAuthStore((s) => s.role);
  const settings = useQuery({
    queryKey: ["commissioner-settings"],
    queryFn: () => api.commissionerSettings(),
    enabled: role === "admin",
  });

  if (role !== "admin") return <Navigate to="/home" replace />;

  return (
    <AppShell
      title="Commissioner"
      subtitle="League-wide rules and automation"
    >
      {settings.isLoading ? (
        <LoadingCard />
      ) : settings.isError ? (
        <ErrorCard message={(settings.error as Error).message} />
      ) : settings.data ? (
        <div className="space-y-6">
          <TradeCard data={settings.data} />
          <InjuryCard data={settings.data} />
          <FinanceCard data={settings.data} />
        </div>
      ) : null}
    </AppShell>
  );
}

function TradeCard({ data }: { data: CommissionerSettings }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(data.trade);
  const mutation = useMutation({
    mutationFn: () => api.saveCommishTrade(draft),
    onSuccess: (next) => queryClient.setQueryData(["commissioner-settings"], next),
  });

  const dirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(data.trade),
    [draft, data.trade],
  );

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Trades</CardTitle>
          <CardDescription>CPU behavior + deadline rules</CardDescription>
        </div>
        <Badge tone="amber">
          <ArrowLeftRight className="h-3 w-3" />{" "}
          {draft.trades_enabled ? "Trading enabled" : "Paused"}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <Toggle
          label="Trades enabled"
          checked={draft.trades_enabled}
          onChange={(v) => setDraft({ ...draft, trades_enabled: v })}
        />
        <Toggle
          label="Draft pick trading"
          checked={draft.draft_pick_trading_enabled}
          onChange={(v) =>
            setDraft({ ...draft, draft_pick_trading_enabled: v })
          }
        />
        <Toggle
          label="Require commissioner approval"
          checked={draft.require_commissioner_approval}
          onChange={(v) =>
            setDraft({ ...draft, require_commissioner_approval: v })
          }
        />
        <Toggle
          label="CPU-initiated offers"
          checked={draft.cpu_initiated_trades_enabled}
          onChange={(v) =>
            setDraft({ ...draft, cpu_initiated_trades_enabled: v })
          }
        />
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label>CPU cadence</Label>
            <select
              value={draft.cpu_proposal_cadence}
              onChange={(e) =>
                setDraft({ ...draft, cpu_proposal_cadence: e.target.value })
              }
              className="h-10 w-full rounded-lg border border-border bg-canvas/60 px-3 text-sm text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
            >
              {data.options.trade_cadences.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label>Max pick trade years</Label>
            <input
              type="number"
              min={1}
              max={10}
              value={draft.max_pick_trade_years}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  max_pick_trade_years: Number(e.target.value) || 1,
                })
              }
              className="h-10 w-full rounded-lg border border-border bg-canvas/60 px-3 text-sm text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
            />
          </div>
        </div>
        {mutation.isError && (
          <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            {(mutation.error as Error).message}
          </div>
        )}
        <div className="flex justify-end">
          <Button
            onClick={() => mutation.mutate()}
            disabled={!dirty || mutation.isPending}
          >
            {mutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Save trade settings
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function InjuryCard({ data }: { data: CommissionerSettings }) {
  const queryClient = useQueryClient();
  const [level, setLevel] = useState(data.injury.level);
  const mutation = useMutation({
    mutationFn: () => api.saveCommishInjury(level),
    onSuccess: (next) => queryClient.setQueryData(["commissioner-settings"], next),
  });
  const dirty = level !== data.injury.level;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Injuries</CardTitle>
          <CardDescription>
            How aggressively the sim produces injuries
          </CardDescription>
        </div>
        <Badge tone="amber">
          <HeartPulse className="h-3 w-3" /> {data.injury.level}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
          {data.options.injury_levels.map((opt) => (
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
        {mutation.isError && (
          <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            {(mutation.error as Error).message}
          </div>
        )}
        <div className="flex justify-end">
          <Button
            onClick={() => mutation.mutate()}
            disabled={!dirty || mutation.isPending}
          >
            {mutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Save injury level
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function FinanceCard({ data }: { data: CommissionerSettings }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(data.finance);
  const mutation = useMutation({
    mutationFn: () =>
      api.saveCommishFinance({
        enabled: draft.enabled,
        preset: draft.preset,
        enforcement_mode: draft.enforcement_mode,
      }),
    onSuccess: (next) => queryClient.setQueryData(["commissioner-settings"], next),
  });
  const dirty = useMemo(
    () =>
      draft.enabled !== data.finance.enabled ||
      draft.preset !== data.finance.preset ||
      draft.enforcement_mode !== data.finance.enforcement_mode,
    [draft, data.finance],
  );

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Finance</CardTitle>
          <CardDescription>
            League financial preset + enforcement mode
          </CardDescription>
        </div>
        <Badge tone={draft.enabled ? "amber" : "neutral"}>
          <DollarSign className="h-3 w-3" />{" "}
          {draft.enabled ? draft.preset : "disabled"}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <Toggle
          label="Finance enabled"
          checked={draft.enabled}
          onChange={(v) => setDraft({ ...draft, enabled: v })}
        />
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label>Preset</Label>
            <select
              value={draft.preset}
              disabled={!draft.enabled}
              onChange={(e) => setDraft({ ...draft, preset: e.target.value })}
              className="h-10 w-full rounded-lg border border-border bg-canvas/60 px-3 text-sm text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40 disabled:opacity-50"
            >
              {data.options.finance_presets.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label>Enforcement</Label>
            <select
              value={draft.enforcement_mode}
              disabled={!draft.enabled}
              onChange={(e) =>
                setDraft({ ...draft, enforcement_mode: e.target.value })
              }
              className="h-10 w-full rounded-lg border border-border bg-canvas/60 px-3 text-sm text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40 disabled:opacity-50"
            >
              {data.options.finance_enforcement.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        </div>
        {mutation.isError && (
          <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            {(mutation.error as Error).message}
          </div>
        )}
        <div className="flex justify-end">
          <Button
            onClick={() => mutation.mutate()}
            disabled={!dirty || mutation.isPending}
          >
            {mutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Save finance settings
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 rounded-lg border border-border bg-surfaceAlt/40 px-3 py-2">
      <span className="text-sm font-semibold">{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-amber"
      />
    </label>
  );
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading settings…</span>
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
