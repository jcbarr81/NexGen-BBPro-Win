/**
 * Redirects ``/my-team-stats`` (and any other "show my team" shortcut)
 * to the team detail page for the user's currently-selected team. The
 * Team Detail page already has the Team Stats card with Batting /
 * Pitching / Team Totals tabs — this just makes it reachable from the
 * My Team hub without needing the team_id in the URL.
 */

import { Navigate } from "react-router-dom";

import { useAuthStore } from "@/lib/auth-store";
import { AppShell } from "@/components/layout/AppShell";
import { AlertTriangle, Loader2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui";

export function MyTeamRedirect() {
  const teamId = useAuthStore((s) => s.selectedTeamId ?? s.teamId);
  if (teamId) {
    return <Navigate to={`/team/${encodeURIComponent(teamId)}`} replace />;
  }
  // Auth store hasn't resolved a team yet (or the user is an admin
  // with no primary team). Surface a graceful empty state rather than
  // an instant redirect-to-nowhere.
  return (
    <AppShell title="Team">
      <Card>
        <CardContent className="flex items-center gap-3 py-10">
          {teamId === undefined ? (
            <>
              <Loader2 className="h-5 w-5 animate-spin text-amber" />
              <span className="text-sm text-muted">Loading your team…</span>
            </>
          ) : (
            <>
              <AlertTriangle className="h-5 w-5 text-warning" />
              <span className="text-sm">
                No team assigned. Pick a team from the Teams page to see
                its stats.
              </span>
            </>
          )}
        </CardContent>
      </Card>
    </AppShell>
  );
}
