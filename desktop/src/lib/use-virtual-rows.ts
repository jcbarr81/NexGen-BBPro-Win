/**
 * Thin wrapper around @tanstack/react-virtual for our big data tables.
 *
 * Uses the "padding row" technique so existing <table>/<tbody> (or <ul>)
 * markup keeps its styling: render one spacer row above and one below the
 * virtual window sized to the off-screen content, then only mount the
 * visible slice. The caller owns the scroll container (fixed max-height,
 * overflow-auto) and passes `scrollRef` to it.
 *
 * Rows self-measure via `measureRow` (attach as ref together with a
 * `data-index={item.index}` attribute) so variable-height rows stay
 * accurate; `estimateRowHeight` just seeds the initial layout.
 */

import { useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";

export function useVirtualRows({
  count,
  estimateRowHeight,
  overscan = 12,
}: {
  count: number;
  estimateRowHeight: number;
  overscan?: number;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const virtualizer = useVirtualizer<HTMLDivElement, Element>({
    count,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => estimateRowHeight,
    overscan,
  });

  const items = virtualizer.getVirtualItems();
  const first = items[0];
  const last = items[items.length - 1];
  const paddingTop = first ? first.start : 0;
  const paddingBottom = last ? virtualizer.getTotalSize() - last.end : 0;

  return {
    scrollRef,
    items,
    paddingTop,
    paddingBottom,
    measureRow: virtualizer.measureElement,
  };
}
