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
  Dice5,
  Loader2,
  Lock,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";

import { api } from "@/lib/api";
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

interface WizardState {
  displayName: string;
  mode: "single_player" | "owner_league";
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
  templateLeagueId: "",
  setupMode: "quickstart",
  quickstartPresetId: "",
  customDivisions: "East, West",
  customTeamsPerDivision: 4,
  divisions: {},
  rulePresetId: "",
  scheduleTemplateId: "",
  financeEnabled: false,
  financePreset: "off",
  financeEnforcement: "warn",
  tradesEnabled: true,
  draftPickTradingEnabled: false,
  cpuInitiatedTrades: true,
  cpuProposalCadence: "normal",
  injuryLevel: "normal",
  draftRounds: 10,
  draftPoolSize: 200,
};

export function LeagueCreatePage() {
  const [params] = useSearchParams();
  const isFirstRun = params.get("first-run") === "1";
  const role = useAuthStore((s) => s.role);
  const navigate = useNavigate();

  // Admin-only once past first-run bootstrap.
  if (!isFirstRun && role !== "admin") {
    return <Navigate to="/home" replace />;
  }

  const [step, setStep] = useState(isFirstRun ? 0 : 1);
  const [state, setState] = useState<WizardState>(INITIAL);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const presets = useQuery({
    queryKey: ["league-presets"],
    queryFn: () => api.leaguePresets(),
    enabled: role === "admin",
  });
  const existingLeagues = useQuery({
    queryKey: ["leagues"],
    queryFn: () => api.listLeagues(),
    enabled: role === "admin",
  });

  const stepLabels = isFirstRun
    ? ["Admin", "Basics", "Setup", "Teams", "Rules", "Review"]
    : ["Basics", "Setup", "Teams", "Rules", "Review"];

  function patch(update: Partial<WizardState>) {
    setState((prev) => ({ ...prev, ...update }));
  }

  async function handleCreate() {
    setCreating(true);
    setCreateError(null);
    try {
      const divisions = state.divisions;
      await api.createLeague({
        display_name: state.displayName,
        mode: state.mode,
        template_league_id: state.templateLeagueId || undefined,
        divisions,
        rule_preset_id: state.rulePresetId || undefined,
        schedule_template_id: state.scheduleTemplateId || undefined,
        finance: {
          enabled: state.financeEnabled,
          preset: state.financePreset,
          enforcement_mode: state.financeEnforcement,
        },
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
      });
      // Land the user on the league picker.
      navigate("/select-league", { replace: true });
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
    // Reset the name pool server-side so we don't get duplicates across
    // repeated randomize-all clicks.
    try {
      await api.resetRandomPool();
    } catch {
      /* ignore */
    }
    const next: Divisions = {};
    for (const [div, teams] of Object.entries(state.divisions)) {
      next[div] = [];
      for (let i = 0; i < teams.length; i++) {
        try {
          const { city, name } = await api.randomTeamName();
          next[div].push({ city, name });
        } catch {
          next[div].push(teams[i]);
        }
      }
    }
    onPatch({ divisions: next });
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
          <Button variant="outline" size="sm" onClick={randomizeAll}>
            <Dice5 className="h-3 w-3" /> Randomize all
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
}: {
  state: WizardState;
  onPatch: (u: Partial<WizardState>) => void;
  presets: Awaited<ReturnType<typeof api.leaguePresets>> | undefined;
}) {
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
            <option value="">None</option>
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
          <Input
            type="number"
            min={1}
            max={50}
            value={state.draftRounds}
            onChange={(e) =>
              onPatch({
                draftRounds: Math.max(
                  1,
                  Math.min(50, Number(e.target.value) || 10),
                ),
              })
            }
          />
          <p className="text-[11px] text-muted">
            How many rounds your amateur draft runs. Typical MLB: 10–20.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label>Draft pool size</Label>
          <Input
            type="number"
            min={20}
            max={2000}
            step={10}
            value={state.draftPoolSize}
            onChange={(e) =>
              onPatch({
                draftPoolSize: Math.max(
                  20,
                  Math.min(2000, Number(e.target.value) || 200),
                ),
              })
            }
          />
          <p className="text-[11px] text-muted">
            Total prospects generated for the pool. Should comfortably exceed
            rounds × teams so undrafted players remain for later.
          </p>
        </div>

        <div className="space-y-1.5">
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
            <div className="mt-2 grid grid-cols-2 gap-2">
              <select
                value={state.financePreset}
                onChange={(e) => onPatch({ financePreset: e.target.value })}
                className="h-10 rounded-lg border border-border bg-canvas/60 px-3 text-sm focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
              >
                {["simple", "standard", "mlb_like", "off", "custom"].map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
              <select
                value={state.financeEnforcement}
                onChange={(e) =>
                  onPatch({ financeEnforcement: e.target.value })
                }
                className="h-10 rounded-lg border border-border bg-canvas/60 px-3 text-sm focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
              >
                {["off", "warn", "block"].map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
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
              ? `${state.financePreset} · ${state.financeEnforcement}`
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
