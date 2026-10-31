/**
 * The owner's draft board (8.7.0): a ranked list of prospects plus a few
 * plain rules, used whenever a pick is made for the club — its pick clock
 * ran out, auto-draft is on, or the commissioner finished the draft. The
 * server (services/draft_board.py) makes the choice; this page edits the
 * board and shows what it would take right now, and why.
 *
 * Boards are private to the club's owner: the API refuses everyone else,
 * the commissioner included.
 */

import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
import {
  AlertTriangle,
  Bot,
  GripVertical,
  ListOrdered,
  Loader2,
  Plus,
  Save,
  Star,
  Trash2,
  X,
} from "lucide-react";

import {
  api,
  type DraftBoardAutodraft,
  type DraftBoardEntry,
  type DraftBoardNeed,
  type DraftBoardRow,
  type DraftBoardSettings,
  type DraftBoardView,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
} from "@/components/ui";

const SELECT_CLASS =
  "h-8 rounded-md border border-border bg-canvas/60 px-2 text-xs font-semibold text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40";

const AUTODRAFT_CHOICES: Array<{
  id: DraftBoardAutodraft;
  label: string;
  help: string;
}> = [
  {
    id: "off",
    label: "Only if my clock runs out",
    help: "You make your own picks. The board is used only if your pick clock runs out (or the commissioner finishes the draft).",
  },
  {
    id: "board",
    label: "Pick from my board when I'm up",
    help: "The moment you're on the clock, the board takes a player from your list. If nobody on your list can be taken, the clock runs as usual and you pick.",
  },
  {
    id: "all",
    label: "Auto-draft everything",
    help: "The board makes every remaining pick the moment you're up, including the fallback when your list runs dry. For when you'll be away.",
  },
];

const WHY_LABEL: Record<string, string> = {
  clock: "Clock ran out",
  autodraft: "Auto-draft",
  commissioner: "Commissioner",
  owner: "Auto-pick",
};

export function draftBoardKey(teamId: string | null, year: number | null) {
  return ["draft-board", teamId, year] as const;
}

/** The board as the API takes it back: settings + bare entries. */
export function boardPayload(
  settings: DraftBoardSettings,
  entries: DraftBoardEntry[],
): DraftBoardSettings & { entries: DraftBoardEntry[] } {
  return {
    use_tiers: settings.use_tiers,
    position_limits: settings.position_limits,
    needs: settings.needs,
    fallback: settings.fallback,
    autodraft: settings.autodraft,
    entries: entries.map((e) => ({
      player_id: e.player_id,
      note: e.note,
      not_before_round: e.not_before_round,
      group: e.group,
      tier: e.tier,
    })),
  };
}

/** Star/unstar a prospect from the draft-class table. */
export function useDraftBoardToggle(teamId: string | null, year: number | null) {
  const queryClient = useQueryClient();
  const boardQ = useQuery({
    queryKey: draftBoardKey(teamId, year),
    queryFn: () => api.draftBoard(teamId!, year ?? undefined),
    enabled: !!teamId && !!year,
    retry: false,
  });
  const onBoard = useMemo(
    () => new Set((boardQ.data?.entries ?? []).map((e) => e.player_id)),
    [boardQ.data],
  );
  const toggle = useMutation({
    mutationFn: (playerId: string) => {
      const view = boardQ.data!;
      const entries: DraftBoardEntry[] = onBoard.has(playerId)
        ? view.entries.filter((e) => e.player_id !== playerId)
        : [
            ...view.entries,
            {
              player_id: playerId,
              note: "",
              not_before_round: null,
              group: null,
              tier: view.entries[view.entries.length - 1]?.tier ?? 1,
            },
          ];
      return api.saveDraftBoard(teamId!, year!, boardPayload(view.board, entries));
    },
    onSuccess: (view) => queryClient.setQueryData(draftBoardKey(teamId, year), view),
  });
  return {
    available: !!boardQ.data && !boardQ.data.draft.complete,
    onBoard,
    toggle,
  };
}

export function DraftBoardTab({ teamId, year }: { teamId: string; year: number }) {
  const queryClient = useQueryClient();
  const boardQ = useQuery({
    queryKey: draftBoardKey(teamId, year),
    queryFn: () => api.draftBoard(teamId, year),
    retry: false,
  });
  const [settings, setSettings] = useState<DraftBoardSettings | null>(null);
  const [entries, setEntries] = useState<DraftBoardEntry[]>([]);
  const [dirty, setDirty] = useState(false);

  // Take the server's board whenever there are no unsaved edits, so a star
  // added from the draft class (or a pick made meanwhile) shows up here.
  useEffect(() => {
    if (!boardQ.data || dirty) return;
    setSettings(boardQ.data.board);
    setEntries(boardQ.data.entries.map(stripRow));
  }, [boardQ.data, dirty]);

  const saveMut = useMutation({
    mutationFn: () => api.saveDraftBoard(teamId, year, boardPayload(settings!, entries)),
    onSuccess: (view) => {
      queryClient.setQueryData(draftBoardKey(teamId, year), view);
      setDirty(false);
    },
  });

  function editSettings(patch: Partial<DraftBoardSettings>) {
    setSettings((prev) => (prev ? { ...prev, ...patch } : prev));
    setDirty(true);
  }
  function editEntries(next: DraftBoardEntry[]) {
    setEntries(next);
    setDirty(true);
  }
  function discard() {
    setDirty(false);
    if (boardQ.data) {
      setSettings(boardQ.data.board);
      setEntries(boardQ.data.entries.map(stripRow));
    }
  }

  if (boardQ.isLoading || (!settings && !boardQ.isError)) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-10">
          <Loader2 className="h-5 w-5 animate-spin text-amber" />
          <span className="text-sm text-muted">Loading your draft board…</span>
        </CardContent>
      </Card>
    );
  }
  if (boardQ.isError || !boardQ.data || !settings) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-10 text-danger">
          <AlertTriangle className="h-5 w-5" />
          <span className="text-sm">{(boardQ.error as Error)?.message ?? "No board."}</span>
        </CardContent>
      </Card>
    );
  }

  const view = boardQ.data;
  const rowsById = new Map(view.entries.map((r) => [r.player_id, r]));
  const locked = view.draft.complete;

  return (
    <div className="space-y-6">
      <PreviewCard view={view} dirty={dirty} />

      {dirty && (
        <div className="sticky top-2 z-20 flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber/40 bg-amber/10 px-4 py-2 text-sm">
          <span>You have unsaved changes to your board.</span>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" onClick={discard} disabled={saveMut.isPending}>
              Discard
            </Button>
            <Button size="sm" onClick={() => saveMut.mutate()} disabled={saveMut.isPending}>
              {saveMut.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              Save board
            </Button>
          </div>
        </div>
      )}
      {saveMut.error && (
        <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {(saveMut.error as Error).message}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <Bot className="h-4 w-4 text-amber" /> When the board picks
              </CardTitle>
              <CardDescription>
                Your board is private: only you can see it.
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              {AUTODRAFT_CHOICES.map((choice) => (
                <label
                  key={choice.id}
                  className={cn(
                    "flex cursor-pointer gap-3 rounded-md border px-3 py-2 text-sm",
                    settings.autodraft === choice.id
                      ? "border-amber/60 bg-amber/10"
                      : "border-border hover:bg-surfaceAlt/40",
                  )}
                >
                  <input
                    type="radio"
                    name="draft-board-autodraft"
                    className="mt-1 h-3 w-3 accent-amber"
                    checked={settings.autodraft === choice.id}
                    disabled={locked}
                    onChange={() => editSettings({ autodraft: choice.id })}
                  />
                  <span>
                    <span className="font-semibold">{choice.label}</span>
                    <span className="block text-xs text-muted">{choice.help}</span>
                  </span>
                </label>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-muted">When nobody on my list can be taken, take</span>
              <select
                className={SELECT_CLASS}
                value={settings.fallback}
                disabled={locked}
                onChange={(e) => editSettings({ fallback: e.target.value })}
              >
                {view.options.fallbacks.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.label}
                  </option>
                ))}
              </select>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-3 w-3 accent-amber"
                checked={settings.use_tiers}
                disabled={locked}
                onChange={(e) => editSettings({ use_tiers: e.target.checked })}
              />
              <span>
                Use tiers{" "}
                <span className="text-xs text-muted">
                  — players in a tier count as equal: the board takes the one
                  who fills a need, then the best overall.
                </span>
              </span>
            </label>
          </CardContent>
        </Card>

        <NeedsAndLimitsCard
          settings={settings}
          view={view}
          locked={locked}
          onChange={editSettings}
        />
      </div>

      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <ListOrdered className="h-4 w-4 text-amber" /> Your board
            </CardTitle>
            <CardDescription>
              Drag to rank. Add players with the{" "}
              <Star className="inline h-3 w-3" /> in the draft class list on
              the Now tab. Players other clubs take stay here, greyed out.
            </CardDescription>
          </div>
          <Badge tone="neutral">{entries.length} players</Badge>
        </CardHeader>
        <CardContent className="p-0">
          {entries.length === 0 ? (
            <div className="px-6 py-8 text-sm text-muted">
              Your board is empty. Until you add players, a pick made for you
              takes {fallbackLabel(view, settings.fallback)}.
            </div>
          ) : (
            <BoardTable
              entries={entries}
              rowsById={rowsById}
              settings={settings}
              groups={view.options.groups}
              rounds={view.draft.rounds}
              locked={locked}
              onChange={editEntries}
            />
          )}
        </CardContent>
      </Card>

      {view.made.length > 0 && (
        <Card>
          <CardHeader>
            <div>
              <CardTitle className="text-base">Picks your board made</CardTitle>
              <CardDescription>And why it made them.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y divide-border/60">
              {[...view.made].reverse().map((m) => (
                <li key={`${m.overall}-${m.player_id}`} className="space-y-1 px-6 py-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs text-muted">
                      Rd {m.round} · #{m.overall}
                    </span>
                    <Link
                      to={`/player/${encodeURIComponent(m.player_id)}`}
                      className="font-semibold hover:text-amber"
                    >
                      {m.name}
                    </Link>
                    <Badge tone="neutral">{WHY_LABEL[m.why] ?? m.why}</Badge>
                  </div>
                  <p className="text-xs text-muted">{m.reason}</p>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function stripRow(row: DraftBoardRow): DraftBoardEntry {
  return {
    player_id: row.player_id,
    note: row.note ?? "",
    not_before_round: row.not_before_round ?? null,
    group: row.group ?? null,
    tier: row.tier ?? 1,
  };
}

function fallbackLabel(view: DraftBoardView, id: string) {
  return view.options.fallbacks.find((f) => f.id === id)?.label ?? "the best player available";
}

function PreviewCard({ view, dirty }: { view: DraftBoardView; dirty: boolean }) {
  let heading: string;
  if (view.draft.complete) heading = `The ${view.year} draft is over.`;
  else if (!view.preview) heading = "You have no picks left in this draft.";
  else {
    const when = view.draft.on_clock
      ? "You're on the clock"
      : view.next_pick
        ? `Your next pick is round ${view.next_pick.round}, #${view.next_pick.overall}`
        : "At your first pick";
    heading = `${when}: if your board picked now, it would take`;
  }
  return (
    <Card className="border-amber/40">
      <CardContent className="space-y-1 py-4">
        <p className="text-sm">
          {heading}{" "}
          {view.preview && !view.draft.complete && (
            <>
              <span className="font-semibold text-amber-text">{view.preview.name}</span>
              {view.preview.source === "fallback" && (
                <span className="text-muted"> (not on your board)</span>
              )}
              .
            </>
          )}
        </p>
        {view.preview && !view.draft.complete && (
          <p className="text-xs text-muted">
            {view.preview.reason} This changes as other clubs pick.
            {dirty && " Save your board to update it."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function NeedsAndLimitsCard({
  settings,
  view,
  locked,
  onChange,
}: {
  settings: DraftBoardSettings;
  view: DraftBoardView;
  locked: boolean;
  onChange: (patch: Partial<DraftBoardSettings>) => void;
}) {
  const positions = view.options.positions;
  function setLimit(pos: string, raw: string) {
    const next = { ...settings.position_limits };
    const n = parseInt(raw, 10);
    if (raw.trim() === "" || Number.isNaN(n)) delete next[pos];
    else next[pos] = Math.max(0, Math.min(99, n));
    onChange({ position_limits: next });
  }
  function setNeed(idx: number, patch: Partial<DraftBoardNeed>) {
    onChange({
      needs: settings.needs.map((n, i) => (i === idx ? { ...n, ...patch } : n)),
    });
  }
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="text-base">Needs & limits</CardTitle>
          <CardDescription>
            Count every pick you make this draft, by you or by the board. IF is
            1B/2B/3B/SS, OF is LF/CF/RF.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="space-y-2">
          <div className="text-xs font-semibold uppercase tracking-wider text-muted">
            At most (blank = no limit)
          </div>
          <div className="grid grid-cols-4 gap-2 sm:grid-cols-6">
            {positions.map((pos) => (
              <label key={pos} className="flex items-center gap-1 text-xs">
                <span className="w-6 font-semibold">{pos}</span>
                <Input
                  className="h-8 w-14 px-2 text-xs"
                  inputMode="numeric"
                  value={settings.position_limits[pos] ?? ""}
                  disabled={locked}
                  onChange={(e) => setLimit(pos, e.target.value)}
                  title={`Drafted so far: ${view.drafted_counts[pos] ?? 0}`}
                />
              </label>
            ))}
          </div>
        </div>
        <div className="space-y-2">
          <div className="text-xs font-semibold uppercase tracking-wider text-muted">
            Needs
          </div>
          {settings.needs.length === 0 && (
            <p className="text-xs text-muted">
              None. A need such as “at least 1 SS by round 4” makes the pick a
              shortstop from round 4 on until you have one.
            </p>
          )}
          {settings.needs.map((need, idx) => {
            const have = view.drafted_counts[need.position] ?? 0;
            return (
              <div key={idx} className="flex flex-wrap items-center gap-2 text-xs">
                <span>At least</span>
                <Input
                  className="h-8 w-12 px-2 text-xs"
                  inputMode="numeric"
                  value={need.count}
                  disabled={locked}
                  onChange={(e) =>
                    setNeed(idx, { count: Math.max(1, parseInt(e.target.value, 10) || 1) })
                  }
                />
                <select
                  className={SELECT_CLASS}
                  value={need.position}
                  disabled={locked}
                  onChange={(e) => setNeed(idx, { position: e.target.value })}
                >
                  {positions.map((pos) => (
                    <option key={pos} value={pos}>
                      {pos}
                    </option>
                  ))}
                </select>
                <span>by round</span>
                <select
                  className={SELECT_CLASS}
                  value={need.by_round}
                  disabled={locked}
                  onChange={(e) => setNeed(idx, { by_round: parseInt(e.target.value, 10) })}
                >
                  {roundOptions(view.draft.rounds).map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
                <Badge tone={have >= need.count ? "success" : "neutral"}>
                  {have >= need.count ? "met" : `have ${have}`}
                </Badge>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  disabled={locked}
                  onClick={() => onChange({ needs: settings.needs.filter((_, i) => i !== idx) })}
                  aria-label="Remove need"
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
            );
          })}
          <Button
            size="sm"
            variant="outline"
            disabled={locked || settings.needs.length >= 12}
            onClick={() =>
              onChange({ needs: [...settings.needs, { position: "SS", count: 1, by_round: 3 }] })
            }
          >
            <Plus className="h-4 w-4" /> Add a need
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function roundOptions(rounds: number) {
  return Array.from({ length: Math.max(1, rounds) }, (_, i) => i + 1);
}

function BoardTable({
  entries,
  rowsById,
  settings,
  groups,
  rounds,
  locked,
  onChange,
}: {
  entries: DraftBoardEntry[];
  rowsById: Map<string, DraftBoardRow>;
  settings: DraftBoardSettings;
  groups: string[];
  rounds: number;
  locked: boolean;
  onChange: (next: DraftBoardEntry[]) => void;
}) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  const ids = entries.map((e) => e.player_id);

  function handleDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    const moved = arrayMove(entries, from, to);
    // A moved player joins the tier he lands in.
    const above = moved[to - 1];
    const below = moved[to + 1];
    moved[to] = { ...moved[to]!, tier: above?.tier ?? below?.tier ?? 1 };
    onChange(monotonicTiers(moved));
  }
  function update(idx: number, patch: Partial<DraftBoardEntry>) {
    onChange(entries.map((e, i) => (i === idx ? { ...e, ...patch } : e)));
  }
  function newTierFrom(idx: number) {
    onChange(entries.map((e, i) => (i >= idx ? { ...e, tier: e.tier + 1 } : e)));
  }
  function mergeTierAt(idx: number) {
    onChange(entries.map((e, i) => (i >= idx ? { ...e, tier: Math.max(1, e.tier - 1) } : e)));
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
                <th className="w-8 px-2 py-2"></th>
                <th className="px-2 py-2 text-left font-semibold">#</th>
                <th className="px-3 py-2 text-left font-semibold">Player</th>
                <th className="px-2 py-2 text-right font-semibold">Pos</th>
                <th className="px-2 py-2 text-right font-semibold">Age</th>
                <th className="px-2 py-2 text-right font-semibold">OVR</th>
                <th className="px-3 py-2 text-left font-semibold" title="Of a group, only one player is taken">
                  Group
                </th>
                <th className="px-3 py-2 text-left font-semibold" title="Don't take him before this round">
                  Not before
                </th>
                <th className="px-3 py-2 text-left font-semibold">Note</th>
                <th className="px-2 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry, idx) => {
                const startsTier =
                  settings.use_tiers && (idx === 0 || entries[idx - 1]!.tier !== entry.tier);
                return (
                  <SortableBoardRow
                    key={entry.player_id}
                    entry={entry}
                    idx={idx}
                    row={rowsById.get(entry.player_id)}
                    tierHeader={startsTier ? entry.tier : null}
                    useTiers={settings.use_tiers}
                    groups={groups}
                    rounds={rounds}
                    locked={locked}
                    onUpdate={(patch) => update(idx, patch)}
                    onRemove={() => onChange(entries.filter((_, i) => i !== idx))}
                    onNewTier={() => newTierFrom(idx)}
                    onMergeTier={idx > 0 ? () => mergeTierAt(idx) : undefined}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      </SortableContext>
    </DndContext>
  );
}

/** Tiers only go up the list (the server reads them the same way). */
function monotonicTiers(entries: DraftBoardEntry[]): DraftBoardEntry[] {
  let tier = 1;
  return entries.map((e) => {
    tier = Math.max(tier, e.tier || 1);
    return e.tier === tier ? e : { ...e, tier };
  });
}

function SortableBoardRow({
  entry,
  idx,
  row,
  tierHeader,
  useTiers,
  groups,
  rounds,
  locked,
  onUpdate,
  onRemove,
  onNewTier,
  onMergeTier,
}: {
  entry: DraftBoardEntry;
  idx: number;
  row: DraftBoardRow | undefined;
  tierHeader: number | null;
  useTiers: boolean;
  groups: string[];
  rounds: number;
  locked: boolean;
  onUpdate: (patch: Partial<DraftBoardEntry>) => void;
  onRemove: () => void;
  onNewTier: () => void;
  onMergeTier?: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: entry.player_id,
    disabled: locked,
  });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  };
  const p = row?.prospect ?? null;
  const taken = row?.taken ?? null;
  return (
    <>
      {tierHeader != null && (
        <tr className="bg-surfaceAlt/60">
          <td colSpan={10} className="px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
            <div className="flex items-center justify-between">
              <span>Tier {tierHeader}</span>
              {onMergeTier && !locked && (
                <button
                  type="button"
                  className="normal-case tracking-normal text-muted hover:text-ink"
                  onClick={onMergeTier}
                >
                  Merge with the tier above
                </button>
              )}
            </div>
          </td>
        </tr>
      )}
      <tr
        ref={setNodeRef}
        style={style}
        className={cn(
          "border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40",
          taken && "opacity-50",
        )}
      >
        <td className="px-2 py-2">
          <button
            type="button"
            className="cursor-grab touch-none rounded-sm p-1 text-muted hover:bg-surfaceAlt hover:text-ink disabled:cursor-not-allowed"
            aria-label="Drag to reorder"
            disabled={locked}
            {...attributes}
            {...listeners}
          >
            <GripVertical className="h-3 w-3" />
          </button>
        </td>
        <td className="px-2 py-2 font-mono text-xs text-muted">{idx + 1}</td>
        <td className="px-3 py-2">
          <div className="flex flex-wrap items-center gap-2">
            {/* A prospect has no player page until he is drafted. */}
            {taken ? (
              <Link
                to={`/player/${encodeURIComponent(entry.player_id)}`}
                className="font-semibold line-through hover:text-amber"
              >
                {p ? `${p.last_name}, ${p.first_name}` : entry.player_id}
              </Link>
            ) : (
              <span className="font-semibold">
                {p ? `${p.last_name}, ${p.first_name}` : entry.player_id}
              </span>
            )}
            {taken && (
              <Badge tone="neutral">
                Taken by {taken.team_id}, #{taken.overall}
              </Badge>
            )}
            {useTiers && !locked && idx > 0 && tierHeader == null && (
              <button
                type="button"
                className="text-[11px] text-muted hover:text-ink"
                onClick={onNewTier}
                title="Start a new tier with this player"
              >
                new tier here
              </button>
            )}
          </div>
        </td>
        <td className="px-2 py-2 text-right text-xs uppercase tracking-wider text-muted">
          {p?.primary_position || "—"}
        </td>
        <td className="px-2 py-2 text-right tabular-nums">{p?.age ?? "—"}</td>
        <td className="px-2 py-2 text-right font-semibold tabular-nums">{p?.overall ?? "—"}</td>
        <td className="px-3 py-2">
          <select
            className={SELECT_CLASS}
            value={entry.group ?? ""}
            disabled={locked}
            onChange={(e) => onUpdate({ group: e.target.value || null })}
            aria-label="Group"
          >
            <option value="">—</option>
            {groups.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        </td>
        <td className="px-3 py-2">
          <select
            className={SELECT_CLASS}
            value={entry.not_before_round ?? ""}
            disabled={locked}
            onChange={(e) =>
              onUpdate({ not_before_round: e.target.value ? parseInt(e.target.value, 10) : null })
            }
            aria-label="Not before round"
          >
            <option value="">any round</option>
            {roundOptions(rounds)
              .filter((r) => r > 1)
              .map((r) => (
                <option key={r} value={r}>
                  round {r}
                </option>
              ))}
          </select>
        </td>
        <td className="px-3 py-2">
          <Input
            className="h-8 min-w-[140px] px-2 text-xs"
            value={entry.note}
            maxLength={200}
            disabled={locked}
            placeholder="Private note"
            onChange={(e) => onUpdate({ note: e.target.value })}
          />
        </td>
        <td className="px-2 py-2 text-right">
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            onClick={onRemove}
            disabled={locked}
            aria-label="Remove from board"
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        </td>
      </tr>
    </>
  );
}
