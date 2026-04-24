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
  GripVertical,
  HeartPulse,
  Loader2,
  MoreHorizontal,
  Users,
} from "lucide-react";
import {
  DndContext,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";

import {
  api,
  type RosterLevel,
  type RatingContextEntry,
  type RosterPlayer,
  type TeamRoster,
} from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { useConfirmDialog } from "@/lib/use-confirm";
import { toast } from "@/lib/toast-store";
import { useActiveTeamColor } from "@/lib/team-colors";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { StarRating } from "@/components/StarRating";
import {
  Badge,
  Button,
  Card,
  CardContent,
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
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
  const teamAccentColor = useActiveTeamColor(fallbackTeamId ?? undefined);

  const roster = useQuery({
    queryKey: ["team-roster", fallbackTeamId],
    queryFn: () => api.teamRoster(fallbackTeamId as string),
    enabled: !!fallbackTeamId,
  });

  const moveMutation = useMutation({
    mutationFn: (args: MoveArgs) =>
      api.moveRoster(fallbackTeamId as string, args),
    onSuccess: (data, args) => {
      queryClient.setQueryData(["team-roster", fallbackTeamId], data);
      toast.success(`Moved to ${args.to}`);
    },
  });
  const cutMutation = useMutation({
    mutationFn: (playerId: string) =>
      api.cutRoster(fallbackTeamId as string, playerId),
    onSuccess: (data) => {
      queryClient.setQueryData(["team-roster", fallbackTeamId], data);
      toast.success("Released to free agency");
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
      ) : roster.data && actions ? (
        <>
          {actions.error && (
            <div className="mb-4 flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span className="whitespace-pre-line">{actions.error}</span>
            </div>
          )}
          <RosterTabs roster={roster.data} actions={actions} />
        </>
      ) : null}
    </AppShell>
  );
}

const POSITION_CONTEXT_KEY = "nexgen:roster:position-context";

function readPositionContextPref(): boolean {
  try {
    const raw = window.localStorage.getItem(POSITION_CONTEXT_KEY);
    if (raw === null) return true; // default on — matches PyQt
    return raw === "1";
  } catch {
    return true;
  }
}

function writePositionContextPref(value: boolean) {
  try {
    window.localStorage.setItem(POSITION_CONTEXT_KEY, value ? "1" : "0");
  } catch {
    /* ignore */
  }
}

function RosterTabs({
  roster,
  actions,
}: {
  roster: TeamRoster;
  actions: RosterActions;
}) {
  const [positionContext, setPositionContextState] = useState(readPositionContextPref);
  const setPositionContext = (value: boolean) => {
    setPositionContextState(value);
    writePositionContextPref(value);
  };

  // Require a small drag distance before activating so single clicks
  // (open profile, context menu, sort) aren't consumed by DnD.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over) return;
    const toLevel = String(over.id) as RosterLevel;
    const from = active.data.current?.level as RosterLevel | undefined;
    const pid = String(active.id);
    if (!pid || !toLevel || toLevel === from) return;
    if (toLevel === "DL") {
      actions.move({ player_id: pid, to: toLevel, dl_tier: "dl15" });
    } else {
      actions.move({ player_id: pid, to: toLevel });
    }
  }

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <Tabs defaultValue="ACT">
        <div className="flex items-center justify-between gap-3">
          <TabsList>
            {LEVEL_ORDER.map((level) => {
              const count = roster.levels[level]?.length ?? 0;
              return (
                <DroppableTabTrigger key={level} level={level} count={count} />
              );
            })}
          </TabsList>
          <label
            className="flex cursor-pointer items-center gap-2 rounded-md border border-border bg-surfaceAlt/50 px-3 py-1.5 text-xs uppercase tracking-wider text-muted hover:text-ink"
            title="Show each hitter's percentile against other players at the same position (C/1B/2B/3B/SS/OF). Pitchers compare against the full pitcher pool."
          >
            <input
              type="checkbox"
              checked={positionContext}
              onChange={(e) => setPositionContext(e.target.checked)}
              className="h-3 w-3 accent-amber"
            />
            Position context
          </label>
        </div>
        {LEVEL_ORDER.map((level) => (
          <TabsContent key={level} value={level}>
            <RosterLevelTable
              players={roster.levels[level] ?? []}
              level={level}
              actions={actions}
              positionContext={positionContext}
            />
          </TabsContent>
        ))}
      </Tabs>
    </DndContext>
  );
}

/** A TabsTrigger that also accepts dropped player rows. Highlights while
 *  a valid drag hovers. DnD identity = the roster level string. */
function DroppableTabTrigger({
  level,
  count,
}: {
  level: RosterLevel;
  count: number;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: level });
  return (
    <TabsTrigger
      value={level}
      ref={setNodeRef}
      className={cn(
        "transition",
        isOver && "ring-2 ring-amber/60 ring-offset-1 ring-offset-transparent",
      )}
    >
      <span>{LEVEL_LABEL[level]}</span>
      <Badge tone="neutral" className="ml-2">
        {count}
      </Badge>
    </TabsTrigger>
  );
}

function RosterLevelTable({
  players,
  level,
  actions,
  positionContext,
}: {
  players: RosterPlayer[];
  level: RosterLevel;
  actions: RosterActions;
  positionContext: boolean;
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
              <HeaderCell label="OVR" keyId="overall" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
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
                positionContext={positionContext}
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
  positionContext,
}: {
  player: RosterPlayer;
  columns: Array<{ key: string; label: string }>;
  level: RosterLevel;
  actions: RosterActions;
  positionContext: boolean;
}) {
  const navigate = useNavigate();
  const { confirm, dialog: confirmDialog } = useConfirmDialog();
  // Each row is draggable — drop on a sibling TabsTrigger to move
  // between levels. Stored ``level`` lets handleDragEnd skip no-op drops.
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: player.player_id,
    data: { level },
  });
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
    <tr
      ref={setNodeRef}
      className={cn(
        "border-b border-border/40 transition last:border-b-0 hover:bg-surfaceAlt/40",
        isDragging && "opacity-40",
      )}
    >
      <td className="px-6 py-2">
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="cursor-grab touch-none text-muted hover:text-amber active:cursor-grabbing"
            aria-label={`Drag ${player.last_name} to another roster level`}
            {...attributes}
            {...listeners}
          >
            <GripVertical className="h-4 w-4" />
          </button>
          <PlayerAvatar
            playerId={player.player_id}
            initials={`${player.first_name?.[0] ?? ""}${player.last_name?.[0] ?? ""}`}
            className="h-7 w-7 shrink-0 overflow-hidden rounded-md text-[10px]"
          />
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
      <td className="px-3 py-2 text-right tabular-nums">
        <OverallCell player={player} />
      </td>
      {columns.map((col) => (
        <td key={col.key} className="px-3 py-2 text-right tabular-nums">
          <RatingCell
            value={player.ratings[col.key]}
            context={
              positionContext
                ? player.ratings_context?.[col.key]
                : undefined
            }
          />
        </td>
      ))}
      <td className="px-4 py-2 text-right">
        <RowActionsMenu player={player} level={level} actions={actions} />
      </td>
    </tr>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuLabel>
          {player.last_name}
          {player.first_name ? `, ${player.first_name}` : ""}
        </ContextMenuLabel>
        <ContextMenuSeparator />
        <ContextMenuItem
          onSelect={() =>
            navigate(`/player/${encodeURIComponent(player.player_id)}`)
          }
        >
          Open profile
        </ContextMenuItem>
        <ContextMenuSeparator />
        {ROSTER_DESTINATIONS
          .filter((d) => d.target !== level)
          .map((d) => (
            <ContextMenuItem
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
            </ContextMenuItem>
          ))}
        {level === "DL" && (
          <ContextMenuItem
            onSelect={() =>
              actions.move({
                player_id: player.player_id,
                to: "DL",
                dl_tier: "dl45",
              })
            }
          >
            Shift to 45-day DL
          </ContextMenuItem>
        )}
        <ContextMenuSeparator />
        <ContextMenuItem
          tone="danger"
          onSelect={async () => {
            if (
              await confirm({
                title: `Release ${player.last_name}?`,
                description: "The player drops to free agency.",
                confirmLabel: "Release",
                danger: true,
              })
            ) {
              actions.cut(player.player_id);
            }
          }}
        >
          Release / Cut
        </ContextMenuItem>
      </ContextMenuContent>
      {confirmDialog}
    </ContextMenu>
  );
}

const ROSTER_DESTINATIONS: Array<{ target: RosterLevel; label: string }> = [
  { target: "ACT", label: "Move to Active" },
  { target: "AAA", label: "Send to AAA" },
  { target: "LOW", label: "Send to Low-A" },
  { target: "DL", label: "Place on DL (15)" },
  { target: "IR", label: "Place on 60-day IR" },
];

function RowActionsMenu({
  player,
  level,
  actions,
}: {
  player: RosterPlayer;
  level: RosterLevel;
  actions: RosterActions;
}) {
  const { confirm, dialog: confirmDialog } = useConfirmDialog();
  const destinations = ROSTER_DESTINATIONS;
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
          onSelect={async () => {
            if (
              await confirm({
                title: `Release ${player.last_name}?`,
                description: "The player drops to free agency.",
                confirmLabel: "Release",
                danger: true,
              })
            ) {
              actions.cut(player.player_id);
            }
          }}
        >
          Release / Cut
        </DropdownMenuItem>
      </DropdownMenuContent>
      {confirmDialog}
    </DropdownMenu>
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

function RatingCell({
  value,
  context,
}: {
  value: number | string | null | undefined;
  context?: RatingContextEntry;
}) {
  if (value == null || value === "") return <span className="text-subtle">—</span>;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return <>{String(value)}</>;
  const tone =
    n >= 85 ? "text-success" : n >= 70 ? "text-amber-text" : n >= 50 ? "text-ink" : "text-subtle";
  if (!context) {
    return <span className={tone}>{Math.round(n)}</span>;
  }
  const bucket = context.bucket ?? "pool";
  const avgText = context.avg == null ? "--" : String(context.avg);
  return (
    <span
      className="inline-flex items-baseline justify-end gap-1"
      title={`Top ${context.top_pct}% of ${bucket} (avg ${avgText})`}
    >
      <span className={tone}>{Math.round(n)}</span>
      <span className="text-[10px] text-muted">({context.top_pct}%)</span>
    </span>
  );
}
