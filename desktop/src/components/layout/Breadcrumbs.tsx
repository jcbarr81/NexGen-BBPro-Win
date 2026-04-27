/**
 * Breadcrumb trail derived from the current pathname + the central
 * ``ROUTE_INDEX`` lookup. Typical trail:
 *
 *     Home / My Team / Roster
 *
 * The leaf (current page) is non-clickable. Earlier segments are links.
 * If the current path isn't in the index (e.g. /player/:id details page),
 * we still render Home + the leaf as a single-segment trail so the
 * AppShell title bar stays consistent.
 */

import { Link, useLocation, useMatch } from "react-router-dom";
import { ChevronRight } from "lucide-react";

import { findRouteMeta, HUB_META } from "@/lib/route-index";
import { cn } from "@/lib/cn";

interface Crumb {
  label: string;
  to?: string;
}

export function Breadcrumbs({ leafLabel }: { leafLabel?: string }) {
  const location = useLocation();
  const profileMatch = useMatch("/player/:id");
  const teamMatch = useMatch("/team/:id");
  const compareMatch = useMatch("/compare/:a/:b");
  const boxscoreMatch = useMatch("/boxscore/:id");

  const crumbs: Crumb[] = [{ label: "Home", to: "/home" }];

  // Derive middle + leaf from the route index when possible.
  const meta = findRouteMeta(location.pathname);
  if (meta && meta.hub !== "today") {
    const hub = HUB_META[meta.hub];
    crumbs.push({ label: hub.label, to: hub.path });
    crumbs.push({ label: leafLabel ?? meta.label });
  } else if (meta) {
    // Today section pages — no middle crumb, just leaf.
    crumbs.push({ label: leafLabel ?? meta.label });
  } else if (profileMatch) {
    crumbs.push({ label: HUB_META.league.label, to: HUB_META.league.path });
    crumbs.push({ label: leafLabel ?? "Player profile" });
  } else if (teamMatch) {
    crumbs.push({ label: HUB_META.league.label, to: HUB_META.league.path });
    crumbs.push({ label: leafLabel ?? "Team" });
  } else if (compareMatch) {
    crumbs.push({ label: HUB_META.league.label, to: HUB_META.league.path });
    crumbs.push({ label: leafLabel ?? "Compare players" });
  } else if (boxscoreMatch) {
    crumbs.push({ label: HUB_META.league.label, to: HUB_META.league.path });
    crumbs.push({ label: leafLabel ?? "Box score" });
  } else if (location.pathname.startsWith("/hub/")) {
    // We're already on a hub landing page — single leaf trail.
    const key = location.pathname.replace("/hub/", "") as keyof typeof HUB_META;
    if (HUB_META[key]) {
      crumbs.push({ label: HUB_META[key].label });
    }
  } else if (leafLabel) {
    crumbs.push({ label: leafLabel });
  }

  if (crumbs.length <= 1) return null;

  return (
    <nav aria-label="Breadcrumb" className="text-[11px]">
      <ol className="flex items-center gap-1">
        {crumbs.map((crumb, idx) => {
          const isLast = idx === crumbs.length - 1;
          return (
            <li key={`${crumb.label}-${idx}`} className="flex items-center gap-1">
              {idx > 0 && (
                <ChevronRight
                  className="h-3 w-3 text-muted/70"
                  aria-hidden
                />
              )}
              {crumb.to && !isLast ? (
                <Link
                  to={crumb.to}
                  className="text-muted hover:text-amber-text"
                  style={{ textShadow: "0 1px 2px rgba(0,0,0,0.45)" }}
                >
                  {crumb.label}
                </Link>
              ) : (
                <span
                  className={cn(
                    "font-semibold text-cream",
                    isLast ? "text-amber-text" : "text-muted",
                  )}
                  style={{ textShadow: "0 1px 2px rgba(0,0,0,0.45)" }}
                >
                  {crumb.label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
