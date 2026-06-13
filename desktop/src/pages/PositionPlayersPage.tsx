/**
 * Position-player roster view — the hitter-side counterpart to PitchersPage.
 *
 * Same level tabs (ACT/AAA/LOW), but filters out pitchers and shows
 * hitter-specific columns. Reuses the ``/teams/{id}/roster`` payload.
 */

import { useMemo, useState } from "react";

import { usePersistedState } from "@/lib/use-persisted-state";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  HeartPulse,
  Loader2,
  Users,
} from "lucide-react";

import {
  api,
  type RosterLevel,
  type RosterPlayer,
  type TeamRoster,
} from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { useActiveTeamColor } from "@/lib/team-colors";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { StarRating } from "@/components/StarRating";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";

const LEVEL_ORDER: RosterLevel[] = ["ACT", "AAA", "LOW"];
const LEVEL_LABEL: Record<RosterLevel, string> = {
  ACT: "Active",
  AAA: "AAA",
  LOW: "Low-A",
  DL: "Disabled",
  IR: "Injured Res.",
};

const COLUMNS: Array<{ key: string; label: string }> = [
  { key: "ch", label: "CH" },
  { key: "ph", label: "PH" },
  { key: "sp", label: "SP" },
  { key: "eye", label: "EYE" },
  { key: "fa", label: "FA" },
  { key: "arm", label: "ARM" },
];

type SortKey = "name" | "age" | "pos" | "overall" | "bats" | string;
type SortDir = "asc" | "desc";

export function PositionPlayersPage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;

  const teams = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
    enabled: !teamId,
  });

  const fallbackTeamId = teamId ?? teams.data?.[0]?.team_id ?? null;
  const teamAccentColor = useActiveTeamColor(fallbackTeamId ?? undefined);

  const roster = useQuery({
    queryKey: ["team-roster", fallbackTeamId],
    queryFn: () => api.teamRoster(fallbackTeamId as string),
    enabled: !!fallbackTeamId,
  });

  if (!fallbackTeamId) {
    return (
      <AppShell title="Position Players">
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
      title="Position Players"
      subtitle={`Team ${fallbackTeamId} · hitters by level`}
      teamAccentColor={teamAccentColor}
    >
      {roster.isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <Loader2 className="h-5 w-5 animate-spin text-amber" />
            <span className="text-sm text-muted">Loading roster…</span>
          </CardContent>
        </Card>
      ) : roster.isError ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-danger">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm">{(roster.error as Error).message}</span>
          </CardContent>
        </Card>
      ) : roster.data ? (
        <PositionTabs roster={roster.data} />
      ) : null}
    </AppShell>
  );
}

function PositionTabs({ roster }: { roster: TeamRoster }) {
  const [level, setLevel] = usePersistedState<RosterLevel>(
    "position-players:level",
    "ACT",
  );
  return (
    <Tabs value={level} onValueChange={(v) => setLevel(v as RosterLevel)}>
      <TabsList>
        {LEVEL_ORDER.map((level) => {
          const count = (roster.levels[level] ?? []).filter(
            (p) => !p.is_pitcher,
          ).length;
          return (
            <TabsTrigger key={level} value={level}>
              <span>{LEVEL_LABEL[level]}</span>
              <Badge tone="neutral" className="ml-2">
                {count}
              </Badge>
            </TabsTrigger>
          );
        })}
      </TabsList>
      {LEVEL_ORDER.map((level) => (
        <TabsContent key={level} value={level}>
          <PositionTable
            level={level}
            players={(roster.levels[level] ?? []).filter(
              (p) => !p.is_pitcher,
            )}
          />
        </TabsContent>
      ))}
    </Tabs>
  );
}

function PositionTable({
  level,
  players,
}: {
  level: RosterLevel;
  players: RosterPlayer[];
}) {
  const navigate = useNavigate();
  const [sortKey, setSortKey] = usePersistedState<SortKey>(
    "position-players:sortKey",
    "overall",
  );
  const [sortDir, setSortDir] = usePersistedState<SortDir>(
    "position-players:sortDir",
    "desc",
  );

  const sorted = useMemo(() => {
    const arr = [...players];
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
  }, [players, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "name" ? "asc" : "desc");
    }
  }

  if (players.length === 0) {
    return (
      <Card className="mt-4">
        <CardContent className="flex items-center gap-3 py-10">
          <Users className="h-5 w-5 text-muted" />
          <span className="text-sm text-muted">
            No position players on {LEVEL_LABEL[level]}.
          </span>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="mt-4">
      <CardHeader>
        <div>
          <CardTitle>{players.length} hitters</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
                <HeaderCell
                  label="Player"
                  keyId="name"
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onClick={toggleSort}
                  align="left"
                />
                <HeaderCell
                  label="Age"
                  keyId="age"
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onClick={toggleSort}
                />
                <HeaderCell
                  label="Pos"
                  keyId="pos"
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onClick={toggleSort}
                />
                <HeaderCell
                  label="B/T"
                  keyId="bats"
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onClick={toggleSort}
                />
                <HeaderCell
                  label="OVR"
                  keyId="overall"
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onClick={toggleSort}
                />
                {COLUMNS.map((col) => (
                  <HeaderCell
                    key={col.key}
                    label={col.label}
                    keyId={col.key}
                    sortKey={sortKey}
                    sortDir={sortDir}
                    onClick={toggleSort}
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((p) => (
                <tr
                  key={p.player_id}
                  className="border-b border-border/40 transition last:border-b-0 hover:bg-surfaceAlt/40"
                >
                  <td className="px-6 py-2">
                    <div className="flex items-center gap-2">
                      <PlayerAvatar
                        playerId={p.player_id}
                        initials={`${p.first_name?.[0] ?? ""}${p.last_name?.[0] ?? ""}`}
                        className="h-7 w-7 shrink-0 overflow-hidden rounded-md text-[10px]"
                      />
                      <button
                        type="button"
                        onClick={() =>
                          navigate(
                            `/player/${encodeURIComponent(p.player_id)}`,
                          )
                        }
                        className="font-semibold text-left hover:text-amber"
                      >
                        {p.last_name}
                        {p.first_name ? `, ${p.first_name}` : ""}
                      </button>
                      {p.injured && (
                        <Badge tone="danger" className="text-[10px]">
                          <HeartPulse className="h-3 w-3" /> DL
                        </Badge>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {p.age ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-right text-xs uppercase tracking-wider text-muted">
                    {p.primary_position || "—"}
                  </td>
                  <td className="px-3 py-2 text-right text-xs">
                    {p.bats || "—"}/{p.throws || "—"}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    <OverallCell player={p} />
                  </td>
                  {COLUMNS.map((col) => (
                    <td
                      key={col.key}
                      className="px-3 py-2 text-right tabular-nums"
                    >
                      <RatingCell value={p.ratings[col.key]} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function sortValue(p: RosterPlayer, key: SortKey): string | number | null {
  switch (key) {
    case "name":
      return `${p.last_name}, ${p.first_name}`;
    case "age":
      return p.age ?? null;
    case "pos":
      return p.primary_position ?? "";
    case "bats":
      return p.bats ?? "";
    case "overall":
      return p.overall_display ?? p.overall_raw ?? null;
    default: {
      const raw = p.ratings[key];
      if (raw == null) return null;
      const n = typeof raw === "number" ? raw : Number(raw);
      return Number.isFinite(n) ? n : String(raw);
    }
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
        "select-none px-3 py-2 font-semibold",
        align === "left" ? "text-left px-6" : "text-right",
      )}
    >
      <button
        type="button"
        onClick={() => onClick(keyId)}
        className={cn(
          "inline-flex items-center gap-1 transition",
          active ? "text-ink" : "hover:text-ink",
        )}
      >
        {label}
        <Arrow className="h-3 w-3 opacity-60" />
      </button>
    </th>
  );
}

function OverallCell({ player }: { player: RosterPlayer }) {
  const display = player.overall_display ?? player.overall_raw;
  if (display == null) return <span className="text-subtle">—</span>;
  const stars = parseFloat(player.overall_stars_text ?? "");
  return (
    <div className="inline-flex flex-col items-end gap-0.5">
      <span className="font-semibold tabular-nums">{display}</span>
      {Number.isFinite(stars) && (
        <StarRating value={stars} size="h-3.5 w-3.5" />
      )}
    </div>
  );
}

function RatingCell({ value }: { value: unknown }) {
  if (value == null || value === "") {
    return <span className="text-subtle">—</span>;
  }
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return <span>{String(value)}</span>;
  return <span>{Math.round(n)}</span>;
}
