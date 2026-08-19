/**
 * Resolve which UI features apply to the currently-active league.
 *
 * The sidebar (and a handful of pages) use these flags to hide navigation
 * that doesn't make sense for the current league — e.g. a single-player
 * league has no owner change-request flow, and a league with financial
 * simulation disabled doesn't need the Finance Queue or Stability pages.
 *
 * Sources:
 *   - ``/leagues`` — each league carries a ``mode`` ("single_player" /
 *     "multi_owner" / "clone").
 *   - ``/teams/{id}/finance/snapshot`` — the snapshot carries
 *     ``financials_enabled``; we use the current team's value since
 *     finance is configured league-wide anyway.
 *
 * Defaults lean **permissive** — if a query is pending or missing, assume
 * the feature is available. That prevents a flash of missing sidebar
 * items on login before data loads.
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";

export interface LeagueCapabilities {
  /** Raw league mode string; unknown until the leagues list loads. */
  mode: string;
  /** True when the active league is a multi-owner league. */
  multiOwner: boolean;
  /** True when financial simulation is enabled for this league. */
  financeEnabled: boolean;
  /** Current season phase string ("PRESEASON", "REGULAR_SEASON",
   *  "AMATEUR_DRAFT", "PLAYOFFS", "OFFSEASON", or "" while loading). */
  phase: string;
  /** True while either query is still fetching — callers may want to
   *  delay hiding items until capabilities are resolved. */
  loading: boolean;
}

export function useLeagueCapabilities(): LeagueCapabilities {
  const activeLeagueId = useAuthStore((s) => s.activeLeagueId);
  const teamId = useAuthStore((s) => s.selectedTeamId ?? s.teamId);
  const token = useAuthStore((s) => s.token);

  const leagues = useQuery({
    queryKey: ["leagues"],
    queryFn: () => api.listLeagues(),
    enabled: !!token,
    // League list/modes only change on admin edits; the cache is wiped on
    // league switch anyway.
    staleTime: 5 * 60_000,
  });
  const snapshot = useQuery({
    queryKey: ["finance-snapshot", teamId],
    queryFn: () => api.financeSnapshot(teamId as string),
    enabled: !!token && !!teamId,
    // Finance toggles rarely change, and sim actions invalidate
    // ["finance-snapshot"] explicitly (StatusRibbon).
    staleTime: 5 * 60_000,
  });
  const seasonState = useQuery({
    queryKey: ["season-state"],
    queryFn: () => api.seasonState(),
    enabled: !!token,
    // Phase changes only on Sim Day / Advance Phase — sim actions
    // invalidate ``season-state`` explicitly (StatusRibbon), which
    // refreshes us automatically.
    staleTime: 5 * 60_000,
  });

  const activeLeague = leagues.data?.find((l) => l.id === activeLeagueId) ?? null;
  const mode = activeLeague?.mode ?? "unknown";

  // Default to multi-owner + finance-enabled while loading so we don't
  // flicker items off and back on.
  const multiOwner = mode === "unknown" ? true : mode !== "single_player";
  // Reflect the real finance state: use the snapshot's flag once we have it;
  // stay permissive ONLY while the query is still loading (so we don't flicker
  // the Finance items off and back on). A settled query with no data (e.g. a
  // 404 because finance was never set up for this league/team) means finance is
  // NOT available — hide it instead of showing an empty, misleading tile.
  const financeEnabled =
    snapshot.data?.financials_enabled ?? (snapshot.isLoading ? true : false);
  const phase = String(seasonState.data?.phase ?? "");

  return {
    mode,
    multiOwner,
    financeEnabled,
    phase,
    loading: leagues.isLoading || snapshot.isLoading,
  };
}
