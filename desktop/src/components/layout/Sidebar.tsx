import { useEffect, useMemo, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import type { ComponentType, SVGProps } from "react";

import { useAuthStore } from "@/lib/auth-store";
import {
  LayoutDashboard,
  CalendarClock,
  ChevronDown,
  Trophy,
  Users,
  ClipboardList,
  ListOrdered,
  Target,
  HeartPulse,
  Calendar,
  Briefcase,
  GraduationCap,
  Crown,
  Award,
  BarChart3,
  Archive,
  UserSearch,
  Activity,
  Newspaper,
  ArrowLeftRight,
  DollarSign,
  Settings,
  UserCog,
  Wrench,
  Gavel,
  Command,
  ListChecks,
  Inbox,
  Medal,
  BookOpen,
  Sliders,
  PlusSquare,
  Layers,
  Snowflake,
  Shuffle,
  LineChart,
  Send,
  HelpCircle,
  Swords,
  Settings2,
  Building2,
} from "lucide-react";

import { cn } from "@/lib/cn";
import { Brand } from "./Brand";

interface NavItem {
  to: string;
  label: string;
  Icon: ComponentType<SVGProps<SVGSVGElement>>;
  adminOnly?: boolean;
}

interface NavSection {
  label: string;
  items: NavItem[];
}

/**
 * Sidebar grouped into semantic sections so the rail doesn't read as one
 * long undifferentiated list. Order within each group reflects how often
 * the screens get touched in a typical session.
 */
const SECTIONS: NavSection[] = [
  {
    label: "Today",
    items: [
      { to: "/home", label: "Dashboard", Icon: LayoutDashboard },
      { to: "/season", label: "Season", Icon: CalendarClock },
      { to: "/news", label: "News", Icon: Newspaper },
    ],
  },
  {
    label: "My Team",
    items: [
      { to: "/roster", label: "Roster", Icon: ClipboardList },
      { to: "/lineup", label: "Lineup", Icon: ListOrdered },
      { to: "/depth-chart", label: "Depth Chart", Icon: Layers },
      { to: "/training", label: "Training", Icon: Target },
      { to: "/injuries", label: "Injuries", Icon: HeartPulse },
      { to: "/finance", label: "Finance", Icon: DollarSign },
      { to: "/settings", label: "Settings", Icon: Settings },
    ],
  },
  {
    label: "League",
    items: [
      { to: "/league", label: "Standings", Icon: Trophy },
      { to: "/leaders", label: "Leaders", Icon: Award },
      { to: "/stats", label: "Stats", Icon: BarChart3 },
      { to: "/players", label: "Players", Icon: UserSearch },
      { to: "/teams", label: "Teams", Icon: Users },
      { to: "/schedule", label: "Schedule", Icon: Calendar },
      { to: "/playoffs", label: "Playoffs", Icon: Crown },
      { to: "/history", label: "History", Icon: Archive },
      { to: "/hall-of-fame", label: "Hall of Fame", Icon: Medal },
      { to: "/records", label: "Records", Icon: BookOpen },
      { to: "/parks", label: "Ballparks", Icon: Building2 },
    ],
  },
  {
    label: "Transactions",
    items: [
      { to: "/free-agency", label: "Free Agency", Icon: Briefcase },
      { to: "/trades", label: "Trades", Icon: ArrowLeftRight },
      { to: "/draft", label: "Draft", Icon: GraduationCap },
      { to: "/submit-change-request", label: "Submit Request", Icon: Send },
      { to: "/transactions", label: "Activity", Icon: Activity },
    ],
  },
  {
    label: "Admin",
    items: [
      { to: "/commissioner", label: "Commissioner", Icon: Gavel, adminOnly: true },
      { to: "/command-center", label: "Command Center", Icon: Command, adminOnly: true },
      { to: "/finance-queue", label: "Finance Queue", Icon: ListChecks, adminOnly: true },
      { to: "/change-requests", label: "Change Requests", Icon: Inbox, adminOnly: true },
      { to: "/exhibition", label: "Exhibition Game", Icon: Swords, adminOnly: true },
      { to: "/offseason", label: "Offseason Flow", Icon: Snowflake, adminOnly: true },
      { to: "/reassign", label: "Reassign Players", Icon: Shuffle, adminOnly: true },
      { to: "/finance-stability", label: "Finance Stability", Icon: LineChart, adminOnly: true },
      { to: "/league-admin", label: "League Admin", Icon: Settings2, adminOnly: true },
      { to: "/tuning", label: "Physics Tuning", Icon: Sliders, adminOnly: true },
      { to: "/leagues/new", label: "New League", Icon: PlusSquare, adminOnly: true },
      { to: "/users", label: "Users", Icon: UserCog, adminOnly: true },
      { to: "/utilities", label: "Utilities", Icon: Wrench },
    ],
  },
];

const STORAGE_KEY = "nexgen:sidebar:collapsed";

function loadCollapsed(): Set<string> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
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
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...set]));
  } catch {
    /* storage may be disabled */
  }
}

export function Sidebar() {
  const role = useAuthStore((s) => s.role);
  const location = useLocation();
  const isAdmin = role === "admin";

  // Filter admin-only items, then drop sections that end up empty.
  const visibleSections: NavSection[] = useMemo(
    () =>
      SECTIONS.map((section) => ({
        ...section,
        items: section.items.filter((n) => !n.adminOnly || isAdmin),
      })).filter((section) => section.items.length > 0),
    [isAdmin],
  );

  const [collapsed, setCollapsed] = useState<Set<string>>(() => loadCollapsed());

  // Always expand the section containing the active route so the user can
  // see where they are -- but preserve their preference for all others.
  const activeSection = useMemo(() => {
    const activePath = location.pathname;
    return visibleSections.find((s) =>
      s.items.some(
        (item) => activePath === item.to || activePath.startsWith(`${item.to}/`),
      ),
    )?.label;
  }, [location.pathname, visibleSections]);

  useEffect(() => {
    if (activeSection && collapsed.has(activeSection)) {
      const next = new Set(collapsed);
      next.delete(activeSection);
      setCollapsed(next);
      saveCollapsed(next);
    }
    // Only runs when the active section changes.
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

  return (
    <aside
      className="relative z-10 flex h-full w-64 shrink-0 flex-col border-r border-border bg-sidebar-gradient"
      style={{
        backgroundImage: [
          "linear-gradient(to right, hsl(var(--mahogany)), hsl(var(--espresso)))",
          // Thin pinstripes over the dugout wood.
          "repeating-linear-gradient(90deg, hsl(var(--cream) / 0.04) 0 1px, transparent 1px 7px)",
        ].join(","),
      }}
    >
      <div className="border-b border-cream/10 px-4 py-4">
        <Brand />
      </div>

      <nav className="flex flex-1 flex-col gap-2 overflow-y-auto px-2 py-3">
        {visibleSections.map((section, idx) => {
          const isCollapsed = collapsed.has(section.label);
          return (
            <div
              key={section.label}
              className={cn(
                "flex flex-col gap-0.5",
                idx > 0 && "border-t border-cream/5 pt-2",
              )}
            >
              <button
                type="button"
                onClick={() => toggle(section.label)}
                aria-expanded={!isCollapsed}
                className="group flex items-center justify-between rounded-md px-3 py-1 text-[10px] font-bold uppercase tracking-[0.18em] text-cream/45 transition hover:text-cream/80"
              >
                <span>{section.label}</span>
                <ChevronDown
                  className={cn(
                    "h-3 w-3 transition-transform duration-150",
                    isCollapsed && "-rotate-90",
                  )}
                  aria-hidden
                />
              </button>
              {!isCollapsed &&
                section.items.map(({ to, label, Icon }) => (
                  <NavLink
                    key={to}
                    to={to}
                    className={({ isActive }) =>
                      cn(
                        "group relative flex items-center gap-3 rounded-lg border-l-[3px] border-transparent px-3 py-1.5 text-sm font-semibold transition",
                        isActive
                          ? "border-amber bg-cream/10 text-cream shadow-inset"
                          : "text-cream/70 hover:border-amber/50 hover:bg-cream/5 hover:text-cream",
                      )
                    }
                  >
                    <Icon className="h-4 w-4 text-amber" aria-hidden />
                    <span>{label}</span>
                  </NavLink>
                ))}
            </div>
          );
        })}
      </nav>

      <div className="border-t border-cream/10 px-2 py-2">
        <NavLink
          to="/help"
          className={({ isActive }) =>
            cn(
              "group relative flex items-center gap-3 rounded-lg border-l-[3px] border-transparent px-3 py-1.5 text-sm font-semibold transition",
              isActive
                ? "border-amber bg-cream/10 text-cream shadow-inset"
                : "text-cream/70 hover:border-amber/50 hover:bg-cream/5 hover:text-cream",
            )
          }
        >
          <HelpCircle className="h-4 w-4 text-amber" aria-hidden />
          <span>Help &amp; Tutorials</span>
        </NavLink>
      </div>
    </aside>
  );
}
