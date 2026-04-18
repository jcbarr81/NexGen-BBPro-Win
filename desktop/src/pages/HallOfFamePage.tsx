/**
 * Phase 4 port of ui/hall_of_fame_settings_dialog.py.
 *
 * Inductees + candidate list with manual induct / remove admin actions.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Award,
  Loader2,
  RefreshCw,
  Trash2,
  UserPlus,
} from "lucide-react";

import { api } from "@/lib/api";
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
} from "@/components/ui";

export function HallOfFamePage() {
  const role = useAuthStore((s) => s.role);
  const isAdmin = role === "admin";
  const queryClient = useQueryClient();

  const hof = useQuery({
    queryKey: ["hall-of-fame"],
    queryFn: () => api.hallOfFame(),
  });

  const induct = useMutation({
    mutationFn: (playerId: string) => api.hofInduct(playerId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["hall-of-fame"] }),
  });
  const remove = useMutation({
    mutationFn: (playerId: string) => api.hofRemove(playerId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["hall-of-fame"] }),
  });
  const refresh = useMutation({
    mutationFn: () => api.hofRefresh(),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["hall-of-fame"] }),
  });

  return (
    <AppShell title="Hall of Fame" subtitle="Inductees + ballot candidates">
      <div className="mb-4 flex items-center justify-end gap-2">
        {isAdmin && (
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
        )}
      </div>

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
                          onClick={() =>
                            window.confirm("Remove from Hall of Fame?") &&
                            remove.mutate(String(i.player_id))
                          }
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
