import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, UserCog } from "lucide-react";

import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { useTeams } from "@/lib/use-teams";
import { Button } from "@/components/ui";

/**
 * Shown on every page while the commissioner is acting for a team that is
 * not their own (8.15.1): the Season page's "Manage team" button, or the
 * dashboard's team switcher, points every team page (Roster, Lineup,
 * Pitching Staff, Depth Chart, Finance, ...) at that club, and changes made
 * there are made for it. The banner names the team, lists what still keeps
 * it from Opening Day (live), and "Done" returns to the commissioner's own
 * view on the Season page.
 *
 * The server already lets a commissioner act on any team
 * (require_team_owner short-circuits role "admin"); this only makes the
 * client's team context visible and easy to leave.
 */
export function ActingForTeamBanner() {
  const navigate = useNavigate();
  const role = useAuthStore((s) => s.role);
  const ownTeamId = useAuthStore((s) => s.teamId);
  const selectedTeamId = useAuthStore((s) => s.selectedTeamId);
  const setSelectedTeam = useAuthStore((s) => s.setSelectedTeam);

  const acting =
    role === "admin" && !!selectedTeamId && selectedTeamId !== (ownTeamId || null);

  const teams = useTeams({ enabled: acting });
  const readiness = useQuery({
    queryKey: ["season-readiness"],
    queryFn: () => api.seasonReadiness(),
    enabled: acting,
    // Moves made on the page underneath change this; keep it current while
    // the commissioner works through the list.
    refetchInterval: acting ? 10_000 : false,
    staleTime: 0,
  });

  if (!acting) return null;

  const team = teams.data?.find((t) => t.team_id === selectedTeamId);
  const name = team ? `${team.city} ${team.name}` : selectedTeamId;
  const status = readiness.data?.teams.find((t) => t.team_id === selectedTeamId);
  const prefix = `${selectedTeamId}: `;
  const issues = (status?.issues ?? []).map((i) =>
    i.startsWith(prefix) ? i.slice(prefix.length) : i,
  );

  function done() {
    setSelectedTeam(ownTeamId || null);
    navigate("/season");
  }

  return (
    <div
      role="status"
      className="border-b border-amber/40 bg-amber/10 px-3 py-2 text-sm sm:px-5 lg:px-8"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <UserCog className="h-4 w-4 shrink-0 text-amber" />
          <span className="min-w-0">
            <span className="font-semibold text-ink">Acting for {name}</span>{" "}
            <span className="text-muted">
              as commissioner. Changes you make on team pages are made for this club.
            </span>
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button size="sm" variant="ghost" onClick={() => navigate("/roster")}>
            Roster
          </Button>
          <Button size="sm" variant="ghost" onClick={() => navigate("/lineup")}>
            Lineup
          </Button>
          <Button size="sm" variant="outline" onClick={done}>
            Done
          </Button>
        </div>
      </div>
      {status &&
        (status.ready ? (
          <div className="mt-1 flex items-center gap-1.5 text-xs text-success">
            <CheckCircle2 className="h-3.5 w-3.5" /> Ready for Opening Day.
          </div>
        ) : (
          <ul className="mt-1 space-y-0.5 text-xs text-danger">
            {issues.slice(0, 4).map((issue, i) => (
              <li key={i}>• {issue}</li>
            ))}
            {issues.length > 4 && (
              <li className="text-muted">…and {issues.length - 4} more</li>
            )}
          </ul>
        ))}
    </div>
  );
}
