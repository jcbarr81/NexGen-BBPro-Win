/**
 * Phase 4 port of ui/lineup_editor.py + ui/pitching_editor.py.
 *
 * Combined editor for a team's batting lineups (vs LHP / vs RHP) and its
 * pitching-staff role slots. Everything edits the same CSV files the
 * simulator reads, so a save here immediately affects the next Sim Day.
 *
 * Intentionally simple interactions -- no drag-and-drop. Move-up / move-
 * down buttons per row keep the UX snappy on touchpads and work with
 * keyboard focus. Autofill reuses the existing Python helper.
 */

import { useEffect, useMemo, useState } from "react";

import { usePersistedState } from "@/lib/use-persisted-state";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ChevronsUpDown,
  Loader2,
  Save,
  Sparkles,
  Trash2,
} from "lucide-react";

import {
  api,
  type Lineup,
  type LineupRow,
  type LineupVs,
  type PitchingStaffEntry,
  type RosterPlayer,
} from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { useActiveTeamColor } from "@/lib/team-colors";
import { useAutosaveDraft } from "@/lib/autosave";
import { useHotkey } from "@/lib/use-hotkey";
import { useLiveValidation } from "@/lib/use-live-validation";
import { AppShell } from "@/components/layout/AppShell";
import { DiamondDiagram, type DiamondPosition } from "@/components/lineup/DiamondDiagram";
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
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";

const HITTER_POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"];
const STAFF_ROLES = [
  "SP1",
  "SP2",
  "SP3",
  "SP4",
  "SP5",
  "LR",
  "MR1",
  "MR2",
  "MR3",
  "SU",
  "CL",
];

export function LineupPage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;

  const teams = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
    enabled: !teamId,
  });
  const activeTeamId = teamId ?? teams.data?.[0]?.team_id ?? null;
  const teamAccentColor = useActiveTeamColor(activeTeamId ?? undefined);

  if (!activeTeamId) {
    return (
      <AppShell title="Lineup">
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
      title="Lineup"
      subtitle={`Team ${activeTeamId} · batting order + pitching staff`}
      teamAccentColor={teamAccentColor}
    >
      <LineupEditor teamId={activeTeamId} />
    </AppShell>
  );
}

// ---------------------------------------------------------------------------

function LineupEditor({ teamId }: { teamId: string }) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = usePersistedState<
    "rhp" | "lhp" | "pitching"
  >("lineup:tab", "rhp");
  const roster = useQuery({
    queryKey: ["team-roster", teamId],
    queryFn: () => api.teamRoster(teamId),
  });

  const autofill = useMutation({
    mutationFn: (vs?: "lhp" | "rhp") => api.autofillLineup(teamId, vs),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["lineup", teamId] });
    },
  });
  const currentSide: "lhp" | "rhp" | null =
    activeTab === "lhp" ? "lhp" : activeTab === "rhp" ? "rhp" : null;

  return (
    <Tabs
      value={activeTab}
      onValueChange={(v) => setActiveTab(v as typeof activeTab)}
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <TabsList>
          <TabsTrigger value="rhp">vs RHP</TabsTrigger>
          <TabsTrigger value="lhp">vs LHP</TabsTrigger>
          <TabsTrigger value="pitching">Pitching Staff</TabsTrigger>
        </TabsList>
        {activeTab !== "pitching" && (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={() => currentSide && autofill.mutate(currentSide)}
              disabled={autofill.isPending || !currentSide}
              title={
                currentSide
                  ? `Autofill the vs ${currentSide.toUpperCase()} lineup only`
                  : ""
              }
            >
              {autofill.isPending && autofill.variables === currentSide ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              Autofill vs {currentSide ? currentSide.toUpperCase() : ""}
            </Button>
            <Button
              variant="outline"
              onClick={() => autofill.mutate(undefined)}
              disabled={autofill.isPending}
              title="Autofill both vs LHP and vs RHP lineups"
            >
              {autofill.isPending && autofill.variables === undefined ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              Autofill both
            </Button>
          </div>
        )}
      </div>

      {autofill.isError && (
        <div className="mb-4 flex items-center gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          <AlertTriangle className="h-4 w-4" />
          {(autofill.error as Error).message}
        </div>
      )}

      <TabsContent value="rhp">
        <LineupTab teamId={teamId} vs="rhp" roster={roster.data?.levels.ACT ?? []} />
      </TabsContent>
      <TabsContent value="lhp">
        <LineupTab teamId={teamId} vs="lhp" roster={roster.data?.levels.ACT ?? []} />
      </TabsContent>
      <TabsContent value="pitching">
        <PitchingTab teamId={teamId} roster={roster.data?.levels.ACT ?? []} />
      </TabsContent>
    </Tabs>
  );
}

// ---------------------------------------------------------------------------

function LineupTab({
  teamId,
  vs,
  roster,
}: {
  teamId: string;
  vs: LineupVs;
  roster: RosterPlayer[];
}) {
  const queryClient = useQueryClient();
  const lineup = useQuery({
    queryKey: ["lineup", teamId, vs],
    queryFn: () => api.getLineup(teamId, vs),
  });
  const [rows, setRows] = useState<LineupRow[]>([]);
  const [dirty, setDirty] = useState(false);

  // Autosave rescue — localStorage-backed draft restored on mount.
  const { autosavedDraft, clearDraft, lastSavedAt } = useAutosaveDraft({
    key: `lineup:${teamId}:${vs}`,
    data: rows,
    dirty,
  });

  // Hydrate local state from the server response.
  useEffect(() => {
    if (lineup.data) {
      const loaded = lineup.data.lineup.length
        ? lineup.data.lineup
        : emptyLineup();
      setRows(loaded);
      setDirty(false);
    }
  }, [lineup.data]);

  const save = useMutation({
    mutationFn: (payload: LineupRow[]) => api.saveLineup(teamId, vs, payload),
    onSuccess: (data: Lineup) => {
      queryClient.setQueryData(["lineup", teamId, vs], data);
      setDirty(false);
    },
  });

  const hitters = useMemo(
    () => roster.filter((p) => !p.is_pitcher),
    [roster],
  );
  const hittersById = useMemo(() => {
    const m = new Map<string, RosterPlayer>();
    for (const p of hitters) m.set(p.player_id, p);
    return m;
  }, [hitters]);

  function update(idx: number, patch: Partial<LineupRow>) {
    setRows((prev) => {
      const copy = [...prev];
      copy[idx] = { ...copy[idx], ...patch, order: idx + 1 } as LineupRow;
      return copy.map((row, i) => ({ ...row, order: i + 1 }));
    });
    setDirty(true);
  }

  function moveTo(from: number, to: number) {
    if (from === to || from < 0 || to < 0) return;
    setRows((prev) => {
      if (from >= prev.length || to >= prev.length) return prev;
      return arrayMove(prev, from, to).map((row, i) => ({ ...row, order: i + 1 }));
    });
    setDirty(true);
  }

  function move(idx: number, delta: number) {
    setRows((prev) => {
      const copy = [...prev];
      const target = idx + delta;
      if (target < 0 || target >= copy.length) return prev;
      [copy[idx], copy[target]] = [copy[target]!, copy[idx]!];
      return copy.map((row, i) => ({ ...row, order: i + 1 }));
    });
    setDirty(true);
  }

  function clearSlot(idx: number) {
    update(idx, { player_id: "", position: rows[idx]?.position ?? "" });
  }

  // Collapse the batting rows into a position→player map for the diamond.
  // Picks up the first occurrence of each position, which is correct since
  // a lineup slot should use a position at most once.
  //
  // IMPORTANT: this hook MUST sit before any early returns below so hook
  // counts stay stable between loading and loaded renders (otherwise React
  // throws "Rendered more hooks than during the previous render").
  const diamondPositions: Partial<Record<string, DiamondPosition>> = useMemo(() => {
    const out: Partial<Record<string, DiamondPosition>> = {};
    for (const row of rows) {
      if (!row.position || !row.player_id) continue;
      if (out[row.position]) continue;
      const p = hittersById.get(row.player_id);
      const label = p ? `${p.first_name[0] ?? ""}. ${p.last_name}`.trim() : row.player_id;
      out[row.position] = {
        code: row.position,
        label: label || row.player_id,
        sub: `#${row.order}`,
      };
    }
    return out;
  }, [rows, hittersById]);

  // All hooks MUST sit before any early returns so hook counts stay stable
  // between loading and loaded renders. Don't move these below the
  // isLoading/isError guards — React will throw "Rendered more hooks than
  // during the previous render".
  const liveValidation = useLiveValidation(
    () => api.validateLineup(teamId, vs, rows),
    [rows, vs, teamId],
  );

  const selectedIds = new Set(rows.map((r) => r.player_id).filter(Boolean));
  const validEntries = rows.filter((r) => r.player_id && r.position).length;

  // Save is gated by server-side validation too, but we pre-disable the
  // button when the live probe says no-op.
  const canSave =
    validEntries === 9 &&
    dirty &&
    !save.isPending &&
    (liveValidation.ok || liveValidation.pending);

  // Ctrl+S / Cmd+S saves the lineup. Only active when something is
  // actually saveable so the keystroke stays meaningful.
  useHotkey(
    "mod+s",
    () => {
      if (canSave) save.mutate(rows);
    },
    { enabled: canSave },
  );

  // Early returns live here, AFTER every hook, so hook counts stay stable.
  if (lineup.isLoading) {
    return <LoadingCard />;
  }
  if (lineup.isError) {
    return <ErrorCard message={(lineup.error as Error).message} />;
  }

  return (
    <>
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
      <Card className="p-3">
        <DiamondDiagram positions={diamondPositions} />
      </Card>
      {autosavedDraft && !dirty && (
        <Card className="xl:col-span-2">
          <CardContent className="flex items-center justify-between gap-3 py-3 text-sm">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-warning" />
              <span>
                Unsaved changes from a previous session found
                {lastSavedAt
                  ? ` (autosaved ${new Date(lastSavedAt).toLocaleString()})`
                  : ""}
                .
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={clearDraft}
                title="Discard the autosaved draft"
              >
                Dismiss
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  setRows(autosavedDraft);
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
      <Card>
      <CardHeader>
        <div>
          <CardTitle>
            Batting order · vs {vs.toUpperCase()}
          </CardTitle>
          <CardDescription>
            {lineup.data?.exists
              ? "Loaded from disk. Edits save to data/lineups."
              : "No lineup file yet — build one below."}
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          {dirty && <Badge tone="warning">Unsaved</Badge>}
          <Badge tone={validEntries === 9 ? "success" : "amber"}>
            {validEntries}/9 filled
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {(liveValidation.errors.length > 0 || liveValidation.warnings.length > 0) && (
          <div className="mx-4 mt-3 rounded-md border border-border bg-surface p-3 text-xs">
            {liveValidation.errors.length > 0 && (
              <div className="mb-1">
                <div className="flex items-center gap-1 font-semibold text-danger">
                  <AlertTriangle className="h-3 w-3" /> {liveValidation.errors.length} error
                  {liveValidation.errors.length === 1 ? "" : "s"}
                </div>
                <ul className="mt-1 list-disc pl-5 text-danger/90">
                  {liveValidation.errors.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              </div>
            )}
            {liveValidation.warnings.length > 0 && (
              <div>
                <div className="flex items-center gap-1 font-semibold text-warning">
                  <AlertTriangle className="h-3 w-3" /> {liveValidation.warnings.length} warning
                  {liveValidation.warnings.length === 1 ? "" : "s"}
                </div>
                <ul className="mt-1 list-disc pl-5 text-warning/90">
                  {liveValidation.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
        <LineupTable
          rows={rows}
          hitters={hitters}
          hittersById={hittersById}
          selectedIds={selectedIds}
          onUpdate={update}
          onMove={move}
          onReorder={moveTo}
          onClear={clearSlot}
        />

        {save.isError && (
          <div className="m-4 flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="whitespace-pre-line">
              {(save.error as Error).message}
            </div>
          </div>
        )}

        <div className="flex items-center justify-between gap-3 border-t border-border/60 bg-surfaceAlt/40 px-6 py-3">
          <div className="text-xs text-muted">
            Active roster pool: {hitters.length} hitters
          </div>
          <Button
            onClick={() => save.mutate(rows)}
            disabled={!canSave}
          >
            {save.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Save lineup
          </Button>
        </div>
      </CardContent>
    </Card>
    </div>
    <EligiblePoolPanel players={hitters} kind="hitters" />
    </>
  );
}

/**
 * Draggable batting-order table. Extracted from LineupTab so the
 * DndContext lives at the smallest scope that needs it, and we don't
 * fire onDragEnd during other renders of the page.
 */
function LineupTable({
  rows,
  hitters,
  hittersById,
  selectedIds,
  onUpdate,
  onMove,
  onReorder,
  onClear,
}: {
  rows: LineupRow[];
  hitters: RosterPlayer[];
  hittersById: Map<string, RosterPlayer>;
  selectedIds: Set<string>;
  onUpdate: (idx: number, patch: Partial<LineupRow>) => void;
  onMove: (idx: number, delta: number) => void;
  onReorder: (from: number, to: number) => void;
  onClear: (idx: number) => void;
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );
  // dnd-kit needs stable string ids. Use `slot-<index>` — the ordering
  // itself is the thing being dragged, so the id stays pinned to a
  // positional slot rather than a player (which can be empty/identical).
  const ids = rows.map((_, i) => `slot-${i}`);
  function handleDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    onReorder(from, to);
  }
  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
              <th className="px-2 py-2 text-left font-semibold"></th>
              <th className="px-4 py-2 text-left font-semibold">#</th>
              <th className="px-3 py-2 text-left font-semibold">Player</th>
              <th className="px-3 py-2 text-left font-semibold">Position</th>
              <th className="px-6 py-2 text-right font-semibold">Order</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <SortableLineupRow
                key={ids[idx]}
                id={ids[idx]!}
                row={row}
                idx={idx}
                rows={rows}
                hitters={hitters}
                hittersById={hittersById}
                selectedIds={selectedIds}
                onUpdate={onUpdate}
                onMove={onMove}
                onClear={onClear}
              />
            ))}
          </tbody>
        </table>
      </SortableContext>
    </DndContext>
  );
}

function SortableLineupRow({
  id,
  row,
  idx,
  rows,
  hitters,
  hittersById,
  selectedIds,
  onUpdate,
  onMove,
  onClear,
}: {
  id: string;
  row: LineupRow;
  idx: number;
  rows: LineupRow[];
  hitters: RosterPlayer[];
  hittersById: Map<string, RosterPlayer>;
  selectedIds: Set<string>;
  onUpdate: (idx: number, patch: Partial<LineupRow>) => void;
  onMove: (idx: number, delta: number) => void;
  onClear: (idx: number) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  };
  return (
    <tr
      ref={setNodeRef}
      style={style}
      className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
    >
      <td className="px-2 py-2">
        <button
          type="button"
          className="cursor-grab touch-none rounded-sm p-1 text-muted hover:bg-surfaceAlt hover:text-ink"
          aria-label="Drag to reorder"
          {...attributes}
          {...listeners}
        >
          <GripVertical className="h-3 w-3" />
        </button>
      </td>
      <td className="px-4 py-2 font-mono text-xs text-muted">{idx + 1}</td>
      <td className="px-3 py-2">
        <PlayerSelect
          value={row.player_id}
          hitters={hitters}
          disabledIds={selectedIds}
          onChange={(player_id) => {
            const p = hittersById.get(player_id);
            onUpdate(idx, {
              player_id,
              position: row.position || p?.primary_position || "",
            });
          }}
        />
      </td>
      <td className="px-3 py-2">
        <select
          value={row.position}
          onChange={(e) => onUpdate(idx, { position: e.target.value })}
          className="h-9 w-full rounded-md border border-border bg-canvas/60 px-2 text-xs font-semibold uppercase tracking-wider text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
        >
          <option value="">—</option>
          {HITTER_POSITIONS.map((pos) => (
            <option key={pos} value={pos}>
              {pos}
            </option>
          ))}
        </select>
      </td>
      <td className="px-6 py-2 text-right">
        <div className="inline-flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onMove(idx, -1)}
            disabled={idx === 0}
            aria-label="Move up"
          >
            <ArrowUp className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onMove(idx, 1)}
            disabled={idx === rows.length - 1}
            aria-label="Move down"
          >
            <ArrowDown className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onClear(idx)}
            aria-label="Clear slot"
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        </div>
      </td>
    </tr>
  );
}

function PlayerSelect({
  value,
  hitters,
  disabledIds,
  onChange,
}: {
  value: string;
  hitters: RosterPlayer[];
  disabledIds: Set<string>;
  onChange: (playerId: string) => void;
}) {
  // Keep the currently selected id available even if it's also in the
  // "selected elsewhere" set for its own row.
  const options = hitters.map((p) => ({
    id: p.player_id,
    label: `${p.last_name}, ${p.first_name} (${p.primary_position || "POS"})`,
    disabled: disabledIds.has(p.player_id) && p.player_id !== value,
  }));
  options.sort((a, b) => a.label.localeCompare(b.label));

  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "h-9 w-full appearance-none rounded-md border border-border bg-canvas/60 px-2 pr-7 text-sm text-ink",
          "focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40",
        )}
      >
        <option value="">— select —</option>
        {options.map((opt) => (
          <option key={opt.id} value={opt.id} disabled={opt.disabled}>
            {opt.label}
          </option>
        ))}
      </select>
      <ChevronsUpDown className="pointer-events-none absolute right-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted" />
    </div>
  );
}

function emptyLineup(): LineupRow[] {
  return Array.from({ length: 9 }, (_, i) => ({
    order: i + 1,
    player_id: "",
    position: "",
  }));
}

// ---------------------------------------------------------------------------

function PitchingTab({
  teamId,
  roster,
}: {
  teamId: string;
  roster: RosterPlayer[];
}) {
  const queryClient = useQueryClient();
  const staff = useQuery({
    queryKey: ["pitching-staff", teamId],
    queryFn: () => api.getPitchingStaff(teamId),
  });
  const [rows, setRows] = useState<PitchingStaffEntry[]>([]);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (staff.data) {
      setRows([...staff.data.staff]);
      setDirty(false);
    }
  }, [staff.data]);

  const save = useMutation({
    mutationFn: (payload: PitchingStaffEntry[]) =>
      api.savePitchingStaff(teamId, payload),
    onSuccess: (data) => {
      queryClient.setQueryData(["pitching-staff", teamId], data);
      setDirty(false);
    },
  });

  const autofill = useMutation({
    mutationFn: () => api.autofillPitchingStaff(teamId),
    onSuccess: (data) => {
      queryClient.setQueryData(["pitching-staff", teamId], data);
      setRows([...data.staff]);
      setDirty(false);
    },
  });

  const pitchers = useMemo(
    () => roster.filter((p) => p.is_pitcher),
    [roster],
  );
  const pitchersById = useMemo(() => {
    const m = new Map<string, RosterPlayer>();
    for (const p of pitchers) m.set(p.player_id, p);
    return m;
  }, [pitchers]);
  const assignedIds = new Set(rows.map((r) => r.player_id).filter(Boolean));

  function updateRow(idx: number, patch: Partial<PitchingStaffEntry>) {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
    setDirty(true);
  }

  function addRow() {
    const nextRole = STAFF_ROLES.find((r) => !rows.some((x) => x.role === r))
      ?? "MR";
    setRows((prev) => [...prev, { player_id: "", role: nextRole }]);
    setDirty(true);
  }

  function removeRow(idx: number) {
    setRows((prev) => prev.filter((_, i) => i !== idx));
    setDirty(true);
  }

  const invalid = rows.some((r) => !r.player_id || !r.role);
  const canSave = !invalid && dirty && !save.isPending;

  // Status mirror of PyQt's "Filled: X/Y | Duplicates: Z" label.
  const filledCount = rows.filter((r) => r.player_id && r.role).length;
  const duplicatePlayers = (() => {
    const seen = new Map<string, number>();
    for (const r of rows) {
      if (!r.player_id) continue;
      seen.set(r.player_id, (seen.get(r.player_id) ?? 0) + 1);
    }
    return Array.from(seen.values()).filter((n) => n > 1).length;
  })();

  useHotkey(
    "mod+s",
    () => {
      if (canSave) save.mutate(rows);
    },
    { enabled: canSave },
  );

  if (staff.isLoading) return <LoadingCard />;
  if (staff.isError) return <ErrorCard message={(staff.error as Error).message} />;

  return (
    <>
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Pitching staff</CardTitle>
          <CardDescription>
            Roles used by the sim: SP1–SP5 starters, LR/MR long/middle relief,
            SU setup, CL closer.
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          {dirty && <Badge tone="warning">Unsaved</Badge>}
          <Badge tone={duplicatePlayers > 0 ? "danger" : "amber"}>
            Filled {filledCount}/{STAFF_ROLES.length}
            {duplicatePlayers > 0 && ` · ${duplicatePlayers} dup`}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
              <th className="px-6 py-2 text-left font-semibold">Role</th>
              <th className="px-3 py-2 text-left font-semibold">Pitcher</th>
              <th className="px-6 py-2 text-right font-semibold"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr
                key={idx}
                className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
              >
                <td className="px-6 py-2">
                  <select
                    value={row.role}
                    onChange={(e) => updateRow(idx, { role: e.target.value })}
                    className="h-9 w-28 rounded-md border border-border bg-canvas/60 px-2 text-xs font-semibold uppercase tracking-wider text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
                  >
                    {STAFF_ROLES.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                    {!STAFF_ROLES.includes(row.role) && row.role && (
                      <option value={row.role}>{row.role}</option>
                    )}
                  </select>
                </td>
                <td className="px-3 py-2">
                  <select
                    value={row.player_id}
                    onChange={(e) =>
                      updateRow(idx, { player_id: e.target.value })
                    }
                    className="h-9 w-full rounded-md border border-border bg-canvas/60 px-2 text-sm text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
                  >
                    <option value="">— select pitcher —</option>
                    {pitchers.map((p) => {
                      const taken =
                        assignedIds.has(p.player_id) &&
                        p.player_id !== row.player_id;
                      return (
                        <option
                          key={p.player_id}
                          value={p.player_id}
                          disabled={taken}
                        >
                          {p.last_name}, {p.first_name}
                          {pitchersById.get(p.player_id)?.role
                            ? ` — ${pitchersById.get(p.player_id)?.role}`
                            : ""}
                        </option>
                      );
                    })}
                  </select>
                </td>
                <td className="px-6 py-2 text-right">
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => removeRow(idx)}
                    aria-label="Remove"
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {save.isError && (
          <div className="m-4 flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="whitespace-pre-line">
              {(save.error as Error).message}
            </div>
          </div>
        )}
        {autofill.isError && (
          <div className="m-4 flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="whitespace-pre-line">
              {(autofill.error as Error).message}
            </div>
          </div>
        )}

        <div className="flex items-center justify-between gap-3 border-t border-border/60 bg-surfaceAlt/40 px-6 py-3">
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={addRow}>
              Add role
            </Button>
            <Button
              variant="outline"
              onClick={() => autofill.mutate()}
              disabled={autofill.isPending}
              title="Auto-assign SP1–SP5 + LR/MR/SU/CL from the active roster"
            >
              {autofill.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : null}
              Auto-fill
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setRows([]);
                setDirty(true);
              }}
              disabled={rows.length === 0}
            >
              Clear
            </Button>
          </div>
          <Button onClick={() => save.mutate(rows)} disabled={!canSave}>
            {save.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Save staff
          </Button>
        </div>
      </CardContent>
    </Card>
    <EligiblePoolPanel players={pitchers} kind="pitchers" />
    </>
  );
}

// ---------------------------------------------------------------------------
// Eligible-pool comparison panel
//
// Renders a sortable table of every active-roster player eligible for the
// editor above (hitters for the lineup tabs, pitchers for the staff tab)
// so the user can compare ratings side-by-side before placing someone in
// a slot. Read-only — assignment still happens through the dropdowns in
// the editor card.

const HITTER_POOL_COLUMNS: Array<{ key: string; label: string }> = [
  { key: "ch", label: "CH" },
  { key: "ph", label: "PH" },
  { key: "sp", label: "SP" },
  { key: "eye", label: "EYE" },
  { key: "fa", label: "FA" },
  { key: "arm", label: "ARM" },
];
const PITCHER_POOL_COLUMNS: Array<{ key: string; label: string }> = [
  { key: "arm", label: "AS" },
  { key: "endurance", label: "EN" },
  { key: "control", label: "CTRL" },
  { key: "movement", label: "MOV" },
  { key: "fb", label: "FB" },
  { key: "sl", label: "SL" },
  { key: "cu", label: "CU" },
  { key: "cb", label: "CB" },
  { key: "si", label: "SI" },
];

function EligiblePoolPanel({
  players,
  kind,
}: {
  players: RosterPlayer[];
  kind: "hitters" | "pitchers";
}) {
  const columns = kind === "hitters" ? HITTER_POOL_COLUMNS : PITCHER_POOL_COLUMNS;
  const [sortKey, setSortKey] = usePersistedState<string>(
    `lineup:eligible:${kind}:sortKey`,
    "overall",
  );
  const [sortDir, setSortDir] = usePersistedState<"asc" | "desc">(
    `lineup:eligible:${kind}:sortDir`,
    "desc",
  );

  const sorted = useMemo(() => {
    const arr = [...players];
    arr.sort((a, b) => {
      const av = poolSortValue(a, sortKey);
      const bv = poolSortValue(b, sortKey);
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

  function toggleSort(key: string) {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "name" ? "asc" : "desc");
    }
  }

  if (players.length === 0) return null;

  return (
    <Card className="mt-4">
      <CardHeader>
        <div>
          <CardTitle className="text-base">
            {kind === "hitters" ? "Eligible hitters" : "Eligible pitchers"}
          </CardTitle>
          <CardDescription>
            Active-roster {kind} with their ratings — read-only reference for
            comparing options before placing them above.
          </CardDescription>
        </div>
        <Badge tone="neutral">{players.length}</Badge>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
                <PoolHeader
                  label="Player"
                  keyId="name"
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onClick={toggleSort}
                  align="left"
                />
                <PoolHeader
                  label={kind === "hitters" ? "Pos" : "Role"}
                  keyId={kind === "hitters" ? "pos" : "role"}
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onClick={toggleSort}
                />
                <PoolHeader
                  label="Age"
                  keyId="age"
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onClick={toggleSort}
                />
                <PoolHeader
                  label="B/T"
                  keyId="bats"
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onClick={toggleSort}
                />
                <PoolHeader
                  label="OVR"
                  keyId="overall"
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onClick={toggleSort}
                />
                {columns.map((col) => (
                  <PoolHeader
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
                  className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
                >
                  <td className="px-6 py-2 font-semibold">
                    {p.last_name}
                    {p.first_name ? `, ${p.first_name}` : ""}
                  </td>
                  <td className="px-3 py-2 text-right text-xs uppercase tracking-wider text-muted">
                    {kind === "hitters"
                      ? (p.primary_position || "—")
                      : (p.role || "—")}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {p.age ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-right text-xs">
                    {p.bats || "—"}/{p.throws || "—"}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums font-semibold">
                    {p.overall_display ?? p.overall_raw ?? "—"}
                  </td>
                  {columns.map((col) => {
                    const raw = p.ratings[col.key];
                    const display =
                      raw == null || raw === ""
                        ? "—"
                        : typeof raw === "number"
                          ? Math.round(raw)
                          : Number.isFinite(Number(raw))
                            ? Math.round(Number(raw))
                            : String(raw);
                    return (
                      <td
                        key={col.key}
                        className="px-3 py-2 text-right tabular-nums"
                      >
                        {display}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function poolSortValue(p: RosterPlayer, key: string): string | number | null {
  switch (key) {
    case "name":
      return `${p.last_name}, ${p.first_name}`;
    case "age":
      return p.age ?? null;
    case "pos":
      return p.primary_position ?? "";
    case "role":
      return p.role ?? "";
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

function PoolHeader({
  label,
  keyId,
  sortKey,
  sortDir,
  onClick,
  align = "right",
}: {
  label: string;
  keyId: string;
  sortKey: string;
  sortDir: "asc" | "desc";
  onClick: (key: string) => void;
  align?: "left" | "right";
}) {
  const active = sortKey === keyId;
  const Arrow = !active ? ChevronsUpDown : sortDir === "asc" ? ArrowUp : ArrowDown;
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

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading…</span>
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
