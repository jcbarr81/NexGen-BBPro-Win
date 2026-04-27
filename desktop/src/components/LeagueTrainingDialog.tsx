/**
 * League-level training focus dialog. Ports ``TrainingFocusDialog``
 * from ``ui/training_focus_dialog.py`` (``mode="league"``): spinboxes for
 * each hitter + pitcher track that must each total 100%. Save writes to
 * ``services.training_settings.update_league_training_defaults`` via the
 * ``/training/league`` endpoint so all teams + players that haven't set an
 * override inherit the new defaults.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, GraduationCap, Loader2 } from "lucide-react";

import { api } from "@/lib/api";
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
}

export function LeagueTrainingDialog({ open, onOpenChange }: Props) {
  const queryClient = useQueryClient();
  const focus = useQuery({
    queryKey: ["league-training"],
    queryFn: () => api.getLeagueTraining(),
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
    mutationFn: () => api.saveLeagueTraining({ hitters, pitchers }),
    onSuccess: (data) => {
      queryClient.setQueryData(["league-training"], data);
      // Bust team/player caches so their inherited defaults re-render.
      queryClient.invalidateQueries({ queryKey: ["training"] });
      queryClient.invalidateQueries({ queryKey: ["player-training"] });
      toast.success("League training defaults updated");
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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            <span className="inline-flex items-center gap-2">
              <GraduationCap className="h-4 w-4" /> League training focus
            </span>
          </DialogTitle>
          <DialogDescription>
            Set the league-wide default split of offseason training time for
            every hitter and pitcher. Teams and players with their own override
            ignore these defaults.
          </DialogDescription>
        </DialogHeader>

        {focus.isLoading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading defaults…
          </div>
        ) : focus.isError ? (
          <div className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{(focus.error as Error).message}</span>
          </div>
        ) : (
          <>
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

            {save.isError && (
              <div className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{(save.error as Error).message}</span>
              </div>
            )}

            <div className="mt-2 flex items-center justify-end gap-2">
              <Button variant="ghost" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button
                onClick={() => save.mutate()}
                disabled={!canSave}
                title={
                  canSave ? "Save league defaults" : "Both totals must equal 100%"
                }
              >
                {save.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                Save defaults
              </Button>
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
                const n = Math.max(
                  0,
                  Math.min(100, Math.round(Number(e.target.value))),
                );
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
