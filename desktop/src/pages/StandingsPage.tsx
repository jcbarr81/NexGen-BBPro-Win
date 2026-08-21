/**
 * Phase 4 port of ui/standings_screen.py.
 *
 * Shows every division side-by-side as its own card. Each division table is
 * sortable by any column (default: PCT desc), and the current user's team
 * row is amber-highlighted if we can resolve it from the auth store.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Loader2,
  Trophy,
} from "lucide-react";

import { api, type LeagueStandingsRow } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import { ReorderableCards } from "@/components/layout/ReorderableCards";
import {
  useLayoutEditStore,
  useRegisterLayoutPage,
} from "@/lib/layout-edit-store";
import { TeamLogo } from "@/components/TeamLogo";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui";

type SortKey =
  | "name"
  | "wins"
  | "losses"
  | "pct"
  | "gb"
  | "run_diff"
  | "streak"
  | "last10";
type SortDir = "asc" | "desc";

export function StandingsPage() {
  const activeTeamId = useAuthStore(
    (s) => s.selectedTeamId ?? s.teamId ?? null,
  );
  const standings = useQuery({
    queryKey: ["league-standings"],
    queryFn: () => api.leagueStandings(),
  });

  useRegisterLayoutPage("standings");
  const editingLayout = useLayoutEditStore((s) => s.editing);

  return (
    <AppShell
      title="League"
      subtitle="Standings across every division, refreshed from the sim state."
    >
      {standings.isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <Loader2 className="h-5 w-5 animate-spin text-amber" />
            <span className="text-sm text-muted">Loading standings…</span>
          </CardContent>
        </Card>
      ) : standings.isError ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-danger">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm">
              {(standings.error as Error).message}
            </span>
          </CardContent>
        </Card>
      ) : !standings.data || standings.data.divisions.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-sm text-muted">
            No standings data available yet.
          </CardContent>
        </Card>
      ) : (
        <ReorderableCards
          pageKey="standings"
          variant="grid"
          className="grid grid-cols-1 gap-6 xl:grid-cols-2"
          editing={editingLayout}
          items={standings.data.divisions.map((division) => ({
            id: division.division,
            label: division.division,
            node: (
              <DivisionCard
                division={division.division}
                teams={division.teams}
                activeTeamId={activeTeamId}
              />
            ),
          }))}
        />
      )}
    </AppShell>
  );
}

function DivisionCard({
  division,
  teams,
  activeTeamId,
}: {
  division: string;
  teams: LeagueStandingsRow[];
  activeTeamId: string | null;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("pct");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const sorted = useMemo(() => {
    const arr = [...teams];
    arr.sort((a, b) => {
      const av = sortValue(a, sortKey);
      const bv = sortValue(b, sortKey);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "asc" ? av - bv : bv - av;
      }
      const as = String(av).toLowerCase();
      const bs = String(bv).toLowerCase();
      if (as < bs) return sortDir === "asc" ? -1 : 1;
      if (as > bs) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return arr;
  }, [teams, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "name" ? "asc" : "desc");
    }
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{division}</CardTitle>
        </div>
        <Badge tone="amber">
          <Trophy className="h-3 w-3" /> {teams.length} teams
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        {/* Mobile: stacked cards (the wide table reads poorly on a phone). */}
        <div className="space-y-1.5 p-2 sm:hidden">
          {sorted.map((team) => (
            <Link
              key={team.team_id}
              to={`/team/${encodeURIComponent(team.team_id)}`}
              className={cn(
                "block rounded-lg border border-border/60 p-2.5 hover:bg-surfaceAlt/40",
                team.team_id === activeTeamId && "border-amber/50 bg-amber/10",
              )}
            >
              <div className="flex items-center gap-2">
                <TeamLogo
                  teamId={team.team_id}
                  abbreviation={team.abbreviation || team.team_id}
                  primaryColor={team.primary_color}
                  secondaryColor={team.secondary_color}
                  className="h-8 w-8 shrink-0 rounded-md text-[10px]"
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-semibold">
                    {team.city} {team.name}
                  </div>
                  <div className="text-[11px] uppercase tracking-wider text-muted">
                    {team.abbreviation}
                  </div>
                </div>
                <StatusCell team={team} />
              </div>
              <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs tabular-nums">
                <span className="font-semibold">
                  {team.wins}-{team.losses}
                </span>
                <span className="text-muted">
                  {team.pct.toFixed(3).replace(/^0/, "")}
                </span>
                <span className="text-muted">GB {team.gb}</span>
                <span
                  className={cn(
                    team.run_diff > 0 && "text-success",
                    team.run_diff < 0 && "text-danger",
                  )}
                >
                  RD {team.run_diff > 0 ? `+${team.run_diff}` : team.run_diff}
                </span>
                <span className="text-muted">Strk {team.streak}</span>
                <span className="text-muted">L10 {team.last10}</span>
              </div>
            </Link>
          ))}
        </div>
        {/* Desktop: full table. */}
        <div className="hidden overflow-x-auto sm:block"><table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
              <HeaderCell label="Team" keyId="name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} align="left" />
              <HeaderCell label="W" keyId="wins" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
              <HeaderCell label="L" keyId="losses" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
              <HeaderCell label="PCT" keyId="pct" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
              <HeaderCell label="GB" keyId="gb" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
              <HeaderCell label="RD" keyId="run_diff" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
              <HeaderCell label="Strk" keyId="streak" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
              <HeaderCell label="L10" keyId="last10" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
              <th className="select-none px-3 py-2 text-right font-semibold text-muted">
                Mag/E
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((team) => (
              <tr
                key={team.team_id}
                className={cn(
                  "border-b border-border/40 transition last:border-b-0 hover:bg-surfaceAlt/40",
                  team.team_id === activeTeamId && "bg-amber/10 hover:bg-amber/15",
                )}
              >
                <td className="px-6 py-2">
                  <Link
                    to={`/team/${encodeURIComponent(team.team_id)}`}
                    className="flex items-center gap-2 hover:text-amber"
                  >
                    <TeamLogo
                      teamId={team.team_id}
                      abbreviation={team.abbreviation || team.team_id}
                      primaryColor={team.primary_color}
                      secondaryColor={team.secondary_color}
                      className="h-7 w-7 shrink-0 rounded-md text-[10px]"
                    />
                    <span className="font-semibold">
                      {team.city} {team.name}
                    </span>
                    <span className="text-[11px] uppercase tracking-wider text-muted">
                      {team.abbreviation}
                    </span>
                  </Link>
                </td>
                <td className="px-2 py-2 text-right tabular-nums">{team.wins}</td>
                <td className="px-2 py-2 text-right tabular-nums">{team.losses}</td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {team.pct.toFixed(3).replace(/^0/, "")}
                </td>
                <td className="px-2 py-2 text-right tabular-nums">{team.gb}</td>
                <td
                  className={cn(
                    "px-2 py-2 text-right tabular-nums",
                    team.run_diff > 0 && "text-success",
                    team.run_diff < 0 && "text-danger",
                  )}
                >
                  {team.run_diff > 0 ? `+${team.run_diff}` : team.run_diff}
                </td>
                <td className="px-2 py-2 text-right tabular-nums">{team.streak}</td>
                <td className="px-2 py-2 text-right tabular-nums">{team.last10}</td>
                <td className="px-3 py-2 text-right">
                  <StatusCell team={team} />
                </td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </CardContent>
    </Card>
  );
}

function StatusCell({ team }: { team: LeagueStandingsRow }) {
  const status = team.status;
  const magic = team.magic_number;
  // Currently holding a wildcard spot (#2) — highlight it above division status.
  if (team.playoff_spot === "wildcard") {
    return (
      <Badge tone="amber" className="text-[10px]" title="Currently in a wildcard spot">
        WC
      </Badge>
    );
  }
  if (status === "clinched_division") {
    return (
      <Badge tone="success" className="text-[10px]">
        Clinched
      </Badge>
    );
  }
  if (status === "leader" && typeof magic === "number" && magic > 0) {
    return (
      <span
        className="text-xs font-semibold tabular-nums text-success"
        title="Magic number to clinch the division"
      >
        M{magic}
      </span>
    );
  }
  // Not in a playoff spot but chasing — games back of the last wildcard.
  if (team.gb_wildcard && team.gb_wildcard !== "—") {
    return (
      <span
        className="text-xs tabular-nums text-muted"
        title="Games back of the last wildcard spot"
      >
        WC −{team.gb_wildcard}
      </span>
    );
  }
  if (status === "eliminated") {
    return (
      <Badge tone="danger" className="text-[10px]">
        Eliminated
      </Badge>
    );
  }
  if (status === "in_race" && typeof magic === "number" && magic > 0) {
    return (
      <span
        className="text-xs tabular-nums text-muted"
        title="Elimination number — leader wins + this team's losses needed to put them out"
      >
        E{magic}
      </span>
    );
  }
  return <span className="text-xs text-subtle">—</span>;
}

function sortValue(
  row: LeagueStandingsRow,
  key: SortKey,
): string | number | null {
  switch (key) {
    case "name":
      return `${row.city} ${row.name}`;
    case "gb":
      if (row.gb === "—") return 0;
      return Number(row.gb) || 0;
    case "streak": {
      // W3 > W1 > L1 > L3 ordering
      const m = row.streak.match(/^([WL])(\d+)$/);
      if (!m) return 0;
      const n = Number(m[2]);
      return m[1] === "W" ? n : -n;
    }
    case "last10": {
      const m = row.last10.match(/^(\d+)-(\d+)$/);
      if (!m) return 0;
      return Number(m[1]) - Number(m[2]);
    }
    default:
      return row[key] as number;
  }
}

interface HeaderCellProps {
  label: string;
  keyId: SortKey;
  sortKey: SortKey;
  sortDir: SortDir;
  onClick: (key: SortKey) => void;
  align?: "left" | "right";
}

function HeaderCell({
  label,
  keyId,
  sortKey,
  sortDir,
  onClick,
  align = "right",
}: HeaderCellProps) {
  const active = sortKey === keyId;
  const Arrow = !active ? ArrowUpDown : sortDir === "asc" ? ArrowUp : ArrowDown;
  return (
    <th
      className={cn(
        "select-none px-2 py-2 font-semibold",
        align === "left" ? "pl-6 text-left" : "text-right",
      )}
    >
      <button
        type="button"
        onClick={() => onClick(keyId)}
        className={cn(
          "inline-flex items-center gap-1 hover:text-ink",
          active ? "text-ink" : "text-muted",
          align === "right" && "flex-row-reverse",
        )}
      >
        <Arrow className="h-3 w-3" />
        {label}
      </button>
    </th>
  );
}
