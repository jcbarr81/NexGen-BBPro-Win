import { ReactNode, useId, useState } from "react";
import { Info } from "lucide-react";

import { cn } from "@/lib/cn";

/**
 * Inline glossary tooltip for finance/roster jargon.
 *
 * Two modes:
 * - `<InfoTip tip="…" />` — a small ⓘ icon (for card titles / stat labels).
 * - `<InfoTip tip="…">Arb-eligible</InfoTip>` — wraps the term with a dotted
 *   underline so users learn "dotted = hover me".
 *
 * Hover or keyboard focus shows the tip; Escape/blur hides it. Pure CSS
 * positioning (no portal), so keep tips off overflow-hidden edges.
 */
export function InfoTip({
  tip,
  children,
  className,
  side = "top",
}: {
  tip: ReactNode;
  children?: ReactNode;
  className?: string;
  side?: "top" | "bottom";
}) {
  const [open, setOpen] = useState(false);
  const id = useId();

  return (
    <span
      className={cn("relative inline-flex items-center", className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
    >
      {children ? (
        <span
          tabIndex={0}
          aria-describedby={open ? id : undefined}
          className="cursor-help underline decoration-dotted decoration-muted underline-offset-2 outline-none focus-visible:decoration-amber"
        >
          {children}
        </span>
      ) : (
        <button
          type="button"
          tabIndex={0}
          aria-label="More info"
          aria-describedby={open ? id : undefined}
          className="cursor-help text-muted outline-none hover:text-ink focus-visible:text-amber"
        >
          <Info className="h-3.5 w-3.5" />
        </button>
      )}
      {open && (
        <span
          id={id}
          role="tooltip"
          className={cn(
            "absolute left-1/2 z-50 w-max max-w-[260px] -translate-x-1/2 rounded-md border border-border bg-elevated px-2.5 py-1.5 text-left text-xs font-normal normal-case leading-snug tracking-normal text-ink shadow-lg",
            side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5",
          )}
        >
          {tip}
        </span>
      )}
    </span>
  );
}
