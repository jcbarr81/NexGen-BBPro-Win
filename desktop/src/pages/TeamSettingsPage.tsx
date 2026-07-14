/**
 * Phase 4 port of ui/team_settings_dialog.py.
 *
 * Edit the per-team configuration owners care about:
 * - Primary + secondary jersey colors (hex, with a swatch preview)
 * - Stadium (free-text or pick from the ballpark catalog)
 * - Team strategy profile (or inherit league default)
 * - Auto-reassign override (enabled / disabled / inherit)
 *
 * Saves call into utils.team_loader.save_team_settings (validates colors)
 * plus services.team_strategy_profiles.set_team_strategy_profile and
 * services.team_auto_reassign_settings.set_team_auto_reassign on the server.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Building2,
  Loader2,
  Palette,
  RotateCcw,
  Save,
  Settings as SettingsIcon,
  ShieldCheck,
} from "lucide-react";

import { api, type TeamSettingsPatch } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { useActiveTeamColor } from "@/lib/team-colors";
import { useHotkey } from "@/lib/use-hotkey";
import { useTeams } from "@/lib/use-teams";
import { AppShell } from "@/components/layout/AppShell";
import { ParkBrowser } from "@/components/park/ParkBrowser";
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

export function TeamSettingsPage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;
  const teams = useTeams({ enabled: !teamId });
  const activeTeamId = teamId ?? teams.data?.[0]?.team_id ?? null;
  const teamAccentColor = useActiveTeamColor(activeTeamId ?? undefined);

  if (!activeTeamId) {
    return (
      <AppShell title="Team Settings">
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
      title="Team Settings"
      subtitle={`Team ${activeTeamId} · colors, stadium, strategy`}
      teamAccentColor={teamAccentColor}
    >
      <SettingsEditor teamId={activeTeamId} />
    </AppShell>
  );
}

function SettingsEditor({ teamId }: { teamId: string }) {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ["team-settings", teamId],
    queryFn: () => api.getTeamSettings(teamId),
  });

  const [parkBrowserOpen, setParkBrowserOpen] = useState(false);

  const [draft, setDraft] = useState<{
    primary_color: string;
    secondary_color: string;
    stadium: string;
    strategy: string;
    auto_reassign: "default" | "enabled" | "disabled";
  } | null>(null);

  useEffect(() => {
    if (settings.data) {
      const s = settings.data;
      setDraft({
        primary_color: s.primary_color || "#000000",
        secondary_color: s.secondary_color || "#FFFFFF",
        stadium: s.stadium || "",
        strategy:
          s.strategy.source === "team_override" ? s.strategy.profile : "",
        auto_reassign:
          s.auto_reassign.source === "team_override"
            ? s.auto_reassign.enabled
              ? "enabled"
              : "disabled"
            : "default",
      });
    }
  }, [settings.data]);

  const save = useMutation({
    mutationFn: (payload: TeamSettingsPatch) =>
      api.saveTeamSettings(teamId, payload),
    onSuccess: (data) => {
      queryClient.setQueryData(["team-settings", teamId], data);
      // Team metadata is referenced everywhere; nuke the relevant caches.
      queryClient.invalidateQueries({ queryKey: ["teams"] });
      queryClient.invalidateQueries({ queryKey: ["team", teamId] });
      queryClient.invalidateQueries({ queryKey: ["league-standings"] });
    },
  });

  const dirty = useMemo(() => {
    if (!settings.data || !draft) return false;
    const s = settings.data;
    const initialStrategy =
      s.strategy.source === "team_override" ? s.strategy.profile : "";
    const initialAuto: "default" | "enabled" | "disabled" =
      s.auto_reassign.source === "team_override"
        ? s.auto_reassign.enabled
          ? "enabled"
          : "disabled"
        : "default";
    return (
      draft.primary_color !== (s.primary_color || "#000000") ||
      draft.secondary_color !== (s.secondary_color || "#FFFFFF") ||
      draft.stadium !== (s.stadium || "") ||
      draft.strategy !== initialStrategy ||
      draft.auto_reassign !== initialAuto
    );
  }, [draft, settings.data]);

  useHotkey(
    "mod+s",
    () => {
      if (dirty && !save.isPending && draft) {
        save.mutate({
          primary_color: draft.primary_color,
          secondary_color: draft.secondary_color,
          stadium: draft.stadium,
          strategy: draft.strategy,
          auto_reassign: draft.auto_reassign,
        });
      }
    },
    { enabled: !!draft && dirty && !save.isPending },
  );

  if (settings.isLoading) {
    return <LoadingCard />;
  }
  if (settings.isError) {
    return <ErrorCard message={(settings.error as Error).message} />;
  }
  if (!settings.data || !draft) return null;

  const data = settings.data;

  return (
    <div className="space-y-6">
      {save.isError && (
        <div className="flex items-center gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          <AlertTriangle className="h-4 w-4" />
          {(save.error as Error).message}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Identity</CardTitle>
              <CardDescription>
                Hex colors and home ballpark.
              </CardDescription>
            </div>
            <Badge tone="amber">
              <Palette className="h-3 w-3" />
              {data.abbreviation}
            </Badge>
          </CardHeader>
          <CardContent className="space-y-4">
            <ColorRow
              label="Primary color"
              value={draft.primary_color}
              onChange={(v) => setDraft({ ...draft, primary_color: v })}
            />
            <ColorRow
              label="Secondary color"
              value={draft.secondary_color}
              onChange={(v) => setDraft({ ...draft, secondary_color: v })}
            />

            <div className="space-y-1.5">
              <Label htmlFor="stadium">Stadium</Label>
              <div className="flex gap-2">
                <Input
                  id="stadium"
                  list="ballpark-list"
                  value={draft.stadium}
                  onChange={(e) =>
                    setDraft({ ...draft, stadium: e.target.value })
                  }
                  placeholder="Park name"
                />
                <Button
                  type="button"
                  variant="secondary"
                  size="icon"
                  onClick={() => setParkBrowserOpen(true)}
                  title="Browse ballpark catalog with previews"
                >
                  <Building2 className="h-4 w-4" />
                </Button>
              </div>
              {data.options.ballparks.length > 0 && (
                <datalist id="ballpark-list">
                  {data.options.ballparks.map((park) => (
                    <option key={park} value={park} />
                  ))}
                </datalist>
              )}
            </div>

            <ParkBrowser
              open={parkBrowserOpen}
              onOpenChange={setParkBrowserOpen}
              currentStadium={draft.stadium}
              onSelect={(park) =>
                setDraft({ ...draft, stadium: park.name })
              }
            />

            <SwatchPreview
              primary={draft.primary_color}
              secondary={draft.secondary_color}
              abbrev={data.abbreviation}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Strategy & Automation</CardTitle>
              <CardDescription>
                How CPU + automation handle this team.
              </CardDescription>
            </div>
            <Badge tone="neutral">
              <SettingsIcon className="h-3 w-3" /> {data.strategy.label}
            </Badge>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-1.5">
              <Label htmlFor="strategy">Team strategy profile</Label>
              <select
                id="strategy"
                value={draft.strategy}
                onChange={(e) =>
                  setDraft({ ...draft, strategy: e.target.value })
                }
                className="h-10 w-full rounded-lg border border-border bg-canvas/60 px-3 text-sm text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
              >
                <option value="">
                  Use league default ({data.options.default_strategy})
                </option>
                {data.options.strategies.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted">
                {(
                  data.options.strategies.find(
                    (s) => s.id === (draft.strategy || data.strategy.profile),
                  ) ?? { description: "" }
                ).description}
              </p>
            </div>

            <div className="space-y-1.5">
              <Label>Auto-reassign roster after moves</Label>
              <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
                {(
                  [
                    { val: "default", label: "League default" },
                    { val: "enabled", label: "Enabled" },
                    { val: "disabled", label: "Disabled" },
                  ] as const
                ).map((opt) => (
                  <button
                    key={opt.val}
                    type="button"
                    onClick={() =>
                      setDraft({ ...draft, auto_reassign: opt.val })
                    }
                    className={cn(
                      "flex-1 rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
                      draft.auto_reassign === opt.val
                        ? "bg-amber text-espresso"
                        : "text-muted hover:bg-surface hover:text-ink",
                    )}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
              <p className="flex items-center gap-1 text-xs text-muted">
                <ShieldCheck className="h-3 w-3" />
                Currently {data.auto_reassign.enabled ? "on" : "off"} ·{" "}
                source: {data.auto_reassign.source}
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="flex items-center justify-end gap-3">
        <Button
          variant="ghost"
          onClick={() => settings.refetch()}
          disabled={save.isPending}
        >
          <RotateCcw className="h-4 w-4" />
          Discard changes
        </Button>
        <Button
          onClick={() =>
            save.mutate({
              primary_color: draft.primary_color,
              secondary_color: draft.secondary_color,
              stadium: draft.stadium,
              strategy: draft.strategy,
              auto_reassign: draft.auto_reassign,
            })
          }
          disabled={!dirty || save.isPending}
        >
          {save.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          Save settings
        </Button>
      </div>
    </div>
  );
}

function ColorRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <div className="flex items-center gap-2">
        <input
          type="color"
          value={normalizeHex(value)}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          className="h-9 w-12 cursor-pointer rounded-md border border-border bg-canvas/60 p-1"
          aria-label={label}
        />
        <Input
          value={value}
          maxLength={7}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          className="flex-1 font-mono"
          spellCheck={false}
        />
      </div>
    </div>
  );
}

function SwatchPreview({
  primary,
  secondary,
  abbrev,
}: {
  primary: string;
  secondary: string;
  abbrev: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surfaceAlt/40 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
        Preview
      </div>
      <div className="mt-2 flex items-center gap-3">
        <div
          className="flex h-14 w-14 items-center justify-center rounded-lg font-display text-lg font-bold"
          style={{
            backgroundColor: normalizeHex(primary),
            color: normalizeHex(secondary),
          }}
        >
          {abbrev || "—"}
        </div>
        <div className="space-y-0.5 font-mono text-xs">
          <div>{primary}</div>
          <div className="text-muted">{secondary}</div>
        </div>
      </div>
    </div>
  );
}

function normalizeHex(value: string): string {
  if (!value) return "#000000";
  let v = value.trim();
  if (!v.startsWith("#")) v = `#${v}`;
  if (/^#[0-9a-fA-F]{6}$/.test(v)) return v.toUpperCase();
  if (/^#[0-9a-fA-F]{3}$/.test(v)) {
    const r = v[1]!;
    const g = v[2]!;
    const b = v[3]!;
    return `#${r}${r}${g}${g}${b}${b}`.toUpperCase();
  }
  return "#000000";
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

