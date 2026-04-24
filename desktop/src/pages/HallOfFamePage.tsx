/**
 * Phase 4 port of ui/hall_of_fame_settings_dialog.py.
 *
 * Inductees + candidate list with manual induct / remove admin actions.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Award,
  Loader2,
  RefreshCw,
  RotateCcw,
  Settings as SettingsIcon,
  Trash2,
  UserPlus,
} from "lucide-react";

import { api } from "@/lib/api";
import { useConfirmDialog } from "@/lib/use-confirm";
import { toast } from "@/lib/toast-store";
import { useAuthStore } from "@/lib/auth-store";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
} from "@/components/ui";

export function HallOfFamePage() {
  const role = useAuthStore((s) => s.role);
  const isAdmin = role === "admin";
  const queryClient = useQueryClient();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { confirm, dialog: confirmDialog } = useConfirmDialog();

  const hof = useQuery({
    queryKey: ["hall-of-fame"],
    queryFn: () => api.hallOfFame(),
  });

  const induct = useMutation({
    mutationFn: (playerId: string) => api.hofInduct(playerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["hall-of-fame"] });
      toast.success("Inducted into the Hall of Fame");
    },
  });
  const remove = useMutation({
    mutationFn: (playerId: string) => api.hofRemove(playerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["hall-of-fame"] });
      toast.success("Removed from the Hall of Fame");
    },
  });
  const refresh = useMutation({
    mutationFn: () => api.hofRefresh(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["hall-of-fame"] });
      toast.info("Ballot recomputed");
    },
  });

  return (
    <AppShell title="Hall of Fame" subtitle="Inductees + ballot candidates">
      <div className="mb-4 flex items-center justify-end gap-2">
        {isAdmin && (
          <>
            <Button variant="outline" onClick={() => setSettingsOpen(true)}>
              <SettingsIcon className="h-4 w-4" /> Settings
            </Button>
            <Button
              variant="outline"
              onClick={() => refresh.mutate()}
              disabled={refresh.isPending}
            >
              {refresh.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              Recompute ballot
            </Button>
          </>
        )}
      </div>

      {isAdmin && (
        <HofSettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
      )}

      {hof.isLoading ? (
        <LoadingCard />
      ) : hof.isError ? (
        <ErrorCard message={(hof.error as Error).message} />
      ) : hof.data ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Inductees</CardTitle>
                <CardDescription>{hof.data.inductees.length}</CardDescription>
              </div>
              <Badge tone="amber">
                <Award className="h-3 w-3" /> {hof.data.inductees.length}
              </Badge>
            </CardHeader>
            <CardContent className="p-0">
              {hof.data.inductees.length === 0 ? (
                <div className="px-6 py-6 text-sm text-muted">
                  No inductees yet.
                </div>
              ) : (
                <ul className="divide-y divide-border/60">
                  {hof.data.inductees.map((i) => (
                    <li
                      key={String(i.player_id ?? i.name)}
                      className="flex items-center justify-between gap-3 px-6 py-2 text-sm"
                    >
                      <div>
                        <Link
                          to={`/player/${encodeURIComponent(
                            String(i.player_id ?? ""),
                          )}`}
                          className="font-semibold hover:text-amber"
                        >
                          {String(i.name ?? i.player_id ?? "—")}
                        </Link>
                        {i.inducted_year && (
                          <span className="ml-2 text-xs text-muted">
                            {String(i.inducted_year)}
                          </span>
                        )}
                      </div>
                      {isAdmin && (
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label="Remove"
                          onClick={async () => {
                            if (
                              await confirm({
                                title: "Remove from Hall of Fame?",
                                description:
                                  "The inductee moves back to the ballot.",
                                confirmLabel: "Remove",
                                danger: true,
                              })
                            ) {
                              remove.mutate(String(i.player_id));
                            }
                          }}
                        >
                          <Trash2 className="h-3 w-3 text-danger" />
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Candidates</CardTitle>
                <CardDescription>{hof.data.candidates.length}</CardDescription>
              </div>
              <Badge tone="neutral">{hof.data.candidates.length}</Badge>
            </CardHeader>
            <CardContent className="p-0">
              {hof.data.candidates.length === 0 ? (
                <div className="px-6 py-6 text-sm text-muted">
                  No candidates on the current ballot.
                </div>
              ) : (
                <ul className="divide-y divide-border/60">
                  {hof.data.candidates.map((c) => (
                    <li
                      key={String(c.player_id ?? c.name)}
                      className="flex items-center justify-between gap-3 px-6 py-2 text-sm"
                    >
                      <div>
                        <Link
                          to={`/player/${encodeURIComponent(
                            String(c.player_id ?? ""),
                          )}`}
                          className="font-semibold hover:text-amber"
                        >
                          {String(c.name ?? c.player_id ?? "—")}
                        </Link>
                        {c.score != null && (
                          <span className="ml-2 text-xs text-muted">
                            score {String(c.score)}
                          </span>
                        )}
                      </div>
                      {isAdmin && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => induct.mutate(String(c.player_id))}
                          disabled={induct.isPending}
                        >
                          <UserPlus className="h-3 w-3" /> Induct
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      ) : null}
      {confirmDialog}
    </AppShell>
  );
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading hall of fame…</span>
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

function HofSettingsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ["hof-settings"],
    queryFn: () => api.hofSettings(),
    enabled: open,
  });
  const [years, setYears] = useState(0);
  const [threshold, setThreshold] = useState(0);

  useEffect(() => {
    if (settings.data) {
      setYears(settings.data.min_years_retired);
      setThreshold(settings.data.score_threshold);
    }
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () =>
      api.hofSaveSettings({
        min_years_retired: years,
        score_threshold: threshold,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["hof-settings"], data);
      // Threshold + years changes re-run update_hall_of_fame() server-
      // side, so the ballot needs a refetch.
      queryClient.invalidateQueries({ queryKey: ["hall-of-fame"] });
      onOpenChange(false);
    },
  });

  function resetToDefaults() {
    if (!settings.data) return;
    setYears(settings.data.defaults.min_years_retired);
    setThreshold(settings.data.defaults.score_threshold);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            <span className="inline-flex items-center gap-2">
              <SettingsIcon className="h-4 w-4" /> Hall of Fame settings
            </span>
          </DialogTitle>
          <DialogDescription>
            Changes apply to future inductions; existing inductees stay on the
            wall.
          </DialogDescription>
        </DialogHeader>

        {settings.isLoading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading settings…
          </div>
        ) : settings.isError ? (
          <div className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{(settings.error as Error).message}</span>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="hof-years">Minimum years retired</Label>
              <Input
                id="hof-years"
                type="number"
                min={0}
                max={50}
                step={1}
                value={years}
                onChange={(e) =>
                  setYears(Math.max(0, Math.round(Number(e.target.value))))
                }
              />
              <p className="text-xs text-muted">
                Default: {settings.data?.defaults.min_years_retired}.
              </p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="hof-threshold">Score threshold</Label>
              <Input
                id="hof-threshold"
                type="number"
                min={0}
                max={10000}
                step={1}
                value={threshold}
                onChange={(e) =>
                  setThreshold(Math.max(0, Number(e.target.value)))
                }
              />
              <p className="text-xs text-muted">
                Default: {settings.data?.defaults.score_threshold}.
              </p>
            </div>

            {save.isError && (
              <div className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{(save.error as Error).message}</span>
              </div>
            )}

            <div className="mt-2 flex items-center justify-between">
              <Button variant="ghost" onClick={resetToDefaults}>
                <RotateCcw className="h-3 w-3" /> Reset to defaults
              </Button>
              <div className="flex items-center gap-2">
                <Button variant="ghost" onClick={() => onOpenChange(false)}>
                  Cancel
                </Button>
                <Button
                  onClick={() => save.mutate()}
                  disabled={save.isPending}
                >
                  {save.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                  Save settings
                </Button>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
