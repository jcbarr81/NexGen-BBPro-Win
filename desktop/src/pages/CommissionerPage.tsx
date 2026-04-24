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
  Command,
  DollarSign,
  GraduationCap,
  HeartPulse,
  Inbox,
  ListChecks,
  Loader2,
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

function StrategyCard({ data }: { data: CommissionerSettings }) {
  const queryClient = useQueryClient();
  const profiles = data.options.strategy_profiles ?? [];
  const teamsQ = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
  });

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
            <table className="w-full text-sm">
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
            </table>
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
      to: "/change-requests",
      label: "Change Requests",
      description: "Owner-submitted bundles",
      Icon: Inbox,
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
