/**
 * Port of ui/depth_chart_dialog.py.
 *
 * Per-position ordered priority list (up to MAX_DEPTH per slot). Used by
 * the autofill + injury replacement flows in the simulator, so saves here
 * immediately affect the next Sim Day.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  GripVertical,
  Loader2,
  RotateCcw,
  Save,
  Sparkles,
  Trash2,
} from "lucide-react";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { api, type RosterPlayer } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { useActiveTeamColor } from "@/lib/team-colors";
import { useAutosaveDraft } from "@/lib/autosave";
import { useHotkey } from "@/lib/use-hotkey";
import { useTeams } from "@/lib/use-teams";
import { useLiveValidation } from "@/lib/use-live-validation";
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

export function DepthChartPage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;

  const teams = useTeams({ enabled: !teamId });
  const activeTeamId = teamId ?? teams.data?.[0]?.team_id ?? null;
  const teamAccentColor = useActiveTeamColor(activeTeamId ?? undefined);

  if (!activeTeamId) {
    return (
      <AppShell title="Depth Chart">
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
      title="Depth Chart"
      subtitle={`Team ${activeTeamId} · ordered priority per position`}
      teamAccentColor={teamAccentColor}
    >
      <DepthChartEditor teamId={activeTeamId} />
    </AppShell>
  );
}

// ---------------------------------------------------------------------------

function DepthChartEditor({ teamId }: { teamId: string }) {
  const queryClient = useQueryClient();

  const chartQuery = useQuery({
    queryKey: ["depth-chart", teamId],
    queryFn: () => api.depthChart(teamId),
  });
  const rosterQuery = useQuery({
    queryKey: ["team-roster", teamId],
    queryFn: () => api.teamRoster(teamId),
  });

  const [draft, setDraft] = useState<Record<string, string[]>>({});
  const [dirty, setDirty] = useState(false);

  const { autosavedDraft, clearDraft, lastSavedAt } = useAutosaveDraft({
    key: `depth-chart:${teamId}`,
    data: draft,
    dirty,
  });

  useEffect(() => {
    if (chartQuery.data) {
      const next: Record<string, string[]> = {};
      for (const pos of chartQuery.data.positions) {
        next[pos] = [...(chartQuery.data.chart[pos] ?? [])];
      }
      setDraft(next);
      setDirty(false);
    }
  }, [chartQuery.data]);

  const saveMut = useMutation({
    mutationFn: (chart: Record<string, string[]>) =>
      api.saveDepthChart(teamId, chart),
    onSuccess: (data) => {
      queryClient.setQueryData(["depth-chart", teamId], data);
      setDirty(false);
    },
  });
  const autofillMut = useMutation({
    mutationFn: () => api.autofillDepthChart(teamId),
    onSuccess: (data) => {
      queryClient.setQueryData(["depth-chart", teamId], data);
      const next: Record<string, string[]> = {};
      for (const pos of data.positions) {
        next[pos] = [...(data.chart[pos] ?? [])];
      }
      setDraft(next);
      // Server already persisted the regenerated chart, so we're back
      // to a clean state — clear the dirty flag and the autosaved draft.
      setDirty(false);
      clearDraft();
    },
  });

  const activePlayers: RosterPlayer[] = useMemo(() => {
    if (!rosterQuery.data) return [];
    const levels = rosterQuery.data.levels;
    return [
      ...(levels.ACT ?? []),
      ...(levels.AAA ?? []),
      ...(levels.LOW ?? []),
    ];
  }, [rosterQuery.data]);

  const byId = useMemo(() => {
    const m: Record<string, RosterPlayer> = {};
    for (const p of activePlayers) m[p.player_id] = p;
    return m;
  }, [activePlayers]);

  // All hooks MUST run unconditionally before any early return below.
  const liveValidation = useLiveValidation(
    () => api.validateDepthChart(teamId, draft),
    [draft, teamId],
  );
  useHotkey(
    "mod+s",
    () => {
      if (dirty && !saveMut.isPending) saveMut.mutate(draft);
    },
    { enabled: dirty && !saveMut.isPending },
  );

  if (chartQuery.isLoading || rosterQuery.isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-10">
          <Loader2 className="h-5 w-5 animate-spin text-amber" />
          <span className="text-sm text-muted">Loading depth chart…</span>
        </CardContent>
      </Card>
    );
  }

  if (chartQuery.isError || !chartQuery.data) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-10">
          <AlertTriangle className="h-5 w-5 text-warning" />
          <span className="text-sm">Failed to load depth chart.</span>
        </CardContent>
      </Card>
    );
  }

  const { positions, max_depth } = chartQuery.data;

  function update(pos: string, list: string[]) {
    setDraft((prev) => ({ ...prev, [pos]: list }));
    setDirty(true);
  }

  function addSlot(pos: string, playerId: string) {
    if (!playerId) return;
    const current = draft[pos] ?? [];
    if (current.includes(playerId)) return;
    if (current.length >= max_depth) return;
    update(pos, [...current, playerId]);
  }

  function removeSlot(pos: string, idx: number) {
    const current = draft[pos] ?? [];
    update(
      pos,
      current.filter((_, i) => i !== idx),
    );
  }

  function moveSlot(pos: string, idx: number, delta: number) {
    const current = [...(draft[pos] ?? [])];
    const target = idx + delta;
    if (target < 0 || target >= current.length) return;
    [current[idx], current[target]] = [current[target], current[idx]];
    update(pos, current);
  }

  function reorderSlot(pos: string, from: number, to: number) {
    const current = [...(draft[pos] ?? [])];
    if (
      from < 0 ||
      to < 0 ||
      from >= current.length ||
      to >= current.length ||
      from === to
    )
      return;
    const [moved] = current.splice(from, 1);
    current.splice(to, 0, moved);
    update(pos, current);
  }

  function reset() {
    if (chartQuery.data) {
      const next: Record<string, string[]> = {};
      for (const pos of chartQuery.data.positions) {
        next[pos] = [...(chartQuery.data.chart[pos] ?? [])];
      }
      setDraft(next);
      setDirty(false);
    }
  }

  function save() {
    saveMut.mutate(draft);
  }

  return (
    <div className="space-y-4">
      {autosavedDraft && !dirty && (
        <Card>
          <CardContent className="flex items-center justify-between gap-3 py-3 text-sm">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-warning" />
              <span>
                Unsaved depth-chart changes from a previous session
                {lastSavedAt
                  ? ` (autosaved ${new Date(lastSavedAt).toLocaleString()})`
                  : ""}
                .
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={clearDraft}>
                Dismiss
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  setDraft(autosavedDraft);
                  setDirty(true);
                  clearDraft();
                }}
              >
                Restore
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
      {(liveValidation.errors.length > 0 || liveValidation.warnings.length > 0) && (
        <Card>
          <CardContent className="space-y-1 py-3 text-xs">
            {liveValidation.errors.length > 0 && (
              <>
                <div className="flex items-center gap-1 font-semibold text-danger">
                  <AlertTriangle className="h-3 w-3" /> {liveValidation.errors.length} error
                  {liveValidation.errors.length === 1 ? "" : "s"}
                </div>
                <ul className="list-disc pl-5 text-danger/90">
                  {liveValidation.errors.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              </>
            )}
            {liveValidation.warnings.length > 0 && (
              <>
                <div className="flex items-center gap-1 font-semibold text-warning">
                  <AlertTriangle className="h-3 w-3" /> {liveValidation.warnings.length} warning
                  {liveValidation.warnings.length === 1 ? "" : "s"}
                </div>
                <ul className="list-disc pl-5 text-warning/90">
                  {liveValidation.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </>
            )}
          </CardContent>
        </Card>
      )}
      <div className="flex items-center justify-between">
        <div className="text-xs text-muted">
          Top of each list gets priority when autofilling lineups and when
          replacing injured players. Up to {max_depth} per position.
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => autofillMut.mutate()}
            disabled={autofillMut.isPending || saveMut.isPending}
            title="Auto-populate every position from the current roster + ratings (overwrites the existing chart)"
          >
            {autofillMut.isPending ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="mr-1 h-4 w-4" />
            )}
            Auto-generate
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={reset}
            disabled={!dirty || saveMut.isPending}
          >
            <RotateCcw className="mr-1 h-4 w-4" /> Reset
          </Button>
          <Button
            onClick={save}
            disabled={!dirty || saveMut.isPending}
            size="sm"
          >
            {saveMut.isPending ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-1 h-4 w-4" />
            )}
            Save
          </Button>
        </div>
      </div>
      {autofillMut.isError && (
        <Card>
          <CardContent className="flex items-center gap-2 py-3 text-sm text-danger">
            <AlertTriangle className="h-4 w-4" />
            <span>{(autofillMut.error as Error).message}</span>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {positions.map((pos) => {
          const slots = draft[pos] ?? [];
          const used = new Set(slots);
          const available = activePlayers.filter(
            (p) => !used.has(p.player_id),
          );
          return (
            <Card key={pos}>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center justify-between text-base">
                  <span>{pos}</span>
                  <Badge>
                    {slots.length} / {max_depth}
                  </Badge>
                </CardTitle>
                <CardDescription>
                  Ordered priority — first entry is the primary starter.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {slots.length === 0 && (
                  <div className="text-xs italic text-muted">No depth set.</div>
                )}
                <SortableSlotList
                  pos={pos}
                  slots={slots}
                  byId={byId}
                  onReorder={reorderSlot}
                  onMove={moveSlot}
                  onRemove={removeSlot}
                />
                {slots.length < max_depth && (
                  <select
                    className="w-full rounded-md border border-border bg-surface px-2 py-1 text-sm"
                    value=""
                    onChange={(e) => {
                      addSlot(pos, e.target.value);
                      e.target.value = "";
                    }}
                  >
                    <option value="">+ Add player…</option>
                    {available.map((p) => (
                      <option key={p.player_id} value={p.player_id}>
                        {p.first_name} {p.last_name} · {p.primary_position} ({p.level})
                      </option>
                    ))}
                  </select>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      {saveMut.isError && (
        <Card>
          <CardContent className="flex items-start gap-3 py-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning" />
            <span className="whitespace-pre-line text-sm">
              {(saveMut.error as Error).message || "Save failed."}
            </span>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Drag-to-reorder priority list (one DndContext per position so a drag never
// crosses into another position). The ↑/↓ buttons stay for keyboard/touchpad.

function SortableSlotList({
  pos,
  slots,
  byId,
  onReorder,
  onMove,
  onRemove,
}: {
  pos: string;
  slots: string[];
  byId: Record<string, RosterPlayer>;
  onReorder: (pos: string, from: number, to: number) => void;
  onMove: (pos: string, idx: number, delta: number) => void;
  onRemove: (pos: string, idx: number) => void;
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );
  // Ordering is the thing being dragged, so ids pin to positional slots
  // rather than player ids (which could repeat as "not on roster" entries).
  const ids = slots.map((_, i) => `${pos}-slot-${i}`);

  function handleDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    onReorder(pos, from, to);
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        <div className="space-y-2">
          {slots.map((pid, idx) => {
            const player = byId[pid];
            const label = player
              ? `${player.first_name} ${player.last_name} · ${player.primary_position}`
              : `${pid} (not on active roster)`;
            return (
              <SortableSlot
                key={ids[idx]}
                id={ids[idx]!}
                idx={idx}
                label={label}
                isLast={idx === slots.length - 1}
                onMoveUp={() => onMove(pos, idx, -1)}
                onMoveDown={() => onMove(pos, idx, 1)}
                onRemove={() => onRemove(pos, idx)}
              />
            );
          })}
        </div>
      </SortableContext>
    </DndContext>
  );
}

function SortableSlot({
  id,
  idx,
  label,
  isLast,
  onMoveUp,
  onMoveDown,
  onRemove,
}: {
  id: string;
  idx: number;
  label: string;
  isLast: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  };
  return (
    <div
      ref={setNodeRef}
      style={style}
      className="flex items-center gap-2 rounded-md border border-border bg-surface px-2 py-1 text-sm"
    >
      <button
        type="button"
        className="cursor-grab touch-none rounded-sm p-1 text-muted hover:bg-surfaceAlt hover:text-ink"
        aria-label="Drag to reorder"
        {...attributes}
        {...listeners}
      >
        <GripVertical className="h-3.5 w-3.5" />
      </button>
      <span className="w-5 text-xs text-muted">{idx + 1}.</span>
      <span className="flex-1 truncate">{label}</span>
      <Button
        variant="ghost"
        size="icon"
        onClick={onMoveUp}
        disabled={idx === 0}
        title="Move up"
      >
        <ArrowUp className="h-4 w-4" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        onClick={onMoveDown}
        disabled={isLast}
        title="Move down"
      >
        <ArrowDown className="h-4 w-4" />
      </Button>
      <Button variant="ghost" size="icon" onClick={onRemove} title="Remove">
        <Trash2 className="h-4 w-4 text-danger" />
      </Button>
    </div>
  );
}
