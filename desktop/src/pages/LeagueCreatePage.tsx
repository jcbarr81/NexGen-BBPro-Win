/**
 * League creation wizard.
 *
 * Multi-step: Basics → Setup → Teams → Rules → Review → Create.
 * When invoked with `?first-run=1` we prepend a "Set admin password"
 * step and POST /admin/bootstrap before issuing any protected calls.
 */

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Dice5,
  Loader2,
  Lock,
  Plus,
  Sparkles,
  Trash2,
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
  Input,
  Label,
} from "@/components/ui";

type Team = { city: string; name: string };
type Divisions = Record<string, Team[]>;

type SetupMode = "quickstart" | "custom";

const FINANCE_LEVEL_LABELS: Record<string, string> = {
  off: "Off",
  basic: "Basic",
  advanced: "Advanced",
  mlb_like: "MLB-Like",
  on: "On",
  // Legacy values still render as "On".
  warn: "On",
  block: "On",
};

// One-liner descriptions surfaced under the Finance preset / enforcement
// dropdowns so the user knows what they're picking. Keep these short —
// the full module-level help is shown inside the advanced expander.
const FINANCE_PRESET_DESCRIPTIONS: Record<string, string> = {
  off: "Finance system off. No budgets, salaries, or CPU finance AI — pure on-field play.",
  simple: "Lightweight: basic revenue, budgets, contracts, payroll, and free agency. No market model or arbitration. Enforcement on (luxury tax in-season).",
  standard: "Most owner + GM modules at Advanced. Adds a basic market model and arbitration. Enforcement on (luxury tax in-season).",
  mlb_like: "Full MLB-style sim: advanced revenue / market / budgets / contracts / arbitration / FA, MLB payroll rules, and enforcement on.",
  custom: "Build it yourself — open the advanced section below to set each module level individually.",
};

const FINANCE_ENFORCEMENT_DESCRIPTIONS: Record<string, string> = {
  off: "Don't enforce the finance rules — signings and trades ignore budgets.",
  on: "Enforce the rules: exceed the luxury threshold during the season and you pay the tax; your team must be solvent at Opening Day.",
};

interface ScoutingTuning {
  base_monthly_credits: number;
  finance_off_multiplier: number;
  monthly_decay: number;
  passive_gain: number;
  max_banked_credits: number;
  auto_spend_cap: number;
}

interface WizardState {
  displayName: string;
  mode: "single_player" | "owner_league";
  commissionerVisibility: "public" | "private";
  templateLeagueId: string;
  setupMode: SetupMode;
  quickstartPresetId: string;
  customDivisions: string;
  customTeamsPerDivision: number;
  divisions: Divisions;
  rulePresetId: string;
  scheduleTemplateId: string;
  financeEnabled: boolean;
  financePreset: string;
  financeEnforcement: string;
  // Advanced finance overrides — only sent when user touches them.
  financeModules: Record<string, string>;
  financeAiTuning: Record<string, number>;
  // Scouting fog-of-war.
  scoutingEnabled: boolean;
  scoutingTuning: ScoutingTuning;
  scoutingTuningTouched: boolean;
  tradesEnabled: boolean;
  draftPickTradingEnabled: boolean;
  cpuInitiatedTrades: boolean;
  cpuProposalCadence: string;
  injuryLevel: string;
  draftRounds: number;
  draftPoolSize: number;
}

const INITIAL: WizardState = {
  displayName: "",
  mode: "single_player",
  commissionerVisibility: "private",
  templateLeagueId: "",
  setupMode: "quickstart",
  quickstartPresetId: "",
  customDivisions: "East, West",
  customTeamsPerDivision: 4,
  divisions: {},
  rulePresetId: "",
  // Default to a real schedule template so the season is playable the
  // moment league creation finishes — leaving this empty stranded the
  // user on the Season page with "no games scheduled" until an admin
  // ran Regenerate Schedule from League Admin.
  scheduleTemplateId: "mlb_162",
  financeEnabled: false,
  financePreset: "off",
  financeEnforcement: "on",
  financeModules: {},
  financeAiTuning: {},
  scoutingEnabled: false,
  scoutingTuning: {
    base_monthly_credits: 100,
    finance_off_multiplier: 1.0,
    monthly_decay: 0.02,
    passive_gain: 0.01,
    max_banked_credits: 1000,
    auto_spend_cap: 100,
  },
  scoutingTuningTouched: false,
  tradesEnabled: true,
  draftPickTradingEnabled: false,
  cpuInitiatedTrades: true,
  cpuProposalCadence: "normal",
  injuryLevel: "normal",
  draftRounds: 10,
  draftPoolSize: 200,
};

/**
 * Numeric input that lets the user type freely. The committed numeric value
 * lives in the wizard state, but the field keeps its own text buffer so you
 * can clear it and type intermediate values (e.g. "1" on the way to "150")
 * without it snapping to the min/default on every keystroke. Clamping +
 * fallback happen only on blur / Enter.
 */
function NumberField({
  id,
  value,
  min,
  max,
  step,
  fallback,
  onCommit,
}: {
  id?: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  fallback: number;
  onCommit: (n: number) => void;
}) {
  const [text, setText] = useState(String(value));
  // Re-sync when the committed value changes from elsewhere (e.g. a preset).
  useEffect(() => {
    setText(String(value));
  }, [value]);

  function commit() {
    const parsed = parseInt(text, 10);
    const next = Number.isFinite(parsed)
      ? Math.max(min, Math.min(max, parsed))
      : fallback;
    setText(String(next));
    if (next !== value) onCommit(next);
  }

  return (
    <Input
      id={id}
      type="number"
      inputMode="numeric"
      min={min}
      max={max}
      step={step}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commit();
        }
      }}
    />
  );
}

export function LeagueCreatePage() {
  const [params] = useSearchParams();
  const isFirstRun = params.get("first-run") === "1";
  const role = useAuthStore((s) => s.role);
  const pkg = useAuthStore((s) => s.pkg);
  const navigate = useNavigate();
  // Cloud commissioner flow: a Commissioner-package account creating their own
  // multi-owner league (vs the legacy admin-only path).
  const isCommissioner = params.get("commissioner") === "1" && pkg === "commissioner";
  const canCreate = role === "admin" || isCommissioner;

  // Admin / commissioner only once past first-run bootstrap.
  if (!isFirstRun && !canCreate) {
    return <Navigate to="/login?require=admin&next=/leagues/new" replace />;
  }

  const [step, setStep] = useState(isFirstRun ? 0 : 1);
  const [state, setState] = useState<WizardState>(INITIAL);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const presets = useQuery({
    queryKey: ["league-presets"],
    queryFn: () => api.leaguePresets(),
    enabled: canCreate,
  });
  const existingLeagues = useQuery({
    queryKey: ["leagues"],
    queryFn: () => api.listLeagues(),
    enabled: canCreate,
  });
  // Pull the commissioner settings catalog so the wizard can render the
  // same module + AI tuning + scouting controls the post-create
  // Commissioner page uses. Static catalog fields (finance_modules,
  // finance_ai_tuning_defaults) are league-agnostic, so the response
  // works as a schema source even before any league exists. Only
  // enabled for admin users.
  const commishSettings = useQuery({
    queryKey: ["commissioner-settings"],
    queryFn: () => api.commissionerSettings(),
    enabled: canCreate,
  });

  const stepLabels = isFirstRun
    ? ["Admin", "Basics", "Setup", "Teams", "Rules", "Review"]
    : ["Basics", "Setup", "Teams", "Rules", "Review"];

  function patch(update: Partial<WizardState>) {
    setState((prev) => ({ ...prev, ...update }));
  }

  // Once the commissioner catalog loads, seed scouting defaults so the
  // numeric inputs show real starting values instead of the placeholder
  // constants. Only seeds while the user hasn't touched the fields and
  // hasn't enabled scouting yet.
  useEffect(() => {
    const data = commishSettings.data;
    if (!data) return;
    setState((prev) => {
      if (prev.scoutingTuningTouched) return prev;
      return {
        ...prev,
        scoutingTuning: {
          base_monthly_credits: data.scouting.base_monthly_credits,
          finance_off_multiplier: data.scouting.finance_off_multiplier,
          monthly_decay: data.scouting.monthly_decay,
          passive_gain: data.scouting.passive_gain,
          max_banked_credits: data.scouting.max_banked_credits,
          auto_spend_cap: data.scouting.auto_spend_cap,
        },
      };
    });
  }, [commishSettings.data]);

  async function handleCreate() {
    setCreating(true);
    setCreateError(null);
    try {
      const divisions = state.divisions;
      const financePayload: Record<string, unknown> = {
        enabled: state.financeEnabled,
        preset: state.financePreset,
        enforcement_mode: state.financeEnforcement,
      };
      // Only forward module + AI overrides when the user actually edited
      // them (which flips the preset to "custom" inline). Sending an
      // empty modules block would otherwise stomp the preset's own
      // defaults server-side.
      if (Object.keys(state.financeModules).length > 0) {
        financePayload.modules = state.financeModules;
      }
      if (Object.keys(state.financeAiTuning).length > 0) {
        financePayload.finance_ai_tuning = state.financeAiTuning;
      }
      const scoutingPayload: Record<string, unknown> = {
        enabled: state.scoutingEnabled,
      };
      if (state.scoutingTuningTouched) {
        Object.assign(scoutingPayload, state.scoutingTuning);
      }
      const createPayload = {
        display_name: state.displayName,
        mode: state.mode,
        template_league_id: state.templateLeagueId || undefined,
        divisions,
        rule_preset_id: state.rulePresetId || undefined,
        schedule_template_id: state.scheduleTemplateId || undefined,
        finance: financePayload,
        scouting: scoutingPayload,
        trades: {
          trades_enabled: state.tradesEnabled,
          draft_pick_trading_enabled: state.draftPickTradingEnabled,
          cpu_initiated_trades_enabled: state.cpuInitiatedTrades,
          cpu_proposal_cadence: state.cpuProposalCadence,
        },
        injury_level: state.injuryLevel,
        draft: {
          rounds: state.draftRounds,
          pool_size: state.draftPoolSize,
        },
      };
      if (isCommissioner) {
        // Cloud: register the league in the control plane with the caller as
        // commissioner. Server forces owner_league mode. Starts private; the
        // commissioner can open it up / generate invites afterwards.
        await api.createLeagueAsCommissioner({
          ...createPayload,
          visibility: state.commissionerVisibility,
        });
        navigate("/my-leagues", { replace: true });
      } else {
        await api.createLeague(createPayload);
        navigate("/select-league", { replace: true });
      }
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Creation failed.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <AppShell
      title={isFirstRun ? "Welcome to NexGen-BBPro" : "Create New League"}
      subtitle={
        isFirstRun
          ? "Let's set up your first league."
          : stepLabels[step - (isFirstRun ? 0 : 1)]
      }
    >
      <StepIndicator labels={stepLabels} current={step - (isFirstRun ? 0 : 1)} />

      <div className="mt-6">
        {isFirstRun && step === 0 && (
          <AdminBootstrapStep onDone={() => setStep(1)} />
        )}
        {step === 1 && (
          <BasicsStep
            state={state}
            onPatch={patch}
            existingLeagues={existingLeagues.data ?? []}
          />
        )}
        {step === 2 && (
          <SetupStep
            state={state}
            onPatch={patch}
            presets={presets.data}
          />
        )}
        {step === 3 && (
          <TeamsStep state={state} onPatch={patch} />
        )}
        {step === 4 && (
          <RulesStep
            state={state}
            onPatch={patch}
            presets={presets.data}
            commish={commishSettings.data}
          />
        )}
        {step === 5 && (
          <ReviewStep
            state={state}
            presets={presets.data}
            creating={creating}
            error={createError}
            onCreate={handleCreate}
          />
        )}
      </div>

      <StepNav
        step={step}
        maxStep={5}
        minStep={isFirstRun ? 0 : 1}
        canAdvance={canAdvance(step, state, isFirstRun)}
        onBack={() => setStep((s) => Math.max(isFirstRun ? 0 : 1, s - 1))}
        onNext={() => {
          // When leaving Setup (step 2), materialize the divisions map so
          // Teams (step 3) has something to render.
          if (step === 2) {
            patch({ divisions: buildInitialDivisions(state, presets.data) });
          }
          setStep((s) => Math.min(5, s + 1));
        }}
        showCreate={step === 5}
        onCreate={handleCreate}
        creating={creating}
      />
    </AppShell>
  );
}

// ---------------------------------------------------------------------------

function StepIndicator({
  labels,
  current,
}: {
  labels: string[];
  current: number;
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-border bg-surfaceAlt/40 p-2">
      {labels.map((label, idx) => {
        const done = idx < current;
        const active = idx === current;
        return (
          <div key={label} className="flex flex-1 items-center gap-2">
            <div
              className={cn(
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold tabular-nums",
                done
                  ? "border-success bg-success/20 text-success"
                  : active
                    ? "border-amber bg-amber/20 text-amber-text"
                    : "border-border bg-surface text-muted",
              )}
            >
              {done ? <CheckCircle2 className="h-3 w-3" /> : idx + 1}
            </div>
            <div
              className={cn(
                "truncate text-xs font-semibold uppercase tracking-wider",
                active ? "text-ink" : "text-muted",
              )}
            >
              {label}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StepNav({
  step,
  maxStep,
  minStep,
  canAdvance,
  onBack,
  onNext,
  showCreate,
  onCreate,
  creating,
}: {
  step: number;
  maxStep: number;
  minStep: number;
  canAdvance: boolean;
  onBack: () => void;
  onNext: () => void;
  showCreate: boolean;
  onCreate: () => void;
  creating: boolean;
}) {
  return (
    <div className="mt-6 flex items-center justify-between">
      <Button variant="ghost" onClick={onBack} disabled={step <= minStep}>
        <ArrowLeft className="h-4 w-4" /> Back
      </Button>
      {showCreate ? (
        <Button onClick={onCreate} disabled={!canAdvance || creating}>
          {creating ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          Create league
        </Button>
      ) : (
        <Button onClick={onNext} disabled={!canAdvance || step >= maxStep}>
          Next <ArrowRight className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}

function canAdvance(
  step: number,
  state: WizardState,
  firstRun: boolean,
): boolean {
  if (firstRun && step === 0) return true; // handled by inline form
  if (step === 1) return state.displayName.trim().length >= 2;
  if (step === 2) {
    if (state.setupMode === "quickstart") return !!state.quickstartPresetId;
    return (
      state.customDivisions
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean).length > 0 && state.customTeamsPerDivision >= 1
    );
  }
  if (step === 3) {
    const totalTeams = Object.values(state.divisions).reduce(
      (acc, list) => acc + list.length,
      0,
    );
    if (totalTeams < 2) return false;
    for (const teams of Object.values(state.divisions)) {
      for (const team of teams) {
        if (!team.city.trim() || !team.name.trim()) return false;
      }
    }
    return true;
  }
  return true;
}

// ---------------------------------------------------------------------------

function AdminBootstrapStep({ onDone }: { onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    setError(null);
    if (pw.length < 4) {
      setError("Password must be at least 4 characters.");
      return;
    }
    if (pw !== pw2) {
      setError("Passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      await api.bootstrapAdmin(pw);
      // Log in with the new credentials so the rest of the wizard can hit
      // protected endpoints.
      const session = await api.login("admin", pw);
      useAuthStore.getState().setSession({
        token: session.token,
        username: session.username,
        role: session.role,
        teamId: session.team_id,
      });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bootstrap failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Set admin password</CardTitle>
          <CardDescription>
            This is a fresh install — pick a password for the built-in admin
            account before creating your first league.
          </CardDescription>
        </div>
        <Badge tone="amber">
          <Lock className="h-3 w-3" /> First run
        </Badge>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4 max-w-md">
          <div className="space-y-1.5">
            <Label htmlFor="admin-pw">New password</Label>
            <Input
              id="admin-pw"
              type="password"
              value={pw}
              onChange={(e) => setPw(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="admin-pw2">Confirm password</Label>
            <Input
              id="admin-pw2"
              type="password"
              value={pw2}
              onChange={(e) => setPw2(e.target.value)}
            />
          </div>
          {error && (
            <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {error}
            </div>
          )}
          <Button type="submit" disabled={busy}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            Continue
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------

function BasicsStep({
  state,
  onPatch,
  existingLeagues,
}: {
  state: WizardState;
  onPatch: (u: Partial<WizardState>) => void;
  existingLeagues: Array<{ id: string; display_name: string }>;
}) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Basics</CardTitle>
          <CardDescription>League name, mode, optional clone.</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5 max-w-md">
          <Label htmlFor="league-name">League name</Label>
          <Input
            id="league-name"
            value={state.displayName}
            onChange={(e) => onPatch({ displayName: e.target.value })}
            placeholder="e.g. 2028 Showcase League"
            autoFocus
          />
        </div>

        <div className="space-y-1.5">
          <Label>Mode</Label>
          <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1 w-fit">
            {([
              ["single_player", "Single-player"],
              ["owner_league", "Multi-owner"],
            ] as const).map(([val, label]) => (
              <button
                key={val}
                type="button"
                onClick={() => onPatch({ mode: val })}
                className={cn(
                  "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
                  state.mode === val
                    ? "bg-amber text-espresso"
                    : "text-muted hover:bg-surface hover:text-ink",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-1.5 max-w-md">
          <Label htmlFor="template-league">Clone from</Label>
          <select
            id="template-league"
            value={state.templateLeagueId}
            onChange={(e) => onPatch({ templateLeagueId: e.target.value })}
            className="h-10 w-full rounded-lg border border-border bg-canvas/60 px-3 text-sm focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
          >
            <option value="">Start blank</option>
            {existingLeagues.map((l) => (
              <option key={l.id} value={l.id}>
                {l.display_name} ({l.id})
              </option>
            ))}
          </select>
          <p className="text-xs text-muted">
            Optional. Seeds the new league's data directory from an existing
            league.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------

function SetupStep({
  state,
  onPatch,
  presets,
}: {
  state: WizardState;
  onPatch: (u: Partial<WizardState>) => void;
  presets: Awaited<ReturnType<typeof api.leaguePresets>> | undefined;
}) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Setup mode</CardTitle>
          <CardDescription>
            Pick a Quick-Start preset for a ready-to-go league, or build the
            structure yourself.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1 w-fit">
          {(["quickstart", "custom"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => onPatch({ setupMode: m })}
              className={cn(
                "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
                state.setupMode === m
                  ? "bg-amber text-espresso"
                  : "text-muted hover:bg-surface hover:text-ink",
              )}
            >
              {m === "quickstart" ? "Quick-Start" : "Custom"}
            </button>
          ))}
        </div>

        {state.setupMode === "quickstart" ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {(presets?.quickstart_presets ?? []).map((p) => {
              const active = state.quickstartPresetId === p.preset_id;
              return (
                <button
                  key={p.preset_id}
                  type="button"
                  onClick={() => onPatch({ quickstartPresetId: p.preset_id })}
                  className={cn(
                    "rounded-xl border p-3 text-left transition",
                    active
                      ? "border-amber bg-amber/10"
                      : "border-border bg-surfaceAlt/40 hover:border-amber/60",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-semibold">{p.name}</div>
                    {active && (
                      <Badge tone="amber">
                        <CheckCircle2 className="h-3 w-3" />
                      </Badge>
                    )}
                  </div>
                  <div className="mt-1 text-xs text-muted">
                    {p.divisions.length} divisions · {p.teams_per_division} teams each
                  </div>
                  <p className="mt-2 text-sm">{p.description}</p>
                </button>
              );
            })}
            {presets && presets.quickstart_presets.length === 0 && (
              <div className="text-sm text-muted">
                No quick-start presets available.
              </div>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 max-w-2xl">
            <div className="space-y-1.5">
              <Label htmlFor="custom-divs">Divisions</Label>
              <Input
                id="custom-divs"
                value={state.customDivisions}
                onChange={(e) => onPatch({ customDivisions: e.target.value })}
                placeholder="East, West"
              />
              <p className="text-xs text-muted">
                Comma-separated division names.
              </p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="custom-tpd">Teams per division</Label>
              <Input
                id="custom-tpd"
                type="number"
                min={1}
                max={20}
                value={state.customTeamsPerDivision}
                onChange={(e) =>
                  onPatch({
                    customTeamsPerDivision:
                      Math.max(1, Math.min(20, Number(e.target.value) || 1)),
                  })
                }
              />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function buildInitialDivisions(
  state: WizardState,
  presets: Awaited<ReturnType<typeof api.leaguePresets>> | undefined,
): Divisions {
  if (state.setupMode === "quickstart") {
    const preset = presets?.quickstart_presets.find(
      (p) => p.preset_id === state.quickstartPresetId,
    );
    if (!preset) return state.divisions;
    const out: Divisions = {};
    for (const div of preset.divisions) {
      const existing = state.divisions[div] ?? [];
      out[div] = Array.from({ length: preset.teams_per_division }, (_, i) =>
        existing[i] ?? { city: "", name: "" },
      );
    }
    return out;
  }
  const divs = state.customDivisions
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const out: Divisions = {};
  for (const div of divs) {
    const existing = state.divisions[div] ?? [];
    out[div] = Array.from(
      { length: state.customTeamsPerDivision },
      (_, i) => existing[i] ?? { city: "", name: "" },
    );
  }
  return out;
}

// ---------------------------------------------------------------------------

function TeamsStep({
  state,
  onPatch,
}: {
  state: WizardState;
  onPatch: (u: Partial<WizardState>) => void;
}) {
  const [busyIdx, setBusyIdx] = useState<string | null>(null);
  const [randomizingAll, setRandomizingAll] = useState(false);

  async function randomize(division: string, idx: number) {
    const key = `${division}-${idx}`;
    setBusyIdx(key);
    try {
      const { city, name } = await api.randomTeamName();
      const next = { ...state.divisions };
      next[division] = next[division].map((t, i) =>
        i === idx ? { city, name } : t,
      );
      onPatch({ divisions: next });
    } catch {
      /* silently ignore — user can type by hand */
    } finally {
      setBusyIdx(null);
    }
  }

  async function randomizeAll() {
    setRandomizingAll(true);
    try {
      // Reset the name pool server-side so we don't get duplicates across
      // repeated randomize-all clicks.
      try {
        await api.resetRandomPool();
      } catch {
        /* ignore */
      }
      // Fill each slot as its name arrives and push an update immediately, so
      // the user sees progress instead of a frozen button — a preset can have
      // 20-30 teams, which is 20-30 sequential round-trips to the cloud.
      let next: Divisions = { ...state.divisions };
      for (const [div, teams] of Object.entries(state.divisions)) {
        for (let i = 0; i < teams.length; i++) {
          try {
            const { city, name } = await api.randomTeamName();
            next = {
              ...next,
              [div]: next[div].map((t, j) => (j === i ? { city, name } : t)),
            };
            onPatch({ divisions: next });
          } catch {
            /* keep the existing name for this slot */
          }
        }
      }
    } finally {
      setRandomizingAll(false);
    }
  }

  function updateTeam(division: string, idx: number, team: Team) {
    const next = { ...state.divisions };
    next[division] = next[division].map((t, i) => (i === idx ? team : t));
    onPatch({ divisions: next });
  }
  function addTeam(division: string) {
    const next = { ...state.divisions };
    next[division] = [...next[division], { city: "", name: "" }];
    onPatch({ divisions: next });
  }
  function removeTeam(division: string, idx: number) {
    const next = { ...state.divisions };
    next[division] = next[division].filter((_, i) => i !== idx);
    onPatch({ divisions: next });
  }

  const total = useMemo(
    () =>
      Object.values(state.divisions).reduce((acc, list) => acc + list.length, 0),
    [state.divisions],
  );

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Team rosters</CardTitle>
          <CardDescription>
            Enter a city + nickname for each team. Use Randomize for quick
            placeholder names.
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone="amber">{total} teams</Badge>
          <Button
            variant="outline"
            size="sm"
            onClick={randomizeAll}
            disabled={randomizingAll}
          >
            {randomizingAll ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Dice5 className="h-3 w-3" />
            )}
            {randomizingAll ? "Randomizing…" : "Randomize all"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {Object.entries(state.divisions).map(([division, teams]) => (
          <div key={division} className="rounded-xl border border-border bg-surfaceAlt/40 p-3">
            <div className="mb-2 flex items-center justify-between">
              <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
                {division} Division · {teams.length} teams
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => addTeam(division)}
              >
                <Plus className="h-3 w-3" /> Add team
              </Button>
            </div>
            <div className="space-y-2">
              {teams.map((team, idx) => {
                const key = `${division}-${idx}`;
                return (
                  <div
                    key={idx}
                    className="flex items-center gap-2"
                  >
                    <span className="w-6 shrink-0 font-mono text-xs text-muted">
                      {idx + 1}
                    </span>
                    <Input
                      className="flex-1"
                      placeholder="City"
                      value={team.city}
                      onChange={(e) =>
                        updateTeam(division, idx, { ...team, city: e.target.value })
                      }
                    />
                    <Input
                      className="flex-1"
                      placeholder="Nickname"
                      value={team.name}
                      onChange={(e) =>
                        updateTeam(division, idx, { ...team, name: e.target.value })
                      }
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => randomize(division, idx)}
                      disabled={busyIdx === key}
                      title="Randomize"
                    >
                      {busyIdx === key ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Dice5 className="h-3 w-3" />
                      )}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => removeTeam(division, idx)}
                      title="Remove team"
                    >
                      <Trash2 className="h-3 w-3 text-danger" />
                    </Button>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------

function RulesStep({
  state,
  onPatch,
  presets,
  commish,
}: {
  state: WizardState;
  onPatch: (u: Partial<WizardState>) => void;
  presets: Awaited<ReturnType<typeof api.leaguePresets>> | undefined;
  commish: CommissionerSettings | undefined;
}) {
  const [showAdvancedFinance, setShowAdvancedFinance] = useState(false);
  const [showFinanceModules, setShowFinanceModules] = useState(false);
  const [showFinanceAi, setShowFinanceAi] = useState(false);
  const [showScouting, setShowScouting] = useState(false);

  const moduleCatalog = commish?.options.finance_modules ?? [];
  const aiDefaults = commish?.options.finance_ai_tuning_defaults ?? {};

  function setModuleLevel(moduleId: string, level: string) {
    // Seed the full preset levels when leaving a preset for custom, so the
    // other modules keep the preset's values instead of reverting to off.
    const presetModules =
      state.financePreset !== "custom"
        ? commish?.options.finance_preset_profiles?.[state.financePreset]?.modules
        : undefined;
    const base = presetModules
      ? { ...state.financeModules, ...presetModules }
      : state.financeModules;
    onPatch({
      financeModules: { ...base, [moduleId]: level },
      // Editing module levels implies "custom" — mirrors the
      // commissioner page's behavior.
      financePreset: "custom",
    });
  }
  function setAiValue(key: string, raw: string) {
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) return;
    onPatch({
      financeAiTuning: { ...state.financeAiTuning, [key]: parsed },
      financePreset: "custom",
    });
  }
  function setScoutingValue(key: keyof ScoutingTuning, raw: string) {
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) return;
    onPatch({
      scoutingTuning: { ...state.scoutingTuning, [key]: parsed },
      scoutingTuningTouched: true,
    });
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Rules & settings</CardTitle>
          <CardDescription>
            Pick a rule preset, schedule length, finance + trade + injury knobs.
            Any of this can be changed later.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-1.5">
          <Label>Rule preset</Label>
          <select
            value={state.rulePresetId}
            onChange={(e) => onPatch({ rulePresetId: e.target.value })}
            className="h-10 w-full rounded-lg border border-border bg-canvas/60 px-3 text-sm focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
          >
            <option value="">None</option>
            {(presets?.rule_presets ?? []).map((p) => (
              <option key={p.preset_id} value={p.preset_id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label>Schedule template</Label>
          <select
            value={state.scheduleTemplateId}
            onChange={(e) => onPatch({ scheduleTemplateId: e.target.value })}
            className="h-10 w-full rounded-lg border border-border bg-canvas/60 px-3 text-sm focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
          >
            {(presets?.schedule_templates ?? []).map((t) => (
              <option key={t.template_id} value={t.template_id}>
                {t.name} ({t.games_per_team} games)
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-1.5">
          <Label>Injury level</Label>
          <div className="flex rounded-lg border border-border bg-surfaceAlt p-1">
            {(["off", "low", "normal"] as const).map((lvl) => (
              <button
                key={lvl}
                type="button"
                onClick={() => onPatch({ injuryLevel: lvl })}
                className={cn(
                  "flex-1 rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
                  state.injuryLevel === lvl
                    ? "bg-amber text-espresso"
                    : "text-muted hover:bg-surface hover:text-ink",
                )}
              >
                {lvl}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-1.5">
          <Label>Draft rounds</Label>
          <NumberField
            value={state.draftRounds}
            min={1}
            max={50}
            fallback={10}
            onCommit={(n) => onPatch({ draftRounds: n })}
          />
          <p className="text-[11px] text-muted">
            How many rounds your amateur draft runs. Typical MLB: 10–20.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label>Draft pool size</Label>
          <NumberField
            value={state.draftPoolSize}
            min={20}
            max={2000}
            step={10}
            fallback={200}
            onCommit={(n) => onPatch({ draftPoolSize: n })}
          />
          <p className="text-[11px] text-muted">
            Total prospects generated for the pool. Should comfortably exceed
            rounds × teams so undrafted players remain for later.
          </p>
        </div>

        <div className="space-y-1.5 md:col-span-2">
          <Label>Finance</Label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={state.financeEnabled}
              onChange={(e) => onPatch({ financeEnabled: e.target.checked })}
              className="h-4 w-4 accent-amber"
            />
            Enable finance module
          </label>
          {state.financeEnabled && (
            <>
              <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-2">
                <div className="space-y-1.5">
                  <Label className="text-xs font-normal text-muted">
                    Preset
                  </Label>
                  <select
                    value={state.financePreset}
                    onChange={(e) => {
                      const preset = e.target.value;
                      const profile =
                        commish?.options.finance_preset_profiles?.[preset];
                      if (profile) {
                        onPatch({
                          financePreset: preset,
                          financeEnforcement: profile.enforcement_mode,
                          financeModules: {
                            ...state.financeModules,
                            ...profile.modules,
                          },
                        });
                      } else {
                        onPatch({ financePreset: preset });
                      }
                    }}
                    className="h-10 w-full rounded-lg border border-border bg-canvas/60 px-3 text-sm focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
                  >
                    {(commish?.options.finance_presets ?? [
                      "simple",
                      "standard",
                      "mlb_like",
                      "off",
                      "custom",
                    ]).map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                  <p className="text-[11px] leading-snug text-muted">
                    {FINANCE_PRESET_DESCRIPTIONS[state.financePreset] ?? ""}
                  </p>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs font-normal text-muted">
                    Enforcement
                  </Label>
                  <select
                    value={state.financeEnforcement}
                    onChange={(e) =>
                      onPatch({ financeEnforcement: e.target.value })
                    }
                    className="h-10 w-full rounded-lg border border-border bg-canvas/60 px-3 text-sm focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
                  >
                    {(commish?.options.finance_enforcement ?? [
                      "off",
                      "on",
                    ]).map((m) => (
                      <option key={m} value={m}>
                        {FINANCE_LEVEL_LABELS[m] ?? m}
                      </option>
                    ))}
                  </select>
                  <p className="text-[11px] leading-snug text-muted">
                    {FINANCE_ENFORCEMENT_DESCRIPTIONS[state.financeEnforcement] ?? ""}
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={() => setShowAdvancedFinance((v) => !v)}
                className="mt-2 inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted hover:text-ink"
              >
                {showAdvancedFinance ? (
                  <ChevronDown className="h-3 w-3" />
                ) : (
                  <ChevronRight className="h-3 w-3" />
                )}
                Show advanced finance + scouting
              </button>

              {showAdvancedFinance && (
                <div className="mt-3 space-y-3">
                  {moduleCatalog.length > 0 && (
                    <div className="rounded-lg border border-border bg-surfaceAlt/40">
                      <button
                        type="button"
                        onClick={() => setShowFinanceModules((v) => !v)}
                        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm font-semibold"
                      >
                        <span className="inline-flex items-center gap-2">
                          {showFinanceModules ? (
                            <ChevronDown className="h-4 w-4" />
                          ) : (
                            <ChevronRight className="h-4 w-4" />
                          )}
                          Module levels
                        </span>
                        <span className="text-xs text-muted">
                          {moduleCatalog.length} modules · {state.financePreset}
                        </span>
                      </button>
                      {showFinanceModules && (
                        <div className="space-y-2 border-t border-border/60 px-3 py-3">
                          {moduleCatalog.map((m) => {
                            // When a non-custom preset is active, show its level
                            // directly so the display matches the selected preset.
                            const presetModules =
                              state.financePreset !== "custom"
                                ? commish?.options.finance_preset_profiles?.[
                                    state.financePreset
                                  ]?.modules
                                : undefined;
                            const level =
                              presetModules?.[m.id] ??
                              state.financeModules[m.id] ??
                              m.levels[0] ??
                              "off";
                            return (
                              <div
                                key={m.id}
                                className="grid grid-cols-1 items-start gap-2 md:grid-cols-[minmax(0,1fr)_180px]"
                              >
                                <div className="min-w-0">
                                  <div className="text-sm font-semibold">
                                    {m.label}
                                  </div>
                                  <div className="text-xs text-muted">
                                    {m.help}
                                  </div>
                                </div>
                                <select
                                  value={level}
                                  onChange={(e) =>
                                    setModuleLevel(m.id, e.target.value)
                                  }
                                  className="h-8 w-full rounded-md border border-border bg-canvas/60 px-2 text-xs text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
                                >
                                  {m.levels.map((lvl) => (
                                    <option key={lvl} value={lvl}>
                                      {FINANCE_LEVEL_LABELS[lvl] ?? lvl}
                                    </option>
                                  ))}
                                </select>
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
                        onClick={() => setShowFinanceAi((v) => !v)}
                        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm font-semibold"
                      >
                        <span className="inline-flex items-center gap-2">
                          {showFinanceAi ? (
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
                      {showFinanceAi && (
                        <div className="space-y-2 border-t border-border/60 px-3 py-3">
                          <p className="text-xs text-muted">
                            Star/underperformer thresholds, salary share caps,
                            arbitration raise %, free-agency avoidance bands.
                            Editing here forces the preset to "custom".
                          </p>
                          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                            {Object.entries(aiDefaults).map(([key, defValue]) => {
                              const value =
                                state.financeAiTuning[key] ?? Number(defValue);
                              return (
                                <div
                                  key={key}
                                  className="grid grid-cols-[minmax(0,1fr)_120px] items-center gap-2"
                                >
                                  <Label
                                    htmlFor={`wiz-ai-${key}`}
                                    className="text-xs font-normal text-muted"
                                  >
                                    {key.replace(/_/g, " ")}
                                  </Label>
                                  <input
                                    id={`wiz-ai-${key}`}
                                    type="number"
                                    step="any"
                                    value={value}
                                    onChange={(e) =>
                                      setAiValue(key, e.target.value)
                                    }
                                    className="h-8 w-full rounded-md border border-border bg-canvas/60 px-2 text-xs text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
                                  />
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  <div className="rounded-lg border border-border bg-surfaceAlt/40">
                    <button
                      type="button"
                      onClick={() => setShowScouting((v) => !v)}
                      className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm font-semibold"
                    >
                      <span className="inline-flex items-center gap-2">
                        {showScouting ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                        Scouting fog-of-war
                      </span>
                      <span className="text-xs text-muted">
                        {state.scoutingEnabled ? "enabled" : "disabled"}
                      </span>
                    </button>
                    {showScouting && (
                      <div className="space-y-3 border-t border-border/60 px-3 py-3">
                        <label className="flex cursor-pointer items-center justify-between gap-3 rounded-md border border-border bg-canvas/40 px-3 py-2">
                          <span className="text-sm font-semibold">
                            Scouting fog-of-war enabled
                          </span>
                          <input
                            type="checkbox"
                            checked={state.scoutingEnabled}
                            onChange={(e) =>
                              onPatch({ scoutingEnabled: e.target.checked })
                            }
                            className="h-4 w-4 accent-amber"
                          />
                        </label>
                        <p className="text-xs text-muted">
                          Hides player ratings until owners spend scouting
                          credits. Pace knobs apply whether finance is on or
                          off.
                        </p>
                        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                          {(
                            [
                              {
                                key: "base_monthly_credits",
                                label: "Base monthly credits",
                                step: 1,
                              },
                              {
                                key: "finance_off_multiplier",
                                label: "Finance-off pace multiplier",
                                step: 0.01,
                              },
                              {
                                key: "monthly_decay",
                                label: "Monthly decay",
                                step: 0.001,
                              },
                              {
                                key: "passive_gain",
                                label: "Passive gain",
                                step: 0.001,
                              },
                              {
                                key: "max_banked_credits",
                                label: "Max banked credits",
                                step: 1,
                              },
                              {
                                key: "auto_spend_cap",
                                label: "Auto spend cap",
                                step: 1,
                              },
                            ] as Array<{
                              key: keyof ScoutingTuning;
                              label: string;
                              step: number;
                            }>
                          ).map(({ key, label, step }) => (
                            <div key={key} className="space-y-1.5">
                              <Label
                                htmlFor={`wiz-scout-${key}`}
                                className="text-xs font-normal text-muted"
                              >
                                {label}
                              </Label>
                              <input
                                id={`wiz-scout-${key}`}
                                type="number"
                                step={step}
                                value={state.scoutingTuning[key]}
                                onChange={(e) =>
                                  setScoutingValue(key, e.target.value)
                                }
                                className="h-8 w-full rounded-md border border-border bg-canvas/60 px-2 text-xs text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
                              />
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        <div className="space-y-1.5 md:col-span-2">
          <Label>Trading</Label>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            <Checkbox
              label="Trades enabled"
              checked={state.tradesEnabled}
              onChange={(v) => onPatch({ tradesEnabled: v })}
            />
            <Checkbox
              label="Draft-pick trading"
              checked={state.draftPickTradingEnabled}
              onChange={(v) => onPatch({ draftPickTradingEnabled: v })}
            />
            <Checkbox
              label="CPU-initiated offers"
              checked={state.cpuInitiatedTrades}
              onChange={(v) => onPatch({ cpuInitiatedTrades: v })}
            />
            <div className="space-y-1.5">
              <Label>CPU proposal cadence</Label>
              <select
                value={state.cpuProposalCadence}
                onChange={(e) =>
                  onPatch({ cpuProposalCadence: e.target.value })
                }
                disabled={!state.cpuInitiatedTrades}
                className="h-10 w-full rounded-lg border border-border bg-canvas/60 px-3 text-sm focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40 disabled:opacity-50"
              >
                {["off", "low", "normal", "high"].map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 rounded-lg border border-border bg-surfaceAlt/40 px-3 py-2 text-sm cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-amber"
      />
      {label}
    </label>
  );
}

// ---------------------------------------------------------------------------

function ReviewStep({
  state,
  presets,
  creating,
  error,
  onCreate,
}: {
  state: WizardState;
  presets: Awaited<ReturnType<typeof api.leaguePresets>> | undefined;
  creating: boolean;
  error: string | null;
  onCreate: () => void;
}) {
  useEffect(() => {
    void presets;
    void onCreate;
  }, [presets, onCreate]);
  const total = Object.values(state.divisions).reduce(
    (acc, list) => acc + list.length,
    0,
  );
  const rule = presets?.rule_presets.find(
    (p) => p.preset_id === state.rulePresetId,
  );
  const template = presets?.schedule_templates.find(
    (t) => t.template_id === state.scheduleTemplateId,
  );
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Review</CardTitle>
          <CardDescription>
            Confirm the setup below, then click Create league.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <ReviewRow label="League name" value={state.displayName || "—"} />
        <ReviewRow
          label="Mode"
          value={state.mode === "owner_league" ? "Multi-owner" : "Single-player"}
        />
        {state.templateLeagueId && (
          <ReviewRow label="Clone from" value={state.templateLeagueId} />
        )}
        <ReviewRow label="Setup mode" value={state.setupMode} />
        <ReviewRow
          label="Teams"
          value={`${total} across ${Object.keys(state.divisions).length} divisions`}
        />
        {rule && <ReviewRow label="Rule preset" value={rule.name} />}
        {template && (
          <ReviewRow
            label="Schedule"
            value={`${template.name} (${template.games_per_team} games)`}
          />
        )}
        <ReviewRow label="Injury level" value={state.injuryLevel} />
        <ReviewRow
          label="Finance"
          value={
            state.financeEnabled
              ? `${state.financePreset} · ${state.financeEnforcement}${
                  Object.keys(state.financeModules).length > 0
                    ? ` · ${Object.keys(state.financeModules).length} module overrides`
                    : ""
                }${
                  Object.keys(state.financeAiTuning).length > 0
                    ? ` · ${Object.keys(state.financeAiTuning).length} AI knobs`
                    : ""
                }`
              : "disabled"
          }
        />
        <ReviewRow
          label="Scouting fog-of-war"
          value={
            state.scoutingEnabled
              ? state.scoutingTuningTouched
                ? "enabled · custom pacing"
                : "enabled · default pacing"
              : "disabled"
          }
        />
        <ReviewRow
          label="Trades"
          value={
            state.tradesEnabled
              ? `on${state.draftPickTradingEnabled ? " + draft picks" : ""} · CPU ${state.cpuInitiatedTrades ? state.cpuProposalCadence : "off"}`
              : "disabled"
          }
        />
        {error && (
          <div className="mt-3 flex items-center gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            <AlertTriangle className="h-4 w-4" />
            {error}
          </div>
        )}
        {creating && (
          <div className="mt-3 flex items-center gap-2 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" />
            Creating league…
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border/40 py-2 last:border-b-0">
      <span className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">
        {label}
      </span>
      <span className="text-right font-semibold">{value}</span>
    </div>
  );
}
