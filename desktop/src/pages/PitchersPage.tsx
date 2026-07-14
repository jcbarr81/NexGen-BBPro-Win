/**
 * Pitcher-only roster view. Ports ui/pitchers_window.py — the PyQt dialog
 * that grouped every pitcher on the team by roster level (ACT/AAA/LOW)
 * and split each level into SP / RP tabs with pitcher-specific columns
 * (arm / endurance / control + pitch mix).
 *
 * Reuses the ``/teams/{id}/roster`` payload — the sidecar already returns
 * every player with ratings + is_pitcher + role; we just filter.
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
  Flame,
  HeartPulse,
  Loader2,
} from "lucide-react";

import {
  api,
  type RosterLevel,
  type RosterPlayer,
  type TeamRoster,
} from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { useActiveTeamColor } from "@/lib/team-colors";
import { useTeams } from "@/lib/use-teams";
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

// Pitcher stat columns — arm + endurance + control + movement, then pitch mix.
// Mirrors the fields PyQt surfaced (AS/EN/CO in the label, plus the pitch
// columns from pitchers_dialog.py). Sort by any column.
const COLUMNS: Array<{ key: string; label: string }> = [
  { key: "arm", label: "AS" },
  { key: "endurance", label: "EN" },
  { key: "control", label: "CTRL" },
  { key: "movement", label: "MOV" },
  { key: "fb", label: "FB" },
  { key: "sl", label: "SL" },
  { key: "cu", label: "CU" },
  { key: "cb", label: "CB" },
  { key: "si", label: "SI" },
  { key: "scb", label: "SCB" },
  { key: "kn", label: "KN" },
];

type SortKey = "name" | "age" | "role" | "overall" | string;
type SortDir = "asc" | "desc";

/** PyQt's get_role() fallback: if ``role`` is empty, infer from endurance
 *  — pitchers with endurance > 50 are starters, otherwise relievers. */
function pitcherRole(p: RosterPlayer): "SP" | "RP" {
  const stored = (p.role || "").toUpperCase();
  if (stored === "SP" || stored === "RP") return stored;
  const endurance = Number(p.ratings.endurance);
  return Number.isFinite(endurance) && endurance > 50 ? "SP" : "RP";
}

export function PitchersPage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;

  const teams = useTeams({ enabled: !teamId });

  const fallbackTeamId = teamId ?? teams.data?.[0]?.team_id ?? null;
  const teamAccentColor = useActiveTeamColor(fallbackTeamId ?? undefined);

  const roster = useQuery({
    queryKey: ["team-roster", fallbackTeamId],
    queryFn: () => api.teamRoster(fallbackTeamId as string),
    enabled: !!fallbackTeamId,
  });

  if (!fallbackTeamId) {
    return (
      <AppShell title="Pitchers">
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
      title="Pitchers"
      subtitle={`Team ${fallbackTeamId} · staff overview`}
      teamAccentColor={teamAccentColor}
    >
      {roster.isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <Loader2 className="h-5 w-5 animate-spin text-amber" />
            <span className="text-sm text-muted">Loading staff…</span>
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
        <PitcherTabs roster={roster.data} />
      ) : null}
    </AppShell>
  );
}

function PitcherTabs({ roster }: { roster: TeamRoster }) {
  const [level, setLevel] = usePersistedState<RosterLevel>(
    "pitchers:level",
    "ACT",
  );
  return (
    <Tabs value={level} onValueChange={(v) => setLevel(v as RosterLevel)}>
      <TabsList>
        {LEVEL_ORDER.map((level) => {
          const count = (roster.levels[level] ?? []).filter(
            (p) => p.is_pitcher,
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
          <LevelPitcherTabs
            level={level}
            pitchers={(roster.levels[level] ?? []).filter((p) => p.is_pitcher)}
          />
        </TabsContent>
      ))}
    </Tabs>
  );
}

function LevelPitcherTabs({
  level,
  pitchers,
}: {
  level: RosterLevel;
  pitchers: RosterPlayer[];
}) {
  const [role, setRole] = usePersistedState<"SP" | "RP">(
    "pitchers:role",
    "SP",
  );
  const byRole = useMemo(() => {
    const sp: RosterPlayer[] = [];
    const rp: RosterPlayer[] = [];
    for (const p of pitchers) {
      if (pitcherRole(p) === "SP") sp.push(p);
      else rp.push(p);
    }
    return { SP: sp, RP: rp };
  }, [pitchers]);

  if (pitchers.length === 0) {
    return (
      <Card className="mt-4">
        <CardContent className="flex items-center gap-3 py-10">
          <Flame className="h-5 w-5 text-muted" />
          <span className="text-sm text-muted">
            No pitchers on {LEVEL_LABEL[level]}.
          </span>
        </CardContent>
      </Card>
    );
  }

  return (
    <Tabs
      value={role}
      onValueChange={(v) => setRole(v as "SP" | "RP")}
      className="mt-3"
    >
      <TabsList>
        <TabsTrigger value="SP">
          Starting Pitchers
          <Badge tone="neutral" className="ml-2">
            {byRole.SP.length}
          </Badge>
        </TabsTrigger>
        <TabsTrigger value="RP">
          Relief Pitchers
          <Badge tone="neutral" className="ml-2">
            {byRole.RP.length}
          </Badge>
        </TabsTrigger>
      </TabsList>
      <TabsContent value="SP">
        <PitcherTable players={byRole.SP} />
      </TabsContent>
      <TabsContent value="RP">
        <PitcherTable players={byRole.RP} />
      </TabsContent>
    </Tabs>
  );
}

function PitcherTable({ players }: { players: RosterPlayer[] }) {
  const navigate = useNavigate();
  const [sortKey, setSortKey] = usePersistedState<SortKey>(
    "pitchers:sortKey",
    "overall",
  );
  const [sortDir, setSortDir] = usePersistedState<SortDir>(
    "pitchers:sortDir",
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
        <CardContent className="py-10 text-sm text-muted">
          No pitchers in this role.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="mt-4">
      <CardHeader>
        <div>
          <CardTitle>{players.length} pitchers</CardTitle>
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
                  label="Role"
                  keyId="role"
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
                    {pitcherRole(p)}
                    {p.preferred_pitching_role &&
                    p.preferred_pitching_role.toUpperCase() !== pitcherRole(p) ? (
                      <span className="ml-1 text-[10px] text-muted">
                        ({p.preferred_pitching_role})
                      </span>
                    ) : null}
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
    case "role":
      return pitcherRole(p);
    case "bats":
      return p.bats;
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
      <span
        className={cn(
          "font-display font-semibold tabular-nums",
          display >= 85
            ? "text-success"
            : display >= 70
            ? "text-amber-text"
            : display >= 50
            ? "text-ink"
            : "text-subtle",
        )}
      >
        {Math.round(display)}
      </span>
      {Number.isFinite(stars) && stars > 0 && (
        <StarRating value={stars} size="h-2.5 w-2.5" />
      )}
    </div>
  );
}

function RatingCell({ value }: { value: number | string | null | undefined }) {
  if (value == null || value === "" || value === 0)
    return <span className="text-subtle">—</span>;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return <>{String(value)}</>;
  const tone =
    n >= 85
      ? "text-success"
      : n >= 70
      ? "text-amber-text"
      : n >= 50
      ? "text-ink"
      : "text-subtle";
  return <span className={tone}>{Math.round(n)}</span>;
}
