/**
 * Single source of truth for route labels + their parent hub.
 *
 * Used by:
 *   - the Breadcrumbs component (derives the trail from current path),
 *   - the four hub pages (My Team / League / Transactions / Admin —
 *     each renders the cards for its child routes),
 *   - the sidebar pin-to-favorites menu (looks up labels for pinned paths).
 *
 * Keep this in sync with src/components/layout/Sidebar.tsx and the
 * <Route> table in src/App.tsx.
 */

import type { ComponentType, SVGProps } from "react";
import {
  Activity,
  ArrowLeftRight,
  Archive,
  Award,
  BarChart3,
  Bell,
  BookOpen,
  Briefcase,
  Building2,
  Calendar,
  CalendarClock,
  ClipboardList,
  Command,
  Crown,
  DollarSign,
  Flame,
  Gavel,
  GraduationCap,
  HeartPulse,
  Inbox,
  Layers,
  LayoutDashboard,
  LineChart,
  ListChecks,
  ListOrdered,
  Medal,
  Newspaper,
  PlusSquare,
  Send,
  Settings,
  Settings2,
  Shuffle,
  Sliders,
  Snowflake,
  Swords,
  Target,
  Trophy,
  UserCog,
  UserSearch,
  Users,
  Wrench,
} from "lucide-react";

export type HubKey = "my-team" | "league" | "transactions" | "admin" | "today";

export interface RouteMeta {
  /** URL path. */
  path: string;
  /** Short human label (sidebar, hub card title, breadcrumb leaf). */
  label: string;
  /** One-line description shown on the hub card. */
  description: string;
  /** Lucide icon used on hub cards + sidebar entries. */
  Icon: ComponentType<SVGProps<SVGSVGElement>>;
  /** Hub the route belongs to — drives breadcrumb middle segment + hub-card grouping. */
  hub: HubKey;
  /** Admin role required to use the page. */
  adminOnly?: boolean;
  /** Capability predicate — finance/multi-owner/phase gating. */
  capability?: "finance" | "multi-owner" | "draft-phase";
}

export const HUB_META: Record<HubKey, { label: string; description: string; Icon: ComponentType<SVGProps<SVGSVGElement>>; path: string }> = {
  today: {
    label: "Today",
    description: "What's happening right now",
    Icon: CalendarClock,
    path: "/home",
  },
  "my-team": {
    label: "My Team",
    description: "Roster, lineup, training, finance, settings",
    Icon: ClipboardList,
    path: "/hub/my-team",
  },
  league: {
    label: "League",
    description: "Standings, leaders, stats, history",
    Icon: Trophy,
    path: "/hub/league",
  },
  transactions: {
    label: "Transactions",
    description: "Free agency, trades, draft, requests",
    Icon: ArrowLeftRight,
    path: "/hub/transactions",
  },
  admin: {
    label: "Admin",
    description: "Commissioner tools, league admin, utilities",
    Icon: Gavel,
    path: "/hub/admin",
  },
};

export const ROUTE_INDEX: RouteMeta[] = [
  // Today
  { path: "/home", label: "Dashboard", description: "Owner home — hero, scoreboard, widgets", Icon: LayoutDashboard, hub: "today" },
  { path: "/season", label: "Season", description: "Sim a day, week, month, or to a milestone", Icon: CalendarClock, hub: "today" },
  { path: "/news", label: "News", description: "League news feed (injuries, trades, milestones)", Icon: Newspaper, hub: "today" },

  // My Team
  { path: "/roster", label: "Roster", description: "ACT/AAA/LOW + DL/IR — moves, drag-and-drop", Icon: ClipboardList, hub: "my-team" },
  { path: "/pitchers", label: "Pitchers", description: "All pitchers split by SP / RP", Icon: Flame, hub: "my-team" },
  { path: "/lineup", label: "Lineup", description: "Batting orders + pitching staff", Icon: ListOrdered, hub: "my-team" },
  { path: "/depth-chart", label: "Depth Chart", description: "Per-position priority + auto-generate", Icon: Layers, hub: "my-team" },
  { path: "/training", label: "Training", description: "Hitter + pitcher focus allocations", Icon: Target, hub: "my-team" },
  { path: "/injuries", label: "Injuries", description: "DL/IR placements, returns, day-to-day", Icon: HeartPulse, hub: "my-team" },
  { path: "/notifications", label: "Notifications", description: "Stop-sim rules + recent events", Icon: Bell, hub: "my-team" },
  { path: "/my-team-stats", label: "Team Stats", description: "Batting, pitching, and team totals for your team", Icon: BarChart3, hub: "my-team" },
  { path: "/finance", label: "Finance", description: "Cash, debt, payroll, projections", Icon: DollarSign, hub: "my-team", capability: "finance" },
  { path: "/settings", label: "Team Settings", description: "Branding, ballpark, strategy profile", Icon: Settings, hub: "my-team" },

  // League
  { path: "/league", label: "Standings", description: "Division standings, GB, last-10, streak", Icon: Trophy, hub: "league" },
  { path: "/leaders", label: "Leaders", description: "Stat leaders with MLB qualifiers", Icon: Award, hub: "league" },
  { path: "/stats", label: "Stats", description: "Full team + league stats tables", Icon: BarChart3, hub: "league" },
  { path: "/players", label: "Players", description: "Searchable league directory", Icon: UserSearch, hub: "league" },
  { path: "/teams", label: "Teams", description: "Every team's overview card", Icon: Users, hub: "league" },
  { path: "/schedule", label: "Schedule", description: "Calendar view of every game", Icon: Calendar, hub: "league" },
  { path: "/playoffs", label: "Playoffs", description: "Bracket + series results", Icon: Crown, hub: "league" },
  { path: "/history", label: "History", description: "Past champions, MVPs, archives", Icon: Archive, hub: "league" },
  { path: "/hall-of-fame", label: "Hall of Fame", description: "Inductees + current candidates", Icon: Medal, hub: "league" },
  { path: "/records", label: "Records", description: "Single-season + career record book", Icon: BookOpen, hub: "league" },
  { path: "/parks", label: "Ballparks", description: "Stadium catalog + diagrams", Icon: Building2, hub: "league" },

  // Transactions
  { path: "/free-agency", label: "Free Agency", description: "Sign unsigned players to your roster", Icon: Briefcase, hub: "transactions" },
  { path: "/trades", label: "Trades", description: "Propose, respond, withdraw", Icon: ArrowLeftRight, hub: "transactions" },
  { path: "/draft", label: "Draft", description: "Live board + history (admin tools)", Icon: GraduationCap, hub: "transactions", capability: "draft-phase" },
  { path: "/submit-change-request", label: "Submit Request", description: "Bundle owner edits for approval", Icon: Send, hub: "transactions", capability: "multi-owner" },
  { path: "/transactions", label: "Activity", description: "Per-team transactions log", Icon: Activity, hub: "transactions" },

  // Admin
  { path: "/commissioner", label: "Commissioner", description: "Trade / injury / finance / strategy", Icon: Gavel, hub: "admin", adminOnly: true },
  { path: "/command-center", label: "Command Center", description: "League-wide attention cards", Icon: Command, hub: "admin", adminOnly: true },
  { path: "/finance-queue", label: "Finance Queue", description: "Pending GM finance decisions", Icon: ListChecks, hub: "admin", adminOnly: true, capability: "finance" },
  { path: "/change-requests", label: "Change Requests", description: "Owner-submitted bundles", Icon: Inbox, hub: "admin", adminOnly: true, capability: "multi-owner" },
  { path: "/exhibition", label: "Exhibition Game", description: "One-off what-if simulation", Icon: Swords, hub: "admin", adminOnly: true },
  { path: "/offseason", label: "Offseason Flow", description: "End-of-season finance rollover", Icon: Snowflake, hub: "admin", adminOnly: true },
  { path: "/reassign", label: "Reassign Players", description: "Bulk auto-assign league rosters", Icon: Shuffle, hub: "admin", adminOnly: true },
  { path: "/finance-stability", label: "Finance Stability", description: "Multi-season finance sandbox", Icon: LineChart, hub: "admin", adminOnly: true, capability: "finance" },
  { path: "/league-admin", label: "League Admin", description: "Schedule reset, repair, clone", Icon: Settings2, hub: "admin", adminOnly: true },
  { path: "/tuning", label: "Physics Tuning", description: "Engine knobs (offense / pitching / etc.)", Icon: Sliders, hub: "admin", adminOnly: true },
  { path: "/leagues/new", label: "New League", description: "Start a new league", Icon: PlusSquare, hub: "admin", adminOnly: true },
  { path: "/users", label: "Users", description: "Accounts + role assignments", Icon: UserCog, hub: "admin", adminOnly: true },
  { path: "/utilities", label: "Utilities", description: "Logos, avatars, exports, almanac", Icon: Wrench, hub: "admin" },
];

const ROUTE_BY_PATH: Record<string, RouteMeta> = ROUTE_INDEX.reduce(
  (acc, meta) => {
    acc[meta.path] = meta;
    return acc;
  },
  {} as Record<string, RouteMeta>,
);

export function findRouteMeta(pathname: string): RouteMeta | null {
  if (!pathname) return null;
  // Exact match first; otherwise walk parents (drop trailing segments).
  if (ROUTE_BY_PATH[pathname]) return ROUTE_BY_PATH[pathname];
  let path = pathname;
  while (path.lastIndexOf("/") > 0) {
    path = path.slice(0, path.lastIndexOf("/"));
    if (ROUTE_BY_PATH[path]) return ROUTE_BY_PATH[path];
  }
  return null;
}

export function routesForHub(hub: HubKey): RouteMeta[] {
  return ROUTE_INDEX.filter((m) => m.hub === hub);
}
