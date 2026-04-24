/**
 * Per-player training focus override dialog. Ports ``TrainingFocusDialog``
 * from ``ui/training_focus_dialog.py`` (``mode="player"``): spinboxes for
 * each hitter + pitcher track that must each total 100%. Save writes a
 * player override; "Use team/league default" clears it.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2, RotateCcw, Target } from "lucide-react";

import { api, type PlayerTrainingFocus } from "@/lib/api";
import { toast } from "@/lib/toast-store";
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";

const HITTER_LABELS: Record<string, string> = {
  contact: "Contact",
  power: "Power",
  speed: "Speed",
  discipline: "Discipline",
  defense: "Defense",
};

const PITCHER_LABELS: Record<string, string> = {
  command: "Command",
  movement: "Movement",
  stamina: "Stamina",
  velocity: "Velocity",
  hold: "Hold Runner",
  pitch_lab: "Pitch Design",
};

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  playerId: string;
  playerName: string;
  teamId: string | null;
}

export function PlayerTrainingDialog({
  open,
  onOpenChange,
  playerId,
  playerName,
  teamId,
}: Props) {
  const queryClient = useQueryClient();
  const focus = useQuery({
    queryKey: ["player-training", playerId, teamId ?? ""],
    queryFn: () => api.getPlayerTraining(playerId, teamId ?? undefined),
    enabled: open,
  });

  const [hitters, setHitters] = useState<Record<string, number>>({});
  const [pitchers, setPitchers] = useState<Record<string, number>>({});

  useEffect(() => {
    if (focus.data) {
      setHitters(roundWeights(focus.data.hitters));
      setPitchers(roundWeights(focus.data.pitchers));
    }
  }, [focus.data]);

  const save = useMutation({
    mutationFn: () =>
      api.savePlayerTraining(playerId, {
        hitters,
        pitchers,
        team_id: teamId ?? undefined,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["player-training", playerId, teamId ?? ""], data);
      // Profile view-model shows the inherited training-focus block — bust
      // its cache so the profile re-renders with the new allocation.
      queryClient.invalidateQueries({ queryKey: ["player-profile", playerId] });
      toast.success(`${playerName} training override saved`);
      onOpenChange(false);
    },
  });
  const reset = useMutation({
    mutationFn: () => api.resetPlayerTraining(playerId, teamId ?? undefined),
    onSuccess: (data) => {
      queryClient.setQueryData(["player-training", playerId, teamId ?? ""], data);
      queryClient.invalidateQueries({ queryKey: ["player-profile", playerId] });
      toast.info(
        `${playerName} reverted to ${teamId ? "team" : "league"} default`,
      );
      onOpenChange(false);
    },
  });

  const hitterTotal = useMemo(
    () => Object.values(hitters).reduce((a, b) => a + b, 0),
    [hitters],
  );
  const pitcherTotal = useMemo(
    () => Object.values(pitchers).reduce((a, b) => a + b, 0),
    [pitchers],
  );
  const canSave = hitterTotal === 100 && pitcherTotal === 100 && !save.isPending;
  const override = focus.data?.source === "player";
  const inheritedFrom =
    focus.data?.source === "team" ? "team" : focus.data?.source === "defaults" ? "league" : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            <span className="inline-flex items-center gap-2">
              <Target className="h-4 w-4" /> {playerName} · training focus
            </span>
          </DialogTitle>
          <DialogDescription>
            Override how this player's offseason training time is split. Hitter
            and pitcher tracks each must total 100%.
          </DialogDescription>
        </DialogHeader>

        {focus.isLoading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading current focus…
          </div>
        ) : focus.isError ? (
          <div className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{(focus.error as Error).message}</span>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2 text-xs text-muted">
              {override ? (
                <Badge tone="amber">Player override active</Badge>
              ) : (
                <Badge tone="neutral">
                  Using {inheritedFrom} default
                </Badge>
              )}
            </div>

            <Section
              title="Hitters"
              tracks={focus.data?.tracks.hitters ?? []}
              labels={HITTER_LABELS}
              values={hitters}
              total={hitterTotal}
              onChange={(k, v) => setHitters({ ...hitters, [k]: v })}
            />
            <Section
              title="Pitchers"
              tracks={focus.data?.tracks.pitchers ?? []}
              labels={PITCHER_LABELS}
              values={pitchers}
              total={pitcherTotal}
              onChange={(k, v) => setPitchers({ ...pitchers, [k]: v })}
            />

            {(save.isError || reset.isError) && (
              <div className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  {
                    (save.error as Error | null)?.message ||
                      (reset.error as Error | null)?.message
                  }
                </span>
              </div>
            )}

            <div className="mt-2 flex items-center justify-between gap-2">
              <Button
                variant="ghost"
                onClick={() => reset.mutate()}
                disabled={!override || reset.isPending}
                title={
                  override
                    ? "Clear the override so the player follows the team/league default"
                    : "Only available when a per-player override is active"
                }
              >
                <RotateCcw className="h-3 w-3" /> Use {teamId ? "team" : "league"} default
              </Button>
              <div className="flex items-center gap-2">
                <Button variant="ghost" onClick={() => onOpenChange(false)}>
                  Cancel
                </Button>
                <Button
                  onClick={() => save.mutate()}
                  disabled={!canSave}
                  title={
                    canSave
                      ? "Save per-player override"
                      : "Both totals must equal 100%"
                  }
                >
                  {save.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                  Save override
                </Button>
              </div>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Section({
  title,
  tracks,
  labels,
  values,
  total,
  onChange,
}: {
  title: string;
  tracks: string[];
  labels: Record<string, string>;
  values: Record<string, number>;
  total: number;
  onChange: (track: string, value: number) => void;
}) {
  return (
    <div className="rounded-xl border border-border bg-surfaceAlt/30 p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="font-semibold">{title}</div>
        <Badge tone={total === 100 ? "success" : "warning"}>
          Total {total}%
        </Badge>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {tracks.map((track) => (
          <label key={track} className="flex items-center justify-between gap-2">
            <span className="text-xs uppercase tracking-wider text-muted">
              {labels[track] ?? track}
            </span>
            <input
              type="number"
              min={0}
              max={100}
              value={values[track] ?? 0}
              onChange={(e) => {
                const n = Math.max(0, Math.min(100, Math.round(Number(e.target.value))));
                onChange(track, Number.isFinite(n) ? n : 0);
              }}
              className="h-9 w-20 rounded-md border border-border bg-canvas/60 px-2 text-right text-sm tabular-nums text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
            />
          </label>
        ))}
      </div>
    </div>
  );
}

function roundWeights(src: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(src)) {
    out[k] = Math.round(Number(v) || 0);
  }
  return out;
}
