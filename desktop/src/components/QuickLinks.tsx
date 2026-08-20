/**
 * A compact "likely next destinations" strip. Drop it near the bottom of a page
 * so the owner can jump straight to the pages they usually visit next (e.g. from
 * the Roster → Lineups / Pitching Staff / Depth Chart) without hunting through
 * the sidebar. Reusable: pass whatever links fit the current page's workflow.
 */

import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";

import { cn } from "@/lib/cn";

export interface QuickLink {
  label: string;
  to: string;
}

export function QuickLinks({
  title = "Next up",
  links,
  className,
}: {
  title?: string;
  links: QuickLink[];
  className?: string;
}) {
  if (!links.length) return null;
  return (
    <div className={cn("mt-6 flex flex-wrap items-center gap-2", className)}>
      <span className="text-[11px] uppercase tracking-wider text-muted">
        {title}
      </span>
      {links.map((l) => (
        <Link
          key={`${l.to}:${l.label}`}
          to={l.to}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surfaceAlt/50 px-3 py-1.5 text-xs font-semibold text-muted transition hover:border-amber/60 hover:text-ink"
        >
          {l.label}
          <ArrowRight className="h-3 w-3" />
        </Link>
      ))}
    </div>
  );
}
