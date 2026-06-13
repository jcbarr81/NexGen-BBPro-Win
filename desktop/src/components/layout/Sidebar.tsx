import { useEffect, useMemo, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import * as Tooltip from "@radix-ui/react-tooltip";
import {
  ArrowLeftRight,
  Bell,
  CalendarClock,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Gavel,
  HelpCircle,
  LayoutDashboard,
  Newspaper,
  Pin,
  PinOff,
  Star,
  Trophy,
  Wrench,
  X,
} from "lucide-react";
import type { ComponentType, SVGProps } from "react";

import { useAuthStore } from "@/lib/auth-store";
import { useIsDesktop } from "@/lib/use-media-query";
import { cn } from "@/lib/cn";
import { useLeagueCapabilities, type LeagueCapabilities } from "@/lib/league-capabilities";
import { useFavoritesStore } from "@/lib/favorites-store";
import { findRouteMeta, HUB_META, type HubKey } from "@/lib/route-index";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui";
import { Brand } from "./Brand";

interface NavItem {
  to: string;
  label: string;
  Icon: ComponentType<SVGProps<SVGSVGElement>>;
  adminOnly?: boolean;
  /** Optional capability predicate. */
  showIf?: (caps: LeagueCapabilities) => boolean;
}

interface NavSection {
  label: string;
  items: NavItem[];
}

/**
 * Sidebar shows three layers:
 *   1. Today — the always-on quick links (Dashboard / Season / News).
 *   2. Favorites — user-pinned routes (right-click any sidebar entry or
 *      hub card to pin/unpin).
 *   3. Hubs — single-entry links to landing pages that grid out every
 *      child route (My Team, League, Transactions, Admin). Collapses
 *      the previous 30+ entries down to ~7 top-level destinations.
 *
 * The whole rail can also collapse to icon-only mode (~56px wide) via
 * the chevron at the top — hover any icon to see its label.
 */

function _todaySection(): NavSection {
  return {
    label: "Today",
    items: [
      { to: "/home", label: "Dashboard", Icon: LayoutDashboard },
      { to: "/season", label: "Season", Icon: CalendarClock },
      { to: "/news", label: "News", Icon: Newspaper },
    ],
  };
}

function _hubsSection(isAdmin: boolean): NavSection {
  return {
    label: "Hubs",
    items: [
      {
        to: HUB_META["my-team"].path,
        label: HUB_META["my-team"].label,
        Icon: ClipboardList,
      },
      {
        to: HUB_META.league.path,
        label: HUB_META.league.label,
        Icon: Trophy,
      },
      {
        to: HUB_META.transactions.path,
        label: HUB_META.transactions.label,
        Icon: ArrowLeftRight,
      },
      ...(isAdmin
        ? [
            {
              to: HUB_META.admin.path,
              label: HUB_META.admin.label,
              Icon: Gavel,
            } as NavItem,
          ]
        : []),
      // Notifications graduates to the top level since it's how owners
      // pause the sim — too important to hide behind My Team's hub click.
      { to: "/notifications", label: "Notifications", Icon: Bell },
      // Utilities is genuinely useful for owners (avatars, logos,
      // reports, almanac, snapshot exports) so it stays top-level —
      // tucking it inside the admin-only hub stranded non-admins.
      { to: "/utilities", label: "Utilities", Icon: Wrench },
    ],
  };
}

const SECTION_COLLAPSE_KEY = "nexgen:sidebar:collapsed";
const RAIL_COLLAPSE_KEY = "nexgen:sidebar:rail-collapsed";

function loadCollapsed(): Set<string> {
  try {
    const raw = window.localStorage.getItem(SECTION_COLLAPSE_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return new Set(parsed.map(String));
  } catch {
    /* ignore parse errors */
  }
  return new Set();
}

function saveCollapsed(set: Set<string>) {
  try {
    window.localStorage.setItem(SECTION_COLLAPSE_KEY, JSON.stringify([...set]));
  } catch {
    /* storage may be disabled */
  }
}

function loadRail(): boolean {
  try {
    return window.localStorage.getItem(RAIL_COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

function saveRail(value: boolean) {
  try {
    window.localStorage.setItem(RAIL_COLLAPSE_KEY, value ? "1" : "0");
  } catch {
    /* ignore */
  }
}

export function Sidebar({
  mobileOpen = false,
  onClose,
}: {
  mobileOpen?: boolean;
  onClose?: () => void;
}) {
  const role = useAuthStore((s) => s.role);
  const location = useLocation();
  const isDesktop = useIsDesktop();
  const isAdmin = role === "admin";
  const capabilities = useLeagueCapabilities();
  const pinned = useFavoritesStore((s) => s.pinned);
  const togglePin = useFavoritesStore((s) => s.toggle);

  const todaySection = useMemo(() => _todaySection(), []);
  const hubsSection = useMemo(() => _hubsSection(isAdmin), [isAdmin]);

  const favoritesSection = useMemo<NavSection | null>(() => {
    if (pinned.length === 0) return null;
    const items: NavItem[] = [];
    for (const path of pinned) {
      const meta = findRouteMeta(path);
      if (!meta) continue;
      if (meta.adminOnly && !isAdmin) continue;
      if (meta.capability === "finance" && !capabilities.financeEnabled) continue;
      if (meta.capability === "multi-owner" && !capabilities.multiOwner) continue;
      if (isHiddenByPhase(meta.path, capabilities.phase)) continue;
      items.push({ to: meta.path, label: meta.label, Icon: meta.Icon });
    }
    if (items.length === 0) return null;
    return { label: "Favorites", items };
  }, [
    pinned,
    isAdmin,
    capabilities.financeEnabled,
    capabilities.multiOwner,
    capabilities.phase,
  ]);

  const sections: NavSection[] = useMemo(() => {
    const out: NavSection[] = [todaySection];
    if (favoritesSection) out.push(favoritesSection);
    out.push(hubsSection);
    return out;
  }, [todaySection, hubsSection, favoritesSection]);

  const [collapsed, setCollapsed] = useState<Set<string>>(() => loadCollapsed());
  const [railCollapsed, setRailCollapsed] = useState<boolean>(() => loadRail());
  // On mobile the sidebar is a full off-canvas drawer (labels shown), so the
  // desktop icon-rail collapse only applies at the lg breakpoint and up.
  const effectiveCollapsed = isDesktop && railCollapsed;

  // Always expand the section containing the active route so the user can
  // see where they are -- but preserve their preference for all others.
  const activeSection = useMemo(() => {
    const activePath = location.pathname;
    return sections.find((s) =>
      s.items.some(
        (item) => activePath === item.to || activePath.startsWith(`${item.to}/`),
      ),
    )?.label;
  }, [location.pathname, sections]);

  useEffect(() => {
    if (activeSection && collapsed.has(activeSection)) {
      const next = new Set(collapsed);
      next.delete(activeSection);
      setCollapsed(next);
      saveCollapsed(next);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSection]);

  function toggle(label: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      saveCollapsed(next);
      return next;
    });
  }

  function toggleRail() {
    setRailCollapsed((prev) => {
      const next = !prev;
      saveRail(next);
      return next;
    });
  }

  return (
    <Tooltip.Provider delayDuration={120}>
      {/* Mobile backdrop — tap to close the drawer. Desktop never shows it. */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/60 lg:hidden"
          onClick={onClose}
          aria-hidden
        />
      )}
      <aside
        className={cn(
          "z-40 flex h-full shrink-0 flex-col border-r border-border bg-sidebar-gradient",
          // Mobile: off-canvas drawer that slides in. Desktop (lg+): in-flow
          // rail that can collapse to an icon strip.
          "fixed inset-y-0 left-0 w-64 transition-transform duration-200",
          "lg:static lg:z-10 lg:translate-x-0 lg:transition-[width]",
          effectiveCollapsed ? "lg:w-14" : "lg:w-64",
          mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
        )}
        style={{
          backgroundImage: [
            "linear-gradient(to right, hsl(var(--mahogany)), hsl(var(--espresso)))",
            // Thin pinstripes over the dugout wood.
            "repeating-linear-gradient(90deg, hsl(var(--cream) / 0.04) 0 1px, transparent 1px 7px)",
          ].join(","),
        }}
      >
        <div
          className={cn(
            "flex items-center justify-between border-b border-cream/10 py-4",
            effectiveCollapsed ? "px-2" : "px-4",
          )}
        >
          {!effectiveCollapsed && <Brand />}
          {/* Collapse-to-rail chevron is a desktop-only affordance. */}
          <button
            type="button"
            onClick={toggleRail}
            aria-label={railCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={railCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="hidden rounded-md p-1 text-cream/60 hover:bg-cream/10 hover:text-cream lg:inline-flex"
          >
            {railCollapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <ChevronLeft className="h-4 w-4" />
            )}
          </button>
          {/* Mobile-only close button. */}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close menu"
            className="rounded-md p-1 text-cream/60 hover:bg-cream/10 hover:text-cream lg:hidden"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="flex flex-1 flex-col gap-2 overflow-y-auto px-2 py-3">
          {sections.map((section, idx) => {
            const isCollapsed = collapsed.has(section.label);
            return (
              <div
                key={section.label}
                className={cn(
                  "flex flex-col gap-0.5",
                  idx > 0 && "border-t border-cream/5 pt-2",
                )}
              >
                {!effectiveCollapsed && (
                  <button
                    type="button"
                    onClick={() => toggle(section.label)}
                    aria-expanded={!isCollapsed}
                    className="group flex items-center justify-between rounded-md px-3 py-1 text-[10px] font-bold uppercase tracking-[0.18em] text-cream/45 transition hover:text-cream/80"
                  >
                    <span className="inline-flex items-center gap-1.5">
                      {section.label === "Favorites" && (
                        <Star className="h-3 w-3 text-amber" aria-hidden />
                      )}
                      {section.label}
                    </span>
                    <ChevronDown
                      className={cn(
                        "h-3 w-3 transition-transform duration-150",
                        isCollapsed && "-rotate-90",
                      )}
                      aria-hidden
                    />
                  </button>
                )}
                {(effectiveCollapsed || !isCollapsed) &&
                  section.items.map(({ to, label, Icon }) => (
                    <SidebarItem
                      key={to}
                      to={to}
                      label={label}
                      Icon={Icon}
                      railCollapsed={effectiveCollapsed}
                      pinned={pinned.includes(to)}
                      onTogglePin={() => togglePin(to)}
                    />
                  ))}
              </div>
            );
          })}
        </nav>

        <div
          className={cn(
            "border-t border-cream/10 py-2",
            effectiveCollapsed ? "px-1" : "px-2",
          )}
        >
          <SidebarItem
            to="/help"
            label="Help & Tutorials"
            Icon={HelpCircle}
            railCollapsed={effectiveCollapsed}
            pinned={pinned.includes("/help")}
            onTogglePin={() => togglePin("/help")}
          />
        </div>
      </aside>
    </Tooltip.Provider>
  );
}

function SidebarItem({
  to,
  label,
  Icon,
  railCollapsed,
  pinned,
  onTogglePin,
}: {
  to: string;
  label: string;
  Icon: ComponentType<SVGProps<SVGSVGElement>>;
  railCollapsed: boolean;
  pinned: boolean;
  onTogglePin: () => void;
}) {
  const link = (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "group relative flex items-center gap-3 rounded-lg border-l-[3px] border-transparent text-sm font-semibold transition",
          railCollapsed ? "justify-center px-0 py-2" : "px-3 py-1.5",
          isActive
            ? "border-amber bg-cream/10 text-cream shadow-inset"
            : "text-cream/70 hover:border-amber/50 hover:bg-cream/5 hover:text-cream",
        )
      }
    >
      <Icon className="h-4 w-4 text-amber" aria-hidden />
      {!railCollapsed && (
        <span className="flex flex-1 items-center justify-between">
          <span>{label}</span>
          {pinned && <Pin className="h-3 w-3 text-amber/70" aria-hidden />}
        </span>
      )}
    </NavLink>
  );

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        {railCollapsed ? (
          <Tooltip.Root>
            <Tooltip.Trigger asChild>{link}</Tooltip.Trigger>
            <Tooltip.Portal>
              <Tooltip.Content
                side="right"
                sideOffset={6}
                className="z-50 rounded-md border border-border bg-surface px-2 py-1 text-xs font-semibold text-ink shadow-md"
              >
                {label}
              </Tooltip.Content>
            </Tooltip.Portal>
          </Tooltip.Root>
        ) : (
          link
        )}
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuLabel>{label}</ContextMenuLabel>
        <ContextMenuSeparator />
        <ContextMenuItem onSelect={onTogglePin}>
          {pinned ? (
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

// ---------------------------------------------------------------------------
// Phase-aware route filtering helpers — exported so HubPage can reuse them.

const PHASE_HIDE_RULES: Record<string, (phase: string) => boolean> = {
  // Hide Draft outside the draft window unless we're in PRESEASON or
  // AMATEUR_DRAFT phase. The hub still shows it; this only filters the
  // sidebar's quick-link rail.
  "/draft": (phase) =>
    !!phase && phase !== "AMATEUR_DRAFT" && phase !== "PRESEASON",
  "/offseason": (phase) => !!phase && phase !== "OFFSEASON" && phase !== "PRESEASON",
};

export function isHiddenByPhase(path: string, phase: string): boolean {
  const rule = PHASE_HIDE_RULES[path];
  return !!rule && rule(phase);
}
