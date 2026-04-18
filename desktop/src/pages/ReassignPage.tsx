/**
 * Port of the roster auto-assign flow (services.roster_auto_assign).
 *
 * Admin can reassign all teams at once, or reassign a single team from the
 * dropdown. The service itself decides which level each player belongs on
 * (ACT/AAA/LOW) from ratings + role, so the UI is intentionally small.
 */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Loader2, Shuffle } from "lucide-react";

import { api } from "@/lib/api";
import { AppShell } from "@/components/layout/AppShell";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";

export function ReassignPage() {
  return (
    <AppShell
      title="Reassign Players"
      subtitle="Admin: bulk auto-assign rosters to ACT/AAA/LOW"
    >
      <ReassignBody />
    </AppShell>
  );
}

function ReassignBody() {
  const teams = useQuery({ queryKey: ["teams"], queryFn: () => api.listTeams() });
  const [selected, setSelected] = useState("");

  const oneMut = useMutation({
    mutationFn: (teamId: string) => api.autoAssignTeam(teamId),
  });
  const allMut = useMutation({ mutationFn: () => api.autoAssignAll() });

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Shuffle className="h-4 w-4 text-amber" /> League-wide reassign
          </CardTitle>
          <CardDescription>
            Runs the auto-assign engine against every team in the league. Good
            for a clean slate after an import or before starting a new season.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-between gap-3">
          <div className="text-xs text-muted">
            This rewrites each team's roster levels. It does not release players.
          </div>
          <Button
            onClick={() => allMut.mutate()}
            disabled={allMut.isPending}
            size="sm"
          >
            {allMut.isPending ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Shuffle className="mr-1 h-4 w-4" />
            )}
            Reassign all teams
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Single team reassign</CardTitle>
          <CardDescription>
            Pick a team and run auto-assign just for that roster.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <select
            className="min-w-[240px] rounded-md border border-border bg-surface px-3 py-2 text-sm"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            <option value="">Select a team…</option>
            {(teams.data ?? []).map((t) => (
              <option key={t.team_id} value={t.team_id}>
                {t.city} {t.name} ({t.team_id})
              </option>
            ))}
          </select>
          <Button
            onClick={() => selected && oneMut.mutate(selected)}
            disabled={!selected || oneMut.isPending}
            size="sm"
          >
            {oneMut.isPending ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Shuffle className="mr-1 h-4 w-4" />
            )}
            Reassign team
          </Button>
        </CardContent>
      </Card>

      {(oneMut.isSuccess || allMut.isSuccess) && (
        <Card>
          <CardContent className="flex items-center gap-2 py-3 text-sm">
            <CheckCircle2 className="h-4 w-4 text-success" />
            {oneMut.isSuccess
              ? `Reassigned team ${oneMut.data?.team_id}.`
              : "Reassigned all teams."}
          </CardContent>
        </Card>
      )}

      {(oneMut.isError || allMut.isError) && (
        <Card>
          <CardContent className="flex items-center gap-2 py-3 text-sm">
            <AlertTriangle className="h-4 w-4 text-warning" />
            {(oneMut.error as Error)?.message ||
              (allMut.error as Error)?.message ||
              "Reassign failed."}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
