/**
 * Generic hub landing page.
 *
 * Each hub key (My Team / League / Transactions / Admin) maps to a
 * filtered slice of `ROUTE_INDEX`. Capability-gated entries (finance,
 * multi-owner, admin-only, draft-phase) are filtered out client-side
 * using the same predicates the sidebar already runs.
 *
 * Cards are also right-clickable to pin/unpin from the sidebar's
 * Favorites section — see ``lib/favorites-store``.
 */

import { useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Pin, PinOff } from "lucide-react";

import { AppShell } from "@/components/layout/AppShell";
import { Card, CardContent } from "@/components/ui";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui";
import { useAuthStore } from "@/lib/auth-store";
import { useLeagueCapabilities } from "@/lib/league-capabilities";
import {
  HUB_META,
  type HubKey,
  type RouteMeta,
  routesForHub,
} from "@/lib/route-index";
import { useFavoritesStore } from "@/lib/favorites-store";

export function HubPage() {
  const { hubKey } = useParams<{ hubKey: HubKey }>();
  const key: HubKey = (hubKey ?? "my-team") as HubKey;
  const meta = HUB_META[key];
  const role = useAuthStore((s) => s.role);
  const capabilities = useLeagueCapabilities();

  const visible = useMemo<RouteMeta[]>(() => {
    if (!meta) return [];
    return routesForHub(key).filter((r) => {
      if (r.adminOnly && role !== "admin") return false;
      if (r.capability === "finance" && !capabilities.financeEnabled) return false;
      if (r.capability === "multi-owner" && !capabilities.multiOwner) return false;
      // Draft-phase gating is informational on the hub — keep it visible
      // so the user can pre-explore. The sidebar handles auto-hide.
      return true;
    });
  }, [key, meta, role, capabilities.financeEnabled, capabilities.multiOwner]);

  if (!meta) {
    return (
      <AppShell title="Not found">
        <Card>
          <CardContent className="py-10 text-sm text-muted">
            Unknown hub: {String(hubKey)}
          </CardContent>
        </Card>
      </AppShell>
    );
  }

  return (
    <AppShell title={meta.label} subtitle={meta.description}>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {visible.map((route) => (
          <HubCard key={route.path} route={route} />
        ))}
      </div>
      {visible.length === 0 && (
        <Card>
          <CardContent className="py-10 text-sm text-muted">
            Nothing in this hub yet — check back when more features unlock.
          </CardContent>
        </Card>
      )}
    </AppShell>
  );
}

function HubCard({ route }: { route: RouteMeta }) {
  const navigate = useNavigate();
  const isPinned = useFavoritesStore((s) => s.isPinned(route.path));
  const toggle = useFavoritesStore((s) => s.toggle);
  const Icon = route.Icon;
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <Link
          to={route.path}
          className="group flex items-start gap-3 rounded-lg border border-border bg-surface p-4 transition hover:border-amber hover:bg-surfaceAlt focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber"
        >
          <Icon className="mt-0.5 h-5 w-5 shrink-0 text-amber" aria-hidden />
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="font-semibold group-hover:text-amber-text">
                {route.label}
              </span>
              {isPinned && (
                <Pin
                  className="h-3 w-3 text-amber"
                  aria-label="Pinned"
                />
              )}
            </div>
            <p className="mt-0.5 text-xs text-muted">{route.description}</p>
          </div>
        </Link>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onSelect={() => navigate(route.path)}>
          Open
        </ContextMenuItem>
        <ContextMenuItem
          onSelect={() => toggle(route.path)}
        >
          {isPinned ? (
            <>
              <PinOff className="mr-1 h-3 w-3" /> Unpin from sidebar
            </>
          ) : (
            <>
              <Pin className="mr-1 h-3 w-3" /> Pin to sidebar
            </>
          )}
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
