/**
 * Phase 4 port of ui/training_focus_dialog.py.
 *
 * Two-track allocator: hitters and pitchers each split 100% across their
 * respective focus tracks. The Save button is disabled until both groups
 * sum to exactly 100. "Reset to defaults" clears the team override and
 * inherits whatever the league-wide defaults are.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Loader2,
  RotateCcw,
  Save,
  Sparkles,
  Target,
} from "lucide-react";

import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { useActiveTeamColor } from "@/lib/team-colors";
import { useHotkey } from "@/lib/use-hotkey";
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

const TRACK_LABEL: Record<string, string> = {
  contact: "Contact",
  power: "Power",
  speed: "Speed",
  discipline: "Discipline",
  defense: "Defense",
  command: "Command",
  movement: "Movement",
  stamina: "Stamina",
  velocity: "Velocity",
  hold: "Hold Runners",
  pitch_lab: "Pitch Lab",
};

const MIN_PERCENT = 5;

export function TrainingPage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;

  const teams = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
    enabled: !teamId,
  });
  const activeTeamId = teamId ?? teams.data?.[0]?.team_id ?? null;
  const teamAccentColor = useActiveTeamColor(activeTeamId ?? undefined);

  if (!activeTeamId) {
    return (
      <AppShell title="Training">
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
      title="Training Focus"
      subtitle={`Team ${activeTeamId} · split 100% across each group`}
      teamAccentColor={teamAccentColor}
    >
      <TrainingEditor teamId={activeTeamId} />
    </AppShell>
  );
}

function TrainingEditor({ teamId }: { teamId: string }) {
  const queryClient = useQueryClient();
  const focus = useQuery({
    queryKey: ["training", teamId],
    queryFn: () => api.getTraining(teamId),
  });

  const [hitters, setHitters] = useState<Record<string, number>>({});
  const [pitchers, setPitchers] = useState<Record<string, number>>({});
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (focus.data) {
      setHitters({ ...focus.data.hitters });
      setPitchers({ ...focus.data.pitchers });
      setDirty(false);
    }
  }, [focus.data]);

  const save = useMutation({
    mutationFn: (payload: {
      hitters: Record<string, number>;
      pitchers: Record<string, number>;
    }) => api.saveTraining(teamId, payload),
    onSuccess: (data) => {
      queryClient.setQueryData(["training", teamId], data);
      setDirty(false);
    },
  });
  const reset = useMutation({
    mutationFn: () => api.resetTraining(teamId),
    onSuccess: (data) => {
      queryClient.setQueryData(["training", teamId], data);
      setDirty(false);
    },
  });

  useHotkey(
    "mod+s",
    () => {
      if (dirty && !save.isPending) save.mutate({ hitters, pitchers });
    },
    { enabled: dirty && !save.isPending },
  );

  function update(group: "hitters" | "pitchers", track: string, value: number) {
    const setter = group === "hitters" ? setHitters : setPitchers;
    setter((prev) => ({ ...prev, [track]: value }));
    setDirty(true);
  }

  function autoBalance(group: "hitters" | "pitchers") {
    const tracks =
      group === "hitters"
        ? focus.data?.tracks.hitters ?? []
        : focus.data?.tracks.pitchers ?? [];
    if (tracks.length === 0) return;
    const each = Math.floor(100 / tracks.length);
    const remainder = 100 - each * tracks.length;
    const next: Record<string, number> = {};
    tracks.forEach((track, i) => {
      next[track] = each + (i < remainder ? 1 : 0);
    });
    if (group === "hitters") setHitters(next);
    else setPitchers(next);
    setDirty(true);
  }

  if (focus.isLoading) return <LoadingCard />;
  if (focus.isError)
    return <ErrorCard message={(focus.error as Error).message} />;
  if (!focus.data) return null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <Badge tone={focus.data.source === "team" ? "amber" : "neutral"}>
          {focus.data.source === "team"
            ? "Team override active"
            : "Inheriting league defaults"}
        </Badge>
        <div className="flex items-center gap-2">
          {focus.data.source === "team" && (
            <Button
              variant="ghost"
              onClick={() => reset.mutate()}
              disabled={reset.isPending || save.isPending}
            >
              {reset.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RotateCcw className="h-4 w-4" />
              )}
              Revert to defaults
            </Button>
          )}
        </div>
      </div>

      {(save.isError || reset.isError) && (
        <div className="flex items-center gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          <AlertTriangle className="h-4 w-4" />
          {((save.error || reset.error) as Error).message}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <AllocatorCard
          title="Hitters"
          icon={<Target className="h-3 w-3" />}
          tracks={focus.data.tracks.hitters}
          values={hitters}
          defaults={focus.data.defaults.hitters}
          onChange={(track, val) => update("hitters", track, val)}
          onAutoBalance={() => autoBalance("hitters")}
        />
        <AllocatorCard
          title="Pitchers"
          icon={<Sparkles className="h-3 w-3" />}
          tracks={focus.data.tracks.pitchers}
          values={pitchers}
          defaults={focus.data.defaults.pitchers}
          onChange={(track, val) => update("pitchers", track, val)}
          onAutoBalance={() => autoBalance("pitchers")}
        />
      </div>

      <div className="flex items-center justify-end gap-3">
        <Button
          onClick={() => save.mutate({ hitters, pitchers })}
          disabled={!dirty || save.isPending || !canSave(hitters, pitchers)}
        >
          {save.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          Save training focus
        </Button>
      </div>
    </div>
  );
}

function canSave(
  hitters: Record<string, number>,
  pitchers: Record<string, number>,
): boolean {
  return total(hitters) === 100 && total(pitchers) === 100;
}

function total(values: Record<string, number>): number {
  let s = 0;
  for (const v of Object.values(values)) s += Math.round(Number(v) || 0);
  return s;
}

function AllocatorCard({
  title,
  icon,
  tracks,
  values,
  defaults,
  onChange,
  onAutoBalance,
}: {
  title: string;
  icon: React.ReactNode;
  tracks: string[];
  values: Record<string, number>;
  defaults: Record<string, number>;
  onChange: (track: string, value: number) => void;
  onAutoBalance: () => void;
}) {
  const sum = useMemo(() => total(values), [values]);
  const valid = sum === 100;
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{title}</CardTitle>
          <CardDescription>
            Each value must be ≥ {MIN_PERCENT}; group total must equal 100.
          </CardDescription>
        </div>
        <Badge tone={valid ? "success" : "warning"}>
          {icon} {sum}%
        </Badge>
      </CardHeader>
      <CardContent className="space-y-3">
        {tracks.map((track) => {
          const value = Math.round(values[track] ?? 0);
          const def = Math.round(defaults[track] ?? 0);
          return (
            <div key={track} className="space-y-1">
              <div className="flex items-baseline justify-between">
                <label
                  htmlFor={`${title}-${track}`}
                  className="text-sm font-semibold"
                >
                  {TRACK_LABEL[track] ?? track}
                </label>
                <span className="text-xs text-muted">default {def}%</span>
              </div>
              <div className="flex items-center gap-3">
                <input
                  id={`${title}-${track}`}
                  type="range"
                  min={0}
                  max={100}
                  step={1}
                  value={value}
                  onChange={(e) => onChange(track, Number(e.target.value))}
                  className="flex-1 accent-amber"
                />
                <input
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  value={value}
                  onChange={(e) => onChange(track, Number(e.target.value))}
                  className="h-8 w-16 rounded-md border border-border bg-canvas/60 px-2 text-right text-sm tabular-nums focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
                />
                <span className="w-3 text-xs text-muted">%</span>
              </div>
              {value < MIN_PERCENT && value > 0 && (
                <p className="text-[11px] text-warning">
                  Below the {MIN_PERCENT}% minimum — server will clamp on save.
                </p>
              )}
            </div>
          );
        })}
        <div className="flex items-center justify-between pt-2">
          <Button variant="outline" size="sm" onClick={onAutoBalance}>
            Auto-balance evenly
          </Button>
          <span
            className={cn(
              "text-xs font-semibold uppercase tracking-wider",
              valid ? "text-success" : "text-warning",
            )}
          >
            {valid ? "Balanced" : `Adjust by ${100 - sum}%`}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading training focus…</span>
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

