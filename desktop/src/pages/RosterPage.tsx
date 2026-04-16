/**
 * Phase 4 port of ui/roster_page.py (read-only first pass).
 *
 * Renders a team's roster split by level (ACT / AAA / LOW / DL / IR) with a
 * sortable rating-heavy table. Editing moves (promote/demote/DL) will layer
 * on top in a follow-up and use POST endpoints backed by
 * services.roster_moves.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  HeartPulse,
  Loader2,
  MoreHorizontal,
  Users,
} from "lucide-react";

import {
  api,
  type RosterLevel,
  type RosterPlayer,
  type TeamRoster,
} from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  CardContent,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";

const LEVEL_ORDER: RosterLevel[] = ["ACT", "AAA", "LOW", "DL", "IR"];
const LEVEL_LABEL: Record<RosterLevel, string> = {
  ACT: "Active",
  AAA: "AAA",
  LOW: "Low-A",
  DL: "Disabled",
  IR: "Injured Res.",
};

// The ratings we surface in the table header. Keep these consistent across
// hitters/pitchers so sort + layout stay stable; pitcher-specific ratings
// (FB, control, movement, endurance) show up as extra columns below.
const HITTER_COLUMNS: Array<{ key: string; label: string }> = [
  { key: "ch", label: "CH" },
  { key: "ph", label: "PH" },
  { key: "sp", label: "SP" },
  { key: "eye", label: "EYE" },
  { key: "fa", label: "FA" },
  { key: "arm", label: "ARM" },
];
const PITCHER_COLUMNS: Array<{ key: string; label: string }> = [
  { key: "fb", label: "FB" },
  { key: "control", label: "CTRL" },
  { key: "movement", label: "MOV" },
  { key: "endurance", label: "END" },
  { key: "arm", label: "ARM" },
  { key: "fa", label: "FA" },
];

type SortKey = "name" | "pos" | "bats" | "role" | string;
type SortDir = "asc" | "desc";

interface MoveArgs {
  player_id: string;
  to: RosterLevel;
  dl_tier?: "dl15" | "dl45";
}

interface RosterActions {
  teamId: string;
  move: (args: MoveArgs) => void;
  cut: (playerId: string) => void;
  pending: boolean;
  error: string | null;
}

export function RosterPage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;
  const queryClient = useQueryClient();

  const teams = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
    enabled: !teamId,
  });

  const fallbackTeamId = teamId ?? teams.data?.[0]?.team_id ?? null;

  const roster = useQuery({
    queryKey: ["team-roster", fallbackTeamId],
    queryFn: () => api.teamRoster(fallbackTeamId as string),
    enabled: !!fallbackTeamId,
  });

  const moveMutation = useMutation({
    mutationFn: (args: MoveArgs) =>
      api.moveRoster(fallbackTeamId as string, args),
    onSuccess: (data) => {
      queryClient.setQueryData(["team-roster", fallbackTeamId], data);
    },
  });
  const cutMutation = useMutation({
    mutationFn: (playerId: string) =>
      api.cutRoster(fallbackTeamId as string, playerId),
    onSuccess: (data) => {
      queryClient.setQueryData(["team-roster", fallbackTeamId], data);
    },
  });

  const actions: RosterActions | null = fallbackTeamId
    ? {
        teamId: fallbackTeamId,
        move: (args) => moveMutation.mutate(args),
        cut: (pid) => cutMutation.mutate(pid),
        pending: moveMutation.isPending || cutMutation.isPending,
        error:
          (moveMutation.error as Error | null)?.message ??
          (cutMutation.error as Error | null)?.message ??
          null,
      }
    : null;

  if (!fallbackTeamId) {
    return (
      <AppShell title="Roster">
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
      title="Roster"
      subtitle={`Team ${fallbackTeamId} · ${roster.data?.active_size ?? "—"} active`}
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
      ) : roster.data && actions ? (
        <>
          {actions.error && (
            <div className="mb-4 flex items-center gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              <AlertTriangle className="h-4 w-4" /> {actions.error}
            </div>
          )}
          <RosterTabs roster={roster.data} actions={actions} />
        </>
      ) : null}
    </AppShell>
  );
}

function RosterTabs({
  roster,
  actions,
}: {
  roster: TeamRoster;
  actions: RosterActions;
}) {
  return (
    <Tabs defaultValue="ACT">
      <TabsList>
        {LEVEL_ORDER.map((level) => {
          const count = roster.levels[level]?.length ?? 0;
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
          <RosterLevelTable
            players={roster.levels[level] ?? []}
            level={level}
            actions={actions}
          />
        </TabsContent>
      ))}
    </Tabs>
  );
}

function RosterLevelTable({
  players,
  level,
  actions,
}: {
  players: RosterPlayer[];
  level: RosterLevel;
  actions: RosterActions;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [filter, setFilter] = useState<"all" | "hitters" | "pitchers">("all");

  // Use a pitcher-weighted column set if the filter narrows to pitchers or
  // if the level is mostly pitchers.
  const pitcherHeavy =
    filter === "pitchers" ||
    (filter === "all" &&
      players.length > 0 &&
      players.filter((p) => p.is_pitcher).length / players.length > 0.5);
  const columns = pitcherHeavy ? PITCHER_COLUMNS : HITTER_COLUMNS;

  const filtered = useMemo(() => {
    if (filter === "hitters") return players.filter((p) => !p.is_pitcher);
    if (filter === "pitchers") return players.filter((p) => p.is_pitcher);
    return players;
  }, [players, filter]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    arr.sort((a, b) => {
      const av = getSortValue(a, sortKey);
      const bv = getSortValue(b, sortKey);
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
  }, [filtered, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "name" || key === "pos" ? "asc" : "desc");
    }
  }

  if (players.length === 0) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-10">
          <Users className="h-5 w-5 text-muted" />
          <span className="text-sm text-muted">
            No players on the {LEVEL_LABEL[level].toLowerCase()} roster.
          </span>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <div className="flex items-center justify-between gap-4 border-b border-border/60 px-6 py-3">
        <div className="flex gap-1">
          {(["all", "hitters", "pitchers"] as const).map((opt) => (
            <button
              key={opt}
              onClick={() => setFilter(opt)}
              className={cn(
                "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
                filter === opt
                  ? "bg-amber text-espresso"
                  : "text-muted hover:bg-surfaceAlt hover:text-ink",
              )}
            >
              {opt}
            </button>
          ))}
        </div>
        <div className="text-xs text-muted">{sorted.length} players</div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
              <HeaderCell label="Player" keyId="name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} align="left" />
              <HeaderCell label="Pos" keyId="pos" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
              <HeaderCell label="B" keyId="bats" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
              <HeaderCell label="Role" keyId="role" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
              {columns.map((col) => (
                <HeaderCell
                  key={col.key}
                  label={col.label}
                  keyId={col.key}
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onClick={toggleSort}
                />
              ))}
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((p) => (
              <RosterRow
                key={p.player_id}
                player={p}
                columns={columns}
                level={level}
                actions={actions}
              />
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function getSortValue(p: RosterPlayer, key: SortKey): string | number | null {
  switch (key) {
    case "name":
      return `${p.last_name}, ${p.first_name}`;
    case "pos":
      return p.primary_position;
    case "bats":
      return p.bats;
    case "role":
      return p.role;
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

function RosterRow({
  player,
  columns,
  level,
  actions,
}: {
  player: RosterPlayer;
  columns: Array<{ key: string; label: string }>;
  level: RosterLevel;
  actions: RosterActions;
}) {
  const navigate = useNavigate();
  return (
    <tr className="border-b border-border/40 transition last:border-b-0 hover:bg-surfaceAlt/40">
      <td className="px-6 py-2">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => navigate(`/player/${encodeURIComponent(player.player_id)}`)}
            className="font-semibold text-left hover:text-amber"
          >
            {player.last_name}
            {player.first_name ? `, ${player.first_name}` : ""}
          </button>
          {player.injured && (
            <Badge tone="danger" className="text-[10px]">
              <HeartPulse className="h-3 w-3" /> DL
            </Badge>
          )}
          {player.dl_tier && (
            <Badge tone="warning" className="text-[10px]">
              {player.dl_tier.toUpperCase()}
            </Badge>
          )}
        </div>
        {player.injury_description && (
          <div className="text-[11px] text-muted">
            {player.injury_description}
          </div>
        )}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        {player.primary_position || "—"}
      </td>
      <td className="px-3 py-2 text-right">{player.bats || "—"}</td>
      <td className="px-3 py-2 text-right text-xs uppercase tracking-wider text-muted">
        {player.role || (player.is_pitcher ? "PIT" : "POS")}
      </td>
      {columns.map((col) => (
        <td key={col.key} className="px-3 py-2 text-right tabular-nums">
          <RatingCell value={player.ratings[col.key]} />
        </td>
      ))}
      <td className="px-4 py-2 text-right">
        <RowActionsMenu player={player} level={level} actions={actions} />
      </td>
    </tr>
  );
}

function RowActionsMenu({
  player,
  level,
  actions,
}: {
  player: RosterPlayer;
  level: RosterLevel;
  actions: RosterActions;
}) {
  const destinations: Array<{ target: RosterLevel; label: string }> = [
    { target: "ACT", label: "Move to Active" },
    { target: "AAA", label: "Send to AAA" },
    { target: "LOW", label: "Send to Low-A" },
    { target: "DL", label: "Place on DL (15)" },
    { target: "IR", label: "Place on 60-day IR" },
  ];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Actions for ${player.last_name}`}
          disabled={actions.pending}
        >
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>
          {player.last_name}
          {player.first_name ? `, ${player.first_name}` : ""}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {destinations
          .filter((d) => d.target !== level)
          .map((d) => (
            <DropdownMenuItem
              key={d.target}
              onSelect={() =>
                actions.move({
                  player_id: player.player_id,
                  to: d.target,
                  ...(d.target === "DL" ? { dl_tier: "dl15" } : {}),
                })
              }
            >
              {d.label}
            </DropdownMenuItem>
          ))}
        {level === "DL" && (
          <DropdownMenuItem
            onSelect={() =>
              actions.move({
                player_id: player.player_id,
                to: "DL",
                dl_tier: "dl45",
              })
            }
          >
            Shift to 45-day DL
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          tone="danger"
          onSelect={() => {
            if (
              window.confirm(
                `Release ${player.last_name}? This drops them to free agency.`,
              )
            ) {
              actions.cut(player.player_id);
            }
          }}
        >
          Release / Cut
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function RatingCell({ value }: { value: number | string | null | undefined }) {
  if (value == null || value === "") return <span className="text-subtle">—</span>;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return <>{String(value)}</>;
  const tone =
    n >= 85 ? "text-success" : n >= 70 ? "text-amber-text" : n >= 50 ? "text-ink" : "text-subtle";
  return <span className={tone}>{Math.round(n)}</span>;
}
