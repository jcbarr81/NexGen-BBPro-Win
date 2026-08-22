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
  ChevronDown,
  ChevronRight,
  Command,
  DollarSign,
  Eye,
  GraduationCap,
  HeartPulse,
  ListChecks,
  Loader2,
  RefreshCw,
  Save,
  Settings2,
  Shuffle,
  Sliders,
  Snowflake,
  Swords,
  UserCog,
} from "lucide-react";
import { Link } from "react-router-dom";

import { api, type CommissionerSettings } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { useTeams } from "@/lib/use-teams";
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
      <QuickAccessGrid />
      {settings.isLoading ? (
        <LoadingCard />
      ) : settings.isError ? (
        <ErrorCard message={(settings.error as Error).message} />
      ) : settings.data ? (
        <div className="space-y-6">
          <TradeCard data={settings.data} />
          <InjuryCard data={settings.data} />
          <FinanceCard data={settings.data} />
          <ScoutingCard data={settings.data} />
          <StrategyCard data={settings.data} />
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

const FINANCE_LEVEL_LABELS: Record<string, string> = {
  off: "Off",
  basic: "Basic",
  advanced: "Advanced",
  mlb_like: "MLB-Like",
  on: "On",
  // Legacy values still render as "On" if an old config surfaces them.
  warn: "On",
  block: "On",
};

function FinanceCard({ data }: { data: CommissionerSettings }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(data.finance);
  const [showModules, setShowModules] = useState(false);
  const [showAiTuning, setShowAiTuning] = useState(false);

  // The "Custom" preset is what unlocks per-module + AI tuning. When the user
  // edits modules/AI directly we flip the preset to custom client-side; the
  // server does the same on the writes that include those fields.
  const mutation = useMutation({
    mutationFn: () =>
      api.saveCommishFinance({
        enabled: draft.enabled,
        preset: draft.preset,
        enforcement_mode: draft.enforcement_mode,
        modules: draft.modules,
        finance_ai_tuning: draft.finance_ai_tuning,
      }),
    onSuccess: (next) => {
      queryClient.setQueryData(["commissioner-settings"], next);
      setDraft(next.finance);
    },
  });
  const dirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(data.finance),
    [draft, data.finance],
  );

  const modules = data.options.finance_modules ?? [];
  const aiDefaults = data.options.finance_ai_tuning_defaults ?? {};

  function applyPreset(preset: string) {
    // Reflect the preset's module levels + enforcement immediately so the UI
    // isn't stale before saving. The server still rebuilds authoritatively from
    // PRESET_PROFILES on save. "custom" keeps the current module values.
    const profile = data.options.finance_preset_profiles?.[preset];
    if (profile) {
      setDraft({
        ...draft,
        preset,
        enforcement_mode: profile.enforcement_mode,
        modules: { ...draft.modules, ...profile.modules },
      });
    } else {
      setDraft({ ...draft, preset });
    }
  }

  function setModuleLevel(moduleId: string, level: string) {
    // When leaving a preset for custom, seed the full preset module levels so
    // the other modules keep their preset values instead of reverting to
    // whatever stale (possibly off) values were in draft.modules.
    const presetModules =
      draft.preset !== "custom"
        ? data.options.finance_preset_profiles?.[draft.preset]?.modules
        : undefined;
    const base = presetModules
      ? { ...draft.modules, ...presetModules }
      : draft.modules;
    setDraft({
      ...draft,
      preset: "custom",
      modules: { ...base, [moduleId]: level },
    });
  }

  function setAiValue(key: string, raw: string) {
    const parsed = Number(raw);
    setDraft({
      ...draft,
      preset: "custom",
      finance_ai_tuning: {
        ...draft.finance_ai_tuning,
        [key]: Number.isFinite(parsed) ? parsed : draft.finance_ai_tuning[key],
      },
    });
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Finance</CardTitle>
          <CardDescription>
            League finance preset, enforcement, per-module levels, and CPU
            tuning. Mirrors PyQt's FinancialSettingsDialog.
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
              onChange={(e) => applyPreset(e.target.value)}
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

        {modules.length > 0 && (
          <div className="rounded-lg border border-border bg-surfaceAlt/40">
            <button
              type="button"
              onClick={() => setShowModules((v) => !v)}
              className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm font-semibold"
            >
              <span className="inline-flex items-center gap-2">
                {showModules ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
                Module levels
              </span>
              <span className="text-xs text-muted">
                {modules.length} modules · {draft.preset}
              </span>
            </button>
            {showModules && (
              <div className="space-y-2 border-t border-border/60 px-3 py-3">
                {modules.map((m) => {
                  // When a non-custom preset is active, show the preset's level
                  // directly so the display is always consistent with the
                  // selected preset (independent of when modules were synced).
                  const presetModules =
                    draft.preset !== "custom"
                      ? data.options.finance_preset_profiles?.[draft.preset]
                          ?.modules
                      : undefined;
                  const level =
                    presetModules?.[m.id] ??
                    draft.modules[m.id] ??
                    m.levels[0] ??
                    "off";
                  return (
                    <div
                      key={m.id}
                      className="grid grid-cols-1 items-start gap-2 md:grid-cols-[minmax(0,1fr)_180px]"
                    >
                      <div className="min-w-0">
                        <div className="text-sm font-semibold">{m.label}</div>
                        <div className="text-xs text-muted">{m.help}</div>
                      </div>
                      <div>
                        <select
                          value={level}
                          disabled={!draft.enabled}
                          onChange={(e) => setModuleLevel(m.id, e.target.value)}
                          className="h-8 w-full rounded-md border border-border bg-canvas/60 px-2 text-xs text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40 disabled:opacity-50"
                        >
                          {m.levels.map((lvl) => (
                            <option key={lvl} value={lvl}>
                              {FINANCE_LEVEL_LABELS[lvl] ?? lvl}
                            </option>
                          ))}
                        </select>
                        {m.level_help?.[level] && (
                          <div className="mt-1 text-[11px] leading-snug text-muted">
                            {m.level_help[level]}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {Object.keys(aiDefaults).length > 0 && (
          <div className="rounded-lg border border-border bg-surfaceAlt/40">
            <button
              type="button"
              onClick={() => setShowAiTuning((v) => !v)}
              className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm font-semibold"
            >
              <span className="inline-flex items-center gap-2">
                {showAiTuning ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
                CPU finance AI tuning
              </span>
              <span className="text-xs text-muted">
                {Object.keys(aiDefaults).length} knobs
              </span>
            </button>
            {showAiTuning && (
              <div className="space-y-2 border-t border-border/60 px-3 py-3">
                <p className="text-xs text-muted">
                  Star/underperformer thresholds, salary share caps, arbitration
                  raise %, and free-agency avoidance bands. Only edit these in
                  Custom mode.
                </p>
                <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                  {Object.entries(aiDefaults).map(([key, defValue]) => {
                    const value =
                      draft.finance_ai_tuning[key] ?? Number(defValue);
                    return (
                      <div
                        key={key}
                        className="grid grid-cols-[minmax(0,1fr)_120px] items-center gap-2"
                      >
                        <Label
                          htmlFor={`ai-${key}`}
                          className="text-xs font-normal text-muted"
                        >
                          {key.replace(/_/g, " ")}
                        </Label>
                        <input
                          id={`ai-${key}`}
                          type="number"
                          step="any"
                          value={value}
                          disabled={!draft.enabled}
                          onChange={(e) => setAiValue(key, e.target.value)}
                          className="h-8 w-full rounded-md border border-border bg-canvas/60 px-2 text-xs text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40 disabled:opacity-50"
                        />
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {mutation.isError && (
          <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            {(mutation.error as Error).message}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            onClick={() => setDraft(data.finance)}
            disabled={!dirty || mutation.isPending}
          >
            <RefreshCw className="h-4 w-4" /> Reset
          </Button>
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

function ScoutingCard({ data }: { data: CommissionerSettings }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(data.scouting);
  const mutation = useMutation({
    mutationFn: () => api.saveCommishScouting(draft),
    onSuccess: (next) => {
      queryClient.setQueryData(["commissioner-settings"], next);
      setDraft(next.scouting);
    },
  });
  const dirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(data.scouting),
    [draft, data.scouting],
  );

  function setNumber(key: keyof typeof draft, raw: string) {
    const parsed = Number(raw);
    setDraft({
      ...draft,
      [key]: Number.isFinite(parsed) ? parsed : (draft[key] as number),
    });
  }

  const fields: Array<{ key: keyof typeof draft; label: string; step?: number }> = [
    { key: "base_monthly_credits", label: "Base monthly credits", step: 1 },
    { key: "finance_off_multiplier", label: "Finance-off pace multiplier", step: 0.01 },
    { key: "monthly_decay", label: "Monthly decay", step: 0.001 },
    { key: "passive_gain", label: "Passive gain", step: 0.001 },
    { key: "max_banked_credits", label: "Max banked credits", step: 1 },
    { key: "auto_spend_cap", label: "Auto spend cap", step: 1 },
  ];

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>
            <span className="inline-flex items-center gap-2">
              <Eye className="h-4 w-4" /> Scouting fog-of-war
            </span>
          </CardTitle>
          <CardDescription>
            Tune the scouting system that hides ratings until owners spend
            credits. Works whether the finance system is on or off.
          </CardDescription>
        </div>
        <Badge tone={draft.enabled ? "amber" : "neutral"}>
          <Eye className="h-3 w-3" /> {draft.enabled ? "enabled" : "disabled"}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <Toggle
          label="Scouting fog-of-war enabled"
          checked={draft.enabled}
          onChange={(v) => setDraft({ ...draft, enabled: v })}
        />
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {fields.map(({ key, label, step }) => (
            <div key={String(key)} className="space-y-1.5">
              <Label htmlFor={`scout-${String(key)}`}>{label}</Label>
              <input
                id={`scout-${String(key)}`}
                type="number"
                step={step ?? "any"}
                value={Number(draft[key])}
                onChange={(e) => setNumber(key, e.target.value)}
                className="h-9 w-full rounded-md border border-border bg-canvas/60 px-2 text-sm text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
              />
            </div>
          ))}
        </div>
        {mutation.isError && (
          <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            {(mutation.error as Error).message}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            onClick={() => setDraft(data.scouting)}
            disabled={!dirty || mutation.isPending}
          >
            <RefreshCw className="h-4 w-4" /> Reset
          </Button>
          <Button
            onClick={() => mutation.mutate()}
            disabled={!dirty || mutation.isPending}
          >
            {mutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Save scouting settings
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

function StrategyCard({ data }: { data: CommissionerSettings }) {
  const queryClient = useQueryClient();
  const profiles = data.options.strategy_profiles ?? [];
  const teamsQ = useTeams();

  const [defaultProfile, setDefaultProfile] = useState(
    data.strategy.default_profile ?? "",
  );
  const [defaultAutoReassign, setDefaultAutoReassign] = useState(
    data.auto_reassign.default_enabled,
  );
  const [teamStrategies, setTeamStrategies] = useState<Record<string, string>>(
    { ...data.strategy.teams },
  );
  const [teamAutoReassigns, setTeamAutoReassigns] = useState<
    Record<string, boolean>
  >({ ...data.auto_reassign.teams });

  // Dirty tracking against the loaded server data — reset after save.
  const dirty =
    defaultProfile !== (data.strategy.default_profile ?? "") ||
    defaultAutoReassign !== data.auto_reassign.default_enabled ||
    JSON.stringify(teamStrategies) !==
      JSON.stringify(data.strategy.teams ?? {}) ||
    JSON.stringify(teamAutoReassigns) !==
      JSON.stringify(data.auto_reassign.teams ?? {});

  const save = useMutation({
    mutationFn: () =>
      api.saveCommishStrategy({
        default_profile: defaultProfile || undefined,
        default_auto_reassign: defaultAutoReassign,
        team_strategies: teamStrategies,
        team_auto_reassigns: teamAutoReassigns,
      }),
    onSuccess: (next) => {
      queryClient.setQueryData(["commissioner-settings"], next);
      setDefaultProfile(next.strategy.default_profile ?? "");
      setDefaultAutoReassign(next.auto_reassign.default_enabled);
      setTeamStrategies({ ...next.strategy.teams });
      setTeamAutoReassigns({ ...next.auto_reassign.teams });
    },
  });

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>
            <span className="inline-flex items-center gap-2">
              <Settings2 className="h-4 w-4" /> Strategy &amp; auto-reassign
            </span>
          </CardTitle>
          <CardDescription>
            League defaults plus per-team overrides. Ports PyQt's
            TeamStrategySettingsDialog.
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          {dirty && <Badge tone="warning">Unsaved</Badge>}
          <Button
            onClick={() => save.mutate()}
            disabled={!dirty || save.isPending}
          >
            {save.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Save strategy
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="commish-default-strategy">
              League default strategy
            </Label>
            <select
              id="commish-default-strategy"
              value={defaultProfile}
              onChange={(e) => setDefaultProfile(e.target.value)}
              className="h-9 w-full rounded-md border border-border bg-canvas/60 px-2 text-sm text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
            >
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label>League default auto-reassign</Label>
            <div className="flex rounded-lg border border-border bg-surfaceAlt p-1">
              {[
                { value: true, label: "Enabled" },
                { value: false, label: "Disabled" },
              ].map((opt) => (
                <button
                  key={String(opt.value)}
                  type="button"
                  onClick={() => setDefaultAutoReassign(opt.value)}
                  className={cn(
                    "flex-1 rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
                    defaultAutoReassign === opt.value
                      ? "bg-amber text-espresso"
                      : "text-muted hover:bg-surface hover:text-ink",
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div>
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
            Team overrides
          </div>
          <div className="max-h-80 overflow-y-auto rounded-lg border border-border bg-canvas/30">
            <div className="overflow-x-auto"><table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 text-[10px] uppercase tracking-wider text-muted">
                  <th className="px-4 py-2 text-left">Team</th>
                  <th className="px-3 py-2 text-left">Strategy</th>
                  <th className="px-3 py-2 text-left">Auto-reassign</th>
                </tr>
              </thead>
              <tbody>
                {(teamsQ.data ?? []).map((team) => {
                  const sid = teamStrategies[team.team_id] ?? "";
                  const ar = teamAutoReassigns[team.team_id];
                  return (
                    <tr
                      key={team.team_id}
                      className="border-b border-border/30 last:border-b-0 hover:bg-surfaceAlt/30"
                    >
                      <td className="px-4 py-2 font-semibold">
                        {team.city} {team.name}
                        <span className="ml-2 text-[10px] uppercase tracking-wider text-muted">
                          {team.abbreviation || team.team_id}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <select
                          value={sid}
                          onChange={(e) =>
                            setTeamStrategies({
                              ...teamStrategies,
                              [team.team_id]: e.target.value,
                            })
                          }
                          className="h-8 w-full rounded-md border border-border bg-canvas/60 px-2 text-xs text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
                        >
                          <option value="">League default</option>
                          {profiles.map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-3 py-2">
                        <select
                          value={
                            ar == null ? "default" : ar ? "enabled" : "disabled"
                          }
                          onChange={(e) => {
                            const v = e.target.value;
                            setTeamAutoReassigns((prev) => {
                              const next = { ...prev };
                              if (v === "default") {
                                delete next[team.team_id];
                              } else {
                                next[team.team_id] = v === "enabled";
                              }
                              return next;
                            });
                          }}
                          className="h-8 w-full rounded-md border border-border bg-canvas/60 px-2 text-xs text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
                        >
                          <option value="default">League default</option>
                          <option value="enabled">Enabled</option>
                          <option value="disabled">Disabled</option>
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table></div>
          </div>
        </div>

        {save.isError && (
          <div className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span className="whitespace-pre-line">
              {(save.error as Error).message}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
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

/**
 * Card grid of the most-used admin actions. Sits at the top of the
 * Commissioner page so admins don't have to hunt through the sidebar.
 */
function QuickAccessGrid() {
  const actions = [
    {
      to: "/command-center",
      label: "Command Center",
      description: "League-wide attention cards",
      Icon: Command,
    },
    {
      to: "/finance-queue",
      label: "Finance Queue",
      description: "Pending GM decisions",
      Icon: ListChecks,
    },
    {
      to: "/offseason",
      label: "Offseason Flow",
      description: "End-of-season checklist",
      Icon: Snowflake,
    },
    {
      to: "/reassign",
      label: "Reassign Players",
      description: "Bulk auto-assign rosters",
      Icon: Shuffle,
    },
    {
      to: "/finance-stability",
      label: "Finance Stability",
      description: "Multi-season sandbox",
      Icon: DollarSign,
    },
    {
      to: "/exhibition",
      label: "Exhibition Game",
      description: "One-off what-if sim",
      Icon: Swords,
    },
    {
      to: "/league-admin",
      label: "League Admin",
      description: "Schedule, reset, clone",
      Icon: Settings2,
    },
    {
      to: "/tuning",
      label: "Physics Tuning",
      description: "Engine knobs",
      Icon: Sliders,
    },
    {
      to: "/users",
      label: "Users",
      description: "Accounts + roles",
      Icon: UserCog,
    },
  ];
  return (
    <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
      {actions.map(({ to, label, description, Icon }) => (
        <Link
          key={to}
          to={to}
          className="group flex items-start gap-2 rounded-md border border-border bg-surface p-3 transition hover:border-amber hover:bg-surfaceAlt"
        >
          <Icon className="mt-0.5 h-4 w-4 shrink-0 text-amber" aria-hidden />
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold group-hover:text-amber-text">
              {label}
            </div>
            <div className="truncate text-[11px] text-muted">{description}</div>
          </div>
        </Link>
      ))}
    </div>
  );
}
