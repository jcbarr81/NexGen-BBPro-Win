/**
 * Drag-and-drop reorderable card container.
 *
 * Pages pass their cards as an ordered ``items`` list (stable ids); when the
 * global "Edit layout" mode is on, each card grows a drag handle and can be
 * reordered. The chosen order persists per-user in localStorage
 * (``use-card-layout`` + ``layout-store``). When edit mode is off, no
 * DndContext is mounted at all — cards render as plain children with zero drag
 * overhead and normal click/link behavior.
 *
 * Two shapes share one component via ``variant``:
 *   - "vertical" — full-width section blocks reordered top-to-bottom.
 *   - "grid" — a uniform responsive grid of equal cards reflowed in 2D.
 * The container uses the page's own ``className`` (its existing grid/stack
 * classes) so layouts are unchanged; sortable items are its direct children.
 */

import type { ReactNode } from "react";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  rectSortingStrategy,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, RotateCcw } from "lucide-react";

import { cn } from "@/lib/cn";
import { useCardLayout } from "@/lib/use-card-layout";
import { Button } from "@/components/ui";

export interface CardItem {
  /** Stable, content-based id (NOT array index). Unique within the page. */
  id: string;
  node: ReactNode;
  /** Friendly name for the drag handle's aria-label. */
  label?: string;
}

interface Props {
  pageKey: string;
  items: CardItem[];
  variant?: "vertical" | "grid";
  /** The page's existing container classes (grid/stack). */
  className?: string;
  /** Global edit-mode flag. */
  editing: boolean;
}

export function ReorderableCards({
  pageKey,
  items,
  variant = "vertical",
  className,
  editing,
}: Props) {
  const ids = items.map((i) => i.id);
  const { orderedIds, setOrder, reset, isCustomized } = useCardLayout(
    pageKey,
    ids,
  );
  const byId = new Map(items.map((i) => [i.id, i]));
  const ordered = orderedIds.map((id) => byId.get(id)).filter(Boolean) as CardItem[];

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  // Read-only path: no DndContext, plain children. Normal clicks/links work.
  if (!editing) {
    return (
      <div className={className}>
        {ordered.map((item) => (
          <div key={item.id}>{item.node}</div>
        ))}
      </div>
    );
  }

  function handleDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const from = orderedIds.indexOf(String(active.id));
    const to = orderedIds.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    setOrder(arrayMove(orderedIds, from, to));
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between rounded-md border border-amber/40 bg-amber/10 px-3 py-2 text-xs">
        <span className="font-semibold uppercase tracking-wider text-amber-text">
          Editing layout — drag the handles to reorder
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={reset}
          disabled={!isCustomized}
          title="Restore this page's default card order"
        >
          <RotateCcw className="mr-1 h-3.5 w-3.5" /> Reset this page
        </Button>
      </div>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={orderedIds}
          strategy={
            variant === "grid"
              ? rectSortingStrategy
              : verticalListSortingStrategy
          }
        >
          <div className={className}>
            {ordered.map((item) => (
              <SortableCardShell
                key={item.id}
                id={item.id}
                label={item.label ?? item.id}
              >
                {item.node}
              </SortableCardShell>
            ))}
          </div>
        </SortableContext>
      </DndContext>
    </div>
  );
}

function SortableCardShell({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: ReactNode;
}) {
  const { setNodeRef, transform, transition, attributes, listeners, isDragging } =
    useSortable({ id });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
  };
  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "relative rounded-xl ring-1 ring-amber/40",
        isDragging && "z-10 opacity-80 shadow-panel",
      )}
    >
      <button
        type="button"
        aria-label={`Reorder ${label}`}
        title="Drag to reorder"
        className="absolute right-2 top-2 z-20 cursor-grab touch-none rounded-md border border-amber/40 bg-surface/90 p-1 text-amber-text shadow-sm hover:bg-surfaceAlt"
        {...attributes}
        {...listeners}
      >
        <GripVertical className="h-4 w-4" />
      </button>
      {children}
    </div>
  );
}
