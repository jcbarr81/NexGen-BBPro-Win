/**
 * Phase 4 port of ui/team_settings_dialog.py.
 *
 * Edit the per-team configuration owners care about:
 * - Primary + secondary jersey colors (hex, with a swatch preview)
 * - Stadium (free-text or pick from the ballpark catalog). Only a park
 *   picked from the catalog plays with real dimensions (audit L13).
 * - Team strategy profile (or inherit league default)
 * - Auto-reassign override (enabled / disabled / inherit)
 * - Game-day play settings (Release 3): auto rest days, similar-position
 *   rest substitutes, automatic activation from the 15- and 60-day IL
 *
 * Saves call into utils.team_loader.save_team_settings (validates colors)
 * plus services.team_strategy_profiles.set_team_strategy_profile and
 * services.team_auto_reassign_settings.set_team_auto_reassign on the server;
 * play settings go to services.team_play_settings via PUT .../settings/play,
 * and only when they changed.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Building2,
  CalendarClock,
  Info,
  Loader2,
  Palette,
  RotateCcw,
  Save,
  Settings as SettingsIcon,
  ShieldCheck,
} from "lucide-react";

import {
  api,
  type TeamPlaySettingKey,
  type TeamPlaySettings,
  type TeamPlaySettingsPatch,
  type TeamSettings,
  type TeamSettingsPatch,
} from "@/lib/api";
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
      subtitle={`Team ${activeTeamId} · colors, stadium, strategy, game day`}
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
    // Catalog park picked in the browser during this edit; null = not
    // picked (the server then decides from the stadium name). Audit L13.
    park_id: string | null;
    strategy: string;
    auto_reassign: "default" | "enabled" | "disabled";
    play: Record<TeamPlaySettingKey, PlayChoice>;
  } | null>(null);

  useEffect(() => {
    if (settings.data) {
      const s = settings.data;
      setDraft({
        primary_color: s.primary_color || "#000000",
        secondary_color: s.secondary_color || "#FFFFFF",
        stadium: s.stadium || "",
        park_id: null,
        strategy:
          s.strategy.source === "team_override" ? s.strategy.profile : "",
        auto_reassign:
          s.auto_reassign.source === "team_override"
            ? s.auto_reassign.enabled
              ? "enabled"
              : "disabled"
            : "default",
        play: playChoices(s.play),
      });
    }
  }, [settings.data]);

  const save = useMutation({
    mutationFn: async ({
      main,
      play,
    }: {
      main: TeamSettingsPatch | null;
      play: TeamPlaySettingsPatch | null;
    }): Promise<TeamSettings | undefined> => {
      // Play settings have their own endpoint, so a play-only change never
      // rewrites the team's colors/stadium row.
      let data = main ? await api.saveTeamSettings(teamId, main) : settings.data;
      if (play && data) {
        const playData = await api.saveTeamPlaySettings(teamId, play);
        data = { ...data, play: playData };
      }
      return data;
    },
    onSuccess: (data, vars) => {
      if (data) queryClient.setQueryData(["team-settings", teamId], data);
      if (vars.main) {
        // Team metadata is referenced everywhere; nuke the relevant caches.
        queryClient.invalidateQueries({ queryKey: ["teams"] });
        queryClient.invalidateQueries({ queryKey: ["team", teamId] });
        queryClient.invalidateQueries({ queryKey: ["league-standings"] });
      }
    },
  });

  const playDirty = useMemo(() => {
    if (!settings.data || !draft) return false;
    const initial = playChoices(settings.data.play);
    return PLAY_SETTINGS.some((spec) => draft.play[spec.key] !== initial[spec.key]);
  }, [draft, settings.data]);

  const mainDirty = useMemo(() => {
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
      (draft.park_id !== null && draft.park_id !== (s.park_id ?? "")) ||
      draft.strategy !== initialStrategy ||
      draft.auto_reassign !== initialAuto
    );
  }, [draft, settings.data]);

  const dirty = mainDirty || playDirty;

  const payloadFromDraft = (
    d: NonNullable<typeof draft>,
  ): TeamSettingsPatch => ({
    primary_color: d.primary_color,
    secondary_color: d.secondary_color,
    stadium: d.stadium,
    // Send park_id only for a browser pick, so a plain rename lets the
    // server match the name against the catalog itself.
    ...(d.park_id !== null ? { park_id: d.park_id } : {}),
    strategy: d.strategy,
    auto_reassign: d.auto_reassign,
  });

  const playPatchFromDraft = (
    d: NonNullable<typeof draft>,
  ): TeamPlaySettingsPatch => {
    const patch: TeamPlaySettingsPatch = {};
    for (const spec of PLAY_SETTINGS) {
      const choice = d.play[spec.key];
      patch[spec.key] = choice === "default" ? "default" : choice === "on";
    }
    return patch;
  };

  const saveDraft = (d: NonNullable<typeof draft>) =>
    save.mutate({
      main: mainDirty ? payloadFromDraft(d) : null,
      play: playDirty ? playPatchFromDraft(d) : null,
    });

  useHotkey(
    "mod+s",
    () => {
      if (dirty && !save.isPending && draft) {
        saveDraft(draft);
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
                    setDraft({
                      ...draft,
                      stadium: e.target.value,
                      park_id: null,
                    })
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
              {data.park_id !== null && (
                <p className="text-xs text-muted">
                  {data.park
                    ? `Plays with the real dimensions of ${data.park.name} (${data.park.year}).`
                    : "Generic park dimensions. Pick a park from the catalog to play in its real dimensions."}
                </p>
              )}
            </div>

            <ParkBrowser
              open={parkBrowserOpen}
              onOpenChange={setParkBrowserOpen}
              currentStadium={draft.stadium}
              onSelect={(park) =>
                setDraft({
                  ...draft,
                  stadium: park.name,
                  park_id: park.park_id || null,
                })
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

      <GameDayCard
        play={data.play}
        choices={draft.play}
        onChange={(key, choice) =>
          setDraft({ ...draft, play: { ...draft.play, [key]: choice } })
        }
      />

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
          onClick={() => saveDraft(draft)}
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

// --- Game-day play settings (Release 3) -----------------------------------

type PlayChoice = "default" | "on" | "off";

interface PlaySettingSpec {
  key: TeamPlaySettingKey;
  label: string;
  on: string;
  off: string;
  /** Where the default comes from, when it is not a fixed value. */
  defaultSource?: string;
}

const PLAY_SETTINGS: PlaySettingSpec[] = [
  {
    key: "auto_rest_days",
    label: "Auto rest days",
    on:
      "Before each game the sim sits a worn-down regular (a catcher after a " +
      "long run of starts, any player whose fatigue is high) and starts a " +
      "bench player instead. Your saved lineup is not changed; he is back " +
      "the next day.",
    off:
      "Your lineup plays as saved, tired or not. A tired regular plays " +
      "worse and carries a small extra injury risk.",
  },
  {
    key: "rest_subs_similar_positions",
    label: "Rest substitutes at similar positions",
    on:
      "When a regular must rest and nobody on the bench lists his position, " +
      "the sim may use a bench player from a similar position (LF/RF, CF to " +
      "a corner, SS to 2B/3B, any infielder to 1B), at most one per game. " +
      "He fields a little worse out of position.",
    off:
      "Only bench players who list the position can substitute. If there " +
      "is none, the regular plays.",
  },
  {
    key: "il_auto_activate_15",
    label: "Activate automatically from the 10/15-day IL",
    on:
      "When a short-term stint is up and the player is healthy, the sim " +
      "moves him back to the active roster. With no room, he goes to AAA " +
      "and you get a \"ready, make room\" item; the sim never moves anyone " +
      "else to make room.",
    off:
      "He waits on the injured list until you activate him from the " +
      "Injuries page.",
    defaultSource: "the league's injured-list setting",
  },
  {
    key: "il_auto_activate_60",
    label: "Activate automatically from the 60-day IL",
    on:
      "The same for the 60-day list: a returning player comes back to the " +
      "active roster, or to AAA with a \"ready, make room\" item when " +
      "there is no room.",
    off: "60-day returns wait for you to activate them.",
  },
];

function playChoices(
  play: TeamPlaySettings | undefined,
): Record<TeamPlaySettingKey, PlayChoice> {
  const out = {} as Record<TeamPlaySettingKey, PlayChoice>;
  for (const spec of PLAY_SETTINGS) {
    const chosen = play?.overrides?.[spec.key];
    out[spec.key] = chosen === undefined ? "default" : chosen ? "on" : "off";
  }
  return out;
}

function GameDayCard({
  play,
  choices,
  onChange,
}: {
  play: TeamPlaySettings | undefined;
  choices: Record<TeamPlaySettingKey, PlayChoice>;
  onChange: (key: TeamPlaySettingKey, choice: PlayChoice) => void;
}) {
  if (!play) return null;
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Game day</CardTitle>
          <CardDescription>
            How the sim handles rest and injured-list returns for your club.
            Changes apply from the next game.
          </CardDescription>
        </div>
        <Badge tone="neutral">
          <CalendarClock className="h-3 w-3" /> Owner choices
        </Badge>
      </CardHeader>
      <CardContent className="space-y-5">
        {play.owner_managed === false && (
          <div className="flex items-start gap-2 rounded-md border border-info/40 bg-info/10 p-3 text-xs text-ink">
            <Info className="mt-0.5 h-3 w-3 shrink-0" />
            <span>
              This club is CPU-run, so the sim ignores these choices: CPU clubs
              always rest tired regulars, use similar-position substitutes and
              activate players from the injured list automatically. They take
              effect once an owner runs the team.
            </span>
          </div>
        )}
        {PLAY_SETTINGS.map((spec) => {
          const choice = choices[spec.key];
          const defaultOn = play.defaults[spec.key];
          const effectiveOn = choice === "default" ? defaultOn : choice === "on";
          const options: { val: PlayChoice; label: string }[] = [
            { val: "default", label: `Default (${defaultOn ? "on" : "off"})` },
            { val: "on", label: "On" },
            { val: "off", label: "Off" },
          ];
          return (
            <div key={spec.key} className="space-y-1.5">
              <Label>{spec.label}</Label>
              <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
                {options.map((opt) => (
                  <button
                    key={opt.val}
                    type="button"
                    onClick={() => onChange(spec.key, opt.val)}
                    aria-pressed={choice === opt.val}
                    className={cn(
                      "flex-1 rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
                      choice === opt.val
                        ? "bg-amber text-espresso"
                        : "text-muted hover:bg-surface hover:text-ink",
                    )}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
              <p className="text-xs text-muted">
                <span className="font-semibold text-ink">
                  {effectiveOn ? "On: " : "Off: "}
                </span>
                {effectiveOn ? spec.on : spec.off}
              </p>
              {choice === "default" && spec.defaultSource && (
                <p className="text-xs text-muted">
                  The default follows {spec.defaultSource}, so it changes if
                  the commissioner changes that.
                </p>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
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

