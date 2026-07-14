/**
 * Phase 4 port of the Teams directory screen.
 *
 * Shows every team in the league grouped by division with colored identity
 * tiles. A search input filters live by city/name/id/abbreviation/division.
 * Clicking a tile selects the team as the owner-dashboard context and
 * navigates there; admins use this as their team-switcher.
 */

import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  Loader2,
  Search,
  Users as UsersIcon,
} from "lucide-react";

import { type Team } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { useTeams } from "@/lib/use-teams";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import { TeamLogo } from "@/components/TeamLogo";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
} from "@/components/ui";

export function TeamsPage() {
  const navigate = useNavigate();
  const setSelectedTeam = useAuthStore((s) => s.setSelectedTeam);
  const activeTeamId = useAuthStore(
    (s) => s.selectedTeamId ?? s.teamId ?? null,
  );
  const [search, setSearch] = useState("");

  const teams = useTeams();

  const divisions = useMemo(() => {
    if (!teams.data) return [] as Array<{ division: string; teams: Team[] }>;
    const needle = search.trim().toLowerCase();
    const filtered = needle
      ? teams.data.filter((t) =>
          [t.team_id, t.abbreviation, t.city, t.name, t.division, t.stadium]
            .map((v) => (v || "").toLowerCase())
            .some((v) => v.includes(needle)),
        )
      : teams.data;
    const groups = new Map<string, Team[]>();
    for (const t of filtered) {
      const key = t.division || "—";
      const arr = groups.get(key) ?? [];
      arr.push(t);
      groups.set(key, arr);
    }
    const out = [...groups.entries()].map(([division, list]) => ({
      division,
      teams: [...list].sort((a, b) =>
        `${a.city} ${a.name}`.localeCompare(`${b.city} ${b.name}`),
      ),
    }));
    out.sort((a, b) => a.division.localeCompare(b.division));
    return out;
  }, [teams.data, search]);

  function pickTeam(teamId: string) {
    navigate(`/team/${encodeURIComponent(teamId)}`);
  }
  // setSelectedTeam still used by the "Set as my team" button on the detail page.
  void setSelectedTeam;

  return (
    <AppShell
      title="Teams"
      subtitle="Browse the league directory and jump into any team's dashboard."
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="relative w-full max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <Input
            className="pl-9"
            placeholder="Search city, name, abbrev, division…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        {teams.data && (
          <div className="text-xs text-muted">{teams.data.length} teams</div>
        )}
      </div>

      {teams.isLoading ? (
        <LoadingCard />
      ) : teams.isError ? (
        <ErrorCard message={(teams.error as Error).message} />
      ) : divisions.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-sm text-muted">
            No teams match that search.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6">
          {divisions.map((division) => (
            <Card key={division.division}>
              <CardHeader>
                <div>
                  <CardTitle>{division.division}</CardTitle>
                </div>
                <Badge tone="amber">
                  <UsersIcon className="h-3 w-3" /> {division.teams.length}
                </Badge>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {division.teams.map((team) => (
                    <TeamTile
                      key={team.team_id}
                      team={team}
                      active={team.team_id === activeTeamId}
                      onClick={() => pickTeam(team.team_id)}
                    />
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </AppShell>
  );
}

function TeamTile({
  team,
  active,
  onClick,
}: {
  team: Team;
  active: boolean;
  onClick: () => void;
}) {
  const logoVersion = useAuthStore((s) => s.logoVersion);
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group relative flex items-center gap-3 overflow-hidden rounded-xl border border-border bg-surfaceAlt/40 p-3 text-left transition hover:border-amber/60 hover:bg-surfaceAlt",
        active && "border-amber/60 bg-amber/10",
      )}
    >
      <TeamLogo
        teamId={team.team_id}
        abbreviation={team.abbreviation || team.team_id}
        primaryColor={team.primary_color}
        secondaryColor={team.secondary_color}
        className="h-14 w-14 shrink-0 rounded-lg text-lg"
        version={logoVersion}
      />
      <div className="min-w-0 flex-1">
        <div className="truncate font-semibold">
          {team.city} {team.name}
        </div>
        <div className="truncate text-xs text-muted">
          {team.stadium || team.team_id}
        </div>
        {active && (
          <div className="mt-1">
            <Badge tone="amber">Active</Badge>
          </div>
        )}
      </div>
    </button>
  );
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading teams…</span>
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
